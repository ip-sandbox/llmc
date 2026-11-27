"""PoC-4 で使う Win32 API の ctypes 定義（Windows でのみ読み込む）。"""
from __future__ import annotations

import ctypes
from ctypes import wintypes as w

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
adv = ctypes.WinDLL("advapi32", use_last_error=True)

INVALID_HANDLE_VALUE = w.HANDLE(-1).value
ERROR_PIPE_CONNECTED = 535
ERROR_ACCESS_DENIED = 5
STILL_ACTIVE = 259


class SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("nLength", w.DWORD), ("lpSecurityDescriptor", w.LPVOID), ("bInheritHandle", w.BOOL)]


class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", w.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", w.DWORD),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", w.DWORD), ("SchedulingClass", w.DWORD)]


class IO_COUNTERS(ctypes.Structure):
    _fields_ = [(n, ctypes.c_uint64) for n in ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                                                 "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION), ("IoInfo", IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]


JobObjectBasicLimitInformation = 2
JobObjectExtendedLimitInformation = 9
JOB_OBJECT_LIMIT_BREAKAWAY_OK = 0x00000800
JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK = 0x00001000
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000

CREATE_BREAKAWAY_FROM_JOB = 0x01000000
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW = 0x08000000

PROCESS_TERMINATE = 0x0001
PROCESS_SET_QUOTA = 0x0100
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TOKEN_QUERY = 0x0008
TokenUser = 1

PIPE_ACCESS_DUPLEX = 0x00000003
FILE_FLAG_FIRST_PIPE_INSTANCE = 0x00080000
PIPE_TYPE_BYTE = 0x0
PIPE_WAIT = 0x0
PIPE_REJECT_REMOTE_CLIENTS = 0x00000008
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
READ_CONTROL = 0x00020000
OPEN_EXISTING = 3
SE_KERNEL_OBJECT = 6
OWNER_SECURITY_INFORMATION = 0x1
DACL_SECURITY_INFORMATION = 0x4
SDDL_REVISION_1 = 1


def _f(lib, name, res, *args):
    fn = getattr(lib, name)
    fn.restype = res
    fn.argtypes = list(args)
    return fn


CloseHandle = _f(k32, "CloseHandle", w.BOOL, w.HANDLE)
GetCurrentProcess = _f(k32, "GetCurrentProcess", w.HANDLE)
OpenProcess = _f(k32, "OpenProcess", w.HANDLE, w.DWORD, w.BOOL, w.DWORD)
GetExitCodeProcess = _f(k32, "GetExitCodeProcess", w.BOOL, w.HANDLE, ctypes.POINTER(w.DWORD))
IsProcessInJob = _f(k32, "IsProcessInJob", w.BOOL, w.HANDLE, w.HANDLE, ctypes.POINTER(w.BOOL))
CreateJobObjectW = _f(k32, "CreateJobObjectW", w.HANDLE, w.LPVOID, w.LPCWSTR)
SetInformationJobObject = _f(k32, "SetInformationJobObject", w.BOOL, w.HANDLE, ctypes.c_int, w.LPVOID, w.DWORD)
QueryInformationJobObject = _f(k32, "QueryInformationJobObject", w.BOOL, w.HANDLE, ctypes.c_int, w.LPVOID,
                               w.DWORD, ctypes.POINTER(w.DWORD))
AssignProcessToJobObject = _f(k32, "AssignProcessToJobObject", w.BOOL, w.HANDLE, w.HANDLE)
TerminateJobObject = _f(k32, "TerminateJobObject", w.BOOL, w.HANDLE, w.UINT)

CreateNamedPipeW = _f(k32, "CreateNamedPipeW", w.HANDLE, w.LPCWSTR, w.DWORD, w.DWORD, w.DWORD, w.DWORD,
                      w.DWORD, w.DWORD, ctypes.POINTER(SECURITY_ATTRIBUTES))
ConnectNamedPipe = _f(k32, "ConnectNamedPipe", w.BOOL, w.HANDLE, w.LPVOID)
DisconnectNamedPipe = _f(k32, "DisconnectNamedPipe", w.BOOL, w.HANDLE)
CreateFileW = _f(k32, "CreateFileW", w.HANDLE, w.LPCWSTR, w.DWORD, w.DWORD, w.LPVOID, w.DWORD, w.DWORD, w.HANDLE)
GetNamedPipeServerProcessId = _f(k32, "GetNamedPipeServerProcessId", w.BOOL, w.HANDLE, ctypes.POINTER(w.ULONG))
WaitNamedPipeW = _f(k32, "WaitNamedPipeW", w.BOOL, w.LPCWSTR, w.DWORD)

ReplaceFileW = _f(k32, "ReplaceFileW", w.BOOL, w.LPCWSTR, w.LPCWSTR, w.LPCWSTR, w.DWORD, w.LPVOID, w.LPVOID)
GetFileAttributesW = _f(k32, "GetFileAttributesW", w.DWORD, w.LPCWSTR)
SetFileAttributesW = _f(k32, "SetFileAttributesW", w.BOOL, w.LPCWSTR, w.DWORD)
GetShortPathNameW = _f(k32, "GetShortPathNameW", w.DWORD, w.LPCWSTR, w.LPWSTR, w.DWORD)

OpenProcessToken = _f(adv, "OpenProcessToken", w.BOOL, w.HANDLE, w.DWORD, ctypes.POINTER(w.HANDLE))
GetTokenInformation = _f(adv, "GetTokenInformation", w.BOOL, w.HANDLE, ctypes.c_int, w.LPVOID, w.DWORD,
                         ctypes.POINTER(w.DWORD))
ConvertSidToStringSidW = _f(adv, "ConvertSidToStringSidW", w.BOOL, w.LPVOID, ctypes.POINTER(w.LPWSTR))
ConvertStringSecurityDescriptorToSecurityDescriptorW = _f(
    adv, "ConvertStringSecurityDescriptorToSecurityDescriptorW", w.BOOL, w.LPCWSTR, w.DWORD,
    ctypes.POINTER(w.LPVOID), ctypes.POINTER(w.ULONG))
ConvertSecurityDescriptorToStringSecurityDescriptorW = _f(
    adv, "ConvertSecurityDescriptorToStringSecurityDescriptorW", w.BOOL, w.LPVOID, w.DWORD, w.DWORD,
    ctypes.POINTER(w.LPWSTR), ctypes.POINTER(w.ULONG))
GetSecurityInfo = _f(adv, "GetSecurityInfo", w.DWORD, w.HANDLE, ctypes.c_int, w.DWORD, w.LPVOID, w.LPVOID,
                     w.LPVOID, w.LPVOID, ctypes.POINTER(w.LPVOID))
LocalFree = _f(k32, "LocalFree", w.HLOCAL, w.HLOCAL)


def last_error() -> int:
    return ctypes.get_last_error()


def process_user_sid(hproc) -> str:
    tok = w.HANDLE()
    if not OpenProcessToken(hproc, TOKEN_QUERY, ctypes.byref(tok)):
        raise ctypes.WinError(last_error())
    try:
        need = w.DWORD()
        GetTokenInformation(tok, TokenUser, None, 0, ctypes.byref(need))
        buf = ctypes.create_string_buffer(need.value)
        if not GetTokenInformation(tok, TokenUser, buf, need, ctypes.byref(need)):
            raise ctypes.WinError(last_error())
        psid = ctypes.cast(buf, ctypes.POINTER(w.LPVOID))[0]  # TOKEN_USER.User.Sid
        s = w.LPWSTR()
        if not ConvertSidToStringSidW(psid, ctypes.byref(s)):
            raise ctypes.WinError(last_error())
        try:
            return s.value
        finally:
            LocalFree(ctypes.cast(s, w.HLOCAL))
    finally:
        CloseHandle(tok)


def current_user_sid() -> str:
    return process_user_sid(GetCurrentProcess())


def handle_dacl_sddl(handle) -> str:
    psd = w.LPVOID()
    rc = GetSecurityInfo(handle, SE_KERNEL_OBJECT, DACL_SECURITY_INFORMATION | OWNER_SECURITY_INFORMATION,
                         None, None, None, None, ctypes.byref(psd))
    if rc != 0:
        raise ctypes.WinError(rc)
    try:
        s = w.LPWSTR()
        if not ConvertSecurityDescriptorToStringSecurityDescriptorW(
                psd, SDDL_REVISION_1, DACL_SECURITY_INFORMATION | OWNER_SECURITY_INFORMATION, ctypes.byref(s), None):
            raise ctypes.WinError(last_error())
        try:
            return s.value
        finally:
            LocalFree(ctypes.cast(s, w.HLOCAL))
    finally:
        LocalFree(ctypes.cast(psd, w.HLOCAL))


def sa_from_sddl(sddl: str):
    psd = w.LPVOID()
    if not ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, SDDL_REVISION_1, ctypes.byref(psd), None):
        raise ctypes.WinError(last_error())
    sa = SECURITY_ATTRIBUTES(ctypes.sizeof(SECURITY_ATTRIBUTES), psd, False)
    return sa, psd


def process_alive(pid: int) -> bool:
    h = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return False
    try:
        code = w.DWORD()
        GetExitCodeProcess(h, ctypes.byref(code))
        return code.value == STILL_ACTIVE
    finally:
        CloseHandle(h)


def is_in_job() -> bool:
    r = w.BOOL()
    IsProcessInJob(GetCurrentProcess(), None, ctypes.byref(r))
    return bool(r.value)


def current_job_limit_flags() -> int | None:
    info = JOBOBJECT_BASIC_LIMIT_INFORMATION()
    if not QueryInformationJobObject(None, JobObjectBasicLimitInformation, ctypes.byref(info),
                                     ctypes.sizeof(info), None):
        return None
    return info.LimitFlags


def create_job(flags: int):
    job = CreateJobObjectW(None, None)
    if not job:
        raise ctypes.WinError(last_error())
    info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    info.BasicLimitInformation.LimitFlags = flags
    if not SetInformationJobObject(job, JobObjectExtendedLimitInformation, ctypes.byref(info), ctypes.sizeof(info)):
        raise ctypes.WinError(last_error())
    return job


def assign_pid_to_job(job, pid: int) -> None:
    h = OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, False, pid)
    if not h:
        raise ctypes.WinError(last_error())
    try:
        if not AssignProcessToJobObject(job, h):
            raise ctypes.WinError(last_error())
    finally:
        CloseHandle(h)
