"""Process-audit T6: the checkCIF chain - strict unknown-parameter
refusal at the dispatcher, alert slimming for the wire, run-to-run
delta, and the delivery-directory scaffold."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


def _ctx():
    ev = SimpleNamespace(event_id="e1")
    store = SimpleNamespace(emit=lambda *a, **k: ev)
    return SimpleNamespace(store=store, trajectory_id=None)


class TestUnknownParamsRefused:
    """r15 live case: run_checkcif(cif_path=...) silently validated the
    wrong target and produced bogus A alerts. Unknown keys now fail the
    call before the tool runs - for EVERY tool."""

    @staticmethod
    def _registry():
        from crystalpilot.tools.base import Tool, ToolRegistry, ToolResult

        class Probe(Tool):
            name = "probe"
            description = "x"
            params_schema = {"type": "object",
                            "properties": {"cif": {"type": "string"}}}

            def __init__(self):
                self.ran = False

            def run(self, ctx, **params):
                self.ran = True
                return ToolResult(ok=True, summary={"got": params})

        reg = ToolRegistry()
        probe = Probe()
        reg.register(probe)
        return reg, probe

    def test_unknown_key_fails_without_running(self):
        from crystalpilot.tools.base import invoke
        reg, probe = self._registry()
        r = invoke(reg, _ctx(), "probe", {"cif_path": "x.cif"})
        assert not r.ok and not probe.ran
        assert "cif_path" in r.error and "'cif'" in r.error
        assert "nothing was run" in r.error

    def test_known_keys_pass(self):
        from crystalpilot.tools.base import invoke
        reg, probe = self._registry()
        r = invoke(reg, _ctx(), "probe", {"cif": "a.cif"})
        assert r.ok and probe.ran

    def test_every_registered_tool_param_use_matches_schema(self):
        """Meta-guard: no registered tool may read a params key its own
        schema does not declare (the dispatcher would now refuse it)."""
        import re
        import inspect
        seen = []
        from crystalpilot.tools.base import Tool

        def _walk(cls):
            for sub in cls.__subclasses__():
                seen.append(sub)
                _walk(sub)
        # import the tool modules so subclasses exist (tools_extra pulls
        # in every refine-side tool module transitively)
        import crystalpilot.refine.tools_analysis  # noqa: F401
        import crystalpilot.refine.tools_deliver  # noqa: F401
        import crystalpilot.refine.tools_extra  # noqa: F401
        import crystalpilot.refine.tools_frames  # noqa: F401
        import crystalpilot.refine.tools_shelxl  # noqa: F401
        _walk(Tool)
        bad = []
        for cls in seen:
            schema = getattr(cls, "params_schema", None) or {}
            props = set(schema.get("properties", {}))
            try:
                src = inspect.getsource(cls.run)
            except (OSError, TypeError):
                continue
            used = set(re.findall(
                r"(?<![\w.])params\.get\(\s*[\"']([a-z_0-9]+)[\"']", src))
            used |= set(re.findall(
                r"(?<![\w.])params\[\s*[\"']([a-z_0-9]+)[\"']\s*\]", src))
            used = {u for u in used if not u.startswith("_")}
            extra = used - props
            if extra:
                bad.append(f"{cls.__name__}: {sorted(extra)}")
        assert not bad, ("tools reading undeclared params (dispatcher now "
                         "refuses them): " + "; ".join(bad))


class TestSlimAlerts:
    def test_levels_trimmed_appropriately(self):
        from crystalpilot.refine.tools_deliver import _slim_alerts
        alerts = [
            {"code": "041", "type": 1, "level": "A", "text": "bad",
             "kb": {"meaning": "m"}},
            {"code": "220", "type": 2, "level": "C", "text": "x" * 200,
             "kb": {"meaning": "dropped"}},
            {"code": "910", "type": 3, "level": "G", "text": "g1"},
            {"code": "910", "type": 3, "level": "G", "text": "g2"},
            {"code": "912", "type": 3, "level": "G", "text": "g3"},
        ]
        out = _slim_alerts(alerts)
        a = next(x for x in out if x["level"] == "A")
        assert a.get("kb")                       # A keeps the annotation
        c = next(x for x in out if x["level"] == "C")
        assert "kb" not in c and len(c["text"]) == 90
        gs = {x["code"]: x["count"] for x in out if x["level"] == "G"}
        assert gs == {"910": 2, "912": 1}


class TestCheckcifDelta:
    @staticmethod
    def _job(root: Path, name: str, target: str, codes):
        j = root / name
        j.mkdir(parents=True)
        (j / "checkcif.json").write_text(json.dumps({
            "target": target,
            "alerts": [{"code": c, "level": lv} for c, lv in codes],
        }), encoding="utf-8")
        return j

    def test_new_resolved_and_kind_filter(self, tmp_path):
        from crystalpilot.refine.tools_deliver import _checkcif_delta
        self._job(tmp_path, "job_1", "node:n0001",
                  [("041", "A"), ("220", "C")])
        self._job(tmp_path, "job_2", "publication:final.cif",
                  [("999", "A")])          # other kind: must be skipped
        cur_job = tmp_path / "job_3"
        cur_job.mkdir()
        cur = [{"code": "041", "level": "A"}, {"code": "306", "level": "B"}]
        d = _checkcif_delta(cur_job, cur, "node")
        assert d["vs"] == "job_1"
        assert d["new"] == ["306(B)"] and d["resolved"] == ["220(C)"]

    def test_no_previous_run_gives_none(self, tmp_path):
        from crystalpilot.refine.tools_deliver import _checkcif_delta
        cur_job = tmp_path / "job_1"
        cur_job.mkdir()
        assert _checkcif_delta(cur_job, [], "node") is None

    def test_level_change_reported(self, tmp_path):
        from crystalpilot.refine.tools_deliver import _checkcif_delta
        self._job(tmp_path, "job_1", "node:n1", [("041", "B")])
        cur_job = tmp_path / "job_2"
        cur_job.mkdir()
        d = _checkcif_delta(cur_job, [{"code": "041", "level": "A"}], "node")
        assert d["level_changed"] == ["041 B->A"]


class TestAlertsScaffold:
    def test_sections_kb_and_slots(self):
        from crystalpilot.refine.tools_deliver import _alerts_scaffold
        alerts = [
            {"code": "041", "type": 1, "level": "A", "text": "calc density",
             "kb": {"meaning": "m1", "causes": "c1", "remedy": "r1"}},
            {"code": "220", "type": 2, "level": "C", "text": "large ueq"},
            {"code": "910", "type": 3, "level": "G", "text": "note"},
            {"code": "910", "type": 3, "level": "G", "text": "note"},
        ]
        report = {"target": "publication:final.cif",
                  "counts": {"A": 1, "B": 0, "C": 1, "G": 2}}
        md = _alerts_scaffold(report, alerts,
                              {"vs": "job_0", "new": ["041(A)"],
                               "resolved": []})
        assert "## A alerts" in md and "041_ALERT_1_A" in md
        assert "- meaning: m1" in md and "- remedy: r1" in md
        assert md.count("- explanation:") == 2      # one per A/B/C alert
        assert "910 x2" in md
        assert "delta vs job_0" in md
