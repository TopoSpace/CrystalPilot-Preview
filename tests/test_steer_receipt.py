"""Steer receipts (round-3 R6): a 插话 has three states the user can see -
accepted (optimistic bubble), persisted (user_steer in the transcript,
with its eid) and submitted to the model (steer_receipt). When the
app-server refuses the turn_steer the words are NOT lost: the transcript
keeps them and the receipt says "failed" with the error, so the client
can offer a retry instead of pretending the model heard it."""
from __future__ import annotations

from typing import Any

from crystalpilot.workbench.core import TaskSession


class _Wb:
    def __init__(self):
        self.events: list[dict[str, Any]] = []

    def _log_event(self, thread_id, ev):
        ev = dict(ev)
        self.events.append(ev)
        return len(self.events)          # eid = 1-based line index


class _Handle:
    def __init__(self, fail: Exception | None = None):
        self.fail = fail
        self.inputs: list[Any] = []

    def steer(self, run_input):
        self.inputs.append(run_input)
        if self.fail is not None:
            raise self.fail
        return {"ok": True}


def _session(handle) -> TaskSession:
    task = TaskSession.__new__(TaskSession)
    task.wb = _Wb()
    task.thread_id = "t1"
    task._active_turn = handle
    return task


def test_submitted_receipt_follows_the_logged_steer():
    h = _Handle()
    task = _session(h)
    eid, receipt = task.steer("把孔里的峰当客体试试", display_text="把孔里的峰当客体试试")
    assert eid == 1 and h.inputs == ["把孔里的峰当客体试试"]
    kinds = [e["kind"] for e in task.wb.events]
    assert kinds == ["user_steer", "steer_receipt"]
    assert receipt["status"] == "submitted" and receipt["steer_eid"] == 1
    assert "error" not in receipt
    assert task.wb.events[1]["status"] == "submitted"


def test_failed_submission_keeps_the_words_and_names_the_error():
    h = _Handle(fail=RuntimeError("turn/steer: turn already completed"))
    task = _session(h)
    eid, receipt = task.steer("先别删 O5")
    assert eid == 1
    assert receipt["status"] == "failed"
    assert "turn already completed" in receipt["error"]
    assert receipt["error"].startswith("RuntimeError")
    # the transcript holds both: the user's words and the failed receipt
    assert [e["kind"] for e in task.wb.events] == ["user_steer", "steer_receipt"]
    assert task.wb.events[0]["text"] == "先别删 O5"
    assert task.wb.events[1]["steer_eid"] == 1


def test_idle_turn_has_no_receipt():
    task = _session(None)
    assert task.steer("hello") == (None, None)
    assert task.wb.events == []
