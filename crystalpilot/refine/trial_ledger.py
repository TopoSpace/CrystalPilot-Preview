"""Round-3 WP7: the trial ledger - "this exact call already ran here".

The live-demo Zr-MOF forensic (2026-09-05) counted 27 fit_fragment calls
of which 15 added nothing, several of them the same anchors on the same
node; the agent had no memory of what it had tried beyond the ghost ledger
(verdicts) and the node history (committing tools only). Read-only probes
(search_fragment_pose, probe_site, integrate_difference_density, ...) leave
no node, so they left no trace at all.

This ledger records every completed call of a TRIALED tool against the
node it read, keyed by the tool name and the *normalised effective inputs*
(label order and case, anchor order, float noise below 1e-3 do not make a
new trial; time budgets and free-text reasons are not inputs). Before the
next call the project looks the key up:

  * same node          -> `tool_status.prior_trial` (the call still runs;
                          the memo says the identical call cannot give a
                          different answer on an unchanged model)
  * an ancestor node   -> `tool_status.prior_trials_on_ancestors`
                          (informational: the model has changed since)
  * another branch     -> nothing (a sibling's result says nothing here)

The ledger informs; it never refuses. Entries are never invalidated by
hand: the node id is immutable, so "same node" is exact by construction.

File: <project>/.crystalpilot/refine/trial_ledger.json (atomic replace,
damaged file reads as empty - same discipline as ghost_ledger).
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

LEDGER_RELPATH = Path(".crystalpilot") / "refine" / "trial_ledger.json"

# tools whose result depends only on (model at this node, inputs): re-running
# one unchanged on the same node is a wasted call, not a new experiment
TRIALED_TOOLS = (
    "fit_fragment", "search_fragment_pose", "probe_site", "ghost_test",
    "element_scan", "integrate_difference_density", "audit_guest_evidence",
)

MAX_ENTRIES = 600

# inputs that shape the run but not the answer
_DROP_KEYS = {"timeout_s", "time_budget_s", "reason", "diagnostic_reason",
              "note", "recompute_peaks", "n_refine", "max_seeds"}
# keys whose string values are atom labels (case-insensitive in SHELX)
_LABEL_KEYS = {"labels", "atoms", "label", "atom", "near_atom", "target",
               "targets", "members", "exclude", "candidates", "atom_labels",
               "guest_labels", "host_labels", "site", "from_atom", "to_atom",
               "anchor_atoms", "near_atoms", "keep", "delete"}


def ledger_path(project_dir) -> Path:
    return Path(project_dir) / LEDGER_RELPATH


# --------------------------------------------------------------------------
# normalisation
def _norm(v: Any, key: str | None = None) -> Any:
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, float):
        r = round(v, 3)
        return 0.0 if r == 0 else r
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        s = v.strip()
        return s.upper() if key in _LABEL_KEYS else s
    if isinstance(v, dict):
        out = {}
        for k in sorted(v, key=str):
            ks = str(k)
            if ks.startswith("_") or ks in _DROP_KEYS:
                continue
            out[ks] = _norm(v[k], ks)
        return out
    if isinstance(v, (list, tuple)):
        items = [_norm(x, key) for x in v]
        if items and all(isinstance(x, str) for x in items):
            # a set of labels / names: order never changes the experiment
            return sorted(items)
        if items and all(isinstance(x, dict) for x in items):
            # anchors / constraints: an unordered set of records
            return sorted(items, key=lambda d: json.dumps(
                d, sort_keys=True, default=str))
        # numeric vectors (site_frac, region boxes) keep their order
        return items
    return str(v)


def normalize_params(params: dict[str, Any] | None) -> dict[str, Any]:
    """The effective inputs of a call, canonicalised (see module doc)."""
    n = _norm(dict(params or {}))
    return n if isinstance(n, dict) else {}


def trial_key(tool: str, params: dict[str, Any] | None) -> str:
    return f"{tool}:" + json.dumps(normalize_params(params), sort_keys=True,
                                   separators=(",", ":"), default=str,
                                   ensure_ascii=False)


# --------------------------------------------------------------------------
# storage
def load(project_dir) -> list[dict[str, Any]]:
    p = ledger_path(project_dir)
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, ValueError, UnicodeDecodeError):
        return []
    if isinstance(raw, dict):
        raw = raw.get("entries")
    if not isinstance(raw, list):
        return []
    return [e for e in raw if isinstance(e, dict)]


def _write(project_dir, entries: list[dict[str, Any]]) -> Path:
    p = ledger_path(project_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".trial_ledger.", suffix=".tmp",
                               dir=str(p.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(entries, fh, indent=1, ensure_ascii=False, default=str)
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return p


# --------------------------------------------------------------------------
# the node line
def ancestor_chain(nodes, node_id: str | None, limit: int = 2000) -> list[str]:
    """[parent, grandparent, ...] of node_id (excluding itself); a node
    store that cannot be read gives an empty chain."""
    chain: list[str] = []
    cur = node_id
    seen: set[str] = set()
    while cur and len(chain) < limit:
        try:
            parent = nodes.node_meta(cur).get("parent")
        except Exception:  # noqa: BLE001 - a memo never blocks a tool
            break
        if not parent or parent in seen:
            break
        seen.add(parent)
        chain.append(parent)
        cur = parent
    return chain


# --------------------------------------------------------------------------
# outcome digest
def _n(v: Any) -> int | None:
    return len(v) if isinstance(v, (list, tuple, dict)) else None


def digest(tool: str, result) -> dict[str, Any]:
    """What a later reader needs to know about a completed call, without
    the payload: ok, execution, the scientific verdict, whether anything
    changed, and one tool-specific count."""
    s = result.summary if isinstance(getattr(result, "summary", None), dict) else {}
    ts = s.get("tool_status") if isinstance(s.get("tool_status"), dict) else {}
    sci = ts.get("scientific_outcome")
    no_change = ts.get("no_change")
    out: dict[str, Any] = {
        "ok": bool(getattr(result, "ok", False)),
        "execution": ts.get("execution"),
        "verdict": (sci.get("verdict") if isinstance(sci, dict) else sci),
        "no_change": (no_change.get("value") if isinstance(no_change, dict)
                      else None),
    }
    if isinstance(sci, dict) and sci.get("reasons"):
        out["reasons"] = [str(r) for r in list(sci["reasons"])[:3]]
    sc = ts.get("state_changed")
    if isinstance(sc, dict):
        out["node_after"] = sc.get("node_after")
        out["changed"] = sc.get("changed")
    if tool == "search_fragment_pose":
        out["n_candidates"] = _n(s.get("candidates"))
        cands = s.get("candidates") or []
        if cands and isinstance(cands[0], dict):
            out["best"] = {k: cands[0].get(k) for k in
                           ("id", "score", "n_direct", "n_weak",
                            "n_geometry_only")}
    elif tool == "fit_fragment":
        out["n_added"] = (_n(s.get("added")) if s.get("added") is not None
                          else s.get("n_added"))
    elif tool in ("ghost_test", "element_scan", "probe_site"):
        for k in ("verdict", "verdicts", "decision", "best", "conclusion"):
            if k in s and k not in out:
                v = s[k]
                out[k] = v if isinstance(v, (str, int, float, bool)) else _n(v)
    elif tool == "integrate_difference_density":
        for k in ("electrons", "electron_count", "sum_e", "n_electrons"):
            if isinstance(s.get(k), (int, float)):
                out["electrons"] = round(float(s[k]), 2)
                break
    elif tool == "audit_guest_evidence":
        out["verdict"] = out.get("verdict") or s.get("verdict")
    err = getattr(result, "error", None)
    if err:
        out["error"] = str(err)[:200]
    return out


def outcome_text(entry: dict[str, Any]) -> str:
    o = entry.get("outcome") or {}
    bits = []
    if not o.get("ok"):
        bits.append("failed" + (f" ({o['error']})" if o.get("error") else ""))
    if o.get("verdict"):
        bits.append(str(o["verdict"]))
    if o.get("no_change"):
        bits.append("no change")
    if o.get("n_candidates") is not None:
        bits.append(f"{o['n_candidates']} candidates")
    if o.get("n_added") is not None:
        bits.append(f"{o['n_added']} atoms added")
    if o.get("electrons") is not None:
        bits.append(f"{o['electrons']} e")
    if o.get("node_after") and o.get("changed"):
        bits.append(f"-> {o['node_after']}")
    return ", ".join(bits) or ("ok" if o.get("ok") else "unknown")


# --------------------------------------------------------------------------
# record / lookup / annotate
def record(project_dir, tool: str, params: dict[str, Any] | None,
           node: str | None, nodes, result) -> dict[str, Any]:
    """Append one completed call; returns the entry written."""
    revision = None
    if node and nodes is not None:
        try:
            revision = nodes.node_meta(node).get("revision")
        except Exception:  # noqa: BLE001
            revision = None
    entry = {
        "key": trial_key(tool, params),
        "tool": tool,
        "node": node,
        "revision": revision,
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "params": normalize_params(params),
        "outcome": digest(tool, result),
    }
    entries = load(project_dir)
    entries.append(entry)
    if len(entries) > MAX_ENTRIES:
        entries = entries[-MAX_ENTRIES:]
    _write(project_dir, entries)
    return entry


def lookup(project_dir, tool: str, params: dict[str, Any] | None,
           node: str | None, chain: list[str] | tuple[str, ...] = ()
           ) -> dict[str, Any]:
    """Prior identical calls: on this node (exact) and on its ancestors
    (with the distance up the line). Other branches are ignored."""
    key = trial_key(tool, params)
    same: list[dict[str, Any]] = []
    anc: list[dict[str, Any]] = []
    index = {n: i + 1 for i, n in enumerate(chain)}
    for e in load(project_dir):
        if e.get("key") != key:
            continue
        if node is not None and e.get("node") == node:
            same.append(e)
        elif e.get("node") in index:
            anc.append({**e, "distance": index[e["node"]]})
    return {"key": key, "same_node": same, "ancestors": anc}


def _brief(e: dict[str, Any]) -> dict[str, Any]:
    return {"node": e.get("node"), "revision": e.get("revision"),
            "ts": e.get("ts"), "outcome": e.get("outcome") or {},
            "outcome_text": outcome_text(e)}


def annotate(result, prior: dict[str, Any] | None) -> None:
    """Attach the memo to the envelope (tool_status.prior_trial /
    prior_trials_on_ancestors + a one-line prior_trial_note)."""
    if not prior or not isinstance(getattr(result, "summary", None), dict):
        return
    same = prior.get("same_node") or []
    anc = prior.get("ancestors") or []
    if not same and not anc:
        return
    env = result.summary.setdefault("tool_status", {})
    notes = []
    if same:
        last = same[-1]
        env["prior_trial"] = {"n": len(same), **_brief(last), "same_node": True}
        notes.append(
            f"this exact call already ran on node {last.get('node')} "
            f"({len(same)}x, last {last.get('ts')}: {outcome_text(last)}) - "
            f"an unchanged model with unchanged inputs cannot give a "
            f"different answer; change the inputs (region / anchors / "
            f"occupancy hypothesis) or the model before trying again")
    if anc:
        anc_sorted = sorted(anc, key=lambda e: e.get("distance", 0))
        env["prior_trials_on_ancestors"] = [
            {**_brief(e), "distance": e.get("distance")} for e in anc_sorted[:5]]
        first = anc_sorted[0]
        notes.append(
            f"the same call ran on ancestor {first.get('node')} "
            f"({first.get('distance')} step(s) up: {outcome_text(first)}); "
            f"the model has changed since, so this result may differ")
    result.summary["prior_trial_note"] = "; ".join(notes)


def recent(project_dir, node: str | None,
           chain: list[str] | tuple[str, ...] = (), n: int = 6
           ) -> list[dict[str, Any]]:
    """Newest-first trials on this line (this node + ancestors), for
    situation_report.open_items.recent_trials."""
    line = ({node} | set(chain)) if node else set(chain)
    if not line:
        return []
    picked = [e for e in load(project_dir) if e.get("node") in line]
    picked.reverse()
    out = []
    for e in picked[:n]:
        p = e.get("params") or {}
        brief = ", ".join(f"{k}={json.dumps(v, ensure_ascii=False, default=str)}"
                          for k, v in list(p.items())[:4])
        out.append({"tool": e.get("tool"), "node": e.get("node"),
                    "ts": e.get("ts"), "params": brief[:160],
                    "outcome": e.get("outcome") or {},
                    "outcome_text": outcome_text(e)})
    return out
