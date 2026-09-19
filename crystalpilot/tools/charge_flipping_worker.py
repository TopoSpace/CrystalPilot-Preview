"""Owned worker process and wall-clock supervisor for charge flipping."""

from __future__ import annotations

import json
import os
import pickle
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

from ..procutil import hidden_popen_kwargs
from .base import ToolContext, ToolResult
from .budget import budget_for

CLEANUP_GRACE_S = 2.0


def _worker_command(directory: Path):
    return [sys.executable, "-m", "crystalpilot.tools.charge_flipping_worker", str(directory)]


def _read_progress(directory):
    try:
        return json.loads((directory / "progress.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"stage": "worker startup", "attempt_table": []}


def _stop_owned_worker(process):
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=0.5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=CLEANUP_GRACE_S - 0.5)


def run_supervised(ctx, params):
    """Only completed output is published to the caller's session."""
    result = None
    cf_info = None
    stopped = None
    process = None
    progress = {"stage": "input serialization", "attempt_table": []}
    with budget_for(ctx, "solve_charge_flipping", params) as budget:
        with tempfile.TemporaryDirectory(prefix="crystalpilot-cf-") as name:
            directory = Path(name)
            ses = ctx.session
            if ses.fo_sq is None:
                return ToolResult.failure("no merged data; set a working space group first")
            from ..chem.solvability import _session_elements

            elements, source = _session_elements(ses)
            payload = {
                "fo_sq": ses.fo_sq,
                "symmetry": ses.symmetry,
                "composition": ses.dataset.composition,
                "elements": elements,
                "elements_source": source,
                "params": params,
            }
            (directory / "input.pkl").write_bytes(
                pickle.dumps(payload, protocol=pickle.HIGHEST_PROTOCOL)
            )
            try:
                stopped = budget.stop_reason()
                if not stopped:
                    # A native initialization/FFT/peak-search may not yield to
                    # Python. Its separate process is the interruption boundary.
                    with (directory / "worker.log").open("wb") as log:
                        env = dict(os.environ)
                        env["PYTHONUTF8"] = "1"
                        process = subprocess.Popen(
                            _worker_command(directory),
                            stdin=subprocess.DEVNULL,
                            stdout=log,
                            stderr=log,
                            env=env,
                            **hidden_popen_kwargs(),
                        )
                        while process.poll() is None:
                            progress = _read_progress(directory)
                            budget.last_stage = progress.get("stage", "worker computation")
                            stopped = budget.stop_reason()
                            if stopped:
                                break
                            budget.tick(budget.last_stage)
                            try:
                                process.wait(timeout=min(0.05, max(0.001, budget.remaining())))
                            except subprocess.TimeoutExpired:
                                pass
                        stopped = stopped or budget.stop_reason()
                        if not stopped:
                            progress = _read_progress(directory)
                            budget.last_stage = progress.get("stage", "result decoding")
                            output = directory / "output.pkl"
                            if process.returncode == 0 and output.exists():
                                result, cf_info = pickle.loads(output.read_bytes())
                            else:
                                result = ToolResult.failure(
                                    "charge-flipping worker failed before completing its result"
                                )
                                result.summary["worker_exit_code"] = process.returncode
                                result.summary["stage"] = _read_progress(directory).get("stage")
                                result.summary["worker_error"] = (
                                    directory / "worker.log"
                                ).read_text(errors="replace")[-1500:]
                if stopped:
                    budget.stopped_by = stopped
                    _stop_owned_worker(process)
                    progress = _read_progress(directory)
                    result = ToolResult(
                        ok=False,
                        error=(
                            "solve_charge_flipping cancelled by the caller"
                            if stopped == "cancelled"
                            else "solve_charge_flipping stopped at its total computation budget"
                        )
                        + "; incomplete worker output was discarded and the session is unchanged",
                        summary={
                            "timed_out": stopped == "timeout",
                            "cancelled": stopped == "cancelled",
                            "stage": progress.get("stage"),
                            "solution_capability": progress.get("solution_capability"),
                            "attempt_table": progress.get("attempt_table", []),
                            "worker_terminated": process is not None,
                        },
                    )
            finally:
                _stop_owned_worker(process)
        # Cleanup time is reported as well. Only small temporary input/output
        # files are removed here; worker termination gets a fixed grace period.
        if result is None:
            result = ToolResult.failure("charge-flipping worker returned no result")
        result.summary["budget"] = {
            **budget.report(),
            "cleanup_grace_s": CLEANUP_GRACE_S,
            "coverage": "tool input serialization, worker startup, preprocessing, initialization, every native iteration, Fourier/peak extraction and result decoding; at most 2s additional worker cleanup; project-lock queue wait excluded",
        }
        result.summary["elapsed_s"] = round(budget.elapsed(), 3)
        if result.ok and budget.stop_reason():
            result = ToolResult(
                ok=False,
                error="charge-flipping budget expired before result publication; session unchanged",
                summary={
                    **result.summary,
                    "timed_out": budget.stop_reason() == "timeout",
                    "cancelled": budget.stop_reason() == "cancelled",
                },
            )
        if result.ok:
            cf_info["elapsed_s"] = result.summary["elapsed_s"]
            ctx.session.cf_info = cf_info
        return result


def main(directory):
    directory = Path(directory)
    last_write = 0.0
    capability = None

    def progress(stage, table=None):
        nonlocal last_write
        now = time.monotonic()
        if now - last_write < 0.1 and stage.startswith("seed "):
            return
        last_write = now
        temporary = directory / "progress.tmp"
        temporary.write_text(
            json.dumps(
                {"stage": stage, "attempt_table": table or [], "solution_capability": capability}
            ),
            encoding="utf-8",
        )
        os.replace(temporary, directory / "progress.json")

    progress("worker imports")
    # Import numerical libraries in the worker, inside the supervised budget.
    from ..chem import solvability
    from .solution_tools import ChargeFlippingSolve, solver_capability

    payload = pickle.loads((directory / "input.pkl").read_bytes())
    ses = SimpleNamespace(
        fo_sq=payload["fo_sq"],
        symmetry=payload["symmetry"],
        dataset=SimpleNamespace(composition=payload["composition"]),
        cf_info={},
        flags={},
        model=None,
    )
    ctx = ToolContext(store=None, session=ses)
    ctx.solver_progress = progress
    progress("capability and input checks")
    params = payload["params"]
    block = solver_capability(
        ses,
        float(params.get("d_min", 1)),
        "d_min truncation this call flips at",
        elements=payload["elements"],
        elements_source=payload["elements_source"],
    )
    capability = block
    result = solvability.attach(ChargeFlippingSolve()._run(ctx, **params), block)
    progress("result serialization", result.summary.get("attempt_table"))
    (directory / "output.pkl").write_bytes(
        pickle.dumps((result, ses.cf_info), protocol=pickle.HIGHEST_PROTOCOL)
    )


if __name__ == "__main__":
    main(sys.argv[1])
