"""PoC-6 (a)(d): 空行の代わりの行と、コピーの HTML の忠実さ（人が送信する方式、個人版）。

書式 llmc/1 で「ファイルの最後に 1 行足し、ほかは 1 文字も変えずに出力」を依頼し、回答のコピーの HTML から取り出した中身を、
期待する中身（元 + 1 行）と比べる。空白だけの行・タブ・行末の空白・U+00A0・入れ子の言語名つきのフェンス・__init__ を含む。

    E1: 空白だけの行を含まない Markdown（代わりの行は空白 1 個になる）
    E2: 空白 1 個・2 個の行を含む YAML（代わりの行は空白 3 個になる）
    E3: 特殊な文字（全角空白、ゼロ幅、EM SPACE など）と、U+00A0 の代わりの記号「⟦U+00A0⟧」が、そのまま返るか
        （E1 で、U+00A0 は送信の時点で普通の空白に変わり、AI に届かないと分かったため）

使い方: .\\.venv\\Scripts\\python.exe poc6_io\\echo_fidelity.py [--only E1]
  案内に従って、Copilot の【新しいチャット】に貼り付けて送信し、回答の下の「コピー」を押す。
結果: out\\poc6-echo-report.md（回答の生データは out\\poc6\\）
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from common6 import OUT, apply_filler, choose_filler, clear_if_ours, parse_cf_html, restore_filler, set_text_private, short_tid, wait_answer  # noqa: E402
import run as M  # noqa: E402
from common.report import Report  # noqa: E402
from htmlseg import segments  # noqa: E402
from protocol import parse, path_key  # noqa: E402

NB = " "
E1 = ("# 架空の手引き\n\n説明の行。末尾に空白 2 個  \n\tタブで始まる行\n"
      f"NBSP を含む行:[{NB}]\n名前の例: pkg/__init__.py と __main__\n\n\n"
      "```python\ndef f():\n    return 1\n\n```\n\n````text\n入れ子の 4 個のフェンス\n````\n\n最後の行\n")
E2 = "# 架空の設定\nserver:\n  workers: 4\n \n  timeout: 30\n  \n  retries: 3\n\nend: true\n"
SPECIALS = {"U+3000 全角空白": "\u3000", "U+200B ゼロ幅空白": "\u200b", "U+FEFF": "\ufeff", "U+2003 EM SPACE": "\u2003",
            "U+2028 行区切り": "\u2028", "U+00AD ソフトハイフン": "\u00ad", "U+FF5E 全角チルダ": "\uff5e", "U+301C 波ダッシュ": "\u301c"}
E3 = ("# 架空の文字の確認\n" + "".join(f"{k}:[{v}]\n" for k, v in SPECIALS.items())
      + "代わりの記号: [⟦U+00A0⟧] と [⟦U+00A0⟧⟦U+00A0⟧]\n最後の行\n")
CASES = {
    "E1": {"path": "docs/sample.md", "text": E1},
    "E2": {"path": "config/sample.yaml", "text": E2},
    "E3": {"path": "docs/chars.md", "text": E3},
}
ADD = "# 確認済み"
TASK = (f"送ったファイルの最後に 1 行「{ADD}」を追加してください。それ以外は 1 文字も変えずに、ファイル全体を出力してください。"
        "空行・空白だけの行・行頭と行末の空白・タブ・特殊な空白もそのまま保ってください。")


def classify(want: list[str], got: list[str]) -> dict:
    def kinds(lines):
        return {"空行": sum(1 for x in lines if x == ""),
                "空白だけの行": sum(1 for x in lines if x and not x.strip(" \t")),
                "タブを含む行": sum(1 for x in lines if "\t" in x),
                "行末の空白": sum(1 for x in lines if x != x.rstrip(" ") and x.strip()),
                "U+00A0 を含む行": sum(1 for x in lines if NB in x)}
    w, g = kinds(want), kinds(got)
    diff = [d for d in difflib.unified_diff(want, got, lineterm="", n=0) if not d.startswith(("---", "+++"))]
    return {"一致": want == got, "行数（期待/回答）": f"{len(want)}/{len(got)}",
            **{k: f"{w[k]}/{g[k]}" for k in w},
            "特殊な文字（期待/回答）": {k: f"{sum(x.count(v) for x in want)}/{sum(x.count(v) for x in got)}"
                                    for k, v in {**SPECIALS, "U+00A0": NB, "⟦U+00A0⟧": "⟦U+00A0⟧"}.items()
                                    if sum(x.count(v) for x in want)},
            "差分（先頭 10 行）": [repr(x) for x in diff[:10]]}


def html_facts(frag: str, tid: str) -> dict:
    pres = re.findall(r"<pre[^>]*>(.*?)</pre>", frag, re.S)
    inner = set()
    for p in pres:
        inner |= set(re.findall(r"<([a-zA-Z0-9]+)", p))
    return {"<pre> の数": len(pres), "<pre> の中の要素": sorted(inner),
            "&nbsp; の実体参照（<pre> の中）": sum(p.count("&nbsp;") for p in pres),
            "U+00A0 の文字（<pre> の中）": sum(p.count(NB) for p in pres),
            "<img> あり": "<img" in frag, "言語名の崩れの形": "<p><span></span></p><div><span>" in frag}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=sorted(CASES))
    a = ap.parse_args()
    rep = Report("poc6-echo", "PoC-6 (a)(d): 空行の代わりの行と、コピーの HTML の忠実さ")
    rep.add("条件", "規則の版", "INFO", M.REV)
    record = {}
    for name, c in CASES.items():
        if a.only and name != a.only:
            continue
        ws = OUT / f"ws-{name}"
        if ws.exists():
            shutil.rmtree(ws)
        (ws / c["path"]).parent.mkdir(parents=True, exist_ok=True)
        (ws / c["path"]).write_bytes(c["text"].encode("utf-8"))
        tid = M.new_tid()
        sc = {"files": {c["path"]: c["text"]}, "allow": [c["path"]], "task": TASK, "new_chat": True}
        prompt, sha, texts = M.build_prompt(tid, sc, ws, long_rules=True)
        filler = choose_filler(texts.values())
        sent = apply_filler(prompt, filler)
        seq = set_text_private(sent)
        sec = f"{name}: {c['path']}"
        print("\n" + "=" * 60, file=sys.stderr)
        print(f"[{name}] ID {short_tid(tid)}、{len(sent)} 文字、代わりの行は空白 {len(filler)} 個", file=sys.stderr)
        print("  Copilot で【新しいチャット】を開き、貼り付けて（Ctrl+V）送信し、回答の下の「コピー」を押してください。", file=sys.stderr)
        got = wait_answer(tid, sent)
        clear_if_ours(seq)
        if "timeout" in got:
            rep.add(sec, "回答", "NG", "時間切れ")
            continue
        (OUT / f"{name}-prompt.txt").write_bytes(prompt.encode("utf-8"))
        (OUT / f"{name}-response.txt").write_bytes((got["text"] or "").encode("utf-8"))
        (OUT / f"{name}-response.html").write_bytes(got["html"])
        cf = parse_cf_html(got["html"])
        rep.add(sec, "コピーの HTML", "OK" if cf["strict_utf8"] and cf["by_offset"] else "WARN",
                {"送り元のホスト": cf["source_url_host"], "ヘッダの位置で切り出せた": cf["by_offset"], "厳密な UTF-8": cf["strict_utf8"],
                 **html_facts(cf["fragment"], tid)})
        res = parse(None, tid, rev=M.REV, ctx_sha=sha, allowed=lambda p: path_key(p) == path_key(c["path"]),
                    segments=segments(cf["fragment"]), ctx_text=texts, space_restore=False)
        rep.add(sec, "解析", "OK" if res.kind == "complete" else "NG", res.summary())
        if res.kind != "complete" or not res.files:
            continue
        raw_lines = res.files[0].lines
        restored = restore_filler(raw_lines, filler)
        want = (c["text"].rstrip("\n") + "\n" + ADD).split("\n")
        rep.add(sec, "代わりの行の書き返し", "INFO",
                {"代わりの行（空白の数）": len(filler), "回答の中の代わりの行": sum(1 for x in raw_lines if x == filler),
                 "回答の中の空行（そのまま）": sum(1 for x in raw_lines if x == ""),
                 "回答の中のほかの空白だけの行（空白の数）": sorted({len(x) for x in raw_lines if x and not x.strip(" ") and x != filler})})
        r1 = classify(want, restored)
        rep.add(sec, "中身の比較（代わりの行を戻した後）", "OK" if r1["一致"] else "NG", r1)
        if not r1["一致"]:
            r2 = classify([x.replace(NB, " ") for x in want], [x.replace(NB, " ") for x in restored])
            rep.add(sec, "参考: U+00A0 を空白とみなした比較", "OK" if r2["一致"] else "NG", r2)
        record[name] = {"tid": tid, "path": c["path"]}
        rep.write()
    (OUT / "echo-record.json").write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    print(f"\nレポート: {rep.write()}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
