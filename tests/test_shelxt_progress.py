"""run_shelxt: phasing grace, truthful budget estimates from the job's own
try table, progress.json, detach + job_status, from_job on killed jobs.

pa2: 25 SHELXT calls, 12 failures, 10134 s. Two runs (cage-l0-r1 #3,
cage-l2-r1 #2) were killed at their budget with a try ALREADY above the
CFOM floor - one batch short of the solution they were then re-run for
(607 s / 1067 s). SHELXT writes nothing until phasing AND the search end,
so a killed run has no .res, and from_job answered 'exit None'. Meanwhile
the agent saw only 'Script running' for ~250 wait polls.

Everything below is estimated from the job's OWN job.lxt (threads, N(iter)
column, -x rule) - no crystal-specific constants are involved.
"""
from __future__ import annotations

import json
import re
import sys
import textwrap
import time
from pathlib import Path

import pytest

from crystalpilot.refine.tools_shelxl import (SHELXT_JOBS_FILE, RunShelxt,
                                              _DETACHED)

# --------------------------------------------------------------------------
# a stand-in for shelxt.exe with SHELXT's log shape: header, "2 threads",
# the try table in batches of two, then (mode 'pass') the acceptance line,
# the search summary, the candidate table and job_a.res
# --------------------------------------------------------------------------

FAKE_SHELXT = textwrap.dedent("""
    import shutil, sys, time
    from pathlib import Path
    mode, phase_s, search_s = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
    res_src = sys.argv[4] if len(sys.argv) > 4 else ""
    lxt = Path("job.lxt")
    def w(s):
        with open(lxt, "a", encoding="ascii") as f:
            f.write(s)
    w(" +  Started at 12:00:00 on 02 Sep 2026   +\\n"
      " Command line parameters:  -t2 -y -m100 -d1 job\\n\\n"
      "  2 threads running in parallel\\n\\n"
      " Laue group identified as number  2:   2/m\\n\\n"
      " Setup:   0.100 secs\\n\\n"
      "  2 threads running in parallel\\n\\n"
      "  Try N(iter)  CC   R(weak)   CHEM    CFOM    best  Sig(min) N(P1) Vol/N\\n")
    top = 0.7000 if mode == "pass" else 0.6000
    rows = [(1, 100, 0.5900), (2, 100, 0.6000), (3, 146, 0.5500), (4, 146, top)]
    for n, it, cfom in rows:
        time.sleep(0.15)
        best = max(c for _, _, c in rows[:n])
        w("   %2d  %4d   85.07  0.2210  0.6980  %.4f  %.4f  2.093   606   31.71\\n"
          % (n, it, cfom, best))
    time.sleep(phase_s)
    if mode != "pass":
        sys.exit(0)
    w("\\n       4 attempts, solution  4 selected with best CFOM = 0.7000, Alpha0 = 0.194\\n\\n"
      " Structure solution:       1.000 secs\\n")
    time.sleep(search_s)
    w("\\n   2 Centrosymmetric and   0 non-centrosymmetric space groups evaluated\\n\\n"
      " Space group determination:       0.100 secs\\n\\n"
      "   R1  Rweak Alpha SysAbs  Orientation      Space group  Flack_x  File  Formula\\n"
      " 0.100 0.050 0.100 0.00      as input       P1                   job_a  C1 O2\\n\\n"
      " Assign elements and isotropic refinement     0.100 secs\\n")
    if res_src:
        shutil.copy(res_src, "job_a.res")
    w("\\n +  SHELXT finished at 12:00:05    Total time:        2.000 secs  +\\n")
""")


def _cmd(tmp_path: Path, mode: str, phase_s: float, search_s: float = 0.2,
         res_src: str = "") -> list[str]:
    fake = tmp_path / "fake_shelxt.py"
    fake.write_text(FAKE_SHELXT, encoding="utf-8")
    if not res_src:
        # a finished SHELXT leaves job_a.res: the stand-in copies this one
        src = tmp_path / "solution.res"
        src.write_text(FORMATE_RES.replace("TITL formate",
                                           "TITL job_a solution"),
                       encoding="ascii")
        res_src = str(src)
    return [sys.executable, str(fake), mode, str(phase_s), str(search_s),
            res_src]


# --------------------------------------------------------------------------
# A. phasing grace
# --------------------------------------------------------------------------

class TestPhasingGrace:
    def test_passed_floor_is_not_killed_at_timeout(self, tmp_path):
        """The try table clears the floor before timeout_s runs out: the
        run is extended (bounded by phasing_grace_s) and finishes."""
        beats: list[str] = []
        r = RunShelxt._run_staged(_cmd(tmp_path, "pass", 2.5), tmp_path,
                                  budget_s=2, grace_s=30, phasing_grace_s=30,
                                  progress=beats.append, poll_s=0.1,
                                  heartbeat_s=0.2)
        assert r["timed_out"] is None, r
        assert r["returncode"] == 0
        assert r["stage"] == "finished"
        assert r["elapsed"] > 2.5                   # ran past timeout_s
        assert r["phasing_grace_used_s"] > 0.3
        assert r["phasing_grace_used_s"] <= r["phasing_grace_granted_s"] <= 30
        assert r["phasing_note"] and "extended" in r["phasing_note"]
        assert "0.7000" in r["phasing_note"]
        assert "acceptance expected at try 16" in r["phasing_note"]
        assert any("phasing budget extended" in b for b in beats)
        assert any("clears the floor" in b for b in beats)

    def test_passed_floor_but_grace_exhausted_is_killed_truthfully(
            self, tmp_path):
        r = RunShelxt._run_staged(_cmd(tmp_path, "pass", 30.0), tmp_path,
                                  budget_s=2, grace_s=30, phasing_grace_s=1,
                                  poll_s=0.1, heartbeat_s=0.2)
        assert r["timed_out"] == "phasing"
        assert r["stage"] == "killed"
        assert 2.5 < r["elapsed"] < 8.0
        assert 0.5 < r["phasing_grace_used_s"] < 3.0
        est = r["estimate"]
        assert est["tries_done"] == 4
        assert est["best_cfom"] == pytest.approx(0.70)
        assert est["passed_acceptance"] is True
        assert est["per_try_s"] and est["per_try_s"] > 0
        assert est["threads"] == 2 and est["accept_at_try"] == 16
        assert est["tries_remaining"] == 12
        assert est["estimated_total_s"] > r["elapsed"]
        assert est["suggested_timeout_s"] % 60 == 0
        assert est["suggested_timeout_s"] >= est["estimated_total_s"] * 1.3
        # a try under 20 s never triggers an -m suggestion
        assert est["suggested_n_phase_sets"] is None
        m = r["error"]
        assert "4 tries done" in m and "0.700" in m
        assert "clears the floor 0.65" in m
        assert "accepts it" in m and "try 16" in m
        assert f"timeout_s >= {est['suggested_timeout_s']}" in m
        assert "phasing grace" in m and "ran out" in m
        # the killed message must never push -m upwards
        assert re.search(r"n_phase_sets\D{0,3}1000", m) is None
        assert "1000" not in m
        assert "raise" not in m.replace("never raise", "")
        # the same message from the public helper
        m2 = RunShelxt._timeout_message(
            tmp_path, r["elapsed"], 2, phasing_grace_used=r[
                "phasing_grace_used_s"], phasing_grace_s=1)
        assert "phasing grace" in m2 and "1000" not in m2

    def test_below_floor_is_killed_at_timeout_even_with_grace(self,
                                                              tmp_path):
        r = RunShelxt._run_staged(_cmd(tmp_path, "below", 30.0), tmp_path,
                                  budget_s=1, grace_s=30,
                                  phasing_grace_s=600, poll_s=0.1)
        assert r["timed_out"] == "phasing"
        assert r["elapsed"] < 3.0
        assert r["phasing_grace_used_s"] == 0
        est = r["estimate"]
        assert est["passed_acceptance"] is False
        assert est["accept_at_try"] is None
        assert est["suggested_timeout_s"] is None
        assert "more time only buys more tries" in r["error"]
        assert "solve_resolution" in r["error"]
        assert "1000" not in r["error"]

    def test_grace_disabled_says_so(self, tmp_path):
        r = RunShelxt._run_staged(_cmd(tmp_path, "pass", 30.0), tmp_path,
                                  budget_s=2, grace_s=30, phasing_grace_s=0,
                                  poll_s=0.1)
        assert r["timed_out"] == "phasing"
        assert r["phasing_grace_used_s"] == 0
        assert "phasing_grace_s=0 disabled" in r["error"]
        assert "timeout_s >=" in r["error"]


# --------------------------------------------------------------------------
# B. estimates from the job's own table (real pa2 cage-l0-r1 #3 excerpt:
#    16 tries in 600 s at -m1000 with 4 threads, try 16 CFOM 0.6704)
# --------------------------------------------------------------------------

CAGE_16 = """\
 Command line parameters:  -t4 -y -a -m1000 -d0.996 -sP2(1)_c job

  4 threads running in parallel

 Laue group set to number  2:   2/m

  Try N(iter)  CC   R(weak)   CHEM    CFOM    best  Sig(min) N(P1) Vol/N
    1  1000   85.07  0.2210  0.6980  0.5938  0.5938  2.093   606   31.71
    2  1000   85.16  0.2179  0.6480  0.5519  0.5938  2.208   581   33.07
    3  1000   86.60  0.2338  0.6382  0.5527  0.5938  1.985   610   31.50
    4  1000   85.91  0.2300  0.5775  0.4962  0.5938  1.975   586   32.79
    5  1464   85.15  0.2251  0.6932  0.5902  0.5938  2.074   576   33.36
    6  1464   86.36  0.2331  0.7018  0.6061  0.6061  1.993   591   32.51
    7  1464   85.15  0.2235  0.6845  0.5828  0.6061  2.068   573   33.54
    8  1464   85.39  0.2263  0.7550  0.6446  0.6446  2.051   579   33.19
    9  2143   85.18  0.2209  0.6772  0.5769  0.6446  2.041   604   31.82
   10  2143   86.07  0.2250  0.5816  0.5006  0.6446  2.070   566   33.95
   11  2143   86.47  0.2343  0.6383  0.5520  0.6446  2.250   607   31.66
   12  2143   86.48  0.2318  0.6750  0.5837  0.6446  2.265   585   32.85
   13  3138   86.38  0.2326  0.6304  0.5446  0.6446  1.848   588   32.68
   14  3138   86.36  0.2351  0.5913  0.5107  0.6446  1.934   582   33.02
   15  3138   86.31  0.2253  0.5505  0.4751  0.6446  1.892   589   32.63
   16  3138   85.96  0.2289  0.7799  0.6704  0.6704  1.904   572   33.59
"""


class TestEstimate:
    def test_accept_at_try_follows_shelxt_batches(self):
        f = RunShelxt._accept_at_try
        # bar(m) = 0.65 + 0.01*max(20-m, 0); batches of 4
        assert f(0.6704, 0.65, 16, 4) == 20     # cage: '20 attempts, solution 16'
        assert f(0.7016, 0.65, 12, 4) == 16     # pa2 '16 attempts, solution 9'
        assert f(0.6516, 0.65, 18, 4) == 20     # pa2 '20 attempts, solution 12'
        assert f(0.7234, 0.65, 8, 4) == 16      # pa2 '16 attempts, solution 8'
        assert f(0.7450, 0.65, 32, 32) == 32    # r25: 32 threads, one batch
        assert f(0.6400, 0.65, 16, 4) is None   # never clears the floor
        assert f(0.9000, 0.65, 2, 4) == 4       # accepted at the batch end

    def test_cage_16_tries_at_600_s(self):
        st = RunShelxt._lxt_status(CAGE_16)
        assert st["threads"] == 4 and st["m_iter"] == 1000
        est = RunShelxt._phasing_estimate(st, 600.0, timeout_s=600)
        assert est["tries_done"] == 16
        assert est["best_cfom"] == pytest.approx(0.6704)
        assert est["passed_acceptance"] is True
        assert est["accept_at_try"] == 20 and est["tries_remaining"] == 4
        assert est["per_try_s"] == pytest.approx(37.5)
        assert est["iter_growth"] == pytest.approx(1.464, abs=0.005)
        # the last batch is the expensive one: 3138 x 1.464 iterations at
        # 600 x 4 / 30980 s per iteration ~ 356 s, NOT 4 x 37.5 = 150 s
        assert 330 < est["estimated_remaining_s"] < 380
        assert est["estimated_total_s"] == pytest.approx(
            600 + est["estimated_remaining_s"])
        assert est["suggested_timeout_s"] == 1260
        assert est["suggested_timeout_s"] % 60 == 0
        # 37.5 s per try: suggest a LOWER -m that fits the run into 600 s
        assert est["suggested_n_phase_sets"] == 480
        assert est["suggested_n_phase_sets"] < 1000

    def test_in_flight_batch_counts_in_full(self):
        cut = "\n".join(CAGE_16.splitlines()[:-2]) + "\n"    # 14 rows
        st = RunShelxt._lxt_status(cut)
        est = RunShelxt._phasing_estimate(st, 500.0)
        assert est["tries_done"] == 14
        assert est["passed_acceptance"] is False        # best 0.6446
        assert est["accept_at_try"] is None
        assert est["floor_reach_s"] is not None
        assert est["floor_reach_s"] > 0

    def test_no_suggestion_for_cheap_tries(self):
        st = RunShelxt._lxt_status(CAGE_16.replace("-m1000", "-m100"))
        est = RunShelxt._phasing_estimate(st, 60.0, timeout_s=60)
        assert est["per_try_s"] < 20
        assert est["suggested_n_phase_sets"] is None

    def test_verdict_text_for_killed_cage_job(self, tmp_path):
        (tmp_path / "job.lxt").write_text(CAGE_16, encoding="utf-8")
        m = RunShelxt._timeout_message(tmp_path, 600.0, 600,
                                       phasing_grace_s=0)
        assert "16 tries done" in m and "0.670" in m
        assert "clears the floor 0.65" in m
        assert "try 20" in m and "4 more tries" in m
        assert "timeout_s >= 1260" in m
        assert "n_phase_sets=480" in m
        assert "-m1000" in m                # the job's own flag, as a fact
        assert re.search(r"n_phase_sets\D{0,3}1000", m) is None
        assert "phasing_grace_s=0 disabled" in m


# --------------------------------------------------------------------------
# C. progress.json
# --------------------------------------------------------------------------

class TestProgressJson:
    def test_written_atomically_with_stage_fields(self, tmp_path):
        seen: list[dict] = []
        prog = tmp_path / "progress.json"

        def _beat(_msg: str) -> None:
            if prog.exists():
                seen.append(json.loads(prog.read_text(encoding="utf-8")))

        r = RunShelxt._run_staged(_cmd(tmp_path, "pass", 0.8), tmp_path,
                                  budget_s=30, grace_s=30, progress=_beat,
                                  poll_s=0.05, heartbeat_s=0.15)
        assert r["timed_out"] is None
        assert r["progress_json"] == str(prog)
        assert not prog.with_name("progress.json.tmp").exists()
        final = json.loads(prog.read_text(encoding="utf-8"))
        for key in ("job", "job_dir", "pid", "started_at", "started_at_epoch",
                    "updated_at", "stage", "running", "elapsed_s",
                    "tries_done", "best_cfom", "passed_acceptance",
                    "per_try_s", "estimated_remaining_s", "last_lxt_line",
                    "budget", "phasing_grace_used_s", "has_solution",
                    "next"):
            assert key in final, key
        assert final["stage"] == "finished" and final["running"] is False
        assert final["tries_done"] == 4
        assert final["best_cfom"] == pytest.approx(0.70)
        assert final["has_solution"] is True
        assert final["returncode"] == 0
        assert "SHELXT finished" in final["last_lxt_line"]
        assert final["budget"]["timeout_s"] == 30
        assert final["estimated_remaining_s"] is None   # nothing left
        assert "from_job" in final["next"]
        mid = [s for s in seen if s["stage"] == "phasing" and s["running"]]
        assert mid, [s["stage"] for s in seen]
        assert any(s["tries_done"] >= 1 for s in mid)
        assert any(s["passed_acceptance"] for s in mid)
        assert all(s["pid"] == final["pid"] for s in seen)

    def test_killed_job_records_the_diagnosis(self, tmp_path):
        r = RunShelxt._run_staged(_cmd(tmp_path, "below", 30.0), tmp_path,
                                  budget_s=1, grace_s=30, poll_s=0.1)
        assert r["timed_out"] == "phasing"
        final = json.loads((tmp_path / "progress.json").read_text(
            encoding="utf-8"))
        assert final["stage"] == "killed" and final["running"] is False
        assert final["timed_out"] == "phasing"
        assert "tries done" in final["error"]
        assert "cannot be resumed" in final["next"]


# --------------------------------------------------------------------------
# D/E. detach -> job_status -> from_job on a real project
# --------------------------------------------------------------------------

FORMATE_RES = textwrap.dedent("""\
    TITL formate
    CELL 0.71073 10.0 10.0 10.0 90.0 90.0 90.0
    ZERR 1 0.001 0.001 0.001 0.0 0.0 0.0
    LATT -1
    SFAC C H O
    UNIT 1 1 2
    WGHT 0.1
    FVAR 1.0
    C1   1  0.500000  0.500000  0.500000  11.00000  0.02000
    AFIX 43
    H1A  2  0.500000  0.593000  0.500000  11.00000 -1.20000
    AFIX 0
    O1   3  0.610900  0.442300  0.500000  11.00000  0.02500
    O2   3  0.389100  0.442300  0.500000  11.00000  0.02500
    HKLF 4
    END
    """)

HKL_3 = ("   1   0   0  100.00    5.00\n"
         "   0   1   0   80.00    4.00\n"
         "   0   0   1   60.00    3.00\n"
         "   0   0   0    0.00    0.00\n")


def _formate_project(tmp_path):
    from crystalpilot.refine.project import RefineProject
    d = tmp_path / "proj"
    d.mkdir()
    (d / "crystal.hkl").write_text(HKL_3, encoding="utf-8")
    (d / "start.res").write_text(FORMATE_RES, encoding="utf-8")
    (d / "context.json").write_text(json.dumps({
        "data": {"hkl": "crystal.hkl", "start_model": "start.res"}}),
        encoding="utf-8")
    p = RefineProject(d)
    p.open()
    return p


def _install_fake(monkeypatch, tmp_path: Path, mode: str, phase_s: float,
                  search_s: float = 0.2) -> None:
    """shelxt.exe -> the stand-in; it copies a P1 formate solution as
    job_a.res when it finishes."""
    exe = tmp_path / "fake_shelxt.exe"
    exe.write_text("", encoding="ascii")
    monkeypatch.setenv("CRYSTALPILOT_SHELXT", str(exe))
    cmd = _cmd(tmp_path, mode, phase_s, search_s)
    monkeypatch.setattr(RunShelxt, "_shelxt_command",
                        staticmethod(lambda exe, flags: list(cmd)))


def _wait_done(p, job: str, limit_s: float = 30.0) -> dict:
    t0 = time.time()
    while True:
        s = p.invoke_tool("run_shelxt", {"job_status": job})
        assert s.ok, s.error
        if not s.summary["running"]:
            return s.summary
        assert time.time() - t0 < limit_s, s.summary
        time.sleep(0.2)


class TestDetachAndJobStatus:
    def test_detach_status_adopt_sequence(self, tmp_path, monkeypatch):
        p = _formate_project(tmp_path)
        _install_fake(monkeypatch, tmp_path, "pass", 0.8)
        r = p.invoke_tool("run_shelxt", {"detach": True, "timeout_s": 20,
                                         "phasing_grace_s": 30,
                                         "search_grace_s": 30})
        assert r.ok, r.error
        s0 = r.summary
        assert s0["detached"] and s0["no_state_change"]
        assert "node" not in s0                       # nothing committed
        assert s0["pid"] and s0["started_at"] and s0["job"].startswith("job_")
        assert "job_status" in s0["note"] and "from_job" in s0["note"]
        job = s0["job"]
        assert str(tmp_path) in s0["job_dir"]
        # immediate status: running, read-only, instant
        t0 = time.time()
        s1 = p.invoke_tool("run_shelxt", {"job_status": job})
        assert time.time() - t0 < 5.0
        assert s1.ok, s1.error
        assert s1.summary["running"] is True
        assert s1.summary["no_state_change"] is True
        assert "node" not in s1.summary
        assert s1.summary["stage"] in ("starting", "phasing",
                                       "space-group search",
                                       "element assignment", "finished")
        assert s1.summary["watchdog"] == "this process"
        assert "poll" in s1.summary["next"]
        done = _wait_done(p, job)
        assert done["stage"] == "finished", done
        assert done["has_solution"] is True
        assert done["tries_done"] == 4
        assert done["best_cfom"] == pytest.approx(0.70)
        assert done["passed_acceptance"] is True
        assert done["phasing_finished"] is True
        assert "from_job" in done["next"]
        assert done["watchdog"] == "none"
        # background-job registry
        reg_path = Path(s0["registry"])
        assert reg_path.name == SHELXT_JOBS_FILE
        reg = json.loads(reg_path.read_text(encoding="utf-8"))
        rec = next(j for j in reg["jobs"] if j["job"] == job)
        assert rec["pid"] == s0["pid"] and rec["stage"] == "finished"
        assert rec["finished_at"]
        assert str(Path(s0["job_dir"])) not in _DETACHED
        # adopt what the background job produced
        r2 = p.invoke_tool("run_shelxt", {"from_job": job})
        assert r2.ok, r2.error
        assert r2.summary["adopted"] and r2.summary.get("node")
        assert r2.summary["best"] == "TITL job_a solution"
        assert r2.summary["reused_job"].endswith(job)
        assert p.session.model.scatterers().size() == 4

    def test_detached_job_killed_then_from_job_explains(self, tmp_path,
                                                         monkeypatch):
        p = _formate_project(tmp_path)
        _install_fake(monkeypatch, tmp_path, "pass", 60.0)
        r = p.invoke_tool("run_shelxt", {"detach": True, "timeout_s": 2,
                                         "phasing_grace_s": 1,
                                         "search_grace_s": 5})
        assert r.ok, r.error
        job = r.summary["job"]
        # from_job while it runs: no adoption, points at job_status
        early = p.invoke_tool("run_shelxt", {"from_job": job})
        assert not early.ok
        assert "STILL RUNNING" in early.error and "job_status" in early.error
        done = _wait_done(p, job)
        assert done["stage"] == "killed", done
        assert done["running"] is False and done["has_solution"] is False
        assert done["tries_done"] == 4 and done["passed_acceptance"] is True
        assert "tries done" in done["error"]
        assert done["phasing_grace_used_s"] and done["phasing_grace_used_s"] > 0.3
        assert "cannot be resumed" in done["next"]
        prog = json.loads((Path(done["job_dir"]) / "progress.json").read_text(
            encoding="utf-8"))
        assert prog["stage"] == "killed" and prog["running"] is False
        # the process is really gone
        from crystalpilot.refine.tools_shelxl import _pid_alive
        assert not _pid_alive(prog["pid"], prog["started_at_epoch"])
        # from_job on the killed job: says what happened and what to do
        r2 = p.invoke_tool("run_shelxt", {"from_job": job})
        assert not r2.ok
        m = r2.error
        assert "was killed by its budget after" in m
        assert "left no .res" in m
        assert "cannot resume" in m
        assert "4 tries done" in m and "above the acceptance floor" in m
        assert re.search(r"timeout_s >= \d+", m)
        assert "1000" not in m
        assert "no element list" not in m
        assert "exit None" not in m

    def test_modes_are_mutually_exclusive(self, tmp_path, monkeypatch):
        p = _formate_project(tmp_path)
        _install_fake(monkeypatch, tmp_path, "pass", 0.5)
        r = p.invoke_tool("run_shelxt", {"detach": True, "from_job": "x"})
        assert not r.ok and "mutually exclusive" in r.error
        r = p.invoke_tool("run_shelxt", {"job_status": "x", "from_job": "x"})
        assert not r.ok and "mutually exclusive" in r.error

    def test_job_status_unknown_job(self, tmp_path, monkeypatch):
        p = _formate_project(tmp_path)
        r = p.invoke_tool("run_shelxt", {"job_status": "job_nope"})
        assert not r.ok and "not a run_shelxt job" in r.error

    def test_blocking_timeout_carries_structured_estimate(self, tmp_path,
                                                          monkeypatch):
        p = _formate_project(tmp_path)
        _install_fake(monkeypatch, tmp_path, "below", 30.0)
        r = p.invoke_tool("run_shelxt", {"timeout_s": 1, "search_grace_s": 5})
        assert not r.ok
        assert "more time only buys more tries" in r.error
        t = r.summary["timeout"]
        assert t["stage"] == "phasing" and t["tries_done"] == 4
        assert t["passed_acceptance"] is False
        assert t["best_cfom"] == pytest.approx(0.60)
        assert t["per_try_s"] > 0 and t["suggested_timeout_s"] is None
        assert t["phasing_grace_used_s"] == 0
        assert Path(t["progress_json"]).exists()
        assert "1000" not in r.error
        assert "node" not in r.summary

    def test_blocking_run_reports_grace_and_progress_file(self, tmp_path,
                                                          monkeypatch):
        p = _formate_project(tmp_path)
        _install_fake(monkeypatch, tmp_path, "pass", 2.0)
        r = p.invoke_tool("run_shelxt", {"timeout_s": 1, "phasing_grace_s": 30,
                                         "search_grace_s": 30})
        assert r.ok, r.error
        s = r.summary
        assert s["adopted"] and s["phasing_grace_used_s"] > 0.3
        assert "extended" in s["phasing_note"]
        assert s["budget"]["phasing_grace_s"] == 30
        assert Path(s["progress_json"]).exists()
        # job_status also works on a job that ran in the foreground
        st = p.invoke_tool("run_shelxt", {"job_status": s["job_dir"]})
        assert st.ok and st.summary["stage"] == "finished"
        assert st.summary["running"] is False
        assert st.summary["has_solution"] is True


class TestSchemaText:
    def test_params_and_budget_wording(self):
        props = RunShelxt.params_schema["properties"]
        for k in ("detach", "job_status", "phasing_grace_s", "from_job"):
            assert k in props
        assert props["phasing_grace_s"]["default"] == 600
        assert props["detach"]["default"] is False
        assert props["n_phase_sets"]["maximum"] == 500
        desc = RunShelxt.description
        assert "detach" in desc and "job_status" in desc
        assert "per try" in desc
        assert "cannot be resumed" in desc
        blob = " ".join([desc] + [p["description"] for p in props.values()])
        assert "-m1000 x 20 tries" not in blob
        assert "PER TRY" in props["n_phase_sets"]["description"]
        assert "LOWER" in props["n_phase_sets"]["description"]
