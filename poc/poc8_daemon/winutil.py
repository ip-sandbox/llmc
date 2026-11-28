"""PoC-8: Windows の状態を調べる小さな関数（ctypes。pywin32 を使わない）。"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
u32 = ctypes.WinDLL("user32", use_last_error=True)

DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_BREAKAWAY_FROM_JOB = 0x01000000
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
SM_REMOTESESSION = 0x1000
DESKTOP_SWITCHDESKTOP = 0x0100


def in_job(handle=None) -> bool | None:
    """プロセスが何かのジョブの中にあるか。handle が None なら自分。"""
    h = handle if handle is not None else k32.GetCurrentProcess()
    r = wintypes.BOOL()
    if not k32.IsProcessInJob(wintypes.HANDLE(int(h)), None, ctypes.byref(r)):
        return None
    return bool(r.value)


def in_job_pid(pid: int) -> bool | None:
    h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return None
    try:
        return in_job(h)
    finally:
        k32.CloseHandle(h)


def session_locked() -> bool | None:
    """画面がロックされているか（入力のデスクトップに切り替えられなければロック中とみなす。目安）。"""
    h = u32.OpenInputDesktop(0, False, DESKTOP_SWITCHDESKTOP)
    if not h:
        return True
    try:
        return not bool(u32.SwitchDesktop(h))
    finally:
        u32.CloseDesktop(h)


def remote_session() -> bool:
    return bool(u32.GetSystemMetrics(SM_REMOTESESSION))
