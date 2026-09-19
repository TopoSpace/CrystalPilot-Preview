"""Fast unit tests for the raw-frames toolchain (no DIALS is ever invoked:
everything here fails/succeeds before any dials.* subprocess would start)."""
from __future__ import annotations

import json
import math
from types import SimpleNamespace
from pathlib import Path

import pytest

from crystalpilot.refine import tools_frames as tf

FRAMES_TOOLS = ("import_frames", "find_spots", "index_frames",
                "integrate_frames", "scale_and_export", "create_start_model")


# --------------------------------------------------------------------------- #
# state.json round-trip
# --------------------------------------------------------------------------- #

def test_state_roundtrip_and_atomic_write(tmp_path):
    assert tf.load_frames_state(tmp_path) == {}
    tf.save_frames_state(tmp_path, {
        "frames_dir": "X:/frames", "dials_env": "C:/envs/dials",
        "stages": {"import_frames": {"completed_at": "now", "n_images": 3}}})
    st = tf.load_frames_state(tmp_path)
    assert st["frames_dir"] == "X:/frames"
    assert st["stages"]["import_frames"]["n_images"] == 3
    # atomic write leaves no tmp litter
    assert [p.name for p in tmp_path.iterdir()] == ["state.json"]
    # re-running a stage overwrites its record
    st["stages"]["import_frames"] = {"completed_at": "later", "n_images": 5}
    tf.save_frames_state(tmp_path, st)
    st2 = tf.load_frames_state(tmp_path)
    assert st2["stages"]["import_frames"]["n_images"] == 5


def test_state_unreadable_returns_empty(tmp_path):
    (tmp_path / "state.json").write_text("{not json", encoding="utf-8")
    assert tf.load_frames_state(tmp_path) == {}


# --------------------------------------------------------------------------- #
# pure helpers
# --------------------------------------------------------------------------- #

def test_parse_composition():
    assert tf.parse_composition("C3 H7 N O2 S") == {
        "C": 3.0, "H": 7.0, "N": 1.0, "O": 2.0, "S": 1.0}
    assert tf.parse_composition("C3H7NO2") == {
        "C": 3.0, "H": 7.0, "N": 1.0, "O": 2.0}
    assert tf.parse_composition("") == {}
    assert tf.parse_composition("Zr6 O32") == {"Zr": 6.0, "O": 32.0}


def test_theta_deg():
    th = tf.theta_deg(0.6889, 0.58)
    assert th is not None
    assert abs(th - math.degrees(math.asin(0.6889 / (2 * 0.58)))) < 1e-3
    assert tf.theta_deg(0.7, 0.3) is None       # asin argument > 1
    assert tf.theta_deg(None, 1.0) is None
    assert tf.theta_deg(0.7, None) is None


DIALS_INS = """TITL 19 in P212121
CELL 0.68890   5.42807   8.12883  12.05269  90.0000  90.0000  90.0000
LATT -1
SYMM -X+1/2,-Y,Z+1/2
SYMM X+1/2,-Y+1/2,-Z
SYMM -X,Y+1/2,-Z+1/2
SFAC C H N O S
UNIT 0 0 0 0 0
HKLF 4
END
"""


def test_build_solve_ins():
    comp = tf.parse_composition("C3 H7 N O2 S")
    text = tf.build_solve_ins(DIALS_INS, comp, z=4)
    lines = text.splitlines()
    assert lines[1].startswith("CELL 0.68890")
    assert "ZERR 4 0 0 0 0 0 0" in text
    assert "LATT -1" in text
    assert text.count("SYMM ") == 3
    assert "SFAC C H N O S" in text
    assert "UNIT 12 28 4 8 4" in text            # counts x Z, SFAC order
    assert text.rstrip().endswith("END")
    nosym = tf.build_solve_ins(DIALS_INS, comp, z=4, include_symmetry=False)
    assert "LATT" not in nosym and "SYMM" not in nosym
    with pytest.raises(ValueError):
        tf.build_solve_ins("TITL no cell here\n", comp, z=1)


def test_last_rmsd_row_ignores_integer_tables():
    log = (
        "RMSDs by experiment:\n"
        "|     0 |   2006 |  0.42223 |  0.69307 |    0.63575 |\n"
        "|     1 |   1934 |  0.38569 |  0.63871 |    0.67456 |\n"
        "index summary (must NOT be picked up as an RMSD):\n"
        "|          0 |        2350 |           289 |           237 |          89 |\n")
    row = tf._last_rmsd_row(log)
    assert row == {"x_px": 0.38569, "y_px": 0.63871, "phi_deg": 0.67456}
    assert tf._last_rmsd_row("no tables at all") is None


def test_deep_merge_preserves_existing_keys():
    dst = {"chemistry": {"ligands": [1]}, "experiment": {"temperature_K": 100}}
    tf._deep_merge(dst, {"experiment": {"computing": {"data_reduction": "DIALS"}},
                         "data": {"hkl": "crystal.hkl"}})
    assert dst["chemistry"] == {"ligands": [1]}
    assert dst["experiment"]["temperature_K"] == 100
    assert dst["experiment"]["computing"]["data_reduction"] == "DIALS"
    assert dst["data"]["hkl"] == "crystal.hkl"


# --------------------------------------------------------------------------- #
# registration + awaiting-data project behaviour (real RefineProject, no DIALS)
# --------------------------------------------------------------------------- #

@pytest.fixture()
def frames_project(tmp_path):
    from crystalpilot.refine.project import RefineProject
    d = tmp_path / "proj"
    d.mkdir()
    (d / "context.json").write_text(json.dumps(
        {"chemistry": {"ligands": [{"name": "test-ligand"}]}}),
        encoding="utf-8")
    return RefineProject(d)


def test_frames_tools_registered(frames_project):
    names = frames_project.registry.names()
    for n in FRAMES_TOOLS:
        assert n in names, f"{n} missing from registry"


def test_import_frames_missing_dir_fails_fast(frames_project):
    p = frames_project
    assert p.open()["state"] == "awaiting_data"
    r = p.invoke_tool("import_frames", {"frames_dir": "no_such_dir"})
    assert not r.ok
    assert "no_such_dir" in (r.error or "")


def test_import_frames_requires_frames_dir(frames_project):
    r = frames_project.invoke_tool("import_frames", {})
    assert not r.ok
    assert "frames_dir" in (r.error or "")


def test_stage_prerequisites(frames_project):
    p = frames_project
    p.open()
    r = p.invoke_tool("find_spots", {})
    assert not r.ok and "import_frames" in (r.error or "")
    r = p.invoke_tool("index_frames", {})
    assert not r.ok and "import_frames" in (r.error or "")
    r = p.invoke_tool("integrate_frames", {})
    assert not r.ok and "index_frames" in (r.error or "")
    r = p.invoke_tool("scale_and_export", {"composition": "C H"})
    assert not r.ok and "integrate_frames" in (r.error or "")
    r = p.invoke_tool("create_start_model", {})
    assert not r.ok and "scale_and_export" in (r.error or "")


# --------------------------------------------------------------------------- #
# screening-run exclusion (RODIN W(CO)6 lesson: 10-frame CrysAlisPro "pre_"
# runs broke dials.integrate profile modelling)
# --------------------------------------------------------------------------- #

def test_filter_screening_runs_drops_short_runs():
    from crystalpilot.refine.tools_frames import _filter_screening_runs
    det = {"scan": [f"a_{i}" for i in range(60)] + ["pre_1", "pre_2"],
           "runs": {"main": [f"a_{i}" for i in range(60)],
                    "pre": ["pre_1", "pre_2"]}}
    notes: list[str] = []
    _filter_screening_runs(det, 12, notes)
    assert list(det["runs"]) == ["main"]
    assert "pre_1" not in det["scan"] and len(det["scan"]) == 60
    assert notes and "screening" in notes[0]


def test_filter_screening_runs_never_drops_everything():
    from crystalpilot.refine.tools_frames import _filter_screening_runs
    det = {"scan": ["x_1", "x_2", "y_1"],
           "runs": {"x": ["x_1", "x_2"], "y": ["y_1"]}}
    notes: list[str] = []
    _filter_screening_runs(det, 12, notes)
    assert len(det["scan"]) == 3 and not notes


def test_filter_screening_runs_disabled_with_min_1():
    from crystalpilot.refine.tools_frames import _filter_screening_runs
    det = {"scan": [f"a_{i}" for i in range(30)] + ["pre_1"],
           "runs": {"a": [f"a_{i}" for i in range(30)], "pre": ["pre_1"]}}
    notes: list[str] = []
    _filter_screening_runs(det, 1, notes)
    assert len(det["scan"]) == 31 and not notes


# --------------------------------------------------------------------------- #
# space-group screen (dials.symmetry is Sohncke-only - W(CO)6/onitwin lesson)
# --------------------------------------------------------------------------- #

def _pnma_intensities():
    """Synthetic Fc^2 of a Pnma structure, delivered as a P1 array
    (unmerged-style) like the exported dials.hkl."""
    from cctbx import crystal, xray
    from cctbx.array_family import flex

    cs = crystal.symmetry(unit_cell=(11.7, 11.2, 6.4, 90, 90, 90),
                          space_group_symbol="P n m a")
    xs = xray.structure(crystal_symmetry=cs)
    for lbl, el, site in (("W1", "W", (0.113, 0.25, 0.317)),
                          ("O1", "O", (0.352, 0.089, 0.411)),
                          ("C1", "C", (0.238, 0.457, 0.083))):
        xs.add_scatterer(xray.scatterer(label=lbl, site=site, u=0.02,
                                        scattering_type=el))
    # compute on the P1-cast structure so systematically-absent classes
    # are PRESENT in the index list (with F ~ 0), like real exported data
    fc = xs.expand_to_p1().structure_factors(d_min=0.9).f_calc()
    ii = fc.as_intensity_array()
    return ii.customized_copy(
        sigmas=flex.double(ii.size(), 1.0)).set_observation_type_xray_intensity()


def test_sg_screen_finds_glide_group_over_sohncke():
    from cctbx import sgtbx
    from crystalpilot.refine.sg_screen import screen_space_groups
    ma = _pnma_intensities()
    laue = sgtbx.space_group_info("P n m a").group().build_derived_laue_group()
    res = screen_space_groups(ma, laue)
    top = res["candidates"][0]
    top_type = sgtbx.space_group_info(top["space_group"]).type().number()
    # Pnma (62) or its acentric absence-twin Pna21-type setting (33)
    assert top_type in (62, 33), res["candidates"][:3]
    assert top["consistent"] and top["n_violations"] == 0
    # P 21 21 21 must rank strictly below (fewer absences explained)
    ranks = {r["space_group"]: i for i, r in enumerate(res["candidates"])}
    assert any(sgtbx.space_group_info(s).type().number() == 62
               for s in ranks), "no No.62 setting in top candidates"
    e = res.get("e_statistics")
    assert e and e["hint"] == "centrosymmetric", e


def test_sg_screen_true_group_beats_its_subgroups():
    from cctbx import sgtbx
    from crystalpilot.refine.sg_screen import screen_space_groups
    ma = _pnma_intensities()
    laue = sgtbx.space_group_info("P n m a").group().build_derived_laue_group()
    res = screen_space_groups(ma, laue, max_out=30)
    def rank_of(number):
        for i, r in enumerate(res["candidates"]):
            if sgtbx.space_group_info(
                    r["space_group"]).type().number() == number:
                return i
        return None
    r62 = rank_of(62)
    r19 = rank_of(19)      # P 21 21 21
    assert r62 is not None
    assert r19 is None or r62 < r19


def test_runner_heartbeat_streams_progress(tmp_path):
    """The heartbeat path must deliver periodic progress callbacks with the
    subprocess's latest output line and still return full stdout."""
    import sys
    from crystalpilot.io.frames_dials import DialsEnv, _Runner

    env = DialsEnv(prefix=Path(sys.executable).parent,
                   python=Path(sys.executable),
                   dispatcher_dirs=[Path(sys.executable).parent])
    r = _Runner(env, tmp_path, timeout=60.0)
    beats: list[str] = []
    code = ("import time\n"
            "for i in range(5):\n"
            "    print('line', i, flush=True)\n"
            "    time.sleep(0.5)\n")
    import subprocess, time as _t
    popen = subprocess.Popen([sys.executable, "-c", code],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             text=True, encoding="utf-8")
    t0 = _t.time()
    stdout, stderr = r._communicate_with_heartbeat(
        popen, "fake", "python", beats.append, t0,
        tmp_path / "fake.log", None, interval=0.6)
    assert "line 4" in stdout
    assert beats, "no heartbeat delivered"
    assert any("fake" in b and "elapsed" in b for b in beats)


def test_runner_heartbeat_timeout_kills_tree(tmp_path):
    import subprocess
    import sys
    import time as _t

    import pytest as _pytest

    from crystalpilot.io.frames_dials import (DialsEnv, DialsProcessingError,
                                              _Runner)
    env = DialsEnv(prefix=Path(sys.executable).parent,
                   python=Path(sys.executable),
                   dispatcher_dirs=[Path(sys.executable).parent])
    r = _Runner(env, tmp_path, timeout=1.2)
    (tmp_path / "logs").mkdir(exist_ok=True)
    popen = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        encoding="utf-8")
    with _pytest.raises(DialsProcessingError, match="timed out"):
        r._communicate_with_heartbeat(
            popen, "fake", "python", lambda m: None, _t.time(),
            tmp_path / "logs" / "fake.log", None, interval=0.4)
    assert popen.poll() is not None, "subprocess survived the timeout"


# --------------------------------------------------------------- hkl hygiene

def test_clean_hklf4_drops_bad_rows(tmp_path):
    from crystalpilot.io.shelx import clean_hklf4
    src = tmp_path / "dials.hkl"
    # 4 data rows: good / sigma=0 / sigma<0 / NaN F2, then terminator
    src.write_text(
        "   1   2   3  100.00    5.00\n"
        "   1   2   4   50.00    0.00\n"
        "   1   2   5   50.00   -1.00\n"
        "   1   2   6     nan    2.00\n"
        "   0   0   0    0.00    0.00\n",
        encoding="utf-8")
    dest = tmp_path / "crystal.hkl"
    stats = clean_hklf4(src, dest)
    assert stats == {"n_kept": 1, "n_dropped_sigma": 2,
                     "n_dropped_nonfinite": 1}
    lines = dest.read_text().splitlines()
    assert lines[0].startswith("   1   2   3")
    assert lines[1].startswith("   0   0   0")   # terminator preserved


def test_clean_hklf4_passthrough_when_clean(tmp_path):
    from crystalpilot.io.shelx import clean_hklf4
    src = tmp_path / "a.hkl"
    body = ("   1   0   0   10.00    1.00\n"
            "   2   0   0   20.00    2.00\n"
            "   0   0   0    0.00    0.00\n")
    src.write_text(body, encoding="utf-8")
    dest = tmp_path / "b.hkl"
    stats = clean_hklf4(src, dest)
    assert stats["n_kept"] == 2
    assert stats["n_dropped_sigma"] == 0
    assert dest.read_text() == body


def test_scale_and_export_schema_has_space_group():
    props = tf.ScaleAndExport.params_schema["properties"]
    assert "space_group" in props
    assert "reindex" in props["space_group"]["description"]


def test_dxtbx_plugin_source_layout():
    """The bundled Rigaku format plugin must stay installable: pyproject with
    the dxtbx.format entry point (DAG parent FormatCBF, see plugin docstring)
    and a version matching frames_dials._PLUGIN_VERSION."""
    import re
    from crystalpilot.io import frames_dials as fd
    root = Path(fd.__file__).resolve().parent / "dxtbx_plugin"
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    assert '"FormatCBFMiniRigaku:FormatCBF"' in pyproject
    assert 'crystalpilot_dxtbx_rigaku:FormatCBFMiniRigaku' in pyproject
    src = (root / "crystalpilot_dxtbx_rigaku" / "__init__.py").read_text(
        encoding="utf-8")
    m = re.search(r'^__version__ = "([^"]+)"', src, re.M)
    assert m and m.group(1) == fd._PLUGIN_VERSION
    mv = re.search(r'^version = "([^"]+)"', pyproject, re.M)
    assert mv and mv.group(1) == fd._PLUGIN_VERSION
    # geometry class hooks that make this format work must not regress
    for hook in ("def understand", "def _detector", "def _goniometer",
                 "def _scan", "def _beam", "Rotation_axis_vector",
                 "Detector_fast_axis_vector", "Incident_beam_vector"):
        assert hook in src


def test_ensure_format_plugins_missing_source(tmp_path, monkeypatch):
    from crystalpilot.io import frames_dials as fd
    env = fd.DialsEnv(prefix=tmp_path, python=tmp_path / "python.exe")
    monkeypatch.setattr(fd, "__file__", str(tmp_path / "frames_dials.py"))
    out = fd.ensure_format_plugins(env)
    assert out["ok"] is False and "plugin source missing" in out["error"]


# --------------------------------------------------------------------------- #
# estimate_resolution: referee dual-metric contract
# --------------------------------------------------------------------------- #

class _FakeProject:
    def __init__(self, d): self.dir = d


def test_estimate_resolution_passes_misigma_and_reports_both(tmp_path,
                                                             monkeypatch):
    proj = _FakeProject(tmp_path)
    tool = tf.EstimateResolution(proj)
    wd = tool.workdir
    (wd / "integrated.refl").write_bytes(b"x")
    (wd / "integrated.expt").write_bytes(b"x")
    seen = {}

    class FakeRunner:
        def run(self, stage, prog, args):
            seen["args"] = args
            return ("Resolution cc_half: 0.84\n"
                    "Resolution I/sig: 0.90\n")

    monkeypatch.setattr(tool, "_dials_env", lambda *_a, **_k: object())
    monkeypatch.setattr(tool, "_runner", lambda *_a, **_k: FakeRunner())
    r = tool.run(SimpleNamespace(session=None))
    assert r.ok, r.error
    assert "misigma=2.0" in seen["args"]
    assert r.summary["by_metric"] == {"cc_half": 0.84, "i_over_sigma": 0.90}
    assert r.summary["suggested_d_min"] == 0.84      # cc_half preferred
    assert "I/sig>=3" in r.summary["note"]


# --------------------------------------------------------------------------- #
# ingest_vendor_data: vendor product recognition
# --------------------------------------------------------------------------- #

def test_parse_p4p_and_hkl_sniff(tmp_path):
    p4p = tmp_path / "a.p4p"
    p4p.write_text(
        "CELL 10.1 12.7 20.8 104.6 104.1 96.2 2474.9\n"
        "CELLSD 0.001 0.002 0.003 0.002 0.002 0.002 1.0\n"
        "SOURCE MO 0.71073 0.70930\n"
        "CHEM ?\n", encoding="ascii")
    d = tf.parse_p4p(p4p)
    assert d["cell"][0] == 10.1 and d["wavelength"] == 0.71073
    assert "chem" not in d

    hkl4 = tmp_path / "b.hkl"
    hkl4.write_text("".join(
        f"{1:4d}{2:4d}{3:4d}{100.0:8.2f}{5.0:8.2f}\n" for _ in range(8)),
        encoding="ascii")
    v = tf.looks_like_shelx_hkl(hkl4)
    assert v["ok"] and not v["hklf5_batches"]

    hkl5 = tmp_path / "c.hkl"
    hkl5.write_text("".join(
        f"{1:4d}{2:4d}{3:4d}{100.0:8.2f}{5.0:8.2f}{(-2 if i % 3 else 2):4d}\n"
        for i in range(8)), encoding="ascii")
    v5 = tf.looks_like_shelx_hkl(hkl5)
    assert v5["ok"] and v5["hklf5_batches"]

    bad = tmp_path / "d.hkl"
    bad.write_text("this is not hkl data at all, just text\n" * 6,
                   encoding="ascii")
    assert not tf.looks_like_shelx_hkl(bad)["ok"]


def test_parse_saint_ls(tmp_path):
    # synthetic SAINT ._ls: reflection summary + global cell LS with
    # GooF-corrected ESDs (the PLAT183/184/185 provenance source)
    ls = tmp_path / "x_0m._ls"
    ls.write_text(
        "SAINT V8.42\n"
        "noise\n"
        "Unconstrained global unit cell refinement ====== 01/01/2026\n"
        "Reflection Summary:\n"
        " Component     Input  RLV.Excl      Used  WorstRes   BestRes"
        "   Min.2Th   Max.2Th\n"
        "    1.1(1)      9292         0      9292    7.0134    0.6876"
        "     5.809    62.242\n"
        "       All      9996         0      9996    7.5386    0.6876"
        "     5.404    62.242\n"
        "\n"
        "Component 1.1(1) cell and ESDs:\n"
        "         A         B         C     Alpha      Beta     Gamma"
        "           Vol\n"
        "   10.1554   12.7075   20.8077  104.7102  104.0489   96.2332"
        "       2477.74\n"
        "    0.0004    0.0005    0.0008    0.0005    0.0005    0.0005"
        "          0.27\n"
        "Corrected for goodness of fit:\n"
        "    0.0017    0.0021    0.0035    0.0021    0.0021    0.0024"
        "          1.25\n"
        "End global unit cell refinement ======\n",
        encoding="ascii")
    from crystalpilot.refine.tools_frames import parse_saint_ls
    r = parse_saint_ls(ls)
    assert r["software"] == "SAINT V8.42"
    assert r["reflns_used"] == 9996            # the 'All' row wins
    assert r["theta_min"] == 2.702 and r["theta_max"] == 31.121
    assert r["cell"][0] == 10.1554
    assert r["cell_esd"] == [0.0017, 0.0021, 0.0035, 0.0021, 0.0021, 0.0024]


# --------------------------------------------------------------------------- #
# ingest_vendor_data: HKLF code follows the chosen data (p770 twin trap)
# --------------------------------------------------------------------------- #

def _hkl_line(h, k, l, i=100.0, s=5.0, batch=None):
    row = f"{h:4d}{k:4d}{l:4d}{i:8.2f}{s:8.2f}"
    return row + (f"{batch:4d}\n" if batch is not None else "\n")


def _write_twin_hkl(path, lead=40, n_dom=2):
    # real TWINABS exports often sort domain-1 rows first: the 30-line
    # sniff alone would misclassify this file
    rows = [_hkl_line(1, 1, i % 9, batch=1) for i in range(lead)]
    for i in range(12):
        rows.append(_hkl_line(2, 1, i % 7, batch=-n_dom))
        rows.append(_hkl_line(2, 1, i % 7, batch=1))
    path.write_text("".join(rows), encoding="ascii")


def test_hklf5_batch_count(tmp_path):
    twin = tmp_path / "twin.hkl"
    _write_twin_hkl(twin, lead=40)
    assert tf.hklf5_batch_count(twin) == 2
    assert not tf.looks_like_shelx_hkl(twin)["hklf5_batches"]  # sniff misses

    plain = tmp_path / "plain.hkl"
    plain.write_text("".join(_hkl_line(1, 2, i) for i in range(10)),
                     encoding="ascii")
    assert tf.hklf5_batch_count(plain) == 0

    ones = tmp_path / "ones.hkl"                 # batch column of all 1s
    ones.write_text("".join(_hkl_line(1, 2, i, batch=1) for i in range(10)),
                    encoding="ascii")
    assert tf.hklf5_batch_count(ones) == 0

    # positive-only 1..7 = SAINT scan/scale batches on HKLF4 data, NOT twin
    # domains (HKLF5 marks composites with negative numbers). r14a live-fire:
    # an 8-batch scale column was misread as a 7-domain twin.
    scaled = tmp_path / "scaled.hkl"
    scaled.write_text("".join(_hkl_line(1, 2, i, batch=(i % 7) + 1)
                              for i in range(20)), encoding="ascii")
    assert tf.hklf5_batch_count(scaled) == 0
    assert tf.scale_batch_max(scaled) == 7
    assert not tf.looks_like_shelx_hkl(scaled)["hklf5_batches"]
    assert tf.scale_batch_max(tmp_path / "twin.hkl") == 0  # true HKLF5


class _IngestProject:
    def __init__(self, d):
        self.dir = d
        self.context = {}

    def reload_inputs(self):
        return {"node": "n0001", "n_atoms": 0, "merge": {}}


def _ingest_src(tmp_path):
    src = tmp_path / "vendor"
    src.mkdir()
    (src / "a.p4p").write_text(
        "CELL 8.3633 10.0945 15.0989 90.0 105.37 90.0 1227.9\n"
        "CELLSD 0.001 0.001 0.002 0.0 0.01 0.0 0.5\n"
        "SOURCE MO 0.71073 0.70930\n", encoding="ascii")
    return src


def test_ingest_hklf5_generates_hklf5_start(tmp_path):
    src = _ingest_src(tmp_path)
    _write_twin_hkl(src / "twin.hkl", lead=40, n_dom=2)
    proj = _IngestProject(tmp_path / "proj")
    proj.dir.mkdir()
    r = tf.IngestVendorData(proj).run(
        SimpleNamespace(session=None), source_dir=str(src), ins="-")
    assert r.ok, r.error
    ins = (proj.dir / "start.ins").read_text(encoding="ascii")
    assert "HKLF 5" in ins and "HKLF 4" not in ins
    assert "BASF 0.5000" in ins and "TWIN" not in ins
    assert r.summary["hkl_candidates"]["twin.hkl"] == "HKLF5-batched"
    assert r.summary["hklf5"]["n_domains"] == 2
    assert "run_shelxl" in r.summary["hklf5"]["note"]


def test_ingest_hklf4_regression_and_twin_note(tmp_path):
    src = _ingest_src(tmp_path)
    (src / "plain.hkl").write_text(
        "".join(_hkl_line(1, 2, i) for i in range(10)), encoding="ascii")
    _write_twin_hkl(src / "twin.hkl", lead=5)
    proj = _IngestProject(tmp_path / "proj")
    proj.dir.mkdir()
    # auto-selection picks the single plain candidate; the twin file must
    # be surfaced as a note, not silently skipped
    r = tf.IngestVendorData(proj).run(
        SimpleNamespace(session=None), source_dir=str(src), ins="-")
    assert r.ok, r.error
    ins = (proj.dir / "start.ins").read_text(encoding="ascii")
    assert "HKLF 4" in ins and "BASF" not in ins
    assert "hklf5" not in r.summary
    assert "twin.hkl" in r.summary["twin_data_note"]


def test_ingest_hklf_mismatch_warning(tmp_path):
    src = _ingest_src(tmp_path)
    _write_twin_hkl(src / "twin.hkl", lead=5)
    (src / "twin.ins").write_text(
        "TITL user start\nCELL 0.71073 8.36 10.09 15.10 90 105.4 90\n"
        "ZERR 1 0 0 0 0 0 0\nLATT 1\nSFAC C\nUNIT 4\nHKLF 4\nEND\n",
        encoding="ascii")
    proj = _IngestProject(tmp_path / "proj")
    proj.dir.mkdir()
    r = tf.IngestVendorData(proj).run(
        SimpleNamespace(session=None), source_dir=str(src))
    assert r.ok, r.error
    assert "HKLF 4" in r.summary["hklf_mismatch"]
    assert "twin.hkl" in r.summary["hklf_mismatch"]


ABS_FIXTURE = """\
 TWINABS - Bruker AXS scaling for twinned crystals - Version 2012/1
 ------------------------------------------------------------------
 noise
 Minimum and maximum apparent transmission:  0.414275  0.746241
 more noise
 HKLF 5 dataset constructed from all observations involving domain 1
 Minimum and maximum apparent transmission:  0.413136  0.746241
 Additional spherical absorption correction applied with mu*r =  0.2000
"""


def test_parse_sadabs_abs(tmp_path):
    p = tmp_path / "a.abs"
    p.write_text(ABS_FIXTURE, encoding="ascii")
    d = tf.parse_sadabs_abs(p)
    assert d["type"] == "multi-scan"
    assert d["t_min"] == 0.413136 and d["t_max"] == 0.746241  # last wins
    assert "TWINABS" in d["details"] and "Version 2012/1" in d["details"]
    assert "mu*r=0.2000" in d["details"]

    bad = tmp_path / "b.abs"
    bad.write_text("some other program output\n", encoding="ascii")
    assert tf.parse_sadabs_abs(bad) is None


def test_ingest_picks_up_abs_absorption_and_dotls(tmp_path):
    import json
    src = _ingest_src(tmp_path)
    (src / "plain.hkl").write_text(
        "".join(_hkl_line(1, 2, i) for i in range(10)), encoding="ascii")
    (src / "plain.abs").write_text(ABS_FIXTURE, encoding="ascii")
    # real Bruker name: 'name._ls' - must be globbed despite not matching
    # '*.ls' (regression: the mining silently never fired on vendor dirs)
    (src / "plain_0m._ls").write_text(
        "SAINT V8.42\n"
        "Unconstrained global unit cell refinement ====== 01/01/2026\n"
        "Reflection Summary:\n"
        " Component     Input  RLV.Excl      Used  WorstRes   BestRes"
        "   Min.2Th   Max.2Th\n"
        "       All      9996         0      9996    7.5386    0.6876"
        "     5.404    62.242\n",
        encoding="ascii")
    proj = _IngestProject(tmp_path / "proj")
    proj.dir.mkdir()
    r = tf.IngestVendorData(proj).run(
        SimpleNamespace(session=None), source_dir=str(src), ins="-")
    assert r.ok, r.error
    assert "plain.abs" in r.summary["absorption_abs"]
    assert "plain_0m._ls" in r.summary["saint_ls"]
    ctx = json.loads((proj.dir / "context.json").read_text(encoding="utf-8"))
    ab = ctx["experiment"]["absorption"]
    assert ab["type"] == "multi-scan"
    assert ab["t_min"] == 0.413136 and ab["t_max"] == 0.746241
    assert "TWINABS" in ab["details"]
    cm = ctx["experiment"]["cell_measurement"]
    assert cm["reflns_used"] == 9996
    assert ctx["experiment"]["computing"]["data_reduction"] == "SAINT V8.42"


CRYSTAL_INI = """\
[Peak table]
skipped usable nobs peakcount percent=0 1035 1017 1035 98.26
[Lattice]
constants plus vol=8.8770990  6.9434946 16.4330544 89.9916699 98.1586520 89.9911174 1002.65
error on constants plus vol=0.0020701  0.0022494 0.0034114 0.0215210 0.0182030 0.0226538 0.4497
[Constrained lattice]
constants plus vol - CCD=0.0000000  0.0000000 0.0000000 0.0000000 0.0000000 0.0000000 0.0000000
constants plus vol=8.8844298  6.9314109 16.4506232 90.0000000 98.2192636 90.0000000 1002.65
error on constants plus vol=0.0023183  0.0029112 0.0040697 0.0000000 0.0246723 0.0000000 0.45
[Gral lattice]
lattice type="C-lattice"
[Reduced cell]
reduced cell plus vol=5.614  5.630 16.465 83.53 83.80 76.47 500.97
"""


def test_parse_crysalis_crystal_ini(tmp_path):
    p = tmp_path / "expinfo" / "x_crystal.ini"
    p.parent.mkdir()
    p.write_text(CRYSTAL_INI, encoding="ascii")
    v = tf.parse_crysalis_crystal_ini(p)
    # constrained cell preferred over the unconstrained [Lattice] fit
    assert v["cell"][0] == 8.8844298 and v["cell"][4] == 98.2192636
    assert v["cell_esd"][0] == 0.0023183
    assert v["centring"] == "C"
    # frames dir is usually a sibling of expinfo/: parent walk finds it
    frames = tmp_path / "frames"
    frames.mkdir()
    assert tf.find_vendor_cell(frames)["cell"][0] == 8.8844298

    # all-zero constrained block falls back to [Lattice]
    p2 = tmp_path / "y_crystal.ini"
    p2.write_text(CRYSTAL_INI.replace(
        "constants plus vol=8.8844298  6.9314109 16.4506232 90.0000000 "
        "98.2192636 90.0000000 1002.65",
        "constants plus vol=0.0 0.0 0.0 0.0 0.0 0.0 0.0"), encoding="ascii")
    v2 = tf.parse_crysalis_crystal_ini(p2)
    assert v2["cell"][0] == 8.877099


def test_run_shelxt_refuses_hklf5(tmp_path):
    from crystalpilot.refine import tools_extra as te
    twin = tmp_path / "crystal.hkl"
    _write_twin_hkl(twin, lead=40)
    proj = SimpleNamespace(dir=tmp_path, hkl_path=twin)
    ses = SimpleNamespace(dataset=object(), symmetry=None, model=None)
    r = te.RunShelxt(proj).run(SimpleNamespace(session=ses))
    assert not r.ok
    assert "HKLF5-batched (2 domains)" in r.error
    assert "solve_charge_flipping" in r.error


# --------------------------------------------------------------------------- #
# run_shelxt: composition-missing message must surface a disclosed ins SFAC
# (ka1 WP2 Part A point 2) instead of a bare "no element list available"
# --------------------------------------------------------------------------- #

def _shelxt_ready(tmp_path, monkeypatch, ins_elements=None):
    """A session/project pair that clears every check in RunShelxt.run()
    before the composition/UNIT section (no dataset issue, no HKLF5 batch,
    real crystal symmetry, a real shelxt.exe path) - so the ONLY thing
    still missing is composition, which is exactly what these tests probe."""
    from cctbx import crystal
    plain = tmp_path / "crystal.hkl"
    plain.write_text("".join(_hkl_line(1, 1, i) for i in range(8)),
                     encoding="ascii")
    fake_exe = tmp_path / "shelxt.exe"
    fake_exe.write_bytes(b"")
    monkeypatch.setenv("CRYSTALPILOT_SHELXT", str(fake_exe))
    proj = SimpleNamespace(dir=tmp_path, hkl_path=plain)
    cs = crystal.symmetry(unit_cell=(10, 11, 12, 90, 90, 90),
                          space_group_symbol="P 1")
    ses = SimpleNamespace(dataset=SimpleNamespace(wavelength=0.71073),
                          symmetry=cs, model=None,
                          flags=({"ins_elements": ins_elements}
                                 if ins_elements is not None else {}))
    return proj, ses


def test_run_shelxt_composition_missing_names_a_placeholder_ins_sfac(
        tmp_path, monkeypatch):
    from crystalpilot.refine import tools_extra as te
    proj, ses = _shelxt_ready(tmp_path, monkeypatch, ins_elements={
        "elements": ["C", "H", "N", "O"], "unit": [1.0, 1.0, 1.0, 1.0],
        "unit_is_placeholder": True, "source": "start.ins SFAC/UNIT",
        "note": "vendor/cold-start declaration, not evidence"})
    r = te.RunShelxt(proj).run(SimpleNamespace(session=ses))
    assert not r.ok
    assert "the ins declares SFAC C H N O" in r.error
    assert "UNIT 1 1 1 1 is a placeholder, not a formula" in r.error
    assert "composition='C H N O'" in r.error
    assert "phasing aid, not an element claim" in r.error


def test_run_shelxt_composition_missing_names_a_non_placeholder_ins_sfac(
        tmp_path, monkeypatch):
    from crystalpilot.refine import tools_extra as te
    proj, ses = _shelxt_ready(tmp_path, monkeypatch, ins_elements={
        "elements": ["Zn", "O", "C", "N"], "unit": [4.0, 32.0, 16.0, 8.0],
        "unit_is_placeholder": False, "source": "start.ins SFAC/UNIT",
        "note": "vendor/cold-start declaration, not evidence"})
    r = te.RunShelxt(proj).run(SimpleNamespace(session=ses))
    assert not r.ok
    assert "the ins declares SFAC Zn O C N" in r.error
    assert "not confirmed evidence" in r.error
    assert "placeholder" not in r.error
    assert "composition='Zn O C N'" in r.error


def test_run_shelxt_composition_missing_without_any_ins_disclosure(
        tmp_path, monkeypatch):
    """No ins_elements flag at all (e.g. the project never ingested a
    vendor ins with a real SFAC card) - keep the original message, plus
    one sentence on where elements normally come from."""
    from crystalpilot.refine import tools_extra as te
    proj, ses = _shelxt_ready(tmp_path, monkeypatch, ins_elements=None)
    r = te.RunShelxt(proj).run(SimpleNamespace(session=ses))
    assert not r.ok
    assert "no element list available - pass composition=" in r.error
    assert "elements normally come from set_experiment" in r.error
    assert "ingest_vendor_data(ins=...)" in r.error


# --------------------------------------------------------------------------- #
# _import_arguments: normalized-link cache must follow the CURRENT selection
# --------------------------------------------------------------------------- #

def _mk_unpadded_frames(root: Path, n: int) -> list[str]:
    """n tiny frames with mixed-width numbering (1..n unpadded) so
    _import_arguments must take the hardlink-normalization path; paths are
    padded long enough to overflow the 25000-char argv threshold."""
    d = root / ("f" * 40)
    d.mkdir(parents=True, exist_ok=True)
    out = []
    for i in range(1, n + 1):
        p = d / f"scan{i}.rodhypix"
        p.write_bytes(b"x")
        out.append(str(p))
    return out


def test_import_arguments_drops_stale_links_on_reimport(tmp_path):
    """r11 case-c live defect: re-import with a narrower scan selection kept
    serving every previously-linked frame (iterdir-based rebuild), while the
    summary honestly reported the exclusion - the agent had to delete
    frames_normalized/ by hand. The link dir must now sync to the input."""
    frames = _mk_unpadded_frames(tmp_path / "src", 400)
    work = tmp_path / "work"
    work.mkdir()

    full, info1 = tf._import_arguments(frames, work)
    link_dir = Path(info1["frames_normalized_dir"])
    assert len(list(link_dir.iterdir())) == 400

    subset = frames[:250]
    args2, info2 = tf._import_arguments(subset, work)
    remaining = list(link_dir.iterdir())
    assert len(remaining) == 250, (
        f"stale links survived: {len(remaining)} in cache for 250 inputs")
    assert any("stale" in n for n in info2["notes"])


def test_import_arguments_full_set_reimport_is_stable(tmp_path):
    frames = _mk_unpadded_frames(tmp_path / "src", 400)
    work = tmp_path / "work"
    work.mkdir()
    _, info1 = tf._import_arguments(frames, work)
    _, info2 = tf._import_arguments(frames, work)
    assert info1["templates"] == info2["templates"]
    assert not any("stale" in n for n in info2["notes"])


class TestDialsAbsorptionRecord:
    def test_corrections_table_row_parsed(self):
        from crystalpilot.refine.tools_frames import _dials_absorption_record
        log = ("| correction   |   n_parameters |\n"
               "|--------------+----------------|\n"
               "| scale        |             10 |\n"
               "| decay        |              9 |\n"
               "| absorption   |             24 |\n")
        rec = _dials_absorption_record(log)
        assert rec["type"] == "empirical"
        assert "24 parameters" in rec["details"]

    def test_no_absorption_row_returns_none(self):
        from crystalpilot.refine.tools_frames import _dials_absorption_record
        assert _dials_absorption_record("| scale | 10 |\n") is None


def test_hkl_trailer_text_not_parsed_as_domains(tmp_path):
    """r14b live-fire: text after the all-zero terminator (the SHELX
    citation, '...48 (2015) 3-10') was scanned as reflections and a
    page range became domain -10 -> a plain 3-scan-batch HKLF4 file
    classified as a 10-domain twin."""
    p = tmp_path / "trailer.hkl"
    rows = [_hkl_line(1, 2, i, batch=(i % 3) + 1) for i in range(12)]
    rows.append(_hkl_line(0, 0, 0, batch=0))
    p.write_text("".join(rows)
                 + " Sheldrick SHELX\n J. Appl. Cryst. 48 (2015) 3-10\n"
                 + "   1   1   1  100.00    5.00  -4\n",  # junk past end
                 encoding="ascii")
    assert tf.hklf5_batch_count(p) == 0
    assert tf.scale_batch_max(p) == 3


def test_hkl_trailer_absorption_parsed(tmp_path):
    """r14b: SADABS appends CIF absorption items after the terminator and
    SHELXL silently copies them into ACTA output - ingest must surface the
    channel so the agent's prose matches its own delivered CIF."""
    p = tmp_path / "t.hkl"
    rows = [_hkl_line(1, 2, i, batch=1) for i in range(6)]
    rows.append(_hkl_line(0, 0, 0, batch=0))
    p.write_text("".join(rows) + (
        " _exptl_absorpt_process_details\n"
        ")\n"
        " SADABS 2016/2: Krause, L. et al.,\n"
        " J. Appl. Cryst. 48 (2015) 3-10\n"
        ")\n"
        " _exptl_absorpt_correction_type   multi-scan\n"
        " _exptl_absorpt_correction_T_max  0.7463\n"
        " _exptl_absorpt_correction_T_min  0.6651\n"),
        encoding="ascii")
    t = tf.parse_hkl_trailer_cif(p)
    assert t is not None
    assert t["type"] == "multi-scan"
    assert t["t_min"] == 0.6651 and t["t_max"] == 0.7463
    assert "SADABS 2016/2" in t["details"]

    plain = tmp_path / "plain.hkl"
    plain.write_text("".join(_hkl_line(1, 2, i) for i in range(5)),
                     encoding="ascii")
    assert tf.parse_hkl_trailer_cif(plain) is None


# --------------------------------------------------------------------------- #
# index_frames: noise-flood ladder params (strongest_n / fft3d_rmsd_cutoff)
# --------------------------------------------------------------------------- #

def test_index_frames_strongest_n_and_cutoff_wiring(tmp_path, monkeypatch):
    proj = _FakeProject(tmp_path)
    tool = tf.IndexFrames(proj)
    wd = tool.workdir
    (wd / "imported.expt").write_bytes(b"x")
    (wd / "strong.refl").write_bytes(b"x")
    seen = {"pycode": None, "args": None}

    class FakeRunner:
        def run_pycode(self, stage, code, timeout=300.0):
            seen["pycode"] = code
            # the tool checks for the filtered file before proceeding
            (wd / "strong_filtered.refl").write_bytes(b"x")
            return "8000\n"

        def run(self, stage, prog, args, progress=None):
            seen["args"] = args
            (wd / "indexed.expt").write_text('{"crystal": [{}]}')
            (wd / "indexed.refl").write_bytes(b"x")
            return "ok"

        def refl_count(self, refl, flag=None):
            return 4000

    monkeypatch.setattr(tool, "_dials_env", lambda *_a, **_k: object())
    monkeypatch.setattr(tool, "_runner", lambda *_a, **_k: FakeRunner())
    r = tool.run(SimpleNamespace(session=None), strongest_n=8000,
                 fft3d_rmsd_cutoff=3, max_lattices=2)
    assert r.ok, r.error
    assert "argsort(-I)[:8000]" in seen["pycode"]
    assert "strong_filtered.refl" in seen["args"][1]
    assert "max_lattices=2" in seen["args"]
    assert "indexing.fft3d.rmsd_cutoff=3" in seen["args"]
    assert r.summary["strongest_n"] == 8000
    assert "noise-flood" in r.summary["spot_filter_note"]


def test_index_frames_schema_has_ladder_params():
    schema = tf.IndexFrames(_FakeProject(Path(".")))
    props = schema.params_schema["properties"]
    assert "strongest_n" in props and "fft3d_rmsd_cutoff" in props


def test_keep_lattice_keeps_all_sweeps_of_chosen_crystal(tmp_path,
                                                         monkeypatch):
    """r15 live failure: joint indexing of 3 sweeps x 2 lattices = 6
    experiment rows sharing 2 crystals; keep_lattice=0 must keep rows
    0,1,2 (all sweeps of crystal 0), not just split_0."""
    proj = _FakeProject(tmp_path)
    tool = tf.IndexFrames(proj)
    wd = tool.workdir
    (wd / "imported.expt").write_bytes(b"x")
    (wd / "strong.refl").write_bytes(b"x")
    seen = {"cmds": []}

    class FakeRunner:
        def run(self, stage, prog, args, progress=None):
            seen["cmds"].append((prog, list(args)))
            if prog == "dials.index":
                (wd / "indexed.expt").write_text(json.dumps({
                    "crystal": [{"a": 1}, {"b": 2}],
                    "experiment": [{"crystal": 0}, {"crystal": 0},
                                   {"crystal": 0}, {"crystal": 1},
                                   {"crystal": 1}, {"crystal": 1}]}))
                (wd / "indexed.refl").write_bytes(b"x")
            elif prog == "dials.split_experiments":
                for i in range(6):
                    (wd / f"split_{i}.expt").write_bytes(b"x")
                    (wd / f"split_{i}.refl").write_bytes(b"x")
            elif prog == "dials.combine_experiments":
                (wd / "indexed.expt").write_text(json.dumps({
                    "crystal": [{"a": 1}],
                    "experiment": [{"crystal": 0}, {"crystal": 0},
                                   {"crystal": 0}]}))
                (wd / "indexed.refl").write_bytes(b"x")
            return "ok"

        def refl_count(self, refl, flag=None):
            return 5000

    monkeypatch.setattr(tool, "_dials_env", lambda *_a, **_k: object())
    monkeypatch.setattr(tool, "_runner", lambda *_a, **_k: FakeRunner())
    r = tool.run(SimpleNamespace(session=None), keep_lattice=0)
    assert r.ok, r.error
    combine = [(p, a) for p, a in seen["cmds"]
               if p == "dials.combine_experiments"]
    assert len(combine) == 1
    args = combine[0][1]
    assert "split_0.expt" in args and "split_1.expt" in args \
        and "split_2.expt" in args
    assert "split_3.expt" not in args      # crystal 1's sweeps stay out
    assert "all 3 of its sweep(s)" in r.summary["lattice_note"]


# --------------------------------------------------------------------------- #
# export_twin_hklf5: orchestration wiring
# --------------------------------------------------------------------------- #

def _twin_indexed_all(wd, n_sweeps=3):
    exps = [{"crystal": 0} for _ in range(n_sweeps)] + \
           [{"crystal": 1} for _ in range(n_sweeps)]
    (wd / "indexed_all.expt").write_text(json.dumps({
        "crystal": [{"a": 1}, {"b": 2}], "experiment": exps}))
    (wd / "indexed_all.refl").write_bytes(b"x")


def test_export_twin_refuses_without_indexed_all(tmp_path):
    tool = tf.ExportTwinHklf5(_FakeProject(tmp_path))
    r = tool.run(SimpleNamespace(session=None))
    assert not r.ok and "indexed_all" in (r.error or "")


def test_export_twin_refuses_three_crystals(tmp_path, monkeypatch):
    tool = tf.ExportTwinHklf5(_FakeProject(tmp_path))
    wd = tool.workdir
    (wd / "indexed_all.expt").write_text(json.dumps({
        "crystal": [{}, {}, {}],
        "experiment": [{"crystal": i} for i in (0, 1, 2)]}))
    (wd / "indexed_all.refl").write_bytes(b"x")
    monkeypatch.setattr(tool, "_dials_env", lambda *_a, **_k: object())
    r = tool.run(SimpleNamespace(session=None))
    assert not r.ok and "exactly 2" in (r.error or "")


def test_export_twin_full_wiring(tmp_path, monkeypatch):
    tool = tf.ExportTwinHklf5(_FakeProject(tmp_path))
    wd = tool.workdir
    _twin_indexed_all(wd)
    seen = {"cmds": [], "pycode": None}
    # domain-A expt for the cell read
    dom_a = {"crystal": [{"real_space_a": [10, 0, 0],
                          "real_space_b": [0, 12, 0],
                          "real_space_c": [0, 0, 20],
                          "space_group_hall_symbol": "-P 1"}],
             "experiment": [{"crystal": 0}]}

    class FakeRunner:
        def run(self, stage, prog, args, progress=None):
            seen["cmds"].append((prog, list(args)))
            if prog == "dials.integrate":
                (wd / "twin_int.expt").write_text(json.dumps({
                    "crystal": [{}, {}],
                    "experiment": [{"crystal": 0}] * 3
                    + [{"crystal": 1}] * 3}))
                (wd / "twin_int.refl").write_bytes(b"x")
            elif prog == "dials.split_experiments":
                for i in range(6):
                    (wd / f"twin_split_{i}.expt").write_bytes(b"x")
                    (wd / f"twin_split_{i}.refl").write_bytes(b"x")
            elif prog == "dials.combine_experiments":
                tag = "A" if "twin_split_0.expt" in args else "B"
                (wd / f"twin_dom{tag}.expt").write_text(json.dumps(dom_a))
                (wd / f"twin_dom{tag}.refl").write_bytes(b"x")
            elif prog == "dials.scale":
                tag = "A" if "twin_domA.expt" in args else "B"
                (wd / f"twin_scaled{tag}.expt").write_bytes(b"x")
                (wd / f"twin_scaled{tag}.refl").write_bytes(b"x")
                return "Rmerge(I)  0.062\nCC half  0.969\n"
            return "ok"

        def run_pycode(self, stage, code, timeout=300.0):
            seen["pycode"] = code
            (wd / "twin5.hkl").write_bytes(b"x")
            (wd / "twin_major_clean.hkl").write_bytes(b"x")
            (wd / "twin5_report.json").write_text(json.dumps({
                "composites": 10, "major_clean": 100,
                "minor_singles_written": 5, "major_partial_dropped": 20,
                "minor_partial_dropped": 20, "minor_clean_available": 90,
                "intensity_divisor": 1.0, "n_batches": 3,
                "policy": "coverage"}))
            return "{}"

    monkeypatch.setattr(tool, "_dials_env", lambda *_a, **_k: object())
    monkeypatch.setattr(tool, "_runner", lambda *_a, **_k: FakeRunner())
    r = tool.run(SimpleNamespace(session=None), minor_policy="coverage")
    assert r.ok, r.error
    progs = [p for p, _ in seen["cmds"]]
    assert progs.count("dials.combine_experiments") == 2
    assert progs.count("dials.scale") == 2
    assert "hklf5_writer" in seen["pycode"] and "coverage" in seen["pycode"]
    s = r.summary
    assert s["overlap_census"]["composites"] == 10
    assert "twin_major_clean" in s["workflow_note"]
    assert "BASF 2" in s["workflow_note"]      # batch-3 caveat included
    assert "20 major-domain" in s["disclosure_note"]


def test_parse_scale_exclusions_signature():
    """The sum-vs-prf filter census that flags biased summation
    backgrounds (E1 experiment 2026-08-31)."""
    from crystalpilot.io.frames_dials import _parse_scale_exclusions
    log = (
        "Applying filter of min_isigi > -5.0, partiality > 0.25\n"
        "Removed 64 reflections below partiality threshold\n"
        "Removed 1583 intensity.sum.value reflections with I/Sig(I) < -5.0\n"
        "Removed 0 intensity.prf.value reflections with I/Sig(I) < -5.0\n"
        "Excluding 1647/7692 reflections\n"
        "Removed 86 reflections below partiality threshold\n"
        "Removed 1775 intensity.sum.value reflections with I/Sig(I) < -5.0\n"
        "Removed 0 intensity.prf.value reflections with I/Sig(I) < -5.0\n"
        "Excluding 1861/6679 reflections\n")
    c = _parse_scale_exclusions(log)
    assert c["excluded_rows"] == 1647 + 1861
    assert c["total_rows"] == 7692 + 6679
    assert c["removed_sum_isigi"] == 1583 + 1775
    assert c["removed_prf_isigi"] == 0
    assert c["removed_partiality"] == 64 + 86
    assert _parse_scale_exclusions("")["excluded_rows"] == 0


def test_dxtbx_plugin_odlegacy_layout():
    """The OD SAPPHIRE 3.0 legacy plugin (zn_dpnpp unlock, 2026-09-01):
    entry point with DAG parent FormatROD + version sync."""
    import re
    from crystalpilot.io import frames_dials as fd
    root = Path(fd.__file__).resolve().parent / "dxtbx_plugin"
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    assert '"FormatRODLegacy:FormatROD"' in pyproject
    assert 'crystalpilot_dxtbx_odlegacy:FormatRODLegacy' in pyproject
    assert '"crystalpilot_dxtbx_odlegacy"' in pyproject
    src = (root / "crystalpilot_dxtbx_odlegacy" / "__init__.py").read_text(
        encoding="utf-8")
    m = re.search(r'^__version__ = "([^"]+)"', src, re.M)
    assert m and m.group(1) == fd._PLUGIN_VERSION
    for hook in ("def understand", "def _read_ascii_header",
                 "3.0 <= v < 4.0"):
        assert hook in src


_ZN_FRAME = Path(r"H:/CrystalPilot/benchmark/data_ext2/frames_zn_dpnpp"
                 r"/frames/pg33_ZnDpNPP/frames/pg33_1_1.img")


@pytest.mark.skipif(
    not _ZN_FRAME.exists()
    or not Path(r"C:/Users/lenovo/miniforge3/envs/dials/python.exe").exists(),
    reason="zn_dpnpp frames or dials env not present")
def test_odlegacy_golden_geometry_and_decode(tmp_path):
    """Golden numbers from the pg33 dataset: header fields verified
    against fabio's independent parser and CAP's own XDS.INP (r21 prep,
    AUDIT 2026-09-01)."""
    import os
    import subprocess

    dials_py = Path(r"C:/Users/lenovo/miniforge3/envs/dials/python.exe")
    code = (
        "from crystalpilot_dxtbx_odlegacy import FormatRODLegacy as F\n"
        f"p = r'{_ZN_FRAME}'\n"
        "assert F.understand(p)\n"
        "f = F(p)\n"
        "bh = f._bin_header\n"
        "assert abs(bh['distance_mm'] - 55.0) < 1e-6\n"
        "assert abs(bh['alpha12_wavelength'] - 0.71073) < 1e-6\n"
        "assert abs(bh['real_px_size_x'] - 0.09676154) < 1e-6\n"
        "sa = f._gonio_start_angles\n"
        "assert abs(sa[0] - -105.0) < 1e-4     # OMEGA\n"
        "assert abs(sa[1] - -31.39398) < 1e-4  # THETA swing\n"
        "assert abs(sa[2] - -57.0) < 1e-4      # KAPPA\n"
        "assert abs(sa[3] - -60.0) < 1e-4      # PHI\n"
        "a = f.get_raw_data().as_numpy_array()\n"
        "assert a.shape == (1024, 1024)\n"
        "assert abs(float(a.mean()) - 275.5948) < 0.01\n"
        "print('OK')\n")
    env = dict(os.environ)
    env["PATH"] = str(dials_py.parent / "Library" / "bin") + os.pathsep \
        + env.get("PATH", "")
    r = subprocess.run([str(dials_py), "-c", code], capture_output=True,
                       text=True, timeout=300, env=env)
    assert r.returncode == 0, (r.stderr or r.stdout)[-800:]
    assert "OK" in r.stdout


def _touch_pair(d: Path, stem: str) -> None:
    (d / f"{stem}.expt").write_text("{}")
    (d / f"{stem}.refl").write_text("x")


def test_dials_split_pair_unpadded(tmp_path):
    _touch_pair(tmp_path, "split_3")
    a, b = tf._dials_split_pair(tmp_path, "split", 3)
    assert a.name == "split_3.expt" and b.name == "split_3.refl"


def test_dials_split_pair_two_digit_padding(tmp_path):
    # r21 signature: 22 experiments -> dials wrote twin_split_00..21,
    # the old lookup tried twin_split_0 then %03d and missed both
    _touch_pair(tmp_path, "twin_split_00")
    _touch_pair(tmp_path, "twin_split_21")
    a0, _ = tf._dials_split_pair(tmp_path, "twin_split", 0)
    a21, _ = tf._dials_split_pair(tmp_path, "twin_split", 21)
    assert a0.name == "twin_split_00.expt"
    assert a21.name == "twin_split_21.expt"
    assert a0.exists() and a21.exists()


def test_dials_split_pair_three_digit_and_legacy(tmp_path):
    _touch_pair(tmp_path, "split_007")
    a, _ = tf._dials_split_pair(tmp_path, "split", 7)
    assert a.name == "split_007.expt"
    missing, _ = tf._dials_split_pair(tmp_path, "split", 9)
    assert missing.name == "experiments_009.expt"   # legacy fallback probe
    assert not missing.exists()


def test_split_outputs_present_lists_disk_state(tmp_path):
    _touch_pair(tmp_path, "twin_split_00")
    _touch_pair(tmp_path, "twin_split_01")
    msg = tf._split_outputs_present(tmp_path, "twin_split")
    assert msg.startswith("2 file(s)") and "twin_split_00.expt" in msg


class TestEstimateResolutionHklFallback:
    """r22 gap #4: vendor-hkl projects got 'integrated.refl not found' from
    estimate_resolution although the brief pointed at it by name; both arms
    hand-wrote the same shell table via SHELL. The tool now degrades to a
    merging-statistics shell table on the session's unmerged intensities."""

    @staticmethod
    def _session(cell=(6, 7, 8, 90, 95, 90), d_min=1.0):
        from cctbx import crystal, miller
        from cctbx.array_family import flex
        cs = crystal.symmetry(unit_cell=cell, space_group_symbol="P 1")
        ms = miller.build_set(cs, anomalous_flag=False, d_min=d_min)
        d = ms.d_spacings().data()
        base = flex.double([1000.0 * (x ** 3) for x in d])
        jit = flex.double([1.0 + 0.02 * ((i % 5) - 2)
                           for i in range(base.size())])
        idx = ms.indices().concatenate(ms.indices())
        data = (base * jit).concatenate(base)
        sig = flex.sqrt(flex.abs(data)) + 1.0
        arr = miller.array(
            miller.set(cs, idx, anomalous_flag=False),
            data=data, sigmas=sig).set_observation_type_xray_intensity()
        return SimpleNamespace(dataset=SimpleNamespace(intensities=arr),
                               symmetry=None, flags={})

    def test_shell_table_from_session(self, tmp_path):
        ses = self._session()
        proj = SimpleNamespace(dir=tmp_path, session=ses)
        r = tf.EstimateResolution(proj).run(SimpleNamespace(session=ses))
        assert r.ok, r.error
        s = r.summary
        assert s["mode"] == "hkl_shells"
        assert len(s["shells"]) >= 6
        row = s["shells"][0]
        assert {"d_min", "completeness", "i_over_sigma"} <= set(row)
        assert s["suggested_d_min"] is not None
        # strong synthetic data: suggestion reaches the data edge
        assert s["suggested_d_min"] <= 1.2
        # P1-of-record data on a monoclinic-metric cell: Laue class is
        # upgraded to 2/m so completeness is not hemisphere-halved
        assert "2/m" in s["merge_laue_class"]
        assert "metric" in s["merge_laue_source"]

    def test_no_session_still_refuses_cleanly(self, tmp_path):
        proj = SimpleNamespace(dir=tmp_path, session=None)
        r = tf.EstimateResolution(proj).run(SimpleNamespace(session=None))
        assert not r.ok
        assert "integrate_frames" in (r.error or "")


CIF_OD_FIXTURE = """\
_audit_creation_date           2026-09-01
_audit_creation_method         'CrysAlisPro 1.171.44.85 (Rigaku OD, 2024)'
_computing_data_collection     'CrysAlis system CCD 1.171.36.21'
_computing_cell_refinement     'CrysAlisPro 1.171.44.85 (Rigaku OD, 2024)'
_computing_data_reduction      'CrysAlisPro 1.171.44.85 (Rigaku OD, 2024)'
_cell_length_a                  7.5443(2)
_cell_measurement_temperature   100.0(2)
_cell_measurement_reflns_used   28200
_cell_measurement_theta_min     3.7840
_cell_measurement_theta_max     37.3680
_exptl_absorpt_correction_T_min                   0.69339
_exptl_absorpt_correction_T_max                   1.00000
_exptl_absorpt_correction_type            multi-scan
_exptl_absorpt_process_details
_diffrn_ambient_temperature 100.0(2)
_diffrn_source 'fine-focus sealed X-ray tube'
_diffrn_source_type 'Enhance (Mo) X-ray Source'
_diffrn_radiation_type 'Mo K\a'
_diffrn_radiation_wavelength 0.71073
_diffrn_radiation_monochromator graphite
_diffrn_measurement_device_type 'Xcalibur, Atlas, Gemini ultra'
_diffrn_detector_type Atlas
"""


def test_parse_crysalis_cif_od(tmp_path):
    """A CrysAlisPro-reduced dataset used to arrive with '?' in every
    experimental slot (PLAT183/184/185 family) because nothing read the
    .cif_od record the vendor writes next to the hkl."""
    p = tmp_path / "pg33_autored.cif_od"
    p.write_text(CIF_OD_FIXTURE, encoding="ascii")
    d = tf.parse_crysalis_cif_od(p)
    assert d["temperature_K"] == 100.0          # esd in parens stripped
    assert d["absorption"] == {
        "type": "multi-scan", "t_min": 0.69339, "t_max": 1.0,
        "details": "CrysAlisPro 1.171.44.85 (Rigaku OD, 2024)"}
    assert d["instrument"]["diffractometer"].startswith("Xcalibur")
    assert d["instrument"]["wavelength_A"] == 0.71073
    assert d["cell_measurement"]["reflns_used"] == 28200
    assert isinstance(d["cell_measurement"]["reflns_used"], int)
    assert d["cell_measurement"]["theta_max"] == 37.368
    assert "CrysAlisPro" in d["computing"]["data_reduction"]


def test_parse_crysalis_cif_od_ignores_other_cifs(tmp_path):
    p = tmp_path / "x.cif_od"
    p.write_text("_audit_creation_method 'SHELXL-2018/3'\n"
                 "_diffrn_ambient_temperature 100\n", encoding="ascii")
    assert tf.parse_crysalis_cif_od(p) is None


def test_ingest_picks_up_crysalis_cif_od(tmp_path):
    import json
    src = _ingest_src(tmp_path)
    (src / "pg33_autored.hkl").write_text(
        "".join(_hkl_line(1, 2, i) for i in range(10)), encoding="ascii")
    (src / "pg33_autored.cif_od").write_text(CIF_OD_FIXTURE, encoding="ascii")
    proj = _IngestProject(tmp_path / "proj")
    proj.dir.mkdir()
    r = tf.IngestVendorData(proj).run(
        SimpleNamespace(session=None), source_dir=str(src), ins="-")
    assert r.ok, r.error
    assert r.summary["crysalis_cif_od"] == ["pg33_autored.cif_od"]
    exp = json.loads(
        (proj.dir / "context.json").read_text(encoding="utf-8"))["experiment"]
    assert exp["absorption"]["t_min"] == 0.69339
    assert exp["temperature_K"] == 100.0
    assert exp["instrument"]["detector"] == "Atlas"
    assert exp["cell_measurement"]["reflns_used"] == 28200


REAL_CIF_OD = (Path(__file__).resolve().parents[1] / "workdir"
               / "cap_tune1" / "exp" / "pg33_autored.cif_od")


@pytest.mark.skipif(not REAL_CIF_OD.exists(), reason="CAP products absent")
def test_parse_crysalis_cif_od_on_a_real_reduction():
    d = tf.parse_crysalis_cif_od(REAL_CIF_OD)
    assert d["absorption"]["t_min"] == 0.69339
    assert d["cell_measurement"]["reflns_used"] == 28200
    assert d["instrument"]["source"].startswith("Enhance")
