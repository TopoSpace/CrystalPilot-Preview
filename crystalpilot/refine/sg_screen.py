"""Small-molecule space-group screening from scaled intensity data.

dials.symmetry is MX-oriented: its space-group recommendation only ranks
SOHNCKE (chiral) groups, so glide planes and inversion centres are never
proposed - a P2(1)/c crystal comes back "P 21", Pnma comes back
"P 21 21 21" (both observed live: round-5 o-nitroaniline, round-6 RODIN
W(CO)6). For small-molecule work the group must be picked from the FULL
Laue class. This module scores every space group compatible with the
cell + Laue class by its systematic-absence classes against the unmerged
exported intensities, and adds centric/acentric E-statistics as an
inversion-centre hint.

Scoring per candidate group: reflections its absence rules mark as
sys-absent are collected; observed intensity there should be noise.
A candidate is 'consistent' when strong violations (I > viol_sigma x
sigma(I)) are essentially absent; among consistent groups, MORE matched
absences = more specific = ranked higher (its absence set strictly
contains the weaker candidates').
"""
from __future__ import annotations

from typing import Any


def _laue_fingerprint(group) -> frozenset:
    """Basis-independent-enough fingerprint of a Laue group IN a fixed
    basis: the set of rotation parts (as tuples)."""
    return frozenset(tuple(op.r().as_double()) for op in group.all_ops())


def _dedupe_key(group) -> frozenset:
    return frozenset(str(op) for op in group.all_ops())


def candidate_groups(cell, laue_group) -> list:
    """All space groups (tabulated settings, deduped) whose derived Laue
    group matches `laue_group` (expressed in the SAME basis) and whose
    symmetry is compatible with `cell`."""
    from cctbx import sgtbx, uctbx

    uc = uctbx.unit_cell(cell) if not hasattr(cell, "parameters") else cell
    want = _laue_fingerprint(laue_group)
    out, seen = [], set()
    for symbols in sgtbx.space_group_symbol_iterator():
        try:
            g = sgtbx.space_group(symbols.hall())
        except RuntimeError:
            continue
        if _laue_fingerprint(g.build_derived_laue_group()) != want:
            continue
        if not g.is_compatible_unit_cell(uc):
            continue
        k = _dedupe_key(g)
        if k in seen:
            continue
        seen.add(k)
        out.append((symbols.universal_hermann_mauguin(), g))
    return out


# ==========================================================================
# intensity statistics: ONE reference table, resolution shells, the
# classical moments, the L-test, and the documented failure conditions of
# the centric/acentric hint
# ==========================================================================

#: Wilson expectations for the intensity statistics, stated ONCE for the
#: whole codebase (every tool that prints one of these numbers reads it
#: from here). The three classical moments are Xtriage's tabulated
#: untwinned / perfect-twin pairs. The two L-test rows are DERIVED here
#: rather than copied, because the published 0.500 / 0.333 line is the
#: ACENTRIC one: for two independent reflections drawn from the same
#: Gamma(k) intensity distribution, I1/(I1+I2) is Beta(k,k), so k = 1
#: (acentric) gives <|L|> 0.500 and <L^2> 0.333 (Padilla & Yeates 2003),
#: k = 1/2 (centric) gives 2/pi = 0.637 and 0.500, and averaging two twin
#: domains raises k by one (acentric perfect twin, k = 2: 0.375 / 0.200).
#: That distinction is a small-molecule fact: in a centrosymmetric group
#: EVERY reflection is centric, so the untwinned expectation is the k=1/2
#: row - judging an organic P-1 structure against the macromolecular
#: 0.500 line would flag every healthy dataset.
INTENSITY_STATISTIC_REFERENCE: dict[str, dict[str, Any]] = {
    "mean_abs_e2_minus_1": {
        "formula": "<|E^2-1|>",
        "acentric_untwinned": 0.736, "acentric_perfect_twin": 0.541,
        "centric_untwinned": 0.968, "centric_perfect_twin": 0.736,
        "beyond_centric_argues_for": "pseudo_translation",
        "ordinary_molecular_range": (1.03, 1.14)},
    "i2_over_i_sq": {
        "formula": "<I^2>/<I>^2",
        "acentric_untwinned": 2.000, "acentric_perfect_twin": 1.500,
        "centric_untwinned": 3.000, "centric_perfect_twin": 2.000,
        "beyond_centric_argues_for": "pseudo_translation",
        "ordinary_molecular_range": (4.1, 4.9)},
    "f_sq_over_f2": {
        "formula": "<F>^2/<F^2>",
        "acentric_untwinned": 0.785, "acentric_perfect_twin": 0.885,
        "centric_untwinned": 0.637, "centric_perfect_twin": 0.785,
        "beyond_centric_argues_for": "pseudo_translation",
        "ordinary_molecular_range": (0.56, 0.63)},
    "mean_abs_l": {
        "formula": "<|L|>, L = (I1-I2)/(I1+I2) over neighbour pairs",
        "acentric_untwinned": 0.500, "acentric_perfect_twin": 0.375,
        "centric_untwinned": 0.637, "centric_perfect_twin": 0.500,
        "beyond_centric_argues_for": "detwinned_or_filtered_data",
        "ordinary_molecular_range": (0.58, 0.70)},
    "mean_l_sq": {
        "formula": "<L^2>",
        "acentric_untwinned": 0.333, "acentric_perfect_twin": 0.200,
        "centric_untwinned": 0.500, "centric_perfect_twin": 0.333,
        "beyond_centric_argues_for": "detwinned_or_filtered_data",
        "ordinary_molecular_range": (0.42, 0.57)},
}

#: the centric / acentric <|E^2-1|> pair every caller quotes
_E2M1_ROW = INTENSITY_STATISTIC_REFERENCE["mean_abs_e2_minus_1"]
E2M1_REFERENCE = {
    "centrosymmetric": _E2M1_ROW["centric_untwinned"],
    "non_centrosymmetric": _E2M1_ROW["acentric_untwinned"],
}

def e2m1_hint(value: float) -> str:
    """centrosymmetric / non_centrosymmetric from <|E^2-1|>, split at the
    midpoint of the two references. Derived from E2M1_REFERENCE so the
    numbers exist in exactly one place - and read together with
    hint_usability(), which says what the answer may be USED for."""
    mid = 0.5 * (E2M1_REFERENCE["centrosymmetric"]
                 + E2M1_REFERENCE["non_centrosymmetric"])
    return "centrosymmetric" if value > mid else "non_centrosymmetric"


#: A deviation counts as resolvable only when it reaches this fraction of
#: the untwinned -> perfect-twin span of the SAME statistic. 0.20 is not a
#: taste: every statistic in the table above moves roughly quadratically
#: with the twin fraction alpha, and 20 % of the span is reached at
#: alpha ~ 0.05 - the level below which a BASF refinement cannot be
#: trusted anyway, and below which the finite-atom departure of a real
#: small-molecule structure from ideal Wilson statistics is the larger
#: effect.
EFFECT_FLOOR_FRACTION = 0.20


def statistic_reading(key: str, value: float, *,
                      standard_error: float | None = None,
                      n: int | None = None,
                      corroboration: list[str] | None = None
                      ) -> dict[str, Any]:
    """Directional, ONE-SIDED reading of one intensity statistic.

    The two UNTWINNED references (acentric and centric) bracket a zone in
    which an untwinned acentric structure, an untwinned centric one and a
    50:50 twinned centric one all overlap - inside it the number selects
    nothing. Outside it the SIGN carries the diagnosis (Xtriage: '<I^2>/
    <I>^2 significantly lower than 2.0 might point to twinning, whereas a
    value significantly larger might point towards pseudo translational
    symmetry'), so the verdict names the direction:

    - beyond the ACENTRIC reference on the twin side: intensity averaging
      (twinning first) - a pseudo-translation moves it the other way;
    - beyond the CENTRIC reference: a pseudo-translation / hypercentric
      distribution (for the L-test rows: detwinned or filtered data) -
      twinning moves it the other way.

    Xtriage's 2.0 line is a macromolecular convention (acentric
    reflections dominate there). For small molecules a centrosymmetric
    group makes EVERY reflection centric, so 3.0 is an ordinary value and
    the honest upper bracket is the centric reference, not the acentric
    one.

    THE TWO DIRECTIONS ARE NOT EQUALLY STRONG, and this function does not
    pretend they are. The Wilson references assume many atoms of similar
    weight at random positions; a real molecular crystal breaks that
    assumption in ONE direction only - bonded rigid groups, flat aromatic
    fragments and anisotropic displacement all INFLATE these moments and
    never deflate them. Measured on this repo's own reference data,
    ordinary published small-molecule sets read <I^2>/<I>^2 4.1-4.9 and
    <|E^2-1|> 1.03-1.10 where the ideal values are 3.000 and 0.968. So an
    upward deviation is the NORMAL state of a molecular crystal and is
    never claimed as a finding on its own: the upward branch reports the
    number, names the candidate causes and asks for an independent
    signature (`corroboration` - a weak/strong index class, an off-origin
    Patterson peak, a dominant heavy scatterer, a file known to be
    fcf-derived). The downward branch needs no such corroboration,
    because none of those contaminants can produce it.

    Nothing here ever reads as 'passed': these statistics are one-sided
    evidence - an anomaly indicates a problem, an ordinary value proves
    nothing (Xtriage: 'Large values can indicate twinning, but small
    values do not necessarily exclude it').
    """
    ref = INTENSITY_STATISTIC_REFERENCE[key]
    formula = ref["formula"]
    a_un = ref["acentric_untwinned"]
    c_un = ref["centric_untwinned"]
    twin_dir = 1.0 if ref["acentric_perfect_twin"] > a_un else -1.0
    span = abs(ref["acentric_perfect_twin"] - a_un)
    floor = EFFECT_FLOOR_FRACTION * span
    three_se = 3.0 * float(standard_error) if standard_error else 0.0
    band = max(floor, three_se)
    dev_twin = (value - a_un) * twin_dir
    dev_cent = (value - c_un) * -twin_dir
    out: dict[str, Any] = {
        "value": round(float(value), 3),
        "formula": formula,
        "reference": {"acentric_untwinned": a_un,
                      "acentric_perfect_twin": ref["acentric_perfect_twin"],
                      "centric_untwinned": c_un,
                      "centric_perfect_twin": ref["centric_perfect_twin"]},
        "resolvable_band": round(band, 4),
    }
    # the prose behind the band is only worth its characters where the
    # band is the reason the tool is hedging
    band_note = (f"counts above max(3 sampling sigma {three_se:.4f}, "
                 f"{EFFECT_FLOOR_FRACTION:.0%} of the twin span {floor:.4f} "
                 f"= twin fraction ~0.05)")
    if n is not None:
        out["n"] = int(n)
    if standard_error is not None:
        out["standard_error"] = round(float(standard_error), 4)
    if dev_twin > 0:
        clear = dev_twin > band
        out.update({
            "direction": "beyond_acentric_on_the_twin_side",
            "strength": "clear" if clear else "marginal",
            "deviation": round(dev_twin, 3),
            "argues_for": ["twinning"],
            "verdict": (
                f"{formula} = {value:.3f} lies {dev_twin:.3f} beyond the "
                f"untwinned acentric value {a_un:.3f}, on the side twin "
                f"superposition moves it (perfect twin "
                f"{ref['acentric_perfect_twin']:.3f}): it "
                + ("argues FOR" if clear else "leans toward")
                + " an intensity-averaging pathology - twinning first, "
                  "then a split/composite crystal indexed as one lattice, "
                  "or data merged in too high a Laue class"
                + ("" if clear else
                   f". The deviation is inside the band this dataset can "
                   f"resolve ({band:.3f}), so it is a lead to check, not "
                   f"a finding")
                + "."),
            "not_argued_for": (
                f"a pseudo-translation moves {formula} the other way "
                f"(beyond {c_un:.3f}); and no value of it is evidence "
                f"that the data are free of either pathology."),
        })
    elif dev_cent > 0:
        beyond = ref["beyond_centric_argues_for"]
        if beyond == "pseudo_translation":
            what = ("a pseudo-translation / superstructure (a bimodal "
                    "weak-strong reflection class) or a hypercentric "
                    "distribution from a dominant heavy-atom "
                    "substructure")
            need = ("a weak/strong INDEX CLASS (parity_classes), an "
                    "off-origin Patterson peak, or a composition with one "
                    "dominant scatterer")
        else:
            what = ("data that were detwinned, model-completed or "
                    "outlier-filtered before export (an fcf-derived or "
                    "otherwise reconstructed file), or a weak/strong "
                    "class the delta=2 pairing did not absorb")
            need = ("a file provenance that explains it (fcf/LIST-4 "
                    "derived, absences already stripped) or a weak/strong "
                    "index class")
        out.update({
            "direction": "beyond_centric",
            "deviation": round(dev_cent, 3),
            "not_argued_for": (
                f"intensity averaging (twinning) moves {formula} the "
                f"other way (beyond {a_un:.3f}); and no value of it is "
                f"evidence that the data are free of either pathology."),
        })
        if corroboration:
            out.update({
                "strength": "corroborated",
                "argues_for": [beyond],
                "corroborated_by": list(corroboration),
                "verdict": (
                    f"{formula} = {value:.3f} lies {dev_cent:.3f} beyond "
                    f"the CENTRIC reference {c_un:.3f} - the value an "
                    f"all-centric structure already reaches - AND an "
                    f"independent signature is present ("
                    + "; ".join(corroboration) + f"): together they argue "
                    f"FOR {what}."),
            })
        else:
            rng = ref.get("ordinary_molecular_range")
            measured = (f", where ordinary small-molecule sets already sit "
                        f"({rng[0]}-{rng[1]} measured on this repo's "
                        f"published reference data and rigid-molecule "
                        f"controls)" if rng else "")
            out.update({
                "strength": "uncorroborated",
                "argues_for": [],
                "verdict": (
                    f"{formula} = {value:.3f} lies {dev_cent:.3f} beyond "
                    f"the CENTRIC reference {c_un:.3f}{measured}: on its "
                    f"own it argues for nothing. It becomes evidence for "
                    f"{what} only with {need}."),
            })
    else:
        out.update({
            "direction": "inside_the_untwinned_bracket",
            "strength": "no_direction",
            "deviation": 0.0,
            "argues_for": [],
            "verdict": (
                f"{formula} = {value:.3f} lies between the untwinned "
                f"acentric ({a_un:.3f}) and centric ({c_un:.3f}) values, "
                f"where an untwinned acentric structure, an untwinned "
                f"centric one and a 50:50 twinned centric one all overlap: "
                f"it selects none of them, and an ordinary value is not "
                f"evidence of ordinary data."),
        })
    if out["strength"] != "clear":
        out["band_note"] = band_note
    return out


def _merged_in_laue(intensities, laue_group):
    """Intensities merged in `laue_group` (same basis as the data)."""
    from cctbx import crystal

    cs_laue = crystal.symmetry(unit_cell=intensities.unit_cell(),
                               space_group=laue_group,
                               assert_is_compatible_unit_cell=False)
    merged = (intensities.customized_copy(crystal_symmetry=cs_laue)
              .merge_equivalents().array())
    return merged, cs_laue


def _normalized_e(intensities, laue_group, n_shells: int | None = None):
    """(merged array, F array carrying the binner, E^2 as flex.double).

    E is quasi-normalized WITHIN resolution shells - the shell mean of
    I/epsilon is the Wilson scale, so the resolution fall-off (and with it
    the overall B) never enters the moments. Same primitive as
    e2m1_statistic, which is why both report the same number."""
    merged, _cs = _merged_in_laue(intensities, laue_group)
    f = merged.f_sq_as_f()
    if n_shells:
        n_bins = max(1, min(int(n_shells), max(1, f.size() // 20)))
        f.setup_binner(n_bins=n_bins)
    else:
        f.setup_binner(auto_binning=True)
    e = f.quasi_normalize_structure_factors()
    return merged, f, e.data() * e.data()


def _sd(values) -> float:
    from cctbx.array_family import flex
    n = values.size()
    if n < 2:
        return 0.0
    d = values - flex.mean(values)
    return float((flex.sum(d * d) / (n - 1)) ** 0.5)


def e2m1_by_shell(intensities, laue_group, n_shells: int = 10, *,
                  corroboration: list[str] | None = None) -> dict[str, Any]:
    """<|E^2-1|> per resolution shell, plus the overall value.

    A single overall number hides the readings SADABS documents for the
    CURVE: 'values that are uniformly lower than expected may indicate
    twinning, and values that are uniformly higher than expected may be
    caused by pseudo-translational symmetry. A systematic drop or rise at
    high resolution may indicate problems with the SAINT integration (e.g.
    integrating data that were not present)'. Shell by shell those are
    three different pictures; collapsed to one mean they are one number.
    """
    from cctbx.array_family import flex

    merged, f, e2 = _normalized_e(intensities, laue_group, n_shells)
    dev = flex.abs(e2 - 1.0)
    binner = f.binner()
    shells: list[dict[str, Any]] = []
    for i_bin in binner.range_used():
        sel = binner.selection(i_bin)
        n = sel.count(True)
        if n == 0:
            continue
        d_max, d_min = binner.bin_d_range(i_bin)
        shells.append({
            "d_max": (None if d_max is None or d_max < 0
                      else round(float(d_max), 3)),
            "d_min": round(float(d_min), 3),
            "n": int(n),
            "mean_abs_e2_minus_1": round(float(flex.mean(dev.select(sel))),
                                         3)})
    n_all = dev.size()
    overall = float(flex.mean(dev)) if n_all else 0.0
    se = (_sd(dev) / (n_all ** 0.5)) if n_all > 1 else None
    d_max_min = merged.d_max_min() if merged.size() else (None, None)
    out: dict[str, Any] = {
        "n_shells": len(shells),
        "shells": shells,
        "overall": {"mean_abs_e2_minus_1": round(overall, 3),
                    "n": int(n_all),
                    "d_max": (round(float(d_max_min[0]), 3)
                              if d_max_min[0] else None),
                    "d_min": (round(float(d_max_min[1]), 3)
                              if d_max_min[1] else None)},
        "reference": dict(E2M1_REFERENCE),
        "reading": statistic_reading("mean_abs_e2_minus_1", overall,
                                     standard_error=se, n=n_all,
                                     corroboration=corroboration),
    }
    if len(shells) >= 4:
        # The trend test compares two GROUPS of shells, so its band is the
        # standard error of their DIFFERENCE - not the overall band, which
        # is far tighter and would flag ordinary shell-to-shell scatter.
        # The lowest-resolution shell is left out on purpose: it is always
        # inflated by the molecular transform (few, very strong
        # reflections dominated by molecular shape), and the reading
        # SADABS documents is about the HIGH-resolution end.
        used = list(binner.range_used())
        rest = used[1:]
        cut = len(rest) // 2
        lo_sel = flex.bool(dev.size(), False)
        hi_sel = flex.bool(dev.size(), False)
        for b in rest[:cut]:
            lo_sel |= binner.selection(b)
        for b in rest[cut:]:
            hi_sel |= binner.selection(b)
        lo_v, hi_v = dev.select(lo_sel), dev.select(hi_sel)
        low = float(flex.mean(lo_v)) if lo_v.size() else 0.0
        high = float(flex.mean(hi_v)) if hi_v.size() else 0.0
        se_diff = ((_sd(lo_v) ** 2 / max(1, lo_v.size())
                    + _sd(hi_v) ** 2 / max(1, hi_v.size())) ** 0.5)
        band = round(max(3.0 * se_diff,
                         out["reading"]["resolvable_band"]), 4)
        trend: dict[str, Any] = {
            "low_resolution_group": round(low, 3),
            "high_resolution_group": round(high, 3),
            "n_low": int(lo_v.size()), "n_high": int(hi_v.size()),
            "first_shell_excluded": True,
            "change": round(high - low, 3),
            "band": band}
        if abs(high - low) > band:
            trend["reading"] = (
                f"<|E^2-1|> {'rises' if high > low else 'drops'} by "
                f"{abs(high - low):.3f} from the low- to the "
                f"high-resolution half. A systematic change ACROSS "
                f"resolution argues for the data reduction rather than for "
                f"the structure: integrating frames where there were no "
                f"data, a wrong scaling/absorption model, or a resolution "
                f"cut applied after normalization. Settle the reduction "
                f"before reading a centric/acentric hint off the overall "
                f"number.")
        else:
            trend["reading"] = (
                "no resolution trend beyond the resolvable band - which "
                "says nothing about the overall LEVEL; read that from the "
                "reading block.")
        out["shell_trend"] = trend
    return out


def intensity_moments(intensities, laue_group, n_shells: int | None = None,
                      *, corroboration: list[str] | None = None
                      ) -> dict[str, Any]:
    """<I^2>/<I>^2 and <F>^2/<F^2> on shell-normalized intensities.

    Both moments are computed on E^2 (intensity normalized within its own
    resolution shell), so the Wilson fall-off cannot masquerade as a
    pathology: <I^2>/<I>^2 on RAW intensities of any structure is large
    simply because low-angle reflections are stronger. n_shells=None uses
    cctbx auto binning (~200 reflections per shell, the same
    normalization e2m1_statistic uses); a COARSER binning leaves residual
    resolution dependence inside the shells and inflates both moments
    (measured: 4 shells 4.9 vs 30 shells 4.3 on the same data), so the
    shell table's display binning is deliberately not reused here."""
    from cctbx.array_family import flex

    _merged, _f, z = _normalized_e(intensities, laue_group, n_shells)
    n = z.size()
    if n < 2:
        return {"error": "fewer than two reflections after merging"}
    dev = flex.abs(z - 1.0)
    e2m1 = float(flex.mean(dev))
    se_e2m1 = _sd(dev) / (n ** 0.5)
    mean_z = float(flex.mean(z))
    z2 = z * z
    mean_z2 = float(flex.mean(z2))
    e_abs = flex.sqrt(flex.abs(z))
    mean_e = float(flex.mean(e_abs))
    denom = max(mean_z * mean_z, 1e-12)
    i2_over_i_sq = mean_z2 / denom
    f_sq_over_f2 = (mean_e * mean_e) / max(mean_z, 1e-12)
    # delta-method standard errors from THIS sample (the spread of the
    # per-reflection quantity), not from a nominal distribution
    se_i2 = _sd(z2) / (n ** 0.5 * denom)
    se_f = 2.0 * mean_e * _sd(e_abs) / (n ** 0.5 * max(mean_z, 1e-12))
    return {
        "n_reflections": int(n),
        "mean_abs_e2_minus_1": statistic_reading(
            "mean_abs_e2_minus_1", e2m1, standard_error=se_e2m1, n=n,
            corroboration=corroboration),
        "i2_over_i_sq": statistic_reading("i2_over_i_sq", i2_over_i_sq,
                                          standard_error=se_i2, n=n,
                                          corroboration=corroboration),
        "f_sq_over_f2": statistic_reading("f_sq_over_f2", f_sq_over_f2,
                                          standard_error=se_f, n=n,
                                          corroboration=corroboration),
        "note": ("the three classical moments, on intensities normalized "
                 "within their own resolution shell (E^2), so the Wilson "
                 "fall-off is divided out. The DIRECTION is the "
                 "diagnosis: below the acentric reference = intensity "
                 "averaging (twinning); above the centric one = "
                 "pseudo-translation / hypercentric; between them the "
                 "statistic decides nothing. The two directions are not "
                 "equally strong: rigid bonded geometry, flat aromatic "
                 "fragments and anisotropic displacement all push these "
                 "moments UP and never down, so ordinary molecular "
                 "crystals live above the ideal references (measured 4.1-"
                 "4.9 for <I^2>/<I>^2 on this repo's published reference "
                 "data) and an upward reading is only claimed when an "
                 "independent signature corroborates it."),
    }


def l_test(intensities, laue_group,
           offsets=((2, 0, 0), (0, 2, 0), (0, 0, 2)), *,
           corroboration: list[str] | None = None) -> dict[str, Any]:
    """Padilla & Yeates L-test on neighbour pairs of unique reflections.

    L = (I1 - I2)/(I1 + I2) for reflections two index units apart. The
    offset is 2, not 1, on purpose: it keeps both members in the SAME
    parity class, which is what makes the L-test robust against a
    pseudo-translation / pseudo-centring (whose weak and strong classes
    differ by parity) while <|E^2-1|> and the moments are not. The two
    families are therefore not redundant - on a tNCS dataset the moments
    are contaminated and the L-test still reads.
    """
    from cctbx import miller
    from cctbx.array_family import flex

    merged, cs_laue = _merged_in_laue(intensities, laue_group)
    idx = merged.indices()
    data = merged.data()
    n = idx.size()
    if n < 20:
        return {"error": f"only {n} unique reflections - too few to pair"}
    lookup = {tuple(h): i for i, h in enumerate(idx)}
    l_vals = flex.double()
    n_skipped = 0
    for off in offsets:
        shifted = flex.miller_index([(h[0] + off[0], h[1] + off[1],
                                      h[2] + off[2]) for h in idx])
        ms = miller.set(cs_laue, shifted,
                        anomalous_flag=merged.anomalous_flag()).map_to_asu()
        for i, h2 in enumerate(ms.indices()):
            j = lookup.get(tuple(h2))
            if j is None or j == i:
                continue
            i1, i2 = float(data[i]), float(data[j])
            # L is only defined for non-negative intensities: a measured
            # I < 0 (routine for weak reflections, and 2-3 % of an
            # fcf-derived file) makes I1+I2 vanish or change sign and
            # sends |L| to infinity. Skipping those pairs is the only
            # honest option here - the count is reported, because
            # discarding the weakest reflections biases L UPWARD and the
            # reader must be able to see how many went.
            if i1 <= 0 or i2 <= 0:
                n_skipped += 1
                continue
            l_vals.append((i1 - i2) / (i1 + i2))
    n_pairs = l_vals.size()
    if n_pairs < 50:
        return {"error": f"only {n_pairs} usable neighbour pairs (from "
                         f"{n} unique reflections, {n_skipped} pairs "
                         f"dropped for a non-positive intensity)"}
    abs_l = flex.abs(l_vals)
    l_sq = l_vals * l_vals
    mean_abs_l = float(flex.mean(abs_l))
    mean_l_sq = float(flex.mean(l_sq))
    # each reflection enters up to len(offsets) pairs, so the pairs are
    # not independent: inflate the naive standard error accordingly
    infl = float(len(offsets)) ** 0.5
    se_abs = infl * _sd(abs_l) / (n_pairs ** 0.5)
    se_sq = infl * _sd(l_sq) / (n_pairs ** 0.5)
    return {
        "n_pairs": int(n_pairs),
        "n_pairs_dropped_non_positive": int(n_skipped),
        "n_unique_reflections": int(n),
        "offsets": [list(o) for o in offsets],
        "mean_abs_l": statistic_reading("mean_abs_l", mean_abs_l,
                                        standard_error=se_abs, n=n_pairs,
                                        corroboration=corroboration),
        "mean_l_sq": statistic_reading("mean_l_sq", mean_l_sq,
                                       standard_error=se_sq, n=n_pairs,
                                       corroboration=corroboration),
        "note": ("neighbour pairs two index units apart (same parity "
                 "class), so a pseudo-translation does not bias the test; "
                 "the untwinned expectation is 0.500/0.333 for acentric "
                 "and 0.637/0.500 for centric reflections - a "
                 "centrosymmetric small-molecule structure is ALL centric "
                 "and belongs against the second pair. The L-test finds "
                 "twinning without a twin law; quantifying a twin fraction "
                 "needs Britton / H / R-vs-R with the law in hand."),
    }


def index_class_selections(indices):
    """(name, flex.bool) for the mod-2 and mod-3 index classes - the
    parity/thirds partition that exposes a doubled axis, a superstructure
    or an undeclared centring. One definition, shared by the parity table
    and by the pseudo-translation failure condition."""
    from cctbx.array_family import flex

    h = flex.int([m[0] for m in indices])
    k = flex.int([m[1] for m in indices])
    l_ = flex.int([m[2] for m in indices])
    return [
        ("h odd", (h % 2) != 0), ("k odd", (k % 2) != 0),
        ("l odd", (l_ % 2) != 0),
        ("h+k odd", ((h + k) % 2) != 0), ("h+l odd", ((h + l_) % 2) != 0),
        ("k+l odd", ((k + l_) % 2) != 0),
        ("h+k+l odd", ((h + k + l_) % 2) != 0),
        ("h not 3n", (h % 3) != 0), ("k not 3n", (k % 3) != 0),
        ("l not 3n", (l_ % 3) != 0),
        ("-h+k+l not 3n", ((-h + k + l_) % 3) != 0),
    ]


#: A whole index class carrying less than this fraction of the average
#: intensity is a weak/strong split, not sampling noise: a random subset
#: of reflections sits at 1.0, and even a strongly anisotropic structure
#: does not thin a whole parity class to a third. Below 0.10 the class is
#: a (pseudo-)absence rather than a weak class - the line the parity table
#: already draws - and an undeclared centring produces the same signature
#: as a superstructure.
WEAK_INDEX_CLASS_RATIO = 0.35


def weak_index_class(intensities, min_n: int = 50) -> dict[str, Any] | None:
    """The most extreme systematically weak index class, or None.

    Classes with fewer than `min_n` reflections are skipped, and so is a
    class with none at all: an absent class means the vendor already
    applied that centring, which is a different fact (reported by the
    centring detection, not here)."""
    from cctbx.array_family import flex

    idx = intensities.indices()
    data = intensities.data()
    if idx.size() < min_n:
        return None
    mean_all = float(flex.mean(data))
    if not mean_all > 0:
        return None
    worst = None
    for name, sel in index_class_selections(idx):
        n = sel.count(True)
        if n < min_n:
            continue
        ratio = float(flex.mean(data.select(sel))) / mean_all
        if worst is None or ratio < worst["mean_i_ratio"]:
            worst = {"class": name, "n": int(n),
                     "mean_i_ratio": round(ratio, 3)}
    if worst is None or worst["mean_i_ratio"] >= WEAK_INDEX_CLASS_RATIO:
        return None
    worst["threshold"] = WEAK_INDEX_CLASS_RATIO
    return worst


# --------------------------------------------------------------------------
# the |E^2-1| centric/acentric hint and its documented failure conditions
# --------------------------------------------------------------------------

#: The five conditions under which the centric/acentric hint is NOT
#: reliable, each with the DIRECTION of the bias it produces. Sources:
#: XPREP manual ('such statistics may be unreliable if heavy atoms are
#: present (especially when they lie on special positions) or if there are
#: very few reflections in one of these three projections. Twinned
#: structures may give an acentric distribution even when the true space
#: group is centrosymmetric'); SADABS manual ('values uniformly lower than
#: expected may indicate twinning, and values uniformly higher than
#: expected may be caused by pseudo-translational symmetry ... for
#: inorganic structures with heavy atoms on special positions this plot is
#: less reliable'); Clegg 2019 (metal complexes routinely land between the
#: two references and settle nothing). The evaluator walks THIS list, so
#: the list is the single source of truth for what was checked.
E2M1_FAILURE_CONDITIONS: tuple[dict[str, str], ...] = (
    {"id": "dominant_heavy_scatterer",
     "title": "the heaviest element carries most of the scattering power",
     "test": "share of the HEAVIEST element (not the most abundant one) in "
             "sum(n Z^2) over the unit-cell content > 0.50 - in any "
             "organic, carbon holds the largest share while the structure "
             "is the ordinary many-similar-atoms Wilson case",
     "bias": "the intensity distribution is then set by a few atoms "
             "instead of by many independent ones and drifts toward "
             "hypercentric-like (HIGH) values whatever the true "
             "centricity - a metal complex commonly lands between the two "
             "references and settles nothing",
     "source": "XPREP manual; Clegg 2019"},
    {"id": "heavy_atom_on_special_position",
     "title": "a heavy scatterer sits on a special position, or the heavy "
              "substructure is itself pseudo-symmetric",
     "test": "any scatterer contributing >= 10 % of sum(n Z^2) alone has "
             "site-symmetry order > 1 (or the caller reports a "
             "pseudo-symmetric heavy substructure)",
     "bias": "the heavy substructure imposes its own symmetry on the "
             "phases: the statistics then report the SUBSTRUCTURE's "
             "centricity, not the structure's, and are pushed HIGH "
             "(toward centric) when the heavy atom sits on a centre or "
             "another special position",
     "source": "XPREP manual ('especially when they lie on special "
               "positions'); SADABS manual"},
    {"id": "twinning_by_merohedry",
     "title": "twinning superimposes domains (any partial twin fraction)",
     "test": "any intensity statistic reads beyond its untwinned ACENTRIC "
             "reference on the twin side",
     "bias": "twin superposition FLATTENS the distribution: <|E^2-1|> is "
             "pushed DOWN, so a CENTROSYMMETRIC structure reads as "
             "acentric (0.968 -> 0.736 and below). It never makes an "
             "acentric structure look centric. Consequence: on "
             "twin-suspicious data the hint may still be used to argue "
             "FOR a centre, never to drop one",
     "source": "XPREP manual ('Twinned structures may give an acentric "
               "distribution even when the true space group is "
               "centrosymmetric')"},
    {"id": "pseudo_translational_symmetry",
     "title": "a superstructure / pseudo-translation splits the "
              "reflections into weak and strong classes",
     "test": "an index class carries < 35 % of the average intensity, or a "
             "statistic reads beyond its untwinned CENTRIC reference",
     "bias": "the bimodal weak/strong distribution pushes <|E^2-1|> UP, so "
             "a NON-centrosymmetric structure can read as centric - the "
             "mirror image of twinning. Consequence: on such data the hint "
             "may be used to argue for the acentric option, never for a "
             "centre",
     "source": "SADABS manual; Xtriage tNCS section"},
    {"id": "too_few_reflections_or_too_low_resolution",
     "title": "the data cannot resolve the 0.232 gap between the two "
              "references",
     "test": "3 sampling sigma of <|E^2-1|> exceeds half of "
             "(0.968 - 0.736) = 0.116 (about 500 unique reflections at a "
             "typical spread), or d_min is coarser than 1.0 A",
     "bias": "direction unknown - the estimate is simply too noisy, or is "
             "taken outside the atomic-resolution regime the Wilson / "
             "atomicity assumption behind normalized structure factors "
             "needs (IUCr asks 0.84 A for publication; missed-symmetry "
             "checks are documented to require atomic resolution data)",
     "source": "XPREP manual ('very few reflections'); Mueller 2009 / "
               "Spek 2009, 2020"},
)

#: sum(n Z^2) share above which ONE element dominates the scattering
HEAVY_DOMINANCE_SHARE = 0.50
#: sum(n Z^2) share above which a SINGLE site counts as a heavy scatterer
HEAVY_SITE_SHARE = 0.10


def scattering_power_shares(model) -> dict[str, Any]:
    """Share of sum(n Z^2) per element in the unit-cell content, and per
    site - composition-derived, with no element list anywhere (the rule
    has to hold for elements no test crystal contains)."""
    from cctbx.eltbx import tiny_pse

    def _z_of(sc) -> int:
        el = (sc.scattering_type or "").strip().capitalize()
        el = el.rstrip("+-0123456789").strip()
        try:
            return int(tiny_pse.table(el).atomic_number())
        except Exception:  # noqa: BLE001 - exotic / dummy scattering types
            return 0

    sites: list[dict[str, Any]] = []
    per_element: dict[str, float] = {}
    total = 0.0
    for i, sc in enumerate(model.scatterers()):
        z = _z_of(sc)
        try:
            mult = float(sc.multiplicity())
        except Exception:  # noqa: BLE001 - multiplicity needs site symmetry
            mult = 1.0
        w = float(sc.occupancy) * max(mult, 1.0) * float(z * z)
        el = (sc.scattering_type or "?").strip()
        per_element[el] = per_element.get(el, 0.0) + w
        sites.append({"i": i, "label": sc.label, "element": el, "z": z,
                      "multiplicity": mult, "weight": w})
        total += w
    total = max(total, 1e-9)
    for s in sites:
        s["share"] = round(s.pop("weight") / total, 4)
    shares = {el: w / total for el, w in per_element.items()}
    dominant = max(shares.items(), key=lambda kv: kv[1]) if shares else None
    # The condition is about the HEAVIEST scatterer, not the most
    # abundant one: in any organic, carbon carries the largest share of
    # sum(n Z^2) (C7H6O2: 65 %) while the structure is the textbook
    # many-similar-atoms Wilson case. What breaks Wilson statistics is a
    # few atoms far heavier than the rest carrying the scattering.
    z_by_el = {s["element"]: s["z"] for s in sites}
    heaviest = (max(z_by_el.items(), key=lambda kv: kv[1])[0]
                if z_by_el else None)
    # participation ratio: how many atoms the scattering is effectively
    # spread over, sum(n Z^2)^2 / sum(n Z^4) - composition-derived, no
    # element list, and it stays meaningful for compositions no test
    # crystal contains
    z4 = sum((s["share"] * total) ** 2 for s in sites) if sites else 0.0
    n_eff = (total * total / z4) if z4 > 0 else None
    return {"total_z_squared": round(total, 1),
            "element_shares": {el: round(v, 3)
                               for el, v in sorted(shares.items(),
                                                   key=lambda kv: -kv[1])},
            "dominant_element": dominant[0] if dominant else None,
            "dominant_share": round(dominant[1], 3) if dominant else None,
            "heaviest_element": heaviest,
            "heaviest_z": z_by_el.get(heaviest) if heaviest else None,
            "heaviest_share": (round(shares[heaviest], 3)
                               if heaviest in shares else None),
            "effective_n_scatterers": (round(n_eff, 1) if n_eff else None),
            "sites": sites}


def site_symmetry_orders(model) -> list[int]:
    """Site-symmetry order per scatterer (1 = general position)."""
    from cctbx import sgtbx

    uc = model.unit_cell()
    sg = model.space_group()
    try:
        table = model.site_symmetry_table()
    except Exception:  # noqa: BLE001 - not every structure carries one
        table = None
    out: list[int] = []
    for i, sc in enumerate(model.scatterers()):
        order = None
        if table is not None:
            try:
                order = int(table.get(i).n_matrices())
            except Exception:  # noqa: BLE001
                order = None
        if not order:
            try:
                order = int(sgtbx.site_symmetry(
                    uc, sg, tuple(sc.site), 0.5, True).n_matrices())
            except Exception:  # noqa: BLE001 - a bad site must not break it
                order = 1
        out.append(max(1, order))
    return out


def hint_usability(hint: str | None) -> dict[str, Any]:
    """What a centric/acentric hint may be used FOR - independently of
    whether any failure condition fires.

    This asymmetry is permanent, not a condition: every intensity-
    averaging pathology (twinning first) pushes <|E^2-1|> DOWN, toward
    and past the acentric value, and no value of the statistic can
    exclude one. So an acentric reading can never carry the weight of
    REMOVING an inversion centre - r16 live: a twinned centrosymmetric
    crystal read 0.72, the run dropped to P1 and never recovered. The
    other direction has its own trap (Palatinus & van der Lee: a
    metallo-organic read 0.904, 'clearly in favor of a centrosymmetric
    space group', and the true group was non-centrosymmetric - an
    inversion twin with Flack 0.405), which is why neither reading is
    ever a decision.
    """
    if hint == "non_centrosymmetric":
        return {"hint": hint,
                "usable_for": ("keeping an acentric candidate on the "
                               "table alongside the absence evidence and "
                               "a solution trial"),
                "not_usable_for": (
                    "DROPPING an inversion centre. Twin superposition and "
                    "every other intensity-averaging pathology move "
                    "<|E^2-1|> exactly this way, and no value of the "
                    "statistic can exclude them. Solve/refine the "
                    "centrosymmetric candidate first (Marsh discipline) "
                    "and keep the acentric group only if the centric one "
                    "demonstrably fails.")}
    if hint == "centrosymmetric":
        return {"hint": hint,
                "usable_for": ("supporting an inversion centre, together "
                               "with a centrosymmetric refinement that "
                               "actually works"),
                "not_usable_for": (
                    "settling it. A pseudo-translation, a dominant "
                    "heavy-atom substructure and plain rigid molecular "
                    "geometry all move <|E^2-1|> this way; published "
                    "non-centrosymmetric structures have read 0.90+ here "
                    "(inversion twins among them).")}
    return {"hint": hint,
            "usable_for": None,
            "not_usable_for": "no hint was computed"}


def e2m1_hint_validity(*, model=None, n_reflections: int | None = None,
                       d_min: float | None = None,
                       e2m1_standard_error: float | None = None,
                       readings: list[dict[str, Any]] | None = None,
                       weak_class: dict[str, Any] | None = None,
                       heavy_substructure_symmetry: str | None = None,
                       hint: str | None = None) -> dict[str, Any]:
    """Walk E2M1_FAILURE_CONDITIONS against THIS composition and THESE
    data and say whether the centric/acentric hint may be read.

    hint_valid=False whenever a condition applies; the hint itself is
    never removed from the output - it is labelled, together with the
    direction each condition pushes it. hint_valid=True means only that
    none of the five documented conditions could be SHOWN to apply here
    (conditions that could not be evaluated are listed separately), never
    that the hint is proven reliable.
    """
    ref_gap = (E2M1_REFERENCE["centrosymmetric"]
               - E2M1_REFERENCE["non_centrosymmetric"])
    results: list[dict[str, Any]] = []
    shares = None
    orders = None
    if model is not None and model.scatterers().size():
        try:
            shares = scattering_power_shares(model)
            orders = site_symmetry_orders(model)
        except Exception as e:  # noqa: BLE001 - a broken model must not
            shares = {"error": f"{type(e).__name__}: {e}"}   # kill the audit

    def _add(cond, applies, evidence):
        # a condition that FIRES is reported in full (its bias direction
        # is what tells the reader which conclusion is still allowed); one
        # that does not gets the compact form - the same five entries are
        # always present, and E2M1_FAILURE_CONDITIONS holds the full text
        if applies:
            results.append({**cond, "applies": True, "evidence": evidence})
        else:
            results.append({"id": cond["id"], "title": cond["title"],
                            "applies": applies, "evidence": evidence})

    for cond in E2M1_FAILURE_CONDITIONS:
        cid = cond["id"]
        if cid == "dominant_heavy_scatterer":
            if not shares or "error" in shares:
                _add(cond, None,
                     shares["error"] if shares else
                     "no model / composition in the session")
            else:
                share = shares.get("heaviest_share") or 0.0
                _add(cond, share > HEAVY_DOMINANCE_SHARE,
                     f"the heaviest element "
                     f"{shares.get('heaviest_element')} "
                     f"(Z={shares.get('heaviest_z')}) carries {share:.0%} "
                     f"of sum(n Z^2) in the unit-cell content (fires above "
                     f"{HEAVY_DOMINANCE_SHARE:.0%}); the scattering is "
                     f"effectively spread over "
                     f"{shares.get('effective_n_scatterers')} atoms; shares "
                     f"{shares.get('element_shares')}")
        elif cid == "heavy_atom_on_special_position":
            if not shares or "error" in shares or orders is None:
                _add(cond, True if heavy_substructure_symmetry else None,
                     heavy_substructure_symmetry
                     or (shares["error"] if shares else
                         "no model / composition in the session"))
            else:
                hits = [(s, o) for s, o in zip(shares["sites"], orders)
                        if s["share"] >= HEAVY_SITE_SHARE and o > 1]
                if hits:
                    txt = "; ".join(
                        f"{s['label'] or s['element']} ({s['element']}, "
                        f"{s['share']:.0%} of sum(n Z^2)) sits on a "
                        f"special position, site-symmetry order {o}"
                        for s, o in hits)
                else:
                    txt = (f"no scatterer with >= {HEAVY_SITE_SHARE:.0%} of "
                           f"sum(n Z^2) sits on a special position")
                if heavy_substructure_symmetry:
                    txt += f"; caller reports {heavy_substructure_symmetry}"
                _add(cond, bool(hits) or bool(heavy_substructure_symmetry),
                     txt)
        elif cid == "twinning_by_merohedry":
            if not readings:
                _add(cond, None, "no intensity statistics supplied")
            else:
                hit = [r for r in readings
                       if "twinning" in (r.get("argues_for") or [])]
                # only a CLEAR reading counts. The marginal band is where
                # ordinary finite-atom structures already live (measured:
                # a healthy 15-atom acentric control reads <I^2>/<I>^2
                # 1.85-1.94 against the 2.000 reference), and the three
                # moments are functions of the same distribution, so two
                # of them agreeing is not independent corroboration.
                strong = [r for r in hit if r.get("strength") == "clear"]
                _add(cond, bool(strong),
                     "; ".join(f"{r['formula']} = {r['value']} "
                               f"({r['strength']})" for r in hit)
                     or "no statistic reads beyond its untwinned acentric "
                        "reference on the twin side - which is not "
                        "evidence of an untwinned crystal")
        elif cid == "pseudo_translational_symmetry":
            hit = [r for r in (readings or [])
                   if "pseudo_translation" in (r.get("argues_for") or [])]
            if weak_class is None and not readings:
                _add(cond, None,
                     "no index-class or statistic evidence supplied")
            else:
                txt = []
                if weak_class:
                    txt.append(f"index class '{weak_class['class']}' "
                               f"carries {weak_class['mean_i_ratio']:.2f} "
                               f"of the average intensity over "
                               f"{weak_class['n']} reflections")
                txt += [f"{r['formula']} = {r['value']} ({r['strength']})"
                        for r in hit]
                _add(cond, bool(weak_class) or bool(hit),
                     "; ".join(txt) or "no weak index class and no "
                     "statistic beyond its untwinned centric reference")
        else:   # too_few_reflections_or_too_low_resolution
            reasons = []
            if e2m1_standard_error is not None:
                if 3.0 * float(e2m1_standard_error) > 0.5 * ref_gap:
                    reasons.append(
                        f"3 sampling sigma of <|E^2-1|> = "
                        f"{3 * float(e2m1_standard_error):.3f} exceeds "
                        f"half the centric/acentric gap "
                        f"({0.5 * ref_gap:.3f})")
            elif n_reflections is not None and n_reflections < 500:
                reasons.append(
                    f"{n_reflections} unique reflections (below 500)")
            if d_min is not None and float(d_min) > 1.0:
                reasons.append(
                    f"d_min {float(d_min):.2f} A is coarser than 1.0 A "
                    f"(IUCr asks 0.84 A for publication; normalized "
                    f"structure factors assume the atomic-resolution "
                    f"regime)")
            if (n_reflections is None and d_min is None
                    and e2m1_standard_error is None):
                _add(cond, None, "no reflection count / resolution supplied")
            else:
                marginal = (d_min is not None
                            and 0.84 < float(d_min) <= 1.0)
                _add(cond, bool(reasons), "; ".join(reasons) or (
                    f"d_min {float(d_min):.2f} A sits between the IUCr "
                    f"0.84 A limit and 1.0 A - marginal, not triggering"
                    if marginal else
                    f"n_unique {n_reflections}, d_min {d_min} A"))
    triggered = [r["id"] for r in results if r["applies"] is True]
    unknown = [r["id"] for r in results if r["applies"] is None]
    return {
        "hint_valid": not triggered,
        "conditions_triggered": triggered,
        "conditions_not_evaluable": unknown,
        "conditions": results,
        "usability": hint_usability(hint),
        "note": (
            ("the centric/acentric hint is UNRELIABLE here: "
             + "; ".join(triggered)
             + ". The hint stays in the output, labelled - settle the "
               "inversion centre by solution/refinement trials (the "
               "centrosymmetric candidate first, Marsh discipline) and "
               "read each condition's bias direction above: it says which "
               "way the number is pushed, and therefore which conclusion "
               "is still allowed.")
            if triggered else
            ("none of the five documented failure conditions could be "
             "SHOWN to apply to this composition and these data - which is "
             "not a certificate: whatever could not be evaluated is listed "
             "in conditions_not_evaluable, and the hint stays one piece of "
             "evidence among absences, Laue R_int and solution trials.")),
    }


def e2m1_statistic(intensities, laue_group) -> float:
    """mean |E^2 - 1| of quasi-normalized structure factors, merged in
    `laue_group` (expressed in the same basis as the data).

    Wilson expectation: 0.968 centrosymmetric, 0.736 non-centrosymmetric.
    Twinned data superimpose two domains' intensities and flatten the
    distribution BELOW even the acentric value - the XPREP convention
    flags < 0.68 as a twin warning. Shared by sg_screen (centric hint)
    and audit_reflection_data (twin alarm) so both judge the same number.
    e2m1_by_shell reports the same statistic shell by shell, where the
    twin (uniformly low), pseudo-translation (uniformly high) and
    data-reduction (drifting with resolution) readings separate.
    """
    from cctbx.array_family import flex

    _merged, _f, e2 = _normalized_e(intensities, laue_group)
    return float(flex.mean(flex.abs(e2 - 1.0)))


#: R_int above which XPREP's manual calls a Laue assignment doubtful
#: ('Generally R(int) should be below 0.1 for the correct assignment')
LAUE_R_INT_REFERENCE = 0.10


def candidate_conflicts(symbol: str, group, row: dict[str, Any],
                        e_stats: dict[str, Any] | None,
                        evidence: dict[str, Any] | None) -> list[dict]:
    """Disagreements between the evidence channels FOR ONE CANDIDATE.

    Purely descriptive. It is computed after the ranking, it never feeds
    back into it, and it carries no supergroup prior: a conflict is a
    fact about the evidence, not a vote. The reason for reporting it at
    all is the SHELXTL roe119 case - 'the statistics are clearly
    centrosymmetric, but only a non-centrosymmetric space group is
    consistent with the systematic absences' - where the contradiction
    itself was the diagnosis (a wrong crystal system, and only half the
    data collected). Palatinus & van der Lee's counter-example runs the
    other way: E statistics 'clearly in favor of a centrosymmetric space
    group' on a structure whose true group is non-centrosymmetric (an
    inversion twin, Flack 0.405). Neither channel wins by default; the
    disagreement is what gets reported.
    """
    out: list[dict[str, Any]] = []
    ev = evidence or {}
    hint = (e_stats or {}).get("hint")
    hint_valid = (e_stats or {}).get("hint_valid")
    try:
        cand_centric = bool(group.is_centric())
    except Exception:  # noqa: BLE001 - a symbol we cannot interrogate
        cand_centric = None
    absence = row.get("absence_evidence")

    if hint and cand_centric is not None:
        hint_centric = hint == "centrosymmetric"
        if hint_centric != cand_centric:
            out.append({
                "id": "candidate_centricity_vs_e_statistics",
                "channels": ["space_group_centricity", "e_statistics"],
                "note": (
                    f"{symbol} is "
                    + ("centrosymmetric" if cand_centric
                       else "non-centrosymmetric")
                    + f" while <|E^2-1|> hints {hint}"
                    + ("" if hint_valid is not False else
                       " (that hint is labelled unreliable here - see "
                       "e_statistics.hint_validity)")
                    + ". Settle it by trial (centrosymmetric candidate "
                      "first), not by picking the louder channel."),
                "e_statistics_hint_valid": hint_valid})

    solver = ev.get("solver") or {}
    best = solver.get("best") or {}
    s_sym = best.get("space_group")
    s_num = best.get("number")
    cand_num = None
    try:
        cand_num = int(group.type().number())
    except Exception:  # noqa: BLE001
        pass
    if s_sym:
        same = (s_num is not None and cand_num is not None
                and int(s_num) == cand_num)
        if same and absence == "violated":
            out.append({
                "id": "solver_choice_violates_absences",
                "channels": ["solver", "absences"],
                "note": (f"{solver.get('engine', 'the solver')} chose "
                         f"{s_sym}, but this file's reflections in its "
                         f"extinct class(es) carry signal "
                         f"(absence_evidence=violated). SHELXT does not "
                         f"use systematic absences at all, so the two "
                         f"channels are independent - a contradiction "
                         f"here usually means the cell/crystal system, "
                         f"not the group.")})
        if not same and absence == "absent":
            out.append({
                "id": "absences_support_a_group_the_solver_did_not_choose",
                "channels": ["absences", "solver"],
                "note": (f"the extinct class(es) of {symbol} are clean in "
                         f"this file, yet "
                         f"{solver.get('engine', 'the solver')} returned "
                         f"{s_sym}.")})
        if (best.get("is_centric") is not None and cand_centric is not None
                and bool(best["is_centric"]) != cand_centric):
            out.append({
                "id": "solver_centricity_vs_candidate",
                "channels": ["solver", "space_group_centricity"],
                "note": (f"{solver.get('engine', 'the solver')}'s "
                         f"{s_sym} is "
                         + ("centrosymmetric" if best["is_centric"]
                            else "non-centrosymmetric")
                         + f", {symbol} is not.")})

    r_int = ev.get("laue_r_int")
    if r_int is not None and float(r_int) > LAUE_R_INT_REFERENCE:
        out.append({
            "id": "laue_r_int_above_reference",
            "channels": ["laue_class", "candidate"],
            "note": (f"every candidate here lives in a Laue class whose "
                     f"R_int is {float(r_int):.3f}, above the 0.10 XPREP "
                     f"calls doubtful for a correct assignment - the "
                     f"class itself, not just the group, is in question "
                     f"(weak data, a wrong metric, or twinning).")})
    w_order = ev.get("working_laue_order")
    l_order = None
    try:
        l_order = int(laue_group.order_z())
    except Exception:  # noqa: BLE001
        pass
    if w_order and l_order and l_order > int(w_order):
        out.append({
            "id": "screened_laue_class_above_working_symmetry",
            "channels": ["laue_class", "working_symmetry"],
            "note": (f"screened in a Laue class of order {l_order} while "
                     f"the session works in one of order {w_order} "
                     f"({ev.get('working_space_group')}): metric "
                     f"pseudo-symmetry is exactly the pseudo-merohedral "
                     f"twin precondition, so this candidate's class may "
                     f"be higher than the crystal's.")})
    return out


def screen_space_groups(intensities, laue_group, viol_sigma: float = 3.0,
                        max_out: int = 10,
                        evidence: dict[str, Any] | None = None
                        ) -> dict[str, Any]:
    """Score candidate space groups against unmerged intensity data.

    intensities: cctbx miller array (intensities + sigmas, any symmetry -
    only its unit cell and indices are used). laue_group: sgtbx
    space_group of the data's Laue class in the SAME basis. evidence:
    optional channels from the session (solver verdicts, working
    symmetry, Laue R_int, the model for the composition-derived hint
    conditions) - they add DESCRIPTIVE `conflicts` per candidate and the
    hint's validity, and never change the ranking."""
    from cctbx import crystal, miller, sgtbx
    from cctbx.array_family import flex

    uc = intensities.unit_cell()
    idx = intensities.indices()
    i_obs = intensities.data()
    sig = intensities.sigmas()
    if sig is None:
        sig = flex.double(i_obs.size(), 1.0)

    from .absence_test import absence_class_summary, class_stats, contrast_verdict

    ios_all = i_obs / flex.double([max(s, 1e-9) for s in sig])
    rows = []
    groups_by_symbol: dict[str, Any] = {}
    for symbol, g in candidate_groups(uc.parameters(), laue_group):
        groups_by_symbol[symbol] = g
        cs = crystal.symmetry(unit_cell=uc,
                              space_group=g,
                              assert_is_compatible_unit_cell=False)
        ms = miller.set(cs, idx, anomalous_flag=False)
        absent = ms.sys_absent_flags().data()
        n_abs = absent.count(True)
        if n_abs == 0:
            # n_abs == 0 is ambiguous by itself: it means either the group
            # truly has no absence-generating symmetry (unfalsifiable by
            # this test, not evidence either way), or it HAS conditions
            # that this particular file never sampled (typical of
            # merged/fcf-derived data with absences stripped before
            # export - itself a real, positive fingerprint, not a null
            # result). absence_class_summary answers the group-theoretic
            # half, independent of the data (ka1-org P5: these two used
            # to be reported byte-identically as 'no_absence_conditions').
            cls = absence_class_summary(g)
            if cls["n_classes"]:
                entry = {
                    "space_group": symbol, "n_absent_obs": 0,
                    "n_violations": 0, "violation_rate": 0.0,
                    "consistent": False,
                    "absence_evidence": "absence_classes_unobserved",
                    "n_expected_absent_classes": cls["n_classes"],
                    "expected_absent_classes": cls["classes"],
                    "note": (
                        f"{symbol} has {cls['n_classes']} systematic-"
                        f"absence class(es) ({', '.join(cls['classes'])}) "
                        "but this reflection file contains ZERO "
                        "observations in any of them - typical of data "
                        "merged/reduced by a prior program (e.g. an "
                        "FCF-derived or otherwise pre-filtered export) "
                        "that stripped the absent reflections before "
                        f"export. This is CONSISTENT with {symbol} but is "
                        "NOT proof of it - decide from E-statistics, "
                        "Rint by Laue class and solution trials.")}
            else:
                entry = {"space_group": symbol, "n_absent_obs": 0,
                         "n_violations": 0, "violation_rate": 0.0,
                         "consistent": True,
                         "absence_evidence": "no_absence_conditions",
                         "note": "no absence conditions"}
            rows.append(entry)
            continue
        ios = ios_all.select(absent)
        n_viol = (ios > viol_sigma).count(True)
        rate = n_viol / n_abs
        # real data always carries a few strong outliers in a truly
        # absent class (lambda/2 harmonics, streaks): judge by the
        # CLASS - a genuinely absent class averages noise (<~2 sigma)
        # and keeps the violation fraction modest; a wrong glide/screw
        # shows mean 5-10+ sigma (W(CO)6 evidence: true P c m n class
        # mean 0.5 with 3.4% outliers vs wrong Pnma-setting mean 7.6).
        # But 'averages noise' needs a control: on weak data EVERY class
        # averages noise (pa2 hex: whole dataset <I/sig> 0.4, and seven
        # R-centred groups led the table), so the absent class is also
        # contrasted with the reflections the group keeps - three states,
        # not a boolean.
        a = class_stats(ios, viol_sigma)
        p = class_stats(ios_all.select(~absent), viol_sigma)
        v = contrast_verdict(a, p, viol_sigma)
        rows.append({
            "space_group": symbol,
            "n_absent_obs": n_abs,
            "n_violations": n_viol,
            "violation_rate": round(rate, 4),
            "mean_i_over_sig_absent": round(float(flex.mean(ios)), 2),
            "max_i_over_sig_absent": round(float(flex.max(ios)), 1),
            "mean_i_over_sig_present": p["mean_i_over_sig"],
            "strong_fraction_absent": a["strong_fraction"],
            "strong_fraction_present": p["strong_fraction"],
            "absent_to_present_ratio": v.get("ratio_mean"),
            "absence_evidence": v["verdict"],
            "consistent": v["verdict"] == "absent",
        })

    rows.sort(key=absence_rank_key)

    # centric/acentric hint from normalized-intensity statistics
    e_stats = None
    try:
        weak = weak_index_class(intensities)
        corrob = ([f"index class '{weak['class']}' carries "
                   f"{weak['mean_i_ratio']:.2f} of the average intensity "
                   f"over {weak['n']} reflections"] if weak else None)
        moments = intensity_moments(intensities, laue_group,
                                    corroboration=corrob)
        e2m1 = float(moments["mean_abs_e2_minus_1"]["value"])
        e_stats = {
            "mean_abs_e2_minus_1": round(e2m1, 3),
            "reference": dict(E2M1_REFERENCE),
            "hint": e2m1_hint(e2m1),
            "moments": {k: moments[k] for k in
                        ("mean_abs_e2_minus_1", "i2_over_i_sq",
                         "f_sq_over_f2") if k in moments},
        }
        readings = [moments[k] for k in ("mean_abs_e2_minus_1",
                                         "i2_over_i_sq", "f_sq_over_f2")
                    if k in moments]
        d_min = None
        try:
            d_min = float(intensities.d_max_min()[1])
        except Exception:  # noqa: BLE001 - a cell we cannot measure
            pass
        validity = e2m1_hint_validity(
            model=(evidence or {}).get("model"),
            n_reflections=moments.get("n_reflections"),
            d_min=d_min,
            e2m1_standard_error=moments["mean_abs_e2_minus_1"].get(
                "standard_error"),
            readings=readings, weak_class=weak,
            heavy_substructure_symmetry=(evidence or {}).get(
                "heavy_substructure_symmetry"),
            hint=e_stats["hint"])
        e_stats["hint_valid"] = validity["hint_valid"]
        e_stats["hint_validity"] = validity
        if weak:
            e_stats["weak_index_class"] = weak
        if e2m1 > 1.1:
            # pa2 hex/cage: 1.18-1.30 was read as "strongly centrosymmetric"
            e_stats["caveat"] = (
                f"{e2m1:.2f} is far ABOVE the centrosymmetric value 0.968 - "
                "that is not 'more centrosymmetric', it means the E "
                "distribution is dominated by noise/outliers (weak data, "
                "pseudo-symmetry, a wrong Laue class or a heavy-atom "
                "dominated cell): the centric/acentric hint is unreliable "
                "here; decide by solution trials (Marsh: centrosymmetric "
                "first)")
    except Exception:  # noqa: BLE001 - stats are advisory
        pass

    # Descriptive conflicts, computed AFTER the sort and written onto the
    # already-ranked rows: the ranking above must not depend on the
    # solver, on the E-statistics or on any supergroup prior (Palatinus &
    # van der Lee: database frequency priors overrode the measured
    # evidence in every program they tested).
    n_conflicts = 0
    for r in rows:
        try:
            c = candidate_conflicts(r["space_group"],
                                    groups_by_symbol.get(r["space_group"]),
                                    r, e_stats, evidence)
        except Exception:  # noqa: BLE001 - descriptive only
            c = []
        r["conflicts"] = c
        n_conflicts += len(c)

    # Data-level summary: of the candidates that HAVE absence conditions
    # (excludes the group-theoretic no_absence_conditions rows, which
    # never had anything to observe), how many actually landed an
    # observation in their absent class(es)? A whole-file "none" here is
    # itself diagnostic (fcf-derived/merged data with absences already
    # stripped) and means absences carry NO discriminating power for
    # this screen at all - a fact easy to miss when every candidate's row
    # individually still reads as a plausible, ranked "consistent" group.
    with_conditions = [r for r in rows
                       if r["absence_evidence"] != "no_absence_conditions"]
    n_observed = sum(1 for r in with_conditions
                     if (r.get("n_absent_obs") or 0) > 0)
    if not with_conditions:
        power, power_note = "none", (
            "every candidate space group compatible with this cell and "
            "Laue class has NO systematic absence conditions at all - "
            "absences provide no discriminating power here regardless of "
            "data quality; decide from E-statistics and solution trials.")
    elif n_observed == 0:
        power, power_note = "none", (
            "this file contains no systematically-absent-class "
            "reflections at all (typical of data merged/rejected by a "
            "prior refinement); space-group decisions here must rest on "
            "E-statistics, Rint by Laue class and solution trials.")
    elif n_observed == len(with_conditions):
        power, power_note = "full", (
            f"all {len(with_conditions)} candidate(s) with absence "
            "conditions have observed reflections in their absent "
            "class(es) - the absence screen carries its normal "
            "discriminating weight here.")
    else:
        power, power_note = "partial", (
            f"{n_observed}/{len(with_conditions)} candidate(s) with "
            "absence conditions have observed reflections in their "
            "absent class(es); the rest (absence_evidence="
            "'absence_classes_unobserved') cannot be judged from "
            "absences alone here - weigh E-statistics and solution "
            "trials for those.")

    return {
        "candidates": rows[:max_out],
        "n_candidates_total": len(rows),
        **({"e_statistics": e_stats} if e_stats else {}),
        "conflicts_summary": {
            "n_conflicts_listed": n_conflicts,
            "channels": ["absences", "e_statistics", "solver",
                         "laue_class", "working_symmetry"],
            "note": ("each candidate's `conflicts` lists disagreements "
                     "between the evidence channels. They are DESCRIPTIVE: "
                     "the ranking is computed from the absences alone and "
                     "is not changed by them, and no supergroup prior is "
                     "applied. A contradiction between channels is a "
                     "signal in its own right - the SHELXTL roe119 case "
                     "('the statistics are clearly centrosymmetric, but "
                     "only a non-centrosymmetric space group is consistent "
                     "with the systematic absences') turned out to be a "
                     "wrong crystal system with half the data collected, "
                     "not a group to be chosen by majority vote.")},
        "absence_screening_power": {"level": power, "note": power_note},
        "note": ("ranked by absence_evidence: 'absent' (the extinct class "
                 "is weak AND clearly weaker than the reflections the "
                 "group keeps) and 'no_absence_conditions' first - among "
                 "them the more specific group (more absences explained) "
                 "leads; then 'undecidable' and 'absence_classes_"
                 "unobserved' together (absent and present classes look "
                 "alike, or this file has zero reflections in the "
                 "group's absent class(es) at all - on weak or "
                 "merged/fcf-derived data this is the normal state and "
                 "it is NOT support for the group; a centred lattice in "
                 "either state would discard its 'absent' observations "
                 "from every later refinement); 'violated' last. See "
                 "absence_screening_power for whether this file can "
                 "distinguish candidates by absences AT ALL. "
                 "dials.symmetry only ranks Sohncke groups - "
                 "glides/inversion come from THIS table + E-statistics. "
                 "Adopt via change_space_group (it re-audits the "
                 "absences and refuses an undecidable or "
                 "classes-unobserved group unless accept_absences=true "
                 "with a reason)."),
    }


_EVIDENCE_RANK = {"absent": 0, "no_absence_conditions": 0,
                  "undecidable": 1, "absence_classes_unobserved": 1,
                  "violated": 2}


def absence_rank_key(row: dict) -> tuple:
    """Sort key: confirmed evidence first (more absences explained = more
    specific = earlier), undecidable groups next with the LARGEST absent
    classes last (the most observations at stake), violated groups at
    the end."""
    rank = _EVIDENCE_RANK.get(row.get("absence_evidence")
                              or ("absent" if row.get("consistent")
                                  else "violated"), 9)
    n_abs = int(row.get("n_absent_obs") or 0)
    return (rank, -n_abs if rank == 0 else n_abs, row.get("space_group", ""))


def read_shelx_hkl_intensities(hkl_path, cell):
    """Unmerged intensities from a SHELX HKLF4 file in P1 (cell given)."""
    from cctbx import crystal
    from iotbx.shelx import hklf

    ra = hklf.reader(file_name=str(hkl_path))
    cs = crystal.symmetry(unit_cell=cell, space_group_symbol="P 1")
    ma = ra.as_miller_arrays(crystal_symmetry=cs)[0]
    return ma.set_observation_type_xray_intensity()
