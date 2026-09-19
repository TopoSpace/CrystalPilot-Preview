"""Round-3 WP1: the layered status envelope every tool result carries under
summary[STATUS_KEY] - did it run, what did it change, what does it say -
plus T-k's situation_report mask block."""
from __future__ import annotations

import sys
import threading
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from crystalpilot.core.events import RunStore  # noqa: E402
from crystalpilot.tools.base import (STATUS_KEY, Tool, ToolContext,  # noqa: E402
                                     ToolRegistry, ToolResult, attach_status,
                                     invoke, status_of)
from crystalpilot.tools.budget import BudgetExceeded, Cancelled  # noqa: E402


class _Base(Tool):
    description = "test tool"
    params_schema = {"type": "object", "properties": {"x": {"type": "integer"}}}


class Ok(_Base):
    name = "t_ok"

    def run(self, ctx, **p):
        return ToolResult(ok=True, summary={"x": p.get("x", 0), "job_dir": "C:/jobs/1"},
                          artifacts={"res": "C:/jobs/1/a.res"})


class NoChange(_Base):
    name = "t_nochange"

    def run(self, ctx, **p):
        return ToolResult(ok=True, summary={"added": [], "no_state_change": True,
                                            "no_change_reason": "nothing on density"})


class Sci(_Base):
    name = "t_sci"

    def run(self, ctx, **p):
        return ToolResult(ok=True, summary={
            "scientific_outcome": {"verdict": "inconclusive",
                                   "reasons": ["series did not settle"],
                                   "measured_by": "mask series"},
            "applicability": ["only while the mask is active"]})


class Boom(_Base):
    name = "t_boom"

    def run(self, ctx, **p):
        raise RuntimeError("kaput")


class Budget(_Base):
    name = "t_budget"

    def run(self, ctx, **p):
        raise BudgetExceeded("search", 12.0, 10.0)


class Gone(_Base):
    name = "t_gone"

    def run(self, ctx, **p):
        raise Cancelled("search", 1.0)


class Partial(_Base):
    name = "t_partial"

    def run(self, ctx, **p):
        return ToolResult(ok=True, summary={"rows": [1], "timeout": "tested 1 of 3"})


class Refused(_Base):
    name = "t_refused"

    def run(self, ctx, **p):
        return ToolResult.failure("nope")


def _reg():
    r = ToolRegistry()
    for t in (Ok(), NoChange(), Sci(), Boom(), Budget(), Gone(), Partial(), Refused()):
        r.register(t)
    return r


def _ctx(tmp_path, cancel=None):
    return ToolContext(store=RunStore(tmp_path / "runs"), session=None,
                       cancel_event=cancel)


def env_of(r: ToolResult) -> dict[str, Any]:
    return r.summary[STATUS_KEY]


class TestExecution:
    def test_ran_with_artifact_index_and_untouched_wire_shape(self, tmp_path):
        r = invoke(_reg(), _ctx(tmp_path), "t_ok", {"x": 3})
        assert r.ok and r.error is None and r.summary["x"] == 3
        e = env_of(r)
        assert e["execution"] == "ran"
        assert e["no_change"] == {"value": False, "reason": None}
        assert e["scientific_outcome"] is None and e["applicability"] == []
        assert e["artifact_index"] == {"res": "C:/jobs/1/a.res", "job_dir": "C:/jobs/1"}
        # project-level state_changed is not this layer's business
        assert e["state_changed"] is None

    def test_exception_is_failed_and_keeps_the_old_error_shape(self, tmp_path):
        r = invoke(_reg(), _ctx(tmp_path), "t_boom", {})
        assert r.ok is False and r.error == "RuntimeError: kaput"
        assert "traceback" in r.summary
        assert env_of(r)["execution"] == "failed"

    def test_refusal_is_failed_too(self, tmp_path):
        r = invoke(_reg(), _ctx(tmp_path), "t_refused", {})
        assert r.ok is False and r.error == "nope"
        assert env_of(r)["execution"] == "failed"

    def test_unknown_parameter_refusal_carries_an_envelope(self, tmp_path):
        r = invoke(_reg(), _ctx(tmp_path), "t_ok", {"y": 1})
        assert r.ok is False and "unknown parameter" in r.error
        assert env_of(r)["execution"] == "failed"

    def test_budget_and_cancellation(self, tmp_path):
        assert env_of(invoke(_reg(), _ctx(tmp_path), "t_budget", {}))["execution"] == "timeout"
        assert env_of(invoke(_reg(), _ctx(tmp_path), "t_gone", {}))["execution"] == "cancelled"
        # a budgeted loop's partial ok:true result reads as timeout, not ran
        r = invoke(_reg(), _ctx(tmp_path), "t_partial", {})
        assert r.ok and env_of(r)["execution"] == "timeout"
        # the client gave up mid-call: cancelled even though the tool finished
        ev = threading.Event()
        ev.set()
        r = invoke(_reg(), _ctx(tmp_path, cancel=ev), "t_ok", {})
        assert r.ok and env_of(r)["execution"] == "cancelled"


class TestLayers:
    def test_no_change_is_derived_from_the_tool_flag(self, tmp_path):
        r = invoke(_reg(), _ctx(tmp_path), "t_nochange", {})
        assert r.ok
        assert env_of(r)["no_change"] == {"value": True, "reason": "nothing on density"}
        # the input flag survives for the project layer (it decides not to commit)
        assert r.summary["no_state_change"] is True

    def test_scientific_outcome_and_applicability_move_under_the_envelope(self, tmp_path):
        r = invoke(_reg(), _ctx(tmp_path), "t_sci", {})
        e = env_of(r)
        assert e["scientific_outcome"] == {"verdict": "inconclusive",
                                           "reasons": ["series did not settle"],
                                           "measured_by": "mask series"}
        assert e["applicability"] == ["only while the mask is active"]
        assert "scientific_outcome" not in r.summary
        assert "applicability" not in r.summary

    def test_attach_is_idempotent_and_normalises_verdicts(self):
        r = ToolResult(ok=True, summary={"scientific_outcome": {"verdict": "maybe"}})
        attach_status(r, "ran")
        first = dict(env_of(r))
        assert first["scientific_outcome"]["verdict"] == "inconclusive"
        attach_status(r, "ran")
        assert env_of(r) == first
        assert status_of(ToolResult(ok=True, summary={})) == {}
        bad = ToolResult(ok=True, summary={})
        attach_status(bad, "weird")
        assert env_of(bad)["execution"] == "failed"

    def test_envelope_never_shadows_the_flat_metrics(self, tmp_path):
        # the UI's tail parser looks for ok / node / r1 breadth-first and
        # skips NON_METRIC containers; nothing inside the envelope may
        # carry those names at any depth
        r = invoke(_reg(), _ctx(tmp_path), "t_ok", {"x": 1})

        def keys(o):
            if isinstance(o, dict):
                for k, v in o.items():
                    yield k
                    yield from keys(v)
            elif isinstance(o, list):
                for v in o:
                    yield from keys(v)
        assert not {"ok", "node", "r1", "wr2", "goof"} & set(keys(env_of(r)))


class TestProjectStateChange:
    """The project layer fills state_changed from the node store."""

    @pytest.fixture()
    def project(self, tmp_path):
        from tests.test_probe_site import ATOMS_A, CELL_A, make_project, _open
        return _open(make_project(tmp_path, CELL_A, "P -1", ATOMS_A, ATOMS_A,
                                  z=2, d_min=0.75))

    def test_read_only_tool_changes_nothing(self, project):
        before = project.nodes.state()["active_node"]
        r = project.invoke_tool("list_nodes", {})
        assert r.ok
        sc = env_of(r)["state_changed"]
        assert sc == {"changed": False, "node_before": before,
                      "node_after": before, "revision_after": None}

    def test_refine_commits_a_node_and_says_so(self, project):
        before = project.nodes.state()["active_node"]
        r = project.invoke_tool("refine", {"n_cycles": 2})
        assert r.ok, r.error
        sc = env_of(r)["state_changed"]
        assert sc["changed"] is True
        assert sc["node_before"] == before
        assert sc["node_after"] == r.summary["node"] != before
        assert isinstance(sc["revision_after"], int)
        assert env_of(r)["execution"] == "ran"


class TestMaskBlock:
    def test_reads_what_solvent_mask_stores(self):
        from crystalpilot.refine.tools_analysis import solvent_mask_block
        assert solvent_mask_block({}) is None
        flags = {"f_mask": object(), "solvent_mask_info": {
            "mask_id": "abc", "computed_at": "2026-09-05T20:00:00",
            "n_voids": 2, "n_voids_masked": 1,
            "total_solvent_electrons_per_cell": 154.2,
            "solvent_volume_A3": 812.5, "solvent_volume_pct_of_cell": 31.4,
            "solvent_mask_converged": False, "voids": [{"x": 1}]}}
        b = solvent_mask_block(flags)
        assert b == {"active": True, "void_electrons_per_cell": 154.2,
                     "void_volume_A3": 812.5, "void_volume_pct_of_cell": 31.4,
                     "n_voids": 2, "n_voids_masked": 1, "converged": False,
                     "mask_id": "abc", "computed_at": "2026-09-05T20:00:00"}
        # a mask without its summary says so instead of pretending
        b = solvent_mask_block({"f_mask": object()})
        assert b["active"] is True and "rerun solvent_mask" in b["note"]
