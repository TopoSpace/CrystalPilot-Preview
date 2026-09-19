"""Symmetry tools: ADDSYM-style audit (check_symmetry) and the
explicit space-group re-declaration (change_space_group).

Split out of tools_analysis (r12 module split); registration stays in
tools_analysis.register_analysis_tools.
"""
from __future__ import annotations

import math
import re
import time
from pathlib import Path
from typing import Any

from ..tools.base import ToolContext, ToolResult
from .toolbase import _ProjectTool


def _match_targets(xs) -> tuple[list, list]:
    """Non-H ASU sites expanded by the structure's OWN space group: a
    candidate op may map an atom onto a symmetry MATE of another atom
    (e.g. the inversion partner of a P2_1 atom is the screw image of its
    glide mate), so matching against bare ASU sites under-counts."""
    ops = list(xs.space_group().all_ops())
    t_sites, t_elems = [], []
    for sc in xs.scatterers():
        el = sc.scattering_type.strip().capitalize()
        if el in ("H", "D"):
            continue
        for g in ops:
            t_sites.append(g * sc.site)
            t_elems.append(el)
    return t_sites, t_elems


def _direct_match_fraction(xs, op, tol_frac_A: float = 0.35) -> dict[str, Any]:
    """Fraction of atoms mapped onto a same-element atom (or a symmetry
    mate of one) by op - direct site matching under lattice translations,
    deliberately NOT emma, whose Euclidean normalizer would always absorb
    an inversion."""
    uc = xs.unit_cell()
    scs = [sc for sc in xs.scatterers()
           if sc.scattering_type.strip().capitalize() not in ("H", "D")]
    sites = [sc.site for sc in scs]
    elems = [sc.scattering_type.strip().capitalize() for sc in scs]
    t_sites, t_elems = _match_targets(xs)
    n_ok, devs = 0, []
    for i, s in enumerate(sites):
        t = op * s
        best = None
        for j, s2 in enumerate(t_sites):
            if t_elems[j] != elems[i]:
                continue
            d = uc.distance(
                tuple(t[k] - math.floor(t[k] - s2[k] + 0.5) for k in range(3)),
                s2)
            if best is None or d < best:
                best = d
        if best is not None and best <= tol_frac_A:
            n_ok += 1
            devs.append(best)
    return {"fraction": n_ok / max(1, len(sites)),
            "mean_dev_A": round(sum(devs) / len(devs), 3) if devs else None,
            "max_dev_A": round(max(devs), 3) if devs else None}


def _fit_translation_match(xs, op, tol_frac_A: float = 0.35) -> dict[str, Any]:
    """ADDSYM-style matching with a FITTED translation part.

    A refined structure's origin floats along the current group's polar
    directions, so a pseudo-symmetry element generally sits at an
    arbitrary location: the coset representative's own translation cannot
    be trusted. Keep the rotation part, generate candidate translations
    from same-(rarest-)element atom pairs, score each with the same
    element-aware min-image matcher, return the best.
    """
    import numpy as np

    uc = xs.unit_cell()
    scs = [sc for sc in xs.scatterers()
           if sc.scattering_type.strip().capitalize() not in ("H", "D")]
    sites = np.array([sc.site for sc in scs], float)
    elems = [sc.scattering_type.strip().capitalize() for sc in scs]
    if not len(sites):
        return {"fraction": 0.0}
    R = np.array(op.r().as_double()).reshape(3, 3)
    O = np.array(uc.orthogonalization_matrix()).reshape(3, 3)
    from collections import Counter
    cnt = Counter(elems)
    rare = min(cnt, key=lambda e: (cnt[e], e))
    idx_r = [i for i, e in enumerate(elems) if e == rare]
    ry = sites @ R.T
    t_sites_l, t_elems_l = _match_targets(xs)
    t_sites = np.array([list(s) for s in t_sites_l], float)
    by_elem = {e: t_sites[[i for i, ee in enumerate(t_elems_l) if ee == e]]
               for e in set(t_elems_l)}
    rare_targets = by_elem[rare]

    def score(t):
        n_ok, devs, unmatched = 0, [], []
        for i in range(len(sites)):
            d = (ry[i] + t) - by_elem[elems[i]]
            d -= np.round(d)
            dist = np.sqrt(((d @ O.T) ** 2).sum(1)).min()
            if dist <= tol_frac_A:
                n_ok += 1
                devs.append(dist)
            else:
                unmatched.append((scs[i].label, round(float(dist), 2)))
        return n_ok / len(sites), devs, unmatched

    scored = []
    seen: set[tuple] = set()
    for i in idx_r:
        for tgt in rare_targets:
            t = (tgt - ry[i]) % 1.0
            key = tuple(np.round(t * 24).astype(int) % 24)
            if key in seen:
                continue
            seen.add(key)
            frac, devs, unmatched = score(t)
            scored.append((frac, t, devs, unmatched))
    scored.sort(key=lambda x: -x[0])
    frac, t, devs, unmatched = scored[0]

    # a pseudo-symmetric arrangement often admits SEVERAL near-equivalent
    # translations for the same rotation (multiple pseudo-centres); the
    # right one is decided by which GROUP closure survives - report the
    # distinct near-best alternatives so the caller can trial each
    def _cart_dist(a, b):
        d = (np.asarray(a) - np.asarray(b))
        d -= np.round(d)
        return float(np.linalg.norm(d @ O.T))

    alts: list[tuple] = []
    for fr, tv, _d, _u in scored[1:]:
        if fr < frac - 0.03:
            break
        if all(_cart_dist(tv, a) > 0.75
               for a in [t] + [x[0] for x in alts]):
            alts.append((tv, fr))
        if len(alts) >= 3:
            break

    return {
        "fraction": frac,
        "t_fitted": [round(float(x) % 1.0, 4) for x in t],
        "mean_dev_A": round(float(np.mean(devs)), 3) if devs else None,
        "max_dev_A": round(float(np.max(devs)), 3) if devs else None,
        "t_alternatives": [
            {"t": [round(float(x) % 1.0, 4) for x in tv],
             "fraction": round(float(fr), 3)} for tv, fr in alts],
        **({"unmatched": unmatched[:6]} if unmatched else {}),
    }


def _polar_shift_for(cur_group, op_r, t_fit):
    """Sound origin standardization for a fitted op whose translation is
    off the /12 grid. Shifting the whole content is legitimate ONLY along
    the CURRENT group's polar directions - the common fixed space of all
    its rotation parts, i.e. exactly the floating-origin freedom (P1 =
    everything, P21 = b, most centrosymmetric groups = nothing): such a
    shift s leaves every declared op untouched and changes the fitted
    translation to t + (I - R_q) s (the op mapping shifted content is
    R (x - s) + t + s). Least-squares s toward t' = 0 (as standard
    an origin as reachable - intrinsic screw/glide parts live in
    null(R_q - I) and survive untouched); components the shift cannot
    reach are pinned by closure with the declared group and must land
    near-rational on their own.

    Returns (shift or None, t_corrected or None)."""
    import numpy as np

    rots = [np.array(h.r().as_double()).reshape(3, 3)
            for h in cur_group.all_ops()]
    A = np.vstack([r - np.eye(3) for r in rots])
    # null space of stacked (R - I) = polar directions
    _u, sv, vt = np.linalg.svd(A)
    sv3 = np.zeros(3)
    sv3[: len(sv)] = sv
    polar = vt[sv3 < 1e-6].T          # columns span the polar subspace
    if polar.size == 0:
        return None, None
    t = np.array([float(x) for x in t_fit])
    t = t - np.round(t)               # centered representative
    Rq = np.array(op_r.as_double()).reshape(3, 3)
    M = (np.eye(3) - Rq) @ polar
    a, *_ = np.linalg.lstsq(M, -t, rcond=None)
    s = polar @ a
    if np.linalg.norm(s) < 1e-4:
        return None, None             # shift would not move anything
    t_new = t + M @ a
    return [float(x) for x in s], [float(x % 1.0) for x in t_new]


#: How coarse the data may be before a direct-space symmetry search stops
#: carrying its normal weight. 0.84 A is the IUCr's minimum resolution for
#: publication (Mueller 2009) and the practical floor of the atomic-
#: resolution regime PLATON/ADDSYM is documented to require ('the
#: PLATON/ADDSYM algorithm that is used to detect missing symmetry
#: requires atomic resolution data', Spek 2009). 1.2 A is where the
#: coordinate errors of light atoms become an appreciable fraction of the
#: 0.35 A site-match tolerance, so a missed operation can hide INSIDE the
#: tolerance and a null result stops meaning much.
SYMMETRY_SEARCH_D_MIN_GOOD = 0.84
SYMMETRY_SEARCH_D_MIN_COARSE = 1.2


def _op_kind(op_str: str) -> str:
    """centre / translation / rotation from an operator's rotation part."""
    from cctbx import sgtbx
    try:
        r = sgtbx.rt_mx(str(op_str)).r()
    except Exception:  # noqa: BLE001 - classify what we can
        return "rotation"
    if r.is_unit_mx():
        return "translation"
    if tuple(r.as_double()) == (-1.0, 0.0, 0.0,
                                0.0, -1.0, 0.0,
                                0.0, 0.0, -1.0):
        return "centre"
    return "rotation"


def _symmetry_risk(found: list, borderline: list, heavy: list,
                   near_misses: list, metric_pseudo: bool,
                   d_min: float | None) -> dict[str, Any]:
    """What KIND of symmetry is at stake, how much a wrong call costs, and
    how far the data let this direct-space search be trusted.

    The two halves are separate on purpose. The COST is a property of the
    operation (Marsh's Cc survey: of 98 structures revised out of Cc, the
    75 that gained an inversion centre showed 'large changes in bond
    lengths and angles', while the 23 that only changed lattice type had
    'molecular dimensions ... effectively unchanged'; Spek: 'overlooking
    an inversion centre is generally serious ... this problem can be
    hidden when structure refinement is performed by using constraints and
    restraints'). The RELIABILITY is a property of the data: ADDSYM-style
    matching compares interatomic positions against a fixed tolerance, so
    it needs coordinates whose error is small against that tolerance.
    """
    kinds = [_op_kind(e.get("op") or e.get("op_rotation") or "")
             for e in (found or [])]
    if found:
        if "centre" in kinds:
            kind, risk = "missed_centre", "high"
            why = ("an inversion centre is the expensive one to miss: the "
                   "pairs of parameters that should be identical become "
                   "highly correlated instead, and adding the centre "
                   "typically changes bond lengths and angles a lot "
                   "(Marsh: 75 of 98 Cc revisions). Refining the acentric "
                   "model with extra restraints to stabilise it is the "
                   "classic way the error stays hidden.")
        elif all(k == "translation" for k in kinds):
            kind, risk = "missed_translation", "low"
            why = ("a missed lattice translation changes the lattice type "
                   "but leaves the molecular dimensions effectively "
                   "unchanged (Marsh: the 23 Cc->Fdd2/R3c/I-4c2 cases). "
                   "The cost is on the DATA side instead: declaring the "
                   "centring discards every reflection in its absent "
                   "class from all later merging and refinement, so audit "
                   "the absences (screen_space_groups) before adopting.")
        else:
            kind, risk = "missed_rotation", "medium"
            why = ("a missed rotation/screw/glide raises the Laue class: "
                   "the asymmetric unit shrinks and the geometry changes, "
                   "though usually less violently than a missed centre "
                   "(Spek: 'some missed symmetry cases are relatively "
                   "harmless ... e.g. wrong Laue group'). Verify on the "
                   "DATA side too - R_int in the higher class and the new "
                   "absence conditions.")
    elif borderline or heavy or any(
            (nm.get("fraction") or 0) >= 0.9 for nm in (near_misses or [])):
        kind, risk = "pseudo_symmetry_only", "medium"
        why = ("nothing matched at the adoption threshold, but something "
               "came close. That is exactly what BOTH a genuine missed "
               "symmetry on a twinned/disordered model and an ordinary "
               "pseudo-symmetric packing look like, and ADDSYM-class "
               "searches are wrong about it more often than not (Marsh: "
               "144 C2 entries flagged, about 50 genuinely revisable). "
               "Decide on the data side, not here.")
    elif metric_pseudo:
        kind, risk = "none_found", "medium"
        why = ("no operation of the higher lattice symmetry maps this "
               "model onto itself, but the CELL still supports more "
               "symmetry than the group uses - the geometric "
               "precondition for pseudo-merohedral twinning "
               "(audit_reflection_data reads the data side of it).")
    else:
        kind, risk = "none_found", "low"
        why = ("neither the model nor the cell metric offers symmetry "
               "beyond the current group. This is not proof that the "
               "group is right: the search is one-sided (it can only "
               "find operations, never certify their absence).")

    if d_min is None:
        level = "unknown"
        note = ("no reflection data in this session, so the resolution "
                "this model was refined against is unknown - and with it "
                "how much a null result is worth. Re-run after the data "
                "are loaded, or read the finding as a suggestion only.")
    elif d_min <= SYMMETRY_SEARCH_D_MIN_GOOD:
        level = "atomic_resolution"
        note = (f"d_min {d_min:.2f} A is at or beyond the IUCr's "
                f"{SYMMETRY_SEARCH_D_MIN_GOOD} A publication limit, the "
                f"atomic-resolution regime this kind of direct-space "
                f"matching is documented to need: coordinate errors are "
                f"small against the 0.35 A site tolerance, so BOTH a hit "
                f"and a miss carry their normal weight here.")
    elif d_min <= SYMMETRY_SEARCH_D_MIN_COARSE:
        level = "marginal"
        note = (f"d_min {d_min:.2f} A is coarser than the IUCr's "
                f"{SYMMETRY_SEARCH_D_MIN_GOOD} A limit: light-atom "
                f"positions carry errors that are no longer negligible "
                f"against the 0.35 A tolerance, so a NULL result is the "
                f"weaker half of this report - a real operation can hide "
                f"inside the tolerance. A hit is still worth verifying by "
                f"re-refinement.")
    else:
        level = "coarse"
        note = (f"d_min {d_min:.2f} A: at this resolution the site-match "
                f"tolerance (0.35 A) is comparable to the coordinate "
                f"errors, and whole groups may be misplaced by unmodelled "
                f"disorder. A null result says almost nothing, and a hit "
                f"is as likely to come from the loose tolerance as from "
                f"the crystal - decide from the reflection data "
                f"(screen_space_groups, audit_reflection_data), not from "
                f"this table.")
    return {"kind": kind, "risk": risk, "risk_reason": why,
            "reliability": {"d_min": (round(float(d_min), 3)
                                      if d_min is not None else None),
                            "level": level, "note": note},
            "one_sided": ("this audit can only ARGUE FOR extra symmetry. "
                          "'none found' is never a certificate that the "
                          "current group is complete.")}


class CheckSymmetry(_ProjectTool):
    name = "check_symmetry"
    description = (
        "Audit the current space-group assignment (ADDSYM-style, "
        "deterministic): finds symmetry operations of the lattice's maximal "
        "group that also map the MODEL onto itself (element-aware direct "
        "site matching, tolerance ~0.35 A) but are missing from the current "
        "space group - i.e. refining in too low a symmetry. Also reports "
        "pure metric pseudo-symmetry (cell alone suggests more). Every "
        "answer carries `kind` (missed_centre / missed_rotation / "
        "missed_translation / pseudo_symmetry_only / none_found), `risk` "
        "(a missed centre rewrites the geometry; a missed centring leaves "
        "molecular dimensions alone but discards data) and a `reliability` "
        "note keyed to the DATA's d_min - this is direct-space matching "
        "against a fixed 0.35 A tolerance, so a null result on 1.2 A data "
        "is a far weaker statement than the same null on 0.8 A data. A "
        "finding is a SUGGESTION: verify by transforming + re-refining, "
        "and disclose the trial either way. Best on refined models; "
        "unreliable on raw trial models.")
    params_schema = {
        "type": "object",
        "properties": {
            "tolerance_A": {"type": "number", "default": 0.35,
                            "description": "site-match tolerance in Angstrom"},
            "timeout_s": {"type": "number", "default": 120,
                          "description": "wall-clock budget for the coset "
                                         "search; on expiry the PARTIAL "
                                         "result is returned with "
                                         "timed_out set (pa1: one call ran "
                                         "476 s and held the project lock)"},
        },
    }

    def run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        import time as _time
        from cctbx import sgtbx
        from cctbx.sgtbx import lattice_symmetry
        ses = ctx.session
        if ses is None or ses.model is None:
            return ToolResult.failure("no model loaded")
        xs = ses.model
        tol = float(params.get("tolerance_A", 0.35))
        timeout_s = float(params.get("timeout_s") or 120.0)
        # perf_counter: monotonic() is 15 ms-grained on Windows
        deadline = _time.perf_counter() + timeout_s
        timed_out: dict[str, Any] = {}

        def _expired(stage: str, k: int, n: int) -> bool:
            if timed_out:
                return True                  # every later stage stops too
            if _time.perf_counter() <= deadline:
                return False
            timed_out.update({"stage": stage, "ops_examined": k,
                              "ops_total": n, "timeout_s": timeout_s})
            return True
        cur_info = xs.space_group_info()

        # Work entirely in the primitive Niggli setting so centering
        # translations are absorbed and group orders are comparable.
        cb = xs.crystal_symmetry().change_of_basis_op_to_niggli_cell()
        xs_n = xs.change_basis(cb)
        cur_n = xs_n.space_group()
        latt_group = lattice_symmetry.group(xs_n.unit_cell(), max_delta=1.4)
        # cctbx reports the ACENTRIC lattice holohedry; every lattice is
        # centrosymmetric, so add the inversion - this also puts -x,-y,-z
        # into the coset search (the P1-vs-P-1 trap).
        latt_group.expand_inv(sgtbx.tr_vec((0, 0, 0)))
        n_latt = latt_group.order_z()          # primitive setting
        n_cur = cur_n.order_z()

        found, rejected, borderline_ops = [], [], []
        polar_shift = None
        heavy_ops: list[dict[str, Any]] = []
        heavy_anchor_info: dict[str, Any] | None = None

        def _in_cur_group(q) -> bool:
            """q equivalent to a current-group op modulo lattice
            translations (numeric - textual forms differ across bases,
            and with group-expanded match targets such an op would
            'match' trivially)."""
            qr = q.r().as_double()
            qt = q.t().as_double()
            for h in cur_n.all_ops():
                if h.r().as_double() != qr:
                    continue
                ht = h.t().as_double()
                if all(abs((qt[k] - ht[k]) - round(qt[k] - ht[k])) < 1e-4
                       for k in range(3)):
                    return True
            return False

        def _close_group(entries):
            g = sgtbx.space_group(cur_n)
            for e in entries:
                g.expand_smx(sgtbx.rt_mx(e["op"]))
            back = sgtbx.space_group_info(group=g).change_basis(cb.inverse())
            return str(back), str(back.as_reference_setting())

        if n_latt > n_cur:
            # coset representatives of latt_group modulo the current group
            reps = []
            covered: set[str] = set()
            for op in latt_group.all_ops():
                s = str(op)
                if _in_cur_group(op) or s in covered:
                    continue
                reps.append(op)
                for h in cur_n.all_ops():
                    covered.add(str(op.multiply(h)))
            for k, op in enumerate(reps[:48]):
                if _expired("direct", k, len(reps[:48])):
                    break
                m = _direct_match_fraction(xs_n, op, tol_frac_A=tol)
                entry = {"op": str(op), **m}
                if m["fraction"] >= 0.975:
                    found.append(entry)
                elif m["fraction"] >= 0.8:
                    rejected.append(entry)

            # The lattice holohedry is symmorphic: its coset reps carry no
            # intrinsic translations, and a refined structure's origin
            # floats along polar directions. So screws/glides and any op
            # away from the current origin can ONLY be found by fitting
            # the translation part (this is what real ADDSYM does).
            if not found:
                fitted = []
                # pre-seed with the current group's rotations: fitting a
                # translation for one of those would trivially rediscover
                # the group's own op (pseudo-CENTERING is not searched
                # here - it shows up on the data side instead)
                seen_rot: set[tuple] = {
                    tuple(h.r().as_double()) for h in cur_n.all_ops()}
                for k, op in enumerate(reps[:48]):
                    if _expired("translation_fit", k, len(reps[:48])):
                        break
                    rk = tuple(op.r().as_double())
                    if rk in seen_rot:
                        continue
                    seen_rot.add(rk)
                    fm = _fit_translation_match(xs_n, op, tol_frac_A=tol)
                    if fm["fraction"] >= 0.9:
                        fitted.append((op, fm))
                    elif fm["fraction"] >= 0.8:
                        rejected.append({
                            "op_rotation": str(sgtbx.rt_mx(op.r())),
                            "translation_fitted": True, **fm})
                # NO blind structure shifting: apply_shift breaks the
                # relation between the content and the DECLARED ops (the
                # declared screw stays at the origin while the content
                # moves) - EXCEPT along the current group's polar
                # directions, where shifting is exactly the floating-
                # origin freedom and therefore sound. Snap each fitted
                # translation to /12 in the ORIGINAL frame; if a snap
                # fails, standardize the origin with a polar shift on a
                # throwaway copy (never the session model) and re-fit.
                # sgtbx then closes the group with the true (possibly
                # non-standard-origin) translations - the resulting
                # symbol carries the origin annotation.
                xs_v = xs_n

                def _off_grid(tv):
                    return any(abs(float(x) * 12 - round(float(x) * 12))
                               > 0.35 for x in tv)

                need = [(op, fm) for op, fm in fitted
                        if _off_grid(fm["t_fitted"])]
                if need:
                    op0, fm0 = max(need, key=lambda p: p[1]["fraction"])
                    s_p, _tn = _polar_shift_for(cur_n, op0.r(),
                                                fm0["t_fitted"])
                    if s_p is not None:
                        xs_v = xs_n.apply_shift(
                            tuple(s_p), recompute_site_symmetries=True)
                        polar_shift = [round(float(x), 4) for x in s_p]
                        refit = []
                        for op, _old in fitted:
                            fm2 = _fit_translation_match(xs_v, op,
                                                         tol_frac_A=tol)
                            if fm2["fraction"] >= 0.9:
                                refit.append((op, fm2))
                        fitted = refit
                for op, fm in fitted:
                    tf = fm["t_fitted"]
                    if _off_grid(tf):
                        rejected.append({
                            "op_rotation": str(sgtbx.rt_mx(op.r())),
                            "translation_fitted": True,
                            "note": "fitted translation is not a /12 "
                                    "crystallographic vector", **fm})
                        continue
                    t12 = [int(round(float(x) * 12)) % 12 for x in tf]
                    op_std = sgtbx.rt_mx(op.r(), sgtbx.tr_vec(t12, 12))
                    m3 = _direct_match_fraction(xs_v, op_std,
                                                tol_frac_A=tol)
                    entry = {"op": str(op_std),
                             "translation_fitted": True, **m3}
                    if m3["fraction"] >= 0.975:
                        found.append(entry)
                    elif m3["fraction"] >= 0.9:
                        borderline_ops.append(entry)
                    else:
                        rejected.append(entry)

            # heavy-anchor fallback: garbage light atoms drown a genuine
            # higher symmetry in full-model matching (r16 live failure:
            # a P1-escape model whose La2Ni2 skeleton obeyed an inversion
            # to 0.02 A scored ~0.3 overall and this tool stayed silent).
            # When the full search finds nothing, redo the coset search on
            # the strong scatterers alone - on a fresh/struggling solution
            # they are the only atoms whose positions deserve trust.
            if not found and not borderline_ops:
                from cctbx.eltbx import tiny_pse

                def _z_of(sc) -> int:
                    el = sc.scattering_type.strip().capitalize()
                    el = el.rstrip("+-0123456789")
                    try:
                        return int(tiny_pse.table(el).atomic_number())
                    except Exception:  # noqa: BLE001 - exotic types
                        return 0

                zs = [_z_of(sc) for sc in xs_n.scatterers()]
                for z_min in (19, 15):
                    anchor_idx = [i for i, z in enumerate(zs) if z >= z_min]
                    if len(anchor_idx) >= 2:
                        break
                if len(anchor_idx) >= 2 and len(anchor_idx) < \
                        xs_n.scatterers().size():
                    from cctbx.array_family import flex as _flex
                    sel = _flex.bool(xs_n.scatterers().size(), False)
                    for i in anchor_idx:
                        sel[i] = True
                    xs_anchor = xs_n.select(sel)
                    labels = sorted({xs_n.scatterers()[i].scattering_type
                                     .strip().capitalize()
                                     for i in anchor_idx})
                    heavy_anchor_info = {"n_anchors": len(anchor_idx),
                                         "elements": labels,
                                         "z_min": z_min}
                    for k, op in enumerate(reps[:48]):
                        if _expired("heavy_anchor", k, len(reps[:48])):
                            break
                        fm = _fit_translation_match(xs_anchor, op,
                                                    tol_frac_A=tol)
                        if fm["fraction"] < 0.9:
                            continue
                        rot = op.r().as_double()
                        entry = {"op_rotation": str(sgtbx.rt_mx(op.r())),
                                 "translation_fitted": True, **fm}
                        if tuple(rot) == (-1.0, 0.0, 0.0,
                                          0.0, -1.0, 0.0,
                                          0.0, 0.0, -1.0):
                            entry["inversion_centre_at"] = [
                                round(float(t) / 2.0 % 1.0, 4)
                                for t in fm["t_fitted"]]
                        heavy_ops.append(entry)

        suggested = None
        suggested_current = None
        borderline_suggestion = None
        if found:
            try:
                suggested_current, suggested = _close_group(found)
            except Exception as exc:  # noqa: BLE001 - group closure can fail
                suggested = f"(ops found but group closure failed: {exc})"
        elif borderline_ops:
            try:
                bl_cur, bl_ref = _close_group(borderline_ops)
                borderline_suggestion = {
                    "space_group_current_basis": bl_cur,
                    "space_group_reference": bl_ref,
                    "min_fraction": round(min(e["fraction"]
                                              for e in borderline_ops), 3),
                    "mean_dev_A": round(sum(
                        (e["mean_dev_A"] or 0) for e in borderline_ops)
                        / len(borderline_ops), 3),
                    "note": ("below the auto threshold (0.975) - adoption "
                             "requires an explicit change_space_group call "
                             "with min_match_fraction lowered, plus "
                             "data-side justification and re-refinement. "
                             "The symbol's parenthesised annotation (if "
                             "any) encodes the non-standard setting - pass "
                             "the symbol verbatim."),
                }
            except Exception:  # noqa: BLE001
                pass

        if found:
            verdict = (f"model obeys {len(found)} extra symmetry op(s) - "
                       f"consider {suggested}")
        else:
            strong_near = borderline_ops + [
                r_ for r_ in rejected if r_.get("fraction", 0) >= 0.9]
            if strong_near:
                nm = strong_near[0]
                verdict = (
                    f"borderline pseudo-symmetry: "
                    f"{nm.get('op') or nm.get('op_rotation')} matches "
                    f"{nm['fraction']:.0%} of atoms (mean dev "
                    f"{nm.get('mean_dev_A')} A). In twin-contaminated or "
                    f"disordered refinements, genuine extra symmetry often "
                    f"shows exactly like this - cross-check the data side "
                    f"(audit_reflection_data) before concluding the lower "
                    f"symmetry is real.")
            elif heavy_ops:
                h0 = heavy_ops[0]
                where = (f" (inversion centre at "
                         f"{h0['inversion_centre_at']})"
                         if h0.get("inversion_centre_at") else "")
                verdict = (
                    f"HEAVY-SUBSTRUCTURE SYMMETRY: the "
                    f"{heavy_anchor_info['n_anchors']} strong scatterers "
                    f"({'/'.join(heavy_anchor_info['elements'])}) obey "
                    f"{h0['op_rotation']}{where} at "
                    f"{h0['fraction']:.0%} (mean dev "
                    f"{h0.get('mean_dev_A')} A) while the full model does "
                    f"NOT. On a fresh or struggling solution this is the "
                    f"classic low-symmetry-escape signature (e.g. P1 "
                    f"instead of P-1): the anchors found the true "
                    f"symmetry and the light atoms were built wrong in "
                    f"the low group. Do not trust the light-atom model; "
                    f"re-solve or rebuild in the higher group (keep the "
                    f"anchors, difference-Fourier the rest), and "
                    f"cross-check the data side knowing that twinning "
                    f"biases |E^2-1| toward acentric values.")
            else:
                verdict = "current space group looks complete for this model"
        if timed_out:
            verdict = (
                f"TIMED OUT after {timeout_s:.0f} s during the "
                f"{timed_out['stage']} search ({timed_out['ops_examined']}/"
                f"{timed_out['ops_total']} coset ops examined) - the result "
                f"below is PARTIAL and a missed op is possible; do not "
                f"conclude the symmetry is complete from this call. Re-run "
                f"with timeout_s={int(timeout_s * 2)} (the call runs alone "
                f"on the project lock) or on the refined model. Partial "
                f"verdict: " + verdict)
        # what kind of symmetry is at stake, what a wrong call costs, and
        # how far THIS dataset's resolution lets a direct-space search be
        # trusted (a null result on 1.2 A data is not the same statement
        # as a null result on 0.8 A data)
        d_min_data = None
        try:
            ds = getattr(ses, "dataset", None)
            raw = getattr(ds, "intensities", None) if ds is not None else None
            if raw is not None and raw.size():
                d_min_data = float(raw.d_max_min()[1])
        except Exception:  # noqa: BLE001 - annotation must not break the audit
            d_min_data = None
        assessment = _symmetry_risk(found, borderline_ops, heavy_ops,
                                    rejected, n_latt > n_cur, d_min_data)
        return ToolResult(ok=True, summary={
            **({"timed_out": timed_out} if timed_out else {}),
            "current_space_group": str(cur_info),
            "order_primitive_current": n_cur,
            "order_primitive_lattice_max": n_latt,
            "metric_pseudo_symmetry": n_latt > n_cur,
            "kind": assessment["kind"],
            "risk": assessment["risk"],
            "risk_reason": assessment["risk_reason"],
            "reliability": assessment["reliability"],
            "one_sided": assessment["one_sided"],
            "extra_ops_matched": found,
            "near_misses": rejected[:6],
            **({"heavy_substructure_ops": heavy_ops,
                "heavy_anchor_info": heavy_anchor_info}
               if heavy_ops else {}),
            "suggested_space_group": suggested,
            **({"suggested_space_group_current_basis": suggested_current}
               if suggested_current else {}),
            **({"borderline_suggestion": borderline_suggestion}
               if borderline_suggestion else {}),
            **({"polar_origin_shift": polar_shift,
                "polar_origin_shift_note": (
                    "the extra op(s) were verified after standardizing "
                    "the floating origin along the current group's polar "
                    "direction(s) by this shift (sound: declared ops are "
                    "unchanged by it). change_space_group re-derives and "
                    "applies the same shift on adoption.")}
               if polar_shift else {}),
            "verdict": verdict,
            "caveat": ("a matched op means the MODEL is (pseudo)symmetric; "
                       "only re-refinement in the higher group proves the "
                       "DATA support it. Disorder or unresolved heavy-atom "
                       "positions can fake or hide symmetry."),
        })


# ==========================================================================
# space-group change (adopt a check_symmetry suggestion, or explicit)
# ==========================================================================

def _subgroup_menu(old_group, limit: int = 24) -> list[dict[str, Any]]:
    """Subgroups of the current group in the CURRENT setting, as symbols an
    agent can pass straight back to change_space_group.

    cage-l2-r1 asked for I2/a -> P2(1)/c, was refused without being told
    what WAS available, and spent the rest of the run in P-1."""
    from cctbx import sgtbx
    from cctbx.sgtbx import subgroups as _subgroups
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    try:
        groups = _subgroups.subgroups(old_group.info()).groups_parent_setting()
    except Exception:  # noqa: BLE001 - a menu, never a blocker
        return out
    for g in groups:
        if g.order_z() >= old_group.order_z():
            continue
        info = sgtbx.space_group_info(group=g)
        sym = str(info)
        if sym in seen:
            continue
        seen.add(sym)
        out.append({"space_group": sym,
                    "number": int(g.type().number()),
                    "reference_symbol": str(info.type().lookup_symbol()),
                    "index": int(old_group.order_z() // g.order_z())})
    out.sort(key=lambda d: (d["index"], -d["number"]))
    return out[:limit]


def _absence_gate(ses, group, accept: bool, current_group=None
                  ) -> tuple[dict[str, Any] | None, str | None]:
    """Audit the target group's systematic absences on the raw data.

    Returns (audit, refusal). The refusal fires only when the target ADDS
    absence conditions beyond the current group and those are
    'undecidable' or 'violated' - and never when accept=True. Sessions
    without raw intensities get (None, None)."""
    from cctbx import sgtbx

    ds = getattr(ses, "dataset", None)
    raw = getattr(ds, "intensities", None) if ds is not None else None
    if raw is None:
        return None, None
    from .absence_test import absence_contrast, describe
    try:
        raw = raw.set_observation_type_xray_intensity()
        c = absence_contrast(raw, group)
    except Exception as e:  # noqa: BLE001 - the audit must not block a change
        return {"error": f"absence audit failed: {type(e).__name__}: {e}"}, None
    audit: dict[str, Any] = {
        "target": str(sgtbx.space_group_info(group=group)),
        "verdict": c["verdict"], "line": describe(c),
        "absent": c["absent"], "present": c["present"],
        "ratio_mean": c.get("ratio_mean"),
        "ratio_strong": c.get("ratio_strong"),
        "discarded_fraction": c["discarded_fraction"],
        "centring": c.get("centring"),
        **({"n_expected_absent_classes": c["n_expected_absent_classes"],
            "expected_absent_classes": c["expected_absent_classes"]}
           if c["verdict"] == "absence_classes_unobserved" else {}),
    }
    # absence_classes_unobserved (the group HAS conditions but this file
    # sampled none of them) is exactly as unproven as undecidable - a
    # zero-observation class is consistent with the target group but is
    # not evidence for it either; treating it as settled would be the same
    # 'no_absence_conditions' conflation this state exists to fix (ka1-org
    # P5), just relocated to the change_space_group gate instead of the
    # screen table.
    unproven = c["verdict"] in ("undecidable", "violated",
                                "absence_classes_unobserved")
    if unproven:
        # screw axes / glide planes: their classes are small and a wrong
        # call costs little data - report, do not block (P2(1)/c on weak
        # data is routinely settled by solution trials, and that is fine
        # as long as the report says so)
        audit["warning"] = (
            f"the systematic absences of '{audit['target']}' are "
            f"{c['verdict']} in the data ({audit['line']}): this "
            "declaration rests on solution trials / chemistry, not on the "
            "extinctions - say so in the report")
    cen = c.get("centring") or {}
    cen_n = (cen.get("absent") or {}).get("n") or 0
    cen_unproven = cen_n > 0 and cen.get("verdict") in ("undecidable",
                                                         "violated")
    if not cen_unproven:
        return audit, None
    if accept:
        audit["accepted_by_caller"] = True
        return audit, None
    # the centring is the one absence class whose adoption throws away a
    # large share of the observations from every later merge and
    # refinement - only refuse when the target ADDS centring translations
    adds = True
    if current_group is not None:
        try:
            adds = current_group.n_ltr() < group.n_ltr()
        except Exception:  # noqa: BLE001
            adds = True
    if not adds:
        return audit, None
    return audit, (
        f"refused: the data do not show the lattice-centring absences of "
        f"'{audit['target']}' - centring class: "
        f"{cen.get('absent', {}).get('n')} obs, <I/sig> "
        f"{cen.get('absent', {}).get('mean_i_over_sig')}, "
        f"{100 * (cen.get('absent', {}).get('strong_fraction') or 0):.1f}% "
        f"> 3sig vs the kept reflections <I/sig> "
        f"{cen.get('present', {}).get('mean_i_over_sig')}, "
        f"{100 * (cen.get('present', {}).get('strong_fraction') or 0):.1f}% "
        f"> 3sig (evidence: {cen.get('verdict')}). Declaring it would "
        f"discard {100 * cen.get('discarded_fraction', 0):.0f}% of the "
        "observations from every later merge and refinement, and R "
        "factors computed on the remainder look better for the wrong "
        "reason (pa2 hex: R-3 on noise, R1 0.14 in the wrong group). "
        "Absences that cannot be told from noise are no evidence: solve "
        "in the primitive candidates first (screen_space_groups ranks "
        "them), or pass accept_absences=true with the independent "
        "evidence written in the report.")


class ChangeSpaceGroup(_ProjectTool):
    name = "change_space_group"
    description = (
        "Re-declare the model in a different space group of the SAME unit "
        "cell and rebuild the asymmetric unit (both directions: adopt a "
        "higher group suggested by check_symmetry - merging now-equivalent "
        "atoms - or descend to a subgroup - the ASU grows). "
        "adopt_suggestion=true runs check_symmetry internally and applies "
        "its auto suggestion end-to-end (group + fitted origin shift). "
        "Manual mode takes space_group (H-M symbol IN THE CURRENT CELL "
        "SETTING, e.g. 'P 1 21/a 1'); the origin is fitted from the "
        "content, never shifted by hand. A refused descent lists the "
        "subgroups that ARE available in the current setting. The model "
        "must actually obey the added symmetry: each added operation needs "
        "a site-match fraction >= min_match_fraction or the tool refuses. "
        "On an ATOMLESS session (vendor-hkl cold start, group decided via "
        "screen_space_groups + solution trials) an explicit space_group "
        "DECLARES the group instead: data re-merged, solvers/run_shelxt "
        "emit it, and a new node preserves it across failures and restarts. "
        "This changes the parameterization, not the truth: always re-refine "
        "and compare against the pre-change node (branch first), and only "
        "keep the higher symmetry if the DATA support it.")
    params_schema = {
        "type": "object",
        "properties": {
            "adopt_suggestion": {
                "type": "boolean", "default": False,
                "description": "run check_symmetry and apply its suggested "
                               "group + origin shift automatically"},
            "space_group": {
                "type": "string",
                "description": "target H-M symbol in the current cell "
                               "setting (ignored with adopt_suggestion)"},
            "min_match_fraction": {
                "type": "number", "default": 0.975,
                "description": "required site-match fraction for each ADDED "
                               "operation; lowering it below 0.975 is an "
                               "explicit override that must be justified "
                               "in the report"},
            "tolerance_A": {"type": "number", "default": 0.35},
            "jitter_A": {
                "type": "number",
                "description": "symmetry-breaking random displacement (A) "
                               "applied after a DESCENT to a subgroup "
                               "(default 0.03 when descending, 0 when "
                               "ascending). A model refined in the higher "
                               "group is a least-squares SADDLE POINT in "
                               "the subgroup - perfectly correlated halves "
                               "never differentiate without this kick. Set "
                               "0 to disable explicitly."},
            "accept_absences": {
                "type": "boolean", "default": False,
                "description": "The tool audits the target group's "
                               "systematic absences on the raw data "
                               "(absent class vs the reflections the group "
                               "keeps) and REFUSES a group whose new "
                               "absences are 'undecidable' or 'violated' - "
                               "absences that cannot be told from noise are "
                               "no evidence, and a centred lattice in that "
                               "state discards those observations from "
                               "every later refinement (pa2 hex: R-3 "
                               "declared on noise, 2/3 of the data merged "
                               "away, R1 0.14 in the wrong group). Pass "
                               "true only with independent evidence "
                               "(solution trials, chemistry) recorded in "
                               "the report."},
        },
    }

    def run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        from cctbx import crystal, sgtbx, xray

        ses = ctx.session
        if ses is None or ses.model is None:
            return ToolResult.failure("no model loaded")
        xs = ses.model
        if xs.scatterers().size() == 0:
            # Atomless session (vendor-hkl cold start): nothing to verify
            # operations against, but the GROUP DECISION often lands here
            # first - screening + solution attempts settle it before any
            # atoms exist. Both r22 arms hit the old refusal and invented
            # the same workaround (hand-write a start.ins carrying the
            # group, re-ingest). With an explicit space_group this now
            # DECLARES the group: data re-merged, session symmetry set
            # (run_shelxt/solvers emit it), and a canonical empty model
            # committed so failures and restarts retain the declaration.
            return self._declare_atomless(ses, params)
        tol = float(params.get("tolerance_A", 0.35))
        min_frac = float(params.get("min_match_fraction", 0.975))

        # -- resolve the target group --------------------------------------
        if params.get("adopt_suggestion"):
            audit = CheckSymmetry(self.project).run(ctx, tolerance_A=tol)
            if not audit.ok:
                return audit
            s = audit.summary
            target = s.get("suggested_space_group_current_basis")
            if not target:
                bl = s.get("borderline_suggestion")
                hint = (f" Borderline candidate exists "
                        f"({bl['space_group_current_basis']}, min fraction "
                        f"{bl['min_fraction']:.2f}) - adopting it requires "
                        f"an explicit space_group= call with "
                        f"min_match_fraction lowered and a justification."
                        if bl else "")
                return ToolResult.failure(
                    "check_symmetry found no auto-adoptable extra symmetry "
                    "(verdict: " + str(s.get("verdict", ""))[:200] + ")."
                    + hint)
        else:
            target = params.get("space_group")
            if not target:
                return ToolResult.failure(
                    "give space_group (H-M in the current cell setting) or "
                    "adopt_suggestion=true")

        try:
            new_sgi = sgtbx.space_group_info(str(target))
        except Exception as exc:  # noqa: BLE001
            return ToolResult.failure(f"cannot parse space group "
                                      f"'{target}': {exc}")
        uc = xs.unit_cell()
        if not new_sgi.group().is_compatible_unit_cell(uc):
            menu = ""
            if new_sgi.group().order_z() < xs.space_group().order_z():
                subs = [m["space_group"] for m in
                        _subgroup_menu(xs.space_group())]
                if subs:
                    menu = (" Subgroups available in the current setting "
                            f"(pass one verbatim): {subs}.")
            return ToolResult.failure(
                f"'{target}' is not compatible with the current cell "
                f"{[round(x, 3) for x in uc.parameters()]} - "
                f"change_space_group only re-declares symmetry in the SAME "
                f"cell setting (no basis change). Give the symbol in the "
                f"current setting (e.g. 'P 1 21/a 1' rather than 'P 21/c')."
                + menu)

        old_group = xs.space_group()
        new_group = new_sgi.group()
        old_ops = {str(op) for op in old_group.all_ops()}

        # -- DESCENT: resolve the requested type as a subgroup of the
        # current group in the CURRENT setting. The standard-setting ops of
        # the target usually do NOT coincide with the actual subgroup's ops
        # (e.g. the 2_1 inside P2_1/c carries z+1/2; the 2 inside C2/c sits
        # off the standard C2 origin) - matching them against the model and
        # "closing the group" would wrongly reconstruct the supergroup.
        # A model refined in the supergroup obeys EVERY subgroup by
        # construction, so no site verification is needed here at all.
        if (new_group.type().number() != old_group.type().number()
                and new_group.order_z() < old_group.order_z()):
            from cctbx.sgtbx import subgroups as _subgroups
            want = new_group.type().number()
            cands = [g for g in _subgroups.subgroups(
                         old_group.info()).groups_parent_setting()
                     if g.type().number() == want]
            if not cands:
                subs = [m["space_group"] for m in _subgroup_menu(old_group)]
                return ToolResult.failure(
                    f"'{target}' (No. {want}) is not a subgroup type of "
                    f"the current group {old_group.info()} - descent is "
                    f"only defined into actual subgroups. Subgroups "
                    f"available in the current setting (pass one "
                    f"verbatim): {subs}")
            new_group = cands[0]
            new_sgi = sgtbx.space_group_info(group=new_group)
            old_ops = {str(op) for op in old_group.all_ops()}

        # -- verify (and if needed origin-correct) in the ORIGINAL frame ---
        # Shifting the structure is NOT sound: the declared ops stay put
        # while the content moves. If the given symbol's added ops fail
        # strictly, fit each failing rotation's translation in place,
        # snap it to /12, and rebuild the group from the fitted ops; the
        # result must be the same group TYPE as requested (same abstract
        # group, origin resolved by the actual content).
        # (the old origin_shift argument is gone: shifting the content
        # silently breaks its relation to the declared symmetry; the
        # annotated symbol from check_symmetry carries the origin, or the
        # plain symbol lets the tool fit it)
        xs_w = xs
        added = [op for op in new_group.all_ops()
                 if str(op) not in old_ops]
        applied_shift = None

        def _verify_pass(xs_c):
            """Verify each added op on xs_c (translation fit + /12 snap
            when the strict match fails). Returns (report, refit_ops,
            None) on success, else (report, None, problem) where problem
            is ('offgrid', op, fm) - the fit is good but its translation
            is irrational, fixable only by a polar origin shift - or
            ('fail', op, entry)."""
            rep: list[dict] = []
            rf: list[Any] = []
            for op in added:
                m = _direct_match_fraction(xs_c, op, tol_frac_A=tol)
                entry = {"op": str(op), **m}
                if m["fraction"] >= min_frac:
                    rep.append(entry)
                    continue
                fm = _fit_translation_match(xs_c, op, tol_frac_A=tol)
                if fm["fraction"] >= min_frac:
                    if any(abs(float(x) * 12 - round(float(x) * 12)) > 0.35
                           for x in fm["t_fitted"]):
                        return rep, None, ("offgrid", op, fm)
                    t12 = [int(round(float(x) * 12)) % 12
                           for x in fm["t_fitted"]]
                    op2 = sgtbx.rt_mx(op.r(), sgtbx.tr_vec(t12, 12))
                    m2 = _direct_match_fraction(xs_c, op2, tol_frac_A=tol)
                    if m2["fraction"] >= min_frac:
                        rep.append({"op": str(op2),
                                    "origin_refitted": True, **m2})
                        rf.append(op2)
                        continue
                return rep, None, ("fail", op,
                                   {**entry, "fitted": fm["t_fitted"],
                                    "fit_fraction": fm["fraction"]})
            return rep, rf, None

        op_report, refit, problem = _verify_pass(xs_w)
        if problem is not None and problem[0] == "offgrid":
            # the op holds but its translation is off the /12 grid: the
            # residual lives along the old group's polar (floating-origin)
            # directions, where shifting the content IS sound
            s_p, _tn = _polar_shift_for(old_group, problem[1].r(),
                                        problem[2]["t_fitted"])
            if s_p is not None:
                xs_try = xs_w.apply_shift(
                    tuple(s_p), recompute_site_symmetries=True)
                rep2, rf2, prob2 = _verify_pass(xs_try)
                if prob2 is None:
                    xs_w = xs_try
                    applied_shift = [round(float(x), 4) for x in s_p]
                    op_report, refit, problem = rep2, rf2, None
        if problem is not None:
            kind, op_bad, info = problem
            if kind == "offgrid":
                return ToolResult.failure(
                    f"'{op_bad.r().as_xyz()}' fits the model (fraction "
                    f"{info['fraction']:.3f}) but its translation "
                    f"{info['t_fitted']} is not a /12 crystallographic "
                    f"vector and no polar origin shift can standardize it "
                    f"- the pseudo-op is incompatible with the declared "
                    f"symmetry. Details: {op_report + [info]}")
            return ToolResult.failure(
                f"model does not obey '{op_bad}' (fraction "
                f"{info['fraction']:.3f} < {min_frac}, refit did not "
                f"help). The extra symmetry is not real at this "
                f"tolerance - if data-side evidence still points to it "
                f"(audit_reflection_data), the model likely absorbed "
                f"twin/disorder error; fix the model first. "
                f"Details: {op_report + [info]}")
        if refit:
            g2 = sgtbx.space_group(old_group)
            try:
                for op2 in refit:
                    g2.expand_smx(op2)
            except Exception as exc:  # noqa: BLE001
                return ToolResult.failure(
                    f"origin-refitted ops do not close a group: {exc}")
            if (g2.type().number()
                    != new_group.type().number()):
                return ToolResult.failure(
                    f"the content's actual symmetry closes to "
                    f"{sgtbx.space_group_info(group=g2)} (No. "
                    f"{g2.type().number()}), not the requested '{target}' "
                    f"(No. {new_group.type().number()}) - use the "
                    f"suggestion from check_symmetry.")
            new_group = g2
            new_sgi = sgtbx.space_group_info(group=g2)

        # -- origin standardization for centric closures -------------------
        # SHELX (LATT convention) and CIF interop require -1 AT the origin.
        # A closure like "P 1 21/c 1 (a,b-5/12,a+c+1/4)" has its inversion
        # centers off-origin: move the origin onto one by a PURE-TRANSLATION
        # change of basis applied consistently to BOTH the group and the
        # content (cell unchanged, hkl indices unchanged - unlike the
        # unsound content-only apply_shift this breaks nothing).
        origin_cb = None
        if new_group.is_centric():
            from fractions import Fraction
            inv_num = None
            inv_den = None
            for op in new_group.all_ops():
                if tuple(op.r().as_double()) != (-1.0, 0.0, 0.0,
                                                 0.0, -1.0, 0.0,
                                                 0.0, 0.0, -1.0):
                    continue
                tn, td = list(op.t().num()), op.t().den()
                if all(n % td == 0 for n in tn):
                    inv_num = None          # (-1|0) already an element
                    break
                if inv_num is None:
                    inv_num, inv_den = tn, td
            if inv_num is not None:
                center = [Fraction(n, 2 * inv_den) for n in inv_num]
                cb_str = ",".join(
                    f"{ax}-{c}" if c > 0 else (f"{ax}+{-c}" if c < 0 else ax)
                    for ax, c in zip(("x", "y", "z"), center))
                cb2 = sgtbx.change_of_basis_op(
                    sgtbx.rt_mx(cb_str, "", 1, 24))
                new_sgi = sgtbx.space_group_info(group=new_group) \
                    .change_basis(cb2)
                new_group = new_sgi.group()
                if not new_group.is_origin_centric():
                    return ToolResult.failure(
                        f"internal: origin standardization via {cb_str} did "
                        f"not produce an origin-centric group - report this")
                xs_w = xs_w.change_basis(cb2)
                origin_cb = cb_str

        # -- rebuild the ASU under the new group ---------------------------
        # H are derived atoms: strip them (riding constraints reference
        # scatterer order which the rebuild destroys) - re-run
        # add_hydrogens afterwards.
        n_h_stripped = 0
        keep = []
        for sc in xs_w.scatterers():
            if sc.scattering_type.strip().capitalize() in ("H", "D"):
                n_h_stripped += 1
            else:
                keep.append(sc)
        if n_h_stripped:
            xs_h = xray.structure(crystal_symmetry=xs_w.crystal_symmetry())
            for sc in keep:
                xs_h.add_scatterer(sc)
            xs_w = xs_h
        sps = crystal.special_position_settings(
            crystal.symmetry(unit_cell=uc, space_group=new_group),
            min_distance_sym_equiv=0.5)
        xs_new = xray.structure(special_position_settings=sps)
        expanded = xs_w.expand_to_p1()          # transforms ADPs correctly
        seen_labels: dict[str, int] = {}
        reps: list[Any] = []                    # scatterers already kept

        def _equiv(site_a, site_b) -> bool:
            for op in new_group.all_ops():
                t = op * site_a
                d = uc.distance(
                    tuple(t[k] - math.floor(t[k] - site_b[k] + 0.5)
                          for k in range(3)), site_b)
                if d <= max(tol, 0.5):
                    return True
            return False

        n_merged = 0
        for sc in expanded.scatterers():
            el = sc.scattering_type
            dup = False
            for kept in reps:
                if kept.scattering_type == el and _equiv(sc.site, kept.site):
                    dup = True
                    break
            if dup:
                n_merged += 1
                continue
            sc2 = sc.customized_copy()
            base = sc.label.strip() or "X"
            n = seen_labels.get(base, 0)
            seen_labels[base] = n + 1
            if n:                                # subgroup direction: new
                sc2.label = f"{base}{chr(ord('a') + n - 1)}"   # independents
            xs_new.add_scatterer(sc2)
            reps.append(sc2)
        xs_new.scattering_type_registry(table="it1992")
        adp_note = None
        if n_merged:
            # merged sites carry ADPs fitted in the OLD parameterization
            # (and may have been snapped onto special positions) - reset to
            # isotropic so the fresh refinement starts positive-definite
            xs_new.convert_to_isotropic()
            for sc in xs_new.scatterers():
                if sc.u_iso < 0.005:
                    sc.u_iso = 0.02
            adp_note = "ADPs reset to isotropic - re-refine iso then aniso"

        n_old = xs.scatterers().size()
        n_new = xs_new.scatterers().size()

        # -- subgroup descent: break the saddle point ----------------------
        # Descending (e.g. C2/c -> C2 on extinction-violation evidence)
        # leaves the ASU halves EXACTLY related by the removed operations;
        # least-squares gradients then cancel pairwise and refinement can
        # never differentiate them - the classic "model closes back to the
        # supergroup" artefact. A small random kick breaks the tie; the
        # data decide whether the halves separate (real lower symmetry)
        # or snap back (pseudo-symmetry confirmed).
        descending = (new_group.order_z() < old_group.order_z())
        jit_note = None
        jit = params.get("jitter_A")
        jit = (0.03 if descending else 0.0) if jit is None else float(jit)
        if jit > 0 and n_new:
            import random as _rnd
            rng = _rnd.Random(42)          # deterministic - auditable
            oi = uc.orthogonalization_matrix()
            for sc in xs_new.scatterers():
                # skip special positions: displacing off the site symmetry
                # would change the chemistry, not break the tie
                ss = sps.site_symmetry(sc.site)
                if ss.is_point_group_1():
                    shift_cart = [rng.gauss(0.0, jit) for _ in range(3)]
                    frac = uc.fractionalize(shift_cart)
                    sc.site = tuple(sc.site[k] + frac[k] for k in range(3))
            jit_note = (f"applied {jit:g} A gaussian symmetry-breaking "
                        f"jitter (seed 42) to general positions - re-refine "
                        f"and compare with the supergroup node; halves "
                        f"snapping back = pseudo-symmetry, separating + "
                        f"extinction violations resolving = real subgroup")

        # DATA side must follow the model: re-merge the raw observations
        # under the new group BEFORE swapping the model in (if the merge
        # fails the session stays consistent). The new r_int is the
        # data-side verdict on the adoption - if it jumps far above the
        # old group's, the data do NOT share the model's pseudo-symmetry.
        data_merge = None
        absence_audit, refusal = _absence_gate(
            ses, new_group, bool(params.get("accept_absences")),
            current_group=old_group)
        if refusal:
            return ToolResult.failure(refusal)
        if getattr(ses, "dataset", None) is not None \
                and getattr(ses.dataset, "intensities", None) is not None:
            try:
                data_merge = ses.set_symmetry(xs_new.crystal_symmetry())
            except Exception as exc:  # noqa: BLE001
                return ToolResult.failure(
                    f"model transforms fine but the reflection data could "
                    f"not be re-merged under '{new_sgi}': {exc}")
        else:
            ses.symmetry = xs_new.crystal_symmetry()
        ses.model = xs_new
        # H were stripped and label sets changed - prune stale metadata
        dropped_meta = []
        labels_new = {sc.label for sc in xs_new.scatterers()}
        for stale_key, why in (
                ("h_riding_meta", "re-run add_hydrogens"),
                ("h_constraints", "rebuilt by add_hydrogens"),
                ("twin", "twin law may coincide with or contradict the new "
                         "symmetry - re-derive with set_twin if needed")):
            if (ses.flags or {}).pop(stale_key, None) is not None:
                dropped_meta.append(f"{stale_key} ({why})")
        rs = (ses.flags or {}).get("restraints")
        if isinstance(rs, list):
            kept_rs = []
            for spec in rs:
                labs = spec.get("atoms") or spec.get("labels") or []
                if all(str(l_).upper() in {x.upper() for x in labels_new}
                       for l_ in labs):
                    kept_rs.append(spec)
                else:
                    dropped_meta.append(
                        f"restraint {spec.get('kind', '?')} {labs}")
            ses.flags["restraints"] = kept_rs

        return ToolResult(ok=True, summary={
            "old_space_group": str(old_group.info()),
            "new_space_group": str(new_sgi),
            "origin_shift_applied": applied_shift,
            **({"symmetry_break_jitter": jit_note} if jit_note else {}),
            **({"origin_change_of_basis": origin_cb,
                "origin_change_of_basis_note": (
                    "the closed group's inversion centers were off-origin; "
                    "group AND content were re-based by this pure origin "
                    "translation together (cell and hkl indices unchanged) "
                    "to satisfy the SHELX/CIF origin-centric convention. "
                    "added_ops_verified are reported in the pre-shift "
                    "frame.")}
               if origin_cb else {}),
            **({"data_merge": data_merge,
                "data_merge_note": (
                    "raw observations re-merged under the new group; "
                    "compare r_int against the previous group's merge "
                    "stats - a large jump means the DATA do not share "
                    "the model's pseudo-symmetry (roll back).")}
               if data_merge else {}),
            "n_atoms_before": n_old,
            "n_atoms_after": n_new,
            "n_h_stripped": n_h_stripped,
            "n_p1_copies_merged": n_merged,
            "added_ops_verified": op_report,
            **({"absence_audit": absence_audit} if absence_audit else {}),
            "dropped_metadata": dropped_meta,
            **({"adp_note": adp_note} if adp_note else {}),
            "note": ("parameterization changed - branch was your job before "
                     "calling this; now re-refine (iso first if the merge "
                     "was large), run_shelxl, and compare R/wR2/GooF against "
                     "the pre-change node. If metrics degrade, the extra "
                     "symmetry is not supported by the data: check out the "
                     "old node and disclose the trial."),
        })

    def _declare_atomless(self, ses, params: dict[str, Any]) -> ToolResult:
        """Atomless space-group declaration (process-audit T8)."""
        from cctbx import crystal, sgtbx, xray

        target = params.get("space_group")
        if not target or params.get("adopt_suggestion"):
            return ToolResult.failure(
                "model has no atoms - there is nothing to verify added "
                "operations against (and adopt_suggestion needs sites). "
                "To DECLARE an already-decided group on this atomless "
                "session, pass space_group=<H-M symbol> explicitly: the "
                "reflection data are re-merged in it, solvers/run_shelxt "
                "will emit it, and a new node saves the declaration across "
                "failures and restarts. Decide the group first "
                "via screen_space_groups + solution trials.")
        if ses.dataset is None or ses.dataset.intensities is None:
            return ToolResult.failure("no reflection data in the session")
        try:
            sgi = sgtbx.space_group_info(str(target))
            new_sym = crystal.symmetry(
                unit_cell=ses.dataset.intensities.unit_cell(),
                space_group_info=sgi)
        except Exception as e:  # noqa: BLE001 - bad symbol/cell combo
            return ToolResult.failure(
                f"cannot declare space group {target!r}: "
                f"{type(e).__name__}: {e}")
        cur = getattr(ses, "symmetry", None)
        absence_audit, refusal = _absence_gate(
            ses, sgi.group(), bool(params.get("accept_absences")),
            current_group=cur.space_group() if cur is not None else None)
        if refusal:
            return ToolResult.failure(refusal)
        previous = str(ses.model.space_group_info())
        stats = ses.set_symmetry(new_sym)
        # A declaration is model state even with zero atoms. Canonical model,
        # merged observations and the next rollback must share the same group.
        ses.model = xray.structure(crystal_symmetry=new_sym)
        ses.cf_info = {}
        ses.refinement_history.clear()
        for key in ("diff_map_peaks", "diff_map_peaks_meta", "f_mask", "scale_k"):
            ses.flags.pop(key, None)
        return ToolResult(ok=True, summary={
            "mode": "atomless_declaration",
            "declared_space_group": str(sgi),
            "previous_space_group": previous,
            "merge": stats,
            **({"absence_audit": absence_audit} if absence_audit else {}),
            "persisted": "canonical model node (original input file remains unchanged)",
            "note": ("no atoms existed to verify against: this DECLARES "
                     "the group (a decision, not a verification) - keep "
                     "the screening/solution evidence for it in the "
                     "report. Data re-merged in the new group; "
                     "run_shelxt / solvers now emit it."),
        })


# ==========================================================================
# canonical relabeling
# ==========================================================================


# ==========================================================================
# ncs_audit: pseudo-symmetry between fragments (process-audit T9)
# ==========================================================================

def _rational_analysis(vec, max_den: int = 6) -> dict[str, Any]:
    """Nearest small-denominator rational per component + max deviation."""
    comps = []
    worst = 0.0
    for v in vec:
        w = v - round(v)                       # into [-0.5, 0.5)
        best = (abs(w), "0")
        for q in (2, 3, 4, 6):
            p = round(w * q)
            dev = abs(w - p / q)
            if dev < best[0] - 1e-12:
                best = (dev, f"{p}/{q}" if p else "0")
        comps.append({"value": round(w, 4), "nearest": best[1],
                      "deviation": round(best[0], 4)})
        worst = max(worst, best[0])
    return {"components": comps, "max_deviation": round(worst, 4),
            "is_rational": worst < 0.02}


def _match_mapped(uc, mapped, sites_b, tol: float):
    """Greedy one-to-one nearest matching (lattice-wrapped), element-
    agnostic so wrong element ASSIGNMENTS surface as mismatches instead
    of breaking the correspondence (the r16 need: labels carried wrong
    elements and the overlay is what proved it)."""
    cands = []
    for i, ma in enumerate(mapped):
        for j, sb in enumerate(sites_b):
            d = tuple(sb[k] - ma[k] for k in range(3))
            d = tuple(x - round(x) for x in d)
            dist = uc.length(d)
            if dist <= tol:
                cands.append((dist, i, j))
    cands.sort()
    used_a: set[int] = set()
    used_b: set[int] = set()
    pairs = []
    for dist, i, j in cands:
        if i in used_a or j in used_b:
            continue
        used_a.add(i)
        used_b.add(j)
        pairs.append((i, j, dist))
    return pairs


class NcsAudit(_ProjectTool):
    name = "ncs_audit"
    description = (
        "Pseudo-symmetry audit between two fragments/molecules: tests the "
        "PSEUDO-TRANSLATION and PSEUDO-INVERSION hypotheses relating them "
        "(lattice-wrapped greedy matching), reports match fraction, RMSD, "
        "the refined operator, whether it sits on RATIONAL fractions - the "
        "missed-crystallographic-operator tell - and an element-mismatch "
        "table for matched pairs (position matching is element-agnostic on "
        "purpose: a wrong C/N assignment shows up as a mismatch instead of "
        "breaking the overlay). Three campaigns hand-wrote exactly this: "
        "r16 pair_match (0.036 A overlay between two 'independent' "
        "molecules - the operator was a MISSED INVERSION CENTRE; a "
        "rational-operator check would have caught the P1 mistake on the "
        "spot), r17 pseudotranslation_pairs (102/114 atoms under "
        "r->-r+(0,0,1/2) - the composite-supercell tell). Evidence, not a "
        "verdict: a strong match on a rational operator means run "
        "check_symmetry / doubt the cell BEFORE more model work. Default "
        "fragments = the two largest identity-bond molecules; Z'=2 "
        "structures, halved-cell suspicions and 'are the two independent "
        "molecules chemically identical' questions are the use cases.")
    params_schema = {
        "type": "object",
        "properties": {
            "fragment_a": {"type": "array", "items": {"type": "string"},
                           "description": "atom labels of fragment A "
                                          "(default: largest molecule)"},
            "fragment_b": {"type": "array", "items": {"type": "string"},
                           "description": "atom labels of fragment B "
                                          "(default: second-largest)"},
            "match_tol_A": {"type": "number", "default": 0.9,
                            "description": "matching distance ceiling"},
        },
    }

    def run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        ses = ctx.session
        if ses is None or ses.model is None \
                or ses.model.scatterers().size() == 0:
            return ToolResult.failure("no model with atoms in the session")
        xs = ses.model
        uc = xs.unit_cell()
        scs = list(xs.scatterers())
        by_label = {sc.label.upper(): i for i, sc in enumerate(scs)}

        def _resolve(labels):
            idxs, missing = [], []
            for lbl in labels:
                i = by_label.get(str(lbl).upper())
                if i is None:
                    missing.append(str(lbl))
                else:
                    idxs.append(i)
            return idxs, missing

        fa, fb = params.get("fragment_a"), params.get("fragment_b")
        if fa and fb:
            ia, miss_a = _resolve(fa)
            ib, miss_b = _resolve(fb)
            if miss_a or miss_b:
                return ToolResult.failure(
                    f"unknown labels: {miss_a + miss_b}")
            frag_note = "explicit fragments"
        else:
            from ..chem.asu_sanity import (_identity_fragments,
                                           _pair_sym_table)
            pst, elements = _pair_sym_table(xs)
            frags, _ = _identity_fragments(xs, pst, elements)
            non_h = [
                [i for i in f
                 if scs[i].scattering_type.strip().capitalize() != "H"]
                for f in frags]
            non_h = [f for f in non_h if len(f) >= 3]
            if len(non_h) < 2:
                # a periodic framework is ONE identity-bond fragment: the
                # default split cannot apply, and that is not an error
                # (pa1: 3 of 10 ncs_audit calls "failed" this way and the
                # agents treated the tool as broken)
                return ToolResult(ok=True, summary={
                    "applicable": False,
                    "no_state_change": True,
                    "verdict": "not applicable: the identity bond graph "
                               "holds fewer than two molecules with >= 3 "
                               "non-H atoms (a periodic framework is one "
                               "fragment), so no pseudo-symmetry test was "
                               "run - nothing is wrong with the model",
                    "fragments_non_h": [len(f) for f in non_h],
                    "note": "to test two halves of a framework (e.g. two "
                            "metal clusters with their linkers) pass "
                            "fragment_a/fragment_b explicitly; for the "
                            "lattice-level question use check_symmetry",
                })
            ia, ib = non_h[0], non_h[1]
            frag_note = ("auto: two largest identity-bond molecules "
                         f"({len(ia)} vs {len(ib)} non-H atoms; all "
                         f"fragments: {[len(f) for f in non_h]})")

        elems_a = [scs[i].scattering_type.strip().capitalize() for i in ia]
        elems_b = [scs[i].scattering_type.strip().capitalize() for i in ib]
        sites_a = [scs[i].site for i in ia]
        sites_b = [scs[i].site for i in ib]
        labels_a = [scs[i].label for i in ia]
        labels_b = [scs[i].label for i in ib]
        tol = float(params.get("match_tol_A") or 0.9)
        n_ref = min(len(ia), len(ib))

        def _centroid(sites):
            return tuple(sum(s[k] for s in sites) / len(sites)
                         for k in range(3))

        ca, cb = _centroid(sites_a), _centroid(sites_b)
        hypotheses: dict[str, Any] = {}
        for name in ("translation", "inversion"):
            if name == "translation":
                op_vec = tuple(cb[k] - ca[k] for k in range(3))

                def _map(sites, v):
                    return [tuple(s[k] + v[k] for k in range(3))
                            for s in sites]
            else:
                op_vec = tuple((ca[k] + cb[k]) / 2 for k in range(3))

                def _map(sites, c):
                    return [tuple(2 * c[k] - s[k] for k in range(3))
                            for s in sites]
            pairs = _match_mapped(uc, _map(sites_a, op_vec), sites_b, tol)
            if pairs:
                # refine the operator from the first-round correspondence,
                # then re-match once
                if name == "translation":
                    deltas = []
                    for i, j, _ in pairs:
                        d = tuple(sites_b[j][k] - sites_a[i][k]
                                  for k in range(3))
                        deltas.append(tuple(
                            d[k] - round(d[k] - op_vec[k])
                            for k in range(3)))
                    op_vec = tuple(sum(d[k] for d in deltas) / len(deltas)
                                   for k in range(3))
                else:
                    centres = [tuple((sites_a[i][k] + sites_b[j][k]) / 2
                                     for k in range(3))
                               for i, j, _ in pairs]
                    op_vec = tuple(
                        sum(c[k] for c in centres) / len(centres)
                        for k in range(3))
                pairs = _match_mapped(uc, _map(sites_a, op_vec),
                                      sites_b, tol)
            frac = len(pairs) / n_ref if n_ref else 0.0
            rmsd = (math.sqrt(sum(d * d for _, _, d in pairs)
                              / len(pairs)) if pairs else None)
            mismatches = [
                {"a": labels_a[i], "b": labels_b[j],
                 "elements": f"{elems_a[i]} vs {elems_b[j]}",
                 "d": round(d, 3)}
                for i, j, d in pairs if elems_a[i] != elems_b[j]]
            rat = _rational_analysis(op_vec)
            head = "t = (" if name == "translation" else "centre = ("
            entry: dict[str, Any] = {
                "operator": head + ", ".join(f"{v:.4f}"
                                             for v in op_vec) + ")",
                "match_fraction": round(frac, 3),
                "n_matched": len(pairs),
                "rmsd_A": round(rmsd, 3) if rmsd is not None else None,
                "rational": rat,
            }
            if mismatches:
                entry["element_mismatches"] = mismatches[:12]
            if frac >= 0.8 and (rmsd if rmsd is not None else 9) <= 0.35:
                if rat["is_rational"]:
                    entry["verdict"] = (
                        "STRONG match on a RATIONAL operator - this looks "
                        "like a missed CRYSTALLOGRAPHIC "
                        + ("translation (components near 1/2 mean "
                           "centring or a doubled/composite cell - audit "
                           "the cell)" if name == "translation" else
                           "inversion centre (run check_symmetry; "
                           "reconsider an acentric-group choice)")
                        + " before doing more model work")
                else:
                    entry["verdict"] = (
                        "strong NCS (operator not on rational fractions): "
                        "genuine Z'>1 relationship - element mismatches "
                        "between the copies deserve competitive "
                        "refinement, and similarity restraints between "
                        "the copies are defensible")
            elif frac >= 0.5:
                entry["verdict"] = (
                    "partial match - when the two halves were built and "
                    "refined independently (unequal atom counts, element "
                    "mix-ups), a missed operator often degrades to "
                    "exactly this; if this hypothesis clearly beats the "
                    "other one, run check_symmetry before trusting Z'>1")
            else:
                entry["verdict"] = "no meaningful match"
            hypotheses[name] = entry

        return ToolResult(ok=True, summary={
            "fragments": frag_note,
            "n_atoms": {"a": len(ia), "b": len(ib)},
            "hypotheses": hypotheses,
            "note": ("evidence, not a verdict: strong+rational => run "
                     "check_symmetry / audit the cell first; "
                     "strong+irrational => true NCS, compare the copies "
                     "chemically. Only translation and inversion "
                     "hypotheses are tested (the two that decided "
                     "r16/r17); a general rotation NCS reads as no "
                     "meaningful match here"),
        })
