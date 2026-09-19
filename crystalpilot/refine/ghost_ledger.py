"""Ghost-verdict ledger: what ghost_test said about each atom, and what
became of it.

pa2 cage-l0-r1 and pa3 hex-l2g-r1: a ghost_test 'real' verdict had no
consequence. C00M - real, the largest dR1 of twelve candidates, 0.47 A
from the hand-built Br site - was deleted eleven minutes later as an
anonymous channel peak; a Cp ring judged real as a group (dR1 +0.0058)
was deleted member by member on single-atom re-tests that said
inconclusive. The verdict lived in one tool result and the next
edit_atoms call never saw it.

The ledger is the project's memory of those verdicts:

- ghost_test appends one entry per tested candidate (record);
- edit_atoms consults it before deleting (real_matches) and refuses to
  delete an atom held as real unless the call carries acknowledge_real;
- an acknowledged delete is written back (mark_disposed) so the same
  atom is not blocked twice and the reason is on file.

Storage: <project>/.crystalpilot/refine/ghost_ledger.json, a JSON list of
entries, rewritten atomically (temp file + os.replace). A missing or
corrupt file reads as empty - the ledger must never break a tool.

Matching an atom to an entry is by label (case-insensitive) OR by site
(symmetry-aware minimum distance <= SITE_MATCH_A), so an atom that was
renamed after the test still matches by site, and a label that
rename_atoms recycled for a different atom elsewhere in the cell does NOT
match (the label match is void when the model atom sits far from the
ledger site).
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

LEDGER_RELPATH = Path(".crystalpilot") / "refine" / "ghost_ledger.json"
#: symmetry-aware distance under which a ledger site and a model atom are
#: the same site (a renamed or re-added atom still matches)
SITE_MATCH_A = 0.3
#: a label match is only trusted while the model atom is still near the
#: ledger site; beyond this the label was recycled for another atom
LABEL_DRIFT_A = 1.0
#: verdicts that release an earlier 'real' on the same candidate set:
#: 'ghost' (no density at all) and 'ripple' (the density belongs to a much
#: heavier neighbour, so it was never an independent atom)
RELEASING_VERDICTS = frozenset({"ghost", "ripple"})


def ledger_path(project_dir) -> Path:
    return Path(project_dir) / LEDGER_RELPATH


def project_dir_from_ctx(ctx) -> Path | None:
    """The project a session-scoped tool is working in, read off the
    RunStore's directory (<project>/.crystalpilot/refine/runs/<run>).
    Session tools are constructed without a project; a bare test context
    (fake store, or a store outside a project) simply has no ledger."""
    store = getattr(ctx, "store", None)
    d = getattr(store, "dir", None)
    if d is None:
        return None
    try:
        p = Path(d).resolve()
    except (TypeError, OSError):
        return None
    for anc in (p, *p.parents):
        if anc.name == ".crystalpilot":
            return anc.parent
    return None


# --------------------------------------------------------------------------
def load(project_dir) -> list[dict[str, Any]]:
    """All entries, oldest first; a missing or damaged file is empty."""
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
    fd, tmp = tempfile.mkstemp(prefix=".ghost_ledger.", suffix=".tmp",
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


def _normalise(entry: dict[str, Any], n_existing: int) -> dict[str, Any]:
    labels = [str(x) for x in (entry.get("labels") or [])]
    e = dict(entry)
    e["id"] = str(entry.get("id") or f"g{n_existing + 1:04d}")
    e["labels"] = labels
    e["labels_upper"] = [lb.upper() for lb in labels]
    sites = []
    for s in entry.get("site_frac") or []:
        try:
            sites.append([float(v) for v in s])
        except (TypeError, ValueError):
            sites.append(None)
    e["site_frac"] = sites
    e["verdict"] = str(entry.get("verdict") or "inconclusive")
    e["group"] = bool(entry.get("group", len(labels) > 1))
    e.setdefault("timestamp", time.strftime("%Y-%m-%dT%H:%M:%S"))
    e.setdefault("disposed", {})
    return e


def record(project_dir, entry: dict[str, Any]) -> dict[str, Any]:
    """Append one verdict. Expected keys: labels, site_frac (one [x,y,z]
    per label), verdict, delta_r1, peak_at_site, baseline, node, engine,
    cycles, group; timestamp/id are filled in when absent. Returns the
    stored entry."""
    entries = load(project_dir)
    e = _normalise(entry, len(entries))
    entries.append(e)
    _write(project_dir, entries)
    return e


# --------------------------------------------------------------------------
def _sym_distance(xs, site_a, site_b) -> float | None:
    """Minimum distance between site_b and any symmetry image of site_a."""
    from cctbx import sgtbx
    try:
        eq = xs.sym_equiv_sites(tuple(site_a))
        return float(sgtbx.min_sym_equiv_distance_info(eq, tuple(site_b))
                     .dist())
    except Exception:  # noqa: BLE001 - a bad site must not break the guard
        return None


def _key(e: dict[str, Any]) -> tuple[str, ...]:
    return tuple(sorted(e.get("labels_upper") or []))


def real_matches(project_dir, xs, labels: list[str]) -> list[dict[str, Any]]:
    """Entries holding any of `labels` as REAL (alone or as a member of a
    group judged real) that have not been disposed of, each with a
    'match' list [{label, by: 'label'|'site', d_A, ledger_label}].

    Supersession: a LATER entry with exactly the same candidate set and
    verdict 'ghost' or 'ripple' (the same test repeated once the model was
    better, or the site recognised as a heavy neighbour's Fourier ripple -
    ka1 cage-tools-r1: 96 ripple sites were deleted through
    acknowledge_real because a returning ripple had been read as 'real')
    releases the earlier 'real'. A later single-member test never releases
    a group verdict, and 'inconclusive' releases nothing.
    """
    entries = load(project_dir)
    if not entries or not labels:
        return []
    by_upper = {sc.label.upper(): sc for sc in xs.scatterers()}
    wanted = [(str(lb), by_upper.get(str(lb).upper())) for lb in labels]
    out: list[dict[str, Any]] = []
    for idx, e in enumerate(entries):
        if e.get("verdict") != "real":
            continue
        lab_up = list(e.get("labels_upper") or [])
        if not lab_up:
            continue
        if any(later.get("verdict") in RELEASING_VERDICTS
               and _key(later) == _key(e)
               for later in entries[idx + 1:]):
            continue
        disposed = e.get("disposed") or {}
        sites = e.get("site_frac") or []
        matches: list[dict[str, Any]] = []
        for lbl, sc in wanted:
            up = lbl.upper()
            if up in lab_up and up not in disposed:
                k = lab_up.index(up)
                site = sites[k] if k < len(sites) else None
                d = (_sym_distance(xs, site, sc.site)
                     if sc is not None and site is not None else None)
                if d is None or d <= LABEL_DRIFT_A:
                    matches.append({"label": lbl, "by": "label",
                                    "d_A": (round(d, 3) if d is not None
                                            else None),
                                    "ledger_label": e["labels"][k]})
                    continue
            if sc is None:
                continue
            best = None
            for k, site in enumerate(sites):
                if site is None or k >= len(lab_up) or lab_up[k] in disposed:
                    continue
                d = _sym_distance(xs, site, sc.site)
                if d is not None and d <= SITE_MATCH_A and (
                        best is None or d < best[0]):
                    best = (d, k)
            if best is not None:
                matches.append({"label": lbl, "by": "site",
                                "d_A": round(best[0], 3),
                                "ledger_label": e["labels"][best[1]]})
        if matches:
            out.append({**e, "match": matches})
    return out


def note_diagnostic_touch(project_dir, labels: list[str], reason: str) -> int:
    """Round-3 WP6: a diagnostic delete (probe_site / ghost_test on an
    isolated branch) touched atoms the ledger holds as real. Record it for
    the audit trail - `diagnostic_touches` on each such entry - WITHOUT
    writing a disposition: the verdict stands, the protection stands.
    Returns the number of entries touched."""
    entries = load(project_dir)
    if not entries:
        return 0
    want = {str(lb).upper() for lb in labels}
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S")
    n = 0
    for e in entries:
        if e.get("verdict") != "real":
            continue
        hit = sorted(up for up in (e.get("labels_upper") or []) if up in want)
        if not hit:
            continue
        e.setdefault("diagnostic_touches", []).append(
            {"labels": hit, "reason": str(reason), "timestamp": stamp})
        n += 1
    if n:
        _write(project_dir, entries)
    return n


def mark_disposed(project_dir, labels: list[str], disposition_text: str,
                  entry_ids: list[str] | None = None) -> int:
    """Write a disposition against the given labels (case-insensitive) on
    every 'real' entry holding them - or only on the entries named by
    entry_ids. A disposition answers a 'real' verdict; ghost/inconclusive
    entries are left alone. Per-label: disposing one member of a group
    leaves the other members protected. Returns the number of (entry,
    label) pairs marked."""
    entries = load(project_dir)
    if not entries:
        return 0
    want = {str(lb).upper() for lb in labels}
    ids = set(entry_ids or [])
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S")
    n = 0
    for e in entries:
        if ids:
            if e.get("id") not in ids:
                continue
        elif e.get("verdict") != "real":
            continue
        disposed = e.setdefault("disposed", {})
        for up in e.get("labels_upper") or []:
            if up in want and up not in disposed:
                disposed[up] = {"text": str(disposition_text),
                                "timestamp": stamp}
                n += 1
        if disposed and all(up in disposed
                            for up in (e.get("labels_upper") or [])):
            e["disposition"] = str(disposition_text)
    if n:
        _write(project_dir, entries)
    return n
