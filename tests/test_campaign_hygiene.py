"""Staging hygiene: answer material must not sit in the agent-visible
data dir (2026-09 survey finding).

The staging trees are assembled by hand and answers live one directory
away from blind data more often than is comfortable - the E-drive survey
found solved CIFs for three blind crystals in a sibling folder, and
benchmark/data ships a SHELXT solution as `ins.ins` (194 atoms, space
group in the header). A leak does not fail a campaign, it silently
invalidates the score, so the runner refuses before the brief goes out.
"""
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def _case(tmp_path, **kw):
    from crystalpilot.benchmark.agent_campaign import CaseRun
    c = object.__new__(CaseRun)
    c.name = "t"
    c.case = {"data_dir": str(tmp_path), **kw}
    return c


def _res(n_atoms: int) -> str:
    head = ("TITL solved\nCELL 0.71073 10 10 10 90 90 90\n"
            "ZERR 1 0 0 0 0 0 0\nLATT -1\nSFAC C\nUNIT 1\n")
    atoms = "".join(
        f"C{i}    1  0.10{i:04d}  0.20000  0.30000  11.00000  0.02000\n"
        for i in range(n_atoms))
    return head + atoms + "HKLF 4\nEND\n"


class TestAnswerDetection:
    def test_solved_res_is_caught(self, tmp_path):
        (tmp_path / "work.res").write_text(_res(30), encoding="utf-8")
        leaks = _case(tmp_path).check_staging_hygiene()
        assert leaks and "30 atom records" in leaks[0]

    def test_cif_with_coordinates_is_caught(self, tmp_path):
        (tmp_path / "answer.cif").write_text(
            "data_x\nloop_\n_atom_site_label\n_atom_site_fract_x\n"
            "C1 0.1\n", encoding="utf-8")
        leaks = _case(tmp_path).check_staging_hygiene()
        assert leaks and "refined coordinates" in leaks[0]

    def test_nested_directories_are_scanned(self, tmp_path):
        d = tmp_path / "work" / "deep"
        d.mkdir(parents=True)
        (d / "a.res").write_text(_res(12), encoding="utf-8")
        assert _case(tmp_path).check_staging_hygiene()

    def test_atomless_bootstrap_ins_is_clean(self, tmp_path):
        # what ingest_vendor_data generates: cell + SFAC + TREF, no atoms
        (tmp_path / "start.ins").write_text(
            "TITL start\nCELL 0.71073 10 10 10 90 90 90\n"
            "ZERR 1 0 0 0 0 0 0\nLATT -1\nSFAC C O ZN\nUNIT 40 20 4\n"
            "TREF\nHKLF 4\nEND\n", encoding="utf-8")
        assert _case(tmp_path).check_staging_hygiene() == []

    def test_hkl_and_par_files_are_clean(self, tmp_path):
        (tmp_path / "crystal.hkl").write_text(
            "   1   0   0  100.00    2.00\n" * 50, encoding="utf-8")
        (tmp_path / "exp.par").write_text("whatever\n", encoding="utf-8")
        assert _case(tmp_path).check_staging_hygiene() == []

    def test_a_handful_of_atom_like_lines_does_not_trip_it(self, tmp_path):
        # 4 records: below the threshold, so a stray fragment in a header
        # does not block a legitimate campaign
        (tmp_path / "x.ins").write_text(_res(4), encoding="utf-8")
        assert _case(tmp_path).check_staging_hygiene() == []

    def test_deliberate_known_model_case_can_opt_out(self, tmp_path):
        (tmp_path / "work.res").write_text(_res(30), encoding="utf-8")
        c = _case(tmp_path, allow_answers_in_data=True)
        assert c.check_staging_hygiene() == []

    def test_alias_target_is_what_gets_scanned(self, tmp_path):
        """data_alias hides the real path from the agent; the check must
        follow the TARGET, not the (possibly absent) junction."""
        target = tmp_path / "real"
        target.mkdir()
        (target / "answer.res").write_text(_res(20), encoding="utf-8")
        from crystalpilot.benchmark.agent_campaign import CaseRun
        c = object.__new__(CaseRun)
        c.name = "t"
        c.case = {"data_alias": {"link": str(tmp_path / "neutral"),
                                 "target": str(target)}}
        assert c.check_staging_hygiene()


STAGING = Path("H:/CrystalPilotData/staging")


@pytest.mark.skipif(not STAGING.exists(), reason="staging not present")
class TestHistoricalStagingIsClean:
    """Regression: every staging dir a real campaign has used must pass,
    or the check is too aggressive to be worth having."""

    @pytest.mark.parametrize("name", ["r15a", "r19a", "r21a", "r22a"])
    def test_campaign_staging_passes(self, name):
        d = STAGING / name
        if not d.exists():
            pytest.skip(f"{name} not staged")
        leaks = _case(d).check_staging_hygiene()
        assert leaks == [], f"{name}: {leaks}"


class TestReferenceCaveats:
    """Not every 'ground truth' is one. r25 graded a correct structure
    below_bar against a reference that was an unfinished SHELXT solution
    with the wrong element and the wrong space group - and the reference
    file said so itself, in its own REM lines."""

    def _ref(self, tmp_path, rems: str) -> "Path":
        p = tmp_path / "ref_res.res"
        p.write_text(f"TITL x\n{rems}\n"
                     "CELL 0.71073 10 10 10 90 90 90\nLATT -1\n"
                     "SFAC C\nUNIT 1\nHKLF 4\nEND\n", encoding="utf-8")
        return p

    def test_hand_written_caveat_wins(self, tmp_path):
        from crystalpilot.benchmark.grade import _reference_caveat
        ref = self._ref(tmp_path, "REM R1 = 0.0400")
        (tmp_path / "REFERENCE-CAVEAT.md").write_text(
            "# note\n\nthis reference has the wrong space group\n",
            encoding="utf-8")
        c = _reference_caveat(ref)
        assert c is not None and "wrong space group" in c
        assert "REFERENCE-CAVEAT.md" in c

    def test_high_r1_is_self_declared(self, tmp_path):
        from crystalpilot.benchmark.grade import _reference_caveat
        c = _reference_caveat(self._ref(tmp_path, "REM R1 = 0.2090"))
        assert c is not None and "0.2090" in c

    def test_shelxt_raw_solution_flagged(self, tmp_path):
        from crystalpilot.benchmark.grade import _reference_caveat
        c = _reference_caveat(self._ref(
            tmp_path, "REM SHELXT solution in P6mm: R1 0.407"))
        assert c is not None and "SHELXT" in c

    def test_flack_half_flags_the_space_group(self, tmp_path):
        from crystalpilot.benchmark.grade import _reference_caveat
        c = _reference_caveat(self._ref(
            tmp_path, "REM Flack x = 0.496 ( 0.030 ) from 1039 quotients"))
        assert c is not None and "中心对称" in c

    def test_a_finished_reference_is_quiet(self, tmp_path):
        from crystalpilot.benchmark.grade import _reference_caveat
        ref = self._ref(tmp_path,
                        "REM R1 = 0.0412\nREM Flack x = 0.02 ( 0.01 )")
        assert _reference_caveat(ref) is None

    def test_cif_reference_without_a_caveat_file_is_quiet(self, tmp_path):
        from crystalpilot.benchmark.grade import _reference_caveat
        p = tmp_path / "ref.cif"
        p.write_text("data_x\n_cell_length_a 10\n", encoding="utf-8")
        assert _reference_caveat(p) is None
