"""Explicit node and delivery versions, not file-integrity assertions."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def read_delivery_report(directory: Path) -> dict[str, Any]:
    try:
        report = json.loads((directory / "REPORT.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return report if isinstance(report, dict) else {}


def next_delivery_revision(directory: Path) -> int:
    previous = read_delivery_report(directory).get("delivery_revision")
    return previous + 1 if isinstance(previous, int) and not isinstance(previous, bool) and previous > 0 else 1


def validation_source(cif: Path, *, node: str | None = None,
                      revision: int | None = None) -> dict[str, Any]:
    """Bind a report to the file/version that was actually submitted.

    A standalone CIF is not silently attributed to the active model. Manual
    external edits are outside version tracking and require a fresh import/check.
    """
    cif = cif.resolve()
    source: dict[str, Any] = {"kind": "file", "target": str(cif),
                              "node": None, "revision": None,
                              "delivery_revision": None}
    if cif.name.lower() == "final.cif":
        report = read_delivery_report(cif.parent)
        if report.get("final_node"):
            state = report.get("source_state") or {}
            source.update(kind="delivery", node=report["final_node"],
                          revision=state.get("revision"),
                          delivery_revision=report.get("delivery_revision"))
    elif node is not None:
        source.update(kind="node", node=node, revision=revision)
    return source


def delivery_source_issue(out: Path, report: dict[str, Any],
                          check: dict[str, Any]) -> str | None:
    """A mismatched/unknown version is not evidence for this delivery."""
    source = check.get("source")
    if not isinstance(source, dict):
        return ("checkcif.json has no node/delivery version recorded; its source is unknown "
                "- re-run run_checkcif(cif=<dir>/final.cif)")
    expected = out.resolve() / "final.cif"
    try:
        same_target = Path(str(source.get("target") or "")).resolve() == expected
    except (OSError, ValueError):
        same_target = False
    state = report.get("source_state") or {}
    current = report.get("delivery_revision")
    if (source.get("kind") != "delivery" or not same_target
            or source.get("node") != report.get("final_node")
            or not isinstance(current, int) or isinstance(current, bool) or current < 1
            or source.get("delivery_revision") != current
            or source.get("revision") != state.get("revision")):
        return ("checkcif.json belongs to a different final.cif or delivery revision "
                "- re-run run_checkcif(cif=<dir>/final.cif)")
    return None
