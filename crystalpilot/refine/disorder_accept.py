"""Acceptance loop for a PART/FVAR disorder split: is the split real?

model_disorder can always DRAW a two-site split; nothing in the platform
used to say whether the data support it. The reg1-ext2 regression is the
whole argument for this module: two organic cases whose deposited models
carry a PART split (orgdis_dbu_cod2241572 P2(1)/n, DBU ring C15/C16;
twintrap_nm_cod2229074 P-1, ethyl C15B/C16B) were delivered UNMODELLED -
one agent wrote that the ring segment "shows anharmonic motion that cannot
be reliably modelled discretely", the other built a split and abandoned it
the moment R1 rose. Neither had a number to argue with.

The number is the refined free variable and its s.u. After SHELXL has
refined FVAR k, the occupancy share k of component A is a measured
quantity with an uncertainty, and three readings are possible:

  * k is more than 2 s.u. away from both 0 and 1, and the s.u. itself is
    small        -> `supported`  (the data resolve two components)
  * k sits within 2 s.u. of 1.0 (or of 0.0)
                 -> `revoke`     (all the density went to one component;
                                  the second one is refining on nothing)
  * the s.u. is larger than SU_BAR
                 -> `inconclusive` (these data do not determine the ratio;
                                  restrain and re-refine, or say so)

Encoding principles (docs/scxrd-expert-knowledge-review.md §4)
are the same ones shelxl_lst.py follows:

* P3  every number is computed from what is in front of us. The U_eq
      reference is the model's OWN median non-H U_eq, the resolvability
      reference is the DATA's own d_min - not table constants.
* P12 one-directional. A verdict of `supported` says the null split was
      excluded at 2 s.u., never that the model is right.
* P13 the DIRECTION is reported: k -> 1 and k -> 0 are different findings
      (the split is absent vs the split is drawn inside out).
* P14 what the block cannot decide is stated in the block.

The two bars below are dimensionless and structure-independent (a fraction
and a sigma multiple), which is what keeps this usable on any crystal:
nothing here is tuned to a cell, an element or a compound class.

Strings are English to match tools_disorder / tools_shelxl; the one
mandated Chinese clause is SU_UNDERESTIMATED, appended to every verdict
that divides by an s.u. (platform convention, see shelxl_lst.py).
"""
from __future__ import annotations

import math
from typing import Any

from .shelxl_lst import SU_UNDERESTIMATED

#: Bar on the free variable's OWN s.u. Occupancy is a fraction, so this is
#: a pure number: "the A:B ratio is not pinned down to better than 10 %".
#: Above it the refinement has not measured the ratio, whatever value it
#: happens to print - and §13.7 says the printed s.u. is itself a lower
#: bound (underestimated 1.5-2x), so the bar is the generous side.
SU_BAR = 0.10
#: Sigma multiple for the null-split test. 2 s.u. is the ordinary
#: crystallographic "significantly different from" window (a value inside
#: it is not distinguishable from the null hypothesis).
NULL_SIGMA = 2.0
#: A component's U_eq this many times above (or below the reciprocal of)
#: the model's OWN median non-H U_eq is outside the range the rest of this
#: structure shows. A ratio, referenced to the structure itself.
U_EQ_FACTOR = 3.0
#: Two components count as being "at similar occupancy" while their shares
#: differ by less than this factor - a MINOR component is expected to
#: carry a larger U_eq, so the U_eq comparison is only made among shares
#: that are comparable.
SIMILAR_OCC_FACTOR = 2.0

VERDICTS = ("supported", "inconclusive", "revoke", "pending", "unknown")
#: A single-site neighbour bonded to BOTH components of a split sees two
#: bond lengths; the mismatch is absorbed by that neighbour's own thermal
#: motion while it stays below this multiple of its rms displacement
#: sqrt(U_eq). Referenced to the neighbour's own U_eq, never to a table.
SPHERE_RMS_FACTOR = 2.0
#: ...with a floor so a neighbour with a very small U_eq is not flagged
#: over a mismatch at the noise level of the coordinates
SPHERE_DELTA_FLOOR_A = 0.15


# --------------------------------------------------------------------- #
# 1. the free variable                                                   #
# --------------------------------------------------------------------- #

def occupancy_verdict(value: float | None, su: float | None,
                      index: int | None = None) -> dict[str, Any]:
    """Verdict on one refined free variable = one disorder group's A share.

    Returns {"verdict", "informative", "rule", "sigma_from_0",
    "sigma_from_1"}; `informative` is the sentence that carries the
    numbers and the direction, `rule` the criterion that produced it.

    Order matters and is deliberate: the s.u. bar is tested FIRST, so a
    ratio that is not measured at all can never be reported as a decisive
    `revoke`. With su <= SU_BAR the two null tests (2 s.u. of 0, 2 s.u. of
    1) cannot both fire, so the verdict is unambiguous.
    """
    tag = f"FVAR{index}" if index else "the free variable"
    if value is None or su is None:
        return {
            "verdict": "unknown",
            "informative": (
                f"{tag} has no refined s.u.: SHELXL prints the free-variable "
                f"esd only for a job that actually ran least-squares cycles. "
                f"Run run_shelxl(mode='adopt', l_s>=4) and read it again - "
                f"an occupancy ratio without an s.u. decides nothing."),
            "rule": "an s.u. is required before any occupancy verdict",
            "sigma_from_0": None, "sigma_from_1": None}
    v, s = float(value), float(su)
    n0 = abs(v) / s if s > 0 else math.inf
    n1 = abs(1.0 - v) / s if s > 0 else math.inf
    common = {"sigma_from_0": round(n0, 1) if math.isfinite(n0) else None,
              "sigma_from_1": round(n1, 1) if math.isfinite(n1) else None}
    if s > SU_BAR:
        return {
            "verdict": "inconclusive",
            "informative": (
                f"{tag} = {format_value_su(v, s)}: the s.u. {s:.3g} is "
                f"larger than {SU_BAR:g}, so these data do not determine the "
                f"A:B ratio to better than {SU_BAR * 100:.0f} % and the "
                f"printed value is not evidence either way. {SU_UNDERESTIMATED}"),
            "rule": (f"s.u.(free variable) > {SU_BAR:g} -> the ratio is "
                     f"undetermined (occupancy is a fraction, so the bar is "
                     f"a plain fraction and applies to any structure)"),
            **common}
    if n1 <= NULL_SIGMA:
        return {
            "verdict": "revoke",
            "informative": (
                f"{tag} = {format_value_su(v, s)} is {n1:.1f} s.u. from "
                f"1.000, i.e. inside the {NULL_SIGMA:g} s.u. window: the "
                f"refinement put essentially ALL of the density on component "
                f"A and left B with nothing. The split is not supported by "
                f"these data - B is refining on noise. {SU_UNDERESTIMATED}"),
            "rule": (f"|1 - k| <= {NULL_SIGMA:g} s.u. -> the minor component "
                     f"is not distinguishable from empty"),
            **common}
    if n0 <= NULL_SIGMA:
        return {
            "verdict": "revoke",
            "informative": (
                f"{tag} = {format_value_su(v, s)} is {n0:.1f} s.u. from "
                f"0.000, i.e. inside the {NULL_SIGMA:g} s.u. window: all of "
                f"the density went to component B and A is empty. The split "
                f"is not supported as drawn - either there is no disorder, "
                f"or the two sites are the wrong way round and B alone is "
                f"the atom. {SU_UNDERESTIMATED}"),
            "rule": (f"|k| <= {NULL_SIGMA:g} s.u. -> the major component as "
                     f"drawn is not distinguishable from empty"),
            **common}
    return {
        "verdict": "supported",
        "informative": (
            f"{tag} = {format_value_su(v, s)}: the A share sits "
            f"{n0:.1f} s.u. clear of 0.000 and {n1:.1f} s.u. clear of 1.000, "
            f"and the s.u. itself is within {SU_BAR:g}. The data resolve two "
            f"components at this ratio - this excludes the null split, it "
            f"does not by itself say the two SITES are chemically right "
            f"(check the geometry and the U_eq below). {SU_UNDERESTIMATED}"),
        "rule": (f"k more than {NULL_SIGMA:g} s.u. from both 0 and 1 with "
                 f"s.u. <= {SU_BAR:g} -> the ratio is measured and neither "
                 f"component is empty"),
        **common}


def format_value_su(value: float, su: float | None) -> str:
    """Crystallographic '0.95(10)': the value carried to as many decimals
    as the s.u. needs for two significant digits, the s.u. in parentheses
    in units of that last decimal. This is the notation the whole field
    argues in, so the verdict quotes it rather than two loose floats."""
    if su is None or su <= 0 or not math.isfinite(su):
        return f"{value:.5g}(?)"
    dec = 1 - int(math.floor(math.log10(su)))
    scaled = int(round(su * 10 ** dec))
    if scaled >= 100:                      # 0.0999 -> 100, shift one back
        dec -= 1
        scaled = int(round(su * 10 ** dec))
    dec = max(0, min(8, dec))
    return f"{value:.{dec}f}({scaled})"


DISPOSITION = {
    "supported": (
        "keep the split. Apply the cards in restraint_suggestion with "
        "set_restraints (SADI ties the two components to the same geometry, "
        "SIMU keeps their ADPs comparable) and re-refine - an unrestrained "
        "minor component drifts even when the ratio is real."),
    "inconclusive": (
        "do not deliver this ratio. Apply restraint_suggestion with "
        "set_restraints and run_shelxl(mode='adopt', l_s>=8) again; if the "
        "s.u. does not come down, these data cannot carry a discrete split - "
        "undo it (model_disorder undo=...) and DISCLOSE the residual density "
        "as unmodelled disorder instead of shipping an undetermined ratio."),
    "revoke": (
        "remove the split: model_disorder(undo=<group>) merges the "
        "components back to one site at the occupancy-weighted position and "
        "drops the FVAR and the PART cards, so the abandoned trial leaves no "
        "debris. Then re-refine and re-read the difference map - if density "
        "is still there, the second site is in the wrong place, not absent."),
    "pending": (
        "the split is drawn but not yet refined: the in-process refine "
        "holds occupancies fixed. Apply restraint_suggestion (set_restraints) "
        "and run run_shelxl(mode='adopt') on THIS branch now - nothing in "
        "this block is a verdict yet, and a separation or ADP caution above "
        "is a note for reading the s.u., not a reason to leave the split "
        "unrefined. The verdict is read from FVAR's s.u. afterwards."),
    "unknown": (
        "no refined s.u. for this group yet - run_shelxl(mode='adopt', "
        "l_s>=4), then read free_variable again."),
}


# --------------------------------------------------------------------- #
# 2. supporting evidence computed from the model itself                  #
# --------------------------------------------------------------------- #

def _u_eq(xs, sc) -> float:
    from cctbx import adptbx
    if sc.flags.use_u_aniso():
        return float(adptbx.u_star_as_u_iso(xs.unit_cell(), sc.u_star))
    return float(sc.u_iso)


def data_d_min(ses) -> float | None:
    """Resolution of the reflections actually in use - the reference the
    resolvability reading is measured against (never a constant)."""
    for attr in ("fo_sq", "f_obs"):
        arr = getattr(ses, attr, None)
        if arr is None:
            continue
        try:
            return float(arr.d_min())
        except Exception:  # noqa: BLE001 - advisory number only
            continue
    return None


def _median(vals: list[float]) -> float | None:
    if not vals:
        return None
    s = sorted(vals)
    n = len(s)
    return s[n // 2] if n % 2 else 0.5 * (s[n // 2 - 1] + s[n // 2])


def adp_reading(comps: list[dict[str, Any]],
                model_median: float | None) -> dict[str, Any]:
    """Per-component U_eq against the model's own median non-H U_eq.

    Two readings, both one-directional:
      * a component far outside the structure's own U_eq range is soaking
        up density it should not have (or has been placed on nothing);
      * two components at COMPARABLE occupancy with very different U_eq
        are not two halves of the same atom - a minor component is
        expected to be looser, a major one is not.
    """
    out: dict[str, Any] = {
        "u_eq": {c["label"]: round(c["u_eq"], 4) for c in comps},
        "model_median_u_eq": (round(model_median, 4)
                              if model_median is not None else None),
        "rule": (f"a component U_eq more than {U_EQ_FACTOR:g}x the model's "
                 f"OWN median non-H U_eq (or below 1/{U_EQ_FACTOR:g} of it) "
                 f"is outside the range the rest of this structure shows; "
                 f"the A/B comparison is only made while the two shares "
                 f"differ by less than {SIMILAR_OCC_FACTOR:g}x, because a "
                 f"minor component is legitimately looser"),
    }
    readings: list[str] = []
    if model_median and model_median > 0:
        for c in comps:
            r = c["u_eq"] / model_median
            if r > U_EQ_FACTOR:
                readings.append(
                    f"{c['label']} U_eq {c['u_eq']:.3f} is {r:.1f}x the "
                    f"model's median {model_median:.3f} - it is absorbing "
                    f"density rather than modelling an atom")
            elif r < 1.0 / U_EQ_FACTOR:
                readings.append(
                    f"{c['label']} U_eq {c['u_eq']:.3f} is {1 / r:.1f}x "
                    f"BELOW the model's median {model_median:.3f} - an "
                    f"over-occupied site or an element too light here")
    pairs = [(a, b) for a in comps for b in comps
             if a["part_sign"] > 0 and b["part_sign"] < 0
             and a.get("pair") is not None and a.get("pair") == b.get("pair")]
    for a, b in pairs:
        oa, ob = a.get("occupancy") or 0.0, b.get("occupancy") or 0.0
        if not (oa > 0 and ob > 0):
            continue
        if max(oa, ob) / min(oa, ob) > SIMILAR_OCC_FACTOR:
            continue
        ua, ub = a["u_eq"], b["u_eq"]
        if min(ua, ub) <= 0:
            continue
        ratio = max(ua, ub) / min(ua, ub)
        if ratio > U_EQ_FACTOR:
            hi = a if ua > ub else b
            lo = b if ua > ub else a
            readings.append(
                f"{a['label']}/{b['label']} carry nearly the same share "
                f"({oa:.2f} vs {ob:.2f}) but U_eq {ua:.3f} vs {ub:.3f} "
                f"({ratio:.1f}x): {hi['label']} is far looser than "
                f"{lo['label']}, which is not what one atom in two "
                f"orientations looks like")
    if readings:
        out["reading"] = "; ".join(readings)
    return out


def separation_reading(d_ab: float | None, pair: list[str] | None,
                       d_min_data: float | None) -> dict[str, Any]:
    """Shortest inter-component distance against the data's own resolution.

    Two alternative sites closer than d_min are inside one resolution
    element: the data cannot separate them, so whatever ratio comes out is
    a partition of a single blob. d_min is read from the reflections in
    use, never assumed.
    """
    out: dict[str, Any] = {
        "closest_pair": pair, "d_A": (round(d_ab, 3)
                                      if d_ab is not None else None),
        "d_min_data_A": (round(d_min_data, 3)
                         if d_min_data is not None else None),
        "rule": ("two alternative sites closer than the resolution d_min of "
                 "the data in use are inside one resolution element and are "
                 "not independently resolvable, whatever the refinement "
                 "prints for their ratio"),
    }
    if d_ab is None:
        return out
    if d_min_data:
        out["resolvable"] = bool(d_ab >= d_min_data)
        if d_ab < d_min_data:
            out["reading"] = (
                f"the components come as close as {d_ab:.2f} A "
                f"({' - '.join(pair or [])}), BELOW the data's own d_min "
                f"{d_min_data:.2f} A: the two sites are not resolved by "
                f"these reflections, so the refined ratio is a partition of "
                f"one density blob and the s.u. verdict cannot be trusted "
                f"on its own. This does NOT forbid the split: refine it "
                f"with the suggested SADI/SIMU cards and read the s.u.; if "
                f"the second site was drawn along the ADP axis rather than "
                f"taken from a difference peak, put it on the peak first "
                f"(model_disorder does that by itself when the last map has "
                f"one)")
    return out


def delta_r1_reading(r1_before: float | None, r1_after: float | None,
                     n_added: int | None = None) -> dict[str, Any]:
    """R1 across the split, with the caveat that makes it usable.

    A split ADDS parameters, so R1 is expected to fall a little for that
    reason alone - a small drop is not evidence. A RISE is evidence: the
    refinement went somewhere worse with more freedom, which usually means
    the second site is in the wrong place. The reg1-ext2 twintrap agent
    abandoned a correct trial on a rise it never diagnosed.
    """
    out: dict[str, Any] = {
        "r1_before_split": (round(r1_before, 4)
                            if r1_before is not None else None),
        "r1_now": round(r1_after, 4) if r1_after is not None else None,
        "rule": ("a split adds parameters, so a small R1 drop is expected "
                 "and is NOT evidence for the split; the occupancy s.u. is "
                 "the test. An R1 RISE is evidence against the split as "
                 "placed"),
    }
    if r1_before is None or r1_after is None:
        out["reading"] = ("no pre-split R1 recorded for this group, so "
                          "delta R1 cannot be computed - judge on the "
                          "occupancy s.u. and the geometry")
        return out
    d = r1_after - r1_before
    out["delta_r1"] = round(d, 4)
    if n_added:
        out["n_atoms_added"] = int(n_added)
    if d > 0:
        out["reading"] = (
            f"R1 ROSE {d:+.4f} ({r1_before:.4f} -> {r1_after:.4f}) although "
            f"the split added parameters - the second site is making the fit "
            f"worse, not better; check its position against the difference "
            f"map before keeping it")
    else:
        out["reading"] = (
            f"R1 fell {d:+.4f} ({r1_before:.4f} -> {r1_after:.4f}); a drop "
            f"of this size is what added parameters buy anyway, so read the "
            f"occupancy s.u., not this number")
    return out


# --------------------------------------------------------------------- #
# 3. restraint suggestion (generic, never applied silently)              #
# --------------------------------------------------------------------- #

#: refine/restraints.py refuses a SADI pair longer than this (beyond it a
#: "bond" is almost always a symmetry contact this version cannot
#: restrain), so a suggestion must not offer one.
_SADI_MAX_A = 3.5


def _nearest_image_distance(uc, s1, s2) -> float:
    """Distance from s1 to the lattice image of s2 nearest to it."""
    s2 = tuple(float(s2[j]) - round(float(s2[j]) - float(s1[j]))
               for j in range(3))
    return float(uc.distance(tuple(float(x) for x in s1), s2))


def sphere_reading(xs, group: dict[str, Any],
                   pairs: list[tuple[str, str]] | None = None,
                   neighbor_table=None,
                   split_labels: set[str] | None = None,
                   peaks: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Do the single-site neighbours of a split see the same atom in both
    orientations?

    A neighbour N bonded to component A at d_A and to component B at d_B is
    ONE atom bonded to two alternative positions of another. While
    |d_A - d_B| is within N's own rms displacement the sphere is
    consistent - a puckered ring atom sits at nearly the same distance
    from both ring neighbours in either position. When it is not, the
    model is inconsistent with itself: either N is disordered too (split
    and restrain it), or the second position is not an atom (a ghost next
    to a metal, a component drawn along the bonds). reg2-mof cage
    (2026-09-04): Zr3/Zr7 0.78 A apart, six single-site donors, kept on a
    `supported` occupancy s.u. - this reading is the one that was missing.
    Referenced to each neighbour's OWN U_eq, so it applies to any element.
    H atoms are never counted: at X-ray resolution they are placed from
    their carriers (riding), so an H bonded to one component is not an
    independent observation of the sphere - reg5-dbu (2026-09-04) flagged
    the split's own riding H as "2 of 5 neighbours inconsistent" while
    every heavy neighbour fitted, and the agent read that as "the second
    position is not an atom". An inconsistent heavy neighbour is looked
    up in `peaks` (the last refine's difference map): its own residual
    peak means it moves with the components and should be split with
    them, and the reading says so by label.
    """
    scs = list(xs.scatterers())
    idx = {sc.label.upper(): i for i, sc in enumerate(scs)}
    uc = xs.unit_cell()
    members = group.get("members") or []
    a_labels = [str(m["label"]) for m in members if int(m.get("sign", 1)) > 0]
    b_labels = [str(m["label"]) for m in members if int(m.get("sign", 1)) < 0]
    in_group = {lb.upper() for lb in a_labels + b_labels}
    split_all = {lb.upper() for lb in (split_labels or ())} | in_group
    if pairs is None:
        pairs = _component_pairs(xs, a_labels, b_labels)
    if neighbor_table is None:
        from .inspect import _neighbor_table
        from .nodes import part_kwargs_from_parts
        part_of = {str(m.get("label", "")).upper(): int(m.get("part") or 0)
                   for m in members}
        neighbor_table = _neighbor_table(
            xs, part_kwargs_from_parts(
                [part_of.get(sc.label.upper(), 0) for sc in scs]))
    out: dict[str, Any] = {
        "rule": (f"a single-site neighbour bonded to both components sees "
                 f"two bond lengths; the difference is absorbed by its own "
                 f"displacement while it is below {SPHERE_RMS_FACTOR:g}x "
                 f"sqrt(U_eq) of that neighbour (floor "
                 f"{SPHERE_DELTA_FLOOR_A:g} A). Beyond that the neighbour "
                 f"would have to be disordered too, or the second "
                 f"component is not an atom"),
        "pairs": [],
    }
    n_single = 0
    n_bad = 0
    worst: tuple[float, str, str, str] | None = None
    for a, b in pairs:
        ia, ib = idx.get(a.upper()), idx.get(b.upper())
        if ia is None or ib is None:
            continue
        nbr_labels: dict[str, float] = {}
        for comp_i in (ia, ib):
            for n in neighbor_table[comp_i]:
                if n["sym"] or n["label"].upper() in in_group:
                    continue
                nbr_labels.setdefault(n["label"], 0.0)
        single: list[dict[str, Any]] = []
        split_nbrs: list[str] = []
        for lb in nbr_labels:
            j = idx.get(lb.upper())
            if j is None:
                continue
            if scs[j].scattering_type.strip().upper() == "H":
                continue                      # placed from its carrier
            if lb.upper() in split_all:
                split_nbrs.append(lb)
                continue
            d_a = _nearest_image_distance(uc, scs[j].site, scs[ia].site)
            d_b = _nearest_image_distance(uc, scs[j].site, scs[ib].site)
            delta = abs(d_a - d_b)
            u_rms = math.sqrt(max(_u_eq(xs, scs[j]), 0.0))
            bar = max(SPHERE_RMS_FACTOR * u_rms, SPHERE_DELTA_FLOOR_A)
            absorbed = delta <= bar
            single.append({"label": lb, "d_a": round(d_a, 3),
                           "d_b": round(d_b, 3), "delta": round(delta, 3),
                           "u_rms": round(u_rms, 3), "bar": round(bar, 3),
                           "absorbed": absorbed})
            n_single += 1
            if not absorbed:
                n_bad += 1
                if worst is None or delta > worst[0]:
                    worst = (delta, lb, a, b)
        out["pairs"].append({
            "a": a, "b": b,
            "d_ab": round(_nearest_image_distance(
                uc, scs[ia].site, scs[ib].site), 3),
            "single_site_neighbours": single,
            "split_neighbours": split_nbrs})
    out["n_single_site_neighbours"] = n_single
    out["n_inconsistent"] = n_bad
    if n_single == 0:
        out["consistent"] = None
        out["reading"] = ("no single-site neighbour is bonded to the "
                          "components (the whole sphere is split, or the "
                          "atom is isolated): nothing to check here")
        return out
    out["consistent"] = n_bad == 0
    if n_bad:
        delta, lb, a, b = worst
        # does the flagged neighbour have its own residual? then it moves
        # with the components and belongs in the split
        bad_labels = [n["label"] for pr in out["pairs"]
                      for n in pr["single_site_neighbours"]
                      if not n["absorbed"]]
        with_peak: list[str] = []
        if peaks:
            from .tools_disorder import _peak_second_site
            sg = xs.space_group()
            for nb in bad_labels:
                j = idx.get(nb.upper())
                if j is None:
                    continue
                pk = _peak_second_site(uc, sg, tuple(scs[j].site), peaks)
                if pk is not None:
                    with_peak.append(f"{nb} ({pk['height']:.2f} e/A^3 at "
                                     f"{pk['d']:.2f} A)")
        out["neighbours_with_own_peak"] = with_peak
        out["reading"] = (
            f"{n_bad} of {n_single} single-site non-H neighbour(s) cannot "
            f"be bonded to both components: {lb} is {delta:.2f} A closer "
            f"to one of {a}/{b} than to the other, beyond what its own "
            f"displacement absorbs. "
            + (f"The difference map has a residual next to {', '.join(with_peak)}"
               f" - that neighbour moves with the components: split it with "
               f"them (model_disorder atoms=[{a}, {', '.join(x.split(' ')[0] for x in with_peak)}]) "
               f"and refine. "
               if with_peak else
               f"No residual peak of its own next to {', '.join(bad_labels)} "
               f"in the last map: either the sphere follows the split only "
               f"after refinement (refine first, re-read), or the second "
               f"position is not an atom. ")
            + "A `supported` occupancy s.u. does not settle this")
    else:
        out["reading"] = (
            f"all {n_single} single-site non-H neighbour(s) sit at nearly "
            f"the same distance from both components: the sphere is "
            f"consistent with one atom in two positions")
    return out


def _direct_distance(xs, a: str, b: str) -> float:
    uc = xs.unit_cell()
    scs = {sc.label.upper(): sc for sc in xs.scatterers()}
    sa, sb = scs.get(a.upper()), scs.get(b.upper())
    if sa is None or sb is None:
        return math.inf
    return float(uc.distance(tuple(sa.site), tuple(sb.site)))


def restraint_suggestion(xs, group: dict[str, Any],
                         neighbor_table=None) -> dict[str, Any]:
    """The SAME/SIMU/DELU obligations of a two-component split, expressed
    as cards this platform can actually apply.

    SHELX SAME says "these two fragments have the same geometry"; the
    restraint set_restraints offers is SADI, which is what SAME expands
    to - one similar-distance restraint per corresponding pair. Built
    generically from the connectivity of the model in hand:

      * intra-fragment: every bonded A_i-A_j pair inside the group is
        tied to the matching B_i-B_j pair;
      * shared pivot: every bonded neighbour that is NOT part of the group
        (the ordered atom both orientations hang off) gives A_i-X tied to
        B_i-X.

    SIMU (ADP similarity) covers every component atom. DELU is a rigid-
    bond restraint on ANISOTROPIC ADPs, so it is offered as the next step
    rather than now - model_disorder puts the components isotropic.
    """
    from .restraints import DEFAULT_SIGMA
    scs = list(xs.scatterers())
    idx = {sc.label.upper(): i for i, sc in enumerate(scs)}
    members = group.get("members") or []
    a_labels = [str(m["label"]) for m in members if int(m.get("sign", 1)) > 0]
    b_labels = [str(m["label"]) for m in members if int(m.get("sign", 1)) < 0]
    in_group = {lb.upper() for lb in a_labels + b_labels}
    pairs = _component_pairs(xs, a_labels, b_labels)
    if neighbor_table is None:
        from .inspect import _neighbor_table
        from .nodes import part_kwargs_from_parts
        part_of = {str(m.get("label", "")).upper(): int(m.get("part") or 0)
                   for m in members}
        neighbor_table = _neighbor_table(
            xs, part_kwargs_from_parts(
                [part_of.get(sc.label.upper(), 0) for sc in scs]))
    of_a = {a: b for a, b in pairs}
    sadi: list[list[str]] = []
    nbrs: dict[str, set[str]] = {}
    # 1-2: every bonded neighbour of an A component. A neighbour inside the
    # group gives the intra-fragment pair; one outside is the shared pivot
    # the two orientations hang off.
    for a, b in pairs:
        i = idx.get(a.upper())
        if i is None:
            continue
        nbrs[a] = {n["label"] for n in neighbor_table[i] if not n["sym"]}
        for n in neighbor_table[i]:
            if n["sym"]:
                continue
            other = n["label"]
            if other.upper() in in_group:
                if other in of_a and other > a:      # each pair once
                    sadi.append([a, other])
                    sadi.append([b, of_a[other]])
            else:
                sadi.append([a, other])
                sadi.append([b, other])
    # 1-3: two components sharing a bonded neighbour (the F...F distances
    # of a CF3 rotor, the C...C of a split ring). SHELX SAME restrains
    # 1-2 AND 1-3 distances; without the 1-3 terms the two orientations
    # can keep the same bond lengths and still be differently splayed.
    for n, (a, b) in enumerate(pairs):
        for a2, b2 in pairs[n + 1:]:
            if a2 in nbrs.get(a, ()) or not (nbrs.get(a) & nbrs.get(a2, set())):
                continue
            if _direct_distance(xs, a, a2) > _SADI_MAX_A:
                continue
            sadi.append([a, a2])
            sadi.append([b, b2])
    # ONE card per corresponding pair-of-pairs. A SADI card restrains
    # every pair listed on it to the SAME distance, so putting a C1-C2
    # bond and a C2-C3 bond on one card would restrain those two bonds
    # equal to each other - which SAME never says. This is exactly the
    # expansion SHELX SAME performs.
    seen: set[tuple[tuple[str, str], tuple[str, str]]] = set()
    specs: list[dict[str, Any]] = []
    for k in range(0, len(sadi) - 1, 2):
        pa, pb = sadi[k], sadi[k + 1]
        key = (tuple(sorted(pa)), tuple(sorted(pb)))
        if key in seen or key[0] == key[1]:
            continue
        seen.add(key)
        specs.append({"kind": "SADI", "sigma": DEFAULT_SIGMA["SADI"],
                      "atoms": [pa, pb]})
    comp_atoms = a_labels + b_labels
    if comp_atoms:
        specs.append({"kind": "SIMU", "sigma": DEFAULT_SIGMA["SIMU"],
                      "atoms": comp_atoms})
    # DELU is a rigid-bond restraint on the ANISOTROPIC ADP components, so
    # it is only offered once the components actually carry one
    aniso = [lb for lb in comp_atoms
             if (i := idx.get(lb.upper())) is not None
             and scs[i].flags.use_u_aniso()]
    if len(aniso) >= 2:
        specs.append({"kind": "DELU", "sigma": DEFAULT_SIGMA["DELU"],
                      "atoms": aniso})
    from .restraints import emit_shelx_cards, normalize_spec
    specs = [normalize_spec(s) for s in specs]
    cards = emit_shelx_cards(specs)
    return {
        "restraints": specs,
        "cards": cards,
        "apply_with": {"tool": "set_restraints",
                       "params": {"action": "add", "restraints": specs}},
        "note": (
            "NOT applied - a restraint is a declaration of prior knowledge "
            "and stays the agent's decision. SADI here is the platform's "
            "form of SHELX SAME (same geometry for both orientations): "
            "corresponding A and B distances are restrained equal, built "
            "from this model's own connectivity, so it transfers to any "
            "fragment. SIMU keeps the two components' ADPs comparable. "
            "DELU (rigid bond) is listed only for components that are "
            "already ANISOTROPIC - model_disorder leaves a fresh split "
            "isotropic, so re-read this suggestion after the components go "
            "aniso. EADP (an equality CONSTRAINT, not a restraint) is not "
            "available in this platform - SIMU is a similarity restraint "
            "and does not replace it."),
    }


def _component_pairs(xs, a_labels: list[str],
                     b_labels: list[str]) -> list[tuple[str, str]]:
    """Match each A component with its own B component by proximity.

    A group's member list carries no explicit pairing (SHELXL rebuilds it
    from sof codes in arbitrary order), and the geometric answer is the
    right one anyway: the B site of an atom is the alternative position of
    THAT atom, i.e. the nearest B. Greedy on distance so a multi-atom
    fragment cannot cross-assign.
    """
    uc = xs.unit_cell()
    scs = {sc.label.upper(): sc for sc in xs.scatterers()}
    cands = []
    for a in a_labels:
        sa = scs.get(a.upper())
        if sa is None:
            continue
        for b in b_labels:
            sb = scs.get(b.upper())
            if sb is None:
                continue
            cands.append((uc.distance(tuple(sa.site), tuple(sb.site)), a, b))
    cands.sort()
    used_a: set[str] = set()
    used_b: set[str] = set()
    out: list[tuple[str, str]] = []
    for _d, a, b in cands:
        if a in used_a or b in used_b:
            continue
        used_a.add(a)
        used_b.add(b)
        out.append((a, b))
    return out


# --------------------------------------------------------------------- #
# 4. the whole acceptance block for one group                            #
# --------------------------------------------------------------------- #

def group_acceptance(xs, group: dict[str, Any], *,
                     free_var: dict[str, Any] | None = None,
                     d_min_data: float | None = None,
                     r1_now: float | None = None,
                     origin: dict[str, Any] | None = None,
                     neighbor_table=None,
                     with_restraints: bool = True,
                     split_labels: set[str] | None = None,
                     peaks: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Everything an agent needs to keep, restrain or revoke one split.

    `free_var` is {"value", "su"} as SHELXL refined it (None before any
    SHELXL job -> verdict `pending`). Every other number is computed from
    `xs` and the data in hand. `split_labels` names the members of EVERY
    disorder group in the model, so a neighbour that is itself split (in
    another group) is not mistaken for a single-site one.
    """
    k = group.get("fvar_index")
    members = group.get("members") or []
    scs = {sc.label.upper(): sc for sc in xs.scatterers()}
    a_labels = [str(m["label"]) for m in members if int(m.get("sign", 1)) > 0]
    b_labels = [str(m["label"]) for m in members if int(m.get("sign", 1)) < 0]
    pairs = _component_pairs(xs, a_labels, b_labels)
    pair_of = {}
    for n, (a, b) in enumerate(pairs):
        pair_of[a.upper()] = n
        pair_of[b.upper()] = n
    comps = []
    for m in members:
        sc = scs.get(str(m["label"]).upper())
        if sc is None:
            continue
        comps.append({"label": sc.label, "u_eq": _u_eq(xs, sc),
                      "occupancy": float(sc.occupancy),
                      "sof": float(sc.weight()),
                      "part": m.get("part"),
                      "part_sign": int(m.get("sign", 1)),
                      "pair": pair_of.get(sc.label.upper())})
    in_group = {c["label"].upper() for c in comps}
    others = [_u_eq(xs, sc) for sc in xs.scatterers()
              if sc.scattering_type.strip().upper() != "H"
              and sc.label.upper() not in in_group]

    if free_var is None:
        verdict_block = {
            "verdict": "pending",
            "informative": (
                f"FVAR{k} has not been refined yet: model_disorder writes "
                f"the split and the linkage, and the in-process refine holds "
                f"occupancies fixed. Only run_shelxl(mode='adopt') refines "
                f"the ratio, and only its s.u. can say whether the split is "
                f"real."),
            "rule": "no refined value yet - nothing is decided",
            "sigma_from_0": None, "sigma_from_1": None}
        fv: dict[str, Any] = {"index": k, "value": group.get("value"),
                              "su": None}
    else:
        verdict_block = occupancy_verdict(free_var.get("value"),
                                          free_var.get("su"), k)
        fv = {"index": k, "value": (round(float(free_var["value"]), 5)
                                    if free_var.get("value") is not None
                                    else None),
              "su": (round(float(free_var["su"]), 5)
                     if free_var.get("su") is not None else None)}
    fv.update({key: verdict_block[key] for key in
               ("informative", "verdict", "rule", "sigma_from_0",
                "sigma_from_1")})

    d_ab, closest = _closest_cross_pair(xs, a_labels, b_labels)
    try:
        sphere = sphere_reading(xs, group, pairs, neighbor_table,
                                split_labels, peaks)
    except Exception as e:  # noqa: BLE001 - advisory reading only
        sphere = {"error": f"sphere reading unavailable: {e}"}
    verdict = verdict_block["verdict"]
    demoted = None
    if verdict == "supported" and sphere.get("consistent") is False:
        # P12: `supported` only says the null split is excluded at 2 s.u.;
        # a sphere that cannot hold both components contradicts the model
        # itself, and the statistical verdict must not outrank the
        # geometry (reg2-mof cage Zr3/Zr7, 2026-09-04)
        demoted = verdict
        verdict = "inconclusive"
    out: dict[str, Any] = {
        "fvar_index": k,
        "components": {"A": a_labels, "B": b_labels},
        "component_pairs": [list(p) for p in pairs],
        "free_variable": fv,
        "verdict": verdict,
        "disposition": (DISPOSITION[verdict] if demoted is None else (
            f"the occupancy s.u. alone would say `{demoted}`, but the "
            f"coordination sphere does not hold both components (see "
            f"sphere.reading). Decide the geometry first: split and "
            f"restrain the neighbours that must move with the components "
            f"(model_disorder on them, SADI/SIMU), or treat the second "
            f"position as not an atom (probe_site / ghost_test, then "
            f"model_disorder undo=...). Do not deliver the split as it "
            f"stands.")),
        "occupancy": {c["label"]: round(c["occupancy"], 4) for c in comps},
        "adp": adp_reading(comps, _median(others)),
        "separation": separation_reading(d_ab, closest, d_min_data),
        "sphere": sphere,
        "delta_r1": delta_r1_reading(
            (origin or {}).get("r1_before"), r1_now,
            len((origin or {}).get("created") or []) or None),
        "undo": (f"model_disorder(undo='fvar{k}')" if k else None),
        "limits": (
            "this block decides whether the DATA support two components at "
            "the refined ratio, and whether the single-site neighbours can "
            "be bonded to both (sphere). It cannot decide whether the two "
            "sites are the chemically right ones - read the geometry "
            "(get_geometry / inspect_model) as well."),
    }
    if demoted is not None:
        out["verdict_demoted_from"] = demoted
    if with_restraints:
        out["restraint_suggestion"] = restraint_suggestion(
            xs, group, neighbor_table)
    return out


def _closest_cross_pair(xs, a_labels: list[str],
                        b_labels: list[str]
                        ) -> tuple[float | None, list[str] | None]:
    """Shortest A-to-B distance in the group (nearest symmetry image)."""
    uc = xs.unit_cell()
    sg = xs.space_group()
    scs = {sc.label.upper(): sc for sc in xs.scatterers()}
    best: tuple[float, list[str]] | None = None
    for a in a_labels:
        sa = scs.get(a.upper())
        if sa is None:
            continue
        ref = tuple(float(x) for x in sa.site)
        for b in b_labels:
            sb = scs.get(b.upper())
            if sb is None:
                continue
            site = tuple(float(x) for x in sb.site)
            for i_op in range(sg.order_z()):
                img = sg(i_op) * site
                img = tuple(img[j] - round(img[j] - ref[j]) for j in range(3))
                d = float(uc.distance(ref, img))
                if best is None or d < best[0]:
                    best = (d, [a, b])
    return (best[0], best[1]) if best else (None, None)
