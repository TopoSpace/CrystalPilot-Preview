"""Pore geometry on the solvent-mask grid (round-2 R3.0-R3.3): channel
dimensionality and direction, largest inscribed sphere, pore-limiting
diameter, packing numbers.

Why this exists (defect D17). `cctbx.masks.flood_fill` is periodic - a void
that crosses a cell face is ONE void - but the centre of mass it accumulates
is the mean of UNWRAPPED grid points, which for a through-channel is a point
outside the cell that means nothing (a hexagonal-channel MOF reported its
17 000 A^3 channel "centred" at (0.39, -0.13, -0.48)). A centroid is only
defined for a 0-D cavity. What every void has is a largest inscribed sphere,
and a periodicity: 0 (cavity), 1 (channel, with a direction), 2 (layer),
3 (a 3-D pore network).

DIMENSIONALITY. The flood-fill label grid is split into NON-periodic
6-connected components (scipy.ndimage.label), then the three pairs of cell
faces are sewn back together with a union-find that carries an integer
offset per component (the cell translation that puts the component into
its root's frame). A sewing edge that closes a cycle with a non-zero
mismatch yields a lattice vector along which the void repeats; the rank of
the mismatch vectors is the dimensionality, a primitive integer basis of
them the channel directions. Same formula `connectivity.analyze_connectivity`
uses for framework dimensionality.

INSCRIBED SPHERE. R(x) = min_a(|x - r_a| - r_vdW(a)) evaluated at the void's
own grid points, with one KD-tree per element over the 27-cell expansion of
the P1 atoms - NOT scipy.ndimage.distance_transform_edt, which measures in
grid units on an orthogonal lattice (wrong in a triclinic cell) and cannot
see per-atom radii. The largest R is the free-sphere radius (LCD = 2R,
Foster 2006 / Zeo++ Willems 2012 convention) and its argmax the
inscribed-sphere centre, defined for a void of any dimensionality. A void
too big to scan whole is thinned to one point per cell of a regular
fractional LATTICE and then refined back to the exact maximum using the
1-Lipschitz bound on R (see `inscribed_sphere`) - never `points[::k]`,
which thins a lexicographically ordered voxel list along one axis only and
let a FINER grid return a SMALLER sphere. The error of both numbers is the
caller's grid step, reported alongside.

PORE-LIMITING DIAMETER. PLD = 2 rho*, rho* = sup{rho : the sub-set
{R >= rho} of the void still percolates}, found by bisection with the
same periodic sewing as the dimensionality (a threshold set is
"percolating" when its own `void_topology` dimensionality is >= 1, i.e.
it repeats along at least one lattice vector). This is a supremum over
ALL paths, not along one straight line: for a single atom per simple
cubic cell the free sphere does not squeeze between two atoms at (1/2,
0, 0) (R = a/2 - r_vdW) but detours through the window at (1/2, 1/2, 0)
(R = a/sqrt(2) - r_vdW), which is the larger of the two and therefore
the answer. Unlike the inscribed sphere this must see EVERY voxel of the
void - a random subsample would cut the very connections being tested -
so when the void is bigger than the budget the whole label grid is
coarsened by an integer stride and the reported step grows with it.

PACKING. Kitaigorodskii packing index = sum of the vdW ball volumes over
the P1 atoms / V_cell, with no overlap correction, and V_cell per
non-hydrogen atom against the 18 A^3 rule. Both are read next to, never
subtracted from, the solvent-accessible volume (knowledge base 5.7).
"""
from __future__ import annotations

from math import gcd
from typing import Any

import numpy as np

#: cap on the void grid points scanned for the inscribed sphere; beyond it
#: every k-th point is taken and the reported grid step grows accordingly
MAX_SCAN_POINTS = 60_000

#: how many thin -> refine rounds the inscribed-sphere scan may take before
#: it reports `exact: False` (a maximum so flat the bins cannot separate it)
MAX_REFINE_ROUNDS = 8


# ------------------------------------------------------------ periodicity --

def _primitive(v: np.ndarray) -> list[int]:
    ints = [int(round(x)) for x in v]
    g = 0
    for x in ints:
        g = gcd(g, abs(x))
    if g > 1:
        ints = [x // g for x in ints]
    # canonical sign: first non-zero component positive
    for x in ints:
        if x != 0:
            if x < 0:
                ints = [-y for y in ints]
            break
    return ints


def lattice_basis(vectors: list) -> tuple[int, list[list[int]]]:
    """(rank, primitive integer basis) of the lattice spanned by integer
    vectors - greedy: shortest first, keep the independent ones."""
    vs = [np.asarray(v, dtype=float) for v in vectors
          if np.any(np.abs(np.asarray(v, dtype=float)) > 1e-9)]
    if not vs:
        return 0, []
    vs.sort(key=lambda v: (float(np.dot(v, v)), tuple(v)))
    basis: list[np.ndarray] = []
    for v in vs:
        cand = basis + [v]
        if np.linalg.matrix_rank(np.array(cand)) == len(cand):
            basis.append(v)
        if len(basis) == 3:
            break
    return len(basis), [_primitive(b) for b in basis]


def void_topology(labels: np.ndarray, value: int) -> dict[str, Any]:
    """Dimensionality / directions / component count of the void whose
    flood-fill label is `value`, on a periodic grid of shape (nx, ny, nz).

    Returns {"dimensionality": 0..3, "directions": [[u, v, w], ...],
    "n_components": int (non-periodic pieces inside one cell)}.
    """
    from scipy import ndimage

    mask = np.asarray(labels) == value
    if not mask.any():
        return {"dimensionality": 0, "directions": [], "n_components": 0}
    comp, n = ndimage.label(mask)          # 6-connected, non-periodic
    parent = list(range(n + 1))
    off = [np.zeros(3, dtype=np.int64) for _ in range(n + 1)]

    def find(c: int) -> tuple[int, np.ndarray]:
        # iterative with path compression; returns (root, offset to root)
        path = []
        while parent[c] != c:
            path.append(c)
            c = parent[c]
        root = c
        # compress: accumulate offsets from the far end
        total = np.zeros(3, dtype=np.int64)
        for node in reversed(path):
            total = total + off[node]
            off[node] = total.copy()
            parent[node] = root
        # off[path[0]] now holds the full offset of the first node
        return root, (off[path[0]].copy() if path else np.zeros(3, dtype=np.int64))

    mismatches: list[np.ndarray] = []

    def union(a: int, b: int, t: np.ndarray) -> None:
        """pos(a) + t == pos(b) (a's copy translated by t touches b)."""
        ra, oa = find(a)
        rb, ob = find(b)
        if ra != rb:
            parent[ra] = rb
            off[ra] = ob - oa - t
        else:
            m = oa + t - ob
            if np.any(m != 0):
                mismatches.append(m)

    shape = mask.shape
    for axis in range(3):
        t = np.zeros(3, dtype=np.int64)
        t[axis] = 1
        lo = np.take(comp, 0, axis=axis)              # face at index 0
        hi = np.take(comp, shape[axis] - 1, axis=axis)  # face at index n-1
        both = (lo > 0) & (hi > 0)
        if not both.any():
            continue
        pairs = {(int(b), int(a)) for a, b in zip(lo[both].ravel(), hi[both].ravel())}
        for b, a in sorted(pairs):
            # the voxel at index n-1 (component b) is adjacent to the voxel
            # at index 0 of the NEXT cell (component a translated by +t)
            union(a, b, t)
    rank, basis = lattice_basis(mismatches)
    return {"dimensionality": int(rank), "directions": basis,
            "n_components": int(n)}


# ------------------------------------------------------- inscribed sphere --

def _vdw_radius(el: str) -> float:
    from cctbx.eltbx import van_der_waals_radii
    try:
        return float(van_der_waals_radii.vdw.table[el.capitalize()])
    except (KeyError, RuntimeError):
        return 2.0


def distance_field(points_frac: np.ndarray, uc, atoms_frac: np.ndarray,
                   elements: list[str]) -> tuple[np.ndarray, np.ndarray]:
    """R(x) = min_a(|x - r_a| - r_vdW(a)) at every point of `points_frac`
    (fractional, any cell), against the P1 atoms expanded over the 27 cell
    images - one cKDTree per element, so each atom carries its own radius.

    NOT `scipy.ndimage.distance_transform_edt`: that measures in grid units
    on an orthogonal lattice (wrong in a triclinic cell) and cannot see
    per-atom radii. Do not "optimise" it back.

    Returns (R, nearest_el): float array (n,) in A - negative inside the vdW
    surface - and an object array (n,) of the element that set each minimum
    (None where there are no atoms, R = +inf there)."""
    from scipy.spatial import cKDTree

    pts = np.asarray(points_frac, dtype=float).reshape(-1, 3)
    best = np.full(len(pts), np.inf)
    best_el = np.empty(len(pts), dtype=object)
    if len(pts) == 0:
        return best, best_el
    ortho = np.array(uc.orthogonalization_matrix(), dtype=float).reshape(3, 3)
    cart = pts @ ortho.T

    af = np.asarray(atoms_frac, dtype=float).reshape(-1, 3) % 1.0
    els = [str(e).capitalize() for e in elements]
    shifts = np.array([[dx, dy, dz] for dx in (-1, 0, 1)
                       for dy in (-1, 0, 1) for dz in (-1, 0, 1)], dtype=float)
    for el in sorted(set(els)):
        sel = np.array([e == el for e in els])
        images = (af[sel][:, None, :] + shifts[None, :, :]).reshape(-1, 3)
        tree = cKDTree(images @ ortho.T)
        d, _ = tree.query(cart, k=1)
        free = d - _vdw_radius(el)
        better = free < best
        best[better] = free[better]
        best_el[better] = el
    return best, best_el


def _bin_keys(pts: np.ndarray, nb: int) -> np.ndarray:
    """Index of the regular nb x nb x nb fractional cell each point falls in."""
    ijk = np.clip((pts % 1.0 * nb).astype(np.int64), 0, nb - 1)
    return (ijk[:, 0] * nb + ijk[:, 1]) * nb + ijk[:, 2]


def _thin_isotropic(pts: np.ndarray, max_points: int) -> tuple[np.ndarray, int]:
    """(one representative per occupied bin, bins per axis) - a SPATIALLY
    uniform subsample.

    Not `pts[::k]`. The void's points arrive in `np.argwhere` order, which is
    lexicographic (x, then y, then z), so a list stride k thins only along
    the fastest axis: x and y stay fully sampled and z is cut to every k-th
    plane. On a big void that is an anisotropic sample whose argmax can sit
    far from the widest point - live case (2026-09, UiO-66): the octahedral
    cage measured 8.46 A on a 0.288 A mask grid and 8.22 A on the FINER
    0.144 A grid, because the finer grid needed a 26x list stride and the
    cage centre fell between two sampled z planes. A finer grid must never
    give a worse answer, so the thinning is a lattice, not a list.
    """
    n = len(pts)
    if n <= max_points:
        return np.arange(n), 0
    lo, hi = 2, 4096                       # binary search the bin count
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if len(np.unique(_bin_keys(pts, mid))) <= max_points:
            lo = mid
        else:
            hi = mid - 1
    _keys, first = np.unique(_bin_keys(pts, lo), return_index=True)
    return first, lo


def inscribed_sphere(points_frac: np.ndarray, uc, atoms_frac: np.ndarray,
                     elements: list[str],
                     max_points: int = MAX_SCAN_POINTS) -> dict[str, Any]:
    """Largest sphere free of the van der Waals surface, centred on one of
    `points_frac` (the void's grid points, fractional, any cell).

    Over `max_points` points the scan is thinned to one representative per
    cell of a regular fractional lattice (`_thin_isotropic`) and then
    REFINED, repeatedly, until the survivors fit the budget: R(x) =
    min_a(|x - r_a| - r_vdW(a)) is 1-Lipschitz in Cartesian space, so a bin
    of Cartesian diameter d hides at most d of extra radius, and the bin
    holding the true maximum is therefore always among those whose
    representative came within d of the best one. Keeping exactly those and
    re-thinning shrinks the pool every round while provably never dropping
    the answer. `exact` is True when the last round evaluated its whole
    pool - i.e. the number is the exact maximum over the points handed in,
    whose error is then the caller's grid step, with no stride correction.

    atoms_frac / elements: the P1 atoms (fractional). Returns
    {"centre_frac" wrapped into [0,1), "radius_A", "lcd_A" (= 2R),
     "n_scanned" (points actually evaluated), "n_points" (handed in),
     "bins_per_axis" (bins per axis of the FIRST thinning round; 0 = the
     scan fitted the budget whole), "n_refine_rounds", "exact" (False only
     when the round budget ran out on a maximum too flat for the bins to
     separate), "stride" (kept for older callers: always 1),
     "nearest_atom"}.
    """
    pts = np.asarray(points_frac, dtype=float)
    if pts.ndim != 2 or len(pts) == 0:
        return {"centre_frac": None, "radius_A": None, "lcd_A": None,
                "n_scanned": 0, "n_points": 0, "bins_per_axis": 0,
                "n_refine_rounds": 0, "exact": True, "stride": 1,
                "nearest_atom": None}
    ortho = np.array(uc.orthogonalization_matrix(), float).reshape(3, 3)
    signs = np.array([[1, 1, 1], [1, 1, -1], [1, -1, 1], [-1, 1, 1]], float)
    # exact Cartesian diameter of one bin: the longest of its four body
    # diagonals (columns of the orthogonalization matrix are a, b, c)
    diag = float(np.linalg.norm(signs @ ortho.T, axis=1).max())
    pool, n_scanned, exact = pts, 0, False
    nb_first, rounds = 0, 0
    for _round in range(MAX_REFINE_ROUNDS):
        keep, nb = _thin_isotropic(pool, max_points)
        scan = pool[keep]
        best, best_el = distance_field(scan, uc, atoms_frac, elements)
        n_scanned += len(scan)
        rounds += 1
        nb_first = nb_first or nb
        if nb == 0:                       # the pool fitted: this IS the max
            exact = True
            break
        top = float(best.max())
        live = np.unique(_bin_keys(scan[best >= top - diag / nb], nb))
        nxt = pool[np.isin(_bin_keys(pool, nb), live)]
        if len(nxt) >= len(pool):         # a flat maximum the bins cannot
            break                         # separate: report the best seen
        pool = nxt
    k = int(np.argmax(best))
    centre = scan[k] % 1.0
    r = float(best[k])
    return {"centre_frac": [round(float(x), 4) for x in centre],
            "radius_A": round(r, 3), "lcd_A": round(2.0 * r, 3),
            "n_scanned": int(n_scanned), "n_points": int(len(pts)),
            "bins_per_axis": int(nb_first), "n_refine_rounds": int(rounds),
            "exact": bool(exact), "stride": 1,
            "nearest_atom": str(best_el[k])}


def grid_step_A(uc, n_real) -> float:
    """Largest axis step of the mask grid, in A (the resolution of every
    grid-derived number here)."""
    a, b, c = uc.parameters()[:3]
    return round(max(a / n_real[0], b / n_real[1], c / n_real[2]), 3)


# -------------------------------------------------- pore-limiting diameter --

#: cap on the void voxels carried through the PLD bisection. Percolation
#: needs EVERY voxel of the void (a subsample would cut the connections
#: under test), so overflow is handled by coarsening the whole label grid
#: with an integer stride, which is reported and enlarges the error bar.
MAX_PLD_POINTS = 2_000_000

_PLD_METHOD = "网格渗流二分（Foster 2006 / Zeo++ Willems 2012 约定）"
_PLD_NOTE_0D = "孤立空腔无渗流路径，PLD 无定义"


def _int_dirs(directions) -> list[list[int]]:
    if directions is None:
        return []
    out = []
    for d in directions:
        v = [int(round(float(x))) for x in d]
        if any(v):
            out.append(v)
    return out


def _spans(basis: list, wanted: list[list[int]]) -> bool:
    """Is every `wanted` direction inside the linear span of `basis`?
    (The percolation lattice repeats along a multiple of the direction -
    the rational span is what "the void runs that way" means.)"""
    if not wanted:
        return True
    if not basis:
        return False
    b = np.array(basis, dtype=float)
    rank_b = int(np.linalg.matrix_rank(b))
    for d in wanted:
        if int(np.linalg.matrix_rank(np.vstack([b, np.array(d, float)]))) > rank_b:
            return False
    return True


def pore_limiting_diameter(labels: np.ndarray, value: int, uc,
                           atoms_frac: np.ndarray, elements: list[str], *,
                           directions=None,
                           max_points: int = MAX_PLD_POINTS,
                           rounds: int = 12) -> dict[str, Any]:
    """Pore-limiting diameter of the void whose flood-fill label is `value`:
    the free sphere that still gets all the way through.

    PLD = 2 rho*, rho* = sup{rho : {R >= rho} inside the void still
    percolates}, bisected in `rounds` steps over [min R, max R] of the void.
    "Percolates" = `void_topology` of the threshold set has dimensionality
    >= 1, i.e. it joins to its own periodic image; when `directions` is
    given (a list of [u, v, w]) the threshold set must additionally repeat
    along every one of them, which gives a directional PLD.

    The bisection is over ALL paths at once, so the answer can be much
    larger than the narrowest straight line through the cell: the sphere
    detours. rho* may come out negative if the only way through is inside
    the vdW surface - that is a reading, not an error.

    `max_points` caps the voxels evaluated; over it the WHOLE label grid is
    coarsened by an integer stride (labels[::s, ::s, ::s]) and the reported
    grid step / error grows with it. Returns
    {"pld_A" (None for a 0-D void, with "pld_note"), "pld_error_A" (= the
    grid step actually used), "pld_directions" (channel directions of the
    last percolating threshold), "n_rounds", "grid_step_A", "n_voxels"
    (void voxels actually evaluated, after coarsening), "stride",
    "dimensionality", "method"}."""
    lab = np.asarray(labels)
    shape = tuple(int(s) for s in lab.shape)

    def _out(step: float, n_vox: int, stride: int, **kw) -> dict[str, Any]:
        base: dict[str, Any] = {
            "pld_A": None, "pld_error_A": step, "pld_directions": [],
            "n_rounds": 0, "grid_step_A": step, "n_voxels": int(n_vox),
            "stride": int(stride), "dimensionality": 0,
            "method": _PLD_METHOD}
        base.update(kw)
        return base

    n_full = int((lab == value).sum())
    if n_full == 0:
        return _out(grid_step_A(uc, shape), 0, 1,
                    pld_note=f"网格上没有标签 {value} 的体素，PLD 无定义")

    stride = 1
    if n_full > max_points:
        stride = max(1, int(np.ceil((n_full / float(max_points)) ** (1.0 / 3.0))))
        cap = max(1, min(shape) // 2)          # keep >= 2 samples on each axis
        stride = min(stride, cap)
        while (stride < cap
               and int((lab[::stride, ::stride, ::stride] == value).sum())
               > max_points):
            stride += 1
    sub = lab[::stride, ::stride, ::stride]
    shape_c = tuple(int(s) for s in sub.shape)
    mask_c = sub == value
    n_vox = int(mask_c.sum())
    step = grid_step_A(uc, shape_c)
    if n_vox == 0:
        return _out(step, 0, stride,
                    pld_note=f"降采样（步长 {stride}）后该空隙不剩体素，"
                             "PLD 无定义")

    idx = np.argwhere(mask_c)
    frac = idx * float(stride) / np.array(shape, dtype=float)
    r_vals, _ = distance_field(frac, uc, atoms_frac, elements)
    if not np.isfinite(r_vals).all():          # no atoms -> R is +inf
        return _out(step, n_vox, stride,
                    pld_note="距离场没有有限值（原子表为空？），PLD 无定义")
    rgrid = np.full(shape_c, -np.inf, dtype=float)
    rgrid[mask_c] = r_vals
    want = _int_dirs(directions)

    def percolates(rho: float) -> tuple[bool, dict[str, Any]]:
        m = np.zeros(shape_c, dtype=np.int8)
        m[rgrid >= rho] = 1
        topo = void_topology(m, 1)
        return (int(topo["dimensionality"]) >= 1
                and _spans(topo["directions"], want)), topo

    lo = float(r_vals.min())
    hi = float(r_vals.max())
    ok, topo = percolates(lo)                  # the void itself
    if not ok:
        note = (_PLD_NOTE_0D if int(topo["dimensionality"]) == 0
                else f"该空隙不沿指定方向 {want} 渗流，PLD 无定义")
        return _out(step, n_vox, stride, pld_note=note,
                    pld_directions=topo["directions"],
                    dimensionality=int(topo["dimensionality"]))

    best = topo
    n_rounds = 0
    ok_hi, topo_hi = percolates(hi)
    if ok_hi:                                  # uniform R over the void
        lo, best = hi, topo_hi
    else:
        for _ in range(int(rounds)):
            mid = 0.5 * (lo + hi)
            ok, topo = percolates(mid)
            n_rounds += 1
            if ok:
                lo, best = mid, topo
            else:
                hi = mid
    return {"pld_A": round(2.0 * lo, 3), "pld_error_A": step,
            "pld_directions": best["directions"], "n_rounds": n_rounds,
            "grid_step_A": step, "n_voxels": n_vox, "stride": int(stride),
            "dimensionality": int(best["dimensionality"]),
            "method": _PLD_METHOD}


# ------------------------------------------------------- packing numbers --

_PACKING_NOTE = (
    "本值不是 100 − 溶剂可及体积%："
    "探针滚不进的尖角空间可占晶胞体积约 30%，而溶剂可及体积仍为零"
    "（知识库 §5.7），两者必须分开读、不互为补数。"
    "packing_index_pct 按 P1 原子 vdW 球的并集体积计（网格计数，"
    "相交处只计一次，误差随网格步长，见 packing_index_error_pct）；"
    "vdw_sum_pct 是球体积直接求和、未做重叠修正的值"
    "（成键原子的球相交处被重复计入，系统性偏高，只作对照）。"
    "占有率 < 1 的原子：求和按占有率加权，并集按全占计入。")

_PACKING_READING = (
    "≈18 Å³/非氢原子为致密有机晶体的典型值（知识库 §12.4）；"
    "明显偏大提示孔隙或缺客体，明显偏小提示原子数偏多。"
    "Kitaigorodskii 堆积指数的典型值约 65%（PLATON）。"
    "以上只作解读，不作判词。")

_PACKING_METHOD = (
    "Kitaigorodskii 堆积指数 = V(∪ vdW 球) / V_cell ×100，并集体积在晶胞"
    "网格上按 min_a(|x−r_a|−r_vdW(a)) < 0 计数（27 胞展开的 KD 树），"
    "r_vdW 取 cctbx.eltbx.van_der_waals_radii（缺表元素回退 2.0 Å）；"
    "vdw_sum_pct = Σ occ·(4/3)πr_vdW³ / V_cell ×100；"
    "Å³/非氢原子 = V_cell / Σ occ(非氢, P1)")

#: cap on the cell-grid points used for the vdW-envelope volume; the step
#: grows (and is reported) when the cell needs more
MAX_PACKING_POINTS = 400_000


def _vdw_union(uc, atoms_frac: np.ndarray, elements: list[str],
               max_points: int) -> dict[str, Any]:
    """Volume of the union of the vdW spheres, as the fraction of a regular
    cell grid that lies inside ANY sphere (R < 0 in `distance_field`).

    Error estimate: the same count on a grid twice as coarse; the
    difference between the two (Richardson-style) is what the grid still
    moves the number by. A bound from the summed sphere surface would be
    an order of magnitude looser on a dense cell and say nothing."""
    a, b, c = (float(x) for x in uc.parameters()[:3])
    v_cell = float(uc.volume())
    step = max((v_cell / max_points) ** (1.0 / 3.0), 0.2)
    n = [max(4, int(np.ceil(L / step))) for L in (a, b, c)]

    def count(nn):
        ix, iy, iz = np.indices(nn)
        pts = (np.stack([ix, iy, iz], axis=-1).reshape(-1, 3)
               / np.array(nn, float))
        R, _el = distance_field(pts, uc, atoms_frac, elements)
        return float(np.count_nonzero(R < 0.0)) / float(len(pts)), len(pts)

    inside, n_pts = count(n)
    coarse, _n2 = count([max(2, k // 2) for k in n])
    eff_step = max(a / n[0], b / n[1], c / n[2])
    return {"fraction": inside, "grid_step_A": round(eff_step, 3),
            "n_points": int(n_pts),
            "error_pct": round(max(100.0 * abs(inside - coarse), 0.01), 3)}


def packing_index(uc, atoms_frac: np.ndarray,
                  elements: list[str],
                  occupancies=None,
                  max_points: int = MAX_PACKING_POINTS) -> dict[str, Any]:
    """Kitaigorodskii packing index and A^3 per non-hydrogen atom, from the
    P1 atom list. `packing_index_pct` is the volume of the UNION of the vdW
    spheres (grid-counted on the cell, overlaps once) - the coefficient
    PLATON / Kitaigorodskii mean, typically 0.65-0.77 for a dense molecular
    crystal; `vdw_sum_pct` is the raw sum of ball volumes (no overlap
    correction, systematically high - 96 % on a dense real structure) kept
    for reference.

    Returns {"packing_index_pct", "vdw_volume_A3", "cell_volume_A3",
    "n_atoms_p1", "n_non_h_atoms_p1", "volume_per_non_h_atom_A3",
    "reading", "note", "method"}. Every number is rounded to 3 dp; the two
    numbers are reported side by side and neither is a verdict.

    `occupancies` (cctbx semantics: 1.0 for a fully occupied site, the
    special-position factor is NOT in it) weight both the ball sum and the
    non-H count, so a two-component disorder is not counted twice."""
    els = [str(e).capitalize() for e in elements]
    n_atoms = len(np.asarray(atoms_frac, dtype=float).reshape(-1, 3))
    if n_atoms != len(els):
        raise ValueError(f"atoms_frac ({n_atoms}) and elements ({len(els)}) "
                         "must have the same length")
    if occupancies is None:
        occ = [1.0] * n_atoms
    else:
        occ = [float(o) for o in occupancies]
        if len(occ) != n_atoms:
            raise ValueError(f"occupancies ({len(occ)}) and elements "
                             f"({n_atoms}) must have the same length")
    v_cell = float(uc.volume())
    v_vdw = sum(o * 4.0 / 3.0 * np.pi * _vdw_radius(el) ** 3
                for el, o in zip(els, occ))
    union = (_vdw_union(uc, atoms_frac, els, max_points)
             if n_atoms and v_cell > 0 else None)
    # hydrogen (and its isotopes) counts in the ball sum but not in the
    # per-atom volume, which is defined on non-H atoms (knowledge 12.4)
    n_non_h = sum(o for el, o in zip(els, occ) if el not in ("H", "D", "T"))
    per_atom = round(v_cell / n_non_h, 3) if n_non_h else None
    return {"packing_index_pct": round(100.0 * union["fraction"], 3)
            if union else None,
            "packing_index_error_pct": union["error_pct"] if union else None,
            "packing_grid_step_A": union["grid_step_A"] if union else None,
            "packing_grid_points": union["n_points"] if union else 0,
            "vdw_union_volume_A3": round(union["fraction"] * v_cell, 3)
            if union else None,
            "vdw_sum_pct": round(100.0 * v_vdw / v_cell, 3)
            if v_cell > 0 else None,
            "vdw_volume_A3": round(float(v_vdw), 3),
            "cell_volume_A3": round(v_cell, 3),
            "n_atoms_p1": int(n_atoms),
            "n_non_h_atoms_p1": round(float(n_non_h), 3),
            "occupancy_weighted": occupancies is not None,
            "volume_per_non_h_atom_A3": per_atom,
            "reading": _PACKING_READING,
            "note": _PACKING_NOTE,
            "method": _PACKING_METHOD}
