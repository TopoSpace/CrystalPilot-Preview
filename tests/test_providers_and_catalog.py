"""Providers (keys in files, never in responses), the generated model
catalog (bundled + custom), the kernel resolver, and the model lists."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from crystalpilot.workbench import (codex_config, kernel, model_catalog, models,
                                    providers)

REAL_CFG = Path(__file__).resolve().parents[1] / "codex-home" / "config.toml"


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    cfg = tmp_path / "config.toml"
    shutil.copy(REAL_CFG, cfg)
    monkeypatch.setattr(codex_config, "CONFIG_PATH", cfg)
    secrets = tmp_path / "secrets"
    monkeypatch.setattr(providers, "SECRETS_DIR", secrets)
    monkeypatch.setattr(providers, "DEFAULT_CRED_FILE", tmp_path / "testAPI.txt")
    return tmp_path


def test_list_providers_never_carries_a_key(sandbox):
    rows = providers.list_providers()
    ids = [r["id"] for r in rows]
    assert ids[0] == "crystalpilot" and "openrouter" in ids
    for r in rows:
        assert "key" not in {k for k in r if k not in ("has_key", "key_updated")}
        assert set(r) >= {"id", "name", "base_url", "kind", "is_default", "auth_kind",
                          "has_key", "cred_file", "key_updated"}
    assert next(r for r in rows if r["id"] == "openrouter")["kind"] == "openrouter"


def test_upsert_writes_key_file_and_auth_hook(sandbox):
    rec = providers.upsert_provider("deepseek", "DeepSeek", "https://api.deepseek.com/v1/",
                                    api_key="sk-test-not-a-real-key")
    assert rec["id"] == "deepseek" and rec["has_key"] is True
    assert rec["base_url"] == "https://api.deepseek.com/v1"
    cred = Path(rec["cred_file"])
    assert cred.parent == providers.SECRETS_DIR
    assert cred.read_text(encoding="utf-8").strip() == "sk-test-not-a-real-key"
    table = codex_config.load()["model_providers"]["deepseek"]
    assert table["wire_api"] == "responses"
    assert table["auth"]["args"][-2:] == ["--cred", str(cred)]
    assert providers.read_key("deepseek") == "sk-test-not-a-real-key"
    # None / blank keeps the key; removal is a separate explicit action.
    providers.upsert_provider("deepseek", None, "https://api.deepseek.com/v1", api_key=None)
    providers.upsert_provider("deepseek", None, "https://api.deepseek.com/v1", api_key="")
    assert providers.get_provider("deepseek")["has_key"] is True
    providers.upsert_provider("deepseek", None, "https://api.deepseek.com/v1",
                              remove_api_key=True)
    assert providers.get_provider("deepseek")["has_key"] is False


def test_provider_http_save_round_trip(sandbox, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from crystalpilot.workbench import routes_config

    monkeypatch.setattr(routes_config, "_broadcast_settings", lambda: None)
    app = FastAPI()
    app.include_router(routes_config.router)
    with TestClient(app) as client:
        response = client.post("/api/providers", json={
            "id": "http-save", "name": "HTTP save", "base_url": "http://127.0.0.1:9/v1",
            "auth_mode": "managed_api_key", "api_key": "DUMMY_HTTP_TOKEN",
            "request_max_retries": 3, "stream_idle_timeout_ms": 45_000,
        })
        assert response.status_code == 200, response.text
        assert response.json()["has_key"] is True
        assert response.json()["request_max_retries"] == 3
        assert "DUMMY_HTTP_TOKEN" not in response.text
        assert providers.read_key("http-save") == "DUMMY_HTTP_TOKEN"
        response = client.post("/api/providers", json={
            "id": "http-save", "name": "Renamed", "base_url": "http://127.0.0.1:9/v1",
        })
        assert response.status_code == 200
        assert response.json()["has_key"] is True
        assert response.json()["stream_idle_timeout_ms"] == 45_000
        bad = client.post("/api/providers", json={
            "id": "http-invalid", "base_url": "http://127.0.0.1:9/v1", "wire_api": "chat",
            "api_key": "DUMMY_MUST_NOT_SAVE",
        })
        assert bad.status_code == 400
        assert not (providers.SECRETS_DIR / "http-invalid.txt").exists()


def test_key_status_uses_the_shared_credential_parser(sandbox):
    rec = providers.upsert_provider(
        "parsecheck", "Parse check", "https://api.example/v1", api_key="dummy-valid-token"
    )
    cred = Path(rec["cred_file"])
    cred.write_text("not a valid bare token\n", encoding="utf-8")
    assert providers.get_provider("parsecheck")["has_key"] is False
    cred.write_text("Key: DUMMY_NOTE_TOKEN\n", encoding="utf-8")
    assert providers.get_provider("parsecheck")["has_key"] is True


def test_remove_parks_the_key_and_refuses_the_default(sandbox):
    providers.upsert_provider("deepseek", "DeepSeek", "https://api.deepseek.com/v1",
                              api_key="sk-x")
    cred = Path(providers.get_provider("deepseek")["cred_file"])
    out = providers.remove_provider("deepseek")
    assert out["removed"] is True and out["key_parked"]
    assert not cred.exists() and Path(out["key_parked"]).exists()
    with pytest.raises(codex_config.ConfigError):
        providers.remove_provider("crystalpilot")


def test_set_default_provider(sandbox):
    providers.set_default_provider("openrouter")
    assert codex_config.load()["model_provider"] == "openrouter"
    with pytest.raises(KeyError):
        providers.set_default_provider("nope")


def test_test_connection_reports_without_leaking(sandbox, monkeypatch):
    calls = []

    def fake_get(url, headers, timeout=20.0):
        calls.append((url, headers.get("Authorization")))
        if url.endswith("/models"):
            return 200, {"data": [{"id": "m1"}, {"id": "m2"}]}
        return 200, {"data": {"label": "cp", "usage": 1.5}}
    monkeypatch.setattr(providers, "_get_json", fake_get)
    out = providers.test_connection(None, "https://x.example/v1", "sk-secret")
    assert out["ok"] is True and out["n_models"] == 2 and out["sample"] == ["m1", "m2"]
    assert out["check"] == "model_catalogue" and out["protocol_compatible"] is None
    assert "sk-secret" not in json.dumps(out)
    assert calls[0][1] == "Bearer sk-secret"

    def denied(url, headers, timeout=20.0):
        return 401, {"error": {"message": "bad key"}}
    monkeypatch.setattr(providers, "_get_json", denied)
    out = providers.test_connection(None, "https://x.example/v1", "sk-secret")
    assert out["ok"] is False and out["status"] == 401 and "bad key" in out["error"]


def test_openrouter_proxy_probe_does_not_forward_credentials_to_another_host(sandbox, monkeypatch):
    calls = []
    def fake_get(url, headers, timeout=20.0):
        calls.append(url)
        return 200, {"data": []}
    monkeypatch.setattr(providers, "_get_json", fake_get)
    providers.test_connection("openrouter", "https://proxy.example/v1", "DUMMY_PROXY_TOKEN",
                              query_params={"api-version": "v1"})
    assert calls == ["https://proxy.example/v1/models?api-version=v1",
                     "https://proxy.example/v1/key?api-version=v1"]


def test_probe_error_redacts_url_encoded_query_secret(sandbox, monkeypatch):
    import urllib.parse
    secret = "DUMMY+QUERY/SECRET="
    def denied(url, headers, timeout=20.0):
        return 401, {"error": {"message": url}}
    monkeypatch.setattr(providers, "_get_json", denied)
    result = providers.test_connection(None, "https://proxy.example/v1",
                                       query_params={"api_key": secret})
    assert secret not in result["error"]
    assert urllib.parse.quote_plus(secret) not in result["error"]
    assert "[redacted]" in result["error"]


def test_public_catalogue_does_not_claim_a_stored_key(sandbox, monkeypatch):
    monkeypatch.setattr(providers, "_get_json", lambda *a, **kw: (200, {"data": []}))
    result = providers.test_connection(None, "https://public.example/v1")
    assert result["ok"] is True
    assert result["has_key"] is False
    assert result["used_stored_key"] is False


@pytest.mark.parametrize("name", ["sig", "password", "X-Password", "passwd"])
def test_sensitive_query_constants_are_not_exposed_or_added(sandbox, name):
    assert providers._masked_map({name: "dummy-secret"}) == {name: providers.MASKED_VALUE}
    with pytest.raises(codex_config.ConfigError):
        providers.upsert_provider("private", "Private", "https://example.test/v1",
                                  query_params={name: "dummy-secret"})


def test_edit_preserves_legacy_auth_and_unknown_settings(sandbox):
    legacy_auth = {"command": r"C:\vendor\auth-helper.exe", "args": ["token"]}
    codex_config.upsert_provider(
        "legacy",
        {"name": "Legacy", "base_url": "https://old.example/v1", "wire_api": "responses",
         "custom_future_option": "keep-me", "request_max_retries": 7},
        legacy_auth,
    )
    rec = providers.upsert_provider("legacy", "Renamed", "https://new.example/v1")
    table = codex_config.load()["model_providers"]["legacy"]
    assert rec["auth_mode"] == "legacy" and rec["has_key"] is False
    assert table["auth"] == legacy_auth
    assert table["custom_future_option"] == "keep-me"
    assert table["request_max_retries"] == 7


def test_explicit_auth_modes_and_key_removal(sandbox):
    rec = providers.upsert_provider(
        "acme", "Acme", "https://api.example/v1", api_key="dummy-managed-token"
    )
    assert rec["auth_mode"] == providers.AUTH_MANAGED and rec["has_key"] is True
    cred = Path(rec["cred_file"])

    rec = providers.upsert_provider(
        "acme", None, "https://api.example/v1",
        auth_mode=providers.AUTH_ENVIRONMENT, env_key="ACME_API_KEY",
    )
    table = codex_config.load()["model_providers"]["acme"]
    assert rec["auth_mode"] == providers.AUTH_ENVIRONMENT
    assert table["env_key"] == "ACME_API_KEY" and "auth" not in table
    assert cred.exists()  # switching modes does not silently destroy a key

    rec = providers.upsert_provider(
        "acme", None, "https://api.example/v1", auth_mode=providers.AUTH_NONE,
    )
    table = codex_config.load()["model_providers"]["acme"]
    assert rec["auth_mode"] == providers.AUTH_NONE
    assert "env_key" not in table and "auth" not in table


def test_sensitive_maps_are_masked_and_masks_preserve_values(sandbox):
    providers.upsert_provider(
        "safe", "Safe", "https://api.example/v1",
        http_headers={"X-Title": "CrystalPilot"},
        query_params={"api-version": "2026-01-01"},
        env_http_headers={"X-Tenant": "CP_TENANT"},
        request_max_retries=4, stream_max_retries=5, stream_idle_timeout_ms=30_000,
    )
    # Simulate legacy hand-written sensitive constants. The UI may preserve
    # their masks but refuses to create or replace them in tracked config.
    table = codex_config.load()["model_providers"]["safe"]
    auth = table.pop("auth")
    table["http_headers"]["Authorization"] = "dummy-static-secret"
    table["query_params"]["api_key"] = "dummy-query-secret"
    codex_config.upsert_provider("safe", table, auth)
    rec = providers.get_provider("safe")
    assert rec is not None
    assert rec["http_headers"] == {
        "Authorization": providers.MASKED_VALUE, "X-Title": "CrystalPilot"
    }
    assert rec["query_params"]["api_key"] == providers.MASKED_VALUE
    assert "dummy-static-secret" not in json.dumps(rec)
    assert "dummy-query-secret" not in json.dumps(rec)

    providers.upsert_provider(
        "safe", "Safe renamed", "https://api.example/v1",
        http_headers=rec["http_headers"], query_params=rec["query_params"],
    )
    table = codex_config.load()["model_providers"]["safe"]
    assert table["http_headers"]["Authorization"] == "dummy-static-secret"
    assert table["query_params"]["api_key"] == "dummy-query-secret"
    assert table["env_http_headers"] == {"X-Tenant": "CP_TENANT"}


def test_invalid_provider_fields_write_nothing(sandbox):
    before = codex_config.read_text()
    cases = [
        {"base_url": "https://user:pass@example.test/v1"},
        {"base_url": "https://example.test/v1", "http_headers": {"Bad Header": "x"}},
        {"base_url": "https://example.test/v1", "http_headers": {"X-Api-Key": "dummy"}},
        {"base_url": "https://example.test/v1", "query_params": {"api_key": "dummy"}},
        {"base_url": "https://example.test/v1", "query_params": {"x": "bad\nvalue"}},
        {"base_url": "https://example.test/v1", "env_http_headers": {"X-Key": "bad-name"}},
        {"base_url": "https://example.test/v1", "request_max_retries": 101},
        {"base_url": "https://example.test/v1", "stream_idle_timeout_ms": -1},
        {"base_url": "https://example.test/v1", "wire_api": "chat"},
    ]
    for kwargs in cases:
        with pytest.raises(codex_config.ConfigError):
            providers.upsert_provider(
                "invalid", "Invalid", api_key="dummy-must-not-be-written", **kwargs
            )
        assert codex_config.read_text() == before
        assert not (providers.SECRETS_DIR / "invalid.txt").exists()


def test_connection_redacts_reflected_secrets_and_applies_query(sandbox, monkeypatch):
    calls = []

    def denied(url, headers, timeout=20.0):
        calls.append((url, headers))
        return 401, {"error": {"message": "rejected dummy-probe-token and dummy-query"}}

    monkeypatch.setattr(providers, "_get_json", denied)
    out = providers.test_connection(
        None, "https://x.example/v1", "dummy-probe-token",
        {"X-Title": "CP"}, {"api_key": "dummy-query"},
    )
    assert out["ok"] is False and out["check"] == "model_catalogue"
    assert "dummy-probe-token" not in json.dumps(out)
    assert "dummy-query" not in json.dumps(out)
    assert calls[0][0].endswith("/models?api_key=dummy-query")
    assert calls[0][1]["Authorization"] == "Bearer dummy-probe-token"


# --------------------------------------------------------------- kernel
def test_kernel_resolver_finds_a_binary():
    info = kernel.kernel_info()
    assert info["path"] and Path(info["path"]).is_file()
    assert info["version"] and info["version"][0].isdigit()
    assert info["source"] in ("env", "npm", "pip")
    assert any(c["source"] == "pip" for c in info["candidates"])
    env = kernel.kernel_env()
    assert not env or any(k.upper() == "PATH" for k in env)


def test_pinned_kernel_provider_schema_offline(tmp_path):
    """Codex 0.147 parses the advanced fields and refuses old chat wire API.

    ``features list`` loads config but never starts app-server or contacts a
    provider. CODEX_HOME is a dummy temp directory with no credential.
    """
    binary = kernel.pip_candidate()
    assert binary is not None and kernel.codex_version(binary) == "0.147.0"
    home = tmp_path / "responses-home"
    home.mkdir()
    (home / "config.toml").write_text(
        'model_provider = "probe"\n'
        '[model_providers.probe]\n'
        'name = "Offline probe"\n'
        'base_url = "http://127.0.0.1:9/v1"\n'
        'wire_api = "responses"\n'
        'request_max_retries = 4\n'
        'stream_max_retries = 5\n'
        'stream_idle_timeout_ms = 30000\n'
        'query_params = { "api-version" = "2026-01-01" }\n'
        'http_headers = { "X-Title" = "CrystalPilot" }\n'
        'env_http_headers = { "X-Api-Key" = "DUMMY_PROVIDER_KEY" }\n',
        encoding="utf-8",
    )
    env = dict(os.environ, CODEX_HOME=str(home))
    good = subprocess.run(
        [str(binary), "features", "list"], capture_output=True, text=True, env=env, timeout=20
    )
    assert good.returncode == 0, good.stderr

    (home / "config.toml").write_text(
        'model_provider = "probe"\n'
        '[model_providers.probe]\n'
        'name = "Offline probe"\n'
        'base_url = "http://127.0.0.1:9/v1"\n'
        'wire_api = "chat"\n',
        encoding="utf-8",
    )
    old_chat = subprocess.run(
        [str(binary), "features", "list"], capture_output=True, text=True, env=env, timeout=20
    )
    assert old_chat.returncode != 0
    assert "no longer supported" in old_chat.stderr and "responses" in old_chat.stderr.lower()


# --------------------------------------------------------------- catalog
@pytest.fixture
def catalog_sandbox(tmp_path, monkeypatch):
    monkeypatch.setattr(model_catalog, "CATALOG_PATH", tmp_path / "model_catalog.json")
    monkeypatch.setattr(model_catalog, "CUSTOM_PATH", tmp_path / "model_catalog.custom.json")
    monkeypatch.setattr(model_catalog, "CACHE_DIR", tmp_path / "cache")
    return tmp_path


def test_bundled_catalog_extracts_from_the_kernel(catalog_sandbox):
    cat = model_catalog.bundled_catalog()
    slugs = [m["slug"] for m in cat["models"]]
    assert "gpt-5.5" in slugs
    # cached on the second call
    assert list((catalog_sandbox / "cache").glob("codex-bundled-catalog-*.json"))


def test_build_merges_custom_over_bundled(catalog_sandbox):
    model_catalog.save_custom([
        {"slug": "z-ai/glm-5.3", "display_name": "GLM-5.3", "provider": "openrouter",
         "input_modalities": ["text"], "context_window": 1310720,
         "default_reasoning_level": "high", "supported_reasoning_levels": ["low", "medium", "high"]},
        {"slug": "gpt-5.5", "display_name": "GPT-5.5 (overridden)",
         "supported_reasoning_levels": ["low", "high"]},
    ])
    cat = model_catalog.build()
    by = {m["slug"]: m for m in cat["models"]}
    assert by["z-ai/glm-5.3"]["context_window"] == 1310720
    assert [lv["effort"] for lv in by["z-ai/glm-5.3"]["supported_reasoning_levels"]] == ["low", "medium", "high"]
    assert by["z-ai/glm-5.3"]["default_reasoning_level"] == "high"
    assert by["z-ai/glm-5.3"]["input_modalities"] == ["text"]
    assert by["gpt-5.5"]["display_name"] == "GPT-5.5 (overridden)"
    # the template's format is the binary's: no invented keys
    template = next(m for m in model_catalog.bundled_catalog()["models"] if m["slug"] == "gpt-5.5")
    assert set(by["z-ai/glm-5.3"]) <= set(template) | {"base_instructions"}
    rec = model_catalog.ensure_catalog()
    assert rec["written"] is True and rec["n_custom"] == 2
    assert model_catalog.ensure_catalog()["written"] is False
    assert model_catalog.effort_ladder_of("z-ai/glm-5.3") == ("low", "medium", "high")
    assert model_catalog.effort_ladder_of("nope/unknown") is None
    assert model_catalog.catalog_entry("gpt-5.5")["source"] == "custom"


def test_upsert_custom_model_regenerates(catalog_sandbox):
    rec = model_catalog.upsert_custom_model({"slug": "acme/m1", "provider": "acme",
                                             "supported_reasoning_levels": []})
    assert rec["written"] is True
    e = model_catalog.catalog_entry("acme/m1")
    assert e and e["efforts"] == [] and e["source"] == "custom"
    model_catalog.remove_custom_model("acme/m1")
    assert model_catalog.catalog_entry("acme/m1") is None


# ---------------------------------------------------------------- models
def test_openrouter_ladders_follow_metadata(sandbox, catalog_sandbox, monkeypatch):
    recs = {
        "z-ai/glm-5.3": {"id": "z-ai/glm-5.3", "name": "GLM 5.3", "context_length": 1310720,
                         "architecture": {"input_modalities": ["text"]},
                         "supported_parameters": ["reasoning", "tools"]},
        "openai/gpt-5.5": {"id": "openai/gpt-5.5", "name": "GPT-5.5", "context_length": 1050000,
                           "architecture": {"input_modalities": ["text", "image"]},
                           "supported_parameters": ["reasoning"]},
        "meta/llama": {"id": "meta/llama", "name": "Llama", "context_length": 128000,
                       "architecture": {"input_modalities": ["text"]},
                       "supported_parameters": ["tools"]},
    }
    monkeypatch.setattr(models, "openrouter_models", lambda refresh=False: recs)
    out = models.list_models("openrouter")
    by = {m["id"]: m for m in out["models"]}
    assert by["z-ai/glm-5.3"]["efforts"] == ["low", "medium", "high"]
    assert by["openai/gpt-5.5"]["efforts"] == ["low", "medium", "high", "xhigh"]
    assert by["meta/llama"]["efforts"] == [] and by["meta/llama"]["reasoning"] is False
    assert models.ladder_from_metadata("openrouter", "meta/llama") == ()
    assert models.ladder_from_metadata("openrouter", "nope") is None
    assert models.ladder_from_metadata("crystalpilot", "gpt-6-astra") is None
    # learning a model declares it to codex with the metadata's facts
    rec = models.learn_model("openrouter", "meta/llama")
    assert rec["changed"] is True
    e = model_catalog.catalog_entry("meta/llama")
    assert e["context_window"] == 128000 and e["efforts"] == []


def test_learn_model_wrong_provider_and_weak_entry_upgrade(sandbox, catalog_sandbox, monkeypatch):
    """Found live 2026-09-07: an OpenRouter id learned while the project
    still sat on the gateway froze a ladder-less entry, so the effort menu
    said 'none' and no effort was sent. Now every provider's metadata is
    consulted, weak entries are upgraded, and an unknown ladder falls
    through to the fallback ladders instead of meaning 'no reasoning'."""
    from crystalpilot.workbench import service
    recs = {
        "z-ai/glm-5.3-flash": {"id": "z-ai/glm-5.3-flash", "name": "GLM 5.3 Flash",
                               "context_length": 1310720,
                               "architecture": {"input_modalities": ["text", "image", "video"]},
                               "supported_parameters": ["reasoning", "tools"]},
    }
    monkeypatch.setattr(models, "openrouter_models", lambda refresh=False: recs)
    rec = models.learn_model("crystalpilot", "z-ai/glm-5.3-flash")
    assert rec["changed"] is True
    e = model_catalog.catalog_entry("z-ai/glm-5.3-flash")
    assert e["efforts"] == ["low", "medium", "high"] and e["context_window"] == 1310720
    assert "image" in e["input_modalities"]
    assert service.effort_ladder("openrouter", "z-ai/glm-5.3-flash") == ("low", "medium", "high")
    # a placeholder written earlier is upgraded once metadata knows the model
    model_catalog.upsert_custom_model({"slug": "acme/weak", "provider": "crystalpilot",
                                       "input_modalities": ["text"]})
    assert service.effort_ladder("crystalpilot", "acme/weak") == service.EFFORT_LADDERS.get(
        "crystalpilot", service.EFFORT_CHOICES)
    recs["acme/weak"] = {"id": "acme/weak", "name": "Weak", "context_length": 32000,
                         "architecture": {"input_modalities": ["text"]},
                         "supported_parameters": ["reasoning"]}
    assert models.learn_model("crystalpilot", "acme/weak")["changed"] is True
    assert model_catalog.catalog_entry("acme/weak")["efforts"] == ["low", "medium", "high"]
    # unknown everywhere: text-only entry, ladder unknown -> provider fallback
    assert models.learn_model("crystalpilot", "nobody/knows")["changed"] is True
    assert model_catalog.catalog_entry("nobody/knows")["input_modalities"] == ["text"]
    assert service.effort_ladder("crystalpilot", "nobody/knows") == service.EFFORT_LADDERS.get(
        "crystalpilot", service.EFFORT_CHOICES)
    # a rich custom entry is left alone
    assert models.learn_model("crystalpilot", "acme/weak").get("already") is True


def test_learn_model_never_moves_an_entry_between_providers(sandbox, catalog_sandbox, monkeypatch):
    """Found live 2026-09-07: learning an OpenRouter model while the gateway
    tab was open re-tagged its custom entry, and list_models then dropped it
    from the OpenRouter tab. The tag is where the model was first learned."""
    recs = {
        "z-ai/glm-5.3-flash": {"id": "z-ai/glm-5.3-flash", "name": "GLM 5.3 Flash",
                               "context_length": 1310720,
                               "architecture": {"input_modalities": ["text", "image"]},
                               "supported_parameters": ["reasoning"]},
    }
    monkeypatch.setattr(models, "openrouter_models", lambda refresh=False: recs)
    models.learn_model("openrouter", "z-ai/glm-5.3-flash")
    assert model_catalog.catalog_entry("z-ai/glm-5.3-flash")["provider"] == "openrouter"
    # the same id learned from the gateway tab keeps its home
    models.learn_model("crystalpilot", "z-ai/glm-5.3-flash")
    assert model_catalog.catalog_entry("z-ai/glm-5.3-flash")["provider"] == "openrouter"
    assert "z-ai/glm-5.3-flash" in {m["id"] for m in models.list_models("openrouter")["models"]}
    # a model only another provider's metadata knows is tagged where it lives
    models.learn_model("crystalpilot", "z-ai/glm-5.3-flash")
    assert model_catalog.catalog_entry("z-ai/glm-5.3-flash")["provider"] == "openrouter"


def test_provider_modalities_are_filtered_to_what_codex_accepts(sandbox, catalog_sandbox, monkeypatch):
    """Live failure 2026-09-07: picking Claude / GPT-5.1 / GLM-Flash in the
    model menu stored OpenRouter's modality list verbatim ("file", "video"),
    codex accepts only text/image/audio, and the whole generated catalog then
    failed to parse - so codex refused to start a thread in ANY project."""
    recs = {
        "anthropic/claude-opus-5": {"id": "anthropic/claude-opus-5", "name": "Opus 5",
                                    "context_length": 200000,
                                    "architecture": {"input_modalities": ["text", "image", "file"]},
                                    "supported_parameters": ["reasoning"]},
        "z-ai/glm-5.3-flash": {"id": "z-ai/glm-5.3-flash", "name": "GLM 5.3 Flash",
                               "context_length": 1310720,
                               "architecture": {"input_modalities": ["text", "image", "video"]},
                               "supported_parameters": ["reasoning"]},
    }
    monkeypatch.setattr(models, "openrouter_models", lambda refresh=False: recs)
    for mid in recs:
        models.learn_model("openrouter", mid)
        assert model_catalog.catalog_entry(mid)["input_modalities"] == ["text", "image"]
    # a hand-written custom entry cannot poison the generated catalog either
    model_catalog.upsert_custom_model({"slug": "acme/odd", "provider": "openrouter",
                                       "input_modalities": ["file", "video"]})
    assert model_catalog.catalog_entry("acme/odd")["input_modalities"] == ["text"]
    allowed = set(model_catalog.CODEX_INPUT_MODALITIES)
    for m in model_catalog.catalog_models():
        assert set(m["input_modalities"]) <= allowed, m["slug"]
