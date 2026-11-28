"""人が送信する方式の PoC。

llmc がプロンプトをクリップボードに入れる → 利用者が Copilot に貼り付けて送信し、回答の「コピー」を押す
→ llmc がクリップボードを見張って回答を拾い、解析して作業用のフォルダに書き込む。

使い方（PowerShell）:
    .\\.venv\\Scripts\\python.exe manual\\run.py                # S1 → S1b → S2 → S3
    .\\.venv\\Scripts\\python.exe manual\\run.py --only S2
    .\\.venv\\Scripts\\python.exe manual\\run.py --no-clipboard  # ファイル経由（out\\manual\\prompt.txt と response.txt）
結果: out\\manual\\report.md（回答の全文は out\\manual\\<課題>-response-*.txt）
"""
from __future__ import annotations

import argparse
import json
import secrets
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
from common.report import OUT_DIR, Report  # noqa: E402
from protocol import content_sha, parse, path_key  # noqa: E402
from rules import LONG, REV, SHORT  # noqa: E402
from scenarios import SCENARIOS  # noqa: E402

ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
WORK = OUT_DIR / "manual"
MAX_CONTINUE = 2


def new_tid() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(6))


def fence_for(text: str) -> str:
    longest = 0
    run = 0
    for ch in text:
        run = run + 1 if ch == "`" else 0
        longest = max(longest, run)
    return "`" * max(4, longest + 1)


def ctx_block(path: str, text: str) -> str:
    f = fence_for(text)
    lines = text.rstrip("\n").count("\n") + 1 if text else 0
    return f'{f}\nLLMC-CTX path="{path}" sha={content_sha(text)} lines={lines}\n{text.rstrip(chr(10))}\nLLMC-CTX-END path="{path}"\n{f}'


PASTE = "space"  # html: テキスト＋HTML（S0 で一字一句届いた） / space: 空行を空白 1 文字に / text: テキストのみ


def to_clipboard_html(prompt: str) -> str:
    """プロンプトを HTML の断片にする。```` で囲んだ部分は（フェンスの行も含めて）<pre>、それ以外は段落（S0 の方式 C）。
    フェンスの行を <pre> から外すと、AI がフェンスを目にせず、回答でコードブロックを使わなくなった（個人版 PoC）。"""
    import html as H
    import re as R
    out, buf, code, fence = [], [], None, None
    for line in prompt.split("\n"):
        if code is None:
            m = R.match(r"^(`{4,})", line)
            if m:
                if buf:
                    out.append("<p>" + "<br>".join(H.escape(x) for x in buf) + "</p>")
                    buf = []
                code, fence = [line], m.group(1)  # フェンスの行も <pre> に含め、AI に見えるようにする
            else:
                buf.append(line)
        else:
            if line == fence:
                code.append(line)
                out.append("<pre><code>" + H.escape("\n".join(code)) + "</code></pre>")
                code = None
            else:
                code.append(line)
    if buf:
        out.append("<p>" + "<br>".join(H.escape(x) for x in buf) + "</p>")
    return "".join(out)


def put_prompt(prompt: str) -> None:
    import clip
    if PASTE == "html":
        clip.set_text_and_html(prompt, to_clipboard_html(prompt))
    elif PASTE == "space":
        clip.set_text("\n".join(" " if x == "" else x for x in prompt.split("\n")))
    else:
        clip.set_text(prompt)


def build_prompt(tid: str, sc: dict, ws: Path, long_rules: bool, extra: str = "") -> tuple[str, dict, dict]:
    sha = {}
    texts = {}
    blocks = []
    for p in sc["allow"]:
        f = ws / p
        if f.exists():
            t = f.read_text(encoding="utf-8")
            sha[path_key(p)] = content_sha(t)
            texts[path_key(p)] = t
            blocks.append(ctx_block(p, t))
    head = f"llmc プロトコル: llmc/1（規則の版 {REV}）\nこのターンの ID: {tid}\n"
    body = [head, LONG if long_rules else SHORT, "", "# 依頼", extra or sc["task"], "",
            "# 書き込みを許可するパス", *[f"- {p}" for p in sc["allow"]], "",
            "# 現在のファイル（全文）", *blocks, "",
            f"このターンの ID: {tid}（回答の LLMC- の行には、この ID を使ってください）"]
    return "\n".join(body), sha, texts


def wait_response(tid: str, use_clip: bool, timeout: float = 1800) -> tuple[str, str | None] | None:
    if not use_clip:
        resp = WORK / "response.txt"
        if resp.exists():
            resp.unlink()
        print(f"  回答を {resp} に保存してください（UTF-8）。", file=sys.stderr)
        t0 = time.time()
        while time.time() - t0 < timeout:
            if resp.exists():
                time.sleep(0.5)
                return resp.read_text(encoding="utf-8-sig"), None
            time.sleep(0.5)
        return None
    import clip
    seq = clip.sequence()
    t0 = time.time()
    while time.time() - t0 < timeout:
        time.sleep(0.4)
        s = clip.sequence()
        if s == seq:
            continue
        seq = s
        try:
            t = clip.get_text()
        except OSError:
            continue
        if t and tid.upper() in t.upper() and "LLMC-CTX path=" not in t:
            try:
                h = clip.get_html()
            except OSError:
                h = None
            return t, h
        if t:
            print("  （ID を含まないコピーを無視しました）", file=sys.stderr)
    return None


def parse_response(text, html, tid, sha, ctx_texts, allowed):
    """HTML（区分）があればそれで解析する。無ければフェンスの無いコピーのテキストとして解析する。"""
    ok = (lambda p: path_key(p) in allowed)
    sr = PASTE == "space"
    if html:
        from htmlseg import segments
        return parse(None, tid, rev=REV, ctx_sha=sha, allowed=ok, segments=segments(html), ctx_text=ctx_texts, space_restore=sr), "HTML の区分"
    plain = text.count("```") == 0 or "LLMC-PLAN" in text.split("```")[0]
    return parse(text, tid, rev=REV, ctx_sha=sha, allowed=ok, plain_copy=plain, ctx_text=ctx_texts, space_restore=sr), \
        ("テキスト（フェンスなしのコピー）" if plain else "テキスト")


def apply(res, ws: Path) -> list[str]:
    """PoC 用の簡易な書き込み（UTF-8、元の改行を保つ）。全件を検証済みの前提。"""
    done = []
    for b in res.files:
        f = ws / b.path
        nl = "\n"
        if f.exists() and b"\r\n" in f.read_bytes():
            nl = "\r\n"
        text = b.text.replace("\n", nl)
        if not text.endswith(nl):
            text += nl
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(text.encode("utf-8"))
        done.append(f"write {b.path}")
    for p in res.deletes:
        (ws / p).unlink(missing_ok=True)
        done.append(f"delete {p}")
    return done


def shape(text: str) -> dict:
    """コピーで取れたテキストの形（生の Markdown か）。"""
    lines = text.splitlines()
    return {"文字数": len(text), "行数": len(lines),
            "フェンスの行": sum(1 for l in lines if l.lstrip().startswith(("```", "~~~"))),
            "見出しの行（#）": sum(1 for l in lines if l.startswith("#")),
            "CRLF を含む": "\r\n" in text}


def run_scenario(name: str, sc: dict, ws: Path, rep: Report, use_clip: bool) -> None:
    sec = f"{name}: {sc['title']}"
    tid = new_tid()
    allowed = {path_key(p) for p in sc["allow"]}
    prompt, sha, ctx_texts = build_prompt(tid, sc, ws, long_rules=sc["new_chat"])
    pending = {}
    deletes: dict[str, str] = {}
    plan_all = None
    extra = ""
    for attempt in range(MAX_CONTINUE + 1):
        (WORK / f"{name}-prompt-{attempt}.txt").write_bytes(prompt.encode("utf-8"))
        print("\n" + "=" * 60, file=sys.stderr)
        print(f"[{sec}] 試行 {attempt + 1}（ID {tid}、{len(prompt)} 文字）", file=sys.stderr)
        if sc["new_chat"] and attempt == 0:
            print("  Copilot で【新しいチャット】を開いてください。", file=sys.stderr)
        else:
            print("  Copilot の【同じチャット】に続けて送ってください。", file=sys.stderr)
        if use_clip:
            put_prompt(prompt)
            print("  プロンプトをクリップボードに入れました。貼り付けて送信し、回答の下の「コピー」を押してください。",
                  file=sys.stderr)
        else:
            print(f"  プロンプト: {WORK / f'{name}-prompt-{attempt}.txt'}", file=sys.stderr)
        t0 = time.time()
        got = wait_response(tid, use_clip)
        elapsed = round(time.time() - t0, 1)
        if got is None:
            rep.add(sec, f"試行 {attempt + 1}", "NG", "回答を受け取れなかった（時間切れ）")
            return
        text, html = got
        # テキストモードで書くと CRLF が \r\r\n になるので、バイト列で保存する
        (WORK / f"{name}-response-{attempt}.txt").write_bytes(text.encode("utf-8"))
        if html:
            (WORK / f"{name}-response-{attempt}.html").write_bytes(html.encode("utf-8"))
        res, how = parse_response(text, html, tid, sha, ctx_texts, allowed)
        rep.add(sec, f"試行 {attempt + 1}: 受け取ったテキストの形", "INFO",
                {**shape(text), "HTML あり": bool(html), "解析に使った形": how, "所要秒": elapsed})
        rep.add(sec, f"試行 {attempt + 1}: 解析", "OK" if res.kind == "complete" else
                ("WARN" if res.kind == "truncated" else "NG"), res.summary())
        if plan_all is None and res.plan:
            plan_all = res.plan
        for b in res.files:
            if b.complete:
                pending[path_key(b.path)] = b
        deletes.update({path_key(p): p for p in res.deletes})
        if res.kind == "complete":
            break
        if res.kind != "truncated" or not plan_all:
            rep.add(sec, "結果", "NG", "形式違反のため書き込まない")
            return
        remaining = [p for op, p in plan_all if path_key(p) not in pending and path_key(p) not in deletes]
        tid = new_tid()
        extra = ("前の回答は途中で切れました。次の項目だけを、同じ書式で（計画から）出し直してください: "
                 + ", ".join(remaining))
        prompt, _, _ = build_prompt(tid, {**sc, "task": extra}, ws, long_rules=False)
    else:
        rep.add(sec, "結果", "NG", "続きの依頼の上限に達したため書き込まない")
        return

    from types import SimpleNamespace
    done = apply(SimpleNamespace(files=list(pending.values()), deletes=list(deletes.values())), ws)
    rep.add(sec, "書き込み", "OK", done)
    checks = sc["check"](ws, res)
    rep.add(sec, "内容の確認", "OK" if all(checks.values()) else "WARN", checks)


def replay() -> int:
    """保存したプロンプトと回答から、解析と書き込みをやり直す（Copilot には接続しない）。"""
    import re
    rep = Report("manual-replay", "人が送信する方式の PoC（保存した回答の再解析）")
    ws = WORK / "replay-workspace"
    for n in ["S1", "S1b", "S2", "S3"]:
        sc = SCENARIOS[n]
        pf, rf = WORK / f"{n}-prompt-0.txt", WORK / f"{n}-response-0.txt"
        if not (pf.exists() and rf.exists()):
            continue
        prompt = pf.read_bytes().decode("utf-8")
        tid = re.search(r"このターンの ID: (\w+)", prompt).group(1)
        # AI が見たのと同じ状態にする: プロンプトの LLMC-CTX から作業用のフォルダと sha を作り直す
        if ws.exists():
            shutil.rmtree(ws)
        sha, ctx_texts = {}, {}
        for m in re.finditer(r'LLMC-CTX path="([^"]+)" sha=(\w+)[^\n]*\n(.*?)\nLLMC-CTX-END path="\1"', prompt, re.S):
            path, h, body = m.group(1), m.group(2), m.group(3) + "\n"
            (ws / path).parent.mkdir(parents=True, exist_ok=True)
            (ws / path).write_bytes(body.encode("utf-8"))
            sha[path_key(path)] = h
            ctx_texts[path_key(path)] = body
            if content_sha(body) != h:
                rep.add(n, f"sha の再計算 {path}", "WARN", f"プロンプト {h} / 再計算 {content_sha(body)}")
        raw = rf.read_bytes().decode("utf-8-sig").replace("\r\r\n", "\n")  # 以前の保存の誤りを戻す
        hf = rf.with_suffix(".html")
        html = hf.read_bytes().decode("utf-8") if hf.exists() else None
        allowed = {path_key(p) for p in sc["allow"]}
        res, how = parse_response(raw, html, tid, sha, ctx_texts, allowed)
        sec = f"{n}: {sc['title']}"
        rep.add(sec, "解析", "OK" if res.kind == "complete" else "NG", {"形": how, **res.summary()})
        if res.kind == "complete":
            rep.add(sec, "書き込み", "OK", apply(res, ws))
            checks = sc["check"](ws, res)
            rep.add(sec, "内容の確認", "OK" if all(checks.values()) else "WARN", checks)
    print(rep.write(), file=sys.stderr)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=sorted(SCENARIOS))
    ap.add_argument("--no-clipboard", action="store_true")
    ap.add_argument("--paste", choices=["html", "space", "text"], default="space",
                    help="プロンプトの貼り付け方（既定 space: 空行を空白 1 文字の行にしてテキストで貼る。"
                         "html はファイルの中身は崩れないが、AI がコードブロックを使わなくなった）")
    ap.add_argument("--replay", action="store_true", help="保存した回答（out\\manual\\*-response-*.txt）をもう一度解析して書き込む")
    a = ap.parse_args()
    if a.replay:
        return replay()
    global PASTE
    PASTE = a.paste
    WORK.mkdir(parents=True, exist_ok=True)
    ws = WORK / "workspace"
    names = [a.only] if a.only else ["S1", "S1b", "S2", "S3"]
    if a.only == "S1b":
        names = ["S1", "S1b"]
    rep = Report("manual", "人が送信する方式の PoC（個人の Copilot）")
    rep.add("条件", "規則の版", "INFO", REV)
    rep.add("条件", "貼り付け方", "INFO", a.paste)
    for n in names:
        sc = SCENARIOS[n]
        if sc["new_chat"]:
            if ws.exists():
                shutil.rmtree(ws)
            for p, t in sc["files"].items():
                (ws / p).parent.mkdir(parents=True, exist_ok=True)
                (ws / p).write_bytes(t.encode("utf-8"))
        try:
            run_scenario(n, sc, ws, rep, not a.no_clipboard)
        except KeyboardInterrupt:
            rep.add(n, "中断", "SKIP", "利用者が中断")
            break
        path = rep.write()
    print(f"\nレポート: {path}", file=sys.stderr)
    (WORK / "summary.json").write_text(json.dumps(rep.items, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
