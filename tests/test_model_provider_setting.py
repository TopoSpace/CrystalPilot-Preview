"""Per-project model provider (2026-09-06): a second [model_providers.<id>]
in the isolated config.toml that a project can switch its NEW threads to.
Model and effort travel with every turn; the provider is fixed at thread
start, so the override reaches new threads only and the settings say so."""
from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

from crystalpilot.workbench import service

INFO = {"model": "gpt-6-astra", "effort": "xhigh", "provider": "crystalpilot",
        "providers": ["crystalpilot", "openrouter"]}


def test_config_lists_both_providers():
    info = service._model_info()
    assert info["provider"] == "crystalpilot"
    assert {"crystalpilot", "openrouter"} <= set(info["providers"])


def test_settings_dict_carries_the_provider(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "_model_info", lambda: dict(INFO))
    d = service.project_settings_dict(tmp_path, {}, "auto")
    assert d["model_provider"] == "crystalpilot"
    assert d["model_provider_override"] is None
    assert d["model_provider_default"] == "crystalpilot"
    assert d["model_providers"] == ["crystalpilot", "openrouter"]
    d = service.project_settings_dict(
        tmp_path, {"model_provider_override": "openrouter"}, "auto")
    assert d["model_provider"] == "openrouter"
    assert d["model_provider_override"] == "openrouter"


def _stub():
    project = SimpleNamespace(settings={}, save=lambda: None, path="x")
    # the engine-sync and settings-push hooks are no-ops on the stub: the
    # tests below check what is STORED, not the rebuild
    return SimpleNamespace(wb=SimpleNamespace(project=project),
                           settings=lambda: dict(project.settings),
                           _sync_engine=lambda learned=None: None,
                           _push_settings=lambda: None)


def test_update_accepts_known_providers_only(monkeypatch):
    monkeypatch.setattr(service, "_model_info", lambda: dict(INFO))
    stub = _stub()
    stub._refresh_delegation = lambda: None
    service.ProjectSession.update_project_settings(
        stub, {"model_provider_override": " openrouter "})
    assert stub.wb.project.settings["model_provider_override"] == "openrouter"
    with pytest.raises(ValueError):
        service.ProjectSession.update_project_settings(
            stub, {"model_provider_override": "nope"})
    assert stub.wb.project.settings["model_provider_override"] == "openrouter"
    service.ProjectSession.update_project_settings(
        stub, {"model_provider_override": None})
    assert stub.wb.project.settings["model_provider_override"] is None


def test_model_change_rerenders_the_roles(monkeypatch):
    """The sub-agent role files carry the project's model: a model_override
    patch must refresh delegation after the new value is stored (the spawn
    probe of 2026-09-06 15:40 ran a GLM parent's auditor on the config
    default gpt-6-astra because the roles were rendered before the model
    was applied)."""
    monkeypatch.setattr(service, "_model_info", lambda: dict(INFO))
    stub = _stub()
    seen: list = []
    stub._refresh_delegation = lambda: seen.append(
        dict(stub.wb.project.settings))
    service.ProjectSession.update_project_settings(
        stub, {"model_override": "z-ai/glm-5.3-flash", "subagents": "aggressive"})
    assert seen and seen[-1]["model_override"] == "z-ai/glm-5.3-flash"
    assert seen[-1]["subagents"] == "on"      # legacy "aggressive" reads as on


def test_new_task_passes_the_provider_to_thread_start(tmp_path):
    from crystalpilot.workbench.core import Workbench
    captured: dict = {}

    class FakeClient:
        def thread_start(self, params):
            captured["params"] = params
            return SimpleNamespace(thread=SimpleNamespace(id="t-%d" % len(captured)))

    wb = Workbench.__new__(Workbench)
    wb._client = FakeClient()
    wb._lock = threading.Lock()
    wb._task_by_thread = {}
    wb.project = SimpleNamespace(path=tmp_path, results_root=tmp_path / "res",
                                 threads=[], save=lambda: None, settings={})
    wb.new_task(title="x", model_provider="openrouter")
    p = captured["params"]
    assert p.model_provider == "openrouter"
    assert p.model_dump(by_alias=True, exclude_none=True)["modelProvider"] == "openrouter"
    wb.new_task(title="y")
    assert captured["params"].model_provider is None
    assert captured["params"].config is None
    assert "view_image" not in captured["params"].developer_instructions
    # a text-only model: the developer instructions say why pictures are
    # off (the view_image tool itself is removed at the process level -
    # core._engine_overrides - since a thread-level config is not honoured)
    wb.new_task(title="z", model_provider="openrouter", images=False)
    p = captured["params"]
    assert p.config is None
    assert "never call view_image" in p.developer_instructions
    # third-party providers get the tool-namespace sentence, the default
    # provider (gateway GPT) keeps its instructions unchanged
    assert "namespace `mcp__crystalpilot`" in p.developer_instructions
    assert "unsupported call" in p.developer_instructions
    wb.new_task(title="w")
    assert "mcp__crystalpilot" not in captured["params"].developer_instructions
    assert "config" not in p.model_dump(by_alias=True, exclude_none=True)


def test_auth_hook_reads_the_file_named_by_cred(tmp_path, monkeypatch, capsys):
    from crystalpilot.workbench import print_token as pt
    monkeypatch.setattr(pt, "_caller_looks_legitimate", lambda: True)
    f = tmp_path / "other.txt"
    f.write_text("Provider: x\nKey: tok-123\n", encoding="utf-8")
    assert pt.main(["--cred", str(f)]) == 0
    assert capsys.readouterr().out == "tok-123"
    assert pt.main(["--cred", str(tmp_path / "missing.txt")]) == 1
    err = capsys.readouterr().err
    assert "missing.txt" in err and "tok-123" not in err
    assert pt.credential_file([]) == pt.CRED_FILE


# ------------------------------------------------- provider effort ladders
def test_ladders_and_tiers():
    assert service.effort_ladder(None) == service.EFFORT_CHOICES
    assert service.effort_ladder("crystalpilot") == service.EFFORT_CHOICES
    assert service.effort_ladder("openrouter") == ("low", "medium", "high")
    top, aggr = service.tiers_for(service.EFFORT_CHOICES)
    assert top == ("xhigh", "max", "ultra") and aggr == ("max", "ultra")
    top, aggr = service.tiers_for(("low", "medium", "high"))
    assert top == ("high",) and aggr == ("high",)


def test_openrouter_project_tiers_at_high(tmp_path, monkeypatch):
    """The sub-agent switch follows the MODEL's ladder: the GLM models
    (custom catalog entries) end at high, the gateway's gpt-6-astra at
    ultra; "auto" is on only at that top rung, "on"/"off" override it."""
    monkeypatch.setattr(service, "_model_info", lambda: dict(INFO))
    base = {"model_provider_override": "openrouter", "model_override": "z-ai/glm-5.3",
            "effort_override": "high"}
    d = service.project_settings_dict(tmp_path, dict(base), "auto")
    assert d["effort_choices"] == ["low", "medium", "high"]
    assert d["delegation"]["top_effort"] == "high"
    assert d["delegation"]["tier"] == "aggressive" and d["delegation"]["active"] is True
    d = service.project_settings_dict(tmp_path, {**base, "subagents": "off"}, "auto")
    assert d["delegation"]["tier"] == "off"
    d = service.project_settings_dict(tmp_path, {**base, "effort_override": "medium"}, "auto")
    assert d["delegation"]["tier"] == "off" and d["delegation"]["auto_default"] is False
    d = service.project_settings_dict(
        tmp_path, {**base, "effort_override": "medium", "subagents": "on"}, "auto")
    assert d["delegation"]["tier"] == "aggressive"
    # the gateway project: the catalog ladder of gpt-6-astra, top rung ultra
    d = service.project_settings_dict(tmp_path, {"effort_override": "ultra"}, "auto")
    assert d["delegation"]["tier"] == "aggressive" and d["effort_choices"][-1] == "ultra"
    d = service.project_settings_dict(tmp_path, {"effort_override": "xhigh"}, "auto")
    assert d["delegation"]["tier"] == "off" and d["effort"] == "xhigh"
    assert d["model_info"]["in_catalog"] is True and d["model_info"]["context_window"] == 272000


def test_provider_change_revalidates_the_effort(monkeypatch):
    monkeypatch.setattr(service, "_model_info", lambda: dict(INFO))
    stub = _stub()
    stub._refresh_delegation = lambda: None
    service.ProjectSession.update_project_settings(stub, {"effort_override": "xhigh"})
    # a provider switch alone keeps the model and therefore its ladder
    service.ProjectSession.update_project_settings(
        stub, {"model_provider_override": "openrouter"})
    assert stub.wb.project.settings["effort_override"] == "xhigh"
    # the GLM model's ladder ends at high: the stored effort snaps to the top
    # rung explicitly rather than staying a value the provider would remap
    service.ProjectSession.update_project_settings(stub, {"model_override": "z-ai/glm-5.3"})
    assert stub.wb.project.settings["effort_override"] == "high"
    with pytest.raises(ValueError):
        service.ProjectSession.update_project_settings(stub, {"effort_override": "xhigh"})
    # a provider + model + effort patch is validated against the new ladder
    service.ProjectSession.update_project_settings(
        stub, {"model_provider_override": None, "model_override": None,
               "effort_override": "xhigh"})
    assert stub.wb.project.settings["effort_override"] == "xhigh"
    assert stub.wb.project.settings["model_provider_override"] is None


