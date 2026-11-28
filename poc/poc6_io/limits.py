"""PoC-6 (c): 入力と出力の上限。

入力: 架空の文章を 8,000 / 16,000 / 32,000 / 64,000 文字にして送り、最後に書いた合言葉を答えさせる。
出力: 書式 llmc/1 で、N 行（既定 300 / 1,000 / 2,000 行）のファイルの全文を出力させ、どこで切れるか・省略されるかを見る。
      切れた場合は、同じチャットで 1 回だけ続きを依頼する。

使い方:
  個人版（人が送信する）: .\\.venv\\Scripts\\python.exe poc6_io\\limits.py [--only input|output] [--lines 400,600]
    待っている間のキー: f = 画面にエラーが出た（送信できない・回答が止まった）、s = 飛ばす、a = 貼り付けたら添付に変わった
  組織版（自動）: .\\.venv\\Scripts\\python.exe poc6_io\\limits.py --auto --url https://m365.cloud.microsoft/chat
結果: out\\poc6-limits-report.md（自動は poc6-limits-auto-report.md）
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from common6 import OUT, add_sender_args, apply_filler, choose_filler, make_sender, parse_cf_html, response_hints  # noqa: E402
import run as M  # noqa: E402
from common.report import Report  # noqa: E402
from htmlseg import segments  # noqa: E402
from protocol import parse  # noqa: E402

LINE = "これは長さを測るための架空の文章です。意味はありません。"


def ask_text(prompt_text: str) -> str:
    print(prompt_text, file=sys.stderr)
    try:
        return input("> ").strip()[:200]
    except EOFError:
        return ""


def failed(rep, sec, item, got, sender) -> bool:
    """回答が得られなかった場合に記録して True を返す。"""
    if "error" in got:
        rep.add(sec, item, "NG", {"事象": got["error"]})
    elif got.get("key") == "s" or "timeout" in got:
        rep.add(sec, item, "INFO", "飛ばした" if got.get("key") else "時間切れ")
    elif got.get("key") in ("f", "a"):
        msg = ask_text("画面の表示を（社内の情報を含まない範囲で）書いてください。空でもかまいません。")
        rep.add(sec, item, "NG", {"事象": "添付に変わった" if got["key"] == "a" else "エラー・止まった", "画面の表示": msg})
    else:
        return False
    rep.write()
    return True


def run_input(rep: Report, sender, sizes) -> None:
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
        item = f"{len(text):,} 文字"
        got = sender.ask(tid, text, True, f"入力 {item}", keys="fsa", want=("LLMC-DONE",))
        if failed(rep, sec, item, got, sender):
            continue
        t = got["text"] or ""
        rep.add(sec, item, "OK" if f"{tid}-OK" in t else "WARN", {"合言葉を答えた": f"{tid}-OK" in t, "回答まで秒": got["seconds"]})
        rep.write()


def run_output(rep: Report, sender, counts, pre: str) -> None:
    sec = "出力の上限"
    path = "data/lines.txt"
    for n in counts:
        ws = OUT / "ws-limits"
        if ws.exists():
            shutil.rmtree(ws)
        ws.mkdir(parents=True)
        tid = M.new_tid()
        task = (f"新しいファイル {path} を作ってください。中身は 1 行目から {n} 行目まで、"
                "各行を「line 0001 架空のデータ abcdefghij」の形（4 桁の行番号だけを変える）にしてください。"
                "省略せずに全部の行を出力してください。")
        prompt, sha, texts = M.build_prompt(tid, {"allow": [path], "task": task}, ws, long_rules=True)
        filler = choose_filler(texts.values())
        sent = apply_filler(prompt, filler)
        item = f"{n} 行（約 {n * 27:,} 文字）"
        got = sender.ask(tid, sent, True, f"出力 {n} 行", keys="fs")
        if failed(rep, sec, item, got, sender):
            continue
        (OUT / f"{pre}limits-{n}-response.html").write_bytes(got["html"])
        res = parse(None, tid, rev=M.REV, ctx_sha=sha, allowed=lambda p: True, segments=segments(parse_cf_html(got["html"])["fragment"]))
        lines = res.files[0].lines if res.files else []
        ok_lines = sum(1 for i, x in enumerate(lines) if x.startswith(f"line {i + 1:04d} "))
        elided = [x for x in lines if x.strip() in ("...", "…")]
        detail = {"分類": res.kind, "完成したブロック": [b.complete for b in res.files], "行数": len(lines),
                  "先頭から正しく続いた行": ok_lines, "... だけの行": len(elided), "回答の文字数": len(got["text"] or ""),
                  "回答まで秒": got["seconds"], "警告": [w for w in res.warnings if w.startswith("W_SUSPECT_ELISION")], "エラー": res.errors}
        if res.kind != "complete" or elided:
            detail.update(response_hints(got["text"], got["html"]))
            detail.update(sender.response_facts())
        rep.add(sec, item, "OK" if res.kind == "complete" and ok_lines == n and not elided else "NG", detail)
        rep.write()
        if res.kind == "truncated":
            tid2 = M.new_tid()
            cont = (f"llmc プロトコル: llmc/1（規則の版 {M.REV}）\nこのターンの ID: {tid2}\n{M.SHORT}\n\n# 依頼\n"
                    f"前の回答は途中で切れました（{path} の LLMC-END が無い）。{path} を、最初から全部、もう一度出力してください。\n\n"
                    f"このターンの ID: {tid2}（回答の LLMC- の行には、この ID を使ってください）")
            got2 = sender.ask(tid2, apply_filler(cont, filler), False, f"出力 {n} 行の続き", keys="fs")
            if failed(rep, sec, item + " の続き", got2, sender):
                continue
            res2 = parse(None, tid2, rev=M.REV, allowed=lambda p: True, segments=segments(parse_cf_html(got2["html"])["fragment"]))
            l2 = res2.files[0].lines if res2.files else []
            d2 = {"分類": res2.kind, "行数": len(l2), "回答の文字数": len(got2["text"] or "")}
            if res2.kind != "complete":
                d2.update(response_hints(got2["text"], got2["html"]))
                d2.update(sender.response_facts())
            rep.add(sec, item + " の続き", "OK" if res2.kind == "complete" else "NG", d2)
            rep.write()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["input", "output"])
    ap.add_argument("--sizes", default="8000,16000,32000,64000")
    ap.add_argument("--lines", default="300,1000,2000")
    add_sender_args(ap)
    a = ap.parse_args()
    if a.auto and not a.url:
        ap.error("--auto には --url が必要")
    rep = Report("poc6-limits-auto" if a.auto else "poc6-limits", "PoC-6 (c): 入力と出力の上限" + ("（自動）" if a.auto else ""))
    sender = make_sender(a)
    try:
        if a.only in (None, "input"):
            run_input(rep, sender, [int(x) for x in a.sizes.split(",")])
        if a.only in (None, "output"):
            run_output(rep, sender, [int(x) for x in a.lines.split(",")], "auto-" if a.auto else "")
    finally:
        sender.close()
    print(f"\nレポート: {rep.write()}", file=sys.stderr)
    from common.digest import show
    show([rep.name])
    return 0


if __name__ == "__main__":
    sys.exit(main())
