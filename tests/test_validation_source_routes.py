import json

import pytest
from fastapi.testclient import TestClient

from server.app import app
from crystalpilot.workbench import routes


@pytest.fixture
def project(tmp_path, monkeypatch):
    (tmp_path / ".crystalpilot" / "refine" / "nodes").mkdir(parents=True)
    monkeypatch.setattr(routes, "_refine_project_or_404", lambda path: tmp_path)
    return tmp_path


def test_delivery_source_route_reports_version(project):
    out = project / "delivery"
    out.mkdir()
    (out / "final.cif").write_text("data_x\n", encoding="utf-8")
    (out / "REPORT.json").write_text(json.dumps({"final_node": "n0002",
        "source_state": {"node": "n0002", "revision": 3}, "delivery_revision": 4}), encoding="utf-8")
    with TestClient(app, base_url="http://127.0.0.1") as client:
        response = client.get("/api/wb/refine/validation-source",
                              params={"project": str(project), "cif": str(out / "final.cif")})
    assert response.status_code == 200
    assert response.json()["source"]["node"] == "n0002"
    assert response.json()["source"]["delivery_revision"] == 4


def test_missing_target_is_explicit_without_a_console_error_response(project):
    with TestClient(app, base_url="http://127.0.0.1") as client:
        response = client.get("/api/wb/refine/validation-source",
                              params={"project": str(project), "cif": "missing.cif"})
    assert response.status_code == 200
    assert response.json() == {"source": None, "status": "missing"}


def test_source_target_cannot_escape_project(project):
    with TestClient(app, base_url="http://127.0.0.1") as client:
        response = client.get("/api/wb/refine/validation-source",
                              params={"project": str(project), "cif": str(project.parent / "outside.cif")})
    assert response.status_code == 403
    assert response.json()["detail"] == "validation target must stay inside the project"
