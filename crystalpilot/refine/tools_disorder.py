"""Disorder and twinning tools.

model_disorder: split atoms into two-site disorder with a shared SHELX free
variable (PART 1/2, sof = +/-(10k+p)); the smtbx engine keeps refining
positions/ADPs with occupancies held, and run_shelxl(mode='adopt') refines
the occupancy ratio (FVAR) natively. Special positions are native (pa1
batch: 9/9 cu runs were refused on the paddlewheel axial site "sits on a
special position ... edit_atoms(action='move') first" and none ever built
the model): p is the conserved sof budget (20.5/-20.5 for a mirror atom),
an existing atom can serve as part B, and a component displaced OFF its
special position takes its own symmetry image as the partner - one atom,
sof fixed by symmetry (10.5), negative PART, no FVAR.

model_disorder(undo=...) is the other half of the loop: a split that the
refined free variable does not support is REMOVED cleanly (components
merged back to one site at the occupancy-weighted position, FVAR dropped
and the remaining groups renumbered, PART cards gone, added atoms deleted
with the same restraint/riding-H hygiene edit_atoms uses), so an abandoned
trial leaves no debris in the model that ships.

The judgment itself lives in refine/disorder_accept.py: after SHELXL has
refined the free variable, its VALUE AND S.U. decide whether the split is
`supported` / `inconclusive` / `revoke`. The reg1-ext2 regression is why -
two organic cases with a deposited PART split were delivered unmodelled,
one because a trial split was abandoned as soon as R1 rose, and no tool
told either agent whether the data supported the split.

set_twin: declare a twin law (TWIN/BASF). smtbx does not refine twinned
data - the refine tool refuses while a twin is active and SHELXL owns the
BASF refinement. 'suggest' lists metric-possible laws without applying.
"""
from __future__ import annotations

import math
import re
import time
from typing import Any

from ..io.twin import twin_component_count
from ..tools.base import ToolContext, ToolResult
from .tools_extra import _ProjectTool

#: two components closer than this to their own symmetry image are bonded
#: by SHELXL/cctbx connectivity unless the PART number is negative
_IMAGE_BOND_D = 2.0
#: a second site within this distance of an existing atom means "link that
#: atom as part B" (cu-l2-r1 passed N3's exact site as N2's second site)
_EXISTING_ATOM_D = 0.15
#: a difference-map peak this far from the atom being split is taken as the
#: second site (closer is the atom's own ripple, farther is another atom)
_PEAK_D_MIN, _PEAK_D_MAX = 0.4, 1.6


def _split_evidence(xs, origin: dict, summary: dict) -> list[dict]:
    """What the model itself says about each drawn second site, so the
    agent's usual objections meet numbers instead of a hunch:

      * nearest modelled H to the B site - a B site ON an H position would
        be H density mis-modelled as a minor atom (reg5-dbu worried about
        exactly this and undid the split without refining; the nearest H
        was 1.1 A away);
      * the carrier's U_eq against the model's own median and its ADP
        anisotropy (max/min eigenvalue) - a fat, elongated carrier with a
        residual next to it is the classic unresolved second position.
    """
    from cctbx import adptbx
    uc = xs.unit_cell()
    sg = xs.space_group()
    scs = list(xs.scatterers())
    by = {sc.label.upper(): sc for sc in scs}
    others = [float(adptbx.u_star_as_u_iso(uc, sc.u_star)
                    if sc.flags.use_u_aniso() else sc.u_iso)
              for sc in scs if sc.scattering_type.strip().upper() != "H"]
    others.sort()
    median = others[len(others) // 2] if others else None
    out: list[dict] = []
    for row in summary.get("split") or []:
        if row.get("mode") != "two_site":
            continue
        a = by.get(str(row["a"]).upper())
        b = by.get(str(row["b"]).upper())
        if a is None or b is None:
            continue
        ev: dict = {"a": row["a"], "b": row["b"],
                    "second_site_from": row.get("second_site_from")}
        near_h = None
        for sc in scs:
            if sc.scattering_type.strip().upper() != "H":
                continue
            d, _img = _nearest_image(uc, sg, tuple(b.site), tuple(sc.site))
            if near_h is None or d < near_h[0]:
                near_h = (d, sc.label)
        if near_h is not None:
            ev["nearest_modelled_H_to_B"] = {"label": near_h[1],
                                             "d_A": round(near_h[0], 2)}
        u_eq = float(row.get("carrier_u_eq_before") or 0.0)
        ev["carrier_u_eq"] = round(u_eq, 4)
        if median and u_eq:
            ev["carrier_u_eq_over_model_median"] = round(u_eq / median, 2)
        if row.get("carrier_adp_max_over_min") is not None:
            ev["carrier_adp_max_over_min"] = row["carrier_adp_max_over_min"]
        parts = []
        if near_h is not None:
            parts.append(
                f"the B site is {near_h[0]:.2f} A from the nearest modelled "
                f"H ({near_h[1]})" + (
                    " - it sits ON an H position: check the H model before "
                    "calling it a second atom" if near_h[0] < 0.35 else
                    " - not an H position"))
        if median and u_eq:
            parts.append(f"{row['a']} U_eq {u_eq:.3f} (before the split) is "
                         f"{u_eq / median:.1f}x the model's median non-H U_eq")
        if "carrier_adp_max_over_min" in ev:
            parts.append(f"ADP max/min {ev['carrier_adp_max_over_min']}")
        ev["reading"] = ("; ".join(parts) + ". A fat, elongated carrier "
                         "with a residual next to it is the signature of an "
                         "unresolved second position; only refinement (FVAR "
                         "s.u., delta R1, residual after) can confirm or "
                         "revoke it") if parts else None
        out.append(ev)
    return out


def _peak_second_site(uc, sg, site0, peaks) -> dict | None:
    """The strongest difference peak that belongs to `site0` - within
    _PEAK_D_MIN.._PEAK_D_MAX A of it (nearest symmetry image) and closer to
    it than to any other atom - as the second site of a split.

    reg4-dbu (2026-09-04): the agent split the right two ring atoms with
    the default 0.6 A ADP-axis displacement while the map had 0.94 and
    0.38 e/A^3 peaks at 1.0 and 0.9 A from them; the tool then said the
    drawn 0.6 A was below d_min and the agent abandoned the split. The
    map knows where the second position is; use it."""
    best = None
    for pk in peaks or []:
        site = pk.get("site")
        if not site or len(site) != 3:
            continue
        try:
            h = float(pk.get("height") or 0.0)
        except (TypeError, ValueError):
            continue
        if h <= 0:
            continue
        d, img = _nearest_image(uc, sg, tuple(float(x) for x in site0),
                                tuple(float(x) for x in site))
        if not _PEAK_D_MIN <= d <= _PEAK_D_MAX:
            continue
        nearest_d = pk.get("nearest_d")
        if nearest_d is not None and float(nearest_d) < d - 0.05:
            continue                       # it is another atom's peak
        if best is None or h > best["height"]:
            best = {"site": img, "d": float(d), "height": h}
    return best


def _nearest_image(uc, sg, ref, site) -> tuple[float, tuple]:
    """(distance, image): the symmetry + lattice image of `site` closest
    to `ref` (difference-map peaks live in the ASU, not next to the
    target atom)."""
    best_d, best = None, tuple(float(x) for x in site)
    for i_op in range(sg.order_z()):
        img = sg(i_op) * site
        img = tuple(img[k] - round(img[k] - ref[k]) for k in range(3))
        d = uc.distance(ref, img)
        if best_d is None or d < best_d:
            best_d, best = d, img
    return float(best_d), best


def _nearest_own_image(uc, sg, site) -> float:
    """Distance from `site` to its closest symmetry equivalent (identity
    excluded; inf in P1). 0 on a special position."""
    best = None
    for i_op in range(1, sg.order_z()):
        img = sg(i_op) * site
        img = tuple(img[k] - round(img[k] - site[k]) for k in range(3))
        d = uc.distance(site, img)
        if best is None or d < best:
            best = d
    return float(best) if best is not None else math.inf


def _site_info(xs, site) -> dict[str, Any]:
    """Site symmetry of a fractional site under the model's own
    special-position tolerance: exact (snapped) site, multiplicity, the
    SHELX multiplicity factor and a human label ('m', 'x,y,1/2')."""
    ss = xs.site_symmetry(site)
    mult = int(ss.multiplicity())
    special = not ss.is_point_group_1()
    return {"site": tuple(float(x) for x in ss.exact_site()),
            "multiplicity": mult,
            "factor": mult / xs.space_group().order_z(),
            "point_group": str(ss.point_group_type()),
            "special_op": (str(ss.special_op_simplified()) if special
                           else None),
            "special": special}


def _site_label(info: dict[str, Any]) -> str:
    if not info["special"]:
        return "general position"
    return (f"special position {info['special_op']} (site symmetry "
            f"{info['point_group']}, multiplicity factor "
            f"{info['factor']:.4g})")


def _refresh_site_symmetry(xs, indices: list[int]) -> None:
    """Re-derive site symmetry for the scatterers in `indices` only (an
    atom moved off a mirror keeps the mirror constraint and its halved
    weight otherwise). Only the moved atoms are re-derived: a whole-model
    rebuild would also re-snap any unrelated atom that refinement drifted
    close to a special position and silently halve its weight."""
    from cctbx import sgtbx
    uc, sg = xs.unit_cell(), xs.space_group()
    old = xs.site_symmetry_table()
    fresh = {}
    for i in indices:
        fresh[i] = xs.scatterers()[i].apply_symmetry(
            uc, sg, xs.min_distance_sym_equiv())
    new = sgtbx.site_symmetry_table()
    for k in range(xs.scatterers().size()):
        new.process(fresh[k] if k in fresh else old.get(k))
    xs.replace_scatterers(xs.scatterers(), site_symmetry_table=new)
    xs.scattering_type_registry(table="it1992")


def _u_eq_of(uc, sc) -> float:
    from cctbx import adptbx
    if sc.flags.use_u_aniso():
        return float(adptbx.u_star_as_u_iso(uc, sc.u_star))
    return float(sc.u_iso)


def _atom_state(xs, sc) -> dict[str, Any]:
    """JSON-able snapshot of one scatterer - the undo record's unit. It
    rides in the session flags and into node.json, so everything here is
    a plain float/bool/str."""
    return {"label": sc.label,
            "element": sc.scattering_type,
            "site": [float(x) for x in sc.site],
            "occupancy": float(sc.occupancy),
            "aniso": bool(sc.flags.use_u_aniso()),
            "u_iso": float(_u_eq_of(xs.unit_cell(), sc)),
            "u_star": ([float(x) for x in sc.u_star]
                       if sc.flags.use_u_aniso() else None)}


def _resolve_undo_ref(ref: str, groups: list[dict],
                      parts_extra: dict) -> tuple[int | None, str | None]:
    """undo=<ref> -> (fvar_index, image_label). Accepts 'fvar2', '2', 2 or
    any component label, because an agent holding a verdict on C15B should
    not have to look up which free variable that atom hangs off."""
    key = str(ref).strip()
    m = re.fullmatch(r"(?:fvar\s*)?(\d+)", key, re.I)
    if m:
        k = int(m.group(1))
        if any(int(g.get("fvar_index", 0)) == k for g in groups):
            return k, None
        return None, None
    up = key.upper()
    for g in groups:
        if any(str(mem.get("label", "")).upper() == up
               for mem in g.get("members", ())):
            return int(g["fvar_index"]), None
    for lbl in parts_extra:
        if str(lbl).upper() == up:
            return None, key
    return None, None


def _renumber_groups(groups: list[dict]) -> dict[int, int]:
    """Free variables must stay a contiguous 2..n block: the FVAR card is
    a positional list, so removing FVAR2 while a group still codes its
    sofs on 3x.xx would silently re-point every one of them at the wrong
    variable. Returns {old: new} for the groups that moved."""
    groups.sort(key=lambda g: int(g["fvar_index"]))
    renum: dict[int, int] = {}
    for n, g in enumerate(groups, start=2):
        old = int(g["fvar_index"])
        if old != n:
            renum[old] = n
            g["fvar_index"] = n
    return renum


def _delete_hygiene(ses, deleted: set[str]) -> dict[str, Any]:
    """Same-fate cleanup for atoms an undo removed: riding-H metadata,
    in-process riding constraints and restraint specs that name them.
    Identical policy to edit_atoms(action='delete') - a spec left pointing
    at a deleted atom rides into every future SHELXL job and aborts it."""
    out: dict[str, Any] = {}
    if not deleted:
        return out
    h_meta = ses.flags.get("h_riding_meta") or {}
    per_carrier = h_meta.get("per_carrier") or []
    if per_carrier:
        kept, pruned = [], 0
        for g in per_carrier:
            if str(g.get("carrier", "")).upper() in deleted:
                pruned += 1
                continue
            hs = [h for h in g.get("h", []) if h.upper() not in deleted]
            if len(hs) != len(g.get("h", [])):
                pruned += 1
            if hs:
                kept.append({**g, "h": hs})
        if pruned:
            h_meta["per_carrier"] = kept
            ses.flags["h_riding_meta"] = h_meta
            out["h_metadata_pruned"] = pruned
    if ses.flags.pop("h_constraints", None) is not None:
        out["h_constraints_cleared"] = True
    rs = ses.flags.get("restraints")
    if isinstance(rs, list) and rs:
        from .restraints import prune_specs_for_deleted
        kept_rs, dropped = prune_specs_for_deleted(rs, deleted)
        if dropped:
            ses.flags["restraints"] = kept_rs
            out["restraints_pruned"] = dropped
    from .parts import prune_parts_for_deleted
    parts = prune_parts_for_deleted(ses.flags, deleted, by="model_disorder undo")
    if parts:
        out["part_hygiene"] = parts
    if ses.flags.get("effective_cards"):
        from .shelx_cards import prune_cards_for_deleted
        kept_c, dropped_c = prune_cards_for_deleted(
            ses.flags["effective_cards"], deleted)
        if dropped_c:
            if kept_c:
                ses.flags["effective_cards"] = kept_c
            else:
                ses.flags.pop("effective_cards", None)
                ses.flags.pop("effective_cards_job", None)
            out["cards_pruned"] = dropped_c
    return out


def register_disorder_tools(reg, project) -> None:
    for cls in (ModelDisorder, SetTwin, InvertStructure):
        reg.register(cls(project))


# ==========================================================================
def _free_h_label(taken: set[str], h_label: str) -> str:
    """A SHELX label (<= 4 chars) for the copy of riding hydrogen
    `h_label` on the second component: the trailing letter is advanced
    (H15A -> H15C when H15B exists), else a 2-digit numeric tail."""
    base = str(h_label).strip()
    stem = base[:-1] if len(base) > 1 and base[-1].isalpha() else base
    stem = stem[:3]
    for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        cand = f"{stem}{ch}"
        if cand.upper() not in taken:
            return cand
    for n in range(1, 100):
        cand = f"H{n:02d}"[:4]
        if cand.upper() not in taken:
            return cand
    raise ValueError("no free hydrogen label left")


def _split_riding_h(xs, per_carrier: list[dict], entry: dict) -> list[str]:
    """reg8: when carrier A is split into A / B, its riding hydrogens are
    duplicated onto B (same AFIX group, sites shifted by B - A, occupancy
    of B); SHELXL re-idealises them on the next run. Returns the new H
    labels (empty when A carries no riding H) and appends B's group to
    `per_carrier`. Scatterer data are read BEFORE any add_scatterer
    (proxies are invalidated by it)."""
    from cctbx import xray as _xray

    carrier = str(entry["label"]).upper()
    grp = next((g for g in per_carrier
                if str(g.get("carrier") or "").upper() == carrier), None)
    if not grp or not grp.get("h"):
        return []
    scs = xs.scatterers()
    by_upper = {sc.label.upper(): i for i, sc in enumerate(scs)}
    taken = set(by_upper)
    shift = tuple(float(b) - float(a)
                  for a, b in zip(entry["site_a"], entry["site_b"]))
    todo = []
    for hl in grp["h"]:
        hi = by_upper.get(str(hl).upper())
        if hi is None:
            continue
        hsc = scs[hi]
        todo.append((hl, tuple(float(x) + s for x, s in zip(hsc.site, shift)),
                     float(hsc.u_iso if not hsc.flags.use_u_aniso() else 0.05)))
    new_h: list[str] = []
    for hl, site, u in todo:
        lbl = _free_h_label(taken, hl)
        taken.add(lbl.upper())
        xs.add_scatterer(_xray.scatterer(
            label=lbl, site=site, u=u, occupancy=float(entry["occ_b"]),
            scattering_type="H"))
        new_h.append(lbl)
    if new_h:
        per_carrier.append({**{k: v for k, v in grp.items() if k != "h"},
                            "carrier": entry["lbl_b"], "h": new_h})
    return new_h


class ModelDisorder(_ProjectTool):
    name = "model_disorder"
    description = (
        "Split atom(s) into two-site disorder: part A keeps the label, part "
        "B is added displaced along the ADP major axis (or at second_sites= "
        "from a difference peak; a second site that coincides with an "
        "EXISTING atom links that atom as part B instead of adding one), "
        "both go isotropic, occupancies are linked through one SHELX free "
        "variable (A=k, B=1-k) with PART 1/2. All atoms in one call share "
        "the SAME variable (a disordered fragment). Special positions are "
        "handled natively: a component that stays on its mirror/axis keeps "
        "its multiplicity (sof written 20.5/-20.5 = 0.5*FVAR, the atom "
        "count is conserved); a second site OFF the special position moves "
        "the atom there and its own symmetry image becomes the partner - "
        "one atom, sof fixed by symmetry (10.5), negative PART, no FVAR "
        "(the ratio is 50:50 by symmetry). The result states multiplicity, "
        "sof and PART written for every component; nothing to hand-edit. "
        "Refine the ratio with run_shelxl(mode='adopt') - the in-process "
        "refine keeps occupancies fixed. Evidence first: split only when "
        "the density demands it (elongated ADP alone is weak; a nearby "
        "difference peak + failed single-site model is strong), and compare "
        "against the unsplit branch before accepting. THE SPLIT IS A "
        "HYPOTHESIS UNTIL THE FREE VARIABLE IS REFINED: run_shelxl returns "
        "disorder_acceptance with the refined occupancy AND ITS S.U. and a "
        "verdict supported / inconclusive / revoke; the result here carries "
        "the SADI+SIMU cards the group should get (restraint_suggestion, "
        "apply with set_restraints - never applied silently). "
        "undo='fvar2' (or any component label) REMOVES a split that did not "
        "hold up: components merge back to one site at the occupancy-"
        "weighted position, the FVAR and PART cards go, atoms this tool "
        "added are deleted with their restraints and riding H.")
    params_schema = {
        "type": "object",
        "properties": {
            "atoms": {"type": "array", "items": {"type": "string"},
                      "minItems": 1},
            "undo": {"type": "string",
                     "description": "remove an existing split instead of "
                                    "making one: 'fvar2' / '2' (the group's "
                                    "free variable) or any component label "
                                    "('C15', 'C15B'). Components merge back "
                                    "to a single site at the occupancy-"
                                    "weighted position, added atoms are "
                                    "deleted, FVAR/PART are dropped and the "
                                    "remaining groups are renumbered"},
            "second_sites": {
                "type": "object",
                "description": "label -> [x,y,z] fractional site for part B "
                               "(a difference-map peak, or the site of an "
                               "existing atom to link as part B); atoms "
                               "without an entry are displaced along their "
                               "ADP major axis. For an atom on a special "
                               "position: a site on the same mirror/axis "
                               "gives an in-plane two-site split; a site off "
                               "it moves the atom there and takes its "
                               "symmetry image as the partner"},
            "separation": {"type": "number", "default": 0.6,
                           "description": "A-B distance (Angstrom) for the "
                                          "ADP-axis displacement. Only used "
                                          "when neither second_sites nor a "
                                          "difference-map peak (0.4-1.6 A "
                                          "from the atom, last refine) gives "
                                          "the second site - the peak is "
                                          "preferred automatically"},
            "occupancy": {"type": "number", "default": 0.5,
                          "description": "starting occupancy share of part "
                                         "A (ignored when the partner is a "
                                         "symmetry image: equal by "
                                         "symmetry)"},
        },
    }

    def run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        ses = ctx.session
        if ses is None or ses.model is None:
            return ToolResult.failure("no model loaded")
        if params.get("undo") not in (None, ""):
            return self._undo(ctx, str(params["undo"]))
        if not params.get("atoms"):
            return ToolResult.failure(
                "model_disorder needs atoms=[...] to split, or "
                "undo=<group> to remove a split the refinement did not "
                "support (undo='fvar2', or any component label)")
        return self._split(ctx, **params)

    # ------------------------------------------------------------------
    def _split(self, ctx: ToolContext, **params: Any) -> ToolResult:
        from cctbx import adptbx, xray
        ses = ctx.session
        xs = ses.model
        scs = list(xs.scatterers())
        by_label = {sc.label.upper(): i for i, sc in enumerate(scs)}
        labels = [str(a) for a in params["atoms"]]
        occ = float(params.get("occupancy", 0.5))
        if not 0.05 <= occ <= 0.95:
            return ToolResult.failure("occupancy must be in [0.05, 0.95]")
        sep = float(params.get("separation", 0.6))
        second = {str(k).upper(): v for k, v in
                  (params.get("second_sites") or {}).items()}

        groups = list(ses.flags.get("disorder_groups") or [])
        parts_extra = dict(ses.flags.get("parts_extra") or {})
        in_group = {m["label"].upper() for g in groups
                    for m in g.get("members", [])}
        in_part = {str(k).upper(): int(p) for k, p in parts_extra.items()}
        targets = {lb.upper() for lb in labels}
        idxs = []
        for lb in labels:
            i = by_label.get(lb.upper())
            if i is None:
                return ToolResult.failure(
                    f"unknown atom {lb!r}; model has "
                    f"{[sc.label for sc in scs]}")
            sc = scs[i]
            el = sc.scattering_type.strip().capitalize()
            if el == "H":
                return ToolResult.failure(
                    f"{lb}: split the carrier atom, not H (riding H follow "
                    f"their carrier)")
            if sc.label.upper() in in_group:
                return ToolResult.failure(
                    f"{lb} is already in a disorder group")
            if sc.label.upper() in in_part:
                p_x = in_part[sc.label.upper()]
                return ToolResult.failure(
                    f"{lb} is already in PART {p_x}"
                    + (" - disordered about a special position, its "
                       "symmetry image is the partner" if p_x < 0 else
                       " (a PART block without FVAR linkage)"))
            if (not sc.flags.use_u_aniso()
                    and sc.label.upper() not in second
                    and _peak_second_site(
                        xs.unit_cell(), xs.space_group(), tuple(sc.site),
                        ses.flags.get("diff_map_peaks")) is None):
                info = _site_info(xs, tuple(sc.site))
                hint = ""
                if info["special"]:
                    hint = (f" {lb} is on the {_site_label(info)}: a second "
                            f"site on the same special position gives an "
                            f"in-plane two-site split (sof "
                            f"{10 + info['factor']:.3f}-style, FVAR-linked); "
                            f"a site off it moves {lb} there and its "
                            f"symmetry image becomes the partner.")
                return ToolResult.failure(
                    f"{lb} is isotropic and no second_sites[{lb}] given - "
                    f"there is no defined split direction. Either refine it "
                    f"anisotropic first (the major axis defines the split) "
                    f"or pass the difference-peak position as second_sites."
                    + hint)
            idxs.append(i)

        uc = xs.unit_cell()
        sg = xs.space_group()
        min_sym_d = float(xs.min_distance_sym_equiv())
        existing = {sc.label.upper() for sc in scs}
        fvar_index = 2 + len(groups)
        # PART for symmetry-image disorder: -1 in an otherwise ordered
        # model (the textbook form); beyond that a fresh number so it never
        # shares |n| with a PART 1/2 group next to it (same |n| bonds)
        used = [abs(int(m.get("part") or 0)) for g in groups
                for m in g.get("members", [])] + [abs(p) for p in in_part.values()]
        image_part = -1 if not used else -(max(used + [2]) + 1)
        partners_taken: set[int] = set()
        # ---- phase 1: plan everything from a plain-Python snapshot -------
        # flex scatterer proxies are invalidated when add_scatterer
        # reallocates the array (multi-atom splits died with "cannot read
        # element from ''" and left half-mutated models behind); nothing
        # touches the model until every target validated.
        plan: list[dict] = []
        for i in idxs:
            sc = scs[i]
            site0 = tuple(float(x) for x in sc.site)
            w0 = float(sc.weight_without_occupancy())
            occ0 = float(sc.occupancy)
            info0 = _site_info(xs, site0)
            snap: dict[str, Any] = {
                "i": i, "label": sc.label, "element": sc.scattering_type,
                "site": site0, "info0": info0, "mode": "two_site",
                "partner": None,
                # sof budget the split conserves (general full atom: 1;
                # mirror atom: 0.5) - it is the p of the +/-(10k+p) codes
                "total": round(w0 * occ0, 5),
                "total_from": f"{sc.label} sof {w0 * occ0:.4g} "
                              f"(occupancy {occ0:.3g} x multiplicity "
                              f"factor {w0:.4g})"}
            site_a = site0
            site_b = None
            given_site = second.get(sc.label.upper())
            peaks = ses.flags.get("diff_map_peaks")
            if given_site is None:
                auto = _peak_second_site(uc, sg, site0, peaks)
                if auto is not None:
                    given_site = auto["site"]
                    snap["second_site_from"] = (
                        f"difference-map peak {auto['height']:.2f} e/A^3 "
                        f"at {auto['d']:.2f} A from {sc.label} (last "
                        f"refine's map; pass second_sites to override)")
            else:
                snap["second_site_from"] = "second_sites (given)"
            if given_site is not None:
                given = tuple(float(x) for x in given_site)
                # difference-map peaks live in the ASU, not next to the
                # target atom: fold the candidate through symmetry +
                # lattice translations to the image nearest site A
                # before judging (agents hit this twice - r14a 16.66 A
                # and r19 12.97 A - and had to hand-convert; r19's
                # manual +1 translation is exactly this loop)
                d, site_b = _nearest_image(uc, sg, site0, given)
                if not 0.2 <= d <= 2.0:
                    hint = ""
                    if info0["special"] and d < 0.2:
                        hint = (f" {sc.label} is on the {_site_label(info0)}"
                                f": to split it across that element give a "
                                f"site at least {(min_sym_d + 0.1) / 2:.2f} "
                                f"A off it (its image becomes the partner), "
                                f"or a site on it >= 0.2 A away for an "
                                f"in-plane two-site split.")
                    return ToolResult.failure(
                        f"{sc.label}: second site is "
                        f"{uc.distance(site0, given):.2f} A away and no "
                        f"symmetry image comes closer than {d:.2f} A - not "
                        f"a plausible split (expect 0.2-2.0 A)." + hint)
                if uc.distance(given, site_b) > 1e-3:
                    snap["site_b_folded"] = (
                        f"candidate folded to the symmetry image {d:.2f} A "
                        f"from {sc.label} (was "
                        f"{uc.distance(site0, given):.2f} A away)")
                # an existing atom at the second site is part B itself
                for j, other in enumerate(scs):
                    if j == i:
                        continue
                    dj, _ = _nearest_image(uc, sg, site_b, tuple(other.site))
                    if dj < _EXISTING_ATOM_D:
                        lb_j = other.label.upper()
                        if other.scattering_type.strip().capitalize() == "H":
                            return ToolResult.failure(
                                f"{sc.label}: the second site is the H atom "
                                f"{other.label} - give a heavy-atom site")
                        if lb_j in in_group or lb_j in in_part:
                            return ToolResult.failure(
                                f"{sc.label}: the second site is "
                                f"{other.label}, which is already in a "
                                f"disorder group / PART block")
                        if lb_j in targets or j in partners_taken:
                            return ToolResult.failure(
                                f"{sc.label}: the second site is "
                                f"{other.label}, which is itself a split "
                                f"target / partner in this call - list each "
                                f"atom once")
                        snap["partner"] = j
                        partners_taken.add(j)
                        site_b = tuple(float(x) for x in other.site)
                        break
                if snap["partner"] is None and info0["special"]:
                    info_b = _site_info(xs, site_b)
                    if uc.distance(site_b, info_b["site"]) > 0.01:
                        # given off the special position but inside the
                        # model's merge tolerance: site_symmetry() snapped
                        # it back (a 0.22 A-off site became B on top of A)
                        # - this is the image request, only too close
                        snap["mode"] = "image"
                        site_a, site_b = tuple(site_b), None
                    elif info_b["factor"] > w0 + 1e-6:
                        # off the special position: the atom moves there
                        # and its own image is the second component
                        snap["mode"] = "image"
                        site_a, site_b = info_b["site"], None
            else:
                # displace +/- sep/2 along the ADP major axis
                snap["second_site_from"] = (
                    f"ADP major axis, +/- {sep / 2:.2f} A (separation "
                    f"{sep:.2f} A): "
                    + ("no difference peak within "
                       f"{_PEAK_D_MIN:g}-{_PEAK_D_MAX:g} A of {sc.label} "
                       "in the last refine's map" if peaks else
                       "no difference map on record - refine first, the "
                       "map usually shows where the second position is")
                    + "; a drawn direction is a guess, a peak is evidence")
                u_cart = adptbx.u_star_as_u_cart(uc, sc.u_star)
                from scitbx import matrix
                from scitbx.linalg import eigensystem
                es = eigensystem.real_symmetric(u_cart)
                v = matrix.col(tuple(es.vectors())[0:3])
                v = v / abs(v)
                shift = uc.fractionalize(tuple(v * (sep / 2.0)))
                site_b = tuple(site0[k] + shift[k] for k in range(3))
                site_a = tuple(site0[k] - shift[k] for k in range(3))
                if info0["special"] and _nearest_image(
                        uc, sg, site_b, site_a)[0] < 0.05:
                    # the major axis is normal to the mirror/axis: the two
                    # displaced sites are symmetry images of each other
                    snap["mode"] = "image"
                    site_b = None
            u_eq = (adptbx.u_star_as_u_iso(uc, sc.u_star)
                    if sc.flags.use_u_aniso() else sc.u_iso)
            snap["u_eq"] = max(float(u_eq), 0.005)
            # the carrier's anisotropy BEFORE the split (the components are
            # written isotropic): evidence for _split_evidence
            snap["adp_ratio"] = None
            if sc.flags.use_u_aniso():
                from scitbx.linalg import eigensystem as _eig
                vals = sorted(float(v) for v in _eig.real_symmetric(
                    adptbx.u_star_as_u_cart(uc, sc.u_star)).values())
                snap["adp_ratio"] = (round(vals[-1] / vals[0], 1)
                                     if vals[0] > 0 else "NPD")
            total = snap["total"]

            if snap["mode"] == "image":
                d_img = _nearest_own_image(uc, sg, site_a)
                if d_img <= min_sym_d + 0.01:
                    return ToolResult.failure(
                        f"{sc.label}: the displaced site is only "
                        f"{d_img:.2f} A from its own symmetry image - "
                        f"below the {min_sym_d:.2f} A symmetry-merge "
                        f"distance of the model (and SHELXL's SPEC 0.2 A "
                        f"from the special position), so it would be "
                        f"snapped back onto the {_site_label(info0)}. Give "
                        f"a site at least {(min_sym_d + 0.1) / 2:.2f} A "
                        f"off it (or separation >= {min_sym_d + 0.1:.1f}).")
                info_a = _site_info(xs, site_a)
                occ_a = total / info_a["factor"]
                if occ_a > 1.0 + 1e-6:
                    return ToolResult.failure(
                        f"{sc.label}: moving to the {_site_label(info_a)} "
                        f"cannot hold its sof {total:.4g} (that site holds "
                        f"at most {info_a['factor']:.4g})")
                snap.update({"site_a": info_a["site"], "info_a": info_a,
                             "occ_a": occ_a, "d_ab": d_img,
                             "part_a": image_part,
                             "n_images": max(1, round(
                                 info_a["multiplicity"]
                                 / info0["multiplicity"]))})
                plan.append(snap)
                continue

            info_a = _site_info(xs, site_a)
            site_a = info_a["site"]
            if snap["partner"] is not None:
                other = scs[snap["partner"]]
                w_b = float(other.weight_without_occupancy())
                occ_b0 = float(other.occupancy)
                info_b = _site_info(xs, site_b)
                if occ0 < 0.999 and occ_b0 < 0.999:
                    # both already partial (a manual set_occupancy split,
                    # cu-l3-r2): their sum is the budget, not A alone
                    total = round(w0 * occ0 + w_b * occ_b0, 5)
                    snap["total_from"] = (
                        f"{sc.label} sof {w0 * occ0:.4g} + {other.label} "
                        f"sof {w_b * occ_b0:.4g} (both already partial)")
                else:
                    snap["total_from"] += (
                        f"; {other.label}'s own occupancy {occ_b0:.3g} is "
                        f"replaced by its share")
                snap["total"] = total
                snap["u_eq_b"] = max(float(
                    adptbx.u_star_as_u_iso(uc, other.u_star)
                    if other.flags.use_u_aniso() else other.u_iso), 0.005)
                lbl_b = other.label
            else:
                info_b = _site_info(xs, site_b)
                site_b = info_b["site"]
                if uc.distance(site_a, site_b) < 0.2:
                    return ToolResult.failure(
                        f"{sc.label}: the second site snaps onto the "
                        f"{_site_label(info_b)} only "
                        f"{uc.distance(site_a, site_b):.2f} A from "
                        f"{sc.label} - not a distinct second site")
                base = sc.label[:3] if len(sc.label) >= 4 else sc.label
                lbl_b = None
                for cand in ([base + "B"] +
                             [f"{base}{c}" for c in "CDEFG23456789"]):
                    if cand.upper() not in existing and len(cand) <= 4:
                        lbl_b = cand
                        break
                if lbl_b is None:
                    return ToolResult.failure(
                        f"could not derive a free 4-char label for the B "
                        f"part of {sc.label}; rename_atoms first")
                existing.add(lbl_b.upper())
            # chemical occupancies: each component's weight is its share
            # of the budget, so occ = share * total / multiplicity factor
            occ_a = occ * total / info_a["factor"]
            occ_b = (1.0 - occ) * total / info_b["factor"]
            for lb_x, occ_x, info_x in ((sc.label, occ_a, info_a),
                                        (lbl_b, occ_b, info_b)):
                if occ_x > 1.0 + 1e-6:
                    return ToolResult.failure(
                        f"{lb_x} on the {_site_label(info_x)} holds at most "
                        f"sof {info_x['factor']:.4g}, but its share of the "
                        f"budget {total:.4g} at occupancy={occ} is "
                        f"{occ_x * info_x['factor']:.4g} - choose the A "
                        f"share so neither component exceeds its site")
            # a general-position component within bonding distance of its
            # own image needs a negative PART (no image bond, no SPEC snap)
            part_a = 1 if (info_a["special"] or _nearest_own_image(
                uc, sg, site_a) >= _IMAGE_BOND_D) else -1
            part_b = 2 if (info_b["special"] or _nearest_own_image(
                uc, sg, site_b) >= _IMAGE_BOND_D) else -2
            snap.update({"site_a": site_a, "site_b": site_b,
                         "info_a": info_a, "info_b": info_b,
                         "lbl_b": lbl_b, "occ_a": occ_a, "occ_b": occ_b,
                         "part_a": part_a, "part_b": part_b,
                         "d_ab": uc.distance(site_a, site_b)})
            plan.append(snap)

        # ---- phase 2: mutate (edits first via fresh handles, then adds) --
        # undo record FIRST: every atom this call is about to change, as it
        # stands now. Without it an abandoned trial can only be rolled back
        # by checking out an older node, which also discards everything
        # else done since (reg1-ext2 twintrap: the agent's split_o5_trial
        # was left in the tree instead).
        restore = [_atom_state(xs, xs.scatterers()[e["i"]]) for e in plan]
        restore += [_atom_state(xs, xs.scatterers()[e["partner"]])
                    for e in plan if e.get("partner") is not None]
        members: list[dict] = []
        created: list[dict] = []
        messages: list[str] = []
        refresh: list[int] = []
        for entry in plan:
            sc = xs.scatterers()[entry["i"]]
            sc.site = entry["site_a"]
            sc.u_iso = entry["u_eq"]
            sc.set_use_u_iso_only()
            sc.occupancy = entry["occ_a"]
            if entry["info_a"]["multiplicity"] != entry["info0"]["multiplicity"]:
                refresh.append(entry["i"])
            if entry["partner"] is not None:
                other = xs.scatterers()[entry["partner"]]
                other.u_iso = entry["u_eq_b"]
                other.set_use_u_iso_only()
                other.occupancy = entry["occ_b"]
        h_meta = dict(ses.flags.get("h_riding_meta") or {})
        per_carrier = list(h_meta.get("per_carrier") or [])
        riding_added = False
        for entry in plan:
            if entry["mode"] == "two_site" and entry["partner"] is None:
                # riding H first: reads A's H before add_scatterer
                # invalidates the scatterer proxies
                grp = next((g for g in per_carrier
                            if str(g.get("carrier") or "").upper()
                            == entry["label"].upper()), None)
                entry["h_a"] = list(grp["h"]) if grp and grp.get("h") else []
                xs.add_scatterer(xray.scatterer(
                    label=entry["lbl_b"], site=entry["site_b"],
                    u=entry["u_eq"], occupancy=entry["occ_b"],
                    scattering_type=entry["element"]))
                entry["h_b"] = _split_riding_h(xs, per_carrier, entry)
                riding_added = riding_added or bool(entry["h_b"])
        if refresh:
            _refresh_site_symmetry(xs, refresh)

        def fmt_site(s) -> list[float]:
            return [round(float(x), 5) for x in s]

        for entry in plan:
            lb, total = entry["label"], entry["total"]
            info0, info_a = entry["info0"], entry["info_a"]
            if entry["mode"] == "image":
                sof = 10.0 + total
                moved = uc.distance(entry["site"], entry["site_a"])
                created.append({
                    "a": lb, "b": None, "mode": "symmetry_image",
                    "d_ab": round(entry["d_ab"], 3),
                    "moved_a": round(moved, 3),
                    "site_a": fmt_site(entry["site_a"]),
                    "n_components": entry["n_images"],
                    "site_symmetry": {"before": _site_label(info0),
                                      "after": _site_label(info_a)},
                    "occupancy": {"a": round(entry["occ_a"], 5)},
                    "sof_written": {"a": f"{sof:.5f} (fixed by symmetry)"},
                    "part": {"a": entry["part_a"]},
                    "total_sof": total, "total_from": entry["total_from"],
                    **({"note": f"occupancy={occ} ignored: the components "
                                f"are symmetry images and share equally"}
                       if abs(occ - 0.5) > 1e-9 else {}),
                    **({"note_fold": entry["site_b_folded"]}
                       if entry.get("site_b_folded") else {})})
                messages.append(
                    f"{lb}: moved {moved:.2f} A off the {_site_label(info0)} "
                    f"to {fmt_site(entry['site_a'])} ({_site_label(info_a)}); "
                    f"its symmetry image {entry['d_ab']:.2f} A away is the "
                    f"other component ({entry['n_images']} images in total, "
                    f"generated by symmetry - NOT a separate atom). "
                    f"Occupancy {entry['occ_a']:.4g} fixed by symmetry "
                    f"(sof {sof:.5f}, conserving {entry['total_from']}), "
                    f"PART {entry['part_a']} (negative: no bond to the image "
                    f"and no SHELXL special-position constraint), no FVAR "
                    f"- the ratio cannot refine.")
                continue
            info_b = entry["info_b"]
            k = fvar_index
            sof_a = (10.0 * k + total)
            sof_b = -(10.0 * k + total)
            members.append({"label": lb, "part": entry["part_a"], "sign": 1,
                            "mult": total})
            members.append({"label": entry["lbl_b"], "part": entry["part_b"],
                            "sign": -1, "mult": total})
            # riding H follow their carrier's PART and free variable
            for h in entry.get("h_a") or []:
                members.append({"label": h, "part": entry["part_a"],
                                "sign": 1, "mult": total})
            for h in entry.get("h_b") or []:
                members.append({"label": h, "part": entry["part_b"],
                                "sign": -1, "mult": total})
            created.append({
                "a": lb, "b": entry["lbl_b"], "mode": "two_site",
                "b_is_existing_atom": entry["partner"] is not None,
                "d_ab": round(entry["d_ab"], 3),
                "site_a": fmt_site(entry["site_a"]),
                "site_b": fmt_site(entry["site_b"]),
                "site_symmetry": {"a": _site_label(info_a),
                                  "b": _site_label(info_b)},
                "occupancy": {"a": round(entry["occ_a"], 5),
                              "b": round(entry["occ_b"], 5)},
                "sof_written": {
                    "a": f"{sof_a:.5f} (= {total:.4g}*FVAR{k})",
                    "b": f"{sof_b:.5f} (= {total:.4g}*(1-FVAR{k}))"},
                "part": {"a": entry["part_a"], "b": entry["part_b"]},
                "total_sof": total, "total_from": entry["total_from"],
                "second_site_from": entry.get("second_site_from"),
                "carrier_u_eq_before": round(entry["u_eq"], 4),
                "carrier_adp_max_over_min": entry.get("adp_ratio"),
                **({"riding_h": {"a": entry.get("h_a"), "b": entry.get("h_b"),
                                 "note": "B's riding H copied from A's AFIX "
                                         "group, shifted by B-A; SHELXL "
                                         "re-idealises them on the next run"}}
                   if entry.get("h_b") else {}),
                **({"note": entry["site_b_folded"]}
                   if entry.get("site_b_folded") else {})})
            messages.append(
                f"{lb}: two-site split (B from {entry.get('second_site_from')}), "
                f"A={lb} at {fmt_site(entry['site_a'])} "
                f"({_site_label(info_a)}) PART {entry['part_a']} sof "
                f"{sof_a:.5f}; B={entry['lbl_b']} "
                f"{'(existing atom linked)' if entry['partner'] is not None else '(added)'} "
                f"at {fmt_site(entry['site_b'])} ({_site_label(info_b)}) "
                f"PART {entry['part_b']} sof {sof_b:.5f}; A-B "
                f"{entry['d_ab']:.2f} A; FVAR{k} = {occ} (A share), total "
                f"sof {total:.4g} conserved from {entry['total_from']}.")

        if members:
            groups.append({"fvar_index": fvar_index, "value": occ,
                           "members": members})
            ses.flags["disorder_groups"] = groups
        for entry in plan:
            if entry["mode"] == "image":
                parts_extra[entry["label"]] = entry["part_a"]
        if parts_extra:
            ses.flags["parts_extra"] = parts_extra
        if riding_added:
            ses.flags["h_riding_meta"] = {**h_meta, "per_carrier": per_carrier}
        n_two = sum(1 for e in plan if e["mode"] == "two_site")
        n_img = len(plan) - n_two
        nxt = []
        if n_two:
            nxt.append(
                f"run_shelxl(mode='adopt') refines the occupancy ratio "
                f"(FVAR{fvar_index}) and positions/ADPs together; consider "
                f"set_restraints SADI (equal A/B bond lengths to shared "
                f"neighbors) and SIMU/DELU for stability. EADP (an "
                f"equality CONSTRAINT tying the two ADPs) is not available "
                f"here; SIMU is a similarity RESTRAINT, not its equivalent "
                f"- it keeps the components close, it does not make them "
                f"equal.")
        if n_img:
            nxt.append(
                "the image component is generated by symmetry: no FVAR to "
                "refine and no EADP/SIMU pairing needed (it shares the "
                "atom's ADP); run_shelxl to confirm the site stays off the "
                "special position (no SPEC constraint under a negative "
                "PART).")
        nxt.append("Compare against the unsplit branch before accepting - "
                   "if R1/wR2/residuals do not improve, roll back.")

        # the acceptance loop's opening move: record what would have to be
        # put back, and what R1 was before, so run_shelxl can report a
        # delta and undo can reverse the call exactly.
        snap = ses.last_refinement() if hasattr(ses, "last_refinement") else None
        origin = {
            "fvar_index": fvar_index if members else None,
            "created": [e["lbl_b"] for e in plan
                        if e["mode"] == "two_site" and e["partner"] is None],
            "linked_existing": [scs[e["partner"]].label for e in plan
                                if e.get("partner") is not None],
            "image_labels": [e["label"] for e in plan
                             if e["mode"] == "image"],
            "restore": restore,
            "occupancy_a": occ,
            "r1_before": (round(float(snap.r1_strong), 4)
                          if snap is not None else None),
            "node_before": self._active_node(),
            "ts": time.time(),
        }
        origins = list(ses.flags.get("disorder_origins") or [])
        origins.append(origin)
        ses.flags["disorder_origins"] = origins

        summary: dict[str, Any] = {
            "split": created,
            "fvar_index": fvar_index if members else None,
            "occupancy_a": occ if members else None,
            "n_atoms": xs.scatterers().size(),
            "message": " ".join(messages),
            "next": " ".join(nxt),
        }
        if members:
            from .disorder_accept import (data_d_min, group_acceptance,
                                          restraint_suggestion)
            grp = groups[-1]
            summary["acceptance"] = group_acceptance(
                xs, grp, free_var=None, d_min_data=data_d_min(ses),
                r1_now=None, origin=origin, with_restraints=False,
                split_labels={str(m.get("label", "")).upper()
                              for g in groups
                              for m in (g.get("members") or [])},
                peaks=ses.flags.get("diff_map_peaks"))
            summary["evidence"] = _split_evidence(xs, origin, summary)
            summary["restraint_suggestion"] = restraint_suggestion(xs, grp)
            summary["undo"] = (
                f"model_disorder(undo='fvar{fvar_index}') removes this split "
                f"again - components merged back to one site at the "
                f"occupancy-weighted position, FVAR and PART dropped, "
                f"{len(origin['created'])} added atom(s) deleted")
        elif origin["image_labels"]:
            summary["undo"] = (
                f"model_disorder(undo='{origin['image_labels'][0]}') puts the "
                f"atom back on its special position and drops the negative "
                f"PART")
        return ToolResult(ok=True, summary=summary)

    def _active_node(self) -> str | None:
        try:
            return self.project.nodes.state().get("active_node")
        except Exception:  # noqa: BLE001 - bare-session tests carry no store
            return None

    # ------------------------------------------------------------------
    def _undo(self, ctx: ToolContext, ref: str) -> ToolResult:
        """Remove a split cleanly: merge, delete, drop FVAR/PART, renumber.

        Undo is only offered for splits THIS tool made, because only then
        is the pre-split state on record. A group parsed out of an
        imported .res is somebody else's model, and silently guessing what
        it looked like before would be a fabrication."""
        from cctbx.array_family import flex

        from .disorder_accept import _component_pairs
        ses = ctx.session
        xs = ses.model
        groups = [dict(g) for g in (ses.flags.get("disorder_groups") or [])]
        origins = [dict(o) for o in (ses.flags.get("disorder_origins") or [])]
        parts_extra = dict(ses.flags.get("parts_extra") or {})
        labels_now = {sc.label.upper() for sc in xs.scatterers()}

        # round-3 WP3: an edit_atoms set_part/clear_part is the most recent
        # change to an atom and is reversed first (LIFO per atom)
        from .parts import latest_part_edit
        part_edit = latest_part_edit(origins, ref)
        if part_edit is not None:
            return self._undo_part_edit(ctx, part_edit)

        target, image_label = _resolve_undo_ref(ref, groups, parts_extra)
        if target is None and image_label is None:
            have = ([f"fvar{g['fvar_index']}" for g in groups]
                    + sorted(parts_extra))
            return ToolResult.failure(
                f"undo={ref!r} matches no disorder group. This model has "
                f"{have or 'no disorder groups'} - pass the free variable "
                f"('fvar2' / '2') or any component label.")

        if image_label is not None:
            return self._undo_image(ctx, image_label, origins, parts_extra)

        grp = next(g for g in groups if g["fvar_index"] == target)
        origin = next((o for o in origins if o.get("fvar_index") == target),
                      None)
        if origin is None:
            return ToolResult.failure(
                f"FVAR{target} was not created by model_disorder in this "
                f"project (no pre-split state on record - it came from the "
                f"imported model or from a node created before this "
                f"version), so undo cannot say what the atoms looked like "
                f"before. Roll back with checkout to a node without the "
                f"split, or take the components apart explicitly with "
                f"edit_atoms.")

        if origin.get("kind") == "fragment_pose":
            return ToolResult.failure(
                f"FVAR{target} is the shared occupancy of a fragment placed by "
                f"accept_fragment_pose ({', '.join(origin.get('created') or [])}); "
                f"it was never a split, so there is nothing to merge back - "
                f"remove the fragment with edit_atoms(delete): its free "
                f"variable, PART and cards go with the atoms.")
        if origin.get("stale"):
            return ToolResult.failure(
                f"FVAR{target} split can no longer be undone: "
                f"{origin.get('stale_reason') or 'a component was deleted'} "
                f"- the pre-split state on record does not describe the "
                f"current model (an atom re-added under the same label is "
                f"not the atom that was split). Roll back with checkout to "
                f"the node before the split "
                f"({origin.get('node_before') or 'unknown'}) or take the "
                f"components apart with edit_atoms.")

        uc, sg = xs.unit_cell(), xs.space_group()
        members = grp.get("members") or []
        a_labels = [str(m["label"]) for m in members
                    if int(m.get("sign", 1)) > 0]
        b_labels = [str(m["label"]) for m in members
                    if int(m.get("sign", 1)) < 0]
        missing = [lb for lb in a_labels + b_labels
                   if lb.upper() not in labels_now]
        if missing:
            return ToolResult.failure(
                f"FVAR{target} lists {missing}, which are no longer in the "
                f"model - the group and the model are out of step (an "
                f"edit_atoms delete?). Fix the model first; undo will not "
                f"guess.")
        by_label = {sc.label.upper(): i for i, sc in enumerate(xs.scatterers())}
        mult_of = {str(m["label"]).upper(): float(m.get("mult", 1.0))
                   for m in members}
        created = {str(x).upper() for x in (origin.get("created") or [])}
        restore_of = {str(r["label"]).upper(): r
                      for r in (origin.get("restore") or [])}

        merged: list[dict[str, Any]] = []
        unlinked: list[dict[str, Any]] = []
        to_delete: set[int] = set()
        refresh: list[int] = []
        pairs = _component_pairs(xs, a_labels, b_labels)
        paired = {lb.upper() for p in pairs for lb in p}
        orphans = [lb for lb in a_labels + b_labels
                   if lb.upper() not in paired]
        for a, b in pairs:
            ia, ib = by_label[a.upper()], by_label[b.upper()]
            sc_a, sc_b = xs.scatterers()[ia], xs.scatterers()[ib]
            if b.upper() not in created:
                # B was an existing atom linked as part B, not one this
                # tool invented: the pair was never one atom, so undo puts
                # each back on its own occupancy and only drops the link
                for lb, i in ((a, ia), (b, ib)):
                    st = restore_of.get(lb.upper())
                    sc = xs.scatterers()[i]
                    old = float(sc.occupancy)
                    if st is not None:
                        sc.occupancy = float(st["occupancy"])
                    unlinked.append({
                        "atom": sc.label,
                        "occupancy": f"{old:.4g} -> {sc.occupancy:.4g}",
                        "site": "unchanged (kept where refinement left it)"})
                continue
            wa, wb = float(sc_a.weight()), float(sc_b.weight())
            if wa + wb <= 0:
                wa = wb = 0.5
            site_a = tuple(float(x) for x in sc_a.site)
            _d, site_b = _nearest_image(uc, sg, site_a,
                                        tuple(float(x) for x in sc_b.site))
            site_m = tuple((wa * site_a[k] + wb * site_b[k]) / (wa + wb)
                           for k in range(3))
            ua = _u_eq_of(uc, sc_a)
            ub = _u_eq_of(uc, sc_b)
            u_m = (wa * ua + wb * ub) / (wa + wb)
            info0 = _site_info(xs, site_a)
            info_m = _site_info(xs, site_m)
            total = mult_of.get(a.upper(), 1.0)
            occ_m = total / info_m["factor"]
            if occ_m > 1.0 + 1e-6:
                return ToolResult.failure(
                    f"undo would put {a} on the {_site_label(info_m)}, "
                    f"which cannot hold its sof {total:.4g} - the two "
                    f"components have refined onto different site "
                    f"symmetries; take them apart with edit_atoms instead")
            sc_a.site = info_m["site"]
            sc_a.occupancy = occ_m
            sc_a.u_iso = max(u_m, 0.005)
            sc_a.set_use_u_iso_only()
            if info_m["multiplicity"] != info0["multiplicity"]:
                refresh.append(ia)
            to_delete.add(ib)
            merged.append({
                "kept": sc_a.label, "deleted": sc_b.label,
                "weights": [round(wa, 4), round(wb, 4)],
                "site": [round(float(x), 5) for x in info_m["site"]],
                "moved_A": round(uc.distance(site_a, info_m["site"]), 3),
                "occupancy": round(occ_m, 5),
                "sof": round(total, 5),
                "u_iso": round(max(u_m, 0.005), 4),
                "site_symmetry": _site_label(info_m)})
        # a member the pairing could not match (a group that lost an atom
        # outside this tool) keeps its site but must not keep a split
        # occupancy - it would leave a half-atom behind with no group
        for lb in orphans:
            sc = xs.scatterers()[by_label[lb.upper()]]
            st = restore_of.get(lb.upper())
            old = float(sc.occupancy)
            sc.occupancy = (float(st["occupancy"]) if st is not None
                            else min(1.0, mult_of.get(lb.upper(), 1.0)
                                     / max(_site_info(
                                         xs, tuple(sc.site))["factor"], 1e-9)))
            unlinked.append({
                "atom": sc.label, "unpaired": True,
                "occupancy": f"{old:.4g} -> {sc.occupancy:.4g}",
                "site": "unchanged (no partner to merge with)"})
        if refresh:
            _refresh_site_symmetry(xs, refresh)
        deleted_labels = {xs.scatterers()[i].label.upper() for i in to_delete}
        # riding H ride with their carrier: an H left behind by a deleted
        # component is exactly the debris this call exists to prevent
        h_orphans: list[str] = []
        for g in ((ses.flags.get("h_riding_meta") or {}).get("per_carrier")
                  or []):
            if str(g.get("carrier", "")).upper() not in deleted_labels:
                continue
            for h in g.get("h", []):
                i = by_label.get(str(h).upper())
                if i is not None and i not in to_delete:
                    to_delete.add(i)
                    h_orphans.append(str(h))
        deleted_labels |= {h.upper() for h in h_orphans}
        if to_delete:
            keep = flex.bool([i not in to_delete
                              for i in range(xs.scatterers().size())])
            ses.model = xs.select(keep)
        ses.model.scattering_type_registry(table="it1992")

        kept = [g for g in groups if g["fvar_index"] != target]
        renum = _renumber_groups(kept)
        if kept:
            ses.flags["disorder_groups"] = kept
        else:
            ses.flags.pop("disorder_groups", None)
        origins = [o for o in origins if o.get("fvar_index") != target]
        for o in origins:
            if o.get("fvar_index") in renum:
                o["fvar_index"] = renum[o["fvar_index"]]
        if origins:
            ses.flags["disorder_origins"] = origins
        else:
            ses.flags.pop("disorder_origins", None)
        hygiene = _delete_hygiene(ses, deleted_labels)

        return ToolResult(ok=True, summary={
            "undone": f"fvar{target}",
            "merged": merged,
            **({"unlinked": unlinked} if unlinked else {}),
            "deleted_atoms": sorted(deleted_labels),
            **({"riding_h_deleted_with_their_carrier": sorted(h_orphans)}
               if h_orphans else {}),
            "n_atoms": ses.model.scatterers().size(),
            "fvar_renumbered": ({f"fvar{a}": f"fvar{b}"
                                 for a, b in renum.items()} or None),
            "disorder_groups_left": len(kept),
            **hygiene,
            "message": (
                f"FVAR{target} removed: "
                + ("; ".join(f"{m['deleted']} merged into {m['kept']} at the "
                             f"occupancy-weighted position "
                             f"({m['weights'][0]:.2f}:{m['weights'][1]:.2f}, "
                             f"{m['kept']} moved {m['moved_A']:.2f} A), sof "
                             f"{m['sof']:.4g} conserved" for m in merged)
                   or "no pair merged")
                + (f"; {len(unlinked)} pre-existing atom(s) unlinked and put "
                   f"back on their own occupancy" if unlinked else "")
                + ". The free variable and the PART cards are gone from "
                  "every future .res / SHELXL job"
                + (f"; remaining groups renumbered "
                   f"{', '.join(f'FVAR{a}->FVAR{b}' for a, b in renum.items())}"
                   if renum else "") + "."),
            "next": (
                "re-refine (refine / run_shelxl) and read the difference map "
                "again: density still sitting on the merged site means the "
                "second component was in the wrong place, not absent. "
                "Whatever the outcome, DISCLOSE the trial and this undo in "
                "the report - an abandoned split is a result, not a "
                "non-event."),
        })

    # ------------------------------------------------------------------
    def _undo_part_edit(self, ctx: ToolContext, origin: dict) -> ToolResult:
        """Reverse an edit_atoms set_part / clear_part exactly (round-3
        WP3): the recorded previous assignment goes back, the record is
        dropped, nothing else moves."""
        from .parts import restore_part_edit
        ses = ctx.session
        labels = [str(x) for x in (origin.get("labels") or [])]
        if origin.get("stale"):
            return ToolResult.failure(
                f"the PART edit of {', '.join(labels)} can no longer be "
                f"undone: {origin.get('stale_reason') or 'an atom was deleted'}"
                f". Set the PART explicitly with edit_atoms(set_part) or "
                f"checkout the node before the edit "
                f"({origin.get('node_before') or 'unknown'}).")
        restored = restore_part_edit(ses.flags, origin)
        shown = ", ".join(f"{lb}: PART {p if p is not None else 0}"
                          for lb, p in restored.items())
        return ToolResult(ok=True, summary={
            "undone": labels,
            "mode": "part_edit",
            "parts": restored,
            "n_atoms": ses.model.scatterers().size(),
            "message": f"PART assignment restored ({shown}); the model's "
                       f"atoms were not moved or deleted."})

    def _undo_image(self, ctx: ToolContext, label: str,
                    origins: list[dict], parts_extra: dict) -> ToolResult:
        """Undo a symmetry-image split: one atom goes back onto the
        special position it was moved off, and the negative PART goes."""
        ses = ctx.session
        xs = ses.model
        origin = next((o for o in origins
                       if label.upper() in {str(x).upper() for x in
                                            (o.get("image_labels") or [])}),
                      None)
        if origin is None:
            return ToolResult.failure(
                f"{label} carries PART {parts_extra.get(label.upper())} but "
                f"model_disorder did not create it in this project, so "
                f"there is no recorded pre-split site to move it back to. "
                f"Use edit_atoms(action='move') with the special-position "
                f"site, or checkout an earlier node.")
        if origin.get("stale"):
            return ToolResult.failure(
                f"the symmetry-image split of {label} can no longer be "
                f"undone: {origin.get('stale_reason') or 'an atom was deleted'}"
                f" - the recorded pre-split site does not describe the "
                f"current model. Roll back with checkout to the node before "
                f"the split ({origin.get('node_before') or 'unknown'}).")
        st = next((r for r in (origin.get("restore") or [])
                   if str(r["label"]).upper() == label.upper()), None)
        if st is None:
            return ToolResult.failure(
                f"no pre-split state recorded for {label}")
        i = next((k for k, sc in enumerate(xs.scatterers())
                  if sc.label.upper() == label.upper()), None)
        if i is None:
            return ToolResult.failure(f"{label} is no longer in the model")
        sc = xs.scatterers()[i]
        moved = float(xs.unit_cell().distance(tuple(sc.site),
                                              tuple(st["site"])))
        sc.site = tuple(st["site"])
        sc.occupancy = float(st["occupancy"])
        if st.get("aniso") and st.get("u_star"):
            sc.u_star = tuple(st["u_star"])
            sc.flags.set_use_u_aniso(True)
        else:
            sc.u_iso = float(st.get("u_iso") or 0.03)
            sc.set_use_u_iso_only()
        _refresh_site_symmetry(xs, [i])
        parts_extra.pop(label.upper(), None)
        parts_extra.pop(label, None)
        if parts_extra:
            ses.flags["parts_extra"] = parts_extra
        else:
            ses.flags.pop("parts_extra", None)
        rest = [o for o in origins if o is not origin]
        if rest:
            ses.flags["disorder_origins"] = rest
        else:
            ses.flags.pop("disorder_origins", None)
        info = _site_info(xs, tuple(sc.site))
        return ToolResult(ok=True, summary={
            "undone": label,
            "mode": "symmetry_image",
            "site": [round(float(x), 5) for x in sc.site],
            "moved_back_A": round(moved, 3),
            "occupancy": round(float(sc.occupancy), 5),
            "site_symmetry": _site_label(info),
            "n_atoms": xs.scatterers().size(),
            "message": (
                f"{label} put back on the {_site_label(info)} "
                f"({moved:.2f} A back) at occupancy {sc.occupancy:.4g}; the "
                f"negative PART is gone. The two components were symmetry "
                f"images, so the special position IS their occupancy-"
                f"weighted position - but any refinement of this atom since "
                f"the split is discarded with it."),
            "next": "re-refine and re-read the difference map.",
        })


# ==========================================================================
class SetTwin(_ProjectTool):
    name = "set_twin"
    description = (
        "Declare (or remove) a twin law: writes SHELX TWIN (3x3 law, row-"
        "major) + BASF (one starting fraction per additional component). "
        "For n components, supply n-1 fractions, e.g. n=3, basf=[0.2,0.15]. "
        "A scalar basf starts EACH additional component at that value. "
        "law='inversion' is the racemic "
        "twin -1 (acentric groups only, the Flack-indicated case); "
        "law='matrix' takes matrix=[9 numbers]; law='suggest' only LISTS "
        "metric-possible (pseudo)merohedral laws from the lattice-vs-Laue "
        "coset without applying. While a twin is active the in-process "
        "refine refuses - run_shelxl(mode='adopt') refines BASF natively. "
        "Declare a twin only on evidence (Flack/|E^2-1|/R-drop), disclose "
        "the trial either way.")
    params_schema = {
        "type": "object",
        "properties": {
            "law": {"type": "string",
                    "enum": ["inversion", "matrix", "suggest", "remove"]},
            "matrix": {"type": "array", "items": {"type": "number"},
                       "minItems": 9, "maxItems": 9},
            "n": {"type": "integer", "default": 2,
                  "description": "TWIN component count >=2; negative even n "
                                 "includes inversion partners (abs(n) total). "
                                 "law='inversion' requires n=2."},
            "basf": {
                "anyOf": [
                    {"type": "number", "minimum": 0.01, "maximum": 0.5},
                    {"type": "array", "minItems": 1,
                     "items": {"type": "number", "exclusiveMinimum": 0,
                               "exclusiveMaximum": 1}},
                ],
                "description": "Exactly abs(n)-1 starting fractions, sum <1; "
                               "the first component has fraction 1-sum(basf). "
                               "A scalar (0.01-0.5) repeats for each additional "
                               "component. Omitted: 0.3 for n=2, otherwise "
                               "equal 1/abs(n) fractions."},
        },
        "required": ["law"],
    }

    def run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        ses = ctx.session
        if ses is None or ses.model is None:
            return ToolResult.failure("no model loaded")
        xs = ses.model
        law = params["law"]

        if law == "remove":
            if not ses.flags.get("twin"):
                return ToolResult(ok=True, summary={
                    "no_state_change": True, "note": "no twin law active"})
            old = ses.flags.pop("twin")
            ses.flags.pop("diff_map_peaks", None)
            ses.flags.pop("diff_map_peaks_meta", None)
            return ToolResult(ok=True, summary={
                "removed": old,
                "note": "twin law removed; refine (smtbx) is available "
                        "again"})

        if law == "suggest":
            return ToolResult(ok=True, summary={
                "no_state_change": True,
                **_suggest_laws(xs)})

        try:
            n = params.get("n", 2)
            count = twin_component_count(n)
        except ValueError as exc:
            return ToolResult.failure(str(exc))

        if law == "inversion":
            if n != 2:
                return ToolResult.failure("law='inversion' requires n=2")
            if xs.space_group().is_centric():
                return ToolResult.failure(
                    "the space group is centrosymmetric - it already "
                    "contains the inversion, a racemic twin law is "
                    "meaningless here")
            matrix = [-1, 0, 0, 0, -1, 0, 0, 0, -1]
        elif law == "matrix":
            raw_matrix = params.get("matrix")
            if (not isinstance(raw_matrix, (list, tuple)) or len(raw_matrix) != 9
                    or any(isinstance(x, bool) or not isinstance(x, (int, float))
                           or not math.isfinite(x) for x in raw_matrix)):
                return ToolResult.failure(
                    "law='matrix' needs matrix=[9 finite numbers, row-major]")
            matrix = [float(x) for x in raw_matrix]
            det = _det3(matrix)
            if not math.isfinite(det) or abs(abs(det) - 1.0) > 0.05:
                return ToolResult.failure(
                    f"twin law determinant is {det:.3f}; a twin operation "
                    f"must have |det| = 1")
        else:
            return ToolResult.failure("law must be inversion, matrix, suggest or remove")

        raw_basf = params.get("basf", 0.3 if count == 2 else 1.0 / count)
        if isinstance(raw_basf, (list, tuple)):
            if len(raw_basf) != count - 1:
                return ToolResult.failure(
                    f"TWIN n={n} requires {count - 1} BASF starting fractions; "
                    f"got {len(raw_basf)}")
            basf = list(raw_basf)
        elif (not isinstance(raw_basf, bool) and isinstance(raw_basf, (int, float))
              and math.isfinite(raw_basf) and 0.01 <= raw_basf <= 0.5):
            basf = [float(raw_basf)] * (count - 1)
        else:
            return ToolResult.failure(
                "basf must be a finite scalar in [0.01, 0.5], or a list "
                "of starting fractions")
        if any(isinstance(b, bool) or not isinstance(b, (int, float))
               or not math.isfinite(b) or not 0 < b < 1 for b in basf):
            return ToolResult.failure("each basf starting fraction must be finite and in (0, 1)")
        # Check the actual five-decimal BASF values SHELX will receive too.
        if (math.fsum(basf) >= 1 or math.fsum(round(b, 5) for b in basf) >= 1
                or any(round(b, 5) == 0 for b in basf)):
            return ToolResult.failure(
                "basf fractions must remain positive with sum < 1 at SHELX "
                "precision; the first component has fraction 1-sum(basf)")
        ses.flags["twin"] = {"matrix": matrix,
                             "n": int(n), "basf": [float(b) for b in basf]}
        ses.flags.pop("diff_map_peaks", None)
        ses.flags.pop("diff_map_peaks_meta", None)
        return ToolResult(ok=True, summary={
            "twin": ses.flags["twin"],
            "note": ("TWIN/BASF will be written to every SHELX job and "
                     "node from now on. refine (smtbx) is disabled while "
                     "twinned - run_shelxl(mode='adopt') refines BASF. "
                     "Judge by: BASF converging away from 0, R1/wR2 drop "
                     "vs the untwinned branch, cleaner difference map."),
        })


class InvertStructure(_ProjectTool):
    name = "invert_structure"
    description = (
        "Invert the absolute structure (the Flack x ~ 1 remedy): applies "
        "the space group's proper change-of-hand operation to every site - "
        "this is NOT always a plain origin inversion (Fdd2/I4(1)-type "
        "groups invert about a shifted point, and enantiomorphic pairs "
        "like P3(1)/P3(2) swap the space group, which is reported and "
        "updated in the session). Refuses while a twin law is active "
        "(set_twin law='remove' first - inverting under TWIN changes the "
        "twin's meaning). After inverting: re-refine (run_shelxl) and "
        "confirm Flack x drops to ~0.")
    params_schema = {"type": "object", "properties": {}}

    def run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        ses = ctx.session
        if ses is None or ses.model is None:
            return ToolResult.failure("no model loaded")
        xs = ses.model
        sg_info = xs.space_group_info()
        if xs.space_group().is_centric():
            return ToolResult.failure(
                "the space group is centrosymmetric - both hands are "
                "already present, inversion is meaningless (and Flack is "
                "undefined)")
        if ses.flags.get("twin"):
            return ToolResult.failure(
                "a twin law is active - remove it first (set_twin "
                "law='remove'): inverting the model under TWIN silently "
                "changes what the twin matrix means")

        cb = sg_info.type().change_of_hand_op()
        new_xs = xs.change_basis(cb)
        new_info = new_xs.space_group_info()
        group_changed = str(new_info) != str(sg_info)
        ses.model = new_xs
        if group_changed:
            # enantiomorphic pair (P3(1) <-> P3(2), P6(1) <-> P6(5), ...):
            # the session's declared symmetry and data view must follow
            ses.symmetry = new_xs.crystal_symmetry()
            if ses.fo_sq is not None:
                ses.fo_sq = ses.fo_sq.customized_copy(
                    crystal_symmetry=new_xs.crystal_symmetry())
        summary = {
            "operation": str(cb.as_xyz()),
            "space_group": str(new_info),
            "group_changed": group_changed,
            "n_atoms": new_xs.scatterers().size(),
            "note": ("all sites inverted by the change-of-hand operation; "
                     "re-run run_shelxl and check Flack x returns ~0"
                     + (" - NOTE the space group changed "
                        f"({sg_info} -> {new_info}), session symmetry "
                        "updated" if group_changed else "")),
        }
        return ToolResult(ok=True, summary=summary)


def _det3(m: list[float]) -> float:
    return (m[0] * (m[4] * m[8] - m[5] * m[7])
            - m[1] * (m[3] * m[8] - m[5] * m[6])
            + m[2] * (m[3] * m[7] - m[4] * m[6]))


#: lattice-vs-Laue angular tolerance for a (pseudo)merohedral twin law
TWIN_SUGGEST_MAX_DELTA_DEG = 3.0
#: wider scan whose extra laws are DISCLOSED as near-misses, not offered
TWIN_SUGGEST_NEAR_MISS_DEG = 8.0


def _lattice_laws(xs, max_delta: float) -> tuple[list[dict[str, Any]], float]:
    """Coset representatives of the lattice point group (within max_delta
    degrees of the Niggli cell) modulo the Laue group, as rotation matrices
    in the WORKING basis, plus the actual metric deviation in degrees.

    2026-09-04 (reg1-ext2 rz): the previous version compared operators by
    str(rot_mx) - an object address - and transformed them with
    rt_mx * rt_mx, which raises TypeError; the exception was swallowed and
    every crystal got "no candidates". Identity is now the integer matrix,
    the transform is C^-1 R C on rot_mx (denominators kept), and a law that
    is non-integral in the working basis is still reported, flagged."""
    from cctbx import sgtbx
    from cctbx.sgtbx import lattice_symmetry
    cb = xs.crystal_symmetry().change_of_basis_op_to_niggli_cell()
    xs_n = xs.change_basis(cb)
    latt = lattice_symmetry.group(xs_n.unit_cell(), max_delta=max_delta)
    # the deviation belongs to the group as found (before the inversion
    # centre is added - find_max_delta wants the proper lattice group)
    try:
        delta = float(lattice_symmetry.find_max_delta(
            reduced_cell=xs_n.unit_cell(), space_group=latt))
    except Exception:  # noqa: BLE001 - a missing number is not a missing law
        delta = float("nan")
    latt.expand_inv(sgtbx.tr_vec((0, 0, 0)))
    laue_n = xs_n.space_group().build_derived_laue_group()
    key = lambda r: tuple(r.num())                       # noqa: E731
    laue_keys = {key(op.r()) for op in laue_n.all_ops()}
    c_fwd = cb.c().r()                                   # working -> niggli
    c_inv = cb.c_inv().r()                               # niggli -> working
    laws: list[dict[str, Any]] = []
    covered: set[tuple] = set(laue_keys)
    for op in latt.all_ops():
        r = op.r()
        if key(r) in covered:
            continue
        # the whole coset r * Laue is one twin law
        for h in laue_n.all_ops():
            covered.add(key(r.multiply(h.r())))
        r_work = c_inv.multiply(r).multiply(c_fwd)       # C^-1 R C
        mat = list(r_work.as_double())
        integral = all(abs(x - round(x)) < 1e-6 for x in mat)
        laws.append({"matrix": [int(round(x)) if integral else round(x, 4)
                                for x in mat],
                     "order": int(r.order()),
                     "integral": integral})
        if len(laws) >= 6:
            break
    return laws, delta


def _suggest_laws(xs, max_delta: float = TWIN_SUGGEST_MAX_DELTA_DEG
                  ) -> dict[str, Any]:
    """Metric-possible (pseudo)merohedral twin laws: coset representatives
    of the (centrosymmetric) lattice point group modulo the Laue group,
    expressed in the current basis, with the metric deviation they need."""
    laws, delta = _lattice_laws(xs, max_delta)
    out: dict[str, Any] = {"candidates": laws, "max_delta_deg": float(max_delta),
                           "lattice_delta_deg": (round(delta, 2)
                                                 if delta == delta else None)}
    if laws:
        note = (f"candidate laws the LATTICE metric allows beyond the Laue "
                f"symmetry (the lattice deviates {out['lattice_delta_deg']} deg "
                f"from the higher metric; tolerance {max_delta:g} deg). A "
                f"candidate is only a real twin if refining it "
                f"(set_twin(law='matrix', matrix=...) + run_shelxl adopt) drops "
                f"R with a stable BASF; try the integral ones first. A law that "
                f"is not integral in this basis is twinning by reticular "
                f"merohedry - still refinable in SHELXL, fewer overlapped "
                f"reflections.")
    else:
        near_laws, near_delta = _lattice_laws(xs, TWIN_SUGGEST_NEAR_MISS_DEG)
        out["near_miss"] = {"max_delta_deg": TWIN_SUGGEST_NEAR_MISS_DEG,
                            "lattice_delta_deg": (round(near_delta, 2)
                                                  if near_delta == near_delta
                                                  else None),
                            "candidates": near_laws}
        note = (f"no lattice-metric law within {max_delta:g} deg of a higher "
                f"symmetry, so twinning by (pseudo)merohedry is unlikely for "
                f"this cell"
                + (f"; the nearest higher metric is {out['near_miss']['lattice_delta_deg']} deg away "
                   f"(laws listed under near_miss - worth one refinement trial "
                   f"only if the data show twin symptoms)"
                   if near_laws else "")
                + ". Twinning by reticular merohedry and non-merohedral "
                  "twinning are NOT excluded by this test: they show as "
                  "un-indexed spots at the frames stage, or in merged data "
                  "as high R_int / a flat |E^2-1| / R values that stall "
                  "with a complete model.")
    if not xs.space_group().is_centric():
        note += (" The inversion twin (racemic, law='inversion') is always "
                 "a candidate in an acentric group - check Flack first.")
    out["note"] = note
    return out
