"""probe_site: refine a candidate atom at FREE occupancy on a throw-away branch.

pa3 (NU-1000, 2026-09): the brief said a post-modified guest with a heavy
atom was expected in the pore at low occupancy; the agent integrated the
two strongest void peaks (3.5 e / 1.7 e), measured them against the FULL-
occupancy electron count of the candidate element and wrote "absent". Its
own reasoning said "an occupancy around 0.1 is still possible" - and no
tool turned that sentence into an action. The human referee did what a
crystallographer does: put the atom at the site, let its occupancy and
Uiso refine, and read whether the occupancy settles, whether Uiso stays
physical and whether R moves. That is this tool. Nothing in it is
specific to one crystal: the element, the occupancy ladder (occupancy x
Z), the void test and the verdict fences are generic refinement
criteria.

Second lesson of the same run: once a solvent mask is stored, every
difference map is computed against Fc + F_mask, so density INSIDE the
masked void is suppressed by construction - a guest search on a masked
node cannot find a guest. probe_site therefore decides, per site, whether
the mask has to be switched off (mode 'auto'), and refines the reference
AND every candidate under the same mask setting so dR1 is like-for-like.

Flow (same skeleton as ghost_test / element_scan): _begin -> reference
refinement of the baseline (with the probed atom deleted in near_atom
mode) -> per element a diag/probe_site/<baseline>/<El>@<x,y,z> branch:
delete (near_atom), add <El>P1 with occupancy and Uiso free, refine ->
read occupancy, Uiso, site drift, dR1/dwR2/dGooF against the reference,
residual at the site before/after, omit-map electrons in a 1.0 A sphere
-> _restore. Three short refinements per candidate, the way it is done
by hand: (A) the occupancy alone with every site and Uiso fixed - a
one-parameter problem that converges at once, where a free full model
lets Levenberg-Marquardt damping starve a lone occupancy for ten cycles;
(B) the probe's site, Uiso and occupancy free with the rest of the model
held at the reference; (C) everything free, so dR1/dwR2 are like-for-like
with the reference. occupancy_at_fixed_u (A) against occupancy_refined
(C) says whether the number is stable against Uiso.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from ..tools.base import ToolContext, ToolResult
from .tools_batch import (DEFAULT_BUDGET_S, MAX_BUDGET_S, MAX_CYCLES,
                          MIN_BUDGET_S, OCC_ONLY_CYCLES, _BatchTool, _Refusal,
                          _atomic_number, _delta, _element_symbol, _neighbours,
                          _now, _resolve_labels, _sayer,
                          _valid_scattering_type, bracketing_elements,
                          count_is_low_biased, electron_bracket_note,
                          low_count_note)

MAX_PROBE_ELEMENTS = 4
DEFAULT_PROBE_CYCLES = 6
#: read radius for the omit-map integral and the site residual
PROBE_RADIUS_A = 1.0
OCC_START_DEFAULT = 0.2
OCC_START_MIN, OCC_START_MAX = 0.02, 1.0
U_START_DEFAULT = 0.10
U_START_MIN, U_START_MAX = 0.005, 0.5
#: occupancy ladder for the expected-electron table (occupancy x Z)
OCCUPANCY_LADDER = (0.1, 0.125, 0.25, 0.5, 1.0)
#: nearest-atom context around the probed site
CONTEXT_CUTOFF_A = 3.0
MAX_NEAREST = 4
#: a probe closer than this to a model atom is not a new site
OVERLAP_A = 0.5

#: verdict fences - generic refinement criteria, not tuned to any crystal
OCC_SUPPORTED = (0.03, 1.05)     # converged occupancy of a real atom
OCC_ABSENT = 0.02                # nothing there
U_SUPPORTED = (0.01, 0.35)       # physical isotropic displacement
U_UNPHYSICAL = 0.5
DR1_BETTER = -0.0005
DWR2_BETTER = -0.001
DR1_WORSE = 0.0005
DWR2_WORSE = 0.001
SITE_DRIFT_A = 0.5               # a localised atom stays put
OCC_STABILITY_ABS = 0.05         # |occ(U fixed) - occ(U free)| tolerance
OCC_STABILITY_REL = 0.5

#: bond-plausibility tolerances around the sum of covalent radii
BOND_TOL_A = 0.20
BOND_TOL_METAL_A = 0.30
TOO_SHORT_A = 0.35

#: geometric stand-in for the BYPASS flood fill (see void_membership)
VOID_RULE = (
    "a site counts as inside the masked void when some point within the "
    "mask's shrink radius of it lies farther than (vdW radius + solvent "
    "radius) from every model atom - the cctbx.masks.around_atoms rule "
    "the stored mask was built with (same vdW table, symmetry-aware, "
    "26-direction sampling); voids the mask dropped as too small or "
    "negative are not distinguished, so treat the flag as approximate")

DISPOSITION = {
    "supported": (
        "model it: add the atom at the refined occupancy "
        "(add_atoms_from_difference_map sites=[[x,y,z]] element=<El> "
        "occupancy=<occupancy_refined>, or edit_atoms set_occupancy "
        "afterwards), name it, restrain if a molecule is expected "
        "(fit_fragment), and re-run solvent_mask afterwards"),
    "not_supported": (
        "no localised atom of this element at this site at any occupancy "
        "the data can see; a diffuse guest stays in the mask and in "
        "unresolved"),
    "borderline": (
        "repeat with more cycles / after the framework is complete; report "
        "the occupancy range, do not conclude"),
    "inconclusive": "the test could not be completed - see error; nothing "
                    "was decided",
}

HOW_TO_READ = (
    "occupancy_at_fixed_u is the occupancy refined alone (every site and "
    "Uiso fixed, the probe's Uiso at u_iso_start - well-conditioned); "
    "occupancy_refined / u_iso_refined / site_shift_A are the result with "
    "everything free (stage_b: probe free, rest fixed; stage_c: all free). "
    "electrons_refined = occupancy x Z is the number "
    "the data pin down: two elements with the same electrons_refined are NOT "
    "distinguished by this test (decide by chemistry: bond_plausibility, the "
    "brief, the synthesis). omit_map_electrons is the positive Fo-Fc density "
    "in a 1.0 A sphere at the site with NOTHING modelled there; compare it "
    "with expected_electrons_at_occupancy, never with the full-occupancy Z. "
    "delta_* are against the reference refinement (same cycles, same mask "
    "setting).")


# ==========================================================================
# shared helpers (also used by integrate_difference_density)
# ==========================================================================

def expected_electrons_table(element: str) -> dict[str, float] | None:
    """occupancy -> electrons for any element: {'0.1': 3.5, ..., '1.0': 35}."""
    z = _atomic_number(_element_symbol(element))
    if not z:
        return None
    return {str(occ): round(occ * z, 1) for occ in OCCUPANCY_LADDER}


def occupancy_note(element: str | None = None) -> str:
    """The sentence that stops 'compare with the full-occupancy value'.
    Illustrated with the given element (Br when none is given)."""
    el = _element_symbol(element) if element else "Br"
    z = _atomic_number(el) or 35
    return (f"occupancy x Z is what the data pin down; a 0.125-occupancy "
            f"{el} is {0.125 * z:.1f} e, not {z} e - compare "
            f"omit_map_electrons with the expected table, never with the "
            f"full-occupancy value")


def _covalent_radius(el: str) -> float | None:
    try:
        from cctbx.eltbx import covalent_radii
        return float(covalent_radii.table(el).radius())
    except Exception:  # noqa: BLE001 - unknown symbol
        return None


def _vdw_radius(el: str) -> float:
    from cctbx.eltbx import van_der_waals_radii
    return float(van_der_waals_radii.vdw.table.get(el, 1.7))


def _expanded_cart(xs, site_frac) -> tuple[np.ndarray, list[int]]:
    """Every symmetry image (+/- one cell) of every atom, as Cartesian
    coordinates near the given fractional site; returns (n, 3) array and
    the scatterer index of each row."""
    uc = xs.unit_cell()
    ops = xs.space_group().all_ops()
    site = np.array([float(c) for c in site_frac])
    orth = np.array(uc.orthogonalization_matrix()).reshape(3, 3)
    frac = np.array([[float(c) for c in sc.site] for sc in xs.scatterers()])
    if frac.size == 0:
        return np.zeros((0, 3)), []
    shifts = np.array([(dx, dy, dz) for dx in (-1, 0, 1)
                       for dy in (-1, 0, 1) for dz in (-1, 0, 1)], float)
    rows, idx = [], []
    for op in ops:
        r = np.array(op.r().as_double()).reshape(3, 3)
        t = np.array(op.t().as_double())
        img = frac @ r.T + t
        img -= np.round(img - site)          # nearest image to the site
        for sh in shifts:
            rows.append((img + sh) @ orth.T)
            idx.extend(range(len(frac)))
    return np.vstack(rows), idx


def void_membership(xs, site_frac, solvent_radius: float = 1.2,
                    shrink: float = 1.2) -> dict[str, Any]:
    """Is a fractional site inside the region a BYPASS mask would cover?

    cctbx.masks.around_atoms marks a grid point as solvent when it is
    farther than (vdW radius + solvent_radius) from every atom, then grows
    that region back by shrink_truncation_radius. So a site is masked
    when some point within `shrink` of it is 'deep' solvent. Sampled on
    26 directions x two shells plus the site itself; symmetry-aware; the
    same vdW table smtbx uses. Approximate (voids the mask dropped as too
    small / negative are not known here) - say so when quoting it."""
    uc = xs.unit_cell()
    p = np.array(uc.orthogonalize(tuple(float(c) for c in site_frac)))
    cart, idx = _expanded_cart(xs, site_frac)
    scs = list(xs.scatterers())
    if len(idx) == 0:
        return {"inside": True, "nearest_atom": None, "nearest_d_A": None,
                "clearance_A": None, "note": "empty model"}
    radii = np.array([_vdw_radius(_element_symbol(scs[i].scattering_type))
                      for i in idx])
    d = np.linalg.norm(cart - p, axis=1)
    k = int(np.argmin(d))
    clearance = d - radii
    j = int(np.argmin(clearance))
    reach = shrink + solvent_radius + float(radii.max()) + 0.1
    local = d <= reach
    dirs = [np.array(v, float) for v in
            ((dx, dy, dz) for dx in (-1, 0, 1) for dy in (-1, 0, 1)
             for dz in (-1, 0, 1)) if any(v)]
    samples = [p]
    for u in dirs:
        u = u / np.linalg.norm(u)
        samples.append(p + shrink * u)
        samples.append(p + 0.5 * shrink * u)
    inside = False
    if not local.any():
        inside = True
    else:
        lc, lr = cart[local], radii[local]
        for q in samples:
            if float(np.min(np.linalg.norm(lc - q, axis=1) - lr)) \
                    > solvent_radius:
                inside = True
                break
    return {"inside": bool(inside),
            "nearest_atom": scs[idx[k]].label,
            "nearest_d_A": round(float(d[k]), 2),
            # distance beyond the nearest vdW surface (negative = inside a
            # vdW sphere)
            "clearance_A": round(float(clearance[j]), 2),
            "solvent_radius": solvent_radius, "shrink": shrink}


def resolve_mask_mode(ses, xs, sites_frac, mode: str | None
                      ) -> tuple[bool, dict[str, Any]]:
    """mask='auto' | 'off' | 'on' -> (use the stored mask?, handling
    block for the summary). Raises _Refusal on a bad mode."""
    mode = str(mode or "auto").strip().lower()
    if mode not in ("auto", "off", "on"):
        raise _Refusal("mask must be 'auto' (default: switch the mask off "
                       "when a probed site lies inside the masked void), "
                       "'off' or 'on'")
    has_mask = ses.flags.get("f_mask") is not None
    info: dict[str, Any] = {"mode": mode, "session_has_mask": has_mask}
    if not has_mask:
        info.update({"mask_used": False,
                     "note": "no solvent mask stored in the session - the "
                             "difference map is Fo - Fc(model) already"})
        return False, info
    params = ses.flags.get("solvent_mask_params") or {}
    solv = float(params.get("solvent_radius") or 1.2)
    shrink = float(params.get("shrink_truncation_radius") or 1.2)
    tests = [void_membership(xs, s, solv, shrink) for s in sites_frac]
    any_inside = any(t["inside"] for t in tests)
    info["void_test"] = tests
    info["sites_in_masked_void"] = [t["inside"] for t in tests]
    info["rule"] = VOID_RULE
    where = "; ".join(
        f"site {i + 1}: {'inside' if t['inside'] else 'outside'} "
        f"(nearest {t['nearest_atom']} {t['nearest_d_A']} A, clearance "
        f"beyond its vdW surface {t['clearance_A']} A)"
        for i, t in enumerate(tests))
    if mode == "off":
        use = False
        info["note"] = ("mask switched OFF on request: the map is Fo - "
                        "Fc(model only), so everything the mask absorbed "
                        "(solvent AND any guest) reappears - " + where)
    elif mode == "on":
        use = True
        info["note"] = "mask kept ON on request - " + where
        if any_inside:
            info["warning"] = (
                "a probed site lies INSIDE the masked void: the mask "
                "already accounts for the density there, so a probe can "
                "only see what the mask left (expect an occupancy near "
                "zero, an integral near zero) - this is the construction "
                "of the mask, not evidence of absence; mask='auto'/'off' "
                "switches it off")
    else:
        use = not any_inside
        info["note"] = (
            ("mask switched OFF automatically: a probed site lies inside "
             "the masked void, where residual density is suppressed by "
             "construction; the map / the reference and every candidate "
             "are computed without the mask so the numbers are "
             "comparable - " if any_inside else
             "mask kept: no probed site lies inside the masked void, so "
             "the stored mask stays part of Fc as in the baseline - ")
            + where)
    info["mask_used"] = use
    return use, info


def sphere_stats(real_map, unit_cell, sites_frac, radius: float
                 ) -> list[dict[str, Any]]:
    """Per-site reading of a real-space map inside a sphere: positive and
    negative electron integrals, extremes, interpolated value at the
    point. One map, many sites - callers compute the map once."""
    from cctbx import maptbx
    from cctbx.array_family import flex
    vpp = unit_cell.volume() / real_map.size()      # A^3 per grid point
    out = []
    for s in sites_frac:
        s = tuple(float(c) for c in s)
        cart = unit_cell.orthogonalize(s)
        sel = maptbx.grid_indices_around_sites(
            unit_cell=unit_cell, fft_n_real=real_map.focus(),
            fft_m_real=real_map.all(),
            sites_cart=flex.vec3_double([cart]),
            site_radii=flex.double([float(radius)]))
        vals = real_map.select(sel)
        if vals.size() == 0:
            out.append({"error": "empty sphere"})
            continue
        out.append({
            "radius_A": float(radius),
            "electrons_positive": round(
                float(flex.sum(vals.select(vals > 0))) * vpp, 2),
            "electrons_negative": round(
                float(flex.sum(vals.select(vals < 0))) * vpp, 2),
            "max": round(float(flex.max(vals)), 2),
            "min": round(float(flex.min(vals)), 2),
            "at_site": round(float(real_map.eight_point_interpolation(s)), 2),
            "n_grid_points": int(vals.size()),
        })
    return out


def sphere_density(ses, xs, sites_frac, radius: float, f_mask
                   ) -> list[dict[str, Any]]:
    """Fo-Fc map of the given model (with or without the mask) read in
    spheres at the sites - the omit-map electron count of probe_site and
    the per-site rows of integrate_difference_density(mask=...)."""
    from ..tools.refinement_tools import difference_map_real
    try:
        _fft, real, _k = difference_map_real(ses, xs, f_mask=f_mask)
    except ValueError as e:
        return [{"error": str(e)} for _ in sites_frac]
    return sphere_stats(real, xs.unit_cell(), sites_frac, radius)


def bond_plausibility(element: str, nearest_atoms: list[dict[str, Any]]
                      ) -> list[dict[str, Any]]:
    """Each neighbour's distance against the sum of covalent radii of the
    pair (+/- a tolerance), or the metal-ligand coordination window from
    chem.knowledge when a metal meets O/N. Generic for any pair."""
    from ..chem.knowledge import METAL_PROFILES, is_metal
    el = _element_symbol(element)
    r_el = _covalent_radius(el)
    out = []
    for nb in nearest_atoms:
        other = nb["element"]
        d = float(nb["d_A"])
        pair = f"{el}-{other}"
        window = None
        for m, lig in ((el, other), (other, el)):
            prof = METAL_PROFILES.get(m)
            if prof is None:
                continue
            if lig == "O":
                window = (prof.m_o_range, f"{m}-O coordination window")
            elif lig == "N" and prof.m_n_range:
                window = (prof.m_n_range, f"{m}-N coordination window")
        row: dict[str, Any] = {"partner": nb["label"], "pair": pair,
                               "d_A": round(d, 2)}
        if window:
            (lo, hi), what = window
            row["reference"] = f"{what} {lo:.2f}-{hi:.2f} A"
            if lo <= d <= hi:
                row["assessment"] = "bond-length match"
            elif d < lo - TOO_SHORT_A:
                row["assessment"] = "too short: clash"
            elif d < lo:
                row["assessment"] = "shorter than the window"
            else:
                row["assessment"] = "longer than a bond: non-bonded contact"
        else:
            r_o = _covalent_radius(other)
            if r_el is None or r_o is None:
                row["assessment"] = "no reference distance for this pair"
                out.append(row)
                continue
            expected = r_el + r_o
            tol = BOND_TOL_METAL_A if (is_metal(el) or is_metal(other)) \
                else BOND_TOL_A
            row["reference"] = (f"sum of covalent radii {expected:.2f} A "
                                f"+/- {tol:.2f}")
            if abs(d - expected) <= tol:
                row["assessment"] = "bond-length match"
            elif d < expected - TOO_SHORT_A:
                row["assessment"] = "too short: clash"
            elif d < expected:
                row["assessment"] = "shorter than a bond"
            else:
                row["assessment"] = "longer than a bond: non-bonded contact"
        out.append(row)
    return out


def probe_verdict(row: dict[str, Any]) -> tuple[str, str]:
    """supported / not_supported / borderline from generic refinement
    criteria: did the occupancy converge to something an atom can have,
    is Uiso physical, did R and the site residual improve, did the atom
    stay where it was put, is the occupancy stable against Uiso."""
    occ = row.get("occupancy_refined")
    occ_a = row.get("occupancy_at_fixed_u")
    u = row.get("u_iso_refined")
    dr1, dwr2 = row.get("delta_r1"), row.get("delta_wr2")
    before = (row.get("residual_before") or {}).get("max")
    after = (row.get("residual_after") or {}).get("max")
    drift = row.get("site_shift_A")
    if occ is None or dr1 is None:
        return "inconclusive", "refinement or map read failed - see error"
    # -- nothing there
    if occ < OCC_ABSENT:
        held = (f"; {occ_a:.3f} with Uiso held, gone once it was freed"
                if occ_a is not None and occ_a >= OCC_ABSENT else "")
        return "not_supported", (
            f"occupancy refined to {occ:.3f} (< {OCC_ABSENT}{held}) - at no "
            f"occupancy does a localised atom of this element fit the "
            f"density at this site")
    if u is not None and u > U_UNPHYSICAL:
        return "not_supported", (
            f"Uiso refined to {u:.2f} (> {U_UNPHYSICAL}): the atom smeared "
            f"itself out instead of finding a localised density - the "
            f"occupancy {occ:.3f} is compensating a non-existent peak")
    if dr1 > DR1_WORSE and (dwr2 is None or dwr2 > DWR2_WORSE):
        moved = (f"dR1 {dr1:+.4f}, dwR2 {dwr2:+.4f}" if dwr2 is not None
                 else f"dR1 {dr1:+.4f}")
        return "not_supported", (
            f"R worsened against the reference ({moved}): the atom is "
            f"fighting the data")
    # -- supported: every criterion at once
    problems: list[str] = []
    if not OCC_SUPPORTED[0] <= occ <= OCC_SUPPORTED[1]:
        if occ > OCC_SUPPORTED[1]:
            problems.append(
                f"occupancy {occ:.3f} > 1: the element is too LIGHT for "
                f"the density here (or the site holds something heavier) - "
                f"occupancy x Z = {row.get('electrons_refined')} e is what "
                f"the data pin down; try the next heavier candidate")
        else:
            problems.append(f"occupancy {occ:.3f} is between the absent "
                            f"fence ({OCC_ABSENT}) and the supported floor "
                            f"({OCC_SUPPORTED[0]})")
    if u is None:
        problems.append("Uiso was not freed (occupancy vanished with site "
                        "and Uiso fixed)")
    elif not U_SUPPORTED[0] <= u <= U_SUPPORTED[1]:
        problems.append(f"Uiso {u:.3f} outside the physical window "
                        f"{U_SUPPORTED[0]}-{U_SUPPORTED[1]}"
                        + (" (too small: element too light for the "
                           "density, or occupancy too low)" if u < U_SUPPORTED[0]
                           else " (large: diffuse density, disorder, or "
                                "the occupancy is compensating)"))
    r_better = (dr1 <= DR1_BETTER) or (dwr2 is not None and dwr2 <= DWR2_BETTER)
    if not r_better:
        problems.append(f"R did not improve measurably (dR1 {dr1:+.4f}, "
                        f"dwR2 {dwr2:+.4f})" if dwr2 is not None else
                        f"R1 did not improve measurably (dR1 {dr1:+.4f})")
    if before is not None and after is not None and not after < before:
        problems.append(f"the residual maximum at the site did not fall "
                        f"({before:.2f} -> {after:.2f} e/A^3)")
    if drift is not None and drift > SITE_DRIFT_A:
        problems.append(f"the atom drifted {drift:.2f} A from the probed "
                        f"site when its coordinates were freed: the density "
                        f"is not localised where it was placed")
    if occ_a is not None and occ is not None:
        if abs(occ - occ_a) > max(OCC_STABILITY_ABS, OCC_STABILITY_REL
                                  * max(abs(occ_a), 1e-9)):
            problems.append(
                f"occupancy depends on Uiso ({occ_a:.3f} with Uiso fixed "
                f"at the start value, {occ:.3f} free): report the range, "
                f"not one number")
    if not problems:
        return "supported", (
            f"occupancy converged to {occ:.3f} ({row.get('electrons_refined')}"
            f" e), Uiso {u:.3f} is physical, R improved (dR1 {dr1:+.4f}, "
            f"dwR2 {dwr2:+.4f}) and the site residual fell "
            f"({before} -> {after} e/A^3)"
            + (f"; the atom stayed put ({drift:.2f} A)" if drift is not None
               else ""))
    return "borderline", "; ".join(problems)


def _fmt_site(site) -> str:
    return ",".join(f"{float(c):.3f}" for c in site)


# ==========================================================================
class ProbeSite(_BatchTool):
    name = "probe_site"
    tag = "probe_site"
    description = (
        "Low-occupancy guest / hetero-atom trial: put ONE candidate element "
        "(or up to 4, one branch each) at a site, refine its OCCUPANCY and "
        "Uiso free on a throw-away branch and read whether the occupancy "
        "converges, whether Uiso stays physical and whether R1/wR2 and the "
        "site residual improve against a reference refinement of the "
        "baseline (same cycles, same mask setting). Position: site=[x,y,z], "
        "peak=<'i' of the session peak table shown by inspect_map>, or "
        "near_atom=<label> (re-type that atom: it is deleted and the "
        "candidate refined at free occupancy in its place). Reports "
        "occupancy x Z, an occupancy->electrons table for the element, the "
        "omit-map electrons in a 1.0 A sphere (what is really there), "
        "nearest atoms with bond plausibility, and a verdict with its "
        "reason and disposition. Solvent mask: mask='auto' switches the "
        "mask OFF when the site lies inside the masked void (density there "
        "is suppressed by construction - a masked map cannot find a guest); "
        "'off' / 'on' force it. This is the test a crystallographer runs "
        "before saying 'absent': a 0.125-occupancy heavy atom is a few "
        "electrons, never the full-occupancy count. Diagnostic nodes stay "
        "on diag/probe_site/<baseline>/<El>@<x,y,z>; the baseline is "
        f"checked out again on return. BUDGET: max {MAX_PROBE_ELEMENTS} "
        f"elements and time_budget_s (default {DEFAULT_BUDGET_S} s), checked "
        "BEFORE each candidate because an in-process refinement cannot be "
        "interrupted - at the budget you get the rows that finished plus the "
        "named candidates that were not started, so re-issue with just "
        "those; in-process engine only.")
    params_schema = {
        "type": "object",
        "properties": {
            "element": {"type": "string",
                        "description": "candidate element symbol, e.g. 'Br'"},
            "elements": {"type": "array", "items": {"type": "string"},
                         "description": "several candidates, one diagnostic "
                                        f"branch each (max {MAX_PROBE_ELEMENTS}"
                                        "); may be combined with element"},
            "site": {"type": "array", "items": {"type": "number"},
                     "minItems": 3, "maxItems": 3,
                     "description": "fractional coordinates [x,y,z] of the "
                                    "probed site"},
            "peak": {"type": "integer",
                     "description": "index 'i' of a peak in the session's "
                                    "difference-map table (as listed by "
                                    "inspect_map / stored with the node)"},
            "near_atom": {"type": "string",
                          "description": "label of an existing atom: probe "
                                         "the candidate element AT its "
                                         "position with the original atom "
                                         "deleted (re-type + free occupancy)"},
            "occupancy_start": {"type": "number", "default": OCC_START_DEFAULT,
                                "description": f"starting occupancy "
                                               f"({OCC_START_MIN}-{OCC_START_MAX})"},
            "u_iso_start": {"type": "number", "default": U_START_DEFAULT,
                            "description": "starting Uiso (A^2); also the "
                                           "value held fixed in the first, "
                                           "occupancy-only refinement"},
            "cycles": {"type": "integer", "default": DEFAULT_PROBE_CYCLES,
                       "description": "refinement cycles for the reference "
                                       "and for each free stage (1-20); the "
                                       f"occupancy-only stage always runs "
                                       f"{OCC_ONLY_CYCLES}"},
            "node_id": {"type": "string",
                        "description": "baseline node or branch (default: "
                                       "the active node)"},
            "mask": {"type": "string", "enum": ["auto", "off", "on"],
                     "default": "auto",
                     "description": "'auto' (default): if the session holds "
                                    "a solvent mask and the site lies inside "
                                    "the masked void, reference and "
                                    "candidates refine WITHOUT the mask; "
                                    "'off' / 'on' force it"},
            "time_budget_s": {"type": "integer", "default": DEFAULT_BUDGET_S,
                              "description": f"wall-clock budget ({MIN_BUDGET_S}"
                                             f"-{MAX_BUDGET_S} s); candidates "
                                             "that would overrun it are not "
                                             "started and are listed back"},
        },
    }

    # -- parameters --------------------------------------------------------
    @staticmethod
    def _elements(params: dict[str, Any]) -> list[str]:
        raw: list[Any] = []
        if params.get("element"):
            raw.append(params["element"])
        raw += list(params.get("elements") or [])
        elements: list[str] = []
        for e in raw:
            el = _element_symbol(str(e))
            if el and el not in elements:
                elements.append(el)
        if not elements:
            raise _Refusal("give the candidate element in 'element' (e.g. "
                           "'Br') or a list in 'elements'")
        bad = [e for e in elements if not _valid_scattering_type(e)]
        if bad:
            raise _Refusal(f"unknown element symbol(s) {bad}: nothing was "
                           f"run. Use IT1992 scattering-factor symbols "
                           f"(e.g. 'Br', 'Cl', 'Zr').")
        if len(elements) > MAX_PROBE_ELEMENTS:
            raise _Refusal(
                f"{len(elements)} candidates exceed the per-call maximum of "
                f"{MAX_PROBE_ELEMENTS}: nothing was run. Pre-select by the "
                f"brief and the chemistry; candidates with the same "
                f"occupancy x Z are not separated by this test anyway.")
        return elements

    @staticmethod
    def _starts(params: dict[str, Any]) -> tuple[float, float, int]:
        occ = params.get("occupancy_start")
        occ = OCC_START_DEFAULT if occ is None else float(occ)
        if not OCC_START_MIN <= occ <= OCC_START_MAX:
            raise _Refusal(f"occupancy_start must be {OCC_START_MIN}-"
                           f"{OCC_START_MAX} (got {occ})")
        u = params.get("u_iso_start")
        u = U_START_DEFAULT if u is None else float(u)
        if not U_START_MIN <= u <= U_START_MAX:
            raise _Refusal(f"u_iso_start must be {U_START_MIN}-{U_START_MAX} "
                           f"A^2 (got {u})")
        cycles = params.get("cycles")
        cycles = DEFAULT_PROBE_CYCLES if cycles is None else int(cycles)
        if not 1 <= cycles <= MAX_CYCLES:
            raise _Refusal(f"cycles must be 1-{MAX_CYCLES} (got {cycles})")
        return occ, u, cycles

    @staticmethod
    def _budget(params: dict[str, Any]) -> int:
        budget = params.get("time_budget_s")
        budget = DEFAULT_BUDGET_S if budget is None else int(budget)
        if not MIN_BUDGET_S <= budget <= MAX_BUDGET_S:
            raise _Refusal(f"time_budget_s must be {MIN_BUDGET_S}-"
                           f"{MAX_BUDGET_S} s (got {budget})")
        return budget

    @staticmethod
    def _position(params: dict[str, Any], ses) -> dict[str, Any]:
        """site / peak / near_atom -> {'mode', 'site', 'omit'?...}, resolved
        against the BASELINE session (peak table, labels)."""
        given = [k for k in ("site", "peak", "near_atom")
                 if params.get(k) is not None]
        if len(given) != 1:
            raise _Refusal("give exactly one position: site=[x,y,z], "
                           "peak=<index in the session peak table> or "
                           "near_atom=<atom label>"
                           + (f" (got {given})" if given else ""))
        xs = ses.model
        if "site" in given:
            raw = params["site"]
            try:
                site = tuple(float(c) for c in raw)
            except (TypeError, ValueError):
                site = ()
            if len(site) != 3 or not isinstance(raw, (list, tuple)):
                raise _Refusal(f"site must be three fractional coordinates "
                               f"[x, y, z], got {raw!r}")
            return {"mode": "site", "site": site}
        if "peak" in given:
            peaks = ses.flags.get("diff_map_peaks") or []
            if not peaks:
                raise _Refusal(
                    "the baseline has no difference-map peak table (none "
                    "stored with the node): run inspect_map on it first - "
                    "each listed peak's 'i' is the peak index - or pass "
                    "site=[x,y,z]")
            try:
                i = int(params["peak"])
            except (TypeError, ValueError):
                raise _Refusal(f"peak must be an integer index, got "
                               f"{params['peak']!r}")
            if not 0 <= i < len(peaks):
                raise _Refusal(f"peak index {i} is outside the stored table "
                               f"(indices 0-{len(peaks) - 1}, as inspect_map "
                               f"lists them under 'i')")
            p = peaks[i]
            return {"mode": "peak", "site": tuple(float(c) for c in p["site"]),
                    "peak_index": i, "peak_height": p.get("height"),
                    "peak_nearest": p.get("nearest_atom"),
                    "peak_nearest_d": p.get("nearest_d")}
        found, missing, close = _resolve_labels(xs, [str(params["near_atom"])])
        if missing:
            raise _Refusal(f"near_atom {missing[0]!r} is not in the baseline "
                           f"model (close labels: {close.get(missing[0])}); "
                           f"inspect_model detail='atoms' lists the labels")
        sc = next(s for s in xs.scatterers()
                  if s.label.upper() == found[0].upper())
        return {"mode": "near_atom", "site": tuple(float(c) for c in sc.site),
                "omit": {"label": sc.label,
                         "element": _element_symbol(sc.scattering_type),
                         "occupancy": round(float(sc.occupancy), 3),
                         "u_iso": round(float(sc.u_iso_or_equiv(
                             xs.unit_cell())), 4)}}

    # -- model edits -------------------------------------------------------
    @staticmethod
    def _probe_label(xs, el: str) -> str:
        taken = {sc.label.upper() for sc in xs.scatterers()}
        n = 1
        while True:
            lbl = f"{el.upper()}P{n}"
            if lbl not in taken:
                return lbl
            n += 1

    @staticmethod
    def _add_probe(xs, label: str, el: str, site, occ: float, u: float) -> None:
        from cctbx import xray
        xs.add_scatterer(xray.scatterer(label=label, site=site, u=u,
                                        occupancy=occ, scattering_type=el))
        for sc in xs.scatterers():
            if sc.label.upper() == label.upper():
                sc.flags.set_grad_occupancy(True)

    @staticmethod
    def _probe_state(xs, label: str) -> dict[str, Any] | None:
        for sc in xs.scatterers():
            if sc.label.upper() == label.upper():
                return {"occupancy": float(sc.occupancy),
                        "u_iso": float(sc.u_iso_or_equiv(xs.unit_cell())),
                        "site": tuple(float(c) for c in sc.site)}
        return None

    @staticmethod
    def _drop_mask(ses) -> None:
        """Diagnostic branch without the mask: the flags go so that refine,
        the map reads and the committed node all agree (the baseline gets
        its mask back from its own snapshot on restore)."""
        for k in ("f_mask", "solvent_mask_info", "solvent_mask_params"):
            ses.flags.pop(k, None)

    def _refine_probe(self, cycles: int, progress,
                      fix_atoms: list[str] | None = None) -> dict[str, Any]:
        """One in-process refinement; fix_atoms holds site AND Uiso of
        those atoms (the refine tool fixes both or neither) - occupancy
        stays free wherever its gradient flag is set."""
        t0 = _now()
        params: dict[str, Any] = {"mode": "isotropic", "n_cycles": cycles}
        if fix_atoms:
            params["fix_atoms"] = list(fix_atoms)
        r = self.project.invoke_tool("refine", params, progress=progress)
        if not r.ok:
            return {"ok": False, "error": r.error, "elapsed_s": _now() - t0}
        m = {k: r.summary.get(k)
             for k in ("r1_strong", "r1_all", "wr2", "goof", "n_params",
                       "diff_map_max", "diff_map_min")}
        m.update({"ok": True, "node": r.summary.get("node"),
                  "branch": r.summary.get("branch"),
                  "n_atoms": r.summary.get("n_atoms"),
                  "elapsed_s": _now() - t0})
        return m

    def _delete(self, label: str, progress) -> str | None:
        # WP6: the omit is the test itself, on an isolated diagnostic
        # branch - the ghost ledger's 'real' verdicts must neither block it
        # nor be disposed of by it (the ledger guard notes the touch)
        r = self.project.invoke_tool(
            "edit_atoms", {"operations": [{"action": "delete",
                                           "atoms": [label]}],
                           "_diagnostic": True,
                           "_diagnostic_reason": f"probe_site omits {label} "
                                                 "on a diagnostic branch"},
            progress=progress)
        if not r.ok:
            raise _Refusal(f"delete of {label} failed: {r.error}")
        return r.summary.get("node")

    # -- run ---------------------------------------------------------------
    def run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        progress = getattr(ctx, "progress", None)
        say = _sayer(progress)
        try:
            elements = self._elements(params)
            occ_start, u_start, cycles = self._starts(params)
            budget = self._budget(params)
            baseline, pre, t_checkout = self._begin(params)
        except _Refusal as e:
            return ToolResult.failure(str(e))
        t_start = _now()
        project = self.project
        ses = project.session
        try:
            if ses is None or ses.model is None:
                raise _Refusal("no model to probe on - import or solve first")
            if ses.fo_sq is None:
                raise _Refusal("no reflection data in the session")
            if ses.flags.get("twin") or int(ses.flags.get("hklf") or 4) == 5:
                raise _Refusal(
                    "probe_site refines in-process (occupancy free) and the "
                    "in-process engine does not refine twinned / HKLF5 "
                    "data; with SHELXL put the candidate on a free variable "
                    "(FVAR) yourself on a branch")
            pos = self._position(params, ses)
            omit = pos.get("omit")
            excl = {omit["label"].upper()} if omit else set()
            nearest = _neighbours(ses.model, pos["site"], excl,
                                  cutoff=CONTEXT_CUTOFF_A)[:MAX_NEAREST]
            if nearest and nearest[0]["d_A"] < OVERLAP_A:
                raise _Refusal(
                    f"the probed site is {nearest[0]['d_A']} A from "
                    f"{nearest[0]['label']} - that is ON an existing atom, "
                    f"not a new site: use near_atom='{nearest[0]['label']}' "
                    f"to re-type it at free occupancy, or element_scan")
            use_mask, mask_info = resolve_mask_mode(
                ses, ses.model, [pos["site"]], params.get("mask"))
        except _Refusal as e:
            restore = self._restore(baseline, pre, checkout=False)
            return ToolResult.failure(
                f"{e} - nothing was run; the baseline {baseline} stays "
                f"checked out ({restore.get('branch')})")

        site = pos["site"]
        site_txt = _fmt_site(site)
        summary: dict[str, Any] = {
            "baseline": {"node": baseline,
                         "branch_before": pre.get("active_branch"),
                         "engine": "refine", "cycles": cycles},
            "position": {"mode": pos["mode"],
                         "site_frac": [round(c, 4) for c in site],
                         **{k: v for k, v in pos.items()
                            if k not in ("mode", "site")},
                         "nearest_atoms": nearest},
            "mask_handling": mask_info,
        }
        rows: list[dict[str, Any]] = []
        verdicts: dict[str, str] = {}
        not_tested: list[str] = []
        try:
            # -- reference: the baseline without anything at the site,
            #    under the same mask setting as the candidates
            ref_branch = f"diag/probe_site/{baseline}/reference"
            self._cut(ref_branch, baseline, checkout=False)
            if not use_mask:
                self._drop_mask(ses)
            what = (f"{omit['label']} deleted" if omit else "as is")
            say(f"probe_site: reference refinement of {baseline} ({what}; "
                f"{cycles} cycles, mask {'on' if use_mask else 'off'}) "
                f"before {len(elements)} candidate(s)")
            if omit:
                self._mark(self._delete(omit["label"], progress), baseline,
                           "reference", "delete")
            ref = self._refine_probe(cycles, progress)
            if not ref["ok"]:
                summary["error_stage"] = "reference"
                return ToolResult(ok=False, summary=summary, error=(
                    f"reference refinement of {baseline} failed "
                    f"({ref['error']}) - nothing to compare against, no "
                    f"candidate was run"))
            self._mark(ref["node"], baseline, "reference", "refine")
            ses_ref = project.session
            ref_read = sphere_density(
                ses_ref, ses_ref.model, [site], PROBE_RADIUS_A,
                f_mask=ses_ref.flags.get("f_mask"))[0]
            summary["baseline"]["reference"] = {
                "node": ref["node"], "branch": ref_branch,
                "omitted": omit["label"] if omit else None,
                "r1_strong": ref.get("r1_strong"), "wr2": ref.get("wr2"),
                "goof": ref.get("goof"), "n_atoms": ref.get("n_atoms"),
                "solvent_mask": ses_ref.flags.get("f_mask") is not None,
                "residual_max_anywhere": ref.get("diff_map_max"),
                "residual_min_anywhere": ref.get("diff_map_min"),
                "site_read": ref_read,
                "elapsed_s": round(ref["elapsed_s"], 1),
                "note": ("deltas are against THIS refinement; site_read is "
                         "the omit map at the probed site (nothing modelled "
                         "there) - its electrons_positive is the "
                         "omit_map_electrons of every row"),
            }

            # -- candidates
            t_last = 0.0
            for ei, el in enumerate(elements):
                elapsed = _now() - t_start
                per_cycle = ref["elapsed_s"] / max(cycles, 1)
                est = max((OCC_ONLY_CYCLES + 2 * cycles) * per_cycle
                          + t_checkout, t_last) * 1.1
                if self._budget_exhausted(elapsed, est, budget):
                    not_tested = elements[ei:]
                    summary["timeout"] = self._timeout_message(
                        "probe_site", len(rows), len(elements), elapsed,
                        max(est / 1.1, 1e-9), budget, not_tested, "elements")
                    break
                tc0 = _now()
                cand = f"{el}@{site_txt}"
                branch = f"diag/probe_site/{baseline}/{cand}"
                z = _atomic_number(el) or 0
                row: dict[str, Any] = {
                    "element": el, "z": z, "branch": branch,
                    "site_frac": [round(c, 4) for c in site],
                    "occupancy_start": occ_start, "u_iso_start": u_start,
                    "expected_electrons_at_occupancy":
                        expected_electrons_table(el),
                    "omit_map_electrons": ref_read.get("electrons_positive"),
                    "omit_map_electrons_negative":
                        ref_read.get("electrons_negative"),
                    "residual_before": {k: ref_read.get(k)
                                        for k in ("max", "min", "at_site")},
                    "nearest_atoms": nearest,
                    "bond_plausibility": bond_plausibility(el, nearest),
                }
                try:
                    self._cut(branch, baseline, checkout=True)
                    ses_c = project.session
                    if not use_mask:
                        self._drop_mask(ses_c)
                    if omit:
                        self._mark(self._delete(omit["label"], progress),
                                   baseline, cand, "delete")
                    label = self._probe_label(ses_c.model, el)
                    row["label"] = label
                    self._add_probe(ses_c.model, label, el, site, occ_start,
                                    u_start)
                    everyone = [sc.label for sc in ses_c.model.scatterers()]
                    others = [l for l in everyone if l.upper() != label.upper()]
                    uc = ses_c.model.unit_cell()

                    def _stage(key: str, what: str, n_cycles: int,
                               fix: list[str] | None, step: str
                               ) -> tuple[dict, dict]:
                        res = self._refine_probe(n_cycles, progress,
                                                 fix_atoms=fix)
                        if not res["ok"]:
                            raise _Refusal(f"refinement with {label} ({what}) "
                                           f"failed: {res['error']}")
                        self._mark(res["node"], baseline, cand, step)
                        st = self._probe_state(project.session.model, label)
                        if st is None:
                            raise _Refusal(f"{label} vanished from the model")
                        row[key] = {
                            "what": what, "node": res["node"],
                            "cycles": n_cycles,
                            "occupancy": round(st["occupancy"], 4),
                            "u_iso": round(st["u_iso"], 4),
                            "site_shift_A": round(float(uc.distance(
                                tuple(site), tuple(st["site"]))), 3),
                            "r1_strong": res.get("r1_strong"),
                            "wr2": res.get("wr2"), "goof": res.get("goof"),
                            "delta_r1": _delta(res.get("r1_strong"),
                                               ref.get("r1_strong")),
                            "delta_wr2": _delta(res.get("wr2"),
                                                ref.get("wr2")),
                        }
                        return res, st

                    # stage A: the occupancy alone, every site and Uiso
                    # held (a one-parameter problem: converges at once,
                    # whatever the damping of the full model would do)
                    final, st = _stage(
                        "stage_a", "occupancy only - every site and Uiso "
                                   "fixed, the probe's Uiso at u_iso_start",
                        OCC_ONLY_CYCLES, everyone, "refine[occupancy only]")
                    row["occupancy_at_fixed_u"] = round(st["occupancy"], 4)
                    row["electrons_at_fixed_u"] = round(st["occupancy"] * z, 2)
                    if st["occupancy"] >= OCC_ABSENT:
                        # stage B: the probe free (site, Uiso, occupancy),
                        # the rest of the model held at the reference
                        _stage("stage_b", "probe site, Uiso and occupancy "
                                          "free, the rest of the model fixed "
                                          "at the reference",
                               cycles, others, "refine[probe free]")
                        # stage C: everything free - deltas like-for-like
                        # with the reference, neighbours allowed to relax
                        final, st = _stage(
                            "stage_c", "everything free", cycles, None,
                            "refine[free]")
                        row["u_iso_refined"] = round(st["u_iso"], 4)
                        row["site_refined"] = [round(c, 4) for c in st["site"]]
                        row["site_shift_A"] = row["stage_c"]["site_shift_A"]
                    else:
                        row["stage_b"] = row["stage_c"] = None
                        row["u_iso_refined"] = None
                        row["stage_note"] = (
                            f"occupancy fell below {OCC_ABSENT} with every "
                            f"site and Uiso fixed: nothing to free")
                    ses_c = project.session
                    after = sphere_density(
                        ses_c, ses_c.model, [site], PROBE_RADIUS_A,
                        f_mask=ses_c.flags.get("f_mask"))[0]
                    row.update({
                        "node": final["node"], "n_atoms": final.get("n_atoms"),
                        "occupancy_refined": round(st["occupancy"], 4),
                        "electrons_refined": round(st["occupancy"] * z, 2),
                        "r1_strong": final.get("r1_strong"),
                        "wr2": final.get("wr2"), "goof": final.get("goof"),
                        "delta_r1": _delta(final.get("r1_strong"),
                                           ref.get("r1_strong")),
                        "delta_wr2": _delta(final.get("wr2"), ref.get("wr2")),
                        "delta_goof": _delta(final.get("goof"),
                                             ref.get("goof")),
                        "residual_after": {k: after.get(k)
                                           for k in ("max", "min", "at_site")},
                    })
                    verdict, reason = probe_verdict(row)
                except _Refusal as e:
                    row["error"] = str(e)
                    verdict, reason = "inconclusive", "the test could not " \
                                                      "be completed"
                except Exception as e:  # noqa: BLE001 - one candidate must not kill the table
                    row["error"] = f"{type(e).__name__}: {e}"
                    verdict, reason = "inconclusive", "the test could not " \
                                                      "be completed"
                row["verdict"], row["reason"] = verdict, reason
                row["disposition"] = DISPOSITION[verdict]
                if verdict == "supported":
                    row["disposition"] = (
                        f"model it: add_atoms_from_difference_map "
                        f"sites=[{[round(c, 4) for c in site]}] element="
                        f"'{el}' occupancy={row['occupancy_refined']} (or "
                        f"edit_atoms set_occupancy afterwards), name it, "
                        f"restrain if a molecule is expected (fit_fragment), "
                        f"and re-run solvent_mask afterwards")
                t_last = _now() - tc0
                row["elapsed_s"] = round(t_last, 1)
                rows.append(row)
                verdicts[el] = verdict
                say(f"probe_site: {len(rows)}/{len(elements)} {el} at "
                    f"{site_txt} -> {verdict} (occ {row.get('occupancy_refined')}"
                    f", Uiso {row.get('u_iso_refined')}, dR1 "
                    f"{row.get('delta_r1')}); {(_now() - t_start):.0f} s of "
                    f"{budget} s")
        finally:
            summary["restore"] = self._restore(baseline, pre)
        summary["rows"] = rows
        summary["verdicts"] = verdicts
        summary["n_tested"] = len(rows)
        if not_tested:
            summary["not_tested"] = not_tested
        summary["note"] = occupancy_note(elements[0])
        # how far can this model's electron counts be trusted, and which
        # elements does the measured count bracket (never a winner)
        ref_info = (summary.get("baseline") or {}).get("reference") or {}
        r1_now = ref_info.get("r1_strong")
        calibration = low_count_note(r1_now)
        if calibration:
            summary["electron_count_calibration"] = calibration
        measured = (ref_info.get("site_read") or {}).get("electrons_positive")
        low_biased = count_is_low_biased(r1_now)
        proposed = bracketing_elements(measured, low_biased=low_biased)
        if proposed:
            summary["candidates_bracketing_the_count"] = proposed
            summary["bracket_note"] = electron_bracket_note(
                measured, proposed, low_biased)
        summary["how_to_read"] = HOW_TO_READ
        summary["tree_note"] = (
            f"diagnostic nodes were kept on branches diag/probe_site/"
            f"{baseline}/<El>@{site_txt} (checkout one to inspect_map the "
            f"site with the probe in place); they are not delivery "
            f"candidates. Active node is {baseline} again "
            f"({summary['restore'].get('branch')}).")
        summary["elapsed_s"] = round(_now() - t_start, 1)
        ok = summary["restore"].get("restored", False)
        return ToolResult(ok=ok, summary=summary,
                          error=None if ok else summary["restore"].get("error"))


def register_probe_tools(reg, project) -> None:
    reg.register(ProbeSite(project))
