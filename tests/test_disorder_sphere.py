"""T1.6b: a split must be consistent with its coordination sphere.

reg2-mof cage (2026-09-04): Zr3/Zr7 were two positions 0.78 A apart with
six single-site oxygen donors; the refined occupancy 0.59(2):0.41(2) came
back `supported` and the agent kept the split "because of chemistry". A
donor bonded to both positions sees two Zr-O lengths differing by up to
0.78 A - far beyond what its own displacement absorbs - so either the
donors are disordered too, or the second Zr is not an atom. The reading
below is referenced to each neighbour's OWN U_eq (any element, any cell)
and demotes `supported` to `inconclusive` when the sphere cannot hold
both components."""
from __future__ import annotations

import pytest
from cctbx import crystal, sgtbx, xray

from crystalpilot.refine import disorder_accept as D

CELL = (10.0, 10.0, 10.0, 90.0, 90.0, 90.0)


def _xs(atoms):
    xs = xray.structure(crystal_symmetry=crystal.symmetry(
        unit_cell=CELL, space_group_info=sgtbx.space_group_info("P 1")))
    for lab, el, site, occ, u in atoms:
        xs.add_scatterer(xray.scatterer(label=lab, scattering_type=el,
                                        site=site, u=u, occupancy=occ))
    return xs


def _group(a, b):
    return {"fvar_index": 2,
            "members": [{"label": a, "sign": 1, "part": 1},
                        {"label": b, "sign": -1, "part": 2}]}


def _metal_split(dx=0.078):
    """A metal at the centre, its alternative dx (fractional, 0.78 A) along
    x, six single-site O donors 2.2 A away along +-x, +-y, +-z."""
    atoms = [("ZR1", "Zr", (0.5, 0.5, 0.5), 0.6, 0.03),
             ("ZR1B", "Zr", (0.5 + dx, 0.5, 0.5), 0.4, 0.03)]
    for i, (sx, sy, sz) in enumerate([(0.22, 0, 0), (-0.22, 0, 0),
                                       (0, 0.22, 0), (0, -0.22, 0),
                                       (0, 0, 0.22), (0, 0, -0.22)]):
        atoms.append((f"O{i + 1}", "O", (0.5 + sx, 0.5 + sy, 0.5 + sz),
                      1.0, 0.03))
    return _xs(atoms)


def test_donors_along_the_split_cannot_hold_both_positions():
    xs = _metal_split()
    r = D.sphere_reading(xs, _group("ZR1", "ZR1B"))
    assert r["consistent"] is False
    assert r["n_single_site_neighbours"] == 6
    # the two donors on the x axis see 2.2 vs 1.42 / 2.98 A; the four
    # perpendicular ones see 2.2 vs 2.33 A, which their U_eq 0.03
    # (rms 0.17 A, bar 0.35 A) absorbs
    assert r["n_inconsistent"] == 2
    bad = [n for n in r["pairs"][0]["single_site_neighbours"]
           if not n["absorbed"]]
    assert sorted(n["label"] for n in bad) == ["O1", "O2"]
    assert all(n["delta"] == pytest.approx(0.78, abs=0.01) for n in bad)
    assert "No residual peak of its own" in r["reading"]   # no map given


def test_supported_occupancy_is_demoted_when_the_sphere_disagrees():
    xs = _metal_split()
    out = D.group_acceptance(xs, _group("ZR1", "ZR1B"),
                             free_var={"value": 0.59, "su": 0.02},
                             d_min_data=0.69, with_restraints=False)
    assert out["free_variable"]["verdict"] == "supported"
    assert out["verdict"] == "inconclusive"
    assert out["verdict_demoted_from"] == "supported"
    assert out["sphere"]["consistent"] is False
    assert "coordination sphere" in out["disposition"]
    assert "Do not deliver" in out["disposition"]


def test_a_puckered_ring_atom_keeps_its_supported_verdict():
    """The alternative position sits PERPENDICULAR to the bonds: both ring
    neighbours are almost equidistant from the two components."""
    xs = _xs([("C1", "C", (0.5, 0.5, 0.5), 0.6, 0.05),
              ("C1B", "C", (0.5, 0.5, 0.56), 0.4, 0.05),
              ("C2", "C", (0.64, 0.5, 0.5), 1.0, 0.05),
              ("C3", "C", (0.36, 0.5, 0.5), 1.0, 0.05)])
    out = D.group_acceptance(xs, _group("C1", "C1B"),
                             free_var={"value": 0.6, "su": 0.02},
                             d_min_data=0.8, with_restraints=False)
    sphere = out["sphere"]
    assert sphere["consistent"] is True
    assert sphere["n_single_site_neighbours"] == 2
    assert all(n["delta"] < 0.15
               for n in sphere["pairs"][0]["single_site_neighbours"])
    assert out["verdict"] == "supported"
    assert "verdict_demoted_from" not in out


def test_neighbours_split_in_another_group_are_not_single_site():
    xs = _metal_split()
    others = {"O1", "O2", "O3", "O4", "O5", "O6"}
    r = D.sphere_reading(xs, _group("ZR1", "ZR1B"), split_labels=others)
    assert r["consistent"] is None
    assert r["n_single_site_neighbours"] == 0
    assert sorted(r["pairs"][0]["split_neighbours"]) == sorted(others)
    out = D.group_acceptance(xs, _group("ZR1", "ZR1B"),
                             free_var={"value": 0.59, "su": 0.02},
                             d_min_data=0.69, with_restraints=False,
                             split_labels=others)
    assert out["verdict"] == "supported"


def test_pending_split_still_carries_the_sphere_reading():
    xs = _metal_split()
    out = D.group_acceptance(xs, _group("ZR1", "ZR1B"), free_var=None,
                             d_min_data=0.69, with_restraints=False)
    assert out["verdict"] == "pending"
    assert out["sphere"]["consistent"] is False
    assert "sphere" in out["limits"]


def test_revoke_is_not_touched_by_the_sphere():
    xs = _metal_split()
    out = D.group_acceptance(xs, _group("ZR1", "ZR1B"),
                             free_var={"value": 0.99, "su": 0.01},
                             d_min_data=0.69, with_restraints=False)
    assert out["verdict"] == "revoke"
    assert "verdict_demoted_from" not in out


def test_pending_readings_do_not_read_like_a_verdict():
    """reg4-dbu: 'below d_min' was read as a prohibition and the branch was
    abandoned unrefined."""
    xs = _metal_split()
    out = D.group_acceptance(xs, _group("ZR1", "ZR1B"), free_var=None,
                             d_min_data=1.0, with_restraints=False)
    assert out["verdict"] == "pending"
    assert "does NOT forbid the split" in out["separation"]["reading"]
    assert "THIS branch now" in out["disposition"]
    assert "not a reason to leave the split unrefined" in out["disposition"]


def test_hydrogen_atoms_are_not_sphere_witnesses():
    """reg5-dbu: the split atom's own riding H were counted as neighbours
    that 'cannot be bonded to both components' while every heavy
    neighbour fitted; the agent undid the split on that reading."""
    xs = _xs([("C1", "C", (0.5, 0.5, 0.5), 0.7, 0.05),
              ("C1B", "C", (0.5, 0.5, 0.60), 0.3, 0.05),      # 1.0 A away
              ("C2", "C", (0.64, 0.5, 0.5), 1.0, 0.05),
              ("C3", "C", (0.36, 0.5, 0.5), 1.0, 0.05),
              ("H1A", "H", (0.5, 0.58, 0.47), 1.0, 0.06),     # riding on C1
              ("H1B", "H", (0.5, 0.42, 0.47), 1.0, 0.06)])
    r = D.sphere_reading(xs, _group("C1", "C1B"))
    labels = [n["label"] for n in r["pairs"][0]["single_site_neighbours"]]
    assert "H1A" not in labels and "H1B" not in labels
    assert r["n_single_site_neighbours"] == 2
    assert "non-H" in r["reading"]


def test_an_inconsistent_neighbour_with_its_own_peak_is_named_for_the_split():
    xs = _metal_split()
    peaks = [{"site": (0.5 + 0.22 + 0.078, 0.5, 0.5), "height": 0.8,
              "nearest_atom": "O1", "nearest_d": 0.78}]
    r = D.sphere_reading(xs, _group("ZR1", "ZR1B"), peaks=peaks)
    assert r["consistent"] is False
    assert r["neighbours_with_own_peak"] and r["neighbours_with_own_peak"][0].startswith("O1 ")
    assert "model_disorder atoms=[ZR1, O1]" in r["reading"]
    r2 = D.sphere_reading(xs, _group("ZR1", "ZR1B"), peaks=[])
    assert "No residual peak of its own" in r2["reading"]

