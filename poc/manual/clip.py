"""Windows のクリップボード（Unicode テキスト）の読み書き。ctypes のみ。"""
from __future__ import annotations

import ctypes
import time
from ctypes import wintypes as w

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002

u32 = ctypes.WinDLL("user32", use_last_error=True)
k32 = ctypes.WinDLL("kernel32", use_last_error=True)
u32.OpenClipboard.argtypes = [w.HWND]
u32.OpenClipboard.restype = w.BOOL
u32.CloseClipboard.restype = w.BOOL
u32.EmptyClipboard.restype = w.BOOL
u32.GetClipboardData.argtypes = [w.UINT]
u32.GetClipboardData.restype = w.HANDLE
u32.SetClipboardData.argtypes = [w.UINT, w.HANDLE]
u32.SetClipboardData.restype = w.HANDLE
u32.GetClipboardSequenceNumber.restype = w.DWORD
u32.IsClipboardFormatAvailable.argtypes = [w.UINT]
u32.IsClipboardFormatAvailable.restype = w.BOOL
k32.GlobalAlloc.argtypes = [w.UINT, ctypes.c_size_t]
k32.GlobalAlloc.restype = w.HGLOBAL
k32.GlobalLock.argtypes = [w.HGLOBAL]
k32.GlobalLock.restype = w.LPVOID
k32.GlobalUnlock.argtypes = [w.HGLOBAL]
k32.GlobalFree.argtypes = [w.HGLOBAL]


def _open(retries: int = 20) -> None:
    for _ in range(retries):
        if u32.OpenClipboard(None):
            return
        time.sleep(0.05)  # 他のアプリが開いている
    raise OSError("クリップボードを開けない")


u32.RegisterClipboardFormatW.argtypes = [w.LPCWSTR]
u32.RegisterClipboardFormatW.restype = w.UINT
k32.GlobalSize.argtypes = [w.HGLOBAL]
k32.GlobalSize.restype = ctypes.c_size_t
CF_HTML = u32.RegisterClipboardFormatW("HTML Format")


def get_html() -> str | None:
    """CF_HTML（UTF-8 のバイト列）を文字列で返す。無ければ None。"""
    if not u32.IsClipboardFormatAvailable(CF_HTML):
        return None
    _open()
    try:
        h = u32.GetClipboardData(CF_HTML)
        if not h:
            return None
        p = k32.GlobalLock(h)
        try:
            data = ctypes.string_at(p, k32.GlobalSize(h))
        finally:
            k32.GlobalUnlock(h)
    finally:
        u32.CloseClipboard()
    return data.split(b"\x00", 1)[0].decode("utf-8", "replace")


def sequence() -> int:
    return u32.GetClipboardSequenceNumber()


def get_text() -> str | None:
    if not u32.IsClipboardFormatAvailable(CF_UNICODETEXT):
        return None
    _open()
    try:
        h = u32.GetClipboardData(CF_UNICODETEXT)
        if not h:
            return None
        p = k32.GlobalLock(h)
        try:
            return ctypes.wstring_at(p)
        finally:
            k32.GlobalUnlock(h)
    finally:
        u32.CloseClipboard()


def set_text(text: str) -> None:
    data = ctypes.create_unicode_buffer(text)
    size = ctypes.sizeof(data)
    h = k32.GlobalAlloc(GMEM_MOVEABLE, size)
    if not h:
        raise ctypes.WinError(ctypes.get_last_error())
    p = k32.GlobalLock(h)
    ctypes.memmove(p, data, size)
    k32.GlobalUnlock(h)
    _open()
    try:
        u32.EmptyClipboard()
        if not u32.SetClipboardData(CF_UNICODETEXT, h):
            k32.GlobalFree(h)
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        u32.CloseClipboard()



def _cf_html(fragment: str) -> bytes:
    """HTML の断片から CF_HTML のバイト列（ヘッダの位置は UTF-8 のバイト数）を作る。"""
    head = "Version:0.9\r\nStartHTML:{0:010d}\r\nEndHTML:{1:010d}\r\nStartFragment:{2:010d}\r\nEndFragment:{3:010d}\r\n"
    pre = "<html><body><!--StartFragment-->"
    post = "<!--EndFragment--></body></html>"
    dummy = head.format(0, 0, 0, 0).encode("utf-8")
    sh = len(dummy)
    sf = sh + len(pre.encode("utf-8"))
    ef = sf + len(fragment.encode("utf-8"))
    eh = ef + len(post.encode("utf-8"))
    return head.format(sh, eh, sf, ef).encode("utf-8") + (pre + fragment + post).encode("utf-8")


def set_text_and_html(text: str, fragment: str) -> None:
    """テキストと HTML の両方をクリップボードに入れる（貼り付け先が HTML を優先するかを試すため）。"""
    tdata = ctypes.create_unicode_buffer(text)
    hdata = _cf_html(fragment) + b"\x00"
    handles = []
    for buf, size in ((tdata, ctypes.sizeof(tdata)), (hdata, len(hdata))):
        h = k32.GlobalAlloc(GMEM_MOVEABLE, size)
        p = k32.GlobalLock(h)
        ctypes.memmove(p, buf, size)
        k32.GlobalUnlock(h)
        handles.append(h)
    _open()
    try:
        u32.EmptyClipboard()
        u32.SetClipboardData(CF_UNICODETEXT, handles[0])
        u32.SetClipboardData(CF_HTML, handles[1])
    finally:
        u32.CloseClipboard()
