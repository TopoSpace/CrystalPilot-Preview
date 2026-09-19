"""The MCP server must notice when its stdio client is gone.

ka1 org-tools (2026-09-04): the MCP process of a campaign case that had
ended by the 7200 s timeout was found 9.6 h later still burning one core
(518 CPU-min); codex had exited and the pipe was broken, but nothing in the
server looked. These tests pin the three layers of the fix in
crystalpilot/mcp/server.py: the non-destructive pipe probe, the pure
watchdog rule, and the real exit path (pipe + thread + os._exit) in a
subprocess that never touches cctbx."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PY = sys.executable


def _env():
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONPATH"] = str(REPO)
    return env


# --- the pure rule -----------------------------------------------------------

class _Handle:
    def __init__(self, running=None, budget=None):
        self._running = running
        self._running_budget_s = budget
        self.project_dir = Path(".")


def test_orphan_step_waits_while_the_client_is_there():
    from crystalpilot.mcp import server as s
    h = _Handle(running=("solve_charge_flipping", 100.0))
    assert s._orphan_step(h, False, None, 1000.0) == (None, None)
    # a transient close followed by a live probe resets the clock
    since, rec = s._orphan_step(h, True, None, 1000.0)
    assert since == 1000.0 and rec is None
    assert s._orphan_step(h, False, since, 1001.0) == (None, None)


def test_orphan_step_gives_a_running_tool_the_grace_then_abandons_it():
    from crystalpilot.mcp import server as s
    h = _Handle(running=("solve_charge_flipping", 100.0), budget=900.0)
    t0 = 5000.0
    since, rec = s._orphan_step(h, True, None, t0)
    assert since == t0 and rec is None
    _, rec = s._orphan_step(h, True, since, t0 + s.ORPHAN_GRACE_S - 1)
    assert rec is None, "inside the grace the tool may still finish itself"
    _, rec = s._orphan_step(h, True, since, t0 + s.ORPHAN_GRACE_S + 0.5)
    assert rec["action"] == "exit_abandoning_tool"
    assert rec["running_tool"] == "solve_charge_flipping"
    assert rec["budget_s"] == 900.0
    assert rec["elapsed_s"] == pytest.approx(t0 + s.ORPHAN_GRACE_S + 0.5 - 100.0)


def test_orphan_step_idle_server_exits_after_one_poll():
    from crystalpilot.mcp import server as s
    h = _Handle()
    since, rec = s._orphan_step(h, True, None, 10.0)
    assert rec is None
    _, rec = s._orphan_step(h, True, since, 10.0 + s.ORPHAN_POLL_S)
    assert rec == {"running_tool": None, "waited_s": s.ORPHAN_POLL_S,
                   "action": "exit_idle"}


# --- the probe ---------------------------------------------------------------

@pytest.mark.skipif(os.name != "nt", reason="pipe probe is the Windows path")
def test_transport_closed_sees_a_broken_stdin_pipe_but_not_an_open_one():
    code = ("import sys; sys.stdin.buffer.read(); "
            "import crystalpilot.mcp.server as s; print(s.transport_closed())")
    p = subprocess.Popen([PY, "-X", "utf8", "-c", code], stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, cwd=str(REPO), env=_env())
    out, _ = p.communicate(input=b"hello\n", timeout=120)
    assert out.decode().strip() == "True"

    code = "import crystalpilot.mcp.server as s; print(s.transport_closed())"
    p = subprocess.Popen([PY, "-X", "utf8", "-c", code], stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, cwd=str(REPO), env=_env())
    try:
        out = p.stdout.readline().decode().strip()      # pipe still open here
    finally:
        p.stdin.close()
        p.wait(timeout=60)
    assert out == "False"


def test_transport_closed_is_false_for_a_file_stdin(tmp_path):
    f = tmp_path / "in.txt"
    f.write_text("x\n")
    code = "import crystalpilot.mcp.server as s; print(s.transport_closed())"
    with f.open("rb") as fh:
        out = subprocess.run([PY, "-X", "utf8", "-c", code], stdin=fh,
                             capture_output=True, cwd=str(REPO), env=_env(),
                             timeout=120).stdout.decode().strip()
    assert out == "False", "not a pipe = unknown, never 'closed'"


# --- the real exit path ------------------------------------------------------

def test_watchdog_exits_an_orphaned_server_and_leaves_evidence(tmp_path):
    """A server whose tool is mid-flight when the client vanishes: the
    watchdog waits the grace, writes the evidence line and _exits(3)."""
    proj = tmp_path / "proj"
    proj.mkdir()
    driver = f"""
import sys, time, threading
import crystalpilot.mcp.server as s
s.ORPHAN_POLL_S = 0.5
s.ORPHAN_GRACE_S = 1.5
h = s.ProjectHandle(__import__('pathlib').Path({str(proj)!r}))
h._running = ("solve_charge_flipping", time.time() - 42.0)
h._running_budget_s = 900.0
s.start_transport_watchdog(h)
print("armed", flush=True)
time.sleep(60)          # the 'tool that cannot check the clock'
print("watchdog did not fire", flush=True)
"""
    p = subprocess.Popen([PY, "-X", "utf8", "-c", driver], stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         cwd=str(REPO), env=_env())
    assert p.stdout.readline().decode().strip() == "armed"
    t0 = time.time()
    p.stdin.close()                       # the client is gone
    rc = p.wait(timeout=60)
    dt = time.time() - t0
    err = p.stderr.read().decode(errors="replace")
    assert rc == 3, err
    assert dt < 20, f"took {dt:.1f}s"
    lines = [json.loads(ln) for ln in
             (proj / ".crystalpilot" / "mcp_server.jsonl").read_text(
                 encoding="utf-8").splitlines()]
    ev = [ln for ln in lines if ln.get("event") == "transport_closed"]
    assert len(ev) == 1
    assert ev[0]["running_tool"] == "solve_charge_flipping"
    assert ev[0]["action"] == "exit_abandoning_tool"
    assert ev[0]["budget_s"] == 900.0
    assert ev[0]["elapsed_s"] >= 42.0
    assert "transport closed" in err


def test_watchdog_leaves_a_server_with_a_live_client_alone(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    driver = f"""
import sys, time
import crystalpilot.mcp.server as s
s.ORPHAN_POLL_S = 0.2
s.ORPHAN_GRACE_S = 0.5
h = s.ProjectHandle(__import__('pathlib').Path({str(proj)!r}))
h._running = ("refine", time.time())
s.start_transport_watchdog(h)
print("armed", flush=True)
time.sleep(3)
print("still here", flush=True)
"""
    p = subprocess.Popen([PY, "-X", "utf8", "-c", driver], stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                         cwd=str(REPO), env=_env())
    try:
        assert p.stdout.readline().decode().strip() == "armed"
        assert p.stdout.readline().decode().strip() == "still here"
        assert p.wait(timeout=60) == 0
    finally:
        p.stdin.close()
    assert not (proj / ".crystalpilot" / "mcp_server.jsonl").exists()
