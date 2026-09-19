"""Where a second position would be, before anyone draws it.

Four single-cell runs on orgdis_dbu (2026-09-04) ended the same way: the
agent saw the residual peak next to the ring carbon, saw its fat and
elongated ADP, wrote "I should model the disorder for C16" - and then
rejected the split with a fresh hypothesis each time ("anharmonic motion",
"below d_min", "might be hydrogen density", "in the H range") before any
refinement. The numbers that answer those hypotheses were all computable
from the model in hand; nobody put them in one place. This module does:
for every residual peak that sits where an alternative position of an atom
would be (0.4-1.6 A from it, closer to it than to any other atom, and not
on a modelled H), it reports the peak, the carrier's U_eq against the
model's own median, its ADP anisotropy and the nearest modelled H to the
peak, and names the next step. No element tables, no crystal-class
constants: everything is referenced to this model and this map. The
decision stays with refinement (disorder_accept): this is a candidate
list, not a verdict.
"""
from __future__ import annotations

from typing import Any

#: a residual this far from an atom is a candidate alternative position of
#: that atom (closer is its own ripple, farther belongs to something else)
PEAK_D_MIN, PEAK_D_MAX = 0.4, 1.6
#: a peak this close to ANY modelled atom (H included) sits on that atom
ON_ATOM_D = 0.35


def _u_eq(uc, sc) -> float:
    from cctbx import adptbx
    return float(adptbx.u_star_as_u_iso(uc, sc.u_star)
                 if sc.flags.use_u_aniso() else sc.u_iso)


def _adp_ratio(uc, sc):
    if not sc.flags.use_u_aniso():
        return None
    from cctbx import adptbx
    from scitbx.linalg import eigensystem
    vals = sorted(float(v) for v in eigensystem.real_symmetric(
        adptbx.u_star_as_u_cart(uc, sc.u_star)).values())
    return round(vals[-1] / vals[0], 1) if vals[0] > 0 else "NPD"


def disorder_candidates(xs, peaks, *, exclude: set[str] | None = None,
                        max_out: int = 8) -> dict[str, Any]:
    """Candidate second positions from the last difference map.

    `peaks`: the session's diff_map_peaks ([{site, height, ...}]);
    `exclude`: labels already in a disorder group / PART block.
    Returns {"candidates": [...], "n_peaks": n, "note": str}.
    """
    from .tools_disorder import _nearest_image
    out: dict[str, Any] = {"candidates": [], "n_peaks": 0}
    if xs is None or not peaks:
        out["note"] = ("no difference map on record - refine (or "
                       "run_shelxl adopt) first; the map is where a second "
                       "position shows itself")
        return out
    uc = xs.unit_cell()
    sg = xs.space_group()
    scs = list(xs.scatterers())
    excl = {lb.upper() for lb in (exclude or ())}
    heavy = [sc for sc in scs if sc.scattering_type.strip().upper() != "H"]
    hyd = [sc for sc in scs if sc.scattering_type.strip().upper() == "H"]
    u_all = sorted(_u_eq(uc, sc) for sc in heavy)
    median = u_all[len(u_all) // 2] if u_all else None
    best: dict[str, dict[str, Any]] = {}
    n_peaks = 0
    for pk in peaks:
        site = pk.get("site")
        if not site or len(site) != 3:
            continue
        try:
            h = float(pk.get("height") or 0.0)
        except (TypeError, ValueError):
            continue
        if h <= 0:
            continue
        n_peaks += 1
        site = tuple(float(x) for x in site)
        # nearest modelled atom of any kind: a peak ON an atom is not a
        # second position (a mis-placed H shows here, not as a candidate)
        near_any = None
        for sc in scs:
            d, _ = _nearest_image(uc, sg, tuple(sc.site), site)
            if near_any is None or d < near_any[0]:
                near_any = (d, sc)
        if near_any is None or near_any[0] < ON_ATOM_D:
            continue
        # the heavy atom it belongs to
        near_heavy = None
        for sc in heavy:
            d, _ = _nearest_image(uc, sg, tuple(sc.site), site)
            if near_heavy is None or d < near_heavy[0]:
                near_heavy = (d, sc)
        if near_heavy is None:
            continue
        d, sc = near_heavy
        if not PEAK_D_MIN <= d <= PEAK_D_MAX:
            continue
        if sc.label.upper() in excl:
            continue
        near_h = None
        for hs in hyd:
            dh, _ = _nearest_image(uc, sg, tuple(hs.site), site)
            if near_h is None or dh < near_h[0]:
                near_h = (dh, hs.label)
        cur = best.get(sc.label.upper())
        if cur is not None and cur["peak_height"] >= h:
            continue
        u_eq = _u_eq(uc, sc)
        ratio = round(u_eq / median, 2) if median else None
        adp = _adp_ratio(uc, sc)
        parts = [f"{sc.label} ({sc.scattering_type.strip()}): residual "
                 f"{h:.2f} e/A^3 at {d:.2f} A"]
        if near_h is not None:
            parts.append(f"nearest modelled H {near_h[1]} is {near_h[0]:.2f} A "
                         f"from the peak" + (" - not an H position"
                                             if near_h[0] >= ON_ATOM_D else ""))
        else:
            parts.append("no H in the model to confuse it with")
        if ratio is not None:
            parts.append(f"U_eq {u_eq:.3f} = {ratio:.1f}x the model's median "
                         f"non-H U_eq")
        if adp is not None:
            parts.append(f"ADP max/min {adp}")
        best[sc.label.upper()] = {
            "atom": sc.label, "element": sc.scattering_type.strip(),
            "peak_height": round(h, 2), "peak_d": round(d, 2),
            "peak_site": [round(x, 4) for x in site],
            "nearest_h": ({"label": near_h[1], "d": round(near_h[0], 2)}
                          if near_h is not None else None),
            "u_eq": round(u_eq, 4), "u_eq_over_median": ratio,
            "adp_max_over_min": adp,
            "reading": "; ".join(parts) + ". A residual where an alternative "
                       "position would be, next to a carrier whose ADP is "
                       "doing the work of two sites, is the signature of "
                       "unresolved disorder. Refinement decides, not a "
                       "hunch:",
            "next": (f"model_disorder(atoms=['{sc.label}']) puts B on this "
                     f"peak -> set_restraints(restraint_suggestion) -> "
                     f"run_shelxl(mode='adopt') on that branch -> read "
                     f"disorder_acceptance (the FVAR s.u. keeps, restrains "
                     f"or revokes the split)"),
        }
    cands = sorted(best.values(), key=lambda c: -c["peak_height"])[:max_out]
    out["candidates"] = cands
    out["n_peaks"] = n_peaks
    out["note"] = (f"{len(cands)} atom(s) carry a residual where a second "
                   f"position would be" if cands else
                   f"none of the {n_peaks} residual peak(s) sits 0.4-1.6 A "
                   f"from an atom without being on a modelled atom")
    return out
