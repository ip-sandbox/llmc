"""PoC-8 (c): v1 の実行の形（デーモンなし。spec-runtime）の仕組みを確かめる。

確かめること（記録は out\\poc8c\\events.jsonl。本文・画面の文字・パス・コマンドラインは記録しない）:
  1. 起動の経路: llmc.exe に当たる起動用のプログラム（pip の distlib で作る）→ venv の python.exe → 本当の Python。
     それぞれがジョブの中か
  2. ファイルのロックで 2 つ目を断れるか（自分で 2 つ目を起動して確かめる）
  3. 自分用のジョブ（KILL_ON_JOB_CLOSE）を作って自分を入れられるか。ドライバ（node）と Edge がそのジョブに入るか
  4. 強制終了・ターミナルを閉じたときに、Edge とドライバが残らないか（check で調べる）。次の起動での exit_type
  5. 待ちの間の Ctrl+C: コンソールの ENABLE_PROCESSED_INPUT を外して、Ctrl+C をキーとして読めるか。
     ドライバと Edge が生き残り、ページを操作できるか（--send なら生成中に停止ボタンを押す）
  6. タスクスケジューラ（ログオンしているときのみ）から起動できるか

使い方（poc フォルダで）:
  .\\.venv\\Scripts\\python.exe poc8_daemon\\runtime_check.py make-launcher        起動用のプログラムを作る（out\\poc8c\\bin\\llmc-poc8.exe）
  .\\out\\poc8c\\bin\\llmc-poc8.exe run --url $env:POC_URL                           起動して待つ。Ctrl+C を押して試す。q で終わる
  .\\out\\poc8c\\bin\\llmc-poc8.exe run --url $env:POC_URL --send                    （組織版）長い回答を頼み、生成中に Ctrl+C で止める
  .\\out\\poc8c\\bin\\llmc-poc8.exe run --url $env:POC_URL --ctrlc signal            比べるため: 入力モードを変えずに Ctrl+C を受ける（前の形）
  .\\.venv\\Scripts\\python.exe poc8_daemon\\runtime_check.py check               残った Edge・ドライバを調べる（強制終了の後に）
  .\\.venv\\Scripts\\python.exe poc8_daemon\\runtime_check.py schedule --url $env:POC_URL [--send]   タスクスケジューラから起動する
  .\\.venv\\Scripts\\python.exe poc8_daemon\\runtime_check.py report
"""
from __future__ import annotations

import argparse
import ctypes
import json
import msvcrt
import os
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
for p in (ROOT, ROOT / "poc1_login", ROOT / "poc2_page", ROOT / "poc3_auto", HERE):
    sys.path.insert(0, str(p))
DIR = ROOT / "out" / ("poc8c" + os.environ.get("LLMC_POC_REPORT_SUFFIX", ""))  # 試験の記録を利用者の記録に混ぜない
EVENTS = DIR / "events.jsonl"
LOCK = DIR / "llmc.lock"
BIN = DIR / "bin"

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.CreateJobObjectW.restype = wintypes.HANDLE
k32.OpenProcess.restype = wintypes.HANDLE
k32.GetCurrentProcess.restype = wintypes.HANDLE
k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
k32.CreateFileW.restype = wintypes.HANDLE
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
JOB_KILL_ON_CLOSE = 0x2000
ENABLE_PROCESSED_INPUT = 0x0001


def event(kind: str, **kw) -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    with EVENTS.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"t": time.strftime("%Y-%m-%d %H:%M:%S"), "pid": os.getpid(), "kind": kind, **kw},
                           ensure_ascii=False) + "\n")
    print(f"[{kind}] {json.dumps(kw, ensure_ascii=False)}", file=sys.stderr, flush=True)


# ---- プロセスの一覧（Toolhelp。名前と親だけ。コマンドラインは読まない） ----
class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_wchar * 260)]


def processes() -> dict[int, tuple[int, str]]:
    snap = k32.CreateToolhelp32Snapshot(0x2, 0)
    out = {}
    e = PROCESSENTRY32W()
    e.dwSize = ctypes.sizeof(e)
    ok = k32.Process32FirstW(snap, ctypes.byref(e))
    while ok:
        out[e.th32ProcessID] = (e.th32ParentProcessID, e.szExeFile.lower())
        ok = k32.Process32NextW(snap, ctypes.byref(e))
    k32.CloseHandle(snap)
    return out


def descendants(root: int, procs: dict) -> list[int]:
    res, todo = [], [root]
    while todo:
        cur = todo.pop()
        for pid, (ppid, _n) in procs.items():
            if ppid == cur and pid not in res and pid != root:
                res.append(pid)
                todo.append(pid)
    return res


def in_job(pid: int, job=None) -> bool | None:
    h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return None
    try:
        r = wintypes.BOOL()
        if not k32.IsProcessInJob(wintypes.HANDLE(h), wintypes.HANDLE(job) if job else None, ctypes.byref(r)):
            return None
        return bool(r.value)
    finally:
        k32.CloseHandle(h)


def chain(procs: dict) -> list[dict]:
    """自分から親へ 3 段。名前とジョブの中か。"""
    out, pid = [], os.getpid()
    for _ in range(4):
        if pid not in procs:
            break
        ppid, name = procs[pid]
        out.append({"name": name, "in_job": in_job(pid)})
        pid = ppid
    return out


# ---- 自分用のジョブ ----
class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]


class IO_COUNTERS(ctypes.Structure):
    _fields_ = [(n, ctypes.c_uint64) for n in ("r", "w", "o", "rb", "wb", "ob")]


class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION), ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]


def make_own_job():
    job = k32.CreateJobObjectW(None, None)
    if not job:
        return None, f"CreateJobObject {ctypes.get_last_error()}"
    info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    info.BasicLimitInformation.LimitFlags = JOB_KILL_ON_CLOSE
    if not k32.SetInformationJobObject(wintypes.HANDLE(job), 9, ctypes.byref(info), ctypes.sizeof(info)):
        return None, f"SetInformationJobObject {ctypes.get_last_error()}"
    if not k32.AssignProcessToJobObject(wintypes.HANDLE(job), wintypes.HANDLE(k32.GetCurrentProcess())):
        return None, f"AssignProcessToJobObject {ctypes.get_last_error()}"
    return job, "ok"


# ---- ロック ----
def take_lock():
    DIR.mkdir(parents=True, exist_ok=True)
    f = open(LOCK, "a+b")
    f.seek(1_000_000)  # 中身（表示用の情報）を読めるよう、ロックはファイルの先から離れた 1 バイトにかける
    try:
        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        f.close()
        return None
    return f


# ---- コンソールの入力モード ----
class ConsoleKeys:
    """待ちの間だけ ENABLE_PROCESSED_INPUT を外し、Ctrl+C をキー（0x03）として読む。"""

    def __init__(self, mode: str):
        self.mode = mode
        self.h = None
        self.old = None
        self.sig = False

    def __enter__(self):
        if self.mode == "keys":
            h = k32.CreateFileW("CONIN$", 0xC0000000, 3, None, 3, 0, None)
            m = wintypes.DWORD()
            if h and h != wintypes.HANDLE(-1).value and k32.GetConsoleMode(wintypes.HANDLE(h), ctypes.byref(m)):
                self.h, self.old = h, m.value
                k32.SetConsoleMode(wintypes.HANDLE(h), m.value & ~ENABLE_PROCESSED_INPUT)
            else:
                self.mode = "none"  # コンソールが無い（タスクスケジューラなど）
        else:
            import signal
            signal.signal(signal.SIGINT, lambda *_: setattr(self, "sig", True))
        return self

    def __exit__(self, *exc):
        if self.h is not None:
            k32.SetConsoleMode(wintypes.HANDLE(self.h), self.old)
            k32.CloseHandle(wintypes.HANDLE(self.h))
        return False

    def poll(self) -> str | None:
        if self.mode == "keys":
            while msvcrt.kbhit():
                c = msvcrt.getwch()
                if c == "\x03":
                    return "ctrl_c"
                if c in "qQ":
                    return "q"
            return None
        if self.mode == "signal" and self.sig:
            self.sig = False
            return "ctrl_c"
        if self.mode == "signal" and msvcrt.kbhit() and msvcrt.getwch() in "qQ":
            return "q"
        return None


def profile_exit_type(fix: bool) -> dict:
    from common_browser import profile_dir
    pref = profile_dir("msedge") / "Default" / "Preferences"
    if not pref.exists():
        return {"exists": False}
    try:
        d = json.loads(pref.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return {"error": type(e).__name__}
    prof = d.get("profile", {})
    out = {"exit_type": prof.get("exit_type"), "exited_cleanly": prof.get("exited_cleanly")}
    if fix and (out["exit_type"] != "Normal" or out["exited_cleanly"] is False):
        prof["exit_type"], prof["exited_cleanly"] = "Normal", True
        d["profile"] = prof
        pref.write_text(json.dumps(d, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        out["fixed"] = True
    return out


def browser_procs(procs: dict, root: int, job) -> dict:
    ds = descendants(root, procs)
    names = {}
    for pid in ds:
        n = procs[pid][1]
        key = "msedge" if n == "msedge.exe" else "node" if n == "node.exe" else "other"
        d = names.setdefault(key, {"n": 0, "in_own_job": 0, "pids": []})
        d["n"] += 1
        d["pids"].append(pid)
        if job and in_job(pid, job):
            d["in_own_job"] += 1
    return names


def run(a) -> int:
    t0 = time.time()
    procs = processes()
    event("run_start", via=a.via, chain=chain(procs), console=bool(k32.GetConsoleWindow()))
    lock = take_lock()
    if lock is None:
        event("busy", note="ロックを取れなかった（別の llmc-poc8 が動いている）")
        return 3
    lock.seek(0)
    lock.truncate()
    lock.write(json.dumps({"pid": os.getpid(), "since": time.strftime("%H:%M:%S")}).encode())
    lock.flush()
    # 2 つ目を自分で起動し、断られるかを見る
    r = subprocess.run([sys.executable, str(Path(__file__)), "busy-probe"], capture_output=True)
    event("second_instance", refused=(r.returncode == 3), rc=r.returncode)
    job, why = make_own_job()
    event("own_job", ok=job is not None, detail=why, self_in_own_job=in_job(os.getpid(), job) if job else None)
    exit_info = profile_exit_type(a.fix_exit_type)
    event("profile_before", **exit_info)
    from playwright.sync_api import sync_playwright

    from common_browser import launch
    with sync_playwright() as pw:
        ctx = launch(pw, "msedge-headed", handle_sigint=False, handle_sigterm=False, handle_sighup=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            cdp = ctx.new_cdp_session(page)
            wid = cdp.send("Browser.getWindowForTarget")["windowId"]
            cdp.send("Browser.setWindowBounds", {"windowId": wid, "bounds": {"windowState": "minimized"}})
        except Exception:  # noqa: BLE001
            pass
        page.goto(a.url, timeout=60000)
        from cp import INPUT
        for _ in range(60):
            if page.locator(INPUT).count() > 0:
                break
            page.wait_for_timeout(500)
        bp = browser_procs(processes(), os.getpid(), job)
        event("browser_ready", seconds=round(time.time() - t0, 1), ready=page.locator(INPUT).count() > 0,
              procs={k: {x: y for x, y in v.items() if x != "pids"} for k, v in bp.items()})
        (DIR / "last_run.json").write_text(json.dumps({"pid": os.getpid(), "browser_pids": {k: v["pids"] for k, v in bp.items()}}),
                                           encoding="utf-8")
        print(f"\n準備ができました（PID {os.getpid()}）。Ctrl+C を押して試してください。q で終わります。"
              f"強制終了を試すときは、別の PowerShell で taskkill /F /PID {os.getpid()} を実行し、その後 check を実行します",
              file=sys.stderr, flush=True)
        sending = False
        if a.send:
            from roundtrip import SEND_BTN, Driver, new_tid
            drv = Driver(page, ctx, a.url)
            drv.new_chat()
            tid = new_tid()
            drv.put(f"これは動作確認です。最初に {tid} とだけ書き、次に 1 から 400 までの数を、1 行に 1 つずつ書いてください。", "paste_text")
            page.locator(SEND_BTN).first.click(timeout=10000)
            sending = True
            event("sent", note="生成中に Ctrl+C を押してください")
        end = time.time() + (a.auto_exit or 10 ** 9)
        with ConsoleKeys(a.ctrlc) as keys:
            event("console_mode", mode=keys.mode)
            while time.time() < end:
                try:
                    page.wait_for_timeout(300)
                except Exception as e:  # noqa: BLE001
                    event("page_error", error=type(e).__name__)
                    break
                k = keys.poll()
                if k == "q":
                    break
                if k == "ctrl_c":
                    res = {"driver_ok": False}
                    try:
                        res["driver_ok"] = page.evaluate("1+1") == 2
                        stops = page.locator("button[aria-label*='停止'], button[aria-label*='Stop']")
                        res["stop_buttons"] = stops.count()
                        if sending and res["stop_buttons"]:
                            stops.first.click(timeout=5000)
                            page.wait_for_timeout(2000)
                            res["stop_clicked"] = True
                            res["stop_buttons_after"] = stops.count()
                    except Exception as e:  # noqa: BLE001
                        res["error"] = type(e).__name__
                    bp = browser_procs(processes(), os.getpid(), job)
                    res["procs"] = {kk: vv["n"] for kk, vv in bp.items()}
                    event("ctrl_c", mode=keys.mode, sending=sending, **res)
                    sending = False
        try:
            ctx.close()
            event("closed", how="normal")
        except Exception as e:  # noqa: BLE001
            event("closed", how="error", error=type(e).__name__)
    return 0


def check() -> int:
    p = DIR / "last_run.json"
    if not p.exists():
        print("前の run の記録がありません", file=sys.stderr)
        return 1
    last = json.loads(p.read_text(encoding="utf-8"))
    procs = processes()
    alive_main = last["pid"] in procs and procs[last["pid"]][1] in ("python.exe", "pythonw.exe")
    left = {}
    for k, pids in last["browser_pids"].items():
        left[k] = sum(1 for x in pids if x in procs and procs[x][1].startswith(k))
    event("check", main_alive=alive_main, left=left, profile=profile_exit_type(False))
    return 0


def busy_probe() -> int:
    return 3 if take_lock() is None else 0


def make_launcher() -> int:
    from pip._vendor.distlib.scripts import ScriptMaker
    BIN.mkdir(parents=True, exist_ok=True)
    m = ScriptMaker(None, str(BIN))
    m.executable = sys.executable  # venv の python.exe（起動用の小さなプログラム）
    m.variants = {""}
    # pip が作る console script と同じ形（.exe の起動用のプログラム＋中のスクリプト）。モジュールの場所だけ足す
    m.script_template = ("# -*- coding: utf-8 -*-\nimport sys\nsys.path.insert(0, %r)\n"
                         "from %%(module)s import %%(import_name)s\nsys.exit(%%(func)s())\n") % str(HERE)
    made = m.make("llmc-poc8 = runtime_check:main")
    print("作りました: " + ", ".join(Path(x).name for x in made), file=sys.stderr)
    event("make_launcher", files=[Path(x).name for x in made])
    return 0


def schedule(a) -> int:
    exe = BIN / "llmc-poc8.exe"
    if not exe.exists():
        make_launcher()
    name = "llmc-poc8-runtime"
    tr = f'"{exe}" run --url "{a.url}" --auto-exit 90 --via scheduler' + (" --send" if a.send else "")
    r = subprocess.run(["schtasks", "/Create", "/F", "/TN", name, "/SC", "ONCE", "/ST", "23:59", "/IT", "/TR", tr],
                       capture_output=True)
    if r.returncode:
        event("schedule", created=False, rc=r.returncode)
        print("タスクを作れませんでした。組織の方針で禁止されているかもしれません", file=sys.stderr)
        return 1
    n0 = sum(1 for _ in EVENTS.open(encoding="utf-8")) if EVENTS.exists() else 0
    subprocess.run(["schtasks", "/Run", "/TN", name], capture_output=True)
    event("schedule", created=True, interactive_only=True)
    print("タスクから起動しました。終わるまで（最大 3 分）待ちます…", file=sys.stderr)
    end = time.time() + 180
    done = False
    while time.time() < end and not done:
        time.sleep(3)
        if EVENTS.exists():
            new = EVENTS.read_text(encoding="utf-8").splitlines()[n0:]
            done = any(json.loads(x)["kind"] == "closed" for x in new if x.strip())
    subprocess.run(["schtasks", "/Delete", "/F", "/TN", name], capture_output=True)
    event("schedule_end", finished=done)
    return 0


def report() -> int:
    from common.report import Report
    rep = Report("poc8-runtime", "PoC-8 (c): v1 の実行の形（ロック・ジョブ・Ctrl+C・スケジューラ）")
    if not EVENTS.exists():
        rep.add("記録", "events.jsonl", "NG", "記録がありません")
        print(rep.write(), file=sys.stderr)
        return 1
    for line in EVENTS.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        e = json.loads(line)
        k = e["kind"]
        d = {x: y for x, y in e.items() if x not in ("t", "kind", "pid")}
        res = "INFO"
        if k == "second_instance":
            res = "OK" if d.get("refused") else "NG"
        elif k == "own_job":
            res = "OK" if d.get("ok") and d.get("self_in_own_job") else "NG"
        elif k == "browser_ready":
            ps = d.get("procs", {})
            res = "OK" if all(v.get("n") == v.get("in_own_job") for v in ps.values()) and ps.get("msedge") else "WARN"
        elif k == "ctrl_c":
            res = "OK" if d.get("driver_ok") and (not d.get("sending") or d.get("stop_clicked")) else "NG"
        elif k == "check":
            res = "OK" if not any(d.get("left", {}).values()) else "NG"
        elif k in ("page_error", "busy"):
            res = "WARN"
        elif k == "schedule_end":
            res = "OK" if d.get("finished") else "NG"
        rep.add(e["t"][5:].replace(":", ""), k, res, d)  # 要約は「:」で区切るので、時刻に「:」を使わない
    print(f"\nレポート: {rep.write()}", file=sys.stderr)
    from common.digest import show
    show([rep.name])
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("op", choices=["make-launcher", "run", "check", "busy-probe", "schedule", "report"])
    ap.add_argument("--url", default=os.environ.get("POC_URL"))
    ap.add_argument("--send", action="store_true", help="長い回答を頼み、生成中の Ctrl+C で停止ボタンを押す（組織版）")
    ap.add_argument("--ctrlc", choices=["keys", "signal"], default="keys",
                    help="keys: 入力モードを変えて Ctrl+C をキーとして読む（v1 の案）。signal: 比べるための前の形")
    ap.add_argument("--auto-exit", type=float, default=0, help="この秒数で自分から終わる（スケジューラ用）")
    ap.add_argument("--fix-exit-type", action="store_true", help="起動の前に、プロファイルの終了状態を正常に直す")
    ap.add_argument("--via", default="console")
    a = ap.parse_args()
    if a.op in ("run", "schedule") and not a.url:
        ap.error("--url が必要（または環境変数 POC_URL）")
    if a.url:
        os.environ["POC_URL"] = a.url
    return {"make-launcher": lambda: make_launcher(), "run": lambda: run(a), "check": check,
            "busy-probe": busy_probe, "schedule": lambda: schedule(a), "report": report}[a.op]()


if __name__ == "__main__":
    sys.exit(main())
