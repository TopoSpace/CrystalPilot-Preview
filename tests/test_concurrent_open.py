"""Several processes opening the same FRESH project at the same moment.

Live cell 2026-09-05 (round-3 R1): Codex started two crystalpilot MCP
servers for one thread while the spec cache was cold; both imported the
start model, collided on the shared state.json.tmp name (WinError 32) and
one of them served only the 'project failed to open' tool for the whole
session. These tests pin the three fixes: per-process temp files with a
retried swap, one bootstrap under a lock, tolerant state reads."""
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))

from crystalpilot.refine.nodes import NodeStore, atomic_write_json, read_json_retry  # noqa: E402

CELL = (7.1, 8.3, 9.7, 90.0, 95.0, 90.0)
ATOMS = [("O1", "O", (0.10, 0.20, 0.30)), ("N1", "N", (0.40, 0.15, 0.55)),
         ("C1", "C", (0.25, 0.45, 0.60)), ("C2", "C", (0.62, 0.70, 0.12)),
         ("C3", "C", (0.80, 0.33, 0.41))]


def _fresh_project(tmp_path: Path) -> Path:
    from test_probe_site import make_project
    return make_project(tmp_path, CELL, "P 1 21/c 1", ATOMS, ATOMS, 4, d_min=0.9)


class TestAtomicWrites:
    def test_many_writers_never_collide_on_the_temp_name(self, tmp_path):
        d = tmp_path / "proj"
        stores = [NodeStore(d) for _ in range(6)]
        errors: list[BaseException] = []

        def worker(store: NodeStore, k: int) -> None:
            try:
                for i in range(40):
                    store._save_state({"active_node": f"n{k:04d}", "active_branch": "main",
                                       "branches": {"main": f"n{k:04d}"}, "seq": i})
                    store.state()
            except BaseException as e:  # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(s, k)) for k, s in enumerate(stores)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []
        st = json.loads((d / ".crystalpilot" / "refine" / "state.json").read_text(encoding="utf-8"))
        assert st["active_node"].startswith("n00")
        leftovers = list((d / ".crystalpilot" / "refine").glob("state.json.tmp*"))
        assert leftovers == []

    def test_reader_waits_out_a_swap_in_progress(self, tmp_path):
        p = tmp_path / "x.json"
        atomic_write_json(p, {"a": 1})
        assert read_json_retry(p) == {"a": 1}
        # a half-written file (what a concurrent reader used to see) is
        # retried, and the good content wins once it lands
        p.write_text("{not json", encoding="utf-8")

        def fix() -> None:
            time.sleep(0.3)
            atomic_write_json(p, {"a": 2})

        threading.Thread(target=fix).start()
        assert read_json_retry(p) == {"a": 2}


CHILD = r"""
import json, sys, time
sys.path.insert(0, sys.argv[1])
from crystalpilot.refine.project import RefineProject
start_at = float(sys.argv[3])
while time.time() < start_at:
    time.sleep(0.01)
try:
    p = RefineProject(sys.argv[2])
    out = p.open()
    st = p.nodes.state()
    print(json.dumps({"ok": True, "active": st["active_node"],
                      "n_atoms": out.get("n_atoms"), "seq": st["seq"]}))
except Exception as e:
    print(json.dumps({"ok": False, "error": f"{type(e).__name__}: {e}"}))
"""


def test_three_processes_open_a_fresh_project_at_once(tmp_path):
    d = _fresh_project(tmp_path)
    procs = []
    start_at = time.time() + 12.0          # after the cctbx imports settle
    for _ in range(3):
        procs.append(subprocess.Popen(
            [sys.executable, "-X", "utf8", "-c", CHILD, str(REPO), str(d), str(start_at)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
            env={**os.environ, "CRYSTALPILOT_CPU_CORES": "1"}))
    results = []
    for p in procs:
        out, err = p.communicate(timeout=240)
        line = [l for l in out.splitlines() if l.startswith("{")]
        assert line, f"child produced no result: stdout={out!r} stderr={err[-1500:]!r}"
        results.append(json.loads(line[-1]))
    assert all(r["ok"] for r in results), results
    assert {r["active"] for r in results} == {"n0000"}, results
    refine = d / ".crystalpilot" / "refine"
    assert sorted(p.name for p in (refine / "nodes").iterdir()) == ["n0000"]
    st = json.loads((refine / "state.json").read_text(encoding="utf-8"))
    assert st["active_node"] == "n0000" and st["seq"] == 1
    assert not (refine / "bootstrap.lock").exists()
    assert list(refine.glob("state.json.tmp*")) == []


class TestBootstrapLock:
    def test_legacy_sentinel_is_ignored_but_never_deleted(self, tmp_path):
        from crystalpilot.refine.project import RefineProject
        d = _fresh_project(tmp_path)
        refine = d / ".crystalpilot" / "refine"
        refine.mkdir(parents=True, exist_ok=True)
        legacy = refine / "bootstrap.lock"
        legacy.write_text("legacy owner", encoding="utf-8")
        p = RefineProject(d)
        out = p.open()
        assert out.get("n_atoms") == len(ATOMS)
        assert p.nodes.state()["active_node"] == "n0000"
        assert legacy.read_text(encoding="utf-8") == "legacy owner"
        assert (refine / "project.lock").exists()

    def test_waiter_resumes_what_the_holder_committed(self, tmp_path):
        from crystalpilot.refine.project import RefineProject
        from crystalpilot.refine.transactions import project_transaction
        d = _fresh_project(tmp_path)
        ready = threading.Event()

        def holder() -> None:
            with project_transaction(d):
                ready.set()
                time.sleep(0.3)
                RefineProject(d)._import_start()

        thread = threading.Thread(target=holder)
        thread.start()
        assert ready.wait(10)
        p = RefineProject(d)
        out = p.open()
        thread.join(10)
        assert not thread.is_alive()
        assert out["resumed"] and out["node"] == "n0000"
        assert p.nodes.state()["seq"] == 1

    def test_resume_does_not_publish_a_reference_revision(self, tmp_path):
        from crystalpilot.refine.project import RefineProject
        d = _fresh_project(tmp_path)
        p = RefineProject(d)
        p.open()
        before = p.nodes.state()
        other = RefineProject(d)
        assert other.open()["resumed"]
        assert other.nodes.state() == before


class TestMcpHandle:
    def test_failed_open_does_not_count_as_opened(self, tmp_path, monkeypatch):
        from crystalpilot.mcp.server import ProjectHandle
        import crystalpilot.refine.project as projmod

        d = _fresh_project(tmp_path)
        calls = {"n": 0}
        real_open = projmod.RefineProject.open

        def flaky(self):
            calls["n"] += 1
            if calls["n"] == 1:
                raise PermissionError("[WinError 32] state.json in use")
            return real_open(self)

        monkeypatch.setattr(projmod.RefineProject, "open", flaky)
        h = ProjectHandle(d)
        with pytest.raises(PermissionError):
            h.specs()
        assert h.ready is False           # a failed open left nothing behind
        specs = h.specs()                 # the retry really opens
        assert h.ready is True and len(specs) > 50
