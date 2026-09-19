"""emma precision on a salt / co-crystal: the model that keeps both ions
must not be punished for the reference fairness filter (reg7-dbu)."""
from __future__ import annotations

from cctbx import crystal, xray

from crystalpilot.benchmark.evaluate import evaluate_against_reference

CELL = (20.0, 20.0, 20.0, 90.0, 90.0, 90.0)


def _xs(atoms):
    xs = xray.structure(crystal_symmetry=crystal.symmetry(
        unit_cell=CELL, space_group_symbol="P 1"))
    uc = xs.unit_cell()
    for lab, el, cart, *rest in atoms:
        occ = rest[0] if rest else 1.0
        xs.add_scatterer(xray.scatterer(label=lab, scattering_type=el,
                                        site=uc.fractionalize(cart), u=0.03,
                                        occupancy=occ))
    return xs


#: a 7-atom bonded chain (the "cation") and a 5-atom chain 9 A away (the
#: "anion"): the fairness filter keeps only the larger fragment
CATION = [(f"C{i + 1}", "C", (2.0 + 1.5 * i, 2.0, 2.0)) for i in range(7)]
ANION = [(f"O{i + 1}", "O", (2.0 + 1.4 * i, 11.0, 11.0)) for i in range(5)]


def test_a_modelled_counter_ion_is_not_spurious():
    ref = _xs(CATION + ANION)
    model = _xs(CATION + ANION + [("C99", "C", (15.0, 15.0, 15.0))])
    r = evaluate_against_reference(model, ref)
    assert r["n_ref_solvent_excluded"] == 5
    assert r["all_atoms"]["n_ref"] == 7 and r["all_atoms"]["n_matched"] == 7
    assert r["n_model_matched_apart"] == 5
    # 7 matched of (13 - 5) = 0.875, not 7/13 = 0.54
    assert r["all_precision"] == 0.875
    assert r["solved"] is True


def test_truly_spurious_atoms_still_lower_precision():
    ref = _xs(CATION + ANION)
    junk = [(f"X{i}", "C", (5.0 + 1.5 * i, 15.0, 5.0)) for i in range(6)]
    model = _xs(CATION + ANION + junk)
    r = evaluate_against_reference(model, ref)
    assert r["n_model_matched_apart"] == 5
    # 7 / (18 - 5) = 0.538 < 0.60: six invented atoms are still spurious
    assert r["all_precision"] < 0.60
    assert r["solved"] is False


def test_single_fragment_reference_is_unchanged():
    ref = _xs(CATION)
    model = _xs(CATION + [("C99", "C", (15.0, 15.0, 15.0))])
    r = evaluate_against_reference(model, ref)
    assert r["n_ref_solvent_excluded"] == 0
    assert r["n_model_matched_apart"] == 0
    assert r["all_precision"] == 0.875 and r["solved"] is True
