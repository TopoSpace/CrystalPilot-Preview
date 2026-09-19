"""ka1_report against a synthetic campaign tree.

Everything here is hand-built under tmp_path: the real workdir is never
read, which is the point of `load_cases(root=...)`. The rollout.jsonl is
written in the exact shape `campaign_analysis.read_rollout` /
`tool_calls` parse (an `mcp_tool_call_end` payload whose Ok envelope
carries `{"ok": false}`, an `agent_reasoning` payload, a `function_call`
payload carrying a shell command), so the process sections are exercised
through the real miner rather than a mock.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from crystalpilot.benchmark import ka1_report as kr

SECTIONS = ("## 1. 结果总表", "## 2. 两臂对比（按晶体）",
            "## 3. 过程分析（执行层）",
            "## 4. 跑偏倾向与打转点（机械信号，待人工核读）",
            "## 5. 工具易用性信号", "## 附：运行记账")

ROLLOUT = [
    {"timestamp": "2026-09-03T01:00:00.000Z", "type": "response_item",
     "payload": {"type": "mcp_tool_call_end",
                 "invocation": {"tool": "run_shelxt",
                                "arguments": {"cell": "a"}},
                 "duration": {"secs": 12, "nanos": 0},
                 "result": {"Ok": {"content": [
                     {"type": "text",
                      "text": '{"ok": false, "error": "shelxt timed out"}'}]}}}},
    {"timestamp": "2026-09-03T01:00:20.000Z", "type": "response_item",
     "payload": {"type": "mcp_tool_call_end",
                 "invocation": {"tool": "run_shelxt",
                                "arguments": {"cell": "a"}},
                 "duration": {"secs": 3, "nanos": 0},
                 "result": {"Ok": {"content": [
                     {"type": "text",
                      "text": '{"ok": false, "error": "shelxt timed out"}'}]}}}},
    {"timestamp": "2026-09-03T01:00:40.000Z", "type": "event_msg",
     "payload": {"type": "agent_reasoning",
                 "text": "run_shelxt timed out twice, falling back to "
                         "charge flipping"}},
    {"timestamp": "2026-09-03T01:01:00.000Z", "type": "response_item",
     "payload": {"type": "function_call", "name": "shell",
                 "arguments": {"command":
                               "Get-Content H:/CrystalPilotData/refs/ans.cif"}}},
]


#: the two things the miner used to miss, in the wire shapes ka1 produced:
#: a call the MCP layer rejected before the tool ran (Ok envelope, bare
#: non-json text) and a detached job polled at the cadence the tool asked
#: for (identical arguments, and correct)
SCHEMA_AND_POLL = [
    {"timestamp": "2026-09-03T02:00:00.000Z", "type": "event_msg",
     "payload": {"type": "mcp_tool_call_end",
                 "invocation": {"tool": "compare_nodes",
                                "arguments": {"nodes": ["n0004", "n0006"]}},
                 "duration": {"secs": 0, "nanos": 4054300},
                 "result": {"Ok": {"content": [
                     {"type": "text",
                      "text": "Input validation error: 'a' is a required "
                              "property"}], "isError": True}}}},
    {"timestamp": "2026-09-03T02:01:00.000Z", "type": "event_msg",
     "payload": {"type": "mcp_tool_call_end",
                 "invocation": {"tool": "compare_nodes",
                                "arguments": {"node_a": "n1",
                                              "node_b": "n2"}},
                 "duration": {"secs": 0, "nanos": 0},
                 "result": {"Ok": {"content": [
                     {"type": "text",
                      "text": "Input validation error: 'a' is a required "
                              "property"}], "isError": True}}}},
] + [
    {"timestamp": f"2026-09-03T02:{2 + i:02d}:00.000Z", "type": "event_msg",
     "payload": {"type": "mcp_tool_call_end",
                 "invocation": {"tool": "run_shelxl",
                                "arguments": {"job_status": "job_x"}},
                 "duration": {"secs": 0, "nanos": 0},
                 "result": {"Ok": {"content": [
                     {"type": "text",
                      "text": '{"ok": true, "summary": {}}'}]}}}}
    for i in range(4)
]

#: the MCP server's transport watchdog: the case ended with this tool
#: still computing, so the rollout has the call and no result
SERVER_LOG = [
    {"ts": "2026-09-03T01:00:00", "pid": 1, "mode": "tools_only"},
    {"ts": "2026-09-03T03:00:00", "pid": 1, "event": "transport_closed",
     "running_tool": "solve_charge_flipping", "elapsed_s": 3142.0,
     "budget_s": 900.0, "waited_s": 60.0, "action": "exit_abandoning_tool"},
]


def _write(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=1),
                 encoding="utf-8")


def _state_entry(**kw):
    base = {"status": "graded", "model": "gpt-5.6-sol", "effort": "xhigh",
            "wall_s": 3600.0, "lanes_busy": 3, "log_bytes": 1234,
            "usage": {"total_tokens": 1_500_000},
            "agents_version": "v32", "agents_sha256": "a" * 64,
            "agents_matches_template": True, "root_agents_sha256": None,
            "agents_chain": [{"is_project": True, "sha256": "a" * 64}]}
    base.update(kw)
    return base


def _grade_below_bar():
    """below_bar, with an incomparable R1 delta and several gates failed."""
    return {
        "project": "p-tools", "grade": "below_bar",
        "grade_reasons": ["R1 0.162 above 0.10 (delta vs reference not "
                          "comparable: different resolution cuts)"],
        "self_consistency": {
            "cif": {"space_group": "P 21 21 21", "r1_gt": 0.162},
            "s2_cif_matches_fcf": True,
            "s3_report_matches_cif": False,
            "checkcif": {"gate_d_pass": True, "counts": {"A": 1, "B": 0}},
            "peek_report": {"clean": True},
            "unresolved_disclosed": ["solvent not modelled"],
            "self_consistent": False,
        },
        "node_tree": {"best_node_id": "n0021", "best_node_r1": 0.101,
                      "delivered_node_r1": 0.162,
                      "delivery_vs_best_delta": 0.061,
                      "better_node_existed": True},
        "porosity": {"mask_block_in_cif": False, "void_fraction": 0.21,
                     "n_guest_fragments": 0,
                     "porous_unmasked_unmodelled": True},
        "reference_layer": {
            "sg_agent": "P 21 21 21", "sg_reference": "P 21 21 21",
            "sg_type_equal": True, "cell_compatible": True,
            "r1_agent": 0.162, "r1_reference": 0.045, "r1_delta": 0.117,
            "r1_delta_incomparable": True, "r1_scored": False,
            "emma": {"solved": True, "metal_identity_ok": False,
                     "n_element_mismatch": 2,
                     "guest": {"n_ref": 4, "n_matched": 0, "recall": 0.0}},
        },
        "verdict_matches_cif": False,
    }


def _grade_publication():
    return {
        "project": "p-full", "grade": "publication",
        "self_consistency": {
            "cif": {"space_group": "P 21 21 21", "r1_gt": 0.0412},
            "s2_cif_matches_fcf": True, "s3_report_matches_cif": True,
            "checkcif": {"gate_d_pass": True, "counts": {"A": 0}},
            "peek_report": {"clean": True},
            "unresolved_disclosed": ["H on O2 not located"],
            "self_consistent": True,
        },
        "node_tree": {"best_node_id": "n0044", "best_node_r1": 0.0412,
                      "delivered_node_r1": 0.0412,
                      "delivery_vs_best_delta": 0.0,
                      "better_node_existed": False},
        "porosity": {"mask_block_in_cif": True, "void_fraction": 0.03,
                     "n_guest_fragments": 2,
                     "porous_unmasked_unmodelled": False},
        "reference_layer": {
            "sg_agent": "P 21 21 21", "sg_reference": "P 21 21 21",
            "sg_type_equal": True, "cell_compatible": True,
            "r1_agent": 0.0412, "r1_reference": 0.0398, "r1_delta": 0.0014,
            "r1_scored": True,
            "emma": {"solved": True, "metal_identity_ok": True,
                     "n_element_mismatch": 0},
        },
        "verdict_matches_cif": True,
    }


def build_tree(root: Path, *, root_agents: str | None = None,
               matches_template: bool = True,
               with_logs: bool = True) -> Path:
    """ka1-hex with both arms graded; ka1-cage never started."""
    hex_dir = root / "ka1-hex"
    chain = [{"is_project": True, "sha256": "a" * 64}]
    if root_agents:
        chain = [{"is_project": False, "sha256": root_agents}] + chain
    _write(hex_dir / "state.json", {
        "hex-tools-r1": _state_entry(
            grade="below_bar", knowledge_mode="tools_only",
            agents_version="ka1-tools-only",
            agents_matches_template=matches_template,
            verdict_matches_cif=False),
        "hex-full-r1": _state_entry(
            grade="publication", knowledge_mode="full", wall_s=5400.0,
            usage={"total_tokens": 2_100_000},
            root_agents_sha256=root_agents, agents_chain=chain,
            verdict_matches_cif=True),
    })
    _write(hex_dir / "hex-tools-r1" / "grade.json", _grade_below_bar())
    _write(hex_dir / "hex-full-r1" / "grade.json", _grade_publication())
    if with_logs:
        logs = hex_dir / "hex-tools-r1" / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        (logs / "rollout.jsonl").write_text(
            "\n".join(json.dumps(x) for x in ROLLOUT), encoding="utf-8")
        _write(logs / "MANIFEST.json",
               {"case": "hex-tools-r1", "lanes_busy": 3, "errors": []})
    # lane present in the manifest, never started: no state.json at all
    (root / "ka1-cage").mkdir(parents=True, exist_ok=True)
    return root


@pytest.fixture()
def tree(tmp_path: Path) -> Path:
    return build_tree(tmp_path / "campaigns", root_agents="d" * 64)


def _recs(root: Path, lanes=("ka1-hex", "ka1-cage")):
    return kr.load_cases(lanes, root=root)


# ------------------------------------------------------------------ loader
def test_load_cases_lists_every_expected_cell(tree: Path):
    recs = _recs(tree)
    names = [r["case"] for r in recs]
    assert names == ["hex-tools-r1", "hex-full-r1",
                     "cage-tools-r1", "cage-full-r1"]
    started = {r["case"]: r["started"] for r in recs}
    assert started["hex-tools-r1"] and started["hex-full-r1"]
    assert not started["cage-tools-r1"] and not started["cage-full-r1"]
    by = {r["case"]: r for r in recs}
    assert by["hex-tools-r1"]["arm"] == "tools"
    assert by["hex-full-r1"]["arm"] == "full"
    assert by["hex-tools-r1"]["crystal"] == "hex"


def test_load_cases_never_touches_a_missing_root(tmp_path: Path):
    recs = kr.load_cases(("ka1-hex",), root=tmp_path / "nope")
    assert len(recs) == 2
    assert all(not r["started"] and not r["graded"] for r in recs)
    assert "未跑" in kr.render_report(recs)


def test_analyse_logs_tolerates_a_missing_logs_dir(tmp_path: Path):
    assert kr.analyse_logs(tmp_path / "logs") is None


def test_grade_facts_are_pulled_off_grade_json(tree: Path):
    by = {r["case"]: r for r in _recs(tree)}
    t = by["hex-tools-r1"]
    assert t["grade"] == "below_bar"
    assert t["r1_agent"] == 0.162 and t["r1_reference"] == 0.045
    assert t["r1_incomparable"] is True and t["r1_scored"] is False
    assert t["elements_ok"] is False
    assert t["better_node_existed"] is True
    assert t["gates"]["s3 REPORT↔CIF"] is False
    assert t["gates"]["结论↔CIF"] is False
    assert t["n_unresolved"] == 1
    assert by["hex-full-r1"]["grade"] == "publication"


# ------------------------------------------------------------- rendering
def test_missing_case_renders_as_not_run(tree: Path):
    md = kr.render_report(_recs(tree))
    row = [l for l in md.splitlines() if l.startswith("| cage-tools-r1 ")]
    assert row, "the never-started case must still get an accounting row"
    cell_rows = [l for l in md.splitlines()
                 if l.startswith("| cage ") and "| 未跑 |" in l]
    assert cell_rows, "cage cells must render 未跑 in the summary table"
    assert "未跑" in md


def test_incomparable_delta_renders_as_not_comparable(tree: Path):
    md = kr.render_report(_recs(tree))
    assert "不可比" in md
    assert "分辨率截断不同" in md
    # the comparable delta must NOT be marked incomparable
    recs = {r["case"]: r for r in _recs(tree)}
    assert kr._delta_cell(recs["hex-full-r1"]) == "+0.0014"
    assert "不可比" in kr._delta_cell(recs["hex-tools-r1"])


def test_two_arm_verdict_prefers_the_higher_grade_band(tree: Path):
    recs = {r["case"]: r for r in _recs(tree)}
    v, why = kr.arm_verdict(recs["hex-tools-r1"], recs["hex-full-r1"])
    assert v == "B>A" and "publication" in why
    assert "**机械判语：B>A**" in kr.render_report(list(recs.values()))


def test_two_arm_verdict_ladder_and_tie_band():
    def cell(grade, r1):
        return {"case": "x", "started": True, "graded": True,
                "grade": grade, "r1_agent": r1}
    assert kr.arm_verdict(cell("publication", 0.04),
                          cell("below_bar", 0.16))[0] == "A≥B"
    assert kr.arm_verdict(cell("acceptable", 0.090),
                          cell("acceptable", 0.089))[0] == "接近"
    assert kr.arm_verdict(cell("acceptable", 0.090),
                          cell("acceptable", 0.060))[0] == "B>A"
    assert kr.arm_verdict(cell("acceptable", 0.060),
                          cell("acceptable", 0.090))[0] == "A≥B"
    assert kr.arm_verdict(None, cell("acceptable", 0.06))[0] == "不可判"
    assert kr.arm_verdict(cell("acceptable", 0.06),
                          {"case": "y", "started": True,
                           "graded": False})[0] == "不可判"


def test_grade_rank_matches_the_grader_ladder():
    r = kr.GRADE_RANK
    assert r["publication"] > r["acceptable"] > r["below_bar"] > r["no_delivery"]
    assert r["self_consistent_pass"] > r["self_consistent_fail"]


def test_contamination_warning_when_root_agents_sha256_is_set(tmp_path: Path):
    dirty = build_tree(tmp_path / "dirty", root_agents="d" * 64)
    md = kr.render_report(_recs(dirty))
    assert "污染告警" in md
    assert "祖先 AGENTS.md" in md

    clean = build_tree(tmp_path / "clean", root_agents=None)
    md_clean = kr.render_report(_recs(clean))
    assert "污染告警" not in md_clean
    assert "未发现祖先 AGENTS.md 注入" in md_clean


def test_template_mismatch_is_flagged_loudly(tmp_path: Path):
    root = build_tree(tmp_path / "bad", matches_template=False)
    md = kr.render_report(_recs(root))
    assert "不匹配模板" in md
    assert "臂标签不可信" in md


def test_process_section_uses_the_real_miner(tree: Path):
    recs = _recs(tree)
    mined = {r["case"]: r["mined"] for r in recs}
    assert mined["hex-tools-r1"] is not None
    assert mined["hex-tools-r1"]["n_tool_errors"] == 2
    assert mined["hex-full-r1"] is None

    md = kr.render_report(recs)
    assert "run_shelxt" in md
    assert "shelxt timed out" in md              # tool error message
    assert "get-content-no-encoding" in md       # shell hazard
    assert "结果作废" in md                       # leakage voids the cell
    assert "falling back" in md                  # pivot excerpt


def test_signals_cover_the_mechanical_flags(tree: Path):
    kinds = {s["kind"] for s in kr.collect_signals(_recs(tree))}
    assert "数据泄漏" in kinds
    assert "交付的不是最佳节点" in kinds
    assert "诚实门未过" in kinds
    assert "祖先 AGENTS.md 注入" in kinds
    assert "多孔但既无掩膜也无客体" in kinds


def test_tool_usability_ranks_by_errors_churn_and_spin(tree: Path):
    agg = kr.aggregate_tools(_recs(tree))
    assert agg["run_shelxt"]["errors"] == 2
    assert agg["run_shelxt"]["error_rate"] == 1.0
    assert agg["run_shelxt"]["secs"] == 15.0
    md = "\n".join(kr.render_tool_usability(_recs(tree)))
    assert "| `run_shelxt` |" in md


def _tree_with(tmp_path: Path, extra_rollout, server_log=None) -> Path:
    root = build_tree(tmp_path / "extra")
    logs = root / "ka1-hex" / "hex-tools-r1" / "logs"
    (logs / "rollout.jsonl").write_text(
        "\n".join(json.dumps(x) for x in ROLLOUT + extra_rollout),
        encoding="utf-8")
    if server_log:
        (logs / "mcp_server.jsonl").write_text(
            "\n".join(json.dumps(x) for x in server_log), encoding="utf-8")
    return root


def test_schema_errors_feed_the_tool_usability_ranking(tmp_path: Path):
    """A tool the model cannot even call must rank as hard to call: these
    calls were rejected before the tool ran, so the tool's own error rate
    would never show them."""
    recs = _recs(_tree_with(tmp_path, SCHEMA_AND_POLL))
    agg = kr.aggregate_tools(recs)
    assert agg["compare_nodes"]["schema_errors"] == 2
    assert agg["compare_nodes"]["errors"] == 2      # a rejection is a failure
    md = "\n".join(kr.render_tool_usability(recs))
    assert "| `compare_nodes` |" in md
    # errors + schema_errors + churn + spin = 2 + 2 + 0 + 0
    row = [ln for ln in md.splitlines() if ln.startswith("| `compare_nodes`")]
    assert row[0].split("|")[2].strip() == "4"
    # and the per-case section names the offending parameter
    case_md = "\n".join(kr.render_process(recs))
    assert "schema 拒绝" in case_md
    assert "`a`" in case_md and "missing_required" in case_md


def test_polling_is_reported_as_waiting_not_as_spin(tmp_path: Path):
    recs = _recs(_tree_with(tmp_path, SCHEMA_AND_POLL))
    mined = {r["case"]: r["mined"] for r in recs}["hex-tools-r1"]
    assert mined["n_polls"] == 4
    assert not any(s["tool"] == "run_shelxl" for s in mined["spin"])
    md = "\n".join(kr.render_process(recs))
    assert "轮询" in md and "job_x" in md
    assert kr.aggregate_tools(recs)["run_shelxl"]["polls"] == 4
    # polling must not push a tool onto the hard-to-call list
    assert "| `run_shelxl` |" not in "\n".join(kr.render_tool_usability(recs))


def test_a_tool_abandoned_at_transport_close_is_reported(tmp_path: Path):
    recs = _recs(_tree_with(tmp_path, [], server_log=SERVER_LOG))
    mined = {r["case"]: r["mined"] for r in recs}["hex-tools-r1"]
    assert mined["server_abandoned_tools"] == [
        {"tool": "solve_charge_flipping", "elapsed_s": 3142.0,
         "budget_s": 900.0}]
    md = kr.render_report(recs)
    assert "solve_charge_flipping" in md
    assert "传输断开" in md
    assert "工具被丢下" in {s["kind"] for s in kr.collect_signals(recs)}


def test_report_is_well_formed_markdown_with_all_six_sections(tree: Path):
    md = kr.render_report(_recs(tree))
    assert md.startswith("# ka1：")
    at = -1
    for head in SECTIONS:
        idx = md.find("\n" + head + "\n")
        assert idx > at, f"missing or out-of-order section: {head}"
        at = idx
    assert "<!-- 人工核读：" in md and "-->" in md
    for line in md.splitlines():
        if line.startswith("|"):
            assert line.rstrip().endswith("|"), f"broken table row: {line}"
    # nothing may leak a python repr into the prose
    assert "None" not in md and "{'" not in md
    assert md.endswith("\n")


def test_render_report_on_an_entirely_empty_experiment(tmp_path: Path):
    recs = kr.load_cases(kr.LANES, root=tmp_path / "empty")
    md = kr.render_report(recs)
    assert len(recs) == 6
    assert "实验尚未开始" in md
    assert "尚无任何已评分的格子" in md
    for head in SECTIONS:
        assert head in md


def test_main_writes_a_file_and_survives_an_empty_tree(tmp_path: Path,
                                                       capsys):
    out = tmp_path / "out" / "KA1-ANALYSIS-draft.md"
    rc = kr.main(["--root", str(tmp_path / "empty"), "--out", str(out),
                  "--lanes", "ka1-hex,ka1-cage,ka1-org"])
    assert rc == 0
    assert "未跑" in out.read_text(encoding="utf-8")
    assert "nothing has run yet" in capsys.readouterr().out


def test_staging_allow_reads_the_lane_manifest(tmp_path):
    """reg1-ext2 (2026-09-04): crystals absent from the ka1 table must still
    have their own staging directory subtracted from the leakage audit."""
    import json

    from crystalpilot.benchmark.ka1_report import staging_allow
    (tmp_path / "reg1-ext2.json").write_text(json.dumps({
        "campaign": "reg1-ext2",
        "cases": [
            {"name": "hsl-full-r1", "crystal": "hsl",
             "data_dir": "H:/CrystalPilotData/staging/reg1-hsl"},
            {"name": "cage-full-r1", "crystal": "cage",
             "data_alias": {"link": "H:/CrystalPilotData/staging/pa1c-link",
                            "target": "H:/CrystalPilotData/staging/pa1c"}},
        ]}), encoding="utf-8")
    assert staging_allow("hsl", "reg1-ext2", tmp_path) == [
        "H:/CrystalPilotData/staging/reg1-hsl"]
    cage = staging_allow("cage", "reg1-ext2", tmp_path)
    assert "H:/CrystalPilotData/staging/pa1c" in cage
    assert "H:/CrystalPilotData/staging/pa1c-link" in cage
    # unknown crystal, no manifest: empty, never an exception
    assert staging_allow("nope", "no-such-lane", tmp_path) == []
