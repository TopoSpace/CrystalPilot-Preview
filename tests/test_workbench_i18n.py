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
