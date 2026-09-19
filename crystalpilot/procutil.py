"""Windows process hygiene for subprocess spawns: console windows + CPU.

Console windows: the engine often runs with no attached console (the MCP
server is a codex child; launchers may be windowless). Spawning a console
executable (shelxl, platon, taskkill, powershell, cmd) from such a
process makes Windows allocate a brand-new VISIBLE console window on the
user's desktop - one flashing black box per call (user report, r11).
Passing CREATE_NO_WINDOW suppresses the window. WMI-created processes
need Win32_ProcessStartup.ShowWindow=0 instead (frames_dials._run_wmi).

CPU: crystallography bursts (SHELXL threads, cctbx FFTs) will happily
saturate every core of the host - on a user workstation that makes the
machine unusable (user report, r12). ``limit_cpu(pid)`` pins a process
to the first CRYSTALPILOT_CPU_CORES cores (default 4, 0 disables) at
BelowNormal priority; Windows children INHERIT the affinity mask, so
seeding the tree root (uvicorn / campaign runner) caps every future
codex, MCP python, SHELXL and PLATON descendant. WMI-created processes
break away from the tree and must be limited per-PID after creation.
"""
from __future__ import annotations

import os
import subprocess

#: pass as ``creationflags=`` on every console-exe spawn
NO_WINDOW: int = (getattr(subprocess, "CREATE_NO_WINDOW", 0)
                  if os.name == "nt" else 0)


def hidden_popen_kwargs() -> dict:
    """Popen kwargs that keep a spawned GUI/console exe off the desktop.

    CREATE_NO_WINDOW only suppresses the console; GUI exes (PLATON's
    WinPLT window, vendor tools) also need STARTUPINFO wShowWindow=
    SW_HIDE, which covers windows shown with SW_SHOWDEFAULT. Apps that
    force an explicit ShowWindow(SW_SHOW) can still ignore the hint -
    verify per vendor exe (PLATON honours it: probed 2026-08-31, no
    visible window while model.chk is produced normally).
    """
    if os.name != "nt":
        return {}
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 0  # SW_HIDE
    return {"creationflags": NO_WINDOW, "startupinfo": si}


def cpu_limit_cores() -> int:
    """Cores CrystalPilot compute trees may use (0 = unlimited)."""
    try:
        return max(0, int(os.environ.get("CRYSTALPILOT_CPU_CORES", "4")))
    except ValueError:
        return 4


def canonical_child_env(extra: dict | None = None) -> dict:
    """Fixed minimal environment for numerically sensitive vendor exes.

    Superflip's trajectory proved sensitive to the ENVIRONMENT-BLOCK
    LAYOUT of its process (classic uninitialised-memory coupling in a
    legacy Fortran binary): live isolation 2026-09-01 - byte-identical
    input with a fixed randomseed converged in 4-6 s or spun past a
    300 s timeout purely depending on the caller's PYTEST_CURRENT_TEST
    value, 100% deterministic per context, and adding one padding
    variable flipped the stuck context to a 5.7 s pass. (A fresh-thread
    spawn appeared to fix it first, but that probe also changed the
    test id env var - confounder, wrong attribution, reverted.) A
    constant minimal env makes such children behave the same under
    every host context (pytest, MCP server, campaign runner, shell)
    instead of a per-context lottery.

    Superseded in part (pa1 bisect, 2026-09-02): the 100% "spin" seen
    under the MCP server was NOT the env block - the child inherited
    the server's stdin pipe while the stdio transport held a read on
    it, and Windows blocks the child's start-up stdin probe on that
    pending read. Vendor spawns now pass stdin=DEVNULL; the constant
    env is kept because it is harmless and still removes the pytest
    context dependence recorded above.
    """
    keep: dict = {}
    for k in ("SystemRoot", "SystemDrive", "windir", "ComSpec",
              "TEMP", "TMP", "NUMBER_OF_PROCESSORS"):
        v = os.environ.get(k)
        if v:
            keep[k] = v
    if extra:
        keep.update(extra)
    return keep


BELOW_NORMAL_PRIORITY_CLASS = 0x00004000


def _kernel32():
    """kernel32 with the HANDLE / DWORD_PTR signatures declared. Without
    them ctypes treats every HANDLE as a 32-bit int: GetCurrentProcess()'s
    pseudo handle (-1) came back truncated to 0xFFFFFFFF, and the
    priority / affinity calls on it failed silently - the uvicorn tree
    root printed "cpu-limited to 4 core(s)" from 2026-08 on while running
    on all 32 cores at Normal priority (measured 2026-09-06: an MCP child
    used 20 cores over 30 s during a live cell)."""
    import ctypes
    import ctypes.wintypes as wt
    k32 = ctypes.windll.kernel32
    k32.GetCurrentProcess.restype = ctypes.c_void_p
    k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
    k32.OpenProcess.restype = ctypes.c_void_p
    k32.CloseHandle.argtypes = [ctypes.c_void_p]
    k32.CloseHandle.restype = wt.BOOL
    k32.SetPriorityClass.argtypes = [ctypes.c_void_p, wt.DWORD]
    k32.SetPriorityClass.restype = wt.BOOL
    k32.GetPriorityClass.argtypes = [ctypes.c_void_p]
    k32.GetPriorityClass.restype = wt.DWORD
    k32.SetProcessAffinityMask.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
    k32.SetProcessAffinityMask.restype = wt.BOOL
    k32.GetProcessAffinityMask.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(ctypes.c_size_t),
        ctypes.POINTER(ctypes.c_size_t)]
    k32.GetProcessAffinityMask.restype = wt.BOOL
    return k32


def cpu_state(pid: int | None = None) -> dict | None:
    """Read back {priority_class, affinity_mask, system_mask} of a process
    (None off Windows / when the process cannot be opened)."""
    if os.name != "nt":
        return None
    import ctypes
    k32 = _kernel32()
    if pid is None:
        handle, close = k32.GetCurrentProcess(), False
    else:
        handle = k32.OpenProcess(0x1000, False, int(pid))   # QUERY_LIMITED
        if not handle:
            return None
        close = True
    try:
        pm, sm = ctypes.c_size_t(), ctypes.c_size_t()
        ok = k32.GetProcessAffinityMask(handle, ctypes.byref(pm), ctypes.byref(sm))
        return {"priority_class": int(k32.GetPriorityClass(handle)),
                "affinity_mask": int(pm.value) if ok else None,
                "system_mask": int(sm.value) if ok else None}
    finally:
        if close:
            k32.CloseHandle(handle)


def limit_cpu(pid: int | None = None) -> str | None:
    """Best-effort CPU cap: BelowNormal priority + affinity to the first
    ``cpu_limit_cores()`` cores. pid=None limits the CURRENT process
    (children inherit the affinity mask). Returns a note that states what
    the kernel actually reports afterwards, or None when the cap is off /
    not applicable / refused (the note names a refusal instead of
    claiming success)."""
    if os.name != "nt":
        return None
    n = cpu_limit_cores()
    if n <= 0:
        return None
    n = min(n, os.cpu_count() or n)
    k32 = _kernel32()
    if pid is None:
        handle, close = k32.GetCurrentProcess(), False
    else:
        # PROCESS_SET_INFORMATION | PROCESS_QUERY_LIMITED_INFORMATION
        handle = k32.OpenProcess(0x0200 | 0x1000, False, int(pid))
        if not handle:
            return None
        close = True
    try:
        ok_prio = bool(k32.SetPriorityClass(handle, BELOW_NORMAL_PRIORITY_CLASS))
        mask = (1 << n) - 1
        ok_aff = bool(k32.SetProcessAffinityMask(handle, mask))
    finally:
        if close:
            k32.CloseHandle(handle)
    state = cpu_state(pid) or {}
    got_mask = state.get("affinity_mask")
    got_prio = state.get("priority_class")
    if ok_prio and ok_aff and got_mask == mask and got_prio == BELOW_NORMAL_PRIORITY_CLASS:
        return f"cpu-limited to {n} core(s) at BelowNormal"
    return (f"cpu cap NOT applied (priority ok={ok_prio}, affinity ok={ok_aff}, "
            f"mask now {got_mask!r}, priority class now {got_prio!r})")
