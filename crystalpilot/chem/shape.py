"""Shape measures: coordination polyhedra (CShM), macrocycle census, and the
measurable shape evidence that replaces polyhedron nicknames (round-2 plan R4).

Three independent pure functions, no I/O, no model state, no element table of
its own:

  `cshm(centre_xyz, ligand_xyz)`      continuous shape measures of one
                                      coordination sphere against the ideal
                                      reference polyhedra for CN 4/5/6
  `largest_cycle(adj, comp)`          the largest CHORDLESS cycle of a bonded
                                      fragment, budgeted, truncation reported
  `shape_evidence(xyz)`               inertia ratios, convex-hull sphericity,
                                      inertia-frame aspect
  `crystallographic_point_symmetry(xs, atom_indices)`
                                      the space-group operators that map one
                                      fragment instance onto itself

WHAT THIS MODULE DELIBERATELY DOES NOT DO (plan R4, "形状/形貌的诚实边界"):
it never names a shape ("lantern", "pear", "distorted", "ideal"). It returns
numbers and the name of the closest tabulated reference; the naming is the
crystallographer's. There is no threshold anywhere in this file that turns a
number into a verdict.

WHAT IT REUSES RATHER THAN RE-IMPLEMENTS

  * bonding: nothing here invents a distance cutoff. `largest_cycle` takes an
    adjacency map that the caller built from `chem.bonding.bond_table` (the
    ONE bonding truth) - see the `largest_cycle` docstring for the exact
    shape of that map and for the lattice-translation rule.
  * `refine.inspect.metal_environments` already holds the metal's fractional
    site and its ligands' fractional sites plus the unit cell, and already
    orthogonalises them for its angle list. `cshm` therefore takes plain
    cartesian coordinates: the wiring next to tau4/tau5 is

        uc = xs.unit_cell()
        centre = uc.orthogonalize(sc.site)
        ligs = [uc.orthogonalize(n["site_frac"]) for n in coord]
        row["shape"] = cshm(centre, ligs)

    (`coord` is the list `metal_environments` already built: the classified
    sphere with `metal_metal` and `non_bonded_close` removed.) This module
    does not edit inspect.py. ONE CAVEAT for that wiring: `cshm` measures
    ligand ATOM positions, so an eta-bound ring contributes five or six
    vertices where `BondTable.cn()` counts it as one ligand - a ferrocene
    iron arrives as CN 10 and gets "no reference shapes for CN 10", which is
    the honest answer for a vertex measure. Feed it the sigma-donor set, or
    ring centroids, if a hapticity-aware polyhedron is wanted.
  * ring finders: `refine.inspect._rings_in` and `chem.connectivity
    ._carbocycles` are capped at 7 and 5/6 members respectively and stay
    exactly as they are - they answer "which small rings are here". The
    census below EXTENDS them with the one question they cannot answer,
    "how large is the largest macrocycle", and uses the same budgeted-DFS
    discipline (`connectivity._RING_SEARCH_BUDGET`, truncation reported).
  * `chem.knowledge.element_symbol` normalises scattering types. There is no
    metal test in this file at all: `cshm` is element-blind on purpose (it
    measures any centre against any ligand set, main-group, lanthanide or
    cluster vertex alike), so `chem.knowledge.is_metal` stays where it
    belongs, in the caller that decides which atoms are metals.

CONVENTIONS ARE FIXED AND REPORTED. Every returned dict carries a `method`
string naming the formula that produced its numbers and a `note` for the
caveats that apply to that particular call.
"""
from __future__ import annotations

import itertools
import math
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

from .knowledge import element_symbol

# ---------------------------------------------------------------------------
# 1. Continuous shape measures
# ---------------------------------------------------------------------------
#
# DEFINITION (Pinsky & Avnir, Inorg. Chem. 1998, 37, 5575; conventions as in
# Alvarez et al., Coord. Chem. Rev. 2005, 249, 1693 and the SHAPE program):
#
#     S(Q, P) = 100 x  min       sum_k |q_k - s R p_sigma(k)|^2
#                   sigma,R,s,t  ---------------------------------
#                                    sum_k |q_k - q_bar|^2
#
# over all permutations sigma of the ligand vertices, all proper rotations
# R in SO(3), all uniform scales s > 0 and all translations t. q_bar is the
# centroid of the problem point set.
#
# CONVENTION USED HERE, FIXED (`include_centre=True`, reported in `method`):
#
#   * the central atom is the (n+1)-th vertex of BOTH point sets - of the
#     problem set at its own measured position, of every reference at the
#     origin, which is the reference polyhedron's centre. This is the SHAPE
#     convention for coordination polyhedra: it makes the measure sensitive
#     to a central atom that does not sit at the centre of its own ligand
#     polyhedron, which a bare vertex-only measure cannot see. The central
#     atom is never permuted with the ligands.
#   * the translation minimum is taken analytically: both point sets are
#     moved onto their own centroid (over all n+1 points). Note this is the
#     CENTROID of the n+1 points, not the central atom - for an ideal
#     polyhedron the two coincide, for a real one they do not.
#   * only proper rotations. Every reference below is achiral, so its mirror
#     image is one of its own vertex permutations and allowing O(3) would
#     change nothing; the det > 0 branch of Kabsch is used so the result
#     stays correct if a chiral reference is ever added.
#
# With both sets centred, the minimum over R and s is closed-form. Writing
# Sq = sum|q_k - q_bar|^2, Sp = sum|p_k - p_bar|^2 and
# H(sigma) = sum_k (p_sigma(k) - p_bar) (q_k - q_bar)^T,
#
#     max_R tr(R H) = sigma_1 + sigma_2 + sign(det H) sigma_3       (Kabsch)
#     best scale     s = max_R tr(R H) / Sp
#     S              = 100 x (1 - [max_R tr(R H)]^2 / (Sq Sp))
#
# so one 3x3 SVD per permutation and nothing else. S is bounded in [0, 100]
# and is invariant to rotation, uniform scaling and ligand order by
# construction.
#
# LITERATURE CONSTANTS THIS REPRODUCES (see tests/test_shape.py)
#   ideal octahedron           S(OC-6)   = 0.000    S(TPR-6) = 16.737
#   ideal trigonal prism       S(TPR-6)  = 0.000    S(OC-6)  = 16.737
#   ideal square               S(SP-4)   = 0.000    S(T-4)   = 33.333
#   ideal tetrahedron          S(T-4)    = 0.000    S(SP-4)  = 33.333
#   ideal trigonal bipyramid   S(TBPY-5) = 0.000    S(SPY-5) =  5.375
#                                                   S(vOC-5) =  7.342
#
# The last row is DERIVED here, not quoted: it is the value of the SPY-5
# reference defined below (apical-basal angle 104.9 deg, Alvarez) measured on
# an ideal D3h trigonal bipyramid, under this module's convention. It is
# shallow in the reference angle - 5.383 at 104.5 deg, 5.375 at 104.9 deg,
# 5.374 at 105.0 deg - so it is quoted to three decimals with the reference
# angle attached, and any comparison with a published SHAPE table must check
# that table's SPY-5 angle first.

#: apical-basal angle of the SPY-5 reference, degrees (Alvarez 2005).
SPY5_APICAL_BASAL_DEG = 104.9

#: how many decimals a shape measure is reported to (SHAPE prints three).
CSHM_DECIMALS = 3


def _reference_shapes() -> dict[str, np.ndarray]:
    """Ideal reference polyhedra, vertices on the unit sphere about the
    central atom at the origin (size is irrelevant - the measure minimises
    over scale - but a common radius keeps the tables readable).

      T-4     regular tetrahedron, Td, L-M-L 109.471 deg
      SP-4    square,              D4h, cis 90 / trans 180 deg
      TBPY-5  trigonal bipyramid,  D3h, ax-M-ax 180, eq-M-eq 120, ax-eq 90
      SPY-5   square pyramid,      C4v, apical-basal SPY5_APICAL_BASAL_DEG
      vOC-5   vacant octahedron,   C4v, octahedron with one vertex removed
              (apical-basal 90 deg) - the CN-5 reference that SPY-5 becomes
              when its apical-basal angle is opened to a right angle
      OC-6    octahedron,          Oh
      TPR-6   trigonal prism,      D3h, all twelve edges equal (two
              equilateral triangles of side a, circumradius a/sqrt(3), at
              z = +-a/2)
    """
    out: dict[str, np.ndarray] = {}
    out["T-4"] = np.array([(1, 1, 1), (1, -1, -1), (-1, 1, -1), (-1, -1, 1)],
                          float) / math.sqrt(3.0)
    out["SP-4"] = np.array([(1, 0, 0), (0, 1, 0), (-1, 0, 0), (0, -1, 0)], float)

    s3 = math.sqrt(3.0) / 2.0
    out["TBPY-5"] = np.array([(0, 0, 1), (0, 0, -1),
                              (1, 0, 0), (-0.5, s3, 0), (-0.5, -s3, 0)], float)
    th = math.radians(SPY5_APICAL_BASAL_DEG)
    st, ct = math.sin(th), math.cos(th)
    out["SPY-5"] = np.array(
        [(0.0, 0.0, 1.0)]
        + [(st * math.cos(math.radians(a)), st * math.sin(math.radians(a)), ct)
           for a in (0.0, 90.0, 180.0, 270.0)], float)
    out["vOC-5"] = np.array([(0, 0, 1), (1, 0, 0), (0, 1, 0),
                             (-1, 0, 0), (0, -1, 0)], float)

    out["OC-6"] = np.array([(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0),
                            (0, 0, 1), (0, 0, -1)], float)
    r = 1.0 / math.sqrt(3.0)          # circumradius of a unit-edge triangle
    out["TPR-6"] = np.array(
        [(r * math.cos(math.radians(t)), r * math.sin(math.radians(t)), z)
         for z in (0.5, -0.5) for t in (0.0, 120.0, 240.0)], float)
    return out


REFERENCE_SHAPES: dict[str, np.ndarray] = _reference_shapes()

#: reference names available per coordination number, in report order
SHAPES_BY_CN: dict[int, tuple[str, ...]] = {
    4: ("T-4", "SP-4"),
    5: ("TBPY-5", "SPY-5", "vOC-5"),
    6: ("OC-6", "TPR-6"),
}

_PERM_CACHE: dict[int, np.ndarray] = {}


def _permutations(n: int) -> np.ndarray:
    """All n! permutations as an (n!, n) index array, built once per n."""
    cached = _PERM_CACHE.get(n)
    if cached is None:
        cached = np.array(list(itertools.permutations(range(n))), dtype=np.intp)
        _PERM_CACHE[n] = cached
    return cached


def _cshm_one(qc: np.ndarray, pc: np.ndarray, sq: float, sp: float,
              perms: np.ndarray) -> float:
    """S for one reference, both point sets already centroid-centred.

    qc, pc  (m, 3) with m = n_ligands + 1; row m-1 is the central atom of
            each set and is NOT permuted (it is appended to every permutation)
    """
    pp = pc[perms]                                    # (n!, m, 3)
    h = np.einsum("pna,nb->pab", pp, qc)              # (n!, 3, 3)
    sv = np.linalg.svd(h, compute_uv=False)           # (n!, 3), descending
    det = np.linalg.det(h)
    sign = np.where(det < 0.0, -1.0, 1.0)
    c = sv[:, 0] + sv[:, 1] + sign * sv[:, 2]
    val = 100.0 * (1.0 - (c * c) / (sq * sp))
    return float(max(0.0, val.min()))


def cshm(centre_xyz: Sequence[float],
         ligand_xyz: Sequence[Sequence[float]],
         shapes: Iterable[str] | None = None,
         *, include_centre: bool = True) -> dict[str, Any]:
    """Continuous shape measures of one coordination sphere.

    centre_xyz   cartesian position of the central atom (Angstrom)
    ligand_xyz   (n, 3) cartesian positions of its n ligand atoms, in the
                 order the caller counted them; the result does not depend
                 on that order
    shapes       reference names to measure; None = every reference tabulated
                 for this coordination number (`SHAPES_BY_CN`)
    include_centre
                 True (fixed default, SHAPE convention): the central atom is
                 an extra, unpermuted vertex of both point sets. False
                 measures the ligand polyhedron alone. The two agree on an
                 ideal polyhedron and differ on a real one; whichever is used
                 is named in `method`.

    Returns, always, and never raises on a coordination number it has no
    reference for:

        {"cn": n,
         "cshm": {"OC-6": 0.021, "TPR-6": 15.884},   # {} when no reference
         "closest_shape": "OC-6" | None,
         "closest_cshm": 0.021 | None,
         "method": <formula, convention, permutation count>,
         "note": <what applies to this call>}

    Measures are rounded to CSHM_DECIMALS (3, as SHAPE prints them); the
    closest reference is chosen on the unrounded values. S = 0 is exact
    agreement with the reference shape and S = 100 the algebraic maximum;
    the number carries no verdict.
    """
    q_lig = np.asarray(ligand_xyz, dtype=float).reshape(-1, 3)
    centre = np.asarray(centre_xyz, dtype=float).reshape(3)
    n = int(q_lig.shape[0])
    notes: list[str] = []

    method = (
        "S = 100 x min over {permutation sigma, rotation R in SO(3), scale s, "
        "translation} of sum|q_k - s.R.p_sigma(k)|^2 / sum|q_k - q_mean|^2 "
        "(Pinsky & Avnir 1998; reference shapes as Alvarez 2005 / SHAPE). "
        + ("Central atom included as an extra unpermuted vertex of both point "
           "sets (SHAPE convention for coordination polyhedra); "
           if include_centre else
           "Ligand polyhedron only, central atom excluded from both point "
           "sets; ")
        + "both sets translated onto their own centroid; rotation by "
        "Kabsch/SVD with the sign(det) branch; scale analytic; permutations "
        "enumerated exhaustively"
        + (f" ({n}! = {math.factorial(n)})" if n in SHAPES_BY_CN else "")
        + f". SPY-5 apical-basal angle {SPY5_APICAL_BASAL_DEG} deg."
    )
    empty = {"cn": n, "cshm": {}, "closest_shape": None, "closest_cshm": None,
             "method": method}

    available = SHAPES_BY_CN.get(n)
    if not available:
        return {**empty, "note": f"no reference shapes for CN {n}"}

    wanted: list[str]
    if shapes is None:
        wanted = list(available)
    else:
        wanted = []
        for name in shapes:
            if name in available:
                wanted.append(name)
            elif name in REFERENCE_SHAPES:
                notes.append(f"{name} has {len(REFERENCE_SHAPES[name])} "
                             f"vertices, not {n} - skipped")
            else:
                notes.append(f"no reference shape named {name!r} - skipped")
        if not wanted:
            return {**empty, "note": "; ".join(notes) or
                    f"no requested reference shape applies to CN {n}"}

    if include_centre:
        q = np.vstack([q_lig, centre[None, :]])
    else:
        q = q_lig
    qc = q - q.mean(axis=0)
    sq = float((qc * qc).sum())
    if not np.isfinite(sq) or sq <= 0.0:
        return {**empty, "note": "; ".join(notes + [
            "the coordination sphere has no spread (all points coincide or a "
            "coordinate is not finite) - the measure is undefined"])}

    perms = _permutations(n)
    if include_centre:
        perms = np.hstack([perms, np.full((perms.shape[0], 1), n, dtype=np.intp)])

    measures: dict[str, float] = {}
    for name in wanted:
        ref = REFERENCE_SHAPES[name]
        p = np.vstack([ref, np.zeros((1, 3))]) if include_centre else ref
        pc = p - p.mean(axis=0)
        sp = float((pc * pc).sum())
        measures[name] = _cshm_one(qc, pc, sq, sp, perms)

    best = min(measures, key=lambda k: measures[k])
    notes.append("S = 0 is exact agreement with the reference; the closest "
                 "reference is the smallest S, not a classification")
    return {
        "cn": n,
        "cshm": {k: round(v, CSHM_DECIMALS) for k, v in measures.items()},
        "closest_shape": best,
        "closest_cshm": round(measures[best], CSHM_DECIMALS),
        "method": method,
        "note": "; ".join(notes),
    }


# ---------------------------------------------------------------------------
# 2. Macrocycle census
# ---------------------------------------------------------------------------

#: DFS steps before the largest-cycle search reports truncation. Same
#: discipline (and same value) as `chem.connectivity._RING_SEARCH_BUDGET`:
#: a ghost-peak cluster must not hang the caller, and the cut is reported.
RING_SEARCH_BUDGET = 2_000_000

#: default upper bound on the ring size searched for.
MACROCYCLE_CAP = 64


def largest_cycle(adj: Mapping[int, Iterable[int]],
                  comp: Iterable[int] | None = None,
                  cap: int = MACROCYCLE_CAP,
                  budget: int = RING_SEARCH_BUDGET) -> dict[str, Any]:
    """Largest chordless cycle of one bonded fragment, plus the size of its
    cycle space.

    adj    the MOLECULAR graph of ONE fragment instance, `{i: set(j)}`,
           symmetric. The atom indices may be ASU-level or P1-level - the
           function never looks at coordinates, so either works - but the
           graph must be SHIFT-FREE: an edge that only closes through a
           lattice translation is not a molecular ring and must not be in
           `adj`. (`refine.inspect.organic_fragments` builds exactly such a
           graph, `n["sym"]` false; a P1 expansion needs the cumulative cell
           shift checked to be (0,0,0) the way
           `chem.connectivity._carbocycles` checks it. Putting a periodic
           edge in `adj` turns a 1-D chain into a spurious macrocycle.)
    comp   the atom indices to search, normally one connected component.
           None searches every key of `adj`.
    cap    largest ring size searched for; rings longer than `cap` are not
           looked for and `truncated` says so. Must be >= 3.
    budget DFS steps before the search stops and reports truncation.

    Returns

        {"size": 24 | None,          # None = no chordless cycle within `cap`
         "atoms": [i, j, ...],       # cycle order; [] when size is None
         "truncated": False,
         "n_cycles_basis": 1,        # edges - vertices + components
         "method": ..., "note": ...}

    CHORDLESS (induced) is the definition on purpose: the 10-membered
    perimeter of naphthalene is a cycle, but the ring-fusion bond is a chord
    of it, so the largest chordless cycle of naphthalene is 6 - which is what
    a crystallographer means by its ring size. `n_cycles_basis` is the
    cyclomatic number (the number of independent cycles a spanning forest
    leaves over, edges - vertices + components), so a fused polycyclic cage
    reports how many rings it has independently of how large the largest
    chordless one is.

    COST. A macrocycle is cheap (a 64-membered ring, 2.6 ms) because a ring
    offers one path per direction. A heavily fused sheet is the worst case
    and is exponential: 72 carbons in a fused-hexagon ladder (25 independent
    cycles) exhaust the 2,000,000-step budget in about 1.5 s and come back
    with `truncated` True and the largest cycle found so far. A caller on a
    time budget should pass a smaller `budget`, or a `comp` that is one
    fragment rather than a whole framework.
    """
    graph: dict[int, set[int]] = {int(u): {int(v) for v in vs if int(v) != int(u)}
                                  for u, vs in adj.items()}
    notes: list[str] = []
    one_way = 0
    for u, vs in list(graph.items()):
        for v in vs:
            if u not in graph.setdefault(v, set()):
                graph[v].add(u)
                one_way += 1
    if one_way:
        notes.append(f"the adjacency map was not symmetric ({one_way} one-way "
                     f"entries); it was symmetrised before the search")
    comp_set = {int(u) for u in (comp if comp is not None else graph.keys())}
    comp_set &= set(graph.keys())

    # -- cycle space of the induced subgraph -------------------------------
    n_vertices = len(comp_set)
    edges = 0
    for u in comp_set:
        edges += sum(1 for v in graph[u] if v in comp_set and v > u)
    seen: set[int] = set()
    n_components = 0
    for u in sorted(comp_set):
        if u in seen:
            continue
        n_components += 1
        stack = [u]
        seen.add(u)
        while stack:
            w = stack.pop()
            for x in graph[w]:
                if x in comp_set and x not in seen:
                    seen.add(x)
                    stack.append(x)
    n_basis = edges - n_vertices + n_components
    if n_components > 1:
        notes.append(f"the selection is not connected ({n_components} "
                     f"components); n_cycles_basis is edges - vertices + "
                     f"components")

    method = (f"cycle space from a spanning forest (edges - vertices + "
              f"components); largest CHORDLESS cycle by depth-first search "
              f"over induced paths, ring size <= {int(cap)}, "
              f"budget {int(budget)} DFS steps")
    out = {"size": None, "atoms": [], "truncated": False,
           "n_cycles_basis": int(n_basis), "method": method}

    if not comp_set:
        return {**out, "note": "; ".join(notes + [
            "the selection is empty (no atom index is a key of the adjacency "
            "map)"])}
    if cap < 3:
        return {**out, "truncated": True,
                "note": "; ".join(notes + [f"cap {cap} is below the smallest "
                                           f"possible ring (3)"])}
    if n_basis <= 0:
        return {**out, "note": "; ".join(notes + [
            "the selection is acyclic (a spanning forest uses every edge), "
            "so it has no ring at all"])}

    best, truncated_cap, truncated_budget = _largest_chordless(
        graph, comp_set, int(cap), int(budget))
    truncated = bool(truncated_cap or truncated_budget)
    if truncated_cap:
        notes.append(f"the search stopped at ring size {int(cap)} (cap); a "
                     f"larger ring, if any, was not looked for")
    if truncated_budget:
        notes.append(f"the search stopped after {int(budget)} DFS steps "
                     f"(budget); the census is incomplete")
    if best is None and not truncated:
        notes.append(f"the search completed and found no chordless cycle, "
                     f"though the cycle space has {int(n_basis)} independent "
                     f"cycle(s) - every cycle here carries a chord")
    return {**out,
            "size": (len(best) if best is not None else None),
            "atoms": (list(best) if best is not None else []),
            "truncated": truncated,
            "note": "; ".join(notes)}


def _largest_chordless(graph: dict[int, set[int]], comp_set: set[int],
                       cap: int, budget: int
                       ) -> tuple[list[int] | None, bool, bool]:
    """Budgeted DFS over INDUCED paths; returns (best cycle, cap hit, budget hit).

    Invariant: `path` is an induced path whose first vertex is the smallest
    of the path and of any cycle it can close into. A candidate v extends it
    when v is adjacent to the last vertex, to no interior vertex, and not to
    the first; when v IS adjacent to the first vertex the cycle path + [v] is
    chordless (the induced path carries no chord and the closing edge is the
    only extra edge), it is recorded and never extended through - any longer
    cycle containing this path would carry v-path[0] as a chord.

    Each chordless cycle is reached once per starting vertex (its smallest)
    and once per direction; `path[1] < v` keeps one of the two directions.
    Implemented with an explicit stack so that `cap` is not bounded by the
    interpreter's recursion limit.
    """
    best: list[int] | None = None
    steps = 0
    cap_hit = False
    budget_hit = False

    def expand(path: list[int], pset: set[int]) -> list[int]:
        """Record any chordless cycle closing at `path`; return extensions."""
        nonlocal best, steps, cap_hit, budget_hit
        p0 = path[0]
        interior = path[1:-1]
        ext: list[int] = []
        for v in graph[path[-1]]:
            steps += 1
            if steps > budget:
                budget_hit = True
                return []
            if v <= p0 or v in pset or v not in comp_set:
                continue
            av = graph[v]
            if any(w in av for w in interior):
                continue                       # chord to the path interior
            if p0 in av:
                if path[1] < v:                # one direction per cycle
                    size = len(path) + 1
                    if size <= cap and (best is None or size > len(best)):
                        best = path + [v]
            elif len(path) + 1 <= cap - 1:
                ext.append(v)
            else:
                cap_hit = True                 # a longer path was available
        return ext

    for start in sorted(comp_set):
        if budget_hit:
            break
        firsts = sorted(v for v in graph[start] if v > start and v in comp_set)
        for first in firsts:
            if budget_hit:
                break
            path = [start, first]
            pset = {start, first}
            frames: list[list[int]] = [expand(path, pset)]
            while frames:
                if budget_hit:
                    break
                cands = frames[-1]
                if not cands:
                    frames.pop()
                    if frames:
                        pset.discard(path.pop())
                    continue
                v = cands.pop()
                path.append(v)
                pset.add(v)
                frames.append(expand(path, pset))
    return best, cap_hit, budget_hit


# ---------------------------------------------------------------------------
# 3. Shape evidence for a finite fragment
# ---------------------------------------------------------------------------
#
# SPHERICITY. The formula implemented is Wadell's,
#
#     Psi = pi^(1/3) (6 V)^(2/3) / A  =  (36 pi V^2)^(1/3) / A
#
# which is 1 for a sphere and < 1 for anything else. The round-2 plan writes
# it as `4 pi^(1/3) (3V)^(2/3) / A`; that transcription is larger by
# 4 (3/6)^(2/3) = 4^(2/3) = 2.5198 and gives 2.520 for a sphere and 2.131 for
# a regular octahedron, so it cannot be the intended quantity. The plan's own
# check ("1.0 for a sphere") is what is implemented here. Reference values
# this reproduces, all analytic:
#
#     sphere              1.000000
#     regular octahedron  pi^(1/3)/sqrt(3)     = 0.845583
#     cube                (pi/6)^(1/3)         = 0.805996
#     regular tetrahedron (pi/2)^(1/3)/sqrt(3) = 0.671126

_SPHERICITY_FORMULA = "sphericity = pi^(1/3)(6V)^(2/3)/A = (36 pi V^2)^(1/3)/A"


def _masses(n: int, elements: Sequence[str] | None) -> tuple[np.ndarray, str | None]:
    """Atomic weights from cctbx, or unit masses. Never raises."""
    if elements is None:
        return np.ones(n), None
    if len(elements) != n:
        return np.ones(n), (f"{len(elements)} element symbols for {n} points - "
                            f"unit masses used instead")
    from cctbx.eltbx import tiny_pse
    out = np.ones(n)
    unknown: list[str] = []
    for k, raw in enumerate(elements):
        el = element_symbol(raw)
        try:
            out[k] = float(tiny_pse.table(el).weight())
        except Exception:
            unknown.append(str(raw))
    if unknown:
        return out, ("no atomic weight for " + ", ".join(sorted(set(unknown)))
                     + " - those points carry unit mass")
    return out, None


def shape_evidence(xyz: Sequence[Sequence[float]],
                   elements: Sequence[str] | None = None) -> dict[str, Any]:
    """Measurable shape evidence for a finite fragment - the honest
    substitute for a shape nickname.

    xyz       (n, 3) cartesian coordinates, Angstrom
    elements  optional element symbols (or scattering types); when given the
              inertia tensor is mass-weighted with cctbx atomic weights,
              otherwise every point carries unit mass. The convex hull is
              always over the bare points: no van der Waals radii are added,
              so `hull_volume_A3` is the volume of the point polyhedron, not
              a molecular volume.

    Returns

        {"inertia_ratios": [I1/I3, I2/I3],   # principal moments, I1<=I2<=I3
         "sphericity": 0.8456,               # convex hull, 1.0 for a sphere
         "hull_volume_A3": 1.333,
         "hull_area_A2": 6.928,
         "longest_axis_A": 2.0,              # largest point-to-point distance
         "aspect": [a/c, b/c],               # inertia-frame bounding box
         "n_points": 6, "mass_weighted": False,
         "method": ..., "note": ...}

    Hull-derived fields are None (with the reason in `note`, never an
    exception) when there are fewer than four points or the points are
    coplanar. Inertia ratios and aspect survive a planar fragment and are
    None only when the fragment has no spread at all.

    CAVEAT carried in `note` when it applies: when two principal moments are
    equal (a spherical or symmetric top - an octahedron, a tetrahedron, a
    linear rod) the principal AXES are not unique inside the degenerate
    subspace, so `aspect`, which is measured in that frame, is one of several
    equally valid answers. `inertia_ratios` and `sphericity` are unaffected.
    """
    pts = np.asarray(xyz, dtype=float).reshape(-1, 3)
    n = int(pts.shape[0])
    notes: list[str] = []
    method = (
        "inertia_ratios: eigenvalues I1<=I2<=I3 of the inertia tensor "
        "sum m(|r|^2 I - r r^T) about the centre of mass, reported as "
        "[I1/I3, I2/I3]; " + _SPHERICITY_FORMULA + " over the convex hull of "
        "the bare atom positions (no van der Waals radii); aspect: extents of "
        "the bounding box in the principal-axis frame, sorted a<=b<=c, "
        "reported as [a/c, b/c]; longest_axis_A: largest point-to-point "
        "distance"
    )
    out: dict[str, Any] = {
        "inertia_ratios": None, "sphericity": None, "hull_volume_A3": None,
        "hull_area_A2": None, "longest_axis_A": None, "aspect": None,
        "n_points": n, "mass_weighted": False, "method": method,
    }
    if n == 0 or not np.isfinite(pts).all():
        return {**out, "note": "no finite coordinates"}

    mass, mass_note = _masses(n, elements)
    out["mass_weighted"] = bool(elements is not None and not mass_note)
    if mass_note:
        notes.append(mass_note)
    com = (mass[:, None] * pts).sum(axis=0) / mass.sum()
    rel = pts - com

    spread = float((mass[:, None] * rel * rel).sum())
    if spread <= 0.0:
        return {**out, "note": "; ".join(notes + [
            "the points have no spread about their centre of mass (a single "
            "point, or every point at the same position) - no shape to "
            "measure"])}

    # -- inertia tensor and its principal frame ----------------------------
    r2 = (rel * rel).sum(axis=1)
    tensor = np.eye(3) * float((mass * r2).sum())
    tensor -= np.einsum("k,ka,kb->ab", mass, rel, rel)
    moments, axes = np.linalg.eigh(tensor)         # ascending, orthonormal
    moments = np.clip(moments, 0.0, None)
    i3 = float(moments[2])
    if i3 > 0.0:
        out["inertia_ratios"] = [round(float(moments[0]) / i3, 4),
                                 round(float(moments[1]) / i3, 4)]
        if min(i3 - float(moments[1]),
               float(moments[1]) - float(moments[0])) <= 1e-6 * i3:
            notes.append("two principal moments coincide, so the principal "
                         "axes - and with them `aspect` - are not unique")

    # -- bounding box in the principal frame -------------------------------
    proj = rel @ axes
    extents = np.sort(proj.max(axis=0) - proj.min(axis=0))
    if extents[2] > 0.0:
        out["aspect"] = [round(float(extents[0] / extents[2]), 4),
                         round(float(extents[1] / extents[2]), 4)]

    # -- longest point-to-point distance -----------------------------------
    out["longest_axis_A"] = round(float(_diameter(pts)), 3)

    # -- convex hull -------------------------------------------------------
    if n < 4:
        notes.append(f"{n} point(s): a convex hull needs four non-coplanar "
                     f"points, so volume, area and sphericity are not defined")
        return {**out, "note": "; ".join(notes)}
    sv = np.linalg.svd(rel, compute_uv=False)
    if sv[0] <= 0.0 or sv[2] <= 1e-9 * sv[0]:
        notes.append("the points are coplanar (or collinear), so the convex "
                     "hull has no volume and sphericity is not defined")
        return {**out, "note": "; ".join(notes)}
    try:
        from scipy.spatial import ConvexHull
        hull = ConvexHull(pts)
        vol = float(hull.volume)
        area = float(hull.area)
        out["hull_volume_A3"] = round(vol, 3)
        out["hull_area_A2"] = round(area, 3)
        if vol > 0.0 and area > 0.0:
            psi = math.pi ** (1.0 / 3.0) * (6.0 * vol) ** (2.0 / 3.0) / area
            out["sphericity"] = round(float(psi), 4)
        if sv[2] <= 1e-3 * sv[0]:
            notes.append("the points are close to coplanar (smallest / largest "
                         f"spread = {float(sv[2] / sv[0]):.2e}), so the hull "
                         "volume and sphericity are ill-conditioned")
    except Exception as exc:                        # Qhull degeneracy
        notes.append(f"the convex hull could not be built "
                     f"({type(exc).__name__}), so volume, area and sphericity "
                     f"are not defined")
    return {**out, "note": "; ".join(notes)}


def _diameter(pts: np.ndarray) -> float:
    """Largest point-to-point distance; the convex hull carries it, so only
    the hull vertices are compared when there are many points."""
    probe = pts
    if pts.shape[0] > 64:
        try:
            from scipy.spatial import ConvexHull
            probe = pts[ConvexHull(pts).vertices]
        except Exception:
            probe = pts
    if probe.shape[0] < 2:
        return 0.0
    d2 = ((probe[:, None, :] - probe[None, :, :]) ** 2).sum(axis=2)
    return float(math.sqrt(max(0.0, float(d2.max()))))


# ---------------------------------------------------------------------------
# 4. Crystallographic point symmetry of a fragment
# ---------------------------------------------------------------------------

#: default match tolerance, fractional coordinates, per component
SITE_SYMMETRY_TOL = 0.02


def crystallographic_point_symmetry(xs, atom_indices: Sequence[int],
                                    tol: float = SITE_SYMMETRY_TOL
                                    ) -> dict[str, Any]:
    """The space-group operators that map one fragment onto itself.

    xs            cctbx.xray.structure
    atom_indices  the scatterer indices of ONE COMPLETE fragment instance.
                  This matters: a molecule sitting on an inversion centre is
                  stored in the asymmetric unit as HALF a molecule, and
                  inversion maps that half onto the other half, not onto
                  itself - passing the ASU half returns the trivial group.
                  Pass the assembled fragment (both halves present as
                  scatterers) to see the inversion.
    tol           per-component tolerance on the fractional coordinates,
                  after wrapping to the nearest lattice translation

    Returns

        {"ops": ["x,y,z", "-x,-y,-z"],
         "order": 2,
         "symbol_hint": "-1" | None,
         "space_group": "P -1", "space_group_order": 2,
         "method": ..., "note": ...}

    An operator is kept when it maps the fragment's atom set onto itself as a
    SET, modulo lattice translations (fractional coordinates compared mod 1)
    and modulo the labelling, with element symbols required to match and the
    induced map required to be a bijection. The result is therefore a
    subgroup of the space group taken modulo lattice translations, and its
    order divides `space_group_order` (= `space_group.order_z()`).

    It is a SUBGROUP of the true molecular point group and generally a proper
    one: a tetrahedral anion in a triclinic cell has molecular symmetry -43m
    and crystallographic site symmetry 1. `symbol_hint` is the
    Hermann-Mauguin symbol of the group generated by the rotation parts, read
    off cctbx in its standard setting, so it names the TYPE of the site
    symmetry and not its orientation in this cell.

    The operator strings are the space group's own (they are members of
    `all_ops()`), so they name the type and orientation of each element but
    NOT where in the cell it sits: because the atom sets are compared modulo
    lattice translations, a molecule on the inversion centre at (1/2,1/2,1/2)
    reports the same `-x,-y,-z` as one on the centre at the origin.
    """
    from cctbx import sgtbx

    idx = [int(i) for i in atom_indices]
    sg = xs.space_group()
    sg_symbol = str(sgtbx.space_group_info(group=sg))
    method = (f"space-group operators g (all_ops of {sg_symbol}) for which "
              f"g maps the fragment's atom set onto itself modulo lattice "
              f"translations (fractional coordinates compared mod 1, per "
              f"component tolerance {tol}), element symbols matched, the "
              f"induced atom map required to be a bijection")
    base = {"ops": [], "order": 0, "symbol_hint": None,
            "space_group": sg_symbol, "space_group_order": int(sg.order_z()),
            "method": method}
    note_tail = ("site-symmetry subgroup of the space group that maps the "
                 "fragment onto itself (mod lattice translations); a SUBGROUP "
                 "of the true molecular point group; each operator is the "
                 "space group's own, so it names the element's type and "
                 "orientation but does not say where in the cell it sits")
    if not idx:
        return {**base, "note": "empty fragment; " + note_tail}

    scs = list(xs.scatterers())
    if any(i < 0 or i >= len(scs) for i in idx):
        return {**base, "note": "atom index out of range; " + note_tail}

    sites = np.array([[float(c) for c in scs[i].site] for i in idx])
    elems = [element_symbol(scs[i].scattering_type) for i in idx]

    ops: list[str] = []
    for op in sg.all_ops():
        rot = np.array(op.r().as_double(), dtype=float).reshape(3, 3)
        trans = np.array(op.t().as_double(), dtype=float)
        images = sites @ rot.T + trans
        hit = _set_maps_onto_itself(images, sites, elems, tol)
        if hit is not None:
            ops.append(op.as_xyz())
    order = len(ops)
    notes = [note_tail]
    if order and int(sg.order_z()) % order:
        notes.append(f"WARNING: the order {order} does not divide the "
                     f"space-group order {int(sg.order_z())} - the tolerance "
                     f"{tol} is admitting an operator that is not a symmetry")

    hint = None
    if ops:
        try:
            grp = sgtbx.space_group()
            for xyz in ops:
                # rotation part only, default translation denominator
                grp.expand_smx(sgtbx.rt_mx(sgtbx.rt_mx(xyz).r().as_xyz()))
            symbol = sgtbx.space_group_info(group=grp).type().lookup_symbol()
            parts = str(symbol).split()
            hint = " ".join(parts[1:]) if len(parts) > 1 else str(symbol)
        except Exception as exc:
            notes.append(f"no Hermann-Mauguin hint ({type(exc).__name__})")
    return {**base, "ops": ops, "order": order, "symbol_hint": hint,
            "note": "; ".join(notes)}


def _set_maps_onto_itself(images: np.ndarray, sites: np.ndarray,
                          elems: Sequence[str], tol: float) -> list[int] | None:
    """The permutation image -> original, or None when there is no bijection.

    Fractional differences are wrapped to the nearest lattice translation and
    compared per component, so any lattice translation is allowed and the
    fragment may straddle a cell face.
    """
    delta = images[:, None, :] - sites[None, :, :]
    delta -= np.round(delta)
    dist = np.abs(delta).max(axis=2)               # (n_images, n_sites)
    taken: set[int] = set()
    perm: list[int] = []
    for k in range(images.shape[0]):
        order = np.argsort(dist[k])
        pick = -1
        for j in order:
            if dist[k, int(j)] > tol:
                break
            if int(j) in taken or elems[int(j)] != elems[k]:
                continue
            pick = int(j)
            break
        if pick < 0:
            return None
        taken.add(pick)
        perm.append(pick)
    return perm
