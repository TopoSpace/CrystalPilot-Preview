"""Round-3 WP7: the investigation record - goal, success tiers, what was
ruled out, what is still open.

The live-demo Zr-MOF (2026-09-05) twice prepared to end with a diagnostic
delivery after a route failed, and twice a human had to push: "the goal
is the whole guest, not this pose". The agent had no object to hold the
goal apart from the current hypothesis, so a failed configuration read as
a failed task. This file is that object:

    goal                 what the study is trying to establish (one line)
    success_tiers        candidate_complete         - a whole-feature
                                                      candidate is in the
                                                      model and refines
                                                      stably (not yet a
                                                      structure claim)
                         scientifically_established - it survives the
                                                      independent tests
                                                      and checkCIF is
                                                      explainable
    budget               free-form limits the agent set itself
    ruled_out[]          configurations rejected WITH the evidence + node
    open_directions[]    routes not yet tried
    updated / history    audit trail of edits (tool call, node, time)

`situation_report` reads it (open_items.investigation), `finalize_delivery`
writes the unmet tiers and the open directions of a *diagnostic* delivery
into open_items, and refuses a diagnostic seal only when neither this
record nor an `unmet_goals` parameter says what was not achieved. A final
promotion is not gated by it.

File: <project>/.crystalpilot/refine/investigation.json (atomic replace,
a damaged file reads as empty).
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from ..tools.base import ToolContext, ToolResult
from .toolbase import _ProjectTool

INVESTIGATION_RELPATH = Path(".crystalpilot") / "refine" / "investigation.json"

TIERS = ("candidate_complete", "scientifically_established")
TIER_MEANING = {
    "candidate_complete": (
        "a whole-molecule (whole-feature) candidate is in the model and "
        "refines stably - a candidate, not yet a structure claim"),
    "scientifically_established": (
        "the candidate survives the independent tests (density integration, "
        "free-occupancy refinement, constraint removal) and every checkCIF "
        "alert it causes is explainable"),
}
TIER_STATUSES = ("unmet", "met", "not_applicable")
MAX_HISTORY = 60


def investigation_path(project_dir) -> Path:
    return Path(project_dir) / INVESTIGATION_RELPATH


def empty() -> dict[str, Any]:
    return {
        "schema": 1,
        "goal": "",
        "success_tiers": {t: {"status": "unmet", "evidence": ""} for t in TIERS},
        "budget": {},
        "ruled_out": [],
        "open_directions": [],
        "updated": None,
        "history": [],
    }


def load(project_dir) -> dict[str, Any]:
    """The record merged over defaults; missing or damaged -> empty."""
    base = empty()
    try:
        raw = json.loads(investigation_path(project_dir).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return base
    except (OSError, ValueError, UnicodeDecodeError):
        return base
    if not isinstance(raw, dict):
        return base
    out = dict(base)
    out["goal"] = str(raw.get("goal") or "")
    tiers = raw.get("success_tiers") if isinstance(raw.get("success_tiers"), dict) else {}
    for t in TIERS:
        v = tiers.get(t)
        if isinstance(v, dict):
            st = str(v.get("status") or "unmet")
            out["success_tiers"][t] = {
                "status": st if st in TIER_STATUSES else "unmet",
                "evidence": str(v.get("evidence") or "")}
        elif isinstance(v, str) and v in TIER_STATUSES:
            out["success_tiers"][t] = {"status": v, "evidence": ""}
    out["budget"] = raw.get("budget") if isinstance(raw.get("budget"), dict) else {}
    out["ruled_out"] = [r for r in (raw.get("ruled_out") or [])
                        if isinstance(r, dict)]
    out["open_directions"] = [str(d) for d in (raw.get("open_directions") or [])
                              if str(d).strip()]
    out["updated"] = raw.get("updated")
    out["history"] = [h for h in (raw.get("history") or []) if isinstance(h, dict)]
    return out


def save(project_dir, inv: dict[str, Any]) -> Path:
    p = investigation_path(project_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".investigation.", suffix=".tmp",
                               dir=str(p.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(inv, fh, indent=1, ensure_ascii=False, default=str)
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return p


def is_set(inv: dict[str, Any] | None) -> bool:
    """Has anyone written anything into the record?"""
    if not inv:
        return False
    if (inv.get("goal") or "").strip():
        return True
    for v in (inv.get("success_tiers") or {}).values():
        if isinstance(v, dict) and (v.get("status") != "unmet"
                                    or (v.get("evidence") or "").strip()):
            return True
    return bool(inv.get("ruled_out") or inv.get("open_directions")
                or inv.get("budget"))


def unmet_tiers(inv: dict[str, Any]) -> list[str]:
    return [t for t in TIERS
            if (inv.get("success_tiers") or {}).get(t, {}).get("status", "unmet")
            == "unmet"]


def summary_block(inv: dict[str, Any]) -> dict[str, Any]:
    """The compact reading situation_report / finalize_delivery carry."""
    tiers = {t: (inv.get("success_tiers") or {}).get(t, {}).get("status", "unmet")
             for t in TIERS}
    ruled = inv.get("ruled_out") or []
    return {
        "goal": inv.get("goal") or "",
        "tiers": tiers,
        "tier_evidence": {t: (inv.get("success_tiers") or {}).get(t, {}).get("evidence", "")
                          for t in TIERS
                          if (inv.get("success_tiers") or {}).get(t, {}).get("evidence")},
        "unmet_tiers": unmet_tiers(inv),
        "n_ruled_out": len(ruled),
        "ruled_out": [{"what": r.get("what"), "evidence": r.get("evidence"),
                       "node": r.get("node"), "ts": r.get("ts")}
                      for r in ruled[-5:]],
        "open_directions": list(inv.get("open_directions") or []),
        "budget": dict(inv.get("budget") or {}),
        "updated": inv.get("updated"),
    }


def open_items_for_delivery(inv: dict[str, Any]) -> list[dict[str, str]]:
    """What a diagnostic delivery must list: unmet tiers (with meaning)
    and untried directions - the reader learns where the study stopped."""
    items: list[dict[str, str]] = []
    goal = (inv.get("goal") or "").strip()
    for t in unmet_tiers(inv):
        text = f"goal tier not reached: {t} ({TIER_MEANING[t]})"
        if goal:
            text += f"; goal: {goal}"
        items.append({"item": f"goal:{t}", "text": text})
    for i, d in enumerate(inv.get("open_directions") or [], 1):
        items.append({"item": f"direction#{i}", "text": f"untried direction: {d}"})
    return items


def narrative(inv: dict[str, Any]) -> str:
    """One Chinese sentence for situation_report's narrative."""
    b = summary_block(inv)
    zh = {"unmet": "未达", "met": "已达", "not_applicable": "不适用"}
    tiers = "，".join(f"{t} {zh.get(s, s)}" for t, s in b["tiers"].items())
    parts = [f"研究目标：{b['goal'] or '（未写目标）'}；层级：{tiers}"]
    if b["n_ruled_out"]:
        last = "；".join(f"{r['what']}（{r['evidence']}，{r['node'] or '—'}）"
                        for r in b["ruled_out"][-3:] if r.get("what"))
        parts.append(f"已否决 {b['n_ruled_out']} 项：{last}")
    if b["open_directions"]:
        parts.append("未试方向：" + "；".join(b["open_directions"]))
    else:
        parts.append("未试方向：无记录（诊断交付前先用 set_investigation 写明）")
    return "。".join(parts) + "。一条路线失败只否决该构型，不否决目标。"


# --------------------------------------------------------------------------
class SetInvestigation(_ProjectTool):
    name = "set_investigation"
    description = (
        "Record the research goal of this project, its success tiers, what "
        "has been ruled out and which directions are still untried "
        "(.crystalpilot/refine/investigation.json). Two tiers: "
        "candidate_complete (a whole-feature candidate is in the model and "
        "refines stably) and scientifically_established (it survives the "
        "independent tests and checkCIF is explainable). A failed route "
        "rules out ONE configuration, never the goal: write it under "
        "rule_out with the evidence and move to an open direction. "
        "situation_report shows this record (open_items.investigation); a "
        "'diagnostic' finalize_delivery writes the unmet tiers and the open "
        "directions into open_items and refuses to seal when neither this "
        "record nor its unmet_goals parameter says what was not achieved. "
        "Partial update: only the fields given change. Never modifies the "
        "model; no node is created.")
    params_schema = {
        "type": "object",
        "properties": {
            "goal": {"type": "string",
                     "description": "one line: what the study must establish "
                                    "(e.g. 'locate the whole p-bromophenyl"
                                    "acetate guest in the NU-1000 pore')"},
            "tiers": {
                "type": "object",
                "description": "status per tier: 'unmet' | 'met' | "
                               "'not_applicable', or an object "
                               "{status, evidence}",
                "properties": {
                    t: {"anyOf": [{"type": "string", "enum": list(TIER_STATUSES)},
                                  {"type": "object",
                                   "properties": {
                                       "status": {"type": "string",
                                                  "enum": list(TIER_STATUSES)},
                                       "evidence": {"type": "string"}},
                                   "required": ["status"]}],
                        "description": TIER_MEANING[t]}
                    for t in TIERS},
            },
            "budget": {"type": "object",
                       "description": "free-form self-set limits, e.g. "
                                      "{'wall_clock_min': 90, 'tool_calls': "
                                      "150, 'note': '...'}; replaces the "
                                      "stored budget"},
            "rule_out": {
                "type": "array",
                "items": {"type": "object",
                          "properties": {"what": {"type": "string"},
                                         "evidence": {"type": "string"}},
                          "required": ["what", "evidence"]},
                "description": "configurations rejected by THIS step, each "
                               "with the evidence (a number, a node, a test "
                               "verdict); appended with the active node"},
            "open_directions": {"type": "array", "items": {"type": "string"},
                                "description": "replaces the list of untried "
                                               "directions"},
            "add_directions": {"type": "array", "items": {"type": "string"},
                               "description": "directions to append"},
            "close_directions": {"type": "array", "items": {"type": "string"},
                                 "description": "directions to remove (exact "
                                                "text); use rule_out to say "
                                                "why"},
            "note": {"type": "string", "description": "free note for the "
                                                       "history line"},
        },
    }

    def run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        p = self.project
        if p is None or not hasattr(p, "dir"):
            return ToolResult.failure("set_investigation needs a project")
        inv = load(p.dir)
        changed: list[str] = []
        node = None
        try:
            node = p._active_node_or_none()
        except Exception:  # noqa: BLE001 - a record never blocks
            node = None
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")

        if params.get("goal") is not None:
            goal = str(params["goal"]).strip()
            if goal != inv["goal"]:
                inv["goal"] = goal
                changed.append("goal")
        tiers = params.get("tiers")
        if tiers is not None:
            if not isinstance(tiers, dict):
                return ToolResult.failure("tiers must be an object keyed by "
                                          + " / ".join(TIERS))
            for t, v in tiers.items():
                if t not in TIERS:
                    return ToolResult.failure(
                        f"unknown tier {t!r}; tiers are {', '.join(TIERS)}")
                if isinstance(v, str):
                    st, ev = v.strip(), None
                elif isinstance(v, dict):
                    st = str(v.get("status") or "").strip()
                    ev = v.get("evidence")
                else:
                    return ToolResult.failure(f"tier {t}: give a status string "
                                              f"or {{status, evidence}}")
                if st not in TIER_STATUSES:
                    return ToolResult.failure(
                        f"tier {t}: status {st!r} is not one of "
                        f"{', '.join(TIER_STATUSES)}")
                if st == "met" and not str(ev or inv["success_tiers"][t].get("evidence") or "").strip():
                    return ToolResult.failure(
                        f"tier {t}: 'met' needs evidence (which test / node "
                        f"/ number established it)")
                cur = inv["success_tiers"][t]
                new = {"status": st,
                       "evidence": str(ev).strip() if ev is not None
                       else cur.get("evidence", "")}
                if new != cur:
                    inv["success_tiers"][t] = new
                    changed.append(f"tier:{t}={st}")
        if params.get("budget") is not None:
            if not isinstance(params["budget"], dict):
                return ToolResult.failure("budget must be an object")
            inv["budget"] = dict(params["budget"])
            changed.append("budget")
        for r in params.get("rule_out") or []:
            if not isinstance(r, dict) or not str(r.get("what") or "").strip():
                return ToolResult.failure("rule_out entries need {what, evidence}")
            ev = str(r.get("evidence") or "").strip()
            if len(ev) < 8:
                return ToolResult.failure(
                    f"rule_out {r.get('what')!r}: the evidence is too short "
                    f"to be a disclosure - name the test, the number or the "
                    f"node that rejected it")
            inv["ruled_out"].append({"what": str(r["what"]).strip(),
                                     "evidence": ev, "node": node, "ts": stamp})
            changed.append(f"ruled_out:{str(r['what']).strip()[:40]}")
        if params.get("open_directions") is not None:
            new_dirs = [str(d).strip() for d in (params["open_directions"] or [])
                        if str(d).strip()]
            if new_dirs != inv["open_directions"]:
                inv["open_directions"] = new_dirs
                changed.append("open_directions")
        for d in params.get("add_directions") or []:
            ds = str(d).strip()
            if ds and ds not in inv["open_directions"]:
                inv["open_directions"].append(ds)
                changed.append(f"+direction:{ds[:40]}")
        for d in params.get("close_directions") or []:
            ds = str(d).strip()
            if ds in inv["open_directions"]:
                inv["open_directions"].remove(ds)
                changed.append(f"-direction:{ds[:40]}")
        if not changed:
            return ToolResult(ok=True, summary={
                "investigation": summary_block(inv),
                "changed": [], "no_state_change": True,
                "no_change_reason": "nothing new was given",
                "path": str(investigation_path(p.dir)),
            })
        inv["updated"] = stamp
        inv["history"].append({"ts": stamp, "node": node, "changed": changed,
                               "note": str(params.get("note") or "")})
        inv["history"] = inv["history"][-MAX_HISTORY:]
        save(p.dir, inv)
        block = summary_block(inv)
        nxt = []
        if block["unmet_tiers"] and not block["open_directions"]:
            nxt.append("no open direction is recorded while a tier is unmet: "
                       "either add one (add_directions) or, if every route is "
                       "exhausted, say so in the diagnostic delivery")
        if not block["goal"]:
            nxt.append("write the goal (one line) so the tiers have a subject")
        return ToolResult(ok=True, summary={
            "investigation": block,
            "changed": changed,
            "path": str(investigation_path(p.dir)),
            "next": nxt or None,
        })


def register_investigation_tools(reg, project) -> None:
    reg.register(SetInvestigation(project))
