"""Typed model parameters that do not require an unconstrained refinement."""

from __future__ import annotations

import copy
import math
import re
from typing import ClassVar

from ..tools.base import ToolResult
from .toolbase import _ProjectTool


def _atoms(xs, labels):
    if not isinstance(labels, list) or not labels or any(not isinstance(a, str) for a in labels):
        raise ValueError("atoms must be a non-empty ordered list of atom labels")
    by_label = {}
    for i, sc in enumerate(xs.scatterers()):
        by_label.setdefault(sc.label.upper(), []).append(i)
    if len({a.upper() for a in labels}) != len(labels):
        raise ValueError("duplicate atom labels are not allowed")
    invalid = [a for a in labels if len(by_label.get(a.upper(), [])) != 1]
    if invalid:
        raise ValueError(f"unknown or ambiguous atoms: {invalid}; nothing was changed")
    return [by_label[a.upper()][0] for a in labels]


class SetAdp(_ProjectTool):
    name = "set_adp"
    description = (
        "Convert only the named atoms' ADP representation (isotropic/anisotropic), "
        "without refining or changing coordinates, occupancy or element. Preserves "
        "AFIX, TWIN/BASF and FVAR linkage. Iso->aniso starts with the equivalent "
        "isotropic tensor projected onto site symmetry. Commits a node; then use "
        "run_shelxl(mode='adopt') to refine under the existing constraints."
    )
    params_schema: ClassVar[dict] = {
        "type": "object",
        "properties": {
            "atoms": {"type": "array", "minItems": 1, "items": {"type": "string"}},
            "mode": {"type": "string", "enum": ["anisotropic", "isotropic"]},
        },
        "required": ["atoms", "mode"],
    }

    def run(self, ctx, **params):
        from cctbx import adptbx
        from cctbx.array_family import flex

        ses = ctx.session
        xs = ses.model
        try:
            indices = _atoms(xs, params.get("atoms"))
            mode = params.get("mode")
            if mode not in ("anisotropic", "isotropic"):
                raise ValueError("mode must be anisotropic or isotropic")
            changed = [
                i
                for i in indices
                if xs.scatterers()[i].flags.use_u_aniso() != (mode == "anisotropic")
            ]
            riding = {
                h.upper()
                for g in (ses.flags.get("h_riding_meta") or {}).get("per_carrier", [])
                for h in g.get("h", [])
            }
            for i in changed:
                if xs.scatterers()[i].label.upper() in riding:
                    raise ValueError(
                        "riding-H ADPs are controlled by their carrier; set_adp cannot replace that constraint"
                    )
                u = xs.scatterers()[i].u_iso_or_equiv(xs.unit_cell())
                if not math.isfinite(u) or u <= 0:
                    raise ValueError(
                        f"{xs.scatterers()[i].label} has nonpositive/invalid Ueq; repair its ADP first"
                    )
        except ValueError as exc:
            return ToolResult.failure(str(exc))
        if not changed:
            return ToolResult(
                ok=True,
                summary={
                    "no_state_change": True,
                    "mode": mode,
                    "note": "all selected atoms already use this ADP representation",
                },
            )
        if mode == "anisotropic":
            xs.convert_to_anisotropic(selection=xs.by_index_selection(changed))
            for i in changed:
                sc = xs.scatterers()[i]
                sc.u_star = xs.site_symmetry_table().get(i).average_u_star(sc.u_star)
        else:
            xs.convert_to_isotropic(selection=flex.size_t(changed))
        rows = []
        for i in indices:
            sc = xs.scatterers()[i]
            rows.append(
                {
                    "atom": sc.label,
                    "changed": i in changed,
                    "multiplicity": sc.multiplicity(),
                    "u_eq": sc.u_iso_or_equiv(xs.unit_cell()),
                    "u_cif": list(adptbx.u_star_as_u_cif(xs.unit_cell(), sc.u_star))
                    if sc.flags.use_u_aniso()
                    else None,
                }
            )
        return ToolResult(
            ok=True,
            summary={
                "mode": mode,
                "atoms": rows,
                "note": "representation conversion only; coordinates, occupancy, element, AFIX and twin parameters are unchanged",
            },
        )


class SetAfix(_ProjectTool):
    name = "set_afix"
    description = (
        "Create/replace/remove a non-H AFIX rigid group using existing accepted atoms. "
        "AFIX 66 = six-membered regular ring in cyclic atom order; AFIX 6 = a whole "
        "connected rigid fragment at its existing geometry (e.g. all 14 atoms of an "
        "accepted anthracene core, with shared fused atoms listed ONCE). No atoms "
        "are created, fitted or moved here; missing candidates must first pass "
        "fit_fragment/accept_fragment_pose density checks. group_index is zero-based "
        "in the returned groups list. Creation checks PART, connectivity, overlap "
        "and site symmetry. Imported special-position groups can be removed, but "
        "creating a new rigid group on special positions needs a dedicated constraint "
        "model and is refused. Refine with SHELXL, not the in-process engine."
    )
    params_schema: ClassVar[dict] = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["list", "create", "replace", "remove"]},
            "atoms": {"type": "array", "minItems": 3, "items": {"type": "string"}},
            "afix": {"type": "integer", "enum": [6, 66]},
            "group_index": {"type": "integer", "minimum": 0},
            "reason": {
                "type": "string",
                "description": "why these accepted atoms should form one rigid group",
            },
        },
        "required": ["action"],
    }

    def run(self, ctx, **params):
        from cctbx.eltbx import covalent_radii

        from .nodes import serialization_extras

        ses = ctx.session
        xs = ses.model
        groups = copy.deepcopy(ses.flags.get("afix_groups") or [])
        action = params.get("action")
        if action == "list":
            return ToolResult(ok=True, summary={"no_state_change": True, "groups": groups})
        try:
            if action not in ("create", "replace", "remove"):
                raise ValueError("action must be list, create, replace or remove")
            reason = str(params.get("reason") or "").strip()
            if not reason:
                raise ValueError("reason is required for an AFIX change")
            index = params.get("group_index")
            if action in ("replace", "remove"):
                if (
                    isinstance(index, bool)
                    or not isinstance(index, int)
                    or not 0 <= index < len(groups)
                ):
                    raise ValueError(
                        "group_index must select an existing group (zero-based); use action='list'"
                    )
            elif index is not None:
                raise ValueError("group_index is only used for replace/remove")
            if action == "remove":
                removed = groups.pop(index)
                ses.flags["afix_groups"] = groups
                return ToolResult(
                    ok=True, summary={"removed": removed, "groups": groups, "reason": reason}
                )
            code = params.get("afix")
            if isinstance(code, bool) or code not in (6, 66):
                raise ValueError(
                    "supported AFIX types are 6 (existing rigid fragment) and 66 (regular hexagon)"
                )
            indices = _atoms(xs, params.get("atoms"))
            if len(indices) < 3 or (code == 66 and len(indices) != 6):
                raise ValueError(
                    "AFIX 6 needs >=3 atoms; AFIX 66 needs exactly six atoms in cyclic order"
                )
            scs = [xs.scatterers()[i] for i in indices]
            labels = [s.label for s in scs]
            occupied = {
                a.upper()
                for j, g in enumerate(groups)
                if action != "replace" or j != index
                for a in g["atoms"]
            }
            overlap = occupied.intersection(a.upper() for a in labels)
            if overlap:
                raise ValueError(
                    f"atoms already belong to another AFIX group: {sorted(overlap)}; fused atoms must appear once in one whole-fragment group"
                )
            if any(s.scattering_type.strip().upper() == "H" for s in scs):
                raise ValueError(
                    "list non-H skeleton atoms only; existing riding-H blocks are preserved automatically"
                )
            if any(s.multiplicity() != xs.space_group().order_z() for s in scs):
                raise ValueError(
                    "a selected atom is on a special position; unconstrained rigid motion is incompatible with its site symmetry"
                )
            parts = serialization_extras(ses.flags).get("parts") or {}
            if len({parts.get(a, 0) for a in labels}) != 1:
                raise ValueError("a rigid group must be contained in a single PART")
            cart = [xs.unit_cell().orthogonalize(s.site) for s in scs]
            radii = [
                covalent_radii.table(s.scattering_type.strip().capitalize()).radius() for s in scs
            ]
            adjacency = [
                {
                    j
                    for j in range(len(scs))
                    if j != i and 0.5 < math.dist(cart[i], cart[j]) <= radii[i] + radii[j] + 0.45
                }
                for i in range(len(scs))
            ]
            seen, todo = set(), [0]
            while todo:
                i = todo.pop()
                if i not in seen:
                    seen.add(i)
                    todo.extend(adjacency[i] - seen)
            if len(seen) != len(scs):
                raise ValueError(
                    "atoms are not connected in their stored coordinates; assemble the fragment before declaring a rigid group"
                )
            import numpy as np

            centered = np.asarray(cart) - np.mean(cart, axis=0)
            _, singular, vectors = np.linalg.svd(centered)
            if singular[1] < 0.05:
                raise ValueError("a rigid group needs noncollinear atoms")
            if code == 66:
                if any((i + 1) % 6 not in adjacency[i] for i in range(6)):
                    raise ValueError("AFIX 66 atom order must trace the six ring bonds")
                if float(np.max(np.abs(centered @ vectors[-1]))) > 0.15:
                    raise ValueError(
                        "AFIX 66 requires an already approximately planar ring; it is not a missing-geometry generator"
                    )
                if any(not 1.2 <= math.dist(cart[i], cart[(i + 1) % 6]) <= 1.65 for i in range(6)):
                    raise ValueError(
                        "AFIX 66 requires an existing aromatic-sized ring; bond lengths are outside 1.2..1.65 A"
                    )
            group = {"afix": int(code), "card": f"AFIX {code}", "atoms": labels}
            if action == "create":
                groups.append(group)
                index = len(groups) - 1
            else:
                groups[index] = group
            # Match the writer's canonical atom order so group_index remains
            # meaningful after commit, process restart and checkout.
            positions = {s.label.upper(): i for i, s in enumerate(xs.scatterers())}
            groups.sort(key=lambda g: positions[g["atoms"][0].upper()])
            index = groups.index(group)
        except (ValueError, RuntimeError) as exc:
            return ToolResult.failure(str(exc))
        ses.flags["afix_groups"] = groups
        return ToolResult(
            ok=True,
            summary={
                "action": action,
                "group_index": index,
                "group": group,
                "groups": groups,
                "reason": reason,
                "note": "existing coordinates were retained; constraints are a modelling choice, not new density evidence",
            },
        )


class SetSiteOccupancy(_ProjectTool):
    name = "set_site_occupancy"
    description = (
        "Set one existing atom's physical occupancy to fixed or SHELXL-FVAR-refinable. "
        "Keeps coordinates, element, ADP, AFIX and TWIN/BASF. value is physical "
        "occupancy (0..1), NEVER encoded SHELX SOF. A free site gets its own FVAR "
        "with the correct special-position multiplier. Use run_shelxl(adopt) and "
        "read site_occupancies (value and s.u.). Compare full/half/free trials on "
        "separate branches; occupancy/ADP correlation and element identity remain "
        "unresolved by a lower R alone. Shared disorder/SUMP linkage is not detached silently."
    )
    params_schema: ClassVar[dict] = {
        "type": "object",
        "properties": {
            "atom": {"type": "string"},
            "mode": {"type": "string", "enum": ["fixed", "free"]},
            "value": {"type": "number", "minimum": 0, "maximum": 1},
        },
        "required": ["atom", "mode"],
    }

    def run(self, ctx, **params):
        from .tools_disorder import _renumber_groups

        ses = ctx.session
        xs = ses.model
        try:
            i = _atoms(xs, [params.get("atom")])[0]
            sc = xs.scatterers()[i]
            mode = params.get("mode")
            if mode not in ("fixed", "free"):
                raise ValueError("mode must be fixed or free")
            value = params.get("value", float(sc.occupancy))
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or not 0 <= value <= 1
            ):
                raise ValueError(
                    "value must be physical occupancy in [0, 1], not an encoded SHELX SOF"
                )
            groups = copy.deepcopy(ses.flags.get("disorder_groups") or [])
            matching = [
                g
                for g in groups
                if any(m["label"].upper() == sc.label.upper() for m in g["members"])
            ]
            if len(matching) > 1 or any(len(g["members"]) != 1 for g in matching):
                raise ValueError(
                    "this atom shares a disorder/FVAR linkage; changing it alone would detach other atoms"
                )
            old = matching[0] if matching else None
            old_index = int(old["fvar_index"]) if old else None
            cards = ses.flags.get("effective_cards") or []
            if old and any(c.split()[0].upper() == "SUMP" for c in cards if c.split()):
                raise ValueError(
                    "SUMP is active; review/remove its free-variable linkage before replacing this occupancy parameter"
                )
            if old:
                groups.remove(old)
            renumbered = {}
            if mode == "free":
                index = old_index or (max([int(g["fvar_index"]) for g in groups], default=1) + 1)
                part = next((m.get("part") for m in (old or {}).get("members", [])), None)
                if part is None:
                    part = (ses.flags.get("parts_extra") or {}).get(sc.label, 0) or None
                multiplier = float(sc.weight_without_occupancy())
                groups.append(
                    {
                        "fvar_index": index,
                        "value": float(value),
                        "members": [
                            {"label": sc.label, "part": part, "sign": 1, "mult": multiplier}
                        ],
                    }
                )
            else:
                index = None
                renumbered = _renumber_groups(groups)
        except ValueError as exc:
            return ToolResult.failure(str(exc))
        ses.flags["disorder_groups"] = groups
        if old and mode == "fixed":
            member = old["members"][0]
            if member.get("part"):
                ses.flags.setdefault("parts_extra", {})[sc.label] = member["part"]
            origins = [
                copy.deepcopy(o)
                for o in (ses.flags.get("disorder_origins") or [])
                if o.get("fvar_index") != old_index
            ]
            for origin in origins:
                if origin.get("fvar_index") in renumbered:
                    origin["fvar_index"] = renumbered[origin["fvar_index"]]
            ses.flags["disorder_origins"] = origins
        sc.occupancy = float(value)
        return ToolResult(
            ok=True,
            summary={
                "atom": sc.label,
                "mode": mode,
                "occupancy": float(value),
                "fvar_index": index,
                "site_multiplier": float(sc.weight_without_occupancy()),
                "fvar_renumbered": renumbered,
                "note": "Occupancy can correlate strongly with ADP and scale; lower R is not an element or composition determination. Use SHELXL and report the s.u.",
            },
        )


def occupancy_adp_correlations(text):
    """Only the selected large correlations printed by SHELXL, not a full matrix."""
    start = text.lower().rfind("correlation matrix")
    if start < 0:
        return []
    term = r"(?:U(?:[123]{2}|iso)?\s+\S+|FVAR\s+\d+)"
    rows = []
    for match in re.finditer(
        r"(-?\d+\.\d+)\s+(" + term + r")\s*/\s*(" + term + r")", text[start:], re.IGNORECASE
    ):
        first, second = match.group(2).split(), match.group(3).split()
        if first[0].upper() == "FVAR":
            first, second = second, first
        if second[0].upper() != "FVAR" or not first[0].upper().startswith("U"):
            continue
        rows.append(
            {
                "atom": first[1].upper(),
                "adp": first[0],
                "fvar_index": int(second[1]),
                "fvar_adp_correlation": float(match.group(1)),
            }
        )
    return rows


def site_occupancy_readback(xs, groups, free_variables, correlations=()):
    """Decode physical occupancy/s.u. for independent one-atom FVAR groups."""
    atoms = {sc.label.upper(): sc for sc in xs.scatterers()}
    rows = []
    for group in groups:
        if len(group.get("members", [])) != 1:
            continue
        member = group["members"][0]
        sc = atoms.get(member["label"].upper())
        if sc is None:
            continue
        index = int(group["fvar_index"])
        fv = free_variables.get(
            f"fvar{index}", free_variables.get(index, free_variables.get(str(index), {}))
        )
        factor = float(member["mult"]) / float(sc.weight_without_occupancy())
        su = fv.get("su")
        rows.append(
            {
                "atom": sc.label,
                "occupancy": float(sc.occupancy),
                "su": abs(factor) * float(su) if su is not None and su > 0 else None,
                "su_status": "reported"
                if su is not None and su > 0
                else "below_shelxl_print_precision"
                if su == 0
                else "not_reported",
                "fvar_index": index,
                "fvar_value": float(group["value"]),
                "site_multiplier": float(sc.weight_without_occupancy()),
                "sof_multiplier": float(member["mult"]),
                "u_eq": float(sc.u_iso_or_equiv(xs.unit_cell())),
                "reported_adp_correlations": [
                    {
                        **r,
                        "occupancy_adp_correlation": r["fvar_adp_correlation"]
                        * (1 if int(member.get("sign", 1)) > 0 else -1),
                    }
                    for r in correlations
                    if r["atom"] == sc.label.upper() and r["fvar_index"] == index
                ],
                "correlation_coverage": "SHELXL prints selected large correlations; no listed correlation does not establish independence",
                "note": "occupancy/ADP correlation is not resolved by this s.u.; compare fixed-occupancy trials and do not infer element identity from R alone",
            }
        )
    return rows


def register_parameter_tools(reg, project):
    for cls in (SetAdp, SetAfix, SetSiteOccupancy):
        reg.register(cls(project))
