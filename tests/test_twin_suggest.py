"""set_twin(law='suggest') must actually list metric-possible twin laws.

reg1-ext2 (2026-09-04, case rz = twin_rz5267_iucr): C2/c with beta =
92.3 deg, refined by the depositors as a two-component pseudo-merohedral
twin (TWIN -1 0 0 0 -1 0 0 0 1, BASF 0.023). The agent asked for
suggestions and was told "no candidates = merohedral twinning impossible
for this metric". Every candidate had in fact raised TypeError (rt_mx *
rt_mx) inside a swallowed try/except, and the op identity used
str(rot_mx) - an object address - so no coset bookkeeping ever worked.
The suggestion had never returned a law for any crystal.

These tests are synthetic and cover several crystal systems; the rz cell
is one of them, not the criterion."""
from __future__ import annotations

import pytest
from cctbx import crystal, xray

from crystalpilot.refine.tools_disorder import _suggest_laws


def _xs(cell, sg):
    return xray.structure(crystal_symmetry=crystal.symmetry(
        unit_cell=cell, space_group_symbol=sg))


def _mats(res):
    return [tuple(int(round(x)) for x in c["matrix"]) for c in res["candidates"]
            if c.get("integral")]


def test_pseudo_orthorhombic_c_centred_monoclinic_offers_the_two_fold():
    # rz: C2/c, beta 92.3 deg -> lattice is orthorhombic within 3 deg
    res = _suggest_laws(_xs((15.954, 5.4599, 28.397, 90, 92.299, 90), "C 1 2/c 1"))
    assert res["candidates"], res["note"]
    assert res["max_delta_deg"] == 3.0
    assert 0 < res["lattice_delta_deg"] < 3.0
    mats = _mats(res)
    # the coset of the 2-fold about c (equivalently about a, modulo 2/m)
    assert (-1, 0, 0, 0, -1, 0, 0, 0, 1) in mats or (1, 0, 0, 0, -1, 0, 0, 0, -1) in mats
    assert all(c["integral"] for c in res["candidates"])
    assert "impossible" not in res["note"]


def test_pseudo_monoclinic_triclinic_offers_a_law_and_true_triclinic_does_not():
    near = _suggest_laws(_xs((5.0, 6.0, 7.0, 90.0, 90.6, 90.0), "P -1"))
    assert near["candidates"] and all(c["order"] == 2 for c in near["candidates"])
    far = _suggest_laws(_xs((5.0, 6.0, 7.0, 80.0, 85.0, 95.0), "P -1"))
    assert far["candidates"] == []
    assert far["lattice_delta_deg"] == 0.0
    assert "not excluded" in far["note"].lower()  # non-merohedral twinning


def test_holohedral_cell_has_no_extra_law():
    # orthorhombic Laue mmm in a cell that is not tetragonal within 3 deg
    res = _suggest_laws(_xs((5.0, 9.0, 13.0, 90, 90, 90), "P n m a"))
    assert res["candidates"] == []


def test_tetragonal_4_over_m_offers_the_4mmm_two_folds():
    res = _suggest_laws(_xs((8.0, 8.0, 12.0, 90, 90, 90), "P 4/n"))
    mats = _mats(res)
    assert mats, res
    # a 2-fold about a (or the diagonal) completes 4/m -> 4/mmm
    assert any(m in mats for m in ((1, 0, 0, 0, -1, 0, 0, 0, -1),
                                   (0, 1, 0, 1, 0, 0, 0, 0, -1),
                                   (-1, 0, 0, 0, 1, 0, 0, 0, -1),
                                   (0, -1, 0, -1, 0, 0, 0, 0, -1)))
    assert all(c["order"] in (2, 4) for c in res["candidates"])


def test_candidates_are_coset_representatives_not_the_whole_group():
    res = _suggest_laws(_xs((8.0, 8.0, 12.0, 90, 90, 90), "P 4/n"))
    # 4/mmm has 16 ops, 4/m has 8: exactly one coset beyond the Laue group
    assert len(res["candidates"]) == 1


def test_near_miss_is_disclosed_beyond_the_default_tolerance():
    # beta 94 deg: outside 3 deg, inside the wider scan
    res = _suggest_laws(_xs((15.954, 5.4599, 28.397, 90, 94.0, 90), "C 1 2/c 1"))
    assert res["candidates"] == []
    assert res["near_miss"]["max_delta_deg"] > 3.0
    assert res["near_miss"]["candidates"]
    assert 3.0 < res["near_miss"]["lattice_delta_deg"] <= res["near_miss"]["max_delta_deg"]


def test_acentric_note_points_at_the_inversion_twin():
    res = _suggest_laws(_xs((5.0, 9.0, 13.0, 90, 90, 90), "P 21 21 21"))
    assert "inversion" in res["note"]
