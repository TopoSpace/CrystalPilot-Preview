"""Unit tests for the campaign runner's reporting layer.

Campaign.__init__ resolves paths against the real repo, so tests build the
object via __new__ and inject only what report() touches.
"""
import json

from crystalpilot.benchmark.agent_campaign import (
    Campaign, CaseRun, harvest_after_interrupt)


def _mk_campaign(tmp_path, state, grades):
    c = Campaign.__new__(Campaign)
    c.name = "t"
    c.cases = [{"name": n} for n in state]
    c.work = tmp_path
    c.state_path = tmp_path / "state.json"
    c.state = state
    for name, grade in grades.items():
        d = tmp_path / name
        d.mkdir()
        (d / "grade.json").write_text(
            json.dumps({"grade": grade}), encoding="utf-8")
    c.state_path.write_text(json.dumps(state), encoding="utf-8")
    return c


def test_report_grade_column_and_distribution_share_source(tmp_path):
    """r11 real bug: table column read grade.json while the distribution
    line read state.json; after an out-of-band re-grade they disagreed
    (publication vs below_bar) in the same report."""
    c = _mk_campaign(
        tmp_path,
        state={"case-x": {"status": "graded", "grade": "below_bar"}},
        grades={"case-x": "publication"})
    c.report()
    rep = (tmp_path / "CAMPAIGN_REPORT.md").read_text(encoding="utf-8")
    assert "publication" in rep
    assert "below_bar" not in rep


def test_report_heals_stale_state_label(tmp_path):
    c = _mk_campaign(
        tmp_path,
        state={"case-x": {"status": "graded", "grade": "below_bar"}},
        grades={"case-x": "publication"})
    c.report()
    on_disk = json.loads(c.state_path.read_text(encoding="utf-8"))
    assert on_disk["case-x"]["grade"] == "publication"


def test_report_no_grade_json_leaves_state_alone(tmp_path):
    state = {"case-y": {"status": "sent"}}
    c = _mk_campaign(tmp_path, state=state, grades={})
    before = c.state_path.read_text(encoding="utf-8")
    c.report()
    assert c.state_path.read_text(encoding="utf-8") == before
    rep = (tmp_path / "CAMPAIGN_REPORT.md").read_text(encoding="utf-8")
    assert "case-y" in rep


# ------------------------------------------------------- open_project accounting
class _Api:
    def __init__(self, project_dir, mode):
        self.calls = []
        self.project_dir = project_dir
        self.mode = mode

    def post(self, path, body):
        self.calls.append((path, body))
        if path == "/projects/settings":
            # the server rewrites AGENTS.md for the requested mode
            from crystalpilot.workbench.agents_md import ensure_agents_md
            ensure_agents_md(self.project_dir,
                             (body.get("settings") or {}).get("knowledge_mode"))
            return {"model": "m", "effort": "xhigh",
                    "knowledge_mode": self.mode}
        return {}


def _case_run(tmp_path, case, defaults):
    from crystalpilot.benchmark.agent_campaign import CaseRun
    c = Campaign.__new__(Campaign)
    c.name = "ka-test"
    c.defaults = defaults
    c.state = {}
    c.save_state = lambda: None
    r = object.__new__(CaseRun)
    r.c = c
    r.case = case
    r.name = case["name"]
    r.project_dir = tmp_path / "proj"
    # make tmp_path its own toplevel: pytest's basetemp lives inside the
    # engine repo, whose root AGENTS.md pointer would otherwise be counted
    (tmp_path / ".git").mkdir(exist_ok=True)
    return r, c


def test_open_project_sends_knowledge_mode_and_records_template(tmp_path):
    """ka1: the arm reaches the server as a project setting and the state
    records the template the agent actually saw (marker + content hash +
    what else codex injects). Both must survive a --regrade months later."""
    data = tmp_path / "data"
    data.mkdir()
    r, c = _case_run(tmp_path,
                     {"name": "x-tools-r1", "data_dir": str(data),
                      "knowledge_mode": "tools_only"},
                     {"permission_mode": "auto", "model_override": "m"})
    c.api = _Api(r.project_dir, "tools_only")
    r.open_project()
    settings = [b for p, b in c.api.calls if p == "/projects/settings"][0]
    assert settings["settings"]["knowledge_mode"] == "tools_only"
    assert settings["settings"]["model_override"] == "m"
    st = c.state["x-tools-r1"]
    assert st["status"] == "opened"
    assert st["knowledge_mode"] == "tools_only"
    assert st["agents_version"].startswith("<!-- crystalpilot-agents-tools")
    assert st["agents_matches_template"] is True
    assert st["root_agents_sha256"] is None      # own toplevel, no root file
    assert len(st["agents_chain"]) == 1


def test_open_project_default_arm_is_full(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    r, c = _case_run(tmp_path, {"name": "x-full-r1", "data_dir": str(data)},
                     {"permission_mode": "auto"})
    c.api = _Api(r.project_dir, "full")
    r.open_project()
    settings = [b for p, b in c.api.calls if p == "/projects/settings"][0]
    assert "settings" not in settings          # nothing to override
    st = c.state["x-full-r1"]
    assert st["knowledge_mode"] == "full"
    from crystalpilot.workbench.agents_md import VERSION_MARKER
    assert st["agents_version"] == VERSION_MARKER      # the live full-arm marker


# ------------------------------------------------- interrupted final turn
def _delivery(project_dir, task="task_20260903_155519", *, cif=True,
              verdict=None, extra=()):
    """A project directory as the agent would have left it."""
    d = project_dir / "CrystalPilot Results" / task
    d.mkdir(parents=True, exist_ok=True)
    if cif:
        (d / "final.cif").write_text("data_x\n", encoding="utf-8")
        (d / "final.fcf").write_text("data_x\n", encoding="utf-8")
    if verdict is not None:
        (d / "verdict.json").write_text(
            json.dumps(verdict, ensure_ascii=False), encoding="utf-8")
    for name in extra:
        (d / name).write_text("x", encoding="utf-8")
    return d


def _grading_case(tmp_path, monkeypatch, state, graded):
    """A CaseRun wired for grade() with a canned grader result."""
    from crystalpilot.benchmark import grade as grade_mod
    c = Campaign.__new__(Campaign)
    c.name = "ka1-org"
    c.state = {"org-tools-r1": dict(state)}
    c.save_state = lambda: None
    r = object.__new__(CaseRun)
    r.c = c
    r.case = {"name": "org-tools-r1"}
    r.name = "org-tools-r1"
    r.project_dir = tmp_path / "proj"
    r.project_dir.mkdir(parents=True, exist_ok=True)
    r.out_dir = tmp_path / "out"
    r.out_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(grade_mod, "grade_delivery",
                        lambda *a, **k: dict(graded))
    return r


class TestHarvestAfterInterrupt:
    def test_it_finds_the_verdict_the_agent_wrote_itself(self, tmp_path):
        proj = tmp_path / "p"
        _delivery(proj, "task_A", verdict={"solved": True, "r1": 0.0412},
                  extra=("SUMMARY.md",))
        h = harvest_after_interrupt(proj, "task_A")
        assert h["verdict"] == {"solved": True, "r1": 0.0412}
        assert h["verdict_path"].endswith("verdict.json")
        assert h["task_dir"].endswith("task_A")
        assert set(h["products"]) == {"final.cif", "final.fcf",
                                      "SUMMARY.md", "verdict.json"}
        assert h["final_cif"].endswith("final.cif")

    def test_the_runs_own_task_dir_wins_over_a_newer_one(self, tmp_path):
        proj = tmp_path / "p"
        _delivery(proj, "task_OLD", cif=False, verdict={"mine": True})
        _delivery(proj, "task_NEW", cif=False, verdict={"someone": "else"})
        assert harvest_after_interrupt(proj, "task_OLD")["verdict"] == {
            "mine": True}

    def test_nothing_delivered_is_reported_as_nothing(self, tmp_path):
        proj = tmp_path / "p"
        proj.mkdir()
        assert harvest_after_interrupt(proj, "task_A") == {
            "verdict": None, "verdict_path": None, "task_dir": None,
            "products": [], "final_cif": None}

    def test_a_started_but_empty_task_dir_is_visible(self, tmp_path):
        # the real ka1 org-tools_only shape: a task dir holding only the
        # workbench transcript, no products at all
        proj = tmp_path / "p"
        _delivery(proj, "task_A", cif=False, extra=("transcript.jsonl",))
        h = harvest_after_interrupt(proj, "task_A")
        assert h["products"] == ["transcript.jsonl"]
        assert h["final_cif"] is None and h["verdict"] is None


class TestGradeAfterInterrupt:
    def test_no_delivery_gets_the_interrupted_reason(self, tmp_path,
                                                     monkeypatch):
        """ka1 org-tools_only: the campaign timeout hit mid-turn, nothing
        was delivered, and the case was then indistinguishable from one
        where the agent simply produced nothing."""
        r = _grading_case(
            tmp_path, monkeypatch,
            {"status": "done", "turn_status": "timeout",
             "task_id": "task_A",
             "agent_text": "状态无变化：原求解仍在运行，没有新节点或错误。"},
            {"grade": "no_delivery"})
        out = r.grade()
        assert out["interrupted"] is True
        assert out["interrupt_turn_status"] == "timeout"
        assert out["no_delivery_reason"] == "interrupted_before_verdict"
        assert any("interrupted_before_verdict" in s
                   for s in out["grade_reasons"])
        # nothing invented: the harvest says the project was empty
        assert out["interrupt_harvest"]["final_cif"] is None
        assert out["interrupt_harvest"]["products"] == []
        # the last thing the agent said is kept, and is NOT called a verdict
        assert out["verdict_source"] == "final_turn_unparsed"
        assert out["interrupt_harvest"]["last_agent_text"].startswith("状态")
        on_disk = json.loads((r.out_dir / "grade.json").read_text(
            encoding="utf-8"))
        assert on_disk["no_delivery_reason"] == "interrupted_before_verdict"
        assert r.c.state["org-tools-r1"]["status"] == "graded"

    def test_a_verdict_written_to_disk_is_harvested(self, tmp_path,
                                                    monkeypatch):
        r = _grading_case(
            tmp_path, monkeypatch,
            {"status": "done", "turn_status": "timeout", "task_id": "task_A",
             "agent_text": "还在跑，稍等。"},
            {"grade": "acceptable",
             "self_consistency": {"cif": {"r1_gt": 0.0412}}})
        _delivery(r.project_dir, "task_A",
                  verdict={"solved": True, "r1": 0.0412, "delivered": True})
        out = r.grade()
        assert out["verdict_source"] == "harvested_after_interrupt"
        assert out["verdict"]["r1"] == 0.0412
        # the honesty gate still runs on a harvested verdict
        assert out["verdict_matches_cif"] is True
        assert "no_delivery_reason" not in out
        assert json.loads((r.out_dir / "verdict.json").read_text(
            encoding="utf-8"))["solved"] is True
        assert (r.c.state["org-tools-r1"]["verdict_source"]
                == "harvested_after_interrupt")

    def test_a_delivered_cif_is_graded_even_though_the_turn_was_cut(
            self, tmp_path, monkeypatch):
        r = _grading_case(
            tmp_path, monkeypatch,
            {"status": "done", "turn_status": "timeout", "task_id": "task_A"},
            {"grade": "acceptable"})
        _delivery(r.project_dir, "task_A")
        out = r.grade()
        assert out["grade"] == "acceptable"      # graded from the CIF
        assert out["interrupted"] is True
        assert "no_delivery_reason" not in out
        assert out["interrupt_harvest"]["final_cif"].endswith("final.cif")
        assert out["verdict_source"] is None     # none existed, none claimed

    def test_a_normal_turn_is_untouched(self, tmp_path, monkeypatch):
        r = _grading_case(
            tmp_path, monkeypatch,
            {"status": "done", "turn_status": "completed",
             "agent_text": json.dumps({"solved": True, "r1": 0.03})},
            {"grade": "no_delivery"})
        out = r.grade()
        assert out["verdict_source"] == "final_turn"
        assert "interrupted" not in out
        assert "interrupt_harvest" not in out
        assert "no_delivery_reason" not in out   # not an interrupted case


class TestRunTailAfterInterrupt:
    def test_a_refused_verdict_turn_never_costs_the_harvest(self, tmp_path,
                                                            monkeypatch):
        """After the interrupt the thread may refuse the steer. That must
        not take the log bundle and the grade down with it."""
        r = _grading_case(
            tmp_path, monkeypatch,
            {"status": "sent", "thread_id": "t1", "task_id": "task_A"},
            {"grade": "no_delivery"})
        waits: list = []
        r.wait_turn = lambda tid, deadline_s=None, **kw: (
            waits.append(deadline_s)
            or {"status": "timeout", "usage": {}, "agent_text": ""})

        def _refuse(*a, **k):
            raise RuntimeError("409 thread busy")
        r.send = _refuse
        r.open_project = lambda: None
        collected: list = []
        r.collect_logs = lambda tid: collected.append(tid)
        r.run()
        st = r.c.state["org-tools-r1"]
        assert st["interrupted"] is True
        assert "409" in st["post_interrupt_error"]
        assert collected == ["t1"]               # bundle still frozen
        assert st["status"] == "graded"          # and the case still graded
        assert waits == [None]        # only the main turn, on its own budget

    def test_the_tail_turns_are_short_leashed_after_an_interrupt(
            self, tmp_path, monkeypatch):
        from crystalpilot.benchmark.agent_campaign import INTERRUPT_TAIL_S
        r = _grading_case(
            tmp_path, monkeypatch,
            {"status": "sent", "thread_id": "t1", "task_id": "task_A"},
            {"grade": "no_delivery"})
        waits: list = []
        r.wait_turn = lambda tid, deadline_s=None, **kw: (
            waits.append(deadline_s)
            or {"status": "timeout" if len(waits) == 1 else "completed",
                "usage": {}, "agent_text": ""})
        r.send = lambda *a, **k: "t1"
        r.open_project = lambda: None
        r.collect_logs = lambda tid: None
        r.run()
        # main turn on the case budget, verdict turn on the short leash: a
        # case that has already spent 7200 s must not be able to spend
        # another one asking for a verdict
        assert waits == [None, INTERRUPT_TAIL_S]


# ------------------------------------------------------- lane anonymisation
from pathlib import Path  # noqa: E402 - appended section


def _manifest(tmp_path, name, root, anonymize_lane=True):
    import json
    m = {"campaign": name, "server": "http://127.0.0.1:1/api",
         "projects_root": str(root),
         "defaults": {"anonymize_projects": True,
                      "anonymize_lane": anonymize_lane},
         "cases": [{"name": "x-full-r1", "data_dir": str(tmp_path),
                    "brief": "b"}]}
    p = tmp_path / f"{name}.json"
    p.write_text(json.dumps(m), encoding="utf-8")
    return p


def test_anonymize_lane_keeps_the_campaign_name_out_of_the_agents_path(
        tmp_path, monkeypatch):
    """reg2-mof (2026-09-04): the project folder was anonymised but its
    parent `.../reg2-mof/` told the agent it was solving a MOF."""
    import crystalpilot.benchmark.agent_campaign as ac
    monkeypatch.setattr(ac, "REPO", tmp_path)
    root = tmp_path / "lanes" / "reg9-mof"
    c = ac.Campaign(_manifest(tmp_path, "reg9-mof", root))
    anon = ac.anonymous_lane_dir(root, "reg9-mof")
    assert Path(c.projects_root) == anon
    assert anon.parent == root.parent
    assert "mof" not in anon.name and anon.name.startswith("l")
    assert ac.anonymous_lane_dir(root, "reg9-mof") == anon     # stable
    run = ac.CaseRun(c, c.cases[0])
    assert run.project_dir.parent == anon
    assert "mof" not in str(run.project_dir).split("lanes")[1]


def test_anonymize_lane_still_finds_a_lane_that_ran_under_its_plain_name(
        tmp_path, monkeypatch):
    import crystalpilot.benchmark.agent_campaign as ac
    monkeypatch.setattr(ac, "REPO", tmp_path)
    root = tmp_path / "lanes" / "reg1-old"
    root.mkdir(parents=True)                       # the old lane exists
    c = ac.Campaign(_manifest(tmp_path, "reg1-old", root))
    assert Path(c.projects_root) == root           # --regrade lands there


def test_without_anonymize_lane_the_root_is_untouched(tmp_path, monkeypatch):
    import crystalpilot.benchmark.agent_campaign as ac
    monkeypatch.setattr(ac, "REPO", tmp_path)
    root = tmp_path / "lanes" / "plain"
    c = ac.Campaign(_manifest(tmp_path, "plain", root, anonymize_lane=False))
    assert Path(c.projects_root) == root


# ------------------------------------------- transient stream-error retry
class _NoLogger:
    def __init__(self):
        self.events: list = []

    def sse(self, seq, ev):
        self.events.append(ev)


class TestTransientStreamRetry:
    ERR = ("stream disconnected before completion: stream closed before "
           "response.completed")

    def _case(self, tmp_path, monkeypatch, outcomes):
        from crystalpilot.benchmark import agent_campaign as ac
        monkeypatch.setattr(ac, "STREAM_RETRY_WAIT_S", 0.0)
        r = _grading_case(
            tmp_path, monkeypatch,
            {"status": "sent", "thread_id": "t1", "task_id": "task_A"},
            {"grade": "no_delivery"})
        r.logger = _NoLogger()
        sent: list = []
        r.send = lambda msg, first=False, with_schema=False: (
            sent.append((msg, first, with_schema)) or "t1")
        r.open_project = lambda: None
        r.collect_logs = lambda tid: None
        queue = list(outcomes)
        r.wait_turn = lambda tid, deadline_s=None, **kw: dict(
            queue.pop(0) if queue else {"status": "completed"},
            usage={}, agent_text="")
        return r, sent

    def test_transient_failure_is_resent_on_the_same_thread(self, tmp_path,
                                                            monkeypatch):
        from crystalpilot.benchmark.agent_campaign import (
            CONTINUE_AFTER_STREAM_ERROR, is_transient_turn_error)
        assert is_transient_turn_error(self.ERR)
        assert not is_transient_turn_error("tool 'refine' raised ValueError")
        assert not is_transient_turn_error(None)
        r, sent = self._case(tmp_path, monkeypatch, [
            {"status": "failed", "error": self.ERR},     # working turn dies
            {"status": "completed"},                     # the resend works
            {"status": "completed"},                     # verdict turn
        ])
        r.run()
        st = r.c.state["org-tools-r1"]
        assert st["stream_retries"] == 1
        assert self.ERR[:40] in st["last_stream_error"]
        assert st["turn_status"] == "completed" and st["interrupted"] is False
        # one continue (not schema-constrained) then the verdict turn
        assert [s[0] for s in sent][0] == CONTINUE_AFTER_STREAM_ERROR
        assert sent[0][1] is False and sent[0][2] is False
        assert sent[-1][2] is True                     # verdict with schema
        assert [e["kind"] for e in r.logger.events] == ["runner_retry"]
        assert st["status"] == "graded"

    def test_retries_are_bounded_and_non_transient_errors_are_not_retried(
            self, tmp_path, monkeypatch):
        from crystalpilot.benchmark.agent_campaign import STREAM_RETRIES
        r, sent = self._case(tmp_path, monkeypatch, [
            {"status": "failed", "error": self.ERR}] * (STREAM_RETRIES + 3))
        r.run()
        st = r.c.state["org-tools-r1"]
        # per turn STREAM_RETRIES, reported cumulatively per case
        assert st["stream_retries"] == STREAM_RETRIES * 2
        assert st["turn_status"] == "failed"
        # the verdict turn also gets its own bounded retries
        n_continue = sum(1 for s in sent if s[0].startswith("运行提示：上一轮因模型流中断"))
        assert n_continue == STREAM_RETRIES * 2
        r2, sent2 = self._case(tmp_path, monkeypatch, [
            {"status": "failed", "error": "tool 'refine' raised ValueError"},
            {"status": "completed"},
        ])
        r2.c.state["org-tools-r1"].pop("stream_retries", None)
        r2.run()
        assert "stream_retries" not in r2.c.state["org-tools-r1"]
        assert all(not s[0].startswith("运行提示：上一轮因模型流中断") for s in sent2)
