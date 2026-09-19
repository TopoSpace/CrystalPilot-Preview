"""Tool interface: every crystallographic operation is a Tool.

Uniform contract so tools are callable from the deterministic pipeline, the LLM agent
(function calling), the CLI, and the UI - with identical logging and reproducibility.
"""
from __future__ import annotations

import contextlib
import json
import threading
import time
import traceback
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ..core.events import RunStore

if TYPE_CHECKING:
    from ..pipeline.session import SolveSession


@dataclass
class ToolResult:
    ok: bool
    summary: dict[str, Any] = field(default_factory=dict)   # compact, LLM-consumable
    artifacts: dict[str, str] = field(default_factory=dict)  # name -> path
    error: str | None = None

    @staticmethod
    def failure(msg: str) -> "ToolResult":
        return ToolResult(ok=False, error=msg)


# ---------------------------------------------------------------------------
# Layered status envelope (round-3 WP1). The wire shape {ok, summary,
# artifacts, error} is fixed - the MCP server, 675 test assertions and the
# UI all read it - so the layers live under ONE reserved summary key:
#
#   summary[STATUS_KEY] = {
#     execution:          ran | failed | timeout | cancelled   (did it run?)
#     scientific_outcome: {verdict, reasons, measured_by} | None
#                          (what the numbers say; verdict supports |
#                           inconclusive | against; only tools that judge
#                           something fill it)
#     state_changed:      {changed, node_before, node_after, revision_after}
#                          | None (filled by RefineProject.invoke_tool)
#     no_change:          {value, reason}   (ran fine, changed nothing)
#     applicability:      [str]             (caveats on WHEN the result holds)
#     artifact_index:     {name: path}
#   }
#
# The forensic case: fit_fragment answered ok:true 27 times, 15 of them
# with zero atoms added; solvent_mask answered ok:true six times, once
# converged. "It ran" and "it found something" are different facts and now
# have different fields. "status" itself is NOT the key - write_outputs and
# the job tools already use summary.status for their own states.
STATUS_KEY = "tool_status"
EXECUTIONS = ("ran", "failed", "timeout", "cancelled")
VERDICTS = ("supports", "inconclusive", "against")
#: summary keys whose string values are paths worth indexing
ARTIFACT_KEYS = ("job_dir", "output_dir", "transcript_dir", "report",
                 "manifest", "log", "lst", "res", "cif", "fcf", "png",
                 "image", "analysis_path")


def attach_status(result: "ToolResult", execution: str) -> dict[str, Any]:
    """Fill (or update) result.summary[STATUS_KEY]. Idempotent: a tool that
    already wrote an envelope keeps what it wrote where this call has
    nothing better. Tools contribute through plain summary keys that are
    folded in: `scientific_outcome` (moved under the envelope),
    `applicability` (moved), `no_state_change` / `no_change_reason` (read)."""
    if not isinstance(result.summary, dict):
        return {}
    s = result.summary
    env = s.get(STATUS_KEY)
    if not isinstance(env, dict):
        env = {}
    env["execution"] = execution if execution in EXECUTIONS else "failed"
    sci = s.pop("scientific_outcome", None)
    if isinstance(sci, dict):
        verdict = str(sci.get("verdict") or "inconclusive")
        env["scientific_outcome"] = {
            "verdict": verdict if verdict in VERDICTS else "inconclusive",
            "reasons": [str(x) for x in (sci.get("reasons") or [])],
            "measured_by": sci.get("measured_by")}
    else:
        env.setdefault("scientific_outcome", None)
    no_change = bool(result.ok and s.get("no_state_change"))
    env["no_change"] = {
        "value": no_change,
        "reason": (str(s["no_change_reason"]) if s.get("no_change_reason")
                   else ("the tool reported no state change" if no_change
                         else None))}
    appl = s.pop("applicability", None)
    if isinstance(appl, (list, tuple)):
        env["applicability"] = [*(env.get("applicability") or []),
                                *(str(x) for x in appl)]
    else:
        env.setdefault("applicability", [])
    idx = dict(env.get("artifact_index") or {})
    for k, v in (result.artifacts or {}).items():
        if isinstance(v, str) and v:
            idx[str(k)] = v
    for k in ARTIFACT_KEYS:
        v = s.get(k)
        if isinstance(v, str) and v:
            idx.setdefault(k, v)
    env["artifact_index"] = idx
    env.setdefault("state_changed", None)
    s[STATUS_KEY] = env
    return env


def status_of(result: "ToolResult") -> dict[str, Any]:
    """The envelope, or {} when the summary is not a dict."""
    s = result.summary
    env = s.get(STATUS_KEY) if isinstance(s, dict) else None
    return env if isinstance(env, dict) else {}


def _execution_of_exception(e: BaseException) -> str:
    from .budget import BudgetExceeded, Cancelled
    if isinstance(e, Cancelled):
        return "cancelled"
    if isinstance(e, BudgetExceeded):
        return "timeout"
    return "failed"


def _execution_of_result(ctx: "ToolContext", result: "ToolResult") -> str:
    cancel = getattr(ctx, "cancel_event", None)
    try:
        if cancel is not None and cancel.is_set():
            return "cancelled"
    except Exception:  # noqa: BLE001 - a stub event never decides this
        pass
    s = result.summary if isinstance(result.summary, dict) else {}
    # budgeted loops (probe_site, ghost_test, element_scan, run_shelxl
    # jobs) return ok:true PARTIAL results with a `timeout` note; the
    # solution / hydrogen tools say `cancelled: true`
    if s.get("cancelled") is True:
        return "cancelled"
    if s.get("timeout"):
        return "timeout"
    return "ran" if result.ok else "failed"


@dataclass
class ToolContext:
    store: RunStore
    session: "SolveSession"
    trajectory_id: str = "main"
    #: optional heartbeat sink for long-running tools (message: str) -> None;
    #: the MCP server wires it to progress notifications so the agent SEES
    #: liveness instead of assuming a slow DIALS stage is stuck
    progress: Any = None
    #: optional threading.Event set by the MCP server when the client gave up
    #: on this call (notifications/cancelled) or the transport closed. Long
    #: loops poll it through tools.budget.Budget and stop at a consistent
    #: point - nothing can interrupt a worker thread from outside, see
    #: crystalpilot/mcp/CANCELLATION_NOTES.md
    cancel_event: Any = None
    #: the ambient tools.budget.Budget while a budgeted tool runs, so a tool
    #: called by another one inherits the remaining wall clock instead of
    #: starting a fresh budget of its own
    budget: Any = None


@contextlib.contextmanager
def progress_heartbeat(ctx: "ToolContext", label: str,
                       interval: float = 20.0):
    """Wall-clock liveness pings while a blocking computation runs.

    Process-audit T2: refine (19 min) and optimize_weights (39 min) gave
    ZERO signal mid-flight - the r12 agent twice misattributed the
    silence to 'the approval queue'. Wrap the blocking call:

        with progress_heartbeat(ctx, "refine: 3620 params"):
            levenberg_marquardt_iterations(...)

    Emits '<label>: computing, Ns elapsed (inside the tool, not waiting
    on approval)' every `interval` seconds to ctx.progress. No-op when
    the context has no progress sink (CLI / tests). The MCP server's
    progress dispatch is thread-agnostic (run_coroutine_threadsafe), so
    pings from this helper's own thread reach the agent."""
    progress = getattr(ctx, "progress", None)
    if progress is None:
        yield
        return
    stop = threading.Event()
    t0 = time.time()

    def _beat() -> None:
        while not stop.wait(interval):
            try:
                progress(f"{label}: computing, {time.time() - t0:.0f}s "
                         f"elapsed (inside the tool, not waiting on "
                         f"approval)")
            except Exception:  # noqa: BLE001 - liveness is best-effort
                return

    th = threading.Thread(target=_beat, daemon=True,
                          name="tool-heartbeat")
    th.start()
    try:
        yield
    finally:
        stop.set()
        th.join(timeout=1.0)


SCHEMA_SUMMARY_MAX = 700


def _bounds(prop: dict[str, Any]) -> str:
    """`[lo..hi]` when the schema declares minimum / maximum (round-3 WP8:
    every bound a tool enforces at run time is declared, so the agent
    reads it here instead of learning it by being refused)."""
    lo, hi = prop.get("minimum"), prop.get("maximum")
    if lo is None and hi is None:
        return ""
    fmt = lambda v: "" if v is None else f"{v:g}"  # noqa: E731
    return f"[{fmt(lo)}..{fmt(hi)}]"


def _type_summary(prop: dict[str, Any]) -> str:
    """Compact type of one JSON-schema property: enums as a|b|c, arrays as
    [item], objects as {keys}, unions joined with |, numeric bounds as
    [lo..hi]."""
    if "enum" in prop:
        return "|".join(str(v) for v in prop["enum"])
    if "const" in prop:
        return str(prop["const"])
    for key in ("anyOf", "oneOf"):
        if isinstance(prop.get(key), list):
            return "|".join(_type_summary(p) for p in prop[key] if isinstance(p, dict))
    ty = prop.get("type")
    if isinstance(ty, list):
        return "|".join(str(x) for x in ty) + _bounds(prop)
    if ty == "array":
        items = prop.get("items")
        inner = _type_summary(items) if isinstance(items, dict) else "any"
        return f"[{inner}]"
    if ty == "object":
        keys = list((prop.get("properties") or {}).keys())
        return "{" + ",".join(keys) + "}" if keys else "object"
    return str(ty or "any") + _bounds(prop)


def schema_summary(schema: dict[str, Any] | None,
                   max_chars: int = SCHEMA_SUMMARY_MAX) -> str:
    """One line naming every parameter of a tool: `Params: a*: string; b:
    x|y|z = x; c: [string]` (`*` = required, `= v` = default, none when the
    tool takes nothing). Round-2 R5: the agent used to spend 15-33 calls per
    cell probing parameter names; the JSON schema is still sent as-is, this
    line just makes it readable in the description."""
    props = (schema or {}).get("properties") or {}
    if not props:
        return "Params: none."
    required = set((schema or {}).get("required") or [])
    parts = []
    for name, prop in props.items():
        if not isinstance(prop, dict):
            continue
        s = f"{name}{'*' if name in required else ''}: {_type_summary(prop)}"
        if "default" in prop:
            d = prop["default"]
            s += " = " + (json.dumps(d, ensure_ascii=False, separators=(",", ":"))
                          if not isinstance(d, str) or d == "" else d)
        parts.append(s)
    line = "Params: " + "; ".join(parts) + "."
    if len(line) > max_chars:
        line = line[:max_chars - 1].rstrip("; ") + "…"
    return line


def describe_with_params(description: str, schema: dict[str, Any] | None) -> str:
    """The description the agent sees: the tool's own text plus the
    parameter line, unless the text already carries one."""
    desc = (description or "").rstrip()
    if "Params:" in desc:
        return desc
    return desc + ("\n" if desc else "") + schema_summary(schema)


class Tool(ABC):
    """Subclass and register. `params_schema` is a JSON schema exposed to the agent."""

    name: str = ""
    description: str = ""
    params_schema: dict[str, Any] = {"type": "object", "properties": {}}

    @abstractmethod
    def run(self, ctx: ToolContext, **params: Any) -> ToolResult: ...


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if not tool.name:
            raise ValueError(f"tool {tool!r} has no name")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise KeyError(f"unknown tool: {name}. Known: {sorted(self._tools)}")
        return self._tools[name]

    def names(self) -> list[str]:
        return sorted(self._tools)

    def specs(self, names: list[str] | None = None) -> list[dict[str, Any]]:
        tools = [self._tools[n] for n in (names or self.names())]
        return [{"name": t.name,
                 "description": describe_with_params(t.description, t.params_schema),
                 "parameters": t.params_schema}
                for t in tools]


def invoke(registry: ToolRegistry, ctx: ToolContext, name: str,
           params: dict[str, Any] | None = None) -> ToolResult:
    """Run a tool with full event logging; exceptions become failed results."""
    params = params or {}
    call_ev = ctx.store.emit("tool_call", {"tool": name, "params": params},
                             trajectory_id=ctx.trajectory_id)
    t0 = time.time()
    try:
        tool = registry.get(name)
        # strict parameter names: a silently-dropped unknown key makes the
        # tool run against the WRONG target (live case: run_checkcif with
        # cif_path= validated the minimal node CIF instead of the
        # publication CIF and produced bogus A alerts)
        known = set((getattr(tool, "params_schema", None) or {})
                    .get("properties", {}))
        # leading underscore = server-injected internal channel (e.g.
        # _actor on save_skill), never agent-facing
        unknown = sorted(k for k in set(params) - known
                         if not k.startswith("_"))
        if unknown:
            result = ToolResult.failure(
                f"unknown parameter(s) {unknown} for '{name}' - nothing "
                f"was run. Accepted parameters: {sorted(known) or 'none'}.")
        else:
            result = tool.run(ctx, **params)
    except Exception as e:  # noqa: BLE001 - agent must see failures, not crash
        result = ToolResult.failure(f"{type(e).__name__}: {e}")
        result.summary["traceback"] = traceback.format_exc(limit=8)
        execution = _execution_of_exception(e)
    else:
        execution = _execution_of_result(ctx, result)
    attach_status(result, execution)
    ctx.store.emit(
        "tool_result",
        {"tool": name, "ok": result.ok, "elapsed_s": round(time.time() - t0, 3),
         "summary": result.summary, "artifacts": result.artifacts, "error": result.error},
        trajectory_id=ctx.trajectory_id, parent_id=call_ev.event_id)
    return result
