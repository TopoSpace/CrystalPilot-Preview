"""Symmetry tools: automatic space-group determination + adopting a working SG."""
from __future__ import annotations

from typing import Any

from cctbx import crystal, sgtbx

from .base import Tool, ToolContext, ToolResult
from .sg_determination import determine_space_group


def _to_input_basis(cand: dict):
    """Express a candidate space group in the basis of the ORIGINAL input cell.

    The determination module works in each candidate's conventional ('best') cell,
    reached via cand['cb_op_inp']. Applying the conventional-setting symbol directly
    to the input cell is WRONG when the change of basis is non-trivial (e.g. the
    same #14 group is P2_1/n in the conventional cell but P2_1/c in the input cell -
    picking the wrong glide corrupts the systematic absences and breaks solution).
    """
    g = sgtbx.space_group_info(symbol="hall: " + cand["hall"]).group()
    try:
        cb = sgtbx.change_of_basis_op(cand["cb_op_inp"])
        if not cb.is_identity_op():
            g = g.change_basis(cb.inverse())
    except (RuntimeError, KeyError):
        pass
    info = sgtbx.space_group_info(group=g)
    return g, str(info.symbol_and_number()).split("(")[0].strip()


class DetermineSpaceGroup(Tool):
    name = "determine_space_group"
    description = (
        "Determine candidate space groups from the unmerged intensities alone "
        "(XPREP-equivalent): Laue-group R_int scan, lattice centering, systematic "
        "absences, E-statistics. Returns a ranked candidate list; ties (e.g. polar vs "
        "centrosymmetric in the same Laue class) must be resolved by trial solutions. "
        "Candidates are stored in the session for set_space_group.")
    params_schema = {
        "type": "object",
        "properties": {
            "max_candidates": {"type": "integer", "default": 8},
        },
    }

    def run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        ses = ctx.session
        raw = ses.dataset.intensities
        result = determine_space_group(raw)
        cands = result["candidates"][: int(params.get("max_candidates", 8))]
        for c in cands:
            try:
                g_in, symbol_in = _to_input_basis(c)
                c["space_group_input_basis"] = symbol_in
                c["hall_input_basis"] = g_in.type().hall_symbol()
            except RuntimeError:
                c["space_group_input_basis"] = c["space_group"]
                c["hall_input_basis"] = c.get("hall")
        ses.sg_candidates = cands
        hint = None
        if ses.dataset.symmetry_hint is not None:
            hint = str(ses.dataset.symmetry_hint.space_group_info())
        # flag near-ties: intensity statistics cannot separate these candidates -
        # they must be resolved by trial solutions (agent's job)
        ambiguous = []
        if len(cands) >= 2:
            top = cands[0]["total_score"]
            ambiguous = [c["space_group"] for c in cands[1:]
                         if abs(c["total_score"] - top) < 20.0]
        return ToolResult(ok=True, summary={
            "ambiguous_with_top": ambiguous,
            "note": ("top candidates are statistically tied - resolve by trial "
                     "solutions in each" if ambiguous else None),
            "laue_group": result.get("laue_group"),
            "laue_r_int": result.get("laue_r_int"),
            "centering": result.get("centering"),
            "e_sq_minus_1": result.get("e_sq_minus_1"),
            "source_symmetry_hint": hint,
            "candidates": [
                {"space_group": c.get("space_group_input_basis", c["space_group"]),
                 "sg_number": c["sg_number"],
                 "total_score": round(c["total_score"], 1),
                 "r_int": c.get("r_int"),
                 "centrosymmetric": c.get("centrosymmetric"),
                 "n_absence_violations": c.get("n_absence_violations")}
                for c in cands],
        })


class SetSpaceGroup(Tool):
    name = "set_space_group"
    description = (
        "Adopt a working space group (by Hermann-Mauguin symbol, e.g. 'C 2 2 21', or "
        "'hint' to use the input file's claim). Re-merges the data accordingly and "
        "reports merging statistics. Use before solving, or to branch a new attempt "
        "in a different candidate.")
    params_schema = {
        "type": "object",
        "properties": {
            "space_group": {"type": "string",
                            "description": "H-M symbol / number, or 'hint'"},
        },
        "required": ["space_group"],
    }

    def run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        ses = ctx.session
        want = str(params["space_group"]).strip()
        if want.lower() == "hint":
            if ses.dataset.symmetry_hint is None:
                return ToolResult.failure("no symmetry hint in the input data")
            symm = ses.dataset.symmetry_hint
        else:
            try:
                sg_info = sgtbx.space_group_info(symbol=want)
            except RuntimeError as e:
                return ToolResult.failure(f"bad space group symbol {want!r}: {e}")
            symm = crystal.symmetry(
                unit_cell=ses.dataset.intensities.unit_cell(),
                space_group_info=sg_info)
        stats = ses.set_symmetry(symm)
        # invalidate downstream state from any previous space group
        ses.model = None
        ses.cf_info = {}
        return ToolResult(ok=True, summary=stats)


def determine_and_set_best(ctx: ToolContext) -> dict[str, Any]:
    """Deterministic helper: pick the top-ranked candidate and adopt it."""
    det = DetermineSpaceGroup().run(ctx)
    if not det.ok or not ctx.session.sg_candidates:
        raise RuntimeError(f"space-group determination failed: {det.error}")
    best = ctx.session.sg_candidates[0]
    symbol = ("hall: " + best["hall_input_basis"]) if best.get("hall_input_basis") \
        else best["space_group"]
    setter = SetSpaceGroup().run(ctx, space_group=symbol)
    if not setter.ok:
        raise RuntimeError(f"could not set space group: {setter.error}")
    return {"determined": det.summary, **setter.summary}
