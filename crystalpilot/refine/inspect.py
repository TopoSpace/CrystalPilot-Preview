"""Model inspection engine: what a crystallographer reads off the screen.

ASU-level bonded environment (symmetry-aware), metal coordination with
distances/angles and tau4/tau5 geometry indices, organic fragment
decomposition with ring census and dangling-atom detection, plus per-atom
ADP/occupancy suspect flags (same thresholds RefineLS reports).
"""
from __future__ import annotations

import math
from typing import Any

from ..chem.bonding import KIND_METAL_METAL, KIND_NON_BONDED, is_metal_element
from ..chem.knowledge import cn_status
from ..chem.shape import SHAPES_BY_CN, cshm


class NeighborTable(list):
    """`[[{j, label, element, d, sym, site_frac, kind, op}], ...]` per ASU
    atom, plus the `chem.bonding.BondTable` it was read from (`.bonds`), so
    consumers that need the classified table - coordination numbers with the
    eta-ring convention, the hidden `non_bonded_close` contacts - do not run
    the engine a second time. It IS a list: every existing consumer indexes,
    iterates and truth-tests it unchanged."""

    bonds: Any = None


def _neighbor_table(xs, part_kwargs: dict | None = None
                    ) -> NeighborTable:
    """Per-ASU-atom bonded neighbours, read from the ONE bonding truth
    (`chem.bonding.bond_table`, migration 1 of plan R2.1).

    Rows are the classified edges whose kind is not `non_bonded_close`:
    the chelating carboxylate carbon at 2.5 A from its metal, the riding
    O-H hydrogen leaning at a large metal and the La...C(arene) 3.2 A
    contact are no longer neighbours here (they were, under the raw smtbx
    search radius - see tests/test_bonding_status_quo.py for the before /
    after). Each row carries `kind` (covalent / coordination / eta /
    metal_metal) and the operator string `op`.

    part_kwargs (from refine.nodes.part_connectivity_kwargs) applies SHELX
    PART semantics so overlapping disorder alternatives are not reported as
    bonded to each other."""
    from cctbx import sgtbx

    from ..chem.bonding import bond_table
    table = bond_table(xs, part_kwargs=part_kwargs)
    scs = list(xs.scatterers())
    labels = table.labels
    elems = table.elements
    out = NeighborTable([] for _ in scs)
    for i in range(len(scs)):
        nbrs = []
        for e in table.by_atom(i):
            sj = sgtbx.rt_mx(e.op) * scs[e.j].site
            nbrs.append({"j": int(e.j), "label": labels[e.j],
                         "element": elems[e.j],
                         "d": round(float(e.d), 3),
                         "sym": e.is_symmetry_image,
                         "site_frac": tuple(float(x) for x in sj),
                         "kind": e.kind, "op": e.op})
        nbrs.sort(key=lambda n: n["d"])
        out[i] = nbrs
    out.bonds = table
    return out


def _angle(uc, si, sj, sk) -> float:
    """Angle j-i-k in degrees from fractional sites."""
    import numpy as np
    pi = np.array(uc.orthogonalize(si))
    vj = np.array(uc.orthogonalize(sj)) - pi
    vk = np.array(uc.orthogonalize(sk)) - pi
    c = float(np.dot(vj, vk) / (np.linalg.norm(vj) * np.linalg.norm(vk)))
    return math.degrees(math.acos(max(-1.0, min(1.0, c))))


def _coordination_shape(uc, site, coord, n_eta: int) -> dict[str, Any]:
    """Continuous shape measure of the ligand-ATOM polyhedron, reported next
    to tau4/tau5 (round-2 R4, `chem.shape.cshm`).

    A vertex measure: it applies when every ligand is a sigma-bound atom and
    the vertex count has tabulated references (4/5/6). An eta-bound ring
    contributes five or six vertices where `cn` counts one ligand, so for a
    hapto sphere the vertex polyhedron is not the coordination polyhedron
    and nothing is measured - the row says so instead. Three keys when
    measured: `cshm` {reference: S}, `closest_shape`, `closest_cshm`; the
    closest reference is the smallest S, never a classification."""
    n = len(coord)
    if n_eta:
        return {"shape_note": f"CShM not measured: {n_eta} eta-bound atom(s) "
                              f"in the sphere - a vertex measure does not "
                              f"describe a hapto ligand"}
    if n not in SHAPES_BY_CN:
        if n >= 7:
            return {"shape_note": f"CShM not measured: no reference polyhedra "
                                  f"tabulated for {n} vertices (CN 4/5/6 only)"}
        return {}
    s = cshm(uc.orthogonalize(site),
             [uc.orthogonalize(nb["site_frac"]) for nb in coord])
    return {"cshm": s["cshm"], "closest_shape": s["closest_shape"],
            "closest_cshm": s["closest_cshm"]}


def metal_environments(xs, neighbor_table=None) -> list[dict[str, Any]]:
    """One row per metal: ligands, metal-metal contacts, the largest L-M-L
    angles, tau4/tau5, and the coordination number.

    `cn` follows the bonding truth: an eta-bound ring counts once, as one
    ligand (ferrocene is CN 2, not 10), `non_bonded_close` contacts never
    count. `cn_plausible` is three-state (True / False / None = no
    MetalProfile window for this element, NOT checked)."""
    nbt = neighbor_table or _neighbor_table(xs)
    bonds = getattr(nbt, "bonds", None)
    uc = xs.unit_cell()
    scs = list(xs.scatterers())
    out = []
    for i, sc in enumerate(scs):
        el = sc.scattering_type.strip().capitalize()
        if not is_metal_element(el):
            continue
        # coordination sphere: everything that is not a metal-metal contact
        # (those are listed apart) and not a hidden non-bonded contact
        coord = [n for n in nbt[i]
                 if n.get("kind", "") not in (KIND_METAL_METAL, KIND_NON_BONDED)
                 and not is_metal_element(n["element"])]
        mm = [n for n in nbt[i]
              if n.get("kind") == KIND_METAL_METAL or is_metal_element(n["element"])]
        cn = bonds.cn(i) if bonds is not None else len(coord)
        st = cn_status(el, cn)
        angles = []
        for a in range(len(coord)):
            for b in range(a + 1, len(coord)):
                ang = _angle(uc, sc.site, coord[a]["site_frac"], coord[b]["site_frac"])
                angles.append(round(ang, 1))
        angles.sort(reverse=True)
        tau4 = tau5 = None
        if len(coord) == 5 and len(angles) >= 2:
            tau5 = round((angles[0] - angles[1]) / 60.0, 3)
        if len(coord) == 4 and len(angles) >= 2:
            tau4 = round((360.0 - (angles[0] + angles[1])) / 141.0, 3)
        n_eta = sum(1 for n in coord if n.get("kind") == "eta")
        shape = _coordination_shape(uc, sc.site, coord, n_eta)
        out.append({
            "atom": sc.label, "element": el, "cn": cn,
            "cn_plausible": st["plausible"], "expected_cn": st["expected_cn"],
            **({"n_eta_atoms": n_eta} if n_eta else {}),
            "neighbors": [f"{n['label']}{'*' if n['sym'] else ''}:{n['d']}"
                          for n in coord],
            "metal_metal": [f"{n['label']}{'*' if n['sym'] else ''}:{n['d']}"
                            for n in mm],
            "largest_angles": angles[:4],
            "tau4": tau4, "tau5": tau5,
            **shape,
        })
    return out


def organic_fragments(xs, neighbor_table=None) -> list[dict[str, Any]]:
    """Connected non-metal fragments in the ASU graph (unit-mx bonds), with
    ring census and dangling-atom (broken-ring symptom) detection."""
    nbt = neighbor_table or _neighbor_table(xs)
    scs = list(xs.scatterers())
    elems = [sc.scattering_type.strip().capitalize() for sc in scs]
    labels = [sc.label for sc in scs]
    organic = [i for i in range(len(scs))
               if not is_metal_element(elems[i]) and elems[i] != "H"]
    # ASU graph: direct (non-sym) bonds between organic atoms
    adj: dict[int, set[int]] = {i: set() for i in organic}
    sym_bonded: set[int] = set()
    for i in organic:
        for n in nbt[i]:
            j = n["j"]
            if j in adj and not n["sym"] and j != i:
                adj[i].add(j)
            if (n["sym"] and n["element"] not in ("H",)
                    and not is_metal_element(n["element"])):
                sym_bonded.add(i)
    seen: set[int] = set()
    frags = []
    for start in organic:
        if start in seen:
            continue
        comp = []
        stack = [start]
        seen.add(start)
        while stack:
            u = stack.pop()
            comp.append(u)
            for v in adj[u]:
                if v not in seen:
                    seen.add(v)
                    stack.append(v)
        counts: dict[str, int] = {}
        for u in comp:
            counts[elems[u]] = counts.get(elems[u], 0) + 1
        rings = _rings_in(adj, comp)
        dangling = [labels[u] for u in comp
                    if elems[u] == "C" and len(adj[u]) <= 1
                    and u not in sym_bonded]
        ordered = sorted(comp)
        local = {u: k for k, u in enumerate(ordered)}
        frags.append({
            "atoms": [labels[u] for u in ordered],
            "element_counts": counts,
            "n_atoms": len(comp),
            "rings": [{"size": len(r), "atoms": [labels[u] for u in r]}
                      for r in rings],
            "dangling_C": dangling,
            "sym_bonded_atoms": [labels[u] for u in comp if u in sym_bonded],
            # local-index graph for ligand matching (stripped from tool output)
            "_elements": [elems[u] for u in ordered],
            "_local_adj": [set(local[v] for v in adj[u]) for u in ordered],
        })
    frags.sort(key=lambda f: -f["n_atoms"])
    return frags


def _rings_in(adj: dict[int, set[int]], comp: list[int],
              max_size: int = 7) -> list[list[int]]:
    """Small-ring census (size 3..max_size) via bounded DFS; dedup by set."""
    comp_set = set(comp)
    rings: list[list[int]] = []
    seen_sets: set[frozenset] = set()

    def dfs(path: list[int]) -> None:
        u = path[-1]
        for v in adj[u]:
            if v not in comp_set:
                continue
            if v == path[0] and len(path) >= 3:
                key = frozenset(path)
                if key not in seen_sets:
                    seen_sets.add(key)
                    rings.append(list(path))
            elif v not in path and len(path) < max_size:
                if v > path[0]:      # canonical start = smallest index
                    dfs(path + [v])

    for start in sorted(comp_set):
        dfs([start])
    # keep minimal rings only (drop rings that are unions of smaller ones)
    rings.sort(key=len)
    minimal: list[list[int]] = []
    for r in rings:
        rs = set(r)
        if not any(set(m) < rs for m in minimal):
            minimal.append(r)
    return minimal


def atom_table(xs, unknown_adp_labels: list[str] | None = None) -> list[dict[str, Any]]:
    from cctbx import adptbx
    uc = xs.unit_cell()
    unknown = {label.upper() for label in unknown_adp_labels or []}
    out = []
    for sc in xs.scatterers():
        el = sc.scattering_type.strip().capitalize()
        u_eq = (adptbx.u_star_as_u_iso(uc, sc.u_star)
                if sc.flags.use_u_aniso() else sc.u_iso)
        issue = None
        adp_known = sc.label.upper() not in unknown
        if adp_known and el != "H":
            if u_eq < 0.002:
                issue = "U too small (element likely too light for this density)"
            elif u_eq > 0.20:
                issue = "U very large (ghost, too-heavy element, or disorder)"
            elif u_eq > 0.12 and is_metal_element(el):
                issue = "U large for a metal (wrongly promoted light atom?)"
            if sc.flags.use_u_aniso() and not adptbx.is_positive_definite(sc.u_star):
                issue = "non-positive-definite ADP"
        out.append({"label": sc.label, "element": el,
                    "site": [round(x, 5) for x in sc.site],
                    "occ": round(float(sc.occupancy), 3),
                    "sof": round(float(sc.weight()), 4),
                    "multiplicity": int(sc.multiplicity()),
                    "u_eq": round(float(u_eq), 4) if adp_known else None,
                    **({"adp_known": False, "adp_note": "ADP not reported"} if not adp_known else {}),
                    "aniso": bool(sc.flags.use_u_aniso()),
                    **({"issue": issue} if issue else {})})
    return out


def disorder_groups_view(xs, flags: dict | None = None,
                         neighbor_table=None) -> list[dict[str, Any]]:
    """One row per PART/FVAR disorder group: components, the refined
    occupancy WITH ITS S.U. if a SHELXL job has read one back, the
    acceptance verdict and what to do about it.

    Until T1.6 a split was invisible here - inspect_model listed the extra
    atoms and nothing said they were two halves of one thing, let alone
    whether the data supported the division. A group with no refined free
    variable yet reads `pending`, never `supported`.
    """
    from .disorder_accept import group_acceptance
    out: list[dict[str, Any]] = []
    for g in (flags or {}).get("disorder_groups") or []:
        fv = g.get("free_variable") or {}
        try:
            blk = group_acceptance(
                xs, g,
                free_var=({"value": fv.get("value"), "su": fv.get("su")}
                          if fv.get("su") is not None else None),
                neighbor_table=neighbor_table, with_restraints=False)
        except Exception as e:  # noqa: BLE001 - advisory view
            out.append({"fvar_index": g.get("fvar_index"),
                        "error": f"disorder reading unavailable: {e}"})
            continue
        out.append({
            "fvar_index": blk["fvar_index"],
            "components": blk["components"],
            "free_variable": blk["free_variable"],
            "verdict": blk["verdict"],
            "disposition": blk["disposition"],
            "occupancy": blk["occupancy"],
            "closest_A_B_A": blk["separation"].get("d_A"),
            **({"adp_reading": blk["adp"]["reading"]}
               if blk["adp"].get("reading") else {}),
            "undo": blk["undo"],
        })
    for lbl, part in ((flags or {}).get("parts_extra") or {}).items():
        out.append({
            "atom": lbl, "part": part, "fvar_index": None,
            "verdict": "n/a",
            "disposition": (
                "a PART block with no free variable: either a component "
                "disordered about a symmetry element (its image is the "
                "partner, ratio fixed at 50:50 by symmetry - there is "
                "nothing to refine and nothing to judge) or a plain sof "
                "SHELXL wrote back. model_disorder(undo='"
                + str(lbl) + "') removes it if this tool created it."),
        })
    return out


def inspect_model(xs, detail: str = "summary",
                  flags: dict | None = None) -> dict[str, Any]:
    from .nodes import part_connectivity_kwargs
    nbt = _neighbor_table(
        xs, part_connectivity_kwargs(flags or {}, xs.scatterers()))
    scs = list(xs.scatterers())
    labels = [sc.label for sc in scs]
    atoms = atom_table(xs, (flags or {}).get("unknown_adp_labels"))
    metals = metal_environments(xs, nbt)
    frags = organic_fragments(xs, nbt)
    summary = {
        "n_atoms": len(scs),
        "element_counts": _counts(atoms),
        "space_group": str(xs.space_group_info()),
        "metals": metals,
        "organic_fragments": [
            {k: f[k] for k in ("element_counts", "n_atoms", "dangling_C",
                               "sym_bonded_atoms")}
            | {"n_rings": len(f["rings"]),
               "ring_sizes": [r["size"] for r in f["rings"]]}
            for f in frags],
        "suspects": [a for a in atoms if a.get("issue")],
        "isolated_atoms": [labels[i] for i in range(len(scs))
                           if not nbt[i]
                           and scs[i].scattering_type.strip().capitalize() != "H"],
    }
    dis = disorder_groups_view(xs, flags, nbt)
    if dis:
        summary["disorder_groups"] = dis
    if detail == "summary":
        return summary
    summary["atoms"] = atoms
    if detail == "full":
        summary["organic_fragments"] = [
            {k: v for k, v in f.items() if not k.startswith("_")} for f in frags]
        summary["bonds"] = [
            {"atom": labels[i],
             "neighbors": [f"{n['label']}{'*' if n['sym'] else ''}:{n['d']}"
                           for n in nbt[i]]}
            for i in range(len(scs))
            if scs[i].scattering_type.strip().capitalize() != "H"]
    return summary


def _counts(atoms: list[dict]) -> dict[str, int]:
    c: dict[str, int] = {}
    for a in atoms:
        c[a["element"]] = c.get(a["element"], 0) + 1
    return c
