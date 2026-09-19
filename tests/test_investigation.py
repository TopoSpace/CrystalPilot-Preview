"""Round-3 WP7: the investigation record (goal / success tiers / ruled out
/ open directions) and the diagnostic-delivery gate that reads it.

Live-demo Zr-MOF: twice the agent prepared to end with a diagnostic
delivery after one route failed, and a human had to say "the goal is the
whole guest, not this pose". `set_investigation` gives the goal an object
of its own; `finalize_delivery` writes the unmet tiers and the untried
directions of a diagnostic delivery into open_items and refuses to seal
only when nothing says what was not achieved. Final promotion is not
gated.
"""
from __future__ import annotations

import json

import pytest

from crystalpilot.refine import investigation as inv
from crystalpilot.refine import tools_deliver as td
from crystalpilot.refine.registry import MUTATING_TOOLS, SESSIONLESS_TOOLS
from tests.test_finalize_delivery import _complete, _ctx, _project, _write  # noqa: E402
from tests.test_probe_site import ATOMS_A, CELL_A, _open, make_project  # noqa: E402


@pytest.fixture()
def proj(tmp_path):
    return _open(make_project(tmp_path, CELL_A, "P -1", ATOMS_A, ATOMS_A,
                              z=2, d_min=0.75))


# ---------------------------------------------------------------------------
class TestSetInvestigation:
    def test_record_roundtrip_and_partial_updates(self, proj):
        p = proj
        n_nodes_before = len(p.nodes.list_nodes()) if hasattr(p.nodes, "list_nodes") else None
        active = p.nodes.state()["active_node"]
        r = p.invoke_tool("set_investigation", {
            "goal": "locate the whole guest in the pore",
            "tiers": {"candidate_complete": "unmet"},
            "open_directions": ["pose search in the other pore region",
                                "second conformer"],
            "budget": {"wall_clock_min": 90}})
        assert r.ok, r.error
        blk = r.summary["investigation"]
        assert blk["goal"] == "locate the whole guest in the pore"
        assert blk["tiers"] == {"candidate_complete": "unmet",
                                "scientifically_established": "unmet"}
        assert blk["unmet_tiers"] == ["candidate_complete",
                                      "scientifically_established"]
        assert blk["open_directions"] == ["pose search in the other pore region",
                                          "second conformer"]
        assert "goal" in r.summary["changed"]
        assert p.nodes.state()["active_node"] == active  # no node created
        rec = inv.load(p.dir)
        assert inv.is_set(rec) and rec["updated"]
        assert json.loads(inv.investigation_path(p.dir).read_text(encoding="utf-8"))["goal"]

        # a failed route rules out one configuration; the direction closes
        r2 = p.invoke_tool("set_investigation", {
            "rule_out": [{"what": "guest lying along a",
                          "evidence": "search_fragment_pose c01 had 5 geometry_only atoms; refine drifted to occupancy 0.02"}],
            "close_directions": ["pose search in the other pore region"]})
        assert r2.ok, r2.error
        blk = r2.summary["investigation"]
        assert blk["n_ruled_out"] == 1
        assert blk["ruled_out"][0]["what"] == "guest lying along a"
        assert blk["ruled_out"][0]["node"] == active
        assert blk["open_directions"] == ["second conformer"]

        # 'met' needs evidence
        r3 = p.invoke_tool("set_investigation",
                           {"tiers": {"candidate_complete": "met"}})
        assert not r3.ok and "needs evidence" in r3.error
        r4 = p.invoke_tool("set_investigation", {"tiers": {
            "candidate_complete": {"status": "met",
                                   "evidence": "accept_fragment_pose c02 at n0012, R1 stable over 3 cycles"}}})
        assert r4.ok, r4.error
        assert r4.summary["investigation"]["unmet_tiers"] == ["scientifically_established"]
        assert r4.summary["investigation"]["tier_evidence"]["candidate_complete"].startswith("accept_fragment_pose")

        # nothing new -> nothing written
        r5 = p.invoke_tool("set_investigation", {"goal": "locate the whole guest in the pore"})
        assert r5.ok and r5.summary["changed"] == []
        assert r5.summary["tool_status"]["no_change"]["value"] is True

        # bad inputs are refused cleanly
        assert not p.invoke_tool("set_investigation",
                                 {"tiers": {"published": "met"}}).ok
        assert not p.invoke_tool("set_investigation",
                                 {"tiers": {"candidate_complete": "done"}}).ok
        assert not p.invoke_tool("set_investigation",
                                 {"rule_out": [{"what": "x", "evidence": "no"}]}).ok
        if n_nodes_before is not None:
            assert len(p.nodes.list_nodes()) == n_nodes_before

    def test_tool_is_sessionless_and_not_a_model_mutation(self):
        assert "set_investigation" in SESSIONLESS_TOOLS
        assert "set_investigation" not in MUTATING_TOOLS
        from crystalpilot.mcp.server import READ_ONLY_TOOLS
        assert "set_investigation" not in READ_ONLY_TOOLS

    def test_situation_report_carries_the_record(self, proj):
        p = proj
        assert p.invoke_tool("set_investigation", {
            "goal": "whole guest", "add_directions": ["other region"]}).ok
        r = p.invoke_tool("situation_report", {})
        assert r.ok, r.error
        blk = r.summary["open_items"]["investigation"]
        assert blk["goal"] == "whole guest"
        assert blk["open_directions"] == ["other region"]
        assert any("研究目标" in line and "未试方向" in line
                   for line in r.summary["narrative"])

    def test_damaged_file_reads_empty(self, tmp_path):
        path = inv.investigation_path(tmp_path)
        path.parent.mkdir(parents=True)
        path.write_text("{oops", encoding="utf-8")
        rec = inv.load(tmp_path)
        assert not inv.is_set(rec)
        assert inv.unmet_tiers(rec) == list(inv.TIERS)


# ---------------------------------------------------------------------------
class TestDiagnosticGate:
    def test_diagnostic_seal_writes_unmet_tiers_and_open_directions(self, tmp_path):
        proj = _project(tmp_path)
        assert _write(proj, status="diagnostic").ok
        out = tmp_path / "CrystalPilot Results" / "t1"
        _complete(out)
        rec = inv.empty()
        rec["goal"] = "whole guest located"
        rec["success_tiers"]["candidate_complete"] = {
            "status": "met", "evidence": "accept_fragment_pose c01 at n0003"}
        rec["open_directions"] = ["free-occupancy refinement of the guest"]
        inv.save(tmp_path, rec)
        r = td.FinalizeDelivery(proj).run(_ctx())
        assert r.ok, r.error
        assert r.summary["status"] == "diagnostic" and r.summary["promoted"] is False
        items = {i["item"]: i["text"] for i in r.summary["open_items"]}
        assert "goal:scientifically_established" in items
        assert "goal:candidate_complete" not in items
        assert "whole guest located" in items["goal:scientifically_established"]
        assert items["direction#1"] == ("untried direction: free-occupancy "
                                        "refinement of the guest")
        man = json.loads((out / "MANIFEST.json").read_text(encoding="utf-8"))
        assert {i["item"] for i in man["open_items"]} >= {
            "goal:scientifically_established", "direction#1"}
        rep = json.loads((out / "REPORT.json").read_text(encoding="utf-8"))
        assert rep["finalized"]["investigation"]["goal"] == "whole guest located"
        assert rep["finalized"]["investigation"]["unmet_tiers"] == [
            "scientifically_established"]

    def test_unmet_goals_parameter_is_the_fallback(self, tmp_path):
        proj = _project(tmp_path)
        assert _write(proj, status="diagnostic").ok
        out = tmp_path / "CrystalPilot Results" / "t1"
        _complete(out)
        r = td.FinalizeDelivery(proj).run(_ctx())
        assert not r.ok and "did NOT achieve" in r.error
        assert "set_investigation" in r.error and "unmet_goals" in r.error
        rep0 = json.loads((out / "REPORT.json").read_text(encoding="utf-8"))
        assert "finalized" not in rep0 and rep0["status"] == "diagnostic"
        r = td.FinalizeDelivery(proj).run(
            _ctx(), unmet_goals=["guest not located", " "])
        assert r.ok, r.error
        assert [i for i in r.summary["open_items"] if i["item"].startswith("unmet_goal")] == [
            {"item": "unmet_goal#1", "text": "guest not located"}]

    def test_final_promotion_is_not_gated(self, tmp_path):
        proj = _project(tmp_path)
        assert _write(proj).ok
        out = tmp_path / "CrystalPilot Results" / "t1"
        _complete(out)
        r = td.FinalizeDelivery(proj).run(_ctx())
        assert r.ok, r.error
        assert r.summary["status"] == "final" and r.summary["promoted"] is True
        assert r.summary["open_items"] == []
        rep = json.loads((out / "REPORT.json").read_text(encoding="utf-8"))
        assert "investigation" not in rep["finalized"]
