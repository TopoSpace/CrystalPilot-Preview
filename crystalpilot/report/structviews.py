"""Multi-view / multi-state structure renderer for agent vision.

Design context (user directive 2026-08-31): the engine model reads
images, so give it what a human crystallographer looks at before
deciding - the structure from several angles and in several states,
because one view of one state (e.g. just the ASU) can badly misrepresent
the situation. Server-side, no browser: orthographic projection drawn
with matplotlib from the session model directly.

States:
  asu        - the refined asymmetric unit as-is
  cell       - P1 expansion, one unit cell (packing, coordination closes)
  supercell  - 2x2x2 packing (voids/channels/stacking become visible)

Bonds come from the one bonding truth (`chem.bonding.bond_table`, plan
R2.1 migration 2): symmetry-exact, PART-aware when the session's PART
keywords are passed, classified (coordination / eta / metal_metal drawn
like covalent bonds; a chelate-bite carbon or a La...C(arene) contact is
not a bond). The packed states place every finite molecule WHOLE by its
centroid (the viewer's `refine.scene._wrapped_groups`), so a molecule
sitting on a cell face is no longer torn into two half-molecules.

Views: down the real axes a/b/c plus an oblique direction. Depth-sorted
ball-and-stick, Jmol-ish element colors, unit-cell edges for the packed
states, metal labels, per-image caption with cell/space group.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from ..chem.bonding import element_of, is_metal_element
from ..chem.connectivity import covalent_radius

#: Jmol-style element colors (hex), fallback handled in _color()
_ELEMENT_COLORS = {
    "H": "#FFFFFF", "D": "#FFFFC0", "B": "#FFB5B5", "C": "#909090",
    "N": "#3050F8", "O": "#FF0D0D", "F": "#90E050", "Na": "#AB5CF2",
    "Mg": "#8AFF00", "Al": "#BFA6A6", "Si": "#F0C8A0", "P": "#FF8000",
    "S": "#FFFF30", "Cl": "#1FF01F", "K": "#8F40D4", "Ca": "#3DFF00",
    "Ti": "#BFC2C7", "V": "#A6A6AB", "Cr": "#8A99C7", "Mn": "#9C7AC7",
    "Fe": "#E06633", "Co": "#F090A0", "Ni": "#50D050", "Cu": "#C88033",
    "Zn": "#7D80B0", "Ga": "#C28F8F", "Ge": "#668F8F", "As": "#BD80E3",
    "Se": "#FFA100", "Br": "#A62929", "Rb": "#702EB0", "Sr": "#00FF00",
    "Y": "#94FFFF", "Zr": "#94E0E0", "Nb": "#73C2C9", "Mo": "#54B5B5",
    "Ru": "#248F8F", "Rh": "#0A7D8C", "Pd": "#006985", "Ag": "#C0C0C0",
    "Cd": "#FFD98F", "In": "#A67573", "Sn": "#668080", "Sb": "#9E63B5",
    "Te": "#D47A00", "I": "#940094", "Cs": "#57178F", "Ba": "#00C900",
    "La": "#70D4FF", "Ce": "#FFFFC7", "Nd": "#C7FFC7", "Eu": "#61FFC7",
    "Gd": "#45FFC7", "Tb": "#30FFC7", "Dy": "#1FFFC7", "Er": "#00E675",
    "Yb": "#00BF38", "Lu": "#00AB24", "Hf": "#4DC2FF", "Ta": "#4DA6FF",
    "W": "#2194D6", "Re": "#267DAB", "Os": "#266696", "Ir": "#175487",
    "Pt": "#D0D0E0", "Au": "#FFD123", "Hg": "#B8B8D0", "Pb": "#575961",
    "Bi": "#9E4FB5", "Th": "#00BAFF", "U": "#008FFF",
}

def _color(el: str) -> str:
    return _ELEMENT_COLORS.get(el, "#FF69B4")


_MAX_BONDS = 4000


def _expand(xs, state: str, part_kwargs: dict | None = None):
    """(cart_xyz Nx3, elements, labels, cell_corners_cart or None,
    instances [(i_seq, rt_mx), ...], BondTable).

    The instances are the same closure the viewer draws: the ASU as-is, or
    every symmetry image packed into the origin cell (2x2x2 cells for the
    supercell) with finite molecules wrapped whole by their centroid."""
    from cctbx import sgtbx

    from ..chem.bonding import bond_table
    from ..refine.scene import _Instances, _translation, _wrapped_groups

    uc = xs.unit_cell()
    scs = list(xs.scatterers())
    table = bond_table(xs, part_kwargs=part_kwargs)
    inst = _Instances(xs)
    if state == "asu":
        identity = sgtbx.rt_mx()
        for i in range(len(scs)):
            inst.add(i, identity)
        corners = None
    else:
        pst = table.as_pair_sym_table()
        n_cell = 1 if state == "cell" else 2
        base_ops = [io for grp in _wrapped_groups(xs, scs, pst) for io in grp]
        for ta in range(n_cell):
            for tb in range(n_cell):
                for tc in range(n_cell):
                    tr = _translation(ta, tb, tc)
                    for i, g in base_ops:
                        inst.add(i, tr.multiply(g))
        corners = np.array([
            uc.orthogonalize((i * n_cell, j * n_cell, k * n_cell))
            for i in (0, 1) for j in (0, 1) for k in (0, 1)])
    pts = np.array([uc.orthogonalize(site) for _i, _op, site in inst.items]
                   ).reshape(-1, 3)
    elems = [table.elements[i] for i, _op, _s in inst.items]
    labels = [table.labels[i] for i, _op, _s in inst.items]
    return pts, elems, labels, corners, inst, table


def _bonds(table, inst, max_n: int = _MAX_BONDS) -> list[tuple[int, int, str]]:
    """[(idx, jdx, kind)] over the drawn instances: every classified edge
    whose both endpoints are drawn (the viewer's closure rule)."""
    from cctbx import sgtbx

    out: list[tuple[int, int, str]] = []
    seen: set[tuple[int, int]] = set()
    for idx, (i, op, _site) in enumerate(inst.items):
        for e in table.by_atom(i):
            op2 = op.multiply(sgtbx.rt_mx(e.op))
            jdx = inst.lookup(e.j, op2 * inst.scs[e.j].site)
            if jdx is None or jdx == idx:
                continue
            key = (min(idx, jdx), max(idx, jdx))
            if key in seen:
                continue
            seen.add(key)
            out.append((key[0], key[1], e.kind))
            if len(out) >= max_n:
                return out
    return out


_CELL_EDGES = [(0, 1), (0, 2), (0, 4), (1, 3), (1, 5), (2, 3), (2, 6),
               (3, 7), (4, 5), (4, 6), (5, 7), (6, 7)]


def _view_matrix(uc, view: str) -> np.ndarray:
    """Rotation putting the requested direction along +z (depth)."""
    O = np.array(uc.orthogonalization_matrix()).reshape(3, 3)
    axes = {"a": O @ (1, 0, 0), "b": O @ (0, 1, 0), "c": O @ (0, 0, 1),
            "oblique": O @ (1.0, 0.7, 0.4)}
    z = np.array(axes.get(view, axes["oblique"]), float)
    z /= np.linalg.norm(z)
    ref = np.array([0.0, 0.0, 1.0]) if abs(z[2]) < 0.9 \
        else np.array([0.0, 1.0, 0.0])
    x = np.cross(ref, z)
    x /= np.linalg.norm(x)
    y = np.cross(z, x)
    return np.stack([x, y, z])


def render_views(xs, out_dir: Path, state: str = "asu",
                 views: Sequence[str] = ("a", "b", "c", "oblique"),
                 highlight: Sequence[str] = (), stem: str = "view",
                 width_px: int = 900,
                 part_kwargs: dict | None = None) -> list[dict[str, Any]]:
    """Render the structure; returns [{path, state, view, caption}, ...].

    part_kwargs: the session's SHELX PART keywords
    (`refine.nodes.part_connectivity_kwargs`) so disorder alternatives are
    not drawn bonded to each other."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.collections import LineCollection

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    uc = xs.unit_cell()
    pts, elems, labels, corners, inst, table = _expand(xs, state, part_kwargs)
    bonds = _bonds(table, inst)
    if len(pts) == 0 and corners is None:
        # an atom-free model (data ingested, nothing solved yet) still has
        # a cell: draw the box so view_structure answers instead of failing
        corners = np.array([uc.orthogonalize((i, j, k))
                            for i in (0, 1) for j in (0, 1) for k in (0, 1)])
    hi = {str(h).strip().upper() for h in highlight}
    sg = str(xs.space_group_info())
    cellp = uc.parameters()
    cap_tail = (f"{sg} | a={cellp[0]:.2f} b={cellp[1]:.2f} c={cellp[2]:.2f} "
                f"al={cellp[3]:.1f} be={cellp[4]:.1f} ga={cellp[5]:.1f} | "
                f"{len(pts)} atoms drawn"
                + (" (cell box only)" if len(pts) == 0 else ""))
    out: list[dict[str, Any]] = []
    for view in views:
        R = _view_matrix(uc, view)
        p = pts @ R.T                       # x,y = screen, z = depth
        order = np.argsort(p[:, 2])         # far first
        fig_w = width_px / 100.0
        cc = corners @ R.T if corners is not None else None
        span_src = p if len(p) else cc      # atom-free: frame the cell
        span_x = span_src[:, 0].max() - span_src[:, 0].min() + 4
        span_y = span_src[:, 1].max() - span_src[:, 1].min() + 4
        fig_h = max(3.0, fig_w * span_y / max(span_x, 1e-6))
        fig, ax = plt.subplots(figsize=(fig_w, min(fig_h, fig_w * 1.4)),
                               dpi=100)
        ax.set_aspect("equal")
        ax.axis("off")
        if cc is not None:
            segs = [[cc[i][:2], cc[j][:2]] for i, j in _CELL_EDGES]
            ax.add_collection(LineCollection(
                segs, colors="#999999", linewidths=0.8, zorder=0))
        # bonds under atoms, split at midpoint for two-color halves
        segs, colors = [], []
        for i, j, _kind in bonds:
            mid = (p[i][:2] + p[j][:2]) / 2
            segs.append([p[i][:2], mid])
            colors.append(_color(elems[i]))
            segs.append([mid, p[j][:2]])
            colors.append(_color(elems[j]))
        ax.add_collection(LineCollection(
            segs, colors=colors, linewidths=1.4, zorder=1, alpha=0.9))
        scale = 260.0 / max(span_x, span_y)
        # ONE scatter call, points pre-sorted far-first (a per-atom artist
        # loop took ~6 s/view on a 3.4k-point supercell and held the MCP
        # serial lock for the whole render)
        radii = np.array([covalent_radius(e) * (0.45 if e not in ("H", "D")
                                                else 0.3) for e in elems])
        ax.scatter(p[order, 0], p[order, 1],
                   s=(radii[order] * scale) ** 2,
                   c=[_color(elems[k]) for k in order],
                   edgecolors="black", linewidths=0.4, zorder=2)
        # labels: metals always (ASU only, packed views get too busy),
        # highlighted atoms everywhere
        for k in range(len(pts)):
            lab = labels[k].strip().upper()
            want = lab in hi or (state == "asu" and is_metal_element(elems[k]))
            if want:
                ax.annotate(labels[k].strip(), (p[k, 0], p[k, 1]),
                            fontsize=7, fontweight="bold", zorder=10,
                            xytext=(3, 3), textcoords="offset points",
                            color="#B00020" if lab in hi else "#222222")
        ax.set_title(f"[{state}] view along {view} | {cap_tail}",
                     fontsize=7.5)
        path = out_dir / f"{stem}_{state}_{view}.png"
        fig.savefig(path, bbox_inches="tight", facecolor="white")
        plt.close(fig)
        out.append({"path": str(path), "state": state, "view": view,
                    "caption": f"[{state}] along {view}",
                    **({"cell_only": True} if len(pts) == 0 else {})})
    return out
