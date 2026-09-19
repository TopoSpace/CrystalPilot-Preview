"""Execution-aware checkCIF records; a failed check is not zero alerts."""
from __future__ import annotations

from typing import Any


def report_issue(report: Any) -> str | None:
    if not isinstance(report, dict):
        return "checkcif.json is not a report object"
    execution = report.get("execution_status")
    if execution is not None and execution != "completed":
        return f"checkCIF execution {execution}: {report.get('error') or 'no complete report'}"
    status = report.get("report_status")
    if status is not None and status != "complete":
        return f"checkCIF report is {status}, not complete"
    if report.get("ok") is False:
        return "checkCIF execution failed"
    counts, alerts = report.get("counts"), report.get("alerts")
    if not isinstance(counts, dict) or not isinstance(alerts, list):
        return "checkCIF alert counts are unknown"
    for level in "ABCG":
        count = counts.get(level)
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            return "checkCIF alert counts are incomplete or invalid"
        if any(not isinstance(a, dict) for a in alerts):
            return "checkCIF alert rows are invalid"
        if count != sum(a.get("level") == level for a in alerts):
            return "checkCIF alert counts disagree with the full report"
    if any(a.get("level") not in ("A", "B", "C", "G") or not a.get("code") for a in alerts):
        return "checkCIF alert rows are invalid"
    return None
