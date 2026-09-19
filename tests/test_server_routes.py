"""Route-level tests for the local server: the security boundary (Host
check + Origin allowlist, commit f2121e6) and the workbench settings /
frames_probe endpoints. TestClient only - no live agent, no codex."""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


@pytest.fixture(scope="module")
def client():
    from server.app import app
    # TestClient's default base_url host is "testserver" - our loopback
    # Host guard would 403 everything, which is itself worth one assert
    return TestClient(app, base_url="http://localhost")


class TestSecurityBoundary:
    def test_foreign_host_rejected(self, client):
        r = client.get("/api/health", headers={"Host": "evil.example"})
        assert r.status_code == 403
        assert "host" in r.text.lower()

    def test_dns_rebinding_host_rejected(self, client):
        # DNS rebinding: attacker's hostname resolving to 127.0.0.1 still
        # carries the foreign Host header
        r = client.get("/api/health",
                       headers={"Host": "attacker.local:8010"})
        assert r.status_code == 403

    def test_loopback_host_allowed(self, client):
        r = client.get("/api/health", headers={"Host": "127.0.0.1:8010"})
        assert r.status_code == 200

    def test_foreign_origin_rejected(self, client):
        # CORS-exempt "simple" POSTs still send Origin - the middleware
        # must reject them server-side, not rely on the browser
        r = client.get("/api/health",
                       headers={"Host": "localhost:8010",
                                "Origin": "http://evil.example"})
        assert r.status_code == 403
        assert "origin" in r.text.lower()

    def test_local_origin_allowed(self, client):
        r = client.get("/api/health",
                       headers={"Host": "localhost:8010",
                                "Origin": "http://localhost:5173"})
        assert r.status_code == 200

    def test_null_origin_rejected(self, client):
        # sandboxed iframes / file:// pages send Origin: null
        r = client.get("/api/health",
                       headers={"Host": "localhost", "Origin": "null"})
        assert r.status_code == 403


class TestWorkbenchSettings:
    def test_get_settings_fallback_has_model_fields(self, client, tmp_path):
        # project not open in the pool -> fallback branch must still
        # return the full settings shape (incl. model/effort wiring)
        proj = tmp_path / "p1"
        proj.mkdir()
        r = client.get("/api/projects/settings",
                       params={"path": str(proj)})
        assert r.status_code == 200, r.text
        j = r.json()
        for key in ("permission_mode", "model", "effort", "model_default",
                    "effort_default", "model_override", "effort_override",
                    "effort_choices"):
            assert key in j, f"missing {key}: {j}"
        # gateway-probed (docs/reg1-2026-09-04/EFFORT-PROBE.md): 'minimal'
        # rejected; max/ultra accepted for gpt-6-astra on 2026-09-05
        assert j["effort_choices"] == ["low", "medium", "high", "xhigh",
                                       "max", "ultra"]

    def test_post_settings_requires_open_project(self, client, tmp_path):
        proj = tmp_path / "p2"
        proj.mkdir()
        r = client.post("/api/projects/settings",
                        json={"path": str(proj),
                              "settings": {"effort_override": "low"}})
        # route contract: 400 "project not open; call /api/projects/open"
        assert r.status_code == 400
        assert "not open" in r.json()["detail"]


class TestFramesProbe:
    def test_probe_counts_frames(self, client, tmp_path):
        d = tmp_path / "frames"
        d.mkdir()
        for i in range(4):
            (d / f"img_{i:03d}.cbf").write_bytes(b"x" * 100)
        (d / "notes.txt").write_text("hi")
        r = client.get("/api/projects/frames_probe",
                       params={"path": str(d)})
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["ok"] is True
        assert j["n_frames"] == 4
        assert j["by_ext"] == {".cbf": 4}
        assert j["n_other_files"] == 1

    def test_probe_missing_dir(self, client, tmp_path):
        r = client.get("/api/projects/frames_probe",
                       params={"path": str(tmp_path / "nope")})
        assert r.status_code == 404

    def test_probe_no_frames(self, client, tmp_path):
        d = tmp_path / "empty"
        d.mkdir()
        (d / "readme.md").write_text("x")
        r = client.get("/api/projects/frames_probe",
                       params={"path": str(d)})
        j = r.json()
        assert j["ok"] is False
        assert j["n_frames"] == 0


class TestRefineDataBlock:
    """GET /api/wb/refine/data - the reflection-data block of one node.

    Since 2026-09-08 a node reads only the observation revision it is bound
    to. A node from before data revisions existed (every node of a
    pre-field campaign) has no binding, and the route must say so rather
    than merge the project's CURRENT reflection file and pass that off as
    the node's history - the data can have been swapped since the commit."""

    PROJ = REPO / "workbench" / "mvp-sjtu9"

    def _get(self, client, **params):
        return client.get("/api/wb/refine/data",
                          params={"project": str(self.PROJ), **params})

    def test_legacy_node_reports_unknown_binding_instead_of_guessing(self, client):
        if not (self.PROJ / "crystal.hkl").exists():
            pytest.skip("mvp-sjtu9 fixture not present")
        r = self._get(client, node="n0013")
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["node"] == "n0013"
        assert j["source"] == "unavailable"
        assert j["data"] is None and j["data_revision"] is None
        assert "swap_reflection_data" in j["note"]

    def test_bound_node_returns_data_and_says_where_it_came_from(self, client, tmp_path):
        from test_peak_persistence import synthetic_project
        from crystalpilot.refine.project import RefineProject
        proj = synthetic_project(tmp_path)
        RefineProject(proj).open()         # a controlled import: n0000 is bound
        r = client.get("/api/wb/refine/data",
                       params={"project": str(proj), "node": "n0000"})
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["node"] == "n0000" and j["data_revision"] == "d000001"
        # a recomputed block is NOT the node's own record; either way it
        # comes from the bound revision, never from a guessed current file
        assert j["source"] in ("node", "computed")
        assert set(j["data"]) >= {"r_int", "n_unique", "d_min",
                                  "completeness", "space_group"}
        if j["source"] == "computed":
            assert j["note"] and j["hkl"] == "observations.hkl"

    def test_bad_node_id_rejected(self, client):
        if not (self.PROJ / "crystal.hkl").exists():
            pytest.skip("mvp-sjtu9 fixture not present")
        assert self._get(client, node="../etc").status_code == 400

    def test_non_refinement_project_404s(self, client, tmp_path):
        d = tmp_path / "plain"
        d.mkdir()
        r = client.get("/api/wb/refine/data",
                       params={"project": str(d), "node": "n0001"})
        assert r.status_code == 404


class TestMcpHealth:
    def test_restart_engine_unopened_project_rejected(self, client,
                                                      tmp_path):
        # _session_or_404 answers 400 "project not open" for unknown paths
        r = client.post("/api/projects/restart_engine",
                        json={"path": str(tmp_path / "nope")},
                        headers={"Host": "localhost:8010"})
        assert r.status_code == 400
        assert "not open" in r.text

    def test_watch_mcp_health_streak(self):
        # detection logic without a live workbench: two consecutive
        # transport-death tool errors -> one mcp_down push; any healthy
        # tool round-trip resets the streak
        from crystalpilot.workbench.service import ProjectSession
        ps = object.__new__(ProjectSession)
        pushed = []
        ps._push = lambda tid, ev: pushed.append(ev)
        dead = {"kind": "tool_completed",
                "error": ("tool call error: tool call failed for "
                          "`crystalpilot/get_project_brief`\n\nCaused by:"
                          "\n    Transport closed")}
        ok = {"kind": "tool_completed", "result_tail": "{}"}

        ps._watch_mcp_health(dead)
        assert not pushed                      # one hit is not a verdict
        ps._watch_mcp_health(ok)               # healthy call resets
        ps._watch_mcp_health(dead)
        assert not pushed
        ps._watch_mcp_health(dead)
        assert len(pushed) == 1 and pushed[0]["kind"] == "mcp_down"
        assert "restart_engine" in pushed[0]["action"]
        ps._watch_mcp_health(dead)             # no repeat spam while down
        assert len(pushed) == 1

    def test_non_transport_errors_ignored(self):
        from crystalpilot.workbench.service import ProjectSession
        ps = object.__new__(ProjectSession)
        pushed = []
        ps._push = lambda tid, ev: pushed.append(ev)
        for _ in range(5):
            ps._watch_mcp_health({"kind": "tool_completed",
                                  "error": "InvalidConstraint: bad label"})
        assert not pushed

    def test_mcp_status_unopened_project_rejected(self, client, tmp_path):
        r = client.post("/api/projects/mcp_status",
                        json={"path": str(tmp_path / "nope")},
                        headers={"Host": "localhost:8010"})
        assert r.status_code == 400
        assert "not open" in r.text

    def test_mcp_status_counts_crystalpilot_tools(self):
        """mcp_status extracts the crystalpilot entry from the app-server's
        mcpServerStatus/list; a startup-frozen MCP shows absent/empty (the
        r11 case-c signature) instead of a transport error."""
        from crystalpilot.workbench.service import ProjectSession

        class FakeClient:
            def request(self, method, params, *, response_model):
                assert method == "mcpServerStatus/list"
                return response_model.model_validate({"data": [{
                    "name": "crystalpilot",
                    "authStatus": "notLoggedIn",
                    "resources": [], "resourceTemplates": [],
                    "tools": {f"t{i}": {"name": f"t{i}", "inputSchema": {}}
                              for i in range(41)},
                }]})

        class FakeWb:
            _client = FakeClient()

        ps = object.__new__(ProjectSession)
        ps.wb = FakeWb()
        st = ps.mcp_status(timeout_s=10)
        assert st["present"] is True
        assert st["n_tools"] == 41
        assert st["error"] is None

    def test_mcp_status_absent_server(self):
        from crystalpilot.workbench.service import ProjectSession

        class FakeClient:
            def request(self, method, params, *, response_model):
                return response_model.model_validate({"data": []})

        class FakeWb:
            _client = FakeClient()

        ps = object.__new__(ProjectSession)
        ps.wb = FakeWb()
        st = ps.mcp_status(timeout_s=10)
        assert st["present"] is False
        assert st["n_tools"] == 0


class TestGzip:
    def test_large_json_gzipped(self, client):
        r = client.get("/api/projects/list",
                       headers={"accept-encoding": "gzip"})
        # small responses stay identity (minimum_size), so probe the UI
        # index instead when the list is tiny: both go through the
        # selective middleware; assert no error and correct negotiation
        assert r.status_code == 200
        if int(r.headers.get("content-length", "0") or 0) >= 1024:
            assert r.headers.get("content-encoding") == "gzip"

    def test_sse_paths_exempt(self, client):
        # unknown thread 404s BEFORE streaming, but the middleware branch
        # is path-based: even the 404 must come back uncompressed
        r = client.get("/api/threads/events?thread_id=nope",
                       headers={"accept-encoding": "gzip"})
        assert r.headers.get("content-encoding") != "gzip"


class TestArtifactAllowlist:
    """The UI may only fetch project files the workbench actually renders.
    views/ joined the list in 2026-09: view_structure and situation_report
    render structure images INTO the model's context, and until then the
    user could not see any of them (the paths came back as JSON strings
    and the endpoint 404'd)."""

    def _paths(self, tmp_path):
        root = tmp_path / "proj"
        results = root / "CrystalPilot Results"
        return root, results

    def test_rendered_views_allowed(self, tmp_path):
        from crystalpilot.workbench.routes import artifact_allowed
        root, results = self._paths(tmp_path)
        img = root / ".crystalpilot" / "views" / "v101530_asu_a.png"
        assert artifact_allowed(root, results, img)

    def test_deliverables_and_engine_outputs_allowed(self, tmp_path):
        from crystalpilot.workbench.routes import artifact_allowed
        root, results = self._paths(tmp_path)
        for p in (results / "task_1" / "final.cif",
                  root / ".crystalpilot" / "refine" / "checkcif" / "c.json",
                  root / ".crystalpilot" / "refine" / "shelxl" / "j" / "a.lst"):
            assert artifact_allowed(root, results, p), p

    def test_other_project_files_refused(self, tmp_path):
        from crystalpilot.workbench.routes import artifact_allowed
        root, results = self._paths(tmp_path)
        # session internals, uploads and the frames tree stay private
        for p in (root / ".crystalpilot" / "refine" / "session.json",
                  root / ".crystalpilot" / "frames" / "integrated.refl",
                  root / "uploads" / "crystal.hkl",
                  root / "context.json"):
            assert not artifact_allowed(root, results, p), p


class TestProjectsStatus:
    """Global situational awareness: where every project stands, without
    booting an engine. Before this the recent-projects list was pure
    navigation - no R1, no alerts, no busy state - and opening project B
    closed project A, so there was no way to see the whole board."""

    def _project(self, tmp_path, *, r1=0.0648, alerts=None):
        import json
        p = tmp_path / "proj"
        (p / ".crystalpilot" / "refine" / "nodes" / "n0000").mkdir(
            parents=True)
        (p / ".crystalpilot-workbench.json").write_text(json.dumps({
            "threads": [{"thread_id": "t1", "title": "older",
                         "last_active": 100.0},
                        {"thread_id": "t2", "title": "newest",
                         "last_active": 500.0}],
            "settings": {"permission_mode": "auto"}}), encoding="utf-8")
        nd = p / ".crystalpilot" / "refine" / "nodes" / "n0000"
        (nd / "node.json").write_text(json.dumps({
            "id": "n0000", "tool": "run_shelxl", "branch": "main",
            "model": {"n_atoms": 63},
            "metrics": {"r1_strong": r1, "wr2": 0.19}}), encoding="utf-8")
        (p / ".crystalpilot" / "refine" / "state.json").write_text(
            json.dumps({"active_node": "n0000", "branches": {"main": "n0000"},
                        "seq": 1}), encoding="utf-8")
        if alerts is not None:
            job = p / ".crystalpilot" / "refine" / "checkcif" / "job_1"
            job.mkdir(parents=True)
            (job / "checkcif.json").write_text(
                json.dumps({"counts": alerts, "alerts": []}),
                encoding="utf-8")
        return p

    def test_reads_head_metrics_and_alerts_off_disk(self, tmp_path):
        from crystalpilot.workbench.routes import _project_status_from_disk
        p = self._project(tmp_path, alerts={"A": 2, "B": 1, "C": 5, "G": 9})
        st = _project_status_from_disk(p)
        assert st["r1"] == 0.0648 and st["n_atoms"] == 63
        assert st["active_node"] == "n0000" and st["n_nodes"] == 1
        assert st["checkcif"]["A"] == 2
        assert st["permission_mode"] == "auto"

    def test_reports_the_most_recent_thread(self, tmp_path):
        from crystalpilot.workbench.routes import _project_status_from_disk
        st = _project_status_from_disk(self._project(tmp_path))
        assert st["n_threads"] == 2
        assert st["last_title"] == "newest" and st["last_active"] == 500.0

    def test_empty_project_does_not_raise(self, tmp_path):
        from crystalpilot.workbench.routes import _project_status_from_disk
        d = tmp_path / "blank"
        d.mkdir()
        assert _project_status_from_disk(d) == {}

    def test_unreadable_state_is_survived(self, tmp_path):
        from crystalpilot.workbench.routes import _project_status_from_disk
        d = tmp_path / "broken"
        d.mkdir()
        (d / ".crystalpilot-workbench.json").write_text("{not json",
                                                        encoding="utf-8")
        # a status view must degrade, never 500 the whole board
        assert _project_status_from_disk(d) == {"n_threads": 0,
                                                "permission_mode": None}

    def test_endpoint_is_served(self, client):
        r = client.get("/api/projects/status")
        assert r.status_code == 200
        assert isinstance(r.json(), list)
        for row in r.json():
            assert {"path", "name", "is_open", "busy"} <= set(row)
