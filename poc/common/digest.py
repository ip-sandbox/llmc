"""レポートの要約（チャットに貼るためのもの）。

レポートの JSON（out\\*-report.json）を読み、切り分けに要る情報だけを短い文字列にまとめる。
  - 先頭: レポートごとに 1 行（名前、OK/NG/WARN/INFO の数、全体の指紋（sha の先頭 8 文字））
  - NG と WARN: 1 項目 1 行で、詳細（エラー・警告のコード、数値、差分の先頭）を短くして載せる
  - INFO: 文字数に余裕があれば短く載せる
  - OK: 節ごとの数だけ
全体を --limit 文字（既定 1,800）に収める。収まらない分は優先度の低いものから省き、省いた数を書く。
結果はクリップボードにも入れる（履歴とクラウドへの同期からは除外する）。そのまま Ctrl+V でチャットに貼る。

使い方:
    .\\.venv\\Scripts\\python.exe common\\digest.py                       # 直近 3 時間に書かれたレポート全部
    .\\.venv\\Scripts\\python.exe common\\digest.py poc6-echo-auto poc6-limits-auto
    .\\.venv\\Scripts\\python.exe common\\digest.py --hours 1 --limit 1200 --no-clip
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from common.report import OUT_DIR  # noqa: E402

PRIO = {"NG": 0, "WARN": 1, "INFO": 2, "OK": 3, "SKIP": 3}
# 詳細のうち、長くなりやすく切り分けに役立たないもの
DROP_KEYS = {"plan", "done"}


def short(v, n: int) -> str:
    """値を n 文字程度の短い文字列にする。"""
    if isinstance(v, bool):
        return "y" if v else "n"
    if isinstance(v, (int, float)) or v is None:
        return str(v)
    if isinstance(v, str):
        v = v.replace("\n", "⏎")
        return v if len(v) <= n else v[: n - 1] + "…"
    if isinstance(v, list):
        if not v:
            return "[]"
        parts = [short(x, max(12, n // 3)) for x in v[:3]]
        more = f"+{len(v) - 3}" if len(v) > 3 else ""
        return "[" + ",".join(parts) + more + "]"
    if isinstance(v, dict):
        return "{" + ";".join(f"{k}={short(x, max(10, n // 3))}" for k, x in list(v.items())[:6]) + "}"
    return short(str(v), n)


def detail_str(d, n: int) -> str:
    if d is None:
        return ""
    if not isinstance(d, dict):
        return short(d, n)
    parts = []
    # エラーと警告のコードは最初に、省かずに載せる（コードの部分だけ）
    for key in ("errors", "warnings", "エラー", "警告"):
        if d.get(key):
            parts.append(f"{key}=" + ",".join(str(x).split(":")[0] for x in d[key]))
    for k, v in d.items():
        if k in DROP_KEYS or k in ("errors", "warnings", "エラー", "警告"):
            continue
        if k == "files" and isinstance(v, list):
            v = [f"{x[1]}:{x[2]}行" if isinstance(x, list) and len(x) >= 3 else x for x in v]
        parts.append(f"{k}={short(v, 60)}")
    s = "; ".join(parts)
    return s if len(s) <= n else s[: n - 1] + "…"


def load(name: str) -> list[dict]:
    return json.loads((OUT_DIR / f"{name}-report.json").read_text(encoding="utf-8"))


def digest(names: list[str], limit: int = 1800) -> str:
    head, lines = [], []
    for name in names:
        items = load(name)
        raw = json.dumps(items, ensure_ascii=False, sort_keys=True).encode("utf-8")
        cnt = {}
        for it in items:
            cnt[it["status"]] = cnt.get(it["status"], 0) + 1
        tag = name.replace("-report", "")
        head.append(f"#{tag} " + " ".join(f"{k}{v}" for k, v in sorted(cnt.items(), key=lambda x: PRIO.get(x[0], 9)))
                    + f" fp={hashlib.sha256(raw).hexdigest()[:8]}")
        ok_by_sec = {}
        for i, it in enumerate(items):
            st = it["status"]
            sec = it["section"].split(":")[0][:16]
            if st == "OK":
                ok_by_sec[sec] = ok_by_sec.get(sec, 0) + 1
                continue
            n = {"NG": 260, "WARN": 200}.get(st, 110)
            lines.append((PRIO.get(st, 9), i, f"{st[0]} {sec}/{it['item'][:24]}: {detail_str(it.get('detail'), n)}"))
        if ok_by_sec:
            lines.append((3, 10_000, f"OK {tag}: " + ", ".join(f"{s}×{c}" for s, c in ok_by_sec.items())))
    lines.sort(key=lambda x: (x[0], x[1]))
    out = list(head)
    used = sum(len(x) + 1 for x in out)
    dropped = 0
    for _p, _i, text in lines:
        if used + len(text) + 1 > limit:
            dropped += 1
            continue
        out.append(text)
        used += len(text) + 1
    if dropped:
        out.append(f"（{dropped} 行を省略。全文は out\\ の各レポート）")
    return "\n".join(out)


# ---------------------------------------------------------------- 短い形（--short）
# 別の PC から打ち直したり、写真から文字を起こしたりしても間違えにくいよう、英数字と記号だけにする。
# 名前は下の略語に置き換える。略語に無い日本語は「~」にし、特殊な文字（空白・ゼロ幅など）は <16 進> で示す。

ABBR = [  # 長いものから順に置き換える
    ("中身の比較（代わりの行を戻した後）", "cmp"), ("参考: U+00A0 を空白とみなした比較", "cmpNB"),
    ("DOM の textContent とコピーの HTML", "domTC"), ("DOM の innerText とコピーの HTML", "domIT"),
    ("代わりの行の書き返し", "fillback"), ("代わりの行（空白の数）", "fill"), ("回答の中の代わりの行", "fillN"),
    ("回答の中の空行（そのまま）", "blankN"), ("回答の中のほかの空白だけの行（空白の数）", "wsN"),
    ("特殊な文字（期待/回答）", "sp"), ("行数（送る/読み戻し）", "n"), ("行数（期待/回答）", "n"), ("差分（先頭 10 行）", "diff"),
    ("先頭から正しく続いた行", "okL"), ("... だけの行", "dots"), ("完成したブロック", "blk"), ("回答の文字数", "chars"),
    ("回答まで秒", "sec"), ("合言葉を答えた", "pw"), ("最初に違う行", "d"), ("入力欄の構造", "dom"), ("コピーの HTML", "html"),
    ("見つかった <pre>", "pres"), ("画面を開く", "open"), ("読み戻し", "r"), ("送る", "s"), ("一致", "eq"),
    ("空白だけの行", "wsL"), ("タブを含む行", "tabL"), ("行末の空白", "trailL"), ("U+00A0 を含む行", "nbL"),
    ("空行のまま", "raw"), ("入力の上限", "in"), ("出力の上限", "out"), ("の続き", "+cont"), ("事象", "ev"), ("画面の表示", "msg"),
    ("画面の様子", "msg"), ("解析", "parse"), ("回答", "ans"), ("準備", "prep"), ("条件", "cond"), ("分類", "k"), ("空行", "blank"),
    ("行数", "n"), ("文字", "c"), ("行", "L"), ("時間切れ", "timeout"), ("飛ばした", "skip"), ("見つからない", "notfound"),
    ("代わりの行（空白 ", "f"), (" 個）", ""), ("正しい行", "okL"), ("省略の警告", "W"), ("（約 ", "~"), ("）", ""), ("（", "("), ("：", ":"), ("、", ","),
]
SPECIAL_CAT = ("Zs", "Zl", "Zp", "Cf", "Cc")


def ascii_only(s: str) -> str:
    import unicodedata
    for ja, ab in sorted(ABBR, key=lambda x: -len(x[0])):
        s = s.replace(ja, ab)
    out = []
    for ch in s:
        if ch.isascii():
            out.append(ch)
        elif unicodedata.category(ch) in SPECIAL_CAT:
            out.append(f"<{ord(ch):x}>")
        elif not out or out[-1] != "~":
            out.append("~")
    return "".join(out)


def short_digest(names: list[str], limit: int = 500) -> str:
    text = digest(names, limit=10_000)
    out, used, dropped = [], 0, 0
    for line in text.split("\n"):
        line = ascii_only(line)
        line = line.replace("; ", " ").replace("=y", "=Y").replace("=n ", "=N ")
        if len(line) > 160:
            line = line[:159] + "~"
        if used + len(line) + 1 > limit and not line.startswith("#"):
            dropped += 1
            continue
        out.append(line)
        used += len(line) + 1
    if dropped:
        out.append(f"(+{dropped} lines)")
    return "\n".join(out)


def recent(hours: float) -> list[str]:
    t = time.time() - hours * 3600
    files = sorted((p for p in OUT_DIR.glob("*-report.json") if p.stat().st_mtime >= t), key=lambda p: p.stat().st_mtime)
    return [p.name[: -len("-report.json")] for p in files]


def to_clipboard(text: str) -> bool:
    try:
        sys.path.insert(0, str(HERE.parent / "poc6_io"))
        from common6 import set_text_private
        set_text_private(text)
        return True
    except Exception:  # noqa: BLE001
        return False


def show(names: list[str], limit: int = 1800, clip: bool = True) -> None:
    """各 PoC の終わりに呼ぶ。要約を表示してクリップボードに入れる。"""
    text = digest(names, limit)
    print("\n----- 貼り付け用の要約（ここから） -----\n" + text + "\n----- （ここまで） -----", file=sys.stderr)
    import os
    if clip and not os.environ.get("LLMC_POC_NO_CLIP") and to_clipboard(text):
        print("要約をクリップボードに入れました。内容を確認してから、チャットに Ctrl+V で貼ってください。", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="*", help="レポートの名前（out\\<名前>-report.json）。省略すると直近のもの")
    ap.add_argument("--hours", type=float, default=3)
    ap.add_argument("--limit", type=int, default=1800)
    ap.add_argument("--no-clip", action="store_true")
    ap.add_argument("--short", action="store_true", help="英数字だけの短い形（別の PC から打ち直す・写真から起こす場合）。既定 500 文字")
    a = ap.parse_args()
    names = a.names or recent(a.hours)
    if not names:
        print("レポートが見つからない", file=sys.stderr)
        return 1
    if a.short:
        text = short_digest(names, a.limit if a.limit != 1800 else 500)
        print("\n----- short digest -----\n" + text + "\n------------------------", file=sys.stderr)
        if not a.no_clip:
            to_clipboard(text)
        return 0
    show(names, a.limit, not a.no_clip)
    return 0


if __name__ == "__main__":
    sys.exit(main())
