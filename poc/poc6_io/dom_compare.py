"""PoC-6 (d): DOM の <pre> と、コピーの HTML の忠実さの比較（自動の方式で会話を開いて読むだけ。送信しない）。

echo_fidelity.py の後に実行する。記録（out\\poc6\\echo-record.json）のターン ID を含む会話を開き、
ID を含む <pre> の textContent・innerText を、保存したコピーの HTML の code 区分と比べる。
会話の題名は表示も記録もしない。

使い方（個人版、この PC）: .\\.venv\\Scripts\\python.exe poc6_io\\dom_compare.py --url https://copilot.microsoft.com/
結果: out\\poc6-dom-report.md
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "poc2_page"))
from common6 import OUT, parse_cf_html  # noqa: E402
from common.report import Report, first_line  # noqa: E402
from htmlseg import segments  # noqa: E402
from readback import compare  # noqa: E402

PRE_JS = r"""(tid) => Array.from(document.querySelectorAll('main pre')).filter(p => p.textContent.includes('id=' + tid))
  .map(p => ({textContent: p.textContent, innerText: p.innerText,
              tags: Array.from(new Set(Array.from(p.querySelectorAll('*')).map(e => e.tagName.toLowerCase()))).sort()}))"""


def find_conversation(page, tid: str, limit: int = 12) -> bool:
    page.wait_for_timeout(3000)
    links = page.locator("a[href*='/chat/conversation/'], a[href*='/chats/']")
    n = links.count()
    idx = [i for i in range(n) if "llmc" in (links.nth(i).inner_text() or "").lower()] or list(range(min(n, limit)))
    for i in idx[:limit]:
        try:
            links.nth(i).click()
            page.wait_for_timeout(4000)
            if tid in page.locator("main").inner_text():
                return True
        except Exception:  # noqa: BLE001
            continue
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--variant", default="msedge-headless")
    a = ap.parse_args()
    os.environ["POC_URL"] = a.url
    record = json.loads((OUT / "echo-record.json").read_text(encoding="utf-8"))
    from playwright.sync_api import sync_playwright

    from cp import open_copilot
    rep = Report("poc6-dom", "PoC-6 (d): DOM の <pre> とコピーの HTML の比較（読むだけ）")
    with sync_playwright() as pw:
        ctx, page, info = open_copilot(pw, variant=a.variant)
        rep.add("準備", "画面を開く", "OK" if info["ready"] else "NG", info)
        for name, r in record.items():
            tid = r["tid"]
            try:
                page.goto(a.url, timeout=60000)
                if not find_conversation(page, tid):
                    rep.add(name, "会話", "NG", "見つからない")
                    continue
                pres = page.evaluate(PRE_JS, tid)
                raw = (OUT / f"{name}-response.html").read_bytes()
                codes = [t for k, t in segments(parse_cf_html(raw)["fragment"]) if k == "code" and f"id={tid}" in t]
                file_html = next((c for c in codes if "LLMC-FILE" in c), None)
                file_dom = next((p for p in pres if "LLMC-FILE" in p["textContent"]), None)
                rep.add(name, "見つかった <pre>", "INFO", {"DOM": len(pres), "コピーの HTML": len(codes),
                                                         "DOM の <pre> の中の要素": file_dom["tags"] if file_dom else None})
                if not (file_html and file_dom):
                    rep.add(name, "比較", "NG", "ファイルのブロックが片方に無い")
                    continue
                for how in ("textContent", "innerText"):
                    c = compare(file_html, file_dom[how].rstrip("\n"))
                    rep.add(name, f"コピーの HTML と DOM の {how}", "OK" if c["一致"] else "NG", c)
                nb = " "
                rep.add(name, "U+00A0", "INFO", {"コピーの HTML": file_html.count(nb), "DOM textContent": file_dom["textContent"].count(nb),
                                                 "DOM innerText": file_dom["innerText"].count(nb)})
            except Exception as e:  # noqa: BLE001
                rep.add(name, "実行", "NG", first_line(e))
            rep.write()
        ctx.close()
    print(f"\nレポート: {rep.write()}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
