from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from dataclasses import dataclass

from cpu_process_limit_windows.core import Win32Error


MAX_PATH = 260
TH32CS_SNAPPROCESS = 0x00000002
INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


ULONG_PTR = ctypes.c_size_t


class ProcessEntry32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ULONG_PTR),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * MAX_PATH),
    ]


@dataclass(frozen=True)
class ProcessInfo:
    pid: int
    name: str
    path: str

    @property
    def searchable_text(self) -> str:
        return f"{self.pid} {self.name} {self.path}".lower()


class ProcessApi:
    def __init__(self) -> None:
        if sys.platform != "win32":
            raise Win32Error("This tool must run on Windows because it calls Win32 APIs.")

        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel32.CreateToolhelp32Snapshot.argtypes = [
            wintypes.DWORD,
            wintypes.DWORD,
        ]
        self.kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE

        self.kernel32.Process32FirstW.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(ProcessEntry32W),
        ]
        self.kernel32.Process32FirstW.restype = wintypes.BOOL

        self.kernel32.Process32NextW.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(ProcessEntry32W),
        ]
        self.kernel32.Process32NextW.restype = wintypes.BOOL

        self.kernel32.OpenProcess.argtypes = [
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
        ]
        self.kernel32.OpenProcess.restype = wintypes.HANDLE

        self.kernel32.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self.kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL

        self.kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel32.CloseHandle.restype = wintypes.BOOL

    def close_handle(self, handle: wintypes.HANDLE | None) -> None:
        if handle:
            self.kernel32.CloseHandle(handle)

    def query_path(self, pid: int) -> str:
        process = self.kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION,
            False,
            pid,
        )
        if not process:
            return ""

        try:
            size = wintypes.DWORD(32768)
            buffer = ctypes.create_unicode_buffer(size.value)
            ok = self.kernel32.QueryFullProcessImageNameW(
                process,
                0,
                buffer,
                ctypes.byref(size),
            )
            if not ok:
                return ""
            return buffer.value
        finally:
            self.close_handle(process)


def list_processes() -> list[ProcessInfo]:
    api = ProcessApi()
    snapshot = api.kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot == INVALID_HANDLE_VALUE:
        error = ctypes.get_last_error()
        raise Win32Error(f"CreateToolhelp32Snapshot failed: {ctypes.WinError(error)}")

    try:
        entry = ProcessEntry32W()
        entry.dwSize = ctypes.sizeof(ProcessEntry32W)
        ok = api.kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        if not ok:
            return []

        processes: list[ProcessInfo] = []
        while ok:
            pid = int(entry.th32ProcessID)
            name = entry.szExeFile
            processes.append(ProcessInfo(pid=pid, name=name, path=api.query_path(pid)))
            ok = api.kernel32.Process32NextW(snapshot, ctypes.byref(entry))

        return sorted(processes, key=lambda item: (item.name.lower(), item.pid))
    finally:
        api.close_handle(snapshot)


def fuzzy_match(query: str, text: str) -> bool:
    query = query.strip().lower()
    if not query:
        return True

    text = text.lower()
    if query in text:
        return True

    index = 0
    for char in query:
        index = text.find(char, index)
        if index == -1:
            return False
        index += 1
    return True
