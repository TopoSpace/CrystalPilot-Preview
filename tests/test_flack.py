"""Flack chain: lst parsing (vendor-verbatim fixtures), verdict wording,
snapshot plumbing."""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from crystalpilot.refine.tools_extra import flack_verdict, parse_flack_lst

# verbatim from workbench/hklf5_experiment/refined_tol010.lst (SHELXL-2019/3)
LST_UNDETERMINED = """
 R1 = 0.1066 for 5935 Fo > 4sig(Fo) and 0.1383 for all 10782 data

 Flack x =    1.546(999) by classical fit to all intensities
             -0.431(999) from 857 selected quotients (Parsons' method)

 ** Absolute structure cannot be determined reliably **
"""

LST_GOOD = """
 R1 = 0.0301 for 4111 Fo > 4sig(Fo) and 0.0329 for all 4384 data

 Flack x =    0.0231(212) by classical fit to all intensities
              -0.011(11) from 1567 selected quotients (Parsons' method)
"""


def test_parse_undetermined_prefers_parsons():
    f = parse_flack_lst(LST_UNDETERMINED)
    assert f is not None
    assert f["classical"]["value"] == pytest.approx(1.546)
    assert f["classical"]["su"] == pytest.approx(0.999)
    assert f["parsons"]["value"] == pytest.approx(-0.431)
    assert f["parsons"]["su"] == pytest.approx(0.999)
    assert f["parsons"]["n_quotients"] == 857
    assert f["method"] == "parsons"
    assert f["value"] == pytest.approx(-0.431)
    assert f["determined"] is False


def test_parse_good_case_last_digit_su_convention():
    f = parse_flack_lst(LST_GOOD)
    assert f["classical"]["su"] == pytest.approx(0.0212)   # 0.0231(212)
    assert f["parsons"]["value"] == pytest.approx(-0.011)
    assert f["parsons"]["su"] == pytest.approx(0.011)      # -0.011(11)
    assert f["determined"] is True


def test_parse_absent_returns_none():
    assert parse_flack_lst("R1 = 0.03 for 100 Fo > 4sig(Fo)") is None


def test_verdict_branches():
    assert "correct absolute structure" in flack_verdict(0.02, 0.05)
    assert "invert_structure" in flack_verdict(0.97, 0.04)
    assert "set_twin" in flack_verdict(0.49, 0.06)
    v = flack_verdict(-0.431, 0.999, determined=False)
    assert "no determination power" in v and "light-atom" in v
    assert "no determination power" in flack_verdict(0.1, 0.5)
    assert "intermediate" in flack_verdict(0.22, 0.03)


def test_verdict_banner_with_small_su_is_not_no_power():
    # r21 live contradiction: Flack 0.51(1) + SHELXL banner. The banner
    # fires because neither hand dominates (racemic twin), NOT because the
    # estimate is weak - the note must not claim "su > 0.3".
    v = flack_verdict(0.51, 0.014, determined=False)
    assert "no determination power" not in v
    assert "set_twin" in v
    assert "neither hand dominates" in v
    # banner is still surfaced as context on the other branches
    v2 = flack_verdict(0.02, 0.05, determined=False)
    assert "correct absolute structure" in v2 and "banner" in v2


def test_snapshot_carries_flack():
    from crystalpilot.pipeline.session import RefinementSnapshot
    s = RefinementSnapshot(label="t", r1_strong=0.03, r1_all=0.04, wr2=0.08,
                           goof=1.02, n_params=100, n_reflections=2000,
                           flack=0.02, flack_su=0.03)
    d = s.as_dict()
    assert d["flack"] == 0.02 and d["flack_su"] == 0.03
    # default stays None so centrosymmetric history is unpolluted
    s2 = RefinementSnapshot(label="t", r1_strong=0.03, r1_all=0.04, wr2=0.08,
                            goof=1.02, n_params=100, n_reflections=2000)
    assert s2.as_dict()["flack"] is None
