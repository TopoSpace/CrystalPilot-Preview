"""Trajectory tools: snapshot / restore the working state so the agent can branch
into alternative hypotheses (different space group, element scheme...) and keep the
best result without losing the current model.
"""
from __future__ import annotations

import copy
from typing import Any

from .base import Tool, ToolContext, ToolResult


def _capture(ses) -> dict[str, Any]:
    return {
        "symmetry": ses.symmetry,
        "fo_sq": ses.fo_sq,
        "model": ses.model.deep_copy_scatterers() if ses.model is not None else None,
        "cf_info": dict(ses.cf_info),
        "refinement_history": list(ses.refinement_history),
        "validation": copy.deepcopy(ses.validation),
    }


def _apply(ses, snap: dict[str, Any]) -> None:
    ses.symmetry = snap["symmetry"]
    ses.fo_sq = snap["fo_sq"]
    ses.model = (snap["model"].deep_copy_scatterers()
                 if snap["model"] is not None else None)
    ses.cf_info = dict(snap["cf_info"])
    ses.refinement_history = list(snap["refinement_history"])
    ses.validation = copy.deepcopy(snap["validation"])


class SnapshotState(Tool):
    name = "snapshot_state"
    description = ("Save the current working state (space group, model, refinement "
                   "history) under a name, so you can branch into an alternative "
                   "hypothesis and restore later if it turns out worse.")
    params_schema = {"type": "object",
                     "properties": {"name": {"type": "string"}},
                     "required": ["name"]}

    def run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        ses = ctx.session
        snaps = ses.flags.setdefault("snapshots", {})
        snaps[params["name"]] = _capture(ses)
        last = ses.last_refinement()
        return ToolResult(ok=True, summary={
            "saved": params["name"],
            "space_group": str(ses.symmetry.space_group_info()) if ses.symmetry else None,
            "n_atoms": ses.model.scatterers().size() if ses.model is not None else 0,
            "r1_strong": last.r1_strong if last else None,
            "snapshots": sorted(snaps)})


class RestoreState(Tool):
    name = "restore_state"
    description = "Restore a previously saved state snapshot (discarding current state)."
    params_schema = {"type": "object",
                     "properties": {"name": {"type": "string"}},
                     "required": ["name"]}

    def run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        ses = ctx.session
        snaps = ses.flags.get("snapshots", {})
        name = params["name"]
        if name not in snaps:
            return ToolResult.failure(
                f"no snapshot {name!r}; available: {sorted(snaps)}")
        _apply(ses, snaps[name])
        last = ses.last_refinement()
        return ToolResult(ok=True, summary={
            "restored": name,
            "space_group": str(ses.symmetry.space_group_info()) if ses.symmetry else None,
            "n_atoms": ses.model.scatterers().size() if ses.model is not None else 0,
            "r1_strong": last.r1_strong if last else None})
