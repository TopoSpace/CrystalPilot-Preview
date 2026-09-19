"""Systematic-absence evidence WITH a null comparison.

The classic screen scores a candidate group by the intensity in its
systematically-absent classes: a class that averages noise is 'absent',
one that carries signal is 'violated'. That test has no control. On weak
data every class averages noise - pa2 hex-l2-r2: the whole dataset had
<I/sigma> 0.40, so the R-centring class (<I/sigma> 0.39, 225 306
observations, 5.1 % above 3 sigma) looked 'consistent', seven R groups
led the candidate table, the agent declared R-3 and two thirds of the
observations were merged away as 'absent'. The allowed class was
indistinguishable from the absent one: 0.40 vs 0.39, 5.2 % vs 5.1 %.

This module compares the absent class against the reflections the same
group keeps (the null hypothesis 'these are ordinary reflections') and
returns a verdict in three states - absent / undecidable / violated -
instead of a boolean. `undecidable` is the honest answer on weak data:
the absence is neither confirmed nor refuted, so the group ranks after
the groups with no absence conditions and needs a solution trial to be
adopted. The lattice centring is audited separately because it is the
one absence class whose adoption discards observations from every later
refinement.
"""
from __future__ import annotations

from typing import Any


def _zone_of(h: int, k: int, l: int) -> str:
    """Which of the 7 canonical hkl zones an index belongs to (the axes
    h00/0k0/00l, the principal zones 0kl/h0l/hk0, and the general hkl) -
    a partition of Z^3 \\ {0} used to COUNT distinct absence classes
    without hand-encoding International Tables reflection conditions."""
    zeros = (h == 0) + (k == 0) + (l == 0)
    if zeros == 2:
        return "00l" if (h == 0 and k == 0) else ("0k0" if (h == 0 and l == 0) else "h00")
    if zeros == 1:
        return "0kl" if h == 0 else ("h0l" if k == 0 else "hk0")
    return "hkl"


def absence_class_summary(space_group, grid: int = 8) -> dict[str, Any]:
    """How many DISTINCT systematic-absence classes `space_group` imposes,
    and which zones they are in - a property of the group alone,
    independent of any dataset (contrast with n_absent_obs in
    screen_space_groups, which counts how many of THIS FILE's reflections
    happen to land in those classes).

    ka1-org P5: 'no_absence_conditions' was reported byte-identically for
    two different things - a group that truly has no absence-generating
    symmetry (P1, P222, Pmmm, ...) vs a group that DOES (P21212121's
    h00/0k0/00l rows) but whose classes simply have zero reflections in
    THIS file (typical of merged/fcf-derived data with absences already
    stripped) - which is actually a positive fingerprint the old wording
    threw away. This function answers the group-theoretic half honestly:
    tested against cctbx's own sys_absent_flags() (the same primitive
    screen_space_groups already trusts) on a synthetic index grid, zone by
    zone, so it generalises to any of the 230 space groups without a
    lookup table. grid=8 comfortably covers every screw/glide/centring
    modulus in International Tables (max 6)."""
    from cctbx import crystal, miller
    from cctbx.array_family import flex

    cs = crystal.symmetry(unit_cell=(10, 11, 12, 90, 90, 90),
                          space_group=space_group,
                          assert_is_compatible_unit_cell=False)
    zone_idx: dict[str, list] = {z: [] for z in
                                 ("h00", "0k0", "00l", "0kl", "h0l", "hk0", "hkl")}
    for h in range(-grid, grid + 1):
        for k in range(-grid, grid + 1):
            for l in range(-grid, grid + 1):
                if (h, k, l) != (0, 0, 0):
                    zone_idx[_zone_of(h, k, l)].append((h, k, l))
    classes = []
    for zone, indices in zone_idx.items():
        ms = miller.set(cs, flex.miller_index(indices), anomalous_flag=False)
        if ms.sys_absent_flags().data().count(True):
            classes.append(zone)
    # canonical, readable order: axes, then zones, then general
    order = {z: i for i, z in enumerate(
        ("h00", "0k0", "00l", "0kl", "h0l", "hk0", "hkl"))}
    classes.sort(key=lambda z: order[z])
    return {"n_classes": len(classes), "classes": classes}


def class_stats(ios, viol_sigma: float) -> dict[str, Any]:
    from cctbx.array_family import flex
    n = ios.size()
    if n == 0:
        return {"n": 0, "mean_i_over_sig": None, "strong_fraction": None}
    return {
        "n": int(n),
        "mean_i_over_sig": round(float(flex.mean(ios)), 3),
        "strong_fraction": round((ios > viol_sigma).count(True) / n, 4),
    }


def contrast_verdict(absent: dict[str, Any], present: dict[str, Any],
                     viol_sigma: float = 3.0, *,
                     class_summary: dict[str, Any] | None = None
                     ) -> dict[str, Any]:
    """Compare an absent class with the present class of the same group.

    Rules (each a plain number the agent can check):
    - violated: the absent class is not weak in absolute terms
      (mean I/sigma >= 2 or >= 10 % of it above viol_sigma) - the old
      criterion, kept.
    - absent: the class is weak AND clearly weaker than the present
      class: both the mean-I/sigma ratio and the strong-fraction ratio
      are <= 0.5. A truly extinct class on usable data sits at a ratio
      of 0.1-0.3.
    - undecidable: otherwise - in particular whenever the present class
      itself has fewer than 5 % strong reflections, because then there
      is no signal to contrast against.
    - no_absence_conditions / absence_classes_unobserved: na == 0 (no
      reflections of THIS FILE fall in the group's absent class(es)) is
      ambiguous by itself - it means either of two different things, and
      class_summary (absence_class_summary(group), a DATA-INDEPENDENT
      group-theoretic fact) is what tells them apart: the group may
      genuinely impose no absence condition at all (no_absence_conditions
      - unfalsifiable by this test, not evidence either way), or it may
      impose conditions that this file simply never sampled
      (absence_classes_unobserved - typical of merged/fcf-derived data
      with absences already stripped before export; CONSISTENT with the
      group, never proof of it). Byte-identical wording for these two
      used to throw away that second, genuinely informative case
      (ka1-org P5). Callers that omit class_summary get the old,
      unconditional no_absence_conditions label (safe default; every
      internal caller now passes it).
    """
    na, npres = absent.get("n") or 0, present.get("n") or 0
    if na == 0:
        n_classes = (class_summary or {}).get("n_classes") or 0
        if n_classes:
            return {"verdict": "absence_classes_unobserved",
                    "ratio_mean": None, "ratio_strong": None,
                    "n_expected_absent_classes": n_classes,
                    "expected_absent_classes": class_summary.get("classes"),
                    "n_observed_in_absent_classes": 0}
        return {"verdict": "no_absence_conditions", "ratio_mean": None,
                "ratio_strong": None}
    ma = absent["mean_i_over_sig"] or 0.0
    fa = absent["strong_fraction"] or 0.0
    if ma >= 2.0 or fa >= 0.10:
        verdict = "violated"
    elif npres == 0:
        verdict = "undecidable"
    else:
        mp = present["mean_i_over_sig"] or 0.0
        fp = present["strong_fraction"] or 0.0
        ratio_mean = (ma / mp) if mp > 1e-9 else None
        ratio_strong = (fa / fp) if fp > 1e-9 else None
        weak_data = fp < 0.05
        if (not weak_data and ratio_mean is not None
                and ratio_strong is not None
                and ratio_mean <= 0.5 and ratio_strong <= 0.5):
            verdict = "absent"
        else:
            verdict = "undecidable"
        return {"verdict": verdict,
                "ratio_mean": (None if ratio_mean is None
                               else round(ratio_mean, 3)),
                "ratio_strong": (None if ratio_strong is None
                                 else round(ratio_strong, 3)),
                "present_data_too_weak": weak_data}
    return {"verdict": verdict, "ratio_mean": None, "ratio_strong": None}


def absence_contrast(intensities, space_group, viol_sigma: float = 3.0
                     ) -> dict[str, Any]:
    """Absent-vs-present statistics of `space_group` on unmerged
    intensities (any symmetry; only indices + cell are used).

    Returns {absent: {n, mean_i_over_sig, strong_fraction}, present: {...},
    verdict, ratio_mean, ratio_strong, discarded_fraction, centring: {...}}
    where centring repeats the audit for the lattice translations alone.
    """
    from cctbx import crystal, miller, sgtbx
    from cctbx.array_family import flex

    uc = intensities.unit_cell()
    idx = intensities.indices()
    i_obs = intensities.data()
    sig = intensities.sigmas()
    if sig is None:
        sig = flex.double(i_obs.size(), 1.0)
    safe_sig = flex.double([max(s, 1e-9) for s in sig])
    ios_all = i_obs / safe_sig

    def _audit(group) -> dict[str, Any]:
        cs = crystal.symmetry(unit_cell=uc, space_group=group,
                              assert_is_compatible_unit_cell=False)
        ms = miller.set(cs, idx, anomalous_flag=False)
        absent = ms.sys_absent_flags().data()
        a = class_stats(ios_all.select(absent), viol_sigma)
        p = class_stats(ios_all.select(~absent), viol_sigma)
        v = contrast_verdict(a, p, viol_sigma,
                             class_summary=absence_class_summary(group))
        n_tot = max(1, i_obs.size())
        return {"absent": a, "present": p, **v,
                "discarded_fraction": round(a["n"] / n_tot, 4)}

    out = _audit(space_group)
    # lattice centring alone: the translation subgroup of the group
    centring = sgtbx.space_group()
    for op in space_group.all_ops():
        if op.r().is_unit_mx():
            centring.expand_smx(op)
    if centring.n_ltr() > 1:
        out["centring"] = {"lattice": space_group.conventional_centring_type_symbol()
                           if hasattr(space_group, "conventional_centring_type_symbol")
                           else "?", **_audit(centring)}
    else:
        out["centring"] = {"lattice": "P", "verdict": "no_absence_conditions",
                           "absent": {"n": 0}, "discarded_fraction": 0.0}
    return out


def describe(c: dict[str, Any]) -> str:
    """One line for a tool message."""
    a, p = c.get("absent") or {}, c.get("present") or {}
    v = c.get("verdict")
    if v == "no_absence_conditions":
        return "no absence conditions"
    if v == "absence_classes_unobserved":
        n = c.get("n_expected_absent_classes")
        classes = ", ".join(c.get("expected_absent_classes") or [])
        return (f"{n} expected-absent class(es) ({classes}) but ZERO of "
                f"this file's {p.get('n')} other reflections fall in "
                "them - consistent with, not proof of, this group "
                "(typical of merged/fcf-derived data with absences "
                "already stripped before export)")
    base = (f"absent class {a.get('n')} obs, <I/sig> {a.get('mean_i_over_sig')}, "
            f"{100 * (a.get('strong_fraction') or 0):.1f}% > 3sig vs present class "
            f"{p.get('n')} obs, <I/sig> {p.get('mean_i_over_sig')}, "
            f"{100 * (p.get('strong_fraction') or 0):.1f}% > 3sig")
    if v == "absent":
        return f"ABSENT (ratios {c.get('ratio_mean')}/{c.get('ratio_strong')}): {base}"
    if v == "violated":
        return f"VIOLATED: {base}"
    return (f"UNDECIDABLE (absent and present classes look alike, ratios "
            f"{c.get('ratio_mean')}/{c.get('ratio_strong')}"
            + (", present class itself < 5% strong"
               if c.get("present_data_too_weak") else "")
            + f"): {base}")
