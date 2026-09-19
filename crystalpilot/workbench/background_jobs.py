"""Narrate a project's detached solver jobs as ``background_job`` events.

Why this exists (2026-09-18, two real NU-1000 sessions): the agent started
SHELXT with ``run_shelxt(detach=true)``, polled ``job_status`` a few times and
the user stopped both turns after 6 and 12 minutes because "nothing moved".
SHELXT was in its space-group search - silent by design, and exhaustive
(-a) because Zr was declared, 775-807 s on that 39 A hexagonal cell. Both
jobs finished WITH a solution 10-15 minutes after the stop; nobody saw it,
nothing adopted it. The watchdog that owns the job lives in the MCP tool
process (``tools_shelxl._DETACHED``); the web service never knew a solver was
running, so the conversation, the status rail and the node tree stood still.

This module is the service-side mirror: a thread per open project that
reads ONLY files the tool process writes - the registry
``.crystalpilot/refine/shelxt/_jobs.json``, each job's ``progress.json`` and
``job.lxt`` - plus pid liveness, and turns changes into events:

* ``transition`` = ``started`` / ``stage`` / ``finished`` / ``killed`` /
  ``failed`` / ``died`` / ``adopted``: persisted into the owning thread's
  transcript when the owner is known (the single busy thread at the moment
  the job appeared), so a reload still shows them;
* ``transition`` = ``heartbeat`` (every HEARTBEAT_S while running) and
  ``snapshot`` (appended to a transcript bootstrap): live only.

A job stays tracked while it runs, and - once finished with a solution -
until it is adopted (``adopted_at`` written by ``run_shelxt(from_job=...)``)
or TRACK_FINISHED_FOR_S has passed. Nothing here changes any scientific
result: the module writes no file under the project.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

SHELXT_SUBDIR = Path(".crystalpilot") / "refine" / "shelxt"
#: a job is running: re-read its files this often
POLL_RUNNING_S = 3.0
#: nothing running: look for new jobs this often
POLL_IDLE_S = 10.0
#: live (unpersisted) progress pushes while a job runs
HEARTBEAT_S = 15.0
#: a finished, unadopted solution stays visible this long after it finished
TRACK_FINISHED_FOR_S = 24 * 3600
#: transitions worth a transcript line (everything else is live only)
PERSISTED = frozenset({"started", "stage", "finished", "killed", "failed",
                       "died", "adopted"})

EmitFn = Callable[[dict, "str | None", bool], None]


def _iso_epoch(s: Any) -> float | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s)).timestamp()
    except ValueError:
        return None


def job_snapshot(job_dir: Path, rec: dict[str, Any] | None = None,
                 now: float | None = None,
                 reference: Any = "auto") -> dict[str, Any] | None:
    """Read-only state of one detached job from its files (progress.json,
    job.lxt, job_a.res) and the registry record; None when the directory
    holds neither a progress record nor a log. Pure apart from file reads
    and a pid liveness check - never adopts, never waits. ``reference``:
    "auto" scans the sibling jobs for the search-time reference; a caller
    polling every few seconds passes the value it already has."""
    from ..refine.tools_shelxl import RunShelxt, _pid_alive, _read_json

    now = time.time() if now is None else now
    rec = rec or {}
    prog = _read_json(job_dir / "progress.json") or {}
    lxt = job_dir / "job.lxt"
    if not prog and not lxt.exists():
        return None
    txt = ""
    if lxt.exists():
        try:
            txt = lxt.read_text(encoding="utf-8", errors="replace")
        except OSError:
            txt = ""
    st = RunShelxt._lxt_status(txt)
    t0 = prog.get("started_at_epoch")
    pid = prog.get("pid") or rec.get("pid")
    has_solution = (job_dir / "job_a.res").exists()
    recorded_running = bool(prog.get("running"))
    stage = str(prog.get("stage") or rec.get("stage") or st["stage"])
    running = False
    if recorded_running:
        # progress.json says running: believe it only while the process
        # (the same one - pids get reused) is alive
        running = _pid_alive(pid, t0)
        if not running:
            stage = "finished" if (has_solution or st["finished"]) else "died"
    if running:
        stage = st["stage"] if (st.get("laue") or st.get("phased")) else (
            str(prog.get("stage") or "starting"))
        if prog.get("phasing_grace_granted_s") and not st["phased"]:
            stage = "phasing (grace)"
        elapsed = (now - float(t0)) if t0 else float(prog.get("elapsed_s") or 0.0)
    else:
        elapsed = float(prog.get("elapsed_s") or rec.get("elapsed_s") or 0.0)
        if stage == "running":          # registry record of a job whose
            stage = "finished" if has_solution else "died"   # watchdog is gone
    est = RunShelxt._phasing_estimate(st, elapsed,
                                      timeout_s=(prog.get("budget") or {}).get("timeout_s"))
    outlook = RunShelxt._search_outlook(job_dir.parent, job_dir, st, elapsed,
                                        reference=reference)
    finished_at = rec.get("finished_at") or (
        prog.get("updated_at") if not running else None)
    return {
        "job": job_dir.name, "job_dir": str(job_dir), "pid": pid,
        "stage": stage, "running": bool(running),
        "elapsed_s": round(float(elapsed), 1),
        "started_at": prog.get("started_at") or rec.get("started_at"),
        "started_at_epoch": (round(float(t0), 3) if t0 else None),
        "finished_at": finished_at,
        "laue": st.get("laue"),
        "tries_done": est["tries_done"], "best_cfom": est["best_cfom"],
        "passed_acceptance": est["passed_acceptance"],
        "phasing_finished": bool(st["phased"]),
        "phasing_s": st.get("phasing_s"),
        "n_space_groups": st.get("n_groups"),
        "auto_a": outlook["auto_a"],
        "exhaustive_search": outlook["exhaustive_search"],
        "search_elapsed_s": outlook["search_elapsed_s"],
        "search_reference": outlook["search_reference"],
        "search_grace_extended_s": prog.get("search_grace_extended_s"),
        "has_solution": bool(has_solution),
        "adopted_at": rec.get("adopted_at"),
        "error": prog.get("error") or rec.get("error"),
        "budget": prog.get("budget") or rec.get("budget"),
        "next": prog.get("next"),
    }


def job_event(snap: dict[str, Any], transition: str) -> dict[str, Any]:
    """The wire shape: one ``background_job`` event for a snapshot."""
    ev = {"kind": "background_job", "tool": "run_shelxt",
          "program": "SHELXT", "transition": transition}
    ev.update(snap)
    return ev


def _terminal(snap: dict[str, Any]) -> bool:
    return not snap["running"]


def _still_interesting(snap: dict[str, Any], now: float) -> bool:
    """Keep tracking? Running jobs always; a finished solution until it is
    adopted or stale; killed / failed / died jobs only briefly (their one
    persisted transition is the record)."""
    if snap["running"]:
        return True
    if snap.get("adopted_at"):
        return False
    fin = _iso_epoch(snap.get("finished_at"))
    age = (now - fin) if fin is not None else None
    if snap["has_solution"]:
        return age is None or age < TRACK_FINISHED_FOR_S
    return age is not None and age < 2 * HEARTBEAT_S


class BackgroundJobWatcher:
    """One per open project. ``emit(event, owner_thread_id, persist)`` is
    the only side effect; ``owner_hint()`` returns the thread id that is
    mid-turn right now (None when none or several), read when a job first
    appears."""

    def __init__(self, project_dir: Path, emit: EmitFn,
                 owner_hint: Callable[[], str | None] | None = None,
                 *, poll_running_s: float = POLL_RUNNING_S,
                 poll_idle_s: float = POLL_IDLE_S,
                 heartbeat_s: float = HEARTBEAT_S) -> None:
        self.project_dir = Path(project_dir)
        self.base_dir = self.project_dir / SHELXT_SUBDIR
        self._emit = emit
        self._owner_hint = owner_hint or (lambda: None)
        self.poll_running_s = float(poll_running_s)
        self.poll_idle_s = float(poll_idle_s)
        self.heartbeat_s = float(heartbeat_s)
        self._owner: dict[str, str | None] = {}
        self._last: dict[str, tuple] = {}        # job -> comparison key
        self._snap: dict[str, dict[str, Any]] = {}
        self._beat: dict[str, float] = {}
        self._ref: dict[str, Any] = {}           # job -> sibling search reference, read once
        self._dropped: set[str] = set()          # no longer interesting
        self._primed = False
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._loop, daemon=True,
            name=f"bg-jobs-{self.project_dir.name}")

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        # one synchronous pass first: /projects/open returns with the
        # snapshot already filled, so the transcript bootstrap that follows
        # at once carries a running or finished-unadopted job (a first poll
        # on the thread lost that race in the 2026-09-18 check)
        try:
            self.poll_once()
        except Exception:  # noqa: BLE001 - the loop retries
            pass
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    @property
    def running_jobs(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(s) for s in self._snap.values() if s["running"]]

    def snapshot_events(self) -> list[dict[str, Any]]:
        """Current state of every tracked job as live-only events - what a
        transcript bootstrap appends so a reload shows a job the transcript
        never recorded (server restart, or no turn owned it)."""
        with self._lock:
            snaps = [dict(s) for s in self._snap.values()]
        out = []
        for s in snaps:
            ev = job_event(s, "snapshot")
            ev["ts"] = time.time()
            out.append(ev)
        return out

    # -- polling -----------------------------------------------------------
    def _registry(self) -> list[dict[str, Any]]:
        from ..refine.tools_shelxl import SHELXT_JOBS_FILE, _read_json
        data = _read_json(self.base_dir / SHELXT_JOBS_FILE) or {}
        jobs = [j for j in (data.get("jobs") or []) if isinstance(j, dict)
                and isinstance(j.get("job"), str)]
        return jobs

    @staticmethod
    def _key(snap: dict[str, Any]) -> tuple:
        return (snap["stage"], snap["running"], snap["tries_done"],
                snap["phasing_finished"], snap["n_space_groups"],
                snap["has_solution"], bool(snap.get("adopted_at")),
                snap.get("error") is not None)

    @staticmethod
    def _transition(prev: dict[str, Any] | None, snap: dict[str, Any]) -> str:
        if prev is None:
            return "started" if snap["running"] else snap["stage"]
        if snap.get("adopted_at") and not prev.get("adopted_at"):
            return "adopted"
        if prev["running"] and not snap["running"]:
            return snap["stage"] if snap["stage"] in (
                "finished", "killed", "failed", "died") else "finished"
        return "stage"

    def poll_once(self, now: float | None = None) -> list[dict[str, Any]]:
        """One pass over the registry; returns the events emitted (tests
        drive this directly, the thread calls it in a loop)."""
        now = time.time() if now is None else now
        emitted: list[dict[str, Any]] = []
        if not self.base_dir.exists():
            return emitted
        try:
            recs = self._registry()
        except Exception:  # noqa: BLE001 - a torn write: try again next poll
            return emitted
        seen: set[str] = set()
        for rec in recs:
            name = rec["job"]
            if name in self._dropped:
                continue
            job_dir = self.base_dir / name
            try:
                snap = job_snapshot(job_dir, rec, now,
                                    reference=self._ref.get(name, "auto"))
            except Exception:  # noqa: BLE001 - never let one job kill the loop
                continue
            if snap is None:
                continue
            if name not in self._ref and snap["phasing_finished"]:
                # the sibling scan happens once per job, not every 3 s
                self._ref[name] = snap.get("search_reference")
            seen.add(name)
            first = name not in self._last
            if first and not self._primed and not snap["running"]:
                # jobs that were already over when this watcher started:
                # a finished solution waiting for adoption is shown (once,
                # live) so the user learns about it; a dead/killed job is
                # history and is left alone
                if not _still_interesting(snap, now) or not snap["has_solution"]:
                    self._dropped.add(name)
                    continue
            key = self._key(snap)
            prev = self._snap.get(name)
            if first:
                self._owner[name] = (self._owner_hint() if snap["running"]
                                     else None)
            transition: str | None = None
            if first or key != self._last.get(name):
                transition = self._transition(prev, snap)
            elif snap["running"] and now - self._beat.get(name, 0.0) >= self.heartbeat_s:
                transition = "heartbeat"
            with self._lock:
                self._snap[name] = snap
            self._last[name] = key
            if transition is not None:
                ev = job_event(snap, transition)
                ev["ts"] = now
                persist = transition in PERSISTED and self._owner.get(name) is not None
                # the first sighting of an already-finished job is live only:
                # no turn owns it and it is not new history
                if first and not snap["running"]:
                    persist = False
                self._beat[name] = now
                try:
                    self._emit(ev, self._owner.get(name), persist)
                except Exception:  # noqa: BLE001 - a dead channel must not stop the watcher
                    pass
                emitted.append(ev)
            if not _still_interesting(snap, now):
                self._dropped.add(name)
                with self._lock:
                    self._snap.pop(name, None)
        # jobs whose directory vanished (user cleanup) stop being tracked
        for name in list(self._snap):
            if name not in seen:
                with self._lock:
                    self._snap.pop(name, None)
                self._last.pop(name, None)
        self._primed = True
        return emitted

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.poll_once()
            except Exception:  # noqa: BLE001 - keep watching
                pass
            wait = self.poll_running_s if self.running_jobs else self.poll_idle_s
            self._stop.wait(wait)
