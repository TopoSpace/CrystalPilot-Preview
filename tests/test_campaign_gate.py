"""Campaign runner: warm-up turn, agent-side liveness, anonymous folders.

pa1: 4 of 32 cells made zero crystalpilot calls. The first model request
of a fresh codex thread is built before the lazily-spawned MCP answers
tools/list, the agents probed ALL_TOOLS once, found nothing, and took the
old CLI clause as their licence. Nothing in the workbench watched for
"MCP up, agent never used it"; the readiness probe reports the
app-server's own connection (63 tools before any thread exists).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from crystalpilot.benchmark import agent_campaign as ac


class _FakeApi:
    """Records posts; serves scripted SSE events per thread."""

    def __init__(self, events_by_call: list[list[tuple[int, dict]]]):
        self.posts: list[tuple[str, dict]] = []
        self._scripts = list(events_by_call)
        self.n_tools = 63

    def post(self, path: str, body: dict) -> dict:
        self.posts.append((path, dict(body)))
        if path == "/threads/send":
            return {"thread_id": body.get("thread_id") or "thr-1",
                    "task_id": "task_x"}
        if path == "/projects/mcp_status":
            return {"present": True, "n_tools": self.n_tools}
        return {"ok": True}

    def get(self, path: str) -> dict:
        return {"threads": [{"thread_id": "thr-1", "busy": False}]}

    def sse_events(self, thread_id: str, after: int):
        script = self._scripts.pop(0) if self._scripts else []
        for seq, ev in script:
            if seq > after:
                yield seq, ev


def _case(tmp_path: Path, api: _FakeApi, defaults: dict | None = None
          ) -> ac.CaseRun:
    c = ac.Campaign.__new__(ac.Campaign)
    c.name = "t"
    c.api = api
    c.defaults = defaults or {}
    c.projects_root = str(tmp_path / "projects")
    c.work = tmp_path / "work"
    c.work.mkdir()
    c.state_path = c.work / "state.json"
    c.state = {}
    c.save_state = lambda: c.state_path.write_text(
        json.dumps(c.state), encoding="utf-8")
    case = {"name": "case-a", "brief": "解这个结构：{data_dir}",
            "data_dir": "X:/data"}
    return ac.CaseRun(c, case)


def _turn(seq0: int, *evs: dict, done: bool = True) -> list[tuple[int, dict]]:
    out = [(seq0 + i, ev) for i, ev in enumerate(evs)]
    if done:
        out.append((seq0 + len(evs), {"kind": "turn_completed",
                                       "duration_ms": 1200}))
    return out


def test_warm_up_turn_precedes_the_brief_on_the_same_thread(tmp_path):
    api = _FakeApi([_turn(1, {"kind": "agent_message", "text": "就绪"})])
    run = _case(tmp_path, api)
    tid = run._first_send_gated()
    sends = [(p, b) for p, b in api.posts if p == "/threads/send"]
    assert len(sends) == 2
    assert sends[0][1]["message"] == ac.CaseRun.WARMUP
    assert "thread_id" not in sends[0][1]          # first=True: new thread
    assert sends[1][1]["message"] == "解这个结构：X:/data"
    assert sends[1][1]["thread_id"] == "thr-1" == tid   # same thread
    assert run.st["warmup_ms"] == 1200 and run.st["mcp_tools"] == 63


def test_failed_warm_up_restarts_the_engine_once(tmp_path):
    api = _FakeApi([_turn(1, {"kind": "turn_failed", "error": "boom"},
                          done=False),
                    _turn(10, {"kind": "agent_message", "text": "就绪"})])
    run = _case(tmp_path, api)
    tid = run._first_send_gated()
    assert tid == "thr-1"
    paths = [p for p, _ in api.posts]
    assert "/threads/interrupt" in paths and "/projects/restart_engine" in paths
    assert "attempt 1" in run.st["mcp_env_note"]
    assert paths.count("/threads/send") == 3      # warm-up, warm-up, brief


def test_liveness_steers_then_gives_up_without_crystalpilot_calls(tmp_path,
                                                                    monkeypatch):
    t = {"now": 1000.0}
    monkeypatch.setattr(ac.time, "time", lambda: t["now"])
    monkeypatch.setattr(ac.time, "sleep", lambda s: None)
    exec_ev = {"kind": "tool_completed", "server": None, "tool": "exec"}

    def script():
        # each event advances the clock by 100 s; liveness_s = 250
        for i in range(12):
            t["now"] += 100.0
            yield i + 1, dict(exec_ev)

    api = _FakeApi([])
    api.sse_events = lambda thread_id, after: script()
    run = _case(tmp_path, api, defaults={"liveness_s": 250})
    r = run.wait_turn("thr-1")
    assert r["status"] == "no_tools"
    steers = [b for p, b in api.posts if p == "/threads/steer"]
    assert len(steers) == 1
    assert "ALL_TOOLS" in steers[0]["message"]
    assert run.st["liveness_steered"] is True
    marks = [json.loads(l)["ev"]["action"] for l in
             (run.out_dir / "logs" / "sse.jsonl").read_text(
                 encoding="utf-8").splitlines()
             if '"runner_liveness"' in l]
    assert marks == ["steer", "give_up"]


def test_one_crystalpilot_call_silences_liveness(tmp_path, monkeypatch):
    t = {"now": 1000.0}
    monkeypatch.setattr(ac.time, "time", lambda: t["now"])
    monkeypatch.setattr(ac.time, "sleep", lambda s: None)

    def script():
        t["now"] += 50.0
        yield 1, {"kind": "tool_completed", "server": "crystalpilot",
                  "tool": "get_project_brief"}
        for i in range(10):
            t["now"] += 100.0
            yield i + 2, {"kind": "tool_completed", "server": None}
        yield 20, {"kind": "turn_completed"}

    api = _FakeApi([])
    api.sse_events = lambda thread_id, after: script()
    run = _case(tmp_path, api, defaults={"liveness_s": 250})
    r = run.wait_turn("thr-1")
    assert r["status"] == "completed"
    assert run.st["saw_crystalpilot"] is True
    assert not [p for p, _ in api.posts if p == "/threads/steer"]


def test_anonymous_project_folder_hides_the_case_name(tmp_path):
    api = _FakeApi([])
    run = _case(tmp_path, api, defaults={"anonymize_projects": True})
    assert run.project_dir.name != "case-a"
    assert run.project_dir.name == ac.anonymous_project_name("t", "case-a")
    assert run.project_dir.name.startswith("p") and len(run.project_dir.name) == 9
    # stable across runs (resume lands in the same folder), distinct per case
    assert ac.anonymous_project_name("t", "case-a") == run.project_dir.name
    assert ac.anonymous_project_name("t", "case-b") != run.project_dir.name
    # logs and grades still live under the readable case name
    assert run.out_dir.name == "case-a"


def test_plain_folder_when_not_anonymised(tmp_path):
    run = _case(tmp_path, _FakeApi([]))
    assert run.project_dir.name == "case-a"
