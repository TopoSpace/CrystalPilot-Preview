"""Vendor/child spawns must not inherit the MCP server's stdin.

The MCP stdio transport keeps a synchronous ReadFile pending on the
server's stdin pipe for the whole life of a tool call. A child that
inherits that handle and probes stdin at start-up (the Intel Fortran
runtime behind superflip, and any python.exe) blocks on the pipe's
serialised I/O until the next JSON-RPC message - which cannot arrive
while the tool call is running. That is how every agent-driven superflip
call from r16 to pa1 (17/17) burned its full timeout with 0 bytes of
output while the identical input converged in ~20 s from a shell; the
env-block theory in procutil.canonical_child_env was a misattribution
(pa1 bisect 2026-09-02). cmd.exe and SHELXL happen not to probe stdin,
which is why only superflip and python children showed it.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

# a parent that holds a pending read on its own stdin pipe (the transport
# shape) and spawns a python child with stdin DETACHED
_CHILD = textwrap.dedent("""
    import subprocess, sys, threading, time
    threading.Thread(target=lambda: sys.stdin.buffer.read(1),
                     daemon=True).start()
    time.sleep(0.3)
    p = subprocess.run([sys.executable, "-c", "print(1)"],
                       stdin=subprocess.DEVNULL, capture_output=True,
                       text=True, timeout=30)
    sys.stdout.write("OK" if p.stdout.strip() == "1" else "BAD")
    sys.stdout.flush()
    os = __import__("os"); os._exit(0)
""")


@pytest.mark.skipif(os.name != "nt", reason="Windows pipe semantics")
def test_detached_python_child_starts_under_pending_stdin_read():
    p = subprocess.Popen([sys.executable, "-c", _CHILD],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL, text=True)
    try:
        out, _ = p.communicate(timeout=90)
    finally:
        if p.poll() is None:
            p.kill()
    assert out.strip() == "OK"


def _spawn_sites(path: Path) -> list[str]:
    """Text of every subprocess.run(...)/Popen(...) call in a source file."""
    src = path.read_text(encoding="utf-8")
    sites = []
    for m in re.finditer(r"subprocess\.(?:run|Popen)\(", src):
        depth, i = 1, m.end()
        while depth and i < len(src):
            depth += {"(": 1, ")": -1}.get(src[i], 0)
            i += 1
        sites.append(src[m.start():i])
    return sites


@pytest.mark.parametrize("rel", [
    "crystalpilot/tools/solution_tools.py",
    "crystalpilot/refine/tools_shelxl.py",
    "crystalpilot/io/frames_dials.py",
])
def test_vendor_and_python_spawns_detach_stdin(rel):
    sites = [s for s in _spawn_sites(REPO / rel)
             if "str(exe)" in s or "SUPERFLIP_EXE" in s or "python" in s]
    assert sites, f"no vendor/python spawn sites found in {rel}"
    missing = [s.splitlines()[0] for s in sites
               if "stdin=subprocess.DEVNULL" not in s]
    assert not missing, f"{rel}: spawn inherits stdin: {missing}"


def test_superflip_tool_passes_devnull_stdin(monkeypatch, tmp_path):
    """The tool itself, not just the source text: intercept the launch."""
    from cctbx import crystal, xray
    from cctbx.array_family import flex

    from crystalpilot.core.dataset import ReflectionDataset
    from crystalpilot.pipeline.session import SolveSession
    from crystalpilot.tools import solution_tools as st
    from crystalpilot.tools.base import ToolContext

    cs = crystal.symmetry(unit_cell=(7.0, 8.0, 9.0, 80.0, 85.0, 95.0),
                          space_group_symbol="P -1")
    xs = xray.structure(crystal_symmetry=cs)
    uc = cs.unit_cell()
    for label, el, cart in (("S1", "S", (1.2, 1.5, 2.0)),
                            ("O1", "O", (2.7, 1.9, 2.6)),
                            ("C1", "C", (3.9, 3.0, 3.4))):
        xs.add_scatterer(xray.scatterer(
            label=label, site=uc.fractionalize(cart),
            scattering_type=el, u=0.02))
    xs.scattering_type_registry(table="it1992")
    fc = xs.structure_factors(d_min=0.8).f_calc()
    fo_sq = fc.intensities().customized_copy(
        sigmas=flex.double(fc.size(), 1.0)) \
        .set_observation_type_xray_intensity()
    ses = SolveSession(dataset=ReflectionDataset(intensities=None,
                                                 wavelength=0.71073))
    ses.symmetry = cs
    ses.fo_sq = fo_sq

    class _Store:
        def record(self, *a, **k):
            return None

        def log(self, *a, **k):
            return None

    seen: dict = {}

    def fake_run(cmd, **kw):
        seen.update(kw)
        raise subprocess.TimeoutExpired(cmd, 1)

    monkeypatch.setattr(st.subprocess, "run", fake_run)
    monkeypatch.setattr(st, "SUPERFLIP_EXE", Path(sys.executable))
    monkeypatch.setattr(st, "_completeness_guard", lambda *a, **k: None)
    monkeypatch.setattr(st, "REPO_ROOT", tmp_path)
    r = st.SolveSuperflip().run(ToolContext(store=_Store(), session=ses),
                                timeout_s=1)
    assert not r.ok
    assert seen.get("stdin") is subprocess.DEVNULL
    # a launch that never produced anything is reported as such, not as
    # "spun without iterating"
    assert "never started computing" in (r.error or "")
