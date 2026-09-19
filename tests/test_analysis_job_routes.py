import json
import threading

from fastapi.testclient import TestClient

from server.app import app
from crystalpilot.refine import analysis
from crystalpilot.workbench import routes
from crystalpilot.workbench.analysis_jobs import AnalysisJobManager


def test_progressive_routes_return_partial_results_and_skip_unchanged_payload(tmp_path, monkeypatch):
    node = tmp_path / ".crystalpilot" / "refine" / "nodes" / "n0000"
    node.mkdir(parents=True)
    (node / "node.json").write_text(json.dumps({"id": "n0000", "revision": 1}), encoding="utf-8")
    (node / "model.res").write_text("test fixture", encoding="utf-8")
    entered, release = threading.Event(), threading.Event()
    def compute(self, stage):
        if stage == "pores":
            entered.set()
            if not release.wait(10):
                raise TimeoutError("test barrier not released")
        return {"fixture": stage}
    monkeypatch.setattr(analysis.AnalysisStages, "compute", compute)
    manager = AnalysisJobManager()
    monkeypatch.setattr(routes, "_analysis_jobs", lambda: manager)
    try:
        with TestClient(app, base_url="http://127.0.0.1") as client:
            started = client.post("/api/wb/refine/analysis/jobs", json={"project": str(tmp_path), "node": "n0000"})
            assert started.status_code == 200, started.text
            first = started.json()
            assert entered.wait(10)
            polled = client.get(f"/api/wb/refine/analysis/jobs/{first['job_id']}",
                                params={"project": str(tmp_path)}).json()
            assert polled["result"]["interactions"] == {"fixture": "interactions"}
            assert polled["result"]["pores"] is None
            assert polled["stages"]["pores"]["status"] == "running"
            unchanged = client.get(f"/api/wb/refine/analysis/jobs/{first['job_id']}",
                                   params={"project": str(tmp_path), "since_result_revision": polled["result_revision"]}).json()
            assert unchanged["result"] is None
            assert unchanged["stages"]["pores"]["status"] == "running"
            second = client.post("/api/wb/refine/analysis/jobs", json={"project": str(tmp_path), "node": "n0000"}).json()
            assert second["job_id"] == first["job_id"]
            cancelled = client.post(f"/api/wb/refine/analysis/jobs/{first['job_id']}/cancel",
                                    json={"project": str(tmp_path), "observer_id": first["observer_id"]}).json()
            assert cancelled["status"] == "running"
            assert cancelled["observers"] == 1
            released = client.post(f"/api/wb/refine/analysis/jobs/{first['job_id']}/release",
                                   json={"project": str(tmp_path), "observer_id": second["observer_id"]}).json()
            assert released["status"] == "running"
            assert released["observers"] == 0
            assert released["result"] is None
            again = client.post(f"/api/wb/refine/analysis/jobs/{first['job_id']}/release",
                                json={"project": str(tmp_path), "observer_id": second["observer_id"]})
            assert again.status_code == 200
    finally:
        release.set()
        manager.shutdown(wait=True)
