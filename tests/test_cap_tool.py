"""reduce_with_crysalis: the agent-facing surface over the verified
CrysAlisPro LISTEN-MODE chain (io/crysalis_cap).

Everything here runs against a fake listen channel - no vendor process.
What is being tested is the surface, not the chain: fail fast with
instructions when the channel is down, refuse to silently reduce inside
somebody's finished structure, and hand a wedged dialog back as an
actionable message instead of a timeout.
"""
import json
from pathlib import Path

import pytest

from crystalpilot.refine import tools_cap as tc


class _Ctx:
    session = None

    def __init__(self):
        self.pings: list[str] = []

    def progress(self, line):
        self.pings.append(line)


def _tool(tmp_path):
    class _Proj:
        dir = tmp_path
    t = object.__new__(tc.ReduceWithCrysalis)
    t.project = _Proj()
    return t


def _res(n: int) -> str:
    return ("TITL solved\nCELL 0.71073 10 10 10 90 90 90\nLATT -1\n"
            "SFAC C\nUNIT 1\n"
            + "".join(f"C{i}    1  0.1{i:03d}  0.2  0.3  11.0  0.02\n"
                      for i in range(n))
            + "HKLF 4\nEND\n")


@pytest.fixture()
def exp(tmp_path):
    d = tmp_path / "exp"
    d.mkdir()
    par = d / "pg33.par"
    par.write_text("", encoding="utf-8")
    (d / "pg33.run").write_text("", encoding="utf-8")
    return par


class TestAnswerScan:
    def test_solved_res_and_cif_found(self, tmp_path):
        d = tmp_path / "e"
        (d / "sub").mkdir(parents=True)
        (d / "final.res").write_text(_res(20), encoding="utf-8")
        (d / "sub" / "x.cif").write_text(
            "data_x\n_atom_site_fract_x\n0.1\n", encoding="utf-8")
        assert tc.scan_for_answers(d) == ["final.res", "x.cif"]

    def test_data_only_experiment_is_clean(self, tmp_path):
        d = tmp_path / "e"
        d.mkdir()
        (d / "pg33.par").write_text("x", encoding="utf-8")
        (d / "pg33_autored.hkl").write_text("   1   0   0  1.0 0.1\n" * 20,
                                            encoding="utf-8")
        (d / "pg33.cif_od").write_text("_diffrn_source 'x'\n",
                                       encoding="utf-8")
        assert tc.scan_for_answers(d) == []


class TestGuards:
    def test_missing_par_reported(self, tmp_path):
        r = _tool(tmp_path).run(_Ctx(), exp_par=str(tmp_path / "nope.par"))
        assert not r.ok and "no such experiment" in r.error

    def test_frames_folder_gets_pointed_at_dials(self, tmp_path, exp):
        wrong = exp.parent / "pg33.run"
        r = _tool(tmp_path).run(_Ctx(), exp_par=str(wrong))
        assert not r.ok
        assert "import_frames" in r.error

    def test_dead_channel_fails_fast_with_the_alternative(self, tmp_path,
                                                          exp, monkeypatch):
        monkeypatch.setattr(
            "crystalpilot.io.crysalis_listen.ListenModeClient.channel_alive",
            lambda self: False)
        r = _tool(tmp_path).run(_Ctx(), exp_par=str(exp))
        assert not r.ok
        # must say what to do instead, not just that it failed
        assert "LISTEN" in r.error and "import_frames" in r.error

    def test_existing_solution_needs_acknowledgement(self, tmp_path, exp,
                                                     monkeypatch):
        monkeypatch.setattr(
            "crystalpilot.io.crysalis_listen.ListenModeClient.channel_alive",
            lambda self: True)
        (exp.parent / "author.res").write_text(_res(30), encoding="utf-8")
        r = _tool(tmp_path).run(_Ctx(), exp_par=str(exp))
        assert not r.ok
        assert "author.res" in r.error and "independent" in r.error

    def test_acknowledged_run_proceeds_and_discloses(self, tmp_path, exp,
                                                     monkeypatch):
        monkeypatch.setattr(
            "crystalpilot.io.crysalis_listen.ListenModeClient.channel_alive",
            lambda self: True)
        (exp.parent / "author.res").write_text(_res(30), encoding="utf-8")
        monkeypatch.setattr(tc, "cap_reduce", None, raising=False)
        monkeypatch.setattr(
            "crystalpilot.io.crysalis_cap.cap_reduce",
            lambda par, client=None, progress=None: {
                "ok": True, "steps": [], "hkl": str(exp.parent / "a.hkl"),
                "n_hkl_rows": 42})
        r = _tool(tmp_path).run(_Ctx(), exp_par=str(exp),
                                acknowledge_existing_model=True)
        assert r.ok, r.error
        assert r.summary["existing_model_in_directory"] == ["author.res"]
        assert "independence_note" in r.summary


class TestChainSurface:
    def _wire(self, monkeypatch, result):
        monkeypatch.setattr(
            "crystalpilot.io.crysalis_listen.ListenModeClient.channel_alive",
            lambda self: True)
        monkeypatch.setattr("crystalpilot.io.crysalis_cap.cap_reduce",
                            result)

    def test_success_reports_steps_and_points_at_ingest(self, tmp_path, exp,
                                                        monkeypatch):
        from crystalpilot.io.crysalis_cap import StepResult
        steps = [StepResult("peaks", "ph snogui", "done", 40.2, "",
                            ["99999 peak locations are merged to 40676 "
                             "profiles"]),
                 StepResult("index", "um twinttt", "done", 2.1, "",
                            ["Best cell: 18538 indexed"])]
        self._wire(monkeypatch, lambda par, client=None, progress=None: {
            "ok": True, "steps": steps,
            "hkl": str(exp.parent / "pg33_autored.hkl"),
            "n_hkl_rows": 108377})
        ctx = _Ctx()
        r = _tool(tmp_path).run(ctx, exp_par=str(exp))
        assert r.ok, r.error
        assert r.summary["n_hkl_rows"] == 108377
        assert r.summary["no_state_change"] is True
        # the reduction is useless until it is brought into the session
        assert "ingest_vendor_data" in r.summary["next"]
        peaks = r.summary["steps"][0]
        assert peaks["step"] == "peaks" and "40676" in peaks["evidence"][0]

    def test_failed_step_surfaces_the_partial_trail(self, tmp_path, exp,
                                                    monkeypatch):
        from crystalpilot.io.crysalis_cap import StepResult
        self._wire(monkeypatch, lambda par, client=None, progress=None: {
            "ok": False,
            "steps": [StepResult("open", "xx selectexpnogui", "error", 2.0,
                                 "CAP reported command failure")],
            "error": "step 'open' error: CAP reported command failure"})
        r = _tool(tmp_path).run(_Ctx(), exp_par=str(exp))
        assert not r.ok
        assert r.summary["steps"][0]["status"] == "error"
        assert "open" in r.error

    def test_wedged_dialog_becomes_an_actionable_message(self, tmp_path, exp,
                                                         monkeypatch):
        from crystalpilot.io.crysalis_cap import HangSuspected

        def _hang(par, client=None, progress=None):
            raise HangSuspected("'dc proffittwin': busy 120s but CAP burned "
                                "only 0.2 CPU-s")
        self._wire(monkeypatch, _hang)
        r = _tool(tmp_path).run(_Ctx(), exp_par=str(exp))
        assert not r.ok
        assert "dialog" in r.error and "human" in r.error
        assert "Nothing was written back" in r.error

    def test_relative_path_resolves_against_the_project(self, tmp_path,
                                                        monkeypatch):
        # CAP resolves relative paths against ITS OWN cwd - caught live
        (tmp_path / "exp").mkdir()
        par = tmp_path / "exp" / "e.par"
        par.write_text("", encoding="utf-8")
        seen = {}
        self._wire(monkeypatch, lambda p, client=None, progress=None:
                   (seen.setdefault("par", p),
                    {"ok": True, "steps": [], "hkl": None,
                     "n_hkl_rows": 0})[1])
        r = _tool(tmp_path).run(_Ctx(), exp_par="exp/e.par")
        assert r.ok, r.error
        assert Path(seen["par"]).is_absolute()
        assert Path(seen["par"]) == par.resolve()


class TestWiring:
    def test_registered_sessionless_and_not_readonly(self):
        from crystalpilot.mcp.server import READ_ONLY_TOOLS
        from crystalpilot.refine.registry import (MUTATING_TOOLS,
                                                  SESSIONLESS_TOOLS)
        # it runs before any session exists (that is the point)
        assert "reduce_with_crysalis" in SESSIONLESS_TOOLS
        # it drives a vendor GUI and writes files: not an inspection call
        assert "reduce_with_crysalis" not in READ_ONLY_TOOLS
        # ...but it changes no session state either
        assert "reduce_with_crysalis" not in MUTATING_TOOLS

    def test_schema_documents_the_experiment_input(self):
        props = tc.ReduceWithCrysalis.params_schema["properties"]
        assert props["exp_par"]["type"] == "string"
        assert "acknowledge_existing_model" in props
        assert tc.ReduceWithCrysalis.params_schema["required"] == ["exp_par"]
