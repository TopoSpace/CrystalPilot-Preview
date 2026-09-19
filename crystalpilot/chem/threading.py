"""Ring threading between nets (round-3 R5): is a second net actually
INSIDE the first one, or merely beside it?

`topology.independent_nets` finds the periodic connected components of the
host and how they are related by symmetry. A symmetry relation is not
interpenetration: two parallel square layers map onto each other and are
not entangled at all, while two nets no operator relates can still thread
each other. The question that decides it is geometric: does a bond of net
B pass THROUGH a window (a ring) of net A?

Method
  1. contract each net to its threading graph: with metals present, metal
     clusters ({metals} + light atoms bonded to >= 2 metals) become nodes
     and the connected fragments between them become edges (a fragment
     touching >= 3 clusters is itself a node), exactly the node-linker
     rule of `topology.simplified_net`; without metals the branch points
     (atoms of degree >= 3) are the nodes and the chains between them the
     edges. Node positions are the centroids of the contracted atoms.
  2. rings of that periodic graph: the shortest cycle through every edge,
     found by breadth-first search in the lifted (node, lattice shift)
     graph, up to MAX_RING_SIZE nodes, deduplicated modulo lattice
     translation. These are the windows.
  3. a window is spanned by the fan of triangles from its centroid; every
     atom-level bond of the other net (as a straight segment, over the
     lattice translations that can reach the window) is tested against
     that fan (Moller-Trumbore). One crossing = the window is threaded.

A pair of nets is interpenetrated when at least one window of either net
is threaded by a bond of the other. The verdict comes with the counts,
one example per direction, the ring-size cap and every truncation, so a
"no" is only claimed when the search actually finished.

Limits (stated, not hidden): rings are those of the contracted graph up
to MAX_RING_SIZE nodes - a window larger than that is not tested; the fan
surface of a strongly non-planar ring is one of many surfaces spanning
it, so a bond crossing it twice (in and out) counts twice - the count is
reported, the verdict only needs >= 1; entanglement without rings (two
helices wound around each other) is invisible to a ring test and is
reported as not_testable; rod-shaped SBUs contract to a point whose
"rings" are ill-defined, reported as inconclusive. Element-generic: bond
topology, lattice shifts and Cartesian geometry only.
"""
from __future__ import annotations

import time
from collections import deque
from typing import Any

import numpy as np

MAX_RING_SIZE = 12
MAX_RINGS = 3000
MAX_BFS_STEPS = 3_000_000
#: lattice translations of the other net's bonds tried around a window
#: (the window itself is normalised into the origin cell first)
BOND_SHIFT_RANGE = 2
#: |lattice shift| bound of a BFS state; a ring of <= 12 nodes never needs
#: more than this many cells
MAX_STATE_SHIFT = 3
DEFAULT_TIME_BUDGET_S = 20.0

METHOD = ("contracted-net windows (shortest cycle through every edge, <= "
          f"{MAX_RING_SIZE} nodes) spanned by a centroid fan; a window is "
          "threaded when a straight bond of the other net crosses the fan "
          "(Moller-Trumbore); interpenetrated = any window of either net "
          "threaded by the other")


# --------------------------------------------------------------------------
def contract(g: dict[str, Any], atoms, metals: set[int]) -> dict[str, Any]:
    """The threading graph of ONE net (see module doc, step 1).

    g: `topology._p1_graph` output; atoms: P1 indices of the net; metals:
    P1 indices that are metals (whole structure). Returns {"nodes":
    [{"atoms", "centroid_frac", "periodic"}], "edges": [(a, b, shift)],
    "rods": n_periodic_nodes, "rule"}.
    """
    from .topology import _components

    adj = g["adj"]
    frac = g["frac"]
    atom_set = {int(i) for i in atoms}
    deg = {i: len([1 for j, _s in adj[i] if j in atom_set]) for i in atom_set}
    net_metals = atom_set & set(metals)
    if net_metals:
        cluster = set(net_metals)
        for i in atom_set:
            if i in cluster:
                continue
            if len({(j, sh) for j, sh in adj[i] if j in net_metals}) >= 2:
                cluster.add(i)
        rule = "metal_clusters"
    else:
        cluster = {i for i in atom_set if deg[i] >= 3}
        rule = "branch_points"
    if not cluster:
        return {"nodes": [], "edges": [], "rods": 0, "rule": rule}

    if rule == "metal_clusters":
        cl_comps = _components(cluster, adj)
    else:
        # branch points are nodes one by one: two bonded branch atoms are
        # two nodes joined by an edge, never one merged "cluster" (a layer
        # of 4-connected atoms would otherwise contract to a single
        # periodic blob with no windows at all)
        cl_comps = [{"atoms": [i], "offset": {i: np.zeros(3, dtype=int)},
                     "dim": 0, "mismatches": []} for i in sorted(cluster)]
    cluster_of: dict[int, int] = {}
    for k, c in enumerate(cl_comps):
        for u in c["atoms"]:
            cluster_of[u] = k
    nodes: list[dict[str, Any]] = []
    for c in cl_comps:
        pts = np.array([frac[u] + c["offset"][u] for u in c["atoms"]], float)
        nodes.append({"atoms": list(c["atoms"]),
                      "centroid_frac": pts.mean(axis=0),
                      "periodic": int(c["dim"]) > 0})
    rest = [i for i in atom_set if i not in cluster]
    edges: list[tuple[int, int, tuple[int, int, int]]] = []
    for c in _components(rest, adj):
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
        if len(contacts) == 2:
            (ca, ta), (cb, tb) = contacts
            edges.append((ca, cb, tuple(int(tb[m] - ta[m]) for m in range(3))))
        elif len(contacts) >= 3:
            pts = np.array([frac[u] + c["offset"][u] for u in c["atoms"]], float)
            nodes.append({"atoms": list(c["atoms"]),
                          "centroid_frac": pts.mean(axis=0),
                          "periodic": int(c["dim"]) > 0})
            bid = len(nodes) - 1
            for cid, t in contacts:
                edges.append((bid, cid, tuple(int(x) for x in t)))
    # clusters bonded directly to each other
    direct: set[tuple[int, int, tuple[int, int, int]]] = set()
    for u in sorted(cluster):
        for v, sh in adj[u]:
            if v not in cluster_of:
                continue
            if cluster_of[v] == cluster_of[u] and (
                    rule == "metal_clusters" or not any(sh)):
                # inside one cluster; a branch point bonded to its own
                # lattice image is a loop edge with a shift and stays
                continue
            a, b = cluster_of[u], cluster_of[v]
            t = tuple(int(x) for x in
                      (cl_comps[a]["offset"][u] + np.array(sh, dtype=int)
                       - cl_comps[b]["offset"][v]))
            if a > b or (a == b and _neg_first(t)):
                a, b, t = b, a, tuple(-x for x in t)
            direct.add((a, b, t))
    edges.extend(sorted(direct))
    return {"nodes": nodes, "edges": edges,
            "rods": sum(1 for nd in nodes if nd["periodic"]), "rule": rule}


def _neg_first(t) -> bool:
    for x in t:
        if x:
            return x < 0
    return False


# --------------------------------------------------------------------------
def rings_of(n_nodes: int, edges, *, max_size: int = MAX_RING_SIZE,
             max_rings: int = MAX_RINGS, deadline: float | None = None
             ) -> tuple[list[list[tuple[int, tuple[int, int, int]]]], bool]:
    """Windows of the periodic graph: for every angle a-b-c the shortest
    cycle that contains it (breadth-first search in the lifted (node,
    lattice shift) graph from c back to a, not passing through b), up to
    `max_size` nodes, deduplicated modulo lattice translation - the
    smallest-ring-per-angle census, which finds every window a
    per-edge search can skip (a pcu node's three 4-rings share edges).
    Returns (rings as ordered (node, shift) lists, truncated)."""
    adj: list[list[tuple[int, tuple[int, int, int]]]] = [[] for _ in range(n_nodes)]
    for a, b, t in edges:
        adj[a].append((b, t))
        adj[b].append((a, tuple(-x for x in t)))
    found: dict[frozenset, list] = {}
    steps = 0
    truncated = False
    zero = (0, 0, 0)

    def _add(ring) -> None:
        m = min(ring)
        key = frozenset((n, (tv[0] - m[1][0], tv[1] - m[1][1], tv[2] - m[1][2]))
                        for n, tv in ring)
        if key not in found:
            found[key] = ring

    for a, b, t in edges:
        if truncated:
            break
        goal = (a, zero)
        mid = (b, t)
        if mid == goal:
            continue                      # a loop edge is not a window
        for c, t2 in adj[b]:
            if truncated:
                break
            if deadline is not None and time.monotonic() > deadline:
                truncated = True
                break
            start = (c, (t[0] + t2[0], t[1] + t2[1], t[2] + t2[2]))
            if start == goal or start == mid:
                continue                  # the edge backwards / a loop
            prev: dict[tuple, tuple | None] = {start: None, mid: None}
            queue: deque[tuple[tuple, int]] = deque([(start, 2)])
            hit = None
            while queue and hit is None:
                (node, tv), depth = queue.popleft()
                if depth >= max_size:
                    continue
                for nb, et in adj[node]:
                    nt = (tv[0] + et[0], tv[1] + et[1], tv[2] + et[2])
                    state = (nb, nt)
                    steps += 1
                    if steps > MAX_BFS_STEPS:
                        truncated = True
                        break
                    if state in prev or max(abs(x) for x in nt) > MAX_STATE_SHIFT:
                        continue
                    prev[state] = (node, tv)
                    if state == goal:
                        hit = state
                        break
                    queue.append((state, depth + 1))
                if truncated:
                    break
            if hit is None:
                continue
            path = []
            cur: tuple | None = hit
            while cur is not None:
                path.append(cur)
                cur = prev[cur]
            # path: goal ... start; the ring runs a(goal) <- ... <- c <- b
            ring = [mid] + list(reversed(path))
            if _is_sp_ring(ring, adj):
                _add(ring)
            if len(found) >= max_rings:
                truncated = True
    return list(found.values()), truncated


def _is_sp_ring(ring, adj) -> bool:
    """Franzblau's shortest-path criterion: a cycle is a ring (a window)
    only if no pair of its vertices is joined by a shorter path outside it.
    Drops the 6-cycles a straight angle x-node-(-x) of a pcu net closes
    (two vertices two bonds apart across the node) while keeping every
    genuine window, kagome hexagons included."""
    n = len(ring)
    for i in range(n):
        for j in range(i + 1, n):
            d_ring = min(j - i, n - (j - i))
            if d_ring < 2:
                continue
            src, dst = ring[i], ring[j]
            seen = {src}
            frontier = [src]
            for _depth in range(d_ring - 1):
                nxt = []
                for node, tv in frontier:
                    for nb, et in adj[node]:
                        state = (nb, (tv[0] + et[0], tv[1] + et[1], tv[2] + et[2]))
                        if state == dst:
                            return False
                        if state not in seen:
                            seen.add(state)
                            nxt.append(state)
                frontier = nxt
                if not frontier:
                    break
    return True


# --------------------------------------------------------------------------
def _segment_triangle_hits(p0: np.ndarray, p1: np.ndarray, a: np.ndarray,
                           b: np.ndarray, c: np.ndarray, eps: float = 1e-7
                           ) -> np.ndarray:
    """Moller-Trumbore for many segments (p0 -> p1, shape (n, 3)) against
    one triangle (a, b, c): True where the segment crosses the triangle."""
    d = p1 - p0
    e1 = b - a
    e2 = c - a
    h = np.cross(d, e2)
    det = h @ e1
    ok = np.abs(det) > 1e-12
    inv = np.zeros_like(det)
    inv[ok] = 1.0 / det[ok]
    s = p0 - a
    u = inv * np.einsum("ij,ij->i", s, h)
    q = np.cross(s, e1)
    v = inv * np.einsum("ij,ij->i", q, d)
    t = inv * (q @ e2)
    return (ok & (u >= -eps) & (v >= -eps) & (u + v <= 1.0 + eps)
            & (t >= -eps) & (t <= 1.0 + eps))


def _bond_segments(g: dict[str, Any], atoms) -> tuple[np.ndarray, np.ndarray, list[tuple[int, int]]]:
    """Every bond of the net once, as fractional endpoints (P0, P1)."""
    adj, frac = g["adj"], g["frac"]
    atom_set = {int(i) for i in atoms}
    p0, p1, pairs = [], [], []
    seen: set[tuple[int, int, tuple[int, int, int]]] = set()
    for i in sorted(atom_set):
        for j, sh in adj[i]:
            if j not in atom_set:
                continue
            key = (i, j, tuple(int(x) for x in sh))
            rev = (j, i, tuple(-int(x) for x in sh))
            if rev in seen:
                continue
            seen.add(key)
            p0.append(frac[i])
            p1.append(frac[j] + np.array(sh, dtype=float))
            pairs.append((i, j))
    if not p0:
        return np.zeros((0, 3)), np.zeros((0, 3)), []
    return np.array(p0, float), np.array(p1, float), pairs


def windows_threaded(uc, nodes, rings, g: dict[str, Any], other_atoms,
                     labels, *, deadline: float | None = None
                     ) -> dict[str, Any]:
    """How many of `rings` (windows of net A) are crossed by a bond of net B
    (`other_atoms`), with one example."""
    om = np.array(uc.orthogonalization_matrix(), float).reshape(3, 3)
    p0f, p1f, pairs = _bond_segments(g, other_atoms)
    if len(pairs) == 0 or not rings:
        return {"n_windows": len(rings), "n_threaded": 0, "n_crossings": 0,
                "example": None, "truncated": False}
    shifts = np.array([(x, y, z)
                       for x in range(-BOND_SHIFT_RANGE, BOND_SHIFT_RANGE + 1)
                       for y in range(-BOND_SHIFT_RANGE, BOND_SHIFT_RANGE + 1)
                       for z in range(-BOND_SHIFT_RANGE, BOND_SHIFT_RANGE + 1)],
                      float)
    n_b = len(pairs)
    seg0 = (p0f[None, :, :] + shifts[:, None, :]).reshape(-1, 3) @ om.T
    seg1 = (p1f[None, :, :] + shifts[:, None, :]).reshape(-1, 3) @ om.T
    pair_idx = np.tile(np.arange(n_b), len(shifts))
    seg_lo = np.minimum(seg0, seg1)
    seg_hi = np.maximum(seg0, seg1)
    threaded = 0
    crossings = 0
    example = None
    truncated = False
    cent_frac = np.array([nd["centroid_frac"] for nd in nodes], float)
    for ring in rings:
        if deadline is not None and time.monotonic() > deadline:
            truncated = True
            break
        vf = np.array([cent_frac[n] + np.array(t, float) for n, t in ring])
        vf = vf - np.floor(vf.mean(axis=0))          # window into the origin cell
        vc = vf @ om.T
        centre = vc.mean(axis=0)
        lo = vc.min(axis=0) - 1e-6
        hi = vc.max(axis=0) + 1e-6
        cand = np.where(np.all(seg_hi >= lo, axis=1) & np.all(seg_lo <= hi, axis=1))[0]
        if cand.size == 0:
            continue
        c0, c1 = seg0[cand], seg1[cand]
        hits = np.zeros(cand.size, dtype=bool)
        n = len(vc)
        for k in range(n):
            hits |= _segment_triangle_hits(c0, c1, centre, vc[k], vc[(k + 1) % n])
        n_hit = int(hits.sum())
        if n_hit:
            threaded += 1
            crossings += n_hit
            if example is None:
                first = cand[np.where(hits)[0][0]]
                i, j = pairs[pair_idx[first]]
                example = {"window": [int(nn) for nn, _t in ring],
                           "window_size": n,
                           "bond": [labels[i], labels[j]],
                           "bond_shift": [int(x) for x in shifts[first // n_b]]}
    return {"n_windows": len(rings), "n_threaded": threaded,
            "n_crossings": crossings, "example": example,
            "truncated": truncated}


# --------------------------------------------------------------------------
def thread_pair(g: dict[str, Any], atoms_a, atoms_b, metals: set[int], *,
                uc, labels, deadline: float | None = None) -> dict[str, Any]:
    """The threading verdict for one pair of nets (both directions)."""
    ca = contract(g, atoms_a, metals)
    cb = contract(g, atoms_b, metals)
    out: dict[str, Any] = {
        "rule": [ca["rule"], cb["rule"]],
        "n_nodes": [len(ca["nodes"]), len(cb["nodes"])],
        "n_edges": [len(ca["edges"]), len(cb["edges"])],
    }
    if ca["rods"] or cb["rods"]:
        out.update({"status": "inconclusive",
                    "reason": "a contracted node is a periodic rod (rod SBU): "
                              "its windows are ill-defined"})
        return out
    ra, ta = rings_of(len(ca["nodes"]), ca["edges"], deadline=deadline)
    rb, tb = rings_of(len(cb["nodes"]), cb["edges"], deadline=deadline)
    if not ra and not rb:
        if ta or tb:
            out.update({"status": "inconclusive",
                        "reason": "the ring search hit its budget before "
                                  "finding a window"})
        else:
            out.update({"status": "not_testable",
                        "reason": "neither net has a ring in its contracted "
                                  "graph (chains without windows): nothing "
                                  "to thread"})
        return out
    ab = windows_threaded(uc, ca["nodes"], ra, g, atoms_b, labels, deadline=deadline)
    ba = windows_threaded(uc, cb["nodes"], rb, g, atoms_a, labels, deadline=deadline)
    truncated = ta or tb or ab["truncated"] or ba["truncated"]
    threaded = ab["n_threaded"] > 0 or ba["n_threaded"] > 0
    out.update({
        "a_windows": ab["n_windows"], "a_windows_threaded_by_b": ab["n_threaded"],
        "b_windows": ba["n_windows"], "b_windows_threaded_by_a": ba["n_threaded"],
        "crossings": ab["n_crossings"] + ba["n_crossings"],
        "example": ab["example"] or ba["example"],
        "truncated": truncated,
        "status": ("threaded" if threaded
                   else "inconclusive" if truncated else "not_threaded"),
    })
    if truncated and not threaded:
        out["reason"] = ("the ring search or the crossing test hit its budget "
                         "before finishing: no threading was found in the "
                         "part that ran")
    return out
