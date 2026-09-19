"""Wall-clock budgets + cooperative cancellation for long tool loops.

Why this exists (ka1 2026-09-03, docs/ka1-2026-09-03/KA1-ANALYSIS.md §5.1):
codex's per-call timeout is 3 900 s (`workbench/core.py`, `tool_timeout_sec`).
When it fires, codex drops the request locally and tells the server nothing
(openai/codex#26956), and even if it did, `anyio.to_thread.run_sync` cannot
interrupt a running worker thread. So the MCP server keeps computing, keeps
the project lock, and every later call queues for `QUEUE_MAX_S` and then
fails. One `solve_charge_flipping` call cost a whole case that way (org-tools:
65 min of computation + 2 x 30 min of queue), one `optimize_weights({})` cost
65 min of a 194 min case (cage-full).

The fix is that a long tool stops *itself*:

    with Budget.for_tool(ctx, "solve_charge_flipping", params) as budget:
        for seed in seeds:
            budget.check(f"seed {seed}")     # raises between iterations
            ...

`check()` raises `BudgetExceeded` (wall clock) or `Cancelled` (the MCP server
saw the client give up / the transport close) *between* iterations, i.e. only
at points where the session and the node store are consistent. The caller
catches the exception and returns a partial result that says what was reached,
that it stopped early, and what the agent can do next.

Generalisation: every number here is a wall-clock default measured from
campaign timings, and every one is overridable per call via `timeout_s`. No
constant in this module depends on a crystal, an element or a data set.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable, Mapping

#: codex's per-tool-call hard timeout (crystalpilot/workbench/core.py
#: _mcp_overrides). Every budget below must be comfortably under it, because
#: past it the agent gets a transport error instead of the tool's own report.
CODEX_TOOL_TIMEOUT_S = 3900.0

#: Wall-clock ceiling of every tool that can plausibly run for minutes:
#: {tool: {parameter name: default seconds}}. The ceiling is the SUM of the
#: entries, so a staged budget (run_shelxt) can be quoted as one number.
#:
#: One table, three readers: the tool takes its own default from here, the
#: params-schema text is generated from here, and mcp/server.py reads it to
#: tell a QUEUED caller when the lock is going to free. Sizing:
#:
#: * solve_charge_flipping 900 s - the org full arm's negative sweep
#:   (4 seeds x 5 attempts x 5 000 iterations, small organic) returned "no
#:   phase transition" in 69.5 s, i.e. ~3.5 s per attempt; 900 s is ~13x that
#:   whole sweep, which leaves room for a cell an order of magnitude larger,
#:   and it is 4.3x below the codex timeout so the agent always receives the
#:   attempt table instead of a transport error.
#: * optimize_weights 600 s - each internal refinement of the 221-atom
#:   all-anisotropic cage model cost ~340 s, so 600 s buys the baseline plus
#:   one update round; past that the grid is the wrong instrument for that
#:   model (which is exactly what the 65 min run proved) and
#:   run_shelxl(mode='adopt_wght') does the same job (17 s in the tools arm).
#: * refine 1800 s - the most expensive legitimate single refinement observed
#:   is 1 582 s (cage-tools, anisotropic, 337 atoms, 5 cycles), so the default
#:   does not truncate anything that has ever finished usefully.
#: * run_shelxt / solve_superflip already enforce their own budgets; they are
#:   listed so the queue message can quote a ceiling for them too.
BUDGET_PARAMS: dict[str, dict[str, float]] = {
    "solve_charge_flipping": {"timeout_s": 900.0, "_cleanup_grace_s": 2.0},
    "optimize_weights": {"timeout_s": 600.0},
    # BYPASS iterations are cheap (hex, 17 000 A^3 cell: ~0.11 s per cycle,
    # 800 cycles in 92 s) but convergence needs hundreds of them; the budget
    # exists so max_cycles can default high enough to converge
    "solvent_mask": {"timeout_s": 600.0},
    "refine": {"timeout_s": 1800.0},
    # whole-fragment pose search: seeds x conformers x local refinement;
    # the candidates found so far come back when the budget runs out
    "search_fragment_pose": {"timeout_s": 600.0},
    "run_shelxt": {"timeout_s": 600.0, "phasing_grace_s": 600.0,
                   "search_grace_s": 900.0},
    "solve_superflip": {"timeout_s": 600.0},
    # external processes killed at exactly timeout_s
    "run_olex2": {"timeout_s": 900.0},
    "run_checkcif": {"timeout_s": 420.0},
    # first build of the per-node analysis product on a large cell: the
    # smtbx solvent mask + electron integration (~70 s on a 17 000 A^3
    # hex cell), PLD bisection and packing envelope (~3 s), guest map
    # (~4 s); cached afterwards (0.05 s)
    "analyze_packing": {"timeout_s": 300.0},
    "submit_iucr_checkcif": {"timeout_s": 300.0},
    "consult_specialist": {"timeout_s": 180.0, "_cleanup_grace_s": 2.0},
    "reduce_with_crysalis": {"timeout_s": 5400.0},
    # DIALS tools: no timeout_s parameter, a fixed per-stage watchdog
    # (tools_frames._TIMEOUTS). The keys below are not real parameters - they
    # are never passed by a caller, so declared_budget_s always falls back to
    # the default, which is the exact UPPER bound of the stages this tool can
    # run. Deliberately absent: run_shelxl (its ceiling is timeout_s x
    # (1+wght_rounds), which this table's sum cannot express) and
    # ghost_test / element_scan / probe_site (their time_budget_s is a
    # pre-check before each candidate, so the last one can overrun by a whole
    # refinement) - "no declared budget" is the honest answer for those.
    "import_frames": {"_dials_stage_ceiling_s": 2400.0},
    "find_spots": {"_dials_stage_ceiling_s": 3600.0},
    "index_frames": {"_dials_stage_ceiling_s": 1800.0},
    "integrate_frames": {"_dials_stage_ceiling_s": 4500.0},
    "scale_and_export": {"_dials_stage_ceiling_s": 4500.0},
}

#: how often a budgeted loop pings the progress channel (the MCP server
#: forwards it as an MCP progress notification)
PING_S = 60.0


def default_timeout_s(tool: str, param: str = "timeout_s") -> float | None:
    """Default value of one budget parameter of `tool` (None if unknown)."""
    return (BUDGET_PARAMS.get(tool) or {}).get(param)


def declared_budget_s(tool: str,
                      arguments: Mapping[str, Any] | None = None) -> float | None:
    """Wall-clock ceiling `tool` will stop itself at, for THESE arguments.

    Sums every budget parameter of the tool, taking the caller's value when
    given and the default otherwise. Returns None for a tool with no declared
    budget - the caller must then say "no declared budget" rather than invent
    a number."""
    spec = BUDGET_PARAMS.get(tool)
    if not spec:
        return None
    args = arguments or {}
    if tool == "solve_charge_flipping" and "time_budget_s" in args and "timeout_s" not in args:
        args = {**args, "timeout_s": args["time_budget_s"]}
    if tool == "solve_charge_flipping":
        try:
            if float(args.get("timeout_s", spec["timeout_s"])) <= 0:
                return None  # cleanup grace alone is not a computation ceiling
        except (TypeError, ValueError):
            pass
    total = 0.0
    for name, default in spec.items():
        v = args.get(name, default)
        try:
            v = float(v)
        except (TypeError, ValueError):
            v = float(default)
        if v > 0:
            total += v
    return total or None


def timeout_param(tool: str, on_exhaustion: str) -> dict[str, Any]:
    """JSON-schema entry for a tool's `timeout_s`, worded the same everywhere.

    `on_exhaustion` says what the agent GETS when the budget runs out - a
    capability boundary, stated explicitly (P14)."""
    default = default_timeout_s(tool) or 600.0
    return {
        "type": "number", "default": default,
        "description": (
            f"Wall-clock budget for this call in seconds (default "
            f"{default:.0f}; 0 or negative = no budget, only do that if you "
            f"are prepared for the call to be cut at codex's "
            f"{CODEX_TOOL_TIMEOUT_S:.0f} s transport timeout, after which the "
            f"server keeps computing and every later call on this project "
            f"queues behind it). The clock is checked BETWEEN iterations, so "
            f"the stop point is always a consistent state. On exhaustion: "
            f"{on_exhaustion}"),
    }


class BudgetStop(Exception):
    """A cooperative loop stopped early at a consistent point."""

    reason = "stopped"

    def __init__(self, stage: str, elapsed_s: float,
                 budget_s: float | None = None) -> None:
        self.stage = stage
        self.elapsed_s = round(float(elapsed_s), 1)
        self.budget_s = None if budget_s is None else round(float(budget_s), 1)
        super().__init__(str(self))

    def __str__(self) -> str:  # noqa: D105
        where = f" during {self.stage}" if self.stage else ""
        cap = (f" of a {self.budget_s:.0f}s budget"
               if self.budget_s else "")
        return (f"{self.reason} after {self.elapsed_s:.0f}s{cap}{where}")


class BudgetExceeded(BudgetStop):
    """The wall-clock budget ran out."""

    reason = "wall-clock budget exhausted"


class Cancelled(BudgetStop):
    """The client gave up on this call (or the transport closed).

    Nobody will read the result, so the only useful thing left to do is free
    the project lock - see crystalpilot/mcp/CANCELLATION_NOTES.md."""

    reason = "call cancelled by the client"


class Budget:
    """Wall clock + cancel flag + progress pings for one tool call.

    Construct through `Budget.for_tool(ctx, name, params)` inside a tool, or
    directly in tests (pass `clock=` for a fake clock). Nesting is automatic:
    a tool that calls another budgeted tool through the same ToolContext gets
    a child budget that can never outlive its parent."""

    def __init__(self, timeout_s: float | None, *,
                 cancel_event: threading.Event | None = None,
                 progress: Callable[[str], None] | None = None,
                 label: str = "", ping_s: float = PING_S,
                 clock: Callable[[], float] = time.monotonic,
                 parent: "Budget | None" = None) -> None:
        self.timeout_s = (float(timeout_s)
                          if timeout_s is not None and float(timeout_s) > 0
                          else None)
        self.cancel_event = cancel_event
        self.progress = progress
        self.label = label
        self.ping_s = float(ping_s)
        self._clock = clock
        self.parent = parent
        self.t0 = clock()
        self._last_ping = self.t0
        self.stopped_by: str | None = None
        #: set by the tool so a partial return can say where it got to
        self.last_stage: str = ""

    # -- state ---------------------------------------------------------
    def elapsed(self) -> float:
        return self._clock() - self.t0

    def remaining(self) -> float:
        """Seconds left before this budget (or its parent's) runs out."""
        own = (float("inf") if self.timeout_s is None
               else self.timeout_s - self.elapsed())
        if self.parent is not None:
            own = min(own, self.parent.remaining())
        return own

    def expired(self) -> bool:
        return self.remaining() <= 0.0

    def cancelled(self) -> bool:
        if self.cancel_event is not None and self.cancel_event.is_set():
            return True
        return self.parent is not None and self.parent.cancelled()

    def stop_reason(self) -> str | None:
        """'cancelled' / 'timeout' / None - non-raising, for loops that must
        break cleanly instead of unwinding (e.g. the LS iteration hook)."""
        if self.cancelled():
            return "cancelled"
        if self.expired():
            return "timeout"
        return None

    # -- use -----------------------------------------------------------
    def check(self, stage: str = "") -> None:
        """Raise if the call must stop; otherwise maybe emit a liveness ping.

        Call this BETWEEN iterations only - never in the middle of one."""
        if stage:
            self.last_stage = stage
        if self.cancelled():
            self.stopped_by = "cancelled"
            raise Cancelled(stage or self.last_stage, self.elapsed(),
                            self.timeout_s)
        if self.expired():
            self.stopped_by = "timeout"
            raise BudgetExceeded(stage or self.last_stage, self.elapsed(),
                                 self.timeout_s)
        self.tick(stage)

    def tick(self, stage: str = "") -> None:
        """Emit a liveness ping if `ping_s` has passed. Never raises."""
        now = self._clock()
        if self.progress is None or now - self._last_ping < self.ping_s:
            return
        self._last_ping = now
        left = self.remaining()
        budget = ("no budget" if self.timeout_s is None
                  else f"{self.elapsed():.0f}s of {self.timeout_s:.0f}s, "
                       f"{max(0.0, left):.0f}s left")
        self.ping(f"{stage or self.last_stage or 'running'} ({budget}) - "
                  f"computing inside the tool, not waiting on approval")

    def ping(self, message: str) -> None:
        """Force a progress message now (best-effort, never raises)."""
        if self.progress is None:
            return
        try:
            self.progress(f"{self.label}: {message}" if self.label
                          else message)
        except Exception:  # noqa: BLE001 - liveness is best-effort
            pass

    def report(self) -> dict[str, Any]:
        """The budget block every partial return carries."""
        out: dict[str, Any] = {"elapsed_s": round(self.elapsed(), 1)}
        if self.timeout_s is not None:
            # echoed faithfully, not rounded to a second: a caller who asked
            # for timeout_s=0.5 must see 0.5 back
            out["timeout_s"] = round(self.timeout_s, 3)
            out["remaining_s"] = round(max(0.0, self.remaining()), 1)
        if self.stopped_by:
            out["stopped_by"] = self.stopped_by
        if self.last_stage:
            out["last_stage"] = self.last_stage
        return out

    # -- installation on a ToolContext ----------------------------------
    @classmethod
    def for_tool(cls, ctx: Any, tool: str,
                 params: Mapping[str, Any] | None = None, *,
                 label: str | None = None,
                 clock: Callable[[], float] | None = None) -> "Budget":
        """Budget for `tool`, from its params and the tool context.

        Takes `timeout_s` from `params` when the caller gave one, otherwise
        the table default. Picks up `ctx.progress` and `ctx.cancel_event`, and
        nests under `ctx.budget` when a budgeted tool is already running (so
        an inner `refine` can never outlive the `optimize_weights` that called
        it)."""
        params = params or {}
        raw = params.get("timeout_s", None)
        timeout = default_timeout_s(tool) if raw is None else raw
        try:
            timeout = None if timeout is None else float(timeout)
        except (TypeError, ValueError):
            timeout = default_timeout_s(tool)
        return cls(timeout,
                   cancel_event=getattr(ctx, "cancel_event", None),
                   progress=getattr(ctx, "progress", None),
                   label=label or tool,
                   clock=clock or time.monotonic,
                   parent=getattr(ctx, "budget", None))

    def install(self, ctx: Any) -> "Budget":
        """Make this budget the ambient one on `ctx` (see `for_tool`).

        `__exit__` puts the previous ambient budget back, so nesting is safe
        even when the inner tool raises."""
        self._prev = getattr(ctx, "budget", None)
        try:
            ctx.budget = self
        except Exception:  # noqa: BLE001 - a ctx stand-in without the slot
            return self
        self._ctx = ctx
        return self

    def __enter__(self) -> "Budget":
        return self

    def __exit__(self, *exc: Any) -> None:
        ctx = getattr(self, "_ctx", None)
        if ctx is not None:
            try:
                ctx.budget = self._prev
            except Exception:  # noqa: BLE001
                pass
        return None


def budget_for(ctx: Any, tool: str, params: Mapping[str, Any] | None = None,
               *, label: str | None = None,
               clock: Callable[[], float] | None = None) -> Budget:
    """`Budget.for_tool(...)` already installed on `ctx` - use as a context
    manager so the previous ambient budget is restored on exit:

        with budget_for(ctx, "refine", params) as budget:
            ...
    """
    b = Budget.for_tool(ctx, tool, params, label=label, clock=clock)
    b.install(ctx)
    return b
