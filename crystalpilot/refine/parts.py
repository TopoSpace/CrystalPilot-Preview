"""SHELX PART bookkeeping shared by edit_atoms, model_disorder(undo) and the
restraint preflight (round-3 WP3).

Two flag sources carry PART numbers: ``disorder_groups[*].members[*].part``
(FVAR-coded components) and ``parts_extra`` ``{LABEL: signed part}`` (loose
PART-block atoms with plain sofs). Until this module every consumer merged
them on its own and nothing cleaned them up when an atom left the model:
the label kept its PART in ``parts_extra``, an atom later re-added under
the same label silently inherited it, and a split's undo record went on
describing atoms that no longer existed (forensic thread T-b).

Everything here mutates ``flags`` in place and returns what it changed, so
the calling tool can report it; nothing touches the xray structure."""
from __future__ import annotations

import time
from typing import Any

#: origin keys that name atoms (model_disorder splits and part edits)
_ORIGIN_LABEL_KEYS = ("created", "linked_existing", "image_labels", "labels")


def part_of_labels(flags: dict | None) -> dict[str, int]:
    """``{LABEL: signed PART}`` from both sources; group membership wins over
    ``parts_extra`` (the same precedence serialization_extras applies when
    it writes the PART cards)."""
    flags = flags or {}
    part_of: dict[str, int] = {}
    for g in flags.get("disorder_groups") or []:
        for m in g.get("members", ()):
            part_of[str(m.get("label", "")).upper()] = int(m.get("part") or 0)
    for lbl, p in (flags.get("parts_extra") or {}).items():
        part_of.setdefault(str(lbl).upper(), int(p or 0))
    return part_of


def _labels_of_origin(origin: dict) -> set[str]:
    out: set[str] = set()
    for key in _ORIGIN_LABEL_KEYS:
        out.update(str(x).upper() for x in (origin.get(key) or []))
    out.update(str(r.get("label", "")).upper()
               for r in (origin.get("restore") or []) if isinstance(r, dict))
    return out


def prune_parts_for_deleted(flags: dict, deleted: set[str], *,
                            by: str = "edit_atoms") -> dict[str, Any]:
    """Same-fate hygiene for PART state when atoms leave the model.

    - ``parts_extra`` loses the labels (so a same-name atom added later
      starts in PART 0 instead of inheriting a block it was never put in);
    - disorder groups lose the members; a group left with no member is
      dropped and the remaining groups renumbered to the contiguous 2..n
      block the FVAR card needs (origins follow the renumbering);
    - every ``disorder_origins`` record that names a deleted atom is marked
      ``stale`` with the reason - its pre-split state no longer describes
      the model, so model_disorder(undo=) refuses it instead of "restoring"
      whatever atom now carries the label.

    Returns ``{}`` when nothing changed."""
    dl = {str(x).upper() for x in deleted}
    out: dict[str, Any] = {}
    if not dl:
        return out

    pe = flags.get("parts_extra") or {}
    gone = sorted(str(lbl).upper() for lbl in pe if str(lbl).upper() in dl)
    if gone:
        kept = {lbl: p for lbl, p in pe.items() if str(lbl).upper() not in dl}
        if kept:
            flags["parts_extra"] = kept
        else:
            flags.pop("parts_extra", None)
        out["parts_extra_cleared"] = gone

    groups = flags.get("disorder_groups") or []
    if groups:
        removed: list[str] = []
        dropped: list[int] = []
        survivors: list[dict] = []
        for g in groups:
            members = list(g.get("members") or [])
            keep = [m for m in members
                    if str(m.get("label", "")).upper() not in dl]
            if len(keep) == len(members):
                survivors.append(g)
                continue
            removed.extend(str(m.get("label", "")).upper() for m in members
                           if str(m.get("label", "")).upper() in dl)
            if keep:
                survivors.append({**g, "members": keep})
            else:
                dropped.append(int(g.get("fvar_index") or 0))
        if removed:
            out["disorder_members_removed"] = removed
            survivors.sort(key=lambda g: int(g.get("fvar_index") or 0))
            renum: dict[int, int] = {}
            renumbered: list[dict] = []
            for n, g in enumerate(survivors, start=2):
                old = int(g.get("fvar_index") or 0)
                if old != n:
                    renum[old] = n
                    g = {**g, "fvar_index": n}
                renumbered.append(g)
            if renumbered:
                flags["disorder_groups"] = renumbered
            else:
                flags.pop("disorder_groups", None)
            if dropped:
                out["disorder_groups_dropped"] = dropped
            if renum:
                out["fvar_renumbered"] = {str(k): v for k, v in renum.items()}
            for o in flags.get("disorder_origins") or []:
                fi = o.get("fvar_index")
                if fi is None:
                    continue
                if int(fi) in dropped:
                    # the group is gone; nothing for undo to find by number
                    o["fvar_index"] = None
                elif int(fi) in renum:
                    o["fvar_index"] = renum[int(fi)]

    stale: list[dict[str, Any]] = []
    for o in flags.get("disorder_origins") or []:
        hit = sorted(_labels_of_origin(o) & dl)
        if not hit or o.get("stale"):
            continue
        o["stale"] = True
        o["stale_reason"] = f"{', '.join(hit)} deleted by {by}"
        o["stale_ts"] = time.time()
        stale.append({"kind": o.get("kind") or "split",
                      "fvar_index": o.get("fvar_index"), "atoms": hit})
    if stale:
        out["disorder_origins_stale"] = stale
    return out


def apply_part_edits(flags: dict, edits: list[tuple[str, int | None]], *,
                     node_before: str | None = None,
                     by: str = "edit_atoms") -> dict[str, Any]:
    """edit_atoms set_part / clear_part: ``(label, part)`` with ``part=None``
    or ``0`` meaning "no PART block". A disorder-group member keeps its FVAR
    coding and only changes the ``part`` of its member record; a loose atom
    goes into / out of ``parts_extra``. The previous assignment is recorded
    as a ``disorder_origins`` entry of kind ``part_edit`` so
    model_disorder(undo=<label>) can reverse it exactly."""
    groups = flags.get("disorder_groups") or []
    member_of: dict[str, dict] = {}
    for g in groups:
        for m in g.get("members", ()):
            member_of[str(m.get("label", "")).upper()] = m
    pe = dict(flags.get("parts_extra") or {})
    key_of = {str(k).upper(): k for k in pe}
    before: dict[str, dict[str, Any]] = {}
    after: dict[str, int | None] = {}
    labels: list[str] = []
    for label, part in edits:
        up = str(label).upper()
        if up in before:
            # the same atom twice in one call: keep the FIRST 'before'
            pass
        else:
            labels.append(up)
        new = None if part in (None, 0) else int(part)
        m = member_of.get(up)
        if m is not None:
            before.setdefault(up, {"source": "group",
                                   "part": int(m.get("part") or 0)})
            m["part"] = new or 0
            after[up] = m["part"]
            continue
        key = key_of.get(up)
        before.setdefault(up, {"source": "parts_extra", "part": int(pe[key])}
                          if key is not None else {"source": None, "part": None})
        if key is not None:
            pe.pop(key)
            key_of.pop(up, None)
        if new is not None:
            pe[up] = new
            key_of[up] = up
        after[up] = new
    if pe:
        flags["parts_extra"] = pe
    else:
        flags.pop("parts_extra", None)
    origin = {"kind": "part_edit", "labels": labels, "before": before,
              "after": after, "node_before": node_before, "by": by,
              "ts": time.time()}
    origins = list(flags.get("disorder_origins") or [])
    origins.append(origin)
    flags["disorder_origins"] = origins
    return {"parts": after,
            "undo": (f"model_disorder(undo='{labels[0]}') restores the "
                     f"previous PART assignment" if labels else None)}


def latest_part_edit(origins: list[dict], label: str) -> dict | None:
    """The most recent ``part_edit`` origin naming ``label`` (undo is LIFO
    per atom: the last change to it is the one reversed first)."""
    up = str(label).strip().upper()
    for o in reversed(origins or []):
        if o.get("kind") != "part_edit":
            continue
        if up in {str(x).upper() for x in (o.get("labels") or [])}:
            return o
    return None


def restore_part_edit(flags: dict, origin: dict) -> dict[str, int | None]:
    """Reverse one ``part_edit`` origin and drop it from the record.
    Returns ``{LABEL: restored part or None}``."""
    groups = flags.get("disorder_groups") or []
    member_of: dict[str, dict] = {}
    for g in groups:
        for m in g.get("members", ()):
            member_of[str(m.get("label", "")).upper()] = m
    pe = dict(flags.get("parts_extra") or {})
    restored: dict[str, int | None] = {}
    for up, st in (origin.get("before") or {}).items():
        up = str(up).upper()
        part = st.get("part") if isinstance(st, dict) else st
        source = st.get("source") if isinstance(st, dict) else None
        m = member_of.get(up)
        if m is not None and source == "group":
            m["part"] = int(part or 0)
            restored[up] = m["part"]
            continue
        pe = {k: v for k, v in pe.items() if str(k).upper() != up}
        if part not in (None, 0):
            pe[up] = int(part)
            restored[up] = int(part)
        else:
            restored[up] = None
    if pe:
        flags["parts_extra"] = pe
    else:
        flags.pop("parts_extra", None)
    sig = (origin.get("ts"), list(origin.get("labels") or []))
    rest = [o for o in (flags.get("disorder_origins") or [])
            if not (o.get("kind") == "part_edit"
                    and (o.get("ts"), list(o.get("labels") or [])) == sig)]
    if rest:
        flags["disorder_origins"] = rest
    else:
        flags.pop("disorder_origins", None)
    return restored
