"""hklf5_writer pure-function core: overlap classification + HKLF5
composition (numpy only - the dials-env main() is exercised by the
skipif integration test at the bottom)."""
from pathlib import Path

import numpy as np
import pytest

from crystalpilot.io import hklf5_writer as w


def test_classify_basic_classes():
    # sweep 0: A0/B0 coincident; A1/B1 partial (4 px apart);
    # A2 clean; B2 clean (far away)
    xyz_a = np.array([[100.0, 100.0, 10.0],
                      [200.0, 200.0, 20.0],
                      [300.0, 300.0, 30.0]])
    xyz_b = np.array([[101.0, 100.5, 10.2],
                      [204.0, 200.0, 20.0],
                      [400.0, 400.0, 40.0]])
    ids = np.zeros(3, dtype=int)
    ca, cb, match = w.classify_overlaps(xyz_a, ids, xyz_b, ids)
    assert list(ca) == [w.COINCIDENT, w.PARTIAL, w.CLEAN]
    assert list(cb) == [w.COINCIDENT, w.PARTIAL, w.CLEAN]
    assert match[0] == 0 and match[1] == -1


def test_classify_sweep_isolation():
    # same detector position but DIFFERENT sweeps: no physical overlap
    xyz_a = np.array([[100.0, 100.0, 10.0]])
    xyz_b = np.array([[100.0, 100.0, 10.0]])
    ca, cb, _ = w.classify_overlaps(
        xyz_a, np.array([0]), xyz_b, np.array([1]))
    assert ca[0] == w.CLEAN and cb[0] == w.CLEAN


def test_classify_b_row_exclusivity():
    # two A spots tight around one B spot: first claims it, second
    # degrades to partial (a blob cannot be two composites)
    xyz_a = np.array([[100.0, 100.0, 10.0], [101.0, 100.0, 10.0]])
    xyz_b = np.array([[100.5, 100.0, 10.0]])
    ids_a = np.zeros(2, dtype=int)
    ca, cb, match = w.classify_overlaps(
        xyz_a, ids_a, xyz_b, np.array([0]))
    assert sorted(ca) == [w.COINCIDENT, w.PARTIAL]
    assert cb[0] == w.COINCIDENT
    assert (match >= 0).sum() == 1


def _mini_sets():
    h_a = np.array([[1, 0, 0], [2, 0, 0], [3, 0, 0]])
    i_a = np.array([100.0, 200.0, 300.0])
    s_a = np.array([1.0, 2.0, 3.0])
    class_a = np.array([w.COINCIDENT, w.CLEAN, w.PARTIAL])
    match = np.array([0, -1, -1])
    h_b = np.array([[0, 1, 0], [0, 2, 0]])
    i_b = np.array([50.0, 60.0])
    s_b = np.array([0.5, 0.6])
    class_b = np.array([w.COINCIDENT, w.CLEAN])
    return h_a, i_a, s_a, class_a, match, h_b, i_b, s_b, class_b


def test_compose_composite_order_and_batches():
    h_a, i_a, s_a, ca, match, h_b, i_b, s_b, cb = _mini_sets()
    lines, major, counts = w.compose_hklf5(
        h_a, i_a, s_a, ca, match, h_b, i_b, s_b, cb,
        minor_keep=np.array([False, True]))
    assert counts == {
        "composites": 1, "pc_composites": 0, "major_clean": 1,
        "minor_singles_written": 1,
        "major_partial_dropped": 1, "minor_partial_dropped": 0,
        "minor_clean_available": 1, "intensity_divisor": 1.0,
        "n_batches": 3}
    # composite: minor line (its OWN hkl, batch -2) then major line
    # (batch 1) carrying the blob intensity
    assert lines[0].endswith("  -2\n") and "   0   1   0" in lines[0]
    assert lines[1].endswith("   1\n") and "   1   0   0" in lines[1]
    assert float(lines[0][12:20]) == float(lines[1][12:20]) == 100.0
    # clean major, then the policy-kept minor single as batch 3
    assert lines[2].endswith("   1\n") and "   2   0   0" in lines[2]
    assert lines[3].endswith("   3\n") and "   0   2   0" in lines[3]
    # terminator
    assert lines[-1].startswith("   0   0   0")
    # major_clean carries ONLY the clean major reflection + terminator
    assert len(major) == 2 and "   2   0   0" in major[0]
    assert len(major[0].rstrip("\n")) == 28      # HKLF4: no batch column


def test_compose_policy_none_two_batches():
    h_a, i_a, s_a, ca, match, h_b, i_b, s_b, cb = _mini_sets()
    lines, _, counts = w.compose_hklf5(
        h_a, i_a, s_a, ca, match, h_b, i_b, s_b, cb, minor_keep=None)
    assert counts["n_batches"] == 2
    assert counts["minor_singles_written"] == 0
    assert not any(line.endswith("   3\n") for line in lines)


def test_pair_partials_exclusive_greedy():
    # A1-B0 is the globally nearest pair and must win B0; A0 then
    # falls back to B1 (5.5 px, still inside the 6 px wide window).
    xyz_a = np.array([[100.0, 100.0, 10.0], [103.0, 100.0, 10.0]])
    xyz_b = np.array([[104.0, 100.0, 10.0], [105.5, 100.0, 10.0]])
    ids_a = np.zeros(2, dtype=int)
    ids_b = np.zeros(2, dtype=int)
    class_a = np.array([w.PARTIAL, w.PARTIAL])
    match = np.array([-1, -1])
    pc = w.pair_partials(xyz_a, ids_a, xyz_b, ids_b, class_a, match)
    assert pc[1] == 0          # 1 px away - globally nearest pair
    assert pc[0] == 1          # falls back to the 5.5 px neighbour
    # a B row claimed as a coincident partner is untouchable
    pc2 = w.pair_partials(xyz_a, ids_a, xyz_b, ids_b, class_a,
                          np.array([-1, 0]))
    assert pc2[1] == 1 and pc2[0] == -1


def test_compose_partial_composite_records():
    h_a, i_a, s_a, ca, match, h_b, i_b, s_b, cb = _mini_sets()
    # pair the PARTIAL A row (index 2) with the CLEAN B row (index 1)
    pc = np.array([-1, -1, 1])
    lines, major, counts = w.compose_hklf5(
        h_a, i_a, s_a, ca, match, h_b, i_b, s_b, cb,
        minor_keep=np.array([False, True]), pc_match=pc)
    assert counts["pc_composites"] == 1
    assert counts["major_partial_dropped"] == 0
    # the pc-consumed B row must NOT be double-written as a single
    assert counts["minor_singles_written"] == 0
    assert counts["n_batches"] == 2
    # pc record: B line (own hkl, batch -2) then A line (batch 1), both
    # carrying the A measurement as the blob estimate
    pc_lines = [ln for ln in lines if "   3   0   0" in ln]
    assert len(pc_lines) == 1 and pc_lines[0].endswith("   1\n")
    b_lines = [ln for ln in lines if "   0   2   0" in ln]
    assert len(b_lines) == 1 and b_lines[0].endswith("  -2\n")
    assert float(b_lines[0][12:20]) == float(pc_lines[0][12:20]) == 300.0
    # the partial never reaches the solving HKLF4 file
    assert not any("   3   0   0" in ln for ln in major)


def test_compose_intensity_divisor():
    h_a = np.array([[1, 0, 0]])
    i_a = np.array([9_900_000.0])
    s_a = np.array([100.0])
    ca = np.array([w.CLEAN])
    lines, _, counts = w.compose_hklf5(
        h_a, i_a, s_a, ca, np.array([-1]), np.empty((0, 3), int),
        np.empty(0), np.empty(0), np.empty(0, int), minor_keep=None)
    assert counts["intensity_divisor"] == 100.0
    assert float(lines[0][12:20]) == 99000.0


_PROBE = Path(r"H:/CrystalPilot/workdir/hklf5_probe")
_DIALS_PY = Path(r"C:/Users/username/miniforge3/envs/dials/python.exe")


@pytest.mark.skipif(
    not (_PROBE / "scaledA.refl").exists() or not _DIALS_PY.exists(),
    reason="r15 probe artifacts or dials env not present")
def test_writer_main_on_r15_probe(tmp_path):
    """Golden regression on the real p770 twin: counts must match the
    validated probe (1533 composites etc., see AUDIT 2026-08-31)."""
    import json
    import os
    import shutil
    import subprocess

    shutil.copy(_PROBE / "scaledA.refl", tmp_path / "twin_scaledA.refl")
    shutil.copy(_PROBE / "scaledB.refl", tmp_path / "twin_scaledB.refl")
    script = Path(w.__file__)
    env = dict(os.environ)
    env["PATH"] = str(_DIALS_PY.parent / "Library" / "bin") + os.pathsep \
        + env.get("PATH", "")
    r = subprocess.run(
        [str(_DIALS_PY), str(script), str(tmp_path),
         "2", "1", "6", "3", "coverage",
         "10.1198,12.6688,20.7241,72.205,75.924,83.745", "hall: -P 1"],
        capture_output=True, text=True, timeout=600, env=env)
    assert r.returncode == 0, r.stderr[-800:]
    rep = json.loads((tmp_path / "twin5_report.json").read_text())
    assert rep["composites"] == 1533
    assert rep["major_clean"] == 8048
    assert rep["major_partial_dropped"] == 3899
    assert rep["policy"] == "coverage"
    assert rep["partial_policy"] == "drop"
    assert rep["coverage_extra_uniques"] > 1500
    assert (tmp_path / "twin5.hkl").exists()
    assert (tmp_path / "twin_major_clean.hkl").exists()


@pytest.mark.skipif(
    not (_PROBE / "scaledA.refl").exists() or not _DIALS_PY.exists(),
    reason="r15 probe artifacts or dials env not present")
def test_writer_main_partial_composite_on_r15_probe(tmp_path):
    """partial_policy=composite golden numbers (E1 experiment
    2026-08-31): every partial pairs, nothing dropped, completeness
    lever engaged."""
    import json
    import os
    import shutil
    import subprocess

    shutil.copy(_PROBE / "scaledA.refl", tmp_path / "twin_scaledA.refl")
    shutil.copy(_PROBE / "scaledB.refl", tmp_path / "twin_scaledB.refl")
    script = Path(w.__file__)
    env = dict(os.environ)
    env["PATH"] = str(_DIALS_PY.parent / "Library" / "bin") + os.pathsep \
        + env.get("PATH", "")
    r = subprocess.run(
        [str(_DIALS_PY), str(script), str(tmp_path),
         "2", "1", "6", "3", "coverage",
         "10.1198,12.6688,20.7241,72.205,75.924,83.745", "hall: -P 1",
         "composite"],
        capture_output=True, text=True, timeout=600, env=env)
    assert r.returncode == 0, r.stderr[-800:]
    rep = json.loads((tmp_path / "twin5_report.json").read_text())
    assert rep["partial_policy"] == "composite"
    assert rep["composites"] == 1533
    assert rep["pc_composites"] == 3899
    assert rep["major_partial_dropped"] == 0
    # pc records cover their uniques, so coverage needs fewer singles
    assert 0 < rep["coverage_extra_uniques"] < 2148
    # every composite writes two lines; quick structural sanity
    txt = (tmp_path / "twin5.hkl").read_text()
    n_minus2 = sum(1 for ln in txt.splitlines() if ln.endswith("  -2"))
    assert n_minus2 == rep["composites"] + rep["pc_composites"]
