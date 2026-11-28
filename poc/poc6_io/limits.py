"""PoC-6 (c): 入力と出力の上限（人が送信する方式、個人版）。

入力: 架空の文章を 8,000 / 16,000 / 32,000 / 64,000 文字にして送り、最後に書いた合言葉を答えさせる。
出力: 書式 llmc/1 で、N 行（300 / 1,000 / 2,000 行）のファイルの全文を出力させ、どこで切れるかを見る。
      切れた場合は、同じチャットで 1 回だけ続きを依頼する。

使い方: .\\.venv\\Scripts\\python.exe poc6_io\\limits.py [--only input|output]
  待っている間のキー: f = 画面にエラーが出た（送信できない・回答が出ない）、s = 飛ばす、a = 貼り付けたら添付（ファイル）に変わった
結果: out\\poc6-limits-report.md
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from common6 import OUT, apply_filler, choose_filler, clear_if_ours, parse_cf_html, set_text_private, short_tid, wait_answer  # noqa: E402
import run as M  # noqa: E402
from common.report import Report  # noqa: E402
from htmlseg import segments  # noqa: E402
from protocol import parse  # noqa: E402

LINE = "これは長さを測るための架空の文章です。意味はありません。"


def ask_key(prompt_text: str) -> str:
    print(prompt_text, file=sys.stderr)
    try:
        return input("> ").strip()[:200]
    except EOFError:
        return ""


def run_input(rep: Report, sizes) -> None:
    sec = "入力の上限"
    for n in sizes:
        tid = M.new_tid()
        head = (f"このターンの ID: {tid}\nこれは入力の長さの確認です。下の架空の文章は読み飛ばしてかまいません。"
                f"最後の行の合言葉だけを「LLMC-DONE v=1 id={tid} answer=<合言葉>」の 1 行で答えてください。\n\n")
        body = []
        i = 0
        while len(head) + sum(len(x) + 1 for x in body) < n - 40:
            i += 1
            body.append(f"{i:05d} {LINE}")
        text = head + "\n".join(body) + f"\n\n合言葉: {tid}-OK\n"
        seq = set_text_private(text)
        print("\n" + "=" * 60, file=sys.stderr)
        print(f"[入力 {len(text):,} 文字] ID {short_tid(tid)}。【新しいチャット】に貼り付けて送信し、回答の「コピー」を押してください。", file=sys.stderr)
        print("  エラーで送れない・回答が出ないときは f、貼り付けで添付に変わったら a、飛ばすなら s を押してください。", file=sys.stderr)
        got = wait_answer(tid, text, want=("LLMC-DONE",), keys="fsa")
        clear_if_ours(seq)
        item = f"{len(text):,} 文字"
        if got.get("key") == "s" or "timeout" in got:
            rep.add(sec, item, "INFO", "飛ばした" if got.get("key") else "時間切れ")
        elif got.get("key") in ("f", "a"):
            msg = ask_key("画面の表示を（社内の情報を含まない範囲で）書いてください。空でもかまいません。")
            rep.add(sec, item, "NG", {"事象": "添付に変わった" if got["key"] == "a" else "エラー", "画面の表示": msg})
        else:
            t = got["text"] or ""
            rep.add(sec, item, "OK" if f"{tid}-OK" in t else "WARN",
                    {"合言葉を答えた": f"{tid}-OK" in t, "回答まで秒": got["seconds"]})
        rep.write()


def run_output(rep: Report, counts) -> None:
    sec = "出力の上限"
    for n in counts:
        path = "data/lines.txt"
        ws = OUT / "ws-limits"
        if ws.exists():
            shutil.rmtree(ws)
        tid = M.new_tid()
        task = (f"新しいファイル {path} を作ってください。中身は 1 行目から {n} 行目まで、"
                "各行を「line 0001 架空のデータ abcdefghij」の形（4 桁の行番号だけを変える）にしてください。"
                "省略せずに全部の行を出力してください。")
        sc = {"files": {}, "allow": [path], "task": task, "new_chat": True}
        ws.mkdir(parents=True)
        prompt, sha, texts = M.build_prompt(tid, sc, ws, long_rules=True)
        filler = choose_filler(texts.values())
        sent = apply_filler(prompt, filler)
        seq = set_text_private(sent)
        print("\n" + "=" * 60, file=sys.stderr)
        print(f"[出力 {n} 行] ID {short_tid(tid)}。【新しいチャット】に貼り付けて送信し、回答の「コピー」を押してください。", file=sys.stderr)
        print("  回答が途中で止まってコピーボタンが出ないときは f、飛ばすなら s を押してください。", file=sys.stderr)
        got = wait_answer(tid, sent, keys="fs")
        clear_if_ours(seq)
        item = f"{n} 行（約 {n * 27:,} 文字）"
        if got.get("key") or "timeout" in got:
            msg = ask_key("画面の様子を書いてください（途中で止まった、エラーの表示など）。") if got.get("key") == "f" else ""
            rep.add(sec, item, "NG" if got.get("key") == "f" else "INFO", {"事象": got.get("key", "時間切れ"), "画面の様子": msg})
            rep.write()
            continue
        (OUT / f"limits-{n}-response.html").write_bytes(got["html"])
        cf = parse_cf_html(got["html"])
        res = parse(None, tid, rev=M.REV, ctx_sha=sha, allowed=lambda p: True, segments=segments(cf["fragment"]))
        lines = res.files[0].lines if res.files else []
        ok_lines = sum(1 for i, x in enumerate(lines) if x.startswith(f"line {i + 1:04d} "))
        detail = {"分類": res.kind, "完成したブロック": [b.complete for b in res.files], "行数": len(lines),
                  "正しい行": ok_lines, "回答の文字数": len(got["text"] or ""), "回答まで秒": got["seconds"],
                  "省略の警告": [w for w in res.warnings if w.startswith("W_SUSPECT_ELISION")], "エラー": res.errors}
        rep.add(sec, item, "OK" if res.kind == "complete" and ok_lines == n else "NG", detail)
        rep.write()
        if res.kind == "truncated":
            tid2 = M.new_tid()
            cont = (f"llmc プロトコル: llmc/1（規則の版 {M.REV}）\nこのターンの ID: {tid2}\n{M.SHORT}\n\n# 依頼\n"
                    f"前の回答は途中で切れました（{path} の LLMC-END が無い）。{path} を、最初から全部、もう一度出力してください。\n\n"
                    f"このターンの ID: {tid2}（回答の LLMC- の行には、この ID を使ってください）")
            sent2 = apply_filler(cont, filler)
            seq = set_text_private(sent2)
            print(f"  [続きの依頼] ID {short_tid(tid2)}。【同じチャット】に貼り付けて送信し、「コピー」を押してください（f / s も使えます）。", file=sys.stderr)
            got2 = wait_answer(tid2, sent2, keys="fs")
            clear_if_ours(seq)
            if got2.get("key") or "timeout" in got2:
                rep.add(sec, item + " の続き", "INFO", got2.get("key", "時間切れ"))
            else:
                res2 = parse(None, tid2, rev=M.REV, allowed=lambda p: True, segments=segments(parse_cf_html(got2["html"])["fragment"]))
                l2 = res2.files[0].lines if res2.files else []
                rep.add(sec, item + " の続き", "OK" if res2.kind == "complete" else "NG",
                        {"分類": res2.kind, "行数": len(l2), "回答の文字数": len(got2["text"] or "")})
            rep.write()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["input", "output"])
    ap.add_argument("--sizes", default="8000,16000,32000,64000")
    ap.add_argument("--lines", default="300,1000,2000")
    a = ap.parse_args()
    rep = Report("poc6-limits", "PoC-6 (c): 入力と出力の上限")
    if a.only in (None, "input"):
        run_input(rep, [int(x) for x in a.sizes.split(",")])
    if a.only in (None, "output"):
        run_output(rep, [int(x) for x in a.lines.split(",")])
    print(f"\nレポート: {rep.write()}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
