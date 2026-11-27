"""PoC-0: 環境の診断（H-10, H-11）。

使い方（venv を有効にした PowerShell か cmd で）:
    python poc0_env\\check_env.py            # すべて
    python poc0_env\\check_env.py --no-browser
結果: poc\\out\\poc0-report.md（チャットに貼る）
"""
from __future__ import annotations

import argparse
import ctypes
import importlib.metadata
import locale
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
from common.report import Report, first_line, is_windows  # noqa: E402


def check_python(rep: Report) -> None:
    sec = "Python"
    rep.add(sec, "版", "INFO", f"{platform.python_version()} {platform.architecture()[0]} {platform.python_implementation()}")
    in_venv = sys.prefix != sys.base_prefix
    rep.add(sec, "venv の中で実行", "OK" if in_venv else "WARN", in_venv)
    rep.add(sec, "実行ファイル", "INFO", sys.executable)
    rep.add(sec, "UTF-8 モード", "INFO", f"sys.flags.utf8_mode={sys.flags.utf8_mode}")
    rep.add(sec, "ロケールの文字コード", "INFO", locale.getpreferredencoding(False))
    rep.add(sec, "ファイルシステムの文字コード", "INFO", sys.getfilesystemencoding())
    for name in ("stdin", "stdout", "stderr"):
        st = getattr(sys, name)
        rep.add(sec, f"{name} の文字コード", "INFO",
                f"{getattr(st, 'encoding', None)}（端末: {st.isatty() if hasattr(st, 'isatty') else '?'}）")
    for k in ("PYTHONUTF8", "PYTHONIOENCODING", "PYTHONLEGACYWINDOWSSTDIO"):
        rep.add(sec, f"環境変数 {k}", "INFO", os.environ.get(k, "（未設定）"))


def check_console(rep: Report) -> None:
    sec = "コンソールとコードページ"
    if not is_windows():
        rep.add(sec, "全体", "SKIP", "Windows 以外")
        return
    k32 = ctypes.windll.kernel32
    rep.add(sec, "GetACP（ANSI）", "INFO", k32.GetACP())
    rep.add(sec, "GetOEMCP", "INFO", k32.GetOEMCP())
    rep.add(sec, "GetConsoleCP（入力）", "INFO", k32.GetConsoleCP())
    rep.add(sec, "GetConsoleOutputCP（出力）", "INFO", k32.GetConsoleOutputCP())
    try:
        out = subprocess.run("cmd.exe /d /c chcp", capture_output=True, timeout=20).stdout
        rep.add(sec, "cmd の chcp", "INFO", out.decode("ascii", "replace").strip())
    except Exception as e:  # noqa: BLE001
        rep.add(sec, "cmd の chcp", "NG", first_line(e))
    # 端末の種類（Windows Terminal か従来のコンソールか）
    rep.add(sec, "Windows Terminal", "INFO", "はい" if os.environ.get("WT_SESSION") else "いいえ（または不明）")


def check_powershell(rep: Report) -> None:
    sec = "PowerShell"
    if not is_windows():
        rep.add(sec, "全体", "SKIP", "Windows 以外")
        return
    script = ("$r = [ordered]@{}; "
              "$r.version = $PSVersionTable.PSVersion.ToString(); "
              "$r.edition = $PSVersionTable.PSEdition; "
              "$r.OutputEncoding = $OutputEncoding.WebName; "
              "$r.ConsoleOutputEncoding = [Console]::OutputEncoding.WebName; "
              "$r.ConsoleInputEncoding = [Console]::InputEncoding.WebName; "
              "$r.ProfileExists = (Test-Path $PROFILE); "
              "$r.OutFileDefault = [string]$PSDefaultParameterValues['Out-File:Encoding']; "
              "$r.ExecutionPolicy = (Get-ExecutionPolicy -List | ForEach-Object { \"$($_.Scope)=$($_.ExecutionPolicy)\" }) -join ', '; "
              "$r.LanguageMode = $ExecutionContext.SessionState.LanguageMode.ToString(); "
              "$r | ConvertTo-Json -Compress")
    import base64
    import json
    try:
        cp = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand",
                             base64.b64encode(script.encode("utf-16-le")).decode()],
                            capture_output=True, timeout=60)
        data = json.loads(cp.stdout.decode("utf-8", "replace").strip() or "{}")
        for k, v in data.items():
            rep.add(sec, k, "INFO", v)
        if data.get("LanguageMode") and data["LanguageMode"] != "FullLanguage":
            rep.add(sec, "言語モードの制限", "WARN", "制約付きの言語モード。プロファイルでの設定が使えない可能性")
    except Exception as e:  # noqa: BLE001
        rep.add(sec, "情報の取得", "NG", first_line(e))
    rep.add(sec, "pwsh（PowerShell 7）の有無", "INFO", bool(shutil.which("pwsh")))


def check_system(rep: Report) -> None:
    sec = "システム"
    if is_windows():
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\FileSystem") as k:
                v, _ = winreg.QueryValueEx(k, "LongPathsEnabled")
            rep.add(sec, "長いパスの有効化（LongPathsEnabled）", "INFO", v)
        except Exception as e:  # noqa: BLE001
            rep.add(sec, "長いパスの有効化（LongPathsEnabled）", "INFO", f"読めない: {first_line(e)}")
        is_admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
        rep.add(sec, "管理者として実行中", "WARN" if is_admin else "OK",
                "管理者で実行している（通常の権限で実行してほしい）" if is_admin else "いいえ")
    lad = os.environ.get("LOCALAPPDATA")
    if lad:
        try:
            d = Path(tempfile.mkdtemp(prefix="llmc-poc-", dir=lad))
            (d / "t.txt").write_bytes(b"x")
            shutil.rmtree(d)
            rep.add(sec, "%LOCALAPPDATA% に書けるか", "OK", "はい")
        except Exception as e:  # noqa: BLE001
            rep.add(sec, "%LOCALAPPDATA% に書けるか", "NG", first_line(e))
    for k in ("OneDrive", "OneDriveCommercial", "OneDriveConsumer"):
        if os.environ.get(k):
            rep.add(sec, f"{k} の設定", "INFO", "あり")
    here_od = any(os.environ.get(k) and str(HERE).lower().startswith(os.environ[k].lower())
                  for k in ("OneDrive", "OneDriveCommercial", "OneDriveConsumer"))
    rep.add(sec, "この PoC は OneDrive の配下にあるか", "INFO", here_od)
    proxies = [k for k in os.environ if k.lower() in ("http_proxy", "https_proxy", "no_proxy", "all_proxy")]
    rep.add(sec, "プロキシの環境変数", "INFO", ", ".join(sorted(proxies)) or "なし")


def check_packages(rep: Report) -> None:
    sec = "パッケージ"
    try:
        cp = subprocess.run([sys.executable, "-m", "pip", "--version"], capture_output=True, timeout=60)
        rep.add(sec, "pip", "OK" if cp.returncode == 0 else "NG", cp.stdout.decode("utf-8", "replace").split(" from ")[0])
    except Exception as e:  # noqa: BLE001
        rep.add(sec, "pip", "NG", first_line(e))
    for pkg in ("playwright", "pywin32", "PyYAML", "textual", "prompt_toolkit", "rich"):
        try:
            rep.add(sec, pkg, "INFO", importlib.metadata.version(pkg))
        except importlib.metadata.PackageNotFoundError:
            rep.add(sec, pkg, "WARN" if pkg == "playwright" else "INFO", "未導入")


def check_browsers(rep: Report) -> None:
    """H-11: Playwright でブラウザを起動できるか（ログインはしない）。"""
    sec = "ブラウザの起動（H-11）"
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        rep.add(sec, "全体", "SKIP", "playwright が未導入（pip install playwright → python -m playwright install chromium）")
        return
    variants = [
        ("同梱 Chromium・ヘッドレス（既定）", {"headless": True}),
        ("同梱 Chromium・新しいヘッドレス（channel=chromium）", {"headless": True, "channel": "chromium"}),
        ("Edge・ヘッドレス（channel=msedge）", {"headless": True, "channel": "msedge"}),
    ]
    with sync_playwright() as pw:
        for label, kw in variants:
            try:
                b = pw.chromium.launch(**kw)
                try:
                    page = b.new_page()
                    page.goto("data:text/html,<p id=x>ok</p>")
                    ua = page.evaluate("navigator.userAgent")
                    ok = page.inner_text("#x") == "ok"
                    rep.add(sec, label, "OK" if ok else "NG",
                            f"版 {b.version}、UA に HeadlessChrome を含む: {'HeadlessChrome' in ua}")
                finally:
                    b.close()
            except Exception as e:  # noqa: BLE001
                rep.add(sec, label, "NG", first_line(e))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--no-pipes", action="store_true")
    a = ap.parse_args()
    rep = Report("poc0", "PoC-0 環境の診断")
    check_python(rep)
    check_console(rep)
    check_powershell(rep)
    check_system(rep)
    check_packages(rep)
    if not a.no_browser:
        check_browsers(rep)
    if not a.no_pipes:
        if is_windows():
            import pipes as pipe_tests
            pipe_tests.run_all(rep)
        else:
            rep.add("パイプとリダイレクト（H-10）", "全体", "SKIP", "Windows 以外")
    path = rep.write()
    print(f"\nレポート: {path}\n内容を確認してから、チャットに貼ってください。", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
