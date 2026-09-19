"""MCP server: calls on one project queue instead of failing "server busy".

pa1: the exec harness batches calls with Promise.all; 295 batches ran, and
in the 5 whose leading member held the lock for >10 s every trailing member
was rejected with a message blaming a client interrupt that never happened
(11 rejections). The agent re-issued them serially and lost a turn each
time; one concluded its output had been truncated.
"""
from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest

from crystalpilot.mcp import server as srv
from crystalpilot.tools.base import ToolResult


class _SlowProject:
    def __init__(self, delay: float):
        self.delay = delay
        self.calls: list[str] = []

    def invoke_tool(self, name, arguments, progress=None, cancel_event=None):
        self.calls.append(name)
        time.sleep(self.delay)
        return ToolResult(ok=True, summary={"name": name})


def _handle(tmp_path, delay):
    h = srv.ProjectHandle(tmp_path)
    h._project = _SlowProject(delay)
    return h


def test_second_call_waits_its_turn_and_reports_the_queue(tmp_path,
                                                          monkeypatch):
    monkeypatch.setattr(srv, "QUEUE_PING_S", 0.2)
    h = _handle(tmp_path, delay=1.0)
    pings: list[str] = []
    results: dict[str, dict] = {}

    def first():
        results["a"] = h.call("refine", {})

    def second():
        time.sleep(0.1)
        results["b"] = h.call("inspect_model", {}, progress=pings.append)

    ta, tb = threading.Thread(target=first), threading.Thread(target=second)
    ta.start(); tb.start(); ta.join(); tb.join()
    assert results["a"]["ok"] and results["b"]["ok"]
    assert h._project.calls == ["refine", "inspect_model"]   # serialized
    assert pings and all("queued behind 'refine'" in p for p in pings)
    assert "nothing was interrupted" in pings[0]
    assert results["b"]["summary"]["queued_s"] >= 0.5
    assert "queued_s" not in results["a"]["summary"]


def test_unqueued_call_carries_no_queue_field(tmp_path):
    h = _handle(tmp_path, delay=0.0)
    out = h.call("inspect_model", {}, progress=lambda m: None)
    assert out["ok"] and "queued_s" not in out["summary"]


def test_gives_up_only_after_queue_max(tmp_path, monkeypatch):
    monkeypatch.setattr(srv, "QUEUE_PING_S", 0.1)
    monkeypatch.setattr(srv, "QUEUE_MAX_S", 0.35)
    h = _handle(tmp_path, delay=2.0)
    threading.Thread(target=lambda: h.call("refine", {}), daemon=True).start()
    time.sleep(0.1)
    t0 = time.time()
    out = h.call("inspect_model", {})
    assert not out["ok"]
    assert "gave up waiting" in out["error"]
    assert "'refine'" in out["error"]
    assert "nothing needs killing" in out["error"]
    assert 0.3 <= time.time() - t0 < 1.5
    assert h._project.calls == ["refine"]


def test_resources_list_is_answered_with_an_empty_list():
    import mcp.types as types
    server = srv.build_server(SimpleNamespace(ready=True, project_dir=None))
    assert types.ListResourcesRequest in server.request_handlers
    assert types.CallToolRequest in server.request_handlers


def test_cancelled_queue_wait_never_runs_tool(tmp_path, monkeypatch):
    monkeypatch.setattr(srv, "QUEUE_PING_S", .1)
    handle = _handle(tmp_path, delay=0)
    cancel = threading.Event()
    handle._lock.acquire()
    output = []
    thread = threading.Thread(target=lambda: output.append(
        handle.call("refine", {}, cancel_event=cancel)))
    thread.start()
    try:
        cancel.set()
        thread.join(2)
        assert not thread.is_alive()
        assert not output[0]["ok"]
        assert output[0]["summary"]["tool_status"]["execution"] == "cancelled"
        assert handle._project.calls == []
    finally:
        handle._lock.release()
        thread.join(2)


def test_busy_message_no_longer_blames_a_client_interrupt():
    import inspect
    src = inspect.getsource(srv.ProjectHandle.call)
    assert "interrupted client request does not stop" not in src
