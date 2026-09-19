"""The explanation gate only demands alerts the agent's own checkCIF
raised. The mentor's PLATON rerun (SHLEXE set, fcf/res/fab embedded)
produces FCF-dependent codes (905/911/934/975) that the pa1 agents' runs
never showed; every pa1 delivery was reported 'not self-consistent' for
codes it could not have explained."""
from __future__ import annotations

import json

from crystalpilot.benchmark.evaluate_refinement import (_agent_checkcif_codes,
                                                        explanation_gate)

RERUN = [{"code": "020", "type": 1, "level": "A", "text": "Rint"},
         {"code": "911", "type": 3, "level": "B", "text": "missing fcf refl"},
         {"code": "934", "type": 3, "level": "C", "text": "missing refl"},
         {"code": "260", "type": 2, "level": "C", "text": "ueq"},
         {"code": "004", "type": 1, "level": "G", "text": "info"}]


def test_rerun_only_codes_are_listed_not_gated():
    need, unexplained, rerun_only = explanation_gate(
        RERUN, vtext="020 explained; 260 explained",
        agent_codes={"020", "260", "004"})
    assert [a["code"] for a in need] == ["020", "260"]
    assert unexplained == []
    assert rerun_only == ["911", "934"]


def test_alerts_the_agent_saw_are_still_demanded():
    need, unexplained, rerun_only = explanation_gate(
        RERUN, vtext="020 explained", agent_codes={"020", "260", "911"})
    assert unexplained == ["260", "911"]
    assert rerun_only == ["934"]


def test_without_agent_checkcif_every_rerun_alert_is_demanded():
    need, unexplained, rerun_only = explanation_gate(RERUN, vtext="",
                                                     agent_codes=None)
    assert [a["code"] for a in need] == ["020", "911", "934", "260"]
    assert unexplained == ["020", "260", "911", "934"]
    assert rerun_only == []


def test_agent_codes_read_from_checkcif_json(tmp_path):
    cif = tmp_path / "final.cif"
    cif.write_text("data_x\n", encoding="utf-8")
    assert _agent_checkcif_codes(cif) is None
    (tmp_path / "checkcif.json").write_text(json.dumps({"alerts": [
        {"code": "020", "level": "A"}, {"code": 911, "level": "B"}]}),
        encoding="utf-8")
    assert _agent_checkcif_codes(cif) == {"020", "911"}
