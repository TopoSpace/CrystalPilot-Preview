"""pa1 fix list P1-9: ingest_vendor_data candidate statistics table,
'-' cell from any .ins, same-file guard, symmetry provenance record.

Evidence (workdir/campaigns/PA1-FINAL-ANALYSIS.md section 4.4 and
pa1-deepdive/tool-usability.md section 4): six cu runs got 'several hkl
candidates' with nothing but 'HKLF4-like' per file and went to the shell
to compare crystal_a/b/c (cu-l3-r1 hung 15 min); four runs asked for an
atomless start (ins='-') and were told 'no .p4p with a cell' while
start.ins carried it; hex-l2-r2 re-ingested the project directory itself
and hit WinError 32 on its own open crystal.hkl.
"""
from __future__ import annotations

import json
import random
from pathlib import Path
from types import SimpleNamespace

import pytest

from crystalpilot.refine import tools_frames as tf

CELL = (10.669, 28.8515, 31.1309, 90.0, 90.0, 90.0)


def _rows(noise: float, n_per: int = 3, seed: int = 0,
          d_min: float = 2.5) -> list[str]:
    """Synthetic unmerged HKLF4 rows: the C-centred half of a P1 set to
    d_min, each reflection n_per times with a seeded relative jitter -
    so merging has duplicates and R_int scales with `noise`."""
    from cctbx import crystal, miller
    rng = random.Random(seed)
    cs = crystal.symmetry(unit_cell=CELL, space_group_symbol="P 1")
    ms = miller.build_set(cs, anomalous_flag=False, d_min=d_min)
    out = []
    for h, k, l in ms.indices():
        if (h + k) % 2:                       # C-centring parity
            continue
        base = 100.0 * (1 + (abs(h) + abs(k) + abs(l)) % 5)
        for _ in range(n_per):
            i = base * (1 + rng.gauss(0.0, noise))
            out.append(f"{h:4d}{k:4d}{l:4d}{i:8.2f}{0.05 * base:8.2f}\n")
    return out


TERMINATOR = "   0   0   0    0.00    0.00\n"
START_INS = ("TITL cold start (indexing cell, symmetry undetermined)\n"
             "CELL 1.54178 10.6690 28.8515 31.1309 90 90 90\n"
             "ZERR 4 0.0005 0.0009 0.0009 0 0 0\n"
             "LATT -1\nSFAC C H N O\nUNIT 4 4 4 4\nHKLF 4\nEND\n")


class _Proj:
    def __init__(self, d: Path):
        self.dir = d
        d.mkdir(exist_ok=True)
        self.context: dict = {}

    def reload_inputs(self):
        return {"node": "n0001", "n_atoms": 0, "merge": {}}


def _ctx():
    return SimpleNamespace(session=None)


def _cu_like_dir(tmp_path: Path) -> Path:
    """Three hkl candidates + one shared start.ins, no .p4p - the r22a
    /staging layout the pa1 cu agents faced. b and c carry the same
    reflection rows and differ only in the trailer."""
    src = tmp_path / "vendor"
    src.mkdir()
    (src / "a.hkl").write_text("".join(_rows(0.03)) + TERMINATOR,
                               encoding="ascii")
    b_rows = "".join(_rows(0.30, seed=1)) + TERMINATOR
    (src / "b.hkl").write_text(b_rows + "\n_computing_structure_solution "
                               "'SHELXT 2018/2'\n", encoding="ascii")
    (src / "c.hkl").write_text(b_rows + "\n\n_computing_structure_solution "
                               "'SHELXT 2018/2 (Sheldrick, 2018)'\n",
                               encoding="ascii")
    (src / "start.ins").write_text(START_INS, encoding="ascii")
    return src


class TestCandidateStats:
    def test_stats_carry_the_numbers_a_crystallographer_picks_on(self,
                                                                  tmp_path):
        src = _cu_like_dir(tmp_path)
        a = tf.hkl_candidate_stats(src / "a.hkl", CELL)
        b = tf.hkl_candidate_stats(src / "b.hkl", CELL)
        for st in (a, b):
            assert "error" not in st, st
            for key in ("n_reflections", "n_unique", "multiplicity",
                        "completeness", "r_int", "r_sigma", "i_over_sigma",
                        "d_max", "d_min", "merge_group", "outer_shell",
                        "looks_merged"):
                assert key in st, key
        assert a["n_reflections"] == len(_rows(0.03))
        # C-centring inferred from parity, merged in the metric Laue class
        assert a["centring_inferred"] == "C"
        assert a["merge_group"].startswith("C m m m")
        assert "lattice metric" in a["merge_group_source"]
        assert 0.0 < a["completeness"] <= 1.0
        assert a["multiplicity"] > 2.5 and not a["looks_merged"]
        # the noisy reduction has the worse R_int - the cu a-vs-b/c call
        assert a["r_int"] < 0.08 < b["r_int"]
        assert a["r_sigma"] < b["r_sigma"] or a["r_sigma"] == b["r_sigma"]
        outer = a["outer_shell"]
        assert outer["d_min"] <= a["d_min"] + 1e-6
        assert outer["n_unique"] < a["n_unique"]
        assert outer["i_over_sigma"] is not None

    def test_declared_group_drives_the_merge_class(self, tmp_path):
        from cctbx import sgtbx
        src = _cu_like_dir(tmp_path)
        g = sgtbx.space_group_info("P 1 21/c 1").group()
        st = tf.hkl_candidate_stats(src / "a.hkl", CELL, space_group=g)
        # 2/m keeps fewer duplicates merged than mmm: more uniques
        st_mmm = tf.hkl_candidate_stats(src / "a.hkl", CELL)
        assert st["merge_group_source"] == "declared LATT/SYMM"
        assert st["n_unique"] > st_mmm["n_unique"]

    def test_merged_file_is_flagged(self, tmp_path):
        # Friedel/P1-merged: no index repeats, yet mmm still finds ~4
        # equivalents per unique - R_int measures Laue consistency only
        p = tmp_path / "m.hkl"
        p.write_text("".join(_rows(0.0, n_per=1)) + TERMINATOR,
                     encoding="ascii")
        st = tf.hkl_candidate_stats(p, CELL)
        assert st["looks_merged"] is True
        assert st["p1_multiplicity"] == 1.0 and st["multiplicity"] > 2
        assert "Laue-class consistency" in st["merged_note"]
        # merged in the Laue class itself: one row per mmm unique
        from cctbx import crystal, miller
        cs = crystal.symmetry(unit_cell=CELL, space_group_symbol="C m m m")
        ms = miller.build_set(cs, anomalous_flag=False, d_min=2.5)
        q = tmp_path / "laue.hkl"
        q.write_text("".join(f"{h:4d}{k:4d}{l:4d}{100.0:8.2f}{5.0:8.2f}\n"
                             for h, k, l in ms.indices()) + TERMINATOR,
                     encoding="ascii")
        st2 = tf.hkl_candidate_stats(q, CELL)
        assert st2["looks_merged"] is True and st2["multiplicity"] < 1.2
        assert "carries no information" in st2["merged_note"]
        # unmerged data are not flagged
        assert tf.hkl_candidate_stats(
            _cu_like_dir(tmp_path) / "a.hkl", CELL)["looks_merged"] is False

    def test_hashes_separate_trailer_from_data(self, tmp_path):
        src = _cu_like_dir(tmp_path)
        hb, hc, ha = (tf.hkl_file_hashes(src / n)
                      for n in ("b.hkl", "c.hkl", "a.hkl"))
        assert hb["sha256"] != hc["sha256"]
        assert hb["data_sha256"] == hc["data_sha256"]
        assert ha["data_sha256"] != hb["data_sha256"]
        assert hb["n_rows"] == len(_rows(0.30, seed=1))

    def test_unreadable_file_reports_instead_of_raising(self, tmp_path):
        p = tmp_path / "junk.hkl"
        p.write_text("not reflections\n" * 5, encoding="ascii")
        st = tf.hkl_candidate_stats(p, CELL)
        assert "error" in st

    def test_hklf5_candidate_counts_composite_rows_once(self, tmp_path):
        """HKLF5 twin export among the candidates: negative-batch component
        rows are not observations of their own (load_shelx_dataset
        convention) and the table must say the numbers are approximate."""
        def line(h, k, l, b):
            return f"{h:4d}{k:4d}{l:4d}{100.0:8.2f}{5.0:8.2f}{b:4d}\n"
        rows = [line(1, 1, i % 9, 1) for i in range(40)]
        for i in range(12):
            rows.append(line(2, 1, i % 7, -2))
            rows.append(line(2, 1, i % 7, 1))
        p = tmp_path / "twin.hkl"
        p.write_text("".join(rows) + TERMINATOR, encoding="ascii")
        st = tf.hkl_candidate_stats(p, (10, 11, 12, 90, 90, 90))
        assert "error" not in st
        assert st["n_reflections"] == 64          # 76 rows - 12 components
        assert "12 negative-batch" in st["hklf5_note"]
        assert st["n_unique"] and st["merge_group"].startswith("P m m m")


class TestIngestCandidateTable:
    def test_several_candidates_answer_with_the_table(self, tmp_path):
        src = _cu_like_dir(tmp_path)
        proj = _Proj(tmp_path / "proj")
        r = tf.IngestVendorData(proj).run(_ctx(), source_dir=str(src))
        assert not r.ok
        # the error names every file with its headline numbers
        for name in ("a.hkl", "b.hkl", "c.hkl"):
            assert name in r.error
        assert "Rint" in r.error and "same reflections as" in r.error
        table = r.summary["candidate_table"]
        assert table["b.hkl"]["same_reflections_as"] == ["c.hkl"]
        assert table["c.hkl"]["same_reflections_as"] == ["b.hkl"]
        assert "identical_file_to" not in table["b.hkl"]
        assert (table["a.hkl"]["stats"]["r_int"]
                < table["b.hkl"]["stats"]["r_int"])
        # cell came from the one shared ins; its group is a GUESS
        assert table["a.hkl"]["cell_source"] == \
            "ins start.ins (shared, not stem-paired)"
        assert table["a.hkl"]["cell"][1] == 28.8515
        assert table["a.hkl"]["space_group_guess"].startswith("P 1 (")
        assert "unverified" in table["a.hkl"]["space_group_guess"]
        assert table["a.hkl"]["format"] == "HKLF4-like"
        # nothing was copied by a refused call
        assert not (proj.dir / "crystal.hkl").exists()

    def test_list_candidates_only_lists(self, tmp_path):
        src = _cu_like_dir(tmp_path)
        proj = _Proj(tmp_path / "proj")
        r = tf.IngestVendorData(proj).run(_ctx(), source_dir=str(src),
                                          list_candidates=True)
        assert r.ok, r.error
        assert r.summary["no_state_change"] is True
        assert set(r.summary["candidate_table"]) == {"a.hkl", "b.hkl",
                                                     "c.hkl"}
        assert not (proj.dir / "crystal.hkl").exists()
        assert not (proj.dir / "start.ins").exists()

    def test_single_candidate_lists_on_request(self, tmp_path):
        src = tmp_path / "vendor"
        src.mkdir()
        (src / "only.hkl").write_text("".join(_rows(0.03)) + TERMINATOR,
                                      encoding="ascii")
        (src / "only.ins").write_text(START_INS, encoding="ascii")
        proj = _Proj(tmp_path / "proj")
        r = tf.IngestVendorData(proj).run(_ctx(), source_dir=str(src),
                                          list_candidates=True)
        assert r.ok, r.error
        assert r.summary["candidate_table"]["only.hkl"]["cell_source"] == \
            "ins only.ins"

    def test_dash_ins_takes_cell_and_wavelength_from_any_ins(self, tmp_path):
        src = _cu_like_dir(tmp_path)
        proj = _Proj(tmp_path / "proj")
        r = tf.IngestVendorData(proj).run(_ctx(), source_dir=str(src),
                                          hkl="a.hkl", ins="-")
        assert r.ok, r.error
        ins = (proj.dir / "start.ins").read_text(encoding="ascii")
        assert "CELL 1.54178 10.66900 28.85150 31.13090" in ins
        assert "LATT 1\n" in ins                 # placeholder, not P1 of the ins
        assert "ZERR 1.00 0.00050 0.00090 0.00090" in ins
        cs = r.summary["cell_source"]
        assert cs["from"] == "ins start.ins"
        assert cs["wavelength"] == 1.54178
        assert cs["wavelength_from"] == "ins start.ins"
        assert cs["space_group_guess"] == "P 1"
        # the success summary still carries the comparison table
        assert "candidate_table" in r.summary
        assert r.summary["chosen"]["hkl"] == "a.hkl"
        ctx = json.loads((proj.dir / "context.json").read_text("utf-8"))
        sym = ctx["symmetry"]
        assert sym["space_group"] == "P -1"
        assert sym["confirmed"] is False
        assert sym["ins_guess"]["space_group"] == "P 1"
        assert sym["ins_guess"]["file"] == "start.ins"
        assert "placeholder" in sym["source"]
        assert ctx["data"]["vendor_hkl_bytes"] == (src / "a.hkl").stat().st_size
        assert (proj.dir / "crystal.hkl").read_bytes() == (src / "a.hkl").read_bytes()
        assert r.summary["symmetry"]["space_group"] == "P -1"

    def test_p4p_still_wins_the_cell_for_a_dash_start(self, tmp_path):
        src = _cu_like_dir(tmp_path)
        (src / "a.p4p").write_text(
            "CELL 10.6700 28.8500 31.1300 90.0 90.0 90.0 9583.0\n"
            "CELLSD 0.002 0.003 0.003 0.0 0.0 0.0 1.0\n"
            "SOURCE CU 1.54184 1.54056\n", encoding="ascii")
        proj = _Proj(tmp_path / "proj")
        r = tf.IngestVendorData(proj).run(_ctx(), source_dir=str(src),
                                          hkl="a.hkl", ins="-")
        assert r.ok, r.error
        assert r.summary["cell_source"]["from"] == "p4p a.p4p"
        assert r.summary["cell_source"]["wavelength"] == 1.54184
        assert "space_group_guess" not in r.summary["cell_source"]

    def test_vendor_sidecars_are_captured_and_named_for_the_handover(
            self, tmp_path):
        """usertest test3-1 (2026-09-08): the .p4p the group hands over
        with the structure had to be fetched from the vendor directory by
        guessing its name. Ingest now records which p4p/ls/abs belong to
        the chosen hkl (stem pair, else the cell source, else the only
        one) and freezes a copy beside the hkl."""
        src = _cu_like_dir(tmp_path)
        p4p = ("CELL 10.6700 28.8500 31.1300 90.0 90.0 90.0 9583.0\n"
               "CELLSD 0.002 0.003 0.003 0.0 0.0 0.0 1.0\n"
               "SOURCE CU 1.54184 1.54056\n")
        (src / "a.p4p").write_text(p4p, encoding="ascii")
        (src / "other.p4p").write_text(p4p, encoding="ascii")
        proj = _Proj(tmp_path / "proj")
        r = tf.IngestVendorData(proj).run(_ctx(), source_dir=str(src),
                                          hkl="a.hkl", ins="-")
        assert r.ok, r.error
        ctx = json.loads((proj.dir / "context.json").read_text("utf-8"))
        assert ctx["data"]["vendor_p4p"] == "a.p4p"        # stem pair, not other.p4p
        assert ctx["data"]["vendor_abs"] is None            # none parsed
        assert ctx["data"]["vendor_source"] == str(src)
        # a project without a data-revision stage: capture_source copies
        # the sidecar into the project so a later delivery can find it
        from crystalpilot.refine.deliver_files import find_vendor_sidecar
        proj.context = ctx
        found = find_vendor_sidecar(proj, {}, ".p4p")
        assert found["path"] is not None
        assert found["path"].read_text(encoding="ascii") == p4p

    def test_dash_ins_without_any_cell_source_lists_what_was_tried(
            self, tmp_path):
        src = tmp_path / "vendor"
        src.mkdir()
        (src / "a.hkl").write_text("".join(_rows(0.03)) + TERMINATOR,
                                   encoding="ascii")
        proj = _Proj(tmp_path / "proj")
        r = tf.IngestVendorData(proj).run(_ctx(), source_dir=str(src),
                                          ins="-")
        assert not r.ok
        assert ".p4p: 0 found" in r.error
        assert ".ins/.res: 0 found" in r.error
        assert "cell=[a, b, c, alpha, beta, gamma]" in r.error
        assert not (proj.dir / "crystal.hkl").exists()   # nothing half-done
        r2 = tf.IngestVendorData(proj).run(
            _ctx(), source_dir=str(src), ins="-", cell=list(CELL),
            wavelength=0.71073)
        assert r2.ok, r2.error
        assert r2.summary["cell_source"]["from"] == "explicit cell= parameter"
        assert r2.summary["cell_source"]["wavelength_from"] == \
            "wavelength= parameter"
        ins = (proj.dir / "start.ins").read_text(encoding="ascii")
        assert "CELL 0.71073 10.66900 28.85150 31.13090" in ins

    def test_bad_explicit_cell_is_refused(self, tmp_path):
        src = _cu_like_dir(tmp_path)
        proj = _Proj(tmp_path / "proj")
        r = tf.IngestVendorData(proj).run(_ctx(), source_dir=str(src),
                                          hkl="a.hkl", ins="-",
                                          cell=[1, 2, 3])
        assert not r.ok and "cell must be" in r.error

    def test_assumed_wavelength_is_disclosed(self, tmp_path):
        src = tmp_path / "vendor"
        src.mkdir()
        (src / "a.hkl").write_text("".join(_rows(0.03)) + TERMINATOR,
                                   encoding="ascii")
        proj = _Proj(tmp_path / "proj")
        r = tf.IngestVendorData(proj).run(_ctx(), source_dir=str(src),
                                          ins="-", cell=list(CELL))
        assert r.ok, r.error
        assert "ASSUMED" in r.summary["cell_source"]["wavelength_from"]


class TestSameFileGuard:
    @staticmethod
    def _ingested(tmp_path):
        src = tmp_path / "vendor"
        src.mkdir()
        (src / "a.hkl").write_text("".join(_rows(0.03)) + TERMINATOR,
                                   encoding="ascii")
        (src / "start.ins").write_text(START_INS, encoding="ascii")
        proj = _Proj(tmp_path / "proj")
        r = tf.IngestVendorData(proj).run(_ctx(), source_dir=str(src),
                                          ins="-")
        assert r.ok, r.error
        return src, proj

    def test_project_dir_as_source_is_refused_with_reset_guidance(
            self, tmp_path):
        """hex-l2-r2: source_dir=<project> to drop placeholder atoms ->
        crystal.hkl copied onto its open self -> WinError 32."""
        _src, proj = self._ingested(tmp_path)
        r = tf.IngestVendorData(proj).run(_ctx(), source_dir=str(proj.dir))
        assert not r.ok
        assert "project's own crystal.hkl" in r.error
        assert "checkout n0000" in r.error
        assert "change_space_group" in r.error

    def test_identical_bytes_under_another_name_are_refused(self, tmp_path):
        src, proj = self._ingested(tmp_path)
        other = tmp_path / "again"
        other.mkdir()
        (other / "renamed.hkl").write_bytes((src / "a.hkl").read_bytes())
        r = tf.IngestVendorData(proj).run(_ctx(), source_dir=str(other),
                                          ins="-", cell=list(CELL))
        assert not r.ok
        assert "byte-identical" in r.error
        assert "ingested from a.hkl" in r.error
        assert "force=true" in r.error
        # force re-imports (rebuilds the start node from the same data)
        r2 = tf.IngestVendorData(proj).run(_ctx(), source_dir=str(other),
                                           ins="-", cell=list(CELL),
                                           force=True)
        assert r2.ok, r2.error
        assert r2.summary["chosen"]["hkl"] == "renamed.hkl"

    def test_same_rows_different_trailer_are_refused(self, tmp_path):
        src, proj = self._ingested(tmp_path)
        other = tmp_path / "again"
        other.mkdir()
        (other / "trailer.hkl").write_bytes(
            (src / "a.hkl").read_bytes() + b"\n_exptl_absorpt_correction_"
            b"type multi-scan\n")
        r = tf.IngestVendorData(proj).run(_ctx(), source_dir=str(other),
                                          ins="-", cell=list(CELL))
        assert not r.ok
        assert "same reflection rows" in r.error

    def test_different_data_is_ingested_normally(self, tmp_path):
        _src, proj = self._ingested(tmp_path)
        other = tmp_path / "again"
        other.mkdir()
        (other / "b.hkl").write_text("".join(_rows(0.30, seed=1))
                                     + TERMINATOR, encoding="ascii")
        r = tf.IngestVendorData(proj).run(_ctx(), source_dir=str(other),
                                          ins="-", cell=list(CELL))
        assert r.ok, r.error


class TestSymmetryProvenance:
    def test_vendor_ins_start_records_its_group_as_unverified(self,
                                                              tmp_path):
        src = tmp_path / "vendor"
        src.mkdir()
        (src / "a.hkl").write_text("".join(_rows(0.03)) + TERMINATOR,
                                   encoding="ascii")
        (src / "a.ins").write_text(
            "TITL vendor solution\nCELL 0.71073 10.669 28.8515 31.1309 "
            "90 90 90\nZERR 4 0 0 0 0 0 0\nLATT 1\nSYMM -X, Y+1/2, -Z+1/2\n"
            "SFAC C H N O\nUNIT 4 4 4 4\nHKLF 4\nEND\n", encoding="ascii")
        proj = _Proj(tmp_path / "proj")
        r = tf.IngestVendorData(proj).run(_ctx(), source_dir=str(src))
        assert r.ok, r.error
        ctx = json.loads((proj.dir / "context.json").read_text("utf-8"))
        sym = ctx["symmetry"]
        assert sym["space_group"] == "P 1 21/c 1"
        assert "a.ins" in sym["source"] and "unverified" in sym["source"]
        assert sym["confirmed"] is False
        assert sym["ins_guess"] is None
        assert r.summary["symmetry"]["space_group"] == "P 1 21/c 1"

    def test_reingest_replaces_the_whole_block(self, tmp_path):
        """context.json is deep-merged: a stale ins_guess from an earlier
        '-' ingest must not survive a later vendor-ins ingest."""
        src = _cu_like_dir(tmp_path)
        proj = _Proj(tmp_path / "proj")
        r = tf.IngestVendorData(proj).run(_ctx(), source_dir=str(src),
                                          hkl="a.hkl", ins="-")
        assert r.ok, r.error
        (src / "b.ins").write_text(START_INS.replace("LATT -1", "LATT 1"),
                                   encoding="ascii")
        r2 = tf.IngestVendorData(proj).run(_ctx(), source_dir=str(src),
                                           hkl="b.hkl", ins="b.ins")
        assert r2.ok, r2.error
        sym = json.loads((proj.dir / "context.json").read_text("utf-8"))[
            "symmetry"]
        assert sym["space_group"] == "P -1"
        assert sym["ins_guess"] is None
        assert "b.ins" in sym["source"]

    def test_ins_cell_metadata(self, tmp_path):
        p = tmp_path / "x.ins"
        p.write_text(START_INS, encoding="ascii")
        m = tf.ins_cell_metadata(p)
        assert m["cell"][2] == 31.1309 and m["wavelength"] == 1.54178
        assert m["cell_esd"] == [0.0005, 0.0009, 0.0009, 0, 0, 0]
        assert m["space_group_symbol"] == "P 1"
        (tmp_path / "nocell.ins").write_text("TITL nothing\nEND\n",
                                             encoding="ascii")
        assert tf.ins_cell_metadata(tmp_path / "nocell.ins") is None


@pytest.mark.skipif(
    not Path("H:/CrystalPilotData/staging/r22a/crystal_c.hkl").exists(),
    reason="r22a staging data absent")
def test_r22a_candidates_are_told_apart():
    """The live cu case: a is the cleaner reduction, b and c are one
    dataset under two names (71 bytes of trailer apart)."""
    src = Path("H:/CrystalPilotData/staging/r22a")
    hkls = {p.name: {**tf.looks_like_shelx_hkl(p), "format": "HKLF4-like"}
            for p in sorted(src.glob("*.hkl"))}
    table = tf.build_candidate_table(src, hkls, ["start.ins"], {}, {})
    assert table["crystal_b.hkl"]["same_reflections_as"] == ["crystal_c.hkl"]
    assert (table["crystal_a.hkl"]["stats"]["r_int"]
            < table["crystal_b.hkl"]["stats"]["r_int"])
    assert table["crystal_a.hkl"]["stats"]["centring_inferred"] == "C"
