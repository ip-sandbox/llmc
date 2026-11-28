"""PoC-6 (b): 入力欄の読み戻しの方法（自動の方式。送信はしない）。

書式 llmc/1 のプロンプト（空行を代わりの行にしたもの、しないもの）を貼り付けイベントで入力欄に入れ、
次の 3 つの読み方で読み戻して、送る本文と比べる。最後に入力欄を空にする。**送信ボタンは押さない。**
    textContent（全体） / innerText（全体） / 段落（<p>）ごとの textContent を改行でつなぐ

使い方:
    個人版（この PC）: .\\.venv\\Scripts\\python.exe poc6_io\\readback.py --url https://copilot.microsoft.com/ --variant msedge-headless
    組織版:           .\\.venv\\Scripts\\python.exe poc6_io\\readback.py --url https://m365.cloud.microsoft/chat --variant msedge-headed
結果: out\\poc6-readback-report.md
"""
from __future__ import annotations

import argparse
import re
import os
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "poc2_page"))
sys.path.insert(0, str(HERE.parent / "poc3_auto"))
from common6 import OUT, apply_filler, choose_filler  # noqa: E402
from echo_fidelity import CASES, TASK  # noqa: E402
import run as M  # noqa: E402
from common.report import Report, first_line  # noqa: E402

READ_JS = r"""(sel) => { const el = document.querySelector(sel);
  const zw = s => s.replace(/[​-‍﻿]/g, '');
  const ps = Array.from(el.querySelectorAll('p'));
  return { textContent: zw(el.textContent), innerText: zw(el.innerText),
           paragraphs: ps.length ? ps.map(p => zw(p.textContent)).join('\n') : null,
           n_p: ps.length, n_br: el.querySelectorAll('br').length,
           tags: Array.from(new Set(Array.from(el.querySelectorAll('*')).map(e => e.tagName.toLowerCase()))).sort() }; }"""


ZW_RE = re.compile('[\u200b-\u200d\ufeff]')


def norm_lines(s: str, strip_zw: bool = False) -> list[str]:
    """NBSP を空白に、行末の空白を無視する。strip_zw なら、ゼロ幅文字も除く（入力欄の Lexical がゼロ幅文字を足すため、読み戻しでは送る側からも除いて比べる）。"""
    s = ZW_RE.sub('', s) if strip_zw else s
    return [x.replace('\u00a0', ' ').rstrip(' ') for x in s.replace('\r\n', '\n').rstrip('\n').split('\n')]


def compare(want: str, got: str | None, strip_zw: bool = False) -> dict:
    if got is None:
        return {"一致": False, "理由": "読めない"}
    w, g = norm_lines(want, strip_zw), norm_lines(got, strip_zw)
    first = next((i for i, (a, b) in enumerate(zip(w, g)) if a != b), None if len(w) == len(g) else min(len(w), len(g)))
    return {"一致": w == g, "行数（送る/読み戻し）": f"{len(w)}/{len(g)}",
            "最初に違う行": None if first is None else {"行": first + 1, "送る": repr(w[first][:40]) if first < len(w) else None,
                                                    "読み戻し": repr(g[first][:40]) if first < len(g) else None}}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--variant", default="msedge-headless")
    a = ap.parse_args()
    os.environ["POC_URL"] = a.url
    from playwright.sync_api import sync_playwright

    from cp import INPUT, open_copilot
    from roundtrip import Driver
    rep = Report("poc6-readback", f"PoC-6 (b): 入力欄の読み戻し（{a.variant}、送信しない）")
    texts = {}
    for name, c in CASES.items():
        ws = OUT / f"ws-rb-{name}"
        if ws.exists():
            shutil.rmtree(ws)
        (ws / c["path"]).parent.mkdir(parents=True, exist_ok=True)
        (ws / c["path"]).write_bytes(c["text"].encode("utf-8"))
        prompt, _sha, ctx = M.build_prompt(M.new_tid(), {"allow": [c["path"]], "task": TASK}, ws, long_rules=True)
        f = choose_filler(ctx.values())
        texts[f"{name} 代わりの行（空白 {len(f)} 個）"] = apply_filler(prompt, f)
        texts[f"{name} 空行のまま"] = prompt
    with sync_playwright() as pw:
        ctx, page, info = open_copilot(pw, variant=a.variant)
        rep.add("準備", "画面を開く", "OK" if info["ready"] else "NG", info)
        if not info["ready"]:
            print(rep.write(), file=sys.stderr)
            return 1
        drv = Driver(page, ctx, a.url)
        for label, t in texts.items():
            try:
                drv.put(t, "paste_text")
                page.wait_for_timeout(500)
                r = page.evaluate(READ_JS, INPUT)
                rep.add(label, "入力欄の構造", "INFO", {"<p> の数": r["n_p"], "<br> の数": r["n_br"], "要素": r["tags"],
                                                     "送る行数": t.count("\n") + 1})
                for how in ("textContent", "innerText", "paragraphs"):
                    c = compare(t, r[how], strip_zw=True)
                    # 採用する読み方（paragraphs）だけを合否にする。ほかは参考（個人版で合わないと分かっている）
                    if how == "paragraphs":
                        rep.add(label, how, "OK" if c["一致"] else "NG", c)
                    else:
                        rep.add(label, how, "INFO", {"一致": c["一致"], "行数": c.get("行数（送る/読み戻し）")})
            except Exception as e:  # noqa: BLE001
                rep.add(label, "実行", "NG", first_line(e))
            finally:
                page.click(INPUT)
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
