"""Linux cold-start regression: live binary imports and executable MCP config."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest


@pytest.mark.skipif(os.name == "nt", reason="Linux/POSIX runtime")
def test_cold_numerical_runtime_does_not_crash():
    code = (
        "import json; from crystalpilot.mcp.prewarm import prewarm_heavy_imports; "
        "r=prewarm_heavy_imports(); print(json.dumps(r['failed']))"
    )
    result = subprocess.run([sys.executable, "-X", "faulthandler", "-c", code],
                            capture_output=True, text=True, timeout=30, check=False)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {}


@pytest.mark.skipif(os.name == "nt", reason="Linux/POSIX runtime")
def test_mcp_command_uses_executable_project_python(tmp_path):
    from crystalpilot.workbench.core import ENGINE_ROOT, _mcp_overrides
    from crystalpilot.workbench.providers import ENGINE_PY
    config = tomllib.loads("\n".join(_mcp_overrides(tmp_path, readonly=True)))
    server = config["mcp_servers"]["crystalpilot"]
    assert server["command"] == str(ENGINE_ROOT / ".venv/bin/python") == str(ENGINE_PY)
    assert os.access(server["command"], os.X_OK)
    assert server["env"]["CRYSTALPILOT_MCP_READONLY"] == "1"


@pytest.mark.skipif(os.name == "nt", reason="Linux/POSIX runtime")
def test_dials_subprocess_can_run_system_shell(tmp_path):
    from crystalpilot.io.frames_dials import DialsEnv
    env = DialsEnv(tmp_path, Path(sys.executable)).subprocess_env()
    result = subprocess.run(["sh", "-c", "printf DIALS-PATH-OK"], env=env,
                            capture_output=True, text=True, timeout=10, check=False)
    assert result.returncode == 0 and result.stdout == "DIALS-PATH-OK"


@pytest.mark.skipif(os.name == "nt", reason="Case-sensitive Linux paths")
def test_projects_with_different_case_remain_distinct(tmp_path, monkeypatch):
    from crystalpilot.workbench import registry
    from crystalpilot.workbench.service import WorkbenchPool
    upper, lower = tmp_path / "Crystal", tmp_path / "crystal"
    upper.mkdir()
    lower.mkdir()
    monkeypatch.setattr(registry, "REGISTRY_FILE", tmp_path / "projects.json")
    monkeypatch.setattr(registry, "CODEX_HOME", tmp_path)
    (tmp_path / "config.toml").write_text("")
    for project in (upper, lower):
        registry.record_recent(project)
        registry.ensure_trusted(project)
    assert len(registry.recent_projects()) == 2
    trusted = tomllib.loads((tmp_path / "config.toml").read_text())["projects"]
    assert str(upper) in trusted and str(lower) in trusted
    assert WorkbenchPool._key(upper) != WorkbenchPool._key(lower)


def test_native_platon_summary_omits_only_zero_levels():
    from crystalpilot.refine.checkcif_runner import complete_report
    report = (
        "# PLATON/CHECK-(synthetic native-format fixture)\n"
        "995_ALERT_1_G synthetic missing SHELXL warning\n"
        "ALERT_Level and ALERT_Type Summary\n"
        "1 ALERT_Level_G = General Info\n"
        "1 ALERT_Type_1 CIF Construction\n"
        "1 Unresolved or to be Checked Issue(s)\n"
    )
    log = ":: CheckCIF out on :model.chk\n"
    assert complete_report(report, log)
    assert not complete_report(report, "")
    assert not complete_report(report.replace("1 ALERT_Level_G", "0 ALERT_Level_G"), log)
    assert not complete_report(report.replace("1 ALERT_Type_1", "0 ALERT_Type_1"), log)
