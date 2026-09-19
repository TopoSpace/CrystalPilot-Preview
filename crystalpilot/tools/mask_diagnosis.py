"""What changed since the last solvent mask that worked.

pa2 cage-l0-r2 / cage-l2-r2: as the agents kept editing the model (atoms
added, sites split, elements reassigned, H added) every solvent_mask call
returned a different electron count (2342 -> 1304 -> 2183 -> ... -> 694;
2821 -> ... -> 502 -> negative integral, dropped). The tool said
"NEGATIVE / diverged", the agents read that as "the mask is unstable",
abandoned it and delivered unmasked models at R1 0.22-0.28 while a masked
node at R1 0.12 sat in their tree. A crystallographer's first move after a
failed mask is to checkout the last node where the mask converged and diff
the two models. This module does that diff and says what it means:

* previous_mask_from_store - the node the last successful mask was
  computed on (the oldest node of the contiguous run of ancestors that
  carry the same mask), its electrons, R1 and timestamp;
* model_delta - a symmetry-aware, site-based comparison of two models
  (a renamed atom is the same atom; added / removed / reassigned / moved
  atoms, occupancy, ADP and H changes, non-H electrons per cell);
* diagnose - the ``mask_diagnosis`` block of the solvent_mask result, with
  a reading that follows from the delta, never from a fixed script.

Nothing here is tuned to a crystal or an element: the tolerances are a
site-match distance (the ghost ledger's 0.3 A), an occupancy delta and a
U delta, and the electron bookkeeping is Z x occupancy x multiplicity.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

import numpy as np

#: symmetry-aware distance under which an atom of the previous model and an
#: atom of the current model are the same site (same rule as ghost_ledger)
SITE_MATCH_A = 0.3
#: a same-label atom beyond SITE_MATCH_A but within this is "moved", not a
#: removal plus an addition
MOVED_MATCH_A = 1.5
#: occupancy / U(iso or equiv) differences below these are refinement drift
OCC_TOL = 0.05
U_TOL_A2 = 0.01
#: an electron-count change beyond this between calls is a model-change
#: signal (electron_count_confidence already downgrades at the same value)
CHANGE_SIGNAL_PCT = 30.0
#: per-list cap in the delta block (the totals are always reported)
LIST_CAP = 12
HYDROGEN = ("H", "D")
#: node.json stores the mask info through nodes._shrink (4000 chars)
_SHRINK_LIMIT = 4000

RULE = ("after NEGATIVE/diverged the first move is to checkout the last "
        "converged-mask node and compare the two models; do not delete atoms "
        "and recompute the mask in the same step; an electron count change "
        "> 30% between calls is a model-change signal, look at the model "
        "delta before touching the mask")

MASK_PARAM_KEYS = ("solvent_radius", "shrink_truncation_radius",
                   "resolution_factor", "d_min", "min_void_volume",
                   "max_cycles")


# --------------------------------------------------------------------------
# model snapshots and the delta
# --------------------------------------------------------------------------
def element_of(scattering_type: Any) -> str:
    """'Zr4+' -> 'Zr', 'o' -> 'O'; unknown -> 'X'."""
    letters = "".join(c for c in str(scattering_type) if c.isalpha())[:2]
    return letters.capitalize() or "X"


_Z_CACHE: dict[str, int] = {}


def atomic_number(element: str) -> int:
    z = _Z_CACHE.get(element)
    if z is None:
        try:
            from cctbx.eltbx import tiny_pse
            z = int(tiny_pse.table(element).atomic_number())
        except Exception:  # noqa: BLE001 - unknown type counts nothing
            z = 0
        _Z_CACHE[element] = z
    return z


def model_snapshot(xs) -> dict[str, Any]:
    """A plain-data copy of what the delta needs: symmetry + per-atom
    label / element / site / occupancy / U(iso|equiv) / aniso flag /
    multiplicity. JSON-serialisable; the session keeps one per mask."""
    from cctbx import adptbx

    uc = xs.unit_cell()
    order_z = int(xs.space_group().order_z())
    atoms = []
    for sc in xs.scatterers():
        aniso = bool(sc.flags.use_u_aniso())
        try:
            u = (float(adptbx.u_star_as_u_iso(uc, sc.u_star)) if aniso
                 else float(sc.u_iso))
        except Exception:  # noqa: BLE001
            u = float(sc.u_iso)
        try:
            mult = int(sc.multiplicity()) or order_z
        except Exception:  # noqa: BLE001
            mult = order_z
        atoms.append({"label": str(sc.label), "element": element_of(
            sc.scattering_type), "site": [float(x) for x in sc.site],
            "occ": float(sc.occupancy), "u": u, "aniso": aniso,
            "mult": mult})
    return {"symmetry": {"unit_cell": [float(x) for x in uc.parameters()],
                         "hall": str(xs.space_group_info().type()
                                     .hall_symbol())},
            "atoms": atoms}


def _symmetry_of(snap: dict[str, Any]):
    from cctbx import crystal
    s = snap["symmetry"]
    return crystal.symmetry(unit_cell=tuple(s["unit_cell"]),
                            space_group_symbol="hall: " + s["hall"])


class _SymDistance:
    """Minimum distance from a site to each of many sites under the space
    group and lattice translations (vectorised over the targets; the
    nearest lattice image is taken per fractional axis, exact at the
    sub-angstrom distances that matter here)."""

    def __init__(self, cs) -> None:
        self.orth = np.array(cs.unit_cell().orthogonalization_matrix(),
                             dtype=float).reshape(3, 3)
        self.ops = list(cs.space_group().all_ops())

    def row(self, site, targets: np.ndarray) -> np.ndarray:
        best = np.full(len(targets), np.inf)
        if not len(targets):
            return best
        for op in self.ops:
            s = np.asarray(op * tuple(float(x) for x in site), dtype=float)
            dd = targets - s
            dd -= np.round(dd)
            best = np.minimum(best, np.linalg.norm(dd @ self.orth.T, axis=1))
        return best

    def one(self, a, b) -> float:
        return float(self.row(a, np.asarray([b], dtype=float))[0])


def _is_h(a: dict[str, Any]) -> bool:
    return a["element"] in HYDROGEN


def _elem_counts_text(atoms: list[dict[str, Any]]) -> str:
    counts: dict[str, int] = {}
    for a in atoms:
        counts[a["element"]] = counts.get(a["element"], 0) + 1
    return ", ".join(f"{n} {el}" for el, n in
                     sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def model_delta(prev, now, *, site_tol: float = SITE_MATCH_A,
                moved_tol: float = MOVED_MATCH_A, occ_tol: float = OCC_TOL,
                u_tol: float = U_TOL_A2) -> dict[str, Any]:
    """Site-based, symmetry-aware difference between two models.

    ``prev`` / ``now`` are cctbx xray.structures or model_snapshot dicts.
    Atoms are paired (1) by label when the same-label atom is still at
    the same site (<= site_tol under symmetry), (2) by site regardless of
    label (a renamed atom is the same atom; nearest pairs first), (3) by
    label within moved_tol (a moved atom, not a removal + addition).
    Everything unpaired is removed / added. When the two models are not
    in the same cell/space group only labels can be compared and the
    block says so (symmetry_changed)."""
    prev = prev if isinstance(prev, dict) else model_snapshot(prev)
    now = now if isinstance(now, dict) else model_snapshot(now)
    ap, an = list(prev["atoms"]), list(now["atoms"])
    try:
        cs_now = _symmetry_of(now)
        sym_ok = bool(_symmetry_of(prev).is_similar_symmetry(cs_now))
    except Exception:  # noqa: BLE001 - unreadable symmetry: labels only
        cs_now, sym_ok = None, False

    by_label_n: dict[str, list[int]] = {}
    for j, a in enumerate(an):
        by_label_n.setdefault(a["label"].strip().upper(), []).append(j)
    pairs: list[tuple[int, int, float | None, str]] = []
    used_p: set[int] = set()
    used_n: set[int] = set()

    def take(i: int, j: int, d: float | None, how: str) -> None:
        pairs.append((i, j, d, how))
        used_p.add(i)
        used_n.add(j)

    def label_cands(i: int) -> list[int]:
        return [j for j in by_label_n.get(ap[i]["label"].strip().upper(), ())
                if j not in used_n]

    if sym_ok:
        sd = _SymDistance(cs_now)
        targets = np.asarray([a["site"] for a in an],
                             dtype=float).reshape(-1, 3)
        # (1) same label, same site
        for i in range(len(ap)):
            cands = label_cands(i)
            if not cands:
                continue
            d, j = min((sd.one(ap[i]["site"], an[j]["site"]), j)
                       for j in cands)
            if d <= site_tol:
                take(i, j, d, "label")
        # (2) same site, any label - nearest pairs first
        up = [i for i in range(len(ap)) if i not in used_p]
        un = [j for j in range(len(an)) if j not in used_n]
        if up and un:
            tn = targets[un]
            cand: list[tuple[float, int, int]] = []
            for i in up:
                row = sd.row(ap[i]["site"], tn)
                for k in np.nonzero(row <= site_tol)[0]:
                    cand.append((float(row[k]), i, un[int(k)]))
            cand.sort()
            for d, i, j in cand:
                if i not in used_p and j not in used_n:
                    take(i, j, d, "site")
        # (3) same label, moved
        for i in [i for i in up if i not in used_p]:
            cands = label_cands(i)
            if not cands:
                continue
            d, j = min((sd.one(ap[i]["site"], an[j]["site"]), j)
                       for j in cands)
            if d <= moved_tol:
                take(i, j, d, "moved")
    else:
        for i in range(len(ap)):
            cands = label_cands(i)
            if cands:
                take(i, cands[0], None, "label")

    removed = [ap[i] for i in range(len(ap)) if i not in used_p]
    added = [an[j] for j in range(len(an)) if j not in used_n]
    reassigned: list[dict[str, Any]] = []
    renamed: list[dict[str, Any]] = []
    moved: list[dict[str, Any]] = []
    occ_changed: list[dict[str, Any]] = []
    u_changed: list[dict[str, Any]] = []
    iso_to_aniso = aniso_to_iso = 0
    by_how = {"label": 0, "site": 0, "moved": 0}
    for i, j, d, how in pairs:
        a, b = ap[i], an[j]
        by_how[how] += 1
        if a["element"] != b["element"]:
            reassigned.append({"label": b["label"], "from": a["element"],
                               "to": b["element"]})
        if a["label"].strip().upper() != b["label"].strip().upper():
            renamed.append({"from": a["label"], "to": b["label"]})
        if how == "moved" and d is not None:
            moved.append({"label": b["label"], "d_A": round(d, 2)})
        if _is_h(a) or _is_h(b):
            continue            # riding H: occupancy and U follow the carrier
        if abs(a["occ"] - b["occ"]) > occ_tol:
            occ_changed.append({"label": b["label"],
                                "from": round(a["occ"], 3),
                                "to": round(b["occ"], 3)})
        if a["aniso"] != b["aniso"]:
            if b["aniso"]:
                iso_to_aniso += 1
            else:
                aniso_to_iso += 1
        if abs(a["u"] - b["u"]) > u_tol:
            u_changed.append({"label": b["label"], "from": round(a["u"], 4),
                              "to": round(b["u"], 4)})
    occ_changed.sort(key=lambda r: -abs(r["to"] - r["from"]))
    u_changed.sort(key=lambda r: -abs(r["to"] - r["from"]))
    moved.sort(key=lambda r: -r["d_A"])

    def electrons(atoms: list[dict[str, Any]]) -> float:
        return sum(atomic_number(a["element"]) * a["occ"] * a["mult"]
                   for a in atoms if not _is_h(a))

    e_before, e_after = electrons(ap), electrons(an)
    e_pct = (round(100.0 * (e_after - e_before) / e_before, 1)
             if e_before > 0 else None)
    removed_nonh = [{"label": a["label"], "element": a["element"]}
                    for a in removed if not _is_h(a)]
    added_nonh = [{"label": a["label"], "element": a["element"]}
                  for a in added if not _is_h(a)]
    n_h_before = sum(1 for a in ap if _is_h(a))
    n_h_after = sum(1 for a in an if _is_h(a))
    delta: dict[str, Any] = {
        "n_atoms": {"before": len(ap), "after": len(an)},
        "n_non_h_atoms": {"before": len(ap) - n_h_before,
                          "after": len(an) - n_h_after},
        "non_h_electrons_per_cell": {"before": round(e_before, 1),
                                     "after": round(e_after, 1),
                                     "change_pct": e_pct},
        "hydrogens": {"before": n_h_before, "after": n_h_after,
                      "added": sum(1 for a in added if _is_h(a)),
                      "removed": sum(1 for a in removed if _is_h(a))},
        "atoms_removed": removed_nonh[:LIST_CAP],
        "n_atoms_removed": len(removed_nonh),
        "atoms_added": added_nonh[:LIST_CAP],
        "n_atoms_added": len(added_nonh),
        "element_reassigned": reassigned[:LIST_CAP],
        "n_element_reassigned": len(reassigned),
        "atoms_renamed": renamed[:LIST_CAP],
        "n_atoms_renamed": len(renamed),
        "atoms_moved": moved[:LIST_CAP],
        "n_atoms_moved": len(moved),
        "occupancy_changed": occ_changed[:LIST_CAP],
        "n_occupancy_changed": len(occ_changed),
        "adp": {"iso_to_aniso": iso_to_aniso, "aniso_to_iso": aniso_to_iso,
                "u_changed": u_changed[:LIST_CAP],
                "n_u_changed": len(u_changed)},
        "matched": {"total": len(pairs), "by_label": by_how["label"],
                    "by_site": by_how["site"], "moved": by_how["moved"]},
        "symmetry_changed": not sym_ok,
        "tolerances": {"site_match_A": site_tol, "moved_A": moved_tol,
                       "occupancy": occ_tol, "u_A2": u_tol},
    }
    if not sym_ok:
        delta["symmetry"] = {
            "before": _symmetry_text(prev), "after": _symmetry_text(now)}
    delta["is_empty"] = not (removed or added or reassigned or moved
                             or occ_changed or u_changed or iso_to_aniso
                             or aniso_to_iso)
    delta["summary"] = "; ".join(delta_phrases(delta)) or "no model change"
    return delta


def _symmetry_text(snap: dict[str, Any]) -> str:
    s = snap.get("symmetry") or {}
    cell = s.get("unit_cell") or []
    return (f"{s.get('hall')} " + " ".join(f"{float(x):.3f}" for x in cell)
            ).strip()


def _items(rows: list[dict[str, Any]], fmt, n_total: int, cap: int = 4
           ) -> str:
    txt = ", ".join(fmt(r) for r in rows[:cap])
    if n_total > cap:
        txt += ", ..."
    return txt


def delta_phrases(delta: dict[str, Any]) -> list[str]:
    """The delta as short clauses ('lost 14 non-H atoms (12 C, 2 O)')."""
    ph: list[str] = []
    if delta.get("symmetry_changed"):
        ph.append("cell/space group changed (label-only comparison)")
    n = delta.get("n_atoms_removed", 0)
    if n:
        ph.append(f"lost {n} non-H atom{'s' if n > 1 else ''} "
                  f"({_elem_counts_text(delta['atoms_removed'])}"
                  f"{', ...' if n > len(delta['atoms_removed']) else ''})")
    n = delta.get("n_atoms_added", 0)
    if n:
        ph.append(f"gained {n} non-H atom{'s' if n > 1 else ''} "
                  f"({_elem_counts_text(delta['atoms_added'])}"
                  f"{', ...' if n > len(delta['atoms_added']) else ''})")
    n = delta.get("n_element_reassigned", 0)
    if n:
        ph.append(f"{n} element reassignment{'s' if n > 1 else ''} ("
                  + _items(delta["element_reassigned"],
                           lambda r: f"{r['label']} {r['from']}->{r['to']}",
                           n) + ")")
    h = delta.get("hydrogens") or {}
    if h.get("added") or h.get("removed"):
        ph.append(f"H {h.get('before')} -> {h.get('after')}")
    n = delta.get("n_occupancy_changed", 0)
    if n:
        ph.append(f"occupancy changed on {n} atom{'s' if n > 1 else ''} ("
                  + _items(delta["occupancy_changed"],
                           lambda r: f"{r['label']} {r['from']:.2f}->"
                                     f"{r['to']:.2f}", n) + ")")
    adp = delta.get("adp") or {}
    if adp.get("iso_to_aniso"):
        ph.append(f"{adp['iso_to_aniso']} atom"
                  f"{'s' if adp['iso_to_aniso'] > 1 else ''} isotropic -> "
                  "anisotropic")
    if adp.get("aniso_to_iso"):
        ph.append(f"{adp['aniso_to_iso']} atom"
                  f"{'s' if adp['aniso_to_iso'] > 1 else ''} anisotropic -> "
                  "isotropic")
    n = adp.get("n_u_changed", 0)
    if n:
        tol = (delta.get("tolerances") or {}).get("u_A2", U_TOL_A2)
        ph.append(f"U changed by > {tol} A^2 on {n} atom"
                  f"{'s' if n > 1 else ''} ("
                  + _items(adp["u_changed"],
                           lambda r: f"{r['label']} {r['from']:.3f}->"
                                     f"{r['to']:.3f}", n) + ")")
    n = delta.get("n_atoms_moved", 0)
    if n:
        tol = delta.get("tolerances") or {}
        ph.append(f"{n} atom{'s' if n > 1 else ''} moved "
                  f"{tol.get('site_match_A', SITE_MATCH_A)}-"
                  f"{tol.get('moved_A', MOVED_MATCH_A)} A ("
                  + _items(delta["atoms_moved"],
                           lambda r: f"{r['label']} {r['d_A']} A", n) + ")")
    n = delta.get("n_atoms_renamed", 0)
    if n:
        ph.append(f"{n} atom{'s' if n > 1 else ''} renamed (same sites)")
    return ph


def next_steps(delta: dict[str, Any] | None) -> str:
    """What to look at first, from the delta."""
    if not delta:
        return "re-check the edits since that node"
    acts: list[str] = []
    n = delta.get("n_atoms_removed", 0)
    if n:
        acts.append(f"restore or explain the {n} removed atom"
                    f"{'s' if n > 1 else ''}")
    n = delta.get("n_element_reassigned", 0)
    if n:
        acts.append("verify the element reassignment"
                    f"{'s' if n > 1 else ''} ("
                    + _items(delta["element_reassigned"],
                             lambda r: r["label"], n) + ")")
    n = delta.get("n_atoms_added", 0)
    if n:
        acts.append(f"check the {n} added atom{'s' if n > 1 else ''} "
                    "against the pre-mask difference map")
    h = delta.get("hydrogens") or {}
    if h.get("added") or h.get("removed"):
        acts.append("check the H placement (riding H change the framework "
                    "scattering)")
    if delta.get("n_occupancy_changed"):
        acts.append("check the changed occupancies")
    adp = delta.get("adp") or {}
    if adp.get("iso_to_aniso") or adp.get("aniso_to_iso") \
            or adp.get("n_u_changed"):
        acts.append("check the ADPs (iso/aniso, U jumps)")
    n = delta.get("n_atoms_moved", 0)
    if n:
        acts.append(f"check the {n} moved atom{'s' if n > 1 else ''}")
    return ", ".join(acts) or "re-check the edits since that node"


# --------------------------------------------------------------------------
# the node store: where was the last successful mask computed?
# --------------------------------------------------------------------------
def _info_key(info: Any) -> str | None:
    """Identity of a mask as node.json carries it. Nodes committed after a
    mask carry the SAME info dict forward until the mask is recomputed, so
    equal keys on a run of ancestors mean one mask; mask_id (written by
    solvent_mask since this module exists) is the first key of the dict
    and survives nodes._shrink's truncation, and older nodes fall back to
    the dumped text itself (truncated to the same length _shrink uses)."""
    if not isinstance(info, dict) or not info:
        return None
    if info.get("mask_id"):
        return "id:" + str(info["mask_id"])
    if "_truncated" in info:
        txt = str(info["_truncated"])
        m = re.search(r'"mask_id":\s*"([^"]+)"', txt)
        if m:
            return "id:" + m.group(1)
        if _scalar(info, "n_voids_masked") in (0, None):
            return None
        return "txt:" + txt[:_SHRINK_LIMIT]
    if not (info.get("n_voids_masked") or 0):
        return None
    try:
        return "txt:" + json.dumps(info, ensure_ascii=False,
                                   default=str)[:_SHRINK_LIMIT]
    except TypeError:
        return None


def _scalar(info: Any, key: str) -> Any:
    """A top-level scalar of the mask info, also out of a truncated dump."""
    if not isinstance(info, dict):
        return None
    if key in info:
        return info[key]
    txt = info.get("_truncated")
    if not isinstance(txt, str):
        return None
    m = re.search(r'"%s":\s*("([^"]*)"|-?\d+(?:\.\d+)?|true|false|null)'
                  % re.escape(key), txt)
    if not m:
        return None
    raw = m.group(1)
    if raw.startswith('"'):
        return m.group(2)
    if raw in ("true", "false"):
        return raw == "true"
    if raw == "null":
        return None
    return float(raw) if "." in raw else int(raw)


def mask_info_of(meta: dict[str, Any], node_dir: Path) -> dict[str, Any] | None:
    """The full mask info of a node: node.json's copy, or the f_mask.pkl
    snapshot when node.json only holds the truncated dump."""
    m = meta.get("mask") or {}
    info = m.get("info")
    if isinstance(info, dict) and "_truncated" not in info:
        return info
    pkl = Path(node_dir) / "f_mask.pkl"
    if pkl.exists():
        try:
            from libtbx import easy_pickle
            blob = easy_pickle.load(str(pkl))
            full = blob.get("info") if isinstance(blob, dict) else None
            if isinstance(full, dict):
                return full
        except Exception:  # noqa: BLE001 - cache only
            pass
    return info if isinstance(info, dict) else None


def _ancestry(store, node_id: str | None, limit: int = 10000
              ) -> list[dict[str, Any]]:
    chain: list[dict[str, Any]] = []
    seen: set[str] = set()
    nid = node_id
    while nid and nid not in seen and len(chain) < limit:
        try:
            meta = store.node_meta(nid)
        except (OSError, ValueError, KeyError):
            break
        seen.add(nid)
        chain.append(meta)
        nid = meta.get("parent")
    return chain


def _mask_runs(chain: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Contiguous runs of ancestors carrying the same mask, newest first;
    each run's oldest node is where that mask was computed."""
    runs: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    for pos, meta in enumerate(chain):
        key = _info_key((meta.get("mask") or {}).get("info")) \
            if meta.get("mask") else None
        if key is None:
            cur = None
            continue
        if cur is not None and cur["key"] == key:
            cur["nodes"].append((pos, meta))
        else:
            cur = {"key": key, "nodes": [(pos, meta)]}
            runs.append(cur)
    return runs


def _iso(ts: Any) -> str | None:
    try:
        return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(float(ts)))
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def _describe_run(store, run: dict[str, Any], relation: str
                  ) -> dict[str, Any]:
    pos, root = run["nodes"][-1]
    ndir = store.node_dir(root["id"])
    info = mask_info_of(root, ndir) or {}
    metrics = root.get("metrics") or {}
    best = None
    for _, n in run["nodes"]:
        r1 = (n.get("metrics") or {}).get("r1_strong")
        if n.get("metrics_current") and isinstance(r1, (int, float)):
            if best is None or r1 < best["r1"]:
                best = {"node": n.get("id"), "r1": r1}
    params = root.get("params") or {}
    post_ls = bool(root.get("tool") in ("refine", "run_shelxl")
                   and params.get("refresh_mask"))
    out = {
        "node": root.get("id"),
        "branch": root.get("branch"),
        "tool": root.get("tool"),
        "timestamp": _iso(root.get("ts")),
        "electrons": _scalar(info, "total_solvent_electrons_per_cell"),
        "n_voids": _scalar(info, "n_voids"),
        "n_voids_masked": _scalar(info, "n_voids_masked"),
        "solvent_volume_A3": _scalar(info, "solvent_volume_A3"),
        "solvent_volume_pct_of_cell": _scalar(info,
                                              "solvent_volume_pct_of_cell"),
        "converged": _scalar(info, "solvent_mask_converged"),
        "bypass_cycles": ((info.get("bypass") or {}).get("cycles_run")
                          if isinstance(info.get("bypass"), dict) else None),
        "r1": metrics.get("r1_strong"),
        "r1_is_current": bool(root.get("metrics_current")),
        "best_r1_with_this_mask": best,
        "params": (root.get("mask") or {}).get("params"),
        "weights": root.get("weights"),
        "scale_k": root.get("scale_k"),
        "relation": relation,
        "commits_since": pos,
        "n_nodes_with_this_mask": len(run["nodes"]),
        "_model_path": str(ndir / "model.res"),
    }
    if out["r1"] is not None and not out["r1_is_current"]:
        out["r1_note"] = ("R1 of the last refinement before this node "
                          "(the mask call itself refines nothing)")
    if post_ls:
        out["model_note"] = ("mask computed inside refine(refresh_mask) - "
                             "the node model is the post-refinement one")
    return out


def previous_mask_from_store(store, session_info: dict[str, Any] | None = None
                             ) -> dict[str, Any] | None:
    """The last successful mask on record and the node it was computed on.

    Walks the active node's ancestry; the mask the session currently
    refines with (session_info) wins when it is found there, else the most
    recent mask in the ancestry, else the most recent masked node anywhere
    in the tree (relation says which). Also names the last CONVERGED mask
    when the chosen one had not converged."""
    st = store.state()
    active = st.get("active_node")
    chain = _ancestry(store, active)
    runs = _mask_runs(chain)
    chosen = None
    relation = "ancestor of the active node"
    want = _info_key(session_info) if session_info else None
    if want is not None:
        chosen = next((r for r in runs if r["key"] == want), None)
    if chosen is None and runs:
        chosen = runs[0]
    if chosen is None:
        newest = None
        for ndir in store.nodes_dir.iterdir():
            mp = ndir / "node.json"
            if not mp.exists():
                continue
            try:
                meta = json.loads(mp.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if _info_key((meta.get("mask") or {}).get("info")) is None:
                continue
            if newest is None or (meta.get("ts") or 0) > (newest.get("ts")
                                                          or 0):
                newest = meta
        if newest is None:
            return None
        chain = _ancestry(store, newest.get("id"))
        runs = _mask_runs(chain)
        if not runs:
            return None
        chosen = runs[0]
        relation = f"another branch ({newest.get('branch')})"
    out = _describe_run(store, chosen, relation)
    out["active_node"] = active
    if not out.get("converged"):
        for r in runs:
            if r is chosen:
                continue
            _, root = r["nodes"][-1]
            info = mask_info_of(root, store.node_dir(root["id"])) or {}
            if _scalar(info, "solvent_mask_converged"):
                out["last_converged_mask"] = {
                    "node": root.get("id"),
                    "electrons": _scalar(
                        info, "total_solvent_electrons_per_cell"),
                    "r1": (root.get("metrics") or {}).get("r1_strong")}
                break
    return out


# --------------------------------------------------------------------------
# the diagnosis block
# --------------------------------------------------------------------------
def _num(x: Any) -> float | None:
    try:
        return None if x is None else float(x)
    except (TypeError, ValueError):
        return None


def params_diff(prev_params: dict[str, Any] | None,
                now_params: dict[str, Any] | None) -> list[dict[str, Any]]:
    out = []
    prev_params = prev_params or {}
    now_params = now_params or {}
    for k in MASK_PARAM_KEYS:
        a, b = _num(prev_params.get(k)), _num(now_params.get(k))
        if a is None and b is None:
            continue
        if a is None or b is None or abs(a - b) > 1e-9:
            out.append({"param": k, "previous": prev_params.get(k),
                        "now": now_params.get(k)})
    return out


def _fmt_r1(r1: Any) -> str:
    return f"R1 {r1:.3f}" if isinstance(r1, (int, float)) else "R1 n/a"


def _fmt_e(e: Any) -> str:
    return f"{e:.0f} e" if isinstance(e, (int, float)) else "? e"


def compose_reading(outcome: str, prev: dict[str, Any] | None,
                    delta: dict[str, Any] | None, change_pct: float | None,
                    kept: bool, params_changed: list[dict[str, Any]],
                    active: str | None, why: str | None = None,
                    scale_weights: dict[str, Any] | None = None) -> str:
    """Two or three sentences a crystallographer would say, built from the
    delta and the outcome - not a fixed script."""
    here = active or "the current node"
    if prev is None:
        head = ("No earlier successful solvent mask is on record for this "
                "project, so there is no reference model to diff against. ")
        tails = {
            "negative_dropped": (
                "The negative void integral is a statement about the "
                "current model (framework too light: atoms or H missing, "
                "elements too light, isotropic or absent ADPs), not about "
                "the void being empty - complete the framework, commit, and "
                "re-run solvent_mask; the next call will diff against this "
                "one."),
            "nothing_masked": (
                "Nothing was masked: complete the framework and re-run "
                "solvent_mask; the next call will diff against this one."),
            "no_voids": (
                "No solvent-accessible void was found on this model; the "
                "next mask call will diff against it."),
            "diverged": (
                "The BYPASS series diverged on this first mask: the "
                "framework model is not yet complete or is mis-scaled - "
                "improve the model and re-run; the next call will diff "
                "against this one."),
            "not_converged": (
                "The series did not settle on this first mask; raise "
                "max_cycles or improve the model - the next call will diff "
                "against this one."),
        }
        return head + tails.get(outcome, "Later calls will diff against "
                                         "this mask.")

    node = prev.get("node")
    ref = f"node {node}" if node else "the previous mask of this session"
    conv_word = "converged" if prev.get("converged") else "successful"
    r1_txt = _fmt_r1(prev.get("r1"))
    best = prev.get("best_r1_with_this_mask") or {}
    best_txt = (f", best R1 with it {best['r1']:.3f} at node {best['node']}"
                if isinstance(best.get("r1"), (int, float))
                and best.get("node") != node else "")
    where = f"{ref} ({_fmt_e(prev.get('electrons'))}, {r1_txt}{best_txt})"
    kept_txt = (f" The last {conv_word} mask ({ref}) is kept in the session."
                if kept else
                (f" No mask is stored now - checkout {node} to continue "
                 f"with the last {conv_word} mask." if node else ""))
    cmp_txt = (f"checkout {node} and compare_nodes({node}, {here})"
               if node else "compare with the model of that call")

    if delta is None:
        return (f"The last {conv_word} mask was computed at {where}; its "
                "model could not be loaded for a diff"
                + (f": {why}" if why else "")
                + f". Do the comparison by hand ({cmp_txt}) before touching "
                f"the mask.{kept_txt}")

    if delta.get("is_empty"):
        s = (f"No model change since {where} - this is a mask-parameter or "
             "grid effect: compare solvent_radius/shrink/resolution_factor/"
             "d_min with the previous call.")
        if params_changed:
            s += (" Changed in this call: " + ", ".join(
                f"{p['param']} {p['previous']} -> {p['now']}"
                for p in params_changed) + ".")
        else:
            sw = ""
            if scale_weights and scale_weights.get("changed"):
                sw = (f" (scale_k {scale_weights.get('scale_k_before')} -> "
                      f"{scale_weights.get('scale_k_after')}, weights "
                      f"{scale_weights.get('weights_before')} -> "
                      f"{scale_weights.get('weights_after')})")
            s += (" The parameters are identical too, so the difference "
                  f"comes from the refinement state{sw} or the data (a "
                  f"re-merge or resolution cutoff) - {cmp_txt}, then re-run "
                  "solvent_mask from that node to confirm.")
        n_ren = delta.get("n_atoms_renamed", 0)
        if n_ren:
            s += (f" ({n_ren} atom{'s' if n_ren > 1 else ''} renamed since "
                  "then - same sites, same atoms.)")
        if outcome in ("negative_dropped", "nothing_masked", "no_voids"):
            s += (" A negative integral on an unchanged model is not "
                  "evidence of an empty void." + kept_txt)
        elif outcome == "diverged":
            s += (" A diverged series on an unchanged model points at the "
                  "grid or the parameters, not at the model.")
        elif outcome == "not_converged":
            s += (" An unsettled series on an unchanged model: raise "
                  "max_cycles rather than editing the model.")
        elif change_pct is not None:
            s += (f" The count moved {change_pct:+.0f}% on an unchanged "
                  "model" + (" - a grid/parameter effect." if params_changed
                             else "; treat both counts as the same mask."))
        return s

    e = delta.get("non_h_electrons_per_cell") or {}
    e_b, e_a = e.get("before"), e.get("after")
    e_pct = e.get("change_pct")
    e_txt = (f"; non-H electrons per cell {e_b:.0f} -> {e_a:.0f}"
             + (f" ({e_pct:+.0f}%)" if isinstance(e_pct, (int, float))
                else "")
             if isinstance(e_b, (int, float)) and isinstance(e_a, (int, float))
             else "")
    s1 = (f"Since the last {conv_word} mask ({where}) the model changed: "
          + "; ".join(delta_phrases(delta)) + e_txt + ".")
    lighter = (isinstance(e_b, (int, float)) and isinstance(e_a, (int, float))
               and e_a < e_b - 0.5)
    heavier = (isinstance(e_b, (int, float)) and isinstance(e_a, (int, float))
               and e_a > e_b + 0.5)
    if outcome in ("negative_dropped", "nothing_masked", "no_voids"):
        what = ("the void integral went negative" if outcome ==
                "negative_dropped" else "nothing was masked")
        if outcome == "no_voids":
            s2 = (" No solvent-accessible void is left on this model: the "
                  "atoms added since then fill the region the mask covered "
                  "- decide whether they are real (pre-mask difference map) "
                  "before choosing between model and mask.")
        elif lighter:
            s2 = (f" So {what} because the framework region is now lighter "
                  "(the zero-mean difference map pushes the deficit into "
                  "the void), not because the void is empty.")
        elif heavier:
            s2 = (f" The model gained scattering, yet {what}: what was "
                  "added is probably in the wrong place or too heavy "
                  "(mis-assigned elements, occupancies), which the "
                  "zero-mean difference map balances inside the void - "
                  "the void is not empty.")
        else:
            s2 = (f" The scattering total is unchanged, so {what} follows "
                  "from how it is distributed now (ADPs, H, element "
                  "assignments), not from an empty void.")
        s2 += kept_txt
    elif outcome == "diverged":
        s2 = (" The BYPASS series diverged on this changed model: the "
              "runaway is the model change speaking, not mask instability, "
              "and the count is not a measurement.")
    elif outcome == "not_converged":
        s2 = (" The series did not settle on this changed model - treat the "
              "count as provisional, and read the change through the "
              "delta, not as instability.")
    else:
        if change_pct is not None and abs(change_pct) > CHANGE_SIGNAL_PCT:
            s2 = (f" The count moved {change_pct:+.0f}%: with this delta "
                  "that is a model-change signal, not mask instability - "
                  "the mask absorbs whatever the model "
                  f"{'lost' if lighter else 'gained' if heavier else 'redistributed'}.")
        elif change_pct is not None:
            s2 = (f" The count moved {change_pct:+.0f}%, within the "
                  "model-change signal threshold; the mask is behaving.")
        else:
            s2 = ""
    s3 = (f" Next: {cmp_txt}; {next_steps(delta)}, then re-run "
          "solvent_mask - do not delete atoms and recompute the mask in "
          "the same step.")
    if params_changed:
        s3 += (" (Mask parameters also changed in this call: " + ", ".join(
            f"{p['param']} {p['previous']} -> {p['now']}"
            for p in params_changed) + " - one change at a time.)")
    return s1 + s2 + s3


def diagnose(ctx, ses, *, outcome: str, prev_info: dict[str, Any] | None,
             prev_snapshot: dict[str, Any] | None,
             current_electrons: float | None, params: dict[str, Any] | None,
             kept_previous: bool) -> dict[str, Any]:
    """Assemble the mask_diagnosis block for a solvent_mask result.

    The previous mask is looked up in the project's node store (found
    through the RunStore directory, as the ghost ledger does), falling
    back to the session's own snapshot of the model it masked last
    (solvent_mask_model) when the session has no project. Never raises
    for a store problem: the block then says what could not be done."""
    out: dict[str, Any] = {"outcome": outcome}
    prev: dict[str, Any] | None = None
    source: str | None = None
    prev_model: Any = None
    why: str | None = None
    active: str | None = None
    try:
        from ..refine.ghost_ledger import project_dir_from_ctx
        project_dir = project_dir_from_ctx(ctx)
    except Exception:  # noqa: BLE001
        project_dir = None
    if project_dir is not None:
        try:
            from ..refine.nodes import NodeStore
            store = NodeStore(project_dir)
            active = store.state().get("active_node")
            prev = previous_mask_from_store(store, prev_info or None)
            if prev is not None:
                source = "project node store"
        except Exception as e:  # noqa: BLE001 - diagnosis must not fail
            why = f"node store unreadable: {type(e).__name__}: {e}"
    if prev is not None:
        path = prev.pop("_model_path", None)
        try:
            from ..io.shelx_model import load_res_model
            prev_model = load_res_model(path).structure
        except Exception as e:  # noqa: BLE001
            why = (f"model.res of node {prev.get('node')} unreadable: "
                   f"{type(e).__name__}: {e}")
    elif prev_snapshot and prev_snapshot.get("atoms"):
        prev = {"node": None,
                "timestamp": prev_snapshot.get("timestamp"),
                "electrons": prev_snapshot.get("electrons"),
                "n_voids": prev_snapshot.get("n_voids"),
                "n_voids_masked": prev_snapshot.get("n_voids_masked"),
                "solvent_volume_A3": prev_snapshot.get("solvent_volume_A3"),
                "converged": prev_snapshot.get("converged"),
                "r1": prev_snapshot.get("r1"),
                "params": prev_snapshot.get("params"),
                "relation": "earlier call in this session (no node store)"}
        source = "session snapshot"
        prev_model = prev_snapshot
    elif prev_info:
        prev = {"node": None,
                "electrons": prev_info.get("total_solvent_electrons_per_cell"),
                "n_voids": prev_info.get("n_voids"),
                "n_voids_masked": prev_info.get("n_voids_masked"),
                "solvent_volume_A3": prev_info.get("solvent_volume_A3"),
                "converged": prev_info.get("solvent_mask_converged"),
                "relation": "earlier call in this session (no model kept)"}
        source = "session flags"
        why = "no model snapshot of the previous mask in this session"
    out["previous_mask"] = prev
    out["previous_mask_source"] = source
    out["active_node"] = active
    if prev is not None and prev.get("last_converged_mask"):
        out["last_converged_mask"] = prev.pop("last_converged_mask")

    delta = None
    if prev_model is not None and getattr(ses, "model", None) is not None:
        try:
            delta = model_delta(prev_model, ses.model)
        except Exception as e:  # noqa: BLE001
            why = f"model diff failed: {type(e).__name__}: {e}"
    out["model_delta"] = delta
    if why:
        out["model_delta_unavailable"] = why

    pct = None
    prev_e = _num(prev.get("electrons")) if prev else None
    if prev_e and prev_e > 0 and current_electrons is not None:
        pct = round(100.0 * (float(current_electrons) - prev_e) / prev_e, 1)
    out["electron_change_pct"] = pct
    out["current_electrons"] = (None if current_electrons is None
                                else round(float(current_electrons), 1))
    changed = params_diff(prev.get("params") if prev else None, params)
    out["mask_params_changed"] = changed

    sw = None
    if prev and (prev.get("weights") is not None
                 or prev.get("scale_k") is not None):
        flags = getattr(ses, "flags", {}) or {}
        w_now = flags.get("weights")
        k_now = flags.get("scale_k")
        w_prev, k_prev = prev.get("weights"), prev.get("scale_k")
        w_changed = bool(
            isinstance(w_prev, dict) and isinstance(w_now, dict) and any(
                abs((_num(w_prev.get(k)) or 0.0)
                    - (_num(w_now.get(k)) or 0.0)) > 1e-6
                for k in ("a", "b")))
        k_changed = bool(k_prev is not None and k_now is not None
                         and abs(float(k_prev) - float(k_now))
                         > 0.02 * max(abs(float(k_prev)), 1e-9))
        sw = {"weights_before": w_prev, "weights_after": w_now,
              "scale_k_before": k_prev, "scale_k_after": k_now,
              "changed": w_changed or k_changed}
        out["scale_weights"] = sw

    out["reading"] = compose_reading(outcome, prev, delta, pct, kept_previous,
                                     changed, active, why, sw)
    out["rule"] = RULE
    return out
