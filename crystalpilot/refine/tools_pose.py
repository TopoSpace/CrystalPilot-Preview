"""Whole-fragment pose search and group-level acceptance (round-3 WP5).

The forensic Zr-MOF thread (2026-09-05) had no tool that places a WHOLE
guest: fit_fragment needs >= 3 anchor atoms of the fragment already in
the model, so the agent walked the peak table atom by atom and finally
found the oblique guest orientation with an ad-hoc shell script.

search_fragment_pose is that tool. A fragment (SMILES -> RDKit conformer
library, or an explicit template) is posed against the difference
density by rigid-body placement seeded from peak triplets (and, when a
region is given, random poses inside it), refined locally, snapped and
folded onto special positions, de-duplicated modulo symmetry, and every
candidate comes with per-atom evidence (direct_peak / weak_density /
geometry_only in units of the map rms), its clashes and the constraints
it satisfies. It changes nothing (candidates are cached beside the
node); accept_fragment_pose turns ONE candidate into a node in a single
step - shared FVAR occupancy, PART block, EADP card.

Every criterion is element-generic: covalent radii for bond ranges,
map sigma for evidence classes, symmetry from the space group. Nothing
here knows what a Zr, a Br or a phenyl ring is.
"""
from __future__ import annotations

import json
import math
import os
import tempfile
import time
from pathlib import Path
from typing import Any

import numpy as np

from ..tools.base import ToolContext, ToolResult
from ..tools.budget import Budget, BudgetStop, timeout_param
from .toolbase import _ProjectTool

POSE_CACHE_RELPATH = Path(".crystalpilot") / "refine" / "pose_candidates.json"
#: closer than this to an existing atom the pose overlaps it (rejected)
HARD_CLASH_A = 0.7
#: evidence classes in units of the difference-map rms
DIRECT_SIGMA = 3.0
WEAK_SIGMA = 1.0
#: two placed atoms closer than this modulo symmetry are one site
FOLD_A = 0.5
#: two candidates whose atoms all lie within this (modulo symmetry) are one
DUP_A = 0.4
#: snap to a special position when this close to it
SNAP_A = 0.25
#: tolerance added to the covalent-radius sum for a default bond range
BOND_TOL_A = 0.35
ANCHOR_KINDS = ("bond", "on_peak", "near_site")
EVIDENCE = ("direct_peak", "weak_density", "geometry_only")


# ==========================================================================
# geometry helpers (pure numpy)
# ==========================================================================
def kabsch(P: np.ndarray, Q: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
    """Rigid transform R, t with R @ p + t ~ q (least squares) and its rms."""
    P = np.asarray(P, float)
    Q = np.asarray(Q, float)
    Pm, Qm = P.mean(axis=0), Q.mean(axis=0)
    H = (P - Pm).T @ (Q - Qm)
    U, _, Vt = np.linalg.svd(H)
    d = np.sign(np.linalg.det(Vt.T @ U.T)) or 1.0
    R = Vt.T @ np.diag([1.0, 1.0, d]) @ U.T
    t = Qm - R @ Pm
    rms = float(np.sqrt((((P @ R.T) + t - Q) ** 2).sum(axis=1).mean()))
    return R, t, rms


def rotation_matrix(v) -> np.ndarray:
    """Rodrigues rotation for an axis-angle vector."""
    v = np.asarray(v, float)
    th = float(np.linalg.norm(v))
    if th < 1e-12:
        return np.eye(3)
    k = v / th
    K = np.array([[0.0, -k[2], k[1]], [k[2], 0.0, -k[0]], [-k[1], k[0], 0.0]])
    return np.eye(3) + math.sin(th) * K + (1.0 - math.cos(th)) * (K @ K)


def sym_min_distance(uc, ops, a_frac, b_frac) -> float:
    """Shortest distance between fractional a and any symmetry image of b."""
    best = float("inf")
    for op in ops:
        s = op * tuple(float(x) for x in b_frac)
        s = tuple(s[k] - round(s[k] - a_frac[k]) for k in range(3))
        best = min(best, float(uc.distance(tuple(float(x) for x in a_frac), s)))
    return best


def symmetry_field(xs) -> tuple[np.ndarray, np.ndarray]:
    """Cartesian positions of every atom over all symmetry operations and
    the 27 neighbouring cells, with the owning scatterer index (the clash
    field fit_fragment builds inline, shared here)."""
    uc = xs.unit_cell()
    ops = xs.space_group().all_ops()
    M = np.array(uc.orthogonalization_matrix()).reshape(3, 3)
    shifts = np.array([(dx, dy, dz) for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                       for dz in (-1, 0, 1)], float)
    pts: list[np.ndarray] = []
    owner: list[np.ndarray] = []
    for i, sc in enumerate(xs.scatterers()):
        for op in ops:
            s = np.array(op * sc.site, float)
            fr = s[None, :] + shifts
            pts.append(fr @ M.T)
            owner.append(np.full(len(shifts), i, dtype=int))
    if not pts:
        return np.zeros((0, 3)), np.zeros(0, dtype=int)
    return np.vstack(pts), np.concatenate(owner)


# ==========================================================================
# fragment templates
# ==========================================================================
def fragment_conformers(smiles: str, n_conformers: int = 8,
                        seed: int = 20260906) -> dict[str, Any]:
    """Heavy-atom conformer library for a SMILES (RDKit ETKDG + MMFF),
    near-duplicates pruned; one conformer when nothing rotates."""
    from .ligand import LigandError, _rdkit, ligand_graph
    rd = _rdkit()
    if not rd:
        raise LigandError("rdkit is not installed in this environment")
    Chem, AllChem, rdMD = rd
    g = ligand_graph(smiles)
    n_rot = int(rdMD.CalcNumRotatableBonds(g["_mol"]))
    mol = Chem.AddHs(g["_mol"])
    params = AllChem.ETKDGv3()
    params.randomSeed = int(seed)
    n = max(1, int(n_conformers)) if n_rot else 1
    cids = list(AllChem.EmbedMultipleConfs(mol, numConfs=n, params=params))
    if not cids:
        raise LigandError("3D embedding failed for this SMILES")
    try:
        AllChem.MMFFOptimizeMoleculeConfs(mol, maxIters=500)
    except Exception:  # noqa: BLE001 - the embedded geometry is still usable
        pass
    heavy = [a.GetIdx() for a in mol.GetAtoms() if a.GetAtomicNum() > 1]
    coords = [np.array(mol.GetConformer(c).GetPositions(), float)[heavy]
              for c in cids]
    kept: list[np.ndarray] = []
    rms_ref: list[float] = []
    for c in coords:
        if any(kabsch(c, k)[2] < 0.25 for k in kept):
            continue
        kept.append(c)
        rms_ref.append(round(kabsch(c, coords[0])[2], 3))
    return {"smiles": smiles, "elements": list(g["elements"]),
            "adjacency": g["adjacency"], "formula": g.get("formula"),
            "n_rotatable": n_rot, "conformers": kept,
            "rmsd_to_reference": rms_ref}


def explicit_template(template: dict[str, Any]) -> dict[str, Any]:
    """An explicit heavy-atom template: {"elements": [...], "coords":
    [[x,y,z], ...]} in angstrom (any consistent origin)."""
    els = [str(e).capitalize() for e in (template.get("elements") or [])]
    coords = np.array(template.get("coords") or [], float)
    if len(els) < 3 or coords.shape != (len(els), 3):
        raise ValueError("template needs >= 3 elements and matching coords")
    return {"smiles": None, "elements": els, "adjacency": None,
            "formula": None, "n_rotatable": 0, "conformers": [coords],
            "rmsd_to_reference": [0.0]}


# ==========================================================================
# anchors (element-generic constraints)
# ==========================================================================
def _default_bond_range(el_a: str, el_b: str) -> tuple[float, float]:
    from ..chem.connectivity import covalent_radius
    s = covalent_radius(el_a) + covalent_radius(el_b)
    return (max(0.5, s - BOND_TOL_A), s + BOND_TOL_A)


def resolve_anchors(anchors: list[dict[str, Any]] | None, xs, elements: list[str],
                    peaks_frac: list[tuple[float, float, float]],
                    field_pts: np.ndarray, field_owner: np.ndarray
                    ) -> tuple[list[dict[str, Any]], str | None]:
    """Turn the anchor specs into evaluable targets. Returns (anchors,
    error); every anchor gets `targets` (cartesian points its template
    atom is measured against) and a `range_A`."""
    from ..chem.knowledge import is_metal
    uc = xs.unit_cell()
    scs = list(xs.scatterers())
    out: list[dict[str, Any]] = []
    for n, a in enumerate(anchors or []):
        kind = str(a.get("kind") or "").lower()
        if kind not in ANCHOR_KINDS:
            return [], f"anchor {n}: kind must be one of {list(ANCHOR_KINDS)}"
        try:
            t = int(a.get("template_index"))
        except (TypeError, ValueError):
            return [], f"anchor {n}: template_index is required"
        if not 0 <= t < len(elements):
            return [], (f"anchor {n}: template_index {t} out of range "
                        f"(fragment has {len(elements)} heavy atoms)")
        item: dict[str, Any] = {"n": n, "kind": kind, "template_index": t,
                                "label": None}
        if kind == "bond":
            owners: list[int] = []
            if a.get("to_atom"):
                lbl = str(a["to_atom"]).strip().upper()
                owners = [i for i, sc in enumerate(scs)
                          if sc.label.strip().upper() == lbl]
                if not owners:
                    return [], f"anchor {n}: no atom {a['to_atom']!r} in the model"
                item["label"] = f"bond template[{t}] {elements[t]} - {scs[owners[0]].label}"
                partner_el = scs[owners[0]].scattering_type
            elif a.get("to_element"):
                want = str(a["to_element"]).strip()
                if want.lower() == "metal":
                    owners = [i for i, sc in enumerate(scs)
                              if is_metal(sc.scattering_type)]
                    if not owners:
                        return [], f"anchor {n}: the model has no metal atom"
                else:
                    owners = [i for i, sc in enumerate(scs)
                              if sc.scattering_type.strip().capitalize()
                              .rstrip("+-0123456789") == want.capitalize()]
                    if not owners:
                        return [], (f"anchor {n}: no atom of element {want} "
                                    f"in the model")
                item["label"] = f"bond template[{t}] {elements[t]} - {want}"
                partner_el = scs[owners[0]].scattering_type
            else:
                return [], f"anchor {n}: bond needs to_atom or to_element"
            rng = a.get("range_A")
            if rng:
                try:
                    lo, hi = float(rng[0]), float(rng[1])
                except (TypeError, ValueError, IndexError):
                    return [], f"anchor {n}: range_A must be [lo, hi]"
            else:
                lo, hi = _default_bond_range(
                    elements[t], str(partner_el).strip().rstrip("+-0123456789"))
            item["range_A"] = (lo, hi)
            mask = np.isin(field_owner, owners)
            item["targets"] = field_pts[mask]
        elif kind == "on_peak":
            try:
                k = int(a.get("peak_index"))
            except (TypeError, ValueError):
                return [], f"anchor {n}: on_peak needs peak_index"
            if not 0 <= k < len(peaks_frac):
                return [], (f"anchor {n}: peak_index {k} out of range "
                            f"({len(peaks_frac)} peaks)")
            tol = float(a.get("tolerance_A") or 0.6)
            item["range_A"] = (0.0, tol)
            item["label"] = f"template[{t}] {elements[t]} on peak {k}"
            item["targets"] = _images_cart(uc, xs.space_group().all_ops(),
                                           peaks_frac[k])
        else:  # near_site
            site = a.get("site")
            try:
                fr = tuple(float(x) for x in site)
                assert len(fr) == 3
            except Exception:  # noqa: BLE001
                return [], f"anchor {n}: near_site needs site=[x,y,z] (fractional)"
            tol = float(a.get("tolerance_A") or 0.6)
            item["range_A"] = (0.0, tol)
            item["label"] = f"template[{t}] {elements[t]} near {[round(x, 3) for x in fr]}"
            item["targets"] = _images_cart(uc, xs.space_group().all_ops(), fr)
        out.append(item)
    return out, None


def _images_cart(uc, ops, frac) -> np.ndarray:
    M = np.array(uc.orthogonalization_matrix()).reshape(3, 3)
    shifts = np.array([(dx, dy, dz) for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                       for dz in (-1, 0, 1)], float)
    rows = []
    for op in ops:
        s = np.array(op * tuple(float(x) for x in frac), float)
        rows.append((s[None, :] + shifts) @ M.T)
    return np.vstack(rows)


# ==========================================================================
# scoring
# ==========================================================================
class PoseScorer:
    """Difference density + clash field + anchors -> one score per pose.

    score = sum(rho_i / sigma) - clash_penalty - anchor_penalty; the map
    rms makes the density term scale- and resolution-free, the penalties
    are in angstrom-of-violation so a pose that half-overlaps an atom or
    misses its bond by an angstrom loses several sigma-atoms of credit."""

    def __init__(self, xs, real_map, sigma: float, field_pts: np.ndarray,
                 field_owner: np.ndarray, anchors: list[dict[str, Any]],
                 clash_d: float, peaks_frac: list[tuple[float, float, float]]):
        from scipy.spatial import cKDTree
        self.xs = xs
        self.uc = xs.unit_cell()
        self.real_map = real_map
        self.sigma = max(float(sigma), 1e-6)
        self.Minv = np.array(self.uc.fractionalization_matrix()).reshape(3, 3)
        self.field_pts = field_pts
        self.field_owner = field_owner
        self.tree = cKDTree(field_pts) if len(field_pts) else None
        self.anchors = anchors
        self.anchor_trees = [cKDTree(a["targets"]) if len(a["targets"]) else None
                             for a in anchors]
        self.clash_d = float(clash_d)
        self.labels = [sc.label for sc in xs.scatterers()]
        ops = xs.space_group().all_ops()
        self.peak_pts = (np.vstack([_images_cart(self.uc, ops, p) for p in peaks_frac])
                         if peaks_frac else np.zeros((0, 3)))
        self.peak_idx = (np.concatenate([np.full(len(ops) * 27, k) for k in range(len(peaks_frac))])
                         if peaks_frac else np.zeros(0, dtype=int))
        self.peak_tree = cKDTree(self.peak_pts) if len(self.peak_pts) else None

    def density(self, cart: np.ndarray) -> np.ndarray:
        from cctbx import maptbx
        frac = cart @ self.Minv.T
        return np.array([float(maptbx.eight_point_interpolation(
            self.real_map, [float(x % 1.0) for x in fr])) for fr in frac])

    def evaluate(self, cart: np.ndarray, full: bool = False,
                 with_anchors: bool = True) -> dict[str, Any]:
        """Score one pose. `cart` is the FULL template pose unless
        with_anchors=False (anchors index template atoms, so a folded
        subset must be scored without them)."""
        rho = self.density(cart)
        sig = rho / self.sigma
        if self.tree is not None:
            dmin, near = self.tree.query(cart)
        else:
            dmin = np.full(len(cart), np.inf)
            near = np.full(len(cart), -1)
        clash_pen = float(np.sum(np.clip(self.clash_d - dmin, 0.0, None)) / self.clash_d * 5.0)
        hard = bool(np.any(dmin < HARD_CLASH_A))
        anchor_pen = 0.0
        constraints: list[dict[str, Any]] = []
        for a, tree in zip(self.anchors if with_anchors else [],
                           self.anchor_trees if with_anchors else []):
            p = cart[a["template_index"]]
            if tree is None:
                d = float("inf")
            else:
                d = float(tree.query(p)[0])
            lo, hi = a["range_A"]
            viol = max(lo - d, d - hi, 0.0)
            anchor_pen += viol * 5.0
            if full:
                constraints.append({"anchor": a["n"], "label": a["label"],
                                    "d_A": round(d, 3) if math.isfinite(d) else None,
                                    "range_A": [round(lo, 3), round(hi, 3)],
                                    "satisfied": viol <= 1e-6})
        score = float(sig.sum() - clash_pen - anchor_pen)
        out = {"score": score, "rho": rho, "sigma": sig, "dmin": dmin,
               "near": near, "clash_penalty": clash_pen,
               "anchor_penalty": anchor_pen, "hard_clash": hard}
        if full:
            out["constraints"] = constraints
        return out

    def nearest_peak(self, p: np.ndarray) -> tuple[int | None, float | None]:
        if self.peak_tree is None:
            return None, None
        d, i = self.peak_tree.query(p)
        return int(self.peak_idx[int(i)]), float(d)


# ==========================================================================
# seeds
# ==========================================================================
def template_triples(tpl: np.ndarray, min_edge: float = 1.0,
                     min_area: float = 0.3) -> list[tuple[int, int, int]]:
    n = len(tpl)
    D = np.linalg.norm(tpl[:, None, :] - tpl[None, :, :], axis=-1)
    out = []
    for i in range(n):
        for j in range(i + 1, n):
            for k in range(j + 1, n):
                a, b, c = D[i, j], D[i, k], D[j, k]
                if min(a, b, c) < min_edge:
                    continue
                s = (a + b + c) / 2.0
                area2 = s * (s - a) * (s - b) * (s - c)
                if area2 <= min_area * min_area:
                    continue
                out.append((i, j, k))
    return out


def peak_triplet_seeds(tpl: np.ndarray, peaks_frac, peak_heights, uc, ops,
                       tol: float, max_seeds: int, budget: Budget | None
                       ) -> list[dict[str, Any]]:
    """Geometric hashing: every (template triple, peak triple) whose three
    distances agree within tol is a rigid-body seed. The first template
    atom of the triple sits on an asymmetric-unit peak; the other two are
    searched among the symmetry images of all peaks within the template
    diameter, so a fragment whose peaks straddle a symmetry element is
    seeded too."""
    n_p = len(peaks_frac)
    if n_p < 3 or len(tpl) < 3:
        return []
    D = np.linalg.norm(tpl[:, None, :] - tpl[None, :, :], axis=-1)
    diameter = float(D.max()) + tol
    triples = template_triples(tpl)
    M = np.array(uc.orthogonalization_matrix()).reshape(3, 3)
    shifts = np.array([(dx, dy, dz) for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                       for dz in (-1, 0, 1)], float)
    # fractional images of every peak under every op (n_p * n_ops, 3)
    img_frac = np.array([np.array(op * tuple(float(x) for x in p), float)
                         for p in peaks_frac for op in ops])
    img_idx = np.repeat(np.arange(n_p), len(ops))
    seeds: list[dict[str, Any]] = []
    for p in range(n_p):
        if budget is not None:
            budget.check("peak-triplet seeds")
        cp_frac = np.array(peaks_frac[p], float)
        cp = cp_frac @ M.T
        # bring every image next to p, then the 27 shifts
        near = img_frac - np.round(img_frac - cp_frac[None, :])
        allf = (near[:, None, :] + shifts[None, :, :]).reshape(-1, 3)
        allc = allf @ M.T
        alli = np.repeat(img_idx, len(shifts))
        dp = np.linalg.norm(allc - cp, axis=1)
        keep = (dp <= diameter) & (dp > 0.3)
        C, idx, dp = allc[keep], alli[keep], dp[keep]
        if len(C) < 2:
            continue
        for (i, j, k) in triples:
            cj = np.where(np.abs(dp - D[i, j]) < tol)[0]
            if not len(cj):
                continue
            ck = np.where(np.abs(dp - D[i, k]) < tol)[0]
            if not len(ck):
                continue
            for jj in cj:
                djk = np.linalg.norm(C[ck] - C[jj], axis=1)
                for kk in ck[np.abs(djk - D[j, k]) < tol]:
                    if kk == jj:
                        continue
                    seeds.append({
                        "template_triple": (i, j, k),
                        "points": np.array([cp, C[jj], C[kk]]),
                        "peaks": (p, int(idx[jj]), int(idx[kk])),
                        "priority": float(peak_heights[p] + peak_heights[idx[jj]]
                                          + peak_heights[idx[kk]])})
    seeds.sort(key=lambda s: -s["priority"])
    return seeds[:max_seeds]


def random_region_seeds(tpl: np.ndarray, uc, center_frac, radius_A: float,
                        n: int, seed: int) -> list[dict[str, Any]]:
    """Rigid-body seeds spread over a sphere: the whole-fragment search when
    the density is too weak or too continuous to give three peaks."""
    rng = np.random.default_rng(int(seed))
    c = np.array(uc.orthogonalize(tuple(float(x) for x in center_frac)), float)
    out = []
    for _ in range(int(n)):
        axis = rng.normal(size=3)
        axis /= max(np.linalg.norm(axis), 1e-9)
        R = rotation_matrix(axis * rng.uniform(0.0, math.pi))
        u = rng.normal(size=3)
        u /= max(np.linalg.norm(u), 1e-9)
        t = c + u * radius_A * rng.uniform(0.0, 1.0) ** (1.0 / 3.0)
        out.append({"template_triple": None, "R": R, "t": t, "peaks": None,
                    "priority": 0.0})
    return out


# ==========================================================================
# refinement, folding, de-duplication
# ==========================================================================
def refine_pose(scorer: PoseScorer, tpl0: np.ndarray, R: np.ndarray,
                t: np.ndarray, max_iter: int = 400) -> tuple[np.ndarray, np.ndarray, float]:
    """Nelder-Mead over (rotation vector about the centroid, translation)."""
    from scipy.optimize import minimize
    base = tpl0 @ R.T

    def f(x):
        cart = base @ rotation_matrix(x[:3]).T + t + x[3:]
        return -scorer.evaluate(cart)["score"]

    res = minimize(f, np.zeros(6), method="Nelder-Mead",
                   options={"maxiter": int(max_iter), "xatol": 0.005,
                            "fatol": 0.005, "initial_simplex": _simplex()})
    x = res.x
    return rotation_matrix(x[:3]) @ R, t + x[3:], float(-res.fun)


def _simplex() -> np.ndarray:
    s = np.zeros((7, 6))
    for i in range(3):
        s[i + 1, i] = 0.15          # ~9 degrees
        s[i + 4, i + 3] = 0.3       # angstrom
    return s


def fold_by_symmetry(xs, cart: np.ndarray) -> dict[str, Any]:
    """Snap atoms onto special positions they are within SNAP_A of, then
    drop every placed atom that is a symmetry image of an earlier one
    (a fragment straddling a symmetry element is described by its unique
    atoms only - listing both halves would double the density)."""
    uc = xs.unit_cell()
    ops = xs.space_group().all_ops()
    sps = xs.crystal_symmetry().special_position_settings(
        min_distance_sym_equiv=0.5)
    fracs = [tuple(float(x) for x in uc.fractionalize(tuple(float(y) for y in c)))
             for c in cart]
    on_special: list[int] = []
    for i, fr in enumerate(fracs):
        ss = sps.site_symmetry(fr)
        if ss.is_point_group_1():
            continue
        ex = tuple(float(x) for x in ss.exact_site())
        if uc.distance(fr, ex) < SNAP_A:
            fracs[i] = ex
            on_special.append(i)
    keep: list[int] = []
    folded: list[dict[str, Any]] = []
    for i in range(len(fracs)):
        onto = None
        for j in keep:
            d = sym_min_distance(uc, ops, fracs[j], fracs[i])
            if d < FOLD_A:
                onto = (j, d)
                break
        if onto is None:
            keep.append(i)
        else:
            folded.append({"template_index": i, "onto": onto[0],
                           "d_A": round(onto[1], 2)})
    return {"fracs": fracs, "keep": keep, "folded": folded,
            "on_special": on_special}


def same_pose(uc, ops, a_sites: list[tuple], a_els: list[str],
              b_sites: list[tuple], b_els: list[str]) -> bool:
    if len(a_sites) != len(b_sites):
        return False
    for fa, ea in zip(a_sites, a_els):
        best = min((sym_min_distance(uc, ops, fa, fb) for fb, eb in zip(b_sites, b_els)
                    if eb == ea), default=float("inf"))
        if best > DUP_A:
            return False
    return True


def evidence_class(sigma_level: float) -> str:
    if sigma_level >= DIRECT_SIGMA:
        return "direct_peak"
    if sigma_level >= WEAK_SIGMA:
        return "weak_density"
    return "geometry_only"


# ==========================================================================
# cache
# ==========================================================================
def cache_path(project_dir) -> Path:
    return Path(project_dir) / POSE_CACHE_RELPATH


def write_cache(project_dir, payload: dict[str, Any]) -> Path:
    p = cache_path(project_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".pose_candidates.", suffix=".tmp",
                               dir=str(p.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=1, ensure_ascii=False, default=str)
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return p


def read_cache(project_dir) -> dict[str, Any] | None:
    try:
        raw = json.loads(cache_path(project_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


# ==========================================================================
# the search tool
# ==========================================================================
_ANCHOR_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "kind": {"type": "string", "enum": list(ANCHOR_KINDS)},
            "template_index": {"type": "integer",
                               "description": "heavy-atom index in the fragment "
                                              "(SMILES atom order without H)"},
            "to_atom": {"type": "string",
                        "description": "bond: model atom label the template atom "
                                       "must be bonded to"},
            "to_element": {"type": "string",
                           "description": "bond: element symbol, or 'metal' for "
                                          "any metal atom of the model"},
            "range_A": {"type": "array", "items": {"type": "number"},
                        "description": "bond: [lo, hi] distance in angstrom "
                                       "(default: covalent-radius sum +/- 0.35)"},
            "peak_index": {"type": "integer",
                           "description": "on_peak: row of the difference-map "
                                          "peak table (inspect_map / refine)"},
            "site": {"type": "array", "items": {"type": "number"},
                     "description": "near_site: fractional x,y,z"},
            "tolerance_A": {"type": "number",
                            "description": "on_peak / near_site: allowed distance "
                                           "(default 0.6)"},
        },
        "required": ["kind", "template_index"],
    },
    "description": ("constraints a pose must satisfy, element-generic: a "
                    "template atom bonded to a model atom / element / any "
                    "metal within a distance range, sitting on a peak, or "
                    "near a site. Violations are penalised in the score and "
                    "reported per candidate (constraints_satisfied)"),
}


class SearchFragmentPose(_ProjectTool):
    name = "search_fragment_pose"
    description = (
        "Read-only whole-fragment pose search against the difference "
        "density: pose a fragment (SMILES -> conformer library, or an "
        "explicit template) by rigid-body placement seeded from peak "
        "triplets (and random poses inside a region), refine each pose "
        "locally, snap and fold onto special positions, de-duplicate modulo "
        "symmetry, and rank by density in map-sigma units minus clash and "
        "anchor penalties. Every candidate carries per-atom evidence "
        "(direct_peak >= 3 sigma / weak_density >= 1 sigma / geometry_only), "
        "clashes, the constraints it satisfies and an id; nothing is "
        "changed. Use it where fit_fragment cannot start (no anchor atoms in "
        "the model yet - a guest, a counter-ion, a solvent molecule): then "
        "accept_fragment_pose(candidate_id) to make ONE candidate a node "
        "with shared occupancy / PART / EADP in one step, and refine. A "
        "geometry_only atom is a claim the map does not support at this "
        "occupancy; say so or leave it out.")
    params_schema = {
        "type": "object",
        "properties": {
            "smiles": {"type": "string",
                       "description": "fragment SMILES (default: first prior ligand)"},
            "template": {"type": "object",
                         "properties": {"elements": {"type": "array", "items": {"type": "string"}},
                                        "coords": {"type": "array"}},
                         "description": "explicit heavy-atom template instead of "
                                        "smiles: elements + cartesian coords (A)"},
            "anchors": _ANCHOR_SCHEMA,
            "region": {"type": "object",
                       "properties": {"center": {"type": "array", "items": {"type": "number"}},
                                      "radius_A": {"type": "number"}},
                       "description": "fractional centre + radius: adds random "
                                      "rigid-body seeds inside the sphere (for "
                                      "density too weak to give three peaks)"},
            "use_peaks": {"type": "boolean", "default": True,
                          "description": "seed from difference-map peak triplets"},
            "recompute_peaks": {"type": "boolean", "default": False,
                                "description": "recompute the peak table from the "
                                               "current model instead of using the "
                                               "session's (last refine / SHELXL)"},
            "n_peaks": {"type": "integer", "default": 60, "minimum": 3, "maximum": 200},
            "peak_tolerance_A": {"type": "number", "default": 0.35,
                                 "minimum": 0.1, "maximum": 1.0,
                                 "description": "distance agreement for a peak "
                                                "triplet to seed a pose"},
            "n_conformers": {"type": "integer", "default": 8, "minimum": 1, "maximum": 48},
            "n_random_seeds": {"type": "integer", "default": 300, "minimum": 0, "maximum": 5000},
            "n_refine": {"type": "integer", "default": 40, "minimum": 1, "maximum": 400,
                         "description": "best seeds refined locally"},
            "max_candidates": {"type": "integer", "default": 10, "minimum": 1, "maximum": 50},
            "max_seeds": {"type": "integer", "default": 4000, "minimum": 10, "maximum": 100000},
            "clash_distance": {"type": "number", "default": 1.0, "minimum": 0.5, "maximum": 2.5},
            "occupancy_hypothesis": {"type": "number", "default": 1.0,
                                     "minimum": 0.01, "maximum": 1.0,
                                     "description": "the occupancy this fragment is "
                                                    "claimed at; recorded with the "
                                                    "candidates, not measured here"},
            "timeout_s": timeout_param("search_fragment_pose",
                                       "the candidates found so far are "
                                       "returned and marked partial"),
        },
    }

    def run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        from cctbx.array_family import flex

        from ..tools.refinement_tools import (_difference_map_analysis,
                                              difference_map_real)
        from .ligand import LigandError
        from .tools_extra import _resolve_smiles

        ses = ctx.session or self.project.session
        if ses is None or ses.model is None:
            return ToolResult.failure("no model in session")
        if ses.fo_sq is None:
            return ToolResult.failure("no merged data in session")
        xs = ses.model
        uc = xs.unit_cell()
        ops = xs.space_group().all_ops()

        # -- fragment ---------------------------------------------------
        try:
            if params.get("template"):
                frag = explicit_template(params["template"])
            else:
                smi = _resolve_smiles(self.project, params)
                if not smi:
                    return ToolResult.failure(
                        "no SMILES given and none in priors (pass smiles= or "
                        "template=)")
                frag = fragment_conformers(smi, int(params.get("n_conformers", 8)))
        except (LigandError, ValueError) as e:
            return ToolResult.failure(str(e))
        elements = frag["elements"]
        n_atoms = len(elements)
        if n_atoms < 3:
            return ToolResult.failure("the fragment needs at least 3 heavy atoms")

        # -- map + peaks -------------------------------------------------
        try:
            _fft, real_map, k_scale = difference_map_real(
                ses, xs, f_mask=ses.flags.get("f_mask"))
        except ValueError as e:
            return ToolResult.failure(f"difference map failed: {e}")
        sigma = float(math.sqrt(flex.mean_sq(real_map.as_1d())))
        peak_rows = None if params.get("recompute_peaks") else ses.flags.get("diff_map_peaks")
        peak_source = "session peak table (last refine / SHELXL)"
        if not peak_rows:
            ana = _difference_map_analysis(ses, xs, n_peaks=int(params.get("n_peaks", 60)),
                                           f_mask=ses.flags.get("f_mask"))
            peak_rows = ana.get("peaks") or []
            peak_source = "recomputed from the current model"
        peak_rows = list(peak_rows)[:int(params.get("n_peaks", 60))]
        peaks_frac = [tuple(float(x) for x in r["site"]) for r in peak_rows]
        peak_heights = [float(r.get("height") or 0.0) for r in peak_rows]

        # -- neighbours, anchors, scorer ----------------------------------
        field_pts, field_owner = symmetry_field(xs)
        anchors, err = resolve_anchors(params.get("anchors"), xs, elements,
                                       peaks_frac, field_pts, field_owner)
        if err:
            return ToolResult.failure(err)
        clash_d = float(params.get("clash_distance", 1.0))
        if not 0.5 <= clash_d <= 2.5:
            return ToolResult.failure("clash_distance must be within 0.5..2.5 A")
        scorer = PoseScorer(xs, real_map, sigma, field_pts, field_owner,
                            anchors, clash_d, peaks_frac)

        budget = Budget.for_tool(ctx, self.name, params)
        partial: str | None = None
        rejected: dict[str, dict[str, Any]] = {}

        def reject(reason: str, example: dict[str, Any] | None = None) -> None:
            slot = rejected.setdefault(reason, {"reason": reason, "n": 0})
            slot["n"] += 1
            if example and "example" not in slot:
                slot["example"] = example

        tol = float(params.get("peak_tolerance_A", 0.35))
        n_refine = int(params.get("n_refine", 40))
        max_seeds = int(params.get("max_seeds", 4000))
        conformers = frag["conformers"]
        scored: list[dict[str, Any]] = []
        refined: list[dict[str, Any]] = []
        n_seeds = 0
        with budget.install(ctx):
            try:
                for ci, conf in enumerate(conformers):
                    tpl0 = conf - conf.mean(axis=0)
                    seeds: list[dict[str, Any]] = []
                    if params.get("use_peaks", True):
                        seeds += peak_triplet_seeds(tpl0, peaks_frac, peak_heights,
                                                    uc, ops, tol, max_seeds, budget)
                    region = params.get("region")
                    if region and region.get("center"):
                        seeds += random_region_seeds(
                            tpl0, uc, region["center"],
                            float(region.get("radius_A") or 2.0),
                            int(params.get("n_random_seeds", 300)), 20260906 + ci)
                    n_seeds += len(seeds)
                    for si, s in enumerate(seeds):
                        if si % 200 == 0:
                            budget.check(f"conformer {ci + 1}/{len(conformers)}: "
                                         f"seed {si}/{len(seeds)}")
                        if s.get("R") is not None:
                            R, t = s["R"], s["t"]
                        else:
                            i, j, k = s["template_triple"]
                            R, t, rms = kabsch(tpl0[[i, j, k]], s["points"])
                            if rms > tol:
                                reject("peak triplet does not fit the template "
                                       "triangle (chirality or distance mismatch)")
                                continue
                        cart = tpl0 @ R.T + t
                        ev = scorer.evaluate(cart)
                        scored.append({"score": ev["score"], "R": R, "t": t,
                                       "conformer": ci, "seed": s, "hard": ev["hard_clash"]})
                # local refinement of the best seeds
                scored.sort(key=lambda r: -r["score"])
                best = scored[:n_refine]
                for ri, r in enumerate(best):
                    budget.check(f"refining pose {ri + 1}/{len(best)}")
                    tpl0 = conformers[r["conformer"]] - conformers[r["conformer"]].mean(axis=0)
                    R2, t2, sc = refine_pose(scorer, tpl0, r["R"], r["t"])
                    refined.append({**r, "R": R2, "t": t2, "score": sc})
            except BudgetStop as stop:
                partial = (f"stopped after {stop.elapsed_s:.0f} s at "
                           f"'{stop.stage}' - the candidates below are the poses "
                           f"refined so far")

        # -- finalise: fold, evaluate, de-duplicate, rank ----------------
        candidates: list[dict[str, Any]] = []
        for r in refined:
            conf = conformers[r["conformer"]]
            tpl0 = conf - conf.mean(axis=0)
            cart = tpl0 @ r["R"].T + r["t"]
            fold = fold_by_symmetry(xs, cart)
            keep = fold["keep"]
            M = np.array(uc.orthogonalization_matrix()).reshape(3, 3)
            cart_kept = np.array([np.array(fold["fracs"][i]) @ M.T for i in keep])
            # density and clashes on the UNIQUE atoms (a folded pose must not
            # be credited twice); anchors index template atoms, so the
            # constraint check runs on the full pose
            ev = scorer.evaluate(cart_kept, full=True, with_anchors=False)
            ev_full = scorer.evaluate(cart, full=True)
            score = float(ev["sigma"].sum() - ev["clash_penalty"]
                          - ev_full["anchor_penalty"])
            if ev["hard_clash"]:
                worst = int(np.argmin(ev["dmin"]))
                reject(f"overlaps an existing atom (< {HARD_CLASH_A} A)",
                       {"atom": scorer.labels[int(scorer.field_owner[ev["near"][worst]])],
                        "d_A": round(float(ev["dmin"][worst]), 2),
                        "template_index": keep[worst]})
                continue
            sites = [fold["fracs"][i] for i in keep]
            els = [elements[i] for i in keep]
            if any(same_pose(uc, ops, sites, els, c["_sites"], c["_els"])
                   for c in candidates):
                continue
            per_atom = []
            for n, i in enumerate(keep):
                sig = float(ev["sigma"][n])
                pk, pd = scorer.nearest_peak(cart_kept[n])
                near_i = int(ev["near"][n]) if len(scorer.field_owner) else -1
                per_atom.append({
                    "template_index": i, "element": elements[i],
                    "site_frac": [round(float(x), 5) for x in sites[n]],
                    "density_e_A3": round(float(ev["rho"][n]), 3),
                    "sigma_level": round(sig, 2),
                    "evidence": evidence_class(sig),
                    "nearest_peak": ({"index": pk, "d_A": round(pd, 2)}
                                     if pk is not None else None),
                    "nearest_atom": ({"label": scorer.labels[int(scorer.field_owner[near_i])],
                                      "d_A": round(float(ev["dmin"][n]), 2)}
                                     if near_i >= 0 else None),
                    "on_special_position": i in fold["on_special"],
                })
            counts = {c: sum(1 for a in per_atom if a["evidence"] == c) for c in EVIDENCE}
            clashes = [{"template_index": keep[n], "element": elements[keep[n]],
                        "atom": scorer.labels[int(scorer.field_owner[int(ev["near"][n])])],
                        "d_A": round(float(ev["dmin"][n]), 2)}
                       for n in range(len(keep))
                       if float(ev["dmin"][n]) < clash_d and len(scorer.field_owner)]
            seed = r["seed"]
            candidates.append({
                "id": None,
                "score": round(score, 2),
                "score_terms": {
                    "density_sigma_sum": round(float(ev["sigma"].sum()), 2),
                    "density_sum_e_A3": round(float(ev["rho"].sum()), 3),
                    "mean_density_e_A3": round(float(ev["rho"].mean()), 3),
                    "mean_sigma_level": round(float(ev["sigma"].mean()), 2),
                    "clash_penalty": round(float(ev["clash_penalty"]), 2),
                    "anchor_penalty": round(float(ev_full["anchor_penalty"]), 2)},
                "n_direct": counts["direct_peak"], "n_weak": counts["weak_density"],
                "n_geometry_only": counts["geometry_only"],
                "per_atom": per_atom,
                "clashes": clashes,
                "constraints_satisfied": ev_full.get("constraints", []),
                "on_special_position": bool(fold["on_special"]),
                "symmetry_folded": ({"n_placed": n_atoms, "n_unique": len(keep),
                                     "folded": fold["folded"]}
                                    if fold["folded"] else None),
                "conformer": {"index": r["conformer"],
                              "rmsd_to_reference_A": frag["rmsd_to_reference"][r["conformer"]]},
                "occupancy_hypothesis": float(params.get("occupancy_hypothesis", 1.0)),
                "seed": ({"template_triple": list(seed["template_triple"]),
                          "peaks": list(seed["peaks"])}
                         if seed.get("template_triple") is not None
                         else {"region": "random pose"}),
                "_sites": sites, "_els": els,
            })
        # round-3 R4 (Zr-MOF rerun, Br-anchored search): a pose that
        # violates a user-declared anchor ranked first on density alone.
        # An anchor is a stated fact about the crystal; poses that honour
        # every anchor rank above those that do not, score second.
        candidates.sort(key=lambda c: (
            0 if all(a.get("satisfied") for a in c.get("constraints_satisfied") or []) else 1,
            -c["score"]))
        max_c = int(params.get("max_candidates", 10))
        candidates = candidates[:max_c]
        for n, c in enumerate(candidates, start=1):
            c["id"] = f"c{n:02d}"
        rejected_rows = sorted(rejected.values(), key=lambda r: -r["n"])

        # -- verdict ---------------------------------------------------------
        applicability: list[str] = [f"peaks: {len(peaks_frac)} from {peak_source}"]
        if not anchors:
            applicability.append("no anchors given: poses are ranked by density "
                                 "and clashes alone")
        if frag["n_rotatable"]:
            applicability.append(f"{frag['n_rotatable']} rotatable bond(s): "
                                 f"{len(conformers)} conformers searched")
        if candidates:
            top = candidates[0]
            if top["n_geometry_only"] == 0 and top["n_direct"] * 2 >= len(top["per_atom"]):
                verdict = "supports"
                reasons = [f"top pose: {top['n_direct']} atom(s) on direct peaks, "
                           f"{top['n_weak']} on weak density, none unsupported"]
            else:
                verdict = "inconclusive"
                reasons = [f"top pose: {top['n_direct']} direct / {top['n_weak']} weak / "
                           f"{top['n_geometry_only']} geometry-only atom(s) - the map "
                           f"does not carry the whole fragment at this occupancy"]
            if not all(c["satisfied"] for c in top["constraints_satisfied"]):
                verdict = "inconclusive"
                reasons.append("the top pose violates an anchor")
        elif refined:
            verdict = "against"
            reasons = ["no pose survived: every refined pose overlapped an "
                       "existing atom (see rejected) - the fragment does not fit "
                       "where the density is"]
        elif n_seeds:
            verdict = "inconclusive"
            reasons = ["every seed was rejected before refinement (see rejected)"]
        else:
            verdict = "inconclusive"
            reasons = ["no seed: fewer than three peaks match the fragment's "
                       "distances - give a region= or check the peak table"]
        summary: dict[str, Any] = {
            "fragment": {"smiles": frag["smiles"], "formula": frag["formula"],
                         "n_heavy": n_atoms, "elements": elements,
                         "n_rotatable": frag["n_rotatable"],
                         "n_conformers": len(conformers)},
            "map": {"kind": "Fo-Fc" + (" (mask-aware)" if ses.flags.get("f_mask") is not None else ""),
                    "sigma_e_A3": round(sigma, 4), "scale_k": round(float(k_scale), 4),
                    "evidence_classes": {"direct_peak": f">= {DIRECT_SIGMA:g} sigma",
                                         "weak_density": f">= {WEAK_SIGMA:g} sigma",
                                         "geometry_only": f"< {WEAK_SIGMA:g} sigma"}},
            "peaks_used": len(peaks_frac),
            "n_seeds": n_seeds, "n_refined": len(refined),
            "candidates": [{k: v for k, v in c.items() if not k.startswith("_")}
                           for c in candidates],
            "rejected": rejected_rows,
            "scientific_outcome": {"verdict": verdict, "reasons": reasons,
                                   "measured_by": "difference density at the posed "
                                                  "atoms in map-sigma units, clash "
                                                  "field, anchor distances"},
            "applicability": applicability,
            "budget": budget.report(),
            "next": ("accept_fragment_pose(candidate_id=...) makes one candidate a "
                     "node (occupancy / PART / EADP in one step); refine and "
                     "audit_guest_evidence afterwards"),
        }
        if partial:
            summary["timeout"] = partial
        # cache for accept_fragment_pose (read-only tool: a derived file)
        if self.project is not None and candidates:
            st = self.project.nodes.state()
            payload = {"node": st.get("active_node"), "revision": st.get("seq"),
                       "created": time.time(), "fragment": summary["fragment"],
                       "map_sigma": sigma,
                       "candidates": [{**{k: v for k, v in c.items() if not k.startswith("_")},
                                       "sites": [list(s) for s in c["_sites"]],
                                       "elements": c["_els"]}
                                      for c in candidates]}
            try:
                summary["cache"] = str(write_cache(self.project.dir, payload))
            except OSError as e:
                summary["cache_error"] = str(e)
        return ToolResult(ok=True, summary=summary)


# ==========================================================================
# the accept tool
# ==========================================================================
def _free_label(existing: set[str], element: str) -> str:
    """Next free SHELX label (<= 4 chars) for an element: EL1, EL2, ...;
    a two-letter element past 99 falls back to its first letter."""
    el = element.upper()[:2]
    for stem in (el, el[0]):
        for n in range(1, 1000):
            lbl = f"{stem}{n}"
            if len(lbl) <= 4 and lbl not in existing:
                existing.add(lbl)
                return lbl
    raise ValueError(f"no free label for element {element}")


class AcceptFragmentPose(_ProjectTool):
    name = "accept_fragment_pose"
    description = (
        "Turn ONE search_fragment_pose candidate into the working model in a "
        "single step: its unique atoms are added at the posed sites with the "
        "given occupancy (shared through one free variable when < 1, so "
        "refine / SHELXL move the whole fragment together), an optional PART "
        "block, and an optional EADP card (equal ADPs across the fragment, "
        "carried as effective model state). The candidates must come from "
        "the current node (re-run the search after any model change). "
        "Refine afterwards and read audit_guest_evidence before believing "
        "the fragment; delete with edit_atoms if the data disown it (the "
        "free variable, PART and card go with the atoms).")
    params_schema = {
        "type": "object",
        "properties": {
            "candidate_id": {"type": "string",
                             "description": "id from search_fragment_pose (c01 ...)"},
            "occupancy": {"type": "number", "minimum": 0.01, "maximum": 1.0,
                          "description": "site occupancy for every atom "
                                         "(default: the candidate's occupancy "
                                         "hypothesis)"},
            "shared_occupancy": {"type": "boolean", "default": True,
                                 "description": "occupancy < 1 refines as ONE "
                                                "free variable for the whole "
                                                "fragment (SHELXL FVAR)"},
            "part": {"type": "integer",
                     "description": "SHELX PART number for the fragment (omit "
                                    "for none; negative = no bonds to symmetry "
                                    "equivalents)"},
            "eadp": {"type": "boolean", "default": False,
                     "description": "constrain all fragment ADPs equal (EADP "
                                    "card, effective model state)"},
            "u_iso": {"type": "number", "default": 0.05, "minimum": 0.005, "maximum": 0.5,
                      "description": "starting Uiso for the placed atoms"},
        },
        "required": ["candidate_id"],
    }

    def run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        from cctbx import xray

        ses = ctx.session or self.project.session
        if ses is None or ses.model is None:
            return ToolResult.failure("no model in session")
        cache = read_cache(self.project.dir)
        if not cache:
            return ToolResult.failure(
                "no search_fragment_pose candidates on file - run the search first")
        st = self.project.nodes.state()
        if cache.get("node") != st.get("active_node") or cache.get("revision") != st.get("seq"):
            return ToolResult.failure(
                f"the candidates were computed on {cache.get('node')} (revision "
                f"{cache.get('revision')}); the model is now {st.get('active_node')} "
                f"(revision {st.get('seq')}) - rerun search_fragment_pose")
        cid = str(params.get("candidate_id") or "").strip()
        cand = next((c for c in cache.get("candidates") or [] if c.get("id") == cid), None)
        if cand is None:
            have = [c.get("id") for c in cache.get("candidates") or []]
            return ToolResult.failure(f"no candidate {cid!r}; on file: {have}")
        occ = params.get("occupancy")
        occ = float(cand.get("occupancy_hypothesis") or 1.0) if occ is None else float(occ)
        if not 0.01 <= occ <= 1.0:
            return ToolResult.failure("occupancy must be within 0.01..1.0")
        u_iso = float(params.get("u_iso", 0.05))
        if not 0.005 <= u_iso <= 0.5:
            return ToolResult.failure("u_iso must be within 0.005..0.5")
        part = params.get("part")
        part = int(part) if part not in (None, "", 0) else None
        shared = bool(params.get("shared_occupancy", True)) and occ < 1.0
        xs = ses.model
        existing = {sc.label.strip().upper() for sc in xs.scatterers()}
        sites = cand.get("sites") or []
        els = cand.get("elements") or []
        if not sites or len(sites) != len(els):
            return ToolResult.failure("candidate on file has no usable sites")
        added: list[dict[str, Any]] = []
        per_atom = {a.get("template_index"): a for a in cand.get("per_atom") or []}
        labels: list[str] = []
        for site, el, row in zip(sites, els, cand.get("per_atom") or [{}] * len(sites)):
            lbl = _free_label(existing, el)
            xs.add_scatterer(xray.scatterer(
                label=lbl, site=tuple(float(x) for x in site),
                scattering_type=el, u=u_iso, occupancy=occ))
            labels.append(lbl)
            added.append({"label": lbl, "element": el,
                          "template_index": row.get("template_index"),
                          "site": [round(float(x), 5) for x in site],
                          "density_e_A3": row.get("density_e_A3"),
                          "sigma_level": row.get("sigma_level"),
                          "evidence": row.get("evidence")})
        xs.scattering_type_registry(table="it1992")
        flags = ses.flags
        fvar_index = None
        if shared:
            groups = list(flags.get("disorder_groups") or [])
            fvar_index = max([int(g.get("fvar_index") or 1) for g in groups] + [1]) + 1
            groups.append({"fvar_index": fvar_index, "value": occ,
                           "members": [{"label": lb, "part": part, "sign": 1, "mult": 1.0}
                                       for lb in labels],
                           "origin": "accept_fragment_pose"})
            flags["disorder_groups"] = groups
            origins = list(flags.get("disorder_origins") or [])
            origins.append({"kind": "fragment_pose", "fvar_index": fvar_index,
                            "created": labels, "candidate_id": cid,
                            "node_before": st.get("active_node"), "ts": time.time()})
            flags["disorder_origins"] = origins
        elif part is not None:
            pe = dict(flags.get("parts_extra") or {})
            for lb in labels:
                pe[lb] = part
            flags["parts_extra"] = pe
        cards_added: list[str] = []
        card_warning = None
        if params.get("eadp") and len(labels) >= 2:
            from ..io.shelx_writer import element_of, sanitize_labels
            from .shelx_cards import validate_extra_cards
            scs = list(xs.scatterers())
            all_labels = [sc.label for sc in scs]
            _lines, applied, err = validate_extra_cards(
                ["EADP " + " ".join(labels)], labels=all_labels,
                elements={element_of(sc.scattering_type) for sc in scs},
                rename=sanitize_labels(all_labels), space_group=xs.space_group())
            if err:
                card_warning = f"EADP card not added: {err}"
            else:
                eff = list(flags.get("effective_cards") or [])
                for c in applied:
                    if c.upper() not in {x.upper() for x in eff}:
                        eff.append(c)
                        cards_added.append(c)
                flags["effective_cards"] = eff
                flags.setdefault("effective_cards_job", "accept_fragment_pose")
        counts = {c: sum(1 for a in added if a.get("evidence") == c) for c in EVIDENCE}
        n = len(added)
        if counts["geometry_only"] == 0 and counts["direct_peak"] * 2 >= n:
            verdict = "supports"
        else:
            verdict = "inconclusive"
        return ToolResult(ok=True, summary={
            "candidate_id": cid,
            "added": added, "labels": labels,
            "occupancy": occ, "fvar_index": fvar_index, "part": part,
            "cards_added": cards_added,
            **({"card_warning": card_warning} if card_warning else {}),
            "n_atoms": xs.scatterers().size(),
            "scientific_outcome": {
                "verdict": verdict,
                "reasons": [f"{counts['direct_peak']} atom(s) on direct peaks, "
                            f"{counts['weak_density']} on weak density, "
                            f"{counts['geometry_only']} geometry-only (from the search)"],
                "measured_by": "difference-density evidence recorded by "
                               "search_fragment_pose; not yet refined"},
            "next": ("refine (the fragment's occupancy is one free variable"
                     if shared else "refine") + "; then audit_guest_evidence on "
                    "the new labels before believing the fragment",
        })


def register_pose_tools(reg, project) -> None:
    for cls in (SearchFragmentPose, AcceptFragmentPose):
        reg.register(cls(project))
