"""PoC-3（自動の方式）: 画面ありの Edge（最小化）で、書式 llmc/1 の往復を自動で確かめる。

1. 入力方法の診断（S0 の自動版）: 空行などを含む架空の中身を 3 つの入力方法で送り、そのまま返させて比べる
     fill / paste_text（貼り付けイベント、テキスト）/ paste_html（貼り付けイベント、テキスト＋HTML）
   OS のクリップボードは使わない（貼り付けイベントはページの中で作る）
2. 課題 S1・S1b・S2・S3: 1 で一致した入力方法で送り、「応答のコピー」を横取りして HTML の区分で解析し、書き込みと確認をする

送る内容はすべて架空。会話の本文はレポートに残さない（一致したか、解析の結果、確認の結果だけ）。

使い方（社内 PC、組織版）:
    $env:POC_URL = "https://m365.cloud.microsoft/chat"
    .\\.venv\\Scripts\\python.exe poc3_auto\\roundtrip.py --url $env:POC_URL
    .\\.venv\\Scripts\\python.exe poc3_auto\\roundtrip.py --url $env:POC_URL --only-s0     # 入力方法の診断だけ
結果: out\\poc3-auto-report.md
"""
from __future__ import annotations

import argparse
import os
import secrets
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
for p in (ROOT, ROOT / "manual", ROOT / "poc2_page"):
    sys.path.insert(0, str(p))

ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
COPY_BTN = "button[aria-label='応答のコピー'], button[aria-label='応答をコピー'], button[aria-label='Copy response']"
SEND_BTN = "button.fai-SendButton, button[type=submit][aria-label='送信'], button[aria-label='Send']"


def new_tid() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(6))


class Driver:
    def __init__(self, page, ctx, url):
        self.page, self.ctx, self.url = page, ctx, url

    def new_chat(self):
        from cp import INPUT
        self.page.goto(self.url, timeout=60000)
        self.page.wait_for_selector(INPUT, timeout=60000)
        self.page.wait_for_timeout(1500)

    def put(self, text: str, method: str, html_frag: str | None = None) -> int:
        from cp import INPUT
        p = self.page
        p.click(INPUT)
        p.keyboard.press("Control+A")
        p.keyboard.press("Delete")
        if method == "fill":
            p.fill(INPUT, text)
        else:
            p.evaluate("""([sel, t, h]) => { const el = document.querySelector(sel); el.focus();
                const dt = new DataTransfer(); dt.setData('text/plain', t); if (h) dt.setData('text/html', h);
                el.dispatchEvent(new ClipboardEvent('paste', {clipboardData: dt, bubbles: true, cancelable: true})); }""",
                       [INPUT, text, html_frag if method == "paste_html" else None])
        p.wait_for_timeout(800)
        return p.evaluate("(s) => document.querySelector(s).textContent.replace(/[\\u200b-\\u200d\\ufeff]/g,'').length", INPUT)

    def send_and_wait(self, timeout: float = 240) -> dict:
        p = self.page
        before = p.locator(COPY_BTN).count()
        p.locator(SEND_BTN).first.click(timeout=10000)
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                if p.locator(COPY_BTN).count() > before:
                    p.wait_for_timeout(1500)  # 操作欄が出そろうのを待つ
                    return {"ok": True, "seconds": round(time.time() - t0, 1)}
                if p.get_by_text("要求を完了できませんでした").count():
                    return {"ok": False, "error": "要求を完了できませんでした"}
            except Exception:  # noqa: BLE001  遷移中
                pass
            p.wait_for_timeout(500)
        return {"ok": False, "error": "時間切れ"}

    def copy_last(self) -> tuple[str | None, str | None]:
        p = self.page
        p.evaluate("window.__llmc.armed = true; window.__llmc.got = []")
        try:
            p.locator(COPY_BTN).last.click(timeout=10000)
            for _ in range(20):
                p.wait_for_timeout(200)
                got = p.evaluate("window.__llmc.got")
                if got:
                    p.wait_for_timeout(500)
                    got = p.evaluate("window.__llmc.got")
                    break
        finally:
            p.evaluate("window.__llmc.armed = false")
        text = next((g["v"] for g in got if g["kind"] in ("write:text/plain", "writeText") or g["kind"].endswith("text/plain")), None)
        html = next((g["v"] for g in got if g["kind"].endswith("text/html")), None)
        return text, html


def run_s0(drv: Driver, rep) -> str | None:
    from probe_input import SAMPLE, compare, extract, prompt_for
    from run import to_clipboard_html
    sec = "S0: 入力方法の診断（自動）"
    best = None
    for method in ("fill", "paste_text", "paste_html"):
        tid = new_tid()
        prompt = prompt_for(tid, SAMPLE)
        try:
            drv.new_chat()
            n = drv.put(prompt, method, to_clipboard_html(prompt))
            w = drv.send_and_wait()
            if not w["ok"]:
                rep.add(sec, method, "NG", {"入力の文字数": n, **w})
                continue
            text, html = drv.copy_last()
            if not text and not html:
                rep.add(sec, method, "NG", "コピーを横取りできなかった")
                continue
            body, how = extract(text or "", html)
            c = compare(SAMPLE, body)
            c.pop("差分（先頭 12 行）") if c["一致"] else None
            rep.add(sec, method, "OK" if c["一致"] else "NG",
                    {"入力の文字数（送る本文）": f"{n}（{len(prompt)}）", "回答まで秒": w["seconds"], "取り出し": how,
                     "HTML あり": bool(html), **c})
            if c["一致"] and best is None:
                best = method
        except Exception as e:  # noqa: BLE001
            from common.report import first_line
            rep.add(sec, method, "NG", first_line(e))
        rep.write()
    rep.add(sec, "採用する入力方法", "OK" if best else "NG", best)
    return best


def run_scenarios(drv: Driver, rep, method: str) -> None:
    import run as M
    from scenarios import SCENARIOS
    ws = M.OUT_DIR / "poc3-auto-workspace"
    for name in ("S1", "S1b", "S2", "S3"):
        sc = SCENARIOS[name]
        sec = f"{name}: {sc['title']}"
        try:
            if sc["new_chat"]:
                if ws.exists():
                    shutil.rmtree(ws)
                for p, t in sc["files"].items():
                    (ws / p).parent.mkdir(parents=True, exist_ok=True)
                    (ws / p).write_bytes(t.encode("utf-8"))
                drv.new_chat()
            tid = new_tid()
            prompt, sha, ctx_texts = M.build_prompt(tid, sc, ws, long_rules=sc["new_chat"])
            n = drv.put(prompt, method, M.to_clipboard_html(prompt))
            w = drv.send_and_wait()
            if not w["ok"]:
                rep.add(sec, "送信と回答", "NG", w)
                continue
            text, html = drv.copy_last()
            allowed = {M.path_key(p) for p in sc["allow"]}
            res, how = M.parse_response(text or "", html, tid, sha, ctx_texts, allowed)
            rep.add(sec, "解析", "OK" if res.kind == "complete" else "NG",
                    {"入力の文字数（送る本文）": f"{n}（{len(prompt)}）", "回答まで秒": w["seconds"], "形": how, **res.summary()})
            if res.kind == "complete":
                rep.add(sec, "書き込み", "OK", M.apply(res, ws))
                checks = sc["check"](ws, res)
                rep.add(sec, "内容の確認", "OK" if all(checks.values()) else "WARN", checks)
        except Exception as e:  # noqa: BLE001
            from common.report import first_line
            rep.add(sec, "実行", "NG", first_line(e))
        rep.write()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--variant", default="msedge-headed")
    ap.add_argument("--no-minimize", action="store_true")
    ap.add_argument("--only-s0", action="store_true")
    ap.add_argument("--method", choices=["fill", "paste_text", "paste_html"], help="S0 を飛ばして、この入力方法で課題を行う")
    a = ap.parse_args()
    os.environ["POC_URL"] = a.url
    from playwright.sync_api import sync_playwright

    from common.report import Report
    from cp import CLIP_HOOK, open_copilot
    rep = Report("poc3-auto", f"PoC-3 書式の往復（自動、{a.variant}）")
    with sync_playwright() as pw:
        ctx, page, info = open_copilot(pw, variant=a.variant, init_script=CLIP_HOOK)
        rep.add("準備", "画面を開く・ログイン", "OK" if info["ready"] else "NG", info)
        if not info["ready"]:
            print(rep.write(), file=sys.stderr)
            return 1
        if not a.no_minimize and a.variant.endswith("headed"):
            cdp = ctx.new_cdp_session(page)
            wid = cdp.send("Browser.getWindowForTarget")["windowId"]
            cdp.send("Browser.setWindowBounds", {"windowId": wid, "bounds": {"windowState": "minimized"}})
        drv = Driver(page, ctx, a.url)
        method = a.method or run_s0(drv, rep)
        if method and not a.only_s0:
            run_scenarios(drv, rep, method)
        ctx.close()
    print(f"\nレポート: {rep.write()}\n内容を確認してから、チャットに貼ってください。", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
