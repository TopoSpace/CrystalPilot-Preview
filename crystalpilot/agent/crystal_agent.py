"""The Crystal Agent: an LLM crystallographer driving the tool registry.

The agent makes the scientific decisions (space group, element assignment, occupancy,
refinement strategy, what to fix next) exactly like a human researcher operating the
software; every decision and tool call is event-logged for full traceability.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..core.events import RunStore
from ..llm.config import LLMConfig, build_provider, resolve_llm_config
from ..llm.provider import LLMMessage, LLMRequest, ToolSpec
from ..pipeline.session import SolveSession
from ..tools.base import ToolContext, ToolRegistry, invoke

SYSTEM_PROMPT = """\
You are CrystalPilot's Crystal Agent: an expert single-crystal X-ray crystallographer \
specializing in MOFs, working autonomously. You drive real crystallographic engines \
through tools; you never invent numbers. You make every scientific decision yourself \
(space group choice, element assignment, occupancies, deleting ghosts, adding missing \
atoms, refinement strategy), like a researcher operating Olex2/SHELX - but through the \
provided tools.

Method: Observe -> Diagnose -> Hypothesize -> Act -> Evaluate. After each tool result, \
briefly diagnose before the next action.

Crystallographic judgment guide:
- R1 (strong) targets: <0.05 excellent, <0.10 acceptable for porous MOFs without \
solvent modeling. wR2/GooF high while R1 moderate often means weighting or unmodeled \
solvent, not a wrong structure.
- Residual density: peaks >2.5 e/A^3 near a metal may be a wrong element or missed \
coordinated atom; isolated peaks in voids are usually solvent. Holes < -3 near a heavy \
atom suggest too-heavy element or over-occupancy.
- ADP diagnostics: U too small => element assigned too light (e.g. C should be N/O, or \
site hosts a heavier atom / higher occupancy). U too large => element too heavy, ghost \
atom, or disorder (consider occupancy < 1).
- MOF chemistry is a hard constraint: metal coordination number/geometry must be \
plausible; carboxylates bind with sensible M-O distances; the framework should usually \
be 2D/3D connected. A low R1 with absurd chemistry is WRONG - prefer chemically sound \
models.
- C/N/O are nearly indistinguishable by X-rays; use chemistry (bond lengths, \
coordination context, linker structure) to assign them.
- Paired difference peaks flanking a heavy atom (each ~0.4-1.0 A away, e.g. +20 e/A^3 \
at 0.6 A from a Cu) mean the atom actually sits off that position - typically a split/\
disordered site or an atom wrongly idealized onto a special position. Fix with \
edit_atoms action 'move' to the peak coordinates (occupancy is auto-rescaled when the \
site multiplicity changes), then refine and check the peaks vanish.
- Space-group ambiguity (e.g. polar vs centrosymmetric, or tied candidates): try \
solving in the alternatives and compare R1, chemistry, and whether the model refines \
stably.
- Known limitation: no solvent masking (SQUEEZE) is available yet. Disordered pore \
solvent can keep R1 at 0.12-0.25 even for a correct framework. Do NOT delete real \
framework atoms to chase R1; note residual solvent in your assessment instead.

Efficiency rules: each tool call is cheap (<1 min) but your budget is limited \
(~{max_steps} tool calls). Avoid repeating a failed approach twice. When converged or \
out of productive ideas, call finish with an honest assessment.\
"""


def _finish_spec() -> ToolSpec:
    return ToolSpec(
        name="finish",
        description="End the session with your final scientific assessment.",
        parameters={
            "type": "object",
            "properties": {
                "status": {"type": "string", "enum": ["solved", "partial", "failed"]},
                "assessment": {"type": "string",
                               "description": "concise scientific summary: what the "
                                              "structure is, quality, remaining issues"},
                "remaining_issues": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["status", "assessment"],
        })


def _get_state_spec() -> ToolSpec:
    return ToolSpec(
        name="get_state",
        description=("Inspect current session state: symmetry, refinement history, "
                     "model atoms, validation, space-group candidates."),
        parameters={"type": "object", "properties": {
            "include_atoms": {"type": "boolean", "default": True}}})


# tools whose execution mutates the model/strategy - gated in Copilot mode
GATED_TOOLS = {"edit_atoms", "set_space_group", "add_atoms_from_difference_map",
               "restore_state"}


class CrystalAgent:
    def __init__(self, registry: ToolRegistry, ctx: ToolContext,
                 llm_cfg: LLMConfig | None = None, task_class: str = "planner",
                 max_steps: int = 18,
                 approval_gate=None) -> None:
        """approval_gate: optional callable(tool_name, params, rationale) ->
        (approved: bool, comment: str). When set (Copilot mode), calls to
        GATED_TOOLS wait for user approval; a rejection is fed back to the agent."""
        self.registry = registry
        self.ctx = ctx
        cfg = llm_cfg or resolve_llm_config()
        self.provider, self.model, self.effort = build_provider(cfg, task_class)
        self.max_steps = max_steps
        self.approval_gate = approval_gate
        self.usage = {"input_tokens": 0, "output_tokens": 0, "calls": 0}

    # ------------------------------------------------------------------
    def _tool_specs(self) -> list[ToolSpec]:
        specs = [ToolSpec(name=s["name"], description=s["description"],
                          parameters=s["parameters"])
                 for s in self.registry.specs()]
        specs.append(_get_state_spec())
        specs.append(_finish_spec())
        return specs

    def _state_snapshot(self, include_atoms: bool = True) -> dict[str, Any]:
        ses = self.ctx.session
        snap: dict[str, Any] = {
            "space_group": str(ses.symmetry.space_group_info()) if ses.symmetry else None,
            "sg_candidates": [
                {"space_group": c.get("space_group_input_basis", c["space_group"]),
                 "score": round(c["total_score"], 1)}
                for c in (ses.sg_candidates or [])[:6]],
            "refinement_history": [s.as_dict() for s in ses.refinement_history[-6:]],
            "validation": {k: v for k, v in (ses.validation or {}).items()
                           if k in ("alerts", "confidence")},
        }
        model_summary = ses.model_summary(max_atoms=80 if include_atoms else 0)
        if not include_atoms:
            model_summary.pop("atoms", None)
        snap["model"] = model_summary
        return snap

    # ------------------------------------------------------------------
    def run(self, task: str) -> dict[str, Any]:
        ses = self.ctx.session
        store = self.ctx.store
        sys_prompt = SYSTEM_PROMPT.format(max_steps=self.max_steps)
        first = {
            "task": task,
            "dataset": ses.dataset.summary(),
            "current_state": self._state_snapshot(),
        }
        messages: list[LLMMessage] = [
            LLMMessage(role="system", content=sys_prompt),
            LLMMessage(role="user",
                       content=json.dumps(first, ensure_ascii=False, default=str)),
        ]
        outcome: dict[str, Any] = {"status": "incomplete", "assessment": ""}
        hard_cap = self.max_steps + max(8, self.max_steps // 2)
        step = -1
        while step + 1 < self.max_steps:
            step += 1
            # extend the budget while the trajectory is still clearly improving
            if step == self.max_steps - 1 and self.max_steps < hard_cap:
                hist = [s.r1_strong for s in ses.refinement_history[-6:]]
                if len(hist) >= 2 and (hist[0] - hist[-1]) > 0.01:
                    self.max_steps = min(hard_cap, self.max_steps + 4)
                    store.emit("agent_budget_extended",
                               {"new_max_steps": self.max_steps},
                               trajectory_id=self.ctx.trajectory_id)
            resp = self.provider.complete(LLMRequest(
                messages=messages, tools=self._tool_specs(),
                model=self.model, reasoning_effort=self.effort,
                max_output_tokens=6000))
            self.usage["input_tokens"] += resp.usage.input_tokens
            self.usage["output_tokens"] += resp.usage.output_tokens
            self.usage["calls"] += 1
            if resp.text:
                store.emit("agent_thought", {"step": step, "text": resp.text},
                           trajectory_id=self.ctx.trajectory_id)
            if not resp.tool_calls:
                # model spoke without acting; nudge once, then stop
                messages.append(LLMMessage(role="assistant", content=resp.text))
                messages.append(LLMMessage(
                    role="user",
                    content="Continue with a tool call, or call finish."))
                continue
            messages.append(LLMMessage(role="assistant", content=resp.text,
                                       tool_calls=resp.tool_calls))
            for tc in resp.tool_calls:
                if tc.name == "finish":
                    outcome = {"status": tc.arguments.get("status", "partial"),
                               "assessment": tc.arguments.get("assessment", ""),
                               "remaining_issues": tc.arguments.get(
                                   "remaining_issues", []),
                               "steps_used": step + 1}
                    store.emit("agent_finish", outcome,
                               trajectory_id=self.ctx.trajectory_id)
                    outcome["usage"] = self.usage
                    return outcome
                if tc.name == "get_state":
                    result_payload = self._state_snapshot(
                        include_atoms=bool(tc.arguments.get("include_atoms", True)))
                elif (self.approval_gate is not None and tc.name in GATED_TOOLS):
                    approved, comment = self.approval_gate(
                        tc.name, tc.arguments, resp.text or "")
                    if approved:
                        r = invoke(self.registry, self.ctx, tc.name, tc.arguments)
                        result_payload = {"ok": r.ok, "summary": r.summary,
                                          "error": r.error,
                                          "user_note": comment or None}
                    else:
                        store.emit("agent_action_rejected",
                                   {"tool": tc.name, "comment": comment},
                                   trajectory_id=self.ctx.trajectory_id)
                        result_payload = {
                            "ok": False,
                            "error": "user rejected this action"
                                     + (f": {comment}" if comment else ""),
                            "hint": "adapt your plan to the user's feedback"}
                else:
                    r = invoke(self.registry, self.ctx, tc.name, tc.arguments)
                    result_payload = {"ok": r.ok, "summary": r.summary,
                                      "error": r.error}
                messages.append(LLMMessage(
                    role="tool", tool_call_id=tc.call_id,
                    content=json.dumps(result_payload, ensure_ascii=False,
                                       default=str)[:8000]))
        last = ses.last_refinement()
        outcome["assessment"] = (
            "step budget exhausted"
            + (f"; final state R1={last.r1_strong}, {ses.model.scatterers().size()} "
               f"atoms in {ses.symmetry.space_group_info()}" if last and ses.model
               is not None and ses.symmetry is not None else ""))
        outcome["usage"] = self.usage
        store.emit("agent_finish", outcome, trajectory_id=self.ctx.trajectory_id)
        return outcome


# ----------------------------------------------------------------------
REPAIR_TASK = """\
The deterministic standard pipeline has just run on this dataset; its outcome and the \
current state are attached. Review the result as a critical crystallographer:
1. Is the space group right? (Check sg_candidates; ties may need trial solutions in \
alternatives - use set_space_group + solve_charge_flipping + interpret_peaks + refine \
to test one, then compare and keep the better trajectory.)
2. Are elements assigned sensibly (ADP suspects, C/N/O by chemistry, missed heavy \
atoms)? Fix with edit_atoms.
3. Is the model complete? Use fourier_complete to grow a partial model efficiently \
(it runs several refine+add+prune cycles in one call). Ghosts to delete? \
Occupancy/disorder signs?
4. Does MOF chemistry validate (coordination, framework dimensionality)?
Then refine to convergence and finish with your assessment. If the pipeline outcome is \
already good, verify briefly and finish - do not churn.\
"""


def file_approval_gate(store: RunStore, timeout_s: float = 1800,
                       poll_s: float = 1.0):
    """Copilot-mode gate: emit pending_approval, wait for a matching decision in
    <run>/approvals.jsonl (written by the server's /approve endpoint). Fails OPEN
    on timeout (run continues as Auto would) with an audit note."""
    import time as _time

    def gate(tool: str, params: dict, rationale: str):
        ev = store.emit("pending_approval",
                        {"tool": tool, "params": params,
                         "rationale": (rationale or "")[:2000]})
        approvals = store.dir / "approvals.jsonl"
        deadline = _time.time() + timeout_s
        while _time.time() < deadline:
            if approvals.exists():
                for line in approvals.read_text(encoding="utf-8").splitlines():
                    try:
                        d = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if d.get("event_id") == ev.event_id:
                        return bool(d.get("approve")), d.get("comment", "")
            _time.sleep(poll_s)
        store.emit("approval_timeout", {"event_id": ev.event_id, "tool": tool})
        return True, "auto-approved after approval timeout"
    return gate


def run_auto(dataset, runs_root: Path, run_id: str | None = None,
             symmetry_mode: str = "auto", max_steps: int = 15,
             llm_cfg: LLMConfig | None = None,
             task: str | None = None,
             copilot: bool = False) -> dict[str, Any]:
    """Auto Mode: deterministic pipeline first, then the agent reviews and repairs.
    copilot=True gates model-changing agent actions on user approval."""
    from ..pipeline.standard import run_standard
    from ..report.cif import structure_to_cif

    result = run_standard(dataset, runs_root, run_id=run_id,
                          symmetry_mode=symmetry_mode)
    ses: SolveSession | None = result.pop("_session", None)
    store: RunStore | None = result.pop("_store", None)
    registry = result.pop("_registry", None)
    if ses is None or store is None or ses.fo_sq is None:
        result["agent"] = {"status": "skipped", "reason": "pipeline produced no session"}
        return result

    pipeline_summary = {k: v for k, v in result.items()
                        if k in ("symmetry", "solution", "refinement", "validation",
                                 "error", "ok")}
    ctx = ToolContext(store=store, session=ses)
    gate = file_approval_gate(store) if copilot else None
    agent = CrystalAgent(registry, ctx, llm_cfg=llm_cfg, max_steps=max_steps,
                         approval_gate=gate)
    outcome = agent.run((task or REPAIR_TASK)
                        + "\n\nPipeline outcome:\n"
                        + json.dumps(pipeline_summary, ensure_ascii=False,
                                     default=str)[:6000])
    result["agent"] = outcome

    # final artifacts after agent edits
    if ses.model is not None:
        last = ses.last_refinement()
        cif_path = store.artifact_path("final.cif")
        structure_to_cif(ses.model, cif_path, wavelength=dataset.wavelength,
                         stats=last.as_dict() if last else None,
                         mask_info=result.get("solvent_mask"))
        result["cif"] = str(cif_path)
        result["refinement_history"] = [s.as_dict() for s in ses.refinement_history]
        if ses.last_refinement():
            result["refinement"] = ses.last_refinement().as_dict()
        if ses.symmetry is not None:
            result.setdefault("symmetry", {})
            if isinstance(result["symmetry"], dict):
                result["symmetry"]["space_group"] = str(ses.symmetry.space_group_info())
        if ses.validation:
            result["validation"] = {
                "alerts": ses.validation.get("alerts"),
                "confidence": ses.validation.get("confidence"),
                "framework_dimensionality":
                    ses.validation.get("connectivity", {}).get(
                        "framework_dimensionality"),
            }
    try:
        from ..report.html import write_html_report
        thoughts = [ev["payload"]["text"] for ev in store.events()
                    if ev.get("kind") == "agent_thought"
                    and ev.get("payload", {}).get("text")]
        cif_text = None
        if result.get("cif") and Path(result["cif"]).exists():
            cif_text = Path(result["cif"]).read_text(encoding="utf-8")
        html_path = store.artifact_path("report.html")
        write_html_report(html_path, title=store.run_id, report=result,
                          cif_text=cif_text, agent_thoughts=thoughts)
        result["html_report"] = str(html_path)
    except Exception:  # noqa: BLE001 - report generation must not fail the run
        pass
    store.save_json("report.json", {k: v for k, v in result.items()
                                    if not k.startswith("_")})
    result["_session"] = ses
    return result
