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
