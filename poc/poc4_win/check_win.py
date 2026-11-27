"""PoC-4: Windows の仕組みの試験（H-12〜H-17）。Copilot には接続しない。

使い方（venv を有効にした PowerShell か cmd で、通常の権限で）:
    python poc4_win\\check_win.py
結果: poc\\out\\poc4-report.md（チャットに貼る）
"""
from __future__ import annotations

import ctypes
import json
import os
import secrets
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from common.report import OUT_DIR, Report, add_redaction, first_line, is_windows  # noqa: E402

WORK = OUT_DIR / "poc4"
PYW = str(Path(sys.executable).with_name("pythonw.exe"))


def wait_file(p: Path, sec: float) -> bool:
    t = time.time()
    while not p.exists():
        if time.time() - t > sec:
            return False
        time.sleep(0.2)
    time.sleep(0.2)
    return True


# ---------------------------------------------------------------- ジョブ（H-13, H-14）
def test_jobs(rep: Report, W) -> None:
    sec = "ジョブ（H-13, H-14）"
    try:
        in_job = W.is_in_job()
        detail = {"in_job": in_job}
        if in_job:
            flags = W.current_job_limit_flags()
            detail["limit_flags"] = None if flags is None else hex(flags)
            if flags is not None:
                detail["breakaway_ok"] = bool(flags & W.JOB_OBJECT_LIMIT_BREAKAWAY_OK)
                detail["silent_breakaway_ok"] = bool(flags & W.JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK)
        rep.add(sec, "このプロセスはジョブの中か（端末からの実行）", "INFO", detail)
    except Exception as e:  # noqa: BLE001
        rep.add(sec, "このプロセスはジョブの中か", "NG", first_line(e))

    # 自分でジョブを作り、その中の補助プロセスからジョブの外へ切り離せるか
    for label, flags in (("切り離し不可のジョブの中から", W.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE),
                         ("切り離し可（BREAKAWAY_OK）のジョブの中から",
                          W.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | W.JOB_OBJECT_LIMIT_BREAKAWAY_OK)):
        go, out = WORK / f"go-{secrets.token_hex(3)}", WORK / f"out-{secrets.token_hex(3)}.json"
        try:
            job = W.create_job(flags)
            p = subprocess.Popen([sys.executable, str(HERE / "job_helper.py"), "breakaway", str(go), str(out)])
            W.assign_pid_to_job(job, p.pid)
            go.write_text("go")
            ok = wait_file(out, 20)
            res = json.loads(out.read_text(encoding="utf-8")) if ok else {"ok": None, "error": "応答なし"}
            expect = flags & W.JOB_OBJECT_LIMIT_BREAKAWAY_OK != 0
            W.TerminateJobObject(job, 1)
            W.CloseHandle(job)
            p.wait(10)
            time.sleep(1)
            gc = res.get("grandchild")
            res["ジョブ終了後も孫が生存（実際に切り離された）"] = bool(gc) and W.process_alive(gc)
            if gc and W.process_alive(gc):
                subprocess.run(["taskkill", "/F", "/PID", str(gc)], capture_output=True)
            actual = res["ジョブ終了後も孫が生存（実際に切り離された）"]
            status = "OK" if actual == expect else "WARN"
            rep.add(sec, f"CREATE_BREAKAWAY_FROM_JOB（{label}）", status, res)
        except Exception as e:  # noqa: BLE001
            rep.add(sec, f"CREATE_BREAKAWAY_FROM_JOB（{label}）", "NG", first_line(e))

    # Job Object でプロセスツリーごと終了できるか
    go, out = WORK / f"go-{secrets.token_hex(3)}", WORK / f"tree-{secrets.token_hex(3)}.json"
    try:
        job = W.create_job(W.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE)
        p = subprocess.Popen([sys.executable, str(HERE / "job_helper.py"), "tree", str(go), str(out)])
        W.assign_pid_to_job(job, p.pid)
        go.write_text("go")
        if not wait_file(out, 20):
            raise RuntimeError("子プロセスの情報が来ない")
        child = json.loads(out.read_text(encoding="utf-8"))["child"]
        before = (W.process_alive(p.pid), W.process_alive(child))
        W.TerminateJobObject(job, 1)
        time.sleep(1)
        after = (W.process_alive(p.pid), W.process_alive(child))
        W.CloseHandle(job)
        rep.add(sec, "TerminateJobObject で孫プロセスまで終了", "OK" if after == (False, False) and before == (True, True)
                else "NG", {"前（親, 子）": before, "後（親, 子）": after})
    except Exception as e:  # noqa: BLE001
        rep.add(sec, "TerminateJobObject で孫プロセスまで終了", "NG", first_line(e))


# ---------------------------------------------------------------- pythonw + Playwright（H-13）
def test_pythonw(rep: Report, W) -> None:
    sec = "pythonw と Playwright（H-13）"
    if not Path(PYW).exists():
        rep.add(sec, "pythonw.exe", "NG", "見つからない")
        return
    try:
        import playwright  # noqa: F401
    except ImportError:
        rep.add(sec, "全体", "SKIP", "playwright が未導入")
        return
    for label, flags in (("DETACHED_PROCESS", W.DETACHED_PROCESS | W.CREATE_NEW_PROCESS_GROUP),
                         ("DETACHED_PROCESS＋BREAKAWAY", W.DETACHED_PROCESS | W.CREATE_NEW_PROCESS_GROUP
                          | W.CREATE_BREAKAWAY_FROM_JOB)):
        out = WORK / f"pw-{secrets.token_hex(3)}.json"
        try:
            subprocess.Popen([PYW, str(HERE / "pw_child.py"), str(out)], creationflags=flags,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as e:
            rep.add(sec, label, "WARN" if "BREAKAWAY" in label else "NG",
                    f"起動できない: winerror={getattr(e, 'winerror', None)} {first_line(e)}")
            continue
        if not wait_file(out, 90):
            rep.add(sec, label, "NG", "90 秒以内に結果が来ない")
            continue
        res = json.loads(out.read_text(encoding="utf-8"))
        rep.add(sec, label, "OK" if res.get("ok") else "NG", res)


# ---------------------------------------------------------------- 名前付きパイプ（H-12）
def test_pipes(rep: Report, W) -> None:
    sec = "名前付きパイプ（H-12）"
    sid = W.current_user_sid()
    add_redaction(sid, "<USER_SID>")

    # 1) 標準ライブラリのパイプの既定の DACL
    try:
        from multiprocessing.connection import Listener
        name = rf"\\.\pipe\llmc-poc-{secrets.token_hex(4)}"
        lst = Listener(name, family="AF_PIPE", authkey=b"poc")
        try:
            h = W.CreateFileW(name, W.READ_CONTROL, 0, None, W.OPEN_EXISTING, 0, None)
            if h == W.INVALID_HANDLE_VALUE:
                raise ctypes.WinError(W.last_error())
            try:
                sddl = W.handle_dacl_sddl(h)
            finally:
                W.CloseHandle(h)
        finally:
            lst.close()
        wide = any(t in sddl for t in (";;;WD)", ";;;AN)", ";;;BU)", ";;;AU)"))
        rep.add(sec, "multiprocessing のパイプの既定の DACL", "WARN" if wide else "INFO",
                {"sddl": sddl, "Everyone・匿名・Users などを含む": wide})
    except Exception as e:  # noqa: BLE001
        rep.add(sec, "multiprocessing のパイプの既定の DACL", "NG", first_line(e))

    # 2) ctypes で DACL を指定したパイプ
    name = rf"\\.\pipe\llmc-poc-{secrets.token_hex(4)}"
    want = f"D:P(A;;GA;;;{sid})(A;;GA;;;SY)"
    server = None
    try:
        sa, psd = W.sa_from_sddl(want)
        server = W.CreateNamedPipeW(name, W.PIPE_ACCESS_DUPLEX | W.FILE_FLAG_FIRST_PIPE_INSTANCE,
                                    W.PIPE_TYPE_BYTE | W.PIPE_WAIT | W.PIPE_REJECT_REMOTE_CLIENTS,
                                    4, 4096, 4096, 0, ctypes.byref(sa))
        if server == W.INVALID_HANDLE_VALUE:
            raise ctypes.WinError(W.last_error())
        got = W.handle_dacl_sddl(server)
        rep.add(sec, "DACL を指定したパイプの作成", "OK" if "WD)" not in got else "NG", {"sddl": got})

        # 3) 同じ名前で FIRST_PIPE_INSTANCE を付けて作る（乗っ取りの検出）
        dup = W.CreateNamedPipeW(name, W.PIPE_ACCESS_DUPLEX | W.FILE_FLAG_FIRST_PIPE_INSTANCE,
                                 W.PIPE_TYPE_BYTE | W.PIPE_WAIT, 4, 4096, 4096, 0, None)
        err = W.last_error()
        if dup != W.INVALID_HANDLE_VALUE:
            W.CloseHandle(dup)
            rep.add(sec, "同名パイプの FIRST_PIPE_INSTANCE", "NG", "作れてしまった")
        else:
            rep.add(sec, "同名パイプの FIRST_PIPE_INSTANCE", "OK" if err == W.ERROR_ACCESS_DENIED else "WARN",
                    f"拒否された（エラー {err}）")

        # 4) クライアントから接続し、サーバのプロセスの所有者を確かめる
        cli = W.CreateFileW(name, W.GENERIC_READ | W.GENERIC_WRITE, 0, None, W.OPEN_EXISTING, 0, None)
        if cli == W.INVALID_HANDLE_VALUE:
            raise ctypes.WinError(W.last_error())
        try:
            pid = ctypes.c_ulong()
            if not W.GetNamedPipeServerProcessId(cli, ctypes.byref(pid)):
                raise ctypes.WinError(W.last_error())
            hp = W.OpenProcess(W.PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
            owner = W.process_user_sid(hp)
            W.CloseHandle(hp)
            rep.add(sec, "接続先サーバの所有者 SID の確認", "OK" if (pid.value == os.getpid() and owner == sid) else "NG",
                    {"pid_一致": pid.value == os.getpid(), "sid_一致": owner == sid})
        finally:
            W.CloseHandle(cli)
        W.LocalFree(psd)
    except Exception as e:  # noqa: BLE001
        rep.add(sec, "DACL を指定したパイプ", "NG", first_line(e))
    finally:
        if server and server != W.INVALID_HANDLE_VALUE:
            W.CloseHandle(server)


# ---------------------------------------------------------------- ReplaceFileW（H-15）
def _explicit_aces(path: Path) -> int:
    out = subprocess.run(["icacls", str(path)], capture_output=True).stdout.decode("cp932", "replace")
    lines = [l for l in out.splitlines()[:-2] if l.strip()]
    return sum(1 for l in lines if "(I)" not in l)


def _ads(path: Path) -> str | None:
    try:
        with open(str(path) + ":llmcpoc", "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def test_replace(rep: Report, W, sid: str) -> None:
    sec = "ファイルの置き換え（H-15）"
    for label in ("ReplaceFileW", "os.replace"):
        d = WORK / f"rep-{secrets.token_hex(3)}"
        d.mkdir(parents=True)
        tgt, tmp = d / "target.txt", d / "target.tmp"
        try:
            tgt.write_bytes(b"old\r\n")
            with open(str(tgt) + ":llmcpoc", "w", encoding="utf-8") as f:
                f.write("ads")
            W.SetFileAttributesW(str(tgt), 0x2000)  # NOT_CONTENT_INDEXED（目印の属性）
            subprocess.run(["icacls", str(tgt), "/grant", f"*{sid}:(R)"], capture_output=True)
            before = {"ads": _ads(tgt), "attr": hex(W.GetFileAttributesW(str(tgt))), "明示的な ACE": _explicit_aces(tgt)}
            tmp.write_bytes(b"new\r\n")
            if label == "ReplaceFileW":
                if not W.ReplaceFileW(str(tgt), str(tmp), None, 0, None, None):
                    raise ctypes.WinError(W.last_error())
            else:
                os.replace(tmp, tgt)
            after = {"content": tgt.read_bytes().decode(), "ads": _ads(tgt),
                     "attr": hex(W.GetFileAttributesW(str(tgt))), "明示的な ACE": _explicit_aces(tgt)}
            kept = after["ads"] == "ads" and after["attr"] == before["attr"] and after["明示的な ACE"] == before["明示的な ACE"]
            rep.add(sec, f"{label} で保たれるもの", "OK" if kept else "INFO", {"前": before, "後": after})
        except Exception as e:  # noqa: BLE001
            rep.add(sec, f"{label} で保たれるもの", "NG", first_line(e))

        # 他のプロセスが開いている間の置き換え
        try:
            tmp.write_bytes(b"new2\r\n")
            holder = subprocess.Popen([sys.executable, "-c",
                                       f"f=open({str(tgt)!r},'rb'); import time; time.sleep(5)"])
            time.sleep(1.0)
            try:
                if label == "ReplaceFileW":
                    ok = bool(W.ReplaceFileW(str(tgt), str(tmp), None, 0, None, None))
                    err = None if ok else W.last_error()
                else:
                    try:
                        os.replace(tmp, tgt)
                        ok, err = True, None
                    except OSError as e:
                        ok, err = False, getattr(e, "winerror", None)
            finally:
                holder.wait(10)
            rep.add(sec, f"{label}（別プロセスが読み取りで開いている）", "INFO", {"成功": ok, "エラー": err})
        except Exception as e:  # noqa: BLE001
            rep.add(sec, f"{label}（別プロセスが読み取りで開いている）", "NG", first_line(e))


# ---------------------------------------------------------------- リパースタグ（H-16）
NAME_SURROGATE = 0x20000000
DENY_TAGS = {0x80000023: "AF_UNIX", 0x8000001B: "APPEXECLINK"}


def classify(tag: int) -> str:
    if tag == 0:
        return "通常"
    if tag & NAME_SURROGATE or tag in DENY_TAGS:
        return "拒否（名前の差し替え）"
    return "許可（名前を差し替えない）"


def test_reparse(rep: Report) -> None:
    sec = "リパースタグ（H-16）"
    d = WORK / f"rp-{secrets.token_hex(3)}"
    (d / "real").mkdir(parents=True)
    (d / "real" / "f.txt").write_text("x")
    cases = {"通常のディレクトリ": d / "real", "通常のファイル": d / "real" / "f.txt"}
    r = subprocess.run(f'cmd.exe /d /c mklink /J "{d / "jn"}" "{d / "real"}"', capture_output=True)
    if r.returncode == 0:
        cases["ジャンクション"] = d / "jn"
    else:
        rep.add(sec, "ジャンクションの作成", "WARN", r.stderr.decode("cp932", "replace")[:200])
    try:
        os.symlink(d / "real" / "f.txt", d / "sl.txt")
        cases["シンボリックリンク（ファイル）"] = d / "sl.txt"
    except OSError as e:
        rep.add(sec, "シンボリックリンクの作成", "INFO", f"作れない（開発者モードでないため、と想定）: {first_line(e)}")
    for label, p in cases.items():
        try:
            st = os.lstat(p)
            tag = getattr(st, "st_reparse_tag", 0)
            rep.add(sec, label, "INFO", {"tag": hex(tag), "判定": classify(tag)})
        except Exception as e:  # noqa: BLE001
            rep.add(sec, label, "NG", first_line(e))
    # OneDrive（ファイルは開かず、属性とタグだけを見る。ファイル名は記録しない）
    for k in ("OneDriveCommercial", "OneDriveConsumer", "OneDrive"):
        root = os.environ.get(k)
        if not root or not Path(root).exists():
            continue
        tags: dict[str, int] = {}
        try:
            for i, e in enumerate(os.scandir(root)):
                if i >= 200:
                    break
                st = e.stat(follow_symlinks=False)
                key = f"{hex(getattr(st, 'st_reparse_tag', 0))}:{classify(getattr(st, 'st_reparse_tag', 0))}"
                tags[key] = tags.get(key, 0) + 1
            rep.add(sec, f"{k} の直下（最大 200 件）", "INFO", tags)
        except Exception as e:  # noqa: BLE001
            rep.add(sec, f"{k} の直下", "NG", first_line(e))


# ---------------------------------------------------------------- パスの挙動（H-17）
def test_paths(rep: Report, W) -> None:
    sec = "パスの挙動（H-17）"
    d = WORK / f"path-{secrets.token_hex(3)}"
    d.mkdir(parents=True)
    try:
        os.mkdir(str(d) + "\\tdot.")
        rep.add(sec, "末尾のドット（mkdir 'tdot.'）", "INFO",
                {"tdot ができた": (d / "tdot").exists(), "名前の一覧": sorted(os.listdir(d))})
    except Exception as e:  # noqa: BLE001
        rep.add(sec, "末尾のドット", "NG", first_line(e))
    try:
        with open(str(d) + "\\tfile .txt ", "w") as f:
            f.write("x")
        rep.add(sec, "末尾の空白（'tfile .txt '）", "INFO", {"名前の一覧": sorted(os.listdir(d))})
    except Exception as e:  # noqa: BLE001
        rep.add(sec, "末尾の空白", "NG", first_line(e))
    long_dir = d / "longdirectoryname_for_poc"
    long_dir.mkdir()
    buf = ctypes.create_unicode_buffer(1024)
    n = W.GetShortPathNameW(str(long_dir), buf, 1024)
    short = buf.value if n else None
    has_83 = bool(short) and "~" in Path(short).name
    rep.add(sec, "8.3 形式の短い名前の生成", "INFO", {"短い名前がある": has_83,
                                                "短い名前": Path(short).name if short else None})
    rp = os.path.realpath(long_dir)
    rep.add(sec, "realpath（GetFinalPathNameByHandle）", "INFO", rp)


def main() -> int:
    rep = Report("poc4", "PoC-4 Windows の仕組みの試験")
    if not is_windows():
        rep.add("全体", "実行環境", "SKIP", "Windows 以外")
        print(rep.write())
        return 0
    import winapi as W
    if WORK.exists():
        shutil.rmtree(WORK, ignore_errors=True)
    WORK.mkdir(parents=True)
    sid = W.current_user_sid()
    add_redaction(sid, "<USER_SID>")
    for fn in (lambda: test_jobs(rep, W), lambda: test_pythonw(rep, W), lambda: test_pipes(rep, W),
               lambda: test_replace(rep, W, sid), lambda: test_reparse(rep), lambda: test_paths(rep, W)):
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            rep.add("全体", "予期しないエラー", "NG", first_line(e))
    path = rep.write()
    print(f"\nレポート: {path}\n内容を確認してから、チャットに貼ってください。", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
