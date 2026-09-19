"""Progressive analysis contracts; fake engines, event barriers, no heavy work."""
from __future__ import annotations

import importlib
import json
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from crystalpilot.refine import analysis

jobs_module = importlib.import_module("crystalpilot.workbench.analysis_jobs")


def make_project(root: Path, *, nodes=("n0001",), meta=None) -> Path:
    store = root / ".crystalpilot" / "refine"
    for index, node in enumerate(nodes, start=1):
        directory = store / "nodes" / node
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "node.json").write_text(json.dumps({
            "id": node, "revision": index, **(meta or {}),
        }), encoding="utf-8")
        (directory / "model.res").write_text("fake model", encoding="utf-8")
    (store / "state.json").write_text(json.dumps({
        "active_node": nodes[0], "branches": {"main": nodes[0]}, "seq": len(nodes),
    }), encoding="utf-8")
    return root


@pytest.fixture
def project(tmp_path):
    return make_project(tmp_path / "project")


@pytest.fixture
def managers(monkeypatch):
    monkeypatch.setattr(jobs_module, "_ensure_prewarmed", lambda: None)
    created, releases = [], []

    def make(**kwargs):
        manager = jobs_module.AnalysisJobManager(**kwargs)
        created.append(manager)
        return manager

    make.releases = releases
    yield make
    for event in releases:
        event.set()
    for manager in created:
        manager.shutdown(wait=True)


def barrier(managers):
    entered, release = threading.Event(), threading.Event()
    managers.releases.append(release)
    return entered, release


def finish(manager, started):
    # Future completion is the synchronization boundary, not a timing guess.
    with manager._lock:
        future = manager._jobs[started["job_id"]].future
    if future is not None:
        future.result(timeout=10)


def fake_result(_self, stage):
    return {"block": stage, "rows": [{"value": 1}]}


def test_import_is_lightweight():
    code = (
        "import sys; import crystalpilot.workbench.analysis_jobs; "
        "assert not any(n in sys.modules for n in "
        "('scipy', 'cctbx', 'smtbx', 'numpy', 'crystalpilot.refine.scene'))"
    )
    subprocess.run([sys.executable, "-c", code], check=True, timeout=10)


def test_early_blocks_dedupe_and_snapshots_are_independent(project, managers, monkeypatch):
    entered, release = barrier(managers)
    calls = []

    def compute(self, stage):
        calls.append(stage)
        if stage == "pores":
            entered.set()
            assert release.wait(10), "test did not release pore calculation"
        return fake_result(self, stage)

    monkeypatch.setattr(analysis.AnalysisStages, "compute", compute)
    manager = managers()
    first = manager.start(project, "active")
    assert first["status"] == "queued"
    assert first["result"]["interactions"] is None
    assert first["result"]["pores"] is None
    assert entered.wait(10)
    second = manager.start(project / ".", "main")
    assert second["job_id"] == first["job_id"]
    assert second["observer_id"] != first["observer_id"]
    assert second["revision"] > first["revision"]
    assert second["source_revision"] == 1
    assert calls == list(analysis.ANALYSIS_STAGES)
    assert second["status"] == "running"
    assert second["stages"]["pores"]["status"] == "running"
    assert second["stages"]["interactions"]["status"] == "ready"
    assert second["result"]["topology"] is not None
    assert second["result"]["guests"] is not None
    assert second["result"]["pores"] is None
    assert second["elapsed_s"] >= 0
    second["result"]["interactions"]["rows"][0]["value"] = -1
    second["stages"]["interactions"]["status"] = "error"
    polled = manager.poll(project, first["job_id"])
    assert polled["result"]["interactions"]["rows"][0]["value"] == 1
    assert polled["stages"]["interactions"]["status"] == "ready"
    # The snapshot from before the worker ran never mutates behind HTTP serialization.
    assert first["result"]["interactions"] is None
    release.set()
    finish(manager, first)
    done = manager.poll(project, first["job_id"])
    assert done["status"] == "ready"
    assert done["revision"] > polled["revision"]
    assert all(stage["status"] == "ready" for stage in done["stages"].values())
    assert set(done["result"]["timings_s"]) == set(analysis.ANALYSIS_STAGES)
    assert analysis.AnalysisStages(project, "active").cached_result() is not None


def test_conditional_poll_skips_unchanged_large_result(project, managers, monkeypatch):
    entered, release = barrier(managers)

    def compute(self, stage):
        if stage == "pores":
            entered.set()
            assert release.wait(10)
        return fake_result(self, stage)

    monkeypatch.setattr(analysis.AnalysisStages, "compute", compute)
    manager = managers()
    first = manager.start(project)
    assert entered.wait(10)
    partial = manager.poll(project, first["job_id"],
                           since_result_revision=first["result_revision"])
    assert partial["result"] is not None
    assert partial["result"]["interactions"] is not None
    assert partial["result"]["pores"] is None
    assert partial["result_revision"] > first["result_revision"]
    other = manager.start(project)
    assert other["revision"] > partial["revision"]
    assert other["result_revision"] == partial["result_revision"]
    internal_result = manager._jobs[first["job_id"]].result
    original_copy = jobs_module.copy.deepcopy
    copied_products = []

    def record_copy(value, *args, **kwargs):
        if value is internal_result:
            copied_products.append(value)
        return original_copy(value, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(jobs_module.copy, "deepcopy", record_copy)
        unchanged = manager.poll(project, first["job_id"],
                                 since_result_revision=partial["result_revision"])
        assert unchanged["result"] is None
        assert copied_products == []
        assert unchanged["result_revision"] == partial["result_revision"]
        assert unchanged["status"] == "running"
        assert unchanged["stages"]["pores"]["status"] == "running"
        assert unchanged["stages"]["interactions"]["status"] == "ready"
        unchanged["stages"]["interactions"]["status"] = "error"
        assert internal_result["stages"]["interactions"]["status"] == "ready"
    release.set()
    finish(manager, first)
    final = manager.poll(project, first["job_id"],
                         since_result_revision=partial["result_revision"])
    assert final["result"] is not None
    assert final["result"]["pores"] is not None
    assert final["status"] == "ready"
    assert final["result_revision"] > partial["result_revision"]
    unchanged = manager.poll(project, first["job_id"],
                             since_result_revision=final["result_revision"])
    assert unchanged["status"] == "ready"
    assert unchanged["result"] is None
    resynced = manager.poll(project, first["job_id"],
                            since_result_revision=final["result_revision"] + 1)
    assert resynced["result"] is not None


def test_independent_failed_and_unsupported_sections(project, managers, monkeypatch):
    def compute(self, stage):
        if stage == "pores":
            raise RuntimeError("pore engine failed")
        if stage == "guests":
            raise analysis.UnsupportedAnalysisStage("no guest capability")
        return fake_result(self, stage)

    monkeypatch.setattr(analysis.AnalysisStages, "compute", compute)
    manager = managers()
    first = manager.start(project, "active")
    finish(manager, first)
    done = manager.poll(project, first["job_id"])
    assert done["status"] == "partial"
    assert done["stages"]["pores"]["status"] == "error"
    assert done["stages"]["guests"]["status"] == "unsupported"
    assert done["result"]["pores"] is None
    assert "pore engine failed" in done["result"]["pores_error"]
    assert done["result"]["interactions"] is not None
    assert done["result"]["topology"] is not None
    assert not analysis.AnalysisStages(project, "active").cache_path.exists()
    retry = manager.start(project, "active")
    assert retry["job_id"] != first["job_id"]
    finish(manager, retry)


def test_all_engine_errors_are_terminal(project, managers, monkeypatch):
    def fail(self, stage):
        raise ValueError(stage)

    monkeypatch.setattr(analysis.AnalysisStages, "compute", fail)
    manager = managers()
    job = manager.start(project)
    finish(manager, job)
    done = manager.poll(project, job["job_id"])
    assert done["status"] == "error"
    assert all(state["status"] == "error" for state in done["stages"].values())


def test_cancel_detaches_only_its_observer(project, managers, monkeypatch):
    entered, release = barrier(managers)

    def compute(self, stage):
        if stage == "interactions":
            entered.set()
            assert release.wait(10)
        return fake_result(self, stage)

    monkeypatch.setattr(analysis.AnalysisStages, "compute", compute)
    manager = managers()
    first = manager.start(project)
    assert entered.wait(10)
    other = manager.start(project)
    detached = manager.cancel(project, first["job_id"], first["observer_id"])
    assert detached["status"] == "running"
    assert detached["observers"] == 1
    assert detached["cancellation_requested"] is False
    assert other["job_id"] == first["job_id"]
    release.set()
    finish(manager, first)
    assert manager.poll(project, first["job_id"])["status"] == "ready"


def test_cancel_retains_running_engine_then_skips_every_later_stage(
        project, managers, monkeypatch):
    entered, release = barrier(managers)
    calls = []

    def compute(self, stage):
        calls.append(stage)
        entered.set()
        assert release.wait(10)
        return fake_result(self, stage)

    monkeypatch.setattr(analysis.AnalysisStages, "compute", compute)
    manager = managers()
    first = manager.start(project)
    assert entered.wait(10)
    pending = manager.cancel(project, first["job_id"], first["observer_id"])
    assert pending["status"] == "cancelling"
    assert pending["stages"]["interactions"]["status"] == "running"
    assert pending["stages"]["pores"]["status"] == "cancelled"
    assert pending["result"]["interactions"] is None
    with pytest.raises(RuntimeError, match="cancellation is pending"):
        manager.start(project)
    release.set()
    finish(manager, first)
    done = manager.poll(project, first["job_id"])
    assert done["status"] == "cancelled"
    assert done["result"]["interactions"] is not None
    assert done["result"]["pores"] is None
    assert done["stages"]["interactions"]["status"] == "ready"
    assert calls == ["interactions"]
    assert not analysis.AnalysisStages(project, "active").cache_path.exists()


def test_unstarted_job_cancellation_and_pending_capacity(tmp_path, managers, monkeypatch):
    project = make_project(tmp_path / "project", nodes=("n0001", "n0002", "n0003"))
    entered, release = barrier(managers)
    calls = []

    def compute(self, stage):
        calls.append((self.node, stage))
        entered.set()
        assert release.wait(10)
        return fake_result(self, stage)

    monkeypatch.setattr(analysis.AnalysisStages, "compute", compute)
    manager = managers(max_pending=2)
    active = manager.start(project, "n0001")
    assert entered.wait(10)
    queued = manager.start(project, "n0002")
    assert queued["status"] == "queued"
    with pytest.raises(jobs_module.AnalysisQueueFull):
        manager.start(project, "n0003")
    cancelled = manager.cancel(project, queued["job_id"], queued["observer_id"])
    assert cancelled["status"] == "cancelled"
    assert all(state["status"] == "cancelled" for state in cancelled["stages"].values())
    release.set()
    finish(manager, active)
    assert {node for node, stage in calls} == {"n0001"}


def test_cancelled_queue_does_not_accumulate_executor_work(tmp_path, managers, monkeypatch):
    project = make_project(tmp_path / "project", nodes=("n0001", "n0002"))
    entered, release = barrier(managers)

    def compute(self, stage):
        entered.set()
        assert release.wait(10)
        return fake_result(self, stage)

    monkeypatch.setattr(analysis.AnalysisStages, "compute", compute)
    manager = managers(max_pending=2, max_finished=2)
    submitted = []
    original_submit = manager._executor.submit

    def submit(*args, **kwargs):
        submitted.append(1)
        return original_submit(*args, **kwargs)

    monkeypatch.setattr(manager._executor, "submit", submit)
    active = manager.start(project, "n0001")
    assert entered.wait(10)
    for _ in range(20):
        queued = manager.start(project, "n0002")
        manager.cancel(project, queued["job_id"], queued["observer_id"])
        assert len(manager._pending) == 0
        assert len(manager._jobs) <= 3
    assert len(submitted) == 1
    release.set()
    finish(manager, active)


def test_simultaneous_starts_are_single_flight(project, managers, monkeypatch):
    entered, release = barrier(managers)
    calls = []

    def compute(self, stage):
        calls.append(stage)
        entered.set()
        assert release.wait(10)
        return fake_result(self, stage)

    monkeypatch.setattr(analysis.AnalysisStages, "compute", compute)
    manager = managers()
    rendezvous = threading.Barrier(3)
    started, failures = [], []

    def start():
        try:
            rendezvous.wait(timeout=10)
            started.append(manager.start(project))
        except Exception as exc:
            failures.append(exc)

    threads = [threading.Thread(target=start) for _ in range(2)]
    for thread in threads:
        thread.start()
    rendezvous.wait(timeout=10)
    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive()
    assert not failures
    assert len(started) == 2
    assert started[0]["job_id"] == started[1]["job_id"]
    assert entered.wait(10)
    release.set()
    finish(manager, started[0])
    assert calls == list(analysis.ANALYSIS_STAGES)


def test_complete_cache_hit_does_not_submit_or_import_engines(project, managers, monkeypatch):
    monkeypatch.setattr(analysis.AnalysisStages, "compute", fake_result)
    path = analysis.cached_analysis(project, "active")
    original = path.read_text(encoding="utf-8")

    def forbidden(*args, **kwargs):
        pytest.fail("cache hit must not warm or execute engines")

    manager = managers()
    monkeypatch.setattr(analysis.AnalysisStages, "compute", forbidden)
    monkeypatch.setattr(jobs_module, "_ensure_prewarmed", forbidden)
    result = manager.start(project)
    assert result["cache_hit"] is True
    assert result["status"] == "ready"
    assert result["result"] == json.loads(original)
    assert result["result_revision"] >= 1
    assert manager.poll(project, result["job_id"],
                        since_result_revision=result["result_revision"])["result"] is None
    assert path.read_text(encoding="utf-8") == original
    assert analysis.cached_analysis(project, "active") == path


def test_finished_retention_and_cross_project_lookup(tmp_path, managers, monkeypatch):
    monkeypatch.setattr(analysis.AnalysisStages, "compute", fake_result)
    project = make_project(tmp_path / "project", nodes=("n0001", "n0002", "n0003"))
    other = make_project(tmp_path / "other")
    manager = managers(max_finished=2)
    runs = []
    for node in ("n0001", "n0002", "n0003"):
        run = manager.start(project, node)
        finish(manager, run)
        runs.append(run)
    with pytest.raises(KeyError, match="unknown analysis job"):
        manager.poll(project, runs[0]["job_id"])
    assert len(manager._jobs) == 2
    assert len(manager._finished) == 2
    assert len(manager._by_node) == 2
    with pytest.raises(KeyError, match="unknown analysis job"):
        manager.poll(other, runs[-1]["job_id"])
    with pytest.raises(KeyError, match="unknown analysis job"):
        manager.cancel(other, runs[-1]["job_id"], runs[-1]["observer_id"])
    separate = manager.start(other, "n0001")
    finish(manager, separate)
    assert separate["job_id"] not in {run["job_id"] for run in runs}


def test_bounded_observers_and_idempotent_attachment(project, managers, monkeypatch):
    monkeypatch.setattr(analysis.AnalysisStages, "compute", fake_result)
    manager = managers(max_observers=1)
    first = manager.start(project)
    again = manager.start(project, observer_id=first["observer_id"])
    assert again["job_id"] == first["job_id"]
    assert again["observers"] == 1
    with pytest.raises(jobs_module.AnalysisQueueFull):
        manager.start(project)
    with pytest.raises(KeyError, match="observer"):
        manager.cancel(project, first["job_id"], "someone-else")
    finish(manager, first)


def test_shutdown_does_not_claim_running_c_code_stopped(tmp_path, managers, monkeypatch):
    project = make_project(tmp_path / "project", nodes=("n0001", "n0002"))
    entered, release = barrier(managers)
    calls = []

    def compute(self, stage):
        calls.append((self.node, stage))
        entered.set()
        assert release.wait(10)
        return fake_result(self, stage)

    monkeypatch.setattr(analysis.AnalysisStages, "compute", compute)
    manager = managers()
    active = manager.start(project, "n0001")
    assert entered.wait(10)
    queued = manager.start(project, "n0002")
    manager.shutdown(wait=False)
    assert manager.poll(project, active["job_id"])["status"] == "cancelling"
    assert manager.poll(project, queued["job_id"])["status"] == "cancelled"
    with pytest.raises(RuntimeError, match="shut down"):
        manager.start(project)
    release.set()
    finish(manager, active)
    assert manager.poll(project, active["job_id"])["status"] == "cancelled"
    assert calls == [("n0001", "interactions")]


def test_cache_write_failure_preserves_scientific_result(project, managers, monkeypatch):
    monkeypatch.setattr(analysis.AnalysisStages, "compute", fake_result)

    def fail_save(self, result):
        raise PermissionError("cache directory is read-only")

    monkeypatch.setattr(analysis.AnalysisStages, "save", fail_save)
    manager = managers()
    job = manager.start(project)
    finish(manager, job)
    done = manager.poll(project, job["job_id"])
    assert done["status"] == "ready"
    assert "PermissionError" in done["cache_error"]
    assert done["result"]["pores"] is not None


@pytest.mark.parametrize(("metadata", "expected"), [
    ({"mask": {"params": {"d_min": 0.9}}, "data": {"d_min": 1.2}}, 0.9),
    ({"mask": {"params": {"d_min": None}}, "data": {"d_min": 1.2}}, 1.2),
    ({"data": {"d_min": 1.3}}, 1.3),
    ({}, None),
])
def test_guest_resolution_does_not_depend_on_pores(tmp_path, metadata, expected):
    project = make_project(tmp_path / "project", meta=metadata)
    assert analysis.AnalysisStages(project, "active").guest_d_min() == expected


def test_real_stage_dispatch_runs_guests_before_void_cache(tmp_path, monkeypatch):
    from crystalpilot.refine import scene

    project = make_project(tmp_path / "project", meta={
        "mask": {"params": {"d_min": 0.8}}, "data": {"d_min": 1.1},
    })
    calls = []
    monkeypatch.setattr(analysis, "interactions_from_res",
                        lambda path: calls.append("interactions") or {"rows": []})
    monkeypatch.setattr(analysis, "topology_from_res",
                        lambda path: calls.append("topology") or {"nets": []})

    def guests(path, *, d_min):
        assert d_min == 0.8
        assert calls == ["interactions", "topology"]
        calls.append("guests")
        return {"summary": {}}

    def voids(directory, node):
        assert calls == ["interactions", "topology", "guests"]
        calls.append("pores")
        meta = tmp_path / "voids.json"
        meta.write_text(json.dumps({"v": scene.VOIDS_CACHE_V, "node": node}),
                        encoding="utf-8")
        return tmp_path / "voids.ccp4", meta

    monkeypatch.setattr(analysis, "guests_from_res", guests)
    monkeypatch.setattr(scene, "cached_voids", voids)
    result = analysis.build_analysis(project, "active")
    assert calls == list(analysis.ANALYSIS_STAGES)
    assert result["pores"]["packing"] is None
    assert result["pores"]["packing_note"] == analysis.PENDING_PACKING_NOTE
    assert result["guests"] is not None


@pytest.mark.parametrize(("structure_only", "has_res", "canonical_model", "suffix"), [
    (True, True, None, ".res"),
    (False, True, None, ".res"),
    (True, False, None, ".cif"),
    (True, True, "model.cif", ".cif"),
    (False, True, "model.cif", ".cif"),
    (True, True, "model.res", ".res"),
    (True, False, "model.res", ".cif"),
])
def test_canonical_model_selection(tmp_path, structure_only, has_res, canonical_model, suffix):
    project = make_project(tmp_path / "project", meta={
        "structure_only": structure_only, "canonical_model": canonical_model,
    })
    directory = project / ".crystalpilot" / "refine" / "nodes" / "n0001"
    (directory / "model.cif").write_text("canonical CIF", encoding="utf-8")
    if not has_res:
        (directory / "model.res").unlink()
    assert analysis.AnalysisStages(project, "active").model_path.suffix == suffix


def test_explicit_canonical_cif_never_silently_falls_back_to_res(tmp_path):
    project = make_project(tmp_path / "project", meta={"canonical_model": "model.cif"})
    context = analysis.AnalysisStages(project, "active")
    assert context.model_path.name == "model.cif"
    assert context.model_path.with_suffix(".res").exists()
    assert not context.model_path.exists()


def test_structure_only_analysis_keeps_canonical_res_parts(tmp_path):
    project = make_project(tmp_path / "project", meta={"structure_only": True})
    directory = project / ".crystalpilot" / "refine" / "nodes" / "n0001"
    (directory / "model.res").write_text("""TITL canonical disorder model
CELL 0.71073 10 10 10 90 90 90
ZERR 1 0 0 0 0 0 0
LATT -1
SFAC CA O
UNIT 1 1
PART 1
CA1 1 .2 .3 .4 11 .05
PART 2
O1 2 .4 .3 .2 11 .05
PART 0
HKLF 4
END
""", encoding="utf-8")
    (directory / "model.cif").write_text("derived viewer copy without PART metadata",
                                          encoding="utf-8")
    context = analysis.AnalysisStages(project, "active")
    assert context.model_path == directory / "model.res"
    parsed = analysis._load_analysis_model(context.model_path)
    assert parsed.parts == {"CA1": 1, "O1": 2}


def test_cif_analysis_keeps_long_labels_and_unknown_hydrogen_provenance(tmp_path):
    cif = tmp_path / "model.cif"
    cif.write_text("""data_geometry
_cell_length_a 10
_cell_length_b 10
_cell_length_c 10
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 90
_space_group_name_H-M_alt 'P 1'
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_U_iso_or_equiv
_atom_site_occupancy
O_donor_water O .200 .5 .5 .05 1
H_unknown_source H .296 .5 .5 .05 1
O_acceptor_water O .480 .5 .5 .05 1
""", encoding="utf-8")
    parsed = analysis._load_analysis_model(cif)
    assert [sc.label for sc in parsed.structure.scatterers()] == [
        "O_donor_water", "H_unknown_source", "O_acceptor_water",
    ]
    result = analysis.interactions_from_res(cif)
    assert result["h_source"] == "unknown"
    row = result["unique"]["hbond"][0]
    assert (row["d"], row["h"], row["a"]) == (
        "O_donor_water", "H_unknown_source", "O_acceptor_water",
    )
    assert not cif.with_suffix(".res").exists()


def test_multiblock_cif_uses_recorded_block_without_model_conversion(tmp_path, monkeypatch):
    from crystalpilot.refine import structure_document

    cif = tmp_path / "model.cif"
    cif.write_text("multiple blocks", encoding="utf-8")
    (tmp_path / "node.json").write_text(
        json.dumps({"params": {"data_block": "selected"}}), encoding="utf-8")
    calls = []
    expected = object()

    def load(path, *, block_name=None):
        calls.append((path, block_name))
        if block_name is None:
            raise ValueError("Choose one CIF structure using block_name")
        assert block_name == "selected"
        return expected

    monkeypatch.setattr(structure_document, "load_structure_document", load)
    assert analysis._load_analysis_model(cif) is expected
    assert calls == [(cif, None), (cif, "selected")]


def test_structure_only_analysis_preserves_geometry_and_unknown_electrons(
        tmp_path, managers, monkeypatch):
    from crystalpilot.refine import scene

    project = make_project(tmp_path / "project", meta={
        "structure_only": True, "mode": "structure_only", "data": None, "mask": None,
    })
    monkeypatch.setattr(analysis, "interactions_from_res", lambda path: {"rows": []})
    monkeypatch.setattr(analysis, "topology_from_res", lambda path: {"nets": []})

    def guests(path, *, d_min):
        assert d_min is None
        return {"geometry_only": True}

    def voids(directory, node):
        path = tmp_path / "geometric-voids.json"
        path.write_text(json.dumps({
            "v": scene.VOIDS_CACHE_V, "node": node,
            "mode": "geometric", "structure_only": True,
            "electron_count_status": "unsupported",
            "total_solvent_electrons_per_cell": None,
            "voids": [{"volume_A3": 12.5, "electrons": None}],
            "packing": {"packing_index_pct": 42.0},
        }), encoding="utf-8")
        return tmp_path / "geometric-voids.ccp4", path

    monkeypatch.setattr(analysis, "guests_from_res", guests)
    monkeypatch.setattr(scene, "cached_voids", voids)
    manager = managers()
    job = manager.start(project)
    finish(manager, job)
    final = manager.poll(project, job["job_id"])
    assert final["status"] == "ready"
    assert all(state["status"] == "ready" for state in final["stages"].values())
    pores = final["result"]["pores"]
    assert pores["mode"] == "geometric"
    assert pores["electron_count_status"] == "unsupported"
    assert pores["total_solvent_electrons_per_cell"] is None
    assert pores["voids"][0]["electrons"] is None
    assert pores["voids"][0]["volume_A3"] == 12.5


def test_sync_pipeline_same_order_failure_isolation_and_atomic_cache(project, monkeypatch):
    calls = []

    def compute(self, stage):
        calls.append(stage)
        if stage == "pores":
            raise RuntimeError("pore failure")
        return fake_result(self, stage)

    def noisy_progress(message):
        raise RuntimeError("broken UI progress callback")

    monkeypatch.setattr(analysis.AnalysisStages, "compute", compute)
    result = analysis.build_analysis(project, "active", progress=noisy_progress)
    assert calls == list(analysis.ANALYSIS_STAGES)
    assert result["interactions"] is not None
    assert result["topology"] is not None
    assert result["pores"] is None
    assert result["pores_error"] == "RuntimeError: pore failure"
    path = analysis.cached_analysis(project, "active")
    assert json.loads(path.read_text(encoding="utf-8"))["pores"] is None
    assert analysis._current(path) is False
    assert not list(path.parent.glob("*.tmp"))
    monkeypatch.setattr(analysis.AnalysisStages, "compute", fake_result)
    analysis.cached_analysis(project, "active")
    assert analysis._current(path) is True
    product = json.loads(path.read_text(encoding="utf-8"))
    product["v"] -= 1
    path.write_text(json.dumps(product), encoding="utf-8")
    assert analysis._current(path) is False


def test_preflight_does_not_first_import_heavy_modules_in_request_thread(monkeypatch):
    from crystalpilot.mcp import prewarm

    monkeypatch.setattr(prewarm, "is_prewarmed", lambda name: False)

    def forbidden():
        pytest.fail("request thread attempted heavy imports")

    monkeypatch.setattr(prewarm, "prewarm_heavy_imports", forbidden)
    failures = []

    def request():
        try:
            jobs_module._ensure_prewarmed()
        except RuntimeError as exc:
            failures.append(str(exc))

    thread = threading.Thread(target=request)
    thread.start()
    thread.join(timeout=10)
    assert not thread.is_alive()
    assert len(failures) == 1
    assert "main thread" in failures[0]
