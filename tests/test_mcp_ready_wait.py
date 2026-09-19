"""ProjectSession._await_mcp_ready: the first turn of a fresh/resumed thread
waits for the crystalpilot MCP to register its tools (bounded), narrating
the wait as mcp_startup events. No app-server: mcp_status is stubbed."""
import sys
import types
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from crystalpilot.workbench.service import ProjectSession  # noqa: E402


def _session(statuses, monkeypatch):
    ps = object.__new__(ProjectSession)
    pushed = []
    seq = iter(statuses)
    last = {"v": statuses[-1]}

    def mcp_status(self, timeout_s=20.0):
        try:
            last["v"] = next(seq)
        except StopIteration:
            pass
        return dict(last["v"])

    monkeypatch.setattr(ProjectSession, "mcp_status", mcp_status)
    ps._push = lambda thread_id, ev: pushed.append(dict(ev, thread_id=thread_id))
    logged = []
    ps.wb = types.SimpleNamespace(
        _log_event=lambda thread_id, ev: logged.append(ev) or 1)
    ps._logged = logged
    monkeypatch.setattr(ProjectSession, "MCP_POLL_S", 0.01)
    monkeypatch.setattr(ProjectSession, "MCP_ABSENT_GIVEUP_S", 0.05)
    monkeypatch.setattr(ProjectSession, "MCP_READY_WAIT_S", 0.5)
    task = types.SimpleNamespace(task_id="task_x", awaiting_mcp=True)
    return ps, task, pushed


ABSENT = {"present": False, "n_tools": 0, "error": None}
STARTING = {"present": True, "n_tools": 0, "error": None}
READY = {"present": True, "n_tools": 70, "error": None}


def test_already_registered_costs_nothing(monkeypatch):
    ps, task, pushed = _session([READY], monkeypatch)
    ps._await_mcp_ready("t1", task)
    assert pushed == [] and task.awaiting_mcp is False


def test_waits_through_startup_then_reports_ready(monkeypatch):
    ps, task, pushed = _session([ABSENT, STARTING, STARTING, READY], monkeypatch)
    ps._await_mcp_ready("t1", task)
    kinds = [(e["kind"], e["status"]) for e in pushed]
    assert kinds == [("mcp_startup", "waiting"), ("mcp_startup", "ready")]
    assert pushed[-1]["n_tools"] == 70 and pushed[-1]["thread_id"] == "t1"
    assert task.awaiting_mcp is False
    # the same rows went to the transcript first (eid identity on reload)
    assert [e["status"] for e in ps._logged] == ["waiting", "ready"]


def test_a_server_that_never_appears_is_given_up_quickly(monkeypatch):
    ps, task, pushed = _session([ABSENT], monkeypatch)
    ps._await_mcp_ready("t1", task)
    assert [e["status"] for e in pushed] == ["waiting", "timeout"]
    assert pushed[-1]["present"] is False


def test_a_listed_server_that_never_registers_tools_times_out(monkeypatch):
    ps, task, pushed = _session([STARTING], monkeypatch)
    ps._await_mcp_ready("t1", task)
    assert [e["status"] for e in pushed] == ["waiting", "timeout"]
    assert pushed[-1]["present"] is True


def test_only_the_first_turn_waits(monkeypatch):
    ps, task, pushed = _session([ABSENT], monkeypatch)
    task.awaiting_mcp = False
    ps._await_mcp_ready("t1", task)
    assert pushed == []
