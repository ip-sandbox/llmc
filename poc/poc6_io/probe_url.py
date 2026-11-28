"""PoC-6: 入力欄が URL をリンクの部品に変えるかを調べる（自動の方式。**送信はしない**）。

E5 で、文脈のファイルの URL が <a href=... class="fai-ChatInputEntity__text ..."> になって AI に届いた。
URL の形と回避の候補を 1 行ずつ貼り付け、入力欄の中の要素（a、span の class など）と、段落の textContent を記録する。

使い方:
    個人版: .\\.venv\\Scripts\\python.exe poc6_io\\probe_url.py --url https://copilot.microsoft.com/ --variant msedge-headless
    組織版: .\\.venv\\Scripts\\python.exe poc6_io\\probe_url.py --url $env:POC_URL --variant msedge-headed
結果: out\\poc6-url-report.md
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parent / "poc2_page"))
sys.path.insert(0, str(HERE.parent / "poc3_auto"))
from common.report import Report, first_line  # noqa: E402

FORMS = {
    "https": "x https://example.invalid/path y",
    "http": "x http://example.invalid/ y",
    "www": "x www.example.invalid y",
    "ドメインだけ": "x example.com y",
    "mailto": "x mailto:a@example.invalid y",
    "メールアドレス": "x a@example.invalid y",
    "引用符の中": "$u = \"https://example.invalid/a?b=1\"",
    "山かっこ": "<https://example.invalid/>",
    "参照の定義": "[link]: https://example.invalid/path",
    "フェンスの中": "```\nhttps://example.invalid/in-fence\n```",
    "候補: ⟦:⟧": "x https⟦U+003A⟧//example.invalid/ y",
    "候補: ゼロ幅": "x https:/​/example.invalid/ y",
    "候補: ⟦//⟧": "x https:⟦U+002F⟧/example.invalid/ y",
}

PROBE_JS = r"""(sel) => { const el = document.querySelector(sel);
  const ents = Array.from(el.querySelectorAll('a, [class*="Entity"], [data-lexical-decorator]')).map(e =>
      ({tag: e.tagName.toLowerCase(), cls: (e.className || '').toString().split(' ').filter(c => !c.startsWith('_') && !/^f[a-z0-9]{6,}$/.test(c)).join(' '),
        href: e.getAttribute('href'), text: e.textContent.slice(0, 60)}));
  const ps = Array.from(el.querySelectorAll('p')).map(p => p.textContent.replace(/[​-‍﻿]/g, ''));
  return {entities: ents, paragraphs: ps, tags: Array.from(new Set(Array.from(el.querySelectorAll('*')).map(e => e.tagName.toLowerCase()))).sort()}; }"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--variant", default="msedge-headless")
    a = ap.parse_args()
    os.environ["POC_URL"] = a.url
    from playwright.sync_api import sync_playwright

    from cp import INPUT, open_copilot
    from roundtrip import Driver
    rep = Report("poc6-url", f"PoC-6: 入力欄の URL のリンク化（{a.variant}、送信しない）")
    with sync_playwright() as pw:
        ctx, page, info = open_copilot(pw, variant=a.variant)
        rep.add("準備", "画面を開く", "OK" if info["ready"] else "NG", info)
        if not info["ready"]:
            print(rep.write(), file=sys.stderr)
            return 1
        drv = Driver(page, ctx, a.url)
        for label, t in FORMS.items():
            try:
                drv.put(t, "paste_text")
                page.wait_for_timeout(800)
                r = page.evaluate(PROBE_JS, INPUT)
                same = "\n".join(r["paragraphs"]) == t
                rep.add(label, "リンクの部品", "NG" if r["entities"] else "OK",
                        {"送る": t, "部品": r["entities"], "要素": r["tags"], "段落の文字は同じ": same})
            except Exception as e:  # noqa: BLE001
                rep.add(label, "実行", "NG", first_line(e))
            finally:  # click は「有効でない」で待ち続けたことがある（個人版）。focus で足りる
                page.focus(INPUT)
                page.keyboard.press("Control+A")
                page.keyboard.press("Delete")
            rep.write()
        ctx.close()
    print(f"\nレポート: {rep.write()}", file=sys.stderr)
    from common.digest import show
    show([rep.name])
    return 0


if __name__ == "__main__":
    sys.exit(main())
