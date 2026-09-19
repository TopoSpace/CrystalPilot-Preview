"""Two stale process handles concurrently publish distinct reflection versions."""
import multiprocessing

from crystalpilot.refine.data_versions import DataVersions
from crystalpilot.refine.project import RefineProject
from tests.test_data_versions import _project
from tests.test_swap_data import _write_hkl

MP = multiprocessing.get_context("spawn")


def _writer(directory, filename, ready, go, results):
    try:
        p = RefineProject(directory)
        p.open()
        ready.set()
        if not go.wait(60):
            raise TimeoutError("test publication start was not released")
        result = p.invoke_tool("swap_reflection_data", {"hkl": filename, "reason": "concurrent controlled input"})
        node = result.summary.get("node")
        results.put({"ok": result.ok, "error": result.error, "file": filename, "node": node,
                     "revision": p.nodes.node_meta(node).get("data_revision") if node else None})
    except BaseException as exc:
        results.put({"ok": False, "error": repr(exc)})
        ready.set()


def test_two_process_data_writers_allocate_distinct_bound_versions(tmp_path):
    p = _project(tmp_path)
    original_revision = p.nodes.state()["active_data_revision"]
    original = p.hkl_path.read_bytes()
    _write_hkl(p.dir / "first.hkl", p.session.fo_sq, 1)
    _write_hkl(p.dir / "second.hkl", p.session.fo_sq, 2)
    expected = {name: (p.dir / name).read_bytes() for name in ("first.hkl", "second.hkl")}
    go, results = MP.Event(), MP.Queue()
    ready = [MP.Event(), MP.Event()]
    children = [MP.Process(target=_writer, args=(str(p.dir), name, ready[index], go, results))
                for index, name in enumerate(expected)]
    for child in children:
        child.start()
    try:
        assert all(event.wait(90) for event in ready)
        go.set()
        outcomes = [results.get(timeout=90) for _ in children]
    finally:
        go.set()
        for child in children:
            child.join(90)
            if child.is_alive():
                child.terminate()
                child.join(10)
    assert all(child.exitcode == 0 for child in children)
    assert all(result["ok"] for result in outcomes), outcomes
    assert len({result["revision"] for result in outcomes}) == 2
    versions = DataVersions(p.dir)
    for result in outcomes:
        hkl, _ = versions.resolve(result["revision"])
        assert hkl.read_bytes() == expected[result["file"]]
        assert p.nodes.node_meta(result["node"])["data_revision"] == result["revision"]
    q = RefineProject(p.dir)
    q.open()
    state = q.nodes.state()
    assert state["data_seq"] == 3 and state["seq"] == 3
    assert (q.dir / "crystal.hkl").read_bytes() == q.hkl_path.read_bytes()
    assert q.hkl_path.read_bytes() in expected.values()
    assert versions.resolve(original_revision)[0].read_bytes() == original
