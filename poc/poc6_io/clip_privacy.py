"""PoC-6 (e): クリップボードの履歴（Win+V）への除外の印の効果（Copilot を使わない）。

1. 除外の印なしで「LLMC-PRIVACY-A」を入れる
2. 除外の印あり（CanIncludeInClipboardHistory=0、CanUploadToCloudClipboard=0、ExcludeClipboardContentFromMonitorProcessing）で
   「LLMC-PRIVACY-B」を入れる
3. 利用者が Win+V の履歴を開き、A があって B が無いかを答える
4. 除外の印のあるコピーを、llmc の読み取り（read_both）が読まないことを確かめる
5. 最後にクリップボードを空にする

前提: 設定 → システム → クリップボード → 「クリップボードの履歴」をオンにしておく（オフなら、その旨を答える）。
使い方: .\\.venv\\Scripts\\python.exe poc6_io\\clip_privacy.py
結果: out\\poc6-clip-report.md
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from common6 import clear_if_ours, read_both, set_text_private  # noqa: E402
from common.report import Report  # noqa: E402


def ask(q: str) -> str:
    print(q, file=sys.stderr)
    try:
        return input("> ").strip().lower()[:100]
    except EOFError:
        return ""


def main() -> int:
    rep = Report("poc6-clip", "PoC-6 (e): クリップボードの履歴への除外の印")
    set_text_private("LLMC-PRIVACY-A（除外の印なし。架空の文字列）", private=False)
    time.sleep(1.5)  # 履歴に入る時間
    seq = set_text_private("LLMC-PRIVACY-B（除外の印あり。架空の文字列）", private=True)
    got = read_both()
    rep.add("読み取り", "除外の印のあるものを読まない", "OK" if got and got["excluded"] and got["text"] is None else "NG",
            {"除外と判定": bool(got and got["excluded"])})
    hist = ask("Win+V を押して、クリップボードの履歴を見てください。\n"
               "  A だけがある → a、A と B の両方がある → ab、履歴がオフ・どちらも無い → n と入力して Enter")
    status = {"a": "OK", "ab": "NG"}.get(hist, "INFO")
    rep.add("履歴", "Win+V に B（除外の印あり）が出ない", status,
            {"回答": {"a": "A だけ", "ab": "A と B", "n": "履歴がオフ、またはどちらも無い"}.get(hist, hist)})
    paste = ask("メモ帳などに Ctrl+V で貼り付けてください。B の文字列が貼り付けられましたか？ y / n")
    rep.add("貼り付け", "除外の印があっても、ふつうに貼り付けられる", "OK" if paste == "y" else "NG", {"回答": paste})
    rep.add("後始末", "自分の書き込みのままなら空にする", "INFO", {"空にした": clear_if_ours(seq)})
    print(f"\nレポート: {rep.write()}\n（Win+V の履歴に残った A は、不要なら履歴から削除してください）", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
