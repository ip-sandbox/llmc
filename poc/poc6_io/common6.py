"""PoC-6 の共通部品: 空行の代わりの行、クリップボード（除外の印つきの書き込み、テキストと HTML の同時の読み取り）、CF_HTML の厳密な読み方。"""
from __future__ import annotations

import ctypes
import msvcrt
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
for p in (ROOT, ROOT / "manual"):
    sys.path.insert(0, str(p))
import clip  # noqa: E402
from clip import CF_HTML, CF_UNICODETEXT, GMEM_MOVEABLE, _open, k32, u32  # noqa: E402
from common.report import OUT_DIR  # noqa: E402

OUT = OUT_DIR / "poc6"
OUT.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------- 空行の代わりの行（spec-file-protocol 9.6）


def choose_filler(texts) -> str:
    """どの文脈ファイルにも「その行そのもの」として現れない、最短の空白だけの行。"""
    for n in range(1, 17):
        f = " " * n
        if all(f not in t.replace("\r\n", "\n").split("\n") for t in texts):
            return f
    raise ValueError("代わりの行を選べない")


def apply_filler(text: str, filler: str) -> str:
    return "\n".join(filler if line == "" else line for line in text.split("\n"))


def restore_filler(lines: list[str], filler: str) -> list[str]:
    return ["" if line == filler else line for line in lines]


# ---------------------------------------------------------------- クリップボード

F_EXCLUDE = u32.RegisterClipboardFormatW("ExcludeClipboardContentFromMonitorProcessing")
F_HISTORY = u32.RegisterClipboardFormatW("CanIncludeInClipboardHistory")
F_CLOUD = u32.RegisterClipboardFormatW("CanUploadToCloudClipboard")
F_PWMGR = u32.RegisterClipboardFormatW("Clipboard Viewer Ignore")


def _global(data: bytes):
    h = k32.GlobalAlloc(GMEM_MOVEABLE, len(data))
    if not h:
        raise ctypes.WinError(ctypes.get_last_error())
    p = k32.GlobalLock(h)
    ctypes.memmove(p, data, len(data))
    k32.GlobalUnlock(h)
    return h


def set_text_private(text: str, private: bool = True) -> int:
    """テキストを入れる。private なら履歴とクラウドへの同期から除外する印も入れる。書き込み後の更新番号を返す。"""
    handles = [(CF_UNICODETEXT, _global((text + "\0").encode("utf-16-le")))]
    if private:
        zero = (0).to_bytes(4, "little")
        handles += [(F_HISTORY, _global(zero)), (F_CLOUD, _global(zero)), (F_EXCLUDE, _global(b"\0"))]
    _open()
    try:
        u32.EmptyClipboard()
        for fmt, h in handles:
            if not u32.SetClipboardData(fmt, h):
                k32.GlobalFree(h)
                raise ctypes.WinError(ctypes.get_last_error())
    finally:
        u32.CloseClipboard()
    return clip.sequence()


def _read(fmt) -> bytes | None:
    h = u32.GetClipboardData(fmt)
    if not h:
        return None
    p = k32.GlobalLock(h)
    try:
        return ctypes.string_at(p, k32.GlobalSize(h))
    finally:
        k32.GlobalUnlock(h)


def read_both() -> dict | None:
    """1 回の OpenClipboard の中でテキストと HTML を読む。前後で更新番号が変われば None（読み直す）。"""
    seq = clip.sequence()
    _open()
    try:
        excluded = bool(u32.IsClipboardFormatAvailable(F_EXCLUDE) or u32.IsClipboardFormatAvailable(F_PWMGR))
        text = html = None
        if not excluded:
            t = _read(CF_UNICODETEXT)
            text = t.decode("utf-16-le", "replace").split("\0", 1)[0] if t else None
            html = _read(CF_HTML) if u32.IsClipboardFormatAvailable(CF_HTML) else None
    finally:
        u32.CloseClipboard()
    if clip.sequence() != seq:
        return None
    return {"seq": seq, "excluded": excluded, "text": text, "html": html.split(b"\0", 1)[0] if html else None}


def clear_if_ours(seq: int) -> bool:
    """更新番号が自分の書き込みのときのままなら、クリップボードを空にする。"""
    if clip.sequence() != seq:
        return False
    _open()
    try:
        u32.EmptyClipboard()
    finally:
        u32.CloseClipboard()
    return True


# ---------------------------------------------------------------- CF_HTML


def parse_cf_html(raw: bytes) -> dict:
    """ヘッダのバイト位置で断片を切り出し、UTF-8 として厳密に復号する。"""
    head = {}
    for m in re.finditer(rb"^(Version|StartHTML|EndHTML|StartFragment|EndFragment|SourceURL):(.*?)\r?$", raw[:600], re.M):
        head[m.group(1).decode()] = m.group(2).decode("ascii", "replace").strip()
    res = {"source_url_host": None, "by_offset": False, "strict_utf8": True, "fragment": None}
    if "SourceURL" in head:
        res["source_url_host"] = re.sub(r"^https?://([^/]+).*$", r"\1", head["SourceURL"])
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        res["strict_utf8"] = False
    try:
        sf, ef = int(head["StartFragment"]), int(head["EndFragment"])
        res["fragment"] = raw[sf:ef].decode("utf-8")
        res["by_offset"] = True
    except (KeyError, ValueError, UnicodeDecodeError):
        s = raw.decode("utf-8", "replace")
        m = re.search(r"<!--StartFragment-->(.*)<!--EndFragment-->", s, re.S)
        res["fragment"] = m.group(1) if m else s
    return res


# ---------------------------------------------------------------- 回答を待つ（spec-browser-driver 13.2）


def norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def wait_answer(tid: str, sent: str, timeout: float = 1800, want=("LLMC-DONE", "LLMC-PLAN"), keys: str = "") -> dict:
    """回答のコピーを待つ。keys に書いたキーが押されたら {"key": キー} を返す（失敗の報告など）。"""
    start_seq = clip.sequence()
    last = start_seq
    t0 = time.time()
    sent_n = norm(sent)
    while time.time() - t0 < timeout:
        time.sleep(0.4)
        while keys and msvcrt.kbhit():
            ch = msvcrt.getwch().lower()
            if ch in keys:
                return {"key": ch}
        s = clip.sequence()
        if s == last:
            continue
        last = s
        try:
            got = read_both()
        except OSError:
            continue
        if got is None:
            last = -1  # 読み直す
            continue
        t = got["text"] or ""
        if got["excluded"]:
            why = "除外の印があるので読まない"
        elif not got["html"]:
            why = "HTML が無い"
        elif tid not in t.upper():
            why = "このターンの ID が無い"
        elif want and not any(re.search(rf"{w}\b[^\n]*id={tid}", t, re.I) for w in want):
            why = "このターンの LLMC-DONE / LLMC-PLAN が無い"
        elif norm(t) == sent_n:
            why = "送った本文と同じ"
        else:
            got["seconds"] = round(time.time() - t0, 1)
            return got
        print(f"  （コピーを無視しました: {why}、{len(t)} 文字）", file=sys.stderr)
    return {"timeout": True}


def short_tid(tid: str) -> str:
    return tid[:2] + "****"
