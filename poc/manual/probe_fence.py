"""S0b: フェンスの書き方ごとに、Copilot がコードブロックとして表示するか（コピーの HTML が <pre> になるか）を調べる。

個人版の実測で、回答のブロックが <pre> ではなく「<div> の行の並び」（__init__ が太字になる＝Markdown として描画）
になることがあった。どのフェンス（バッククォートの数、言語名、チルダ）で起きるかを切り分ける。

使い方: .\\.venv\\Scripts\\python.exe manual\\probe_fence.py
  Copilot で【新しいチャット】を開き、貼り付けて（Ctrl+V）送信し、回答の下の「コピー」を押す。
結果: out\\manual-probe-fence-report.md（回答の生データは out\\manual\\S0b-response.*）
"""
from __future__ import annotations

import re
import secrets
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import clip  # noqa: E402
from common.report import OUT_DIR, Report  # noqa: E402
from htmlseg import cf_html_fragment  # noqa: E402

ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
# 番号, 開きのフェンス, 閉じのフェンス
STYLES = [
    (1, "```", "```"),
    (2, "```text", "```"),
    (3, "```python", "```"),
    (4, "````", "````"),
    (5, "````text", "````"),
    (6, "````python", "````"),
    (7, "`````", "`````"),
    (8, "`````python", "`````"),
    (9, "~~~", "~~~"),
    (10, "~~~~python", "~~~~"),
]


def prompt_for(tid: str) -> str:
    lines = [f"このターンの ID: {tid}",
             "これは表示の動作確認です。次の一覧の番号ごとに、指定した開きの行と閉じの行をそのまま使ったコードブロックを1つずつ、"
             "番号の順に出力してください。各ブロックの中身は次の3行です（<n> は番号）。",
             "  1行目: LLMC-PROBE n=<n> pkg/__init__.py",
             "  2行目: （空行）",
             "  3行目: 終わり <n>",
             "開きの行と閉じの行は、バッククォートやチルダの数も言語名も一字一句変えないでください。ブロックの間に説明は書かないでください。",
             ""]
    for n, o, c in STYLES:
        lines.append(f"- 番号 {n}: 開きの行は「{o}」、閉じの行は「{c}」")
    lines += ["", f"最後に、コードブロックの外に「LLMC-PROBE-DONE id={tid}」と1行書いてください。"]
    return "\n".join(lines)


def analyze(text: str, html: str | None) -> dict[int, dict]:
    res = {n: {} for n, _, _ in STYLES}
    frag = cf_html_fragment(html or "")
    # HTML: 各 LLMC-PROBE n=<n> の行が <pre> の中にあるか、太字（<strong>）になったか
    pres = re.findall(r"<pre[^>]*>(.*?)</pre>", frag, re.S)
    for n in res:
        pat = rf"LLMC-PROBE n={n}\b"
        in_pre = any(re.search(pat, p) for p in pres)
        m = re.search(pat + r"[^<\n]*(?:<[^>]+>[^<\n]*){0,4}", frag)
        res[n]["HTML"] = "pre" if in_pre else ("無い" if not m else "pre 以外")
        if m and not in_pre:
            res[n]["太字になった"] = "<strong>" in m.group(0)
    # テキスト: その番号の前の行（開きのフェンス）が残っているか
    tl = text.replace("\r\n", "\n").split("\n")
    for i, l in enumerate(tl):
        m = re.match(r"\s*LLMC-PROBE n=(\d+)", l)
        if m and int(m.group(1)) in res:
            prev = tl[i - 1] if i else ""
            res[int(m.group(1))]["テキストの前の行"] = repr(prev[:20])
            res[int(m.group(1))]["__init__ が残った"] = "__init__" in l
    return res


def main() -> int:
    rep = Report("manual-probe-fence", "S0b: フェンスの書き方と表示（コードブロックになるか）")
    out = OUT_DIR / "manual"
    out.mkdir(parents=True, exist_ok=True)
    tid = "".join(secrets.choice(ALPHABET) for _ in range(6))
    p = prompt_for(tid)
    clip.set_text(p)
    print("Copilot で【新しいチャット】を開き、貼り付けて（Ctrl+V）送信し、回答の下の「コピー」を押してください。", file=sys.stderr)
    seq, t0, got = clip.sequence(), time.time(), None
    while time.time() - t0 < 1200:
        time.sleep(0.4)
        if clip.sequence() == seq:
            continue
        seq = clip.sequence()
        try:
            t = clip.get_text()
        except OSError:
            continue
        if t and "LLMC-PROBE n=" in t and "開きの行は" not in t:
            got = (t, clip.get_html())
            break
        if t:
            print(f"  （回答ではないコピーを無視しました: {t[:30]!r}）", file=sys.stderr)
    if not got:
        rep.add("回答", "受け取り", "NG", "受け取れなかった")
        print(rep.write(), file=sys.stderr)
        return 1
    text, h = got
    (out / "S0b-response.txt").write_bytes(text.encode("utf-8"))
    (out / "S0b-response.html").write_bytes((h or "").encode("utf-8"))
    rep.add("回答", "受け取り", "OK", {"HTML あり": bool(h), "ID あり": tid in text})
    for n, r in analyze(text, h).items():
        o = next(x for x in STYLES if x[0] == n)[1]
        rep.add("フェンスごと", f"{n}: {o}", "OK" if r.get("HTML") == "pre" else "NG", r)
    print(f"\nレポート: {rep.write()}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
