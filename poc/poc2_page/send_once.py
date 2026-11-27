"""PoC-2/2b: 架空の短い依頼を 1 回だけ送り、送信が受け付けられるかを調べる。

会話の本文はレポートに残さない（送信できたか、回答の要素が現れたか、エラーの表示があったか、だけ）。

使い方:
    python poc2_page\\send_once.py                          # 個人の Copilot（copilot.microsoft.com）
    python poc2_page\\send_once.py --url https://m365.cloud.microsoft/chat --tag org
    python poc2_page\\send_once.py --variant msedge-headed   # 画面ありで見ながら
結果: out\\poc2-send-<tag>-report.md
"""
from __future__ import annotations

import argparse
import os
import secrets
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"

ERROR_TEXTS = ("要求を完了できませんでした", "問題が発生しました", "Something went wrong",
               "couldn't complete", "上限に達しました")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", help="開く URL（既定は個人の Copilot）")
    ap.add_argument("--tag", default="personal", help="レポートの名前に付ける（personal / org など）")
    ap.add_argument("--variant", default="msedge-headless")
    ap.add_argument("--wait", type=float, default=60, help="送信後に観察する秒数")
    a = ap.parse_args()
    if a.url:
        os.environ["POC_URL"] = a.url  # common_browser が読み込まれる前に設定する

    from playwright.sync_api import sync_playwright

    from common.report import Report, first_line
    from cp import INPUT, open_copilot

    tid = "".join(secrets.choice(ALPHABET) for _ in range(6))
    msg = (f"このターンの ID: {tid}\n"
           "これは動作確認用の架空の依頼です。1+1 はいくつですか？ 1 文で答えてください。\n"
           f"このターンの ID: {tid}")

    rep = Report(f"poc2-send-{a.tag}", f"PoC-2 送信の確認（{a.tag}、{a.variant}）")
    sec = "送信"
    with sync_playwright() as pw:
        try:
            ctx, page, info = open_copilot(pw, variant=a.variant)
        except Exception as e:  # noqa: BLE001
            rep.add(sec, "画面を開く", "NG", first_line(e))
            print(rep.write())
            return 1
        rep.add(sec, "画面を開く・ログイン", "OK" if info["ready"] else "NG", info)
        if not info["ready"]:
            ctx.close()
            print(rep.write(), file=sys.stderr)
            return 1
        try:
            # 「職場 / Web」などの表示があれば記録する（組織版）
            toggles = page.evaluate("""() => [...document.querySelectorAll('main button[aria-pressed], main [role=tab], main [role=switch]')]
                .map(b => ((b.getAttribute('aria-label') || b.innerText || '').trim().slice(0, 30)) + '=' +
                          (b.getAttribute('aria-pressed') || b.getAttribute('aria-selected') || b.getAttribute('aria-checked')))""")
            rep.add(sec, "切り替えの表示（aria-pressed など）", "INFO", toggles)

            page.fill(INPUT, msg)
            page.wait_for_timeout(500)
            send = page.locator("button.fai-SendButton, button[type=submit][aria-label='送信'], button[aria-label='Send']")
            rep.add(sec, "送信ボタン", "OK" if send.count() > 0 else "NG", f"{send.count()} 個")
            send.first.click(timeout=10000)
            t0 = time.time()
            result = {"入力欄が空になった": False, "自分のメッセージ（ID を含む要素）": False,
                      "停止ボタン": False, "エラー表示": None, "セキュリティ チェック": False, "URL の変化": None}
            path0 = page.evaluate("location.pathname")
            while time.time() - t0 < a.wait:
                try:
                    st = page.evaluate("""([sel, tid, errs]) => {
                        const inp = document.querySelector(sel);
                        const ilen = inp ? inp.textContent.replace(/[\\u200b-\\u200d\\ufeff]/g, '').length : -1;
                        const main = document.querySelector('main') || document.body;
                        let mine = 0;
                        for (const el of main.querySelectorAll('*')) {
                          if (el.children.length === 0 && !el.closest('[contenteditable]') && (el.textContent || '').includes(tid)) mine++;
                        }
                        const stop = [...main.querySelectorAll('button')].some(b => /停止|Stop/i.test(b.getAttribute('aria-label') || ''));
                        const txt = main.innerText || '';
                        const err = errs.find(e => txt.includes(e)) || null;
                        const sec = [...document.querySelectorAll('[role=dialog]')].some(d => /セキュリティ|security|verify|確認/i.test(d.getAttribute('aria-label') || ''));
                        return {ilen, mine, stop, err, sec, path: location.pathname};
                    }""", [INPUT, tid, list(ERROR_TEXTS)])
                except Exception:  # noqa: BLE001  遷移中
                    page.wait_for_timeout(300)
                    continue
                el = round(time.time() - t0, 1)
                if st["ilen"] == 0 and not result["入力欄が空になった"]:
                    result["入力欄が空になった"] = el
                if st["mine"] and not result["自分のメッセージ（ID を含む要素）"]:
                    result["自分のメッセージ（ID を含む要素）"] = el
                if st["stop"] and not result["停止ボタン"]:
                    result["停止ボタン"] = el
                if st["err"] and not result["エラー表示"]:
                    result["エラー表示"] = f"{st['err']}（{el} 秒）"
                if st["sec"] and not result["セキュリティ チェック"]:
                    result["セキュリティ チェック"] = el
                if st["path"] != path0 and not result["URL の変化"]:
                    result["URL の変化"] = el
                if result["エラー表示"] or result["セキュリティ チェック"]:
                    break
                page.wait_for_timeout(300)
            sent = bool(result["入力欄が空になった"] and result["自分のメッセージ（ID を含む要素）"])
            blocked = bool(result["エラー表示"] or result["セキュリティ チェック"])
            rep.add(sec, "結果（数値は送信後の秒数）", "OK" if sent and not blocked else "NG", result)
        except Exception as e:  # noqa: BLE001
            rep.add(sec, "送信の途中", "NG", first_line(e))
        finally:
            ctx.close()
    path = rep.write()
    print(f"\nレポート: {path}\n内容を確認してから、チャットに貼ってください。", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
