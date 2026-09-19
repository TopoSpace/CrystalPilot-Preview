import json
from pathlib import Path

from crystalpilot.refine.nodes import NodeStore
from crystalpilot.refine.provenance import (
    delivery_source_issue, next_delivery_revision, validation_source,
)
from crystalpilot.refine.tools_deliver import write_manifest


def delivery(tmp_path, revision=1, node="n0003"):
    out = tmp_path / "delivery"
    out.mkdir(exist_ok=True)
    report = {"final_node": node, "source_state": {"node": node, "revision": 4},
              "delivery_revision": revision}
    (out / "REPORT.json").write_text(json.dumps(report), encoding="utf-8")
    (out / "final.cif").write_text("data_x\n", encoding="utf-8")
    return out, report


def test_source_uses_exported_node_not_an_active_node_guess(tmp_path):
    out, report = delivery(tmp_path)
    source = validation_source(out / "final.cif", node="n0099", revision=100)
    assert source["node"] == "n0003"
    assert source["revision"] == 4
    assert source["delivery_revision"] == 1
    assert delivery_source_issue(out, report, {"source": source}) is None


def test_reexport_advances_delivery_version_and_invalidates_old_check(tmp_path):
    out, report = delivery(tmp_path)
    check = {"source": validation_source(out / "final.cif")}
    assert next_delivery_revision(out) == 2
    report["delivery_revision"] = 2
    assert "different final.cif" in delivery_source_issue(out, report, check)


def test_same_named_node_in_another_project_is_not_the_same_target(tmp_path):
    out, report = delivery(tmp_path)
    check = {"source": validation_source(out / "final.cif")}
    other = tmp_path / "other"
    other.mkdir()
    other_out, other_report = delivery(other)
    assert "different final.cif" in delivery_source_issue(other_out, other_report, check)


def test_unattributed_legacy_report_stays_unknown(tmp_path):
    out, report = delivery(tmp_path)
    assert "source is unknown" in delivery_source_issue(out, report, {"counts": {"A": 0}})


def test_standalone_file_is_not_bound_to_a_nearby_delivery(tmp_path):
    out, _ = delivery(tmp_path)
    source = validation_source(out / "manual.cif")
    assert source["kind"] == "file"
    assert source["node"] is None
    assert source["delivery_revision"] is None


def test_node_source_reports_legacy_revision_as_unknown(tmp_path):
    store = NodeStore(tmp_path)
    node = store.node_dir("n0000")
    node.mkdir()
    (node / "node.json").write_text(json.dumps({"id": "n0000"}), encoding="utf-8")
    store.set_active("n0000")
    # a legacy node has neither a model revision nor a data binding, and
    # both stay unknown rather than being inferred (2026-09-08)
    assert store.source_state() == {"node": "n0000", "revision": None, "data_revision": None}
    (node / "node.json").write_text(json.dumps({"id": "n0000", "revision": 1}), encoding="utf-8")
    assert store.source_state() == {"node": "n0000", "revision": 1, "data_revision": None}
    (node / "node.json").write_text(json.dumps({"id": "n0000", "revision": 1, "data_revision": "d000001"}),
                                    encoding="utf-8")
    assert store.source_state() == {"node": "n0000", "revision": 1, "data_revision": "d000001"}


def test_check_records_the_submitted_version_not_a_later_reexport(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from crystalpilot.refine import tools_deliver as tools
    out, report = delivery(tmp_path)
    binary = tmp_path / "platon.exe"
    binary.touch()
    monkeypatch.setenv("CRYSTALPILOT_PLATON", str(binary))
    monkeypatch.setenv("CRYSTALPILOT_KNOWLEDGE_MODE", "tools_only")
    def synthetic_run(job, *args):
        (job / "model.chk").write_text("183_ALERT_1_A metadata missing\n", encoding="utf-8")
        report["delivery_revision"] = 2
        (out / "REPORT.json").write_text(json.dumps(report), encoding="utf-8")
        return {"execution_status": "completed", "report_status": "complete",
                "exit_code": 0, "cleanup_complete": True, "elapsed_s": 0.1}
    from crystalpilot.refine import checkcif_runner
    monkeypatch.setattr(checkcif_runner, "run_platon", synthetic_run)
    project = SimpleNamespace(dir=tmp_path, nodes=SimpleNamespace(state=lambda: {"active_node": "n0003"}))
    result = tools.RunCheckcif(project).run(SimpleNamespace(progress=None),
        cif=str((out / "final.cif").relative_to(tmp_path)), timeout_s=5)
    assert result.ok, result.error
    assert result.summary["source"]["delivery_revision"] == 1
    checked = json.loads((out / "checkcif.json").read_text(encoding="utf-8"))
    assert "different final.cif" in delivery_source_issue(out, report, checked)


def test_inventory_lists_files_without_reading_their_payload(tmp_path, monkeypatch):
    (tmp_path / "final.cif").write_text("data_x\n", encoding="utf-8")
    def no_payload_read(self):
        raise AssertionError("file inventory must not inspect payload bytes")
    monkeypatch.setattr(Path, "read_bytes", no_payload_read)
    manifest = write_manifest(tmp_path, ["final.cif"], scope="test", status="provisional")
    assert manifest["schema_version"] == 2
    assert manifest["files"]["final.cif"] == {"bytes": (tmp_path / "final.cif").stat().st_size}
