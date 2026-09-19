"""Contain the PLATON/SHELXL tree, including PLATON's lingering GUI helpers."""
from __future__ import annotations

import os
import signal
import subprocess
import time

from ..procutil import hidden_popen_kwargs, limit_cpu


class CheckcifProcess:
    """Own one process tree, never discover or kill processes by executable name.

    Windows assignment happens before the first instruction runs. A Job Object
    also contains grandchildren when their immediate parent has already exited.
    """

    def __init__(self, args: list[str], **kwargs):
        self.proc = None
        self.job = None
        options = hidden_popen_kwargs()
        try:
            if os.name == "nt":
                self._windows_job()
                options["creationflags"] = options.get("creationflags", 0) | 0x4
            else:
                options["start_new_session"] = True
            self.proc = subprocess.Popen(args, **kwargs, **options)
            if os.name == "nt":
                import ctypes
                handle = int(self.proc._handle)
                if not self.kernel.AssignProcessToJobObject(self.job, handle):
                    raise ctypes.WinError()
                limit_cpu(self.proc.pid)
                resume = ctypes.WinDLL("ntdll").NtResumeProcess
                resume.argtypes = [ctypes.c_void_p]
                resume.restype = ctypes.c_long
                if resume(handle) != 0:
                    raise OSError("could not resume contained PLATON process")
        except BaseException:
            if self.proc is not None and self.proc.poll() is None:
                self.proc.kill()
                self.proc.wait(timeout=5)
            self.close()
            raise

    def _windows_job(self):
        import ctypes as c
        from ctypes import wintypes as w

        class BasicLimits(c.Structure):
            _fields_ = [("PerProcessUserTimeLimit", c.c_longlong),
                        ("PerJobUserTimeLimit", c.c_longlong), ("LimitFlags", w.DWORD),
                        ("MinimumWorkingSetSize", c.c_size_t),
                        ("MaximumWorkingSetSize", c.c_size_t),
                        ("ActiveProcessLimit", w.DWORD), ("Affinity", c.c_size_t),
                        ("PriorityClass", w.DWORD), ("SchedulingClass", w.DWORD)]

        class IoCounters(c.Structure):
            _fields_ = [(name, c.c_ulonglong) for name in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

        class ExtendedLimits(c.Structure):
            _fields_ = [("BasicLimitInformation", BasicLimits), ("IoInfo", IoCounters),
                        ("ProcessMemoryLimit", c.c_size_t), ("JobMemoryLimit", c.c_size_t),
                        ("PeakProcessMemoryUsed", c.c_size_t),
                        ("PeakJobMemoryUsed", c.c_size_t)]

        class Accounting(c.Structure):
            _fields_ = [(name, c.c_longlong) for name in (
                "TotalUserTime", "TotalKernelTime", "ThisPeriodTotalUserTime",
                "ThisPeriodTotalKernelTime")] + [(name, w.DWORD) for name in (
                "TotalPageFaultCount", "TotalProcesses", "ActiveProcesses",
                "TotalTerminatedProcesses")]

        self.accounting_type = Accounting
        k = c.WinDLL("kernel32", use_last_error=True)
        signatures = {
            "CreateJobObjectW": ([c.c_void_p, w.LPCWSTR], w.HANDLE),
            "SetInformationJobObject": ([w.HANDLE, c.c_int, c.c_void_p, w.DWORD], w.BOOL),
            "QueryInformationJobObject": (
                [w.HANDLE, c.c_int, c.c_void_p, w.DWORD, c.c_void_p], w.BOOL),
            "AssignProcessToJobObject": ([w.HANDLE, w.HANDLE], w.BOOL),
            "TerminateJobObject": ([w.HANDLE, w.UINT], w.BOOL),
            "CloseHandle": ([w.HANDLE], w.BOOL),
        }
        for name, (args, result) in signatures.items():
            fn = getattr(k, name)
            fn.argtypes, fn.restype = args, result
        self.kernel = k
        self.job = k.CreateJobObjectW(None, None)
        if not self.job:
            raise c.WinError(c.get_last_error())
        limits = ExtendedLimits()
        limits.BasicLimitInformation.LimitFlags = 0x2000  # KILL_ON_JOB_CLOSE
        if not k.SetInformationJobObject(self.job, 9, c.byref(limits), c.sizeof(limits)):
            raise c.WinError(c.get_last_error())

    @property
    def pid(self):
        return self.proc.pid

    def poll(self):
        return self.proc.poll()

    def active(self) -> bool:
        if self.job:
            import ctypes as c
            info = self.accounting_type()
            if not self.kernel.QueryInformationJobObject(
                    self.job, 1, c.byref(info), c.sizeof(info), None):
                raise c.WinError(c.get_last_error())
            return info.ActiveProcesses > 0
        if self.proc is None:
            return False
        if os.name == "nt":
            return self.proc.poll() is None
        self.proc.poll()
        try:
            os.killpg(self.pid, 0)
            return True
        except ProcessLookupError:
            return False

    def close(self) -> bool:
        """Terminate only this owned tree, reap its root and confirm shutdown."""
        if self.job:
            try:
                if not self.kernel.TerminateJobObject(self.job, 1):
                    return False
                if self.proc is not None:
                    self.proc.wait(timeout=5)
                until = time.monotonic() + 5
                while self.active() and time.monotonic() < until:
                    time.sleep(0.05)
                return not self.active()
            finally:
                self.kernel.CloseHandle(self.job)
                self.job = None
        if self.proc is None:
            return True
        if os.name == "nt":
            return self.proc.poll() is not None
        try:
            os.killpg(self.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        self.proc.wait(timeout=5)
        return True
