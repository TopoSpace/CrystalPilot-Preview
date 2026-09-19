"""Where the guests / counter-ions sit relative to the host framework
(round-2 R3.4): cage cavity, channel, inter-molecular cavity, interstitial.

WHY THE MASK IS BUILT FROM THE HOST ALONE.  A solvent mask of the WHOLE
model has no void where a guest is: the guest fills its own pore and the
region disappears.  So the region map is computed from the host atoms only
(`host_void_map`), and the guests are then located inside it.  The host
mask needs no reflection data - `cctbx.masks.around_atoms` +
`cctbx.masks.flood_fill` act on the model - so a data-less model, or one
whose data were never merged, still gets its pores; only the electron
counts (which need the structure-factor pass) are missing, and they are
not reported here.

MASK PARAMETERS.  Copied from `refine.scene.VOID_PREVIEW_DEFAULTS`, the
solvent_mask tool's schema defaults that `build_void_ccp4` shows in the
viewer, so a region here is the same region the user is looking at:
solvent (probe) radius 1.2 A, shrink truncation radius 1.2 A,
resolution_factor 0.25, min_void_volume 8 A^3.  Without reflection data
there is no d_min, so the grid is set by an explicit step (0.3 A by
default) instead of by resolution; pass `d_min` to reproduce the viewer's
resolution-based gridding exactly.  The step actually used is reported.

WHAT "IN A REGION" MEANS.  `around_atoms` marks a grid point as solvent
when it is farther than (r_vdW + probe) from every atom, then the shrink
truncation grows that region back by 1.2 A.  With the default 1.2/1.2 the
outer boundary of a region therefore sits about r_vdW from an isolated
atom, while the CONNECTIVITY of the regions (what is one pore and what is
two) is still decided by where the 1.2 A probe can roll.  That asymmetry
is the whole content of `interstitial`: a crevice the probe cannot roll
into and that is not within the shrink radius of anywhere it can.

FRAGMENT INSTANCES, NOT FRAGMENT TYPES.  The cage test asks whether the
wall of a region belongs to ONE molecule.  `connectivity._fragment_census`
collapses the symmetry copies of a molecule into one entry with `copies`,
which is the wrong unit here: a channel drilled through a stack of copies
of one macrocycle would be "95 % one fragment" and yet is no cage.  So the
share is counted per INSTANCE (`F1#0`, `F1#1`, ... - one physical molecule
each), grouped by the bonding truth (`chem.bonding.bond_table`): two atom
images are joined when the truth lists an edge between their ASU atoms at
exactly that distance.  `enclosing_fragment_keys` carries the per-type
share as well, so both readings are visible.

Every classification carries the criterion text (`criteria`, the plan's
definitions verbatim) and the measured numbers; nothing here emits a
verdict word beyond the four site labels.
"""
from __future__ import annotations

from typing import Any, Sequence

import numpy as np

# ---------------------------------------------------------------- defaults --
#: refine.scene.VOID_PREVIEW_DEFAULTS (the solvent_mask tool's schema
#: defaults). Kept in step with the viewer on purpose - a region reported
#: here must be a region the user can see.
DEFAULT_PROBE_A = 1.2
DEFAULT_SHRINK_A = 1.2
DEFAULT_RESOLUTION_FACTOR = 0.25
DEFAULT_MIN_VOID_VOLUME_A3 = 8.0

#: grid step used when there is no d_min (the no-reflection-data route).
#: Everything grid-derived carries an error of one step; it is reported.
DEFAULT_GRID_STEP_A = 0.3

#: share of a region's enclosing atoms that must belong to ONE 0-D host
#: fragment instance before the region is called a cage cavity (plan 3.4)
CAGE_SHARE = 0.95

#: a 0-D fragment with at least this share of the largest host fragment's
#: atoms is host too (a second independent cage / macrocycle), not a guest
HOST_MIN_FRACTION = 0.5

#: tolerance on "this image pair is the bonded pair the truth lists"
_BOND_MATCH_TOL_A = 1e-3

SITES = ("cage_cavity", "channel", "cavity", "interstitial")

#: PLAN-2026-09-04-round2 section 3.4, verbatim - the definitions travel
#: with every answer so a reader never has to trust the label alone.
CRITERIA_VERBATIM: dict[str, str] = {
    "host": '宿主 = `role=="main"` 片段 + 维度 ≥1 的片段 + 原子数不少于最大宿主片段 50% 的片段（第二个独立的笼/大环是宿主，不是客体），其余为客体',
    "cage_cavity": "`cage_cavity`（宿主掩膜区域的包围原子 ≥95% 属同一个 0D "
                   "片段 → 笼内）",
    "channel": "`channel`（区域 dim ≥1）",
    "cavity": "`cavity`（dim=0 且不能归于单一分子 → 宿主分子之间）",
    "interstitial": "`interstitial`（不在任何 ≥ `min_void_volume` 的区域内 → "
                    "1.2 Å 探针滚不进的缝隙）",
}

CRITERIA_EN: dict[str, str] = {
    "host": ('host = the fragments whose census role is "main", plus every '
             "fragment periodic in >= 1 direction; everything else is a guest"),
    "cage_cavity": ("the enclosing atoms of the host-mask region are >= 95 % "
                    "from a single 0-D host fragment INSTANCE - inside that "
                    "molecule"),
    "channel": "the region is periodic in >= 1 direction",
    "cavity": ("a 0-D region that cannot be attributed to one molecule - "
               "between host molecules"),
    "interstitial": ("the guest centroid lies in no region of at least "
                     "min_void_volume - a crevice the 1.2 A probe cannot roll "
                     "into"),
}

_ORDER = ("interstitial (is the centroid in a region at all?) -> channel "
          "(region dimensionality >= 1) -> cage_cavity (>= 95 % of the "
          "region's enclosing atoms from one 0-D fragment instance) -> "
          "cavity (the remaining 0-D regions). A finite molecule cannot "
          "enclose a periodic region, so channel before cage_cavity only "
          "fixes the order of two tests that never both pass.")

_MASK_SOURCE = ("cctbx.masks.around_atoms + cctbx.masks.flood_fill on the "
                "HOST atoms only, with refine.scene.VOID_PREVIEW_DEFAULTS "
                "(the solvent_mask tool's schema defaults the viewer shows); "
                "no reflection data is used, so no electron counts")

_ENCLOSING_RULE = ("for every region grid point on the region's surface (a "
                   "6-neighbour outside it), the host atom image with the "
                   "smallest d - r_vdW; the share is the count of DISTINCT "
                   "such atom images per host fragment instance")


# ------------------------------------------------------------------ helpers --

def _element(scattering_type: str) -> str:
    from .knowledge import element_symbol
    return element_symbol(scattering_type)


def _vdw_radius(el: str) -> float:
    """cctbx van der Waals table, the one smtbx builds the mask with."""
    from cctbx.eltbx import van_der_waals_radii
    try:
        return float(van_der_waals_radii.vdw.table[el])
    except (KeyError, RuntimeError):
        return 2.0


def _selection_indices(xs, selection) -> list[int]:
    """None | bool mask | index sequence | label sequence -> ASU indices."""
    n = xs.scatterers().size()
    if selection is None:
        return list(range(n))
    items = list(selection)
    if items and isinstance(items[0], str):
        want = {s.upper() for s in items}
        return [i for i, sc in enumerate(xs.scatterers())
                if sc.label.upper() in want]
    if len(items) == n and all(isinstance(v, (bool, np.bool_)) for v in items):
        return [i for i, v in enumerate(items) if v]
    return sorted(int(v) for v in items)


def _select(xs, indices: Sequence[int]):
    from scitbx.array_family import flex
    n = xs.scatterers().size()
    keep = flex.bool(n, False)
    for i in indices:
        keep[int(i)] = True
    return xs.select(keep)


def _sym_string(op, shift) -> str:
    """The operator string of the image `op * site + shift` ('x,y,z' for the
    stored atom, '-x+1,-y,-z' for an inversion image one cell over)."""
    from cctbx import sgtbx
    tr = sgtbx.rt_mx(sgtbx.rot_mx(),
                     sgtbx.tr_vec([12 * int(round(v)) for v in shift], 12))
    return str(tr.multiply(op))


def _wrap(delta: np.ndarray) -> np.ndarray:
    """Fractional difference folded into [-0.5, 0.5) - the minimum image."""
    return delta - np.round(delta)


class _Cloud:
    """Every symmetry image of every atom of `xs` in the 3x3x3 block of cells
    around the origin cell: Cartesian coordinates, the ASU atom each came
    from, and enough bookkeeping to name the operator that made it.

    Same reach as `refine.tools_probe._expanded_cart` (all ops x 27 cells);
    that helper drops the operator, which this module has to report, so the
    expansion is repeated here with the operator kept.
    """

    def __init__(self, xs) -> None:
        uc = xs.unit_cell()
        ops = list(xs.space_group().all_ops())
        scs = list(xs.scatterers())
        ortho = np.array(uc.orthogonalization_matrix(), float).reshape(3, 3)
        sites = np.array([[float(v) for v in sc.site] for sc in scs],
                         float).reshape(-1, 3)
        shifts = np.array([(dx, dy, dz) for dx in (-1, 0, 1)
                           for dy in (-1, 0, 1) for dz in (-1, 0, 1)], float)
        frac_rows, atom_rows, op_rows, tr_rows = [], [], [], []
        seen: set[tuple] = set()
        for k, op in enumerate(ops):
            r = np.array(op.r().as_double(), float).reshape(3, 3)
            t = np.array(op.t().as_double(), float)
            img = sites @ r.T + t
            wrap = np.floor(img)
            base = img - wrap
            for sh in shifts:
                for i in range(len(sites)):
                    f = base[i] + sh
                    key = (i, round(float(f[0]), 4), round(float(f[1]), 4),
                           round(float(f[2]), 4))
                    if key in seen:
                        continue
                    seen.add(key)
                    frac_rows.append(f)
                    atom_rows.append(i)
                    op_rows.append(k)
                    tr_rows.append(sh - wrap[i])
        self.xs = xs
        self.ops = ops
        self.frac = np.array(frac_rows, float).reshape(-1, 3)
        self.cart = self.frac @ ortho.T
        self.atom = np.array(atom_rows, int)
        self._op = np.array(op_rows, int)
        self._tr = np.array(tr_rows, float).reshape(-1, 3)
        self.elements = [_element(sc.scattering_type) for sc in scs]
        self.labels = [str(sc.label) for sc in scs]
        self.radii = np.array([_vdw_radius(e) for e in self.elements], float)

    def sym(self, row: int) -> str:
        return _sym_string(self.ops[int(self._op[row])], self._tr[row])

    def nearest(self, points_cart: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """(row index, d - r_vdW) of the image with the smallest van der
        Waals clearance for each query point. One KD-tree per element, as
        `chem.pores.inscribed_sphere` does - a single tree cannot see
        per-element radii."""
        from scipy.spatial import cKDTree

        q = np.asarray(points_cart, float).reshape(-1, 3)
        best = np.full(len(q), np.inf)
        best_row = np.zeros(len(q), int)
        el_of_row = np.array([self.elements[i] for i in self.atom], object)
        for el in sorted(set(self.elements)):
            rows = np.flatnonzero(el_of_row == el)
            if rows.size == 0:
                continue
            d, k = cKDTree(self.cart[rows]).query(q, k=1)
            free = d - _vdw_radius(el)
            better = free < best
            best[better] = free[better]
            best_row[better] = rows[k[better]]
        return best_row, best


def _instance_of_image(xs, cloud: _Cloud, parts) -> np.ndarray:
    """Connected-component id of every image in `cloud` - one component per
    physical molecule (per periodic net, for a framework).

    The ONLY bonding criterion is `chem.bonding.bond_table`: two images are
    joined when the truth lists an edge between their ASU atoms at exactly
    the distance they are apart. No cutoff is invented here.
    """
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    from scipy.spatial import cKDTree

    from .bonding import bond_table

    n = len(cloud.cart)
    table = bond_table(xs, parts)
    by_pair: dict[tuple[int, int], list[float]] = {}
    for e in table.edges:
        by_pair.setdefault((min(e.i, e.j), max(e.i, e.j)), []).append(float(e.d))
    if not by_pair:
        return np.arange(n)
    d_max = max(max(v) for v in by_pair.values())
    pairs = cKDTree(cloud.cart).query_pairs(d_max + _BOND_MATCH_TOL_A,
                                            output_type="ndarray")
    rows, cols = [], []
    for u, v in pairs:
        key = (min(int(cloud.atom[u]), int(cloud.atom[v])),
               max(int(cloud.atom[u]), int(cloud.atom[v])))
        cand = by_pair.get(key)
        if not cand:
            continue
        d = float(np.linalg.norm(cloud.cart[u] - cloud.cart[v]))
        if any(abs(d - x) < _BOND_MATCH_TOL_A for x in cand):
            rows.append(u)
            cols.append(v)
    if not rows:
        return np.arange(n)
    g = coo_matrix((np.ones(len(rows)), (rows, cols)), shape=(n, n))
    _n_comp, labels = connected_components(g, directed=False)
    return labels


def _surface(mask: np.ndarray) -> np.ndarray:
    """The region's own grid points that touch something else, wrapping at
    the cell faces (the mask grid is periodic)."""
    edge = np.zeros(mask.shape, bool)
    for axis in range(3):
        for step in (1, -1):
            edge |= mask & ~np.roll(mask, step, axis=axis)
    return edge


def _unwrap_region(region: np.ndarray, n_real, centre_frac
                   ) -> tuple[np.ndarray, np.ndarray, bool]:
    """(points, surface points, whole?) of a 0-D region as ONE contiguous
    body, in fractional coordinates that may leave [0, 1).

    D17 again, one level down: a cavity sitting on a cell corner is stored
    as eight pieces at eight corners of the grid. Counting its wall atoms
    piece by piece would find eight molecules where there is one, and the
    same cage would be called a cage or a cavity depending only on where
    the origin was put. The grid is rolled so the region's centre of mass
    sits at the middle of the array, which reassembles anything smaller
    than the cell, and the points are shifted back afterwards.
    """
    from scipy import ndimage

    n = np.array(n_real, int)
    idx_c = np.array([int(round(float(centre_frac[a]) % 1.0 * n[a])) % n[a]
                      for a in range(3)], int)
    shift = n // 2 - idx_c
    rolled = np.roll(region, tuple(int(v) for v in shift), axis=(0, 1, 2))
    comp, n_comp = ndimage.label(rolled)
    if n_comp < 1:
        return (np.zeros((0, 3)), np.zeros((0, 3)), True)
    sizes = np.bincount(comp.ravel(), minlength=n_comp + 1)[1:]
    keep = comp == (int(np.argmax(sizes)) + 1)
    whole = bool(keep.sum() == region.sum())
    pts = (np.argwhere(keep) - shift) / n.astype(float)
    surf = (np.argwhere(_surface(keep)) - shift) / n.astype(float)
    return pts, surf, whole


def _formula(el_counts: dict[str, int]) -> str:
    """Hill order: C, H, then alphabetical."""
    rest = sorted(e for e in el_counts if e not in ("C", "H"))
    order = [e for e in ("C", "H") if e in el_counts] + rest
    return "".join(e + (str(el_counts[e]) if el_counts[e] != 1 else "")
                   for e in order)


def _parts_dict(xs, parts, part_kwargs) -> dict[str, int] | None:
    """{label: signed PART} for `connectivity.analyze_connectivity`, from
    either form the callers already have. `part_kwargs` is converted by the
    one inverse there is (`chem.bonding.parts_from_part_kwargs`)."""
    from .bonding import parts_from_part_kwargs

    labels = [str(sc.label) for sc in xs.scatterers()]
    if parts is None and part_kwargs:
        parts = parts_from_part_kwargs(part_kwargs, len(labels))
    if parts is None:
        return None
    if isinstance(parts, dict):
        out = {str(k).upper(): int(v or 0) for k, v in parts.items()}
    else:
        vals = [int(v or 0) for v in parts]
        if len(vals) != len(labels):
            raise ValueError(f"parts has {len(vals)} entries for "
                             f"{len(labels)} atoms")
        out = {lb.upper(): v for lb, v in zip(labels, vals)}
    return out or None


# ------------------------------------------------------------ the void map --

def host_void_map(xs, host_selection=None, *,
                  probe_A: float = DEFAULT_PROBE_A,
                  shrink_A: float = DEFAULT_SHRINK_A,
                  grid_step_A: float | None = DEFAULT_GRID_STEP_A,
                  d_min: float | None = None,
                  resolution_factor: float = DEFAULT_RESOLUTION_FACTOR,
                  min_void_volume_A3: float = DEFAULT_MIN_VOID_VOLUME_A3,
                  host_fragments: list[dict] | None = None,
                  parts=None) -> dict[str, Any]:
    """Solvent-accessible regions of the HOST alone, with their periodicity
    and the host fragments that enclose each of them. No reflection data.

    xs               the whole model (ASU); `host_selection` picks the host
    host_selection   None (every atom) | bool mask | ASU indices | labels
    probe_A          solvent radius of `around_atoms` (viewer default 1.2)
    shrink_A         shrink truncation radius (viewer default 1.2)
    grid_step_A      explicit grid step; ignored when `d_min` is given
    d_min            when known, grid by resolution exactly as the viewer
                     does (resolution_factor 0.25) instead of by step
    host_fragments   [{"key", "asu_labels", "dimensionality"}] of the host,
                     as `locate_guests` derives them from
                     `connectivity.analyze_connectivity`; computed here when
                     not supplied
    parts            SHELX PARTs, {label: part} or one int per ASU atom

    Returns {"labels": (nx, ny, nz) int array (0 = host, >= 2 = region id
    + 1), "voids": [...], "grid_step_A", "probe_A", ...}. Each void carries
    `volume_A3`, `dimensionality` / `directions` (chem.pores.void_topology),
    the largest inscribed sphere (chem.pores.inscribed_sphere) and
    `enclosing_fragments` - the share of its enclosing atoms per host
    fragment INSTANCE, which is what the cage test needs.
    """
    from cctbx import masks, maptbx, sgtbx

    from .pores import grid_step_A as grid_step_of
    from .pores import inscribed_sphere, void_topology

    idx = _selection_indices(xs, host_selection)
    host = _select(xs, idx)
    uc = xs.unit_cell()
    uc_volume = float(uc.volume())
    p1 = host.expand_to_p1()
    if d_min:
        gridding = maptbx.crystal_gridding(
            unit_cell=uc, space_group_info=xs.space_group_info(),
            d_min=float(d_min), resolution_factor=float(resolution_factor),
            symmetry_flags=sgtbx.search_symmetry_flags(
                use_space_group_symmetry=False))
        grid_source = f"resolution (d_min {float(d_min):.2f} A, " \
                      f"resolution_factor {resolution_factor})"
    else:
        gridding = maptbx.crystal_gridding(
            unit_cell=uc, space_group_info=xs.space_group_info(),
            step=float(grid_step_A),
            symmetry_flags=sgtbx.search_symmetry_flags(
                use_space_group_symmetry=False))
        grid_source = f"step (requested {float(grid_step_A)} A)"
    n_real = tuple(int(v) for v in gridding.n_real())
    step = grid_step_of(uc, n_real)

    out: dict[str, Any] = {
        "labels": np.zeros(n_real, dtype=np.int32),
        "voids": [], "grid_step_A": step, "grid_source": grid_source,
        "gridding": list(n_real), "probe_A": float(probe_A),
        "shrink_A": float(shrink_A),
        "min_void_volume_A3": float(min_void_volume_A3),
        "n_host_atoms": len(idx), "n_host_atoms_p1": p1.scatterers().size(),
        "host_selection": [int(i) for i in idx],
        "mask_source": _MASK_SOURCE,
        "solvent_volume_A3": 0.0, "solvent_volume_pct_of_cell": 0.0,
    }
    if not idx:
        out["note"] = "no host atoms selected - no mask computed"
        return out

    radii = masks.vdw_radii(p1).atom_radii
    mask = masks.around_atoms(
        unit_cell=p1.unit_cell(),
        space_group_order_z=p1.space_group().order_z(),
        sites_frac=p1.sites_frac(), atom_radii=radii,
        gridding_n_real=n_real, solvent_radius=float(probe_A),
        shrink_truncation_radius=float(shrink_A))
    flood = masks.flood_fill(mask.data, uc)
    labels = mask.data.as_numpy_array()
    out["labels"] = labels
    n_voids = int(flood.n_voids())
    if n_voids == 0:
        return out

    n_grid = int(np.prod(n_real))
    per_void = flood.grid_points_per_void()
    volumes = [uc_volume * per_void[i] / n_grid for i in range(n_voids)]

    # host fragments -> which instance every atom image belongs to
    if host_fragments is None:
        host_fragments = _fragments_of(host, parts)
    frag_of_label: dict[str, str] = {}
    dim_of_key: dict[str, int] = {}
    for f in host_fragments:
        dim_of_key[f["key"]] = int(f.get("dimensionality", 0))
        for lb in f["asu_labels"]:
            frag_of_label[str(lb).upper()] = f["key"]
    cloud = _Cloud(host)
    comp = _instance_of_image(host, cloud, parts)
    inst_name = _name_instances(cloud, comp, frag_of_label)

    ortho = np.array(uc.orthogonalization_matrix(), float).reshape(3, 3)
    p1_frac = np.array([[float(v) for v in sc.site]
                        for sc in p1.scatterers()]).reshape(-1, 3)
    p1_els = [_element(sc.scattering_type) for sc in p1.scatterers()]

    com = flood.centres_of_mass_frac()
    for i in range(n_voids):
        value = i + 2
        region = labels == value
        topo = void_topology(labels, value)
        dim = int(topo["dimensionality"])
        whole = True
        if dim == 0:
            pts, surf, whole = _unwrap_region(region, n_real, com[i])
        else:
            # a periodic region has no single body to reassemble; its wall
            # is counted as gridded, and the cage share never decides a
            # channel anyway
            pts = np.argwhere(region) / np.array(n_real, float)
            surf = np.argwhere(_surface(region)) / np.array(n_real, float)
        insc = inscribed_sphere(pts, uc, p1_frac, p1_els)
        rows, _free = cloud.nearest(surf @ ortho.T)
        wall = sorted(set(int(r) for r in rows.tolist()))
        share: dict[str, float] = {}
        by_key: dict[str, float] = {}
        for r in wall:
            name = inst_name[int(comp[r])]
            share[name] = share.get(name, 0.0) + 1.0
            key = name.split("#")[0]
            by_key[key] = by_key.get(key, 0.0) + 1.0
        n_wall = float(len(wall)) or 1.0
        share = {k: round(v / n_wall, 4) for k, v in
                 sorted(share.items(), key=lambda kv: -kv[1])}
        by_key = {k: round(v / n_wall, 4) for k, v in
                  sorted(by_key.items(), key=lambda kv: -kv[1])}
        out["voids"].append({
            "id": i + 1,
            "volume_A3": round(float(volumes[i]), 1),
            "below_min_volume": bool(volumes[i] < min_void_volume_A3),
            "dimensionality": dim,
            "directions": topo["directions"],
            "n_components": topo["n_components"],
            "inscribed_centre_frac": insc["centre_frac"],
            "inscribed_radius_A": insc["radius_A"],
            "lcd_A": insc["lcd_A"],
            "centre_frac": ([round(float(x), 3) for x in com[i]]
                            if dim == 0 else None),
            "enclosing_atoms": len(wall),
            "enclosing_fragments": share,
            "enclosing_fragment_keys": by_key,
            "enclosing_rule": _ENCLOSING_RULE + (
                "" if dim == 0 else
                "; a periodic region is counted as gridded, one cell's worth "
                "of wall"),
            "reassembled": whole,
        })
    kept = [v["volume_A3"] for v in out["voids"] if not v["below_min_volume"]]
    out["solvent_volume_A3"] = round(float(sum(kept)), 1)
    out["solvent_volume_pct_of_cell"] = round(
        100.0 * float(sum(kept)) / uc_volume, 1)
    out["fragment_instances"] = sorted(set(inst_name.values()))
    out["fragment_dimensionality"] = dim_of_key
    return out


def _name_instances(cloud: _Cloud, comp: np.ndarray,
                    frag_of_label: dict[str, str]) -> dict[int, str]:
    """component id -> "<fragment key>#<n>", numbered by position so the
    name of a molecule does not depend on the traversal order."""
    members: dict[int, list[int]] = {}
    for row, c in enumerate(comp.tolist()):
        members.setdefault(int(c), []).append(row)
    entries = []
    for c, rows in members.items():
        keys = {frag_of_label.get(cloud.labels[int(cloud.atom[r])].upper(), "?")
                for r in rows}
        key = sorted(keys)[0] if keys else "?"
        centre = tuple(round(float(x), 3)
                       for x in cloud.frac[rows].mean(axis=0))
        entries.append((key, centre, c))
    entries.sort()
    out: dict[int, str] = {}
    seen: dict[str, int] = {}
    for key, _centre, c in entries:
        n = seen.get(key, 0)
        seen[key] = n + 1
        out[c] = f"{key}#{n}"
    return out


def _fragments_of(xs, parts) -> list[dict]:
    """[{"key", "asu_labels", "dimensionality", ...}] for every unique bonded
    fragment of `xs`, straight from `connectivity.analyze_connectivity`
    (keys F1, F2, ... in census order: largest first)."""
    from .connectivity import analyze_connectivity

    rep = analyze_connectivity(xs, parts=parts)
    labels_of: dict[frozenset, list[str]] = {}
    dim_of: dict[frozenset, int] = {}
    for f in rep.fragments:
        k = frozenset(f["asu_labels"])
        labels_of[k] = sorted(f["asu_labels"])
        dim_of[k] = max(dim_of.get(k, 0), int(f["dimensionality"]))
    out = []
    for n, c in enumerate(rep.fragment_census, start=1):
        k = None
        for cand in labels_of:
            if len(cand) == c["n_asu_labels"] and \
                    set(c["asu_labels"]) <= cand:
                k = cand
                break
        if k is None:
            continue
        out.append({
            "key": f"F{n}", "asu_labels": labels_of[k],
            "dimensionality": dim_of[k], "n_atoms": int(c["n_atoms"]),
            "copies": int(c["copies"]), "role": c["role"],
            "identity": c.get("identity"),
            "formula": _formula(c["elements"]),
            "elements": dict(c["elements"]),
        })
    return out


# ------------------------------------------------------------ guest siting --

def locate_guests(xs, *, parts=None, part_kwargs: dict | None = None,
                  probe_A: float = DEFAULT_PROBE_A,
                  shrink_A: float = DEFAULT_SHRINK_A,
                  grid_step_A: float | None = DEFAULT_GRID_STEP_A,
                  d_min: float | None = None,
                  resolution_factor: float = DEFAULT_RESOLUTION_FACTOR,
                  min_void_volume_A3: float = DEFAULT_MIN_VOID_VOLUME_A3,
                  max_contacts: int = 6,
                  host_min_fraction: float = HOST_MIN_FRACTION
                  ) -> dict[str, Any]:
    """Locate every guest / counter-ion in the host's void map.

    Host and guests come from `connectivity.analyze_connectivity`: role
    "main", every fragment periodic in >= 1 direction, AND every fragment
    with at least `host_min_fraction` of the largest host fragment's atoms
    is host (a second crystallographically independent cage molecule is
    host, not a guest sitting in the first one's channel - observed on a
    real Zr3 cage project); the rest are guests. The regions come from
    `host_void_map`, computed from the host alone so a guest cannot hide
    its own pore.

    parts / part_kwargs
        SHELX PART information in either form the callers hold. Atoms in
        different non-zero PARTs are disorder alternatives and never bond to
        each other, so a two-position guest stays two fragments instead of
        fusing into one.

    Returns {"criteria" (the plan's definitions verbatim + the numbers used),
    "host", "guests", "voids", "summary", "grid_step_A", "probe_A"}.
    Distances are in A to 3 decimals; `sym` is the operator of the host
    image, from the space group's own operators over a 27-cell block.
    """
    parts_d = _parts_dict(xs, parts, part_kwargs)
    fragments = _fragments_of(xs, parts_d)
    host_keys = [f["key"] for f in fragments
                 if f["role"] == "main" or f["dimensionality"] >= 1]
    n_big = max((f["n_atoms"] for f in fragments if f["key"] in host_keys),
                default=0)
    host_keys += [f["key"] for f in fragments
                  if f["key"] not in host_keys
                  and n_big > 0
                  and f["n_atoms"] >= host_min_fraction * n_big]
    host_frags = [f for f in fragments if f["key"] in host_keys]
    guest_frags = [f for f in fragments if f["key"] not in host_keys]

    label_index = {str(sc.label).upper(): i
                   for i, sc in enumerate(xs.scatterers())}
    host_idx = sorted(label_index[lb.upper()] for f in host_frags
                      for lb in f["asu_labels"] if lb.upper() in label_index)

    vmap = host_void_map(
        xs, host_idx, probe_A=probe_A, shrink_A=shrink_A,
        grid_step_A=grid_step_A, d_min=d_min,
        resolution_factor=resolution_factor,
        min_void_volume_A3=min_void_volume_A3,
        host_fragments=[{k: f[k] for k in
                         ("key", "asu_labels", "dimensionality")}
                        for f in host_frags],
        parts=_sub_parts(parts_d, xs, host_idx))

    out: dict[str, Any] = {
        "criteria": {
            "definitions": dict(CRITERIA_VERBATIM),
            "definitions_en": dict(CRITERIA_EN),
            "source": "PLAN-2026-09-04-round2 section 3.4 (verbatim)",
            "order": _ORDER,
            "probe_A": float(probe_A), "shrink_A": float(shrink_A),
            "grid_step_A": vmap["grid_step_A"],
            "grid_source": vmap["grid_source"],
            "min_void_volume_A3": float(min_void_volume_A3),
            "resolution_factor": float(resolution_factor),
            "cage_share": CAGE_SHARE,
            "mask_source": _MASK_SOURCE,
            "enclosing_share": _ENCLOSING_RULE,
            "assignment": ("a guest is placed by the CENTROID of its ASU "
                           "atoms; `atoms_in_regions` lists the region of "
                           "every atom, and `straddles_regions` is true when "
                           "they are not all the same, so a guest lying "
                           "across a window is visible instead of silently "
                           "rounded to one side"),
            "clearance": ("min over the guest's atoms of |x - host atom| - "
                          "r_vdW(host); negative means the guest atom is "
                          "inside a host van der Waals sphere"),
            "parts": ("PART numbers applied (atoms in different non-zero "
                      "PARTs never bond)" if parts_d else
                      "no PART information supplied"),
        },
        "host": {
            "fragments": [{k: f[k] for k in
                           ("key", "formula", "n_atoms", "copies",
                            "dimensionality", "role", "identity")}
                          for f in host_frags],
            "n_atoms": len(host_idx),
            "selection_rule": CRITERIA_VERBATIM["host"],
        },
        "guests": [],
        "guest_parts": [],
        "voids": vmap["voids"],
        "summary": {s: 0 for s in SITES},
        "grid_step_A": vmap["grid_step_A"],
        "probe_A": float(probe_A),
    }
    if not host_idx:
        out["criteria"]["note"] = (
            "no fragment qualifies as host - nothing to locate guests in")
        return out

    host_xs = _select(xs, host_idx)
    cloud = _Cloud(host_xs)
    uc = xs.unit_cell()
    n_real = tuple(vmap["gridding"])
    labels = vmap["labels"]
    void_by_id = {v["id"]: v for v in vmap["voids"]}
    ortho = np.array(uc.orthogonalization_matrix(), float).reshape(3, 3)

    for f in guest_frags:
        rec = _place_guest(xs, f, cloud, labels, n_real, ortho, uc,
                           void_by_id, label_index, min_void_volume_A3,
                           max_contacts, float(probe_A), float(shrink_A))
        rec["parts"] = sorted({int((parts_d or {}).get(str(lb).upper(), 0))
                               for lb in f["asu_labels"]})
        out["guests"].append(rec)
        out["summary"][rec["site"]] += 1
    out["guest_parts"] = sorted({p for g in out["guests"]
                                 for p in g["parts"] if p})
    if out["guest_parts"]:
        out["criteria"]["parts"] += (
            "; a guest modelled in two PARTs stays TWO fragments here - one "
            "per disorder component, each placed on its own - because the "
            "components carry different labels and the bonding truth never "
            "joins them. `parts` on each guest says which component it is")
    return out


def _sub_parts(parts_d: dict[str, int] | None, xs, idx: Sequence[int]):
    if not parts_d:
        return None
    keep = {str(xs.scatterers()[int(i)].label).upper() for i in idx}
    sub = {k: v for k, v in parts_d.items() if k in keep}
    return sub or None


def _place_guest(xs, frag: dict, cloud: _Cloud, labels: np.ndarray,
                 n_real, ortho: np.ndarray, uc, void_by_id: dict,
                 label_index: dict[str, int], min_void_volume_A3: float,
                 max_contacts: int, probe_A: float, shrink_A: float
                 ) -> dict[str, Any]:
    """One guest fragment: which region it sits in, and the numbers behind
    the call."""
    scs = list(xs.scatterers())
    rows = [label_index[lb.upper()] for lb in frag["asu_labels"]
            if lb.upper() in label_index]
    frac = np.array([[float(v) for v in scs[i].site] for i in rows],
                    float).reshape(-1, 3)
    # keep the fragment contiguous before averaging: a molecule split by the
    # cell boundary has no meaningful centroid otherwise
    frac = frac[0] + _wrap(frac - frac[0])
    centroid = frac.mean(axis=0)

    grid = np.array(n_real, int)

    def _region(f) -> int:
        ix = tuple(int(round(v)) % int(grid[a])
                   for a, v in enumerate(np.asarray(f, float) % 1.0 * grid))
        v = int(labels[ix])
        return v - 1 if v >= 2 else 0

    per_atom = {}
    for i, f in zip(rows, frac):
        per_atom[str(scs[i].label)] = _region(f)
    vid = vid_gridded = _region(centroid)
    void = void_by_id.get(vid)
    if void is not None and void["below_min_volume"]:
        # a region the mask found but dropped as too small is not a region
        # the plan's definitions know about - the guest is interstitial
        void, vid = None, 0

    cart = (frac @ ortho.T)
    near_rows, free = cloud.nearest(cart)
    contacts = []
    for k, i in enumerate(rows):
        r = int(near_rows[k])
        d = float(np.linalg.norm(cart[k] - cloud.cart[r]))
        contacts.append({"atom": str(scs[i].label),
                         "host_atom": cloud.labels[int(cloud.atom[r])],
                         "d": round(d, 3), "sym": cloud.sym(r),
                         "clearance_A": round(float(free[k]), 3)})
    contacts.sort(key=lambda c: c["d"])
    clearance = round(float(np.min(free)), 3) if len(free) else None

    # independent check of the same question, off the grid: the geometric
    # stand-in refine.tools_probe uses for the BYPASS flood fill (26
    # directions x two shells around the site, same vdW table). A
    # disagreement means the answer sits within a grid step of the region
    # boundary, and is reported rather than hidden.
    from ..refine.tools_probe import VOID_RULE, void_membership
    vm = void_membership(cloud.xs, [float(v) for v in centroid],
                         solvent_radius=probe_A, shrink=shrink_A)

    site, used, host_fragment = _classify(void, min_void_volume_A3)
    rec: dict[str, Any] = {
        "fragment": frag["key"], "formula": frag["formula"],
        "copies": frag["copies"], "n_atoms": frag["n_atoms"],
        "role": frag["role"], "identity": frag["identity"],
        "asu_labels": frag["asu_labels"][:12],
        "site": site, "void_id": vid or None,
        "host_fragment": host_fragment,
        "centroid_frac": [round(float(v % 1.0), 4) for v in centroid],
        "d_to_inscribed_centre_A": None,
        "nearest_host_contacts": contacts[:max_contacts],
        "clearance_A": clearance,
        "atoms_in_regions": per_atom,
        "straddles_regions": len(set(per_atom.values())) > 1,
        "criteria_used": used,
        "void_membership": {
            "inside": bool(vm["inside"]),
            "nearest_atom": vm["nearest_atom"],
            "nearest_d_A": vm["nearest_d_A"],
            # compared with the RAW grid label: void_membership knows
            # nothing about min_void_volume, so a region dropped for being
            # too small is not a disagreement
            "agrees_with_grid": bool(vm["inside"]) == (vid_gridded > 0),
            "rule": VOID_RULE,
        },
    }
    if void is not None:
        rec["region"] = {
            "id": void["id"], "volume_A3": void["volume_A3"],
            "dimensionality": void["dimensionality"],
            "directions": void["directions"],
            "inscribed_radius_A": void["inscribed_radius_A"],
            "enclosing_fragments": void["enclosing_fragments"],
        }
        centre = void["inscribed_centre_frac"]
        if centre is not None:
            delta = _wrap(np.array(centre, float) - centroid)
            rec["d_to_inscribed_centre_A"] = round(
                float(uc.length(tuple(float(v) for v in delta))), 3)
    return rec


def _classify(void: dict | None, min_void_volume_A3: float
              ) -> tuple[str, str, str | None]:
    """(site, the criterion text with the measured numbers, host fragment)."""
    if void is None:
        return ("interstitial",
                f"{CRITERIA_VERBATIM['interstitial']} | "
                f"{CRITERIA_EN['interstitial']}: the centroid lies in no "
                f"region of >= {min_void_volume_A3} A^3", None)
    dim = int(void["dimensionality"])
    share = void["enclosing_fragments"]
    top = next(iter(share.items()), (None, 0.0))
    if dim >= 1:
        return ("channel",
                f"{CRITERIA_VERBATIM['channel']} | {CRITERIA_EN['channel']}: "
                f"region {void['id']} is periodic in {dim} direction(s) "
                f"{void['directions']}", None)
    if top[0] is not None and top[1] >= CAGE_SHARE:
        return ("cage_cavity",
                f"{CRITERIA_VERBATIM['cage_cavity']} | "
                f"{CRITERIA_EN['cage_cavity']}: {100 * top[1]:.1f} % of the "
                f"{void['enclosing_atoms']} enclosing atoms of region "
                f"{void['id']} belong to {top[0]}", top[0])
    return ("cavity",
            f"{CRITERIA_VERBATIM['cavity']} | {CRITERIA_EN['cavity']}: "
            f"region {void['id']} is 0-D and its {void['enclosing_atoms']} "
            f"enclosing atoms split {share} - no single molecule reaches "
            f"{100 * CAGE_SHARE:.0f} %", None)
