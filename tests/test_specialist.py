"""Gating tests for consult_specialist (no harness spawned here - the real
nested-turn E2E lives in workdir/smoke_specialist.py because it costs a full
model conversation)."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from crystalpilot.refine.tools_specialist import (ConsultSpecialist,
                                                  specialists_enabled)


def _proj(tmp_path, settings=None):
    if settings is not None:
        (tmp_path / ".crystalpilot-workbench.json").write_text(
            json.dumps({"threads": [], "settings": settings}),
            encoding="utf-8")
    return SimpleNamespace(dir=tmp_path)


def test_disabled_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("CRYSTALPILOT_SPECIALISTS", raising=False)
    monkeypatch.delenv("CRYSTALPILOT_MCP_READONLY", raising=False)
    assert not specialists_enabled(tmp_path)


def test_enabled_by_project_setting(tmp_path, monkeypatch):
    monkeypatch.delenv("CRYSTALPILOT_SPECIALISTS", raising=False)
    monkeypatch.delenv("CRYSTALPILOT_MCP_READONLY", raising=False)
    _proj(tmp_path, {"enable_specialists": True})
    assert specialists_enabled(tmp_path)


def test_enabled_by_env(tmp_path, monkeypatch):
    monkeypatch.setenv("CRYSTALPILOT_SPECIALISTS", "1")
    monkeypatch.delenv("CRYSTALPILOT_MCP_READONLY", raising=False)
    assert specialists_enabled(tmp_path)


def test_no_recursion_inside_readonly_specialist(tmp_path, monkeypatch):
    monkeypatch.setenv("CRYSTALPILOT_SPECIALISTS", "1")
    monkeypatch.setenv("CRYSTALPILOT_MCP_READONLY", "1")
    assert not specialists_enabled(tmp_path)


def test_typed_refusal_when_disabled(tmp_path, monkeypatch):
    monkeypatch.delenv("CRYSTALPILOT_SPECIALISTS", raising=False)
    monkeypatch.delenv("CRYSTALPILOT_MCP_READONLY", raising=False)
    tool = ConsultSpecialist(_proj(tmp_path))
    r = tool.run(SimpleNamespace(session=None), specialty="density",
                 question="test")
    assert not r.ok
    assert "disabled" in r.error and "enable_specialists" in r.error


def test_unknown_specialty_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("CRYSTALPILOT_SPECIALISTS", "1")
    tool = ConsultSpecialist(_proj(tmp_path))
    r = tool.run(SimpleNamespace(session=None), specialty="astrology",
                 question="test")
    assert not r.ok and "unknown specialty" in r.error


def test_registry_hides_tool_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("CRYSTALPILOT_SPECIALISTS", raising=False)
    monkeypatch.delenv("CRYSTALPILOT_MCP_READONLY", raising=False)
    from crystalpilot.refine.tools_specialist import register_specialist_tools

    class _Reg:
        def __init__(self):
            self.names = []

        def register(self, tool):
            self.names.append(tool.name)

    reg = _Reg()
    register_specialist_tools(reg, _proj(tmp_path))
    assert reg.names == []
    monkeypatch.setenv("CRYSTALPILOT_SPECIALISTS", "1")
    register_specialist_tools(reg, _proj(tmp_path))
    assert reg.names == ["consult_specialist"]
