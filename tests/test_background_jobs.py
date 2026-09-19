"""Detached SHELXT jobs must stay visible and must not be misjudged.

2026-09-18, two real NU-1000 sessions (usertest/test-NU1000, -2): the agent
started SHELXT detached; SHELXT phased in 35 s, then spent 775-807 s in the
SILENT space-group search - exhaustive (-a) because Zr was declared, 18
groups of 6/mmm on a 39 A cell. The tool reported per_try_s = elapsed/12
(72-80 s for 3 s tries), nothing in the workbench showed a solver running,
and the user stopped both turns; both jobs finished with a solution 10-15
minutes later, unadopted.

Covered here: the pace estimate after phasing, the search-stage facts and
their project-own reference, the CPU-aware search grace, and the service
side watcher that turns job files into background_job events. The SHELXT
log below is the real one from that day (trimmed); no crystal-specific
constant is used anywhere in the code under test.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
from pathlib import Path

import pytest

from crystalpilot.refine import tools_shelxl
from crystalpilot.refine.tools_shelxl import (SHELXT_JOBS_FILE, RunShelxt,
                                              SEARCH_ACTIVE_EXT_FACTOR)
from crystalpilot.workbench.background_jobs import (BackgroundJobWatcher,
                                                    job_snapshot)

NU1000_HEAD = """
 ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
 +  SHELXT  -  CRYSTAL STRUCTURE SOLUTION - VERSION 2018/2            +
 +  Started at 16:46:12 on 18 Sep 2026                                +
 ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

 Command line parameters:  -t4 -d1 job

  4 threads running in parallel

 Unit-cell:  39.190  39.190  16.610   90.00   90.00  120.00

 -a set to extend space group search because atom heavier than Sc expected

 Laue group identified as number 12:   6/mmm

  337815 reflections read from file job.hkl

 Setup:   0.752 secs

  4 threads running in parallel

  Try N(iter)  CC   R(weak)   CHEM    CFOM    best  Sig(min) N(P1) Vol/N
    1   100   87.76  0.1480  0.7957  0.7297  0.7297  2.161   618   35.75
    2   100   86.72  0.1380  0.7043  0.7292  0.7297  2.329   640   34.52
    3   100   87.05  0.1399  0.7446  0.7306  0.7306  2.315   628   35.18
    4   100   87.33  0.1452  0.7185  0.7282  0.7306  2.262   592   37.32
    5   146   86.86  0.1358  0.7365  0.7328  0.7328  2.334   608   36.34
    6   146   87.74  0.1522  0.6940  0.7251  0.7328  2.470   625   35.35
    7   146   87.85  0.1461  0.6247  0.7324  0.7328  2.415   668   33.07
    8   146   87.53  0.1434  0.6846  0.7319  0.7328  2.292   641   34.47
    9   214   87.64  0.1479  0.6237  0.7285  0.7328  2.367   622   35.52
   10   214   87.55  0.1385  0.7070  0.7370  0.7370  2.428   601   36.76
   11   214   88.10  0.1532  0.6114  0.7278  0.7370  2.391   615   35.92
   12   214   87.77  0.1428  0.6495  0.7349  0.7370  2.451   616   35.86

      12 attempts, solution 10 selected with best CFOM = 0.7370, Alpha0 = 0.185

 Structure solution:      34.820 secs
"""

NU1000_TAIL = """
   4 Centrosymmetric and  14 non-centrosymmetric space groups evaluated

 Space group determination:     774.969 secs

   R1  Rweak Alpha SysAbs  Orientation      Space group  Flack_x  File  Formula
 0.327 0.069 0.109 0.00      as input       P6/mmm               job_a  C121 O90 Zr6
 0.314 0.051 0.104 0.00      as input       P6mm          0.47   job_b  C783 O253 I18

 Assign elements and isotropic refinement    50.060 secs

 ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
 +  SHELXT finished at 17:00:32    Total time:      860.601 secs  +
 ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
"""
NU1000_FULL = NU1000_HEAD + NU1000_TAIL

# a sibling job on the same project that fixed the group with -s: 3 s search
SINGLE_GROUP_LXT = """
 Command line parameters:  -t4 -s"P6_mmm" job
 Laue group set to number 12:   6/mmm
  Try N(iter)  CC   R(weak)   CHEM    CFOM    best  Sig(min) N(P1) Vol/N
    1   100   87.76  0.1480  0.7957  0.7297  0.7297  2.161   618   35.75
      1 attempts, solution  1 selected with best CFOM = 0.7297, Alpha0 = 0.185
 Structure solution:      30.000 secs
   1 Centrosymmetric and   0 non-centrosymmetric space groups evaluated
 Space group determination:       3.200 secs
 Assign elements and isotropic refinement    40.000 secs
 +  SHELXT finished at 17:00:32    Total time:       75.000 secs  +
"""

MONOCLINIC_LXT = NU1000_FULL.replace("number 12:   6/mmm", "number  2:   2/m")


# --------------------------------------------------------------------------
# 1. the pace estimate after phasing
# --------------------------------------------------------------------------

class TestPaceAfterPhasing:
    def test_per_try_comes_from_phasing_time_once_phased(self):
        st = RunShelxt._lxt_status(NU1000_HEAD)
        assert st["phased"] and st["phasing_s"] == pytest.approx(34.82)
        # 15 minutes into the search the wall clock says 900 s
        est = RunShelxt._phasing_estimate(st, 900.0, timeout_s=600)
        assert est["tries_done"] == 12
        assert est["per_try_s"] == pytest.approx(34.82 / 12, abs=0.1)
        assert est["per_try_s"] < 5          # not 75 s (= 900 / 12)

    def test_unphased_estimate_still_uses_the_wall_clock(self):
        cut = NU1000_HEAD.split("12 attempts")[0]
        st = RunShelxt._lxt_status(cut)
        assert not st["phased"]
        est = RunShelxt._phasing_estimate(st, 60.0, timeout_s=600)
        assert est["per_try_s"] == pytest.approx(60.0 / 12, abs=0.1)


# --------------------------------------------------------------------------
# 2. search-stage facts
# --------------------------------------------------------------------------

def _sibling(base: Path, name: str, txt: str) -> Path:
    d = base / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "job.lxt").write_text(txt, encoding="utf-8")
    return d


class TestSearchReference:
    def test_reference_matches_laue_class_and_search_scope(self, tmp_path):
        base = tmp_path / "shelxt"
        _sibling(base, "job_1", NU1000_FULL)          # exhaustive, 775 s
        _sibling(base, "job_2", SINGLE_GROUP_LXT)     # -s, 3.2 s
        _sibling(base, "job_3", MONOCLINIC_LXT)       # other Laue class
        _sibling(base, "job_4", NU1000_HEAD)          # unfinished search
        ref = RunShelxt._search_reference(base, "6/mmm", True, exclude="job_9")
        assert ref["n_jobs"] == 1 and ref["median_s"] == pytest.approx(774.97, abs=0.1)
        assert ref["last_job"] == "job_1" and ref["exhaustive"] is True
        ref_s = RunShelxt._search_reference(base, "6/mmm", False)
        assert ref_s["n_jobs"] == 1 and ref_s["median_s"] == pytest.approx(3.2)
        assert RunShelxt._search_reference(base, "mmm", True) is None
        assert RunShelxt._search_reference(base, None, True) is None
        # the job itself is not its own reference
        assert RunShelxt._search_reference(base, "6/mmm", True, exclude="job_1") is None

    def test_exhaustive_detection(self):
        assert RunShelxt._exhaustive_search(RunShelxt._lxt_status(NU1000_HEAD))
        st = RunShelxt._lxt_status(SINGLE_GROUP_LXT)
        assert not RunShelxt._exhaustive_search(st)
        assert RunShelxt._exhaustive_search({"auto_a": False, "cli": "-t4 -a job"})
        assert RunShelxt._exhaustive_search({"auto_a": False, "cli": "-a0.3 -y job"})
        assert not RunShelxt._exhaustive_search({"auto_a": False, "cli": "-t4 -d1 job"})


class TestSearchOutlook:
    def test_running_search_reports_elapsed_reason_and_reference(self, tmp_path):
        base = tmp_path / "shelxt"
        _sibling(base, "job_prev", NU1000_FULL)
        job = _sibling(base, "job_now", NU1000_HEAD)
        st = RunShelxt._lxt_status(NU1000_HEAD)
        out = RunShelxt._search_outlook(base, job, st, 300.0)
        assert out["auto_a"] is True and out["exhaustive_search"] is True
        assert out["search_elapsed_s"] == pytest.approx(300.0 - 34.82, abs=0.1)
        assert out["search_reference"]["median_s"] == pytest.approx(774.97, abs=0.1)
        note = out["search_note"]
        assert "prints nothing" in note
        assert "every space group of Laue class 6/mmm" in note
        assert "heavier than Sc" in note
        assert "775 s" in note
        assert "space_group=" in note

    def test_finished_search_reports_shelxt_time_no_note(self, tmp_path):
        base = tmp_path / "shelxt"
        job = _sibling(base, "job_done", NU1000_FULL)
        out = RunShelxt._search_outlook(base, job, RunShelxt._lxt_status(NU1000_FULL), 861.0)
        assert out["search_elapsed_s"] == pytest.approx(774.97, abs=0.1)
        assert out["search_note"] is None

    def test_before_phasing_ends_nothing_is_claimed(self, tmp_path):
        cut = NU1000_HEAD.split("12 attempts")[0]
        job = _sibling(tmp_path / "shelxt", "job_p", cut)
        out = RunShelxt._search_outlook(job.parent, job, RunShelxt._lxt_status(cut), 20.0)
        assert out["search_elapsed_s"] is None and out["search_note"] is None


# --------------------------------------------------------------------------
# 3. CPU-aware search grace
# --------------------------------------------------------------------------

class TestSearchExtensionRule:
    def test_idle_or_unknown_process_gets_nothing(self):
        assert RunShelxt._search_extension(None, 900, 0.0) == 0.0
        assert RunShelxt._search_extension(0.05, 900, 0.0) == 0.0

    def test_busy_process_gets_bounded_slices(self):
        assert RunShelxt._search_extension(0.9, 900, 0.0) == 225.0     # 0.25 x grace
        assert RunShelxt._search_extension(0.9, 60, 0.0) == 60.0       # floor
        cap = SEARCH_ACTIVE_EXT_FACTOR * 900
        assert RunShelxt._search_extension(0.9, 900, cap) == 0.0        # cap reached
        assert RunShelxt._search_extension(0.9, 900, cap - 100) == 100.0


def _load_fake():
    spec = importlib.util.spec_from_file_location(
        "tsp", Path(__file__).with_name("test_shelxt_progress.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


class TestWatchLoopSearchGrace:
    def test_idle_process_is_still_killed_at_search_grace(self, tmp_path):
        tsp = _load_fake()
        # phasing ~0.9 s, then a 6 s "search" in which the stand-in sleeps
        r = RunShelxt._run_staged(tsp._cmd(tmp_path, "pass", 0.3, search_s=6.0),
                                  tmp_path, budget_s=2, grace_s=2,
                                  phasing_grace_s=0, poll_s=0.2)
        assert r["timed_out"] == "search" and r["stage"] == "killed"
        assert r["search_grace_extended_s"] == 0.0
        assert "search grace" in r["error"]

    def test_busy_process_is_extended_and_finishes(self, tmp_path, monkeypatch):
        tsp = _load_fake()
        monkeypatch.setattr(tools_shelxl._CpuActivity, "sample",
                            lambda self: 1.0)      # "one core busy"
        beats: list[str] = []
        r = RunShelxt._run_staged(tsp._cmd(tmp_path, "pass", 0.3, search_s=6.0),
                                  tmp_path, budget_s=2, grace_s=2,
                                  phasing_grace_s=0, poll_s=0.2,
                                  progress=beats.append, heartbeat_s=1.0)
        assert r["timed_out"] is None and r["stage"] == "finished", r
        assert r["search_grace_extended_s"] > 0
        assert "extended" in r["search_grace_note"]
        assert any("search grace extended" in b for b in beats)
        prog = json.loads((tmp_path / "progress.json").read_text(encoding="utf-8"))
        assert prog["search_grace_extended_s"] == r["search_grace_extended_s"]
        assert prog["stage"] == "finished" and prog["has_solution"] is True


# --------------------------------------------------------------------------
# 4. the service-side watcher
# --------------------------------------------------------------------------

def _own_pid_and_start() -> tuple[int, float]:
    import psutil
    return os.getpid(), psutil.Process().create_time()


def _project_with_job(tmp_path: Path, *, running: bool, lxt: str,
                      solution: bool = False, adopted: bool = False,
                      finished_at: str | None = None,
                      started_epoch: float | None = None) -> tuple[Path, Path]:
    base = tmp_path / ".crystalpilot" / "refine" / "shelxt"
    job = base / "job_20260918_164612"
    job.mkdir(parents=True)
    (job / "job.lxt").write_text(lxt, encoding="utf-8")
    pid, t_create = _own_pid_and_start()
    t0 = started_epoch if started_epoch is not None else t_create
    budget = {"timeout_s": 600, "search_grace_s": 900, "phasing_grace_s": 600}
    prog = {"job": job.name, "job_dir": str(job), "pid": pid,
            "started_at": "2026-09-18T16:46:12", "started_at_epoch": t0,
            "budget": budget, "stage": "space-group search" if running else "finished",
            "running": running, "updated_at": "2026-09-18T16:55:00",
            "elapsed_s": 500.0 if running else 862.6}
    (job / "progress.json").write_text(json.dumps(prog), encoding="utf-8")
    if solution:
        (job / "job_a.res").write_text("TITL job_a\n", encoding="ascii")
    rec = {"job": job.name, "job_dir": str(job), "pid": pid,
           "started_at": "2026-09-18T16:46:12", "budget": budget,
           "stage": "running" if running else "finished"}
    if finished_at:
        rec["finished_at"] = finished_at
    if adopted:
        rec["adopted_at"] = "2026-09-18T17:30:00"
    (base / SHELXT_JOBS_FILE).write_text(json.dumps({"jobs": [rec]}), encoding="utf-8")
    return base, job


def _finish(base: Path, job: Path, *, adopted: bool = False) -> None:
    prog = json.loads((job / "progress.json").read_text(encoding="utf-8"))
    prog.update(stage="finished", running=False, elapsed_s=862.6,
                updated_at="2026-09-18T17:00:34",
                next=f"run_shelxt(from_job='{job.name}') adopts the solution")
    (job / "progress.json").write_text(json.dumps(prog), encoding="utf-8")
    (job / "job.lxt").write_text(NU1000_FULL, encoding="utf-8")
    (job / "job_a.res").write_text("TITL job_a\n", encoding="ascii")
    reg = json.loads((base / SHELXT_JOBS_FILE).read_text(encoding="utf-8"))
    reg["jobs"][0].update(stage="finished", finished_at="2026-09-18T17:00:34",
                          elapsed_s=862.6)
    if adopted:
        reg["jobs"][0]["adopted_at"] = "2026-09-18T17:30:00"
    (base / SHELXT_JOBS_FILE).write_text(json.dumps(reg), encoding="utf-8")


class TestJobSnapshot:
    def test_running_search_from_files(self, tmp_path):
        base, job = _project_with_job(tmp_path, running=True, lxt=NU1000_HEAD)
        rec = json.loads((base / SHELXT_JOBS_FILE).read_text(encoding="utf-8"))["jobs"][0]
        s = job_snapshot(job, rec, now=time.time())
        assert s["running"] is True and s["stage"] == "space-group search"
        # the pid check demands the recorded start time to match the live
        # process, so the elapsed time is this test process's own age
        assert 0.0 <= s["elapsed_s"] < 3600.0
        assert s["phasing_finished"] is True and s["tries_done"] == 12
        assert s["best_cfom"] == pytest.approx(0.737)
        assert s["auto_a"] is True and s["exhaustive_search"] is True
        assert s["search_elapsed_s"] == pytest.approx(
            max(0.0, s["elapsed_s"] - 34.82), abs=2.0)
        assert s["has_solution"] is False and s["adopted_at"] is None

    def test_recorded_running_but_process_gone(self, tmp_path):
        base, job = _project_with_job(tmp_path, running=True, lxt=NU1000_HEAD)
        prog = json.loads((job / "progress.json").read_text(encoding="utf-8"))
        prog["pid"] = 2 ** 22 + 1                      # nobody
        (job / "progress.json").write_text(json.dumps(prog), encoding="utf-8")
        s = job_snapshot(job, {}, now=time.time())
        assert s["running"] is False and s["stage"] == "died"

    def test_no_files_is_none(self, tmp_path):
        d = tmp_path / "job_empty"
        d.mkdir()
        assert job_snapshot(d, {}, now=time.time()) is None


class TestWatcherTransitions:
    def _watcher(self, tmp_path, owner="thr-1"):
        got: list[tuple[dict, str | None, bool]] = []
        w = BackgroundJobWatcher(tmp_path, emit=lambda ev, o, p: got.append((ev, o, p)),
                                 owner_hint=lambda: owner, heartbeat_s=15.0)
        return w, got

    def test_started_heartbeat_finished_adopted(self, tmp_path):
        base, job = _project_with_job(tmp_path, running=True, lxt=NU1000_HEAD)
        w, got = self._watcher(tmp_path)
        t = time.time()
        assert len(w.poll_once(now=t)) == 1
        ev, owner, persist = got[-1]
        assert ev["kind"] == "background_job" and ev["transition"] == "started"
        assert ev["program"] == "SHELXT" and ev["tool"] == "run_shelxt"
        assert ev["running"] is True and ev["stage"] == "space-group search"
        assert owner == "thr-1" and persist is True
        # nothing changed, not yet heartbeat time: silence
        assert w.poll_once(now=t + 5) == []
        # heartbeat: live only
        assert len(w.poll_once(now=t + 16)) == 1
        ev, owner, persist = got[-1]
        assert ev["transition"] == "heartbeat" and persist is False and owner == "thr-1"
        assert [e["job"] for e in w.snapshot_events()] == [job.name]
        assert w.running_jobs and w.running_jobs[0]["job"] == job.name
        # the tool process finishes the job
        _finish(base, job)
        assert len(w.poll_once(now=t + 20)) == 1
        ev, owner, persist = got[-1]
        assert ev["transition"] == "finished" and persist is True
        assert ev["running"] is False and ev["has_solution"] is True
        assert ev["search_elapsed_s"] == pytest.approx(774.97, abs=0.1)
        assert ev["n_space_groups"] == 18
        assert w.running_jobs == []
        # still tracked while unadopted: a reload gets it as a snapshot
        assert [e["transition"] for e in w.snapshot_events()] == ["snapshot"]
        # the agent adopts it in a later turn (from_job writes adopted_at)
        _finish(base, job, adopted=True)
        assert len(w.poll_once(now=t + 30)) == 1
        ev, owner, persist = got[-1]
        assert ev["transition"] == "adopted" and persist is True
        assert ev["adopted_at"] == "2026-09-18T17:30:00"
        assert w.snapshot_events() == []
        assert w.poll_once(now=t + 40) == []

    def test_no_owner_means_live_only(self, tmp_path):
        _project_with_job(tmp_path, running=True, lxt=NU1000_HEAD)
        w, got = self._watcher(tmp_path, owner=None)
        w.poll_once(now=time.time())
        ev, owner, persist = got[-1]
        assert ev["transition"] == "started" and owner is None and persist is False

    def test_finished_unadopted_solution_surfaces_once_live(self, tmp_path):
        # the user's real situation: the server sees the job only after the
        # fact (project reopened) - the finished solution must still be
        # shown so it can be adopted, but it is not new history
        base, job = _project_with_job(tmp_path, running=False, lxt=NU1000_FULL,
                                      solution=True,
                                      finished_at="2026-09-18T17:00:34")
        w, got = self._watcher(tmp_path)
        assert len(w.poll_once(now=time.time())) == 1
        ev, owner, persist = got[-1]
        assert ev["transition"] == "finished" and ev["has_solution"] is True
        assert persist is False and owner is None
        assert len(w.snapshot_events()) == 1
        assert w.poll_once(now=time.time() + 1) == []

    def test_history_is_left_alone(self, tmp_path):
        # adopted long ago: nothing to say
        _project_with_job(tmp_path, running=False, lxt=NU1000_FULL, solution=True,
                          adopted=True, finished_at="2026-09-18T17:00:34")
        w, got = self._watcher(tmp_path)
        assert w.poll_once(now=time.time()) == [] and got == []
        assert w.snapshot_events() == []

    def test_dead_job_without_solution_is_not_announced_late(self, tmp_path):
        _, job = _project_with_job(tmp_path, running=True, lxt=NU1000_HEAD)
        prog = json.loads((job / "progress.json").read_text(encoding="utf-8"))
        prog["pid"] = 2 ** 22 + 1
        (job / "progress.json").write_text(json.dumps(prog), encoding="utf-8")
        w, got = self._watcher(tmp_path)
        assert w.poll_once(now=time.time()) == [] and got == []

    def test_missing_registry_is_quiet(self, tmp_path):
        w, got = self._watcher(tmp_path)
        assert w.poll_once() == [] and got == []

    def test_emit_failure_does_not_stop_the_watcher(self, tmp_path):
        _project_with_job(tmp_path, running=True, lxt=NU1000_HEAD)

        def boom(ev, o, p):
            raise RuntimeError("channel gone")
        w = BackgroundJobWatcher(tmp_path, emit=boom, owner_hint=lambda: None)
        assert len(w.poll_once(now=time.time())) == 1
        assert len(w.snapshot_events()) == 1


@pytest.mark.skipif(sys.platform != "win32", reason="pid liveness via psutil on Windows")
class TestPidCheckIsSpecific:
    def test_same_pid_other_start_time_is_not_alive(self):
        from crystalpilot.refine.tools_shelxl import _pid_alive
        pid, t0 = _own_pid_and_start()
        assert _pid_alive(pid, t0) is True
        assert _pid_alive(pid, t0 - 3600.0) is False
