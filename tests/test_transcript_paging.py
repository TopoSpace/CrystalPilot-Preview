"""Round-3 R1: event identity (eid), transcript paging, channel generation,
stored command output and the browser diagnostics sink. TestClient only -
no live agent, no codex (the pool never opens a project here)."""
import asyncio
import json
import sys
import types
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from crystalpilot.workbench.core import (RESULTS_DIRNAME, Workbench,  # noqa: E402
                                         _count_lines, normalize_notification)
from crystalpilot.workbench.service import Channel  # noqa: E402


@pytest.fixture(scope="module")
def client():
    from server.app import app
    return TestClient(app, base_url="http://localhost")


def _project(tmp_path: Path, n_events: int = 25, *, bad_line_at: int | None = None) -> Path:
    p = tmp_path / "proj"
    p.mkdir()
    (p / ".crystalpilot-workbench.json").write_text(json.dumps({
        "threads": [{"thread_id": "t1", "task_id": "task_x", "title": "t"}],
        "settings": {}}), encoding="utf-8")
    task = p / RESULTS_DIRNAME / "task_x"
    task.mkdir(parents=True)
    lines = []
    for i in range(1, n_events + 1):
        if bad_line_at == i:
            lines.append("{not json")
            continue
        kind = "user_message" if i % 10 == 1 else "tool_completed"
        # old transcripts carry no eid at all; the route must assign one
        lines.append(json.dumps({"kind": kind, "ts": 1000.0 + i, "text": f"m{i}"}))
    (task / "transcript.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    out = task / "command_output"
    out.mkdir()
    (out / "item_abc.txt").write_text("x" * 5000 + "\nEND", encoding="utf-8")
    return p


class TestTranscriptPaging:
    def test_newest_page_carries_line_index_eids(self, client, tmp_path):
        p = _project(tmp_path)
        r = client.get("/api/threads/transcript",
                       params={"thread_id": "t1", "project": str(p), "limit": 10})
        assert r.status_code == 200, r.text
        j = r.json()
        assert [e["eid"] for e in j["events"]] == list(range(16, 26))
        assert j["total"] == 25 and j["has_more"] is True
        assert j["oldest_eid"] == 16
        # project not open in the pool: no live numbering to resume from
        assert j["live_cursor"] == 0 and j["generation"] is None

    def test_before_pages_backwards_to_the_first_line(self, client, tmp_path):
        p = _project(tmp_path)
        base = {"thread_id": "t1", "project": str(p), "limit": 10}
        j = client.get("/api/threads/transcript", params={**base, "before": 16}).json()
        assert [e["eid"] for e in j["events"]] == list(range(6, 16))
        assert j["has_more"] is True and j["oldest_eid"] == 6
        j = client.get("/api/threads/transcript", params={**base, "before": 6}).json()
        assert [e["eid"] for e in j["events"]] == [1, 2, 3, 4, 5]
        assert j["has_more"] is False and j["oldest_eid"] == 1
        j = client.get("/api/threads/transcript", params={**base, "before": 1}).json()
        assert j["events"] == [] and j["oldest_eid"] is None and j["has_more"] is False

    def test_default_page_is_the_whole_short_transcript(self, client, tmp_path):
        p = _project(tmp_path, n_events=7)
        j = client.get("/api/threads/transcript",
                       params={"thread_id": "t1", "project": str(p)}).json()
        assert [e["eid"] for e in j["events"]] == [1, 2, 3, 4, 5, 6, 7]
        assert j["has_more"] is False and j["total"] == 7

    def test_malformed_line_keeps_its_eid_slot(self, client, tmp_path):
        # identity is the line index, so a corrupt line must not shift the
        # eids of everything after it (that would re-duplicate on reload)
        p = _project(tmp_path, n_events=5, bad_line_at=3)
        j = client.get("/api/threads/transcript",
                       params={"thread_id": "t1", "project": str(p)}).json()
        assert [e["eid"] for e in j["events"]] == [1, 2, 4, 5]
        assert j["total"] == 5

    def test_unknown_thread_404s(self, client, tmp_path):
        p = _project(tmp_path)
        r = client.get("/api/threads/transcript",
                       params={"thread_id": "nope", "project": str(p)})
        assert r.status_code == 404


class TestCommandOutput:
    def test_stored_output_is_served_in_full(self, client, tmp_path):
        p = _project(tmp_path)
        r = client.get("/api/threads/command_output",
                       params={"thread_id": "t1", "project": str(p),
                               "item_id": "item/abc"})
        assert r.status_code == 200, r.text
        assert r.text.endswith("END") and len(r.text) > 5000

    def test_missing_output_404s(self, client, tmp_path):
        p = _project(tmp_path)
        r = client.get("/api/threads/command_output",
                       params={"thread_id": "t1", "project": str(p),
                               "item_id": "other"})
        assert r.status_code == 404

    def test_path_tricks_stay_inside_the_folder(self, client, tmp_path):
        p = _project(tmp_path)
        r = client.get("/api/threads/command_output",
                       params={"thread_id": "t1", "project": str(p),
                               "item_id": "../../transcript"})
        assert r.status_code == 404


class TestEventIdentity:
    def _wb(self, tmp_path: Path):
        """A Workbench-shaped stub: _log_event only touches these fields."""
        import threading
        proj = types.SimpleNamespace(results_root=tmp_path / RESULTS_DIRNAME)
        (proj.results_root / "task_x").mkdir(parents=True)
        return types.SimpleNamespace(
            project=proj, _task_by_thread={"t1": "task_x"},
            _log_lock=threading.Lock(), _eids={})

    def test_eids_continue_from_the_existing_file(self, tmp_path):
        wb = self._wb(tmp_path)
        path = wb.project.results_root / "task_x" / "transcript.jsonl"
        path.write_text('{"kind":"a"}\n{"kind":"b"}\n{"kind":"c"}\n', encoding="utf-8")
        assert _count_lines(path) == 3
        ev = {"kind": "tool_completed", "ts": 1.0}
        assert Workbench._log_event(wb, "t1", ev) == 4
        assert ev["eid"] == 4  # the same dict the channel will push
        assert Workbench._log_event(wb, "t1", {"kind": "x"}) == 5
        lines = path.read_text(encoding="utf-8").splitlines()
        assert json.loads(lines[3])["eid"] == 4 and json.loads(lines[4])["eid"] == 5

    def test_unknown_thread_logs_nothing(self, tmp_path):
        wb = self._wb(tmp_path)
        ev = {"kind": "x"}
        assert Workbench._log_event(wb, "ghost", ev) is None
        assert "eid" not in ev

    def test_channel_generation_is_per_channel(self):
        a, b = Channel(), Channel()
        assert a.generation and a.generation != b.generation

    def test_sse_opens_with_a_hello_carrying_the_generation(self):
        from crystalpilot.workbench.routes import _sse
        ch = Channel()
        ch.push({"kind": "idle"})
        resp = _sse(ch, 0)

        async def first_two():
            it = resp.body_iterator
            return [await it.__anext__(), await it.__anext__()]

        chunks = asyncio.run(first_two())
        assert chunks[0].startswith("retry:")
        assert chunks[1].startswith("data: ") and "id:" not in chunks[1]
        hello = json.loads(chunks[1][len("data: "):].strip())
        assert hello["kind"] == "channel_hello"
        assert hello["generation"] == ch.generation and hello["seq"] == 1


class TestCommandOutputCapture:
    def _payload(self, item):
        return types.SimpleNamespace(item=item)

    def test_completed_command_keeps_tail_and_hands_over_the_full_text(self):
        out = "line\n" * 800  # 4000 chars
        ev = normalize_notification("item/completed", self._payload({
            "type": "commandExecution", "id": "item_7", "command": "dir",
            "status": "completed", "exit_code": 0, "aggregated_output": out}))
        assert ev["kind"] == "command_completed"
        assert len(ev["output_tail"]) == 1500 and ev["output_len"] == 4000
        assert ev["item_id"] == "item_7" and ev["_output_full"] == out

    def test_short_output_has_no_side_file(self):
        ev = normalize_notification("item/completed", self._payload({
            "type": "commandExecution", "id": 3, "command": "dir",
            "status": "completed", "exit_code": 0, "aggregated_output": "ok"}))
        assert ev["output_len"] == 2 and "_output_full" not in ev
        assert ev["item_id"] == "3"

    def test_started_command_is_unchanged(self):
        ev = normalize_notification("item/started", self._payload({
            "type": "commandExecution", "id": "i", "command": "dir",
            "status": "in_progress", "exit_code": None, "aggregated_output": ""}))
        assert ev["output_tail"] is None and "output_len" not in ev


class TestUiDiagnostics:
    def test_report_is_appended_as_one_json_line(self, client, tmp_path, monkeypatch):
        from crystalpilot.workbench import routes
        log = tmp_path / "ui-diagnostics.jsonl"
        monkeypatch.setattr(routes, "UI_DIAGNOSTICS_LOG", log)
        body = {"area": "chat", "message": "TypeError: x is null",
                "stack": "s" * 30000, "context": {"threadId": "t1", "cursor": 42}}
        r = client.post("/api/ui/diagnostics", json=body)
        assert r.status_code == 200 and r.json()["ok"] is True
        rec = json.loads(log.read_text(encoding="utf-8").splitlines()[-1])
        assert rec["area"] == "chat" and rec["context"]["cursor"] == 42
        assert len(rec["stack"]) < 30000 and "received" in rec

    def test_non_object_body_rejected(self, client):
        r = client.post("/api/ui/diagnostics", json=[1, 2, 3])
        assert r.status_code in (400, 422)
