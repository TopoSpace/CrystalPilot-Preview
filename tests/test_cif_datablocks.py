"""What counts as a data block, and where the reflections hide (2026-09 survey).

Two findings from the same file set, pulling in opposite directions.

1. Journal deposits routinely put several compounds in ONE .cif, one data
   block each. Every extractor in import_cif_model is either a whole-file
   regex (_semicolon_field / _cif_number) or a single-block reader (gemmi,
   which refuses the file outright), so an unsliced multi-block CIF used to
   return block 1 SILENTLY - you asked for compound 4 and got compound 1,
   with no note anywhere. Worse: if block 1 has a res but not an hkl, the
   res and the reflections could come from different compounds.

2. Olex2's IUCr export looks like two same-named blocks and is not: the
   second `data_` sits INSIDE the semicolon field _iucr_refine_fcf_details,
   which holds the entire .fcf - a CIF document in its own right. The
   scanner in (1) is right to see one block, and iotbx is right that the
   block has no _refln loop. But the reflections ARE in the file, and these
   deposits carry no _shelx_hkl_file, so that fcf is the only copy: 4 of the
   13 shortlist files were unimportable for want of reading it.
"""
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def _block(name: str, a: float, formula: str) -> str:
    """A minimal but structurally real block: cell, one atom, an embedded
    SHELX res and hkl - the two fields the whole-file regexes grab.

    Written flush-left on purpose: in CIF a semicolon text field only
    opens/closes when the ';' is in column 1."""
    # SHELX HKLF4 is fixed-format 3I4,2F8.2 - not free-form
    hkl = "\n".join("%4d%4d%4d%8.2f%8.2f" % (h, 0, 0, 100.0, 2.0)
                    for h in range(1, 15))
    return (
        f"data_{name}\n"
        f"_chemical_formula_sum          '{formula}'\n"
        f"_cell_length_a                 {a}\n"
        f"_cell_length_b                 {a}\n"
        f"_cell_length_c                 {a}\n"
        "_cell_angle_alpha              90\n"
        "_cell_angle_beta               90\n"
        "_cell_angle_gamma              90\n"
        "_cell_formula_units_Z          1\n"
        "_space_group_name_H-M_alt      'P 1'\n"
        "_diffrn_radiation_wavelength   0.71073\n"
        "_shelx_res_file\n;\n"
        f"TITL {name}\n"
        f"CELL 0.71073 {a} {a} {a} 90 90 90\n"
        "ZERR 1 0.001 0.001 0.001 0 0 0\n"
        "LATT -1\nSFAC C\nUNIT 1\n"
        "C1    1  0.100000  0.100000  0.100000  11.00000  0.02000\n"
        "HKLF 4\nEND\n;\n"
        "_shelx_hkl_file\n;\n"
        f"{hkl}\n   0   0   0    0.00     0.00\n;\n")


@pytest.fixture()
def multi_cif(tmp_path):
    p = tmp_path / "deposit.cif"
    p.write_text(_block("COMPOUND-A", 10.0, "C1")
                 + _block("COMPOUND-B", 20.0, "C1")
                 + _block("COMPOUND-C", 30.0, "C1"), encoding="utf-8")
    return p


@pytest.fixture()
def project(tmp_path):
    d = tmp_path / "proj"
    d.mkdir()
    (d / "context.json").write_text(json.dumps({"chemistry": {}}),
                                    encoding="utf-8")
    from crystalpilot.refine.project import RefineProject
    p = RefineProject(d)
    p.open()
    return p


class TestBlockScanner:
    def test_splits_on_block_headers(self, multi_cif):
        from crystalpilot.refine.tools_ingest import _cif_data_blocks
        got = _cif_data_blocks(multi_cif.read_text(encoding="utf-8"))
        assert [n for n, _ in got] == ["COMPOUND-A", "COMPOUND-B",
                                       "COMPOUND-C"]
        # each slice must carry its OWN embedded res, not the first one
        assert "CELL 0.71073 20.0" in got[1][1]
        assert "CELL 0.71073 10.0" not in got[1][1]

    def test_data_line_inside_a_text_field_is_not_a_header(self):
        from crystalpilot.refine.tools_ingest import _cif_data_blocks
        text = ("data_only\n_note\n;\ndata_this_is_prose_not_a_block\n;\n"
                "_cell_length_a 5\n")
        assert [n for n, _ in _cif_data_blocks(text)] == ["only"]

    def test_single_block_file(self, multi_cif):
        from crystalpilot.refine.tools_ingest import _cif_data_blocks
        one = _block("SOLO", 12.0, "C1")
        assert [n for n, _ in _cif_data_blocks(one)] == ["SOLO"]


class TestImportRefusesToGuess:
    def test_multi_block_without_a_choice_is_refused(self, project,
                                                     multi_cif):
        r = project.invoke_tool("import_cif_model",
                                {"cif_path": str(multi_cif)})
        assert not r.ok
        assert "3 data blocks" in r.error
        # the names must be in the message or the agent cannot choose
        for n in ("COMPOUND-A", "COMPOUND-B", "COMPOUND-C"):
            assert n in r.error

    def test_unknown_block_name_lists_the_real_ones(self, project,
                                                    multi_cif):
        r = project.invoke_tool("import_cif_model",
                                {"cif_path": str(multi_cif),
                                 "data_block": "COMPOUND-Z"})
        assert not r.ok
        assert "COMPOUND-A" in r.error

    def test_chosen_block_is_the_one_imported(self, project, multi_cif):
        r = project.invoke_tool("import_cif_model",
                                {"cif_path": str(multi_cif),
                                 "data_block": "COMPOUND-B"})
        assert r.ok, r.error
        # a=20 belongs to block B alone; block A (a=10) came first in the
        # file and is what the old whole-file regexes returned
        cell = project.session.model.unit_cell().parameters()
        assert cell[0] == pytest.approx(20.0)
        assert any("COMPOUND-B" in n for n in r.summary["conversion_notes"])


SURVEY = Path("H:/CrystalPilotData/e-survey/misc-cifs/1901776-1901786.cif")


@pytest.mark.skipif(not SURVEY.exists(), reason="survey CIF not staged")
class TestRealDeposit:
    def test_five_blocks_found(self):
        from crystalpilot.refine.tools_ingest import _cif_data_blocks
        names = [n for n, _ in
                 _cif_data_blocks(SURVEY.read_text(encoding="utf-8",
                                                   errors="replace"))]
        # the filename advertises 11 CCDC numbers; the file holds 5 blocks
        assert names == ["IAM-2-lt", "IAM-2-rt", "IAM-2-BPYDC",
                         "IAM-2-BPDC", "IAM-3"]


# ==========================================================================
# Olex2 IUCr export: the reflections live inside _iucr_refine_fcf_details
# ==========================================================================

#: F^2 large enough that write_hklf4 must scale to fit the F8.2 field - the
#: case where the deposited FVAR and the written hkl disagree by a decade
_BIG = 1.0e5


def _olex2_cif(name: str = "SYNTH", n_refl: int = 30, big: bool = True) -> str:
    """A CIF shaped like Olex2's IUCr export: structure block, no
    _shelx_hkl_file and no _shelx_res_file, the whole .fcf embedded as
    _iucr_refine_fcf_details and the .res as _iucr_refine_instructions_details.

    The inner `data_` is flush-left on purpose: that is exactly what makes it
    look like a second block to anything scanning for headers, and exactly why
    it is not one.
    """
    scale = _BIG if big else 1.0
    rows = "\n".join(
        "%d 0 0 %.3f %.3f %.3f o" % (h, scale, scale, scale / 50.0)
        for h in range(1, n_refl + 1))
    fcf = (f"data_{name}\n"
           "_shelx_refln_list_code            4\n"
           "loop_\n"
           "  _space_group_symop_id\n"
           "  _space_group_symop_operation_xyz\n"
           "  1  x,y,z\n"
           "loop_\n"
           " _refln_index_h\n _refln_index_k\n _refln_index_l\n"
           " _refln_F_squared_calc\n _refln_F_squared_meas\n"
           " _refln_F_squared_sigma\n _refln_observed_status\n"
           f"{rows}\n")
    res = ("TITL synth in P1\n"
           "CELL 0.71073 10 10 10 90 90 90\n"
           "ZERR 1 0.001 0.001 0.001 0 0 0\n"
           "LATT -1\nSFAC C\nUNIT 1\n"
           "WGHT 0.2 0\n"
           "FVAR 0.39535 0.75\n"
           "C1    1  0.100000  0.100000  0.100000  11.00000  0.02000\n"
           "HKLF 4\nEND\n")
    return (
        f"data_{name}\n"
        "_chemical_formula_sum          'C1'\n"
        "_cell_length_a                 10\n"
        "_cell_length_b                 10\n"
        "_cell_length_c                 10\n"
        "_cell_angle_alpha              90\n"
        "_cell_angle_beta               90\n"
        "_cell_angle_gamma              90\n"
        "_cell_formula_units_Z          1\n"
        "_space_group_name_H-M_alt      'P 1'\n"
        "_diffrn_radiation_wavelength   0.71073\n"
        "loop_\n"
        " _atom_site_label\n _atom_site_type_symbol\n"
        " _atom_site_fract_x\n _atom_site_fract_y\n _atom_site_fract_z\n"
        " _atom_site_U_iso_or_equiv\n"
        " C1 C 0.1 0.1 0.1 0.02\n"
        f"_iucr_refine_fcf_details\n;\n{fcf};\n"
        f"_iucr_refine_instructions_details\n;\n{res};\n")


@pytest.fixture()
def olex2_cif(tmp_path):
    p = tmp_path / "olex2.cif"
    p.write_text(_olex2_cif(), encoding="utf-8")
    return p


class TestEmbeddedFcfIsNotASecondBlock:
    def test_scanner_still_sees_one_block(self, olex2_cif):
        from crystalpilot.refine.tools_ingest import _cif_data_blocks
        text = olex2_cif.read_text(encoding="utf-8")
        assert text.count("\ndata_SYNTH") == 1     # the inner one is flush-left
        assert [n for n, _ in _cif_data_blocks(text)] == ["SYNTH"]

    def test_reflections_are_found_inside_the_text_field(self, olex2_cif):
        import iotbx.cif
        from crystalpilot.io.cif_sf import _find_refln_block
        model = iotbx.cif.reader(file_path=str(olex2_cif)).model()
        # the premise: the block itself genuinely has no _refln loop
        assert model["SYNTH"].get("_refln_index_h") is None
        name, block, host = _find_refln_block(model)
        assert len(block["_refln_index_h"]) == 30
        assert host is model["SYNTH"]              # metadata falls back here
        assert "_iucr_refine_fcf_details" in name  # provenance stays visible

    def test_a_real_refln_loop_wins_over_an_embedded_one(self, tmp_path):
        import iotbx.cif
        from crystalpilot.io.cif_sf import _find_refln_block
        p = tmp_path / "both.cif"
        p.write_text(_olex2_cif().replace(
            "loop_\n _atom_site_label",
            "loop_\n _refln_index_h\n _refln_index_k\n _refln_index_l\n"
            " _refln_F_squared_meas\n _refln_F_squared_sigma\n"
            " 9 9 9 5.0 1.0\n"
            "loop_\n _atom_site_label"), encoding="utf-8")
        _name, block, host = _find_refln_block(
            iotbx.cif.reader(file_path=str(p)).model())
        assert len(block["_refln_index_h"]) == 1   # the top-level loop
        assert host is None


class TestLoadEmbeddedFcf:
    def test_dataset_metadata_comes_from_the_host_block(self, olex2_cif):
        from crystalpilot.io.cif_sf import load_cif_sf_dataset
        ds = load_cif_sf_dataset(olex2_cif)
        assert ds.intensities.size() == 30
        # the bare fcf carries symops but no cell/wavelength/formula: those
        # can only have come from the structure block that hosted it
        assert ds.intensities.unit_cell().parameters()[0] == pytest.approx(10.0)
        assert ds.wavelength == pytest.approx(0.71073)
        assert ds.composition is not None and ds.composition.elements == {"C": 1.0}
        assert ds.instrument_meta["embedded_fcf"] is True
        assert ds.instrument_meta["merged"] is True
        assert ds.instrument_meta["shelx_refln_list_code"] == "4"

    def test_plain_cif_without_reflections_still_raises(self, tmp_path):
        from crystalpilot.io.cif_sf import load_cif_sf_dataset
        p = tmp_path / "bare.cif"
        p.write_text(_block("BARE", 10.0, "C1"), encoding="utf-8")
        with pytest.raises(ValueError, match="no _refln_index_h"):
            load_cif_sf_dataset(p)


class TestImportFromEmbeddedFcf:
    def test_import_succeeds_and_says_the_data_is_merged(self, project,
                                                         olex2_cif):
        r = project.invoke_tool("import_cif_model",
                                {"cif_path": str(olex2_cif)})
        assert r.ok, r.error
        assert r.summary["imported_atoms"] == 1
        assert (project.dir / "crystal.hkl").exists()
        note = " ".join(r.summary["conversion_notes"])
        assert "_iucr_refine_fcf_details" in note
        # the caveat is the point: this is not the raw measurement
        assert "MERGED" in note and "not the raw measurement" in note

    def test_provenance_is_recorded_in_context(self, project, olex2_cif):
        project.invoke_tool("import_cif_model", {"cif_path": str(olex2_cif)})
        ctx = json.loads((project.dir / "context.json").read_text(
            encoding="utf-8"))
        assert "_iucr_refine_fcf_details" in ctx["data"]["reflections"]

    def test_scale_factor_is_rewritten_to_match_the_written_hkl(
            self, project, olex2_cif):
        """The deposited FVAR scales the deposit's own hkl; next to
        fcf-derived reflections it is the wrong number and the res
        contradicts the crystal.hkl written beside it. (It does not change
        the recomputed R1 - both engines refit the overall scale - so this
        is about self-consistent inputs, not about reproducing the deposit.)"""
        r = project.invoke_tool("import_cif_model",
                                {"cif_path": str(olex2_cif)})
        assert r.ok, r.error
        res = (project.dir / "start.res").read_text(encoding="ascii")
        fvar = next(ln.split() for ln in res.splitlines()
                    if ln.split() and ln.split()[0] == "FVAR")
        # F^2 ~ 1e5 overflows F8.2, so write_hklf4 scales by 1e-2 and the
        # matching overall scale factor is sqrt(1e-2)
        assert float(fvar[1]) == pytest.approx(0.1, abs=1e-6)
        assert float(fvar[2]) == pytest.approx(0.75)   # free variables kept
        assert any("scale factor" in n for n in r.summary["conversion_notes"])

    def test_untouched_when_the_hkl_needed_no_rescaling(self, project,
                                                        tmp_path):
        small = tmp_path / "small.cif"
        small.write_text(_olex2_cif(big=False), encoding="utf-8")
        r = project.invoke_tool("import_cif_model", {"cif_path": str(small)})
        assert r.ok, r.error
        res = (project.dir / "start.res").read_text(encoding="ascii")
        fvar = next(ln.split() for ln in res.splitlines()
                    if ln.split() and ln.split()[0] == "FVAR")
        assert float(fvar[1]) == pytest.approx(1.0)    # sqrt(scale 1.0)

    def test_free_variables_survive_a_rewrite(self, tmp_path):
        from crystalpilot.refine.tools_ingest import _set_res_osf
        p = tmp_path / "x.res"
        p.write_text("TITL t\nFVAR 0.39535 0.75 0.25\nHKLF 4\nEND\n",
                     encoding="ascii")
        assert _set_res_osf(p, 0.1) == pytest.approx(0.39535)
        assert p.read_text(encoding="ascii").splitlines()[1].split()[1:] == \
            ["0.100000", "0.75", "0.25"]

    def test_missing_reflections_message_names_both_tags(self, project,
                                                         tmp_path):
        p = tmp_path / "nodata.cif"
        # a structure block with neither an embedded hkl nor an embedded fcf
        text = _block("NODATA", 10.0, "C1")
        text = text[:text.index("_shelx_hkl_file")]
        p.write_text(text, encoding="utf-8")
        r = project.invoke_tool("import_cif_model", {"cif_path": str(p)})
        assert not r.ok
        assert "no reflection data" in r.error
        assert "_shelx_hkl_file" in r.error
        assert "_iucr_refine_fcf_details" in r.error


SURVEY_OLEX2 = {
    "Q.cif": 5865,
    "T2-1-cage.cif": 32064,
    "shelxt-2024-07-Cu.cif": 11896,
    "shelxt250626-La.cif": 20054,
}


@pytest.mark.skipif(not SURVEY.parent.exists(), reason="survey CIFs not staged")
class TestRealOlex2Deposits:
    """The four files the 2026-09 survey could not ingest at all. Reflection
    counts are the deposits' own _refine_ls REM Reflections_all."""

    @pytest.mark.parametrize("name,n_refl", sorted(SURVEY_OLEX2.items()))
    def test_imports_with_its_reflections(self, project, name, n_refl):
        src = SURVEY.parent / name
        if not src.exists():
            pytest.skip(f"{name} not staged")
        r = project.invoke_tool("import_cif_model", {"cif_path": str(src)})
        assert r.ok, r.error
        assert r.summary["imported_via"] == "embedded_shelx_res"
        # HKLF4 plus the 0 0 0 terminator
        lines = (project.dir / "crystal.hkl").read_text().strip().splitlines()
        assert len(lines) == n_refl + 1


ED_CIF = Path("H:/CrystalPilotData/e-survey/wechat-2026-08/SJTU-98.cif")


class TestLongFormSfac:
    """SHELX long-form SFAC (one element + its 14 scattering-factor
    coefficients) is how a refinement supplies non-default form factors -
    in practice, electron scattering factors. iotbx's own parser raises
    NotImplementedError on the card, which knocked the fidelity path out
    and silently degraded the import to the atom loop (losing disorder
    linkage and restraints) on the one file where they matter."""

    def _res(self, tmp_path, lam="0.0251"):
        p = tmp_path / "ed.res"
        p.write_text(
            f"TITL ed\nCELL {lam} 10 10 10 90 90 90\n"
            "ZERR 1 0 0 0 0 0 0\nLATT -1\n"
            "SFAC  C 0.136 0.373 0.548 3.281 1.227 13.046 0.597 41.02 "
            "0 0 0 0 0.75 12.011\n"
            "SFAC  O 0.143 0.305 0.51 2.268 0.937 8.262 0.392 25.665 "
            "0 0 0 0 0.63 15.999\n"
            "UNIT 2 1\nFVAR 1.0\n"
            "C1    1  0.100000  0.100000  0.100000  11.00000  0.02000\n"
            "O1    2  0.300000  0.300000  0.300000  11.00000  0.02500\n"
            "HKLF 4\nEND\n", encoding="ascii")
        return p

    def test_parses_and_keeps_the_element_order(self, tmp_path):
        from crystalpilot.io.shelx_model import load_res_model
        m = load_res_model(self._res(tmp_path))
        assert m.sfac == ["C", "O"]          # index 1=C, 2=O: atom types
        assert m.structure.scatterers().size() == 2
        els = [sc.scattering_type for sc in m.structure.scatterers()]
        assert els == ["C", "O"]

    def test_custom_factors_are_recorded_not_discarded(self, tmp_path):
        from crystalpilot.io.shelx_model import load_res_model
        m = load_res_model(self._res(tmp_path))
        assert set(m.custom_sfac) == {"C", "O"}
        assert m.custom_sfac["C"][0] == pytest.approx(0.136)
        assert m.is_electron_diffraction

    def test_xray_wavelength_is_not_called_electron(self, tmp_path):
        from crystalpilot.io.shelx_model import load_res_model
        m = load_res_model(self._res(tmp_path, lam="0.71073"))
        assert m.custom_sfac and not m.is_electron_diffraction

    @pytest.mark.skipif(not ED_CIF.exists(), reason="survey CIF not staged")
    def test_real_electron_diffraction_deposit(self, project):
        r = project.invoke_tool("import_cif_model", {"cif_path": str(ED_CIF)})
        assert r.ok, r.error
        assert r.summary["imported_atoms"] == 140
        assert r.summary["imported_via"] == "embedded_shelx_res"
        note = " ".join(r.summary["conversion_notes"])
        assert "ELECTRON diffraction" in note and "X-RAY tables" in note
