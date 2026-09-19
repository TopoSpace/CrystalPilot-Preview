from pathlib import Path
import tomllib

import pytest

from crystalpilot.llm.config import LLMConfig, ModelRouting, _from_env, build_provider


ROOT = Path(__file__).resolve().parents[1]


def test_codex_default_is_sol_at_xhigh():
    """The isolated codex config's default model is an owner decision:
    gpt-6-astra until 2026-09-08, then gpt-5.6-sol (the model the
    2026-09-07/08 round actually ran on the gateway). Per-project
    model_override still wins; this pins the fallback only."""
    config = tomllib.loads((ROOT / "codex-home" / "config.toml").read_text(encoding="utf-8"))
    assert config["model"] == "gpt-5.6-sol"
    assert config["model_reasoning_effort"] == "xhigh"
    assert config["model_provider"] == "crystalpilot"


@pytest.mark.parametrize("role", ["planner", "analyst", "fast"])
def test_legacy_roles_default_to_astra(role):
    config = LLMConfig()
    provider, model, effort = build_provider(config, role)
    assert model == "gpt-6-astra"
    assert provider.default_model == model
    assert effort == getattr(config.routing, f"{role}_effort")
    assert ModelRouting().planner_effort == "xhigh"


def test_explicit_byok_model_override_remains_supported(monkeypatch):
    monkeypatch.setenv("CRYSTALPILOT_LLM_BASE_URL", "https://example.invalid")
    monkeypatch.setenv("CRYSTALPILOT_LLM_API_KEY", "test-placeholder")
    monkeypatch.setenv("CRYSTALPILOT_LLM_MODEL", "owner-selected-model")
    config = _from_env()
    assert config is not None
    for role in ("planner", "analyst", "fast"):
        assert getattr(config.routing, role) == "owner-selected-model"
