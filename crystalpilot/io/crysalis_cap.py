"""High-level autonomous CrysAlisPro reduction over LISTEN MODE.

The verified chain (live bring-up 2026-09-01, zn_dpnpp frames - see the
cap-listen-reduction knowledge card for the evidence trail):

    xx selectexpnogui <exp.par>     open the experiment (~2 s)
    ph snogui                       peak hunt (~20 s / 1100 frames)
    um twinttt                      Duisenberg direct-space multi-domain
                                    indexing (um f reciprocal-space fails
                                    on contaminated peak tables)
    um i                            refine the current (component-1) UB
    dc proffit auto                 dialog-free reduction (~4 min)

Product: <name>_autored.hkl (+ .cif_od/.errmod/red.sum) in the
experiment directory. On the reference twin this beat the author's own
reduction AND the published data (transplant R1 0.0747 vs 0.0811 /
0.0904).

Hard-won constraints (do not "simplify"):

* Wizard commands (dc proffittwin / dc proffitrrptwin / dc xmlrrp) pop
  a modal assistant - the AUTO suffix is NOT accepted there. Driving
  them needs the BM_CLICK chain in workdir/cap_tune1/drive_wizard.ps1;
  they are deliberately outside this module.
* ``xx savetext`` opens a bitmap save dialog (it saves GRAPHICS) and
  wedges the channel. Never send it.
* A silent redLOG does NOT mean a hang; a hang is diagnosed by CPU burn
  rate (integration saturates a core, a modal dialog burns ~0). The
  watchdog below implements exactly that discriminator.
* ``dc autoanalyse`` is an acquisition-time hook: offline it waits for
  new data and no-ops.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .crysalis_listen import ListenModeClient, ListenResult


def _cap_cpu_seconds() -> float | None:
    """Total CPU seconds of the pro.exe process (None if not found)."""
    import subprocess
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='pro.exe'\" | "
             "ForEach-Object { ($_.KernelModeTime + $_.UserModeTime) / 1e7 }"],
            capture_output=True, text=True, timeout=30)
        vals = [float(x) for x in out.stdout.split()]
        return sum(vals) if vals else None
    except Exception:  # noqa: BLE001 - diagnostics only
        return None


@dataclass
class StepResult:
    name: str
    command: str
    status: str
    elapsed_s: float
    detail: str = ""
    log_extract: list[str] = field(default_factory=list)


class HangSuspected(RuntimeError):
    """Busy channel + near-zero CAP CPU burn: almost certainly a modal
    dialog is waiting (possibly invisible while the main window is
    hidden). Enumerate windows (workdir/cap_tune1/listallwin.ps1) and
    WM_CLOSE the dialog; the channel then reports done/error."""


def send_watched(client: ListenModeClient, command: str,
                 timeout_s: float = 3600.0,
                 hang_after_s: float = 90.0,
                 min_burn_ratio: float = 0.05,
                 burn_check_interval_s: float = 45.0,
                 poll_s: float = 2.0) -> ListenResult:
    """client.send() with the CPU-burn hang discriminator.

    After ``hang_after_s`` of busy, compare CAP CPU growth to wall time;
    below ``min_burn_ratio`` (5% of one core) raise HangSuspected instead
    of silently waiting out the timeout."""
    root = client.root
    t0 = time.monotonic()
    client._clear_markers()
    (root / "command.in").write_text(command.strip() + "\n",
                                     encoding="ascii")
    cpu0 = mark = None
    while True:
        el = time.monotonic() - t0
        if (root / "command.done").exists():
            return ListenResult("done", el)
        if (root / "command.error").exists():
            return ListenResult("error", el, "CAP reported command failure")
        if el > timeout_s:
            return ListenResult("timeout", el, "gave up waiting")
        if el > hang_after_s:
            if cpu0 is None:
                cpu0, mark = _cap_cpu_seconds(), el
            elif el - mark > burn_check_interval_s:
                cpu1 = _cap_cpu_seconds()
                if cpu0 is not None and cpu1 is not None:
                    burn = (cpu1 - cpu0) / (el - mark)
                    if burn < min_burn_ratio:
                        raise HangSuspected(
                            f"'{command}': busy {el:.0f}s but CAP burned "
                            f"only {cpu1 - cpu0:.1f} CPU-s in the last "
                            f"{el - mark:.0f}s - a modal dialog is likely "
                            "waiting (see HangSuspected docstring)")
                cpu0, mark = cpu1, el
        time.sleep(poll_s)


_STEPS: list[tuple[str, str, float]] = [
    ("open", "xx selectexpnogui {par}", 180.0),
    ("peaks", "ph snogui", 1200.0),
    ("index", "um twinttt", 1200.0),
    ("refine", "um i", 600.0),
    ("reduce", "dc proffit auto", 5400.0),
]

_LOG_MARKS = {
    "peaks": (r"(\d+) peak locations are merged to (\d+) profiles",
              r"Peak table: (\d+) peaks"),
    "index": (r"Best cell:\s+(\d+) indexed[^:]*:\s*(.+)",),
    "refine": (r"UB fit with (\d+) obs out of (\d+)",),
    "reduce": (r"^ inf-\S+\s+\d+\s+\d+\s+\d+\s+[\d.]+.*",
               r"Reduction sum: (.+)"),
}


def _latest_redlog(exp_dir: Path) -> Path | None:
    logs = sorted((exp_dir / "log").glob("crysalispro_redLOG*"),
                  key=lambda p: p.stat().st_mtime)
    return logs[-1] if logs else None


def cap_reduce(exp_par: Path | str,
               client: ListenModeClient | None = None,
               progress: Callable[[str], None] | None = None) -> dict[str, Any]:
    """Run the full verified reduction chain on an experiment .par.

    Returns {"ok", "steps": [StepResult...], "hkl": path-or-None,
    "log_tail": str}. Raises HangSuspected if a step wedges on a modal
    dialog (caller decides how to clear it)."""
    # ABSOLUTE path or CAP resolves against its own cwd and errors out -
    # the same trap as olex2c's relative `reap` (live-caught both times)
    exp_par = Path(exp_par).resolve()
    exp_dir = exp_par.parent
    client = client or ListenModeClient()
    if not client.channel_alive():
        return {"ok": False, "steps": [],
                "error": f"listen channel missing at {client.root}"}
    steps: list[StepResult] = []
    log_before = _latest_redlog(exp_dir)
    off0 = log_before.stat().st_size if log_before else 0
    for name, tmpl, tmo in _STEPS:
        cmd = tmpl.format(par=str(exp_par).replace("/", "\\"))
        if progress:
            progress(f"cap_reduce[{name}]: {cmd}")
        r = send_watched(client, cmd, timeout_s=tmo)
        sr = StepResult(name, cmd, r.status, round(r.elapsed_s, 1),
                        r.detail)
        # per-step evidence from the redLOG delta
        log = _latest_redlog(exp_dir)
        if log is not None:
            text = log.read_text(encoding="utf-8", errors="replace")
            delta = text[off0:] if log == log_before else text
            off0, log_before = len(text), log
            pats = _LOG_MARKS.get(name, ())
            for pat in pats:
                for m in re.finditer(pat, delta, re.M):
                    sr.log_extract.append(m.group(0).strip()[:160])
        steps.append(sr)
        if r.status != "done":
            return {"ok": False, "steps": steps,
                    "error": f"step '{name}' {r.status}: {r.detail}"}
    hkl = sorted(exp_dir.glob("*_autored.hkl"),
                 key=lambda p: p.stat().st_mtime)
    return {"ok": True, "steps": steps,
            "hkl": str(hkl[-1]) if hkl else None,
            "n_hkl_rows": (sum(1 for _ in open(hkl[-1], errors="replace"))
                           if hkl else 0)}
