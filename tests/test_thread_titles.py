import json
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest

from crystalpilot.workbench.core import ProjectState, Workbench
from crystalpilot.workbench.service import ProjectSession
from crystalpilot.workbench import thread_titles


def workbench(tmp_path, records):
    wb = Workbench.__new__(Workbench)
    wb.project = ProjectState(tmp_path, records, {"model_override": "gpt-5.6-luna", "model_provider_override": "test-provider"})
    wb._lock = threading.Lock()
    wb._task_by_thread = {}
    wb._client = Mock()
    wb._client.thread_start.return_value = SimpleNamespace(thread=SimpleNamespace(id="new-thread"))
    return wb


def session(wb):
    ps = ProjectSession.__new__(ProjectSession)
    ps.wb = wb
    ps._closed = False
    ps._title_lock = threading.Lock()
    ps._push = Mock()
    return ps


def test_only_new_unnamed_records_qualify_and_claim_is_persistent(tmp_path):
    wb = workbench(tmp_path, [])
    wb.new_task()
    assert wb.project.threads[0]["title_source"] == "unnamed"
    assert wb.claim_auto_title("new-thread", "sample42 · 晶体求解", "gpt-5.6-luna")
    assert wb.claim_auto_title("new-thread", "again", "another-model") is None
    saved = json.loads(wb.project.state_file.read_text())
    assert saved["threads"][0]["title_source"] == "auto_pending"
    reopened = workbench(tmp_path, saved["threads"])
    assert reopened.claim_auto_title("new-thread", "after restart", "gpt-5.6-luna") is None


@pytest.mark.parametrize("source", [None, "manual", "auto", "fallback", "auto_pending"])
def test_already_named_and_historical_threads_never_call_a_model(tmp_path, monkeypatch, source):
    record = {"thread_id": "t", "task_id": "task", "title": "历史样品 · 精修"}
    if source is not None:
        record["title_source"] = source
    ps = session(workbench(tmp_path, [record]))
    generate = Mock()
    monkeypatch.setattr(thread_titles, "generate_title", generate)
    ps._start_auto_title("t", "继续检查", [])
    generate.assert_not_called()
    assert record["title"] == "历史样品 · 精修"


def test_selected_model_and_dataset_are_used_once_and_manual_rename_wins(tmp_path, monkeypatch):
    (tmp_path / "alanine_042.hkl").touch()
    wb = workbench(tmp_path, [{"thread_id": "t", "task_id": "task", "title": "task", "title_source": "unnamed"}])
    ps = session(wb)
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    calls = []

    def generate(context, **kwargs):
        calls.append((context, kwargs))
        entered.set()
        assert release.wait(3)
        finished.set()
        return "alanine_042 · 单晶求解"

    monkeypatch.setattr(thread_titles, "generate_title", generate)
    ps._start_auto_title("t", "请解析丙氨酸的结构", [])
    assert entered.wait(3)
    ps._start_auto_title("t", "又一条消息", [])
    ps.rename("t", "我的样品 · 最终验证")
    release.set()
    assert finished.wait(3)
    # Acquire the same lock used to commit the background result.
    with ps._title_lock:
        assert wb.project.threads[0]["title"] == "我的样品 · 最终验证"
        assert wb.project.threads[0]["title_source"] == "manual"
    assert len(calls) == 1
    assert calls[0][1] == {"model": "gpt-5.6-luna", "provider": "test-provider"}
    assert "alanine_042.hkl" in calls[0][0]["data_files"]


@pytest.mark.parametrize("fail", [False, True])
def test_success_and_failure_both_finish_the_single_attempt(tmp_path, monkeypatch, fail):
    wb = workbench(tmp_path, [{"thread_id": "t", "task_id": "task", "title": "task", "title_source": "unnamed"}])
    ps = session(wb)
    done = threading.Event()
    original = wb.finish_auto_title
    def finish(*args):
        result = original(*args)
        done.set()
        return result
    wb.finish_auto_title = finish
    generate = Mock(side_effect=RuntimeError("private failure") if fail else None, return_value="sample42 · 结构验证")
    monkeypatch.setattr(thread_titles, "generate_title", generate)
    ps._start_auto_title("t", "验证 sample42", [])
    assert done.wait(3)
    ps._start_auto_title("t", "继续", [])
    generate.assert_called_once()
    assert wb.project.threads[0]["title_source"] == ("fallback" if fail else "auto")
    assert "private failure" not in json.dumps(wb.project.threads)


def test_request_uses_isolated_provider_and_extracts_only_message_text(monkeypatch):
    monkeypatch.setattr(thread_titles.codex_config, "load", lambda: {"model_providers": {"chosen": {
        "base_url": "https://example.test/openai/v1", "wire_api": "responses", "query_params": {"api-version": "test"}}}})
    monkeypatch.setattr(thread_titles.providers, "read_key", lambda pid: "test-secret")
    from crystalpilot.workbench import model_catalog
    monkeypatch.setattr(model_catalog, "effort_ladder_of", lambda _: ("low", "high"))
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(200, json={"status": "completed", "output": [
            {"type": "reasoning", "summary": [{"text": "ignore this"}]},
            {"type": "message", "content": [{"type": "output_text", "text": "alanine_042 · 单晶求解"}]}]})
    client_type = httpx.Client
    monkeypatch.setattr(thread_titles.httpx, "Client", lambda **kwargs: client_type(transport=httpx.MockTransport(respond), **kwargs))
    title = thread_titles.generate_title({"project": "alanine_042", "task": "解晶", "data_files": []}, model="gpt-5.6-luna", provider="chosen")
    assert title == "alanine_042 · 单晶求解"
    assert len(calls) == 1
    request = calls[0]
    assert request.url.path == "/openai/v1/responses"
    assert request.url.params["api-version"] == "test"
    body = json.loads(request.content)
    assert body["model"] == "gpt-5.6-luna" and body["store"] is False
    assert body["reasoning"] == {"effort": "low"}
    assert "tools" not in body
    assert "test-secret" not in request.content.decode()
