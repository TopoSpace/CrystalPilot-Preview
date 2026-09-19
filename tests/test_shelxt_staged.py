"""run_shelxt: stage-aware budget, truthful timeout messages, -s and from_job.

pa1 batch: 16/49 SHELXT calls timed out; 7 of those were reported as
"before writing any progress" while job.lxt held 7.5-9 KB of tries (a regex
that allowed ONE space where SHELXT writes two for single-digit Laue
numbers), and 5 were killed in the space-group search after phasing had
finished (37-574 s of finished work discarded, then re-run from scratch).
"""
from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

from crystalpilot.refine.tools_shelxl import (RunShelxt, shelxt_accept_bar,
                                              shelxt_space_group_name)

# verbatim excerpts of two pa1 job.lxt files -------------------------------

CAGE_PHASING = """\
 Command line parameters:  -t4 -y -a -m2000 -d0.996 job

  4 threads running in parallel

 Unit-cell:  17.810  26.470  41.000   90.00   96.18   90.00

 Laue group identified as number  2:   2/m

  280987 reflections read from file job.hkl

 Unique Patterson peaks (origin + d>1.7A) for superposition:

    N      X        Y        Z    Height Distance
    1   0.0000   0.0000   0.0000  999.00   0.000
    2   0.9889   0.5000   0.7259  321.04  17.349

 Setup:   0.909 secs

  4 threads running in parallel

  Try N(iter)  CC   R(weak)   CHEM    CFOM    best  Sig(min) N(P1) Vol/N
    1  2000   85.07  0.2210  0.6980  0.5938  0.5938  2.093   606   31.71
    2  2000   85.16  0.2179  0.6480  0.5519  0.5938  2.208   581   33.07
    3  2000   86.60  0.2338  0.6382  0.5527  0.5938  1.985   610   31.50
    4  2000   85.91  0.2300  0.5775  0.4962  0.5938  1.975   586   32.79
    5  2928   86.38  0.2341  0.7514  0.6490  0.6490  1.975   591   32.51
"""

HEX_FINISHED = """\
 Command line parameters:  -t4 -y -a -m1000 -d1 job

 Laue group identified as number 12:   6/mmm

  Try N(iter)  CC   R(weak)   CHEM    CFOM    best  Sig(min) N(P1) Vol/N
    1  1000   87.28  0.1318  0.7260  0.6336  0.6336  2.432   616   35.86
    6  2143   88.47  0.1408  0.7826  0.7096  0.7096  2.396   603   36.64

      16 attempts, solution  6 selected with best CFOM = 0.7096, Alpha0 = 0.194

 Structure solution:     837.720 secs

   4 Centrosymmetric and  14 non-centrosymmetric space groups evaluated

 Space group determination:     294.645 secs

   R1  Rweak Alpha SysAbs  Orientation      Space group  Flack_x  File  Formula
 0.332 0.071 0.110 0.00      as input       P6/mmm               job_a  C109 N78 O117 I9

 Assign elements and isotropic refinement    91.928 secs

 ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
 +  SHELXT finished at 01:50:53    Total time:     1225.070 secs  +
 ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
"""


class TestLxtStatus:
    def test_phasing_in_progress_single_digit_laue(self):
        st = RunShelxt._lxt_status(CAGE_PHASING)
        assert st["stage"] == "phasing"
        assert st["laue"] == "2/m" and st["laue_number"] == 2
        assert len(st["tries"]) == 5
        assert st["best_cfom"] == pytest.approx(0.6490)
        assert st["tries"][4]["n_iter"] == 2928
        assert st["tries"][4]["cc"] == pytest.approx(86.38)
        assert not st["phased"] and not st["finished"]
        # the Patterson peak table must not be mistaken for tries
        assert all(t["try"] <= 5 for t in st["tries"])

    def test_finished_job(self):
        st = RunShelxt._lxt_status(HEX_FINISHED)
        assert st["stage"] == "finished"
        assert st["phased"] and st["finished"]
        assert st["phasing_s"] == pytest.approx(837.72)
        assert st["n_attempts"] == 16 and st["selected_try"] == 6
        assert st["best_cfom"] == pytest.approx(0.7096)
        assert st["n_groups"] == 18
        assert st["sg_search_s"] == pytest.approx(294.645)
        assert st["assign_s"] == pytest.approx(91.928)
        assert st["total_s"] == pytest.approx(1225.07)

    def test_accept_bar_rule(self):
        assert shelxt_accept_bar(1) == pytest.approx(0.84)
        assert shelxt_accept_bar(16) == pytest.approx(0.69)
        assert shelxt_accept_bar(20) == pytest.approx(0.65)
        assert shelxt_accept_bar(40) == pytest.approx(0.65)
        assert shelxt_accept_bar(20, x=0.7) == pytest.approx(0.70)

    def test_custom_x_from_command_line(self):
        st = RunShelxt._lxt_status(CAGE_PHASING.replace(
            "-m2000 -d0.996", "-m2000 -x0.60 -d0.996"))
        assert st["accept_x"] == pytest.approx(0.60)


class TestTimeoutMessage:
    def _msg(self, tmp_path: Path, text, elapsed=1801.0, limit=1800,
             grace=None):
        (tmp_path / "job.lxt").write_text(text, encoding="utf-8")
        return RunShelxt._timeout_message(tmp_path, elapsed, limit, grace)

    def test_single_digit_laue_is_progress_not_silence(self, tmp_path):
        """pa1 cage-l3-r1: 1800 s, 16 tries, best CFOM 0.649 - was reported
        as 'before writing any progress'."""
        m = self._msg(tmp_path, CAGE_PHASING)
        assert "before writing any progress" not in m
        assert "during phasing in Laue class 2/m" in m
        assert "5 tries done" in m
        assert "0.649" in m
        # below the floor: more budget is the wrong lever
        assert "more time only buys more tries" in m
        assert "solve_resolution" in m

    def test_above_floor_says_more_time_finishes_it(self, tmp_path):
        txt = CAGE_PHASING.replace("0.6490  0.6490", "0.6710  0.6710")
        m = self._msg(tmp_path, txt, elapsed=300.0, limit=300)
        assert "already clears the floor 0.65" in m
        assert "larger timeout_s" in m

    def test_no_try_yet(self, tmp_path):
        txt = CAGE_PHASING.split("  Try N(iter)")[0]
        m = self._msg(tmp_path, txt, elapsed=120.0, limit=120)
        assert "no try has completed yet" in m

    def test_search_stage_with_grace_exhausted(self, tmp_path):
        txt = HEX_FINISHED.split("   4 Centrosymmetric")[0]
        m = self._msg(tmp_path, txt, elapsed=1500.0, limit=600, grace=900)
        assert "PHASING HAD ALREADY FINISHED in 837.720 s" in m
        assert "0.7096" in m and "16 tries" in m
        assert "900 s search grace" in m
        assert "space_group=" in m

    def test_nothing_written(self, tmp_path):
        m = RunShelxt._timeout_message(tmp_path, 30.0, 30)
        assert "before writing any progress" in m
        assert "start-up problem" in m


class TestSpaceGroupName:
    @pytest.mark.parametrize("hm, want", [
        ("P 21/c", "P2(1)_c"),
        ("P21/c", "P2(1)_c"),
        ("P 1 21/c 1", "P2(1)_c"),
        ("C c c m", "Cccm"),
        ("P 6/m m m", "P6_mmm"),
        ("P 63/m m c", "P6(3)_mmc"),
        ("P n a 21", "Pna2(1)"),
        ("I 2/a", "I2_a"),
        ("P -1", "P-1"),
        ("P 41 21 2", "P4(1)2(1)2"),
        ("P 6 2 2", "P622"),
        ("P -6 2 m", "P-62m"),
        ("P 31 2 1", "P3(1)21"),
        ("P2(1)_c", "P2(1)_c"),        # already SHELXT-shaped
    ])
    def test_conversion(self, hm, want):
        assert shelxt_space_group_name(hm) == want

    def test_cli_flag(self):
        assert RunShelxt._cli_flags({"space_group": "P 21"}) == ["-sP2(1)"]


FAKE_SHELXT = textwrap.dedent("""
    import sys, time
    from pathlib import Path
    lxt = Path("job.lxt")
    def w(s):
        with open(lxt, "a", encoding="ascii") as f:
            f.write(s)
    search_s = float(sys.argv[1])
    w(" Command line parameters:  -t4 job\\n\\n"
      " Laue group identified as number  2:   2/m\\n\\n"
      "  Try N(iter)  CC   R(weak)   CHEM    CFOM    best  Sig(min) N(P1) Vol/N\\n")
    time.sleep(0.4)
    w("    1  2000   85.07  0.2210  0.6980  0.5938  0.5938  2.093   606   31.71\\n")
    time.sleep(0.4)
    w("    2  2928   86.38  0.2341  0.7514  0.6490  0.6490  1.975   591   32.51\\n")
    time.sleep(0.7)
    w("\\n       2 attempts, solution  2 selected with best CFOM = 0.6490, Alpha0 = 0.194\\n\\n"
      " Structure solution:       1.500 secs\\n")
    time.sleep(search_s)
    w("\\n   4 Centrosymmetric and  14 non-centrosymmetric space groups evaluated\\n\\n"
      " Space group determination:     3.000 secs\\n")
""")


class TestStagedRunner:
    """timeout_s cuts only the phasing stage; a finished phasing gets grace."""

    def _cmd(self, tmp_path: Path, search_s: float = 3.0) -> list[str]:
        fake = tmp_path / "fake_shelxt.py"
        fake.write_text(FAKE_SHELXT, encoding="utf-8")
        return [sys.executable, str(fake), str(search_s)]

    def test_killed_during_phasing(self, tmp_path):
        beats: list[str] = []
        r = RunShelxt._run_staged(self._cmd(tmp_path), tmp_path, budget_s=1,
                                  grace_s=30, progress=beats.append,
                                  poll_s=0.15, heartbeat_s=0.3)
        assert r["timed_out"] == "phasing"
        assert r["elapsed"] < 2.5
        assert any("phasing in Laue class 2/m" in b for b in beats)
        m = RunShelxt._timeout_message(tmp_path, r["elapsed"], 1)
        assert "during phasing" in m and "tries done" in m

    def test_finished_phasing_outlives_timeout_within_grace(self, tmp_path):
        beats: list[str] = []
        # The fake phases for 1.5 s of sleeps AFTER interpreter start-up;
        # with budget_s=2 the margin was ~0.2 s on an idle machine and the
        # test flipped to "killed during phasing" whenever start-up took
        # longer (seen 2026-09-04 with two full suites and a browser on
        # the box). budget_s=3 keeps the intent - the budget expires while
        # the search stage is still running - with a margin start-up
        # cannot eat.
        r = RunShelxt._run_staged(self._cmd(tmp_path, 3.0), tmp_path,
                                  budget_s=3, grace_s=30,
                                  progress=beats.append, poll_s=0.15,
                                  heartbeat_s=0.3)
        assert r["timed_out"] is None
        assert r["returncode"] == 0
        assert r["elapsed"] > 3.0          # ran past timeout_s on purpose
        assert r["status"]["phased"]
        assert any("phasing FINISHED" in b for b in beats)
        assert any("not cut by timeout_s" in b for b in beats)

    def test_grace_exhausted_in_search(self, tmp_path):
        r = RunShelxt._run_staged(self._cmd(tmp_path, 30.0), tmp_path,
                                  budget_s=2, grace_s=1, poll_s=0.15)
        assert r["timed_out"] == "search"
        assert 2.5 < r["elapsed"] < 6.0
        m = RunShelxt._timeout_message(tmp_path, r["elapsed"], 2, grace=1)
        assert "PHASING HAD ALREADY FINISHED" in m
        assert "1 s search grace" in m
