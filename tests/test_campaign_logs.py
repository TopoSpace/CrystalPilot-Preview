"""Log capture and log mining for agent campaigns.

Two properties matter more than any single metric here:

  * capture never loses a finished case. A campaign case can cost two
    hours and 30 M tokens; a locked file or a missing rollout must degrade
    to a note in MANIFEST["errors"], never to an exception.
  * mining sees the failures that actually happen. CrystalPilot tools
    report "could not do it" inside a SUCCESSFUL MCP envelope, so an
    analyser that only counts protocol errors reports every tool as
    flawless - including the two `run_shelxt` timeouts that sent r25 down
    a charge-flipping detour.
"""
from __future__ import annotations

import json

import pytest

from crystalpilot.benchmark.campaign_analysis import (
    analyse_case, audit_leakage, audit_path_tokens, failure_consequences,
    find_arg_churn, find_error_chains, find_shell_hazards, find_spin,
    reasoning_texts, tool_calls,
)
from crystalpilot.benchmark.campaign_logs import CaseLogger


def _mcp(tool, args=None, *, ok=True, error=None, secs=0, ts=None):
    """One mcp_tool_call_end rollout record."""
    if ok:
        body = {"ok": True, "summary": {}}
    else:
        body = {"ok": False, "summary": {}, "error": error or "boom"}
    return {
        "timestamp": ts or "2026-09-02T00:00:00.000Z",
        "type": "event_msg",
        "payload": {
            "type": "mcp_tool_call_end",
            "invocation": {"server": "crystalpilot", "tool": tool,
                           "arguments": args or {}},
            "duration": {"secs": secs, "nanos": 0},
            "result": {"Ok": {"content": [
                {"type": "text", "text": json.dumps(body)}]}},
        },
    }


def _reason(text, ts="2026-09-02T00:00:00.000Z"):
    return {"timestamp": ts, "type": "response_item",
            "payload": {"type": "reasoning",
                        "summary": [{"type": "summary_text", "text": text}]}}


class TestFailureDetection:
    def test_ok_envelope_carrying_ok_false_counts_as_a_failure(self):
        # the whole point: this is what a real CrystalPilot failure looks
        # like on the wire, and the transport says everything is fine
        calls = tool_calls([_mcp("run_shelxt", ok=False,
                                 error="shelxt timed out", secs=180)])
        assert calls[0]["ok"] is False
        assert calls[0]["error"] == "shelxt timed out"
        assert calls[0]["secs"] == pytest.approx(180)

    def test_protocol_error_also_counts(self):
        rec = _mcp("refine")
        rec["payload"]["result"] = {"Err": "transport exploded"}
        assert tool_calls([rec])[0]["ok"] is False

    def test_success_is_not_reported_as_failure(self):
        assert tool_calls([_mcp("refine")])[0]["ok"] is True

    def test_error_chain_sums_the_wasted_time(self):
        calls = tool_calls([_mcp("run_shelxt", ok=False, error="x", secs=180),
                            _mcp("run_shelxt", ok=False, error="x", secs=120)])
        chain = find_error_chains(calls)[0]
        assert chain["tool"] == "run_shelxt"
        assert chain["length"] == 2
        assert chain["secs"] == pytest.approx(300.0)


class TestFailureConsequences:
    def test_links_an_error_to_what_the_agent_decided_next(self):
        recs = [_mcp("run_shelxt", ok=False, error="shelxt timed out",
                     secs=180, ts="2026-09-02T00:00:00.000Z"),
                _reason("I'm dealing with the unavailable SHELXT and will "
                        "continue with the charge flip model.",
                        ts="2026-09-02T00:02:00.000Z")]
        calls = tool_calls(recs)
        out = failure_consequences(calls, reasoning_texts(recs))
        assert len(out) == 1
        assert out[0]["tool"] == "run_shelxt"
        assert "charge flip" in out[0]["next_reasoning"]
        assert out[0]["gap_s"] == pytest.approx(120.0)
        # "unavailable" must register: a timeout during the space-group
        # search does not make the program unavailable, and that misreading
        # is the finding
        assert out[0]["pivoted"] is True

    def test_a_successful_run_produces_no_consequences(self):
        recs = [_mcp("refine"), _reason("all good")]
        assert failure_consequences(tool_calls(recs),
                                    reasoning_texts(recs)) == []


class TestReasoningDedup:
    def test_the_same_summary_from_both_channels_counts_once(self):
        # rollouts carry each summary twice (response_item/reasoning and
        # event_msg/agent_reasoning); counting both doubles every pivot
        a = _reason("thinking about space groups")
        b = {"timestamp": a["timestamp"], "type": "event_msg",
             "payload": {"type": "agent_reasoning",
                         "text": "thinking about space groups"}}
        assert len(reasoning_texts([a, b])) == 1


class TestSpinAndChurn:
    def test_repeated_identical_call_in_a_window_is_spin(self):
        calls = tool_calls([_mcp("audit_reflection_data") for _ in range(4)])
        spin = find_spin(calls)
        assert spin and spin[0]["tool"] == "audit_reflection_data"
        assert spin[0]["repeats"] == 3

    def test_the_same_call_far_apart_is_not_spin(self):
        # bracketing a long session with two audits is good practice
        calls = tool_calls([_mcp("situation_report")]
                           + [_mcp(f"t{i}") for i in range(20)]
                           + [_mcp("situation_report")])
        assert not any(s["tool"] == "situation_report" for s in find_spin(calls))

    def test_wait_polling_is_not_spin(self):
        # `wait` on one cell is how you await a long tool, not confusion
        calls = tool_calls([]) + [{"tool": "wait", "args": {"cell_id": "3"},
                                   "ok": None, "secs": 0, "t": 0}] * 5
        assert find_spin(calls) == []

    def test_varying_args_on_one_tool_is_churn(self):
        calls = tool_calls([_mcp("screen_space_groups", {"n": i})
                            for i in range(4)])
        churn = find_arg_churn(calls)
        assert churn[0] == {"tool": "screen_space_groups", "calls": 4,
                            "distinct_args": 4, "n_errors": 0}

    def test_churn_with_errors_is_the_guessing_signature(self):
        """reg3-rz: five successful read_skill calls on different cards
        were reported as a hard-to-call tool. Errors inside the run are
        what separates guessing from browsing; error-bearing runs sort
        first."""
        recs = ([_mcp("read_skill", {"name": f"card-{i}"}) for i in range(4)]
                + [_mcp("set_twin", {"law": "x"}, ok=False, error="bad law"),
                   _mcp("set_twin", {"matrix": [1]}, ok=False, error="bad"),
                   _mcp("set_twin", {"law": "suggest"})])
        churn = find_arg_churn(tool_calls(recs))
        by = {c["tool"]: c for c in churn}
        assert by["read_skill"]["n_errors"] == 0
        assert by["set_twin"]["n_errors"] == 2
        assert churn[0]["tool"] == "set_twin"


class TestShellHazards:
    def test_get_content_without_encoding_is_flagged(self):
        h = find_shell_hazards(["Get-Content -Raw -LiteralPath x.json"])
        assert h[0]["hazard"] == "get-content-no-encoding"

    def test_get_content_with_encoding_is_clean(self):
        assert find_shell_hazards(
            ["Get-Content -Encoding utf8 -Raw x.json"]) == []


class TestRegressionManifests:
    def test_pa2_reuses_the_pa1_briefs_and_data(self):
        from crystalpilot.benchmark.pa1_manifests import (build_all,
                                                          build_regression)
        pa1 = build_all()
        pa2 = build_regression()
        assert set(pa2) == {"pa2-hex", "pa2-cage1", "pa2-cage2"}
        by_name = {c["name"]: c for m in pa1.values() for c in m["cases"]}
        for man in pa2.values():
            assert man["projects_root"].endswith("/pa2")
            assert man["defaults"]["anonymize_projects"] is True
            for c in man["cases"]:
                assert c["arm"] in ("L0", "L2")
                base = by_name[c["name"]] if c["name"] in by_name else \
                    by_name[c["name"][:-1] + "1"]
                # same brief, same data, same reference as the pa1 cell
                assert c["brief"] == base["brief"]
                assert c.get("data_dir") == base.get("data_dir")
                assert c.get("data_alias") == base.get("data_alias")
                assert c["reference"] == base["reference"]
                assert "context" not in c           # L0/L2 carry no context
        assert [c["name"] for c in pa2["pa2-hex"]["cases"]] == [
            "hex-l2-r1", "hex-l0-r1", "hex-l2-r2", "hex-l0-r2"]
        assert [c["name"] for c in pa2["pa2-cage2"]["cases"]] == [
            "cage-l2-r2", "cage-l0-r2"]


class TestLeakageAudit:
    def test_the_cases_own_staging_dir_is_allowed(self):
        cmd = ['ingest_vendor_data({source_dir:"H:/CrystalPilotData/'
               'staging/pa1c"})']
        assert audit_leakage(cmd, [], ["H:/CrystalPilotData/staging/pa1c"]) == []

    def test_a_mentor_reference_path_is_caught(self):
        # reads are NOT sandboxed, so this is detection, not prevention
        hits = audit_leakage(['cat H:/CrystalPilotData/refs/answer.cif'], [],
                             ["H:/CrystalPilotData/staging/pa1c"])
        assert hits and hits[0]["where"] == "shell"

    def test_a_reference_path_in_private_reasoning_is_caught(self):
        hits = audit_leakage([], [(0.0, "I could look at benchmark/data/"
                                        "034A1_.../ref_res.res")], [])
        assert hits and hits[0]["where"] == "reasoning"

    def test_folder_name_cited_as_a_prior_is_reported(self):
        # pa1: four blind cu runs reasoned "the folder is cu-l0-r2, so Cu"
        reasons = [(0.0, "The project folder is cu-l0-r2, which suggests "
                         "copper; I'll look for Cu first."),
                   (1.0, "Nothing about paths here.")]
        hits = audit_path_tokens(reasons, ["cu-l0-r2", "r22a", "cu"])
        assert [h["token"] for h in hits] == ["cu-l0-r2"]   # "cu" too short
        assert "suggests copper" in hits[0]["context"]
        assert audit_path_tokens(reasons, ["p1a2b3c4"]) == []

    def test_analyse_case_reports_path_tokens(self, tmp_path):
        logs = tmp_path / "logs"
        logs.mkdir()
        (logs / "MANIFEST.json").write_text(json.dumps(
            {"case": "cu-l0-r2", "project_dir": "X:/pa1/cu-l0-r2",
             "data_dir": "H:/CrystalPilotData/staging/r22a"}),
            encoding="utf-8")
        rec = {"type": "response_item", "payload": {
            "type": "reasoning", "summary": [
                {"type": "summary_text",
                 "text": "**Folder hint**: cu-l0-r2 implies Cu."}]}}
        (logs / "rollout.jsonl").write_text(json.dumps(rec) + "\n",
                                            encoding="utf-8")
        out = analyse_case(logs, ["H:/CrystalPilotData/staging/r22a"])
        assert out["path_token_cited"] is True
        assert out["path_tokens"][0]["token"] == "cu-l0-r2"


class TestCaseLoggerRobustness:
    def test_capture_survives_a_missing_rollout(self, tmp_path):
        lg = CaseLogger(tmp_path / "out", tmp_path / "proj", "case-x")
        man = lg.collect("thread-that-never-existed")
        assert any("rollout" in e for e in man["errors"])
        assert man["case"] == "case-x"

    def test_capture_survives_a_missing_project_dir(self, tmp_path):
        lg = CaseLogger(tmp_path / "out", tmp_path / "nope", "case-y")
        man = lg.collect(None)          # must not raise
        assert man["files"] == []

    def test_sse_is_appended_as_utf8_and_hashed(self, tmp_path):
        lg = CaseLogger(tmp_path / "out", tmp_path / "proj", "case-z")
        lg.sse(1, {"kind": "agent_message", "text": "空间群定为 P2₁/c"})
        lg.sse(2, {"kind": "turn_completed"})
        man = lg.collect(None)
        f = tmp_path / "out" / "logs" / "sse.jsonl"
        lines = f.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2
        assert "P2₁/c" in lines[0]      # non-ASCII survives the round trip
        entry = next(x for x in man["files"] if x["path"] == "sse.jsonl")
        import hashlib
        assert entry["sha256"] == hashlib.sha256(f.read_bytes()).hexdigest()

    def test_non_serialisable_event_is_noted_not_raised(self, tmp_path):
        lg = CaseLogger(tmp_path / "out", tmp_path / "proj", "case-w")
        lg.sse(1, {"kind": "x", "blob": object()})   # default=str handles it
        man = lg.collect(None)
        assert isinstance(man["errors"], list)


class TestAnalyseCase:
    def test_reads_a_bundle_end_to_end(self, tmp_path):
        logs = tmp_path / "logs"
        logs.mkdir()
        recs = [_mcp("run_shelxt", ok=False, error="shelxt timed out",
                     secs=180),
                _mcp("refine", {"cycles": 5}),
                _reason("falling back to charge flipping")]
        logs.joinpath("rollout.jsonl").write_text(
            "\n".join(json.dumps(r) for r in recs), encoding="utf-8")
        logs.joinpath("MANIFEST.json").write_text(
            json.dumps({"case": "c1", "arm": "L2", "crystal": "hex",
                        "wall_s": 42.0, "lanes_busy": 3}), encoding="utf-8")
        out = analyse_case(logs)
        assert out["case"] == "c1" and out["arm"] == "L2"
        assert out["lanes_busy"] == 3        # wall_s is meaningless without it
        assert out["n_tool_calls"] == 2 and out["n_tool_errors"] == 1
        assert out["tools"]["run_shelxt"]["error_rate"] == 1.0
        assert out["failures"][0]["error"] == "shelxt timed out"
        assert out["leak_clean"] is True

    def test_a_truncated_last_line_does_not_lose_the_rest(self, tmp_path):
        logs = tmp_path / "logs"
        logs.mkdir()
        good = json.dumps(_mcp("refine"))
        logs.joinpath("rollout.jsonl").write_text(
            good + "\n" + good[:40], encoding="utf-8")
        assert analyse_case(logs)["n_tool_calls"] == 1


class TestPromptLadder:
    """The ladder is the experiment. If the levels are not strictly nested,
    or if L3 smuggles in a structural answer, the whole batch measures
    nothing."""

    def test_each_level_contains_the_one_below_it_verbatim(self):
        from crystalpilot.benchmark.pa1_manifests import ARMS, brief_for
        for lo, hi in zip(ARMS, ARMS[1:]):
            assert brief_for(lo) in brief_for(hi), f"{lo} not inside {hi}"

    def test_the_levels_actually_differ(self):
        from crystalpilot.benchmark.pa1_manifests import ARMS, brief_for
        assert len({brief_for(a) for a in ARMS}) == len(ARMS)

    def test_only_l3_gets_a_context_file(self):
        from crystalpilot.benchmark.pa1_manifests import ARMS, build_case
        for arm in ARMS:
            case = build_case("hex", arm, 1)
            assert ("context" in case) is (arm == "L3"), arm

    def test_l3_context_carries_no_structural_conclusion(self):
        # the discipline that separates "more informative prompt" from
        # "answer leakage": charge-side priors only
        import json
        import re
        from crystalpilot.benchmark.pa1_manifests import CRYSTALS
        banned = re.compile(
            r"空间群|space.?group|P2\d|P ?6/|Cccm|C2/c|晶胞参数|"
            r"cell (?:length|param)|R1|wR2|_refine|原子数|拓扑|"
            r"\bZ\s*=|化学式|formula_sum", re.I)
        for name, spec in CRYSTALS.items():
            blob = json.dumps(spec["context"], ensure_ascii=False)
            hit = banned.search(blob)
            assert hit is None, f"{name} context leaks: {hit.group(0)!r}"

    def test_briefs_are_identical_across_crystals_apart_from_the_path(self):
        # anything else that differs would confound crystal with prompt
        from crystalpilot.benchmark.pa1_manifests import ARMS, build_case
        for arm in ARMS:
            briefs = {build_case(c, arm, 1)["brief"]
                      for c in ("hex", "cu", "cage")}
            assert len(briefs) == 1, arm

    def test_the_grid_is_sixteen_cells_with_a_duplicate_ladder(self):
        from crystalpilot.benchmark.pa1_manifests import build_all
        mans = build_all()
        cells = [c for m in mans.values() for c in m["cases"]]
        assert len(cells) == 16
        assert len({c["name"] for c in cells}) == 16   # no collisions
        # the duplicate ladder is what supplies the noise floor; without it
        # an L0-vs-L3 difference cannot be told from LLM variance
        hex_arms = sorted(c["arm"] for c in cells if c["crystal"] == "hex")
        assert hex_arms == ["L0", "L0", "L1", "L1", "L2", "L2", "L3", "L3"]

    def test_every_case_names_a_reference_so_it_can_be_scored(self):
        from crystalpilot.benchmark.pa1_manifests import build_all
        for man in build_all().values():
            for c in man["cases"]:
                assert c["reference"] and c["reference_kind"]

    def test_the_brief_never_carries_a_reference_path(self):
        from crystalpilot.benchmark.pa1_manifests import build_all
        for man in build_all().values():
            for c in man["cases"]:
                assert "refs/" not in c["brief"]
                assert "reference" not in c["brief"].lower()


class TestToolOkFlag:
    """`ok` in a tool_completed event is CrystalPilot's own envelope
    convention, not MCP's. Codex built-ins answer in their own shape, and
    reading a missing key as False painted the first two calls of every
    session as failures."""

    @staticmethod
    def _ev(text, tool="t", server="crystalpilot"):
        from types import SimpleNamespace
        from crystalpilot.workbench.core import normalize_notification
        payload = SimpleNamespace(item={
            "type": "mcpToolCall", "server": server, "tool": tool,
            "arguments": {}, "status": "completed", "duration_ms": 1,
            "result": {"content": [{"type": "text", "text": text}]}})
        return normalize_notification("item/completed", payload)

    def test_a_codex_builtin_with_no_ok_key_is_not_a_failure(self):
        # {"resources": []} is the CORRECT answer from a server that
        # exposes no resources; it used to render as ok=False
        ev = self._ev('{"resources": []}', tool="list_mcp_resources",
                      server="codex")
        assert ev["ok"] is None

    def test_an_explicit_false_still_reads_as_failure(self):
        assert self._ev('{"ok": false, "error": "shelxt timed out"}',
                        tool="run_shelxt")["ok"] is False

    def test_an_explicit_true_still_reads_as_success(self):
        assert self._ev('{"ok": true, "summary": {}}')["ok"] is True

    def test_non_json_output_stays_unknown(self):
        assert self._ev("not json at all")["ok"] is None

    def test_a_json_scalar_does_not_crash_the_mapper(self):
        assert self._ev('"just a string"')["ok"] is None
