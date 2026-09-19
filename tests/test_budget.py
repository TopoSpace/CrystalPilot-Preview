"""Wall-clock budgets + cooperative cancellation (WP1).

ka1 2026-09-03: one `solve_charge_flipping` call held the project lock for
7 545 s after codex had given up at 3 900 s, and one `optimize_weights({})`
burned 65 min of a 194 min case. Neither tool had a clock, and the queued
calls behind them each burned QUEUE_MAX_S before saying "gave up waiting".

These tests pin the three things that fix it: a budget helper that stops a
loop at a consistent point, the two worst offenders returning a usable
partial result instead of nothing, and a queue message that names the running
tool's budget and what the agent can DO.
"""
from __future__ import annotations

import threading
import time

import pytest
from cctbx import crystal, xray
from cctbx.array_family import flex

from crystalpilot.core.dataset import ReflectionDataset
from crystalpilot.mcp import server as srv
from crystalpilot.pipeline.session import SolveSession
from crystalpilot.tools import hydrogen_tools as ht
from crystalpilot.tools import solution_tools as st
from crystalpilot.tools.base import ToolContext, ToolResult
from crystalpilot.tools.budget import (BUDGET_PARAMS, Budget, BudgetExceeded,
                                       Cancelled, budget_for,
                                       declared_budget_s, default_timeout_s,
                                       timeout_param)


class _Clock:
    """Fake clock: 0.0 for the first `n_zero` reads, then far in the future.

    Every Budget.check() reads it exactly twice (once for remaining(), once
    for the ping cadence), so `n_zero` sets a deterministic number of checks
    that pass before the budget expires."""

    def __init__(self, n_zero: int, after: float = 1e6) -> None:
        self.n_zero = n_zero
        self.after = after
        self.n = 0

    def __call__(self) -> float:
        self.n += 1
        return 0.0 if self.n <= self.n_zero else self.after


class _Store:
    def record(self, *a, **k):
        return None

    def log(self, *a, **k):
        return None

    def emit(self, *a, **k):
        return None


# ---------------------------------------------------------------- helper ---
def test_remaining_counts_down_and_check_raises_budget_exceeded():
    clock = _Clock(n_zero=3)
    b = Budget(100.0, clock=clock)
    assert b.remaining() == 100.0
    b.check("seed 1")                      # still inside the budget
    with pytest.raises(BudgetExceeded) as exc:
        b.check("seed 2")
    assert "seed 2" in str(exc.value)
    assert "100" in str(exc.value)         # the budget is named, not implied
    assert b.stopped_by == "timeout"
    assert b.report()["stopped_by"] == "timeout"


def test_cancel_event_wins_over_a_budget_that_has_not_expired():
    ev = threading.Event()
    b = Budget(1e6, cancel_event=ev, clock=_Clock(n_zero=1000))
    b.check("still fine")
    ev.set()
    with pytest.raises(Cancelled):
        b.check("client gave up")
    assert b.stopped_by == "cancelled"


def test_stop_reason_never_raises_for_loops_that_must_break_cleanly():
    """The least-squares hook cannot unwind mid-cycle - it breaks instead."""
    b = Budget(100.0, clock=_Clock(n_zero=1))
    assert b.stop_reason() is None or b.stop_reason() == "timeout"
    b2 = Budget(None)
    assert b2.stop_reason() is None and b2.remaining() == float("inf")


def test_a_child_budget_can_never_outlive_its_parent():
    parent = Budget(10.0, clock=lambda: 0.0)
    child = Budget(1800.0, parent=parent, clock=lambda: 0.0)
    assert child.remaining() == 10.0        # not 1800
    ev = threading.Event()
    parent.cancel_event = ev
    ev.set()
    assert child.cancelled()


def test_for_tool_nests_through_the_tool_context_and_restores_on_exit():
    ctx = ToolContext(store=_Store(), session=None)
    with budget_for(ctx, "optimize_weights") as outer:
        assert ctx.budget is outer
        assert outer.timeout_s == default_timeout_s("optimize_weights")
        with budget_for(ctx, "refine") as inner:
            assert ctx.budget is inner and inner.parent is outer
            assert inner.remaining() <= outer.timeout_s
        assert ctx.budget is outer          # restored
    assert ctx.budget is None


def test_progress_pings_are_rate_limited_and_say_how_much_is_left():
    msgs: list[str] = []
    t = {"v": 0.0}
    b = Budget(100.0, progress=msgs.append, label="refine[anisotropic]",
               ping_s=60.0, clock=lambda: t["v"])
    b.tick("cycle 1")
    assert msgs == []                       # too early for a ping
    t["v"] = 61.0
    b.tick("cycle 2")
    assert len(msgs) == 1
    assert "refine[anisotropic]" in msgs[0] and "cycle 2" in msgs[0]
    assert "39s left" in msgs[0]
    assert "not waiting on approval" in msgs[0]
    t["v"] = 70.0
    b.tick("cycle 3")
    assert len(msgs) == 1                   # still inside the ping interval


def test_a_budget_of_zero_or_less_means_no_budget_not_an_instant_stop():
    b = Budget(0)
    assert b.timeout_s is None and not b.expired()
    assert b.remaining() == float("inf")


# ------------------------------------------------------- the budget table ---
def test_declared_budget_uses_the_callers_own_arguments():
    assert declared_budget_s("refine") == 1800.0
    assert declared_budget_s("refine", {"timeout_s": 120}) == 120.0
    # staged budgets are summed so one number can be quoted
    assert declared_budget_s("run_shelxt") == 600.0 + 600.0 + 900.0
    # a tool with no declared budget must say so, never invent one
    assert declared_budget_s("inspect_model") is None
    assert declared_budget_s("ghost_test") is None


def test_every_budgeted_tool_is_under_the_client_tool_timeout():
    """A budget above codex's 3900 s cannot ever report back to the agent."""
    from crystalpilot.tools.budget import CODEX_TOOL_TIMEOUT_S
    for tool in ("solve_charge_flipping", "optimize_weights", "refine",
                 "run_shelxt", "solve_superflip"):
        assert declared_budget_s(tool) < CODEX_TOOL_TIMEOUT_S, tool


def test_timeout_param_schema_matches_the_table_and_states_the_consequence():
    p = timeout_param("refine", "ok=true with budget_exhausted=true")
    assert p["default"] == BUDGET_PARAMS["refine"]["timeout_s"]
    assert "BETWEEN iterations" in p["description"]
    assert "ok=true with budget_exhausted=true" in p["description"]


# --------------------------------------------------- solve_charge_flipping ---
def _synthetic_session():
    """Tiny P-1 structure, Fc^2 as Fo^2 - enough for a real flipping run."""
    cs = crystal.symmetry(unit_cell=(7.0, 8.0, 9.0, 80.0, 85.0, 95.0),
                          space_group_symbol="P -1")
    xs = xray.structure(crystal_symmetry=cs)
    uc = cs.unit_cell()
    for label, el, cart in (("S1", "S", (1.20, 1.50, 2.00)),
                            ("S2", "S", (4.10, 4.40, 4.90)),
                            ("O1", "O", (2.70, 1.90, 2.60)),
                            ("O2", "O", (1.75, 3.30, 4.20)),
                            ("N1", "N", (3.30, 0.95, 1.35)),
                            ("C1", "C", (3.90, 3.00, 3.40)),
                            ("C2", "C", (2.45, 4.60, 1.10)),
                            ("C3", "C", (5.05, 2.10, 0.75))):
        xs.add_scatterer(xray.scatterer(
            label=label, site=uc.fractionalize(cart),
            scattering_type=el, u=0.02))
    xs.scattering_type_registry(table="it1992")
    fc = xs.structure_factors(d_min=0.8).f_calc()
    fo_sq = fc.intensities().customized_copy(
        sigmas=flex.double(fc.size(), 1.0)).set_observation_type_xray_intensity()
    ses = SolveSession(dataset=ReflectionDataset(intensities=None,
                                                 wavelength=0.71073))
    ses.symmetry = cs
    ses.fo_sq = fo_sq
    return ses, xs


def _fake_clock_budget(monkeypatch, module, n_zero: int):
    """Make `module.budget_for` build budgets on a deterministic fake clock."""
    def _budget_for(ctx, tool, params=None, **kw):
        kw.pop("clock", None)
        b = Budget.for_tool(ctx, tool, params, clock=_Clock(n_zero=n_zero),
                            **kw)
        b.install(ctx)
        return b
    monkeypatch.setattr(module, "budget_for", _budget_for)


def test_charge_flipping_stops_between_attempts_and_returns_the_table(
        monkeypatch):
    ses, _xs = _synthetic_session()
    ctx = ToolContext(store=_Store(), session=ses)
    # 1 read at construction + 2 per check => 10 checks pass, then it stops -
    # far enough in to be well inside the flipping loop, not at its door
    _fake_clock_budget(monkeypatch, st, n_zero=21)
    # Inner cooperative loop: public run() additionally supervises a worker.
    r = st.ChargeFlippingSolve()._run(ctx, d_min=1.0, seeds=[11, 22, 33],
                                     max_attempts_per_seed=2,
                                     max_solving_iterations=5000,
                                     timeout_s=900)
    assert r.ok is False
    s = r.summary
    assert s["timed_out"] is True and s["cancelled"] is False
    # the partial table: the seed it was on, with what it had reached
    assert s["seeds_started"] == 1
    assert [row["seed"] for row in s["attempt_table"]] == [11]
    row = s["attempt_table"][0]
    assert row["attempts"] >= 1 and "elapsed_s" in row
    assert row["iterations"] > 0            # it really was flipping
    assert row["best_skewness"] > 0         # the phase-transition observable
    assert row["phase_transition"] is False
    assert s["budget"]["last_stage"].startswith("seed 11, attempt 1")
    assert s["budget"]["timeout_s"] == 900.0
    assert s["seeds_requested"] == [11, 22, 33]
    # the error says nothing was killed and the call ended itself
    assert "no process was killed" in r.error
    assert "stopped" in r.error
    # ... and the next step names a knob that is NOT "more seeds"
    assert "adding seeds or attempts is NOT the move" in s["next_step"]
    assert "run_shelxt" in s["cheap_alternative"]


def test_the_skewness_trace_decides_whether_more_time_could_help():
    """The phase transition IS a jump in map skewness, so a flat trace means
    a longer budget buys nothing - the same decidability the superflip
    R-trajectory readout gives."""
    verdict = st.ChargeFlippingSolve._skewness_verdict
    flat = verdict([{"best_skewness": 3.5}, {"best_skewness": 3.5},
                    {"best_skewness": 3.52}, {"best_skewness": 3.49}])
    assert "did NOT move" in flat and "would buy nothing" in flat
    climbing = verdict([{"best_skewness": 3.5}, {"best_skewness": 3.6},
                        {"best_skewness": 5.1}, {"best_skewness": 6.4}])
    assert "still climbing" in climbing
    assert "larger timeout_s" in climbing
    assert "Keep seeds and max_attempts_per_seed as they are" in climbing
    # every branch ends with the same menu of knobs, none of them "more seeds"
    for msg in (flat, climbing, verdict([{"best_skewness": 3.5}])):
        assert "adding seeds or attempts is NOT the move" in msg


def test_charge_flipping_never_tells_the_agent_to_try_more_seeds():
    """The org-tools case followed exactly that sentence into a dead run."""
    tool = st.ChargeFlippingSolve()
    assert "try more seeds" not in tool.description
    assert "BUDGET:" in tool.description
    assert str(st.MAX_TOTAL_ATTEMPTS) in tool.description
    knob = tool.params_schema["properties"]["max_attempts_per_seed"]
    assert str(st.MAX_TOTAL_ATTEMPTS) in knob["description"]


def test_the_seed_attempt_product_is_capped_and_the_trim_is_disclosed():
    seeds, attempts, capped = st.ChargeFlippingSolve()._cap_attempts(
        [101, 203, 307, 409, 503, 607, 709, 811], 20)      # the org call
    assert attempts == 20 and len(seeds) == 2               # 2 x 20 = 40
    assert capped["requested"].startswith("8 seeds x 20 attempts = 160")
    assert capped["cap"] == st.MAX_TOTAL_ATTEMPTS
    assert "do not accumulate" in capped["why"]
    # a request inside the cap is left completely alone
    assert st.ChargeFlippingSolve()._cap_attempts([1, 2, 3, 4], 2) == (
        [1, 2, 3, 4], 2, None)


# ------------------------------------------------------- optimize_weights ---
def test_optimize_weights_returns_a_partial_and_points_at_adopt_wght():
    ses, xs = _synthetic_session()
    ses.model = xs
    ctx = ToolContext(store=_Store(), session=ses)
    # a budget already spent: the baseline refinement still runs (it is not
    # optional), then the grid stops at its first point
    r = ht.OptimizeWeights().run(ctx, mode="isotropic", n_cycles=1,
                                 timeout_s=0.001)
    assert r.ok is True                      # a partial is still useful
    s = r.summary
    assert s["partial"] is True and s["timed_out"] is True
    assert s["weights"] == ses.flags["weights"]     # stored for later refines
    assert s["budget"]["timeout_s"] == 0.001
    assert "nothing was lost" in s["note"]
    assert "run_shelxl(mode='adopt_wght')" in s["next_step"]
    assert "do NOT just re-issue the same call" in s["next_step"]


@pytest.mark.parametrize("max_rounds, phase", [(2, "shelxl_update"),
                                               (0, "bisection_fallback")])
def test_optimize_weights_full_run_still_improves_goof(max_rounds, phase):
    """Guards the split into _optimize/_grid and the mutable `best`: both
    phases must still carry their improvement back out of the loop."""
    ses, xs = _synthetic_session()
    xs.shake_sites_in_place(rms_difference=0.03)
    ses.model = xs
    ctx = ToolContext(store=_Store(), session=ses)
    r = ht.OptimizeWeights().run(ctx, mode="isotropic", n_cycles=2,
                                 max_rounds=max_rounds)
    assert r.ok and "partial" not in r.summary
    assert r.summary["phases"][phase] > 0
    # the reported best must come from a LATER point, not the baseline
    before, after = r.summary["goof_before"], r.summary["goof_after"]
    assert abs(after - 1.0) < abs(before - 1.0)
    assert r.summary["weights"] == ses.flags["weights"]


def test_optimize_weights_description_states_its_budget_and_the_alternative():
    d = ht.OptimizeWeights().description
    assert "BUDGET:" in d and "partial=true" in d
    assert "adopt_wght" in d


# ------------------------------------------------------------------ refine ---
def test_refine_stops_at_the_budget_and_keeps_a_consistent_model():
    ses, xs = _synthetic_session()
    # perturb so there is something left to refine
    xs.shake_sites_in_place(rms_difference=0.05)
    ses.model = xs
    ctx = ToolContext(store=_Store(), session=ses)
    from crystalpilot.tools.refinement_tools import RefineLS
    r = RefineLS().run(ctx, mode="isotropic", n_cycles=8, timeout_s=0.001)
    assert r.ok is True                      # the partial IS the deliverable
    s = r.summary
    assert s["budget_exhausted"] is True and s["cancelled"] is False
    assert s["cycles_done"] < s["cycles_requested"] == 8
    assert "last COMPLETED cycle" in s["note_budget"]
    assert "re-run BOTH sides with the same budget" in s["note_budget"]
    # the model is still a usable structure, not a half-applied shift
    assert ses.model.scatterers().size() == 8
    assert 0.0 <= s["r1_strong"] <= 1.0


def test_an_unbudgeted_refine_is_unchanged():
    ses, xs = _synthetic_session()
    xs.shake_sites_in_place(rms_difference=0.02)
    ses.model = xs
    ctx = ToolContext(store=_Store(), session=ses)
    from crystalpilot.tools.refinement_tools import RefineLS
    r = RefineLS().run(ctx, mode="isotropic", n_cycles=3)
    assert r.ok and "budget_exhausted" not in r.summary


# ------------------------------------------------------ the queue message ---
class _SlowProject:
    def __init__(self, delay: float):
        self.delay = delay
        self.seen: list[tuple] = []

    def invoke_tool(self, name, arguments, progress=None, cancel_event=None):
        self.seen.append((name, cancel_event))
        time.sleep(self.delay)
        return ToolResult(ok=True, summary={"name": name})


def _handle(tmp_path, delay):
    h = srv.ProjectHandle(tmp_path)
    h._project = _SlowProject(delay)
    return h


def test_queue_giveup_names_the_running_tool_its_budget_and_the_way_out(
        tmp_path, monkeypatch):
    monkeypatch.setattr(srv, "QUEUE_PING_S", 0.05)
    monkeypatch.setattr(srv, "QUEUE_MAX_S", 60.0)     # would have been a wait
    monkeypatch.setattr(srv, "QUEUE_GRACE_S", 0.2)
    h = _handle(tmp_path, delay=3.0)
    threading.Thread(
        target=lambda: h.call("optimize_weights", {"timeout_s": 0.1}),
        daemon=True).start()
    time.sleep(0.1)
    t0 = time.time()
    out = h.call("get_project_brief", {})
    waited = time.time() - t0
    assert out["ok"] is False
    err = out["error"]
    assert "'optimize_weights'" in err
    assert "0s budget" in err or "budget" in err
    assert "nothing needs killing" in err
    assert "ends by itself at its budget" in err
    assert "smaller timeout_s" in err          # something the agent can DO
    # and it did NOT burn the full QUEUE_MAX_S: the running tool's own
    # budget said when the lock would free
    assert waited < 2.0, waited


def test_queue_giveup_says_so_when_the_running_tool_has_no_budget(
        tmp_path, monkeypatch):
    monkeypatch.setattr(srv, "QUEUE_PING_S", 0.05)
    monkeypatch.setattr(srv, "QUEUE_MAX_S", 0.3)
    h = _handle(tmp_path, delay=2.0)
    threading.Thread(target=lambda: h.call("ghost_test", {}),
                     daemon=True).start()
    time.sleep(0.05)
    out = h.call("get_project_brief", {})
    assert out["ok"] is False
    assert "declares no wall-clock budget" in out["error"]
    assert "open-ended" in out["error"]


def test_the_cancel_event_reaches_the_tool(tmp_path):
    h = _handle(tmp_path, delay=0.0)
    ev = threading.Event()
    h.call("refine", {}, cancel_event=ev)
    assert h._project.seen == [("refine", ev)]


def test_cancel_bridge_stops_the_worker_and_frees_the_lock():
    """The whole point: a cancelled request must not hold the project lock.

    Mirrors what mcp 1.29.1 does on notifications/cancelled - it cancels the
    scope that wraps the handler - and checks the worker thread notices."""
    import anyio

    class _Handle:
        def __init__(self):
            self.stopped_after = None
            self.lock_held = True

        def call(self, name, arguments, progress=None, cancel_event=None):
            t0 = time.time()
            try:
                while time.time() - t0 < 5.0:
                    if cancel_event is not None and cancel_event.is_set():
                        self.stopped_after = time.time() - t0
                        return {"ok": False, "error": "cancelled"}
                    time.sleep(0.02)
                return {"ok": True}
            finally:
                self.lock_held = False       # the finally that frees the lock

    handle = _Handle()
    got: dict = {}

    async def main():
        # the scope mcp's RequestResponder puts around the handler
        with anyio.CancelScope() as scope:
            async with anyio.create_task_group() as tg:
                async def killer():
                    await anyio.sleep(0.3)
                    scope.cancel()
                tg.start_soon(killer)
                got["payload"] = await srv.call_with_cancel_bridge(
                    handle, "refine", {})

    t0 = time.time()
    anyio.run(main)
    elapsed = time.time() - t0
    assert handle.stopped_after is not None, "the worker never saw the cancel"
    assert handle.stopped_after < 1.0
    assert handle.lock_held is False, "the project lock must be released"
    assert got["payload"]["error"] == "cancelled"
    assert elapsed < 2.0, "the handler must not wait out the full 5 s"
