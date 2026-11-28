"""PoC-8 (a)(b)(c): 常駐の確認のクライアント。resident.py を pythonw で起動し、命令を送り、結果をレポートにまとめる。

使い方（組織版。poc フォルダで）:
  .\\.venv\\Scripts\\python.exe poc8_daemon\\ctl.py start --url $env:POC_URL   起動（ジョブからの切り離しを試し、結果を示す）
  .\\.venv\\Scripts\\python.exe poc8_daemon\\ctl.py status                     状態（ウィンドウ、ログイン、ロック）
  .\\.venv\\Scripts\\python.exe poc8_daemon\\ctl.py send [--delay 60]          架空の短い依頼を 1 回送る（delay の間に画面をロックできる）
  .\\.venv\\Scripts\\python.exe poc8_daemon\\ctl.py restore / minimize / relaunch
  .\\.venv\\Scripts\\python.exe poc8_daemon\\ctl.py stop
  .\\.venv\\Scripts\\python.exe poc8_daemon\\ctl.py report                     記録をレポートにし、要約を示す
  .\\.venv\\Scripts\\python.exe poc8_daemon\\ctl.py schedule --url $env:POC_URL  タスクスケジューラから start する（(c)。作ったタスクは最後に消す）
結果: out\\poc8-resident-report.md（記録の元: out\\poc8\\events.jsonl）
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
from winutil import CREATE_BREAKAWAY_FROM_JOB, CREATE_NEW_PROCESS_GROUP, DETACHED_PROCESS, in_job, in_job_pid  # noqa: E402

DIR = ROOT / "out" / ("poc8" + os.environ.get("LLMC_POC_REPORT_SUFFIX", ""))  # 試験の記録を利用者の記録に混ぜない
EVENTS = DIR / "events.jsonl"


def note(kind: str, **kw) -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    with EVENTS.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"t": time.strftime("%Y-%m-%d %H:%M:%S"), "kind": kind, **kw}, ensure_ascii=False) + "\n")


def status() -> dict | None:
    p = DIR / "status.json"
    if not p.exists():
        return None
    s = json.loads(p.read_text(encoding="utf-8"))
    s["age_s"] = round(time.time() - p.stat().st_mtime)
    return s


def cmd(op: str, wait_s: float, **kw) -> dict | None:
    DIR.mkdir(parents=True, exist_ok=True)
    n = f"{int(time.time() * 1000)}"
    (DIR / f"cmd-{n}.json").write_text(json.dumps({"op": op, **kw}), encoding="utf-8")
    res = DIR / f"res-{n}.json"
    end = time.time() + wait_s
    while time.time() < end:
        if res.exists():
            time.sleep(0.2)
            out = json.loads(res.read_text(encoding="utf-8"))
            res.unlink()
            return out
        time.sleep(0.5)
    return None


def start(url: str, via: str = "console") -> int:
    s = status()
    if s and s["age_s"] < 15:
        print(f"既に動いています（pid {s['pid']}）。先に stop してください", file=sys.stderr)
        return 1
    pyw = Path(sys.executable).with_name("pythonw.exe")
    argv = [str(pyw), str(HERE / "resident.py"), "--url", url]
    flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    breakaway = "requested"
    try:
        p = subprocess.Popen(argv, creationflags=flags | CREATE_BREAKAWAY_FROM_JOB, close_fds=True, cwd=str(ROOT))
    except OSError as e:  # 切り離しを許さないジョブでは、エラー 5 で失敗することがある
        breakaway = f"refused ({getattr(e, 'winerror', e)})"
        p = subprocess.Popen(argv, creationflags=flags, close_fds=True, cwd=str(ROOT))
    child_in_job = in_job_pid(p.pid)
    # venv の pythonw.exe は起動用の小さなプログラムで、本当の Python は別のプロセス（その子）になる。
    # 起動用のプログラムは子を自分のジョブに入れるので、常駐側の「ジョブの中」は resident.py が自分で記録する（start の事象）
    note("ctl_start", via=via, ctl_in_job=in_job(), breakaway=breakaway, launcher_in_job=child_in_job)
    print(f"起動しました（起動用 pid {p.pid}）。ctl はジョブの中: {in_job()}、切り離し: {breakaway}、起動用のプログラムはジョブの中: {child_in_job}",
          file=sys.stderr)
    t0 = time.time()
    for _ in range(240):
        s = status()
        if s and s["age_s"] < 10 and (DIR / "status.json").stat().st_mtime > t0:
            print(f"準備ができました: {json.dumps(s, ensure_ascii=False)}", file=sys.stderr)
            return 0
        time.sleep(0.5)
    print("120 秒で準備ができませんでした。report を実行して記録を見てください", file=sys.stderr)
    return 1


def schedule(url: str) -> int:
    """タスクスケジューラから start する（タスクの中はジョブの中のことがある）。作ったタスクは消す。"""
    name = "llmc-poc8-start"
    py = Path(sys.executable)
    tr = f'"{py}" "{HERE / "ctl.py"}" start --url "{url}" --via scheduler'
    r = subprocess.run(["schtasks", "/Create", "/F", "/TN", name, "/SC", "ONCE", "/ST", "23:59", "/TR", tr],
                       capture_output=True, text=True)
    if r.returncode:
        print(f"タスクを作れませんでした（終了コード {r.returncode}）。組織の方針で禁止されているかもしれません", file=sys.stderr)
        note("schedule", created=False, rc=r.returncode)
        return 1
    note("schedule", created=True)
    subprocess.run(["schtasks", "/Run", "/TN", name], capture_output=True)
    print("タスクから起動しました。60 秒待ってから、タスクを消します…", file=sys.stderr)
    time.sleep(60)
    subprocess.run(["schtasks", "/End", "/TN", name], capture_output=True)  # タスクの終了で、ジョブの中の常駐も終わるかを見る
    time.sleep(10)
    subprocess.run(["schtasks", "/Delete", "/F", "/TN", name], capture_output=True)
    s = status()
    alive = bool(s and s["age_s"] < 15)
    note("schedule_after_end", resident_alive=alive)
    print(f"タスクを終えた後も常駐が動いているか: {alive}", file=sys.stderr)
    return 0


def report() -> int:
    from common.report import Report
    rep = Report("poc8-resident", "PoC-8 (a)(b)(c): 常駐（最小化した画面ありの Edge）")
    if not EVENTS.exists():
        rep.add("記録", "events.jsonl", "NG", "記録がありません")
        print(rep.write(), file=sys.stderr)
        return 1
    evs = [json.loads(x) for x in EVENTS.read_text(encoding="utf-8").splitlines() if x.strip()]
    for e in evs:
        k = e["kind"]
        detail = {x: y for x, y in e.items() if x not in ("t", "kind")}
        if k == "ctl_start":
            res = "OK" if detail.get("launcher_in_job") is False else "WARN"
        elif k == "send_end":
            res = "OK" if e.get("ok") and e.get("id_in_answer") else "NG"
        elif k in ("crash", "cmd_error"):
            res = "NG"
        elif k in ("browser_closed", "gap", "schedule_after_end"):
            res = "WARN" if k != "schedule_after_end" or not detail.get("resident_alive") else "OK"
        else:
            res = "INFO"
        rep.add(e["t"][5:].replace(":", ""), k, res, detail)  # 要約は「:」で区切るので、時刻に「:」を使わない（11-28 182847）
    print(f"\nレポート: {rep.write()}", file=sys.stderr)
    from common.digest import show
    show([rep.name])
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("op", choices=["start", "status", "send", "restore", "minimize", "relaunch", "stop", "report", "schedule"])
    ap.add_argument("--url", default=os.environ.get("POC_URL"))
    ap.add_argument("--delay", type=float, default=0, help="send の前に待つ秒数（その間に画面をロックする）")
    ap.add_argument("--via", default="console")
    a = ap.parse_args()
    if a.op in ("start", "schedule") and not a.url:
        ap.error("--url が必要（または環境変数 POC_URL）")
    if a.op == "start":
        return start(a.url, a.via)
    if a.op == "schedule":
        return schedule(a.url)
    if a.op == "report":
        return report()
    if a.op == "status":
        s = status()
        print(json.dumps(s, ensure_ascii=False) if s else "状態の記録がありません（動いていない）")
        if s and s["age_s"] > 15:
            print(f"注意: 状態が {s['age_s']} 秒更新されていません（止まっているか、スリープの後）")
        return 0
    wait = {"send": a.delay + 400, "stop": 30}.get(a.op, 60)
    if a.op == "send" and a.delay:
        print(f"{a.delay:.0f} 秒後に送ります。その間に画面をロック（Win+L）するなど、試したい状態にしてください", file=sys.stderr)
    out = cmd(a.op, wait, delay_s=a.delay)
    print(json.dumps(out, ensure_ascii=False) if out else f"{wait:.0f} 秒で結果がありません（report で記録を見てください）")
    return 0 if out else 1


if __name__ == "__main__":
    sys.exit(main())
