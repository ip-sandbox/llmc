"""PoC-6 (a)(d): 空行の代わりの行と、コピーの HTML の忠実さ（人が送信する方式、個人版）。

書式 llmc/1 で「ファイルの最後に 1 行足し、ほかは 1 文字も変えずに出力」を依頼し、回答のコピーの HTML から取り出した中身を、
期待する中身（元 + 1 行）と比べる。空白だけの行・タブ・行末の空白・U+00A0・入れ子の言語名つきのフェンス・__init__ を含む。

    E1: 空白だけの行を含まない Markdown（代わりの行は空白 1 個になる）
    E2: 空白 1 個・2 個の行を含む YAML（代わりの行は空白 3 個になる）
    E3: 特殊な文字（全角空白、ゼロ幅、EM SPACE など）と、U+00A0 の代わりの記号「⟦U+00A0⟧」が、そのまま返るか
        （E1 で、U+00A0 は送信の時点で普通の空白に変わり、AI に届かないと分かったため）
    E4: PowerShell の「[名前]::」など（個人版で壊れた）
    E5: E4 の [ ] を ⟦ ⟧ に置き換えて出させる（AI に届いた時点で壊れているかの切り分け）
    E6: 壊れる形の規則と、代わりの記号の候補（21 行）
    E7: URL がリンクの HTML になるのは、AI に届く前か、回答か（「:」を「⟦:⟧」にして出させる）
    E8: 「[名前]」の直後の「:」を「⟦U+003A⟧」と書く規則を、AI が新しく書くコードで守るか

使い方:
  個人版（人が送信する）: .\\.venv\\Scripts\\python.exe poc6_io\\echo_fidelity.py [--only E1]
    案内に従って、Copilot の【新しいチャット】に貼り付けて送信し、回答の下の「コピー」を押す。
  組織版（自動）: .\\.venv\\Scripts\\python.exe poc6_io\\echo_fidelity.py --auto --url https://m365.cloud.microsoft/chat
    最小化した Edge で自動で送信し、同じ画面の DOM の <pre> とも比べる。
結果: out\\poc6-echo-report.md（自動は poc6-echo-auto-report.md。回答の生データは out\\poc6\\）
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
from common6 import OUT, add_sender_args, apply_filler, choose_filler, make_sender, parse_cf_html, restore_filler  # noqa: E402
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
# 公開されている類似の実装（copilot-operator）の報告: Copilot は「[名前]:」を壊す（[math]::Round → :Round）。コードブロックの中でも。
# Markdown の参照リンクの定義（[name]: url）として扱われると見られる。PowerShell の型の書き方と、Markdown・INI の形を確かめる
E4 = ("# 架空の PowerShell のスクリプト\n$x = 3.14159\n$r = [math]::Round($x, 2)\n$s = [string]::Join(',', @('a', 'b'))\n"
      "[int]$n = 5\n[Console]::OutputEncoding = [System.Text.Encoding]::UTF8\nWrite-Output \"[info]: done\"\n"
      "# 参照リンクの形\n[link]: https://example.invalid/path\n[a][b]\n[section]\nkey=value\n")
# E4 で壊れた（個人版、2026-11-28）: [math]:: → :、"[info]: done" → "done"。[link]: url と [System.Text.Encoding]:: は残った。
# E5: AI に届いた時点で壊れているか。[ を ⟦、] を ⟧ に置き換えて出させる（⟦math⟧::Round が返れば、届いた時点では壊れていない）
LB, RB = "⟦", "⟧"
# E6: 壊れる形の規則と、代わりの記号の候補。各行の末尾の「# Lnn」で行を見分ける（行頭の形を変えないため末尾に置く）
E6_LINES = [
    "$a = [math]::Round($x)", "[math]::Round($x)", "[math]:Round", "[math]: Round", "[math] ::Round", "[m]::x", "[1]::x",
    "[a_b]::x", "[a-b]::x", "[a.b]::x", "[System.Math]::Round($x)", "[math ]::Round", "[[math]]::Round", "x[info]:y",
    "\"[info]: done\"", "[info]: https://example.invalid/", "`[math]::Round`", "\\[math\\]::Round",
    "⟦U+005B⟧math]::Round", "[math⟦U+005D⟧::Round", "[math]⟦U+003A⟧:Round",
]
E6 = "# 架空の形の確認\n" + "".join(f"{x} # L{i:02d}\n" for i, x in enumerate(E6_LINES, 1))
# E7: URL が <a href=... class="fai-ChatInputEntity__text"> になった（E5・E6）。AI に届いた時点でそうなのか、回答で変わるのか。
# すべての「:」を「⟦:⟧」にして出させる（AI に HTML で届いていれば <a href="https⟦:⟧// が返る）。
# さらに、AI が自分で組み立てた URL の行を足させる（回答の側でリンクの HTML になるか）
E7 = ("# 架空の URL の形\nx https://example.invalid/path y\nx http://example.invalid/ y\nx www.example.invalid y\n"
      "x example.com y\nx a@example.invalid y\n$u = \"https://example.invalid/a?b=1\"\n<https://example.invalid/>\n")
E7_NEW = "https" + "://example.invalid/new"
# E8: 規則（spec-file-protocol 9.7）を AI が守るか。送る文脈は代わりの記号にした E4。既存の行はそのまま、新しいコードは AI が書く
PH = "⟦U+003A⟧"
E8 = re.sub(r"(\[[A-Za-z0-9_]+\]):", lambda m: m.group(1) + PH,
             E4.replace("[link]: https://example.invalid/path\n", ""))  # URL の問題（E7）と混ぜない
TASK8 = (f"規則: 「[」英数字「]」の直後に「:」を書くときは、その「:」を「{PH}」と書いてください（例: [math]{PH}:Floor）。"
         f"ファイルにある「{PH}」は変えずに書き返してください。\n"
         "送ったファイルの既存の行は 1 文字も変えずに、最後に次の 3 行の PowerShell のコードを足してください。"
         "(1) $x を [math] の Round で小数 1 桁に丸めて $y に入れる (2) [string] の Join で 'p' と 'q' を '-' でつなぎ $z に入れる "
         "(3) [Console] の OutputEncoding に [System.Text.Encoding] の UTF8 を入れる。")
ADD = "# 確認済み"
TASK7 = ("送ったファイルのすべての「:」を「⟦:⟧」に置き換えてください。次に、「https」と「//example.invalid/new」を「:」でつないだ文字列"
         f"（置き換えない）だけの行を 1 行追加し、最後に 1 行「{ADD}」を追加してください。それ以外は 1 文字も変えずに、ファイル全体を出力してください。")
TASK = (f"送ったファイルの最後に 1 行「{ADD}」を追加してください。それ以外は 1 文字も変えずに、ファイル全体を出力してください。"
        "空行・空白だけの行・行頭と行末の空白・タブ・特殊な空白もそのまま保ってください。")
TASK5 = (f"送ったファイルのすべての「[」を「{LB}」に、すべての「]」を「{RB}」に置き換え、最後に 1 行「{ADD}」を追加してください。"
         "それ以外は 1 文字も変えずに、ファイル全体を出力してください。")
CASES = {
    "E1": {"path": "docs/sample.md", "text": E1},
    "E2": {"path": "config/sample.yaml", "text": E2},
    "E3": {"path": "docs/chars.md", "text": E3},
    "E4": {"path": "scripts/sample.ps1", "text": E4},
    "E5": {"path": "scripts/sample.ps1", "text": E4, "task": TASK5,
           "want": E4.replace("[", LB).replace("]", RB)},
    "E6": {"path": "scripts/forms.ps1", "text": E6},
    "E7": {"path": "docs/urls.md", "text": E7, "task": TASK7, "want": E7.replace(":", "⟦:⟧") + E7_NEW + "\n"},
    "E8": {"path": "scripts/sample.ps1", "text": E8, "task": TASK8, "rule_check": True},
}


def rule_check(text: str, lines: list[str]) -> dict:
    """E8: 既存の行が保たれたか、足した行で代わりの記号を守ったか、消えた形（:Round など）が無いか。"""
    old = text.rstrip("\n").split("\n")
    added = lines[len(old):]
    stripped = [x for x in lines if re.search(r"(^|[=(\s]):[A-Za-z]", x)]
    raw = [x for x in added if re.search(r"\[[A-Za-z0-9_]+\]:", x)]
    return {"既存の行が同じ": lines[:len(old)] == old, "足した行": added,
            "足した行の代わりの記号の数": sum(x.count(PH) for x in added),
            "そのままの [名前]: （消える形）": raw, "消えた跡に見える行": stripped,
            "合格": lines[:len(old)] == old and not raw and not stripped and sum(x.count(PH) for x in added) >= 3}


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
    add_sender_args(ap)
    a = ap.parse_args()
    if a.auto and not a.url:
        ap.error("--auto には --url が必要")
    pre = "auto-" if a.auto else ""
    # --only のときは事例ごとの名前にする（続けて実行すると前の結果が上書きされたため）
    rep = Report(("poc6-echo-auto" if a.auto else "poc6-echo") + (f"-{a.only}" if a.only else ""),
                 "PoC-6 (a)(d): 空行の代わりの行と、コピーの HTML の忠実さ" + ("（自動）" if a.auto else ""))
    sender = make_sender(a)
    try:
        return _run(a, rep, sender, pre)
    finally:
        sender.close()


def _run(a, rep, sender, pre) -> int:
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
        sc = {"files": {c["path"]: c["text"]}, "allow": [c["path"]], "task": c.get("task", TASK), "new_chat": True}
        prompt, sha, texts = M.build_prompt(tid, sc, ws, long_rules=True)
        filler = choose_filler(texts.values())
        sent = apply_filler(prompt, filler)
        sec = f"{name}: {c['path']}"
        got = sender.ask(tid, sent, True, f"{name}、代わりの行は空白 {len(filler)} 個")
        if "timeout" in got or "error" in got:
            rep.add(sec, "回答", "NG", got.get("error", "時間切れ"))
            rep.write()
            continue
        (OUT / f"{pre}{name}-prompt.txt").write_bytes(prompt.encode("utf-8"))
        (OUT / f"{pre}{name}-response.txt").write_bytes((got["text"] or "").encode("utf-8"))
        (OUT / f"{pre}{name}-response.html").write_bytes(got["html"])
        cf = parse_cf_html(got["html"])
        rep.add(sec, "コピーの HTML", "OK" if cf["strict_utf8"] and cf["by_offset"] is not False else "WARN",
                {"送り元のホスト": cf["source_url_host"], "ヘッダの位置で切り出せた": cf["by_offset"], "厳密な UTF-8": cf["strict_utf8"],
                 **html_facts(cf["fragment"], tid)})
        res = parse(None, tid, rev=M.REV, ctx_sha=sha, allowed=lambda p: path_key(p) == path_key(c["path"]),
                    segments=segments(cf["fragment"]), ctx_text=texts, space_restore=False)
        rep.add(sec, "解析", "OK" if res.kind == "complete" else "NG", res.summary())
        pres = sender.dom_pres(tid)
        if pres is not None:  # 自動の方式: 同じ画面の DOM の <pre> と、コピーの HTML の code 区分を比べる
            from readback import compare
            codes = [t for k, t in segments(cf["fragment"]) if k == "code" and "LLMC-FILE" in t]
            dom = next((p for p in pres if "LLMC-FILE" in p["textContent"]), None)
            for how in ("textContent", "innerText"):
                cmp = compare(codes[0], dom[how].rstrip("\n")) if codes and dom else {"一致": False, "理由": "片方に無い"}
                rep.add(sec, f"DOM の {how} とコピーの HTML", "OK" if cmp["一致"] else "NG", cmp)
        if res.kind != "complete" or not res.files:
            rep.write()
            continue
        raw_lines = res.files[0].lines
        restored = restore_filler(raw_lines, filler)
        if c.get("rule_check"):
            rc = rule_check(c["text"], restored)
            rep.add(sec, "規則（⟦U+003A⟧）を守ったか", "OK" if rc["合格"] else "NG", rc)
            record[name] = {"tid": tid, "path": c["path"]}
            rep.write()
            continue
        want =(c.get("want", c["text"]).rstrip("\n") + "\n" + ADD).split("\n")
        broken = [f"{w!r} → {g!r}" for w, g in zip(want, restored) if w != g]
        if broken:  # 壊れた行をすべて（E4〜E6 の切り分けのため。短縮の要約にも出る）
            rep.add(sec, "変わった行", "NG", {"数": len(broken), "行": broken})
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
    (OUT / f"{pre}echo-record.json").write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    print(f"\nレポート: {rep.write()}", file=sys.stderr)
    from common.digest import show
    show([rep.name])
    return 0


if __name__ == "__main__":
    sys.exit(main())
