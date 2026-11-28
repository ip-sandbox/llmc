"""S0: 貼り付けたファイルの中身が、AI に一字一句そのまま届くかを調べる（人が送信する方式）。

3 つの貼り付け方で、AI に中身をそのまま返させ、元と比べる。
    A: テキストをそのまま貼り付ける（今の方式）
    B: 空行を「空白 1 文字の行」にしてから貼り付ける
    C: テキストに加えて HTML（<pre>）もクリップボードに入れる

使い方: .\\.venv\\Scripts\\python.exe manual\\probe_input.py
結果: out\\manual-probe-input-report.md
"""
from __future__ import annotations

import difflib
import html
import secrets
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import clip  # noqa: E402
from common.report import OUT_DIR, Report  # noqa: E402
from htmlseg import segments  # noqa: E402

# 空行（連続を含む）、インデント、タブ、行末の空白、全角、入れ子のフェンスを含む架空の中身
SAMPLE = ("# 架空の設定\n\nserver:\n  workers: 4\n\n\n  timeout: 30\n\tタブ行\n末尾に空白2個  \n"
          "```python\nprint('x')\n\nprint('y')\n```\n\n最後の行\n")
ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def prompt_for(tid: str, body: str) -> str:
    f = "````"
    return (f"このターンの ID: {tid}\n"
            "これは動作確認です。次のコードブロックの中身（LLMC-ECHO の行の次の行から、LLMC-ECHO-END の行の前の行まで）を、"
            "1 文字も変えずに、バッククォート 4 個のコードブロックに入れて返してください。"
            "空行の数、行頭と行末の空白、タブもそのまま保ってください。説明は不要です。\n\n"
            f"{f}text\nLLMC-ECHO id={tid}\n{body.rstrip(chr(10))}\nLLMC-ECHO-END id={tid}\n{f}\n")


def extract(text: str, html_raw: str | None) -> tuple[str | None, str]:
    """回答のコードブロックの中身を取り出す。HTML があれば <pre> を使う。"""
    if html_raw:
        codes = [t for k, t in segments(html_raw) if k == "code"]
        if codes:
            c = max(codes, key=len)
            lines = c.split("\n")
            if lines and lines[0].startswith("LLMC-ECHO"):
                lines = lines[1:]
            if lines and lines[-1].startswith("LLMC-ECHO-END"):
                lines = lines[:-1]
            return "\n".join(lines), "HTML の <pre>"
    return text.strip("\n"), "テキスト"


def compare(want: str, got: str) -> dict:
    w, g = want.rstrip("\n").split("\n"), got.rstrip("\n").split("\n")
    # 行の位置（@@ の行）も残し、前後 1 行を付ける。どこで空行が増減したかを分かるようにする
    diff = [l for l in difflib.unified_diff(w, g, lineterm="", n=1) if not l.startswith(("---", "+++"))]
    return {"一致": w == g, "行数（元/回答）": f"{len(w)}/{len(g)}",
            "空行の数（元/回答）": f"{sum(1 for x in w if x == '')}/{sum(1 for x in g if x == '')}",
            "<br> の行": sum(1 for x in g if x.strip() == "<br>"),
            "空白だけの行": sum(1 for x in g if x and not x.strip()),
            "差分（先頭 12 行）": [repr(x) for x in diff[:12]]}


def main() -> int:
    rep = Report("manual-probe-input", "S0: 貼り付けた中身が AI にそのまま届くか")
    out = OUT_DIR / "manual"
    out.mkdir(parents=True, exist_ok=True)
    variants = {
        "A テキスト": (SAMPLE, False),
        "B 空行を空白1文字に": ("\n".join(" " if l == "" else l for l in SAMPLE.rstrip("\n").split("\n")) + "\n", False),
        "C テキスト＋HTML": (SAMPLE, True),
    }
    for name, (body, with_html) in variants.items():
        tid = "".join(secrets.choice(ALPHABET) for _ in range(6))
        p = prompt_for(tid, body)
        if with_html:
            intro, block = p.split("````text\n", 1)
            frag = (f"<p>{html.escape(intro).replace(chr(10), '<br>')}</p>"
                    f"<pre><code>{html.escape(block.rsplit('````', 1)[0])}</code></pre>")
            clip.set_text_and_html(p, frag)
        else:
            clip.set_text(p)
        print("\n" + "=" * 60, file=sys.stderr)
        print(f"[{name}] Copilot で【新しいチャット】を開き、貼り付けて（Ctrl+V）送信し、回答の「コピー」を押してください。",
              file=sys.stderr)
        print("  ※貼り付けた直後の入力欄の見た目（空行が残っているか、コードの枠になったか）も覚えておいてください。", file=sys.stderr)
        seq, t0, got = clip.sequence(), time.time(), None
        while time.time() - t0 < 1200:
            time.sleep(0.4)
            if clip.sequence() == seq:
                continue
            seq = clip.sequence()
            t = clip.get_text()
            if t and "このターンの ID" not in t and "架空の設定" in t:
                got = (t, clip.get_html())
                break
        if not got:
            rep.add(name, "回答", "NG", "受け取れなかった")
            continue
        text, h = got
        (out / f"S0-{name[0]}-response.txt").write_bytes(text.encode("utf-8"))
        if h:
            (out / f"S0-{name[0]}-response.html").write_bytes(h.encode("utf-8"))
        body_got, how = extract(text, h)
        want = SAMPLE if name[0] != "B" else SAMPLE  # B も元の中身（空行）と比べる。空白だけの行は別に数える
        c = compare(want, body_got if name[0] != "B" else "\n".join("" if not l.strip() else l for l in body_got.split("\n")))
        rep.add(name, f"比較（{how}）", "OK" if c["一致"] else "NG", c)
        rep.write()
    print(f"\nレポート: {rep.write()}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
