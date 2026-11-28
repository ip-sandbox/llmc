"""PoC-8 (a)(b)(c): 常駐するデーモンの代わり。pythonw で動き、画面ありの Edge を最小化して開いたままにする。

ctl.py が起動する（直接は実行しない）。命令は out\\poc8\\cmd-*.json で受け、結果を res-*.json に書く。
5 秒ごとに、ウィンドウの状態・ブラウザが生きているか・画面のロック・RDP を調べ、変わったら events.jsonl に記録する。
ループの間隔が 30 秒を超えて空いたら、スリープなどで止まっていたとみなして記録する。
**本文・会話の題名・画面の文字は記録しない**（送信の結果は、ID が含まれたか、文字数、秒数だけ）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
for p in (ROOT, ROOT / "poc1_login", ROOT / "poc2_page", ROOT / "poc3_auto", HERE):
    sys.path.insert(0, str(p))
DIR = ROOT / "out" / ("poc8" + os.environ.get("LLMC_POC_REPORT_SUFFIX", ""))  # 試験の記録を利用者の記録に混ぜない
EVENTS = DIR / "events.jsonl"


def now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def event(kind: str, **kw) -> None:
    DIR.mkdir(parents=True, exist_ok=True)
    with EVENTS.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"t": now(), "kind": kind, **kw}, ensure_ascii=False) + "\n")


class Resident:
    def __init__(self, url: str):
        self.url = url
        self.pw = None
        self.ctx = self.page = self.drv = self.cdp = None
        self.closed_reason = None

    def launch(self) -> dict:
        from cp import CLIP_HOOK, open_copilot
        from roundtrip import Driver
        t0 = time.time()
        self.ctx, self.page, info = open_copilot(self.pw, variant="msedge-headed", init_script=CLIP_HOOK)
        self.closed_reason = None
        self.ctx.on("close", lambda *_: self._closed("context_close"))
        self.page.on("close", lambda *_: self._closed("page_close"))
        self.page.on("crash", lambda *_: self._closed("page_crash"))
        self.cdp = self.ctx.new_cdp_session(self.page)
        self.minimize()
        self.drv = Driver(self.page, self.ctx, self.url)
        info = {k: info.get(k) for k in ("ready", "relogin", "host")}
        info["seconds"] = round(time.time() - t0, 1)
        event("launch", **info)
        return info

    def _closed(self, why: str) -> None:
        if not self.closed_reason:
            self.closed_reason = why
            event("browser_closed", reason=why)

    def alive(self) -> bool:
        return self.ctx is not None and not self.closed_reason

    def window_state(self) -> str | None:
        try:
            wid = self.cdp.send("Browser.getWindowForTarget")["windowId"]
            return self.cdp.send("Browser.getWindowBounds", {"windowId": wid})["bounds"].get("windowState")
        except Exception:  # noqa: BLE001
            return None

    def minimize(self) -> None:
        wid = self.cdp.send("Browser.getWindowForTarget")["windowId"]
        self.cdp.send("Browser.setWindowBounds", {"windowId": wid, "bounds": {"windowState": "minimized"}})

    def restore(self) -> None:
        wid = self.cdp.send("Browser.getWindowForTarget")["windowId"]
        self.cdp.send("Browser.setWindowBounds", {"windowId": wid, "bounds": {"windowState": "normal"}})

    def login_state(self) -> str:
        try:
            host = self.page.evaluate("location.hostname") or ""
            if host.startswith("login."):
                return "login_page"
            from cp import INPUT
            return "ready" if self.page.locator(INPUT).count() > 0 else "no_input"
        except Exception:  # noqa: BLE001
            return "error"

    def send(self, delay_s: float, timeout: float) -> dict:
        """架空の短い依頼を新しいチャットで送り、回答に ID が含まれるかを見る。"""
        from roundtrip import new_tid
        from winutil import remote_session, session_locked
        if delay_s:
            end = time.time() + delay_s
            while time.time() < end:
                self.page.wait_for_timeout(500)
        if not self.alive():
            event("relaunch_for_send")
            self.launch()
        tid = new_tid()
        cond = {"locked": session_locked(), "remote": remote_session(), "window": self.window_state()}
        event("send_start", tid=tid, **cond)
        t0 = time.time()
        self.drv.new_chat()
        self.drv.put(f"これは動作確認です。次の ID だけを 1 行で返してください: {tid}", "paste_text")
        w = self.drv.send_and_wait(timeout=timeout, tid=tid)
        res = {"tid": tid, "at_send": cond, "ok": bool(w.get("ok")), "error": w.get("error"),
               "no_copy_button": bool(w.get("no_copy_button"))}
        if w.get("ok"):
            if w.get("no_copy_button"):
                r = self.drv.tail(tid, full=True)
                text, res["extract"] = r.get("text") or "", "dom"
            else:
                text, _h = self.drv.copy_last(tid=tid)
                text, res["extract"] = text or "", "copy"
            res["id_in_answer"] = tid in text
            res["answer_chars"] = len(text)
        res["seconds"] = round(time.time() - t0, 1)
        res["at_end"] = {"locked": session_locked(), "remote": remote_session(), "window": self.window_state()}
        event("send_end", **{k: v for k, v in res.items() if k != "tid"}, tid=tid)
        return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--idle-exit-min", type=float, default=240)
    a = ap.parse_args()
    os.environ["POC_URL"] = a.url
    from playwright.sync_api import sync_playwright

    from winutil import in_job, remote_session, session_locked
    DIR.mkdir(parents=True, exist_ok=True)
    (DIR / "resident.pid").write_text(str(os.getpid()), encoding="utf-8")
    event("start", pid=os.getpid(), in_job=in_job(), exe=Path(sys.executable).name)
    r = Resident(a.url)
    last_cmd = time.time()
    try:
        with sync_playwright() as pw:
            r.pw = pw
            r.launch()
            prev = {}
            last_tick = time.time()
            last_probe = 0.0
            while True:
                t = time.time()
                if t - last_tick > 30:
                    event("gap", seconds=round(t - last_tick))  # スリープ・休止などで止まっていた
                last_tick = t
                if t - last_probe >= 5:
                    last_probe = t
                    cur = {"alive": r.alive(), "window": r.window_state() if r.alive() else None,
                           "locked": session_locked(), "remote": remote_session(),
                           "login": r.login_state() if r.alive() else None}
                    if cur != prev:
                        event("state", **cur)
                        prev = cur
                    (DIR / "status.json").write_text(json.dumps({"t": now(), "pid": os.getpid(), **cur}), encoding="utf-8")
                for f in sorted(DIR.glob("cmd-*.json")):
                    cmd = json.loads(f.read_text(encoding="utf-8"))
                    f.unlink()
                    last_cmd = time.time()
                    out = {"cmd": cmd["op"]}
                    try:
                        if cmd["op"] == "stop":
                            event("stop")
                            (DIR / f.name.replace("cmd-", "res-")).write_text(json.dumps(out), encoding="utf-8")
                            if r.alive():
                                r.ctx.close()
                            return 0
                        if cmd["op"] == "send":
                            out.update(r.send(cmd.get("delay_s", 0), cmd.get("timeout", 300)))
                        elif cmd["op"] == "relaunch":
                            out.update(r.launch())
                        elif cmd["op"] == "minimize":
                            r.minimize()
                        elif cmd["op"] == "restore":
                            r.restore()
                    except Exception as e:  # noqa: BLE001
                        out["exception"] = f"{type(e).__name__}: {str(e).splitlines()[0][:200] if str(e) else ''}"
                        event("cmd_error", op=cmd["op"], error=out["exception"])
                    (DIR / f.name.replace("cmd-", "res-")).write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
                if time.time() - last_cmd > a.idle_exit_min * 60:
                    event("idle_exit")
                    return 0
                if r.alive():
                    try:
                        r.page.wait_for_timeout(1000)  # 同期 API では、待つ間もイベントを処理させる
                    except Exception:  # noqa: BLE001
                        time.sleep(1)
                else:
                    time.sleep(1)
    except Exception as e:  # noqa: BLE001
        # パスに利用者の名前が入るので、ファイル名と関数名と行だけを残す
        tb = [f"{Path(f.filename).name}:{f.name}:{f.lineno}" for f in traceback.extract_tb(e.__traceback__)[-4:]]
        event("crash", error=type(e).__name__, where=tb)
        return 1
    finally:
        event("exit")


if __name__ == "__main__":
    sys.exit(main())
