"""Symmetry names must be true for the operators beside them - in EVERY
setting, not just the reference one.

reg1-ext2 hsl (org_hsl_cod2241460) was solved by SHELXT on a shifted
origin - `P 21 21 21 (a+1/4,b,c-1/4)` - and delivered with the
reference-setting symbol `P 21 21 21` next to the SHIFTED operator loop.
cctbx refused the file (CifBuilderError), the grader fell through to its
gemmi fallback (which reads the NAME), and a 13/13 rms-0.001 structure was
graded "framework not reproduced".

Coverage is synthetic and deliberately spread over the ways a setting can
be non-standard: a pure origin shift, an axis choice that reindexes hkl
(P2(1)/n vs P2(1)/c), a centred lattice, a triclinic cell that is not
reduced, a rhombohedral setting, and both origin choices of a group that
has two (Fd-3m, I4(1)/a).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from crystalpilot.io import cif_symmetry as CS  # noqa: E402


def _sg(symbol, cb=None):
    from cctbx import sgtbx
    info = sgtbx.space_group_info(symbol)
    if cb:
        info = info.change_basis(sgtbx.change_of_basis_op(cb))
    return info.group()


def _structure(symbol, cell, cb=None):
    from cctbx import crystal, xray
    from cctbx import sgtbx
    info = sgtbx.space_group_info(symbol)
    if cb:
        info = info.change_basis(sgtbx.change_of_basis_op(cb))
    sym = crystal.symmetry(unit_cell=cell, space_group_info=info)
    xs = xray.structure(crystal_symmetry=sym)
    for lab, el, site in (("C1", "C", (0.123, 0.234, 0.345)),
                          ("O1", "O", (0.312, 0.456, 0.178)),
                          ("N1", "N", (0.201, 0.088, 0.412))):
        xs.add_scatterer(xray.scatterer(label=lab, scattering_type=el,
                                        site=site, u=0.02))
    return xs


#: (id, H-M symbol, cell, change of basis applied to the setting)
SETTINGS = [
    ("p212121_origin_shift", "P 21 21 21", (5.0, 9.9, 17.8, 90, 90, 90),
     "x+1/4,y,z-1/4"),
    ("p21n_axis_choice", "P 21/n", (10.0, 12.0, 14.0, 90, 100, 90), None),
    ("p21c_reference", "P 21/c", (10.0, 12.0, 14.0, 90, 100, 90), None),
    ("c2c_centred", "C 2/c", (20.0, 7.0, 15.0, 90, 105, 90), None),
    ("p-1_non_reduced", "P -1", (7.0, 8.0, 25.0, 88, 95, 91), None),
    ("fd3m_origin1", "F d -3 m :1", (25.0, 25.0, 25.0, 90, 90, 90), None),
    ("fd3m_origin2", "F d -3 m :2", (25.0, 25.0, 25.0, 90, 90, 90), None),
    ("r-3_rhombohedral", "R -3 :R", (10.0, 10.0, 10.0, 95, 95, 95), None),
    ("i41a_origin1", "I 41/a :1", (12.0, 12.0, 20.0, 90, 90, 90), None),
    ("p212121_reference", "P 21 21 21", (5.0, 9.9, 17.8, 90, 90, 90), None),
]


@pytest.mark.parametrize("name,symbol,cell,cb",
                         SETTINGS, ids=[s[0] for s in SETTINGS])
def test_written_cif_round_trips_in_every_setting(tmp_path, name, symbol,
                                                  cell, cb):
    """write -> cctbx parses -> the operators ARE the model's group."""
    import iotbx.cif

    from crystalpilot.report.cif import structure_to_cif

    xs = _structure(symbol, cell, cb)
    p = structure_to_cif(xs, tmp_path / f"{name}.cif", z=4)
    text = p.read_text(encoding="utf-8")
    built = iotbx.cif.reader(input_string=text).build_crystal_structures()
    got = list(built.values())[0]
    assert got.space_group() == xs.space_group(), (
        f"{name}: read back {got.space_group_info()} for "
        f"{xs.space_group_info()}")
    # and the names in the file are true for the loop, not merely parseable
    assert CS.check_cif_symmetry(text)["consistent"] is True
    # every line stays inside the 80-character CIF record limit (PLATON 802)
    assert not [ln for ln in text.splitlines() if len(ln) > 80]


def test_hm_symbol_only_when_it_is_true():
    """A tabulated setting keeps its H-M name; an arbitrary origin shift
    gets '?' rather than a symbol the operators contradict."""
    assert CS.hm_symbol_for(_sg("P 21/n")) == "P 1 21/n 1"
    assert CS.hm_symbol_for(_sg("C 2/c")) == "C 1 2/c 1"
    assert CS.hm_symbol_for(_sg("F d -3 m :1")) == "F d -3 m :1"
    shifted = _sg("P 21 21 21", "x+1/4,y,z-1/4")
    assert CS.hm_symbol_for(shifted) is None


@pytest.mark.parametrize("name,symbol,cell,cb",
                         SETTINGS, ids=[s[0] for s in SETTINGS])
def test_hall_symbol_parses_back_to_the_same_group(name, symbol, cell, cb):
    from cctbx import sgtbx
    sg = _sg(symbol, cb)
    hall = CS.hall_symbol_for(sg)
    assert hall, f"{name}: no Hall symbol"
    assert sgtbx.space_group(hall) == sg, f"{name}: {hall} names another group"


def test_describe_reports_the_change_of_basis_and_whether_hkl_moves():
    shifted = CS.describe(_sg("P 21 21 21", "x+1/4,y,z-1/4"))
    assert shifted["is_reference_setting"] is False
    assert shifted["cb_op"] == "x+1/4,y,z-1/4"
    assert shifted["hkl_reindexed"] is False        # pure origin shift
    assert shifted["hm"] is None and shifted["hall"]
    # an axis choice is NOT a pure origin shift: hkl would be reindexed
    p21n = CS.describe(_sg("P 21/n"))
    assert p21n["is_reference_setting"] is False
    assert p21n["hkl_reindexed"] is True
    assert p21n["hm"] == "P 1 21/n 1"
    p21c = CS.describe(_sg("P 21/c"))
    assert p21c["is_reference_setting"] is True
    assert p21c["hkl_reindexed"] is False
    assert p21c["cb_op"] == "x,y,z"


# --------------------------------------------------------------------------- #
# the hsl file, by hand: a true symbol for the WRONG setting
# --------------------------------------------------------------------------- #

INCONSISTENT_CIF = """\
data_hsl
_cell_length_a     5.0215
_cell_length_b     9.8852
_cell_length_c    17.7668
_cell_angle_alpha 90.000
_cell_angle_beta  90.000
_cell_angle_gamma 90.000
_space_group_crystal_system  orthorhombic
_space_group_IT_number       19
_space_group_name_H-M_alt    'P 21 21 21'
_space_group_name_Hall       ?
_symmetry_cell_setting       orthorhombic
_symmetry_Int_Tables_number  19
_symmetry_space_group_name_H-M 'P 21 21 21'
loop_
 _space_group_symop_operation_xyz
 'x, y, z'
 'x+1/2, -y+1/2, -z+1/2'
 '-x+1/2, y+1/2, -z'
 '-x, -y, z+1/2'
_chemical_formula_sum  'C8 N1 O4'
_cell_formula_units_Z  4
_refine_ls_R_factor_gt  0.0263
_refine_ls_wR_factor_ref 0.0683
_refine_ls_goodness_of_fit_ref 1.038
_refine_ls_number_parameters 119
loop_
 _atom_site_label
 _atom_site_type_symbol
 _atom_site_fract_x
 _atom_site_fract_y
 _atom_site_fract_z
 _atom_site_occupancy
 O1 O 0.3000 0.2000 0.1000 1.0
 O2 O 0.6000 0.3000 0.2000 1.0
 N1 N 0.1000 0.5000 0.3000 1.0
 C1 C 0.4000 0.4000 0.4000 1.0
"""


def test_the_defect_is_detected_named_and_repaired(tmp_path):
    import iotbx.cif

    chk = CS.check_cif_symmetry(INCONSISTENT_CIF)
    assert chk["consistent"] is False
    assert chk["ops_setting"] == "P 21 21 21 (a+1/4,b,c-1/4)"
    tags = {c["tag"] for c in chk["conflicting"]}
    assert "_space_group_name_H-M_alt" in tags
    # the IT number is TRUE for every setting of the group - not a conflict
    assert "_space_group_IT_number" not in tags

    with pytest.raises(Exception):
        iotbx.cif.reader(
            input_string=INCONSISTENT_CIF).build_crystal_structures()

    fixed, info = CS.rewrite_symmetry_tags(INCONSISTENT_CIF)
    assert info["changed"]
    assert info["setting_change"]["cb_op"] == "x+1/4,y,z-1/4"
    assert info["setting_change"]["hkl_reindexed"] is False
    built = iotbx.cif.reader(input_string=fixed).build_crystal_structures()
    xs = list(built.values())[0]
    assert str(xs.space_group_info()) == "P 21 21 21 (a+1/4,b,c-1/4)"
    assert CS.check_cif_symmetry(fixed)["consistent"] is True
    # coordinates and operators are untouched - only the NAMES moved
    for line in INCONSISTENT_CIF.splitlines():
        if line.startswith((" O", " N", " C", " 'x", " '-")):
            assert line in fixed
    # idempotent: a second pass changes nothing
    again, info2 = CS.rewrite_symmetry_tags(fixed)
    assert again == fixed and not info2["changed"]


def test_consistent_cif_is_left_alone_except_for_a_missing_hall():
    from crystalpilot.report.cif import structure_to_cif
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        p = structure_to_cif(_structure("P 21/c", (10, 11, 12, 90, 95, 90)),
                             Path(d) / "m.cif")
        text = p.read_text(encoding="utf-8")
    fixed, info = CS.rewrite_symmetry_tags(text)
    assert fixed == text and not info["changed"]


def test_loader_believes_the_operator_loop(tmp_path):
    """The grader's own loader: the structure comes back on the SHIFTED
    operators, and the defect is reported instead of being papered over."""
    from crystalpilot.benchmark.evaluate import load_cif_structure

    p = tmp_path / "final.cif"
    p.write_text(INCONSISTENT_CIF, encoding="utf-8")
    xs, info = load_cif_structure(p)
    assert xs is not None
    assert info["cif_symmetry_inconsistent"] is True
    assert info["loader"] == "iotbx"
    assert str(xs.space_group_info()) == "P 21 21 21 (a+1/4,b,c-1/4)"
    assert [o.as_xyz() for o in xs.space_group().all_ops()] == [
        "x,y,z", "x+1/2,-y+1/2,-z+1/2", "-x+1/2,y+1/2,-z", "-x,-y,z+1/2"]


def test_loader_reports_nothing_for_a_clean_cif(tmp_path):
    from crystalpilot.benchmark.evaluate import load_cif_structure

    fixed, _ = CS.rewrite_symmetry_tags(INCONSISTENT_CIF)
    p = tmp_path / "clean.cif"
    p.write_text(fixed, encoding="utf-8")
    xs, info = load_cif_structure(p)
    assert xs is not None and info["cif_symmetry_inconsistent"] is False


def test_operator_loop_read_from_the_deprecated_tag():
    """Old files spell the loop `_symmetry_equiv_pos_as_xyz`, sometimes
    with a site-id column."""
    text = INCONSISTENT_CIF.replace(
        "loop_\n _space_group_symop_operation_xyz\n",
        "loop_\n _symmetry_equiv_pos_site_id\n _symmetry_equiv_pos_as_xyz\n")
    for i, op in enumerate(("x, y, z", "x+1/2, -y+1/2, -z+1/2",
                            "-x+1/2, y+1/2, -z", "-x, -y, z+1/2"), 1):
        text = text.replace(f" '{op}'", f" {i} '{op}'")
    sg = CS.space_group_from_cif_text(text)
    assert sg is not None
    assert str(sg.info()) == "P 21 21 21 (a+1/4,b,c-1/4)"


def test_scan_fallback_survives_an_unparseable_cif():
    """A file iotbx cannot even tokenize still yields its operator loop."""
    broken = "data_x\n_bad_tag\nloop_\n _space_group_symop_operation_xyz\n" \
             " 'x, y, z'\n '-x, -y, -z'\n\n_cell_length_a ]]]\n"
    ops = CS._ops_via_scan(broken)
    assert ops == ["x, y, z", "-x, -y, -z"]
    assert str(CS.space_group_from_cif_text(broken).info()) == "P -1"


# --------------------------------------------------------------------------- #
# write_outputs: the delivery reports its setting and stays coherent
# --------------------------------------------------------------------------- #

def _shifted_p212121_structure():
    return _structure("P 21 21 21", (5.0215, 9.8852, 17.7668, 90, 90, 90),
                      "x+1/4,y,z-1/4")


def test_delivery_coherence_flags_a_lying_symbol(tmp_path):
    from crystalpilot.refine.tools_deliver import WriteOutputs

    out = tmp_path / "d"
    out.mkdir()
    (out / "final.cif").write_text(INCONSISTENT_CIF, encoding="utf-8")
    issues = WriteOutputs._delivery_coherence(out, {}, publication=False)
    assert any("final.cif symmetry" in s for s in issues), issues
    fixed, _ = CS.rewrite_symmetry_tags(INCONSISTENT_CIF)
    (out / "final.cif").write_text(fixed, encoding="utf-8")
    assert not [s for s in WriteOutputs._delivery_coherence(
        out, {}, publication=False) if "symmetry" in s]


@pytest.mark.parametrize("name,symbol,cell,cb",
                         SETTINGS, ids=[s[0] for s in SETTINGS])
def test_both_delivery_writers_agree_on_the_names(tmp_path, name, symbol,
                                                  cell, cb):
    """final.cif has two producers - the minimal writer (report/cif.py, used
    when no SHELXL job matches) and the publication assembler over SHELXL's
    ACTA backbone (report/publication.py). They must name the setting the
    same way; before the fix one wrote the reference-setting symbol and the
    other passed SHELXL's '?' Hall through untouched."""
    from crystalpilot.report.cif import structure_to_cif
    from crystalpilot.report.publication import assemble_publication_cif

    sg = _sg(symbol, cb)
    minimal = structure_to_cif(_structure(symbol, cell, cb),
                               tmp_path / f"{name}.cif").read_text(
                                   encoding="utf-8")
    # a SHELXL-shaped backbone: same operators, the reference-setting name
    shelxl_like = (
        "data_job\n"
        f"_space_group_crystal_system       {sg.crystal_system().lower()}\n"
        f"_space_group_IT_number            {sg.info().type().number()}\n"
        "_space_group_name_H-M_alt         "
        f"'{str(sg.info().reference_setting())}'\n"
        "_space_group_name_Hall            ?\n"
        "loop_\n _space_group_symop_operation_xyz\n"
        + "".join(f" '{o.as_xyz()}'\n" for o in sg.all_ops())
        + "_cell_length_a  10.0\n")
    assembled = assemble_publication_cif(shelxl_like)[0]
    hm = CS.hm_symbol_for(sg)
    hall = CS.hall_symbol_for(sg)
    for text, who in ((minimal, "minimal"), (assembled, "publication")):
        assert CS.check_cif_symmetry(text)["consistent"] is True, who
        assert _tag(text, "_space_group_name_H-M_alt") == (
            f"'{hm}'" if hm else "?"), who
        assert _tag(text, "_space_group_name_Hall") == f"'{hall}'", who


def _tag(text: str, tag: str) -> str | None:
    for line in text.splitlines():
        if line.startswith(tag):
            return line[len(tag):].strip()
    return None


def test_publication_assembly_corrects_the_names_and_reports_the_setting():
    from crystalpilot.report.publication import assemble_publication_cif

    text, rep = assemble_publication_cif(INCONSISTENT_CIF)
    assert rep["symmetry_names_corrected"]
    setting = rep["setting_change"]
    assert setting["cb_op"] == "x+1/4,y,z-1/4"
    assert setting["is_reference_setting"] is False
    assert CS.check_cif_symmetry(text)["consistent"] is True
    # the '?' H-M is disclosed with the alert it costs, not hidden
    assert any(m["tag"] == "_space_group_name_H-M_alt"
               and m.get("checkcif_alert") == "122_A"
               for m in rep["missing_metadata"])


# ---------------------------------------------------------------------------
# 2026-09-08 usertest test3-2 (P3(2)21): the Hall symbol's own double quote
# ---------------------------------------------------------------------------

HALL_QUOTE_CIF = """\
data_x
_cell_length_a 37.6938
_cell_length_b 37.6938
_cell_length_c 21.1155
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 120
_space_group_crystal_system trigonal
_space_group_IT_number 154
_space_group_name_H-M_alt 'P 32 2 1'
_space_group_name_Hall 'P 32 2"'
loop_
 _space_group_symop_operation_xyz
 'x, y, z'
 '-y, x-y, z+2/3'
 '-x+y, -x, z+1/3'
 'x-y, -y, -z+1/3'
 '-x, -x+y, -z+2/3'
 'y, x, -z'
"""


def test_hall_symbol_ending_in_a_double_quote_is_not_a_conflict():
    """SHELXL writes P3(2)21's Hall symbol as 'P 32 2"'; the quote is the
    2" axis, not a delimiter. Stripping it named P3(2)12 and made
    finalize_delivery refuse a correct CIF three times in one session."""
    sym = CS.check_cif_symmetry(HALL_QUOTE_CIF)
    assert sym["checked"] is True
    assert sym["consistent"] is True, sym
    # the same file must survive rewrite_symmetry_tags byte-identical
    text, info = CS.rewrite_symmetry_tags(HALL_QUOTE_CIF)
    assert text == HALL_QUOTE_CIF
    assert info["corrected"] == [] and info["filled"] == []


def test_cif_unquote_removes_only_a_matching_outer_pair():
    assert CS.cif_unquote("'P 32 2\"'") == 'P 32 2"'
    assert CS.cif_unquote('"P 3 2\'"') == "P 3 2'"
    assert CS.cif_unquote("'P 21 21 21'") == "P 21 21 21"
    assert CS.cif_unquote("154") == "154"
    assert CS.cif_unquote("  ?  ") == "?"
    assert CS.cif_unquote(None) is None
    # a stray leading quote with no partner is left alone (not a token)
    assert CS.cif_unquote("'abc") == "'abc"


@pytest.mark.parametrize("symbol", ["P 3 2 1", "P 31 2 1", "P 32 2 1",
                                    "R 3 2 :H", "R -3 c :H", "P -3 m 1"])
def test_every_double_quote_hall_symbol_round_trips(symbol):
    """All twelve tabulated Hall symbols that carry a `"` must come back
    consistent from our own writer (cif_symmetry_block) and from a
    SHELXL-style quoted tag."""
    from cctbx import sgtbx
    sg = sgtbx.space_group_info(symbol=symbol).group()
    lines, desc = CS.cif_symmetry_block(sg)
    assert '"' in desc["hall"], desc["hall"]      # 2" axis (P 3 2", -R 3 2"c ...)
    body = "\n".join(lines) + "\nloop_\n _space_group_symop_operation_xyz\n" + \
        "\n".join(f" '{op.as_xyz()}'" for op in sg.all_ops()) + "\n"
    assert CS.check_cif_symmetry(body)["consistent"] is True
