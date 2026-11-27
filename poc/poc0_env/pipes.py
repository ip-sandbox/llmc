"""PowerShell 5.1 と cmd.exe のパイプ・リダイレクトで、日本語がどのバイト列で届くかを調べる（H-10）。"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from common.report import OUT_DIR, Report, first_line  # noqa: E402
from emit import TEXT  # noqa: E402

PY = sys.executable
EMIT = str(HERE / "emit.py")
ECHO = str(HERE / "echo_bytes.py")


def judge_bytes(data: bytes, expect_enc: str | None = None) -> tuple[str, str]:
    """届いたバイト列が、どの文字コードの TEXT だったかを判定する。"""
    for enc, label, bom in (("utf-8", "UTF-8", b"\xef\xbb\xbf"), ("utf-16-le", "UTF-16LE", b"\xff\xfe"),
                            ("cp932", "cp932", b"")):
        has_bom = bool(bom) and data.startswith(bom)
        body = data[len(bom):] if has_bom else data
        try:
            text = body.decode(enc)
        except UnicodeDecodeError:
            continue
        if text.strip("\r\n\x00") == TEXT:
            ok = expect_enc in (None, label)
            return ("OK" if ok else "WARN"), f"{label}{'（BOM 付き）' if has_bom else ''}で正しく届いた"
    preview = data.decode("utf-8", "replace")[:30]
    return "NG", f"文字化け（先頭のバイト列 {data[:24].hex()} / UTF-8 として表示 {preview!r}）"


def run_ps(script: str, timeout: int = 60) -> subprocess.CompletedProcess:
    enc = base64.b64encode(script.encode("utf-16-le")).decode()
    return subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", enc],
                          capture_output=True, timeout=timeout)


def run_cmd(inner: str, timeout: int = 60) -> subprocess.CompletedProcess:
    # 文字列で渡すと、Python はそのままコマンドラインとして CreateProcess に渡す
    return subprocess.run(f'cmd.exe /d /s /c "{inner}"', capture_output=True, timeout=timeout)


def q_ps(path: str) -> str:
    return "'" + path.replace("'", "''") + "'"


def run_all(rep: Report) -> None:
    work = OUT_DIR / "pipes"
    work.mkdir(parents=True, exist_ok=True)
    utf8_file = work / "sample_utf8.txt"
    utf8_file.write_bytes(TEXT.encode("utf-8") + b"\r\n")
    sec = "パイプとリダイレクト（H-10）"

    def via_echo(label, runner, build, expect=None, note=""):
        out = work / f"{label}.json"
        if out.exists():
            out.unlink()
        try:
            cp = runner(build(str(out)))
        except Exception as e:  # noqa: BLE001
            rep.add(sec, label, "NG", first_line(e))
            return
        if not out.exists():
            rep.add(sec, label, "NG", f"受け側が動かなかった（終了コード {cp.returncode}、stderr: "
                    f"{cp.stderr.decode('cp932', 'replace')[:200]}）")
            return
        res = json.loads(out.read_text(encoding="utf-8"))
        status, msg = judge_bytes(bytes.fromhex(res["hex"]), expect)
        rep.add(sec, label, status, (note + " → " if note else "") + msg)

    def via_file(label, runner, build, note=""):
        out = work / f"{label}.txt"
        if out.exists():
            out.unlink()
        try:
            runner(build(str(out)))
            data = out.read_bytes()
        except Exception as e:  # noqa: BLE001
            rep.add(sec, label, "NG", first_line(e))
            return
        status, msg = judge_bytes(data)
        rep.add(sec, label, "INFO" if status != "NG" else "NG", (note + " → " if note else "") + msg)

    P, E, C = q_ps(PY), q_ps(EMIT), q_ps(ECHO)
    lit = "'" + TEXT + "'"
    utf8_set = "$OutputEncoding = [Text.UTF8Encoding]::new($false); "
    utf8_all = utf8_set + "[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false); "

    # PowerShell 5.1
    via_echo("ps-文字列→python（既定）", run_ps, lambda o: f"{lit} | & {P} {C} {q_ps(o)}",
             note="PS の文字列をネイティブコマンドへ。$OutputEncoding の既定のまま")
    via_echo("ps-文字列→python（$OutputEncoding=UTF8）", run_ps,
             lambda o: utf8_set + f"{lit} | & {P} {C} {q_ps(o)}", expect="UTF-8")
    via_echo("ps-python(utf8)→python（既定）", run_ps, lambda o: f"& {P} {E} utf-8 | & {P} {C} {q_ps(o)}",
             note="ネイティブ同士。PS が [Console]::OutputEncoding で読んで $OutputEncoding で書き直す")
    via_echo("ps-python(cp932)→python（既定）", run_ps, lambda o: f"& {P} {E} cp932 | & {P} {C} {q_ps(o)}")
    via_echo("ps-python(utf8)→python（両方UTF8）", run_ps,
             lambda o: utf8_all + f"& {P} {E} utf-8 | & {P} {C} {q_ps(o)}", expect="UTF-8")
    via_echo("ps-python(既定の出力)→python（既定）", run_ps, lambda o: f"& {P} {E} default | & {P} {C} {q_ps(o)}",
             note="Python がパイプに書くときの既定の文字コード＋PS の書き直し")
    via_echo("ps-Get-Content(UTF8ファイル)→python（既定）", run_ps,
             lambda o: f"Get-Content -Encoding UTF8 {q_ps(str(utf8_file))} | & {P} {C} {q_ps(o)}")
    via_file("ps-python(utf8) > ファイル（既定）", run_ps, lambda o: f"& {P} {E} utf-8 > {q_ps(o)}",
             note="PS 5.1 のリダイレクトは Out-File の既定（UTF-16LE の想定）")

    # cmd.exe
    via_echo("cmd-type(UTF8ファイル)|python", run_cmd, lambda o: f'type "{utf8_file}" | "{PY}" "{ECHO}" "{o}"',
             note="cmd はバイト列をそのまま渡す想定", expect="UTF-8")
    via_echo("cmd-python(utf8)|python", run_cmd, lambda o: f'"{PY}" "{EMIT}" utf-8 | "{PY}" "{ECHO}" "{o}"',
             expect="UTF-8")
    via_echo("cmd-python(既定の出力)|python", run_cmd, lambda o: f'"{PY}" "{EMIT}" default | "{PY}" "{ECHO}" "{o}"',
             note="Python がパイプに書くときの既定の文字コード")
    via_file("cmd-python(utf8) > ファイル", run_cmd, lambda o: f'"{PY}" "{EMIT}" utf-8 > "{o}"')

    # Python の UTF-8 モード
    env = dict(os.environ, PYTHONUTF8="1")
    via_echo("cmd-python(既定の出力, PYTHONUTF8=1)|python",
             lambda c: subprocess.run(c, capture_output=True, timeout=60, env=env),
             lambda o: f'cmd.exe /d /s /c ""{PY}" "{EMIT}" default | "{PY}" "{ECHO}" "{o}""', expect="UTF-8")
