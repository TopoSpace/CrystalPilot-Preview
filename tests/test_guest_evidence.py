"""audit_guest_evidence: the three guest-evidence tests on model copies.

Synthetic ground truth: intensities are CALCULATED from a structure that
contains a genuine O guest. Auditing that O in the matching model must
come out supportive; auditing a phantom C (present in the model, absent
from the data-generating structure) must come out against. Read-only:
the session model must be byte-identical after every audit.
"""
from types import SimpleNamespace

import pytest
from cctbx import crystal, xray
from cctbx.array_family import flex

from crystalpilot.core.dataset import ReflectionDataset
from crystalpilot.pipeline.session import SolveSession
from crystalpilot.refine.tools_chemaudit import AuditGuestEvidence
from crystalpilot.tools.base import ToolContext


class _Store:
    def record(self, *a, **k):
        return None

    def log(self, *a, **k):
        return None


def _ctx(ses):
    return ToolContext(store=_Store(), session=ses)


def _structure(with_guest: bool, with_phantom: bool = False,
               guest_occ: float = 1.0, guest_on_centre: bool = False):
    cs = crystal.symmetry(unit_cell=(7.5, 8.5, 9.5, 90.0, 95.0, 90.0),
                          space_group_symbol="P -1")
    xs = xray.structure(crystal_symmetry=cs)
    uc = cs.unit_cell()
    atoms = [("S1", "S", (1.30, 1.60, 2.10)),
             ("S2", "S", (4.20, 4.50, 5.00)),
             ("O1", "O", (2.80, 2.00, 2.70)),
             ("C1", "C", (4.00, 3.10, 3.50)),
             ("C2", "C", (2.55, 4.70, 1.20))]
    if with_guest:
        # isolated guest far from the framework atoms (or on the inversion
        # centre at the origin, 2.9 A from S1, for the multiplicity case)
        atoms.append(("O9", "O", (0.0, 0.0, 0.0) if guest_on_centre
                      else (0.60, 6.80, 7.60)))
    if with_phantom:
        # a modelled atom sitting in genuinely empty space
        atoms.append(("C9", "C", (6.30, 1.00, 7.90)))
    for label, el, cart in atoms:
        xs.add_scatterer(xray.scatterer(
            label=label, site=uc.fractionalize(cart),
            scattering_type=el, u=0.025,
            occupancy=guest_occ if label == "O9" else 1.0))
    xs.scattering_type_registry(table="it1992")
    return xs


def _session(guest_occ: float = 1.0, guest_on_centre: bool = False):
    truth = _structure(with_guest=True, guest_occ=guest_occ,
                       guest_on_centre=guest_on_centre)  # data carry the O guest
    fc = truth.structure_factors(d_min=0.9).f_calc()
    fo_sq = fc.intensities().customized_copy(
        sigmas=flex.double(fc.size(), 1.0)).set_observation_type_xray_intensity()
    ses = SolveSession(dataset=ReflectionDataset(
        intensities=None, wavelength=0.71073))
    ses.symmetry = truth.crystal_symmetry()
    ses.fo_sq = fo_sq
    return ses


def _snapshot(xs):
    return [(sc.label, tuple(sc.site), float(sc.occupancy))
            for sc in xs.scatterers()]


def test_refuses_unknown_atoms():
    ses = _session()
    ses.model = _structure(with_guest=True)
    r = AuditGuestEvidence(None).run(_ctx(ses), atoms=["ZZ9"])
    assert not r.ok and "ZZ9" in (r.error or "")


def test_true_guest_supported_and_model_untouched():
    ses = _session()
    ses.model = _structure(with_guest=True)
    before = _snapshot(ses.model)
    r = AuditGuestEvidence(None).run(
        _ctx(ses), atoms=["O9"], expected_formula="O", n_cycles=6)
    assert r.ok, r.error
    s = r.summary
    t1 = s["test1_omit_region"]
    assert "error" not in t1, t1
    # a real 8-electron O leaves most of itself in the omit map
    assert t1["region_electrons_net"] > 4.0
    t2 = s["test2_occupancy"]
    assert "error" not in t2, t2
    assert t2["refined_mean"] > 0.7
    # no restraints in the session -> test 3 trivially applicable=False
    assert s["test3_restraints"]["applicable"] is False
    assert any("test1" in v for v in s["verdict"])
    assert _snapshot(ses.model) == before      # read-only contract


def test_phantom_guest_rejected():
    ses = _session()
    ses.model = _structure(with_guest=True, with_phantom=True)
    r = AuditGuestEvidence(None).run(
        _ctx(ses), atoms=["C9"], expected_formula="C", n_cycles=8)
    assert r.ok, r.error
    s = r.summary
    t1 = s["test1_omit_region"]
    assert "error" not in t1, t1
    assert t1["region_electrons_net"] < 2.5     # empty space
    t2 = s["test2_occupancy"]
    assert "error" not in t2, t2
    # freed occupancy of a phantom collapses well below its start of 1.0
    assert t2["refined_mean"] < 0.5


def test_restraint_withdrawal_runs_on_restrained_guest():
    ses = _session()
    ses.model = _structure(with_guest=True)
    # nonsense-but-valid restraint touching the guest: O9-C1 distance
    ses.flags["restraints"] = [
        {"kind": "DFIX", "atoms": [["O9", "C1"]], "target": 7.0,
         "sigma": 0.02}]
    r = AuditGuestEvidence(None).run(_ctx(ses), atoms=["O9"], n_cycles=4)
    assert r.ok, r.error
    t3 = r.summary["test3_restraints"]
    assert "error" not in t3, t3
    assert t3["n_restraints_withdrawn"] == 1
    assert "max_site_shift_A" in t3


def test_mask_active_skips_trial_refinements():
    ses = _session()
    ses.model = _structure(with_guest=True)
    ses.flags["f_mask"] = ses.fo_sq          # any placeholder object
    r = AuditGuestEvidence(None).run(_ctx(ses), atoms=["O9"])
    assert r.ok, r.error
    s = r.summary
    assert "mask_warning" in s
    assert s["test2_occupancy"] == {"skipped": "mask active"}
    assert s["test3_restraints"] == {"skipped": "mask active"}


# ------------------------------------------------- round-3 WP4 accounting
def test_denominators_are_labelled_and_the_verdict_reads_the_working_hypothesis():
    """Data carry O9 at occupancy 0.2; the model says so too. Against the
    full-occupancy formula the region holds ~20% (the forensic 'against');
    against the hypothesis the model states it holds ~100%."""
    ses = _session(guest_occ=0.2)
    ses.model = _structure(with_guest=True, guest_occ=0.2)
    r = AuditGuestEvidence(None).run(
        _ctx(ses), atoms=["O9"], expected_formula="O", n_cycles=6)
    assert r.ok, r.error
    s = r.summary
    acc = s["accounting"]
    assert acc["per_atom"][0]["electrons_at_site"] == pytest.approx(1.6)
    assert acc["per_atom"][0]["electrons_full_occupancy"] == 8
    den = acc["denominators"]
    assert set(den) == {"working_occupancy", "full_occupancy_model",
                        "full_occupancy_formula", "formula_at_working_occupancy"}
    assert den["working_occupancy"]["electrons"] == pytest.approx(1.6)
    assert den["full_occupancy_formula"]["electrons"] == 8.0
    assert den["formula_at_working_occupancy"]["electrons"] == pytest.approx(1.6)
    assert all("meaning" in d for d in den.values())
    t1 = s["test1_omit_region"]
    assert "error" not in t1, t1
    ratios = t1["ratio_by_denominator"]
    assert ratios["full_occupancy_formula"] < 0.35
    assert ratios["formula_at_working_occupancy"] >= 0.6
    assert t1["verdict_denominator"] == "formula_at_working_occupancy"
    assert "full-occupancy" in t1["note"].lower() or "FULL-occupancy" in t1["note"]
    line = next(v for v in s["verdict"] if v.startswith("test1"))
    assert "SUPPORTS" in line and "working hypothesis" in line
    assert "occupancy 0.20" in line
    # the occupancy trial reads per atom, holds at the working value
    t2 = s["test2_occupancy"]
    assert t2["per_atom"][0]["reading"] == "holds"
    assert t2["cycles_done"] > 0 and t2["terminated_by"]
    assert s["scientific_outcome"]["verdict"] == "supports"
    assert s["conditioned_by_prior"]["value"] is False


def test_full_occupancy_model_of_a_partial_guest_reads_against_the_model():
    ses = _session(guest_occ=0.2)
    ses.model = _structure(with_guest=True, guest_occ=1.0)
    r = AuditGuestEvidence(None).run(_ctx(ses), atoms=["O9"], n_cycles=8)
    assert r.ok, r.error
    s = r.summary
    t1 = s["test1_omit_region"]
    assert t1["verdict_denominator"] == "working_occupancy"
    assert t1["ratio_vs_hypothesis"] < 0.3
    assert any(v.startswith("test1 AGAINST") for v in s["verdict"])
    row = s["test2_occupancy"]["per_atom"][0]
    assert row["occ_start"] == 1.0 and row["occ_refined"] < 0.3
    assert row["reading"] == "collapses" and row["at_bound"] is None
    assert any(v.startswith("test2 AGAINST") for v in s["verdict"])
    assert s["scientific_outcome"]["verdict"] == "against"


def test_special_position_guest_counts_its_multiplicity():
    ses = _session(guest_on_centre=True)
    ses.model = _structure(with_guest=True, guest_on_centre=True)
    r = AuditGuestEvidence(None).run(_ctx(ses), atoms=["O9", "C1"], n_cycles=2)
    assert r.ok, r.error
    acc = r.summary["accounting"]
    rows = {a["label"]: a for a in acc["per_atom"]}
    assert rows["O9"]["multiplicity"] == 1 and rows["O9"]["special_position"]
    assert rows["O9"]["electrons_per_cell"] == rows["O9"]["electrons_at_site"] == 8
    assert rows["C1"]["multiplicity"] == 2 and not rows["C1"]["special_position"]
    assert rows["C1"]["electrons_per_cell"] == 12 and rows["C1"]["electrons_at_site"] == 6
    assert acc["totals"]["n_special_position_atoms"] == 1
    assert acc["totals"]["space_group_order"] == 2
    assert acc["totals"]["electrons_per_cell"] == 20.0


def test_zero_cycles_is_inconclusive_never_supports():
    ses = _session()
    ses.model = _structure(with_guest=True)
    ses.flags["restraints"] = [
        {"kind": "DFIX", "atoms": [["O9", "C1"]], "target": 7.0, "sigma": 0.02}]
    r = AuditGuestEvidence(None).run(_ctx(ses), atoms=["O9"], n_cycles=0)
    assert r.ok, r.error
    s = r.summary
    t2, t3 = s["test2_occupancy"], s["test3_restraints"]
    assert t2["cycles_done"] == 0 and t2["terminated_by"] == "no_cycles_requested"
    assert t2["reading"] == "inconclusive"
    assert t3["cycles_done"] == 0 and t3["reading"] == "inconclusive"
    assert t3["n_reflections"] > 0 and t3["d_min"] == pytest.approx(0.9, abs=0.05)
    assert t3["npd_after"] == []
    assert sum(v.startswith("test2 INCONCLUSIVE") for v in s["verdict"]) == 1
    assert sum(v.startswith("test3 INCONCLUSIVE") for v in s["verdict"]) == 1
    assert not any("SUPPORTS" in v for v in s["verdict"] if not v.startswith("test1"))
    assert s["scientific_outcome"]["verdict"] == "inconclusive"
    assert s["conditioned_by_prior"] == {
        "value": True, "restraints": ["DFIX"], "fvar_groups": [],
        "riding_h": False, "note": s["conditioned_by_prior"]["note"]}
    assert "prior knowledge" in s["conditioned_by_prior"]["note"]


def test_mixed_group_is_read_atom_by_atom_not_by_the_mean():
    ses = _session()
    ses.model = _structure(with_guest=True, with_phantom=True)
    r = AuditGuestEvidence(None).run(_ctx(ses), atoms=["O9", "C9"], n_cycles=8)
    assert r.ok, r.error
    t2 = r.summary["test2_occupancy"]
    rows = {x["label"]: x for x in t2["per_atom"]}
    assert rows["O9"]["reading"] == "holds"
    assert rows["C9"]["reading"] in ("collapses", "partial")
    assert t2["reading"] == "inconclusive"
    line = next(v for v in r.summary["verdict"] if v.startswith("test2"))
    assert "INCONCLUSIVE" in line and "O9" in line and "C9" in line
    assert "refined_mean" in t2          # still reported, no longer judging
    assert r.summary["scientific_outcome"]["verdict"] == "inconclusive"


def test_displacement_control_separates_grip_from_inertia():
    """Round-3 R4 (Zr-MOF rerun): a 0.07-occupancy guest read 'stays put
    (max shift 0.00 A)' while SHELXL let it drift 5 A. Test 3 now displaces
    a copy of the guest by 0.3 A: a real guest is pulled back by the map, a
    phantom stays where it was put - and 'stays put' alone is then
    inconclusive, not support."""
    ses = _session()
    ses.model = _structure(with_guest=True)
    ses.flags["restraints"] = [
        {"kind": "DFIX", "atoms": [["O9", "C1"]], "target": 7.0,
         "sigma": 0.02}]
    r = AuditGuestEvidence(None).run(_ctx(ses), atoms=["O9"], n_cycles=8)
    assert r.ok, r.error
    t3 = r.summary["test3_restraints"]
    ctrl = t3["displacement_control"]
    assert "error" not in ctrl, ctrl
    assert ctrl["displacement_A"] == 0.3
    assert ctrl["return_fraction"] >= 0.5, ctrl
    assert ctrl["reading"] == "held"
    assert t3["reading"] == "supports"
    assert any("returns" in v for v in r.summary["verdict"])

    # a phantom in empty space: nothing pulls the displaced copy back
    ses2 = _session()
    ses2.model = _structure(with_guest=True, with_phantom=True)
    ses2.flags["restraints"] = [
        {"kind": "DFIX", "atoms": [["C9", "C1"]], "target": 6.0,
         "sigma": 0.02}]
    r2 = AuditGuestEvidence(None).run(_ctx(ses2), atoms=["C9"], n_cycles=8)
    assert r2.ok, r2.error
    t3b = r2.summary["test3_restraints"]
    ctrl2 = t3b["displacement_control"]
    assert "error" not in ctrl2, ctrl2
    assert ctrl2["return_fraction"] < 0.5, ctrl2
    assert t3b["reading"] in ("inconclusive", "warns"), t3b
    if t3b["reading"] == "inconclusive":
        assert any("inertia, not evidence" in v for v in r2.summary["verdict"])
