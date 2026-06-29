from __future__ import annotations

import ctypes
import subprocess
import sys
from ctypes import wintypes
from dataclasses import dataclass


JOB_OBJECT_CPU_RATE_CONTROL_ENABLE = 0x00000001
JOB_OBJECT_CPU_RATE_CONTROL_HARD_CAP = 0x00000004
JOB_OBJECT_CPU_RATE_CONTROL_INFORMATION_CLASS = 15

PROCESS_TERMINATE = 0x0001
PROCESS_SET_QUOTA = 0x0100
SYNCHRONIZE = 0x00100000

CREATE_SUSPENDED = 0x00000004
CREATE_BREAKAWAY_FROM_JOB = 0x01000000

WAIT_OBJECT_0 = 0x00000000
WAIT_TIMEOUT = 0x00000102
STILL_ACTIVE = 259


class Win32Error(RuntimeError):
    pass


class JobObjectCpuRateControlInformation(ctypes.Structure):
    _fields_ = [
        ("ControlFlags", wintypes.DWORD),
        ("CpuRate", wintypes.DWORD),
    ]


class StartupInfoW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD),
        ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD),
        ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD),
        ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD),
        ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.POINTER(ctypes.c_byte)),
        ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class ProcessInformation(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE),
        ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD),
        ("dwThreadId", wintypes.DWORD),
    ]


class Kernel32:
    def __init__(self) -> None:
        if sys.platform != "win32":
            raise Win32Error("This tool must run on Windows because it calls Win32 APIs.")

        self.dll = ctypes.WinDLL("kernel32", use_last_error=True)
        self._configure()

    def _configure(self) -> None:
        self.dll.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
        self.dll.CreateJobObjectW.restype = wintypes.HANDLE

        self.dll.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            wintypes.LPVOID,
            wintypes.DWORD,
        ]
        self.dll.SetInformationJobObject.restype = wintypes.BOOL

        self.dll.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self.dll.AssignProcessToJobObject.restype = wintypes.BOOL

        self.dll.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.dll.OpenProcess.restype = wintypes.HANDLE

        self.dll.CreateProcessW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.LPWSTR,
            wintypes.LPVOID,
            wintypes.LPVOID,
            wintypes.BOOL,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.LPCWSTR,
            ctypes.POINTER(StartupInfoW),
            ctypes.POINTER(ProcessInformation),
        ]
        self.dll.CreateProcessW.restype = wintypes.BOOL

        self.dll.ResumeThread.argtypes = [wintypes.HANDLE]
        self.dll.ResumeThread.restype = wintypes.DWORD

        self.dll.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self.dll.WaitForSingleObject.restype = wintypes.DWORD

        self.dll.GetExitCodeProcess.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self.dll.GetExitCodeProcess.restype = wintypes.BOOL

        self.dll.CloseHandle.argtypes = [wintypes.HANDLE]
        self.dll.CloseHandle.restype = wintypes.BOOL

    def check(self, ok: int, action: str) -> None:
        if ok:
            return
        error = ctypes.get_last_error()
        raise Win32Error(f"{action} failed: {ctypes.WinError(error)}")

    def close(self, handle: wintypes.HANDLE | None) -> None:
        if handle:
            self.dll.CloseHandle(handle)


class Handle:
    def __init__(self, kernel32: Kernel32, value: wintypes.HANDLE | None = None) -> None:
        self.kernel32 = kernel32
        self.value = value

    def close(self) -> None:
        if self.value:
            self.kernel32.close(self.value)
            self.value = None

    def __enter__(self) -> Handle:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


@dataclass
class CpuLimitSession:
    kernel32: Kernel32
    job: Handle
    process: Handle
    pid: int
    cpu_percent: float
    command_line: str | None = None

    def set_cpu_percent(self, cpu_percent: float) -> None:
        _set_cpu_hard_limit(self.kernel32, self.job.value, cpu_percent)
        self.cpu_percent = cpu_percent

    def release(self) -> None:
        if self.job.value:
            _clear_cpu_limit(self.kernel32, self.job.value)
        self.close()

    def wait(self, timeout_ms: int = 1000) -> int | None:
        result = self.kernel32.dll.WaitForSingleObject(self.process.value, timeout_ms)
        if result == WAIT_TIMEOUT:
            return None
        if result != WAIT_OBJECT_0:
            raise Win32Error(f"WaitForSingleObject failed with status {result}.")
        return self.exit_code()

    def wait_until_exit(self) -> int:
        while True:
            exit_code = self.wait(1000)
            if exit_code is not None:
                return exit_code

    def exit_code(self) -> int:
        exit_code = wintypes.DWORD(STILL_ACTIVE)
        self.kernel32.check(
            self.kernel32.dll.GetExitCodeProcess(self.process.value, ctypes.byref(exit_code)),
            "GetExitCodeProcess",
        )
        return int(exit_code.value)

    def close(self) -> None:
        self.process.close()
        self.job.close()


def _create_job(kernel32: Kernel32) -> Handle:
    job = kernel32.dll.CreateJobObjectW(None, None)
    if not job:
        error = ctypes.get_last_error()
        raise Win32Error(f"CreateJobObjectW failed: {ctypes.WinError(error)}")
    return Handle(kernel32, job)


def _set_cpu_hard_limit(
    kernel32: Kernel32,
    job: wintypes.HANDLE,
    cpu_percent: float,
) -> None:
    info = JobObjectCpuRateControlInformation()
    info.ControlFlags = (
        JOB_OBJECT_CPU_RATE_CONTROL_ENABLE | JOB_OBJECT_CPU_RATE_CONTROL_HARD_CAP
    )
    info.CpuRate = max(1, min(10000, round(cpu_percent * 100)))

    kernel32.check(
        kernel32.dll.SetInformationJobObject(
            job,
            JOB_OBJECT_CPU_RATE_CONTROL_INFORMATION_CLASS,
            ctypes.byref(info),
            ctypes.sizeof(info),
        ),
        "SetInformationJobObject(JobObjectCpuRateControlInformation)",
    )


def _clear_cpu_limit(kernel32: Kernel32, job: wintypes.HANDLE) -> None:
    info = JobObjectCpuRateControlInformation()
    info.ControlFlags = 0
    info.CpuRate = 0

    kernel32.check(
        kernel32.dll.SetInformationJobObject(
            job,
            JOB_OBJECT_CPU_RATE_CONTROL_INFORMATION_CLASS,
            ctypes.byref(info),
            ctypes.sizeof(info),
        ),
        "SetInformationJobObject(clear JobObjectCpuRateControlInformation)",
    )


def _assign_process(
    kernel32: Kernel32,
    job: wintypes.HANDLE,
    process: wintypes.HANDLE,
) -> None:
    kernel32.check(
        kernel32.dll.AssignProcessToJobObject(job, process),
        "AssignProcessToJobObject",
    )


def limit_existing_process(pid: int, cpu_percent: float) -> CpuLimitSession:
    kernel32 = Kernel32()
    access = PROCESS_SET_QUOTA | PROCESS_TERMINATE | SYNCHRONIZE
    process = kernel32.dll.OpenProcess(access, False, pid)
    if not process:
        error = ctypes.get_last_error()
        raise Win32Error(f"OpenProcess({pid}) failed: {ctypes.WinError(error)}")

    process_handle = Handle(kernel32, process)
    job = _create_job(kernel32)
    try:
        _set_cpu_hard_limit(kernel32, job.value, cpu_percent)
        _assign_process(kernel32, job.value, process_handle.value)
        return CpuLimitSession(kernel32, job, process_handle, pid, cpu_percent)
    except Exception:
        process_handle.close()
        job.close()
        raise


def launch_limited_process(command: list[str], cpu_percent: float) -> CpuLimitSession:
    if not command:
        raise Win32Error("Missing command to run.")

    return launch_limited_command_line(subprocess.list2cmdline(command), cpu_percent)


def launch_limited_command_line(command_line: str, cpu_percent: float) -> CpuLimitSession:
    command_line = command_line.strip()
    if not command_line:
        raise Win32Error("Missing command to run.")

    kernel32 = Kernel32()
    command_buffer = ctypes.create_unicode_buffer(command_line)
    startup_info = StartupInfoW()
    startup_info.cb = ctypes.sizeof(StartupInfoW)
    process_info = ProcessInformation()
    job = _create_job(kernel32)

    try:
        _set_cpu_hard_limit(kernel32, job.value, cpu_percent)
        kernel32.check(
            kernel32.dll.CreateProcessW(
                None,
                command_buffer,
                None,
                None,
                False,
                CREATE_SUSPENDED | CREATE_BREAKAWAY_FROM_JOB,
                None,
                None,
                ctypes.byref(startup_info),
                ctypes.byref(process_info),
            ),
            "CreateProcessW",
        )

        process = Handle(kernel32, process_info.hProcess)
        thread = Handle(kernel32, process_info.hThread)
        try:
            _assign_process(kernel32, job.value, process.value)
            if kernel32.dll.ResumeThread(thread.value) == 0xFFFFFFFF:
                error = ctypes.get_last_error()
                raise Win32Error(f"ResumeThread failed: {ctypes.WinError(error)}")
        except Exception:
            process.close()
            raise
        finally:
            thread.close()

        return CpuLimitSession(
            kernel32=kernel32,
            job=job,
            process=process,
            pid=int(process_info.dwProcessId),
            cpu_percent=cpu_percent,
            command_line=command_line,
        )
    except Exception:
        job.close()
        raise
