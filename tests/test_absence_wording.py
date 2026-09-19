"""ka1 WP2 Part B: absence screening must say when the data cannot decide.

ka1-org P5: `no_absence_conditions` was reported byte-identically for two
different things - a group with truly no absence-generating symmetry (P1,
P222, ...) vs a group that DOES have conditions (P21212121's h00/0k0/00l
rows) but whose classes simply have zero reflections in THIS file (typical
of merged/fcf-derived data with absences already stripped before export) -
a positive fingerprint the old wording threw away. This file tests the fix
end to end: absence_class_summary (group-theoretic, data-independent),
contrast_verdict/describe (the new 'absence_classes_unobserved' state),
screen_space_groups' data-level absence_screening_power summary, and the
change_space_group gate (_absence_gate).

Element-agnostic / group-agnostic by construction: every fixture is a
synthetic P1 miller array read through cctbx's own sys_absent_flags(), not
a hand-encoded reflection condition, and the space groups exercised span
orthorhombic through cubic (P21212121, P4(1)2(1)2, Fd-3m, P21/c, C2/c) -
no test crystal is special-cased. One-directional wording (P12): the new
text is checked to never claim "confirmed".
"""
from __future__ import annotations

import random
from types import SimpleNamespace

from cctbx import crystal, miller, sgtbx
from cctbx.array_family import flex

from crystalpilot.refine.absence_test import (absence_class_summary,
                                              contrast_verdict, describe)
from crystalpilot.refine.sg_screen import screen_space_groups
from crystalpilot.refine.tools_symmetry import _absence_gate

CELL_ORTHO = (10.0, 12.0, 14.0, 90.0, 90.0, 90.0)
CELL_MONO = (10.0, 12.0, 14.0, 90.0, 105.0, 90.0)


# --------------------------------------------------------------------------- #
# absence_class_summary: a property of the group alone, no data involved -
# checked against International Tables reflection conditions by hand
# --------------------------------------------------------------------------- #

def test_class_summary_matches_international_tables_across_crystal_systems():
    # orthorhombic, three independent 2(1) screw axes -> h00/0k0/00l
    assert absence_class_summary(
        sgtbx.space_group_info("P 21 21 21").group()) == {
            "n_classes": 3, "classes": ["h00", "0k0", "00l"]}
    # no absence-generating symmetry at all
    assert absence_class_summary(sgtbx.space_group_info("P 1").group()) == {
        "n_classes": 0, "classes": []}
    assert absence_class_summary(sgtbx.space_group_info("P 2 2 2").group()) == {
        "n_classes": 0, "classes": []}
    # tetragonal: the 4(1) axis (00l) is NOT present in P4(1)2(1)2's
    # standard setting - only the two 2(1)'s along a/b show
    assert absence_class_summary(sgtbx.space_group_info("P 4 21 2").group()) == {
        "n_classes": 2, "classes": ["h00", "0k0"]}
    # cubic diamond glide: every one of the 7 zones, including general hkl
    assert absence_class_summary(sgtbx.space_group_info("F d -3 m").group()) == {
        "n_classes": 7,
        "classes": ["h00", "0k0", "00l", "0kl", "h0l", "hk0", "hkl"]}
    # monoclinic c-glide + 2(1) axis: the c-glide's h0l condition (l=2n)
    # also restricts its own h=0 sub-case (00l reflections all have k=0),
    # so 00l is a class DISTINCT from h0l even though one operator causes
    # both - and distinct again from 0k0, caused by the 2(1) axis instead
    assert absence_class_summary(
        sgtbx.space_group_info("P 1 21/c 1").group()) == {
            "n_classes": 3, "classes": ["0k0", "00l", "h0l"]}
    # C-centring (h+k=2n) is a general condition: it reaches every zone
    # except 00l (h=k=0 always makes h+k even) - so the centred group's
    # class list is the primitive group's classes PLUS the general 'hkl'
    # zone, still missing 00l as P21/c did
    assert absence_class_summary(
        sgtbx.space_group_info("C 1 2/c 1").group()) == {
            "n_classes": 7,
            "classes": ["h00", "0k0", "00l", "0kl", "h0l", "hk0", "hkl"]}


# --------------------------------------------------------------------------- #
# contrast_verdict / describe: na == 0 is ambiguous by itself -
# class_summary is what tells "no conditions" apart from "never sampled"
# --------------------------------------------------------------------------- #

def test_zero_observations_in_the_absent_class_is_two_different_things():
    absent0 = {"n": 0, "mean_i_over_sig": None, "strong_fraction": None}
    present = {"n": 500, "mean_i_over_sig": 12.3, "strong_fraction": 0.55}

    # the group HAS conditions, this file just never sampled them
    csum = absence_class_summary(sgtbx.space_group("C 2y"))
    v = contrast_verdict(absent0, present, class_summary=csum)
    assert v["verdict"] == "absence_classes_unobserved"
    assert v["n_expected_absent_classes"] == 6
    assert v["expected_absent_classes"] == [
        "h00", "0k0", "0kl", "h0l", "hk0", "hkl"]
    assert v["n_observed_in_absent_classes"] == 0

    # the group genuinely has none - unfalsifiable, not the same claim
    v_none = contrast_verdict(absent0, present,
                              class_summary={"n_classes": 0, "classes": []})
    assert v_none["verdict"] == "no_absence_conditions"

    # callers that omit class_summary keep the old, safe default (every
    # internal caller now passes it; this is the compatibility fallback)
    assert contrast_verdict(absent0, present)["verdict"] == "no_absence_conditions"


def test_describe_states_the_class_count_and_says_consistent_not_proof():
    absent0 = {"n": 0, "mean_i_over_sig": None, "strong_fraction": None}
    present = {"n": 500, "mean_i_over_sig": 12.3, "strong_fraction": 0.55}
    csum = absence_class_summary(sgtbx.space_group("C 2y"))
    v = contrast_verdict(absent0, present, class_summary=csum)
    line = describe({"verdict": v["verdict"], "absent": absent0,
                     "present": present,
                     "n_expected_absent_classes": v["n_expected_absent_classes"],
                     "expected_absent_classes": v["expected_absent_classes"]})
    assert "6 expected-absent class(es)" in line
    assert "h00, 0k0, 0kl, h0l, hk0, hkl" in line
    assert "ZERO" in line and "500" in line
    assert "consistent with, not proof of" in line
    assert "confirmed" not in line.lower()  # P12: never claim confirmation


# --------------------------------------------------------------------------- #
# screen_space_groups: absence_screening_power (the data-level summary) and
# the per-candidate wording, both directions
# --------------------------------------------------------------------------- #

def _pa2_data(absent_scale: float, noise_only: bool = False, seed: int = 1,
             cell=CELL_ORTHO):
    """Same construction as test_pa2_tool_fixes.py's _data: a full P1
    sphere; reflections in the C-centring class (h+k odd) get
    `absent_scale` x the signal. Kept local (matching this repo's existing
    per-file-fixture convention) rather than imported across test files."""
    rng = random.Random(seed)
    cs = crystal.symmetry(unit_cell=cell, space_group_symbol="P 1")
    ms = miller.build_set(cs, anomalous_flag=False, d_min=1.2)
    data, sig = flex.double(), flex.double()
    for h, k, l in ms.indices():
        if noise_only:
            i = rng.gauss(0.0, 1.0)
        else:
            i = rng.expovariate(1.0 / 50.0)
            if (h + k) % 2:
                i *= absent_scale
            i += rng.gauss(0.0, 1.0)
        data.append(i)
        sig.append(1.0)
    return miller.array(ms, data, sig).set_observation_type_xray_intensity()


def _all_even_data(cell=CELL_MONO, half_range=8):
    """No reflection here can ever satisfy ANY space group's systematic-
    absence condition: every International Tables condition is a mod-2
    linear form in h, k, l (screw axes, glides, centring alike), and
    h, k, l all even makes every such form even. This is a general,
    group-agnostic way to build a "this file samples NONE of the group's
    absent classes" fixture without hand-enumerating centring types -
    exercised below against a full 35-candidate 'P 2/m' Laue-class
    enumeration (candidate_groups) at once, covering primitive, C-, and
    I-centred settings simultaneously."""
    cs = crystal.symmetry(unit_cell=cell, space_group_symbol="P 1")
    idx = [(h, k, l)
          for h in range(-half_range, half_range + 1, 2)
          for k in range(-half_range, half_range + 1, 2)
          for l in range(-half_range, half_range + 1, 2)
          if (h, k, l) != (0, 0, 0)]
    ms = miller.set(cs, flex.miller_index(idx), anomalous_flag=False)
    data = flex.double([50.0] * len(idx))
    sig = flex.double([5.0] * len(idx))
    return miller.array(ms, data, sig).set_observation_type_xray_intensity()


def test_absence_screening_power_is_none_when_no_class_was_ever_sampled():
    res = screen_space_groups(_all_even_data(),
                              sgtbx.space_group_info("P 2/m").group(),
                              max_out=60)
    assert res["n_candidates_total"] == 35
    assert res["absence_screening_power"] == {
        "level": "none",
        "note": ("this file contains no systematically-absent-class "
                 "reflections at all (typical of data merged/rejected by "
                 "a prior refinement); space-group decisions here must "
                 "rest on E-statistics, Rint by Laue class and solution "
                 "trials.")}
    rows = {r["space_group"]: r for r in res["candidates"]}
    row = rows["P 1 21/c 1"]
    assert row["absence_evidence"] == "absence_classes_unobserved"
    assert row["consistent"] is False
    assert row["n_absent_obs"] == 0
    assert row["n_expected_absent_classes"] == 3
    assert row["expected_absent_classes"] == ["0k0", "00l", "h0l"]
    assert "CONSISTENT with P 1 21/c 1 but is NOT proof of it" in row["note"]
    # a group with genuinely no conditions is untouched by this fixture
    assert rows["P 1 2 1"]["absence_evidence"] == "no_absence_conditions"
    assert rows["P 1 2 1"]["consistent"] is True


def test_absence_screening_power_is_full_and_old_verdicts_are_unchanged():
    # same fixture as
    # test_pa2_tool_fixes.py::TestScreenRanking.test_true_centring_leads_and_is_marked_absent
    # - this is a regression check that the OLD 'absent' verdict path is
    # untouched, plus the NEW absence_screening_power field alongside it
    res = screen_space_groups(_pa2_data(0.0),
                              sgtbx.space_group_info("P 2/m").group(),
                              max_out=40)
    top = res["candidates"][0]
    assert top["space_group"].startswith("C")
    assert top["absence_evidence"] == "absent" and top["consistent"] is True

    with_conditions = [r for r in res["candidates"]
                      if r["absence_evidence"] != "no_absence_conditions"]
    assert len(with_conditions) == 32
    assert res["absence_screening_power"]["level"] == "full"
    assert res["absence_screening_power"]["note"].startswith(
        "all 32 candidate(s) with absence conditions")
    assert "normal discriminating weight" in res["absence_screening_power"]["note"]


# --------------------------------------------------------------------------- #
# _absence_gate: 'absence_classes_unobserved' is exactly as unproven as
# 'undecidable' (warns, never silently settles the declaration) - but only
# the CENTRING sub-check can ever refuse, and a centring with ZERO
# observations in its own class has nothing to discard either way
# --------------------------------------------------------------------------- #

def _ses(ma):
    return SimpleNamespace(dataset=SimpleNamespace(intensities=ma))


def test_gate_warns_but_does_not_refuse_a_noncentred_group_never_sampled():
    audit, refusal = _absence_gate(
        _ses(_all_even_data()), sgtbx.space_group_info("P 1 21/c 1").group(),
        False, current_group=sgtbx.space_group("P 1"))
    assert refusal is None
    assert audit["verdict"] == "absence_classes_unobserved"
    assert "warning" in audit and "solution trials" in audit["warning"]
    assert audit["n_expected_absent_classes"] == 3
    assert audit["expected_absent_classes"] == ["0k0", "00l", "h0l"]


def test_gate_does_not_refuse_a_centred_group_either_when_centring_itself_is_unsampled():
    # deliberate design point (not a gap): cen_unproven requires cen_n > 0
    # - an "unproven" centring with ZERO observations has nothing to
    # discard, unlike a centring that carries noise/signal and is merely
    # undecidable (that case is covered, unchanged, by
    # test_pa2_tool_fixes.py::TestAbsenceGate.test_noise_centring_is_refused_with_the_numbers)
    audit, refusal = _absence_gate(
        _ses(_all_even_data()), sgtbx.space_group_info("C 1 2/c 1").group(),
        False, current_group=sgtbx.space_group("P 1"))
    assert refusal is None
    assert audit["verdict"] == "absence_classes_unobserved"
    assert audit["centring"]["absent"]["n"] == 0
    assert audit["centring"]["verdict"] == "absence_classes_unobserved"
