"""画面を開いたときの状態を、本文や個人情報を記録せずに調べる。"""
from __future__ import annotations

import re
import time
from urllib.parse import urlparse

SIGNIN = re.compile(r"サインイン|Sign in|ログイン|Log in", re.I)
CHALLENGE = re.compile(r"人間であることを確認|ロボットではありません|verify you are human|are you a robot|captcha", re.I)
LOGIN_HOSTS = ("login.live.com", "login.microsoftonline.com", "account.live.com", "login.microsoft.com")


def page_state(ctx, page, wait_s: float = 30) -> dict:
    """ログインしているか、チャットの入力欄があるか、ボット対策の表示があるか。"""
    t0 = time.time()
    textbox = False
    while time.time() - t0 < wait_s:
        try:
            if page.get_by_role("textbox").count() > 0:
                textbox = True
                break
        except Exception:  # noqa: BLE001
            pass
        time.sleep(1)
    host = urlparse(page.url).hostname or ""
    try:
        body = page.inner_text("body", timeout=5000)
    except Exception:  # noqa: BLE001
        body = ""
    signin_buttons = 0
    try:
        for role in ("button", "link"):
            loc = page.get_by_role(role, name=SIGNIN)
            for i in range(min(loc.count(), 10)):
                if loc.nth(i).is_visible():
                    signin_buttons += 1
    except Exception:  # noqa: BLE001
        pass
    frames = [urlparse(f.url).hostname or "" for f in page.frames if f != page.main_frame]
    cookies = ctx.cookies()
    by_domain: dict[str, int] = {}
    for c in cookies:
        d = c.get("domain", "").lstrip(".")
        key = next((k for k in ("live.com", "microsoft.com", "microsoftonline.com", "bing.com") if d.endswith(k)), "その他")
        by_domain[key] = by_domain.get(key, 0) + 1
    try:
        ua = page.evaluate("navigator.userAgent")
        webdriver = page.evaluate("navigator.webdriver")
    except Exception:  # noqa: BLE001
        ua, webdriver = "", None
    return {
        "url_host": host,
        "ログイン画面へ転送": host in LOGIN_HOSTS,
        "入力欄（role=textbox）": textbox,
        "見えているサインインのボタン・リンクの数": signin_buttons,
        "ボット対策らしい表示": bool(CHALLENGE.search(body)),
        "iframe のホスト": sorted(set(h for h in frames if h))[:8],
        "cookie の数（ドメイン別）": by_domain,
        "UA に HeadlessChrome": "HeadlessChrome" in ua,
        "navigator.webdriver": webdriver,
        "待った秒数": round(time.time() - t0, 1),
    }


def verdict(st: dict) -> str:
    if st["ログイン画面へ転送"]:
        return "NG"
    if st["ボット対策らしい表示"] or not st["入力欄（role=textbox）"]:
        return "NG"
    if st["見えているサインインのボタン・リンクの数"] > 0:
        return "WARN"  # 入力欄はあるが、ログインしていない（未ログインでも使える状態）可能性
    return "OK"
