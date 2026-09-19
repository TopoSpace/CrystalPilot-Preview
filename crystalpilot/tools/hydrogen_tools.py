"""Geometric hydrogen atoms (riding model) and SHELX-style weight optimization.

AddHydrogens places idealized H on carrier atoms (default: C) from the model's
connectivity and attaches smtbx *riding constraints*:

  - site: smtbx.refinement.constraints.geometrical.hydrogens classes
    (secondary_planar_xh_site for aromatic CH, secondary_xh2_sites for CH2,
    staggered_terminal_tetrahedral_xh3_sites for CH3, tertiary_xh_site, ...);
  - displacement: u_iso_proportional_to_pivot_u_eq (1.2x, 1.5x for CH3/OH).

The constraint objects are stored in ctx.session.flags["h_constraints"];
RefineLS feeds them into constraints.reparametrisation, so every subsequent
refinement re-idealizes the H geometry (true olex2-style riding, not fixed
sites). A leading pseudo-constraint (_HRidingFixup) converts H back to
isotropic each cycle -- RefineLS's 'anisotropic' mode calls
convert_to_anisotropic() on all scatterers including H -- and validates that
the stored scatterer indices still match the model (clear error instead of
silent corruption if atoms were deleted/reordered after add_hydrogens).

Metal-bonded carriers (pa2, 2026-09-02): the decision is the atom's own
skeleton, never "bonded to a metal" and never the label text. The tool
asks chem.metal_bonded_audit (the same audit validate_structure reports)
and acts on its verdicts instead of re-deriving them:

  - eta-ring members (pi_ligands): the ring metal is a face-on contact,
    not a valence neighbour - a Cp/arene CH gets its H like any ring
    carbon (ferrocene Fe-C 2.05 A is INSIDE the covalent-radii sum, so
    the old distance rule skipped every Cp carbon);
  - skeleton-less / mislabelled metal-bonded C/N (suspect_elements: a
    mu3-O or carboxylate O wearing SHELXT's placeholder C/N) are skipped
    with the audit's reason and candidate identities - retype them with
    edit_atoms, do not hide them in exclude=; force_kind is the per-atom
    opt-in for a genuine M-CH3;
  - audit-recognised sigma M-C (plausible_metal_bonds: alkyl, aryl, NHC,
    carbonyl, cyanide) count the metal as a neighbour and get H by their
    own geometry (M-CH2-R two H, sigma-aryl / carbene none, carbonyl /
    cyanide none).

Every non-H atom the call looked at gets one row in summary["decisions"]
(label, element, neighbour count, geometry, decision, n_h, kind, reason),
so an agent sees WHY an atom was skipped and what to do about it. One bad
carrier (cross-PART, degenerate geometry, a generator that throws) is
skipped with its reason; the call fails only when nothing could be
processed.

OptimizeWeights iterates the SHELXL weighting-scheme update (the smtbx port of
the SHELXL a,b grid search that flattens the variance binned by Fc/Fc_max and
drives GooF to 1) alternating with least-squares refinement, then records the
chosen (a, b) in ctx.session.flags["weights"], which RefineLS uses as its
default weights from then on.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
from cctbx import xray
from cctbx.array_family import flex
from smtbx.refinement import least_squares
from smtbx.refinement.constraints import InvalidConstraint
from smtbx.refinement.constraints.adp import u_iso_proportional_to_pivot_u_eq
from smtbx.refinement.constraints.geometrical import hydrogens as gh
import smtbx.utils

from ..chem.knowledge import is_metal
from ..io.shelx_writer import SHELXL_BOND_TOLERANCE_A
from ..chem.metal_bonded_audit import (audit_metal_bonded_light_atoms,
                                       metal_bond_window)
from .base import Tool, ToolContext, ToolResult
from .budget import (BudgetStop, Cancelled, budget_for, default_timeout_s,
                     timeout_param)

TETRAHEDRAL = math.degrees(math.acos(-1.0 / 3.0))   # 109.47

#: rows of the per-atom decision table kept in the summary. The table is
#: the point of the tool, so the cap is generous; when it bites, the
#: summary says so (decisions_note) and the counts still cover every atom.
DECISION_TABLE_CAP = 500
#: skipped= entries kept in the summary (the decision table has them all)
_SKIPPED_CAP = 60
#: placement/verification passes before the remaining carriers are dropped
_PLACEMENT_PASSES = 4

_RCOV_CACHE: dict[str, float] = {}


def _rcov(el: str) -> float:
    r = _RCOV_CACHE.get(el)
    if r is None:
        try:
            from cctbx.eltbx import covalent_radii
            r = float(covalent_radii.table(el).radius())
        except Exception:  # noqa: BLE001 - unknown symbol: fall back to C
            r = 0.77
        _RCOV_CACHE[el] = r
    return r


def _bond_plausible(el_i: str, el_j: str, d: float) -> bool:
    """Element-pair-aware sanity window for a carrier's bond.

    The old fixed 1.20-1.80 A gate silently rejected every carbon bonded to
    a third-row element (P-C 1.83-1.90, S-C 1.81, Si-C 1.87 A) - round-10
    practice-770 lost all isopropyl H on phosphorus. The C-C limits of the
    old gate are reproduced by 0.78*sum / sum+0.30 of covalent radii.
    """
    s = _rcov(el_i) + _rcov(el_j)
    return max(1.05, 0.78 * s) <= d <= s + 0.30

# kind -> (constraint class, n_H, u multiplier)
_KINDS = {
    "aromatic_CH":  (gh.secondary_planar_xh_site, 1, 1.2),
    "CH2":          (gh.secondary_xh2_sites, 2, 1.2),
    "tertiary_CH":  (gh.tertiary_xh_site, 1, 1.2),
    "CH3":          (gh.staggered_terminal_tetrahedral_xh3_sites, 3, 1.5),
    "CH3_rotating": (gh.terminal_tetrahedral_xh3_sites, 3, 1.5),
    "vinyl_CH2":    (gh.terminal_planar_xh2_sites, 2, 1.2),
    "linear_CH":    (gh.terminal_linear_ch_site, 1, 1.2),
    "OH":           (gh.terminal_tetrahedral_xh_site, 1, 1.5),
    "NH_planar":    (gh.secondary_planar_xh_site, 1, 1.2),
    "NH2_planar":   (gh.terminal_planar_xh2_sites, 2, 1.2),
    "tertiary_NH":  (gh.tertiary_xh_site, 1, 1.2),
}

#: heavy neighbours each kind's geometry builder needs (see _h_directions);
#: force_kind is checked against this so a forced kind cannot silently
#: produce garbage directions from the wrong number of bond vectors
_KIND_N_HEAVY = {
    "aromatic_CH": 2, "NH_planar": 2, "CH2": 2,
    "tertiary_CH": 3, "tertiary_NH": 3,
    "linear_CH": 1, "vinyl_CH2": 1, "NH2_planar": 1,
    "CH3": 1, "CH3_rotating": 1, "OH": 1,
}


# --------------------------------------------------------------------------
# SHELXL's own AFIX connectivity check, run at placement time
# --------------------------------------------------------------------------
def _shelxl_neighbours(pivot_el: str, nbs: list[dict]
                       ) -> tuple[list[dict], list[dict]]:
    """(all, keepable) bonded non-H neighbours as SHELXL sees them.

    Its rule, not ours (io.shelx_writer, measured on shelxl.exe 2019/3):
    bonded = within the covalent-radii sum + 0.5 A; and when the count
    does not fit the AFIX code SHELXL drops the bonds to elements outside
    Z 6-10 and tries again. Deliberately NOT the audit-filtered `heavy`
    list the geometry is built from - the two disagree exactly where
    SHELXL aborts the job.
    """
    from ..io.shelx_writer import shelxl_bonded, shelxl_counts_as_neighbour
    all_nb, keep = [], []
    for nb in nbs:
        el = nb["element"]
        if el == "H" or not shelxl_bonded(pivot_el, el, nb["d"]):
            continue
        all_nb.append(nb)
        if shelxl_counts_as_neighbour(el):
            keep.append(nb)
    return all_nb, keep


def _afix_mismatch(kind: str, pivot_label: str, pivot_el: str,
                   nbs: list[dict], labels: list[str],
                   substituent_of: Any = None) -> dict[str, Any] | None:
    """Would SHELXL reject the AFIX group this kind emits? (None = no.)

    Accepted when ANY count between "all bonded neighbours" and "all
    minus the droppable elements" fits the code: SHELXL drops as many
    droppable bonds as it needs and no more (measured). Distances use
    SHELXL's own radii (io.shelx_writer.SHELXL_SFAC_RADII_A - its metal
    radii run up to 0.2 A shorter than cctbx's, which is exactly what
    decides whether a long M...X contact is a bond over there). So this
    fires when the count SHELXL will see cannot be the one the AFIX code
    needs: the model has more C/N/O/F neighbours on that carrier than the
    group allows, or fewer bonds in total than it needs (the usual cause
    being a model that changed after the H were placed).

    `substituent_of(neighbour)` returns a further bonded atom of that
    neighbour, or None - consulted only for the codes that build a plane
    from it. Returns the row for
    summary['afix_connectivity_mismatches'].
    """
    from ..io.shelx_writer import (AFIX_NEEDS_NEIGHBOUR_SUBSTITUENT,
                                   AFIX_NEIGHBOUR_RULE, AFIX_OF_KIND,
                                   afix_count_fits)
    afix = AFIX_OF_KIND.get(kind)
    rule = AFIX_NEIGHBOUR_RULE.get(afix)
    if rule is None:
        return None
    lo, hi = rule
    all_nb, keep = _shelxl_neighbours(pivot_el, nbs)

    def txt(items):
        return [f"{labels[nb['j']]}:{nb['d']:.2f}({nb['element']})"
                for nb in items]

    need = (f"exactly {lo}" if hi == lo else
            f"at least {lo}" if hi is None else f"{lo}-{hi}")
    droppable = [nb for nb in all_nb if nb not in keep]
    base = {"atom": pivot_label, "afix": afix, "kind": kind,
            "expected": need, "bonded": txt(all_nb),
            "n_bonded": len(all_nb),
            "n_after_dropping_heavy": len(keep),
            "droppable": txt(droppable)}
    if not afix_count_fits(afix, len(all_nb), len(keep)):
        return {**base, "problem": "count"}
    if (afix in AFIX_NEEDS_NEIGHBOUR_SUBSTITUENT and all_nb
            and substituent_of is not None
            and substituent_of(all_nb[0]) is None):
        return {**base, "problem": "substituent",
                "expected": f"{need} + one further atom on that neighbour"}
    return None


def _afix_mismatch_reason(m: dict[str, Any]) -> str:
    """The skip reason: what SHELXL would have said, and how to fix it."""
    if m["problem"] == "substituent":
        why = ("the neighbour it would build the group's plane from has no "
               "other bonded atom, so SHELXL cannot define that plane")
    else:
        why = (f"SHELXL sees {m['n_bonded']} ({m['bonded'] or 'none'})"
               + (f", down to {m['n_after_dropping_heavy']} if it drops "
                  f"every bond it is allowed to drop ({m['droppable']} - "
                  f"outside Z 6-10); no count in that range fits"
                  if m["droppable"] else " - that does not fit"))
    return (
        f"afix_connectivity_mismatch: AFIX {m['afix']} ({m['kind']}) needs "
        f"{m['expected']} bonded neighbour(s) of the pivot; {why}. SHELXL "
        f"builds that count itself (covalent radii + "
        f"{SHELXL_BOND_TOLERANCE_A} A) and would refuse the whole job "
        f"(\"** BAD AFIX {m['afix']} CONNECTIVITY OR PART NUMBERS ... ** "
        f"TERMINATING BECAUSE OF BAD HFIX OR AFIX INSTRUCTIONS **\"), so "
        f"no H was placed here. Fix the model at this site (a wrong "
        f"element, a missing or spurious neighbour), or force_kind this "
        f"carrier to a kind whose AFIX matches what SHELXL counts; "
        f"exclude= only hides it. Every carrier with this problem is in "
        f"this one call - see afix_connectivity_mismatches.")


# --------------------------------------------------------------------------
# constraint plumbing
# --------------------------------------------------------------------------
class _HRidingFixup:
    """Pseudo-constraint run first in each reparametrisation build.

    1) verifies the scatterer indices recorded by add_hydrogens still label the
       same atoms (model edits after add_hydrogens invalidate the constraints);
    2) forces H scatterers back to isotropic ADPs, undoing the blanket
       convert_to_anisotropic() of RefineLS's 'anisotropic' mode, because the
       riding u_iso constraint requires an isotropic H.
    """

    constrained_parameters = ()

    def __init__(self, checks: list[tuple[int, str]], h_indices: list[int]) -> None:
        self.checks = checks
        self.h_indices = h_indices

    def add_to(self, reparametrisation) -> None:
        scs = reparametrisation.structure.scatterers()
        for i, lbl in self.checks:
            if i >= scs.size() or scs[i].label != lbl:
                raise InvalidConstraint(
                    "stored hydrogen constraints are stale (model atoms were "
                    "deleted/reordered after add_hydrogens): expected %r at index "
                    "%d. Re-run add_hydrogens." % (lbl, i))
        uc = reparametrisation.structure.unit_cell()
        for i in self.h_indices:
            sc = scs[i]
            if sc.flags.use_u_aniso():
                sc.convert_to_isotropic(uc)


# --------------------------------------------------------------------------
# geometry helpers (cartesian)
# --------------------------------------------------------------------------
def _unit(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    if n < 1e-9:
        raise ValueError("zero vector")
    return v / n


def _any_perp(a: np.ndarray) -> np.ndarray:
    e = np.array([1.0, 0.0, 0.0])
    if abs(float(np.dot(a, e))) > 0.9:
        e = np.array([0.0, 1.0, 0.0])
    return _unit(np.cross(a, e))


def _perp_component(v: np.ndarray, axis: np.ndarray) -> np.ndarray:
    w = v - axis * float(np.dot(v, axis))
    n = float(np.linalg.norm(w))
    if n < 1e-6:
        return _any_perp(axis)
    return w / n


def _rotate(v: np.ndarray, axis: np.ndarray, angle_deg: float) -> np.ndarray:
    a = math.radians(angle_deg)
    return (v * math.cos(a) + np.cross(axis, v) * math.sin(a)
            + axis * float(np.dot(axis, v)) * (1.0 - math.cos(a)))


def _h_directions(kind: str, u_vecs: list[np.ndarray],
                  ref_perp: np.ndarray | None) -> list[np.ndarray]:
    """Idealized unit vectors pivot->H. u_vecs: unit vectors pivot->neighbours.
    ref_perp: unit vector perpendicular to the pivot->neighbour axis pointing
    towards a substituent of the neighbour (terminal kinds only)."""
    if kind in ("aromatic_CH", "NH_planar"):
        return [-_unit(u_vecs[0] + u_vecs[1])]
    if kind in ("tertiary_CH", "tertiary_NH"):
        return [-_unit(u_vecs[0] + u_vecs[1] + u_vecs[2])]
    if kind == "CH2":
        b = -_unit(u_vecs[0] + u_vecs[1])
        n = _unit(np.cross(u_vecs[0], u_vecs[1]))
        half = math.radians(107.6 / 2.0)
        return [_unit(b * math.cos(half) + n * math.sin(half)),
                _unit(b * math.cos(half) - n * math.sin(half))]
    if kind == "linear_CH":
        return [-u_vecs[0]]
    if kind in ("vinyl_CH2", "NH2_planar"):
        a = u_vecs[0]
        p = ref_perp if ref_perp is not None else _any_perp(a)
        c, s = math.cos(math.radians(120.0)), math.sin(math.radians(120.0))
        return [_unit(a * c + p * s), _unit(a * c - p * s)]
    if kind in ("CH3", "CH3_rotating", "OH"):
        a = u_vecs[0]
        p = -(ref_perp if ref_perp is not None else _any_perp(a))  # anti/staggered
        c = math.cos(math.radians(TETRAHEDRAL))          # -1/3
        s = math.sin(math.radians(TETRAHEDRAL))
        n_h = 1 if kind == "OH" else 3
        return [_unit(a * c + _rotate(p, a, k * 120.0) * s) for k in range(n_h)]
    raise ValueError(f"unknown H kind {kind}")


# --------------------------------------------------------------------------
# metal-bonded chemistry: the audit's verdicts, keyed by label
# --------------------------------------------------------------------------
_LINEAR_MC_WORDS = ("carbonyl", "cyanide", "isocyanide", "alkynyl", "linear")


class _MetalAudit:
    """What chem.metal_bonded_audit says about the model, keyed by label.

    The tool never re-derives the audit's rules (ring detection, donor
    windows, skeleton tests): it reads pi_ligands, suspect_elements and
    plausible_metal_bonds and acts on them. An audit that throws leaves
    `error` set and every map empty, and the caller falls back to the
    covalent-radii gate with a warning."""

    def __init__(self) -> None:
        self.pi_of: dict[str, dict[str, Any]] = {}     # label -> ring facts
        self.suspect_of: dict[str, dict[str, Any]] = {}
        self.plausible_of: dict[str, dict[str, str]] = {}  # label -> {metal: kind}
        self.pi_rings: list[str] = []
        self.suspects: list[dict[str, Any]] = []
        self.plausible: list[str] = []
        self.error: str | None = None
        self.note: str | None = None

    @classmethod
    def build(cls, xs, parts: dict[str, int] | None) -> "_MetalAudit":
        out = cls()
        try:
            mba = audit_metal_bonded_light_atoms(xs, parts=parts or None)
        except Exception as e:  # noqa: BLE001 - the audit must not take the tool down
            out.error = f"{type(e).__name__}: {e}"
            return out
        out.note = mba.get("note")
        for r in mba.get("pi_ligands") or []:
            m_lu = str(r["metal"]).upper()
            for lb in r["ring_labels"]:
                rec = out.pi_of.setdefault(str(lb).upper(), {
                    "metals": set(), "hapticity": int(r["hapticity"]),
                    "closed": bool(r["ring_closed"])})
                rec["metals"].add(m_lu)
            out.pi_rings.append(
                f"eta{r['hapticity']} [{', '.join(r['ring_labels'])}] on "
                f"{r['metal']} M-C {r['m_c_range'][0]}-{r['m_c_range'][1]} A"
                + ("" if r["ring_closed"] else " (open fragment)"))
        for s in mba.get("suspect_elements") or []:
            lu = str(s["label"]).upper()
            prev = out.suspect_of.get(lu)
            if prev is None or (prev.get("severity") != "high"
                                and s.get("severity") == "high"):
                out.suspect_of[lu] = s
        for lu, s in out.suspect_of.items():
            out.suspects.append({
                "label": s["label"], "element": s["element"],
                "kind": s["kind"], "severity": s["severity"],
                "metal": s["metal"], "d": s["d"],
                "n_skeleton_neighbours": s.get("n_skeleton_neighbours"),
                "candidates": list(s.get("candidates") or [])})
        for p in mba.get("plausible_metal_bonds") or []:
            out.plausible_of.setdefault(str(p["label"]).upper(), {})[
                str(p["metal"]).upper()] = str(p["kind"])
            out.plausible.append(f"{p['label']}: {p['kind']} "
                                 f"({p['metal']} {p['d']:.2f} A)")
        return out

    def report(self) -> dict[str, Any] | None:
        """Compact block for the summary; None when there is nothing to
        say (no metals, or no metal-bonded light atom of interest)."""
        if self.error:
            return {"error": self.error,
                    "note": "audit unavailable - metal-bonded carriers were "
                            "gated by the covalent-radii rule only"}
        if not (self.pi_rings or self.suspects or self.plausible):
            return None
        out: dict[str, Any] = {
            "n_pi_ligands": len(self.pi_rings),
            "n_suspect_elements": len(self.suspects),
            "n_plausible_metal_bonds": len(self.plausible),
        }
        if self.pi_rings:
            out["pi_ligands"] = self.pi_rings[:20]
        if self.suspects:
            out["suspect_elements"] = self.suspects[:40]
        if self.plausible:
            out["plausible_metal_bonds"] = self.plausible[:40]
        if self.note:
            out["note"] = self.note
        return out


def _suspect_reason(s: dict[str, Any]) -> str:
    """Skip reason for an audit suspect: what the geometry says, what the
    atom could be, and the fix (retype, not exclude)."""
    cands = "; ".join(str(c) for c in (s.get("candidates") or [])) or "?"
    return (f"metal-bonded {s['element']} flagged by the metal-bonded audit "
            f"[{s['kind']}, {s['severity']}]: {s['reason']}. Candidates: "
            f"{cands}. See validate_structure metal_bonded_light_atom - "
            "reassign with edit_atoms and rerun add_hydrogens; do NOT "
            "exclude= it (force_kind is the opt-in for a genuine M-C)")


def _within(window: tuple[float, float], d: float) -> bool:
    return window[0] <= d <= window[1]


def _nb_text(labels: list[str], heavy: list[dict],
             pi_metals: list[dict]) -> list[str]:
    """Compact neighbour list for a decision row: 'C2:1.39', a metal
    counted as a neighbour 'ZR1:2.28(M)', a face-on / long metal contact
    'FE1:2.05(pi)'."""
    out = [f"{labels[nb['j']]}:{nb['d']:.2f}"
           + ("(M)" if is_metal(nb["element"]) else "") for nb in heavy]
    out += [f"{labels[nb['j']]}:{nb['d']:.2f}(pi)" for nb in pi_metals]
    return out


# --------------------------------------------------------------------------
def _partition_existing_h(xs, elements: list[str], force_kind: dict,
                          riding_meta: dict) -> tuple[list[dict], list[str]]:
    """(explicit H to keep, H labels to strip) for an add_hydrogens run.

    Stripped: H bonded to a carrier whose element is requested, H on a
    force_kind carrier, H this tool generated before (riding meta), and H
    with no bonded carrier at all. Kept: explicit H on any other carrier
    (water/hydroxyl H placed from the difference map while protonating
    the carbons, pa2 hex-l0-r1)."""
    tool_made: set[str] = set()
    pc = riding_meta.get("per_carrier") if isinstance(riding_meta, dict) \
        else None
    entries = (pc.values() if isinstance(pc, dict) else pc) or []
    for entry in entries:
        if isinstance(entry, dict):
            for h in entry.get("h") or []:
                tool_made.add(str(h).upper())
    scs = xs.scatterers()
    elems = [sc.scattering_type.strip().capitalize() for sc in scs]
    labels = [sc.label for sc in scs]
    want = {str(e).capitalize() for e in elements}
    forced = {str(k).upper() for k in (force_kind or {})}
    carrier_of: dict[int, int | None] = {}
    try:
        ct = smtbx.utils.connectivity_table(xs)
        pst = ct.pair_asu_table.extract_pair_sym_table(
            skip_j_seq_less_than_i_seq=False,
            all_interactions_from_inside_asu=True)
        for i, el in enumerate(elems):
            if el != "H":
                continue
            carrier_of[i] = next((j for j in pst[i].keys()
                                  if elems[j] != "H"), None)
    except Exception:  # noqa: BLE001 - no table: fall back to strip-all
        carrier_of = {i: None for i, el in enumerate(elems) if el == "H"}
    keep: list[dict] = []
    strip: list[str] = []
    for i, j in carrier_of.items():
        lab = labels[i]
        if (j is None or lab.upper() in tool_made or elems[j] in want
                or labels[j].upper() in forced):
            strip.append(lab)
        else:
            keep.append({"h": lab, "carrier": labels[j],
                         "carrier_element": elems[j]})
    return keep, strip


class AddHydrogens(Tool):
    name = "add_hydrogens"
    description = (
        "Add geometrically placed hydrogen atoms with a riding model (olex2/SHELX "
        "HFIX style). Carriers are classified from connectivity: aromatic/sp2 CH, "
        "sp3 CH2/CH3, tertiary CH; optionally O-H and N-H. H sites and Uiso "
        "(1.2/1.5 x U_eq of the carrier) ride on the carrier via smtbx constraints "
        "that all subsequent refine calls apply automatically. Every non-H atom "
        "considered gets a row in summary.decisions (element, neighbours, "
        "geometry, decision, n_h, kind, reason) - read it. Metal-bonded carriers "
        "are judged by their own skeleton through the metal-bonded audit "
        "(validate_structure's metal_bonded_light_atom): eta-ring CH (Cp/arene) "
        "get H like any ring carbon, audit-recognised sigma M-C get H by their "
        "geometry (M-CH2-R yes, carbonyl/cyanide/aryl-ipso no), and a "
        "skeleton-less metal-bonded 'C'/'N' (a mu-O/OH, carboxylate O or halide "
        "wearing SHELXT's placeholder label) is SKIPPED with the audit's "
        "candidates - retype it with edit_atoms and rerun; exclude= is not a "
        "fix. Saturated carbons and ambiguous sites are skipped with reasons. "
        "Disorder-aware (SHELX PART semantics): atoms in different non-zero "
        "parts do not see each other, so overlapping PART 1/PART 2 alternatives "
        "each get their own H with the carrier's occupancy, joined to the "
        "carrier's disorder group (same FVAR linkage). "
        "Re-running replaces previously added hydrogens. When the automatic "
        "classification reads a carrier differently than you do, say so per "
        "atom - force_kind={'C11':'CH2'} / exclude=['C14'] - instead of "
        "hunting for global thresholds that happen to flip that one atom "
        "(the thresholds move every OTHER carrier too, and the misreading "
        "comes back on the next re-run).")
    params_schema = {
        "type": "object",
        "properties": {
            "elements": {"type": "array", "items": {"type": "string"},
                         "default": ["C"],
                         "description": "carrier elements to protonate; add 'O' "
                                        "and/or 'N' for hydroxyl/amine H (these "
                                        "are chemically ambiguous - check the "
                                        "warnings)"},
            "bond_lengths": {"type": "object", "default": {},
                             "description": "optional X-H bond length overrides "
                                            "(Angstrom) by kind: aromatic_CH, CH2, "
                                            "CH3, tertiary_CH, OH, ... Defaults are "
                                            "the SHELXL room-temperature values "
                                            "built into smtbx (e.g. 0.93 aromatic, "
                                            "0.97 CH2, 0.96 CH3)"},
            "sp2_angle_min": {"type": "number", "default": 115.0,
                              "description": "2-coordinate C with X-C-X angle above "
                                             "this is sp2 (1 H)"},
            "sp_linear_min": {"type": "number", "default": 160.0,
                              "description": "2-coordinate C with X-C-X angle above "
                                             "this is a linear sp carbon "
                                             "(nitrile/alkyne interior) - no H"},
            "sp2_avg_bond_max": {"type": "number", "default": 1.42,
                                 "description": "2-coordinate C with mean bond "
                                                "length below this is sp2 even at "
                                                "small ring angles (imidazole etc.)"},
            "planar_sum_min": {"type": "number", "default": 348.0,
                               "description": "3-coordinate C whose angles sum "
                                              "above this is a planar sp2 junction "
                                              "-> no H"},
            "methyl_min_bond": {"type": "number", "default": 1.45,
                                "description": "1-coordinate C with a bond at least "
                                               "this long is treated as a methyl"},
            "include_metal_bonded": {"type": "boolean", "default": False,
                                     "description": "also protonate carriers "
                                                    "sigma-bonded to a metal that the "
                                                    "metal-bonded audit could NOT "
                                                    "classify (the metal counts as a "
                                                    "geometric neighbour), and "
                                                    "metal-coordinated N/O. Not needed "
                                                    "for eta-ring CH (Cp/arene: "
                                                    "automatic) or audit-recognised "
                                                    "sigma M-C (automatic, by "
                                                    "geometry). Never protonates an "
                                                    "audit suspect (skeleton-less "
                                                    "metal-bonded C/N): retype it, or "
                                                    "force_kind it if it is a real "
                                                    "M-CH3"},
            "force_kind": {"type": "object", "default": {},
                           "description": "per-atom override of the automatic "
                                          "classification, e.g. {\"C11\": \"CH2\"}. "
                                          "Kinds: aromatic_CH, CH2, CH3, "
                                          "CH3_rotating, tertiary_CH, vinyl_CH2, "
                                          "linear_CH, OH, NH_planar, NH2_planar, "
                                          "tertiary_NH. Use when YOUR chemistry "
                                          "reading beats the geometry heuristics "
                                          "(a distorted or partly-modelled "
                                          "environment misleads them); the H "
                                          "directions are still built from the "
                                          "real bond vectors, so the forced kind "
                                          "must match the carrier's heavy-neighbour "
                                          "count. Also protonates carriers whose "
                                          "element is not in elements=, and is "
                                          "the per-atom opt-in for a metal-bonded "
                                          "carrier the audit flagged (a genuine "
                                          "M-CH3: {\"C7\": \"CH3\"} - the metal "
                                          "counts as the neighbour). Survives "
                                          "re-runs - global thresholds do not."},
            "exclude": {"type": "array", "items": {"type": "string"},
                        "default": [],
                        "description": "atom labels to leave unprotonated (e.g. a "
                                       "carbon you judge to be substituted in a "
                                       "part of the model that is still "
                                       "incomplete). Disclose in the report. NOT "
                                       "for metal-bonded atoms the audit flags as "
                                       "mislabelled - those need edit_atoms "
                                       "reassign, and the tool already skips them "
                                       "with the reason."},
        },
    }

    def run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        ses = ctx.session
        if ses.model is None:
            return ToolResult.failure("no model - build one first")
        elements = [str(e).capitalize() for e in params.get("elements", ["C"])]
        kept_explicit: list[dict] = []
        if not elements:
            return ToolResult.failure(
                "elements=[] protonates nothing - pass e.g. ['C'] or "
                "['C','N','O']")
        blank = [sc.label for sc in ses.model.scatterers()
                 if not sc.scattering_type.strip()]
        if blank:
            return ToolResult.failure(
                f"model has atoms with an EMPTY scattering type "
                f"({blank[:6]}) - a prior tool left corrupt state; fix with "
                "edit_atoms(element=...) or checkout a clean node first")
        bond_lengths = params.get("bond_lengths") or {}
        sp2_angle_min = float(params.get("sp2_angle_min", 115.0))
        sp2_avg_bond_max = float(params.get("sp2_avg_bond_max", 1.42))
        planar_sum_min = float(params.get("planar_sum_min", 348.0))
        methyl_min_bond = float(params.get("methyl_min_bond", 1.45))
        include_metal = bool(params.get("include_metal_bonded", False))
        sp_linear_min = float(params.get("sp_linear_min", 160.0))
        force_kind = {str(k).upper(): str(v) for k, v
                      in (params.get("force_kind") or {}).items()}
        bad_kinds = sorted({v for v in force_kind.values() if v not in _KINDS})
        if bad_kinds:
            return ToolResult.failure(
                f"unknown H kind(s) {bad_kinds} in force_kind; valid kinds: "
                f"{sorted(_KINDS)}")
        exclude = {str(x).upper() for x in (params.get("exclude") or [])}
        # replay-internal channel (leading underscore: never agent-facing,
        # see tools.base.invoke): labels the loaded model's H carried, which
        # the fresh H must not take. The riding replay (run_shelxl adopt,
        # checkout, import) strips those H and re-derives them per carrier,
        # then matches old and new H BY LABEL; without the reservation the
        # sequential fallback names below (H1, H2 ...) landed on carriers
        # other than the ones that owned them in the loaded model, and the
        # replay's rescue deleted / doubled the wrong atoms (pa2 cage-l0-r2
        # n0102 / n0107: 28 -> 20 H, eleven H labels written twice)
        reserved = {str(x).strip().upper()
                    for x in (params.get("_reserve_labels") or [])}
        # a typo in force_kind/exclude that silently does nothing is exactly
        # the friction these params exist to remove (T7 discipline). Checked
        # BEFORE the strip below: this refusal used to come after every H
        # had already been removed, so a stale label (hex-l2-r2: force_kind
        # still naming O007 after rename_atoms made it O5) left the model
        # with no H at all while reporting a plain parameter error.
        known_labels = {sc.label.upper() for sc in ses.model.scatterers()
                        if sc.scattering_type.strip().capitalize() != "H"}
        unknown = sorted((set(force_kind) | exclude) - known_labels)
        if unknown:
            return ToolResult.failure(
                f"unknown atom label(s) {unknown} in force_kind/exclude - "
                "check inspect_model for the current labels")

        # ---- start clean: strip the H this call REPLACES --------------------
        # Only H riding on a carrier of a requested element (or made by an
        # earlier add_hydrogens, or on a force_kind carrier) are replaced;
        # explicit H on other carriers stay. pa2 hex-l0-r1: three water H
        # placed from the difference map were wiped by every re-run on the
        # carbons - 18 nodes of churn, all of it discarded.
        xs = ses.model
        kept_explicit, strip_labels = _partition_existing_h(
            xs, elements, force_kind, ses.flags.get("h_riding_meta") or {})
        strip_set = {s.upper() for s in strip_labels}
        h_sel = flex.bool([sc.scattering_type.strip().capitalize() == "H"
                           and sc.label.upper() in strip_set
                           for sc in xs.scatterers()])
        n_h_removed = h_sel.count(True)
        if n_h_removed:
            stripped_h = {sc.label.upper() for sc, ish
                          in zip(xs.scatterers(), h_sel) if ish}
            for g in ses.flags.get("disorder_groups") or []:
                g["members"] = [m for m in g.get("members", ())
                                if str(m.get("label", "")).upper()
                                not in stripped_h]
            if ses.flags.get("parts_extra"):
                ses.flags["parts_extra"] = {
                    lbl: p for lbl, p in ses.flags["parts_extra"].items()
                    if str(lbl).upper() not in stripped_h}
            xs = xs.select(~h_sel)
            ses.model = xs
        ses.flags.pop("h_constraints", None)
        ses.flags.pop("h_riding_meta", None)

        uc = xs.unit_cell()
        scatterers = xs.scatterers()
        n0 = scatterers.size()
        # snapshot everything we need as plain Python objects NOW: flex proxies
        # into the scatterer array are invalidated once add_scatterer reallocates
        cart = [np.array(uc.orthogonalize(sc.site)) for sc in scatterers]
        elems = [sc.scattering_type.strip().capitalize() for sc in scatterers]
        labels = [sc.label for sc in scatterers]
        occs = [float(sc.occupancy) for sc in scatterers]
        u_eqs = [float(sc.u_iso_or_equiv(uc)) for sc in scatterers]
        asu_sites = [tuple(sc.site) for sc in scatterers]

        # SHELX PART semantics for disordered models: the connectivity table
        # is purely geometric, so overlapping PART 1/PART 2 alternatives look
        # bonded to each other and every disordered carrier appears saturated
        # (no H placed). Atoms in different non-zero parts must never see each
        # other; part 0 bonds to everything.
        from ..refine.nodes import part_kwargs_from_parts
        dgroups = ses.flags.get("disorder_groups") or []
        part_of: dict[str, int] = {}
        for g in dgroups:
            for m in g.get("members", ()):
                part_of[str(m.get("label", "")).upper()] = int(m.get("part") or 0)
        for _lbl, _p in (ses.flags.get("parts_extra") or {}).items():
            part_of.setdefault(str(_lbl).upper(), int(_p or 0))
        parts = [part_of.get(lb.upper(), 0) for lb in labels]

        def _part_compat(p: int, q: int) -> bool:
            # PART -n bonds like part n (sym_excl handled at table level)
            return not p or not q or abs(p) == abs(q)

        ct = smtbx.utils.connectivity_table(
            xs, **part_kwargs_from_parts(parts))
        pst = ct.pair_asu_table.extract_pair_sym_table(
            skip_j_seq_less_than_i_seq=False,
            all_interactions_from_inside_asu=True)

        def neighbours_of(i: int) -> list[dict]:
            out = []
            for j, ops in pst[i].items():
                if not _part_compat(parts[i], parts[j]):
                    continue
                for op in ops:
                    site_j = op * asu_sites[j]
                    p = np.array(uc.orthogonalize(site_j))
                    d = float(np.linalg.norm(p - cart[i]))
                    if d < 0.1:
                        continue
                    out.append({"j": j, "op": op, "cart": p,
                                "element": elems[j], "d": d})
            return out

        def substituent_perp(nb: dict, pivot_i: int) -> np.ndarray | None:
            """Unit vector perpendicular to the pivot->neighbour axis, towards a
            (non-H) substituent of the neighbour; None if the neighbour has no
            other substituent."""
            axis = _unit(nb["cart"] - cart[pivot_i])
            for k, ops_k in pst[nb["j"]].items():
                if elems[k] == "H":
                    continue
                if not (_part_compat(parts[k], parts[nb["j"]])
                        and _part_compat(parts[k], parts[pivot_i])):
                    continue
                for op_k in ops_k:
                    site_k = nb["op"] * (op_k * asu_sites[k])
                    p = np.array(uc.orthogonalize(site_k))
                    if (np.linalg.norm(p - cart[pivot_i]) < 0.5
                            or np.linalg.norm(p - nb["cart"]) < 0.5):
                        continue
                    return _perp_component(p - nb["cart"], axis)
            return None

        def counted_substituent(nb: dict, pivot_i: int) -> str | None:
            """Label of a further bonded atom on `nb` (SHELXL's own bond
            rule): what defines the plane of an AFIX 93 group. Any
            element will do - a Zr in that role was measured to be
            enough - but a bare neighbour is not."""
            from ..io.shelx_writer import shelxl_bonded
            j = nb["j"]
            for k, ops_k in pst[j].items():
                if elems[k] == "H":
                    continue
                if not _part_compat(parts[k], parts[j]):
                    continue
                for op_k in ops_k:
                    site_k = nb["op"] * (op_k * asu_sites[k])
                    p = np.array(uc.orthogonalize(site_k))
                    d = float(np.linalg.norm(p - nb["cart"]))
                    # the pivot itself is not a substituent of its own
                    # neighbour (it can reappear as a symmetry image)
                    if d < 0.1 or np.linalg.norm(p - cart[pivot_i]) < 0.5:
                        continue
                    if not shelxl_bonded(elems[j], elems[k], d):
                        continue
                    return labels[k]
            return None

        site_sym = xs.site_symmetry_table()
        warnings: list[str] = []
        #: carriers whose AFIX group SHELXL would refuse - ALL of them,
        #: in this one call (see _afix_mismatch)
        afix_mismatches: list[dict] = []
        #: metal-coordinated N/O that were considered and not protonated:
        #: one informational line at the end instead of a per-atom warning
        #: that contradicts the skip
        metal_donor_skips: list[str] = []
        skipped: list[dict] = []
        plan: list[dict] = []
        #: the per-atom decision table, by scatterer index (model order)
        rows_by_i: dict[int, dict] = {}
        errors: list[str] = []

        # ---- metal-bonded chemistry: the audit decides what a metal-bonded
        # light atom IS (eta-ring member / mislabelled donor / real M-C);
        # this tool only acts on the verdicts. Same audit, same PART
        # semantics as validate_structure, so the agent reads one story.
        audit = _MetalAudit.build(xs, part_of)
        if audit.error:
            warnings.append(
                f"metal-bonded light-atom audit did not run ({audit.error}) "
                "- metal-bonded carriers fall back to the covalent-radii "
                "gate (include_metal_bonded); eta-ring CH and mislabelled "
                "donors are NOT told apart in this call")

        kept_by_carrier: dict[str, list[str]] = {}
        for k in kept_explicit:
            kept_by_carrier.setdefault(str(k["carrier"]).upper(), []).append(
                str(k["h"]))

        def _row(i: int, decision: str, *, n: int | None = None,
                 geometry: str | None = None, kind: str | None = None,
                 n_h: int = 0, reason: str = "",
                 nb: list[str] | None = None) -> dict:
            row = {"label": labels[i], "element": elems[i],
                   "n_heavy_neighbours": n, "geometry": geometry,
                   "decision": decision, "n_h": n_h, "kind": kind,
                   "reason": reason}
            if nb:
                row["neighbours"] = nb
            rows_by_i[i] = row
            return row

        def _skip(i: int, reason: str, *, decision: str = "skipped",
                  **kw: Any) -> None:
            skipped.append({"atom": labels[i], "reason": reason})
            _row(i, decision, reason=reason, **kw)

        def _angle_sum(u: list[np.ndarray]) -> float:
            s = 0.0
            for a in range(3):
                for b in range(a + 1, 3):
                    s += math.degrees(math.acos(np.clip(
                        float(np.dot(u[a], u[b])), -1, 1)))
            return s

        def _classify(i: int, forced: str | None) -> dict | None:
            """Decide one carrier: returns the plan entry, or None after
            recording the skip (with its reason) in the decision table."""
            label, el = labels[i], elems[i]
            lu = label.upper()
            # warnings about THIS carrier are held until it actually gets
            # its H: a warning that says "O003 protonated
            # (include_metal_bonded)" while `skipped` lists O003 is not a
            # warning, it is a contradiction the agent has to resolve
            # (ka1 hex readout section 7, defect 2)
            pending: list[str] = []
            nbs = neighbours_of(i)
            pi_rec = audit.pi_of.get(lu)
            ring_metals = pi_rec["metals"] if pi_rec else set()
            sigma_kinds = audit.plausible_of.get(lu) or {}
            pi_metals: list[dict] = []
            heavy: list[dict] = []
            sigma_metals: list[dict] = []
            unblessed: list[dict] = []
            for nb in nbs:
                if nb["element"] == "H":
                    continue
                if not is_metal(nb["element"]):
                    heavy.append(nb)
                    continue
                m_lu = labels[nb["j"]].upper()
                in_window = _within(metal_bond_window(nb["element"], el),
                                    nb["d"])
                if m_lu in ring_metals:
                    # face-on eta contact (Cp/arene/allyl): never a valence
                    # neighbour, whatever the M-C distance
                    pi_metals.append(nb)
                elif m_lu in sigma_kinds and in_window:
                    # the audit recognised a real M-X bond (this image of
                    # the metal sits inside the audit's bonded window): a
                    # neighbour even beyond the covalent-radii sum
                    heavy.append(nb)
                    sigma_metals.append(nb)
                elif el != "C":
                    # N/O (and any other donor): the metal's own donor
                    # window from chem.knowledge, through the audit, says
                    # whether this is a coordination bond - a Cu-O 2.00 A
                    # dative bond is BEYOND the Cu+O covalent-radii sum
                    if in_window:
                        heavy.append(nb)
                        sigma_metals.append(nb)
                        unblessed.append(nb)
                    else:
                        pi_metals.append(nb)
                elif nb["d"] > _rcov(el) + _rcov(nb["element"]):
                    # a carbon beyond the covalent-radii sum with no audit
                    # verdict: a pi/electrostatic contact, not a valence
                    # bond (La...C 3.2 A arene contacts blocked every ring
                    # CH in practice-770; every carbon the audit's window
                    # does reach has a verdict - suspect, plausible, ring
                    # - or is a skeleton contact the audit does not count)
                    pi_metals.append(nb)
                else:
                    # sigma distance, no verdict (a metal the audit does
                    # not classify, or an audit that did not run): the
                    # include_metal_bonded gate of old
                    heavy.append(nb)
                    sigma_metals.append(nb)
                    unblessed.append(nb)
            n = len(heavy)
            nb_txt = _nb_text(labels, heavy, pi_metals)
            m_txt = ", ".join(f"{labels[nb['j']]} {nb['d']:.2f} A"
                              for nb in sigma_metals)

            # 1) the audit's mislabel verdict beats everything but force_kind
            suspect = audit.suspect_of.get(lu)
            if suspect is not None:
                if forced is None:
                    _skip(i, _suspect_reason(suspect), n=n, nb=nb_txt,
                          geometry=("metal-bonded, %s skeleton neighbour(s)"
                                    % suspect.get("n_skeleton_neighbours", "?")))
                    return None
                pending.append(
                    f"{label}: force_kind={forced} overrides the metal-bonded "
                    f"audit's {suspect['severity']} {suspect['kind']} flag - "
                    "disclose in the report")
            if pi_metals and not any(labels[nb["j"]].upper() in ring_metals
                                     for nb in pi_metals):
                pending.append(
                    f"{label}: long metal contact ({pi_metals[0]['element']} "
                    f"{pi_metals[0]['d']:.2f} A) treated as pi/non-valence - "
                    "H placed from the organic neighbours only")
            # 2) a metal counted as a neighbour: who said it is a bond?
            if sigma_metals:
                if forced is not None:
                    pending.append(
                        f"{label}: force_kind={forced} on a metal-bonded "
                        f"carrier ({m_txt}) - the metal counts as a neighbour; "
                        "check the difference map and disclose")
                elif el != "C":
                    if not include_metal:
                        metal_donor_skips.append(label)
                        _skip(i, f"{el} coordinated to {m_txt}: the H count on "
                                 "a coordinated N/O (aqua/hydroxo/oxo O, "
                                 "amine/amide/imine N) is chemistry the riding "
                                 "geometry does not settle - place H from the "
                                 "difference map, or force_kind (e.g. "
                                 f"{{'{label}': 'OH'}}) for one riding H with "
                                 "the metal as the neighbour",
                              n=n, nb=nb_txt, geometry="metal-coordinated")
                        return None
                    pending.append(f"{label}: metal-coordinated {el} "
                                    "protonated (include_metal_bonded) - "
                                    "verify against the difference map")
                elif unblessed and not include_metal:
                    _skip(i, f"sigma-bonded to metal ({m_txt}) that the "
                             "metal-bonded audit did not classify - pass "
                             "include_metal_bonded=true to protonate with the "
                             "metal as a neighbour, or force_kind for this atom",
                          n=n, nb=nb_txt, geometry="metal-bonded")
                    return None
                else:
                    why = ("; ".join(sorted(set(sigma_kinds.values())))
                           or "include_metal_bonded")
                    pending.append(
                        f"{label}: metal-bonded carrier ({m_txt}; {why}) "
                        "protonated by its own geometry with the metal as a "
                        "neighbour - verify against the difference map")
            # 3) a part-0 carrier bonded into BOTH alternatives of a
            # disorder region counts each alternative as a separate
            # neighbour: n is inflated and any auto riding H conflicts with
            # one PART at SHELXL level (r12 CD-MOF C6H/C6J: HFIX 13 vs A/B
            # alternative oxygens). Per-PART H needs a deliberate split model.
            nz_parts = {parts[nb["j"]] for nb in heavy if parts[nb["j"]]}
            if parts[i] == 0 and len(nz_parts) >= 2 and forced is None:
                _skip(i, "bonded into %d different disorder PARTs %s - "
                         "auto riding H would conflict with one "
                         "alternative; model per-PART H deliberately "
                         "(split the carrier or add PART-matched H) or "
                         "leave unprotonated with disclosure"
                         % (len(nz_parts), sorted(nz_parts)),
                      n=n, nb=nb_txt, geometry="cross-PART")
                return None
            u_vecs = [_unit(nb["cart"] - cart[i]) for nb in heavy]
            kind: str | None = None
            geometry = ""
            note = ""

            # 4) typing by element + geometry (never by label text)
            if forced is not None:
                need = _KIND_N_HEAVY[forced]
                if n != need:
                    _skip(i, f"force_kind={forced} builds its geometry "
                             f"from {need} heavy neighbour(s) but this "
                             f"carrier has {n} - fix the model or pick a "
                             "kind that matches",
                          n=n, nb=nb_txt, geometry="forced")
                    return None
                kind = forced
                geometry = "forced"
                note = f"kind forced by request ({n} neighbours)"
                pending.append(
                    f"{label}: kind FORCED to {forced} (auto-classification "
                    "bypassed) - directions still come from the real bond "
                    "vectors; check the difference map and disclose")
            elif el == "C":
                linear_mc = next((k for k in sigma_kinds.values()
                                  if any(w in k for w in _LINEAR_MC_WORDS)),
                                 None)
                if linear_mc is not None:
                    _skip(i, f"no H on a {linear_mc} carbon (metal-bonded "
                             "audit: linear M-C-X, triple-bonded partner)",
                          n=n, nb=nb_txt, geometry="sp linear on metal")
                    return None
                if n == 0:
                    _skip(i, "isolated atom", n=0, nb=nb_txt,
                          geometry="isolated")
                    return None
                if n >= 4:
                    _skip(i, "saturated (4+ bonds)", n=n, nb=nb_txt,
                          geometry="saturated")
                    return None
                if any(not _bond_plausible(el, nb["element"], nb["d"])
                       for nb in heavy if not is_metal(nb["element"])):
                    _skip(i, "implausible bond length(s) "
                             f"({', '.join('%s %.2f' % (nb['element'], nb['d']) for nb in heavy)}"
                             " A vs covalent radii) - likely a "
                             "ghost/solvent blob",
                          n=n, nb=nb_txt, geometry="implausible bond")
                    return None
                if pi_rec is not None and n <= 2:
                    # eta-ring carbon: an aromatic/olefinic CH carrier
                    # whatever the ring angle (108 deg in a Cp) or the
                    # C-C length says about sp2/sp3 thresholds
                    if n == 2:
                        kind = "aromatic_CH"
                        geometry = f"eta{pi_rec['hapticity']}-ring sp2"
                        note = "face-on ring carbon: planar CH"
                    else:
                        kind = "vinyl_CH2"
                        geometry = f"eta{pi_rec['hapticity']}-fragment end"
                        note = "end atom of an open eta-fragment: =CH2"
                        pending.append(
                            f"{label}: end atom of an open eta"
                            f"{pi_rec['hapticity']}-fragment treated as =CH2 "
                            "- if this is a broken Cp/arene ring, complete "
                            "the ring first")
                elif n == 3:
                    angsum = _angle_sum(u_vecs)
                    if angsum >= planar_sum_min:
                        _skip(i, "planar sp2 junction (no H)", n=n, nb=nb_txt,
                              geometry=f"sp2 planar junction "
                                       f"(angle sum {angsum:.0f} deg)")
                        return None
                    kind = "tertiary_CH"
                    geometry = "sp3 tertiary"
                    note = f"angle sum {angsum:.0f} deg"
                elif n == 2:
                    ang = math.degrees(math.acos(np.clip(
                        float(np.dot(u_vecs[0], u_vecs[1])), -1, 1)))
                    if ang >= sp_linear_min:
                        _skip(i, f"near-linear sp carbon ({ang:.0f} deg - "
                                 "nitrile/alkyne/cumulene) - no H",
                              n=n, nb=nb_txt,
                              geometry=f"sp linear ({ang:.0f} deg)")
                        return None
                    avg_d = (heavy[0]["d"] + heavy[1]["d"]) / 2.0
                    if ang >= sp2_angle_min or avg_d <= sp2_avg_bond_max:
                        kind = "aromatic_CH"
                        geometry = "sp2"
                    else:
                        kind = "CH2"
                        geometry = "sp3"
                    note = f"X-C-X {ang:.0f} deg, mean bond {avg_d:.2f} A"
                else:  # n == 1
                    d = heavy[0]["d"]
                    if d >= methyl_min_bond:
                        kind = "CH3"
                        geometry = "terminal sp3"
                        pending.append(f"{label}: terminal C treated as methyl "
                                        f"(bond {d:.2f} A) - verify the model is "
                                        "complete here")
                    elif d >= 1.30:
                        kind = "vinyl_CH2"
                        geometry = "terminal sp2"
                        pending.append(f"{label}: terminal sp2 C treated as =CH2 "
                                        f"(bond {d:.2f} A) - ambiguous")
                    else:
                        kind = "linear_CH"
                        geometry = "terminal sp"
                        pending.append(f"{label}: terminal C with short bond "
                                        f"({d:.2f} A) treated as linear CH")
                    note = f"single neighbour at {d:.2f} A"
            elif el == "O":
                if (n == 1 and heavy[0]["element"] == "C"
                        and 1.32 <= heavy[0]["d"] <= 1.60):
                    kind = "OH"
                    geometry = "terminal on C (single bond)"
                    note = f"C-O {heavy[0]['d']:.2f} A"
                    pending.append(f"{label}: hydroxyl H added (C-O "
                                    f"{heavy[0]['d']:.2f} A) - torsion refined")
                else:
                    if n == 0:
                        geometry, why = "isolated", (
                            "isolated O (water / solvent?) - H come from the "
                            "difference map, not from riding geometry")
                    elif n == 1 and is_metal(heavy[0]["element"]):
                        metal_donor_skips.append(label)
                        geometry, why = "terminal on metal", (
                            "terminal on a metal (aqua/hydroxo/oxo O): H only "
                            f"on explicit request - force_kind={{'{label}': "
                            "'OH'} places one riding H")
                    elif n == 1 and heavy[0]["element"] == "C":
                        geometry, why = "terminal on C (double bond)", (
                            f"C=O {heavy[0]['d']:.2f} A: carbonyl / "
                            "carboxylate O - no H")
                    elif n == 1:
                        geometry, why = "terminal", (
                            f"terminal on {heavy[0]['element']} "
                            f"{heavy[0]['d']:.2f} A - not a clear hydroxyl")
                    else:
                        geometry, why = f"{n}-connected", (
                            f"{n}-connected O (ether / bridging / "
                            "carboxylate) - no H")
                    _skip(i, why, n=n, nb=nb_txt, geometry=geometry)
                    return None
            elif el == "N":
                if n == 3:
                    angsum = _angle_sum(u_vecs)
                    if angsum >= planar_sum_min:
                        _skip(i, "planar sp2 N (amide / aromatic / nitro) - "
                                 "no H", n=n, nb=nb_txt,
                              geometry=f"sp2 planar (angle sum {angsum:.0f} deg)")
                        return None
                    kind = "tertiary_NH"
                    geometry = "sp3 pyramidal"
                    note = f"angle sum {angsum:.0f} deg"
                elif n == 2:
                    kind = "NH_planar"
                    geometry = "2-connected"
                    note = "one planar H assumed"
                    pending.append(f"{label}: N-H added on 2-coordinate N - "
                                    "verify it is not a pyridine-type N")
                elif n == 1:
                    kind = "NH2_planar"
                    geometry = "terminal"
                    note = "planar NH2 assumed"
                    pending.append(f"{label}: terminal N treated as planar NH2 "
                                    "- ambiguous")
                else:
                    _skip(i, "isolated N", n=0, nb=nb_txt, geometry="isolated")
                    return None
            else:
                _skip(i, f"element {el} not supported", n=n, nb=nb_txt,
                      geometry="unsupported")
                return None

            # 5) SHELXL's own AFIX rule, applied BEFORE the H is placed.
            # The writer will emit AFIX_OF_KIND[kind]; SHELXL rebuilds the
            # connectivity itself (covalent radii + 0.5 A) and counts only
            # partners inside its H-generation window (Z 6-10), so a
            # carrier whose extra neighbour is a metal, a halogen or a
            # heavy main-group atom is counted differently there than
            # here. A mismatch used to surface at the NEXT run_shelxl,
            # one carrier per run ("** BAD AFIX 43 CONNECTIVITY ..."),
            # and cost the ka1 cage lane six add_hydrogens(exclude=[...])
            # rounds. Every offender is now found in this one call.
            mismatch = _afix_mismatch(kind, label, el, nbs, labels,
                                      lambda nb: counted_substituent(nb, i))
            if mismatch is not None:
                afix_mismatches.append(mismatch)
                _skip(i, _afix_mismatch_reason(mismatch), n=n, nb=nb_txt,
                      geometry=geometry, kind=kind)
                return None

            n_h = _KINDS[kind][1]
            if not site_sym.get(i).is_point_group_1() and n_h > 1:
                _skip(i, f"{kind} carrier on a special position - multi-H "
                         "riding groups would create symmetry duplicates",
                      n=n, nb=nb_txt, geometry=geometry, kind=kind)
                return None

            ref_perp = None
            if kind in ("CH3", "CH3_rotating", "OH", "vinyl_CH2", "NH2_planar"):
                ref_perp = substituent_perp(heavy[0], i)
                if ref_perp is None and kind == "CH3":
                    kind = "CH3_rotating"   # no substituent to stagger against
                    pending.append(f"{label}: methyl neighbour has no substituent"
                                    " - using freely rotating CH3")
                if ref_perp is None and kind in ("vinyl_CH2", "NH2_planar"):
                    _skip(i, "terminal sp2 group needs a neighbour "
                             "substituent to define the plane",
                          n=n, nb=nb_txt, geometry=geometry, kind=kind)
                    return None
            try:
                dirs = _h_directions(kind, u_vecs, ref_perp)
            except (ValueError, ZeroDivisionError):
                _skip(i, "degenerate geometry (collinear neighbours)",
                      n=n, nb=nb_txt, geometry=geometry, kind=kind)
                return None
            _row(i, "added", n=n, geometry=geometry, kind=kind, n_h=n_h,
                 reason=note, nb=nb_txt)
            # this carrier really does get H: its warnings are true now
            warnings.extend(pending)
            # the metal images counted as neighbours, so the placement
            # verification sees exactly the same neighbour set
            return {"i": i, "kind": kind, "dirs": dirs, "n_heavy": n,
                    "metal_images": [(labels[nb["j"]].upper(), nb["d"])
                                     for nb in sigma_metals]}

        for i in range(n0):
            el = elems[i]
            if el == "H":
                continue
            label = labels[i]
            forced = force_kind.get(label.upper())
            # force_kind is a per-atom opt-in: it also reaches carriers whose
            # element the caller did not list
            if el not in elements and forced is None:
                kept = kept_by_carrier.get(label.upper())
                if kept:
                    _row(i, "already_has_H", n_h=len(kept), kind="explicit",
                         reason=f"explicit H kept ({', '.join(kept)}) - {el} "
                                "is not in elements=, so they are not replaced")
                continue
            if label.upper() in exclude:
                _skip(i, "excluded by request (exclude=)", decision="excluded")
                continue
            # one carrier the classifier cannot handle must not take the
            # other carriers down with it: skip it WITH the reason
            try:
                entry = _classify(i, forced)
            except Exception as e:  # noqa: BLE001 - per-carrier robustness
                errors.append(f"{label}: {type(e).__name__}: {e}")
                _skip(i, f"classifier raised {type(e).__name__}: {e} - this "
                         "carrier was skipped, the others were processed")
                continue
            if entry is not None:
                plan.append(entry)

        # informational lines: things the call did NOT do and why. Kept
        # apart from `warnings`, which only ever describe H that were
        # actually placed.
        notes: list[str] = []
        if metal_donor_skips:
            notes.append(
                f"{len(metal_donor_skips)} metal-coordinated N/O carrier(s) "
                f"were considered and left unprotonated "
                f"({', '.join(metal_donor_skips[:20])}"
                f"{' ...' if len(metal_donor_skips) > 20 else ''}): whether "
                f"an aqua / hydroxo / oxo O or an amine / amide / imine N "
                f"carries H is chemistry the riding geometry cannot settle"
                + (" and include_metal_bonded does not settle it either"
                   if include_metal else "")
                + f" - read the difference map at the site, or state the H "
                  f"count yourself with force_kind (e.g. "
                  f"{{'{metal_donor_skips[0]}': 'OH'}}), which places one "
                  f"riding H with the metal as the neighbour. Their rows "
                  f"are in decisions/skipped.")
        if afix_mismatches:
            notes.append(
                f"{len(afix_mismatches)} carrier(s) were left unprotonated "
                f"because SHELXL would refuse the AFIX group the writer "
                f"emits for them (afix_connectivity_mismatches below, ALL "
                f"of them in this one call): SHELXL rebuilds the "
                f"connectivity itself (covalent radii + "
                f"{SHELXL_BOND_TOLERANCE_A} A) and, when the count does "
                f"not fit the AFIX code, retries after dropping the bonds "
                f"to elements outside Z 6-10 ('Bond(s) to X ignored in "
                f"idealizing H-atoms') - here neither count fits, so its "
                f"reading differs from the one the geometry was built "
                f"from. Placing them anyway would abort the next "
                f"run_shelxl with '** BAD AFIX ... CONNECTIVITY OR PART "
                f"NUMBERS ... TERMINATING **'.")

        def _decision_block() -> dict[str, Any]:
            rows = [rows_by_i[k] for k in sorted(rows_by_i)]
            counts: dict[str, int] = {"considered": len(rows)}
            for d in ("added", "skipped", "excluded", "already_has_H"):
                counts[d] = sum(1 for r in rows if r["decision"] == d)
            out: dict[str, Any] = {
                "decisions": rows[:DECISION_TABLE_CAP],
                "decision_counts": counts,
            }
            if len(rows) > DECISION_TABLE_CAP:
                out["decisions_note"] = (
                    f"decision table capped at {DECISION_TABLE_CAP} of "
                    f"{len(rows)} atoms (model order); decision_counts "
                    "covers all of them, skipped= lists the first "
                    f"{_SKIPPED_CAP} skipped carriers with reasons")
            mba = audit.report()
            if mba is not None:
                out["metal_bonded_audit"] = mba
            if afix_mismatches:
                out["afix_connectivity_mismatches"] = afix_mismatches
            if notes:
                out["notes"] = notes
            return out

        if errors and not plan and len(errors) == sum(
                1 for r in rows_by_i.values() if r["decision"] == "skipped"):
            # nothing at all could be processed: that is a failure, with
            # the table attached so the agent still sees what happened
            return ToolResult(ok=False, error=(
                f"add_hydrogens could not classify any carrier ({len(errors)} "
                f"raised): {errors[0]}"),
                summary={"n_h_added": 0, "n_h_removed": n_h_removed,
                         "per_carrier": [], "skipped": skipped[:_SKIPPED_CAP],
                         "warnings": warnings[:40], "errors": errors[:10],
                         **_decision_block()})

        if not plan:
            return ToolResult(ok=True, summary={
                "n_h_added": 0, "n_h_removed": n_h_removed,
                "per_carrier": [], "skipped": skipped[:_SKIPPED_CAP],
                "warnings": warnings[:40],
                "note": "no suitable carrier atoms found - see decisions",
                **_decision_block()})

        # ---- add H scatterers + build constraints --------------------------
        # After placement, verify against a fresh connectivity table that each
        # pivot still has exactly the neighbour count its constraint class will
        # see (a placed H from a nearby carrier can fall within the covalent
        # cutoff of a distorted pivot and change the count -> InvalidConstraint
        # at the next refine). Offending carriers are dropped and the placement
        # redone (dropping H only reduces counts, so this converges quickly).
        def _strip_all_h():
            # only the H THIS call appended (index >= n0). The explicit H
            # kept by _partition_existing_h sit below n0 and must stay:
            # stripping every H here shifted the fresh H down by their
            # number, every constraint index pointed at the wrong atom,
            # every carrier failed verification (2 -> 3 neighbours) and
            # the kept water H vanished with them - the hex-l0-r1 "keep
            # the difference-map water H" path never survived placement
            n_now = ses.model.scatterers().size()
            if n_now > n0:
                ses.model = ses.model.select(
                    flex.bool([k < n0 for k in range(n_now)]))

        def _drop(entry: dict, reason: str) -> None:
            """A carrier that failed at placement: recorded like any other
            skip, its decision row flipped from 'added' to 'skipped'."""
            i = entry["i"]
            skipped.append({"atom": labels[i], "reason": reason})
            row = rows_by_i.get(i)
            if row is not None:
                row.update({"decision": "skipped", "n_h": 0,
                            "reason": reason})

        geom_constraints: list = []
        u_constraints: list = []
        checks: list[tuple[int, str]] = []
        h_indices: list[int] = []
        per_carrier: list[dict] = []
        kind_counts: dict[str, int] = {}
        h_of_pivot: dict[int, set[int]] = {}
        h_part: dict[int, int] = {}

        for _attempt in range(_PLACEMENT_PASSES):
            _strip_all_h()
            geom_constraints, u_constraints = [], []
            checks, h_indices, per_carrier = [], [], []
            kind_counts, h_of_pivot, h_part = {}, {}, {}
            existing_labels = set(labels)

            def _taken(name: str) -> bool:
                return name in existing_labels or name.upper() in reserved

            next_idx = n0
            entries_ok = []
            for entry in plan:
                i, kind = entry["i"], entry["kind"]
                cls, n_h, u_mult = _KINDS[kind]
                pivot_el = elems[i]
                length = bond_lengths.get(kind)
                if length is None:
                    length_tab = cls.room_temperature_bond_length.get(pivot_el)
                    if length_tab is None:
                        _drop(entry, f"no ideal {pivot_el}-H length for {kind}")
                        continue
                    length = length_tab
                base = labels[i]
                if base[:2].capitalize() == pivot_el and len(pivot_el) == 2:
                    suffix = base[2:]
                elif base[:1].upper() == pivot_el:
                    suffix = base[1:]
                else:
                    suffix = base
                u_init = float(u_mult * u_eqs[i])
                h_idx_group = [next_idx + k for k in range(n_h)]
                h_labels: list[str] = []
                for k in range(n_h):
                    tag = "" if n_h == 1 else chr(ord("A") + k)
                    lbl = f"H{suffix}{tag}"
                    m = 0
                    while _taken(lbl):
                        m += 1
                        lbl = f"H{suffix}{tag}{m}"
                    if len(lbl) > 4:
                        # SHELX labels are 4 chars: a longer label would be
                        # renamed at serialization and desync every
                        # label-keyed flag (PART membership above all) -
                        # fall back to plain sequential H numbering
                        q = 1
                        while _taken(f"H{q}"):
                            q += 1
                        lbl = f"H{q}"
                    existing_labels.add(lbl)
                    h_labels.append(lbl)
                kwargs = {"pivot": i,
                          "constrained_site_indices": tuple(h_idx_group)}
                if bond_lengths.get(kind) is not None:
                    kwargs["bond_length"] = float(length)
                if kind in ("OH", "CH3_rotating"):
                    kwargs["rotating"] = True
                # build the constraint and the sites BEFORE touching the
                # model: a generator that throws for this one carrier
                # leaves no orphan H behind and the other carriers go on
                try:
                    con = cls(**kwargs)
                    h_sites = [uc.fractionalize(tuple(
                        cart[i] + entry["dirs"][k] * float(length)))
                        for k in range(n_h)]
                except Exception as e:  # noqa: BLE001 - per-carrier robustness
                    _drop(entry, f"H generator {cls.__name__} raised "
                                 f"{type(e).__name__}: {e} - carrier skipped")
                    continue
                for h_i, lbl, site in zip(h_idx_group, h_labels, h_sites):
                    ses.model.add_scatterer(xray.scatterer(
                        label=lbl, site=site, scattering_type="H",
                        u=u_init, occupancy=occs[i]))
                    h_part[h_i] = parts[i]
                next_idx += n_h
                geom_constraints.append(con)
                for h_i, h_lbl in zip(h_idx_group, h_labels):
                    u_constraints.append(u_iso_proportional_to_pivot_u_eq(
                        u_iso_scatterer_idx=h_i, u_eq_scatterer_idx=i,
                        multiplier=float(u_mult)))
                    checks.append((h_i, h_lbl))
                checks.append((i, labels[i]))
                h_indices.extend(h_idx_group)
                h_of_pivot[i] = set(h_idx_group)
                kind_counts[kind] = kind_counts.get(kind, 0) + 1
                per_carrier.append({"carrier": labels[i], "kind": kind,
                                    "n_h": n_h, "h": h_labels,
                                    "x_h": round(float(length), 3)})
                entries_ok.append(entry)
            plan = entries_ok
            if not plan:
                break
            ses.model.scattering_type_registry(table="it1992")
            # ---- verification pass against a fresh connectivity table ------
            n_now = ses.model.scatterers().size()
            ct2 = smtbx.utils.connectivity_table(
                ses.model, **part_kwargs_from_parts(
                    parts + [h_part.get(k, 0) for k in range(n0, n_now)]))
            pst2 = ct2.pair_asu_table.extract_pair_sym_table(
                skip_j_seq_less_than_i_seq=False,
                all_interactions_from_inside_asu=True)
            bad: list[dict] = []
            scs_now = ses.model.scatterers()
            for entry in plan:
                i = entry["i"]
                own_h = h_of_pivot.get(i, set())
                metal_imgs = entry.get("metal_images") or []
                count = 0
                for j, ops in pst2[i].items():
                    if j in own_h:
                        continue
                    pj = parts[j] if j < n0 else h_part.get(j, 0)
                    if not _part_compat(parts[i], pj):
                        continue
                    el_j = elems[j] if j < n0 else "H"
                    if is_metal(el_j):
                        # the same metal images the planning pass counted
                        # (a ring metal at 2.05 A is a pi contact, an
                        # audit-blessed sigma metal at 2.55 A a neighbour):
                        # nothing else is re-derived here
                        lj = labels[j].upper()
                        for op in ops:
                            p_j = np.array(uc.orthogonalize(
                                op * tuple(scs_now[j].site)))
                            d_j = float(np.linalg.norm(p_j - cart[i]))
                            if any(lb == lj and abs(d_j - d0) < 1e-3
                                   for lb, d0 in metal_imgs):
                                count += 1
                        continue
                    count += len(ops)
                if count != entry["n_heavy"]:
                    bad.append(entry)
                    _drop(entry, "H placement changed the pivot's apparent "
                                 f"connectivity ({entry['n_heavy']} -> {count} "
                                 "neighbours) - crowded/distorted site, H "
                                 "removed")
            if not bad:
                break
            bad_ids = {id(e) for e in bad}
            plan = [e for e in plan if id(e) not in bad_ids]
        else:
            _strip_all_h()
            for entry in plan:
                _drop(entry, "placement verification did not converge in "
                             f"{_PLACEMENT_PASSES} passes - H removed")
            plan = []

        if not plan:
            ses.model.scattering_type_registry(table="it1992")
            return ToolResult(ok=True, summary={
                "n_h_added": 0, "n_h_removed": n_h_removed,
                "per_carrier": [], "skipped": skipped[:_SKIPPED_CAP],
                "warnings": warnings[:40],
                "note": "no carrier passed placement verification - see "
                        "decisions",
                **_decision_block()})
        fixup = _HRidingFixup(checks=checks, h_indices=h_indices)
        ses.flags["h_constraints"] = [fixup] + geom_constraints + u_constraints
        # full (untruncated) riding metadata: SHELX writer AFIX emission and
        # node-store checkout (re-running add_hydrogens) both depend on it
        ses.flags["h_riding_meta"] = {"elements": elements,
                                      "per_carrier": list(per_carrier),
                                      # full input params: the run_shelxl
                                      # adopt replay re-runs with these so
                                      # custom classification params
                                      # (planar_sum_min etc.) survive
                                      "params": {str(k): v for k, v
                                                 in params.items()
                                                 if not str(k).startswith("_")}}

        # H on a disordered carrier joins the carrier's disorder group: same
        # PART, same FVAR sign/multiplier -> the SHELX writer emits it inside
        # the right PART block with the sof coded to the same free variable,
        # and its occupancy (already copied from the carrier) stays linked.
        n_h_in_parts = 0
        if part_of:
            member_of = {str(m.get("label", "")).upper(): (g, m)
                         for g in dgroups for m in g.get("members", ())}
            extra = ses.flags.get("parts_extra") or {}
            for pc in per_carrier:
                gm = member_of.get(pc["carrier"].upper())
                if gm is None:
                    p_x = extra.get(pc["carrier"].upper())
                    if p_x:
                        # carrier sits in a PART block without FVAR linkage:
                        # its H stay in the same block (plain sofs)
                        for h_lbl in pc["h"]:
                            extra[h_lbl.upper()] = int(p_x)
                            n_h_in_parts += 1
                        ses.flags["parts_extra"] = extra
                    continue
                g, m0 = gm
                for h_lbl in pc["h"]:
                    g["members"].append({"label": h_lbl,
                                         "part": int(m0.get("part") or 0),
                                         "sign": int(m0.get("sign", 1)),
                                         "mult": float(m0.get("mult", 1.0))})
                    n_h_in_parts += 1

        n_c = sum(1 for e in elems if e == "C")
        return ToolResult(ok=True, summary={
            "n_h_added": len(h_indices),
            "n_h_removed": n_h_removed,
            "n_carriers": len(per_carrier),
            "n_h_in_disorder_parts": n_h_in_parts or None,
            "kinds": kind_counts,
            "h_per_c": round(len(h_indices) / n_c, 2) if n_c else None,
            "riding": "site + Uiso(1.2/1.5 x U_eq) ride on carrier via smtbx "
                      "constraints applied in every subsequent refine",
            "per_carrier": per_carrier[:60],
            "skipped": skipped[:_SKIPPED_CAP],
            "warnings": warnings[:40],
            "n_atoms": ses.model.scatterers().size(),
            # per-atom overrides are a disclosure item, not a hidden setting
            "forced_kinds": force_kind or None,
            "excluded": sorted(exclude) or None,
            # explicit H on carriers outside elements= survive a re-run
            "kept_explicit_h": kept_explicit or None,
            # the per-atom decision table (+ counts, + the metal-bonded
            # audit block when the model has metal-bonded light atoms)
            **_decision_block(),
        })


# --------------------------------------------------------------------------
class OptimizeWeights(Tool):
    name = "optimize_weights"
    description = (
        "Optimize the SHELX weighting-scheme parameters a, b "
        "(w = 1/[sigma^2 + (aP)^2 + bP], P=(Fo^2+2Fc^2)/3) so the goodness of "
        "fit approaches 1.0 and the variance is flat across intensity bins "
        "(the SHELXL WGHT update recipe). Alternates the a,b grid search with "
        "least-squares refinement until stable, stores the chosen weights in "
        "the session so later refine calls use them by default, and reports "
        "GooF before/after. NOT the first choice: run_shelxl("
        "mode='adopt_wght') loops SHELXL's own suggested WGHT to convergence "
        "and adopts it in minutes (17 s on a 221-atom case), while this tool "
        "alternates an in-process a,b search with FULL refinements - up to "
        "~15 of them - and once ran 65 min on a large framework without "
        "returning (ka1 cage 2026-09). Use it where adopt_wght cannot go (no "
        "SHELXL binary) or when the SHELXL loop will not settle. BUDGET: it "
        f"stops itself at timeout_s (default "
        f"{default_timeout_s('optimize_weights'):.0f} s) and returns the "
        "best weights reached so far with partial=true.")
    params_schema = {
        "type": "object",
        "properties": {
            "mode": {"type": "string",
                     "enum": ["isotropic", "aniso_heavy", "anisotropic"],
                     "default": "anisotropic",
                     "description": "refinement mode used during optimization "
                                    "(should match the current model state)"},
            "n_cycles": {"type": "integer", "default": 8},
            "max_rounds": {"type": "integer", "default": 4,
                           "description": "bounds the SHELXL a,b-update "
                                          "phase ONLY; if |GooF-1| still "
                                          "exceeds goof_tol afterwards, a "
                                          "bisection fallback may add up "
                                          "to ~11 more refinements (the "
                                          "summary's phases field shows "
                                          "the split; r12 read "
                                          "'max_rounds=2 but n_rounds=8' "
                                          "as a bug - it was the "
                                          "fallback)"},
            "use_solvent_mask": {"type": "boolean", "default": True},
            "goof_tol": {"type": "number", "default": 0.08,
                         "description": "after the SHELXL update, |GooF-1| above "
                                        "this triggers a direct bisection on b "
                                        "(GooF>1) or a (GooF<1)"},
            "timeout_s": timeout_param(
                "optimize_weights",
                "ok=true with partial=true, the best a,b reached so far "
                "already stored in the session, the full history, and a "
                "pointer to run_shelxl(mode='adopt_wght') as the cheap "
                "alternative"),
        },
    }

    def _shelx_ab_update(self, ses, a: float, b: float, n_params: int,
                         use_mask: bool) -> tuple[float, float]:
        fo_sq = ses.fo_sq
        f_calc = fo_sq.structure_factors_from_scatterers(
            xray_structure=ses.model, algorithm="direct").f_calc()
        f_mask = ses.flags.get("f_mask") if use_mask else None
        if f_mask is not None and f_mask.size() == fo_sq.size():
            f_calc = f_calc.customized_copy(data=f_calc.data() + f_mask.data())
        fc_sq = fo_sq.array(
            data=flex.norm(f_calc.data())).set_observation_type_xray_intensity()
        denom = flex.sum(fc_sq.data() * fc_sq.data())
        if denom <= 0:
            raise RuntimeError("zero Fc^2 - cannot scale")
        scale = flex.sum(fo_sq.data() * fc_sq.data()) / denom
        weighting = least_squares.mainstream_shelx_weighting(a=a, b=b)
        new = weighting.optimise_parameters(fo_sq, fc_sq, scale, max(n_params, 1))
        return float(new.a), float(new.b)

    def run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        from .refinement_tools import RefineLS
        ses = ctx.session
        if ses.model is None or ses.fo_sq is None:
            return ToolResult.failure("need a model and merged data")
        mode = params.get("mode", "anisotropic")
        n_cycles = int(params.get("n_cycles", 8))
        max_rounds = int(params.get("max_rounds", 4))
        use_mask = bool(params.get("use_solvent_mask", True))
        refine = RefineLS()

        wflags = ses.flags.get("weights") or {}
        a = float(wflags.get("a", 0.1))
        b = float(wflags.get("b", 0.0))

        budget = budget_for(ctx, "optimize_weights", params)

        def _ping(msg: str) -> None:
            budget.ping(msg)

        with budget:
            return self._optimize(ctx, budget, refine, ses, params, mode,
                                  n_cycles, max_rounds, use_mask, a, b, _ping)

    def _optimize(self, ctx, budget, refine, ses, params, mode, n_cycles,
                  max_rounds, use_mask, a, b, _ping) -> ToolResult:
        # the baseline refinement is not optional: without it there is no
        # "before" to compare against and no n_params for the a,b update
        r = refine.run(ctx, mode=mode, n_cycles=n_cycles, weight_a=a, weight_b=b,
                       use_solvent_mask=use_mask, label="weights_baseline")
        if not r.ok:
            return ToolResult.failure(f"baseline refinement failed: {r.error}")
        before = {k: r.summary[k] for k in ("r1_strong", "wr2", "goof")}
        n_params = int(r.summary.get("n_params") or 1)
        _ping(f"baseline: GooF {before['goof']}, R1 "
              f"{before['r1_strong']} (a={a:g}, b={b:g})")

        history = [{"a": round(a, 5), "b": round(b, 5),
                    "goof": r.summary["goof"], "r1": r.summary["r1_strong"],
                    "wr2": r.summary["wr2"]}]
        # a LIST, not a tuple: _grid and _eval rebind it in place so the
        # partial return below sees the best point actually reached, not the
        # baseline (the whole point of a partial result)
        best = [abs(r.summary["goof"] - 1.0), a, b, r.summary]
        try:
            return self._grid(ctx, budget, refine, ses, params, mode, n_cycles,
                              max_rounds, use_mask, a, b, _ping, before,
                              n_params, history, best)
        except BudgetStop as stop:
            # the last COMPLETED refinement left the model consistent and its
            # weights are the best we know: keep them, say it is partial
            ses.flags["weights"] = {"a": round(best[1], 5), "b": round(best[2], 5)}
            cancelled = isinstance(stop, Cancelled)
            return ToolResult(ok=True, summary={
                "partial": True,
                "timed_out": not cancelled,
                "cancelled": cancelled,
                "budget": budget.report(),
                "weights": ses.flags["weights"],
                "goof_before": before["goof"], "goof_after": best[3]["goof"],
                "r1_before": before["r1_strong"],
                "r1_after": best[3]["r1_strong"],
                "n_rounds": len(history) - 1,
                "history": history,
                "note": (
                    f"stopped early ({stop}) with the best a,b found so far "
                    f"stored in the session - later refine calls already use "
                    f"them, nothing was lost and nothing was killed."),
                "next_step": (
                    "each grid point here is a FULL refinement of this "
                    "model, so the grid is the wrong instrument once one "
                    "refinement costs minutes. Cheap alternative that does "
                    "the same job: run_shelxl(mode='adopt_wght') loops "
                    "SHELXL's own suggested WGHT to convergence and adopts "
                    "it (17 s on a 221-atom all-anisotropic model where this "
                    "tool ran 65 min). If you do want to continue here, "
                    "raise timeout_s deliberately or cut the cost per point "
                    "with n_cycles / mode='aniso_heavy' - do NOT just "
                    "re-issue the same call."),
            })

    def _grid(self, ctx, budget, refine, ses, params, mode, n_cycles,
              max_rounds, use_mask, a, b, _ping, before, n_params,
              history, best) -> ToolResult:
        n_update_rounds = 0
        for it in range(max_rounds):
            budget.check(f"SHELXL a,b update round {it + 1}/{max_rounds}")
            try:
                new_a, new_b = self._shelx_ab_update(ses, a, b, n_params, use_mask)
            except Exception as e:  # noqa: BLE001
                return ToolResult(ok=True, summary={
                    "weights": {"a": round(best[1], 5), "b": round(best[2], 5)},
                    "goof_before": before["goof"], "goof_after": best[3]["goof"],
                    "history": history,
                    "warning": f"a,b update failed ({e}); kept best so far"})
            converged = abs(new_a - a) < 2e-4 and abs(new_b - b) < 2e-2
            a, b = new_a, new_b
            _ping(f"update round {it + 1}/{max_rounds}: trying a={a:g}, "
                  f"b={b:g} ({budget.remaining():.0f}s of budget left)")
            r = refine.run(ctx, mode=mode, n_cycles=n_cycles,
                           weight_a=a, weight_b=b, use_solvent_mask=use_mask,
                           label=f"weights_round_{it}")
            if not r.ok:
                break
            n_update_rounds += 1
            history.append({"a": round(a, 5), "b": round(b, 5),
                            "goof": r.summary["goof"],
                            "r1": r.summary["r1_strong"],
                            "wr2": r.summary["wr2"]})
            n_params = int(r.summary.get("n_params") or n_params)
            _ping(f"round {it + 1}: GooF {r.summary['goof']}, "
                  f"R1 {r.summary['r1_strong']}"
                  + (" - converged" if converged else ""))
            if abs(r.summary["goof"] - 1.0) < best[0]:
                best[:] = [abs(r.summary["goof"] - 1.0), a, b, r.summary]
            if converged:
                break

        # ---- fallback: the SHELXL grid clamps a at 0.2 (b reset to 0); if
        # GooF is still off target, bisect b upward (GooF > 1) or a downward
        # (GooF < 1) - both monotonically reduce/raise chi^2.
        goof_tol = float(params.get("goof_tol", 0.08))

        def _eval(aa: float, bb: float, tag: str):
            budget.check(f"bisection fallback {tag} (a={aa:g}, b={bb:g})")
            _ping(f"bisection fallback ({tag}): trying a={aa:g}, b={bb:g} "
                  f"({budget.remaining():.0f}s of budget left)")
            rr = refine.run(ctx, mode=mode, n_cycles=n_cycles, weight_a=aa,
                            weight_b=bb, use_solvent_mask=use_mask, label=tag)
            if not rr.ok:
                return None
            history.append({"a": round(aa, 5), "b": round(bb, 5),
                            "goof": rr.summary["goof"],
                            "r1": rr.summary["r1_strong"],
                            "wr2": rr.summary["wr2"]})
            if abs(rr.summary["goof"] - 1.0) < best[0]:
                best[:] = [abs(rr.summary["goof"] - 1.0), aa, bb, rr.summary]
            return rr.summary["goof"]

        if best[0] > goof_tol:
            a, b, goof_now = best[1], best[2], best[3]["goof"]
            if goof_now > 1.0:
                lo, hi, hi_goof = b, max(2.0, 2.0 * b if b else 2.0), None
                for _ in range(5):          # expand until GooF crosses 1
                    g = _eval(a, hi, "weights_bexp")
                    if g is None:
                        break
                    if g <= 1.0:
                        hi_goof = g
                        break
                    lo, hi = hi, hi * 3.0
                if hi_goof is not None:
                    for _ in range(5):      # bisect
                        mid = 0.5 * (lo + hi)
                        g = _eval(a, mid, "weights_bbis")
                        if g is None or abs(g - 1.0) <= goof_tol:
                            break
                        if g > 1.0:
                            lo = mid
                        else:
                            hi = mid
            else:
                lo, hi = 0.0, a             # shrink a to raise GooF
                for _ in range(6):
                    mid = 0.5 * (lo + hi)
                    g = _eval(mid, b, "weights_abis")
                    if g is None or abs(g - 1.0) <= goof_tol:
                        break
                    if g < 1.0:
                        hi = mid
                    else:
                        lo = mid

        best_a, best_b, best_summary = best[1], best[2], best[3]
        ses.flags["weights"] = {"a": round(best_a, 5), "b": round(best_b, 5)}
        n_total = len(history) - 1
        return ToolResult(ok=True, summary={
            "weights": ses.flags["weights"],
            "goof_before": before["goof"], "goof_after": best_summary["goof"],
            "r1_before": before["r1_strong"], "r1_after": best_summary["r1_strong"],
            "wr2_before": before["wr2"], "wr2_after": best_summary["wr2"],
            "n_rounds": n_total,
            "phases": {"shelxl_update": n_update_rounds,
                       "bisection_fallback": n_total - n_update_rounds},
            "history": history,
            "note": "chosen a,b stored in session; subsequent refine calls "
                    "use them by default. n_rounds counts EVERY refinement "
                    "(update phase, bounded by max_rounds, PLUS the "
                    "bisection fallback) - see phases for the split",
        })
