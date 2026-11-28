"""PoC-8 (d): ログインの保持。日を空けて実行し、ログインの状態の移り変わりを記録する（**送信はしない**）。

画面ありの Edge でプロファイルを開き、すぐ最小化して、何も押さずに状態を判定する。
サインインのボタンがあれば 1 回だけ押し、黙ってログインできるか（自動の再ログイン）を見る。資格情報の入力が出たら何も入力せずに止める。
記録は out\\poc8-login-history.jsonl に追記し、初回からの日数とあわせてレポートにする。本文・画面の文字・アカウントの名前は記録しない。

使い方（組織版。前の日にログインしたまま、翌朝のログインの前に 1 回。何日も保たれるかは確かめない。plan 前提 18）:
  .\\.venv\\Scripts\\python.exe poc8_daemon\\login_check.py --url $env:POC_URL
結果: out\\poc8-login-report.md
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
for p in (ROOT, ROOT / "poc1_login", ROOT / "poc2_page"):
    sys.path.insert(0, str(p))
HIST = ROOT / "out" / f"poc8-login-history{os.environ.get('LLMC_POC_REPORT_SUFFIX', '')}.jsonl"  # 試験の記録を利用者の記録に混ぜない

CRED = "input[type=password], input[type=email], input[name=loginfmt], input[name=passwd]"


def judge(page) -> dict:
    from cp import INPUT
    from probe_state import SIGNIN
    try:
        host = page.evaluate("location.hostname") or ""
    except Exception:  # noqa: BLE001
        host = ""
    d = {"host": host if host.endswith(("microsoft.com", "microsoftonline.com", "live.com", "office.com", "copilot.com", "cloud.microsoft")) else "(他)"}
    try:
        d["input"] = page.locator(INPUT).count() > 0
        d["credential_input"] = page.locator(CRED).count() > 0
        d["signin_button"] = sum(1 for i in range(min(page.get_by_role("button", name=SIGNIN).count(), 5))
                                 if page.get_by_role("button", name=SIGNIN).nth(i).is_visible())
    except Exception as e:  # noqa: BLE001
        d["error"] = type(e).__name__
    if d.get("input") and not host.startswith("login."):
        d["state"] = "logged_in"
    elif d.get("credential_input"):
        d["state"] = "login_required"
    elif host.startswith("login."):
        d["state"] = "login_page"
    elif d.get("signin_button"):
        d["state"] = "resumable"
    else:
        d["state"] = "unknown"
    return d


def wait_judge(page, seconds: float) -> dict:
    end = time.time() + seconds
    d = judge(page)
    while time.time() < end and d["state"] in ("unknown", "login_page"):
        page.wait_for_timeout(1000)
        d = judge(page)
    return d


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=os.environ.get("POC_URL"))
    ap.add_argument("--no-resume", action="store_true", help="サインインのボタンを押さない（状態の記録だけ）")
    a = ap.parse_args()
    if not a.url:
        ap.error("--url が必要（または環境変数 POC_URL）")
    os.environ["POC_URL"] = a.url
    from playwright.sync_api import sync_playwright

    from common_browser import launch
    from common.report import Report
    rec = {"t": datetime.now().strftime("%Y-%m-%d %H:%M"), "url_host": a.url.split("/")[2]}
    with sync_playwright() as pw:
        t0 = time.time()
        ctx = launch(pw, "msedge-headed")
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            cdp = ctx.new_cdp_session(page)
            wid = cdp.send("Browser.getWindowForTarget")["windowId"]
            cdp.send("Browser.setWindowBounds", {"windowId": wid, "bounds": {"windowState": "minimized"}})
            rec["minimized"] = True
        except Exception:  # noqa: BLE001
            rec["minimized"] = False
        page.goto(a.url, timeout=60000)
        rec["before"] = wait_judge(page, 30)
        rec["open_s"] = round(time.time() - t0, 1)
        if rec["before"]["state"] == "resumable" and not a.no_resume:
            from probe_state import SIGNIN
            t1 = time.time()
            try:
                page.get_by_role("button", name=SIGNIN).first.click(timeout=15000)
            except Exception:  # noqa: BLE001
                pass
            end = time.time() + 60
            d = judge(page)
            while time.time() < end and d["state"] not in ("logged_in", "login_required"):
                page.wait_for_timeout(1000)
                d = judge(page)
            rec["after_resume"] = d
            rec["resume_s"] = round(time.time() - t1, 1)
        ctx.close()
    final = rec.get("after_resume", rec["before"])["state"]
    rec["final"] = final
    HIST.parent.mkdir(parents=True, exist_ok=True)
    with HIST.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    rep = Report("poc8-login", "PoC-8 (d): ログインの保持（送信しない）")
    hist = [json.loads(x) for x in HIST.read_text(encoding="utf-8").splitlines() if x.strip()]
    first = datetime.strptime(hist[0]["t"], "%Y-%m-%d %H:%M")
    for h in hist:
        days = (datetime.strptime(h["t"], "%Y-%m-%d %H:%M") - first).total_seconds() / 86400
        res = {"logged_in": "OK", "resumable": "WARN"}.get(h["final"], "NG")
        if h["final"] == "logged_in" and h.get("after_resume"):
            res = "OK"  # 押せば黙ってログインできた
        rep.add(f"{h['t'][5:].replace(':', '')} {days:.1f}d", "ログインの状態", res,
                {"最初": h["before"]["state"], "再ログインの後": h.get("after_resume", {}).get("state"),
                 "再ログインの秒数": h.get("resume_s"), "開くまでの秒数": h.get("open_s"), "最小化": h.get("minimized"),
                 "ホスト": h["before"].get("host")})
    print(f"\nレポート: {rep.write()}", file=sys.stderr)
    print(f"今回: {final}", file=sys.stderr)
    if final in ("login_required", "login_page", "unknown"):
        print("ログインが切れています。poc1_login\\login.py でログインし直してから、この後の確認を続けてください"
              "（記録は続きます）", file=sys.stderr)
    from common.digest import show
    show([rep.name])
    return 0


if __name__ == "__main__":
    sys.exit(main())
