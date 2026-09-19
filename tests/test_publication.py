"""Publication CIF assembler: fills SHELXL ACTA '?' slots, honestly reports
what remains, and documents the solvent mask."""
from __future__ import annotations

from crystalpilot.report.publication import assemble_publication_cif

MINI_ACTA = """\
data_test
_chemical_formula_moiety          ?
_cell_measurement_temperature     293(2)
_cell_measurement_reflns_used     ?
_cell_measurement_theta_min       ?
_cell_measurement_theta_max       ?
_exptl_crystal_description        ?
_exptl_crystal_colour             ?
_exptl_crystal_size_max           ?
_exptl_crystal_size_mid           ?
_exptl_crystal_size_min           ?
_exptl_absorpt_correction_type    ?
_exptl_absorpt_correction_T_min   ?
_exptl_absorpt_correction_T_max   ?
_exptl_absorpt_process_details    ?
_diffrn_ambient_temperature       293(2)
_diffrn_source                    ?
_diffrn_measurement_device_type   ?
_diffrn_measurement_method        ?
_computing_data_collection        ?
_computing_structure_solution     'SHELXT 2018/2 (Sheldrick, 2018)'
_computing_molecular_graphics     ?
_computing_publication_material   ?
_refine_special_details           ?
_atom_sites_solution_primary      ?
_refine_ls_R_factor_gt            0.0611

loop_
 _atom_site_label
 _atom_site_type_symbol
 C1 C
"""

EXPERIMENT = {
    "temperature_K": 100,
    "crystal": {"description": "block", "colour": "colourless",
                "size_mm": [0.2, 0.15, 0.1]},
    "instrument": {"diffractometer": "Bruker D8 VENTURE",
                   "source": "sealed tube", "method": "omega scans"},
    "absorption": {"type": "multi-scan", "t_min": 0.6, "t_max": 0.75,
                   "details": "SADABS"},
    "cell_measurement": {"reflns_used": 9917, "theta_min": 3.6,
                         "theta_max": 79.8},
}

MASK = {"voids": [{"void": 1, "volume_A3": 9060.7, "electrons": 1385.0,
                   "centre_frac": [0.0, 0.25, 0.42]}],
        "solvent_volume_A3": 9060.7,
        "total_solvent_electrons_per_cell": 1385.0}


def test_fractional_formula_sum_caveat():
    cif = MINI_ACTA.replace(
        "_chemical_formula_moiety          ?",
        "_chemical_formula_moiety          ?\n"
        "_chemical_formula_sum             'C6 H4.50 N1 O0.50'")
    _, rep = assemble_publication_cif(cif)
    assert any("非整数" in c for c in rep["caveats"])


def test_integral_formula_sum_no_caveat():
    cif = MINI_ACTA.replace(
        "_chemical_formula_moiety          ?",
        "_chemical_formula_moiety          ?\n"
        "_chemical_formula_sum             'C6 H4.00 N2 O1'")
    _, rep = assemble_publication_cif(cif)
    assert not any("非整数" in c for c in rep["caveats"])


def test_fills_experiment_and_mask():
    out, rep = assemble_publication_cif(MINI_ACTA, experiment=EXPERIMENT,
                                        mask_info=MASK, moiety="C1 H1")
    assert "_exptl_crystal_colour             colourless" in out
    assert "_exptl_absorpt_correction_type    multi-scan" in out
    assert "_cell_measurement_reflns_used     9917" in out
    # temperature is FORCED (SHELXL default 293(2) must be overridden)
    assert "_diffrn_ambient_temperature       100" in out
    # our solution provenance replaces the SHELXT default claim
    assert "CrystalPilot (charge flipping" in out
    assert "_platon_squeeze_void_nr" in out
    assert " 1 0.000 0.250 0.420 9060.7 1385.0" in out
    assert "_refine_special_details" in out and "solvent mask" in out.lower()
    assert "_exptl_crystal_size_max" in rep["filled"] or \
           "_exptl_crystal_size_max           0.200" in out
    # nothing left silently: remaining placeholders reported
    assert isinstance(rep["remaining_placeholders"], list)


def test_honest_when_nothing_known():
    out, rep = assemble_publication_cif(MINI_ACTA)
    # untouched placeholders stay '?', and the report says so
    assert "_exptl_crystal_colour             ?" in out
    assert any("_exptl_crystal_colour" in c for c in
               rep["remaining_placeholders"])
    # WP4: an unmeasured temperature must never reach the CIF as a number.
    # SHELXL's silent 20 C/293 K default (a fine assumption for riding-H
    # geometry, printed here into ACTA's temperature tags as if measured)
    # must be OVERRIDDEN to '?', not copied forward as a fact.
    assert "293(2)" not in out
    assert "_diffrn_ambient_temperature       ?" in out
    assert "_cell_measurement_temperature     ?" in out
    assert any("_diffrn_ambient_temperature" in c for c in
               rep["remaining_placeholders"])
    assert any("_cell_measurement_temperature" in c for c in
               rep["remaining_placeholders"])
    # the override is still disclosed as a caveat, just no longer a lie
    assert any("293(2)" in c for c in rep["caveats"])


def test_mask_details_without_void_list():
    out, rep = assemble_publication_cif(
        MINI_ACTA, mask_info={"solvent_volume_A3": 9082.7,
                              "total_solvent_electrons_per_cell": 2014.6})
    assert "_platon_squeeze_details" in out
    assert "_platon_squeeze_void_nr" not in out   # no fabricated void rows


ACTA_WITH_ESTIMATE = MINI_ACTA + """\
_shelx_estimated_absorpt_T_min    0.7776
_shelx_estimated_absorpt_T_max    0.8578
"""


def test_estimated_T_promoted_when_method_known():
    # a correction METHOD is on record but its T range is not -> SHELXL's
    # SIZE-based estimate is the honest fallback, with a caveat
    exp = {"absorption": {"type": "multi-scan"}}
    out, rep = assemble_publication_cif(ACTA_WITH_ESTIMATE, experiment=exp)
    assert "_exptl_absorpt_correction_T_min   0.7776" in out
    assert "_exptl_absorpt_correction_T_max   0.8578" in out
    assert any("SIZE" in c and "0.7776" in c for c in rep["caveats"])


def test_estimated_T_stays_caveat_without_method():
    # no correction on record: promoting the estimate would fabricate a
    # correction that never happened - caveat only
    out, rep = assemble_publication_cif(ACTA_WITH_ESTIMATE)
    assert "_exptl_absorpt_correction_T_min   ?" in out
    assert any("0.7776" in c and "set_experiment" in c
               for c in rep["caveats"])


def test_measured_T_wins_over_estimate():
    exp = {"absorption": {"type": "multi-scan", "t_min": 0.4131,
                          "t_max": 0.7462, "details": "TWINABS 2012/1"}}
    out, rep = assemble_publication_cif(ACTA_WITH_ESTIMATE, experiment=exp)
    assert "_exptl_absorpt_correction_T_min   0.4131" in out
    assert not any("SIZE" in c for c in rep["caveats"])


def test_non_ascii_transliterated_to_cif_markup():
    """CIF 1.1 is ASCII-only: Greek/Å riding in via experiment strings must
    come out as IUCr markup (Mo Kα → Mo K\a), never raw UTF-8 (r13: the
    grader's C++ CIF lexer crashed on _diffrn_source)."""
    exp = {"instrument": {
        "diffractometer": "Bruker",
        "source": "Mo sealed tube, Mo K\u03b1, \u03bb = 0.71073 \u00c5"}}
    text, rep = assemble_publication_cif(MINI_ACTA, experiment=exp)
    assert all(ord(c) < 127 for c in text)
    assert "Mo K" + chr(92) + "a" in text
    assert chr(92) + "l = 0.71073 " + chr(92) + "%A" in text
    assert any("转写" in c for c in rep["caveats"])


def test_pure_ascii_has_no_translit_caveat():
    text, rep = assemble_publication_cif(MINI_ACTA, experiment=EXPERIMENT)
    assert all(ord(c) < 127 for c in text)
    assert not any("转写" in c for c in rep["caveats"])


def test_bare_tags_get_question_marks():
    """r14b live-fire: SHELXL copies SADABS hkl-trailer metadata into ACTA
    output but drops the ')'-delimited process_details text, leaving a
    valueless tag that strict CIF parsers reject. The assembler must patch
    it to '?' while leaving semicolon text fields and loop headers alone."""
    broken = (
        "data_x\n"
        "_exptl_absorpt_correction_type   multi-scan\n"
        "_exptl_absorpt_process_details\n"
        "_exptl_absorpt_special_details    ?\n"
        "_refine_special_details\n"
        ";\n multi-line ok\n;\n"
        "loop_\n _atom_site_label\n _atom_site_type_symbol\n C1 C\n")
    text, rep = assemble_publication_cif(broken)
    assert "_exptl_absorpt_process_details    ?" in text
    assert ";\n multi-line ok\n;" in text          # semicolon field untouched
    assert "_atom_site_label    ?" not in text      # loop header untouched
    assert any("无值" in c for c in rep["caveats"])
    import iotbx.cif
    iotbx.cif.reader(input_string=text).model()     # strict parse passes


def test_value_on_next_line_not_patched():
    """CIF allows the value on the line after the tag - the bare-tag fixer
    must not orphan it (r14b regrade: _chemical_formula_sum + next-line
    quoted formula got a spurious '?')."""
    cif = ("data_x\n"
           "_chemical_formula_sum\n"
           "'C59.5 H56.5 Cl1.5 N4 O2'\n"
           "_exptl_absorpt_process_details\n"
           "_diffrn_ambient_temperature 150\n")
    text, rep = assemble_publication_cif(cif)
    assert "_chemical_formula_sum    ?" not in text
    assert "'C59.5 H56.5 Cl1.5 N4 O2'" in text
    assert "_exptl_absorpt_process_details    ?" in text
    import iotbx.cif
    iotbx.cif.reader(input_string=text).model()
