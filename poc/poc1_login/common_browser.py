"""PoC-1/2 共通: ブラウザの起動の組み合わせと、プロファイルの置き場所。"""
from __future__ import annotations

import os
from pathlib import Path

URL = os.environ.get("POC_URL", "https://copilot.microsoft.com/")

# 試験用: 既にあるブラウザを使う場合（llmc の開発環境での確認用）。利用者の PC では設定しない
_EXE = os.environ.get("POC_CHROMIUM_PATH")


def profile_root() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".cache")
    return Path(base) / "llmc-poc" / "profiles"


def profile_dir(browser: str) -> Path:
    """browser: 'chromium'（Playwright 同梱）または 'msedge'。ブラウザごとに別のプロファイルにする。"""
    return profile_root() / browser


# (ラベル, プロファイル, launch_persistent_context に渡す引数)
VARIANTS = {
    "chromium-headed": ("chromium", {"headless": False}),
    "chromium-headless-shell": ("chromium", {"headless": True}),
    "chromium-new-headless": ("chromium", {"headless": True, "channel": "chromium"}),
    "chromium-headless-shell-uafix": ("chromium", {"headless": True, "_uafix": True}),
    "msedge-headed": ("msedge", {"headless": False, "channel": "msedge"}),
    "msedge-headless": ("msedge", {"headless": True, "channel": "msedge"}),
}


def launch(pw, variant: str, **extra):
    browser, kw = VARIANTS[variant]
    kw = dict(kw)
    uafix = kw.pop("_uafix", False)
    if _EXE and browser == "chromium":
        kw.pop("channel", None)
        kw["executable_path"] = _EXE
    kw.update(extra)
    kw.setdefault("locale", "ja-JP")
    kw.setdefault("viewport", {"width": 1280, "height": 900})
    d = profile_dir(browser)
    d.mkdir(parents=True, exist_ok=True)
    ctx = pw.chromium.launch_persistent_context(str(d), **kw)
    if uafix:
        # ヘッドレスの UA に含まれる HeadlessChrome を Chrome に置き換えて、扱いが変わるかを見る
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        ua = page.evaluate("navigator.userAgent").replace("HeadlessChrome", "Chrome")
        ctx.close()
        kw["user_agent"] = ua
        ctx = pw.chromium.launch_persistent_context(str(d), **kw)
    return ctx
