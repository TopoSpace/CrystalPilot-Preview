"""Fake advisor harness plus real spawned read-only MCP handles; no model or key access."""
from __future__ import annotations

import json
import multiprocessing
import queue
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from crystalpilot.refine import tools_specialist as specialist
from crystalpilot.refine.specialist_snapshot import create_snapshot
from crystalpilot.refine.transactions import LockTimeout, project_transaction

MP = multiprocessing.get_context("spawn")
VERDICT = {"assessment": "snapshot examined", "recommendation": "verify", "confidence": "low",
           "evidence": ["local tool output"], "risks": ["not a historical data replay"]}
SETTINGS = {"model_override": "gpt-6-astra", "model_provider_override": "crystalpilot",
            "effort_override": "xhigh", "knowledge_mode": "tools_only"}


def _project(tmp_path, monkeypatch, structure_only=False):
    monkeypatch.setenv("CRYSTALPILOT_SPECIALISTS", "1")
    monkeypatch.delenv("CRYSTALPILOT_MCP_READONLY", raising=False)
    if structure_only:
        from tests.test_upgrade_structure_document import CIF
        from crystalpilot.refine.project import RefineProject
        source = tmp_path / "source.cif"
        source.write_text(CIF, encoding="utf-8")
        project = RefineProject.create_structure_only(tmp_path / "proj", source)
    else:
        from tests.test_shelxl_tools import _formate_project
        project = _formate_project(tmp_path)
    (project.dir / ".crystalpilot-workbench.json").write_text(json.dumps({
        "settings": {**SETTINGS, "api_key": "fake-not-a-credential", "enable_specialists": True},
        "threads": [{"id": "parent-history-not-for-snapshot"}],
    }), encoding="utf-8")
    return project


def _scientific_bytes(project):
    paths = [project.dir / "context.json", project.nodes.state_path,
             project.dir / ".crystalpilot-workbench.json"]
    if project.hkl_path:
        paths.append(project.hkl_path)
    paths += [path for path in project.nodes.nodes_dir.rglob("*") if path.is_file()]
    return {str(path): path.read_bytes() for path in paths}


def _snapshot_child(directory, original, knowledge_mode, results):
    import os
    os.environ["CRYSTALPILOT_MCP_READONLY"] = "1"
    os.environ["CRYSTALPILOT_KNOWLEDGE_MODE"] = knowledge_mode
    try:
        from crystalpilot.mcp.server import ProjectHandle
        handle = ProjectHandle(Path(directory))
        specs = handle.specs()
        brief = handle.call("get_project_brief", {})
        inspection = handle.call("inspect_model", {})
        blocked = handle.call("set_weights", {"a": .2})
        try:
            with project_transaction(original, timeout_s=.15):
                parent_locked = False
        except LockTimeout:
            parent_locked = True
        results.put({"brief": brief, "inspection": inspection, "blocked": blocked,
                     "parent_locked": parent_locked,
                     "recursive_tool": any(s["name"] == "consult_specialist" for s in specs),
                     "node": handle._project.nodes.state()["active_node"]})
    except BaseException as exc:
        results.put({"error": repr(exc)})


def _held_project(directory, ready, release):
    with project_transaction(directory):
        ready.set()
        release.wait(15)


def _lock_probe(directory, results):
    try:
        with project_transaction(directory, timeout_s=.5):
            results.put(True)
    except Exception as exc:
        results.put(repr(exc))


def _join(child):
    child.join(30)
    if child.is_alive():
        child.terminate()
        child.join(5)
        pytest.fail("owned test subprocess failed to finish")


def _fake_harness(monkeypatch, events_factory):
    from crystalpilot.workbench import core
    records = {"closed": threading.Event(), "interrupted": threading.Event()}

    class FakeTask:
        def send(self, prompt, **kwargs):
            records["send"] = (prompt, kwargs)
            yield from events_factory(records)

        def interrupt(self):
            records["interrupted"].set()

    class FakeWorkbench:
        def __init__(self, state, **kwargs):
            records["state"] = state
            records["workbench"] = kwargs
            records["callback"] = kwargs["event_cb"]

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            records["worker_exited"] = True
            self.close()

        def new_task(self, **kwargs):
            records["new_task"] = kwargs
            return FakeTask()

        def close(self):
            records["closed"].set()

    monkeypatch.setattr(core, "Workbench", FakeWorkbench)
    return records


def _final_events(records):
    yield {"kind": "agent_message", "text": json.dumps(VERDICT)}
    yield {"kind": "turn_completed"}


@pytest.mark.parametrize("structure_only", [False, True])
def test_spawned_readonly_child_reads_snapshot_while_parent_lock_stays_held(
        tmp_path, monkeypatch, structure_only):
    project = _project(tmp_path, monkeypatch, structure_only)
    before = _scientific_bytes(project)
    version = project.nodes.version()

    def events(records):
        results = MP.Queue()
        state = records["state"]
        child = MP.Process(target=_snapshot_child, args=(str(state.path), str(project.dir),
                                                        SETTINGS["knowledge_mode"], results))
        child.start()
        try:
            records["child"] = results.get(timeout=90)
        finally:
            _join(child)
        yield from _final_events(records)

    records = _fake_harness(monkeypatch, events)
    result = project.invoke_tool("consult_specialist", {
        "specialty": "chemistry", "question": "inspect this fixed model", "timeout_s": 120})
    assert result.ok, result.error
    child = records["child"]
    assert "error" not in child, child
    assert child["brief"]["ok"] and child["inspection"]["ok"], child
    assert not child["blocked"]["ok"] and not child["recursive_tool"]
    assert child["parent_locked"] is True
    assert child["node"] == version["node"]
    assert _scientific_bytes(project) == before
    snapshot = records["state"].path
    assert snapshot != project.dir
    assert not (snapshot / ".crystalpilot-workbench.json").exists()
    assert records["state"].settings == SETTINGS
    assert records["workbench"]["multi_agent"] is False
    assert records["workbench"]["mcp_readonly"] is True
    assert records["new_task"]["model_provider"] == "crystalpilot"
    kwargs = records["send"][1]["turn_kwargs"]
    assert kwargs["model"] == "gpt-6-astra" and kwargs["effort"] == "xhigh"
    assert kwargs["sandbox"].value == "read-only"
    source = result.summary["source_state"]
    assert source["project"] == str(project.dir.resolve())
    assert source["node"] == version["node"]
    assert source["project_revision"] == version["project_revision"]
    assert source["model_revision"] == version["revision"]
    assert source["historical_data_revision"] == (None if structure_only else version["data_revision"])
    assert result.summary["specialist_cost"]["configuration"]["parent_turn_overrides_known"] is False
    if not structure_only:
        assert (snapshot / "crystal.hkl").read_bytes() == project.hkl_path.read_bytes()
    assert not list(snapshot.rglob("*.ccp4"))


def test_historical_reflection_nodes_refuse_before_starting_harness(tmp_path, monkeypatch):
    project = _project(tmp_path, monkeypatch)
    assert project.invoke_tool("set_weights", {"a": .12}).ok
    meta_path = project.nodes.node_dir("n0000") / "node.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta.pop("data_revision")
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    records = _fake_harness(monkeypatch, _final_events)
    before = _scientific_bytes(project)
    result = project.invoke_tool("consult_specialist", {
        "specialty": "density", "question": "old data?", "node": "n0000"})
    assert not result.ok and "unknown reflection data" in result.error
    assert "state" not in records
    assert _scientific_bytes(project) == before
    project.checkout("n0000")
    result = project.invoke_tool("consult_specialist", {"specialty": "density", "question": "old active?"})
    assert not result.ok and "unknown" in result.error
    assert "state" not in records


def test_bound_historical_snapshot_uses_its_own_hkl(tmp_path, monkeypatch):
    from tests.test_data_versions import _other
    project = _project(tmp_path, monkeypatch)
    original = project.hkl_path.read_bytes()
    old_revision = project.nodes.node_meta("n0000")["data_revision"]
    _other(project)
    assert project.invoke_tool("swap_reflection_data", {"hkl": "other.hkl", "reason": "B"}).ok
    active = project.nodes.state()
    snapshot = create_snapshot(project, tmp_path / "historical", ref="n0000")
    assert (snapshot.directory / "crystal.hkl").read_bytes() == original
    assert snapshot.source["data_revision"] == old_revision
    assert snapshot.source["data_binding"] == "bound_revision"
    assert project.nodes.state() == active
    from crystalpilot.refine.project import RefineProject
    restored = RefineProject(snapshot.directory)
    restored.open()
    assert restored.hkl_path.read_bytes() == original


def test_hklf5_and_model_cards_are_copied_verbatim(tmp_path, monkeypatch):
    from tests.test_swap_data import _session_with_model, _write_hklf5
    project = _project(tmp_path, monkeypatch)
    _, fo = _session_with_model()
    _write_hklf5(project.dir / "twin5.hkl", fo, 40)
    result = project.invoke_tool("swap_reflection_data", {"hkl": "twin5.hkl", "reason": "snapshot test"})
    assert result.ok, result.error
    node = result.summary["node"]
    (project.nodes.node_dir(node) / "huge-map.ccp4").write_bytes(b"not necessary")
    snapshot = create_snapshot(project, tmp_path / "audit", deadline=time.monotonic() + 10)
    assert (snapshot.directory / "crystal.hkl").read_bytes() == project.hkl_path.read_bytes()
    copied = snapshot.directory / ".crystalpilot" / "refine" / "nodes" / node / "model.res"
    assert copied.read_bytes() == (project.nodes.node_dir(node) / "model.res").read_bytes()
    assert "HKLF 5" in copied.read_text(encoding="utf-8")
    assert not list(snapshot.directory.rglob("*.ccp4"))
    assert "sha256" not in json.dumps(snapshot.source)


def test_callback_and_iterator_tool_completions_are_not_double_counted(tmp_path, monkeypatch):
    project = _project(tmp_path, monkeypatch)

    def events(records):
        # Identical separate calls count twice, but each callback+yield counts once.
        for _ in range(2):
            event = {"kind": "tool_completed", "tool": "inspect_model"}
            records["callback"](dict(event))
            yield event
        event = {"kind": "token_usage", "total": {"input_tokens": 100, "output_tokens": 50}}
        records["callback"](dict(event))
        yield event
        yield from _final_events(records)

    _fake_harness(monkeypatch, events)
    result = project.invoke_tool("consult_specialist", {"specialty": "chemistry", "question": "count"})
    assert result.ok, result.error
    stats = result.summary["specialist_cost"]
    assert stats["n_tool_calls"] == 2
    assert stats["input_tokens"] == 100 and stats["output_tokens"] == 50


@pytest.mark.parametrize("cancelled", [False, True])
def test_bounded_stop_releases_parent_lock_and_late_result_cannot_publish(
        tmp_path, monkeypatch, cancelled):
    project = _project(tmp_path, monkeypatch)
    before = _scientific_bytes(project)
    started, release = threading.Event(), threading.Event()
    cancel = threading.Event()
    monkeypatch.setattr(specialist, "CLEANUP_GRACE_S", .05)

    def events(records):
        started.set()
        release.wait(10)
        yield from _final_events(records)

    records = _fake_harness(monkeypatch, events)

    def forbidden_rebuild(*args, **kwargs):
        pytest.fail("advisor cleanup must not start a fresh scientific reconstruction")

    monkeypatch.setattr(project, "checkout", forbidden_rebuild)
    replies = queue.Queue()
    caller = threading.Thread(target=lambda: replies.put(project.invoke_tool("consult_specialist", {
        "specialty": "chemistry", "question": "stop", "timeout_s": 1}, cancel_event=cancel)))
    t0 = time.monotonic()
    caller.start()
    try:
        assert started.wait(5)
        if cancelled:
            cancel.set()
        result = replies.get(timeout=4)
        assert time.monotonic() - t0 < 4
        assert not result.ok and result.summary["cleanup_pending"] is True
        assert records["closed"].is_set() and records["interrupted"].is_set()
        status = "cancelled" if cancelled else "timeout"
        assert result.summary["tool_status"]["execution"] == status
        out = Path(result.summary["transcript_dir"])
        diagnostic = (out / "consultation.json").read_bytes()
        assert json.loads(diagnostic)["status"] == status
        results = MP.Queue()
        child = MP.Process(target=_lock_probe, args=(str(project.dir), results))
        child.start()
        try:
            assert results.get(timeout=10) is True
        finally:
            _join(child)
        release.set()
        for _ in range(100):
            if records.get("worker_exited"):
                break
            time.sleep(.01)
        assert records.get("worker_exited")
        assert not (out / "verdict.json").exists()
        assert (out / "consultation.json").read_bytes() == diagnostic
        assert _scientific_bytes(project) == before
    finally:
        release.set()
        caller.join(5)


def test_project_queue_time_does_not_consume_advisor_execution_budget(tmp_path, monkeypatch):
    project = _project(tmp_path, monkeypatch)
    _fake_harness(monkeypatch, _final_events)
    ready, release = MP.Event(), MP.Event()
    holder = MP.Process(target=_held_project, args=(str(project.dir), ready, release))
    holder.start()
    replies = queue.Queue()
    caller = None
    try:
        assert ready.wait(15)
        caller = threading.Thread(target=lambda: replies.put(project.invoke_tool("consult_specialist", {
            "specialty": "chemistry", "question": "after queue", "timeout_s": 1})))
        caller.start()
        time.sleep(1.15)
        assert replies.empty() and project._operation_started_at is None
        release.set()
        result = replies.get(timeout=5)
        assert result.ok, result.error
        assert result.summary["specialist_cost"]["total_execution_s"] < 1
    finally:
        release.set()
        _join(holder)
        if caller is not None:
            caller.join(5)


def test_missing_overrides_remain_explicitly_unknown_not_invented(tmp_path, monkeypatch):
    project = _project(tmp_path, monkeypatch)
    (project.dir / ".crystalpilot-workbench.json").write_text('{"settings": {}}', encoding="utf-8")
    records = _fake_harness(monkeypatch, _final_events)
    result = project.invoke_tool("consult_specialist", {"specialty": "chemistry", "question": "defaults"})
    assert result.ok, result.error
    assert records["state"].settings == {}
    assert records["new_task"]["model_provider"] is None
    kwargs = records["send"][1]["turn_kwargs"]
    assert "model" not in kwargs and "effort" not in kwargs
    configuration = result.summary["specialist_cost"]["configuration"]
    assert configuration["model"] is None and configuration["parent_turn_overrides_known"] is False


def test_queue_budget_starts_after_project_ownership(tmp_path):
    from crystalpilot.mcp.server import ProjectHandle
    from crystalpilot.tools.budget import declared_budget_s, default_timeout_s
    assert default_timeout_s("consult_specialist") == 180
    assert declared_budget_s("consult_specialist", {"timeout_s": 1}) == 3
    handle = ProjectHandle(tmp_path)
    handle._project = SimpleNamespace(_operation_started_at=None)
    handle._running = ("consult_specialist", time.time() - 120)
    handle._running_budget_s = 3
    message, left = handle._queue_detail()
    assert "has not started" in message and left is None
    handle._project._operation_started_at = time.time()
    _, left = handle._queue_detail()
    assert 2.5 < left <= 3
