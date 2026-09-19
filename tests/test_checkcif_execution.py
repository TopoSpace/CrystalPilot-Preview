"""Synthetic execution failures are separate from the opt-in real PLATON test."""
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from crystalpilot.refine import checkcif_runner as runner
from crystalpilot.refine.checkcif_process import CheckcifProcess
from crystalpilot.refine.tools_deliver import RunCheckcif, _checkcif_delta, _persist_checkcif
from crystalpilot.report.checkcif import report_issue
from crystalpilot.tools.budget import Budget


def synthetic_report(alerts="183_ALERT_1_A synthetic missing metadata\n"):
    parsed = runner.parse_alerts(alerts)
    return ("# PLATON/CHECK-(synthetic fixture, NOT scientific evidence)\n" + alerts
            + "\n".join(f"{sum(a['level'] == lv for a in parsed)} ALERT_Level_{lv} = synthetic"
                        for lv in "ABCG") + "\n")


def project(tmp_path):
    out = tmp_path / "delivery"
    out.mkdir()
    (out / "final.cif").write_text("data_synthetic\n", encoding="utf-8")
    (out / "REPORT.json").write_text(json.dumps({"final_node": "n0002",
        "source_state": {"node": "n0002", "revision": 3}, "delivery_revision": 4}), encoding="utf-8")
    return SimpleNamespace(dir=tmp_path, nodes=SimpleNamespace(
        state=lambda: {"active_node": "n0099"},
        node_dir=lambda node: out, node_meta=lambda node: {"revision": 7}))


def fake_process(monkeypatch, tmp_path, *, text="", log="", code=0, active=False,
                 close=True, callback=None):
    binary = tmp_path / "synthetic-platon.exe"
    binary.touch()
    monkeypatch.setenv("CRYSTALPILOT_PLATON", str(binary))
    monkeypatch.setenv("CRYSTALPILOT_SHELXL", str(tmp_path / "missing-shelxl.exe"))
    monkeypatch.setenv("CRYSTALPILOT_KNOWLEDGE_MODE", "tools_only")
    monkeypatch.setattr(runner, "STABLE_S", 0.03)
    monkeypatch.setattr(runner, "POLL_S", 0.01)
    seen = {"closed": False}

    class SyntheticProcess:
        pid = 123
        def __init__(self, args, **kwargs):
            cwd = Path(kwargs["cwd"])
            seen["runtime"] = cwd
            assert kwargs["stdin"] == subprocess.DEVNULL
            assert kwargs["stdout"] != subprocess.PIPE
            kwargs["stderr"].write(b"synthetic stderr evidence\n")
            kwargs["stderr"].flush()
            if text:
                (cwd / "model.chk").write_text(text, encoding="utf-8")
            (cwd / "platon.out").write_text(log, encoding="utf-8")
            if callback:
                callback(cwd)
        def poll(self):
            return code
        def active(self):
            return active
        def close(self):
            seen["closed"] = True
            return close

    monkeypatch.setattr(runner, "CheckcifProcess", SyntheticProcess)
    return seen


@pytest.mark.parametrize("text,code,reason,status", [
    ("", 0, "process_exit_no_report", "missing"),
    ("183_ALERT_1_A incomplete synthetic\n", 0, "process_exit_partial_report", "partial"),
    (synthetic_report(), 23, "process_exit_error", "partial"),
])
def test_synthetic_exit_failure_replaces_old_success(tmp_path, monkeypatch, text, code, reason, status):
    proj = project(tmp_path)
    out = tmp_path / "delivery"
    (out / "checkcif.json").write_text(json.dumps({"counts": {lv: 0 for lv in "ABCG"},
                                                   "alerts": []}), encoding="utf-8")
    seen = fake_process(monkeypatch, tmp_path, text=text, code=code,
                        log=":: CheckCIF out on :model.chk\n")
    result = RunCheckcif(proj).run(SimpleNamespace(progress=None), cif="delivery/final.cif")
    assert not result.ok and result.summary["counts"] is None
    assert result.summary["failure_reason"] == reason
    assert result.summary["report_status"] == status
    record = json.loads((out / "checkcif.json").read_text(encoding="utf-8"))
    assert record["source"]["node"] == "n0002"
    assert record["source"]["revision"] == 3 and record["source"]["delivery_revision"] == 4
    assert record["execution_status"] == "failed" and report_issue(record)
    assert Path(result.artifacts["stderr.log"]).read_text().startswith("synthetic stderr")
    assert seen["closed"] and not seen["runtime"].exists()
    assert "unknown, not zero" in (out / "checkcif_alerts.md").read_text()


@pytest.mark.parametrize("text", ["", "183_ALERT_1_A synthetic partial\n"])
def test_synthetic_timeout_partial_and_missing_are_distinct(tmp_path, monkeypatch, text):
    seen = fake_process(monkeypatch, tmp_path, text=text, code=None, active=True)
    job = tmp_path / "job"
    job.mkdir()
    messages = []
    result = runner.run_platon(job, tmp_path / "synthetic-platon.exe", tmp_path / "absent",
                              Budget(0.1, progress=messages.append))
    assert result["execution_status"] == "timeout"
    assert result["failure_reason"] == ("timeout_partial_report" if text else "timeout_no_report")
    assert result["elapsed_s"] < 2 and seen["closed"]
    assert len(messages) >= 3


def test_synthetic_complete_idle_report_keeps_metadata_and_continuations(tmp_path, monkeypatch):
    proj = project(tmp_path)
    fake_process(monkeypatch, tmp_path, text=synthetic_report(
        "183_ALERT_1_A synthetic metadata\n934_ALERT_3_B synthetic outliers\n"
        "               -1  3  0,  -2  4  0,\n048_ALERT_1_C synthetic moiety\n"),
        log=":: CheckCIF out on :model.chk\n", code=None, active=True)
    result = RunCheckcif(proj).run(SimpleNamespace(progress=None), cif="delivery/final.cif")
    assert result.ok, result.error
    assert result.summary["counts"] == {"A": 1, "B": 1, "C": 1, "G": 0}
    assert result.summary["exit_code"] is None
    record = json.loads(Path(result.artifacts["checkcif_json"]).read_text(encoding="utf-8"))
    assert "-1  3  0" in record["alerts"][1]["text"]
    assert report_issue(record) is None
    assert record["alerts"][0]["type"] == 1


def test_synthetic_minimal_node_does_not_suppress_metadata(tmp_path, monkeypatch):
    proj = project(tmp_path)
    shutil.copy2(tmp_path / "delivery" / "final.cif", tmp_path / "delivery" / "model.cif")
    fake_process(monkeypatch, tmp_path, text=synthetic_report(), log=":: CheckCIF out on :model.chk\n")
    result = RunCheckcif(proj).run(SimpleNamespace(progress=None))
    assert result.ok and result.summary["counts"]["A"] == 1
    assert result.summary["n_metadata_alerts"] == 1
    assert result.summary["source"]["node"] == "n0099"


def test_synthetic_cancel_wins_over_complete_report(tmp_path, monkeypatch):
    proj = project(tmp_path)
    event = threading.Event()
    seen = fake_process(monkeypatch, tmp_path, text=synthetic_report(),
                        log=":: CheckCIF out on :model.chk\n", callback=lambda cwd: event.set())
    result = RunCheckcif(proj).run(SimpleNamespace(cancel_event=event, progress=None), cif="delivery/final.cif")
    assert not result.ok and result.summary["execution_status"] == "cancelled"
    assert result.summary["counts"] is None and seen["closed"]


def test_synthetic_cancel_during_annotation_discards_counts(tmp_path, monkeypatch):
    from crystalpilot.refine import tools_deliver
    proj = project(tmp_path)
    event = threading.Event()
    fake_process(monkeypatch, tmp_path, text=synthetic_report(),
                 log=":: CheckCIF out on :model.chk\n")
    monkeypatch.setattr(tools_deliver, "_checkcif_delta", lambda *args: event.set())
    result = RunCheckcif(proj).run(SimpleNamespace(cancel_event=event, progress=None), cif="delivery/final.cif")
    assert not result.ok and result.summary["execution_status"] == "cancelled"
    assert result.summary["counts"] is None and result.summary["alerts"] == []


def test_synthetic_cleanup_failure_is_never_success(tmp_path, monkeypatch):
    proj = project(tmp_path)
    fake_process(monkeypatch, tmp_path, text=synthetic_report(),
                 log=":: CheckCIF out on :model.chk\n", close=False)
    result = RunCheckcif(proj).run(SimpleNamespace(progress=None), cif="delivery/final.cif")
    assert not result.ok and result.summary["failure_reason"] == "cleanup_failed"
    assert result.summary["counts"] is None


def test_missing_binary_persists_failure_and_new_unique_attempt(tmp_path, monkeypatch):
    proj = project(tmp_path)
    monkeypatch.setenv("CRYSTALPILOT_PLATON", str(tmp_path / "missing"))
    first = RunCheckcif(proj).run(SimpleNamespace(progress=None), cif="delivery/final.cif")
    second = RunCheckcif(proj).run(SimpleNamespace(progress=None), cif="delivery/final.cif")
    assert not first.ok and not second.ok
    assert first.summary["failure_reason"] == "executable_missing"
    assert first.artifacts["checkcif_json"] != second.artifacts["checkcif_json"]
    assert Path(first.artifacts["checkcif_json"]).is_file()


@pytest.mark.parametrize("timeout", [0, -1, 3601, 1.5, True, "420"])
def test_timeout_is_bounded(tmp_path, timeout):
    result = RunCheckcif(project(tmp_path)).run(SimpleNamespace(), timeout_s=timeout)
    assert not result.ok and "1 to 3600" in result.error


def test_complete_gate_rejects_idle_partial_and_wrong_counts():
    log = ":: CheckCIF out on :model.chk\n"
    assert not runner.complete_report("183_ALERT_1_A unfinished\n", log)
    assert not runner.complete_report(synthetic_report(), "")
    assert not runner.complete_report(synthetic_report().replace("1 ALERT_Level_A", "0 ALERT_Level_A"), log)
    assert runner.complete_report(synthetic_report(""), log)


def test_delta_skips_failed_attempt(tmp_path):
    for name, status in (("job_1", "completed"), ("job_2", "failed")):
        path = tmp_path / name
        path.mkdir()
        (path / "checkcif.json").write_text(json.dumps({"target": "publication:x",
            "execution_status": status, "alerts": [{"code": "183", "level": "A"}]}))
    current = tmp_path / "job_3"
    current.mkdir()
    assert _checkcif_delta(current, [], "publication")["vs"] == "job_1"


def test_older_completion_cannot_replace_new_failure(tmp_path):
    delivery = tmp_path / "delivery"
    delivery.mkdir()
    old, new = tmp_path / "job_1", tmp_path / "job_2"
    old.mkdir()
    new.mkdir()
    failure = {"attempt_id": "job_2", "execution_status": "failed", "error": "new failure"}
    assert _persist_checkcif(new, delivery, failure)
    success = {"attempt_id": "job_1", "execution_status": "completed", "counts": {lv: 0 for lv in "ABCG"}}
    assert not _persist_checkcif(old, delivery, success)
    assert json.loads((delivery / "checkcif.json").read_text()) == failure
    assert "new failure" in (delivery / "checkcif_alerts.md").read_text()
    assert json.loads((old / "checkcif.json").read_text()) == success


@pytest.mark.parametrize("record", [None, [], {}, {"execution_status": "running"},
    {"execution_status": "timeout"}, {"report_status": "partial"},
    {"counts": {lv: 0 for lv in "ABCG"}, "alerts": [{"code": "183", "level": "A"}]}])
def test_report_gate_cannot_finalize_unknown_or_failed(record):
    assert report_issue(record)


def test_real_process_tree_cleanup_after_root_exits(tmp_path):
    """Real OS processes, synthetic workload (not a crystallographic check)."""
    child_code = "import time; time.sleep(60)"
    root_code = ("import subprocess,sys,pathlib; "
                 f"p=subprocess.Popen([sys.executable,'-c',{child_code!r}]); "
                 f"pathlib.Path({str(tmp_path / 'child.pid')!r}).write_text(str(p.pid))")
    process = CheckcifProcess([sys.executable, "-c", root_code], cwd=tmp_path,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        until = time.monotonic() + 10
        while not (tmp_path / "child.pid").exists() and time.monotonic() < until:
            time.sleep(0.05)
        assert (tmp_path / "child.pid").exists()
        process.proc.wait(timeout=5)
        assert process.active()
    finally:
        assert process.close()
    if os.name == "nt":
        assert not process.active()


@pytest.mark.slow
def test_real_platon_publication_cif_long_project_path(tmp_path, monkeypatch):
    """Opt-in real binary/input integration; never substitute synthetic CIFs."""
    source = os.environ.get("CRYSTALPILOT_TEST_CHECKCIF_CIF")
    exe = os.environ.get("CRYSTALPILOT_PLATON")
    shelxl = os.environ.get("CRYSTALPILOT_SHELXL")
    if not source or not exe or not shelxl:
        pytest.skip("requires explicit real publication CIF and PLATON/SHELXL paths")
    assert Path(source).is_file() and Path(exe).is_file() and Path(shelxl).is_file()
    root = tmp_path / ("long project with spaces " + "a" * 60)
    out = root / "delivery"
    out.mkdir(parents=True)
    shutil.copy2(source, out / "final.cif")
    for suffix in (".fcf", ".res", ".hkl", ".fab"):
        sidecar = Path(source).with_suffix(suffix)
        if sidecar.is_file():
            shutil.copy2(sidecar, out / ("final" + suffix))
    report = Path(source).parent / "REPORT.json"
    if report.is_file():
        shutil.copy2(report, out / report.name)
    monkeypatch.setenv("CRYSTALPILOT_KNOWLEDGE_MODE", "tools_only")
    obj = SimpleNamespace(dir=root, nodes=SimpleNamespace(state=lambda: {"active_node": None}))
    result = RunCheckcif(obj).run(SimpleNamespace(progress=None), cif="delivery/final.cif", timeout_s=90)
    assert result.ok, result.error
    record = json.loads(Path(result.artifacts["checkcif_json"]).read_text(encoding="utf-8"))
    assert report_issue(record) is None and record["cleanup_complete"]
    assert runner.complete_report(Path(result.artifacts["chk"]).read_text(encoding="utf-8"),
                                  Path(result.artifacts["platon.out"]).read_text(encoding="utf-8"))
    assert not Path(record["runtime_path"]).exists()
    assert (out / "final.cif").read_bytes() == Path(source).read_bytes()
