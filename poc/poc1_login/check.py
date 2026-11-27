"""PoC-1: ログイン済みのプロファイルを、ブラウザとヘッドレスの組み合わせごとに開き、ログインが保たれるかを調べる（H-01）。

メッセージは送らない。画面を開いて状態を見るだけ。
使い方:
    python poc1_login\\check.py                 # ログイン済みのプロファイルがあるブラウザについて、すべての組み合わせ
    python poc1_login\\check.py --only chromium-new-headless
日を空けて何度か実行すると、ログインが保たれる期間の目安になる。
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
from common_browser import URL, VARIANTS, launch, profile_dir  # noqa: E402
from probe_state import page_state, verdict  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=sorted(VARIANTS))
    ap.add_argument("--wait", type=float, default=30, help="入力欄が現れるまで待つ秒数")
    ap.add_argument("--anonymous", action="store_true",
                    help="ログインせず、使い捨てのプロファイルで開く（ボット対策で止められないかを見る）")
    a = ap.parse_args()
    from playwright.sync_api import sync_playwright
    if a.anonymous:
        import tempfile
        import common_browser
        tmp = Path(tempfile.mkdtemp(prefix="llmc-poc-anon-"))
        common_browser.profile_root = lambda: tmp
        for b in ("chromium", "msedge"):
            (tmp / b).mkdir(parents=True)
            (tmp / b / "llmc-poc-login.json").write_text('{"logged_in_at": "2000-01-01T00:00"}', encoding="utf-8")
    rep = Report("poc1-anon" if a.anonymous else "poc1-check",
                 "PoC-1 未ログインでの表示" if a.anonymous else "PoC-1 ログインの保持（ブラウザとヘッドレスの組み合わせ）")
    for browser in ("chromium", "msedge") if not a.anonymous else ():
        meta = profile_dir(browser) / "llmc-poc-login.json"
        if meta.exists():
            t = json.loads(meta.read_text(encoding="utf-8"))["logged_in_at"]
            age = datetime.datetime.now() - datetime.datetime.fromisoformat(t)
            rep.add("プロファイル", browser, "INFO", f"ログインから {age.days} 日 {age.seconds // 3600} 時間")
        else:
            rep.add("プロファイル", browser, "SKIP", "login.py でのログインがまだ")
    with sync_playwright() as pw:
        for variant, (browser, _kw) in VARIANTS.items():
            if a.only and variant != a.only:
                continue
            if not (profile_dir(browser) / "llmc-poc-login.json").exists():
                continue
            try:
                ctx = launch(pw, variant)
                try:
                    page = ctx.pages[0] if ctx.pages else ctx.new_page()
                    page.goto(URL, timeout=60000)
                    st = page_state(ctx, page, wait_s=a.wait)
                    rep.add("組み合わせ", variant, verdict(st), st)
                finally:
                    ctx.close()
            except Exception as e:  # noqa: BLE001
                rep.add("組み合わせ", variant, "NG", first_line(e))
    path = rep.write()
    print(f"\nレポート: {path}\n内容を確認してから、チャットに貼ってください。", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
