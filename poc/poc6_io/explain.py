"""保存した回答（out\\poc6\\*-response.html）が書式どおりでなかった理由の手がかりを、英数字だけで短く示す（送信しない）。

使い方: .\\.venv\\Scripts\\python.exe poc6_io\\explain.py [ファイル名の一部（既定 limits）]
出力の例: auto-limits-1000 chars=261 hint=DL+LIMIT links=1 pres=1 llmc_lines=2 first=LLMC-PLAN
  hint の意味: DL=ファイルの作成・ダウンロードに触れた、LIMIT=上限・長さに触れた、REFUSE=断った、SPLIT=分割・続きに触れた、
              CODE=コードの実行に触れた、ASK=質問で終わった
"""
from __future__ import annotations

import html
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
from common6 import OUT, parse_cf_html, response_hints  # noqa: E402
from common.digest import ascii_only  # noqa: E402


def text_of(frag: str) -> str:
    frag = re.sub(r"<(style|head)[^>]*>.*?</\1>", "", frag, flags=re.S)
    frag = re.sub(r"<br\s*/?>|</(p|div|li|pre|h\d)>", "\n", frag)
    return html.unescape(re.sub(r"<[^>]+>", "", frag))


def main() -> int:
    key = sys.argv[1] if len(sys.argv) > 1 else "limits"
    files = sorted(p for p in OUT.glob("*-response.html") if key in p.name)
    if not files:
        print("該当する回答が無い", file=sys.stderr)
        return 1
    lines = []
    for p in files:
        raw = p.read_bytes()
        t = text_of(parse_cf_html(raw)["fragment"]).strip()
        h = response_hints(t, raw)
        first = next((x.strip() for x in t.split("\n") if x.strip()), "")
        first = first.split()[0] if first.startswith("LLMC-") else ascii_only(first)[:20]
        lines.append(f"{p.name.replace('-response.html', '')} chars={len(t)} hint={h['hint']} links={h['links']} pres={h['pres']} "
                     f"imgs={h['imgs']} llmc_lines={h['llmc_lines']} first={first}")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
