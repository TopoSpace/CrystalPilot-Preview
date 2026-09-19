"""The hand-over files (res / cif / ins / hkl / p4p) a crystallographer
continues from by hand - what each is made of and what is written down
about it. Shapes taken from usertest test3-1 / test3-2 (2026-09-08):
a vendor hkl ending at EOF (Olex2: "unknown hkl error"), a final.ins that
was a bare copy of final.res (no L.S. - restarts nothing), a .p4p fetched
by guessing its name, a model CIF with no statistics, and a SHELXL
_geom_bond row Zn-C 2.52 A that Olex2 drew as a seventh bond.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from crystalpilot.refine import deliver_files as df

ROWS = ("   1   0   0  100.00    2.00\n"
        "   0   1   0   50.00    1.50\n"
        "  -1   1   0   25.00    1.00\n")
TERM = "   0   0   0    0.00    0.00\n"
TRAILER = ("_computing_data_reduction 'SAINT V8.40B'\n"
           "_exptl_absorpt_correction_type multi-scan\n")

RES = ("TITL test in P -1\n"
       "CELL 0.71073 10.0 11.0 12.0 90 90 90\n"
       "ZERR 2 0.001 0.001 0.001 0 0 0\n"
       "LATT 1\nSFAC C H O\nUNIT 2 2 2\n"
       "WGHT 0.1\nFVAR 1.0\n"
       "C1 1 0.1 0.1 0.1 11.0 0.05\n"
       "O1 3 0.2 0.2 0.2 11.0 0.05\n"
       "HKLF 4\nEND\n")


# ---------------------------------------------------------------------------
class TestFinalHkl:
    def test_terminator_appended_when_the_data_end_at_eof(self, tmp_path):
        src = tmp_path / "v.hkl"
        src.write_bytes(ROWS.encode("ascii"))
        info = df.copy_hkl_for_handover(src, tmp_path / "final.hkl")
        out = (tmp_path / "final.hkl").read_bytes().decode("ascii")
        assert out == ROWS + TERM
        assert info["terminator_added"] is True
        assert info["n_reflections"] == 3 and info["trailer_lines"] == 0
        assert info["bytes"] == len(ROWS.encode("ascii"))
        assert info["source"] == str(src)

    def test_existing_terminator_and_sadabs_trailer_are_byte_preserved(self, tmp_path):
        src = tmp_path / "v.hkl"
        raw = (ROWS + TERM + TRAILER).encode("ascii")
        src.write_bytes(raw)
        info = df.copy_hkl_for_handover(src, tmp_path / "final.hkl")
        assert (tmp_path / "final.hkl").read_bytes() == raw
        assert info["terminator_added"] is False
        assert info["n_reflections"] == 3 and info["trailer_lines"] == 2

    def test_crlf_files_get_a_crlf_terminator(self, tmp_path):
        src = tmp_path / "v.hkl"
        src.write_bytes(ROWS.replace("\n", "\r\n").encode("ascii"))
        info = df.copy_hkl_for_handover(src, tmp_path / "final.hkl")
        out = (tmp_path / "final.hkl").read_bytes()
        assert out.endswith((TERM.rstrip("\n") + "\r\n").encode("ascii"))
        assert b"\n\n" not in out and info["terminator_added"]

    def test_missing_final_newline_does_not_glue_the_terminator(self, tmp_path):
        src = tmp_path / "v.hkl"
        src.write_bytes(ROWS.rstrip("\n").encode("ascii"))
        df.copy_hkl_for_handover(src, tmp_path / "final.hkl")
        lines = (tmp_path / "final.hkl").read_bytes().decode("ascii").splitlines()
        assert len(lines) == 4 and lines[-1] == TERM.rstrip("\n")


# ---------------------------------------------------------------------------
class TestFinalIns:
    def test_bare_res_gets_a_command_block_before_wght(self):
        text, info = df.restart_ins_text(RES, l_s=4)
        keys = [ln.split()[0] for ln in text.splitlines() if ln.strip()]
        assert "L.S." in keys and "ACTA" in keys
        assert keys.index("L.S.") < keys.index("WGHT")
        assert keys.index("L.S.") > keys.index("UNIT")
        assert any(c.startswith("L.S. 4") for c in info["inserted"])
        assert "ACTA" in info["inserted"]
        # atoms and cards are untouched
        assert "C1 1 0.1 0.1 0.1 11.0 0.05" in text
        assert all(len(ln) <= 80 for ln in text.splitlines())

    def test_deck_with_its_own_ls_is_returned_unchanged(self):
        deck = RES.replace("WGHT", "L.S. 10\nACTA\nWGHT", 1)
        text, info = df.restart_ins_text(deck)
        assert text == deck and info["inserted"] == []
        assert "L.S." in info["note"]

    def test_cgls_counts_as_a_command_block(self):
        deck = RES.replace("WGHT", "CGLS 20\nWGHT", 1)
        text, info = df.restart_ins_text(deck)
        assert text == deck and info["inserted"] == []


# ---------------------------------------------------------------------------
def _proj(tmp_path, context=None):
    return SimpleNamespace(dir=tmp_path, context=context or {})


class TestFinalP4p:
    def test_revision_source_copy_wins(self, tmp_path):
        rev = tmp_path / ".crystalpilot" / "refine" / "data" / "d000001"
        (rev / "sources").mkdir(parents=True)
        (rev / "observations.hkl").write_text(ROWS + TERM, encoding="ascii")
        (rev / "sources" / "a.p4p").write_text("CELL 10 11 12 90 90 90 1320\n",
                                               encoding="ascii")
        (rev / "sources" / "a.hkl").write_text(ROWS + TERM, encoding="ascii")
        (rev / "data.json").write_text(json.dumps({
            "schema": 1, "id": "d000001", "file": "observations.hkl",
            "sources": [{"file": "a.hkl", "source": "E:/vendor/a.hkl"},
                        {"file": "a.p4p", "source": "E:/vendor/a.p4p"}],
            "input_context": {"data": {"vendor_p4p": "a.p4p"}}}),
            encoding="utf-8")
        r = df.find_vendor_sidecar(_proj(tmp_path), {"data_revision": "d000001"})
        assert r["path"] == rev / "sources" / "a.p4p"
        assert "d000001" in r["source"] and "E:/vendor/a.p4p" in r["source"]

    def test_context_vendor_p4p_under_vendor_source(self, tmp_path):
        vendor = tmp_path / "vendor"
        vendor.mkdir()
        (vendor / "x.p4p").write_text("CELL\n", encoding="ascii")
        (vendor / "y.p4p").write_text("CELL\n", encoding="ascii")
        ctx = {"data": {"vendor_source": str(vendor), "vendor_p4p": "y.p4p"}}
        r = df.find_vendor_sidecar(_proj(tmp_path, ctx), {})
        assert r["path"] == vendor / "y.p4p"

    def test_single_p4p_in_vendor_dir_is_taken_several_are_not_guessed(self, tmp_path):
        vendor = tmp_path / "vendor"
        vendor.mkdir()
        (vendor / "x.p4p").write_text("CELL\n", encoding="ascii")
        ctx = {"data": {"vendor_source": str(vendor)}}
        r = df.find_vendor_sidecar(_proj(tmp_path, ctx), {})
        assert r["path"] == vendor / "x.p4p" and "only one" in r["source"]
        (vendor / "y.p4p").write_text("CELL\n", encoding="ascii")
        r2 = df.find_vendor_sidecar(_proj(tmp_path, ctx), {})
        assert r2["path"] is None and "not guessing" in r2["note"]

    def test_nothing_on_record_is_reported_not_fabricated(self, tmp_path):
        r = df.find_vendor_sidecar(_proj(tmp_path), {})
        assert r["path"] is None
        assert "cannot be derived from the model" in r["note"]


# ---------------------------------------------------------------------------
MODEL_CIF = ("data_n0005\n"
             "_cell_length_a 10.0\n"
             "_symmetry_space_group_name_H-M 'P -1'\n"
             "\nloop_\n  _atom_site_label\n  _atom_site_type_symbol\n"
             "  C1 C\n")


class TestModelCifStatistics:
    def test_rint_only_when_the_data_were_merged_here(self):
        merged = {"data": {"n_obs": 1200, "n_unique": 400, "r_int": 0.045,
                           "d_min": 0.80, "wavelength": 0.71073,
                           "completeness": 0.99}}
        lines = df.data_statistics_lines(merged)
        tags = [ln.split()[0] for ln in lines]
        assert "_diffrn_reflns_av_R_equivalents" in tags
        assert "_diffrn_reflns_theta_max" in tags
        assert any(ln.startswith("_refine_ls_d_res_high") and ln.endswith("0.800")
                   for ln in lines)
        premerged = {"data": {"n_obs": 400, "n_unique": 400, "r_int": 0.0,
                              "d_min": 0.80, "wavelength": 0.71073}}
        tags2 = [ln.split()[0] for ln in df.data_statistics_lines(premerged)]
        assert "_diffrn_reflns_av_R_equivalents" not in tags2
        assert "_diffrn_reflns_number" in tags2

    def test_enrich_uses_the_zero_cycle_numbers_and_is_idempotent(self):
        meta = {"id": "n0005", "metrics": {"r1_strong": 0.05, "label": "x"},
                "metrics_current": True,
                "data": {"n_obs": 1200, "n_unique": 400, "r_int": 0.045,
                         "d_min": 0.80, "wavelength": 0.71073}}
        zero = {"job": "job_z", "shelxl": {"r1_strong": 0.0512, "r1_all": 0.0700,
                                           "wr2": 0.1400, "goof": 1.02,
                                           "n_reflections": 400, "n_params": 100}}
        text, info = df.enrich_model_cif(MODEL_CIF, meta, zero)
        assert info["grade"] == "model"
        assert "job_z" in info["statistics_source"]
        assert "_refine_ls_R_factor_gt              0.0512" in text.replace("  ", " ") \
            or "_refine_ls_R_factor_gt" in text
        assert "_refine_ls_wR_factor_ref" in info["added"]
        assert "_diffrn_reflns_av_R_equivalents" in info["added"]
        # the block sits before the atom loop, the loop itself is intact
        assert text.index("_refine_ls_R_factor_gt") < text.index("_atom_site_label")
        assert text.count("loop_") == 1
        again, info2 = df.enrich_model_cif(text, meta, zero)
        assert again == text and info2["added"] == []
        # legal CIF
        import iotbx.cif
        block = next(iter(iotbx.cif.reader(input_string=text).model().values()))
        assert str(block["_refine_ls_R_factor_gt"]) == "0.0512"

    def test_without_measurement_the_note_says_so(self):
        meta = {"id": "n0005", "metrics": {}, "metrics_current": False, "data": {}}
        text, info = df.enrich_model_cif(MODEL_CIF, meta, None)
        assert text == MODEL_CIF and info["added"] == []
        assert "no measurement on record" in info["note"]
        assert "mode='adopt'" in info["note"]


# ---------------------------------------------------------------------------
def _zn_imine_structure():
    """Zn with a bound imine N (2.10 A) whose carbon sits 2.47 A from the
    metal - the test3-1 Zn02/N7/C21 geometry SHELXL's radius table lists as
    a Zn-C bond. Plus a second N that IS a bond. Synthetic, P1, 20 A box."""
    from cctbx import crystal, xray
    from cctbx.array_family import flex
    cs = crystal.symmetry(unit_cell=(20, 20, 20, 90, 90, 90), space_group_symbol="P 1")
    xs = xray.structure(crystal_symmetry=cs)
    atoms = [("Zn1", "Zn", (0.0, 0.0, 0.0)),
             ("N1", "N", (2.10, 0.0, 0.0)),
             ("C1", "C", (2.10, 1.30, 0.0)),      # N1-C1 1.30, Zn1...C1 2.47
             ("C2", "C", (2.10 + 1.40, 1.30, 0.0)),  # C1-C2 1.40
             ("N2", "N", (0.0, 0.0, 2.05))]
    for label, el, xyz in atoms:
        site = tuple(c / 20.0 for c in xyz)
        xs.add_scatterer(xray.scatterer(label=label, scattering_type=el, site=site,
                                        u=0.03))
    return xs


BOND_CIF = ("data_x\nloop_\n _geom_bond_atom_site_label_1\n _geom_bond_atom_site_label_2\n"
            " _geom_bond_distance\n _geom_bond_site_symmetry_2\n _geom_bond_publ_flag\n"
            "Zn1 N1 2.100(2) . ?\n"
            "Zn1 N2 2.050(2) . ?\n"
            "Zn1 C1 2.470(3) . ?\n"
            "N1 C1 1.300(3) . ?\n"
            "C1 C2 1.400(3) . ?\n"
            "\nloop_\n _atom_site_label\n Zn1\n")


class TestGeomBondAudit:
    def test_metal_carbon_row_the_model_does_not_bond_is_flagged(self):
        r = df.geom_bond_audit(BOND_CIF, _zn_imine_structure())
        assert r["checked"] and r["n_rows"] == 5
        pairs = {(s["a"], s["b"]) for s in r["suspects"]}
        assert pairs == {("Zn1", "C1")}, r
        s = r["suspects"][0]
        assert s["free_card"] == "FREE Zn1 C1" and s["distance"] == 2.47
        assert "not bonded" in s["verdict"] or "non_bonded" in s["verdict"]
        assert "run_shelxl(mode='adopt'" in r["note"]

    def test_no_loop_or_no_model_is_not_a_verdict(self):
        r = df.geom_bond_audit("data_x\n_cell_length_a 10\n", _zn_imine_structure())
        assert r["checked"] is False and r["suspects"] == []
        r2 = df.geom_bond_audit(BOND_CIF, None)
        assert r2["checked"] is False

    def test_real_delivery_flags_the_zn02_c21_row(self):
        """The delivered test3-1 CIF (user's own record, read only)."""
        base = Path("H:/CrystalPilot-campaigns/usertest/test3-1-0908")
        cif = (base / "CrystalPilot Results"
               / "task_20260908_160046-hydrogenated-squeeze-ACTA" / "final.cif")
        res = base / ".crystalpilot" / "refine" / "nodes" / "n0100" / "model.res"
        if not (cif.exists() and res.exists()):
            pytest.skip("usertest test3-1 record not on this machine")
        from crystalpilot.io.shelx_model import load_res_model
        xs = load_res_model(res).structure
        r = df.geom_bond_audit(cif.read_text(encoding="utf-8", errors="replace"), xs)
        assert r["checked"]
        assert [(s["a"], s["b"], s["distance"]) for s in r["suspects"]] == \
            [("Zn02", "C21", 2.52)]
        assert r["suspects"][0]["free_card"] == "FREE Zn02 C21"


# ---------------------------------------------------------------------------
class TestManualContinuation:
    def test_five_files_present_is_ready(self, tmp_path):
        for f in df.MANUAL_FILES:
            (tmp_path / f).write_text("x", encoding="ascii")
        r = df.manual_continuation(tmp_path, {}, masked=False)
        assert r["ready"] and r["missing"] == []
        assert r["files"] == list(df.MANUAL_FILES)

    def test_missing_p4p_never_blocks_but_is_explained(self, tmp_path):
        for f in ("final.res", "final.cif", "final.ins", "final.hkl"):
            (tmp_path / f).write_text("x", encoding="ascii")
        prov = {"final.p4p": {"absent": True, "note": "no .p4p on record: ..."},
                "final.hkl": {"terminator_added": True}}
        r = df.manual_continuation(tmp_path, prov, masked=False)
        assert r["ready"] and r["missing"] == ["final.p4p"]
        assert any(n.startswith("final.p4p: no .p4p on record") for n in r["notes"])
        assert any("terminator row appended" in n for n in r["notes"])

    def test_masked_model_needs_final_fab(self, tmp_path):
        for f in df.MANUAL_FILES:
            (tmp_path / f).write_text("x", encoding="ascii")
        r = df.manual_continuation(tmp_path, {}, masked=True)
        assert not r["ready"] and r["missing"] == ["final.fab"]
        (tmp_path / "final.fab").write_text("x", encoding="ascii")
        r2 = df.manual_continuation(tmp_path, {}, masked=True)
        assert r2["ready"] and any("ABIN" in n for n in r2["notes"])
