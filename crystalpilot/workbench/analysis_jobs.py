"""Bounded, read-only progressive analysis jobs for HTTP polling.

Importing this module starts no threads and imports no scientific engines.
The server must call mcp.prewarm.prewarm_heavy_imports on its main thread
before submitting uncached work. One executor worker limits concurrent heavy
calculations. Each start attaches an observer to a shared project/node job;
cancelling one observer cannot cancel another observer's work.

shutdown(wait=False) cancels queued work and requests cooperative cancellation
between stages. It does NOT interrupt a running C routine. Python's executor
threads are joined at interpreter exit, so final process exit may still wait
for that routine; use wait=True when the caller can wait for a clean drain.
"""
from __future__ import annotations

import copy
import os
import threading
import time
import uuid
from collections import OrderedDict, deque
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


TERMINAL_STATUSES = frozenset({"ready", "partial", "error", "cancelled"})


class AnalysisQueueFull(RuntimeError):
    """The bounded pending-job or observer capacity has been reached."""


def _project_key(project: str | Path) -> str:
    return os.path.normcase(str(Path(project).resolve()))


def _ensure_prewarmed() -> None:
    from ..mcp.prewarm import (HEAVY_MODULES, PRELOOP_MODULES, is_prewarmed,
                               prewarm_heavy_imports)

    # Direct main-thread users share exactly the server's idempotent contract.
    # A request/worker thread must never be the first DLL importer.
    if threading.current_thread() is threading.main_thread():
        report = prewarm_heavy_imports()
        if not report.get("failed"):
            return
    missing = [name for name in PRELOOP_MODULES + HEAVY_MODULES
               if not is_prewarmed(name)]
    if missing:
        raise RuntimeError(
            "Analysis engines are not prewarmed; call prewarm_heavy_imports() "
            "on the server's main thread before starting jobs. Missing: "
            + ", ".join(missing))


def _result_status(result: dict[str, Any]) -> str:
    states = [state["status"] for state in result["stages"].values()]
    if "cancelled" in states:
        return "cancelled"
    if all(state == "ready" for state in states):
        return "ready"
    if "error" in states and not any(state == "ready" for state in states):
        return "error"
    return "partial"


@dataclass
class _Job:
    job_id: str
    project_key: str
    node: str
    analysis: Any
    result: dict[str, Any]
    created_at: float = field(default_factory=time.monotonic)
    status: str = "queued"
    revision: int = 1
    result_revision: int = 1
    cache_hit: bool = False
    finished_at: float | None = None
    stage_started: dict[str, float] = field(default_factory=dict)
    observers: set[str] = field(default_factory=set)
    cancelled: threading.Event = field(default_factory=threading.Event)
    future: Future | None = None
    cache_error: str | None = None


class AnalysisJobManager:
    """Single flight by canonical project directory and resolved node ID.

    start/poll/cancel return independent deep copies, safe for serialization
    after the manager lock is released. Revisions advance on state changes;
    result_revision advances only when the staged product changes, not when an
    observer attaches or live elapsed durations advance. Conditional polls can
    omit the large result while always returning current stage metadata.
    Finished retention is completion-ordered, including failed/cancelled jobs.
    Evicted IDs and IDs belonging to another project both raise KeyError.
    """

    def __init__(self, *, max_finished: int = 32, max_pending: int = 32,
                 max_observers: int = 128) -> None:
        if min(max_finished, max_pending, max_observers) < 1:
            raise ValueError("analysis job limits must be positive")
        self.max_finished = max_finished
        self.max_pending = max_pending
        self.max_observers = max_observers
        self._lock = threading.RLock()
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="crystalpilot-analysis")
        self._jobs: dict[str, _Job] = {}
        self._by_node: dict[tuple[str, str], str] = {}
        self._finished: OrderedDict[str, None] = OrderedDict()
        self._pending: deque[_Job] = deque()
        self._dispatching = False
        self._closed = False

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    def start(self, project: str | Path, node: str = "active", *,
              observer_id: str | None = None) -> dict[str, Any]:
        """Attach to or start a job. Retain observer_id for explicit cancellation.

        An optional existing observer_id makes a repeated attachment idempotent.
        Polling does not attach another observer. Browser disconnects need not
        call cancel; successful shared jobs are retained only up to the bound.
        """
        from ..refine.analysis import AnalysisStages, cacheable_analysis

        analysis = AnalysisStages(project, node)
        key = (_project_key(project), analysis.node)
        with self._lock:
            if self._closed:
                raise RuntimeError("analysis job manager is shut down")
            existing = self._jobs.get(self._by_node.get(key, ""))
            if existing is not None:
                if existing.status == "cancelling":
                    raise RuntimeError("analysis cancellation is pending; poll before restarting")
                if (existing.status not in TERMINAL_STATUSES
                        or cacheable_analysis(existing.result)):
                    return self._attach(existing, observer_id)
            cached = analysis.cached_result()
            if cached is None:
                pending = sum(job.finished_at is None for job in self._jobs.values())
                if pending >= self.max_pending:
                    raise AnalysisQueueFull("analysis pending-job capacity reached")
                _ensure_prewarmed()
            job = _Job(job_id=uuid.uuid4().hex, project_key=key[0],
                       node=analysis.node, analysis=analysis,
                       result=cached if cached is not None else analysis.empty_result(),
                       cache_hit=cached is not None)
            self._jobs[job.job_id] = job
            self._by_node[key] = job.job_id
            if cached is not None:
                self._finish(job, _result_status(cached))
            else:
                job.future = Future()
                self._pending.append(job)
                if not self._dispatching:
                    self._dispatching = True
                    try:
                        self._executor.submit(self._drain)
                    except BaseException:
                        self._dispatching = False
                        self._pending.remove(job)
                        self._jobs.pop(job.job_id, None)
                        self._by_node.pop(key, None)
                        raise
            return self._attach(job, observer_id)

    def poll(self, project: str | Path, job_id: str, *,
             since_result_revision: int | None = None) -> dict[str, Any]:
        """Return result=None when that job's product revision is unchanged.

        The client retains its previous result in that case, but replaces stage
        metadata/status/durations from every response. Omit the revision to
        request a full snapshot; a mismatched revision also returns the result.
        """
        with self._lock:
            return self._snapshot(self._lookup(project, job_id),
                                  since_result_revision=since_result_revision)

    def cancel(self, project: str | Path, job_id: str,
               observer_id: str) -> dict[str, Any]:
        """Detach this observer, cancelling pending work only after the last one.

        A cancelling job still has a running engine: the running stage remains
        running until it returns. No browser is permitted to force-stop that
        engine or to cancel on behalf of all observers.
        """
        with self._lock:
            job = self._lookup(project, job_id)
            if observer_id not in job.observers:
                raise KeyError("unknown analysis observer")
            job.observers.remove(observer_id)
            job.revision += 1
            if not job.observers and job.finished_at is None:
                self._request_cancel(job)
            return self._snapshot(job)

    def release(self, project: str | Path, job_id: str,
                observer_id: str) -> dict[str, Any]:
        """Stop observing without cancelling a reusable background computation."""
        with self._lock:
            job = self._lookup(project, job_id)
            if observer_id in job.observers:
                job.observers.remove(observer_id)
                job.revision += 1
            return self._snapshot(job, since_result_revision=job.result_revision)

    def shutdown(self, wait: bool = False) -> None:
        """Reject new work and cancel queued/pending stages, never live C calls."""
        with self._lock:
            self._closed = True
            for job in list(self._jobs.values()):
                if job.finished_at is None:
                    self._request_cancel(job)
        self._executor.shutdown(wait=wait, cancel_futures=True)

    def _attach(self, job: _Job, observer_id: str | None) -> dict[str, Any]:
        observer = observer_id or uuid.uuid4().hex
        if observer not in job.observers:
            if len(job.observers) >= self.max_observers:
                raise AnalysisQueueFull("analysis observer capacity reached")
            job.observers.add(observer)
            job.revision += 1
        snapshot = self._snapshot(job)
        snapshot["observer_id"] = observer
        return snapshot

    def _lookup(self, project: str | Path, job_id: str) -> _Job:
        job = self._jobs.get(job_id)
        if job is None or job.project_key != _project_key(project):
            raise KeyError("unknown analysis job")
        return job

    def _snapshot(self, job: _Job, *,
                  since_result_revision: int | None = None) -> dict[str, Any]:
        now = job.finished_at if job.finished_at is not None else time.monotonic()
        stages = copy.deepcopy(job.result["stages"])
        for stage, started in job.stage_started.items():
            if stages[stage]["status"] == "running":
                stages[stage]["elapsed_s"] = round(now - started, 3)
        result = None
        if since_result_revision != job.result_revision:
            result = copy.deepcopy(job.result)
            result["stages"] = copy.deepcopy(stages)
        return {
            "job_id": job.job_id, "node": job.node,
            "source_revision": job.result.get("source_revision"),
            "status": job.status, "revision": job.revision,
            "result_revision": job.result_revision,
            "elapsed_s": round(now - job.created_at, 3),
            "cache_hit": job.cache_hit, "cache_error": job.cache_error,
            "cancellation_requested": job.cancelled.is_set(),
            "observers": len(job.observers), "stages": stages, "result": result,
        }

    def _request_cancel(self, job: _Job) -> None:
        from ..refine.analysis import apply_analysis_update

        job.cancelled.set()
        job.status = "cancelling"
        job.revision += 1
        for stage, state in list(job.result["stages"].items()):
            if state["status"] == "waiting":
                apply_analysis_update(job.result, {
                    "stage": stage, "status": "cancelled", "elapsed_s": 0.0,
                    "error": None, "note": "已取消，未开始计算", "value": None,
                })
                job.result_revision += 1
        if job.future is not None and job.future.cancel():
            self._pending.remove(job)
            self._finish(job, "cancelled")

    def _drain(self) -> None:
        # Keep only a single dispatcher in the executor's unbounded work queue.
        # Cancelled jobs are removed from OUR bounded queue immediately, rather
        # than accumulating executor work items behind a long-running C call.
        while True:
            with self._lock:
                if not self._pending:
                    self._dispatching = False
                    return
                job = self._pending.popleft()
                if not job.future.set_running_or_notify_cancel():
                    continue
            try:
                self._run(job)
            finally:
                job.future.set_result(None)

    def _finish(self, job: _Job, status: str) -> None:
        job.status = status
        job.finished_at = time.monotonic()
        job.analysis = None
        job.revision += 1
        self._finished[job.job_id] = None
        while len(self._finished) > self.max_finished:
            expired, _ = self._finished.popitem(last=False)
            old = self._jobs.pop(expired)
            key = (old.project_key, old.node)
            if self._by_node.get(key) == expired:
                self._by_node.pop(key)

    def _run(self, job: _Job) -> None:
        from ..refine.analysis import (apply_analysis_update, cacheable_analysis,
                                       iter_analysis_stages)

        analysis = job.analysis
        try:
            with self._lock:
                if not job.cancelled.is_set():
                    job.status = "running"
                    job.revision += 1
            for update in iter_analysis_stages(analysis, cancelled=job.cancelled.is_set):
                with self._lock:
                    if update["status"] == "running":
                        if job.cancelled.is_set():
                            continue
                        job.stage_started[update["stage"]] = time.monotonic()
                    apply_analysis_update(job.result, update)
                    job.result_revision += 1
                    job.revision += 1
            with self._lock:
                product = (copy.deepcopy(job.result)
                           if not job.cancelled.is_set() and cacheable_analysis(job.result)
                           else None)
            if product is not None:
                try:
                    analysis.save(product)
                except Exception as exc:  # noqa: BLE001 - cache is not the result
                    with self._lock:
                        job.cache_error = f"{type(exc).__name__}: {exc}"
                        job.revision += 1
        except Exception as exc:  # noqa: BLE001 - leave a pollable terminal job
            with self._lock:
                for stage, state in list(job.result["stages"].items()):
                    if state["status"] in {"waiting", "running"}:
                        apply_analysis_update(job.result, {
                            "stage": stage, "status": "error", "elapsed_s": 0.0,
                            "error": f"{type(exc).__name__}: {exc}",
                            "note": "分析任务失败", "value": None,
                        })
                        job.result_revision += 1
        finally:
            with self._lock:
                status = "cancelled" if job.cancelled.is_set() else _result_status(job.result)
                self._finish(job, status)


# No thread starts until the first uncached start(); the server owns shutdown.
analysis_jobs = AnalysisJobManager()
