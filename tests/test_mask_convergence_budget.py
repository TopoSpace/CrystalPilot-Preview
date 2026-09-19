"""solvent_mask converges by default, under a wall-clock budget.

reg1-mof hex-full-r1 (2026-09-04): the same framework model refined to
R1 0.134 with a 30-cycle mask and 0.083 with an 800-cycle one (mask-swap
experiment, SHELXL L.S. 0). WP1's BUDGET sentence had told the agent that
an unconverged mask was "honest, not a failure" and to lower max_cycles;
the tool now defaults high enough to converge and stops itself on wall
clock instead."""
from __future__ import annotations

from types import SimpleNamespace

from crystalpilot.tools.budget import BUDGET_PARAMS, BudgetExceeded
from crystalpilot.tools.mask_tools import BypassMask, SolventMask

from test_mask_bypass import _framework_and_solvent


def _ctx():
    model, fo_sq = _framework_and_solvent()
    ses = SimpleNamespace(model=model, fo_sq=fo_sq, flags={})
    return SimpleNamespace(session=ses, store=None, progress=None), ses


def test_schema_defaults_favour_convergence():
    t = SolventMask()
    props = t.params_schema["properties"]
    assert props["max_cycles"]["default"] >= 500
    assert "timeout_s" in props
    assert BUDGET_PARAMS["solvent_mask"]["timeout_s"] >= 300
    d = t.description
    assert "lower max_cycles" not in d
    assert "UPPER bound" in d and "LOWER bound" in d
    assert "honest, not a failure" not in d


def test_stop_check_ends_the_loop_and_keeps_the_best_cycle():
    model, fo_sq = _framework_and_solvent()
    m = BypassMask(model, fo_sq, use_set_completion=True)
    m.compute(solvent_radius=1.2, shrink_truncation_radius=1.2,
              resolution_factor=0.25)
    calls = []

    def stop(i):
        calls.append(i)
        if i >= 3:
            raise BudgetExceeded("BYPASS", 1.0, 1.0)

    f = m.structure_factors(max_cycles=50, stop_check=stop)
    assert f is not None
    assert m.n_cycles == 3
    assert m.stopped_by == "budgetexceeded"
    assert m.converged is False
    assert calls == [1, 2, 3]


def test_tool_reports_the_budget_stop_with_advice():
    ctx, ses = _ctx()
    # a budget no cycle can fit in: the check after cycle 1 already expires
    r = SolventMask().run(ctx, timeout_s=0.001, max_cycles=400)
    assert r.ok, r.error
    s = r.summary
    assert s["solvent_mask_converged"] is False
    assert s["bypass"]["stopped_by"] == "budgetexceeded"
    assert s["bypass"]["cycles_run"] == 1
    assert s["budget"]["timeout_s"] == 0.001
    assert s["budget"]["stopped_by"] == "timeout"
    assert "UPPER bound" in s["convergence_advice"]
    assert "timeout_s" in s["convergence_advice"]
    assert ses.flags.get("f_mask") is not None        # best cycle kept


def test_default_call_converges_on_a_small_cell():
    ctx, ses = _ctx()
    r = SolventMask().run(ctx)
    assert r.ok, r.error
    assert r.summary["bypass"]["max_cycles"] == 1000
    assert r.summary["solvent_mask_converged"] is True
    assert "convergence_advice" not in r.summary
    assert r.summary["bypass"]["stopped_by"] is None
    assert r.summary["budget"]["timeout_s"] == 600.0
