"""Bounded, local PLATON execution with durable diagnostics and strict completion."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from ..tools.budget import Budget, BudgetStop
from .checkcif_process import CheckcifProcess

POLL_S = 0.2
STABLE_S = 2.0
OUTPUTS = ("model.chk", "model.ckf", "model.vrf", "model.ps", "platon.out",
           "stdout.log", "stderr.log")
ALERT = re.compile(r"\s*(?:PLAT)?(\d{3}|[A-Z]{2,6}\d{2})_ALERT_(\d)_([ABCG])\s+(.*)")


def parse_alerts(text: str) -> list[dict[str, Any]]:
    from ..report.checkcif_kb import annotate
    alerts = []
    continuation = False
    for line in text.splitlines():
        match = ALERT.match(line)
        if match:
            code, kind, level, message = match.groups()
            alert = {"code": code, "type": int(kind), "level": level, "text": message.strip()}
            kb = annotate(code)
            if kb:
                alert["kb"] = kb
            alerts.append(alert)
            continuation = True
        elif continuation and line.startswith("              ") and line.strip():
            # Reflection/atom lists on following lines are part of the alert.
            alerts[-1]["text"] += "\n" + line.strip()
        else:
            continuation = False
    return alerts


def complete_report(text: str, log: str) -> bool:
    """Require PLATON's own report summary and end-of-output notification.

    An idle writer or a zero exit code alone proves nothing. Counts are checked
    against actual rows, including type-1 metadata alerts, for every entry.
    """
    entries = len(re.findall(r"(?m)^#\s*PLATON/CHECK-", text))
    if not entries or not re.search(r"CheckCIF out on\s*:\s*model\.chk", log):
        return False
    for block in re.split(r"(?m)^#\s*PLATON/CHECK-", text)[1:]:
        alerts = parse_alerts(block)
        # Current native UNIX PLATON omits zero-count summary rows. Only
        # accept that format with the full summary/footer and independently
        # matching type counts; missing nonzero counts still fail closed.
        type_counts = re.findall(r"(?m)^\s*(\d+)\s+ALERT_Type_\d\s", block)
        compact_summary = (
            "ALERT_Level and ALERT_Type Summary" in block
            and "Unresolved or to be Checked Issue(s)" in block
            and sum(map(int, type_counts)) == len(alerts)
        )
        for level in "ABCG":
            counts = re.findall(rf"(?m)^\s*(\d+)\s+ALERT_Level_{level}\s*=", block)
            actual = sum(a["level"] == level for a in alerts)
            if not counts and compact_summary and actual == 0:
                continue
            if len(counts) != 1 or int(counts[0]) != actual:
                return False
    return True


def _text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _tail(path: Path, limit: int = 4096) -> str:
    try:
        with path.open("rb") as stream:
            stream.seek(0, 2)
            stream.seek(max(0, stream.tell() - limit))
            return stream.read(limit).decode("utf-8", errors="replace").replace("\x00", "").strip()
    except OSError:
        return ""


def _signature(job: Path) -> tuple:
    values = []
    for name in OUTPUTS:
        try:
            stat = (job / name).stat()
            values.append((name, stat.st_size, stat.st_mtime_ns))
        except FileNotFoundError:
            pass
    return tuple(values)


def run_platon(job: Path, exe: Path, shelxl: Path, budget: Budget) -> dict[str, Any]:
    result: dict[str, Any] = {"execution_status": "failed", "report_status": "missing",
                              "exit_code": None, "cleanup_complete": True,
                              "engine": {"platon": str(exe), "shelxl": str(shelxl)}}
    process = None
    runtime = None
    archive = job
    try:
        budget.ping("preparing local validation; alert counts remain unknown until completion")
        budget.check("preparing local PLATON")
        if not exe.is_file():
            result["failure_reason"] = "executable_missing"
            raise FileNotFoundError(f"platon.exe not found at {exe}")
        env = dict(os.environ)
        result["shelxl_exposed"] = shelxl.is_file()
        # WinPLATON resolves SHELXL through PATH into a fixed-length buffer.
        # Its file I/O also fails for long working directories. Stage both
        # binaries and inputs physically short, even when the project is long.
        runtime = tempfile.TemporaryDirectory(prefix="cc-", dir=os.environ.get(
            "CRYSTALPILOT_CHECKCIF_RUNTIME_ROOT"))
        job = binary_dir = Path(runtime.name)
        result["runtime_path"] = str(job)
        if os.name == "nt" and len(str(binary_dir / "shelxl.exe")) > 80:
            result["failure_reason"] = "runtime_path_too_long"
            raise OSError("PLATON requires a short runtime path; set "
                          "CRYSTALPILOT_CHECKCIF_RUNTIME_ROOT to a short writable directory")
        for suffix in (".cif", ".fcf", ".res", ".hkl", ".fab"):
            source = archive / ("model" + suffix)
            if source.is_file():
                shutil.copy2(source, job / source.name)
        if shelxl.is_file():
            shutil.copy2(shelxl, binary_dir / "shelxl.exe")
            for dll in shelxl.parent.glob("*.dll"):
                shutil.copy2(dll, binary_dir / dll.name)
            env["SHLEXE"] = "shelxl.exe"
            env["PATH"] = str(binary_dir) + os.pathsep + env.get("PATH", "")
        else:
            env.pop("SHLEXE", None)
        budget.check("starting PLATON")
        with (job / "stdout.log").open("wb") as stdout, (job / "stderr.log").open("wb") as stderr:
            process = CheckcifProcess([str(exe.resolve()), "-u", "model.cif"], cwd=str(job),
                                     stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, env=env)
            result["pid"] = process.pid
            budget.ping(f"PLATON running (owned PID {process.pid}); budget {budget.timeout_s:g}s")
            stable_since, signature = time.monotonic(), None
            budget.ping_s = 5.0
            while True:
                current = _signature(job)
                if current != signature:
                    signature, stable_since = current, time.monotonic()
                chk = _text(job / "model.chk")
                # WinPLATON writes platon.out; native UNIX writes stdout.
                log = _tail(job / "platon.out") + "\n" + _tail(job / "stdout.log")
                budget.check("PLATON: report present, checking completeness" if chk else
                             "PLATON: waiting for report; diagnostics captured")
                code = process.poll()
                result["exit_code"] = code
                if code not in (None, 0):
                    result.update(failure_reason="process_exit_error", error=f"PLATON exited with code {code}")
                    break
                if re.search(r"Executable .* not found!", log, re.IGNORECASE):
                    result.update(failure_reason="launcher_error", error=log)
                    break
                if complete_report(chk, log) and time.monotonic() - stable_since >= STABLE_S:
                    # Cancellation wins over a just-finished report.
                    budget.check("publishing complete PLATON report")
                    result.update(execution_status="completed", report_status="complete",
                                  completion_reason="stable_report_and_platon_completion_marker")
                    break
                if not process.active() and not complete_report(chk, log):
                    result.update(failure_reason="process_exit_partial_report" if chk else
                                  "process_exit_no_report", error="PLATON exited without a complete .chk report")
                    break
                time.sleep(min(POLL_S, max(0.0, budget.remaining())))
    except BudgetStop as error:
        result.update(execution_status=budget.stopped_by or "failed", error=str(error))
        result["failure_reason"] = ("cancelled" if budget.stopped_by == "cancelled" else
                                    "timeout_partial_report" if _text(job / "model.chk") else
                                    "timeout_no_report")
    except Exception as error:  # noqa: BLE001 - persist all execution failures
        result.setdefault("failure_reason", "execution_error")
        result["error"] = f"{type(error).__name__}: {error}"
    finally:
        if process is not None:
            try:
                result["cleanup_complete"] = process.close()
            except Exception as error:  # noqa: BLE001 - never hide failed tree cleanup
                result["cleanup_complete"] = False
                result["cleanup_error"] = f"{type(error).__name__}: {error}"
            if not result["cleanup_complete"]:
                result.update(execution_status="failed", failure_reason="cleanup_failed",
                              error="Could not confirm shutdown of the owned PLATON process tree")
        if result["execution_status"] != "completed":
            result["report_status"] = "partial" if _text(job / "model.chk") else "missing"
        if runtime is not None:
            try:
                for name in (*OUTPUTS, "model.fcf", "model.lst", "model.lis"):
                    if (job / name).is_file():
                        shutil.copy2(job / name, archive / name)
            except OSError as error:
                result.update(execution_status="failed", report_status="partial", failure_reason="artifact_error",
                              error=f"Could not preserve PLATON output: {error}")
            finally:
                try:
                    runtime.cleanup()
                except OSError as error:
                    result.update(execution_status="failed", failure_reason="runtime_cleanup_failed",
                                  error=f"Could not remove private PLATON runtime: {error}")
        job = archive
        result["elapsed_s"] = round(budget.elapsed(), 3)
        result["timeout_s"] = budget.timeout_s
        result["diagnostics"] = {name: _tail(job / name) for name in
                                 ("platon.out", "stdout.log", "stderr.log")}
        result["engine"]["report_header"] = _text(job / "model.chk").splitlines()[:6]
        budget.ping(f"{result['execution_status']} after {result['elapsed_s']:.1f}s; "
                    f"report {result['report_status']}; owned tree cleaned={result['cleanup_complete']}")
    return result
