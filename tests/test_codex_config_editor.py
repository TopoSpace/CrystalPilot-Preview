"""codex_config: line-level edits of the isolated config.toml that keep
comments and every other byte, validated with tomllib before landing."""
from __future__ import annotations

import shutil
import tomllib
from pathlib import Path

import pytest

from crystalpilot.workbench import codex_config

REAL = Path(__file__).resolve().parents[1] / "codex-home" / "config.toml"


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    p = tmp_path / "config.toml"
    shutil.copy(REAL, p)
    monkeypatch.setattr(codex_config, "CONFIG_PATH", p)
    return p


def test_top_level_replace_keeps_the_rest(cfg):
    before = cfg.read_text(encoding="utf-8")
    out = codex_config.set_top_level("model", "gpt-5.5")
    assert out["model"] == "gpt-5.5"
    after = cfg.read_text(encoding="utf-8")
    # exactly one line differs
    diff = [(a, b) for a, b in zip(before.split("\n"), after.split("\n")) if a != b]
    assert len(diff) == 1 and diff[0][0].startswith("model = ") and diff[0][1] == 'model = "gpt-5.5"'
    assert cfg.with_suffix(".toml.bak").read_text(encoding="utf-8") == before


def test_top_level_insert_and_remove(cfg):
    out = codex_config.set_top_level("model_context_window", 200000)
    assert out["model_context_window"] == 200000
    lines = cfg.read_text(encoding="utf-8").split("\n")
    idx = next(i for i, ln in enumerate(lines) if ln.startswith("model_context_window"))
    first_header = next(i for i, ln in enumerate(lines) if ln.startswith("["))
    assert idx < first_header
    out = codex_config.set_top_level("model_context_window", None)
    assert "model_context_window" not in out
    assert "model_context_window" not in cfg.read_text(encoding="utf-8")


def test_provider_upsert_new_lands_before_agents_and_parses(cfg):
    table = {"name": "Test Provider", "base_url": "https://api.example.com/v1",
             "wire_api": "responses", "http_headers": {"X-Title": "CrystalPilot"}}
    auth = {"command": r"H:\CrystalPilot\.venv\Scripts\python.exe",
            "args": [r"H:\CrystalPilot\crystalpilot\workbench\print_token.py", "--cred",
                     r"H:\CrystalPilot\secrets\testprov.txt"]}
    rec = codex_config.upsert_provider("testprov", table, auth, comment="added by a test")
    assert rec["base_url"] == "https://api.example.com/v1"
    assert rec["auth"]["args"][-1].endswith("testprov.txt")
    text = cfg.read_text(encoding="utf-8")
    assert text.index("[model_providers.testprov]") < text.index("[agents]")
    assert "# added by a test" in text
    parsed = tomllib.loads(text)
    assert set(parsed["model_providers"]) >= {"crystalpilot", "openrouter", "testprov"}
    # the [agents] guard rails survive untouched
    assert parsed["agents"]["max_concurrent_threads_per_session"] == 2


def test_provider_upsert_existing_replaces_in_place(cfg):
    before = cfg.read_text(encoding="utf-8")
    start = before.index("[model_providers.openrouter]")
    codex_config.upsert_provider("openrouter", {"name": "OpenRouter (renamed)",
                                                "base_url": "https://openrouter.ai/api/v1",
                                                "wire_api": "responses"},
                                 {"command": "x", "args": ["y"]})
    after = cfg.read_text(encoding="utf-8")
    parsed = tomllib.loads(after)
    assert parsed["model_providers"]["openrouter"]["name"] == "OpenRouter (renamed)"
    assert parsed["model_providers"]["openrouter"]["auth"]["command"] == "x"
    # the text before the block (incl. the crystalpilot provider) is unchanged
    assert after[:start - 200] == before[:start - 200]
    assert after.count("[model_providers.openrouter]") == 1
    assert "[agents]" in after and "[projects.'h:\\crystalpilot']" in after


def test_remove_provider(cfg):
    assert codex_config.remove_provider("openrouter") is True
    parsed = tomllib.loads(cfg.read_text(encoding="utf-8"))
    assert "openrouter" not in parsed["model_providers"]
    assert "crystalpilot" in parsed["model_providers"]
    assert codex_config.remove_provider("openrouter") is False


def test_provider_id_validation():
    for bad in ("", "Open Router", "openai", "a.b", "-x", "x" * 40):
        with pytest.raises(codex_config.ConfigError):
            codex_config.validate_provider_id(bad)
    assert codex_config.validate_provider_id(" deepseek ") == "deepseek"


def test_toml_value_rendering():
    tv = codex_config.toml_value
    assert tv(True) == "true" and tv(3) == "3"
    assert tv('say "hi"') == '"say \\"hi\\""'
    assert tv(r"H:\x\y") == r"'H:\x\y'"
    assert tv(["a", "b"]) == '["a", "b"]'
    assert tv({"X-Title": "CP"}) == '{ "X-Title" = "CP" }'
