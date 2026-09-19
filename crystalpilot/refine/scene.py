"""Scene builder for the live crystal viewer.

Pure geometry: loads a node's canonical CIF/RES and materializes atom instances for a
chosen view mode, with exact symmetry-derived bonds and optional coordination
polyhedra. No reflection data needed (the Fo-Fc map is a separate, session-
backed path: build_fofc_ccp4).

Modes (what slice of the crystal is materialized)
  asu        the asymmetric unit only (bonds = direct ASU bonds)
  cell       full P1 unit-cell content; finite molecules (guests, ions,
             cages, molecular crystals) are wrapped by centroid and drawn
             whole across the box boundary (Olex2 pack semantics), while
             polymeric components keep per-atom wrapping
  supercell  n x n x n packing of the P1 cell
  grow       accepted alias for asu with hops>=1 (see below)

Growing is NOT a mode. `hops` grows the materialized set outward by that
many bonded shells, seeded from EVERY instance the mode produced - so it
composes with asu and cell alike, which is how Olex2 means `grow` (you
`pack` a cell and then `grow` from it). Bounded because a framework is an
infinite polymer and would otherwise run to MAX_ATOMS every time.

Every atom instance is (i_seq, rt_mx); bonds come from the smtbx connectivity
pair_sym_table closed over the materialized set, so bond geometry is exact and
cross-image bonds only draw when both endpoints exist.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import os
import threading
from collections import deque
from pathlib import Path
import time
from typing import Any

MAX_ATOMS = 20000
#: most lattice tiles the `range` contract will name (R2.2 / D7). The client
#: instances every per-cell overlay over them, so this is a drawing budget,
#: not a correctness limit - past it the scene says so via tiles_truncated.
#: 4**3, so the largest supercell the API accepts is never truncated.
MAX_TILES = 64

#: bond kind codes on the wire (index = code): chem.bonding.KIND_CODE
BOND_KINDS = ["covalent", "coordination", "eta", "metal_metal"]
POLY_LIGAND_ELEMS = {"O", "N", "S", "Cl", "Br", "F", "I", "P", "C"}
POLY_MAX_D = 3.0

# ORTEP convention: 50% probability surface of the trivariate Gaussian
# (Olex2 `telp 50` default). r = PROB50 * sqrt(eigenvalue).
PROB50 = 1.53818
# htab-style hydrogen-bond detection (Olex2 defaults: D...A <= 2.9 A)
HBOND_ELEMS = {"N", "O", "F", "S", "Cl"}
HBOND_D_MIN = 2.2
HBOND_D_MAX = 2.9


def _ellipsoid_for(uc, op, u_star) -> dict[str, Any] | None:
    """50%-probability ADP ellipsoid of a symmetry instance: rotate U_cart by
    the op's Cartesian rotation, eigendecompose, return semi-axis radii (A)
    and a row-major rotation matrix (eigenvectors as columns). NPD atoms
    return {"npd": True} so the client can fall back to a marker sphere."""
    from cctbx import adptbx
    from scitbx import matrix
    from scitbx.linalg import eigensystem

    u_cart = adptbx.u_star_as_u_cart(uc, u_star)
    r = op.r().as_double()
    if r != (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0):
        o = matrix.sqr(uc.orthogonalization_matrix())
        rc = o * matrix.sqr(r) * o.inverse()
        u = rc * matrix.sym(sym_mat3=u_cart) * rc.transpose()
        e = u.elems
        u_cart = (e[0], e[4], e[8],
                  (e[1] + e[3]) / 2, (e[2] + e[6]) / 2, (e[5] + e[7]) / 2)
    es = eigensystem.real_symmetric(u_cart)
    vals = list(es.values())            # descending
    if vals[-1] <= 1e-6:
        return {"npd": True}
    v = list(es.vectors())              # row i = eigenvector i
    det = (v[0] * (v[4] * v[8] - v[5] * v[7])
           - v[1] * (v[3] * v[8] - v[5] * v[6])
           + v[2] * (v[3] * v[7] - v[4] * v[6]))
    if det < 0:
        # right-handed frame, or the client's transformed sphere triangles
        # flip winding and the mesh lights from the inside (renders black)
        v[6], v[7], v[8] = -v[6], -v[7], -v[8]
    # columns = eigenvectors so m maps local (ellipsoid) axes -> Cartesian
    m = [v[0], v[3], v[6],
         v[1], v[4], v[7],
         v[2], v[5], v[8]]
    return {
        "r": [round(PROB50 * val ** 0.5, 4) for val in vals],
        "m": [round(x, 5) for x in m],
    }


def _detect_hbonds(atoms: list[dict], bonds: list[tuple],
                   limit: int = 400) -> list[list]:
    """Non-bonded D...A contacts between N/O/F/S/Cl atoms in htab range.
    Geometry-only (no H-angle gate: early models often lack H atoms);
    the client renders them as thin dashed lines, toggleable."""
    donors = [i for i, a in enumerate(atoms)
              if a["elem"] in HBOND_ELEMS and a.get("flag") != "removed"]
    if len(donors) < 2:
        return []
    bonded = set()
    adj: dict[int, set[int]] = {}
    for i, j, *_kind in bonds:
        bonded.add((min(i, j), max(i, j)))
        adj.setdefault(i, set()).add(j)
        adj.setdefault(j, set()).add(i)
    out: list[list] = []
    for ai in range(len(donors)):
        i = donors[ai]
        xi = atoms[i]["xyz"]
        for aj in range(ai + 1, len(donors)):
            j = donors[aj]
            if (min(i, j), max(i, j)) in bonded:
                continue
            # skip 1-3 contacts (both bonded to a common atom, e.g. chelate)
            if adj.get(i, set()) & adj.get(j, set()):
                continue
            xj = atoms[j]["xyz"]
            d2 = ((xi[0] - xj[0]) ** 2 + (xi[1] - xj[1]) ** 2
                  + (xi[2] - xj[2]) ** 2)
            if HBOND_D_MIN ** 2 <= d2 <= HBOND_D_MAX ** 2:
                out.append([i, j, round(d2 ** 0.5, 3)])
                if len(out) >= limit:
                    return out
    return out


# ---------------------------------------------------------------------------
def _bond_table(xs, parts_by_label: dict[str, int] | None = None):
    """The one bonding truth for this structure (`chem.bonding.bond_table`,
    migration 3 of plan R2.1), with the model's SHELX PART numbers."""
    from ..chem.bonding import bond_table
    parts = None
    if parts_by_label:
        parts = [int(parts_by_label.get(sc.label.upper(),
                                        parts_by_label.get(sc.label, 0)) or 0)
                 for sc in xs.scatterers()]
    return bond_table(xs, parts)


def _pair_sym_table(xs, parts_by_label: dict[str, int] | None = None):
    """Classified bonds in pair_sym_table shape (`table[i][j] -> [rt_mx]`,
    both orientations) - what the closure / growth / packing loops walk.
    Until migration 3 this was the raw smtbx table (search radius
    sum(r_cov)+0.5 A), which drew a chelate-bite carbon and La...C(arene)
    contacts as bonds."""
    return _bond_table(xs, parts_by_label).as_pair_sym_table()


def _site_key(i: int, site) -> tuple:
    return (i, round(site[0], 4), round(site[1], 4), round(site[2], 4))


class _Instances:
    """Materialized atom instances keyed by (i_seq, rounded frac site)."""

    def __init__(self, xs) -> None:
        self.xs = xs
        self.uc = xs.unit_cell()
        self.scs = list(xs.scatterers())
        self.keys: dict[tuple, int] = {}
        self.items: list[tuple[int, Any, tuple]] = []   # (i_seq, rt_mx, site)

    def add(self, i: int, op) -> int:
        site = op * self.scs[i].site
        k = _site_key(i, site)
        idx = self.keys.get(k)
        if idx is None:
            idx = len(self.items)
            self.keys[k] = idx
            self.items.append((i, op, site))
        return idx

    def lookup(self, i: int, site) -> int | None:
        return self.keys.get(_site_key(i, site))

    def __len__(self) -> int:
        return len(self.items)


def _rot_key(op) -> tuple:
    """The rotation part of an operator - the 'symmetry element' Olex2's
    grow rule speaks of; two operators that differ by a lattice
    translation share it."""
    return tuple(int(v) for v in op.r().num())


def _grow_all(inst: _Instances, pst, scs, max_atoms: int) -> dict[str, Any]:
    """Olex2 `grow` (no arguments): keep growing bonded symmetry images
    "until the operation results in a symmetry element that has been used
    previously" - read per connected fragment and per atom: a new image of
    atom j is added unless the fragment already holds an image of j with
    the same rotation part (then the new one is a lattice repeat, i.e. the
    fragment is periodic along that edge). Finite molecules therefore
    complete - including ones spread over several symmetry images or
    crossing the cell boundary - while a chain / layer / framework stops
    after one period per direction. The lattice repeat itself is still
    drawn once as a cap (so the periodic bond is visible) but never grown
    from. Element-generic: bond topology and operators only.

    Returns {"periodic_edges", "caps", "n_added", "budget_hit",
    "complete"}: complete = no periodic edge was met and the budget held."""
    from collections import deque

    n0 = len(inst)
    parent = list(range(n0))

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    rot_used: dict[int, dict[int, set]] = {}   # root -> {atom: {rot keys}}

    def union(a: int, b: int) -> int:
        ra, rb = find(a), find(b)
        if ra == rb:
            return ra
        # merge the smaller table into the larger
        ta, tb = rot_used.get(ra, {}), rot_used.get(rb, {})
        if len(ta) < len(tb):
            ra, rb, ta, tb = rb, ra, tb, ta
        parent[rb] = ra
        for j, keys in tb.items():
            ta.setdefault(j, set()).update(keys)
        rot_used[ra] = ta
        rot_used.pop(rb, None)
        return ra

    # fragments of the slice as materialized, and the elements each holds
    for a, b, *_rest in _closure_bonds(inst, pst):
        union(a, b)
    for idx, (i, op, _s) in enumerate(inst.items):
        rot_used.setdefault(find(idx), {}).setdefault(i, set()).add(_rot_key(op))

    frontier: deque[int] = deque(range(n0))
    periodic = 0
    caps = 0
    while frontier and len(inst) < max_atoms:
        idx = frontier.popleft()
        i, op, _site = inst.items[idx]
        for j, ops in pst[i].items():
            for rt in ops:
                if len(inst) >= max_atoms:
                    break
                op2 = op.multiply(rt)
                site2 = op2 * scs[j].site
                jdx = inst.lookup(j, site2)
                if jdx is not None:
                    if jdx != idx:
                        union(idx, jdx)
                    continue
                root = find(idx)
                table = rot_used.setdefault(root, {})
                rk = _rot_key(op2)
                if rk in table.get(j, ()):
                    # a lattice repeat of an image this fragment already
                    # holds: the fragment is periodic here - draw the cap,
                    # do not grow from it
                    periodic += 1
                    new = inst.add(j, op2)
                    if new >= len(parent):
                        parent.append(new)
                        caps += 1
                        union(new, idx)
                    continue
                table.setdefault(j, set()).add(rk)
                new = inst.add(j, op2)
                if new >= len(parent):
                    parent.append(new)
                    union(new, idx)
                    frontier.append(new)
    budget_hit = len(inst) >= max_atoms
    return {"periodic_edges": periodic, "caps": caps,
            "n_added": len(inst) - n0, "budget_hit": budget_hit,
            "complete": periodic == 0 and not budget_hit}


def _closure_bonds(inst: _Instances, pst, kind_of: dict | None = None):
    """All classified bonds whose both endpoints are materialized, as
    (idx, jdx) pairs - or (idx, jdx, kind_code) triples when `kind_of` maps
    (i_seq, j_seq, operator string) to a `chem.bonding.KIND_CODE`."""
    bonds: dict[tuple[int, int], int] = {}
    for idx, (i, op, _site) in enumerate(inst.items):
        for j, ops in pst[i].items():
            for rt in ops:
                op2 = op.multiply(rt)
                jdx = inst.lookup(j, op2 * inst.scs[j].site)
                if jdx is None or jdx == idx:
                    continue
                key = (min(idx, jdx), max(idx, jdx))
                if key in bonds:
                    continue
                bonds[key] = (kind_of.get((i, j, str(rt).replace(" ", "")), 0)
                              if kind_of is not None else 0)
    if kind_of is None:
        return sorted(bonds)
    return [(a, b, c) for (a, b), c in sorted(bonds.items())]


def _hull_faces(verts: list[tuple[float, float, float]]) -> list[list[int]]:
    """Brute-force convex hull triangles for small vertex sets (CN<=12)."""
    n = len(verts)
    faces: list[list[int]] = []
    c = [sum(v[k] for v in verts) / n for k in range(3)]
    for i, j, k in itertools.combinations(range(n), 3):
        a, b, d = verts[i], verts[j], verts[k]
        u = [b[m] - a[m] for m in range(3)]
        v = [d[m] - a[m] for m in range(3)]
        nrm = [u[1] * v[2] - u[2] * v[1],
               u[2] * v[0] - u[0] * v[2],
               u[0] * v[1] - u[1] * v[0]]
        mag = sum(x * x for x in nrm) ** 0.5
        if mag < 1e-9:
            continue
        pos = neg = 0
        for m in range(n):
            if m in (i, j, k):
                continue
            dd = sum(nrm[t] * (verts[m][t] - a[t]) for t in range(3))
            if dd > 1e-9:
                pos += 1
            elif dd < -1e-9:
                neg += 1
        if pos and neg:
            continue
        dc = sum(nrm[t] * (c[t] - a[t]) for t in range(3))
        faces.append([i, k, j] if dc > 0 else [i, j, k])
    return faces


# stub cap: enough dangling grow directions for interactive use without
# flooding dense frameworks
MAX_STUBS = 240

# molecule-closure probe: a connected component still growing past this many
# instances is polymeric (framework/chain) and gets per-atom cell wrapping
MOL_CAP = 800

# vdW short contacts (Olex2 grow -s / PLATON intermolecular contacts):
# non-bonded pairs with d <= r_vdw(i)+r_vdw(j), search radius capped
CONTACT_DMAX = 4.6
VDW_FALLBACK = 2.0
MAX_CONTACTS = 400


def _elem_sym(scattering_type: str) -> str:
    return "".join(c for c in scattering_type if c.isalpha())[:2].capitalize()


def _contact_sym_table(xs, pst, part_list: list[int]):
    """Symmetry-level short vdW contacts {i: [(j, rt_mx, d), ...]}.

    Excluded: covalent 1-2/1-3 pairs (via pst closure), pairs of different
    nonzero disorder PARTs (phantom contacts between alternatives), and
    polar pairs in hydrogen-bond range (those draw via the hbond channel).
    H atoms are skipped - riding positions make their contacts noise."""
    from cctbx.eltbx import van_der_waals_radii
    vdw = van_der_waals_radii.vdw.table
    scs = list(xs.scatterers())
    uc = xs.unit_cell()
    elems = [_elem_sym(sc.scattering_type) for sc in scs]

    # per-atom exclusion sets: bonded (1-2) and angle (1-3) instance keys
    excl: list[set[tuple[int, str]]] = [set() for _ in scs]
    for i in range(len(scs)):
        for j, ops in pst[i].items():
            for rt in ops:
                excl[i].add((j, str(rt)))
                for k, ops2 in pst[j].items():
                    for rt2 in ops2:
                        excl[i].add((k, str(rt.multiply(rt2))))

    pat = xs.pair_asu_table(distance_cutoff=CONTACT_DMAX)
    sym = pat.extract_pair_sym_table(
        skip_j_seq_less_than_i_seq=False, all_interactions_from_inside_asu=True)
    out: dict[int, list[tuple[int, Any, float]]] = {}
    for i in range(len(scs)):
        if elems[i] == "H":
            continue
        limit_i = vdw.get(elems[i], VDW_FALLBACK)
        for j, ops in sym[i].items():
            if elems[j] == "H":
                continue
            if part_list[i] and part_list[j] and part_list[i] != part_list[j]:
                continue
            dmax = limit_i + vdw.get(elems[j], VDW_FALLBACK)
            hbond_pair = (elems[i] in HBOND_ELEMS and elems[j] in HBOND_ELEMS)
            for rt in ops:
                if (j, str(rt)) in excl[i]:
                    continue
                d = uc.distance(scs[i].site, rt * scs[j].site)
                if not 1.0 < d <= dmax:
                    continue
                if hbond_pair and d <= HBOND_D_MAX:
                    continue
                out.setdefault(i, []).append((j, rt, d))
    return out


# symmetry-element display cap (F-lattice high-symmetry groups explode)
MAX_SYM_ELEMENTS = 240

# interaction layer (R2.3): per-kind display-row cap for the viewer wire
# format, and the largest halo the scene builder will grow to when the
# engine reports that the default 8 A cannot cover every partner
MAX_INTERACTION_ROWS = 400
INTERACTION_HALO_MAX = 14.0


def _h_source_of(parsed) -> str | None:
    """riding / refined / absent / mixed, or unknown for CIF-only geometry.

    The interaction engine requires it: SHELXL riding hydrogens sit at
    idealised X-ray distances, so H...A from a riding model is ~0.1-0.15 A
    too long and the D-H...A angle is imposed - the layer must say so."""
    scs = list(parsed.structure.scatterers())
    h_labels = {sc.label.upper() for sc in scs
                if _elem_sym(sc.scattering_type) in ("H", "D")}
    if not h_labels:
        return "absent"
    from .structure_document import StructureDocument, is_structure_only_node
    if isinstance(parsed, StructureDocument):
        return None
    source_path = getattr(parsed, "path", None)
    if source_path and is_structure_only_node(
            _read_json(Path(source_path).with_name("node.json")) or {}):
        return None  # Coordinates alone do not establish riding/refined H.
    riding: set[str] = set()
    for g in parsed.h_riding or []:
        for h in g.get("h") or []:
            riding.add(str(h).upper())
    n_r = len(h_labels & riding)
    if n_r == 0:
        return "refined"
    return "riding" if n_r >= len(h_labels) else "mixed"


def _interactions_block(xs, parsed, inst: "_Instances") -> dict[str, Any]:
    """`chem.interactions.find_interactions` on the drawn instances, in the
    viewer's wire format.

    Every display row carries the two endpoints it should be drawn between
    (`p` = first object, `q` = second object / ring centroid / off-screen
    partner) in cartesian A, the scene atom indices `ai` / `bi` when the
    endpoint is a drawn atom (None for a ring centroid or a partner outside
    the drawn range - `boundary: true`, with `sym` naming the operator), and
    the kind's own geometry + `passes`. The engine's `d` / `h` / `a` / `c`
    keys are atom LABELS. `criteria`, `h_source` and `counts` come through
    verbatim: numbers are never shown without their rule.

    The halo is the engine's default; when the engine reports the default
    cannot cover every partner (`halo_sufficient: false`) the layer is
    rebuilt once with the advised halo, capped at INTERACTION_HALO_MAX -
    and the cap, if hit, is reported rather than silently under-covering."""
    from cctbx import sgtbx

    from ..chem.interactions import DEFAULT_HALO_A, KINDS, find_interactions

    range_atoms = [(i, op) for i, op, _s in inst.items]
    caps = {k: MAX_INTERACTION_ROWS for k in KINDS}
    h_source = _h_source_of(parsed)
    kw = dict(parts=parsed.parts, h_source=h_source, range_atoms=range_atoms,
              caps=caps)
    halo = float(DEFAULT_HALO_A)
    res = find_interactions(xs, halo_A=halo, **kw)
    if not res["range"]["halo_sufficient"]:
        advised = float(res["range"]["halo_advised_A"]) + 0.05
        halo = min(INTERACTION_HALO_MAX, advised)
        if halo > float(DEFAULT_HALO_A):
            res = find_interactions(xs, halo_A=halo, **kw)

    scs = inst.scs
    idx_of: dict[int, int] = {}
    for k, it in enumerate(res["instances"]):
        if not it["in_range"]:
            continue
        i = int(it["i_seq"])
        j = inst.lookup(i, sgtbx.rt_mx(it["sym"]) * scs[i].site)
        if j is not None:
            idx_of[k] = j

    drop = {"i", "j", "ring_inst", "ring_a_inst", "ring_b_inst",
            "xyz_i", "xyz", "i_seq", "j_seq"}
    rows: list[dict[str, Any]] = []
    for r in res["rows"]:
        row = {k: v for k, v in r.items() if k not in drop}
        row["ai"] = idx_of.get(r["i"]) if r.get("i") is not None else None
        row["bi"] = idx_of.get(r["j"]) if r.get("j") is not None else None
        row["p"] = r["xyz_i"]
        row["q"] = r["xyz"]
        rows.append(row)

    rg = res["range"]
    return {
        "h_source": res["h_source"],
        "h_source_note": res["h_source_note"],
        "criteria": res["criteria"],
        "counts": res["counts"],
        "truncated": res["truncated"],
        "range": {
            "halo_A": rg["halo_A"],
            "halo_advised_A": rg["halo_advised_A"],
            "halo_sufficient": rg["halo_sufficient"],
            "halo_capped": bool(not rg["halo_sufficient"]
                                and halo >= INTERACTION_HALO_MAX),
            "n_range": rg["n_range"], "n_halo": rg["n_halo"],
            "n_boundary": res["counts"]["n_boundary"],
            "boundary_rule": rg["boundary_rule"],
        },
        "rings": [{"centroid": r["centroid"], "normal": r["normal"],
                   "radius": r["radius"], "atoms": r["atoms"],
                   "aromatic": r["aromatic"], "in_range": r["in_range"]}
                  for r in res["rings"]],
        "rows": rows,
    }


def _clip_line_to_cell(p0, d, lo=0.0, hi=1.0):
    """Clip the fractional line p0 + s*d to the [lo,hi]^3 box (slab method).
    Returns (a, b) endpoints or None."""
    smin, smax = -1e9, 1e9
    for k in range(3):
        if abs(d[k]) < 1e-9:
            if not lo - 1e-6 <= p0[k] <= hi + 1e-6:
                return None
            continue
        s1 = (lo - p0[k]) / d[k]
        s2 = (hi - p0[k]) / d[k]
        if s1 > s2:
            s1, s2 = s2, s1
        smin = max(smin, s1)
        smax = min(smax, s2)
    if smax - smin < 1e-6:
        return None
    a = [p0[k] + smin * d[k] for k in range(3)]
    b = [p0[k] + smax * d[k] for k in range(3)]
    return a, b


def _clip_plane_to_cell(p0, nrm):
    """Convex polygon (fractional verts) of a plane through p0 with normal
    nrm intersected with the unit box, ordered around the centroid."""
    d0 = sum(nrm[k] * p0[k] for k in range(3))
    pts: list[tuple] = []
    corners = [(i, j, k) for i in (0, 1) for j in (0, 1) for k in (0, 1)]
    edges = [(a, b) for a in corners for b in corners
             if sum(abs(a[m] - b[m]) for m in range(3)) == 1 and a < b]
    for a, b in edges:
        fa = sum(nrm[k] * a[k] for k in range(3)) - d0
        fb = sum(nrm[k] * b[k] for k in range(3)) - d0
        if abs(fa) < 1e-9:
            pts.append(a)
        if abs(fb) < 1e-9:
            pts.append(b)
        if fa * fb < -1e-12:
            s = fa / (fa - fb)
            pts.append(tuple(a[k] + s * (b[k] - a[k]) for k in range(3)))
    uniq: list[tuple] = []
    for p in pts:
        if not any(sum((p[k] - q[k]) ** 2 for k in range(3)) < 1e-8
                   for q in uniq):
            uniq.append(p)
    if len(uniq) < 3:
        return None
    c = [sum(p[k] for p in uniq) / len(uniq) for k in range(3)]
    # in-plane basis for angular ordering
    ref = uniq[0]
    u = [ref[k] - c[k] for k in range(3)]
    lu = sum(x * x for x in u) ** 0.5
    if lu < 1e-9:
        return None
    u = [x / lu for x in u]
    v = [nrm[1] * u[2] - nrm[2] * u[1],
         nrm[2] * u[0] - nrm[0] * u[2],
         nrm[0] * u[1] - nrm[1] * u[0]]
    import math
    def ang(p):
        w = [p[k] - c[k] for k in range(3)]
        return math.atan2(sum(w[k] * v[k] for k in range(3)),
                          sum(w[k] * u[k] for k in range(3)))
    uniq.sort(key=ang)
    return [[round(x, 5) for x in p] for p in uniq]


def _reduce_mod1(v) -> list[float]:
    """Translation components reduced into (-1/2, 1/2] (glide/screw vectors
    are defined modulo the lattice)."""
    out = []
    for x in v:
        r = x - round(x)
        if abs(r + 0.5) < 1e-9:
            r = 0.5
        out.append(r)
    return out


def _glide_symbol(intrinsic) -> str:
    """Name a glide by its translation vector (a/b/c/n/d; fallback g)."""
    intrinsic = _reduce_mod1(intrinsic)
    nz = [k for k in range(3) if abs(intrinsic[k]) > 1e-6]
    if len(nz) == 1 and abs(abs(intrinsic[nz[0]]) - 0.5) < 1e-6:
        return "abc"[nz[0]]
    if len(nz) >= 2 and all(abs(abs(intrinsic[k]) - 0.5) < 1e-6 for k in nz):
        return "n"
    if nz and all(abs(abs(intrinsic[k]) - 0.25) < 1e-6 for k in nz):
        return "d"
    return "g"


_SUBS = str.maketrans("0123456", "₀₁₂₃₄₅₆")


def _symmetry_elements(xs) -> list[dict[str, Any]]:
    """Geometric symmetry elements of the space group, clipped to the unit
    cell, in fractional coordinates: rotation/screw axes as segments,
    mirror/glide planes as convex polygons, inversion centres as points.
    Rotoinversions (-3/-4/-6) contribute their axis + centre point."""
    from cctbx import sgtbx

    import numpy as np

    out: list[dict[str, Any]] = []
    seen: set[tuple] = set()
    axis_m: dict[tuple, int] = {}         # canonical line -> screw m
    axis_at: dict[tuple, int] = {}        # canonical line -> index in out
    sg = xs.space_group()
    # element locations sit at t_loc/2-ish, so covering [0,1] needs
    # translation indices up to +2
    trange = (-1, 0, 1, 2)
    for op in sg.all_ops():
        info = op.r().info()
        t_type = info.type()
        if t_type == 1:
            continue                      # identity / pure translation
        ev = info.ev()
        # exact decomposition of the base op; lattice-shifted variants are
        # derived in floats (sgtbx tr_vec cannot hold thirds/12 mixtures)
        ti0 = sgtbx.translation_part_info(op)
        intr0 = np.array(ti0.intrinsic_part().as_double())
        p00 = np.array(ti0.origin_shift().as_double())
        rmat = np.array(op.r().as_double()).reshape(3, 3)
        n_ord = 1
        acc = rmat.copy()
        while n_ord < 6 and not np.allclose(acc, np.eye(3), atol=1e-9):
            acc = acc @ rmat
            n_ord += 1
        proj_inv = sum(np.linalg.matrix_power(rmat, k)
                       for k in range(n_ord)) / n_ord
        m_ir = np.eye(3) - rmat
        for da in trange:
            for db in trange:
                for dc in trange:
                    if len(out) >= MAX_SYM_ELEMENTS:
                        return out
                    delta = np.array([da, db, dc], dtype=float)
                    d_int = proj_inv @ delta
                    d_loc = delta - d_int
                    x = np.linalg.lstsq(m_ir, d_loc, rcond=None)[0]
                    intr = [float(v) for v in intr0 + d_int]
                    p0 = [float(v) for v in p00 + x]
                    if t_type == -1:
                        p = tuple(round(x, 4) for x in p0)
                        if not all(-1e-4 <= x <= 1 + 1e-4 for x in p):
                            continue
                        key = ("pt", p)
                        if key in seen:
                            continue
                        seen.add(key)
                        out.append({"kind": "point", "symbol": "-1",
                                    "p": list(p)})
                    elif t_type == -2:
                        seg = _clip_plane_to_cell(p0, ev)
                        if seg is None:
                            continue
                        red = _reduce_mod1(intr)
                        glide = any(abs(x) > 1e-6 for x in red)
                        d0 = round(sum(ev[k] * p0[k] for k in range(3)), 4)
                        key = ("pl", ev, d0)
                        if key in seen:
                            continue
                        seen.add(key)
                        out.append({
                            "kind": "plane",
                            "symbol": _glide_symbol(red) if glide else "m",
                            "glide": glide,
                            "poly": seg,
                        })
                    else:
                        order = abs(t_type)
                        seg = _clip_line_to_cell(p0, ev)
                        if seg is None:
                            continue
                        # canonical axis key: direction + perp offset
                        dd = ev
                        n2 = sum(x * x for x in dd)
                        proj = sum(p0[k] * dd[k] for k in range(3)) / n2
                        perp = tuple(round(p0[k] - proj * dd[k], 4)
                                     for k in range(3))
                        key = ("ax", t_type, dd, perp)
                        # screw fraction along +ev in [0,1); only the
                        # positive-sense op names the line (a 3₂ op's
                        # square reduces to 1/3 and must not rename it)
                        s = (sum(intr[k] * dd[k] for k in range(3)) / n2) % 1.0
                        m = round(s * order) % order if t_type > 0 else 0
                        naming = t_type < 0 or order == 2 or info.sense() > 0
                        if key in seen:
                            if naming and axis_m.get(key) is None:
                                axis_m[key] = m
                                if m > 0:
                                    out[axis_at[key]]["symbol"] = (
                                        f"{order}" + str(m).translate(_SUBS))
                                    out[axis_at[key]]["screw"] = True
                            continue
                        seen.add(key)
                        screw = t_type > 0 and m > 0
                        if t_type < 0:
                            symbol = str(t_type)
                        elif screw:
                            symbol = f"{order}" + str(m).translate(_SUBS)
                        else:
                            symbol = str(order)
                        el: dict[str, Any] = {
                            "kind": "axis", "symbol": symbol,
                            "order": order, "screw": screw,
                            "seg": [[round(x, 5) for x in seg[0]],
                                    [round(x, 5) for x in seg[1]]],
                        }
                        if t_type < 0:
                            el["centre"] = [round(x, 4) for x in p0]
                        axis_m[key] = m if naming else None
                        axis_at[key] = len(out)
                        out.append(el)
    return out


# The unit cell never enters _symmetry_elements - every clip happens in
# fractional space - so the result is a pure function of the space group and
# one entry serves every node, mode and grow variant in the process. It ran
# on EVERY build and costs ~0.15 s for a cubic F/I group (240-element cap),
# which the interactive grow path pays on each click.
_SYM_MEMO: dict[str, list[dict[str, Any]]] = {}
_SYM_MEMO_GUARD = threading.Lock()
MAX_SYM_MEMO = 32          # far above the few groups one session ever sees


def _symmetry_elements_memo(xs) -> list[dict[str, Any]]:
    """Hall symbol keys the memo because it pins the SETTING too (P 2₁/c and
    P 2₁/n share a group but not their element geometry). The returned list
    is shared with every other scene of that group - never mutate it."""
    key = xs.space_group().type().hall_symbol()
    with _SYM_MEMO_GUARD:
        hit = _SYM_MEMO.get(key)
    if hit is not None:
        return hit
    els = _symmetry_elements(xs)
    with _SYM_MEMO_GUARD:
        if len(_SYM_MEMO) >= MAX_SYM_MEMO:
            _SYM_MEMO.clear()
        _SYM_MEMO[key] = els
    return els


def _molecule_closure(seed: int, pst, scs, cap: int = MOL_CAP):
    """Complete molecule containing the identity instance of `seed`, as
    [(i_seq, rt_mx), ...] - or None if the component is polymeric (closure
    exceeds `cap`). pst is symmetric (skip_j_seq_less_than_i_seq=False)."""
    from cctbx import sgtbx
    identity = sgtbx.rt_mx()
    out: list[tuple[int, Any]] = [(seed, identity)]
    seen = {_site_key(seed, scs[seed].site)}
    dq: deque[tuple[int, Any]] = deque(out)
    while dq:
        i, op = dq.popleft()
        for j, ops in pst[i].items():
            for rt in ops:
                op2 = op.multiply(rt)
                k = _site_key(j, op2 * scs[j].site)
                if k in seen:
                    continue
                if len(out) >= cap:
                    return None
                seen.add(k)
                out.append((j, op2))
                dq.append((j, op2))
    return out


# ---------------------------------------------------------------------------
# packing helpers (Olex2 `pack` family): shared by cell / supercell / radius /
# range so a finite molecule is always wrapped WHOLE by its centroid

MAX_PACK_RADIUS = 30.0


def _translation(ta: int, tb: int, tc: int):
    from cctbx import sgtbx
    return sgtbx.rt_mx(sgtbx.rot_mx(),
                       sgtbx.tr_vec([12 * ta, 12 * tb, 12 * tc], 12))


def _partition_molecules(pst, scs):
    """Connected components of the ASU bond graph: finite molecules as
    closures [(i_seq, rt_mx), ...] plus the atoms of polymeric components
    (closure exceeds MOL_CAP)."""
    uf = list(range(len(scs)))

    def _find(a: int) -> int:
        while uf[a] != a:
            uf[a] = uf[uf[a]]
            a = uf[a]
        return a

    for i in range(len(scs)):
        for j in pst[i].keys():
            uf[_find(i)] = _find(j)
    comps: dict[int, list[int]] = {}
    for i in range(len(scs)):
        comps.setdefault(_find(i), []).append(i)
    finite_mols: list[list[tuple[int, Any]]] = []
    poly_atoms: list[int] = []
    for members in comps.values():
        mol = _molecule_closure(members[0], pst, scs)
        if mol is None:
            poly_atoms.extend(members)
        else:
            finite_mols.append(mol)
    return finite_mols, poly_atoms


def _wrapped_groups(xs, scs, pst) -> list[list[tuple[int, Any]]]:
    """Every symmetry image of the ASU translated into the origin cell, as
    groups that must be drawn together: a finite molecule is wrapped by its
    CENTROID and is one group (Olex2 pack semantics - never chopped across
    a face); each atom of a polymeric component is its own group, wrapped
    on its own."""
    from cctbx import sgtbx
    finite_mols, poly_atoms = _partition_molecules(pst, scs)
    groups: list[list[tuple[int, Any]]] = []
    for g in xs.space_group():
        for mol in finite_mols:
            imaged = [(i, g.multiply(op)) for i, op in mol]
            cen = [0.0, 0.0, 0.0]
            for i, op2 in imaged:
                s = op2 * scs[i].site
                for k in range(3):
                    cen[k] += s[k]
            shift = [-int((c / len(imaged)) // 1) for c in cen]
            tr = sgtbx.rt_mx(sgtbx.rot_mx(),
                             sgtbx.tr_vec([12 * s for s in shift], 12))
            groups.append([(i, tr.multiply(op2)) for i, op2 in imaged])
        for i in poly_atoms:
            site = g * scs[i].site
            # wrap into [0,1) via a pure translation so bonds stay exact
            shift = [-int(x // 1) for x in site]
            tr = sgtbx.rt_mx(sgtbx.rot_mx(),
                             sgtbx.tr_vec([12 * s for s in shift], 12))
            groups.append([(i, tr.multiply(g))])
    return groups


def _centre_frac(scs, center: str | None) -> tuple[float, float, float]:
    """Fractional centre for a radius pack: the named ASU atom, else the
    centroid of the asymmetric unit."""
    if center:
        want = center.strip().upper()
        for sc in scs:
            if sc.label.upper() == want:
                return tuple(sc.site)
    n = max(1, len(scs))
    return tuple(sum(sc.site[k] for sc in scs) / n for k in range(3))


def _pack_radius(inst: "_Instances", xs, scs, pst, radius: float,
                 center: str | None) -> None:
    """Olex2 `pack r`: every whole molecule (or polymer atom) with at least
    one atom within `radius` Å of the centre."""
    import math

    import numpy as np
    uc = xs.unit_cell()
    r = max(1.0, min(float(radius), MAX_PACK_RADIUS))
    cfrac = _centre_frac(scs, center)
    ccart = np.array(uc.orthogonalize(cfrac), dtype=float)
    groups = _wrapped_groups(xs, scs, pst)
    coords = [np.array([uc.orthogonalize(op * scs[i].site) for i, op in grp],
                       dtype=float) for grp in groups]
    # cells to search along each axis: the interplanar spacing d_100 is
    # 1/a*, so ceil(r*a*) cells cover the sphere; +1 because a wrapped
    # molecule can poke one cell out of its box
    astar, bstar, cstar = uc.reciprocal_parameters()[:3]
    span = [int(math.ceil(r * s)) + 1 for s in (astar, bstar, cstar)]
    c0 = [int(math.floor(x)) for x in cfrac]
    for ta in range(c0[0] - span[0], c0[0] + span[0] + 1):
        for tb in range(c0[1] - span[1], c0[1] + span[1] + 1):
            for tc in range(c0[2] - span[2], c0[2] + span[2] + 1):
                shift = np.array(uc.orthogonalize((ta, tb, tc)), dtype=float)
                tr = _translation(ta, tb, tc)
                for grp, xyz in zip(groups, coords):
                    if np.min(np.linalg.norm(xyz + shift - ccart, axis=1)) > r:
                        continue
                    for i, op in grp:
                        if len(inst) >= MAX_ATOMS:
                            return
                        inst.add(i, tr.multiply(op))


def _pack_range(inst: "_Instances", xs, scs, pst,
                frac_range: tuple[tuple[float, float, float],
                                  tuple[float, float, float]]) -> None:
    """Olex2 `pack a1 a2 b1 b2 c1 c2`: every group whose (wrapped) centroid
    falls inside the fractional box [lo, hi] on all three axes. Molecules
    are judged by centroid so they stay whole, which is the one deliberate
    difference from Olex2's per-atom test."""
    import math
    lo = [max(-4.0, min(4.0, float(v))) for v in frac_range[0]]
    hi = [max(-4.0, min(4.0, float(v))) for v in frac_range[1]]
    for k in range(3):
        if hi[k] < lo[k]:
            lo[k], hi[k] = hi[k], lo[k]
    groups = _wrapped_groups(xs, scs, pst)
    cens = []
    for grp in groups:
        cen = [0.0, 0.0, 0.0]
        for i, op in grp:
            s = op * scs[i].site
            for k in range(3):
                cen[k] += s[k] / len(grp)
        cens.append(cen)
    rng = [range(int(math.floor(lo[k])) - 1, int(math.ceil(hi[k])) + 1)
           for k in range(3)]
    for ta in rng[0]:
        for tb in rng[1]:
            for tc in rng[2]:
                tr = _translation(ta, tb, tc)
                for grp, cen in zip(groups, cens):
                    if not all(lo[k] <= cen[k] + (ta, tb, tc)[k] <= hi[k]
                               for k in range(3)):
                        continue
                    for i, op in grp:
                        if len(inst) >= MAX_ATOMS:
                            return
                        inst.add(i, tr.multiply(op))


def _scene_range(uc, items: list[tuple[int, Any, tuple]],
                 fixed_tiles: list[tuple[int, int, int]] | None = None,
                 ) -> dict[str, Any]:
    """The lattice extent of the drawn instances (R2.2 场景 range 契约, D7).

    `tiles` is the set of integer translations t whose unit box [t, t+1)^3
    HOLDS at least one drawn site (the occupied cells), united with
    `fixed_tiles` when given - the n^3 block a packed cell / supercell is
    defined by. So `cell` names exactly [[0,0,0]] even though a
    centroid-wrapped molecule pokes into a neighbour (the pore surface is
    not tiled into a cell that only holds a few poking-out atoms), while a
    grown or radius / range slice names every cell its atoms reach,
    negative translations included. Ghosts are not drawn instances.

    Contract: the per-cell products (void mask, Fo-Fc map, Q peaks,
    symmetry elements) stay cached per NODE - one marching-cubes mesh, one
    peak list, one set of elements - and only the cheap client-side
    instancing depends on the range. Tiling them server-side would put
    ~1.4 GB of a 4x4x4 MOF void grid on the wire.

    Truncation keeps the MAX_TILES boxes whose centre is nearest
    `centre_cart` (ties by lexicographic tile, so the answer is
    deterministic); `n_tiles` always reports the count BEFORE truncation.
    """
    import math
    if not items:
        return {"frac_lo": [0.0, 0.0, 0.0], "frac_hi": [0.0, 0.0, 0.0],
                "tiles": [[0, 0, 0]], "n_tiles": 1, "tiles_truncated": False,
                "centre_cart": [0.0, 0.0, 0.0]}
    lo = [min(s[k] for _i, _op, s in items) for k in range(3)]
    hi = [max(s[k] for _i, _op, s in items) for k in range(3)]
    cen = [sum(s[k] for _i, _op, s in items) / len(items) for k in range(3)]
    ccart = list(uc.orthogonalize(cen))
    occupied = {tuple(int(math.floor(s[k])) for k in range(3))
                for _i, _op, s in items}
    if fixed_tiles:
        occupied |= {tuple(int(v) for v in ft) for ft in fixed_tiles}
    tiles = sorted(occupied)
    n_tiles = len(tiles)
    if n_tiles > MAX_TILES:
        def _key(t):
            p = uc.orthogonalize([t[k] + 0.5 for k in range(3)])
            d2 = sum((p[k] - ccart[k]) ** 2 for k in range(3))
            # rounded so a symmetric pair never breaks on float noise
            return (round(d2, 6), t)
        tiles = sorted(tiles, key=_key)[:MAX_TILES]
    # the bounds are rounded for the wire ONLY - tiles come from the
    # unrounded sites, at the same 1e-4 precision _site_key dedupes on
    return {"frac_lo": [round(v, 4) for v in lo],
            "frac_hi": [round(v, 4) for v in hi],
            "tiles": [list(t) for t in sorted(tiles)],
            "n_tiles": n_tiles,
            "tiles_truncated": n_tiles > MAX_TILES,
            "centre_cart": [round(c, 4) for c in ccart]}


# ---------------------------------------------------------------------------
def build_scene(res_path: str | Path,
                mode: str = "asu",
                n: int = 2,
                hops: int = 0,
                polyhedra: bool = True,
                parent_res_path: str | Path | None = None,
                extra: list[dict[str, Any]] | None = None,
                contacts: bool = False,
                complete: bool = False,
                radius: float = 8.0,
                center: str | None = None,
                frac_range: tuple[tuple[float, float, float],
                                  tuple[float, float, float]] | None = None,
                interactions: bool = False,
                grow_all: bool = False,
                ) -> dict[str, Any]:
    """mode: asu | cell | supercell(n) | radius(radius, center) |
    range(frac_range); `grow` is an accepted alias for asu with hops>=1.

    grow_all: Olex2 `grow` (no arguments) - grow bonded images until the
    operation would repeat a symmetry element already used for that atom
    in the same fragment; finite molecules complete, periodic nets stop
    after one period per direction (see `_grow_all`; the scene reports
    `grow_all` with periodic_edges / caps / budget_hit / complete).
    complete: Olex2 `grow -w` - after growth, apply every symmetry
    operator already used by a drawn instance to the WHOLE asymmetric unit,
    so solvent / counter-ions that belong with a grown image come along.

    extra: user-grown instances [{"i": i_seq, "op": "sym op string"}]
    appended after the mode's own materialization (Olex2 mode-grow analog:
    the client sends back the ops of clicked grow stubs).

    contacts: also emit short vdW contacts between materialized atoms and
    (asu/grow) clickable contact stubs toward unmaterialized packing
    neighbours (Olex2 grow -s analog).

    interactions: also run `chem.interactions` on the drawn instances
    (hydrogen bonds, pi-pi, C-H...pi, C-H...X, halogen, anion-pi) and attach
    the display rows under `interactions` (see `_interactions_block`)."""
    from cctbx import adptbx, sgtbx

    from ..chem.bonding import KIND_CODE, is_metal_element
    from .structure_document import load_model_document

    parsed = load_model_document(Path(res_path))
    xs = parsed.structure
    uc = xs.unit_cell()
    scs = list(xs.scatterers())
    # PART-aware, classified bonds (chem.bonding): overlapping disorder
    # alternatives are never drawn bonded; a chelate-bite carbon or a
    # La...C(arene) contact is not a bond; each drawn bond carries its kind
    table = _bond_table(xs, parsed.parts)
    pst = table.as_pair_sym_table()
    kind_of = {(e.i, e.j, e.op.replace(" ", "")): KIND_CODE[e.kind]
               for e in table.edges}
    inst = _Instances(xs)
    identity = sgtbx.rt_mx()

    # `grow` is not a slice of the crystal - it is an ACTION applied to
    # whichever slice is on screen, which is how Olex2 means it (you `pack`
    # a cell and then `grow` from it). It stays accepted as a mode name for
    # cached keys and older clients, meaning "the asymmetric unit, grown".
    if mode == "grow":
        mode, hops = "asu", max(1, int(hops))
    hops = max(0, min(int(hops), 4))

    if mode == "asu":
        for i in range(len(scs)):
            inst.add(i, identity)
    elif mode in ("cell", "supercell"):
        n = max(1, min(int(n), 4)) if mode == "supercell" else 1
        # P1-4 跨界分子补全: finite molecules are wrapped by their CENTROID
        # and drawn whole even where they poke out of the box (Olex2 pack
        # semantics); polymeric components keep the per-atom wrap.
        base_ops = [io for grp in _wrapped_groups(xs, scs, pst) for io in grp]
        for ta in range(n):
            for tb in range(n):
                for tc in range(n):
                    tr = _translation(ta, tb, tc)
                    for i, g in base_ops:
                        if len(inst) >= MAX_ATOMS:
                            break
                        inst.add(i, tr.multiply(g))
    elif mode == "radius":
        _pack_radius(inst, xs, scs, pst, radius, center)
    elif mode == "range":
        _pack_range(inst, xs, scs, pst,
                    frac_range or ((-0.5, -0.5, -0.5), (1.5, 1.5, 1.5)))
    else:
        raise ValueError(f"unknown scene mode: {mode}")

    # ---- growth on top of whatever the mode materialized -----------------
    # Seeded from EVERY current instance, not just the identity ones, so
    # growing out of a packed cell reaches the neighbours of the images the
    # cell put there. Each pass is one shell (Olex2 `grow -s` repeated), so
    # the client can hold a level and step it.
    if hops > 0:
        frontier: deque[tuple[int, Any, int]] = deque(
            (i, op, 0) for i, op, _s in inst.items)
        while frontier and len(inst) < MAX_ATOMS:
            i, op, h = frontier.popleft()
            if h >= hops:
                continue
            for j, ops in pst[i].items():
                for rt in ops:
                    op2 = op.multiply(rt)
                    before = len(inst)
                    inst.add(j, op2)
                    if len(inst) > before:
                        frontier.append((j, op2, h + 1))

    # ---- user-grown instances (clicked grow stubs) -----------------------
    for e in extra or []:
        if len(inst) >= MAX_ATOMS:
            break
        try:
            inst.add(int(e["i"]), sgtbx.rt_mx(str(e["op"])))
        except (KeyError, ValueError, TypeError, RuntimeError):
            continue  # malformed entry: skip rather than fail the scene

    # ---- grow all (Olex2 `grow`, round-3 R5) ------------------------------
    closure: dict[str, Any] | None = None
    if grow_all:
        closure = _grow_all(inst, pst, scs, MAX_ATOMS)

    # ---- complete (Olex2 grow -w) ----------------------------------------
    # Every operator that produced a drawn instance is applied to the whole
    # ASU, so a counter-ion or solvent molecule that belongs with a grown
    # image is drawn beside it instead of being left in the origin cell.
    if complete:
        used: dict[str, Any] = {}
        for _i, op, _s in inst.items:
            used.setdefault(str(op), op)
        for op in used.values():
            for i in range(len(scs)):
                if len(inst) >= MAX_ATOMS:
                    break
                inst.add(i, op)

    truncated = len(inst) >= MAX_ATOMS
    bonds = _closure_bonds(inst, pst, kind_of)

    # ---- dangling grow directions (Olex2 mode-grow dashed bonds) ---------
    # For asu/cell scenes: bonded symmetry neighbours NOT yet materialized.
    # The client renders them as clickable stubs; clicking one sends the op
    # back via `extra` and the fragment keeps growing.
    stubs: list[dict[str, Any]] = []
    seen_pos: set = set()
    if mode in ("asu", "cell", "radius", "range"):
        for idx, (i, op, _site) in enumerate(inst.items):
            if len(stubs) >= MAX_STUBS:
                break
            for j, ops in pst[i].items():
                for rt in ops:
                    op2 = op.multiply(rt)
                    site2 = op2 * scs[j].site
                    if inst.lookup(j, site2) is not None:
                        continue
                    key = _site_key(j, site2)
                    if key in seen_pos:
                        continue
                    seen_pos.add(key)
                    stubs.append({
                        "from": idx,
                        "i": j,
                        "op": str(op2),
                        "elem": scs[j].scattering_type.strip().capitalize(),
                        "label": scs[j].label,
                        "xyz": [round(c, 4)
                                for c in uc.orthogonalize(site2)],
                    })
                    if len(stubs) >= MAX_STUBS:
                        break
                if len(stubs) >= MAX_STUBS:
                    break

    # ---- short vdW contacts (P2-2, Olex2 grow -s analog) -----------------
    # Materialized-pair dashed edges everywhere; in asu/grow additionally
    # clickable contact stubs toward unmaterialized packing neighbours
    # (same grow mechanism: clicking sends the op back via `extra`).
    contact_edges: list[list] = []
    if contacts:
        part_list = [int((parsed.parts or {}).get(
            sc.label.upper(), (parsed.parts or {}).get(sc.label, 0)) or 0)
            for sc in scs]
        cst = _contact_sym_table(xs, pst, part_list)
        seen_c: set[tuple[int, int]] = set()
        for idx, (i, op, _site) in enumerate(inst.items):
            if len(contact_edges) >= MAX_CONTACTS:
                break
            for j, rt, d in cst.get(i, ()):
                op2 = op.multiply(rt)
                site2 = op2 * scs[j].site
                jdx = inst.lookup(j, site2)
                if jdx is not None:
                    if jdx == idx:
                        continue
                    ckey = (min(idx, jdx), max(idx, jdx))
                    if ckey not in seen_c:
                        seen_c.add(ckey)
                        contact_edges.append([ckey[0], ckey[1], round(d, 3)])
                        if len(contact_edges) >= MAX_CONTACTS:
                            break
                elif mode in ("asu", "cell", "radius", "range") and len(stubs) < MAX_STUBS:
                    key = _site_key(j, site2)
                    if key in seen_pos:
                        continue
                    seen_pos.add(key)
                    stubs.append({
                        "from": idx,
                        "i": j,
                        "op": str(op2),
                        "elem": scs[j].scattering_type.strip().capitalize(),
                        "label": scs[j].label,
                        "xyz": [round(c, 4)
                                for c in uc.orthogonalize(site2)],
                        "kind": "contact",
                    })

    # ---- diff vs parent (ASU labels) -------------------------------------
    flags: dict[str, str] = {}
    ghosts: list[dict[str, Any]] = []
    if parent_res_path is not None:
        parent = load_model_document(Path(parent_res_path)).structure
        pmap = {sc.label.upper(): (sc.scattering_type.strip().capitalize(),
                                   parent.unit_cell().orthogonalize(sc.site))
                for sc in parent.scatterers()}
        cmap = {sc.label.upper(): (sc.scattering_type.strip().capitalize(),
                                   uc.orthogonalize(sc.site))
                for sc in scs}
        for lbl, (el, xyz) in cmap.items():
            if lbl not in pmap:
                flags[lbl] = "added"
            else:
                pel, pxyz = pmap[lbl]
                if pel != el:
                    flags[lbl] = "element_changed"
                elif sum((a - b) ** 2 for a, b in zip(xyz, pxyz)) ** 0.5 > 0.3:
                    flags[lbl] = "moved"
        if mode in ("asu", "cell"):
            for lbl in sorted(set(pmap) - set(cmap)):
                el, xyz = pmap[lbl]
                ghosts.append({"label": lbl, "elem": el,
                               "xyz": [round(c, 4) for c in xyz],
                               "flag": "removed"})

    # ---- serialize -------------------------------------------------------
    atoms = []
    unknown_adps = set(getattr(parsed, "unknown_adp_labels", []))
    for i, op, site in inst.items:
        sc = scs[i]
        el = sc.scattering_type.strip().capitalize()
        xyz = uc.orthogonalize(site)
        u_eq = (adptbx.u_star_as_u_iso(uc, sc.u_star)
                if sc.flags.use_u_aniso() else sc.u_iso)
        a: dict[str, Any] = {"label": sc.label, "elem": el,
                             "xyz": [round(c, 4) for c in xyz],
                             "occ": round(float(sc.occupancy), 3),
                             "u_eq": (None if sc.label in unknown_adps
                                      else round(float(u_eq), 4)),
                             "sym": not op.is_unit_mx()}
        if hasattr(parsed, "unknown_adp_labels"):
            a["adp_known"] = sc.label not in unknown_adps
            if not a["adp_known"]:
                a["adp_note"] = "ADP not reported"
        if is_metal_element(el):
            a["m"] = True                 # server-side metal verdict (D9)
        part = (parsed.parts or {}).get(sc.label)
        if part:
            a["part"] = part              # disorder PART (Olex2 showp)
        if a["sym"]:
            a["symop"] = str(op)          # Olex2-style symmetry-mate note
        if sc.flags.use_u_aniso():
            ell = _ellipsoid_for(uc, op, sc.u_star)
            if ell is not None:
                a["ell"] = ell
        f = flags.get(sc.label.upper())
        if f:
            a["flag"] = f
        atoms.append(a)

    polys = []
    if polyhedra:
        adj: dict[int, list[int]] = {}
        for a_i, b_i, *_kind in bonds:
            adj.setdefault(a_i, []).append(b_i)
            adj.setdefault(b_i, []).append(a_i)
        for idx, a in enumerate(atoms):
            if not a.get("m"):
                continue
            verts = []
            for jdx in adj.get(idx, []):
                b = atoms[jdx]
                if b["elem"] in POLY_LIGAND_ELEMS and b["elem"] != "C":
                    d = sum((x - y) ** 2
                            for x, y in zip(a["xyz"], b["xyz"])) ** 0.5
                    if d <= POLY_MAX_D:
                        verts.append(tuple(b["xyz"]))
            if len(verts) >= 4:
                polys.append({"metal": idx,
                              "vertices": [list(v) for v in verts],
                              "faces": _hull_faces(verts)})

    inter = _interactions_block(xs, parsed, inst) if interactions else None

    p = uc.parameters()
    from .structure_document import is_structure_only_node, structure_capabilities
    node_meta = _read_json(Path(res_path).with_name("node.json")) or {}
    document_info = ({"project_mode": "structure_only", "read_only": True,
                      "source_revision": node_meta.get("revision"),
                      "capabilities": structure_capabilities(True)}
                     if is_structure_only_node(node_meta) else {})
    return {
        **document_info,
        "mode": mode,
        "atoms": atoms + ghosts,
        "bonds": [list(b) for b in bonds],
        "bond_kinds": list(BOND_KINDS),
        "hbonds": _detect_hbonds(atoms, bonds),
        "contacts": contact_edges,
        "stubs": stubs,
        "polyhedra": polys,
        "cell": {"a": p[0], "b": p[1], "c": p[2],
                 "alpha": p[3], "beta": p[4], "gamma": p[5],
                 "volume": round(uc.volume(), 1)},
        "space_group": str(xs.space_group_info()),
        # P2-3 对称元素: cell-clipped fractional geometry (optional field -
        # scenes cached before this feature simply lack it)
        "sym_elements": _symmetry_elements_memo(xs),
        # R2.2 场景 range 契约 (D7): which lattice tiles the client must
        # instance the per-cell overlays over. Ghost (parent-only) atoms are
        # deliberately excluded - they are not drawn instances.
        "range": _scene_range(uc, inst.items, fixed_tiles=(
            [(ta, tb, tc) for ta in range(n) for tb in range(n)
             for tc in range(n)] if mode in ("cell", "supercell") else None)),
        **({"interactions": inter} if inter is not None else {}),
        **({"grow_all": closure} if closure is not None else {}),
        "meta": {"n_atoms": len(atoms), "n_ghosts": len(ghosts),
                 "n_bonds": len(bonds), "n_polyhedra": len(polys),
                 "truncated": truncated},
    }


# ---------------------------------------------------------------------------
# Fo-Fc map for an arbitrary node (session-backed, cached by the caller)
# ---------------------------------------------------------------------------
_MAP_LOCKS: dict[str, threading.Lock] = {}
_MAP_LOCKS_GUARD = threading.Lock()


def _project_lock(project_dir: Path):
    from .transactions import project_transaction
    return project_transaction(project_dir, operation="derived_data")


def build_fofc_ccp4(project_dir: str | Path, node_id: str,
                    out_path: str | Path,
                    kind: str = "fofc") -> dict[str, Any]:
    """Compute the Fo-Fc (or 2Fo-Fc, kind="2fofc") map for a node and
    write a CCP4 file. The Q-peak table (peaks.json) is a residual-map
    concept and is only written for kind="fofc".

    Builds a throwaway session for the node (model + data + recorded solvent
    mask) WITHOUT touching the project's active-node state, so it is safe to
    run while the MCP server holds the live session.
    """
    from .project import RefineProject

    project_dir = Path(project_dir)
    out_path = Path(out_path)
    with _project_lock(project_dir):
        proj = RefineProject(project_dir)
        node = _resolve_ref(proj.nodes, node_id)
        meta = proj.nodes.node_meta(node)
        from .structure_document import STRUCTURE_ONLY_PRECONDITION, is_structure_only_node
        if is_structure_only_node(meta):
            raise ValueError(STRUCTURE_ONLY_PRECONDITION)
        from .data_versions import reflection_cache_source
        reflection_cache_source(proj.nodes, node)
        proj._load_node(node)
        ses = proj.session
        if ses.fo_sq is None:
            raise ValueError(STRUCTURE_ONLY_PRECONDITION)
        f_mask = ses.flags.get("f_mask")
        applied_mask = (meta.get("comparison_conditions") or {}).get("mask") or {}
        if applied_mask.get("state") == "none":
            f_mask = None
        elif applied_mask.get("state") == "unknown":
            raise ValueError("The node's applied mask is unknown; cannot reproduce its reflection map")
        elif applied_mask.get("state") == "bound" and f_mask is None:
            raise ValueError("The node's bound applied mask could not be restored; reflection map is unavailable")
        from ..tools.refinement_tools import (_difference_map_analysis,
                                              difference_map_real)
        fft_map, _real, _k = difference_map_real(ses, ses.model, f_mask,
                                                 kind=kind)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        fft_map.as_ccp4_map(file_name=str(out_path))
        n_peaks = 0
        if kind == "fofc":
            # one throwaway session, two products: the Q-peak table rides
            # along so the web viewer can render discrete difference peaks
            # (调研 P0-1) without a second model+data rebuild. Same
            # peak_search parameters as the agent-side inspect_map, but
            # computed independently - peak ORDINALS may differ from the
            # live session's table, so consumers should cite peaks by
            # position/height/nearest atom, not bare index.
            diff = _difference_map_analysis(ses, ses.model, f_mask=f_mask)
            peaks_path = out_path.with_name("peaks.json")
            peaks_path.write_text(json.dumps({
                "node": node,
                "max": diff.get("max"), "min": diff.get("min"),
                "scale_k": diff.get("scale_k"),
                "map_provenance": diff.get("map_provenance"),
                "masked": f_mask is not None,
                "peaks": diff.get("peaks") or [],
            }), encoding="utf-8")
            n_peaks = len(diff.get("peaks") or [])
        return {"node": node, "path": str(out_path),
                "bytes": out_path.stat().st_size,
                "gridding": list(fft_map.n_real()),
                "masked": f_mask is not None,
                "n_peaks": n_peaks}


# ---------------------------------------------------------------------------
# Disk cache helpers (used by the web routes)
# ---------------------------------------------------------------------------
def cache_dir(project_dir: str | Path, node_id: str) -> Path:
    return (Path(project_dir) / ".crystalpilot" / "refine" / "scene-cache"
            / node_id)


def _resolve_ref(store, node_id: str) -> str:
    if node_id == "active":
        nid = store.state().get("active_node")
        if not nid:
            raise KeyError("project has no active node yet")
        return nid
    return store.resolve(node_id)


# Grown scenes get their own disk entries, marked by a `_g<digest>` tail so
# they can be pruned WITHOUT touching the plain per-node keys (whose space is
# the bounded product of the view options, and which prewarm_display_cache
# depends on finding). Bound: a grow session mints a fresh set on every
# click, and a MOF grow scene runs to several MB, so the cache is capped at
# the most recently USED entries - reuse comes from short windows (a mode or
# diff toggle, a node round-trip, an ungrow/regrow), not from long history.
GROWN_CACHE_MAX = 16
_DIGEST_LEN = 16
# anchored on the digest SHAPE, not just "_g", so the sweep can never reach
# a plain entry (a diff-vs key carries a node id, which is n%04d)
_GROWN_GLOB = "scene8_*_g" + "[0-9a-f]" * _DIGEST_LEN + ".json"


def _extra_digest(extra: list[dict[str, Any]]) -> str:
    """Order-independent digest of the grown-instance set.

    Order-independence is safe even though build_scene appends `extra` in the
    order given: a different order only permutes the tail of `atoms`, and
    every index-bearing field (bonds/hbonds/stubs/polyhedra) is resolved
    against that same array inside one response, so two orderings are
    interchangeable to a client that re-reads the whole scene - which the
    viewer does (it drops its selection on every scene load). Order does leak
    at the MAX_ATOMS ceiling, where position decides which extras survive the
    cap; such a scene comes back flagged truncated regardless.

    Op strings are normalized textually, never parsed: two spellings of one
    op ("1/2+x" vs "x+1/2") cost a cache MISS, which is harmless, while
    parsing would drag sgtbx onto the cache-HIT path.
    """
    items: set[tuple[int, str]] = set()
    for e in extra:
        try:
            items.add((int(e["i"]), str(e["op"]).replace(" ", "").lower()))
        except (KeyError, ValueError, TypeError):
            # build_scene silently drops malformed entries, but they must
            # not let two different requests share one key
            items.add((-1, repr(e)))
    payload = ";".join(f"{i}:{op}" for i, op in sorted(items))
    return hashlib.sha256(payload.encode()).hexdigest()[:_DIGEST_LEN]


def _prune_grown_cache(d: Path) -> None:
    def _mtime(p: Path):
        try:
            return (p.stat().st_mtime_ns, p.name)
        except OSError:
            return (0, p.name)      # vanished under a concurrent prune

    try:
        entries = list(d.glob(_GROWN_GLOB))
    except OSError:
        return
    if len(entries) <= GROWN_CACHE_MAX:
        return
    for p in sorted(entries, key=_mtime)[:-GROWN_CACHE_MAX]:
        try:
            p.unlink()
        except OSError:
            pass        # held open by a reader on Windows; retried next write


def _read_scene_cache(path: Path, touch: bool) -> dict[str, Any] | None:
    """None on miss, unreadable or truncated entry - a bad file heals by
    rebuilding, and the read must survive a concurrent prune deleting it.
    `touch` refreshes mtime so _prune_grown_cache orders by USE, not by
    write; a read-only cache directory must not break the viewer."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or "atoms" not in data:
        return None
    if touch:
        try:
            os.utime(path, None)
        except OSError:
            pass
    return data


def _write_scene_cache(path: Path, scene: dict[str, Any],
                       grown: bool) -> None:
    """Best-effort: the scene is already built, so a full disk or a losing
    race on the replace must not fail the request. The pid-tagged temp keeps
    two processes on one project from clobbering each other's partial file."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".tmp{os.getpid()}")
        tmp.write_text(json.dumps(scene), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        return
    if grown:
        _prune_grown_cache(path.parent)
    # older wire formats of the same node are never served again: sweep
    # them (best effort) so the cache directory does not keep every version
    for stale in path.parent.glob("scene[1-7]_*.json"):
        try:
            stale.unlink()
        except OSError:
            pass


def cached_scene(project_dir: str | Path, node_id: str,
                 mode: str, n: int, hops: int, polyhedra: bool,
                 diff: bool,
                 extra: list[dict[str, Any]] | None = None,
                 diff_vs: str | None = None,
                 contacts: bool = False,
                 complete: bool = False,
                 radius: float = 8.0,
                 center: str | None = None,
                 frac_range: tuple[tuple[float, float, float],
                                   tuple[float, float, float]] | None = None,
                 interactions: bool = False,
                 grow_all: bool = False,
                 ) -> dict[str, Any]:
    """Scene JSON with a per-node disk cache (node contents are immutable).
    User-grown `extra` instances are cached too, under a digest of the grown
    SET, capped at GROWN_CACHE_MAX entries per node - every grow click used
    to pay a full load_res_model + pair_sym_table + closure rebuild.

    diff_vs: compare against THIS node instead of the parent (查看器 P1
    节点对比泛化 - any-vs-any); implies diff."""
    from .nodes import NodeStore

    project_dir = Path(project_dir)
    store = NodeStore(project_dir)
    node = _resolve_ref(store, node_id)
    vs = _resolve_ref(store, diff_vs) if diff_vs else None
    # v5: centroid-wrapped finite molecules; optional vdW contact channel
    # v7: bonds are classified [i, j, kind] triples from chem.bonding and
    #     metal atoms carry m: true (bonding migration 3)
    # v8: the scene carries `range` (R2.2 / D7) - an entry without it would
    #     leave every per-cell overlay stuck in the origin cell
    dkey = f"vs-{vs}" if vs else str(int(diff))
    ckey = "_c1" if contacts else ""
    gkey = f"_g{_extra_digest(extra)}" if extra else ""
    # the new slices and grow -w only add key material when used, so every
    # existing cache file stays valid
    xkey = "_w1" if complete else ""
    if grow_all:
        xkey += "_ga1"
    if mode == "radius":
        ctr = hashlib.sha1((center or "").upper().encode("utf-8")).hexdigest()[:6]
        xkey += f"_r{max(1.0, min(float(radius), MAX_PACK_RADIUS)):.1f}_ctr{ctr}"
    if mode == "range" and frac_range:
        xkey += "_rg" + "_".join(f"{float(v):+.2f}"
                                 for v in (*frac_range[0], *frac_range[1]))
    if interactions:
        xkey += "_i1"
    adp_key = ("_adp1" if store.node_meta(node).get("canonical_model") == "model.cif"
               else "")
    key = (f"scene8_{mode}_n{n}_h{hops}_p{int(polyhedra)}"
           f"_d{dkey}{ckey}{gkey}{xkey}{adp_key}.json")
    path = cache_dir(project_dir, node) / key
    hit = _read_scene_cache(path, touch=bool(gkey))
    if hit is not None:
        return hit
    parent = None
    if vs is not None:
        parent = store.node_dir(vs) / "model.res"
    elif diff:
        parent_id = store.node_meta(node).get("parent")
        if parent_id:
            parent = store.node_dir(parent_id) / "model.res"
    scene = build_scene(store.node_dir(node) / "model.res", mode=mode, n=n,
                        hops=hops, polyhedra=polyhedra, parent_res_path=parent,
                        extra=extra, contacts=contacts, complete=complete,
                        grow_all=grow_all,
                        radius=radius, center=center, frac_range=frac_range,
                        interactions=interactions)
    scene["node"] = node
    _write_scene_cache(path, scene, grown=bool(gkey))
    return scene


_PREWARM_BUSY: set[str] = set()
_PREWARM_GUARD = threading.Lock()


def prewarm_display_cache(project_dir: str | Path) -> None:
    """Background-warm the display products a user opens FIRST after a
    turn (asu scene, Fo-Fc map + Q-peak table, void mask) for the active
    node. Everything is a cache-or-build helper, so warm hits are free;
    masked nodes recompute the solvent mask here instead of on the
    user's first click (the real source of 'Q 峰计算很长' on big MOFs).
    Never raises; one warmer per project at a time; runs under the
    process-wide CPU cap - the point is to move first-click latency
    into the idle gap right after a turn."""
    key = str(project_dir).lower()
    with _PREWARM_GUARD:
        if key in _PREWARM_BUSY:
            return
        _PREWARM_BUSY.add(key)
    try:
        from .nodes import NodeStore
        project_dir = Path(project_dir)
        node = NodeStore(project_dir).state().get("active_node")
        if not node:
            return
        for fn in (
            lambda: cached_scene(project_dir, node, mode="asu", n=2,
                                 hops=0, polyhedra=True, diff=False),
            lambda: cached_fofc(project_dir, node),
            lambda: cached_voids(project_dir, node),
            # the first press of 生长 is where the cold build actually
            # hurts, and the ungrown asu was the only warmed view, so that
            # press always paid the full cctbx build. Warmed LAST so the
            # three products above are never delayed by it.
            lambda: cached_scene(project_dir, node, mode="asu", n=2,
                                 hops=1, polyhedra=True, diff=False),
        ):
            try:
                fn()
            except Exception:  # noqa: BLE001 - warming is best-effort
                pass
    except Exception:  # noqa: BLE001
        pass
    finally:
        with _PREWARM_GUARD:
            _PREWARM_BUSY.discard(key)


def cached_fofc(project_dir: str | Path, node_id: str,
                kind: str = "fofc") -> Path:
    from .nodes import NodeStore

    if kind not in ("fofc", "2fofc"):
        raise ValueError("kind must be fofc|2fofc")
    project_dir = Path(project_dir)
    store = NodeStore(project_dir)
    node = _resolve_ref(store, node_id)
    from .structure_document import STRUCTURE_ONLY_PRECONDITION, is_structure_only_node
    if is_structure_only_node(store.node_meta(node)):
        raise ValueError(STRUCTURE_ONLY_PRECONDITION)
    from .data_versions import reflection_cache_source
    from .nodes import atomic_write_json
    source = reflection_cache_source(store, node)
    path = cache_dir(project_dir, node) / f"{kind}.ccp4"
    from ..tools.twin_maps import MAP_ALGORITHM_VERSION
    source = {**source, "map_algorithm": MAP_ALGORITHM_VERSION}
    stamp = path.with_suffix(path.suffix + ".source.json")
    if not path.exists() or _read_json(stamp) != source:
        build_fofc_ccp4(project_dir, node, path, kind=kind)
        atomic_write_json(stamp, source)
        if kind == "fofc":
            atomic_write_json(path.parent / "peaks.json.source.json", source)
    return path


# The solvent_mask TOOL (crystalpilot/tools/mask_tools.py) is the reference
# implementation for everything below: a user reads the picture next to the
# refinement report, so the display may not invent its own mask. These are
# that tool's schema defaults, used ONLY when the node never ran it - naming
# them here keeps a preview from carrying unstated parameters.
VOID_PREVIEW_DEFAULTS: dict[str, Any] = {
    "solvent_radius": 1.2,
    "shrink_truncation_radius": 1.2,
    "resolution_factor": 0.25,
    "min_void_volume": 8.0,
    "max_cycles": 10,
}
# bumped whenever the voids.json shape or its numbers change, so stale
# per-node caches heal instead of being served forever (node contents are
# immutable, the BUILDER is not)
# v3 (R3.0, D17): per-void dimensionality / directions / inscribed sphere;
#    centre_frac is null for anything but a 0-D cavity
# v5 (2026-09 known-answer validation): lcd_A is now the EXACT maximum over
#    the void's grid points (inscribed_sphere thins on a lattice and refines
#    back, instead of a list stride that could make a finer grid worse), so
#    grid_step_A is the mask grid step itself, not step * stride**(1/3), and
#    lcd_exact rides alongside
#: 7: the recount drives BypassMask (its `bypass` series is recorded) on a
#: model that carries the refinement's anomalous terms (`anomalous_terms`)
VOIDS_CACHE_V = 7


def _void_mask_params(meta: dict[str, Any],
                      session_d_min: float | None) -> tuple[dict, str]:
    """(full six-key parameter set, "node"|"defaults").

    d_min is never left unset: smtbx would silently fall back to the merged
    data resolution, which is a parameter the response could not report.
    """
    recorded = (meta.get("mask") or {}).get("params") or {}
    src = "node" if recorded else "defaults"
    p = dict(VOID_PREVIEW_DEFAULTS)
    p.update({k: v for k, v in recorded.items() if v is not None})
    if p.get("d_min") is None:
        p["d_min"] = session_d_min
    return p, src


def build_void_ccp4(project_dir: str | Path, node_id: str,
                    out_path: str | Path) -> dict[str, Any]:
    """Solvent-accessible void mask for a node: whole-cell CCP4 (binarized
    0/1 grid) + voids.json metadata (volumes / electron counts / centres).

    Runs even when the node never executed solvent_mask - the probe geometry
    depends only on the model, which is exactly the "look BEFORE deciding to
    SQUEEZE" scenario (调研 P0-2); `params_source` says which of the two the
    caller is looking at.

    The mask is always recomputed against THIS node's model. A node that
    merely INHERITED an f_mask (solvent_mask ran at an ancestor and no
    refine passed refresh_mask=true) therefore gets numbers that can differ
    from its own `mask.info` snapshot - that snapshot is carried verbatim in
    `recorded` so the two are comparable instead of silently disagreeing.
    """
    from .project import RefineProject

    project_dir = Path(project_dir)
    out_path = Path(out_path)
    with _project_lock(project_dir):
        proj = RefineProject(project_dir)
        node = _resolve_ref(proj.nodes, node_id)
        meta = proj.nodes.node_meta(node)
        # a legacy node (no data_revision) is rebuilt unbound: geometry
        # stays available, reflection-derived numbers do not (2026-09-08)
        proj._build_session(proj.nodes.node_dir(node) / "model.res",
                            allow_unbound=True)
        ses = proj.session
        xs, fo_sq = ses.model, ses.fo_sq
        if fo_sq is None:
            return _build_geometric_void_ccp4(
                xs, node, out_path, meta=meta,
                parts=ses.flags.get("parts_extra"),
                binding_required=bool(ses.flags.get("data_binding_required")))

        params, src = _void_mask_params(
            meta, (ses.merge_info or {}).get("d_min"))
        solvent_radius = float(params["solvent_radius"])
        shrink = float(params["shrink_truncation_radius"])
        res_factor = float(params["resolution_factor"])
        min_void_volume = float(params["min_void_volume"])
        max_cycles = int(params["max_cycles"])
        d_min = params.get("d_min")

        from cctbx import maptbx, sgtbx

        from ..io.shelx_writer import anomalous_terms_of
        from ..tools.mask_tools import BypassMask
        # the tool's instrumented loop, not smtbx's silent one: the recount
        # then says whether ITS series converged, like the refinement mask
        mask_obj = BypassMask(xs, fo_sq, use_set_completion=True)
        crystal_gridding = None
        if d_min:
            crystal_gridding = maptbx.crystal_gridding(
                unit_cell=xs.unit_cell(),
                space_group_info=xs.space_group_info(),
                d_min=float(d_min), resolution_factor=res_factor,
                symmetry_flags=sgtbx.search_symmetry_flags(
                    use_space_group_symmetry=False))
        mask_obj.compute(solvent_radius=solvent_radius,
                         shrink_truncation_radius=shrink,
                         resolution_factor=res_factor,
                         crystal_gridding=crystal_gridding)
        n_voids = int(mask_obj.n_voids())
        info: dict[str, Any] = {
            "v": VOIDS_CACHE_V,
            "node": node, "n_voids": n_voids,
            "mask_params": params,
            "params_source": src,
            # the f'/f'' this recount integrated with (the session rebuild
            # applies the refinement's terms; zeros = no wavelength)
            "anomalous_terms": anomalous_terms_of(xs),
            # kept flat as well: the two probe radii predate mask_params
            "solvent_radius": solvent_radius,
            "shrink_truncation_radius": shrink,
            "voids": [],
        }
        rec_info = (meta.get("mask") or {}).get("info") or {}
        if rec_info:
            info["recorded"] = {
                k: rec_info.get(k) for k in
                ("n_voids", "solvent_volume_A3",
                 "solvent_volume_pct_of_cell",
                 "total_solvent_electrons_per_cell")
                if rec_info.get(k) is not None}
        out_path.parent.mkdir(parents=True, exist_ok=True)
        import numpy as np

        from ..chem.pores import (grid_step_A, inscribed_sphere,
                                  packing_index, pore_limiting_diameter,
                                  void_topology)
        uc = xs.unit_cell()
        p1 = xs.expand_to_p1()
        p1_frac = np.array([[float(x) for x in sc.site]
                            for sc in p1.scatterers()]).reshape(-1, 3)
        p1_els = [_elem_sym(sc.scattering_type) for sc in p1.scatterers()]
        # packing numbers (R3.3) do not depend on the mask: every node gets
        # them; occupancy-weighted so a disorder pair counts once
        info["packing"] = packing_index(
            uc, p1_frac, p1_els,
            occupancies=[float(sc.occupancy) for sc in p1.scatterers()])
        if n_voids > 0:
            uc_vol = uc.volume()
            n_grid = mask_obj.crystal_gridding.n_grid_points()
            gp = mask_obj.flood_fill.grid_points_per_void()
            com = mask_obj.flood_fill.centres_of_mass_frac()
            void_vols = [uc_vol * gp[i] / n_grid for i in range(n_voids)]
            dropped = []
            for i, vol in enumerate(void_vols):
                if vol < min_void_volume:
                    mask_obj.exclude_void_flags[i] = True
                    dropped.append(i + 1)
            electrons = raw_e = None
            if not all(mask_obj.exclude_void_flags):
                try:
                    # electron integration needs the structure-factor pass;
                    # volumes/centres remain useful if it fails
                    if mask_obj.structure_factors(
                            max_cycles=max_cycles) is not None:
                        # the kept cycle's own per-void counts, not smtbx's
                        # re-integration of the mutated map buffer
                        raw_e = [float(x) for x in
                                 (mask_obj.per_void_electrons
                                  or mask_obj.electron_counts_per_void())]
                        tr = list(mask_obj.trajectory)
                        info["bypass"] = {
                            "converged": bool(mask_obj.converged),
                            "diverged": bool(mask_obj.diverged),
                            "n_cycles": int(mask_obj.n_cycles),
                            "max_cycles": max_cycles,
                            "kept_cycle": (None if mask_obj.kept_cycle is None
                                           else int(mask_obj.kept_cycle) + 1),
                            "f000s_first": round(tr[0], 1) if tr else None,
                            "f000s_last": round(tr[-1], 1) if tr else None,
                            "f000s_min": round(min(tr), 1) if tr else None,
                            "f000s_max": round(max(tr), 1) if tr else None,
                        }
                except Exception:  # noqa: BLE001
                    raw_e = None
            # no f_000_s means the BYPASS pass produced no cell total to
            # reconcile the per-void integrals against - report neither
            total_e = 0.0
            if raw_e and mask_obj.f_000_s:
                total_e = float(mask_obj.f_000_s)
                electrons = _consistent_void_electrons(mask_obj, gp, raw_e,
                                                       total_e)
            excl = list(mask_obj.exclude_void_flags)
            # pore geometry (chem.pores, R3.0 / R3.1): periodicity from the
            # flood-fill label grid, largest inscribed sphere from the vdW
            # surface. The flood-fill centre of mass is reported only for a
            # 0-D cavity: for a channel / layer / network it is the mean of
            # UNWRAPPED grid points and lies anywhere, even outside the
            # cell (D17) - the inscribed-sphere centre is defined for all.
            labels_np = mask_obj.mask.data.as_numpy_array()
            n_real = tuple(int(x) for x in mask_obj.crystal_gridding.n_real())
            step = grid_step_A(uc, n_real)
            for i in range(n_voids):
                topo = void_topology(labels_np, i + 2)
                pts = np.argwhere(labels_np == i + 2) / np.array(n_real, float)
                insc = inscribed_sphere(pts, uc, p1_frac, p1_els)
                dim = int(topo["dimensionality"])
                v: dict[str, Any] = {
                    "void": i + 1,
                    "volume_A3": round(void_vols[i], 1),
                    "masked": not excl[i],
                    "dimensionality": dim,
                    "directions": topo["directions"],
                    "n_components": topo["n_components"],
                    "inscribed_centre_frac": insc["centre_frac"],
                    "inscribed_radius_A": insc["radius_A"],
                    "lcd_A": insc["lcd_A"],
                    # inscribed_sphere refines its thinned scan back to the
                    # exact maximum over the void's grid points, so the
                    # resolution of lcd_A is the mask grid step itself - the
                    # old `step * stride**(1/3)` modelled a list stride as
                    # an isotropic one, which it never was
                    "grid_step_A": round(step, 3),
                    "lcd_exact": insc["exact"],
                    "nearest_atom": insc["nearest_atom"],
                }
                # pore-limiting diameter (R3.2): the free sphere that still
                # percolates, bisected over ALL paths; None for a cavity
                t_pld = time.monotonic()
                pld = pore_limiting_diameter(labels_np, i + 2, uc, p1_frac,
                                             p1_els)
                v["pld_A"] = pld["pld_A"]
                v["pld_error_A"] = pld["pld_error_A"]
                v["pld_directions"] = pld["pld_directions"]
                if pld.get("pld_note"):
                    v["pld_note"] = pld["pld_note"]
                # round-3 R5: the pore-limiting diameter ALONG each cell axis
                # (a channel can be wide along c and narrow along a), same
                # bisection constrained to percolate along that axis
                v.update(_pld_along_axes(
                    labels_np, i + 2, uc, p1_frac, p1_els, dim,
                    time.monotonic() - t_pld))
                if dim == 0:
                    v["centre_frac"] = [round(x, 3) for x in com[i]]
                else:
                    v["centre_frac"] = None
                    v["centre_note"] = (
                        f"a {dim}-D void has no centroid (the flood-fill "
                        "centre of mass is the mean of unwrapped grid "
                        "points): place labels at inscribed_centre_frac")
                if electrons is not None:
                    v["electrons"] = round(electrons[i], 1)
                    if round(raw_e[i], 1) != v["electrons"]:
                        v["electrons_bypass_raw"] = round(raw_e[i], 1)
                info["voids"].append(v)
            info["n_voids_masked"] = sum(1 for f in excl if not f)
            info["pore_note"] = (
                "dimensionality 0/1/2/3 = cavity / channel (directions [u v "
                "w]) / layer / 3-D network, from the periodic sewing of the "
                "mask grid; lcd_A = 2 x the largest sphere free of the van "
                "der Waals surface centred on a void grid point (Foster 2006 "
                "/ Zeo++ convention), error ~ grid_step_A; pld_A = 2 x the "
                "largest free-sphere radius whose threshold set still joins "
                "its own periodic image (bisection over ALL paths, so the "
                "sphere may detour), +- pld_error_A = the grid step used, "
                "None for a 0-D cavity; packing = Kitaigorodskii index and "
                "A^3 per non-H atom, occupancy-weighted, NOT 100 - solvent%")
            info["dropped_small_voids"] = dropped
            info["solvent_volume_A3"] = round(
                float(mask_obj.solvent_accessible_volume), 1)
            info["solvent_volume_pct_of_cell"] = round(
                100.0 * float(mask_obj.solvent_accessible_volume) / uc_vol, 1)
            if electrons is not None:
                info["total_solvent_electrons_per_cell"] = round(total_e, 1)
                if any("electrons_bypass_raw" in v for v in info["voids"]):
                    info["electron_count_note"] = (
                        "electrons_bypass_raw is the number the "
                        "solvent_mask report prints. smtbx integrates each "
                        "void over the difference map structure_factors() "
                        "left behind, and that map still carries the "
                        "uniform f_000_s/V the last BYPASS cycle added "
                        "over the void region, so every per-void count "
                        "comes back inflated by n_grid/(n_grid-n_solvent)."
                        " `electrons` has that offset removed and sums to "
                        "total_solvent_electrons_per_cell. The offset is "
                        "only there when the iteration ended on max_cycles "
                        "instead of converging - so whenever this note "
                        "appears BOTH numbers are still moving with "
                        "max_cycles; compare them with `recorded` before "
                        "reasoning on them.")
            # binarize the flood-fill labels (0 = crystal, >=2 = void ids) so
            # a fixed 0.5 isosurface always wraps every void. Voids the mask
            # EXCLUDED (below min_void_volume, or a negative electron count
            # inside the BYPASS loop) are cut out of the SURFACE but stay in
            # `voids` with masked=false - the isosurface is what refinement
            # applied, the list is what the probe found.
            info["gridding"] = list(mask_obj.crystal_gridding.n_real())
            info["map"] = info["n_voids_masked"] > 0
            if info["map"]:
                from scitbx.array_family import flex as sci_flex
                binary = mask_obj.mask.data.as_double()
                binary.set_selected(binary > 0.5, 1.0)
                for i, is_excluded in enumerate(excl):
                    if is_excluded:
                        binary.set_selected(mask_obj.mask.data == i + 2, 0.0)
                import iotbx.mrcfile
                iotbx.mrcfile.write_ccp4_map(
                    file_name=str(out_path),
                    unit_cell=uc,
                    space_group=xs.space_group(),
                    map_data=binary,
                    labels=sci_flex.std_string(
                        [f"crystalpilot voids node={node} probe="
                         f"{solvent_radius} shrink={shrink}"]))
        else:
            info["map"] = False
        if not info["map"]:
            # a stale surface from an earlier build would outlive its
            # metadata and keep being served by /wb/refine/voidmap
            out_path.unlink(missing_ok=True)
        (out_path.with_name("voids.json")).write_text(
            json.dumps(info), encoding="utf-8")
        return info


#: a full-path PLD slower than this skips the three axial bisections (they
#: cost about the same each); the product then says so instead of hanging
PLD_AXES_BUDGET_S = 15.0
_AXES = (("a", [1, 0, 0]), ("b", [0, 1, 0]), ("c", [0, 0, 1]))


def _pld_along_axes(labels_np, value: int, uc, p1_frac, p1_els, dim: int,
                    full_pld_seconds: float) -> dict[str, Any]:
    """{"pld_along": {"a": A | None, "b": ..., "c": ...},
    "pld_along_error_A": grid step} for a percolating void: the largest
    free sphere that still travels along THAT cell axis (None = the void
    does not percolate along it). Cavities (dim 0) get no entry; a void
    whose full PLD already blew the budget gets a note instead."""
    from ..chem.pores import pore_limiting_diameter

    if dim <= 0:
        return {}
    if full_pld_seconds > PLD_AXES_BUDGET_S:
        return {"pld_along_note": (f"skipped: the full-path PLD took "
                                   f"{full_pld_seconds:.0f} s, over the "
                                   f"{PLD_AXES_BUDGET_S:.0f} s budget for the "
                                   f"three axial runs")}
    out: dict[str, Any] = {}
    err = None
    for name, d in _AXES:
        try:
            r = pore_limiting_diameter(labels_np, value, uc, p1_frac, p1_els,
                                       directions=[d])
        except Exception as e:  # noqa: BLE001 - a per-axis number never fails the map
            out[name] = None
            out.setdefault("_errors", []).append(f"{name}: {type(e).__name__}")
            continue
        out[name] = r.get("pld_A")
        err = err or r.get("pld_error_A")
    res: dict[str, Any] = {"pld_along": {k: out.get(k) for k, _d in _AXES}}
    if err is not None:
        res["pld_along_error_A"] = err
    if out.get("_errors"):
        res["pld_along_note"] = "; ".join(out["_errors"])
    return res


def _build_geometric_void_ccp4(xs, node: str, out_path: Path, *,
                                meta: dict, parts=None,
                                binding_required: bool = False) -> dict[str, Any]:
    """Geometry-only preview. No BYPASS, Fobs, density or electron integration.

    Two callers land here and the difference matters to the reader: a
    CIF-only node HAS no observed reflections; a legacy node has reflections
    whose identity is unknown until bound (`binding_required`)."""
    import numpy as np
    from ..chem.guests import host_void_map
    from ..chem.pores import packing_index, pore_limiting_diameter

    uc = xs.unit_cell()
    step = max(0.3, (float(uc.volume()) / 2_000_000) ** (1 / 3),
               max(uc.parameters()[:3]) / 256)
    geom = host_void_map(xs, grid_step_A=step, parts=parts)
    p1 = xs.expand_to_p1()
    frac = np.array([sc.site for sc in p1.scatterers()]).reshape(-1, 3)
    elements = [_elem_sym(sc.scattering_type) for sc in p1.scatterers()]
    voids = []
    included = []
    for raw in geom["voids"]:
        keep = not raw["below_min_volume"]
        value = int(raw["id"]) + 1
        if keep:
            included.append(value)
        t_pld = time.monotonic()
        pld = pore_limiting_diameter(geom["labels"], value, uc, frac, elements)
        along = _pld_along_axes(geom["labels"], value, uc, frac, elements,
                                int(raw.get("dimensionality") or 0),
                                time.monotonic() - t_pld)
        voids.append({**raw, **pld, **along, "void": raw["id"],
                      "electrons": None, "masked": False, "surface": keep,
                      "grid_step_A": geom["grid_step_A"]})
    info = {
        "v": VOIDS_CACHE_V, "node": node,
        "source_state": {"node": node, "revision": meta.get("revision")},
        "mode": "geometric", "structure_only": not binding_required,
        "binding_required": binding_required,
        "electron_count_status": "binding_required" if binding_required else "unsupported",
        "total_solvent_electrons_per_cell": None,
        "electron_count_note": (
            "Reflection data binding is unknown for this legacy node: residual "
            "electrons are unavailable until matching HKL is bound explicitly "
            "(swap_reflection_data), not zero"
            if binding_required else
            "No observed reflections: residual electrons are unavailable, not zero"),
        "n_voids": len(voids), "voids": voids,
        "n_voids_masked": 0, "n_voids_displayed": len(included),
        "map": bool(included), "gridding": geom["gridding"],
        "grid_step_A": geom["grid_step_A"], "grid_source": geom["grid_source"],
        "params_source": "geometric_defaults",
        "mask_params": {"solvent_radius": geom["probe_A"],
                        "shrink_truncation_radius": geom["shrink_A"],
                        "grid_step_A": step,
                        "min_void_volume": geom["min_void_volume_A3"]},
        "solvent_radius": geom["probe_A"],
        "shrink_truncation_radius": geom["shrink_A"],
        "solvent_volume_A3": geom["solvent_volume_A3"],
        "solvent_volume_pct_of_cell": geom["solvent_volume_pct_of_cell"],
        "packing": packing_index(uc, frac, elements,
                                 occupancies=[sc.occupancy for sc in p1.scatterers()]),
        "pore_note": "Pure geometric accessible-volume preview of all model atoms; not a refinement solvent mask",
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if included:
        import iotbx.mrcfile
        from scitbx.array_family import flex
        binary = flex.double(np.isin(geom["labels"], included).astype(np.float64))
        iotbx.mrcfile.write_ccp4_map(
            file_name=str(out_path), unit_cell=uc, space_group=xs.space_group(),
            map_data=binary,
            labels=flex.std_string([f"crystalpilot geometric voids node={node}; no electron density"]))
    else:
        out_path.unlink(missing_ok=True)
    out_path.with_name("voids.json").write_text(json.dumps(info), encoding="utf-8")
    return info


def _consistent_void_electrons(mask_obj, gp, raw_e: list[float],
                               total_e: float) -> list[float]:
    """Per-void electron counts that sum to f_000_s (see mask_tools).

    Thin alias so the display path and the solvent_mask TOOL cannot drift:
    the same buffer-aliasing surplus has to come off both, or the picture
    and the number the agent reasons on disagree by ~5x.
    """
    from ..tools.mask_tools import consistent_void_electrons

    return consistent_void_electrons(mask_obj, gp, raw_e, total_e)


def cached_voids(project_dir: str | Path, node_id: str) -> tuple[Path, Path]:
    """(voids.ccp4, voids.json) for a node, built lazily. The ccp4 is absent
    when nothing was masked - no voids found at all, or every void below
    min_void_volume - so callers check voids.json's `map` first."""
    from .nodes import NodeStore

    project_dir = Path(project_dir)
    store = NodeStore(project_dir)
    node = _resolve_ref(store, node_id)
    ccp4 = cache_dir(project_dir, node) / "voids.ccp4"
    meta = cache_dir(project_dir, node) / "voids.json"
    from .structure_document import is_structure_only_node
    node_meta = store.node_meta(node)
    from .data_versions import DataBindingRequired, reflection_cache_source
    from .nodes import atomic_write_json
    try:
        source = reflection_cache_source(store, node)
    except DataBindingRequired:
        # a legacy node: its voids are geometry-only, keyed on the model
        # alone - the same form a CIF-only node gets (2026-09-08)
        source = {"schema": 1, "builder": "geometry-only-v1", "node": node,
                  "model_revision": node_meta.get("revision"),
                  "data_revision": None, "data_binding": "legacy_unknown",
                  "interpretation": {"engine": "cctbx", "data_view": "geometry_only"}}
    source_path = meta.with_suffix(".json.source.json")
    hit = _read_json(meta) or {}
    expected_geometric = (is_structure_only_node(node_meta)
                          or not node_meta.get("data_revision"))
    wrong_mode = expected_geometric != (hit.get("mode") == "geometric")
    missing_map = bool(hit.get("map")) and not ccp4.exists()
    if (not _voids_cache_current(meta) or wrong_mode or missing_map
            or _read_json(source_path) != source):
        build_void_ccp4(project_dir, node, ccp4)
        atomic_write_json(source_path, source)
    return ccp4, meta


def _voids_cache_current(meta: Path) -> bool:
    try:
        return json.loads(meta.read_text(encoding="utf-8")).get(
            "v") == VOIDS_CACHE_V
    except (OSError, ValueError, AttributeError):
        return False


def cached_data_block(project_dir: str | Path,
                      node_id: str) -> dict[str, Any]:
    """The reflection-data block (Rint / n_unique / d_min / completeness /
    space group / wavelength / HKLF / SHEL) for one node.

    Prefer recorded facts. A missing block may be computed only from the
    node's own bound observation revision, never from a current project HKL
    guessed to match old history. The source distinguishes recorded and newly
    computed evidence; node.json is not rewritten to repair missing provenance.
    """
    from .nodes import _data_block
    from .project import RefineProject

    project_dir = Path(project_dir)
    proj = RefineProject(project_dir)          # cheap: no cctbx, no merge
    node = _resolve_ref(proj.nodes, node_id)
    node_meta = proj.nodes.node_meta(node)
    from .structure_document import is_structure_only_node
    if is_structure_only_node(node_meta):
        return {"node": node, "source": "unavailable", "data": None,
                "mode": "structure_only",
                "note": "No observed reflections are attached to this model node"}
    recorded = node_meta.get("data")
    if recorded:
        return {"node": node, "source": "node", "data": recorded,
                "data_revision": node_meta.get("data_revision")}
    from .data_versions import DataVersions, DataBindingRequired, reflection_cache_source
    try:
        proj.hkl_path, _ = DataVersions(project_dir).for_node(node_meta)
        stamp = reflection_cache_source(proj.nodes, node)
    except DataBindingRequired as exc:
        return {"node": node, "source": "unavailable", "data": None,
                "data_revision": node_meta.get("data_revision"), "note": str(exc)}
    path = cache_dir(project_dir, node) / "data.json"
    hit = _read_json(path)
    if hit and hit.get("hkl_stamp") == stamp:
        return hit
    with _project_lock(project_dir):
        # the merge IS the cost here, and it is the same one _build_session
        # already runs for every other per-node display product
        proj._build_session(proj.nodes.node_dir(node) / "model.res")
        out = {
            "node": node, "source": "computed",
            "data": _data_block(proj.session),
            "hkl": (proj.hkl_path.name if proj.hkl_path else None),
            "hkl_stamp": stamp,
            "data_revision": node_meta.get("data_revision"),
            "note": "recomputed from this node's bound immutable reflection version",
        }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".tmp{os.getpid()}")
        tmp.write_text(json.dumps(out), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:  # a read-only cache dir must not fail the request
        pass
    return out


def _hkl_stamp(hkl_path: Path | None) -> str | None:
    """name:mtime:size of the project's reflection file - a recomputed data
    block is only valid for the data it was computed from, and
    swap_reflection_data is a thing users do mid-campaign."""
    try:
        st = hkl_path.stat()
    except (AttributeError, OSError):
        return None
    return f"{hkl_path.name}:{int(st.st_mtime)}:{st.st_size}"


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def cached_peaks(project_dir: str | Path, node_id: str) -> Path:
    """Q-peak table for a node (written alongside fofc.ccp4 by
    build_fofc_ccp4). Caches built before the peaks feature are healed by
    a rebuild of both products."""
    from .nodes import NodeStore

    project_dir = Path(project_dir)
    store = NodeStore(project_dir)
    node = _resolve_ref(store, node_id)
    from .structure_document import STRUCTURE_ONLY_PRECONDITION, is_structure_only_node
    if is_structure_only_node(store.node_meta(node)):
        raise ValueError(STRUCTURE_ONLY_PRECONDITION)
    from .data_versions import reflection_cache_source
    from .nodes import atomic_write_json
    source = reflection_cache_source(store, node)
    path = cache_dir(project_dir, node) / "peaks.json"
    from ..tools.twin_maps import MAP_ALGORITHM_VERSION
    source = {**source, "map_algorithm": MAP_ALGORITHM_VERSION}
    stamp = path.with_suffix(".json.source.json")
    if not path.exists() or _read_json(stamp) != source:
        build_fofc_ccp4(project_dir, node,
                        cache_dir(project_dir, node) / "fofc.ccp4")
        atomic_write_json(stamp, source)
        atomic_write_json(path.parent / "fofc.ccp4.source.json", source)
    return path
