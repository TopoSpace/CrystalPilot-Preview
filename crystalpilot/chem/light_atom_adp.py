"""Post-refinement element consistency of the LIGHT atoms, read from their
displacement parameters.

reg1-ext2 case rz (twin_rz5267_iucr, C2/c, 2026-09-04): the metal-free
`interpret_peaks` branch deliberately never guesses C vs N (a 17 % step in
Z, invisible on an unrefined map) and labels such sites C with
element_uncertain. The agent refined that model, delivered a nitro group's
nitrogen as a carbon, and rationalised the resulting C(O)2 as a
carboxylate - formula C30H24N2O9 against the reference C28H22N4O9. No
geometry could have caught it: nitro N-O 1.21-1.23 A and carboxylate C-O
1.25-1.28 A overlap once the esds are honest.

What CAN catch it is the refinement itself. A site whose label carries the
wrong number of electrons is compensated by its ADP: least squares matches
Z * exp(-8 pi^2 U s^2) over the measured range, so

    dU = U_refined - U_true = ln(Z_label / Z_true) / (8 pi^2 <s^2>)

A label with too FEW electrons (C on an N site) refines to a Ueq that is
too SMALL - the model shrinks U to concentrate more density at the site -
and a label with too many (N on a C site, O on an N site) to a Ueq that is
too LARGE. This is the same physics `metal_bonded_audit` already uses for
light atoms bonded to a metal (ueq_over_metal_light_neighbours); the only
difference here is the reference: an atom's OWN bonded non-H neighbours
instead of the metal's other light donors, so the rule reaches every light
atom in an organic, metal-free or not.

Nothing here is element-specific: the bands are ratios, the suggested
alternative is one step in Z through the periodic table, and the implied
electron count comes from the equation above with the data's own d_min.
The audit never relabels anything - it reports the numbers and what they
are compatible with.

Pure function: audit_light_atom_elements(xs, ...) -> dict.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

from .connectivity import covalent_radius
from .knowledge import is_metal
from .metal_bonded_audit import (_PLANAR_SUM_DEG, _TOL_ORGANIC, _Model,
                                 _angle, _atomic_number, _element_of,
                                 _is_audit_metal, _mx_window)

# ---------------------------------------------------------------------------
# the physics
# ---------------------------------------------------------------------------
# dU = ln(Z_label / Z_true) / (8 pi^2 <s^2>), with <s^2> the INFORMATION-
# weighted mean squared (sin theta / lambda) of the data. That is much
# smaller than the volume-weighted (3/5) s_max^2, because intensities fall
# off with angle: refining synthetic Fo^2 of ring-plus-substituent
# structures in this repo's own cctbx (d_min 0.70/0.83/1.00, five one- and
# two-step mislabels) puts it at 0.19-0.39 of s_max^2, i.e.
_S2_EFF_FRACTION = 0.25         # <s^2> / s_max^2, s_max = 1 / (2 d_min)
_D_MIN_FALLBACK = 0.83          # A, routine Mo data, when the session has none
# With that value the implied electron count below reproduces the true Z of
# every one of those cases to within 10 %. In Ueq terms, at d_min 0.83 A a
# ONE-STEP error moves an ordinary light-atom U (0.026 A^2) by 0.018-0.030
# A^2 - tests/test_light_atom_element_check.py refines the same structures
# and shows the effect end to end:
#     N site labelled C   0.0260 -> 0.0080   (0.31x)
#     O site labelled N   0.0300 -> 0.0096   (0.32x)
#     C site labelled N   0.0260 -> 0.0566   (2.18x)
#     N site labelled O   0.0300 -> 0.0598   (1.99x)
#     O site labelled C   0.0260 -> 0.0000   (two steps: U hits zero)
# So the Ueq response (a factor of ~3 down or ~2 up) is far LARGER than the
# electron-count error it comes from (C<->N 17 %, N<->O 14 %), and it is
# asymmetric: going UP is cheaper for the fit than going down, which cannot
# pass zero. The response is a fixed dU, not a fixed ratio, so it shrinks
# against a large U: at room temperature (U ~ 0.055) the same one-step error
# is only a 0.67x / 1.5x effect and the LOW side starts to miss things.

# ---------------------------------------------------------------------------
# the bands
# ---------------------------------------------------------------------------
# Ueq also carries libration, and the reference here is the atom's OWN
# bonded neighbours, so a raw ratio against their median is biased by their
# connectivity: a TERMINAL neighbour (nitro / carboxylate O, a methyl C)
# legitimately librates 1.3-1.6x above the skeleton atom it hangs off, and
# a correct carboxylate C therefore sits at 0.6-0.77 of its own two
# oxygens. Two guards keep that out of the verdict - the reference is
# mass-matched (below), and the band has to be cleared against EVERY
# reference neighbour individually, not just their median (see UNANIMITY in
# audit_light_atom_elements). A correct carboxylate C is low against its
# oxygens but never against the ring carbon it hangs on, so it survives;
# a mislabelled site is low against all of them. What is left to clear:
#
#  * LOW side. Motifs whose neighbours are ALL terminal have nothing else
#    to be checked against (nitrate N, formate/carbonate C): a correct one
#    sits at 0.65-0.77 of its oxygens. The band goes below that floor, and
#    above the 0.31-0.55x a one-step error produces.
_UEQ_RATIO_LOW = 0.55
#  * HIGH side. A mass-matched neighbour does not vibrate LESS than the
#    skeleton atom holding it, so there is no matching upward bias; only a
#    floppy bridging atom (up to ~1.3x its own, more rigid neighbours) has
#    to be cleared, against a ~2x one-step response.
_UEQ_RATIO_HIGH = 1.50

#: ADP magnitude scales with mass - a sulfonate S sits well BELOW its own
#: three oxygens with nothing wrong with it - so a reference neighbour must
#: be of comparable weight. Within this factor in Z: for C/N/O that keeps
#: B/C/N/O/F and drops P/S/Cl/Br; an atom with no mass-matched reference is
#: reported as skipped rather than judged against the wrong yardstick.
_REF_Z_FACTOR = 1.6
#: a median needs more than one number, and a TERMINAL atom's Ueq is
#: dominated by its own libration rather than by its electron count, so an
#: atom is only compared when it has at least this many non-H neighbours
_MIN_REFERENCE_NEIGHBOURS = 2
#: below this occupancy the ADP is refined against the occupancy (they are
#: strongly correlated) and carries no element information
_MIN_OCCUPANCY = 0.9
#: how many flags travel in the report before they are only counted
_MAX_FLAGS = 20

#: noble gases are never the answer to "one step in Z"
_NOBLE = frozenset({"He", "Ne", "Ar", "Kr", "Xe", "Rn", "Og"})
#: below boron there is no covalent light-atom chemistry to suggest
_MIN_SUGGESTION_Z = 5

NOTE = ("Ueq is compared with the median Ueq of the atom's own bonded non-H "
        "neighbours of comparable mass, and a flag has to clear the band "
        "against every one of them: a label with too few electrons refines to "
        "a Ueq that is too small, one with too many to a Ueq that is too "
        "large. A quiet result is not a clean bill of health - the effect is "
        "a fixed shift in U, so it shrinks against a large (warm) Ueq, and a "
        "site whose neighbours are all pseudo-equivalent shares the error "
        "with them. This is a HINT with the numbers behind it, never an "
        "element decision - cross-check the chemistry (connectivity, H count, "
        "composition) and an omit map (integrate_difference_density) before "
        "retyping anything.")

_GEOMETRY_NOTE = (
    "geometry cannot separate these: nitro N-O 1.21-1.23 A overlaps "
    "carboxylate C-O 1.25-1.28 A / C=O 1.21 A once the esds are honest. The "
    "electron count is what differs (N 7 vs C 6), and after refinement that "
    "shows up in Ueq")


def _u_per_ln_z(d_min: float | None) -> float:
    """Ueq (A^2) absorbed per unit ln(Z) of mislabel, for data to d_min."""
    d = float(d_min) if d_min and d_min > 0.3 else _D_MIN_FALLBACK
    s_max_sq = 1.0 / (2.0 * d) ** 2
    return 1.0 / (8.0 * math.pi ** 2 * _S2_EFF_FRACTION * s_max_sq)


def _element_by_z(z: int) -> str | None:
    try:
        from cctbx.eltbx import tiny_pse
        return str(tiny_pse.table(int(z)).symbol())
    except Exception:  # noqa: BLE001 - out of range / no such element
        return None


def one_step_in_z(el: str, direction: int) -> str | None:
    """The element one step up (+1) or down (-1) in Z from `el`, restricted
    to something a light-atom site could plausibly be: no noble gas, no
    metal, nothing below boron. Element-generic - no table of pairs."""
    z = _atomic_number(el)
    if not z:
        return None
    cand = _element_by_z(z + direction)
    if cand is None or cand in _NOBLE or is_metal(cand):
        return None
    if (_atomic_number(cand) or 0) < _MIN_SUGGESTION_Z:
        return None
    return cand


def _confidence(margin: float, caps: list[str]) -> str:
    """margin = how far outside the band the ratio sits, as a factor >= 1."""
    base = "high" if margin >= 1.30 else "medium" if margin >= 1.10 else "low"
    order = ["low", "medium", "high"]
    cap = "high"
    for c in caps:
        cap = order[min(order.index(cap), order.index(c))]
    return order[min(order.index(base), order.index(cap))]


def _cutoff_for(elems: list[str]) -> float:
    """Neighbour-search cutoff covering every organic bond plus the metal
    windows of whatever metals are present (same recipe as the metal-bonded
    audit, so the two checks see the same graph)."""
    present = sorted({e for e in elems if e != "H"})
    metals = [e for e in present if _is_audit_metal(e)]
    lights = [e for e in present if not _is_audit_metal(e)]
    cutoff = 2.3
    for a in lights:
        for b in lights:
            cutoff = max(cutoff, covalent_radius(a) + covalent_radius(b)
                         + _TOL_ORGANIC)
    for m in metals:
        for x in lights:
            cutoff = max(cutoff, _mx_window(m, x)[1])
    return min(cutoff + 0.05, 4.0)


def _model_state(model: _Model, n_refinements: int) -> dict[str, Any]:
    """Whether the ADPs mean anything yet.

    The session records refinements in refinement_history; an externally
    imported model can also arrive already anisotropic. Either counts. A
    model whose non-H Ueq are all the same number never went through least
    squares whatever the history says (interpret_peaks builds every site
    with u = 0.05), so that is checked too.
    """
    idx = [i for i in range(len(model.labels)) if model.elems[i] != "H"]
    n_aniso = sum(1 for i in idx if model.aniso[i])
    us = [model.ueq[i] for i in idx]
    spread = (max(us) - min(us)) if us else 0.0
    flat = len(us) > 1 and spread < 1e-6
    refined = (n_aniso > 0 or n_refinements > 0) and not flat
    if flat:
        reason = (f"every non-H atom carries the same Ueq "
                  f"({us[0]:.4f} A^2): the displacement parameters have not "
                  "been refined, so they carry no element information yet")
    elif refined:
        reason = (f"{n_aniso} anisotropic non-H atom(s), "
                  f"{n_refinements} refinement(s) on record")
    else:
        reason = ("the model is isotropic and no refinement is on record - "
                  "Ueq only carries element information once it has been "
                  "refined against the data")
    return {"refined": refined, "n_anisotropic": n_aniso,
            "n_refinements": int(n_refinements),
            "n_non_h": len(idx), "ueq_spread": round(spread, 5),
            "reason": reason}


def _neighbour_rec(model: _Model, j: int, d: float) -> dict[str, Any]:
    return {"label": model.labels[j], "element": model.elems[j],
            "d": round(d, 3), "ueq": round(model.ueq[j], 4),
            "occupancy": round(model.occ[j], 3)}


def _terminal_oxygen_slots(model: _Model, i: int) -> list[int]:
    """Positions in model.heavy[i] of neighbours that are O with no other
    non-H neighbour of their own (the O of a nitro, carboxylate,
    sulfonate, phosphonate ...). Positions, not (j, op, d) tuples, so the
    remaining slot can be picked out without comparing symmetry ops."""
    return [k for k, (j, _op, _d) in enumerate(model.heavy[i])
            if model.elems[j] == "O" and len(model.heavy[j]) <= 1]


def _planarity_sum(model: _Model, i: int,
                   nbrs: list[tuple[int, Any, float]]) -> float | None:
    """Sum of the three X-i-Y angles at a three-connected atom (360 deg =
    perfectly planar)."""
    if len(nbrs) != 3:
        return None
    pos = [model.pos(j, op) for j, op, _d in nbrs]
    c = model.cart[i]
    return float(sum(_angle(pos[a], c, pos[b])
                     for a, b in ((0, 1), (0, 2), (1, 2))))


def audit_light_atom_elements(xs, parts: dict[str, int] | None = None,
                              n_refinements: int = 0,
                              d_min: float | None = None) -> dict[str, Any]:
    """Element consistency of every non-H, non-metal atom from its ADP.

    parts: optional {label: SHELX PART} - atoms in different non-zero PARTs
    never see each other (same semantics as chem.connectivity).
    n_refinements: how many refinements the session has on record.
    d_min: the data's resolution, used only for the implied electron count.

    Returns {status, reason, model_state, rule, bands, n_atoms_checked,
    n_flagged, flags, nitro_vs_carboxylate_candidates, skipped, note}.
    status is "checked" or "not_applicable"; nothing is ever relabelled.
    """
    u_per_ln_z = _u_per_ln_z(d_min)
    bands = {"too_light_below": _UEQ_RATIO_LOW,
             "too_heavy_above": _UEQ_RATIO_HIGH,
             "min_occupancy": _MIN_OCCUPANCY,
             "min_reference_neighbours": _MIN_REFERENCE_NEIGHBOURS,
             "reference_z_factor": _REF_Z_FACTOR,
             "ueq_per_ln_z": round(u_per_ln_z, 4),
             "d_min_assumed": round(float(d_min), 3) if d_min else _D_MIN_FALLBACK}
    rule = (
        "dU = ln(Z_label/Z_true) / (8 pi^2 <s^2>): a label with too few "
        "electrons refines LOW, one with too many HIGH (at this resolution a "
        f"one-step Z error is {u_per_ln_z * 0.154:.4f} A^2 for C<->N and "
        f"{u_per_ln_z * 0.134:.4f} A^2 for N<->O - a factor of ~3 down or ~2 "
        "up on an ordinary light-atom Ueq). Ueq is compared with the median "
        "Ueq of the atom's own bonded non-H neighbours of comparable mass, "
        f"and flagged below {_UEQ_RATIO_LOW} / above {_UEQ_RATIO_HIGH} - but "
        "only when the band is cleared against EVERY one of those neighbours "
        "individually, so that terminal-atom libration (a correct "
        "carboxylate C sits at 0.6-0.77 of its own oxygens) and one "
        "disturbed neighbour cannot manufacture a flag. The response is a "
        "fixed dU, so the low side loses sensitivity on a high-Ueq "
        "(room-temperature) structure")
    out: dict[str, Any] = {
        "status": "not_applicable", "reason": "empty model", "rule": rule,
        "bands": bands, "n_atoms_checked": 0, "n_flagged": 0, "flags": [],
        "nitro_vs_carboxylate_candidates": [], "note": NOTE,
        "skipped": {}, "model_state": {},
    }
    scs = list(xs.scatterers())
    if not scs:
        return out

    model = _Model(xs, parts, _cutoff_for([_element_of(sc) for sc in scs]))
    n = len(model.labels)
    state = _model_state(model, n_refinements)
    out["model_state"] = state
    if not state["refined"]:
        out["reason"] = state["reason"]
        return out

    skipped = {"hydrogen": 0, "metal": 0, "partial_occupancy": [],
               "too_few_neighbours": 0, "no_mass_matched_reference": 0,
               "non_positive_reference": 0}
    flags: list[dict[str, Any]] = []
    motifs: list[dict[str, Any]] = []
    n_checked = 0

    for i in range(n):
        el = model.elems[i]
        if el == "H":
            skipped["hydrogen"] += 1
            continue
        if model.is_metal[i]:
            skipped["metal"] += 1
            continue
        if model.occ[i] < _MIN_OCCUPANCY:
            skipped["partial_occupancy"].append(
                f"{model.labels[i]}:{model.occ[i]:.2f}")
            continue
        nbrs = [(j, op, d) for j, op, d in model.heavy[i]
                if model.occ[j] >= _MIN_OCCUPANCY]
        if len(nbrs) < _MIN_REFERENCE_NEIGHBOURS:
            skipped["too_few_neighbours"] += 1
            continue

        z_i = _atomic_number(el) or 0
        ref_nbrs = [(j, op, d) for j, op, d in nbrs
                    if z_i and (_atomic_number(model.elems[j]) or 0)
                    and 1.0 / _REF_Z_FACTOR
                    <= (_atomic_number(model.elems[j]) / z_i) <= _REF_Z_FACTOR]
        if len(ref_nbrs) < _MIN_REFERENCE_NEIGHBOURS:
            skipped["no_mass_matched_reference"] += 1
            continue
        caps: list[str] = []
        ref_u = [model.ueq[j] for j, _o, _d in ref_nbrs]
        u_ref = float(np.median(ref_u))
        n_ref = len(ref_nbrs)
        ref_kind = f"{n_ref} mass-matched non-H neighbour(s)"
        if u_ref <= 1e-6 or min(ref_u) <= 1e-6:
            skipped["non_positive_reference"] += 1
            continue
        n_checked += 1

        u_i = model.ueq[i]
        ratio = u_i / u_ref
        # UNANIMITY. The median of two neighbours is their mean, which is
        # not a robust statistic: one disturbed neighbour drags it and
        # manufactures a flag on the atom next door (a collapsed mislabelled
        # site pulls the median of ITS neighbours down, and they then read
        # "too heavy"). So the anomaly has to hold against EVERY mass-
        # matched neighbour individually, not just their median. That also
        # neutralises the libration bias by construction: a correct
        # carboxylate C is low only against its two terminal O, never
        # against the ring carbon it hangs on, so it is never flagged.
        # u_i/u_j is largest against the SMALLEST neighbour, so that one is
        # the hardest test for "too light"; the largest neighbour is the
        # hardest test for "too heavy".
        ratio_vs_lowest = u_i / min(ref_u)      # decides too_light_label
        ratio_vs_highest = u_i / max(ref_u)     # decides too_heavy_label
        n_metal_nbrs = len(model.metals[i]) + len(model.far_metals[i])
        heavy_i = model.heavy[i]
        o_slots = _terminal_oxygen_slots(model, i)
        planar_sum = _planarity_sum(model, i, heavy_i)
        motif = None
        if (len(heavy_i) == 3 and len(o_slots) == 2
                and planar_sum is not None
                and planar_sum >= _PLANAR_SUM_DEG):
            rest = [k for k in range(3) if k not in o_slots]
            motif = {"third": heavy_i[rest[0]] if rest else None,
                     "terminal_o": [heavy_i[k] for k in o_slots],
                     "planar_sum": planar_sum}

        if n_metal_nbrs:
            # metal_bonded_light_atom is the primary check there, and the
            # metal's own ADP pulls on this one
            caps.append("medium")

        # implied electron count: invert the dU equation with the neighbour
        # median standing in for the Ueq the site would carry if its label
        # were right. Biased by exactly the libration the bands allow for,
        # so it is reported as an estimate, never used to decide anything.
        z_implied = (z_i * math.exp(max(-3.0, min(3.0, (u_ref - u_i)
                                                  / u_per_ln_z)))
                     if z_i else None)

        kind = None
        if ratio_vs_lowest < _UEQ_RATIO_LOW:
            kind, direction = "too_light_label", +1
            margin = _UEQ_RATIO_LOW / max(ratio_vs_lowest, 1e-6)
        elif ratio_vs_highest > _UEQ_RATIO_HIGH:
            kind, direction = "too_heavy_label", -1
            margin = ratio_vs_highest / _UEQ_RATIO_HIGH
        if kind is None:
            if motif:
                motifs.append(_motif_record(model, i, motif, ratio, u_i,
                                            u_ref, None))
            continue

        alt = one_step_in_z(el, direction)
        alt_note = alt
        if motif and alt:
            third_el = (model.elems[motif["third"][0]]
                        if motif["third"] else None)
            if kind == "too_light_label" and el == "C" and alt == "N":
                alt_note = ("N (nitro / nitrate-type X(O)2)" if third_el == "C"
                            else "N (X(O)2 with a non-carbon third neighbour)")
            elif kind == "too_heavy_label" and el == "N" and alt == "C":
                alt_note = ("C (carboxylate / carboxylic acid)"
                            if third_el == "C" else "C")
        weakest = (ratio_vs_lowest if kind == "too_light_label"
                   else ratio_vs_highest)
        reason = (
            f"Ueq {u_i:.4f} A^2 is {ratio:.2f}x the median Ueq of "
            f"{ref_kind} ({u_ref:.4f} A^2), and {weakest:.2f}x against the "
            "least favourable of them individually"
            + (f", below the {_UEQ_RATIO_LOW} band: the site holds MORE "
               "electrons than the label supplies, so least squares shrank "
               "U to put more density there"
               if kind == "too_light_label" else
               f", above the {_UEQ_RATIO_HIGH} band: the label supplies MORE "
               "electrons than the site holds, so least squares inflated U "
               "to take density away")
            + (f"; implied electron count ~{z_implied:.1f} e vs {z_i} for "
               f"{el}" if z_implied else ""))
        advice = (
            (f"consider {alt_note} - one step in Z, the direction the ADP "
             f"points" if alt else
             f"no chemically sensible one-step neighbour of {el} in Z; the "
             "anomaly may be disorder, an unmodelled partial site or an "
             "absorption/scale problem rather than a wrong element")
            + ". Cross-check the chemistry (connectivity, H count, the "
            "composition's remaining allowance) and the omit-map electrons "
            "(integrate_difference_density) before retyping; then "
            "edit_atoms reassign, re-refine and confirm the Ueq settles")
        if n_metal_nbrs:
            advice += ("; this atom is also bonded to a metal - "
                       "metal_bonded_light_atom is the primary check there")
        rec = {
            "label": model.labels[i], "element": el, "kind": kind,
            "ueq": round(u_i, 4), "neighbour_median_ueq": round(u_ref, 4),
            "ratio": round(ratio, 2),
            "reference": ref_kind,
            "ratio_vs_weakest_neighbour": round(weakest, 2),
            "neighbours": [_neighbour_rec(model, j, d)
                           for j, _op, d in model.heavy[i]],
            "n_reference_neighbours": n_ref,
            "n_metal_neighbours": n_metal_nbrs,
            "anisotropic": bool(model.aniso[i]),
            "suggested_element": alt,
            "suggested_element_note": alt_note,
            "implied_electron_count": (round(z_implied, 1)
                                       if z_implied else None),
            "confidence": _confidence(margin, caps),
            "reason": reason, "advice": advice,
            "motif": ("planar X(O)2 with a "
                      f"{model.elems[motif['third'][0]] if motif['third'] else '?'}"
                      " third neighbour" if motif else None),
        }
        flags.append(rec)
        if motif:
            motifs.append(_motif_record(model, i, motif, ratio, u_i, u_ref,
                                        rec))

    flags.sort(key=lambda r: abs(math.log(max(r["ratio"], 1e-6))), reverse=True)
    out.update({
        "status": "checked",
        "reason": state["reason"],
        "n_atoms_checked": n_checked,
        "n_flagged": len(flags),
        "flags": flags[:_MAX_FLAGS],
        "nitro_vs_carboxylate_candidates": motifs[:_MAX_FLAGS],
        "skipped": {**skipped,
                    "partial_occupancy": skipped["partial_occupancy"][:_MAX_FLAGS],
                    "n_partial_occupancy": len(skipped["partial_occupancy"])},
    })
    return out


def _motif_record(model: _Model, i: int, motif: dict, ratio: float,
                  u_i: float, u_ref: float,
                  flag: dict | None) -> dict[str, Any]:
    """One planar X(O)2 site: nitro or carboxylate, read from Ueq.

    A planar three-coordinate atom carrying two TERMINAL oxygens is a
    carboxylate / carboxylic acid only if its third neighbour is a carbon
    AND its own Ueq is consistent with those oxygens. Below the band it has
    fewer electrons than its label - the nitro reading (N). The record
    carries the numbers; it is a hint, not a verdict.
    """
    el = model.elems[i]
    o_recs = [_neighbour_rec(model, j, d) for j, _op, d in motif["terminal_o"]]
    u_o = float(np.median([r["ueq"] for r in o_recs]))
    ratio_o = u_i / u_o if u_o > 1e-6 else None
    third = motif["third"]
    third_rec = (_neighbour_rec(model, third[0], third[2]) if third else None)
    third_el = third_rec["element"] if third_rec else None

    suspect = False
    if ratio_o is None:
        reading, conf = "no usable oxygen ADP reference", "low"
    elif el == "C" and third_el == "C":
        if ratio_o < _UEQ_RATIO_LOW:
            suspect = True
            reading = (f"labelled C but Ueq is only {ratio_o:.2f}x its two "
                       "terminal O - fewer electrons than a carbon supplies: "
                       "more likely a NITRO nitrogen (N) than a carboxylate C")
            conf = "high" if ratio_o < _UEQ_RATIO_LOW / 1.25 else "medium"
        else:
            reading = (f"labelled C with Ueq {ratio_o:.2f}x its two terminal "
                       f"O (band {_UEQ_RATIO_LOW}): consistent with a "
                       "carboxylate / carboxylic acid carbon")
            conf = "medium"
    elif el == "N":
        if ratio_o > _UEQ_RATIO_HIGH:
            suspect = True
            reading = (f"labelled N but Ueq is {ratio_o:.2f}x its two "
                       "terminal O - more electrons in the label than the "
                       "site holds: a CARBOXYLATE carbon (C) is the likelier "
                       "reading")
            conf = "medium"
        else:
            reading = (f"labelled N with Ueq {ratio_o:.2f}x its two terminal "
                       "O: consistent with a nitro / nitrate-type nitrogen")
            conf = "medium"
    else:
        reading = (f"planar {el}(O)2 with a "
                   f"{third_el or 'missing'} third neighbour - neither the "
                   "carboxylate nor the nitro reading applies to this "
                   f"element; Ueq is {ratio_o:.2f}x its terminal O")
        conf = "low"

    if suspect and flag is None:
        # the two oxygens alone say one thing and the full neighbour set
        # (which includes the third, non-terminal neighbour) says the atom is
        # normal: terminal-O libration explains it without any element error,
        # so the reading stays in the report but weak
        reading += (f"; BUT its Ueq is {ratio:.2f}x its full neighbour "
                    "median and inside the band against the third, "
                    "non-terminal neighbour - the terminal oxygens' own "
                    "libration explains this on its own, so the reading is "
                    "weak and no alert is raised")
        conf = "low"

    return {
        "label": model.labels[i], "element": el, "ueq": round(u_i, 4),
        "terminal_oxygens": o_recs,
        "terminal_o_median_ueq": round(u_o, 4),
        "ratio_over_terminal_o": (round(ratio_o, 2) if ratio_o else None),
        "third_neighbour": third_rec,
        "neighbour_median_ueq": round(u_ref, 4),
        "ratio_over_all_neighbours": round(ratio, 2),
        "planarity_angle_sum_deg": round(motif["planar_sum"], 1),
        "x_o_distances": [r["d"] for r in o_recs],
        "reading": reading, "confidence": conf, "suspect": suspect,
        "flagged_by_ueq_band": bool(flag),
        "geometry_note": _GEOMETRY_NOTE,
    }
