"""A text-only model gets no pictures and double-encoded arguments are
decoded (first GLM-5.3 cell, 2026-09-06)."""
from __future__ import annotations

import json
import threading
from types import SimpleNamespace

import pytest

from crystalpilot.mcp.server import coerce_json_strings, content_blocks
from crystalpilot.workbench import model_caps

SCHEMA = {"type": "object", "properties": {
    "goal": {"type": "string"},
    "tiers": {"type": "object"},
    "open_directions": {"type": "array", "items": {"type": "string"}},
    "maybe": {"anyOf": [{"type": "object"}, {"type": "null"}]},
    "kind": {"type": ["string", "null"]}}}


def test_json_strings_become_the_objects_the_schema_wants():
    args, names = coerce_json_strings({
        "goal": "x",
        "tiers": json.dumps({"candidate_complete": {"status": "unmet"}}),
        "open_directions": json.dumps(["a", "b"]),
        "maybe": json.dumps({"k": 1}),
        "kind": json.dumps({"not": "wanted"})}, SCHEMA)
    assert args["tiers"] == {"candidate_complete": {"status": "unmet"}}
    assert args["open_directions"] == ["a", "b"]
    assert args["maybe"] == {"k": 1}
    # a string-typed property keeps its string, even when it parses as JSON
    assert args["kind"] == json.dumps({"not": "wanted"})
    assert names == ["tiers", "open_directions", "maybe"]
    # wrong container / not JSON: untouched, validation reports it
    args, names = coerce_json_strings({"tiers": "[1, 2]", "open_directions": "nope"}, SCHEMA)
    assert args == {"tiers": "[1, 2]", "open_directions": "nope"} and names == []
    assert coerce_json_strings({}, {}) == ({}, [])


def test_pictures_stay_on_disk_for_a_text_only_model(tmp_path):
    png = tmp_path / "view.png"
    png.write_bytes(b"not a real png")
    payload = {"ok": True, "summary": {"n": 1, "_image_files": [str(png)]}}
    blocks = content_blocks(json.loads(json.dumps(payload)), images_ok=False)
    assert len(blocks) == 1 and blocks[0].type == "text"
    text = json.loads(blocks[0].text)
    assert text["summary"]["images_saved"] == [str(png)]
    assert "no image input" in text["summary"]["image_note"]
    assert "_image_files" not in text["summary"]
    # a multimodal model: the picture is attempted (here unreadable -> noted)
    blocks = content_blocks(json.loads(json.dumps(payload)), images_ok=True)
    text = json.loads(blocks[0].text)
    assert "image_errors" in text["summary"] and "images_saved" not in text["summary"]


def test_image_capability_by_provider_and_model(tmp_path, monkeypatch):
    cache = tmp_path / "models.json"
    cache.write_text(json.dumps({"data": [
        {"id": "z-ai/glm-5.3", "architecture": {"input_modalities": ["text"]}},
        {"id": "z-ai/glm-5.3-flash", "architecture": {"input_modalities": ["text", "image", "video"]}},
    ]}), encoding="utf-8")
    monkeypatch.setattr(model_caps, "CACHE_FILE", cache)
    monkeypatch.delenv("CRYSTALPILOT_NO_IMAGES", raising=False)
    assert model_caps.image_input_supported(None, "gpt-6-astra") is True
    assert model_caps.image_input_supported("crystalpilot", "anything") is True
    assert model_caps.image_input_supported("openrouter", "z-ai/glm-5.3") is False
    assert model_caps.image_input_supported("openrouter", "z-ai/glm-5.3-flash") is True
    assert model_caps.image_input_supported("openrouter", "vendor/unknown") is None
    assert model_caps.image_input_supported("openrouter", None) is None
    assert model_caps.image_input_supported("someone-else", "m") is None
    monkeypatch.setenv("CRYSTALPILOT_NO_IMAGES", "1")
    assert model_caps.image_input_supported(None, "gpt-6-astra") is False


def test_settings_carry_vision_and_the_mcp_env_follows(tmp_path, monkeypatch):
    from crystalpilot.workbench import service
    from crystalpilot.workbench.core import _mcp_overrides
    monkeypatch.setattr(service, "_model_info", lambda: {
        "model": "gpt-6-astra", "effort": "xhigh", "provider": "crystalpilot",
        "providers": ["crystalpilot", "openrouter"]})
    monkeypatch.setattr(model_caps, "image_input_supported",
                        lambda p, m: False if m == "z-ai/glm-5.3" else True)
    d = service.project_settings_dict(tmp_path, {}, "auto")
    assert d["vision"] is True
    d = service.project_settings_dict(
        tmp_path, {"model_provider_override": "openrouter",
                   "model_override": "z-ai/glm-5.3"}, "auto")
    assert d["vision"] is False
    env_on = [x for x in _mcp_overrides(tmp_path, images=True) if x.startswith("mcp_servers.crystalpilot.env=")][0]
    env_off = [x for x in _mcp_overrides(tmp_path, images=False) if x.startswith("mcp_servers.crystalpilot.env=")][0]
    assert "CRYSTALPILOT_NO_IMAGES" not in env_on and "CRYSTALPILOT_NO_IMAGES='1'" in env_off


def test_model_change_that_flips_vision_rebuilds(monkeypatch):
    """Process-level codex flags (the image tool, the multi-agent tools)
    follow the settings through an engine rebuild - at once when idle,
    after the running turn otherwise."""
    from crystalpilot.workbench import service
    monkeypatch.setattr(service, "_model_info", lambda: {
        "model": "gpt-6-astra", "effort": "xhigh", "provider": "crystalpilot",
        "providers": ["crystalpilot", "openrouter"]})
    rebuilt: list[dict] = []
    project = SimpleNamespace(settings={}, save=lambda: None, path="x")
    wb = SimpleNamespace(project=project, mcp_images=True,
                         multi_agent=service.subagents_on({}),
                         context_window=None, auto_compact_limit=None)
    stub = SimpleNamespace(wb=wb, settings=lambda: dict(project.settings),
                           _refresh_delegation=lambda: None,
                           _push_settings=lambda: None,
                           _lock=threading.Lock(), _busy=set(),
                           _restart_pending=False,
                           _running_catalog_stamp=service._catalog_stamp())

    def rebuild(ev):
        rebuilt.append(ev)
        wb.mcp_images = service.vision_for(project.settings) is not False
        wb.multi_agent = service.subagents_on(project.settings)
        wb.context_window = project.settings.get("context_window_override") or None
        wb.auto_compact_limit = project.settings.get("auto_compact_token_limit") or None
        stub._running_catalog_stamp = service._catalog_stamp()
    stub._rebuild_workbench = rebuild

    def bind(fn):
        return lambda *a, **k: fn(stub, *a, **k)
    for name in ("_sync_engine", "_rebuild_or_defer", "_engine_flags",
                 "_running_flags", "_apply_pending_restart"):
        setattr(stub, name, bind(getattr(service.ProjectSession, name)))
    assert wb.multi_agent is False       # auto: xhigh is not astra's top rung
    service.ProjectSession.update_project_settings(
        stub, {"model_provider_override": "openrouter", "model_override": "z-ai/glm-5.3"})
    # text-only model -> images off; effort snapped to the GLM top rung
    # (high) -> auto switches the sub-agents on: one rebuild for both
    assert len(rebuilt) == 1 and rebuilt[0]["kind"] == "engine_restarted"
    assert wb.mcp_images is False and wb.multi_agent is True
    service.ProjectSession.update_project_settings(
        stub, {"model_override": "z-ai/glm-5.3-flash"})
    assert len(rebuilt) == 2 and wb.mcp_images is True
    service.ProjectSession.update_project_settings(stub, {"effort_override": "medium"})
    assert len(rebuilt) == 3 and wb.multi_agent is False
    service.ProjectSession.update_project_settings(stub, {"display_name": "x"})
    assert len(rebuilt) == 3
    service.ProjectSession.update_project_settings(stub, {"subagents": "on"})
    assert len(rebuilt) == 4 and wb.multi_agent is True
    # while a turn runs, the restart waits for the turn to end
    stub._busy.add("t1")
    service.ProjectSession.update_project_settings(stub, {"subagents": "off"})
    assert len(rebuilt) == 4 and stub._restart_pending is True
    stub._busy.clear()
    stub._apply_pending_restart()
    assert len(rebuilt) == 5 and wb.multi_agent is False
    assert stub._restart_pending is False


