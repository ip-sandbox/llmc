"""poc3_auto の回答（out\\poc3-auto-raw）の形を要約する。会話は架空なので、先頭の行も表示する。

使い方: .\\.venv\\Scripts\\python.exe poc3_auto\\inspect_raw.py S1
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "manual")]
from htmlseg import segments  # noqa: E402

name = sys.argv[1] if len(sys.argv) > 1 else "S1"
d = ROOT / "out" / "poc3-auto-raw"
text = (d / f"{name}-response.txt").read_bytes().decode("utf-8")
html = (d / f"{name}-response.html").read_bytes().decode("utf-8")
print(f"== {name}: text {len(text)} 文字 / html {len(html)} 文字")
print("html のタグの数:", {t: len(re.findall(rf"<{t}[\s>]", html)) for t in ("pre", "code", "p", "div", "table", "strong", "ol", "ul", "li")})
print("text でフェンスの行:", sum(1 for l in text.splitlines() if l.lstrip().startswith(("```", "~~~"))))
print("\n== 区分（種類・行数・先頭の行）")
for k, t in segments(html):
    print(f"  {k:4s} {t.count(chr(10)) + 1:3d} 行 | {t.splitlines()[0][:70] if t.strip() else ''!r}")
print("\n== text の先頭 25 行")
for l in text.splitlines()[:25]:
    print("  " + repr(l))
