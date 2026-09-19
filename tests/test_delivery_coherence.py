"""Process-audit T11: scientific delivery coherence and file inventory.

The r15 near-miss (final.cif paired with the wrong ACTA job) and the
2-8 minute hand-run Select-String verification loops at the end of every
campaign become one structured check inside write_outputs."""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

RES_3ATOMS = """TITL t
CELL 0.71073 10 10 10 90 90 90
ZERR 4 0 0 0 0 0 0
SFAC C H O
UNIT 4 8 4
FVAR 1.0
C1 1 0.1 0.1 0.1 11.0 0.03
O1 3 0.2 0.2 0.2 11.0 0.03
H1 2 0.3 0.3 0.3 11.0 0.04
HKLF 4
END
"""


def _cif(n_atoms=3, z=4, r1="0.0400"):
    rows = "\n".join(f"C{i} C 0.1 0.1 0.{i}" for i in range(n_atoms))
    return (f"data_final\n_cell_length_a 10.0\n_cell_formula_units_Z {z}\n"
            f"_refine_ls_R_factor_gt {r1}\n"
            "loop_\n _atom_site_label\n _atom_site_type_symbol\n"
            " _atom_site_fract_x\n _atom_site_fract_y\n _atom_site_fract_z\n"
            f"{rows}\n")


class TestDeliveryCoherence:
    @staticmethod
    def _check(tmp_path, cif_text, res_text=RES_3ATOMS, r1_node=0.04,
               publication=True):
        from crystalpilot.refine.tools_deliver import WriteOutputs
        (tmp_path / "final.res").write_text(res_text, encoding="utf-8")
        if cif_text is not None:
            (tmp_path / "final.cif").write_text(cif_text, encoding="utf-8")
        report = {"metrics": {"r1_strong": r1_node}}
        return WriteOutputs._delivery_coherence(tmp_path, report,
                                                publication)

    def test_agreement_is_clean(self, tmp_path):
        assert self._check(tmp_path, _cif()) == []

    def test_atom_count_mismatch(self, tmp_path):
        issues = self._check(tmp_path, _cif(n_atoms=2))
        assert any("atom count" in i for i in issues)

    def test_z_mismatch(self, tmp_path):
        issues = self._check(tmp_path, _cif(z=8))
        assert any(i.startswith("Z:") for i in issues)

    def test_r1_divergence_only_for_publication(self, tmp_path):
        issues = self._check(tmp_path, _cif(r1="0.0900"))
        assert any(i.startswith("R1:") for i in issues)
        assert self._check(tmp_path, _cif(r1="0.0900"),
                           publication=False) == []

    def test_missing_cif_reported(self, tmp_path):
        assert self._check(tmp_path, None) == ["final.cif was not written"]
