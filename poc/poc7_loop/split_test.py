"""PoC-7 (0): 1 回の回答の出力の上限を超えるファイルの書き換え。2 つの案の守られ方を比べる（spec-file-protocol 11.1）。

架空の設定ファイル（約 13,000 文字、330 行）の 3 か所の値を変える依頼を、次の 2 つの方式で行う。それぞれ新しいチャット。
  A 分割の出力: ファイル全体を部分に分けて出させる。部分ごとに 1 ターン（llmc が続きを依頼する）
  B 範囲の置き換え: 行番号つきでファイルを送り、変える範囲だけを LLMC-EDIT で出させる。各範囲の 1 行目の元の中身も書き返させて確かめる
結果を期待する中身（元 + 3 か所の変更）と比べる。

使い方:
  個人版（人が送信する）: .\\.venv\\Scripts\\python.exe poc7_loop\\split_test.py [--only A|B]
  組織版（自動）:         .\\.venv\\Scripts\\python.exe poc7_loop\\split_test.py --auto --url https://m365.cloud.microsoft/chat
結果: out\\poc7-split-report.md（自動は poc7-split-auto-report.md）。最後に貼り付け用の要約を出す
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "poc6_io"))
sys.path.insert(0, str(HERE.parent))
from common6 import OUT, add_sender_args, apply_filler, choose_filler, make_sender, parse_cf_html, response_hints  # noqa: E402
import run as M  # noqa: E402
from common.report import Report  # noqa: E402
from htmlseg import segments  # noqa: E402
from protocol import content_sha, parse_attrs  # noqa: E402

PATH = "config/big.ini"
N = 330
ORIG = "\n".join(f"key_{i:04d} = value_{i:04d}    ; 架空の設定の説明 abcdefghij" for i in range(1, N + 1)) + "\n"
EDITS = {50: "CHANGED_A", 200: "CHANGED_B", 320: "CHANGED_C"}
EXPECT = "\n".join((f"key_{i:04d} = {EDITS[i]}    ; 架空の設定の説明 abcdefghij" if i in EDITS else l)
                   for i, l in enumerate(ORIG.rstrip("\n").split("\n"), 1))
TASK = ("config/big.ini の key_0050 の値を CHANGED_A に、key_0200 の値を CHANGED_B に、key_0320 の値を CHANGED_C に変えてください。"
        "ほかの行は 1 文字も変えないでください。")
PART_MAX = 5000

RULE_A = f"""# 大きなファイルの出力（分割）
このファイルは 1 回の回答に収まらない。次の形で、部分に分けて出力する。省略はしない。
- 1 回の回答に出す部分は {PART_MAX:,} 文字まで。部分の区切りは行の境目にする。
- 部分のコードブロックの 1 行目: LLMC-FILE id=<ID> path="<相対パス>" base=<sha> part=<部分の番号（1 から）>
- 最後の部分でないときのコードブロックの最終行: LLMC-PART-END id=<ID> path="<相対パス>" part=<番号> next_line=<次の部分の最初の行の行番号>
- 最後の部分のコードブロックの最終行: LLMC-END id=<ID> path="<相対パス>"
- 最後の部分でなければ、回答の最後に LLMC-DONE ではなく LLMC-CONTINUE id=<ID> part=<番号> を書いて止める。llmc が続きを依頼する。
- 計画（LLMC-PLAN）は最初の回答にだけ書く。"""

RULE_B = """# 大きなファイルの書き換え（範囲の置き換え）
ファイル全体は出力しない。変える行の範囲だけを、次の形のコードブロックで出力する（範囲ごとに 1 つ）。
- 1 行目: LLMC-EDIT id=<ID> path="<相対パス>" base=<sha> lines=<最初の行番号>-<最後の行番号> first="<最初の行の元の中身（先頭 30 文字）>"
- 2 行目から: その範囲を置き換える新しい行（行番号の「NNNN| 」は付けない）
- 最終行: LLMC-END id=<ID> path="<相対パス>"
- 行番号は、送ったファイルの左端の番号を使う。範囲どうしは重ならないようにする。
- 計画は LLMC-PLAN id=<ID> edit="<相対パス>" と書く。"""


def code_blocks(html_raw: bytes) -> list[str]:
    return [t for k, t in segments(parse_cf_html(html_raw)["fragment"]) if k == "code"]


def head_and_tail(block: str):
    ls = block.split("\n")
    return ls[0].strip(), ls[1:-1], ls[-1].strip() if len(ls) > 1 else ""


def directive(line: str, name: str, tid: str):
    m = re.match(rf"^{name}\s+(.*)$", line.strip())
    if not m:
        return None
    a = parse_attrs(m.group(1))
    return a if a.get("id", "").upper() == tid.upper() else {"_wrong_id": a.get("id")}


def check_lines(lines: list[str]) -> dict:
    nums = [int(m.group(1)) for x in lines if (m := re.match(r"key_(\d{4}) ", x))]
    dup = len(nums) - len(set(nums))
    missing = sorted(set(range(1, N + 1)) - set(nums))
    return {"行数": len(lines), "重複した行": dup, "欠けた行": len(missing), "欠けた行の例": missing[:5],
            "順序が正しい": nums == sorted(nums)}


def ctx_numbered(text: str) -> str:
    body = "\n".join(f"{i:04d}| {l}" for i, l in enumerate(text.rstrip("\n").split("\n"), 1))
    return f'````\nLLMC-CTX path="{PATH}" sha={content_sha(text)} lines={N} numbered=1\n{body}\nLLMC-CTX-END path="{PATH}"\n````'


def prompt(tid: str, rule: str, ctx: str, task: str) -> str:
    return "\n".join([f"llmc プロトコル: llmc/1（規則の版 {M.REV}）\nこのターンの ID: {tid}\n", M.LONG, "", rule, "", "# 依頼", task, "",
                      "# 書き込みを許可するパス", f"- {PATH}", "", "# 現在のファイル（全文）", ctx, "",
                      f"このターンの ID: {tid}（回答の LLMC- の行には、この ID を使ってください）"])


def run_a(rep, sender, pre):
    sec = "A 分割の出力"
    sha = content_sha(ORIG)
    tid = M.new_tid()
    filler = choose_filler([ORIG])
    text = prompt(tid, RULE_A, M.ctx_block(PATH, ORIG), TASK)
    parts, turn, new_chat = {}, 1, True
    while turn <= 6:
        got = sender.ask(tid, apply_filler(text, filler), new_chat, f"A ターン {turn}",
                         want=("LLMC-DONE", "LLMC-CONTINUE", "LLMC-PLAN", "LLMC-FILE"))
        new_chat = False
        if "error" in got or "timeout" in got:
            rep.add(sec, f"ターン {turn}", "NG", got.get("error", "時間切れ"))
            return
        (OUT / f"{pre}split-A-{turn}.html").write_bytes(got["html"])
        blocks = code_blocks(got["html"])
        got_part, cont, done = None, None, False
        for b in blocks:
            h, body, tail = head_and_tail(b)
            a = directive(h, "LLMC-FILE", tid)
            if a and "path" in a:
                end = directive(tail, "LLMC-END", tid)
                pend = directive(tail, "LLMC-PART-END", tid)
                got_part = {"part": a.get("part"), "lines": body, "final": bool(end), "pend": pend, "base_ok": a.get("base") == sha}
            for line in b.split("\n"):
                if directive(line, "LLMC-CONTINUE", tid):
                    cont = True
                if directive(line, "LLMC-DONE", tid):
                    done = True
        info = {"文字数": len(got["text"] or ""), "秒": got["seconds"], "部分": got_part and got_part["part"],
                "部分の行数": got_part and len(got_part["lines"]), "最後の部分": got_part and got_part["final"],
                "next_line": got_part and got_part["pend"] and got_part["pend"].get("next_line"),
                "base が正しい": got_part and got_part["base_ok"], "CONTINUE": cont, "DONE": done}
        if not got_part:
            info.update(response_hints(got["text"], got["html"]))
        rep.add(sec, f"ターン {turn}", "OK" if got_part else "NG", info)
        rep.write()
        if not got_part:
            return
        parts[int(got_part["part"] or turn)] = got_part
        if got_part["final"]:
            break
        nxt = got_part["pend"].get("next_line") if got_part["pend"] else "?"
        tid = M.new_tid()
        text = (f"llmc プロトコル: llmc/1（規則の版 {M.REV}）\nこのターンの ID: {tid}\n\n# 依頼\n続きを出力してください: {PATH} の part={int(got_part['part'] or turn) + 1}"
                f"（{nxt} 行目から）。形は前と同じ（LLMC-FILE ... part=、最後の部分なら LLMC-END と LLMC-DONE、そうでなければ LLMC-PART-END と LLMC-CONTINUE）。"
                f"計画は書かない。\n\nこのターンの ID: {tid}（回答の LLMC- の行には、この ID を使ってください）")
        turn += 1
    lines = [x for k in sorted(parts) for x in parts[k]["lines"]]
    lines = ["" if x == filler else x for x in lines]
    chk = check_lines(lines)
    eq = "\n".join(lines) == EXPECT
    rep.add(sec, "連結した結果", "OK" if eq else "NG", {"一致": eq, "部分の数": len(parts), "ターン": turn, **chk,
                                                      "変更の反映": {k: any(v in x for x in lines) for k, v in EDITS.items()}})


def run_b(rep, sender, pre):
    sec = "B 範囲の置き換え"
    sha = content_sha(ORIG)
    tid = M.new_tid()
    filler = choose_filler([ORIG])
    text = prompt(tid, RULE_B, ctx_numbered(ORIG), TASK)
    got = sender.ask(tid, apply_filler(text, filler), True, "B", want=("LLMC-DONE", "LLMC-PLAN", "LLMC-EDIT"))
    if "error" in got or "timeout" in got:
        rep.add(sec, "回答", "NG", got.get("error", "時間切れ"))
        return
    (OUT / f"{pre}split-B.html").write_bytes(got["html"])
    orig = ORIG.rstrip("\n").split("\n")
    edits, problems = [], []
    for b in code_blocks(got["html"]):
        h, body, tail = head_and_tail(b)
        a = directive(h, "LLMC-EDIT", tid)
        if not a or "lines" not in a:
            continue
        m = re.match(r"^(\d+)-(\d+)$", a["lines"])
        if not m:
            problems.append(f"lines の形: {a['lines']}")
            continue
        s, e = int(m.group(1)), int(m.group(2))
        first_ok = 1 <= s <= len(orig) and orig[s - 1].startswith(a.get("first", "\0")[:30].rstrip("…").rstrip())
        end_ok = bool(directive(tail, "LLMC-END", tid))
        numbered_left = any(re.match(r"^\d{4}\| ", x) for x in body)
        edits.append({"範囲": f"{s}-{e}", "first が一致": first_ok, "終了行": end_ok, "新しい行数": len(body),
                      "行番号が残った": numbered_left, "base が正しい": a.get("base") == sha, "_s": s, "_e": e, "_body": body})
    rep.add(sec, "回答", "OK" if edits else "NG",
            {"文字数": len(got["text"] or ""), "秒": got["seconds"], "範囲の数": len(edits), "問題": problems,
             **({} if edits else response_hints(got["text"], got["html"]))})
    for ed in edits:
        rep.add(sec, f"範囲 {ed['範囲']}", "OK" if ed["first が一致"] and ed["終了行"] and not ed["行番号が残った"] else "NG",
                {k: v for k, v in ed.items() if not k.startswith("_")})
    new = list(orig)
    overlap = False
    last = None
    for ed in sorted(edits, key=lambda x: -x["_s"]):
        if last is not None and ed["_e"] >= last:
            overlap = True
        new[ed["_s"] - 1: ed["_e"]] = ["" if x == filler else x for x in ed["_body"]]
        last = ed["_s"]
    eq = "\n".join(new) == EXPECT
    rep.add(sec, "適用した結果", "OK" if eq else "NG", {"一致": eq, "範囲が重なった": overlap, **check_lines(new)})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["A", "B"])
    add_sender_args(ap)
    a = ap.parse_args()
    if a.auto and not a.url:
        ap.error("--auto には --url が必要")
    pre = "auto-" if a.auto else ""
    rep = Report("poc7-split-auto" if a.auto else "poc7-split", "PoC-7 (0): 出力の上限を超えるファイルの書き換え" + ("（自動）" if a.auto else ""))
    rep.add("条件", "ファイル", "INFO", {"文字数": len(ORIG), "行数": N, "部分の上限": PART_MAX, "規則の版": M.REV})
    sender = make_sender(a)
    try:
        if a.only in (None, "A"):
            run_a(rep, sender, pre)
            rep.write()
        if a.only in (None, "B"):
            run_b(rep, sender, pre)
    finally:
        sender.close()
    print(f"\nレポート: {rep.write()}", file=sys.stderr)
    from common.digest import show
    show([rep.name])
    return 0


if __name__ == "__main__":
    sys.exit(main())
