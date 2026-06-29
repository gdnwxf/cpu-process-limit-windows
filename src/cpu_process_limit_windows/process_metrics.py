from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes

from cpu_process_limit_windows.core import Win32Error


PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
FILETIME_UNITS_PER_SECOND = 10_000_000


def get_process_cpu_time(pid: int) -> float:
    if sys.platform != "win32":
        raise Win32Error("This tool must run on Windows because it calls Win32 APIs.")

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetProcessTimes.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
    ]
    kernel32.GetProcessTimes.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    process = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not process:
        error = ctypes.get_last_error()
        raise Win32Error(f"OpenProcess({pid}) failed: {ctypes.WinError(error)}")

    try:
        creation = wintypes.FILETIME()
        exit_time = wintypes.FILETIME()
        kernel = wintypes.FILETIME()
        user = wintypes.FILETIME()
        ok = kernel32.GetProcessTimes(
            process,
            ctypes.byref(creation),
            ctypes.byref(exit_time),
            ctypes.byref(kernel),
            ctypes.byref(user),
        )
        if not ok:
            error = ctypes.get_last_error()
            raise Win32Error(f"GetProcessTimes({pid}) failed: {ctypes.WinError(error)}")
        return (_filetime_to_int(kernel) + _filetime_to_int(user)) / FILETIME_UNITS_PER_SECOND
    finally:
        kernel32.CloseHandle(process)


def calculate_cpu_percent(
    previous_time: float,
    previous_cpu_time: float,
    current_time: float,
    current_cpu_time: float,
) -> float:
    elapsed = current_time - previous_time
    if elapsed <= 0:
        return 0.0

    cpu_count = os.cpu_count() or 1
    percent = (current_cpu_time - previous_cpu_time) / elapsed / cpu_count * 100
    return max(0.0, percent)


def _filetime_to_int(value: wintypes.FILETIME) -> int:
    return (int(value.dwHighDateTime) << 32) | int(value.dwLowDateTime)
