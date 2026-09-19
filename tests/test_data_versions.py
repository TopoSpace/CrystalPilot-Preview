"""Bound reflection storage uses actual process exits and byte comparisons."""
from __future__ import annotations

import json
import multiprocessing
import os
from pathlib import Path

import pytest

from crystalpilot.refine.data_versions import DataBindingRequired, DataVersions
from crystalpilot.refine.project import RefineProject

MP = multiprocessing.get_context("spawn")


def _project(tmp_path):
    from tests.test_shelxl_tools import _formate_project
    return _formate_project(tmp_path)


def _other(project):
    from tests.test_swap_data import _write_hkl
    target = project.dir / "other.hkl"
    _write_hkl(target, project.session.fo_sq, 30)
    return target


def _inventory(directory):
    return {str(p.relative_to(directory)): p.read_bytes() for p in directory.rglob("*") if p.is_file()}


def test_swap_and_checkout_restore_exact_bound_data(tmp_path):
    p = _project(tmp_path)
    a = p.nodes.state()["active_node"]
    ra = p.nodes.node_meta(a)["data_revision"]
    original = p.hkl_path.read_bytes()
    files_a = _inventory(DataVersions(p.dir).path(ra))
    target = _other(p)
    b_bytes = target.read_bytes()
    result = p.invoke_tool("swap_reflection_data", {"hkl": target.name, "reason": "test new observations"})
    assert result.ok, result.error
    b = p.nodes.state()["active_node"]
    assert p.nodes.state()["active_data_revision"] != ra
    assert p.hkl_path.read_bytes() == b_bytes
    assert (p.dir / "crystal.hkl").read_bytes() == b_bytes
    assert _inventory(DataVersions(p.dir).path(ra)) == files_a
    p.checkout(a)
    assert p.hkl_path.read_bytes() == original
    assert (p.dir / "crystal.hkl").read_bytes() == original
    assert p.nodes.state()["active_data_revision"] == ra
    q = RefineProject(p.dir)
    q.open()
    assert q.hkl_path.read_bytes() == original
    q.checkout(b)
    assert q.hkl_path.read_bytes() == b_bytes


def test_model_tools_do_not_copy_or_change_versions(tmp_path):
    p = _project(tmp_path)
    directory = DataVersions(p.dir).directory
    before = _inventory(directory)
    result = p.invoke_tool("set_weights", {"a": .12, "b": 0})
    assert result.ok, result.error
    p.checkout("n0000")
    assert _inventory(directory) == before


def test_legacy_geometry_is_available_without_data_inference(tmp_path):
    p = _project(tmp_path)
    node = p.nodes.state()["active_node"]
    meta_path = p.nodes.node_dir(node) / "node.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta.pop("data_revision")
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    before = meta_path.read_bytes()
    q = RefineProject(p.dir)
    result = q.open()
    assert result["state"] == "binding_required"
    assert q.session.model.scatterers().size() > 0
    assert q.session.dataset is None and not q.structure_only
    with pytest.raises(DataBindingRequired):
        q._build_session(q.nodes.node_dir(node) / "model.res")
    assert not q.invoke_tool("refine", {"n_cycles": 1}).ok
    assert meta_path.read_bytes() == before


def test_unbound_old_caches_are_not_served_or_recomputed(tmp_path):
    from crystalpilot.refine.scene import cache_dir, cached_fofc, cached_peaks, cached_data_block
    p = _project(tmp_path)
    node = p.nodes.state()["active_node"]
    path = p.nodes.node_dir(node) / "node.json"
    meta = json.loads(path.read_text(encoding="utf-8"))
    meta.pop("data_revision")
    meta.pop("data")
    path.write_text(json.dumps(meta), encoding="utf-8")
    cache = cache_dir(p.dir, node)
    cache.mkdir(parents=True, exist_ok=True)
    (cache / "fofc.ccp4").write_bytes(b"pre-version unknown input map")
    (cache / "peaks.json").write_text("{}", encoding="utf-8")
    with pytest.raises(DataBindingRequired):
        cached_fofc(p.dir, node)
    with pytest.raises(DataBindingRequired):
        cached_peaks(p.dir, node)
    result = cached_data_block(p.dir, node)
    assert result["source"] == "unavailable" and result["data"] is None


def test_explicit_legacy_binding_creates_new_child(tmp_path):
    p = _project(tmp_path)
    node = p.nodes.state()["active_node"]
    path = p.nodes.node_dir(node) / "node.json"
    meta = json.loads(path.read_text(encoding="utf-8"))
    meta.pop("data_revision")
    path.write_text(json.dumps(meta), encoding="utf-8")
    before = path.read_bytes()
    p = RefineProject(p.dir)
    p.open()
    result = p.invoke_tool("swap_reflection_data", {"model_node": node, "hkl": "crystal.hkl", "reason": "explicit matching-data supplied"})
    assert result.ok, result.error
    current = p.nodes.node_meta(p.nodes.state()["active_node"])
    assert current["id"] != node and current["parent"] == node
    assert current["data_revision"] and not current["metrics_current"]
    assert path.read_bytes() == before
    assert p.session.dataset is not None
    assert p.invoke_tool("set_weights", {"a": .13}).ok
    assert p.nodes.node_meta(p.nodes.state()["active_node"])["parent"] == current["id"]


def _crash_swap(directory, checkpoint):
    import crystalpilot.refine.data_versions as dv
    p = RefineProject(directory)
    p.open()
    if checkpoint in ("before_data", "after_data"):
        original = dv.publish_data
        def crash(store, pending):
            if checkpoint == "after_data":
                original(store, pending)
            os._exit(27)
        dv.publish_data = crash
    elif checkpoint == "during_alias_copy":
        original = dv.shutil.copyfileobj
        def crash(incoming, outgoing, *args, **kwargs):
            if Path(outgoing.name).parent.name == "alias-copies":
                outgoing.write(incoming.read(7))
                outgoing.flush()
                os._exit(27)
            return original(incoming, outgoing, *args, **kwargs)
        dv.shutil.copyfileobj = crash
    elif checkpoint in ("before_state", "after_state"):
        original = p.nodes._save_state
        def crash(state):
            if checkpoint == "after_state":
                original(state)
            os._exit(27)
        p.nodes._save_state = crash
    else:
        original = dv.finish_aliases
        def crash(store, token):
            if checkpoint == "after_aliases":
                original(store, token)
            os._exit(27)
        dv.finish_aliases = crash
    p.invoke_tool("swap_reflection_data", {"hkl": "other.hkl", "reason": "crash checkpoint"})


@pytest.mark.parametrize("checkpoint,committed", [
    ("before_data", False), ("after_data", False), ("before_state", False),
    ("after_state", True), ("before_aliases", True), ("after_aliases", True),
    ("during_alias_copy", True)])
def test_process_exit_recovers_one_model_data_pair(tmp_path, checkpoint, committed):
    p = _project(tmp_path)
    original = p.hkl_path.read_bytes()
    target = _other(p)
    replacement = target.read_bytes()
    old = p.nodes.state()
    child = MP.Process(target=_crash_swap, args=(str(p.dir), checkpoint))
    child.start()
    child.join(60)
    if child.is_alive():
        child.terminate()
        child.join(10)
        pytest.fail("owned crash test child timed out")
    assert child.exitcode == 27
    q = RefineProject(p.dir)
    q.open()
    state = q.nodes.state()
    assert state["seq"] == old["seq"] + int(committed)
    assert state["active_data_revision"] == q.nodes.node_meta(state["active_node"])["data_revision"]
    expected = replacement if committed else original
    assert q.hkl_path.read_bytes() == expected
    assert (q.dir / "crystal.hkl").read_bytes() == expected
    assert not q.nodes.publication_path.exists()
    if checkpoint == "during_alias_copy":
        _, manifest = DataVersions(q.dir).resolve(state["active_data_revision"])
        partials = list((q.nodes.root / ".staging" / manifest["transaction"] / "alias-copies").iterdir())
        assert any(path.read_bytes() == replacement[:7] for path in partials)


@pytest.mark.parametrize("import_cif", [False, True])
def test_recovered_commit_advances_undo_before_failure_cleanup(tmp_path, monkeypatch, import_cif):
    import crystalpilot.refine.data_versions as dv
    p = _project(tmp_path)
    old = p.nodes.state()
    other = _other(p)
    original_finish = dv.finish_aliases
    attempted = []
    def once(store, token):
        if not attempted:
            attempted.append(token)
            assert store._read_state()["active_data_revision"] != old["active_data_revision"]
            raise OSError("one-shot post-commit alias failure")
        return original_finish(store, token)
    monkeypatch.setattr(dv, "finish_aliases", once)
    if import_cif:
        public = Path(__file__).resolve().parents[1] / "benchmark" / "public" / "sucrose"
        result = p.invoke_tool("import_cif_model", {"cif_path": str(public / "ref_cif.cif"), "hkl_path": str(public / "sf.cif")})
    else:
        result = p.invoke_tool("swap_reflection_data", {"hkl": other.name, "reason": "publication failure test"})
    assert not result.ok and result.summary["committed_nodes"]
    q = RefineProject(p.dir)
    q.open()
    state = q.nodes.state()
    assert state["seq"] == old["seq"] + 1
    hkl, manifest = DataVersions(q.dir).resolve(state["active_data_revision"])
    assert (q.dir / "crystal.hkl").read_bytes() == hkl.read_bytes()
    inputs = q.nodes.root / ".staging" / manifest["transaction"] / "inputs"
    for name in ("start.res", "context.json"):
        assert (q.dir / name).read_bytes() == (inputs / name).read_bytes()
    assert not q.nodes.publication_path.exists()


def test_persistent_alias_failure_reports_committed_state_truthfully(tmp_path, monkeypatch):
    import crystalpilot.refine.data_versions as dv
    p = _project(tmp_path)
    old = p.nodes.state()
    replacement = _other(p).read_bytes()
    def unavailable(*args):
        raise OSError("compatibility alias remains locked")
    with monkeypatch.context() as patch:
        patch.setattr(dv, "finish_aliases", unavailable)
        result = p.invoke_tool("swap_reflection_data", {"hkl": "other.hkl", "reason": "persistent alias failure"})
        assert not result.ok
        assert result.summary.get("recovery_required") is True
        committed = p.nodes._read_state()
        assert committed["seq"] == old["seq"] + 1
        assert result.summary["committed_nodes"] == [committed["active_node"]]
        assert result.summary["tool_status"]["state_changed"]["changed"] is True
    q = RefineProject(p.dir)
    q.open()
    assert q.nodes.state()["active_node"] == committed["active_node"]
    assert q.hkl_path.read_bytes() == replacement == (q.dir / "crystal.hkl").read_bytes()


@pytest.mark.parametrize("corrupt", [False, True])
def test_bound_mask_failure_cannot_publish_unmasked_cache(tmp_path, monkeypatch, corrupt):
    from cctbx import miller
    from cctbx.array_family import flex
    from crystalpilot.tools.base import ToolResult
    from crystalpilot.tools.mask_tools import SolventMask
    from crystalpilot.refine.scene import cache_dir, cached_fofc, cached_peaks
    p = _project(tmp_path)
    p.session.flags["f_mask"] = miller.array(p.session.fo_sq.set(),
        data=flex.complex_double(p.session.fo_sq.size(), complex(.02, .01)))
    p.session.flags["solvent_mask_params"] = {"solvent_radius": 1.2}
    node = p.nodes.commit(p.session, tool="solvent_mask", params={})["id"]
    mask = p.nodes.node_dir(node) / "f_mask.pkl"
    if corrupt:
        mask.write_bytes(b"invalid mask snapshot")
    else:
        mask.unlink()
    monkeypatch.setattr(SolventMask, "run", lambda *args, **kwargs: ToolResult.failure("forced mask recomputation failure"))
    cache = cache_dir(p.dir, node)
    for operation in (cached_fofc, cached_peaks):
        with pytest.raises(ValueError, match="bound applied mask could not be restored"):
            operation(p.dir, node)
    for filename in ("fofc.ccp4", "peaks.json", "fofc.ccp4.source.json", "peaks.json.source.json"):
        assert not (cache / filename).exists()
