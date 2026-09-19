"""Unit tests for the headless olex2c driver (no vendor binaries needed).

The live end-to-end smoke (boot + reap + refine) takes ~1 min and needs
vendor/olex2; it is gated behind CRYSTALPILOT_OLEX2C_LIVE=1 so the
default suite stays fast and vendor-free.
"""
import os
from pathlib import Path

import pytest

from crystalpilot.io.olex2c import (
    APP_DEFAULT, build_env, refine_job, strip_ansi, Olex2Console)


def test_strip_ansi_removes_escapes_and_cr():
    raw = "\x1b[0;94m\x1b[0;90mRefinement finished \r\r\n\x1b[60;3H>>"
    assert strip_ansi(raw) == "Refinement finished \n>>"


def test_build_env_scrubs_python_vars(monkeypatch):
    monkeypatch.setenv("PYTHONPATH", r"C:\ChemOffice\pollution")
    monkeypatch.setenv("PYTHONHOME", r"C:\elsewhere")
    monkeypatch.setenv("pythonstartup", "x")
    app = Path("H:/fake/app")
    env = build_env(app, Path("H:/fake/work/olex2data"))
    assert env["PYTHONHOME"] == str(app / "Python")
    assert "PYTHONPATH" not in env
    assert "pythonstartup" not in env
    assert env["OLEX2_DIR"] == str(app)
    assert env["OLEX2_CCTBX_DIR"] == str(app / "cctbx")
    # unrelated vars survive
    assert "PATH" in env or "Path" in env


def test_fwd_normalizes_backslashes():
    assert Olex2Console.fwd(r"H:\a\b c\d.res") == "H:/a/b c/d.res"


@pytest.mark.skipif(
    os.environ.get("CRYSTALPILOT_OLEX2C_LIVE") != "1"
    or not (APP_DEFAULT / "olex2c.dll").exists(),
    reason="live olex2c smoke: set CRYSTALPILOT_OLEX2C_LIVE=1 (needs vendor)")
def test_refine_job_live(tmp_path):
    import shutil
    probe = Path("H:/CrystalPilot/workdir/hklf5_probe")
    shutil.copy(probe / "probe_a.res", tmp_path / "job.res")
    shutil.copy(probe / "probe_a.hkl", tmp_path / "job.hkl")
    out = refine_job(tmp_path, cycles=2, refine_timeout_s=600)
    assert out["refinement_finished"], out["console_tail"]
    res_text = (tmp_path / "job.res").read_text(errors="replace")
    assert "REM R1_gt" in res_text or "REM R1 =" in res_text
