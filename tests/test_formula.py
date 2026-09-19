"""Formula / Z bookkeeping audit (chem.formula.formula_audit)."""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from crystalpilot.chem.formula import formula_audit


def _toy(occ_o: float = 1.0):
    from cctbx import crystal, xray
    cs = crystal.symmetry(unit_cell=(9.1, 10.3, 11.7, 92, 101, 96),
                          space_group_symbol="P -1")
    xs = xray.structure(crystal_symmetry=cs)
    for lbl, el, occ in (("CU1", "Cu", 1.0), ("O1", "O", occ_o),
                         ("N1", "N", 1.0), ("C1", "C", 1.0)):
        xs.add_scatterer(xray.scatterer(
            label=lbl, site=(0.1, 0.2, 0.3), u=0.03, occupancy=occ,
            scattering_type=el))
    return xs


def test_integral_formula_quiet():
    a = formula_audit(_toy())               # Z defaults to order_z = 2
    assert a["z"] == 2 and "assumed" in a["z_source"]
    assert a["formula_per_z"] == "C1 Cu1 N1 O1"
    assert "fractional_counts" not in a and "note" not in a
    assert a["density_model_gcm3"] > 0


def test_wrong_z_suggests_clean_candidate():
    a = formula_audit(_toy(), z=4)          # true content divides at Z=2
    assert a["fractional_counts"]["Cu"] == 0.5
    assert 2 in a["z_candidates_clean"]
    assert "referees" in a["note"]


def test_partial_occupancy_has_no_clean_z():
    a = formula_audit(_toy(occ_o=0.25), z=2)
    assert a["fractional_counts"] == {"O": 0.25}
    assert "z_candidates_clean" not in a
    assert "partial-occupancy" in a["note"]


def test_charged_scattering_types_normalize():
    from cctbx import crystal, xray
    cs = crystal.symmetry(unit_cell=(10, 10, 10, 90, 90, 90),
                          space_group_symbol="P 1")
    xs = xray.structure(crystal_symmetry=cs)
    xs.add_scatterer(xray.scatterer(label="CU1", site=(0, 0, 0), u=0.02,
                                    scattering_type="Cu2+"))
    xs.add_scatterer(xray.scatterer(label="O1", site=(0.5, 0, 0), u=0.02,
                                    scattering_type="O2-"))
    a = formula_audit(xs)
    assert a["formula_per_z"] == "Cu1 O1"
