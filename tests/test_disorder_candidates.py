"""disorder_candidates: the residual-plus-ADP signature of a second
position, listed before anyone draws a split (reg4/5/6-dbu, 2026-09-04)."""
from __future__ import annotations

import pytest
from cctbx import adptbx, crystal, xray

from crystalpilot.refine.disorder_candidates import disorder_candidates

CELL = (12.0, 12.0, 12.0, 90.0, 90.0, 90.0)


def _model():
    cs = crystal.symmetry(unit_cell=CELL, space_group_symbol="P 1")
    xs = xray.structure(crystal_symmetry=cs)
    uc = cs.unit_cell()
    atoms = [("C1", "C", (0.5, 0.5, 0.5), 0.03),
             ("C2", "C", (0.5 + 1.5 / 12, 0.5, 0.5), 0.03),
             ("C3", "C", (0.5 - 1.5 / 12, 0.5, 0.5), 0.03),
             ("N1", "N", (0.2, 0.2, 0.2), 0.03),
             ("O1", "O", (0.8, 0.8, 0.8), 0.03),
             ("H1A", "H", (0.5, 0.5 + 0.97 / 12, 0.5), 0.04),
             ("H1B", "H", (0.5, 0.5 - 0.97 / 12, 0.5), 0.04)]
    for lab, el, site, u in atoms:
        xs.add_scatterer(xray.scatterer(label=lab, scattering_type=el,
                                        site=site, u=u))
    c1 = xs.scatterers()[0]
    # fat and elongated along z: U_eq 0.06 (2x the others), max/min 4
    c1.u_star = adptbx.u_cart_as_u_star(uc, (0.03, 0.03, 0.12, 0, 0, 0))
    c1.flags.set_use_u_aniso(True)
    return xs


def test_the_peak_next_to_the_fat_atom_is_a_candidate():
    xs = _model()
    peaks = [
        {"site": (0.5, 0.5, 0.5 + 1.0 / 12), "height": 0.9},   # 1.0 A from C1
        {"site": (0.5, 0.5 + 0.97 / 12, 0.5 + 0.2 / 12), "height": 0.4},  # on H1A
        {"site": (0.1, 0.9, 0.5), "height": 0.5},               # far from all
    ]
    r = disorder_candidates(xs, peaks)
    assert r["n_peaks"] == 3
    assert [c["atom"] for c in r["candidates"]] == ["C1"]
    c = r["candidates"][0]
    assert c["peak_height"] == 0.9 and c["peak_d"] == pytest.approx(1.0, abs=0.01)
    assert c["u_eq_over_median"] == pytest.approx(2.0, abs=0.05)
    assert c["adp_max_over_min"] == pytest.approx(4.0, abs=0.1)
    assert c["nearest_h"]["d"] == pytest.approx(1.39, abs=0.02)
    assert "not an H position" in c["reading"]
    assert "model_disorder(atoms=['C1'])" in c["next"]
    assert "Refinement decides" in c["reading"]


def test_atoms_already_split_and_empty_maps_are_handled():
    xs = _model()
    peaks = [{"site": (0.5, 0.5, 0.5 + 1.0 / 12), "height": 0.9}]
    assert disorder_candidates(xs, peaks, exclude={"C1"})["candidates"] == []
    r = disorder_candidates(xs, None)
    assert r["candidates"] == [] and "no difference map" in r["note"]


def test_validate_structure_and_situation_report_carry_the_candidates():
    from test_system_type_validation import _run, _session, _structure
    xs = _structure([("C1", "C", (6.0, 6.0, 6.0)),
                     ("C2", "C", (7.5, 6.0, 6.0)),
                     ("C3", "C", (4.5, 6.0, 6.0)),
                     ("C4", "C", (8.9, 6.0, 6.0)),
                     ("C5", "C", (3.1, 6.0, 6.0))], cell=(20, 20, 20, 90, 90, 90))
    ses = _session(xs)
    ses.flags["diff_map_peaks"] = [{"site": (0.3, 0.3, 0.35), "height": 0.8}]
    from crystalpilot.tools.base import ToolContext
    from crystalpilot.tools.validation_tools import ValidateStructure
    from test_system_type_validation import _Store
    r = ValidateStructure().run(ToolContext(store=_Store(), session=ses))
    assert r.ok, r.error
    dcs = r.summary["disorder_candidates"]
    assert [c["atom"] for c in dcs["candidates"]] == ["C1"]
    assert any(a["code"] == "disorder_candidate" for a in r.summary["alerts"])
