"""Real spawned-process ownership and operation consistency, using external fixtures."""
from __future__ import annotations

import json
import multiprocessing
import os
from pathlib import Path

import pytest

from crystalpilot.refine.nodes import NodeStore
from crystalpilot.refine.transactions import (LockTimeout, StateConflict,
                                              TransactionCancelled, project_transaction)

MP = multiprocessing.get_context("spawn")


def _holding(directory, ready, release):
    with project_transaction(directory, operation="test-holder"):
        ready.set()
        release.wait(30)


def _waiter(directory, ready, cancel, results):
    ready.set()
    try:
        with project_transaction(directory, timeout_s=2, cancel_event=cancel):
            results.put("acquired")
    except TransactionCancelled:
        results.put("cancelled")


def _crashing_holder(directory, ready):
    with project_transaction(directory):
        ready.set()
        os._exit(23)


def _join(process, timeout=30):
    process.join(timeout)
    if process.is_alive():
        process.terminate()
        process.join(10)
        pytest.fail(f"owned test child {process.pid} did not finish")


def _bare_commit(store):
    with store.staged_node() as stage:
        state, node, directory, _ = stage
        meta = {"id": node, "parent": state["active_node"], "revision": state["seq"] + 1,
                "tool": "test", "model": {"n_atoms": 0}}
        (directory / "model.res").write_text("TITL complete test node\n", encoding="ascii")
        (directory / "node.json").write_text(json.dumps(meta), encoding="utf-8")
        state["seq"] += 1
        state["active_node"] = state["branches"]["main"] = node
        store.publish_node(stage, meta)
        return node


def _crashing_publication(directory, after_replace):
    store = NodeStore(directory)
    real_save = store._save_state

    def crash(state):
        if after_replace:
            real_save(state)
        os._exit(24)

    store._save_state = crash
    _bare_commit(store)


def test_os_lock_timeout_and_wait_cancellation(tmp_path):
    ready, release = MP.Event(), MP.Event()
    holder = MP.Process(target=_holding, args=(str(tmp_path), ready, release))
    holder.start()
    try:
        assert ready.wait(15)
        with pytest.raises(LockTimeout) as error:
            with project_transaction(tmp_path, timeout_s=0.15):
                pytest.fail("second process acquired held lock")
        assert error.value.details["owner"]["pid"] == holder.pid
        cancel, waiting, results = MP.Event(), MP.Event(), MP.Queue()
        waiter = MP.Process(target=_waiter, args=(str(tmp_path), waiting, cancel, results))
        waiter.start()
        assert waiting.wait(15)
        cancel.set()
        assert results.get(timeout=10) == "cancelled"
        _join(waiter)
    finally:
        release.set()
        _join(holder)
    assert (tmp_path / ".crystalpilot" / "refine" / "project.lock").exists()


def test_crashed_owner_releases_permanent_lock(tmp_path):
    ready = MP.Event()
    process = MP.Process(target=_crashing_holder, args=(str(tmp_path), ready))
    process.start()
    assert ready.wait(15)
    _join(process)
    assert process.exitcode == 23
    lock = tmp_path / ".crystalpilot" / "refine" / "project.lock"
    identity = lock.stat().st_ino
    with project_transaction(tmp_path, timeout_s=0.5):
        assert lock.stat().st_ino == identity


def test_canonical_reentrant_multiple_store_lock(tmp_path):
    alias = str(tmp_path).upper() if os.name == "nt" else str(tmp_path / ".")
    with project_transaction(tmp_path):
        with project_transaction(alias, timeout_s=0):
            a, b = NodeStore(tmp_path), NodeStore(alias)
            node = _bare_commit(a)
            b.branch("alt")
            a.set_active(node)
            assert b.state()["branches"]["alt"] == node


@pytest.mark.parametrize("after_replace", [False, True])
def test_crash_between_node_rename_and_state_commit(tmp_path, after_replace):
    store = NodeStore(tmp_path)
    _bare_commit(store)
    child = MP.Process(target=_crashing_publication, args=(str(tmp_path), after_replace))
    child.start()
    _join(child)
    assert child.exitcode == 24
    state = store.state()  # recovery under OS ownership
    assert state["seq"] == (2 if after_replace else 1)
    assert len(store.list_nodes()["nodes"]) == state["seq"]
    assert not store.publication_path.exists()
    next_node = _bare_commit(store)
    assert next_node == ("n0002" if after_replace else "n0001")


def _project(tmp_path):
    from tests.test_shelxl_tools import _formate_project
    return _formate_project(tmp_path)


def _writer(directory, label, value, ready, go, results):
    try:
        from crystalpilot.mcp.server import ProjectHandle
        from crystalpilot.refine.project import RefineProject
        project = RefineProject(directory)
        project.open()
        handle = ProjectHandle(Path(directory))
        handle._project = project
        ready.set()
        assert go.wait(60)
        out = handle.call("edit_atoms", {"operations": [
            {"action": "set_u_iso", "atoms": [label], "u_iso": value}]})
        results.put(out)
    except BaseException as exc:
        results.put({"ok": False, "error": repr(exc)})
        ready.set()


def test_two_process_handles_edit_without_losing_either_model_change(tmp_path):
    project = _project(tmp_path)
    go, results = MP.Event(), MP.Queue()
    events = [MP.Event(), MP.Event()]
    children = [MP.Process(target=_writer, args=(str(project.dir), label, value,
                                               events[i], go, results))
                for i, (label, value) in enumerate((("C1", .031), ("O1", .047)))]
    for child in children:
        child.start()
    try:
        assert all(ready.wait(90) for ready in events)
        go.set()
        outputs = [results.get(timeout=120) for _ in children]
        assert all(out["ok"] for out in outputs), outputs
    finally:
        go.set()
        for child in children:
            _join(child, 120)
    project.invoke_tool("list_nodes")  # old live handle refreshes, too
    values = {s.label: s.u_iso for s in project.session.model.scatterers()}
    assert values["C1"] == pytest.approx(.031)
    assert values["O1"] == pytest.approx(.047)
    state = project.nodes.state()
    assert state["seq"] == 3 and state["branches"]["main"] == state["active_node"]
    assert len({out["summary"]["node"] for out in outputs}) == 2


def _direct_writer(directory, branch, ready, go, results):
    from crystalpilot.refine.project import RefineProject
    project = RefineProject(directory)
    project.open()
    # An independent low-level caller supplies an intentionally untracked model.
    del project.session._crystalpilot_source
    ready.set()
    assert go.wait(60)
    meta = project.nodes.commit(project.session, tool="direct", params={})
    project.nodes.branch(branch, meta["id"])
    results.put(meta["id"])


def test_direct_nodestore_processes_allocate_unique_ids_and_preserve_refs(tmp_path):
    project = _project(tmp_path)
    ready, go, results = [MP.Event(), MP.Event()], MP.Event(), MP.Queue()
    children = [MP.Process(target=_direct_writer,
                           args=(str(project.dir), f"worker{i}", ready[i], go, results))
                for i in range(2)]
    for child in children:
        child.start()
    try:
        assert all(event.wait(90) for event in ready)
        go.set()
        ids = {results.get(timeout=90) for _ in children}
        assert ids == {"n0001", "n0002"}
    finally:
        go.set()
        for child in children:
            _join(child, 120)
    state = project.nodes.state()
    assert state["seq"] == 3
    assert {"main", "worker0", "worker1"} <= state["branches"].keys()
    assert project.nodes.node_meta("n0002")["parent"] == "n0001"


def test_explicit_project_revision_rejects_aba_and_schema_is_additive(tmp_path):
    project = _project(tmp_path)
    original = project.nodes.version()
    result = project.invoke_tool("edit_atoms", {"operations": [
        {"action": "set_u_iso", "atoms": ["C1"], "u_iso": .031}]})
    assert result.ok, result.error
    project.checkout(original["node"])
    state = project.nodes.state()
    result = project.invoke_tool("set_weights", {"a": .12,
        "expected_node": original["node"],
        "expected_project_revision": original["project_revision"]})
    assert not result.ok and result.summary["transaction_error"]["code"] == "state_conflict"
    assert project.nodes.state() == state
    spec = next(s for s in project.registry.specs() if s["name"] == "set_weights")
    assert "expected_project_revision" in spec["parameters"]["properties"]
    assert "expected_project_revision" not in project.registry.get("set_weights").params_schema["properties"]


def test_failed_mutation_and_late_cancel_do_not_publish_dirty_session(tmp_path, monkeypatch):
    import threading
    from crystalpilot.tools.base import ToolResult
    project = _project(tmp_path)
    state = project.nodes.state()
    old = project.session.model.scatterers()[0].u_iso
    tool = project.registry.get("set_weights")

    def dirty(ctx, **params):
        ctx.session.model.scatterers()[0].u_iso = .8
        return ToolResult.failure("injected failure")

    monkeypatch.setattr(tool, "run", dirty)
    result = project.invoke_tool("set_weights", {})
    assert not result.ok
    assert project.nodes.state() == state
    assert project.session.model.scatterers()[0].u_iso == pytest.approx(old)
    cancel = threading.Event()

    def cancelled(ctx, **params):
        ctx.session.model.scatterers()[0].u_iso = .9
        cancel.set()
        return ToolResult(ok=True)

    monkeypatch.setattr(tool, "run", cancelled)
    result = project.invoke_tool("set_weights", {}, cancel_event=cancel)
    assert not result.ok and result.summary["tool_status"]["execution"] == "cancelled"
    assert project.nodes.state() == state
    assert project.session is None  # cancellation must not launch mask/H reconstruction
    assert project.invoke_tool("list_nodes").ok
    assert project.session.model.scatterers()[0].u_iso == pytest.approx(old)


def test_swap_failure_preserves_hkl_and_context(tmp_path, monkeypatch):
    project = _project(tmp_path)
    old_hkl = project.hkl_path.read_bytes()
    old_context = (project.dir / "context.json").read_bytes()
    (project.dir / "bad.hkl").write_text("invalid data", encoding="ascii")
    result = project.invoke_tool("swap_reflection_data", {"hkl": "bad.hkl", "reason": "test"})
    assert not result.ok
    assert project.hkl_path.read_bytes() == old_hkl
    (project.dir / "good.hkl").write_bytes(old_hkl.replace(b"100.00", b"110.00"))
    state = project.nodes.state()

    def fail(*args, **kwargs):
        raise OSError("injected commit failure")

    monkeypatch.setattr(project.nodes, "commit", fail)
    result = project.invoke_tool("swap_reflection_data", {"hkl": "good.hkl", "reason": "test"})
    assert not result.ok
    assert project.hkl_path.read_bytes() == old_hkl
    assert (project.dir / "context.json").read_bytes() == old_context
    assert project.nodes.state() == state


def _reader(directory, ready, release, results):
    from crystalpilot.refine.project import RefineProject
    from crystalpilot.tools.base import ToolResult
    project = RefineProject(directory)
    project.open()

    def read(ctx, **params):
        before = project.nodes.version()
        ready.set()
        assert release.wait(60)
        assert project.nodes.version() == before
        return ToolResult(ok=True, summary={"observed": before})

    project.registry.get("inspect_model").run = read
    result = project.invoke_tool("inspect_model")
    results.put({"ok": result.ok, "summary": result.summary, "error": result.error})


def test_reader_keeps_one_version_and_blocks_other_process_writer(tmp_path):
    import queue
    project = _project(tmp_path)
    original = project.nodes.version()
    ready, release, results = MP.Event(), MP.Event(), MP.Queue()
    reader = MP.Process(target=_reader, args=(str(project.dir), ready, release, results))
    writer_ready, go, writes = MP.Event(), MP.Event(), MP.Queue()
    writer = MP.Process(target=_writer, args=(str(project.dir), "C1", .061,
                                            writer_ready, go, writes))
    writer.start()
    try:
        assert writer_ready.wait(90)
        reader.start()
        assert ready.wait(90)
        go.set()
        with pytest.raises(queue.Empty):
            writes.get(timeout=.4)
        release.set()
        observed = results.get(timeout=90)
        assert observed["ok"], observed
        assert observed["summary"]["observed"] == original
        assert writes.get(timeout=90)["ok"]
    finally:
        release.set()
        go.set()
        if reader.pid is not None:
            _join(reader, 120)
        _join(writer, 120)


def test_legacy_state_without_project_revision_still_opens_and_commits(tmp_path):
    from crystalpilot.refine.project import RefineProject
    project = _project(tmp_path)
    path = project.nodes.state_path
    state = json.loads(path.read_text(encoding="utf-8"))
    state.pop("project_revision")
    state.pop("last_transaction")
    path.write_text(json.dumps(state), encoding="utf-8")
    legacy = RefineProject(project.dir)
    legacy.open()
    assert legacy.nodes.version()["project_revision"] == 0
    result = legacy.invoke_tool("set_weights", {"a": .12, "expected_project_revision": 0})
    assert result.ok, result.error
    assert legacy.nodes.node_meta("n0000")["revision"] == 1
    assert legacy.nodes.version()["project_revision"] == 1


def test_direct_stale_session_commit_is_refused(tmp_path):
    from crystalpilot.refine.project import RefineProject
    project = _project(tmp_path)
    old_session = project.session
    other = RefineProject(project.dir)
    other.open()
    assert other.invoke_tool("set_weights", {"a": .12}).ok
    with pytest.raises(StateConflict):
        project.nodes.commit(old_session, tool="direct", params={})
    assert project.nodes.state()["seq"] == 2


def test_failed_compound_keeps_committed_child_and_clears_dirty_model(tmp_path, monkeypatch):
    from crystalpilot.tools.base import ToolResult
    project = _project(tmp_path)

    def compound(ctx, **params):
        result = project.invoke_tool("edit_atoms", {"operations": [
            {"action": "set_u_iso", "atoms": ["C1"], "u_iso": .071}]})
        assert result.ok, result.error
        project.session.model.scatterers()[0].u_iso = .9
        return ToolResult.failure("outer failed after child commit")

    monkeypatch.setattr(project.registry.get("ghost_test"), "run", compound)
    result = project.invoke_tool("ghost_test")
    assert not result.ok and result.summary["partial"] is True
    assert result.summary["committed_nodes"] == ["n0001"]
    assert project.nodes.state()["seq"] == 2
    assert project.session.model.scatterers()[0].u_iso == pytest.approx(.071)
    assert result.summary["tool_status"]["state_changed"]["changed"] is True


def test_nested_direct_reference_move_cannot_relabel_a_stale_model(tmp_path, monkeypatch):
    from crystalpilot.tools.base import ToolResult
    project = _project(tmp_path)
    assert project.invoke_tool("edit_atoms", {"operations": [
        {"action": "set_u_iso", "atoms": ["C1"], "u_iso": .071}]}).ok

    def compound(ctx, **params):
        project.nodes.branch("earlier", "n0000")
        child = project.invoke_tool("set_weights", {"a": .13})
        assert child.ok, child.error
        return ToolResult(ok=True)

    monkeypatch.setattr(project.registry.get("ghost_test"), "run", compound)
    assert project.invoke_tool("ghost_test").ok
    assert project.session.model.scatterers()[0].u_iso == pytest.approx(.02)
    assert project.nodes.node_meta("n0002")["parent"] == "n0000"


def test_staged_serialization_failure_and_cancel_before_state_replace(tmp_path, monkeypatch):
    import threading
    from crystalpilot.refine import nodes
    project = _project(tmp_path)
    state = project.nodes.state()
    real_write = project.nodes._serialize_commit

    def fail(session, stage, **kwargs):
        (stage[2] / "model.res").write_text("half a model", encoding="ascii")
        raise OSError("serialization stopped")

    monkeypatch.setattr(project.nodes, "_serialize_commit", fail)
    result = project.invoke_tool("set_weights", {"a": .12})
    assert not result.ok and project.nodes.state() == state
    assert not project.nodes.node_dir("n0001").exists()
    monkeypatch.setattr(project.nodes, "_serialize_commit", real_write)
    cancel = threading.Event()
    rename = nodes.os.rename

    def cancel_after_rename(src, dst):
        rename(src, dst)
        if Path(dst).name == "n0001":
            cancel.set()

    monkeypatch.setattr(nodes.os, "rename", cancel_after_rename)
    result = project.invoke_tool("set_weights", {"a": .12}, cancel_event=cancel)
    assert not result.ok and project.nodes.state() == state
    assert not project.nodes.node_dir("n0001").exists()


def test_child_commit_advances_input_undo_but_later_failed_edits_roll_back(tmp_path, monkeypatch):
    from crystalpilot.tools.base import ToolResult
    project = _project(tmp_path)
    context_path = project.dir / "context.json"

    def write_temperature(value):
        context = json.loads(context_path.read_text(encoding="utf-8"))
        context["experiment"] = {"temperature_K": value}
        context_path.write_text(json.dumps(context), encoding="utf-8")
        project.context = context

    def compound(ctx, **params):
        write_temperature(180)
        assert project.invoke_tool("set_weights", {"a": .13}).ok
        write_temperature(999)
        return ToolResult.failure("failed after a committed child")

    monkeypatch.setattr(project.registry.get("ghost_test"), "run", compound)
    result = project.invoke_tool("ghost_test")
    assert not result.ok and result.summary["committed_nodes"] == ["n0001"]
    assert json.loads(context_path.read_text(encoding="utf-8"))["experiment"]["temperature_K"] == 180
    assert project.nodes.state()["seq"] == 2


def test_peak_refresh_invalidates_old_handle_and_explicit_revision(tmp_path, monkeypatch):
    from crystalpilot.refine.project import RefineProject
    from crystalpilot.tools.base import ToolResult
    project = _project(tmp_path)
    project.session.cf_info = {"peak_sites": [[.1, .2, .3]], "peak_heights": [10]}
    project.nodes.save_peaks("n0000", project.session, update_meta=True)
    reader = RefineProject(project.dir)
    reader.open()
    before = reader.nodes.version()

    def solve(ctx, **params):
        ctx.session.cf_info = {"peak_sites": [[.7, .8, .9]], "peak_heights": [20]}
        return ToolResult(ok=True)

    def consume(ctx, **params):
        return ToolResult(ok=True, summary={"seen": ctx.session.cf_info["peak_sites"],
                                           "no_state_change": True})

    monkeypatch.setattr(project.registry.get("solve_charge_flipping"), "run", solve)
    monkeypatch.setattr(reader.registry.get("interpret_peaks"), "run", consume)
    assert project.invoke_tool("solve_charge_flipping").ok
    assert project.nodes.version()["project_revision"] > before["project_revision"]
    result = reader.invoke_tool("interpret_peaks", {
        "expected_project_revision": before["project_revision"]})
    assert not result.ok and result.summary["transaction_error"]["code"] == "state_conflict"
    result = reader.invoke_tool("interpret_peaks")
    assert result.ok and result.summary["seen"] == [(.7, .8, .9)]


def test_investigation_versions_and_undo_are_tracked(tmp_path, monkeypatch):
    from crystalpilot.tools.base import ToolResult
    project = _project(tmp_path)
    before = project.nodes.version()["project_revision"]
    result = project.invoke_tool("set_investigation", {"goal": "first goal"})
    assert result.ok, result.error
    assert project.nodes.version()["project_revision"] > before
    assert result.summary["tool_status"]["state_changed"]["changed"] is True
    path = project.nodes.root / "investigation.json"
    original = path.read_bytes()

    def fail(ctx, **params):
        path.write_text('{"goal": "uncommitted"}', encoding="utf-8")
        return ToolResult.failure("injected")

    monkeypatch.setattr(project.registry.get("set_investigation"), "run", fail)
    assert not project.invoke_tool("set_investigation", {"goal": "uncommitted"}).ok
    assert path.read_bytes() == original


def test_rebuild_inherits_active_cancellation_progress_and_budget(tmp_path, monkeypatch):
    import threading
    from crystalpilot.tools.base import ToolResult
    project = _project(tmp_path)
    meta_path = project.nodes.node_dir("n0000") / "node.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["mask"] = {"params": {}, "info": {}}
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    cancel = threading.Event()
    progress = lambda message: None
    budget = object()
    observed = []

    def mask(ctx, **params):
        observed.append((ctx.cancel_event, ctx.progress, ctx.budget))
        return ToolResult(ok=True)

    monkeypatch.setattr(project.registry.get("solvent_mask"), "run", mask)
    project.ctx.budget = budget
    with project_transaction(project.dir, cancel_event=cancel, progress=progress):
        project.checkout("n0000", _log_tool="resume")
    assert observed == [(cancel, progress, budget)]


def test_registry_policies_cover_every_registered_tool(tmp_path):
    from crystalpilot.refine.registry import operation_policy
    from crystalpilot.mcp.server import READ_ONLY_TOOLS
    project = _project(tmp_path)
    for name in project.registry.names():
        operation_policy(name)
    assert operation_policy("run_shelxl", {"mode": "check"}).auto_commit is False
    assert operation_policy("run_shelxl", {"mode": "adopt"}).auto_commit is True
    assert operation_policy("ghost_test").kind == "compound"
    assert "checkout" not in READ_ONLY_TOOLS and "run_checkcif" in READ_ONLY_TOOLS
