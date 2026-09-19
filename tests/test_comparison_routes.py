from fastapi import FastAPI
from fastapi.testclient import TestClient

from crystalpilot.workbench.routes import router
from tests.test_data_versions import _project


def test_comparison_route_is_explicit_and_readonly(tmp_path, monkeypatch):
    p = _project(tmp_path)
    before = p.nodes.state()
    def forbid(*args, **kwargs):
        raise AssertionError("read-only comparison must not open a project session")
    monkeypatch.setattr(type(p), "open", forbid)
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        params = {"project": str(p.dir), "node": "n0000", "baseline": "n0000"}
        response = client.get("/api/wb/refine/comparison", params=params)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["node"] == body["baseline"] == "n0000"
        assert body["sources"]["node"]["data_binding"] == "bound"
        assert body["metrics"]["r1"]["status"] == "unknown"
        assert client.get("/api/wb/refine/comparison", params={**params, "node": "active"}).status_code == 400
        assert client.get("/api/wb/refine/comparison", params={**params, "node": "n9999"}).status_code == 404
    assert p.nodes.state() == before
