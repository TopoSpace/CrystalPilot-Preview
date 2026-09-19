"""DDLm (dotted-tag) CIF dialect: normalization + reference-loader retry."""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from crystalpilot.io.cif_compat import looks_like_ddlm, normalize_ddlm_tags

DDL1 = """\
data_test
_cell_length_a     10.000
_cell_length_b     11.000
_cell_length_c     12.000
_cell_angle_alpha  90.000
_cell_angle_beta   95.000
_cell_angle_gamma  90.000
_space_group_name_H-M_alt  'P 21/c'
_cell_formula_units_Z  4
loop_
 _atom_site_label
 _atom_site_type_symbol
 _atom_site_fract_x
 _atom_site_fract_y
 _atom_site_fract_z
 _atom_site_occupancy
 Cu1 Cu 0.2500 0.2500 0.2500 1.0
 O1 O 0.4000 0.3000 0.2000 1.0
 C1 C 0.5000 0.4000 0.1500 1.0
"""


def _to_ddlm(text: str) -> str:
    """Mechanical DDL1 -> DDLm conversion for the tags in the fixture."""
    reps = {
        "_cell_length_a": "_cell.length_a",
        "_cell_length_b": "_cell.length_b",
        "_cell_length_c": "_cell.length_c",
        "_cell_angle_alpha": "_cell.angle_alpha",
        "_cell_angle_beta": "_cell.angle_beta",
        "_cell_angle_gamma": "_cell.angle_gamma",
        "_space_group_name_H-M_alt": "_space_group.name_H-M_alt",
        "_cell_formula_units_Z": "_cell.formula_units_Z",
        "_atom_site_label": "_atom_site.label",
        "_atom_site_type_symbol": "_atom_site.type_symbol",
        "_atom_site_fract_x": "_atom_site.fract_x",
        "_atom_site_fract_y": "_atom_site.fract_y",
        "_atom_site_fract_z": "_atom_site.fract_z",
        "_atom_site_occupancy": "_atom_site.occupancy",
    }
    for old, new in reps.items():
        text = text.replace(old, new)
    return text


def test_detection_and_passthrough():
    assert not looks_like_ddlm(DDL1)
    assert normalize_ddlm_tags(DDL1) == DDL1        # byte-identical
    ddlm = _to_ddlm(DDL1)
    assert looks_like_ddlm(ddlm)


def test_normalization_restores_ddl1_names():
    norm = normalize_ddlm_tags(_to_ddlm(DDL1))
    assert "_cell_length_a" in norm and "_cell.length_a" not in norm
    assert "_space_group_name_H-M_alt" in norm     # exception map spelling
    assert "_atom_site_fract_x" in norm
    # values untouched (the quoted space-group symbol keeps its content)
    assert "'P 21/c'" in norm


def test_dots_inside_values_survive():
    tricky = DDL1 + "_exptl.special_details 'grown from 1.5 M soln.'\n"
    norm = normalize_ddlm_tags(_to_ddlm(tricky))
    assert "_exptl_special_details" in norm
    assert "'grown from 1.5 M soln.'" in norm      # value dot untouched


def test_load_reference_reads_ddlm(tmp_path):
    from crystalpilot.benchmark.evaluate import load_reference
    p1 = tmp_path / "a.cif"
    p1.write_text(DDL1, encoding="utf-8")
    p2 = tmp_path / "b.cif"
    p2.write_text(_to_ddlm(DDL1), encoding="utf-8")
    xs1 = load_reference(None, str(p1))
    xs2 = load_reference(None, str(p2))
    assert xs1 is not None and xs2 is not None
    assert xs1.scatterers().size() == xs2.scatterers().size() == 3
    assert (xs1.unit_cell().parameters()[0]
            == xs2.unit_cell().parameters()[0] == 10.0)
