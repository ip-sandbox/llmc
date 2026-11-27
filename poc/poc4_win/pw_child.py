"""pythonw から起動され、Playwright でヘッドレスの Chromium を開けるかを確かめる。"""
import json
import sys
import traceback

out = sys.argv[1]
res = {"ok": False}
try:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True)
        page = b.new_page()
        page.goto("data:text/html,<p id=x>ok</p>")
        res["ok"] = page.inner_text("#x") == "ok"
        res["version"] = b.version
        b.close()
except Exception as e:  # noqa: BLE001
    res["error"] = f"{type(e).__name__}: {e}"[:300]
    res["trace"] = traceback.format_exc()[-600:]
with open(out, "w", encoding="utf-8") as f:
    json.dump(res, f, ensure_ascii=False)
