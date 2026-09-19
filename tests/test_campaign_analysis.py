"""Three signals the ka1 log mining used to get wrong.

  polling      `run_shelxt(job_status='job_...')` eleven times is the tool
               contract being followed, not the agent spinning. The tool's
               own result says "poll again in 60-120 s"; scoring that as
               spin punished obedience and buried the real repeats.
  schema       a call the MCP layer rejected against the tool's JSON
               schema comes back as an `Ok` envelope carrying a bare
               non-json string, so the json-only parse read it as a
               success. Those are the calls the model could not even make,
               which is exactly the "hard to call" list we want.
  abandoned    a tool still computing when the MCP server lost its client
               leaves NO result in the rollout - only the server's own log
               knows the case ended with that tool still running.

Fixtures are the real wire shapes, copied from ka1 bundles: an Ok envelope
whose text is `{"ok": false}` for a runtime failure, an Ok envelope whose
text is `Input validation error: ...` for a rejection, and
`{"job_status": "job_..."}` arguments for a poll.
"""
from __future__ import annotations

import json

import pytest

from crystalpilot.benchmark.campaign_analysis import (
    analyse_case, find_abandoned_tools, find_polling, find_spin, poll_job,
    read_server_log, tool_calls,
)

T0 = 1788422369.0


def _ts(offset: float) -> str:
    import datetime
    return (datetime.datetime.fromtimestamp(
        T0 + offset, datetime.timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%S.000Z"))


def _mcp(tool, args=None, *, text=None, ok=True, error=None, secs=0,
         at=0.0):
    """One mcp_tool_call_end record. `text` overrides the result body with
    a raw string, which is how the MCP layer answers a rejected call."""
    if text is None:
        text = json.dumps({"ok": True, "summary": {}} if ok else
                          {"ok": False, "error": error or "boom"})
    return {
        "timestamp": _ts(at), "type": "event_msg",
        "payload": {
            "type": "mcp_tool_call_end",
            "invocation": {"server": "crystalpilot", "tool": tool,
                           "arguments": args or {}},
            "duration": {"secs": int(secs), "nanos": 0},
            "result": {"Ok": {"content": [{"type": "text", "text": text}],
                              "isError": text.startswith("Input")}},
        },
    }


def _poll(job="job_20260903_155917", at=0.0, tool="run_shelxt"):
    return _mcp(tool, {"job_status": job}, at=at)


# ------------------------------------------------------------- polling
class TestPollingIsNotSpin:
    def test_repeated_job_status_calls_are_polling_not_spin(self):
        # the ka1-hex shape: one detached job, polled every ~70 s
        recs = [_mcp("run_shelxt", {"detach": True})] + [
            _poll(at=70 * i) for i in range(8)]
        calls = tool_calls(recs)
        assert find_spin(calls) == []
        poll = find_polling(calls)
        assert len(poll) == 1
        assert poll[0]["tool"] == "run_shelxt"
        assert poll[0]["job"] == "job_20260903_155917"
        assert poll[0]["polls"] == 8
        assert poll[0]["span_s"] == pytest.approx(490.0)
        assert poll[0]["mean_interval_s"] == pytest.approx(70.0)

    def test_two_jobs_are_two_rows(self):
        calls = tool_calls([_poll("job_a", at=0), _poll("job_a", at=60),
                            _poll("job_b", at=600)])
        rows = {p["job"]: p for p in find_polling(calls)}
        assert rows["job_a"]["polls"] == 2 and rows["job_b"]["polls"] == 1
        assert rows["job_b"]["span_s"] is None      # one poll spans nothing

    def test_polling_works_for_every_long_tool(self):
        calls = tool_calls([_poll("j1", tool="run_shelxl"),
                            _poll("j1", tool="run_shelxl", at=60),
                            _poll("j2", tool="solve_charge_flipping"),
                            _poll("j2", tool="solve_charge_flipping", at=60)])
        assert find_spin(calls) == []
        assert {p["tool"] for p in find_polling(calls)} == {
            "run_shelxl", "solve_charge_flipping"}

    def test_a_real_repeat_is_still_spin(self):
        # identical NON-poll calls: the behaviour the detector exists for
        calls = tool_calls([_mcp("audit_reflection_data") for _ in range(4)])
        assert find_spin(calls)[0]["repeats"] == 3
        assert find_polling(calls) == []

    def test_poll_job_reads_a_json_string_argument(self):
        # the function-call transport carries arguments as a JSON string
        assert poll_job('{"job_status": "job_x"}') == "job_x"
        assert poll_job({"job_status": "  job_y  "}) == "job_y"
        assert poll_job({"job_status": ""}) is None
        assert poll_job({"detach": True}) is None
        assert poll_job("not json") is None

    def test_analyse_case_reports_polls_and_the_wall_clock(self, tmp_path):
        logs = tmp_path / "logs"
        logs.mkdir()
        recs = [_mcp("run_shelxt", {"detach": True})] + [
            _poll(at=60 * i) for i in range(1, 6)]
        logs.joinpath("rollout.jsonl").write_text(
            "\n".join(json.dumps(r) for r in recs), encoding="utf-8")
        out = analyse_case(logs)
        assert out["spin"] == []
        assert out["n_polls"] == 5
        assert out["polled_wall_s"] == pytest.approx(240.0)
        assert out["tools"]["run_shelxt"]["polls"] == 5
        assert out["tools"]["run_shelxt"]["calls"] == 6   # detach + 5 polls


# -------------------------------------------------------- schema errors
class TestSchemaErrors:
    def test_a_rejected_call_is_a_failure_not_a_success(self):
        # ka1-cage: the Ok envelope carries a bare string, so the json-only
        # parse scored this a clean call
        c = tool_calls([_mcp("compare_nodes", {"nodes": ["n0004", "n0006"]},
                             text="Input validation error: 'a' is a "
                                  "required property")])[0]
        assert c["ok"] is False
        assert c["schema_error"]["param"] == "a"
        assert c["schema_error"]["kind"] == "missing_required"

    def test_the_parameter_is_recovered_from_the_offending_value(self):
        # "600 is greater than the maximum of 500" names no parameter; the
        # call that produced it does (ka1-cage-tools-r1)
        c = tool_calls([_mcp("run_shelxt", {"n_phase_sets": 600,
                                            "detach": True},
                             text="Input validation error: 600 is greater "
                                  "than the maximum of 500")])[0]
        assert c["schema_error"] == {"param": "n_phase_sets",
                                     "kind": "out_of_range",
                                     "message": "600 is greater than the "
                                                "maximum of 500"}

    def test_an_unexpected_property_is_named(self):
        c = tool_calls([_mcp("refine", {"cycles": 5},
                             text="Input validation error: Additional "
                                  "properties are not allowed ('cycles' "
                                  "was unexpected)")])[0]
        assert c["schema_error"]["param"] == "cycles"
        assert c["schema_error"]["kind"] == "unknown_param"

    def test_a_wrong_type_falls_back_to_the_argument_that_held_it(self):
        c = tool_calls([_mcp("refine", {"cycles": "five"},
                             text="Input validation error: 'five' is not "
                                  "of type 'integer'")])[0]
        assert c["schema_error"]["param"] == "cycles"
        assert c["schema_error"]["kind"] == "wrong_type"

    def test_an_unparseable_message_still_counts_as_a_rejection(self):
        c = tool_calls([_mcp("refine", {},
                             text="Input validation error: something new")])[0]
        assert c["ok"] is False
        assert c["schema_error"]["param"] is None
        assert c["schema_error"]["kind"] == "invalid_arguments"

    def test_a_runtime_failure_is_not_a_schema_error(self):
        c = tool_calls([_mcp("run_shelxt", ok=False,
                             error="shelxt timed out")])[0]
        assert c["ok"] is False and c["schema_error"] is None

    def test_a_tool_that_merely_talks_about_validation_is_not_rejected(self):
        # a successful result whose own json mentions the phrase: the
        # marker is only trusted on a bare, non-json envelope
        c = tool_calls([_mcp("validate_structure", {}, text=json.dumps(
            {"ok": True,
             "summary": {"note": "Input validation error seen upstream"}}))
        ])[0]
        assert c["ok"] is True and c["schema_error"] is None

    def test_analyse_case_counts_them_as_their_own_category(self, tmp_path):
        logs = tmp_path / "logs"
        logs.mkdir()
        recs = [_mcp("compare_nodes", {"nodes": ["n1", "n2"]},
                     text="Input validation error: 'a' is a required "
                          "property"),
                _mcp("compare_nodes", {"node_a": "n1", "node_b": "n2"},
                     text="Input validation error: 'a' is a required "
                          "property"),
                _mcp("run_shelxt", ok=False, error="shelxt timed out",
                     secs=180),
                _mcp("refine", {"cycles": 5})]
        logs.joinpath("rollout.jsonl").write_text(
            "\n".join(json.dumps(r) for r in recs), encoding="utf-8")
        out = analyse_case(logs)
        assert out["n_schema_errors"] == 2
        assert {e["tool"] for e in out["schema_errors"]} == {"compare_nodes"}
        assert out["schema_errors"][0]["param"] == "a"
        # a rejected call IS a failed call: 2 rejections + 1 timeout
        assert out["n_tool_errors"] == 3
        assert out["tools"]["compare_nodes"]["schema_errors"] == 2
        assert out["tools"]["compare_nodes"]["error_rate"] == 1.0
        assert out["tools"]["run_shelxt"]["schema_errors"] == 0


# ----------------------------------------------------- server watchdog
class TestAbandonedTools:
    def test_exit_abandoning_tool_lines_are_reported(self, tmp_path):
        p = tmp_path / "mcp_server.jsonl"
        p.write_text("\n".join(json.dumps(x) for x in [
            # older bundles have startup lines with no event key at all
            {"ts": "2026-09-03T15:55:22", "pid": 58768, "mode": "tools_only"},
            {"ts": "2026-09-03T15:55:30", "pid": 46212, "event": "startup"},
            {"ts": "2026-09-03T17:55:30", "pid": 46212,
             "event": "transport_closed", "running_tool": None,
             "action": "exit_idle"},
            {"ts": "2026-09-03T17:56:30", "pid": 46212,
             "event": "transport_closed",
             "running_tool": "solve_charge_flipping", "elapsed_s": 3142.0,
             "budget_s": 900.0, "waited_s": 60.0,
             "action": "exit_abandoning_tool"},
        ]), encoding="utf-8")
        log = read_server_log(p)
        assert [r["event"] for r in log] == [
            "startup", "startup", "transport_closed", "transport_closed"]
        assert find_abandoned_tools(log) == [
            {"tool": "solve_charge_flipping", "elapsed_s": 3142.0,
             "budget_s": 900.0}]

    def test_a_missing_server_log_is_not_an_error(self, tmp_path):
        assert read_server_log(tmp_path / "nope.jsonl") == []
        assert find_abandoned_tools([]) == []

    def test_analyse_case_exposes_them(self, tmp_path):
        logs = tmp_path / "logs"
        logs.mkdir()
        logs.joinpath("rollout.jsonl").write_text(
            json.dumps(_mcp("refine")), encoding="utf-8")
        logs.joinpath("mcp_server.jsonl").write_text(json.dumps(
            {"ts": "2026-09-03T17:56:30", "pid": 1, "event":
             "transport_closed", "running_tool": "run_shelxl",
             "elapsed_s": 3142.0, "budget_s": 900.0,
             "action": "exit_abandoning_tool"}), encoding="utf-8")
        out = analyse_case(logs)
        assert out["server_abandoned_tools"] == [
            {"tool": "run_shelxl", "elapsed_s": 3142.0, "budget_s": 900.0}]

    def test_a_bundle_without_a_server_log_reports_an_empty_list(self,
                                                                tmp_path):
        logs = tmp_path / "logs"
        logs.mkdir()
        logs.joinpath("rollout.jsonl").write_text(
            json.dumps(_mcp("refine")), encoding="utf-8")
        assert analyse_case(logs)["server_abandoned_tools"] == []


# ------------------------------------------------------ protocol refusals
class TestExpectedRefusals:
    """reg1-ext2: every case's first finalize_delivery was refused by design
    (WP5: refuse, agent waives with reasons, second call seals) and the five
    refusals topped the tool-usability table as errors."""

    def _logs(self, tmp_path):
        logs = tmp_path / "logs"
        logs.mkdir()
        recs = [
            _mcp("finalize_delivery", {"output_dir": "CrystalPilot Results/t"},
                 ok=False, error="NOT finalized: H:/x/CrystalPilot Results/t "
                                 "blocking items: alert:183_A ...", at=0),
            _mcp("finalize_delivery", {"output_dir": "CrystalPilot Results/t",
                                       "waivers": [{"item": "alert:183_A"}]},
                 at=30),
            _mcp("view_structure", {"view": "a"}, ok=False,
                 error="unknown parameter(s) ['view'] for 'view_structure'",
                 at=60),
        ]
        logs.joinpath("rollout.jsonl").write_text(
            "\n".join(json.dumps(r) for r in recs) + "\n", encoding="utf-8")
        return logs

    def test_the_first_refusal_is_not_an_error(self, tmp_path):
        out = analyse_case(self._logs(tmp_path))
        assert out["n_tool_errors"] == 1                  # view_structure only
        assert out["n_expected_refusals"] == 1
        assert out["expected_refusals"][0]["tool"] == "finalize_delivery"
        fd = out["tools"]["finalize_delivery"]
        assert fd["calls"] == 2 and fd["errors"] == 0
        assert fd["expected_refusals"] == 1 and fd["error_rate"] == 0.0
        assert [f["tool"] for f in out["failures"]] == ["view_structure"]

    def test_a_real_finalize_failure_still_counts(self, tmp_path):
        logs = tmp_path / "logs"
        logs.mkdir()
        logs.joinpath("rollout.jsonl").write_text(json.dumps(_mcp(
            "finalize_delivery", {"output_dir": "nope"}, ok=False,
            error="no such delivery directory: nope")) + "\n",
            encoding="utf-8")
        out = analyse_case(logs)
        assert out["n_tool_errors"] == 1 and out["n_expected_refusals"] == 0
