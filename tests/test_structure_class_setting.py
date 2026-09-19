"""Owner-declared structure class (round-2 R6): a plain per-project setting
that the analysis tab opens its blocks by and the agent reads from the
brief. Unknown values are refused at the settings boundary, never stored."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from crystalpilot.workbench.service import (STRUCTURE_CLASSES, ProjectSession,
                                            normalize_structure_class,
                                            project_settings_dict)


def test_normalize_accepts_the_known_classes_only():
    for c in STRUCTURE_CLASSES:
        assert normalize_structure_class(c) == c
        assert normalize_structure_class(f"  {c.upper()} ") == c
    assert normalize_structure_class(None) is None
    assert normalize_structure_class("") is None
    assert normalize_structure_class("protein") is None
    assert "framework" in STRUCTURE_CLASSES and "cage" in STRUCTURE_CLASSES


def test_settings_dict_carries_the_class_and_the_choices(tmp_path):
    d = project_settings_dict(tmp_path, {"structure_class": "cage"}, "auto")
    assert d["structure_class"] == "cage"
    assert d["structure_classes"] == list(STRUCTURE_CLASSES)
    d = project_settings_dict(tmp_path, {}, "auto")
    assert d["structure_class"] is None
    # a stale / foreign value on disk reads as undeclared, not as a crash
    d = project_settings_dict(tmp_path, {"structure_class": "zeolite"}, "auto")
    assert d["structure_class"] is None


def _stub():
    saved: list[int] = []
    project = SimpleNamespace(settings={}, save=lambda: saved.append(1),
                              path="x")
    stub = SimpleNamespace(wb=SimpleNamespace(project=project),
                           settings=lambda: dict(project.settings), saved=saved,
                           _sync_engine=lambda learned=None: None,
                           _push_settings=lambda: None)
    return stub


def test_update_persists_and_refuses_unknown_values():
    stub = _stub()
    out = ProjectSession.update_project_settings(
        stub, {"structure_class": "Macrocycle"})
    assert out["structure_class"] == "macrocycle"
    assert stub.saved == [1]
    ProjectSession.update_project_settings(stub, {"structure_class": None})
    assert stub.wb.project.settings["structure_class"] is None
    with pytest.raises(ValueError):
        ProjectSession.update_project_settings(
            stub, {"structure_class": "zeolite"})
    assert stub.wb.project.settings["structure_class"] is None


def test_brief_reads_the_declaration_live(tmp_path):
    import json
    from crystalpilot.refine.tools_extra import declared_structure_class
    assert declared_structure_class(tmp_path)["declared"] is None
    f = tmp_path / ".crystalpilot-workbench.json"
    f.write_text(json.dumps({"settings": {"structure_class": "framework"}}),
                 encoding="utf-8")
    d = declared_structure_class(tmp_path)
    assert d["declared"] == "framework" and "declared by the user" in d["note"]
    f.write_text("{not json", encoding="utf-8")
    assert declared_structure_class(tmp_path)["declared"] is None


# --------------------------------------------------------------- round-2 R7
def test_delegation_tier_in_settings_and_update(tmp_path, monkeypatch):
    """The sub-agent switch (2026-09-07): "auto" resolves to on exactly at
    the top rung of the model's ladder, "on"/"off" are the user's choice;
    on = the proactive AGENTS.md variant + the role files, off = the plain
    template and no roles. Legacy policy names still read."""
    from crystalpilot.workbench import service
    from crystalpilot.workbench.agents_md import (VERSION_MARKER,
                                                  VERSION_MARKER_AGGRESSIVE)
    monkeypatch.setattr(service, "_model_info",
                        lambda: {"model": "m", "effort": "high"})
    # model "m" is unknown everywhere: the gateway ladder applies (top: ultra)
    d = service.project_settings_dict(tmp_path, {}, "auto")
    assert d["subagents"] == "auto" and d["delegation"]["active"] is False
    assert d["effort_choices"] == list(service.EFFORT_CHOICES)
    assert d["delegation"]["top_effort"] == "ultra"
    assert d["delegation"]["auto_default"] is False and d["delegation"]["tier"] == "off"
    assert d["delegation"]["roles"] == ["chemistry", "density", "refinement_strategy",
                                        "space_group", "validation"]
    d = service.project_settings_dict(tmp_path, {"effort_override": "ultra"}, "auto")
    assert d["delegation"]["active"] is True and d["delegation"]["tier"] == "aggressive"
    assert d["delegation"]["auto_default"] is True
    d = service.project_settings_dict(tmp_path, {"effort_override": "xhigh"}, "auto")
    assert d["delegation"]["active"] is False
    d = service.project_settings_dict(
        tmp_path, {"effort_override": "low", "subagents": "on"}, "auto")
    assert d["delegation"]["active"] is True and d["subagents"] == "on"
    d = service.project_settings_dict(
        tmp_path, {"effort_override": "ultra", "subagents": "off"}, "auto")
    assert d["delegation"]["active"] is False and d["subagents"] == "off"
    # legacy names on disk, and garbage reads as the default - never a crash
    assert service.project_settings_dict(
        tmp_path, {"subagents": "aggressive"}, "auto")["subagents"] == "on"
    assert service.project_settings_dict(
        tmp_path, {"subagents": "top_tier"}, "auto")["subagents"] == "auto"
    assert service.project_settings_dict(
        tmp_path, {"subagents": "always"}, "auto")["subagents"] == "auto"

    pushed: list[dict] = []
    project = SimpleNamespace(settings={}, save=lambda: None, path=tmp_path,
                              agents_md={}, agent_roles={})
    stub = SimpleNamespace(wb=SimpleNamespace(project=project),
                           settings=lambda: dict(project.settings),
                           _push=lambda tid, ev: pushed.append(ev),
                           _refresh_delegation=lambda: service.ProjectSession._refresh_delegation(stub),
                           _sync_engine=lambda learned=None: None,
                           _push_settings=lambda: None)
    service.ProjectSession.update_project_settings(stub, {"subagents": "on"})
    agents = tmp_path / "AGENTS.md"
    roles = tmp_path / ".codex" / "agents"
    assert agents.read_text(encoding="utf-8").startswith(VERSION_MARKER_AGGRESSIVE)
    assert sorted(p.stem for p in roles.glob("*.toml")) == [
        "chemistry", "density", "refinement_strategy", "space_group", "validation"]
    assert pushed[-1]["kind"] == "delegation" and pushed[-1]["active"] is True
    assert pushed[-1]["tier"] == "aggressive"
    service.ProjectSession.update_project_settings(stub, {"subagents": "off"})
    assert agents.read_text(encoding="utf-8").startswith(VERSION_MARKER)
    assert list(roles.glob("*.toml")) == []
    assert pushed[-1]["active"] is False
    with pytest.raises(ValueError):
        service.ProjectSession.update_project_settings(stub, {"subagents": "always"})


def test_delegation_stays_on_above_xhigh(tmp_path, monkeypatch):
    """With the switch on "auto", only the ladder's TOP rung enables the
    sub-agents: on the gateway ladder that is ultra (max/ultra were added
    above xhigh on 2026-09-05), on the three-rung OpenRouter GLM ladder it
    is high."""
    from crystalpilot.workbench import service
    monkeypatch.setattr(service, "_model_info", lambda: {
        "model": "m", "effort": "high", "provider": "crystalpilot",
        "providers": ["crystalpilot", "openrouter"]})
    assert service.EFFORT_CHOICES[-2:] == ("max", "ultra")
    assert service.TOP_TIER_EFFORTS == ("xhigh", "max", "ultra")
    for eff, on in (("ultra", True), ("max", False), ("xhigh", False), ("high", False)):
        d = service.project_settings_dict(tmp_path, {"effort_override": eff}, "auto")
        assert d["delegation"]["active"] is on, eff
        assert d["delegation"]["top_effort"] == "ultra"
    d = service.project_settings_dict(
        tmp_path, {"model_provider_override": "openrouter",
                   "model_override": "z-ai/glm-5.3", "effort_override": "high"}, "auto")
    assert d["effort_choices"] == ["low", "medium", "high"]
    assert d["delegation"]["active"] is True and d["delegation"]["top_effort"] == "high"


