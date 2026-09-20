"""The interface language the browser states must reach the few texts the server composes."""
from __future__ import annotations

import contextvars

from fastapi import FastAPI
from fastapi.testclient import TestClient

from crystalpilot.workbench import i18n, thread_titles


def test_normalize_maps_header_values_onto_supported_languages():
    assert i18n.normalize(None) == "zh"
    assert i18n.normalize("") == "zh"
    assert i18n.normalize("en") == "en"
    assert i18n.normalize("EN-us") == "en"
    assert i18n.normalize("en_GB") == "en"
    assert i18n.normalize("zh-CN") == "zh"
    assert i18n.normalize("fr") == "zh"


def test_msg_follows_the_bound_language_and_an_explicit_override():
    assert i18n.current() == "zh"
    assert i18n.msg("甲", "a") == "甲"
    token = i18n.bind("en")
    try:
        assert i18n.current() == "en"
        assert i18n.msg("甲", "a") == "a"
        assert i18n.msg("甲", "a", "zh") == "甲"
    finally:
        i18n.reset(token)
    assert i18n.msg("甲", "a") == "甲"
    assert i18n.msg("甲", "a", "en") == "a"


def test_language_is_captured_by_a_copied_context_for_background_work():
    token = i18n.bind("en")
    try:
        ctx = contextvars.copy_context()
    finally:
        i18n.reset(token)
    assert ctx.run(i18n.current) == "en"
    assert i18n.current() == "zh"


def test_middleware_binds_header_or_query_for_the_request_only():
    app = FastAPI()

    @app.middleware("http")
    async def _interface_language(request, call_next):
        token = i18n.bind(request.headers.get(i18n.HEADER) or request.query_params.get("lang"))
        try:
            return await call_next(request)
        finally:
            i18n.reset(token)

    @app.get("/probe")
    def probe():
        return {"lang": i18n.current(), "text": i18n.msg("文件夹不存在", "The folder does not exist")}

    client = TestClient(app)
    assert client.get("/probe").json() == {"lang": "zh", "text": "文件夹不存在"}
    assert client.get("/probe", headers={i18n.HEADER: "en"}).json()["lang"] == "en"
    assert client.get("/probe?lang=en-US").json()["text"] == "The folder does not exist"
    assert client.get("/probe", headers={i18n.HEADER: "xx"}).json()["lang"] == "zh"
    assert i18n.current() == "zh"


def test_server_app_carries_the_language_middleware():
    from server.app import app

    names = [getattr(m, "cls", None).__name__ if hasattr(m, "cls") else "" for m in app.user_middleware]
    # BaseHTTPMiddleware wraps our function; make sure the dispatch is registered
    dispatches = [getattr(getattr(m, "kwargs", {}), "get", lambda *_: None)("dispatch") for m in app.user_middleware]
    assert any(getattr(d, "__name__", "") == "_interface_language" for d in dispatches), names


def test_fallback_title_speaks_the_requested_language_and_reads_both_languages():
    ctx = {"project": "P", "data_files": ["sample_042.hkl"], "task": "请精修这个结构"}
    assert thread_titles.fallback_title(ctx) == "sample_042 · 结构精修"
    assert thread_titles.fallback_title(ctx, "en") == "sample_042 · structure refinement"
    ctx = {"project": "P", "data_files": [], "task": "Please run checkCIF and validate the model"}
    assert thread_titles.fallback_title(ctx) == "P · 结构验证"
    assert thread_titles.fallback_title(ctx, "en") == "P · structure validation"
    ctx = {"project": "P", "data_files": ["frames/001.cbf"], "task": "Solve this structure from the frames"}
    assert thread_titles.fallback_title(ctx, "en") == "P · structure solution"
    assert thread_titles.fallback_title(ctx, "zh") == "P · 晶体求解"


def test_naming_instructions_follow_the_language():
    assert thread_titles.instructions_for("zh") is thread_titles.INSTRUCTIONS
    assert thread_titles.instructions_for(None) is thread_titles.INSTRUCTIONS
    assert thread_titles.instructions_for("en") is thread_titles.INSTRUCTIONS_EN
    assert "English" in thread_titles.INSTRUCTIONS_EN and "60" in thread_titles.INSTRUCTIONS_EN
    assert thread_titles.clean_title("Title: sample_042 · refinement") == "sample_042 · refinement"
    assert thread_titles.clean_title("标题：alanine_042 · 单晶求解") == "alanine_042 · 单晶求解"


# -- the remembered language reaches the agent side --------------------------

def test_preferences_round_trip_and_default(tmp_path, monkeypatch):
    from crystalpilot.workbench import preferences

    monkeypatch.setenv("CRYSTALPILOT_PREFERENCES_FILE", str(tmp_path / "prefs.json"))
    assert preferences.language() == "zh"
    assert preferences.set_language("en-US") == "en"
    assert preferences.language() == "en"
    assert preferences.set_language("xx") == "zh"
    assert preferences.language() == "zh"
    (tmp_path / "prefs.json").write_text("not json", encoding="utf-8")
    assert preferences.language() == "zh"


def test_agent_template_follows_the_language_with_its_own_marker(tmp_path):
    from crystalpilot.workbench import agents_md as am

    zh_text = am.render_agents_md()
    en_text = am.render_agents_md(language="en")
    assert zh_text.startswith(am.VERSION_MARKER)
    assert en_text.startswith(am.VERSION_MARKER.replace(" -->", "-en -->"))
    assert "与用户交流用中文。" in zh_text and "中文 SUMMARY.md" in zh_text
    assert "与用户交流用中文" not in en_text
    assert "communicate with the user in English" in en_text
    assert "英文 SUMMARY.md" in en_text
    tools_only_en = am.render_agents_md("tools_only", language="en")
    assert tools_only_en.startswith(am.VERSION_MARKER_TOOLS_ONLY.replace(" -->", "-en -->"))
    assert "英文 `SUMMARY.md`" in tools_only_en
    # the rest of the template is identical: only the directive lines differ
    diff = [a for a, b in zip(zh_text.splitlines(), en_text.splitlines()) if a != b]
    assert 1 <= len(diff) <= 3, diff
    # a language switch regenerates the project's file, both ways
    f = tmp_path / "AGENTS.md"
    assert am.ensure_agents_md(tmp_path)["action"] == "written"
    assert am.ensure_agents_md(tmp_path, language="zh")["action"] == "current"
    r = am.ensure_agents_md(tmp_path, language="en")
    assert r["action"] == "written" and r["language"] == "en"
    assert f.read_text(encoding="utf-8") == en_text
    assert am.ensure_agents_md(tmp_path, language="en")["action"] == "current"
    assert am.ensure_agents_md(tmp_path)["action"] == "written"
    assert f.read_text(encoding="utf-8") == zh_text
    assert am.agents_md_sha256(language="en") != am.agents_md_sha256()


def test_language_route_stores_the_choice_and_rejects_unknown_values(tmp_path, monkeypatch):
    from crystalpilot.workbench import preferences
    from server.app import app

    monkeypatch.setenv("CRYSTALPILOT_PREFERENCES_FILE", str(tmp_path / "prefs.json"))
    client = TestClient(app, base_url="http://127.0.0.1")  # the host guard admits loopback only
    assert client.get("/api/language").json() == {"language": "zh"}
    res = client.post("/api/language", json={"language": "en"})
    assert res.status_code == 200
    body = res.json()
    assert body["language"] == "en" and isinstance(body["projects"], list)
    assert preferences.language() == "en"
    assert client.get("/api/language").json() == {"language": "en"}
    assert client.post("/api/language", json={"language": "fr"}).status_code == 400
    assert preferences.language() == "en"
    assert client.post("/api/language", json={"language": "zh"}).json()["language"] == "zh"


def test_new_threads_get_the_english_directive_only_in_english(tmp_path, monkeypatch):
    from crystalpilot.workbench import core, preferences

    monkeypatch.setenv("CRYSTALPILOT_PREFERENCES_FILE", str(tmp_path / "prefs.json"))
    assert core._language_instruction() == ""
    preferences.set_language("en")
    text = core._language_instruction()
    assert "communicate with them in English" in text and "SUMMARY.md" in text
