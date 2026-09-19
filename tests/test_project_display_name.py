"""Round-3 R2-B sidebar/node-tree data: project display names and the
delivered-node marks, all read off disk without booting an engine."""
from __future__ import annotations

import json
from types import SimpleNamespace

from crystalpilot.workbench import registry
from crystalpilot.workbench.service import (ProjectSession,
                                            project_settings_dict)


def _project(tmp_path, name="proj"):
    p = tmp_path / name
    p.mkdir()
    return p


class TestDisplayName:
    def test_settings_name_wins_over_context_title(self, tmp_path):
        p = _project(tmp_path)
        (p / "context.json").write_text(json.dumps({"title": "Zr-MOF 客体"}),
                                        encoding="utf-8")
        assert registry.project_display_name(p) == "Zr-MOF 客体"
        (p / ".crystalpilot-workbench.json").write_text(json.dumps({
            "threads": [], "settings": {"display_name": "  NU-1000 + pBrAc "}}),
            encoding="utf-8")
        assert registry.project_display_name(p) == "NU-1000 + pBrAc"

    def test_no_name_means_none_not_the_directory(self, tmp_path):
        p = _project(tmp_path)
        assert registry.project_display_name(p) is None
        (p / ".crystalpilot-workbench.json").write_text(json.dumps({
            "threads": [], "settings": {"display_name": "   "}}),
            encoding="utf-8")
        (p / "context.json").write_text(json.dumps({"mode": "structure_only"}),
                                        encoding="utf-8")
        assert registry.project_display_name(p) is None

    def test_broken_files_are_survived(self, tmp_path):
        p = _project(tmp_path)
        (p / ".crystalpilot-workbench.json").write_text("{not json",
                                                        encoding="utf-8")
        (p / "context.json").write_text("[1, 2", encoding="utf-8")
        assert registry.project_display_name(p) is None

    def test_recent_list_and_status_board_carry_it(self, tmp_path, monkeypatch):
        p = _project(tmp_path)
        (p / "context.json").write_text(json.dumps({"title": "笼 t2_2"}),
                                        encoding="utf-8")
        gone = tmp_path / "gone"
        monkeypatch.setattr(registry, "REGISTRY_FILE", tmp_path / "projects.json")
        registry.record_recent(gone)
        registry.record_recent(p)
        rows = registry.recent_projects()
        assert [r["display_name"] for r in rows] == ["笼 t2_2"]
        # the registry file itself stays name-free (names live in the project)
        stored = json.loads((tmp_path / "projects.json").read_text(encoding="utf-8"))
        assert all("display_name" not in e for e in stored)
        from crystalpilot.workbench.routes import projects_status
        board = projects_status()
        mine = [r for r in board if r["path"].lower() == str(p.resolve()).lower()]
        assert mine and mine[0]["display_name"] == "笼 t2_2"

    def test_rename_is_a_plain_setting(self):
        saved: list[int] = []
        project = SimpleNamespace(settings={}, save=lambda: saved.append(1),
                                  path="x")
        stub = SimpleNamespace(wb=SimpleNamespace(project=project),
                               settings=lambda: dict(project.settings),
                               _sync_engine=lambda learned=None: None,
                               _push_settings=lambda: None)
        ProjectSession.update_project_settings(
            stub, {"display_name": "  Zr6   cage\n(ZJJ1174)  "})
        assert project.settings["display_name"] == "Zr6 cage (ZJJ1174)"
        assert saved == [1]
        ProjectSession.update_project_settings(stub, {"display_name": ""})
        assert project.settings["display_name"] is None
        ProjectSession.update_project_settings(stub, {"display_name": "x" * 200})
        assert len(project.settings["display_name"]) == 80
        d = project_settings_dict("x", {"display_name": "MOF-5"}, "auto")
        assert d["display_name"] == "MOF-5"
        assert project_settings_dict("x", {}, "auto")["display_name"] is None


class TestDeliveries:
    def _results(self, p):
        from crystalpilot.workbench.core import RESULTS_DIRNAME
        root = p / RESULTS_DIRNAME
        top = root / "task_20260905_151009"
        sub = top / "whole-guest-study"
        sub.mkdir(parents=True)
        (top / "MANIFEST.json").write_text(json.dumps({
            "status": "diagnostic", "source_state": {"node": "n0070"},
            "delivery_revision": 1, "generated": "2026-09-05T15:10:09"}),
            encoding="utf-8")
        (sub / "MANIFEST.json").write_text(json.dumps({
            "status": "provisional", "final_node": "n0224",
            "delivery_revision": 4}), encoding="utf-8")
        legacy = root / "task_20260905_080102"
        legacy.mkdir()
        (legacy / "MANIFEST.json").write_text(json.dumps({"status": "final"}),
                                              encoding="utf-8")
        (root / "task_broken").mkdir()
        (root / "task_broken" / "MANIFEST.json").write_text("{", encoding="utf-8")
        return root

    def test_manifests_become_marks_and_legacy_ones_are_skipped(self, tmp_path):
        from crystalpilot.workbench.routes import _deliveries_from_disk
        p = _project(tmp_path)
        assert _deliveries_from_disk(p) == []
        self._results(p)
        marks = _deliveries_from_disk(p)
        assert [(m["node"], m["status"], m["rel"]) for m in marks] == [
            ("n0070", "diagnostic", "task_20260905_151009"),
            ("n0224", "provisional", "task_20260905_151009/whole-guest-study"),
        ]
        assert marks[0]["revision"] == 1 and marks[1]["revision"] == 4

    def test_node_route_carries_the_marks(self, tmp_path):
        from crystalpilot.workbench.routes import refine_nodes
        p = _project(tmp_path)
        assert refine_nodes(str(p))["deliveries"] == []
        nd = p / ".crystalpilot" / "refine" / "nodes" / "n0000"
        nd.mkdir(parents=True)
        (nd / "node.json").write_text(json.dumps({
            "id": "n0000", "tool": "run_shelxl", "branch": "main",
            "model": {"n_atoms": 3}, "metrics": {"r1_strong": 0.05}}),
            encoding="utf-8")
        (p / ".crystalpilot" / "refine" / "state.json").write_text(
            json.dumps({"active_node": "n0000", "branches": {"main": "n0000"},
                        "seq": 1}), encoding="utf-8")
        self._results(p)
        out = refine_nodes(str(p))
        assert [n["id"] for n in out["nodes"]] == ["n0000"]
        assert [m["node"] for m in out["deliveries"]] == ["n0070", "n0224"]
