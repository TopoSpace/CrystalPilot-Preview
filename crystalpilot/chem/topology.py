"""Topology of the bonded net: interpenetration, node-linker simplification,
a gated Systre bridge and helical chains (round-2 plan R4).

Everything here reads ONE truth: `chem.bonding.bond_table` placed on the P1
expansion by `chem.connectivity.analyze_connectivity`. No distance criterion
is invented in this module - the edges and their lattice shifts arrive
classified, and the periodic-component machinery (BFS carrying the cell
translation, dimensionality = rank of the translation-mismatch lattice) is
the same algorithm `connectivity.analyze_connectivity` runs for its
fragments, re-expressed here on an atom SUBSET (the host, one cluster, one
linker) because that module only exposes whole-structure fragments.

Every answer carries its definition text. The labels are descriptive - a
simplified net is a DESCRIPTION offered for a crystallographer to check, not
a verdict, and `confidence` names the cases where the description can be
wrong (unusual SBUs, rod nodes, branch linkers, terminal groups).

Not in this module, on purpose (plan R4 "形状/形貌的诚实边界"): automatic
lantern/pear naming, mechanical interlocking of finite molecules
(catenane/rotaxane), an RCSR symbol without Systre, topological chirality.
"""
from __future__ import annotations

import time

import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]

#: an operator image lands ON the target net when every mapped atom sits
#: within this fractional tolerance of a target atom of the same element
MATCH_TOL_FRAC = 0.02

#: pairwise symmetry relation is O(n_ops x n_atoms^2); a structure with more
#: periodic components than this reports the relations of the largest ones
#: and says the rest were not compared
MAX_NETS_COMPARED = 12

#: candidate translations tried per (net, op) pair - the anchor atom of the
#: rarest element is matched against every target atom of that element
MAX_TRANSLATION_CANDIDATES = 256

SYSTRE_MAIN = "org.gavrog.apps.systre.SystreCmdline"
SYSTRE_JAR_GLOB = "vendor/gavrog/*.jar"

# ------------------------------------------------------------- definitions

DEF_NETS = (
    "独立网 = 去客体后宿主的周期性连通分量：带晶格平移标签的 BFS，"
    "维度 = 平移失配格的秩；维度 ≥1 的分量各算一个网。"
    "symmetry_related 只表示维度 ≥2 的网可由平移或空间群操作逐原子映射，"
    f"同元素的分数坐标偏差 < {MATCH_TOL_FRAC}；symmetry_related_1d 表示一维链的同类关系。"
    "对称相关不等于互穿（平行层也可对称相关），没有找到映射的 independent "
    "也不排除不同类型网的互穿。互穿由环穿越判定（chem/threading.py）：每个网"
    "按金属簇–连接子规则（无金属时按分支点）收缩，取收缩图里过每条边的最短环"
    "（≤12 个节点）作窗口，窗口用质心扇面张成，另一网的任一原子级键（直线段）"
    "穿过扇面即穿越；一对网只要有一个窗口被穿就是 interpenetrated（维度 ≥2）"
    "或 interlocked_1d（一维链）。搜索或穿越检验未跑完 → null 并说明；链里"
    "没有环 → not_testable（无环缠绕看不见）；棒状 SBU → inconclusive。"
)

DEF_NETS_EN = (
    "A net is a periodic connected component of the host, with dimensionality "
    "given by the rank of lattice-shift mismatches. symmetry_related reports "
    "atom-wise translation/space-group mapping between nets of dimension >=2; "
    "symmetry_related_1d reports the corresponding chain relation. "
    f"Element-aware matching uses {MATCH_TOL_FRAC} fractional tolerance. "
    "A symmetry mapping is NOT proof of interpenetration (parallel layers also "
    "map), and independent nets may still interpenetrate. Interpenetration is "
    "decided by ring threading (chem/threading.py): each net is contracted "
    "(metal clusters / branch points to nodes), the shortest cycle through "
    "every edge (<= 12 nodes) is a window spanned by its centroid fan, and a "
    "straight atom-level bond of the other net crossing the fan threads it; "
    "one threaded window makes the pair interpenetrated (dimension >= 2) or "
    "interlocked_1d (chains). null means the search did not finish (reason "
    "given), not_testable means the chains have no rings, inconclusive means "
    "a rod SBU."
)

DEF_SIMPLIFIED = (
    "节点–连接子简化（描述，不是判定）："
    "金属簇 = {金属原子} ∪ {与 ≥2 个金属（含不同晶格像）成键的轻原子} 的连通"
    "分量，整体收缩为一个节点；连接子 = 其余成键骨架的连通分量。"
    "一个连接子触到的金属簇按 (簇, 晶格平移) 计数："
    "触 2 个 → 收缩成一条边；触 ≥3 个 → 它自己也成为一个节点（branch_linker）；"
    "触 1 个 → 端基（terminal），不进网；触 0 个 → 与金属无关的独立片段，不进网。"
    "边保留晶格平移 (du,dv,dw)，因此简化网可以画进查看器、也可以直接写成 "
    "Systre 的 .cgd。节点连接数 = 该节点的边端点数（自环计 2）。"
)

DEF_SIMPLIFIED_EN = (
    "Node-linker simplification (a DESCRIPTION, not a verdict). Metal "
    "cluster = connected component of {metals} U {light atoms bonded to >= "
    "2 metal images}, contracted to one node. Linkers = components of the "
    "remaining bonded skeleton; a linker touching exactly 2 clusters "
    "becomes an edge, one touching >= 3 becomes a node itself, one "
    "touching 1 is terminal and stays out of the net, one touching none is "
    "a free fragment. Edges keep the lattice shift, so the quotient graph "
    "can be drawn and written for Systre. Node connectivity counts edge "
    "ENDS (a loop counts twice)."
)

DEF_HELIX = (
    "螺旋链 = 一个 dim=1 的片段，被空间群的某个螺旋操作（模晶格平移）映回它"
    "自己，且螺旋轴方向与链的周期方向平行。"
    "手性由螺旋符号定：3₁/4₁/6₁/6₂ 右手，3₂/4₃/6₅/6₄ 左手，2₁/4₂/6₃ 无手性"
    "（m = n/2，自身即其反演伙伴）。"
    "螺距 = 沿轴的晶格重复长度 T × min(m, n−m)：n_m 与 n_(n−m) 是同一条螺旋"
    "从两个方向数出来的，因此左手支用 n−m（3₂ 的螺距是 c 不是 2c）。"
    "群里若含非固有操作（-1、m、滑移、旋反），左右手链必然成对出现，报 "
    "racemic=True 且不为单条链断言手性。"
)

DEF_HELIX_EN = (
    "A helix is a 1-D fragment mapped onto itself (modulo lattice "
    "translations) by a screw operation of the space group whose axis is "
    "parallel to the chain direction. Handedness from the screw symbol: "
    "3_1/4_1/6_1/6_2 right, 3_2/4_3/6_5/6_4 left, 2_1/4_2/6_3 achiral. "
    "Pitch = T * min(m, n-m) with T the lattice repeat along the axis: "
    "n_m and n_(n-m) are one helix counted in opposite senses, so a 3_2 "
    "helix has pitch c, not 2c. A group with any improper operation "
    "contains both hands, so racemic=True and no handedness is claimed."
)

#: n_m -> handedness. m < n/2 right, m > n/2 left, m == n/2 achiral.
_ACHIRAL_SCREWS = {(2, 1), (4, 2), (6, 3)}


# --------------------------------------------------------- shared internals

def _p1_graph(xs, parts=None) -> dict[str, Any]:
    """P1 atoms + the truth's bonded edges with their lattice shifts.

    `analyze_connectivity` owns the expansion and the bond placement; the
    P1 scatterer order it indexes is reproduced here by calling
    `xs.expand_to_p1()` the same way (deterministic for one structure).
    """
    from .connectivity import analyze_connectivity

    rep = analyze_connectivity(xs, parts=parts)
    p1 = xs.expand_to_p1()
    scs = list(p1.scatterers())
    if len(scs) != rep.n_atoms_p1:
        # rep.bonds index THIS list; if the expansion ever stopped being a
        # deterministic pure function of xs the indices would silently
        # point at the wrong atoms, so fail loudly instead
        raise RuntimeError(
            f"P1 expansion disagrees with analyze_connectivity "
            f"({len(scs)} vs {rep.n_atoms_p1} atoms)")
    elements = [sc.scattering_type.strip().capitalize() for sc in scs]
    labels = [str(sc.label) for sc in scs]
    frac = (np.array([[x % 1.0 for x in sc.site] for sc in scs], float)
            if scs else np.zeros((0, 3)))
    adj: dict[int, list[tuple[int, tuple[int, int, int]]]] = {
        i: [] for i in range(len(scs))}
    for b in rep.bonds:
        sh = tuple(int(s) for s in b.shift)
        adj[b.i].append((b.j, sh))
        adj[b.j].append((b.i, tuple(-s for s in sh)))
    return {"rep": rep, "elements": elements, "labels": labels, "frac": frac,
            "adj": adj, "n": len(scs), "unit_cell": p1.unit_cell()}


def _components(keep, adj) -> list[dict[str, Any]]:
    """Periodic connected components of the atom subset `keep`.

    Same BFS as `connectivity.analyze_connectivity`'s fragment loop, run on
    a subset: every atom carries the integer cell offset that reached it,
    every re-encounter contributes a translation mismatch, and the
    dimensionality is the rank of those mismatches. Written here (rather
    than imported) because connectivity.py exposes only whole-structure
    fragments - see the module docstring.
    """
    keep = set(int(i) for i in keep)
    seen: set[int] = set()
    out: list[dict[str, Any]] = []
    for start in sorted(keep):
        if start in seen:
            continue
        comp: list[int] = []
        mismatches: list[np.ndarray] = []
        off = {start: np.zeros(3, dtype=int)}
        stack = [start]
        seen.add(start)
        while stack:
            u = stack.pop()
            comp.append(u)
            for v, sh in adj[u]:
                if v not in keep:
                    continue
                v_off = off[u] + np.array(sh, dtype=int)
                if v not in seen:
                    seen.add(v)
                    off[v] = v_off
                    stack.append(v)
                else:
                    d = v_off - off[v]
                    if np.any(d != 0):
                        mismatches.append(d)
        dim = (int(np.linalg.matrix_rank(np.array(mismatches, dtype=float)))
               if mismatches else 0)
        out.append({"atoms": sorted(comp), "offset": off, "dim": dim,
                    "mismatches": mismatches})
    return out


def _primitive_direction(mismatches) -> list[int]:
    """The primitive lattice direction spanned by a rank-1 mismatch set."""
    from math import gcd

    best: tuple[int, tuple[int, int, int]] | None = None
    for v in mismatches:
        vi = [int(round(float(x))) for x in v]
        if not any(vi):
            continue
        g = 0
        for x in vi:
            g = gcd(g, abs(x))
        if g:
            vi = [x // g for x in vi]
        for x in vi:                     # sign: first non-zero positive
            if x:
                if x < 0:
                    vi = [-y for y in vi]
                break
        norm = sum(x * x for x in vi)
        if best is None or norm < best[0]:
            best = (norm, tuple(vi))
    return list(best[1]) if best else [0, 0, 0]


def _codes(elements: list[str]) -> np.ndarray:
    """Element symbols -> small integers, so the set match stays in numpy."""
    order: dict[str, int] = {}
    return np.array([order.setdefault(e, len(order)) for e in elements],
                    dtype=int)


def _set_matches(image: np.ndarray, image_code: np.ndarray,
                 target: np.ndarray, target_code: np.ndarray,
                 tol: float = MATCH_TOL_FRAC) -> bool:
    """`image` IS `target` as a decorated point set, modulo the lattice."""
    if image.shape != target.shape:
        return False
    if len(image) == 0:
        return True
    d = image[:, None, :] - target[None, :, :]
    d -= np.round(d)
    hit = (np.abs(d) < tol).all(axis=2) & np.equal.outer(image_code,
                                                         target_code)
    return bool(hit.any(axis=1).all() and hit.any(axis=0).all())


def _translation_between(image: np.ndarray, image_el: list[str],
                         target: np.ndarray, target_el: list[str]
                         ) -> list[float] | None:
    """The lattice-modulo translation carrying `image` onto `target`, or None.

    Anchored on the rarest element so a big net costs one candidate per
    atom of that element, not per atom. The anchor MUST land on some target
    atom of its own element, so trying them all is a complete search - up
    to MAX_TRANSLATION_CANDIDATES, past which `independent_nets` says the
    search was truncated instead of reporting a silent "independent".
    """
    if image.shape != target.shape or len(image) == 0:
        return None
    if sorted(image_el) != sorted(target_el):
        return None
    shared = sorted(set(image_el) | set(target_el))
    code_of = {el: k for k, el in enumerate(shared)}
    ic = np.array([code_of[e] for e in image_el], dtype=int)
    tc = np.array([code_of[e] for e in target_el], dtype=int)
    counts: dict[str, int] = {}
    for el in image_el:
        counts[el] = counts.get(el, 0) + 1
    anchor_el = min(counts, key=lambda e: counts[e])
    a = image[image_el.index(anchor_el)]
    cands = [target[k] for k, el in enumerate(target_el) if el == anchor_el]
    for q in cands[:MAX_TRANSLATION_CANDIDATES]:
        t = q - a
        if _set_matches((image + t) % 1.0, ic, target, tc):
            return [_wrap01(x) for x in t]
    return None


def _wrap01(x: float) -> float:
    """Fractional shift into [0, 1), rounded, with -0.0 and 0.9999 snapped."""
    v = round(float(x) % 1.0, 4)
    return 0.0 if v in (0.0, 1.0) else v


def _anchor_count(elements: list[str]) -> int:
    """How many translation candidates a net costs (rarest element count)."""
    counts: dict[str, int] = {}
    for el in elements:
        counts[el] = counts.get(el, 0) + 1
    return min(counts.values()) if counts else 0


def host_fragments(xs, *, parts=None) -> tuple[list[dict], list[dict], dict]:
    """(host fragments, guest fragments, parts dict) under the guests rule.

    The rule is `chem.guests.locate_guests`': role "main" + every fragment
    periodic in >= 1 direction + every fragment with at least
    HOST_MIN_FRACTION of the largest host's atoms. `guests.py` keeps that
    rule inline in `locate_guests` (which also builds the void map, an FFT
    mask we do not need here), so the three lines are re-applied on top of
    its own `_fragments_of`; see the report's "helpers we wish existed".
    """
    from .guests import HOST_MIN_FRACTION, _fragments_of, _parts_dict

    parts_d = _parts_dict(xs, parts, None)
    frags = _fragments_of(xs, parts_d)
    keys = [f["key"] for f in frags
            if f["role"] == "main" or f["dimensionality"] >= 1]
    n_big = max((f["n_atoms"] for f in frags if f["key"] in keys), default=0)
    keys += [f["key"] for f in frags
             if f["key"] not in keys and n_big > 0
             and f["n_atoms"] >= HOST_MIN_FRACTION * n_big]
    host = [f for f in frags if f["key"] in keys]
    guests = [f for f in frags if f["key"] not in keys]
    return host, guests, (parts_d or {})


# ----------------------------------------------- 1. interpenetration / nets

def independent_nets(xs, *, parts=None,
                     threading_budget_s: float = 20.0) -> dict[str, Any]:
    """Independent nets of the host and how they are (or are not) related.

    Returns net dimensions and symmetry relations, not a proof of mechanical
    interpenetration or interlocking. The legacy verdict fields are unknown
    (None) for multiple nets; symmetry_related names what was actually tested.
    """
    host, guests, parts_d = host_fragments(xs, parts=parts)
    host_labels = {lb.upper() for f in host for lb in f["asu_labels"]}
    g = _p1_graph(xs, parts_d or None)
    labels, elements, frac, adj = (g["labels"], g["elements"], g["frac"],
                                   g["adj"])
    keep = [i for i, lb in enumerate(labels) if lb.upper() in host_labels]
    comps = [c for c in _components(keep, adj) if c["dim"] >= 1]
    comps.sort(key=lambda c: (-len(c["atoms"]), c["atoms"][0]))

    nets: list[dict[str, Any]] = []
    for k, c in enumerate(comps, start=1):
        nets.append({
            "id": k,
            "dimensionality": int(c["dim"]),
            "n_atoms_p1": len(c["atoms"]),
            "asu_labels": sorted({labels[i] for i in c["atoms"]}),
            "direction": (_primitive_direction(c["mismatches"])
                          if c["dim"] == 1 else None),
        })

    notes: list[str] = []
    compared = comps[:MAX_NETS_COMPARED]
    if len(comps) > len(compared):
        notes.append(f"只比较了最大的 {MAX_NETS_COMPARED} 个网的对称关系，"
                     f"其余 {len(comps) - len(compared)} 个未比较（如实报告）")
    if guests:
        notes.append("客体/抗衡离子片段已按 guests.locate_guests 的宿主规则移除："
                     + ", ".join(f"{f['key']} {f['formula']}" for f in guests))

    if any(_anchor_count([elements[i] for i in c["atoms"]])
           > MAX_TRANSLATION_CANDIDATES for c in compared):
        notes.append(f"某个网最稀有元素的原子数超过 {MAX_TRANSLATION_CANDIDATES}，"
                     "候选平移被截断：此时 relation=independent 只说明在被试的"
                     "平移里没找到映射，不是已证明的独立")

    ops = _proper_ops(xs)
    relations: list[dict[str, Any]] = []
    for ia in range(len(compared)):
        for ib in range(ia + 1, len(compared)):
            relations.append(_relate(ia + 1, ib + 1, compared[ia],
                                     compared[ib], frac, elements, ops))

    dim_of = {n["id"]: n["dimensionality"] for n in nets}
    related = [r for r in relations
               if r["relation"] in ("translation", "space_group_op")]
    symmetry_related = any(dim_of[r["a"]] >= 2 and dim_of[r["b"]] >= 2
                           for r in related)
    related_1d = any(dim_of[r["a"]] == 1 and dim_of[r["b"]] == 1 for r in related)
    multiple = len(nets) > 1
    # round-3 R5: interpenetration is DECIDED by ring threading, per pair of
    # compared nets, within a time budget; the status says what happened
    threading: dict[str, Any] = {"method": None, "pairs": []}
    interpenetrated: bool | None = None if multiple else False
    interlocked_1d: bool | None = None if multiple else False
    status = "not_applicable"
    if multiple:
        from . import threading as _thr
        from .knowledge import is_metal
        threading["method"] = _thr.METHOD
        threading["max_ring_size"] = _thr.MAX_RING_SIZE
        metals = {i for i in range(len(elements)) if is_metal(elements[i])}
        deadline = time.monotonic() + threading_budget_s
        uc = g["unit_cell"]
        pairs = []
        for ia in range(len(compared)):
            for ib in range(ia + 1, len(compared)):
                pr = _thr.thread_pair(g, compared[ia]["atoms"], compared[ib]["atoms"],
                                      metals, uc=uc, labels=labels, deadline=deadline)
                pr = {"a": ia + 1, "b": ib + 1,
                      "dims": [dim_of[ia + 1], dim_of[ib + 1]], **pr}
                pairs.append(pr)
        threading["pairs"] = pairs

        def _verdict(select) -> tuple[bool | None, str]:
            rows = [p for p in pairs if select(p)]
            if not rows:
                return None, "no_pair"
            if any(p["status"] == "threaded" for p in rows):
                return True, "tested"
            if all(p["status"] == "not_threaded" for p in rows):
                return False, "tested"
            kinds = sorted({p["status"] for p in rows if p["status"] != "not_threaded"})
            return None, "+".join(kinds)

        interpenetrated, st2 = _verdict(lambda p: min(p["dims"]) >= 2)
        interlocked_1d, st1 = _verdict(lambda p: p["dims"] == [1, 1])
        mixed, _stm = _verdict(lambda p: min(p["dims"]) == 1 and max(p["dims"]) >= 2)
        if mixed:
            threading["chain_through_layer_or_net"] = True
        status = st2 if st2 != "no_pair" else st1
        if interpenetrated is True:
            ex = next((p["example"] for p in pairs if p.get("status") == "threaded"), None)
            notes.append("环穿越判定：至少一个网的窗口被另一网的键穿过 → 互穿"
                         + (f"（例：窗口 {ex['window_size']} 节点，键 "
                            f"{ex['bond'][0]}–{ex['bond'][1]}）" if ex else "") + "。")
        elif interpenetrated is False:
            notes.append("环穿越判定：所有被比较网对的窗口都没有被另一网的键穿过 → "
                         "不互穿（对称相关的平行层属于此类）。")
        elif st2 not in ("tested", "no_pair"):
            notes.append(f"环穿越判定未完成（{st2}）：interpenetrated 为 null，"
                         "不是肯定或否定结论。")
        if interlocked_1d is True:
            notes.append("一维链的环被另一条链的键穿过 → 机械互锁（interlocked_1d）。")
        elif st1 == "not_testable":
            notes.append("一维链的收缩图里没有环：链间缠绕不是环穿越能看见的，"
                         "interlocked_1d 保持 null。")
    return {
        "n_nets": len(nets),
        "nets": nets,
        "relations": relations,
        "symmetry_related": bool(symmetry_related),
        "symmetry_related_1d": bool(related_1d),
        "interpenetration_status": status,
        "interpenetrated": interpenetrated,
        "interlocked_1d": interlocked_1d,
        "threading": threading,
        "definition": DEF_NETS,
        "definition_en": DEF_NETS_EN,
        "host": {"fragments": [{k: f[k] for k in
                                ("key", "formula", "n_atoms", "dimensionality",
                                 "role")} for f in host],
                 "selection_rule": ("guests.locate_guests 的宿主规则："
                                    "role==main + 维度≥1 + 原子数 ≥ 最大宿主 "
                                    "50% 的片段")},
        "notes": notes,
    }


def _proper_ops(xs) -> list:
    """Space-group operators worth testing: the rotation part must not be
    the identity (pure translations are covered by the translation test)."""
    ops = []
    for op in xs.space_group().all_ops():
        r = op.r()
        if r.is_unit_mx():
            continue
        ops.append(op)
    return ops


def _relate(id_a: int, id_b: int, ca: dict, cb: dict, frac, elements,
            ops) -> dict[str, Any]:
    """translation | space_group_op | independent, for one pair of nets."""
    pa = frac[ca["atoms"]] % 1.0
    pb = frac[cb["atoms"]] % 1.0
    ea = [elements[i] for i in ca["atoms"]]
    eb = [elements[i] for i in cb["atoms"]]
    t = _translation_between(pa, ea, pb, eb)
    if t is not None:
        return {"a": id_a, "b": id_b, "relation": "translation",
                "op": None, "shift": t}
    if pa.shape == pb.shape and sorted(ea) == sorted(eb):
        for op in ops:
            r = np.array(op.r().as_double(), float).reshape(3, 3)
            tr = np.array(op.t().as_double(), float)
            img = (pa @ r.T + tr) % 1.0
            t = _translation_between(img, ea, pb, eb)
            if t is not None:
                return {"a": id_a, "b": id_b, "relation": "space_group_op",
                        "op": str(op), "shift": t}
    return {"a": id_a, "b": id_b, "relation": "independent",
            "op": None, "shift": None}


# --------------------------------------------- 2. node-linker simplification

def simplified_net(xs, *, parts=None) -> dict[str, Any]:
    """Contract metal clusters to nodes and linkers to edges (DEF_SIMPLIFIED).

    Returns {"nodes", "edges", "n_nodes_per_cell", "n_edges_per_cell",
    "node_connectivity_histogram", "linkers", "definition", "definition_en",
    "confidence", "note"}. Descriptive, never a verdict: `confidence` names
    every place the description can be wrong.
    """
    from .knowledge import is_metal

    g = _p1_graph(xs, parts)
    n, labels, elements, frac, adj = (g["n"], g["labels"], g["elements"],
                                      g["frac"], g["adj"])
    empty = {
        "nodes": [], "edges": [], "n_nodes_per_cell": 0,
        "n_edges_per_cell": 0, "n_parallel_edges": 0,
        "n_simple_edges_per_cell": 0, "node_connectivity_histogram": {},
        "linkers": [], "definition": DEF_SIMPLIFIED,
        "definition_en": DEF_SIMPLIFIED_EN,
    }
    metals = {i for i in range(n) if is_metal(elements[i])}
    if not metals:
        dims = [f["dimensionality"] for f in g["rep"].fragments]
        if not n:
            why = "结构里没有原子。"
        elif max(dims, default=0) == 0:
            why = "这是分子晶体（所有片段 dim=0），没有可简化的网。"
        else:
            why = (f"骨架 dim={max(dims)} 但全为非金属（COF/HOF 一类），"
                   "全有机网的简化要用分支点规则，本模块未实现，故不给节点。")
        empty["note"] = "结构里没有金属原子：金属簇–连接子简化不适用。" + why
        empty["confidence"] = "无金属 → 不作任何简化描述"
        return empty

    cluster_set = set(metals)
    for i in range(n):
        if i in cluster_set:
            continue
        if len({(j, sh) for j, sh in adj[i] if j in metals}) >= 2:
            cluster_set.add(i)

    cl_comps = _components(cluster_set, adj)
    cluster_of: dict[int, int] = {}
    for k, c in enumerate(cl_comps):
        for u in c["atoms"]:
            cluster_of[u] = k

    rest = [i for i in range(n) if i not in cluster_set]
    lk_comps = _components(rest, adj)

    nodes: list[dict[str, Any]] = []
    for k, c in enumerate(cl_comps):
        nodes.append(_node_record(len(nodes) + 1, "metal_cluster", c, labels,
                                  frac))
        nodes[-1]["periodic"] = int(c["dim"])

    linkers: list[dict[str, Any]] = []
    edges: list[tuple[int, int, tuple[int, int, int]]] = []
    branch_nodes = 0
    terminal = 0
    free = 0
    for k, c in enumerate(lk_comps, start=1):
        touches: dict[tuple[int, tuple[int, int, int]], int] = {}
        for u in c["atoms"]:
            for v, sh in adj[u]:
                if v not in cluster_of:
                    continue
                cell = tuple(int(x) for x in
                             (c["offset"][u] + np.array(sh, dtype=int)
                              - cl_comps[cluster_of[v]]["offset"][v]))
                key = (cluster_of[v], cell)
                touches[key] = touches.get(key, 0) + 1
        contacts = sorted(touches)
        rec = {"id": f"L{k}",
               "atoms": sorted({labels[u] for u in c["atoms"]}),
               "n_atoms_p1": len(c["atoms"]),
               "n_nodes_touched": len(contacts)}
        if len(contacts) == 2:
            (ca, ta), (cb, tb) = contacts
            edges.append((ca + 1, cb + 1,
                          tuple(int(tb[m] - ta[m]) for m in range(3))))
            rec["role"] = "edge"
        elif len(contacts) >= 3:
            branch_nodes += 1
            nodes.append(_node_record(len(nodes) + 1, "branch_linker", c,
                                      labels, frac))
            bid = nodes[-1]["id"]
            for cid, t in contacts:
                edges.append((bid, cid + 1, tuple(int(x) for x in t)))
            rec["role"] = "node"
            rec["node_id"] = bid
        elif len(contacts) == 1:
            terminal += 1
            rec["role"] = "terminal"
        else:
            free += 1
            rec["role"] = "free"
        linkers.append(rec)

    # clusters bonded directly to each other (deduped: one edge per pair
    # and shift, however many bonds cross between them)
    direct: set[tuple[int, int, tuple[int, int, int]]] = set()
    for u in sorted(cluster_set):
        for v, sh in adj[u]:
            if v not in cluster_of or cluster_of[v] == cluster_of[u]:
                continue
            a, b = cluster_of[u], cluster_of[v]
            t = tuple(int(x) for x in
                      (cl_comps[a]["offset"][u] + np.array(sh, dtype=int)
                       - cl_comps[b]["offset"][v]))
            direct.add(_canonical_edge(a + 1, b + 1, t))
    edges.extend(sorted(direct))

    edges = [_canonical_edge(a, b, t) for a, b, t in edges]
    edges.sort(key=lambda e: (e[0], e[1], _first_nonzero(e[2]), e[2]))

    conn = {nd["id"]: 0 for nd in nodes}
    for a, b, _t in edges:
        conn[a] = conn.get(a, 0) + 1
        conn[b] = conn.get(b, 0) + 1
    hist: dict[int, int] = {}
    for nd in nodes:
        nd["connectivity"] = int(conn.get(nd["id"], 0))
        hist[nd["connectivity"]] = hist.get(nd["connectivity"], 0) + 1

    conf = ["简化是对结构的描述，不是判定：SBU 少见时（混金属簇、μ-桥连方式"
            "特殊、金属–金属键成簇）收缩规则可能与文献惯例不同，请对照叠加层"
            "核对。"]
    if branch_nodes:
        conf.append(f"{branch_nodes} 个连接子触到 ≥3 个金属簇，按规则它们自己"
                    "被当作节点（三联/多联配体的常规做法）")
    if terminal:
        conf.append(f"{terminal} 个连接子只触到 1 个金属簇，记为端基，不进网")
    if free:
        conf.append(f"{free} 个片段与金属没有成键（溶剂/抗衡离子），不进网")
    rods = [nd["id"] for nd in nodes if nd.get("periodic")]
    if rods:
        conf.append(f"节点 {rods} 的金属簇本身是周期性的（棒状 SBU）：把无限长"
                    "的棒收缩成一个点是有争议的简化，质心只是胞内平均位置")
    # parallel links: the same (u, v, lattice shift) reached by more than one
    # linker. They are kept in `edges` and counted in the histogram (a node
    # IS bonded that many times) but a periodic GRAPH has one such edge, so
    # write_cgd / Systre see the simple graph - say so instead of letting the
    # two counts disagree silently.
    n_parallel = len(edges) - len(set(edges))
    if n_parallel:
        conf.append(f"{n_parallel} 条重边（同一对节点被 ≥2 个连接子以同一晶格"
                    "平移直接相连）：连接数直方图数的是连接子数，写给 "
                    "Systre 的 .cgd 只能是简单图（重边合并为一条），RCSR 符号"
                    "命名的是合并后的简单图")
    return {
        "nodes": nodes,
        "edges": [[a, b, list(t)] for a, b, t in edges],
        "n_nodes_per_cell": len(nodes),
        "n_edges_per_cell": len(edges),
        "n_parallel_edges": int(n_parallel),
        "n_simple_edges_per_cell": len(set(edges)),
        "node_connectivity_histogram": hist,
        "linkers": linkers,
        "definition": DEF_SIMPLIFIED,
        "definition_en": DEF_SIMPLIFIED_EN,
        "confidence": " ".join(conf),
    }


def _node_record(node_id: int, kind: str, comp: dict, labels, frac
                 ) -> dict[str, Any]:
    pts = np.array([frac[u] + comp["offset"][u] for u in comp["atoms"]],
                   float)
    centroid = pts.mean(axis=0) % 1.0
    return {"id": node_id, "kind": kind,
            "atoms": sorted({labels[u] for u in comp["atoms"]}),
            "n_atoms_p1": len(comp["atoms"]),
            "centroid_frac": [float(round(x, 4)) for x in centroid],
            "connectivity": 0}


def _canonical_edge(a: int, b: int, t) -> tuple[int, int, tuple[int, int, int]]:
    """One orientation per edge: lower vertex first; a loop takes the
    lattice shift whose first non-zero component is positive."""
    t = tuple(int(x) for x in t)
    if a > b or (a == b and _negative_first(t)):
        return (b, a, tuple(-x for x in t))
    return (a, b, t)


def _negative_first(t) -> bool:
    for x in t:
        if x:
            return x < 0
    return False


def _first_nonzero(t) -> int:
    for k, x in enumerate(t):
        if x:
            return k
    return len(t)


# --------------------------------------------------- 3. Systre bridge (gated)

def write_cgd(net: dict, name: str) -> str:
    """Systre `.cgd` PERIODIC_GRAPH block for a `simplified_net` result.

    One `EDGES` line per quotient-graph edge, `u v du dv dw`: the edge runs
    from vertex u in the origin cell to vertex v in cell (du, dv, dw).
    Edges come out in a deterministic order (vertex pair, then the first
    cell direction the edge crosses), so the standard pcu net writes as the
    standard three lines 1 1 1 0 0 / 1 1 0 1 0 / 1 1 0 0 1.

    PARALLEL LINKS are written ONCE. A contracted net legitimately has
    them - two crystallographically distinct linkers bridging the same pair
    of clusters with the same lattice shift is one periodic-graph edge
    twice - but Gavrog's `.cgd` EDGES list is a SET: a repeated triple
    aborts the whole file with `IllegalArgumentException: duplicate edge`,
    losing every structure in it (live case: a Mn-terephthalate rod MOF
    whose two carboxylates bridge the same pair of rods). The count of
    dropped repeats is `simplified_net`'s `n_parallel_edges`; the node
    connectivity histogram still counts every link, so the two numbers
    disagree exactly when the net is a multigraph - which is the honest
    reading, since an RCSR symbol only ever names the simple graph.
    """
    edges = [tuple(e) if not isinstance(e, list) else (e[0], e[1], tuple(e[2]))
             for e in net.get("edges", [])]
    edges = {_canonical_edge(a, b, t) for a, b, t in edges}
    lines = ["PERIODIC_GRAPH", f"  NAME {name}", "  EDGES"]
    for a, b, t in sorted(edges, key=lambda e: (e[0], e[1],
                                                _first_nonzero(e[2]), e[2])):
        lines.append(f"    {a} {b} {t[0]} {t[1]} {t[2]}")
    lines.append("END")
    return "\n".join(lines) + "\n"


def systre_jar() -> Path | None:
    """The Gavrog jar, when the user has placed one (never bundled)."""
    hits = sorted(REPO_ROOT.glob(SYSTRE_JAR_GLOB))
    return hits[0] if hits else None


def _systre_unavailable(status: str) -> dict[str, Any]:
    """Same keys as a real run, so a caller never has to test for absence."""
    return {"rcsr_symbol": None, "rcsr_symbols": [], "rcsr_status": status,
            "systre_error": None, "systre_output": None}


def run_systre(cgd_text: str, timeout_s: int = 60) -> dict[str, Any]:
    """Name the net with Systre, when a jar and a java are present.

    Never raises: a missing jar, a missing java, a timeout or a crash all
    come back as `rcsr_symbol: None` plus the reason in `rcsr_status`.
    """
    jar = systre_jar()
    if jar is None:
        return _systre_unavailable(
            "未算（未安装 Systre）：把 gavrog 的 jar 放到 "
            f"{REPO_ROOT / 'vendor' / 'gavrog'} 后本项才会计算；二进制不入库")
    java = shutil.which("java")
    if java is None:
        return _systre_unavailable("未算（找到 jar 但 PATH 上没有 java）")
    try:
        with tempfile.TemporaryDirectory(prefix="systre-") as tmp:
            path = Path(tmp) / "net.cgd"
            path.write_text(cgd_text, encoding="utf-8")
            proc = subprocess.run(
                [java, "-cp", str(jar), SYSTRE_MAIN, str(path)],
                capture_output=True, text=True, timeout=timeout_s,
                encoding="utf-8", errors="replace")
        out = (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired:
        return _systre_unavailable(
            f"未算（Systre 超过 {timeout_s} s 未返回）")
    except OSError as exc:
        return _systre_unavailable(f"未算（启动 Systre 失败：{exc}）")
    return _read_systre(out)


def _read_systre(out: str) -> dict[str, Any]:
    """The verdict of ONE SystreCmdline run: symbol(s), status, raw output.

    Systre refuses some nets outright (`!!! ERROR (STRUCTURE) - Structure
    has collisions ...`) and splits a disconnected net into components,
    naming each. Both were previously flattened into "已跑 Systre 但输出里
    没有 RCSR 符号" / the FIRST component's symbol, which hides the reason
    and, for a 2-fold interpenetrated net, hid the fact that there were two
    answers at all. Both are surfaced here.
    """
    syms = parse_systre_symbols(out)
    err = parse_systre_error(out)
    split = "Structure is not connected" in (out or "")
    uniq = sorted(set(syms))
    if not syms:
        if err:
            why = f"Systre 报错：{err}"
        elif re.search(r"Structure is new for this", out or ""):
            # Systre finished: the net is simply not in the RCSR archive.
            # That is an ANSWER (a new/unnamed net), not a failure.
            why = ("Systre 算完了，但这个网不在 RCSR 档案里（\"Structure is "
                   "new for this run\"）：有坐标序列和理想空间群，没有符号")
        else:
            why = "输出里没有 RCSR 符号"
        return {"rcsr_symbol": None, "rcsr_symbols": [],
                "rcsr_status": f"已跑 Systre 但未得到符号（{why}）",
                "systre_error": err, "systre_output": out}
    if not split and len(uniq) == 1:
        status = "已算（Systre）"
    elif len(uniq) == 1:
        status = (f"已算（Systre）：简化网不连通，{len(syms)} 个分量都是 "
                  f"{uniq[0]}（互穿/多重网的常态）")
    else:
        status = ("已跑 Systre：简化网不连通，各分量的符号不同（"
                  + " / ".join(syms) + "），不给单一符号")
    if err:
        status += f"；Systre 另有报错：{err}"
    return {"rcsr_symbol": uniq[0] if len(uniq) == 1 else None,
            "rcsr_symbols": syms, "rcsr_status": status,
            "systre_error": err, "systre_output": out}


def parse_systre_symbols(output: str) -> list[str]:
    """Every RCSR symbol in a SystreCmdline report, in output order (one
    per connected component - a disconnected .cgd gets one block each)."""
    return re.findall(r"RCSR symbol:\s*\n\s*Name:\s*(\S+)", output or "")


def parse_systre_symbol(output: str) -> str | None:
    """The first RCSR symbol out of a SystreCmdline report, or None."""
    syms = parse_systre_symbols(output)
    if syms:
        return syms[0]
    m = re.search(r"Name:\s*(\S+)", output or "")
    return m.group(1) if m else None


def parse_systre_error(output: str) -> str | None:
    """Systre's own `!!! ERROR (KIND) - message` line, or None."""
    m = re.search(r"!!!\s*ERROR\s*\(([^)]*)\)\s*-\s*(.+)", output or "")
    if not m:
        return None
    return f"{m.group(1)}: {m.group(2).strip()}"


# ------------------------------------------------------------- 4. helices

def helices(xs, *, parts=None) -> list[dict[str, Any]]:
    """Helical 1-D fragments and their screw, handedness and pitch (DEF_HELIX).

    A 1-D fragment is helical when a screw operation of the space group
    maps it onto itself modulo lattice translations with the screw axis
    along the chain. Symmetry-equivalent chains are reported once.

    The screw is read from `xs.space_group().all_ops()` +
    `sgtbx.translation_part_info` rather than from
    `refine.scene._symmetry_elements`: that helper returns the geometry of
    the elements (segments, symbols, orders) but not the operator itself,
    and the "does this op map THIS chain onto itself" test needs the
    operator. The screw fraction is read the same way scene.py reads it
    (positive-sense op names the axis, m = round(s * order) % order).
    """
    from cctbx import sgtbx

    g = _p1_graph(xs, parts)
    labels, elements, frac, adj = (g["labels"], g["elements"], g["frac"],
                                   g["adj"])
    uc = g["unit_cell"]
    sg = xs.space_group()
    racemic = any(np.linalg.det(np.array(op.r().as_double()).reshape(3, 3))
                  < 0 for op in sg.all_ops())
    out: list[dict[str, Any]] = []
    seen: set[tuple] = set()
    for comp in _components(range(g["n"]), adj):
        if comp["dim"] != 1:
            continue
        direction = _primitive_direction(comp["mismatches"])
        hit = _screw_of(comp, sg, sgtbx, frac, elements, direction)
        if hit is None:
            continue
        order, m, ev = hit
        t_axis = float(uc.length([float(x) for x in ev]))
        turns = min(m, order - m)
        hand = None if (order, m) in _ACHIRAL_SCREWS or racemic else (
            "right" if m * 2 < order else "left")
        rec: dict[str, Any] = {
            "fragment": f"F{len(out) + 1}",
            "asu_labels": sorted({labels[i] for i in comp["atoms"]}),
            "n_atoms_p1": len(comp["atoms"]),
            "dimensionality": 1,
            "axis_direction": [int(x) for x in ev],
            "chain_direction": direction,
            "screw": f"{order}_{m}",
            "order": int(order),
            "handedness": hand,
            "pitch_A": round(t_axis * turns, 4),
            "axis_repeat_A": round(t_axis, 4),
            "racemic": bool(racemic),
            "definition": DEF_HELIX,
            "definition_en": DEF_HELIX_EN,
        }
        if (order, m) in _ACHIRAL_SCREWS:
            rec["note"] = (f"{order}_{m} 是自反演的螺旋（m = n/2），没有手性")
        elif racemic:
            rec["note"] = ("空间群含非固有操作，左右手链成对存在（外消旋堆积），"
                           "不为单条链断言手性")
        key = (tuple(rec["asu_labels"]), rec["screw"], tuple(direction))
        if key in seen:                      # symmetry-equivalent chain
            continue
        seen.add(key)
        out.append(rec)
    return out


def _screw_of(comp, sg, sgtbx, frac, elements, direction):
    """(order, m, ev) of the screw that maps this chain onto itself, or None.

    Only the positive-sense operator names an axis (scene.py's rule: a
    3_2 op's square reduces to 1/3 and must not rename the axis), so the
    inverse operator - which maps the same chain onto itself - is skipped.
    """
    pts = frac[comp["atoms"]] % 1.0
    code = _codes([elements[i] for i in comp["atoms"]])
    best = None
    for op in sg.all_ops():
        info = op.r().info()
        t_type = info.type()
        if t_type < 2:                       # identity, translation, improper
            continue
        order = int(t_type)
        if order > 2 and info.sense() <= 0:
            continue
        ti = sgtbx.translation_part_info(op)
        intr = np.array(ti.intrinsic_part().as_double(), float)
        if not np.any(np.abs(intr) > 1e-9):
            continue                         # pure rotation, not a screw
        ev = [int(x) for x in info.ev()]
        if not _parallel(ev, direction):
            continue
        n2 = float(sum(x * x for x in ev))
        s = float(sum(intr[k] * ev[k] for k in range(3)) / n2) % 1.0
        m = int(round(s * order)) % order
        if m == 0:
            continue
        r = np.array(op.r().as_double(), float).reshape(3, 3)
        tr = np.array(op.t().as_double(), float)
        img = (pts @ r.T + tr) % 1.0
        if not _set_matches(img, code, pts, code):
            continue
        if best is None or min(m, order - m) < min(best[1], best[0] - best[1]):
            best = (order, m, ev)
    return best


def _parallel(u, v) -> bool:
    u = np.array(u, float)
    v = np.array(v, float)
    if not np.any(u) or not np.any(v):
        return False
    return bool(np.linalg.norm(np.cross(u, v)) < 1e-9)
