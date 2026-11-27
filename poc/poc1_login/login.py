"""PoC-1: 画面ありのブラウザで手動でログインし、プロファイルに保存する。

使い方:
    python poc1_login\\login.py --browser chromium     # Playwright 同梱の Chromium
    python poc1_login\\login.py --browser msedge       # Edge（入っていれば）
ブラウザが開いたら Microsoft アカウントでログインし、チャットの画面が出たらコンソールで Enter を押す。
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
from common.report import Report, first_line  # noqa: E402
from common_browser import URL, launch, profile_dir  # noqa: E402
from probe_state import page_state, verdict  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--browser", choices=["chromium", "msedge"], required=True)
    a = ap.parse_args()
    from playwright.sync_api import sync_playwright
    rep = Report(f"poc1-login-{a.browser}", f"PoC-1 ログイン（{a.browser}）")
    variant = "chromium-headed" if a.browser == "chromium" else "msedge-headed"
    with sync_playwright() as pw:
        try:
            ctx = launch(pw, variant)
        except Exception as e:  # noqa: BLE001
            rep.add("ログイン", "ブラウザの起動", "NG", first_line(e))
            print(rep.write())
            return 1
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(URL)
        print("\nブラウザで Microsoft アカウントにログインしてください。"
              "\nチャットの入力欄が表示されたら、ここで Enter を押してください。", file=sys.stderr)
        input()
        st = page_state(ctx, page, wait_s=10)
        rep.add("ログイン", "ログイン直後の状態", verdict(st), st)
        ans = input("画面上でログインできていますか（右上にアカウントが表示されているなど）？ [y/n]: ").strip().lower()
        rep.add("ログイン", "利用者の目視", "OK" if ans == "y" else "NG", ans)
        ctx.close()
    meta = profile_dir(a.browser) / "llmc-poc-login.json"
    meta.write_text(json.dumps({"logged_in_at": datetime.datetime.now().isoformat(timespec="minutes")}),
                    encoding="utf-8")
    path = rep.write()
    print(f"\nレポート: {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
