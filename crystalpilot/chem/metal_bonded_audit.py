"""Geometry audit of the light atoms (C/N/O) bonded to metals.

pa2 (2026-09-02, cage-l0-r1/r2, cage-l2-r2): SHELXT's placeholder
composition "C H N O" hands out C and N labels by peak height; the agent
kept them, and the delivered CIFs carried 10-13 Zr-C at 2.1-2.6 A and 18
Zr-N <= 2.6 A (mu3-O/OH and carboxylate O in the reference), 30 N-N
"bonds" of 1.2-1.8 A, and eta5-Cp rings reported as five short contacts
plus an "unrecognised C4 fragment". No tool said so; the agent hid the
metal-bonded "carbons" in add_hydrogens' exclude list instead of retyping.

This is the missing check, and it is ELEMENT-GENERIC by design (the next
crystal is not a Zr6 cage): every distance fence is a covalent-radii sum
plus a tolerance, widened by the per-metal M-O/M-N donor window that
chem.knowledge already carries; pi ligands are recognised for any metal
and any ring size (closed C/N rings of 3-8 atoms, open eta2/eta3-type
fragments and broken rings); donor candidates follow the metal's usual
chemistry (hard: O / F- / Cl-; soft: S / halide / N). Real metal-carbon
chemistry (carbonyl, cyanide, alkynyl, sigma-alkyl/aryl, NHC) is told
apart from mislabelled donors by the atom's own skeleton: an O has no
carbon skeleton behind it, a carbonyl C is linear with a 1.1-1.2 A
partner, a carboxylate O is terminal on a trigonal carbon.

The audit never decides an element. It says what the geometry is
compatible with, ranks the candidates, and names what settles it (M-X
distance against the candidate windows, Ueq, omit-map electrons).

Pure function: audit_metal_bonded_light_atoms(xs, parts=None) -> dict.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

from .connectivity import covalent_radius
from .knowledge import is_metal, profile_for

# --- fences: covalent-radii sums plus tolerances, nothing element-specific --
_TOL_ORGANIC = 0.40        # X-Y (non-metal pair) bonded when d <= r_X + r_Y + 0.40
_MIN_ORGANIC = 0.60        # ... and d >= 0.60 x (r_X + r_Y): closer is a split site
_MX_EXTRA_CN = 0.25        # M-C / M-N bonded window upper: r_M + r_X + 0.25 ...
_MX_EXTRA_O = 0.30         # ... or the metal's donor window from chem.knowledge, whichever is wider
_MX_EXTRA_OTHER = 0.40
_MX_SHORT = 0.70           # below 0.70 x (r_M + r_X) a pair is an impossible contact, not a bond
_PI_LO, _PI_HI = -0.35, 0.40   # pi (face-on) window relative to r_M + r_C
_PI_EDGE_MAX = 1.50        # C/N-C/N distance joining two pi candidates (aromatic, alkene, alkyne, mislabelled)
_PI_EDGE_MIN = 1.00
_PI_PLANE_RMS = 0.15
_PI_TILT_MAX = 35.0        # ring normal vs centroid->metal (deg)
_PI_SPREAD_CLOSED = 0.45   # max-min M-C inside one ring (slipped rings tolerated)
_PI_SPREAD_OPEN = 0.50
_PI_SPREAD_ETA2 = 0.35
_PI_CENTROID_MIN = 1.20
_PI_OPEN_EXTRA = 0.15      # open fragments / eta2 need one M-C within r_M + r_C + 0.15
_PI_MAX_COMPONENT = 12     # bigger clusters of "ring" candidates are ghost clusters, not ligands
_SIGMA_C_EXTRA = 0.15      # a skeleton C is a sigma M-C donor only within r_M + r_C + 0.15
_LINEAR_DEG = 150.0
_TRIPLE_MAX = 1.25         # C=O / C=N / N=N / alkyne partner distance (A)
_DOUBLE_MAX = 1.32         # terminal atom on a trigonal carbon: C=O 1.20-1.27, C=N 1.27-1.30
_SINGLE_CO_MAX = 1.47      # C-O single 1.38-1.46 vs C-C single 1.48-1.56
_PLANAR_SUM_DEG = 350.0
_UEQ_COMPRESSED = 0.60
_NN_MIN, _NN_MAX = 1.10, 1.80
_CC_SHORT_MIN, _CC_SHORT_MAX = 1.15, 1.28
_RING_MAX = 6              # ring sizes examined for the N-N / ring-N rules
_CYCLE_STEP_BUDGET = 20000

#: donor atoms a metal is usually bound to, by metal class (candidates are
#: ranked; the audit lists them instead of writing "O" for everything)
_HARD_METALS = frozenset({
    "Li", "Na", "K", "Rb", "Cs", "Be", "Mg", "Ca", "Sr", "Ba", "Al", "Ga",
    "In", "Sc", "Y", "Ti", "Zr", "Hf", "V", "Nb", "Ta", "Cr", "Mo", "W",
    "La", "Ce", "Pr", "Nd", "Pm", "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er",
    "Tm", "Yb", "Lu", "Ac", "Th", "Pa", "U", "Np", "Pu", "Am", "Cm"})
_SOFT_METALS = frozenset({"Ag", "Au", "Hg", "Pd", "Pt", "Ir", "Os", "Rh",
                          "Ru", "Tl"})   # Cu stays borderline: paddlewheel O, Cu-N
_DONORS_HARD = ("O (oxo/mu-O/OH, carboxylate, aqua)", "F-/Cl-",
                "N (only behind a carbon skeleton)")
_DONORS_SOFT = ("S/Se (thiolate, thioether)", "Cl-/Br-/I-",
                "N (behind a carbon skeleton)", "O")
_DONORS_BORDERLINE = ("O (oxo/mu-O/OH, carboxylate, aqua)",
                      "N (behind a carbon skeleton)", "Cl-/Br-",
                      "S (thiolate/sulfide)")

NOTE = ("labels from SHELXT with a placeholder composition (C H N O) are "
        "heuristics, not element evidence; a metal-bonded atom's identity "
        "is decided by M-X distance, environment, Ueq and omit-map electrons")

_HALOGENS = frozenset({"F", "Cl", "Br", "I"})


def donor_candidates(metal_el: str) -> tuple[str, ...]:
    """Ranked donor atoms the metal is usually bound to (hard / soft /
    borderline classes; the placeholder composition only ever offers
    C/N/O, so the real answer is often outside it)."""
    el = metal_el.capitalize()
    if el in _HARD_METALS:
        return _DONORS_HARD
    if el in _SOFT_METALS:
        return _DONORS_SOFT
    return _DONORS_BORDERLINE


def _element_of(sc) -> str:
    el = sc.scattering_type.strip().capitalize().rstrip("+-0123456789")
    return "H" if el == "D" else el


def _atomic_number(el: str) -> int:
    try:
        from cctbx.eltbx import tiny_pse
        return int(tiny_pse.table(el).atomic_number())
    except Exception:  # noqa: BLE001 - unknown symbol: treat as light
        return 0


def _is_audit_metal(el: str) -> bool:
    return is_metal(el) and _atomic_number(el) >= 11


def _mx_window(m_el: str, x_el: str) -> tuple[float, float]:
    """[lo, hi] (A) inside which a non-H atom X is bonded to metal M:
    covalent-radii sum + tolerance, widened by the metal's O/N donor
    window from chem.knowledge when known (an O mislabelled C or N sits at
    the M-O distance, so the C/N windows must reach it). lo is the
    impossible-contact fence."""
    s = covalent_radius(m_el) + covalent_radius(x_el)
    lo = _MX_SHORT * s
    prof = profile_for(m_el)
    donor_hi = 0.0
    if prof is not None:
        donor_hi = prof.m_o_range[1]
        if prof.m_n_range:
            donor_hi = max(donor_hi, prof.m_n_range[1])
        donor_hi += 0.05
        lo = min(lo, prof.m_o_range[0] - 0.10)
    if x_el in ("C", "N"):
        hi = max(s + _MX_EXTRA_CN, donor_hi)
    elif x_el == "O":
        hi = max(s + 0.10, donor_hi) if prof is not None else s + _MX_EXTRA_O
    else:
        hi = max(s + _MX_EXTRA_OTHER, donor_hi)
    return lo, hi


def metal_bond_window(metal_el: str, x_el: str) -> tuple[float, float]:
    """Public accessor for the M-X bonded window [lo, hi] (A) the audit's
    verdicts refer to. Tools that act on those verdicts (add_hydrogens:
    a plausible_metal_bonds entry makes the metal a geometric neighbour)
    use it to tell which symmetry image of the metal the verdict is
    about, instead of re-deriving the rule."""
    return _mx_window(metal_el, x_el)


def _pi_window(m_el: str) -> tuple[float, float]:
    s = covalent_radius(m_el) + covalent_radius("C")
    return s + _PI_LO, s + _PI_HI


def _o_window_text(m_el: str) -> str:
    prof = profile_for(m_el)
    if prof is not None:
        return f"M-O {prof.m_o_range[0]:.2f}-{prof.m_o_range[1]:.2f}"
    s = covalent_radius(m_el) + covalent_radius("O")
    return f"M-O ~{s - 0.30:.2f}-{s + 0.10:.2f}"


def _halide_text(m_el: str) -> str:
    s = covalent_radius(m_el) + covalent_radius("Cl")
    return f"M-Cl ~{s - 0.30:.2f}-{s + 0.05:.2f}"


def _halide_floor(m_el: str) -> float:
    """Below this M-X distance a lone atom cannot be a chloride (bromide/
    iodide sit further out still)."""
    return covalent_radius(m_el) + covalent_radius("Cl") - 0.30


def _halide_reach(m_el: str) -> float:
    """Furthest M-X at which a lone atom may still be a metal-bound halide."""
    return covalent_radius(m_el) + covalent_radius("Cl") + 0.20


def _sites_of(hapticity: int) -> int:
    """Coordination sites an eta-n ligand occupies (the organometallic
    convention: Cp/arene = 3 fac sites, allyl/diene = 2, olefin = 1) -
    what the CN window of chem.knowledge, written for donor-atom counts,
    is compared with."""
    if hapticity >= 5:
        return 3
    if hapticity >= 3:
        return 2
    return 1


def _angle(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> float:
    """Angle a-b-c in degrees."""
    v1, v2 = a - b, c - b
    n1, n2 = np.linalg.norm(v1), np.linalg.norm(v2)
    if n1 < 1e-6 or n2 < 1e-6:
        return 0.0
    cosang = max(-1.0, min(1.0, float(np.dot(v1, v2) / (n1 * n2))))
    return float(np.degrees(np.arccos(cosang)))


def _fmt(label: str, d: float) -> str:
    return f"{label}:{d:.2f}"


class _Model:
    """ASU atoms with a symmetry-complete neighbour table."""

    def __init__(self, xs, parts: dict[str, int] | None, cutoff: float):
        from cctbx import sgtbx
        self.identity = sgtbx.rt_mx()
        self.uc = xs.unit_cell()
        scs = list(xs.scatterers())
        self.labels = [sc.label for sc in scs]
        self.elems = [_element_of(sc) for sc in scs]
        self.sites = [tuple(sc.site) for sc in scs]
        self.cart = [np.array(self.uc.orthogonalize(s)) for s in self.sites]
        self.ueq = [float(sc.u_iso_or_equiv(self.uc)) for sc in scs]
        # occupancy is the chemical site-occupation factor (cctbx keeps the
        # special-position multiplicity out of it); aniso says whether the
        # atom carries a refined ADP tensor rather than one u_iso
        self.occ = [float(sc.occupancy) for sc in scs]
        self.aniso = [bool(sc.flags.use_u_aniso()) for sc in scs]
        self.is_metal = [_is_audit_metal(e) for e in self.elems]
        part_of = {str(k).upper(): abs(int(v or 0)) for k, v in (parts or {}).items()}
        self.part = [part_of.get(lb.upper(), 0) for lb in self.labels]
        n = len(scs)
        # symmetry-complete pair table: all_interactions_from_inside_asu so
        # a metal on a special position sees every image of its ligands
        pat = xs.pair_asu_table(distance_cutoff=cutoff)
        pst = pat.extract_pair_sym_table(skip_j_seq_less_than_i_seq=False,
                                         all_interactions_from_inside_asu=True)
        self.nbrs: list[list[tuple[int, Any, float]]] = [[] for _ in range(n)]
        for i in range(n):
            for j, ops in pst[i].items():
                j = int(j)
                if self.part[i] and self.part[j] and self.part[i] != self.part[j]:
                    continue
                for op in ops:
                    d = float(self.uc.distance(self.sites[i], op * self.sites[j]))
                    if 0.2 < d <= cutoff:
                        self.nbrs[i].append((j, op, d))
        # skeleton (non-metal, non-H) neighbours, metal neighbours (inside
        # the bonded window / beyond it but inside a halide's reach), H count
        self.heavy: list[list[tuple[int, Any, float]]] = [[] for _ in range(n)]
        self.metals: list[list[tuple[int, Any, float]]] = [[] for _ in range(n)]
        self.far_metals: list[list[tuple[int, Any, float]]] = [[] for _ in range(n)]
        self.n_h = [0] * n
        for i in range(n):
            ei = self.elems[i]
            for j, op, d in self.nbrs[i]:
                ej = self.elems[j]
                if ej == "H":
                    if d <= covalent_radius(ei) + covalent_radius("H") + _TOL_ORGANIC:
                        self.n_h[i] += 1
                    continue
                if self.is_metal[j]:
                    if not self.is_metal[i] and ei != "H":
                        lo, hi = _mx_window(ej, ei)
                        if lo <= d <= hi:
                            self.metals[i].append((j, op, d))
                        elif hi < d <= _halide_reach(ej):
                            self.far_metals[i].append((j, op, d))
                    continue
                if self.is_metal[i] or ei == "H":
                    continue
                s = covalent_radius(ei) + covalent_radius(ej)
                if _MIN_ORGANIC * s <= d <= s + _TOL_ORGANIC:
                    self.heavy[i].append((j, op, d))

    def pos(self, j: int, op) -> np.ndarray:
        if op is None or op.is_unit_mx():
            return self.cart[j]
        return np.array(self.uc.orthogonalize(op * self.sites[j]))

    def compose(self, op_a, op_b):
        """Image op of a neighbour (op_b, relative to an ASU atom) seen
        from that atom's own image op_a."""
        if op_a is None or op_a.is_unit_mx():
            return op_b
        return op_a.multiply(op_b)

    def ring_sizes_through_edge(self, j: int, k: int, op_k,
                                max_size: int = _RING_MAX) -> set[int]:
        """Sizes of simple rings (<= max_size) of the skeleton graph that
        contain the edge j-(k image op_k); symmetry images walked in
        Cartesian space so a ring closing across a symmetry element is a
        ring too."""
        start = self.cart[j]
        sizes: set[int] = set()
        budget = [_CYCLE_STEP_BUDGET]

        def dfs(cur: int, cur_op, path: list[np.ndarray]) -> None:
            if budget[0] <= 0:
                return
            for n2, op2, _d in self.heavy[cur]:
                budget[0] -= 1
                op_n = self.compose(cur_op, op2)
                p = self.pos(n2, op_n)
                if n2 == j and np.linalg.norm(p - start) < 1e-3:
                    if len(path) >= 3:
                        sizes.add(len(path))
                    continue
                if len(path) >= max_size:
                    continue
                if any(np.linalg.norm(p - q) < 1e-3 for q in path):
                    continue
                dfs(n2, op_n, path + [p])

        dfs(k, op_k, [start, self.pos(k, op_k)])
        return sizes


def _simple_cycles(nodes: list[int], adj: dict[int, set[int]],
                   max_len: int = 8) -> list[list[int]]:
    """Simple cycles (3..max_len) of a small graph, each once."""
    cycles: list[list[int]] = []
    seen: set[frozenset] = set()
    steps = [0]

    def dfs(path: list[int]) -> None:
        if steps[0] > _CYCLE_STEP_BUDGET:
            return
        steps[0] += 1
        u = path[-1]
        for v in adj[u]:
            if v == path[0] and len(path) >= 3:
                key = frozenset(path)
                if key not in seen:
                    seen.add(key)
                    cycles.append(list(path))
            elif v > path[0] and v not in path and len(path) < max_len:
                dfs(path + [v])

    for start in sorted(nodes):
        dfs([start])
    return cycles


def _pi_geometry(points: np.ndarray, metal: np.ndarray, closed: bool
                 ) -> dict[str, Any] | None:
    """Face-on test: flat set of atoms, metal on the normal above the
    centroid, all M-X inside a narrow spread. None when not face-on."""
    n = len(points)
    dists = np.linalg.norm(points - metal, axis=1)
    spread = float(dists.max() - dists.min())
    if n == 2:
        if spread > _PI_SPREAD_ETA2:
            return None
        centroid = points.mean(axis=0)
        dc = float(np.linalg.norm(metal - centroid))
        if dc < _PI_CENTROID_MIN:
            return None
        return {"centroid_d": round(dc, 2), "plane_rms": 0.0, "tilt_deg": None,
                "m_x_range": [round(float(dists.min()), 2), round(float(dists.max()), 2)],
                "mean_m_x": round(float(dists.mean()), 2)}
    if spread > (_PI_SPREAD_CLOSED if closed else _PI_SPREAD_OPEN):
        return None
    centroid = points.mean(axis=0)
    x = points - centroid
    _, _, vt = np.linalg.svd(x, full_matrices=False)
    normal = vt[-1]
    rms = float(np.sqrt(np.mean((x @ normal) ** 2)))
    if rms > _PI_PLANE_RMS:
        return None
    dc = float(np.linalg.norm(metal - centroid))
    if dc < _PI_CENTROID_MIN:
        return None
    cosang = abs(float(np.dot(normal, (metal - centroid) / dc)))
    tilt = float(np.degrees(np.arccos(min(1.0, cosang))))
    if tilt > _PI_TILT_MAX:
        return None
    return {"centroid_d": round(dc, 2), "plane_rms": round(rms, 3),
            "tilt_deg": round(tilt, 1),
            "m_x_range": [round(float(dists.min()), 2), round(float(dists.max()), 2)],
            "mean_m_x": round(float(dists.mean()), 2)}


def _order_path(members: list[int], adj: dict[int, set[int]]) -> list[int]:
    """Members of a path graph in chain order (degree-1 end first)."""
    ends = [m for m in members if len(adj[m] & set(members)) == 1]
    if not ends:
        return sorted(members)
    order = [ends[0]]
    while len(order) < len(members):
        nxt = [v for v in adj[order[-1]] if v in members and v not in order]
        if not nxt:
            break
        order.append(nxt[0])
    return order


def _find_pi_ligands(model: _Model, i: int) -> list[dict[str, Any]]:
    """Face-on C/N ligands of metal i: closed rings (any size 3-8), open
    chains (eta3-allyl-type, broken rings) and eta2 C=C pairs."""
    m_el = model.elems[i]
    lo, hi = _pi_window(m_el)
    s_c = covalent_radius(m_el) + covalent_radius("C")
    metal_pos = model.cart[i]
    cands = [(j, op, d) for j, op, d in model.nbrs[i]
             if model.elems[j] in ("C", "N") and lo <= d <= hi
             and len(model.heavy[j]) <= 3]
    if len(cands) < 2:
        return []
    pos = [model.pos(j, op) for j, op, _ in cands]
    adj: dict[int, set[int]] = {a: set() for a in range(len(cands))}
    for a in range(len(cands)):
        for b in range(a + 1, len(cands)):
            dd = float(np.linalg.norm(pos[a] - pos[b]))
            if _PI_EDGE_MIN <= dd <= _PI_EDGE_MAX:
                adj[a].add(b)
                adj[b].add(a)
    # connected components
    seen: set[int] = set()
    comps: list[list[int]] = []
    for a in range(len(cands)):
        if a in seen or not adj[a]:
            continue
        stack, comp = [a], []
        seen.add(a)
        while stack:
            u = stack.pop()
            comp.append(u)
            for v in adj[u]:
                if v not in seen:
                    seen.add(v)
                    stack.append(v)
        comps.append(sorted(comp))
    found: list[dict[str, Any]] = []
    for comp in comps:
        if len(comp) > _PI_MAX_COMPONENT:
            continue
        chosen = None
        cycles = _simple_cycles(comp, adj)
        scored = []
        for cyc in cycles:
            pts = np.array([pos[a] for a in cyc])
            geom = _pi_geometry(pts, metal_pos, closed=True)
            if geom is not None:
                scored.append((geom["m_x_range"][1] - geom["m_x_range"][0],
                               geom["plane_rms"], -len(cyc), cyc, geom))
        if scored:
            scored.sort(key=lambda t: (t[0], t[1], t[2]))
            _s, _r, _n, cyc, geom = scored[0]
            chosen = (cyc, geom, True)
        else:
            # open fragment: a path (broken ring, allyl-type) of >= 3
            # sp2 atoms, or an eta2 C=C pair; must reach the sigma range
            path_like = all(len(adj[a] & set(comp)) <= 2 for a in comp)
            if path_like:
                order = _order_path(comp, adj)
                pts = np.array([pos[a] for a in order])
                dmin = float(np.linalg.norm(pts - metal_pos, axis=1).min())
                ok_len = len(order) >= 3 or (
                    len(order) == 2
                    and all(model.elems[cands[a][0]] == "C" for a in order)
                    and float(np.linalg.norm(pts[0] - pts[1])) <= 1.45)
                if ok_len and dmin <= s_c + _PI_OPEN_EXTRA:
                    geom = _pi_geometry(pts, metal_pos, closed=False)
                    if geom is not None:
                        chosen = (order, geom, False)
        if chosen is None:
            continue
        idx, geom, closed = chosen
        members = [(cands[a][0], cands[a][1]) for a in idx]
        n_labels = [model.labels[j] for j, _ in members if model.elems[j] == "N"]
        rec = {
            "metal": model.labels[i], "metal_element": m_el,
            "ring_labels": [model.labels[j] for j, _ in members],
            "ring_size": len(members), "hapticity": len(members),
            "ring_closed": closed,
            "mean_M_C": geom["mean_m_x"], "m_c_range": geom["m_x_range"],
            "centroid_d": geom["centroid_d"], "plane_rms": geom["plane_rms"],
            "tilt_deg": geom["tilt_deg"],
            "n_symmetry_images": sum(1 for _, op in members if not op.is_unit_mx()),
            "n_members_labelled_N": n_labels,
            "sites": _sites_of(len(members)),
            "_members": members,
        }
        if not closed:
            rec["note"] = ("open fragment - a Cp/arene ring missing atoms, or an "
                           "allyl/olefin-type ligand; complete the ring before "
                           "judging it")
        found.append(rec)
    return found


def _classify_light_atom(model: _Model, j: int, ueq_ratio: float | None,
                         pi_member: bool) -> dict[str, Any]:
    """What the skeleton of a metal-bonded C/N/O says about its identity.

    Returns {"verdict": "suspect"|"plausible"|"skeleton"|"none", ...}."""
    el = model.elems[j]
    mts = sorted(model.metals[j], key=lambda t: t[2])
    if not mts or pi_member:
        return {"verdict": "none"}
    m, op_m, d_m = mts[0]
    m_el = model.elems[m]
    hv = model.heavy[j]
    n_hv, n_m = len(hv), len(mts)
    x_pos = model.cart[j]
    m_pos = model.pos(m, op_m)
    s_mx = covalent_radius(m_el) + covalent_radius(el)
    cands = donor_candidates(m_el)
    settle = (f"decide by the M-X distance ({_o_window_text(m_el)}, "
              f"{_halide_text(m_el)} A), Ueq and omit-map electrons "
              f"(integrate_difference_density)")
    compressed = ueq_ratio is not None and ueq_ratio < _UEQ_COMPRESSED
    heavier_first = (f"Ueq is {ueq_ratio:.2f}x the metal's other light "
                     f"neighbours: more electrons here than {el} supplies - "
                     "try the heavier candidates first (O, then Cl-/Br-); "
                     if compressed else "")

    def suspect(sev: str, reason: str, suggestion: str, kind: str) -> dict:
        if compressed and sev != "high":
            sev = "high"
        return {"verdict": "suspect", "severity": sev, "reason": reason,
                "suggestion": heavier_first + suggestion, "kind": kind,
                "candidates": list(cands)}

    def plausible(kind: str) -> dict:
        return {"verdict": "plausible", "kind": kind}

    metals_txt = ", ".join(f"{model.labels[mm]} {dd:.2f} A" for mm, _, dd in mts)

    if el == "O":
        # rule 1d only: a lone O inside a halide's distance range with a
        # compressed Ueq is a halide's signature (a mu3-O at a short M-O
        # keeps its low Ueq legitimately - it is rigid, not heavy)
        if n_hv == 0 and compressed and d_m >= _halide_floor(m_el):
            return {"verdict": "suspect", "severity": "medium",
                    "kind": "lone_halide_candidate",
                    "reason": (f"lone O bonded only to metals ({metals_txt}) "
                               f"inside the M-Cl range, Ueq {ueq_ratio:.2f}x "
                               "the metal's other light neighbours"),
                    "suggestion": ("Cl-/Br- (or S2-) candidate: check omit-map "
                                   "electrons (integrate_difference_density) and "
                                   "Ueq before keeping it as O"),
                    "candidates": ["Cl-/Br-", "O"]}
        return {"verdict": "donor"}

    if el not in ("C", "N"):
        return {"verdict": "donor"}

    if n_hv == 0:
        if el == "C":
            sev = "high" if n_m >= 2 else "medium"
            alt = (f"the only carbon alternative is a terminal M-CH3/alkyl "
                   f"(M-C ~{s_mx - 0.30:.2f}-{s_mx + 0.05:.2f} A, normal Ueq); "
                   if n_m == 1 else
                   "a carbon bridging metals without a skeleton is not "
                   "organic chemistry; ")
            return suspect(
                sev,
                f"C with no C/N/O neighbour, bonded to {n_m} metal(s) "
                f"({metals_txt})",
                f"retype as one of {m_el}'s usual donors ({'; '.join(cands)}): "
                f"a mu-O/OH bridge, aqua/hydroxo O or a halide - {alt}{settle}",
                "isolated_c")
        sev = "high" if n_m >= 2 else "medium"
        alt = ("an ammine (NH3) ligand is the N alternative and looks exactly "
               "like aqua O by geometry; " if n_m == 1 else
               "a nitrogen bridging metals without a skeleton (nitride) is "
               "exotic; ")
        return suspect(
            sev,
            f"N with no carbon skeleton, bonded to {n_m} metal(s) ({metals_txt})",
            f"an N donor needs a carbon skeleton behind it - retype as one of "
            f"{m_el}'s usual donors ({'; '.join(cands)}): O (mu-O/OH, aqua) or "
            f"a halide - {alt}{settle}", "isolated_n")

    if n_hv == 1:
        k, op_k, d_xy = hv[0]
        y_el = model.elems[k]
        y_pos = model.pos(k, op_k)
        ang = _angle(m_pos, x_pos, y_pos)
        y_heavy = model.heavy[k]
        # linear M-X-Y with a short X-Y: carbonyl, cyanide, isocyanide,
        # nitrile (end-on), alkynyl, dinitrogen, nitrosyl
        if ang >= _LINEAR_DEG and d_xy <= _TRIPLE_MAX:
            kind = {"C": {"O": "carbonyl M-C=O", "N": "cyanide/isocyanide M-C=N",
                          "C": "alkynyl M-C=C"},
                    "N": {"C": "nitrile M-N=C (end-on)", "N": "dinitrogen/azide M-N=N",
                          "O": "nitrosyl M-N=O"}}[el].get(y_el, f"linear M-{el}-{y_el}")
            return plausible(kind)
        if el == "N" and y_el == "N" and d_xy <= _DOUBLE_MAX:
            # end-on azide: M-N-N bent at the bound N, N-N-N linear beyond it
            for k2, op2, d2 in y_heavy:
                if d2 <= 1.30:
                    p2 = model.pos(k2, model.compose(op_k, op2))
                    if k2 == j and np.linalg.norm(p2 - x_pos) < 1e-3:
                        continue
                    if _angle(x_pos, y_pos, p2) >= _LINEAR_DEG:
                        return plausible("azide/diazenido M-N-N=N")
        if y_el == "C" and d_xy <= _DOUBLE_MAX and len(y_heavy) >= 2:
            # terminal atom double-bonded to a trigonal carbon
            sibling = None
            for k2, op2, d2 in y_heavy:
                if model.elems[k2] in ("O", "N") and d2 <= _DOUBLE_MAX:
                    p2 = model.pos(k2, model.compose(op_k, op2))
                    if k2 == j and np.linalg.norm(p2 - x_pos) < 1e-3:
                        continue
                    sibling = (model.labels[k2], float(np.linalg.norm(p2 - x_pos)))
                    break
            if sibling is not None:
                return suspect(
                    "high",
                    f"terminal atom {d_xy:.2f} A from trigonal carbon "
                    f"{model.labels[k]} that carries another O/N "
                    f"({sibling[0]}, X...X' {sibling[1]:.2f} A): the "
                    f"carboxylate / nitro shape, bonded to {metals_txt}",
                    f"carboxylate (or nitrate) O labelled {el}: retype as O - "
                    f"{settle}", "carboxylate_o")
            return suspect(
                "medium",
                f"terminal atom {d_xy:.2f} A from trigonal carbon "
                f"{model.labels[k]} (M-X-C {ang:.0f} deg), bonded to {metals_txt}",
                (f"carbonyl / amide O labelled {el} (a C=C this short exists "
                 "only in allenes/ketenes)" if el == "C" else
                 f"carbonyl / amide O labelled N (a terminal imine =NH is the "
                 "N alternative)") + f" - {settle}", "carbonyl_o")
        if el == "C":
            if y_el == "C":
                if d_xy < _SINGLE_CO_MAX:
                    return suspect(
                        "medium",
                        f"C whose only skeleton bond is C-{model.labels[k]} "
                        f"{d_xy:.2f} A (M-C-C {ang:.0f} deg), bonded to {metals_txt}",
                        "alkoxide/phenoxide O labelled C (C-O 1.30-1.45 A), or "
                        "a vinyl/aryl carbon sigma-bonded to the metal - "
                        f"{settle}", "single_bond_c")
                return plausible(f"sigma-alkyl M-C (C-C {d_xy:.2f} A)")
            if y_el == "N":
                sibling = any(model.elems[k2] in ("O", "N") and d2 <= _DOUBLE_MAX
                              for k2, _o, d2 in y_heavy) and len(y_heavy) >= 2
                return suspect(
                    "high" if sibling else "medium",
                    f"C whose only skeleton bond is to N {model.labels[k]} "
                    f"{d_xy:.2f} A, bonded to {metals_txt}",
                    ("nitrate / nitro O labelled C" if sibling else
                     "N-oxide / oxime / nitrite O labelled C (an NHC carbene "
                     "carries TWO N)") + f" - {settle}", "n_bound_c")
            return suspect(
                "medium",
                f"C whose only skeleton bond is to {y_el} {model.labels[k]} "
                f"{d_xy:.2f} A, bonded to {metals_txt}",
                f"geometry does not support a metal-bonded carbon here; "
                f"candidates {'; '.join(cands)} - {settle}", "odd_c")
        # el == "N", one skeleton neighbour, not linear, not on a trigonal C
        if y_el == "C":
            return plausible(f"N donor with a carbon behind it (N-C {d_xy:.2f} A)")
        if y_el in ("N", "O"):
            return suspect(
                "high",
                f"N whose only skeleton bond is N-{y_el} {d_xy:.2f} A "
                f"({model.labels[k]}), bonded to {metals_txt}",
                "an N donor needs a carbon skeleton behind it: hydrazine / "
                "hydroxylamine bound this way are rare - a mislabelled O-C, "
                "O-N (nitrite) or two mislabelled ring carbons are far more "
                f"likely; candidates {'; '.join(cands)} - {settle}",
                "n_without_carbon")
        return plausible(f"N bound to {y_el}")

    # two or more skeleton neighbours: part of an organic skeleton
    if el == "C":
        if n_hv == 2 and d_m <= s_mx + _SIGMA_C_EXTRA:
            return plausible("sigma-aryl / carbene / ring carbon M-C")
        return {"verdict": "skeleton"}
    # N with a skeleton
    if n_hv == 2:
        both_c = all(model.elems[k] == "C" for k, _o, _d in hv)
        if both_c and all(d >= 1.38 for _k, _o, d in hv):
            k0, op0, _d0 = hv[0]
            if _RING_MAX in model.ring_sizes_through_edge(j, k0, op0):
                return suspect(
                    "medium",
                    f"six-ring N bound to {metals_txt} whose two ring bonds "
                    f"are {hv[0][2]:.2f}/{hv[1][2]:.2f} A (pyridine C-N 1.34; "
                    "1.39 is aromatic C-C)",
                    "aromatic C labelled N? - or a pyridine N at low "
                    "precision; retype only if Ueq and the ring's other "
                    "bonds agree", "ring_c_as_n")
        return {"verdict": "donor", "kind": "N donor (imine / pyridine / amido)"}
    if n_hv == 3:
        pts = [model.pos(k, op) for k, op, _d in hv]
        angle_sum = (_angle(pts[0], x_pos, pts[1]) + _angle(pts[1], x_pos, pts[2])
                     + _angle(pts[0], x_pos, pts[2]))
        if angle_sum >= _PLANAR_SUM_DEG:
            return suspect(
                "medium",
                f"planar three-connected N (angle sum {angle_sum:.0f} deg) "
                f"bonded to {metals_txt}",
                "a planar N with three bonds has no lone pair to give a "
                "metal: an aromatic C (or an amide N) labelled N, or a "
                "metal contact that is not a bond - retype only if Ueq and "
                "the ring geometry agree", "planar_n3")
        return {"verdict": "donor", "kind": "tertiary amine N"}
    return {"verdict": "skeleton"}


def audit_metal_bonded_light_atoms(xs, parts: dict[str, int] | None = None
                                   ) -> dict[str, Any]:
    """Symmetry-aware geometry audit of every light atom bonded to a metal.

    parts: optional {label: SHELX PART}; atoms in different non-zero PARTs
    never see each other (same semantics as chem.connectivity /
    refine.nodes.part_connectivity_kwargs).

    Returns {pi_ligands, suspect_elements, suspect_bonds,
    metal_environments, plausible_metal_bonds, summary, note}. Every
    entry names what the geometry is compatible with and what would
    settle it; nothing here is an element decision.
    """
    out: dict[str, Any] = {"pi_ligands": [], "suspect_elements": [],
                           "suspect_bonds": [], "metal_environments": [],
                           "plausible_metal_bonds": [],
                           "summary": "empty model", "note": NOTE}
    scs = list(xs.scatterers())
    if not scs:
        return out
    elems = [_element_of(sc) for sc in scs]
    metals_present = sorted({e for e in elems if _is_audit_metal(e)})
    lights_present = sorted({e for e in elems if not _is_audit_metal(e) and e != "H"})
    cutoff = 2.3
    for m in metals_present:
        cutoff = max(cutoff, _pi_window(m)[1])
        for x in lights_present:
            cutoff = max(cutoff, _mx_window(m, x)[1])
    cutoff = min(cutoff + 0.05, 4.0)
    model = _Model(xs, parts, cutoff)
    n = len(model.labels)

    # ---- pi ligands ---------------------------------------------------
    pi_of_metal: dict[int, list[dict]] = {}
    pi_member_atoms: set[int] = set()
    for i in range(n):
        if not model.is_metal[i]:
            continue
        rings = _find_pi_ligands(model, i)
        if rings:
            pi_of_metal[i] = rings
            for r in rings:
                pi_member_atoms.update(j for j, _ in r["_members"])
    for i, rings in pi_of_metal.items():
        for r in rings:
            out["pi_ligands"].append({k: v for k, v in r.items() if k != "_members"})

    # ---- reference Ueq per metal: its light in-window neighbours --------
    light_ueq_of_metal: dict[int, list[float]] = {}
    for i in range(n):
        if not model.is_metal[i]:
            continue
        vals = []
        for j, _op, d in model.nbrs[i]:
            if model.elems[j] == "H" or model.is_metal[j]:
                continue
            lo, hi = _mx_window(model.elems[i], model.elems[j])
            if lo <= d <= hi:
                vals.append(model.ueq[j])
        light_ueq_of_metal[i] = vals

    def ueq_ratio(j: int, metal_list=None) -> float | None:
        ref = []
        for m, _op, _d in (metal_list if metal_list is not None else model.metals[j]):
            ref.extend(u for u in light_ueq_of_metal.get(m, []))
        # exclude the atom's own value(s)
        own = model.ueq[j]
        others = [u for u in ref if abs(u - own) > 1e-9] or ref
        if len(others) < 2:
            return None
        med = float(np.median(others))
        return round(own / med, 2) if med > 1e-6 else None

    # ---- light atoms bonded to metals -----------------------------------
    verdict: dict[int, dict[str, Any]] = {}
    for j in range(n):
        if model.is_metal[j] or model.elems[j] == "H" or not model.metals[j]:
            continue
        v = _classify_light_atom(model, j, ueq_ratio(j), j in pi_member_atoms)
        verdict[j] = v
        mts = sorted(model.metals[j], key=lambda t: t[2])
        m, _op, d_m = mts[0]
        if v["verdict"] == "suspect":
            out["suspect_elements"].append({
                "label": model.labels[j], "element": model.elems[j],
                "metal": model.labels[m], "metal_element": model.elems[m],
                "d": round(d_m, 3),
                "metals": [_fmt(model.labels[mm], dd) for mm, _o, dd in mts],
                "n_metals": len(mts),
                "n_skeleton_neighbours": len(model.heavy[j]),
                "neighbours": [_fmt(model.labels[k], dd) for k, _o, dd in model.heavy[j]],
                "n_h": model.n_h[j],
                "ueq": round(model.ueq[j], 4),
                "ueq_over_metal_light_neighbours": ueq_ratio(j),
                "kind": v["kind"], "severity": v["severity"],
                "reason": v["reason"], "suggestion": v["suggestion"],
                "candidates": v["candidates"],
            })
        elif v["verdict"] == "plausible":
            out["plausible_metal_bonds"].append({
                "metal": model.labels[m], "label": model.labels[j],
                "element": model.elems[j], "d": round(d_m, 3), "kind": v["kind"]})

    # rule 1d beyond the bonded window: a lone C/N/O sitting where only a
    # halide bonds, with a compressed Ueq, is a Cl-/Br- wearing a light
    # label (pa1 cage: "ghost" O with Ueq -0.001 on the published Cl-)
    extra_donors: dict[int, list[tuple[int, Any, float]]] = {}
    for j in range(n):
        if (j in verdict or model.is_metal[j] or model.elems[j] not in ("C", "N", "O")
                or model.heavy[j] or not model.far_metals[j]):
            continue
        ratio = ueq_ratio(j, model.far_metals[j])
        if ratio is None or ratio >= _UEQ_COMPRESSED:
            continue
        far = sorted(model.far_metals[j], key=lambda t: t[2])
        m, op, d_m = far[0]
        extra_donors.setdefault(m, []).append((j, op, d_m))
        out["suspect_elements"].append({
            "label": model.labels[j], "element": model.elems[j],
            "metal": model.labels[m], "metal_element": model.elems[m],
            "d": round(d_m, 3),
            "metals": [_fmt(model.labels[mm], dd) for mm, _o, dd in far],
            "n_metals": len(far), "n_skeleton_neighbours": 0, "neighbours": [],
            "n_h": model.n_h[j], "ueq": round(model.ueq[j], 4),
            "ueq_over_metal_light_neighbours": ratio,
            "kind": "lone_halide_candidate", "severity": "medium",
            "reason": (f"lone {model.elems[j]} beyond the M-{model.elems[j]} "
                       f"window but inside the M-Cl range ({model.labels[m]} "
                       f"{d_m:.2f} A), Ueq {ratio:.2f}x the metal's other light "
                       "neighbours"),
            "suggestion": ("Cl-/Br- counter-ion candidate: check omit-map "
                           "electrons (integrate_difference_density) and Ueq"),
            "candidates": ["Cl-/Br-", model.elems[j]],
        })

    # N labels inside a face-on ring: Cp/arene carbons wearing the
    # composition's N (eta5-pyrrolyl / eta6-pyridine complexes are rare)
    for i, rings in pi_of_metal.items():
        for r in rings:
            n_members = [(j, op) for j, op in r["_members"] if model.elems[j] == "N"]
            if not n_members:
                continue
            sev = "high" if len(n_members) >= 2 else "medium"
            for j, op in n_members:
                d_m = float(np.linalg.norm(model.pos(j, op) - model.cart[i]))
                out["suspect_elements"].append({
                    "label": model.labels[j], "element": "N",
                    "metal": model.labels[i], "metal_element": model.elems[i],
                    "d": round(d_m, 3),
                    "metals": [_fmt(model.labels[i], d_m)], "n_metals": 1,
                    "n_skeleton_neighbours": len(model.heavy[j]),
                    "neighbours": [_fmt(model.labels[k], dd)
                                   for k, _o, dd in model.heavy[j]],
                    "n_h": model.n_h[j], "ueq": round(model.ueq[j], 4),
                    "ueq_over_metal_light_neighbours": ueq_ratio(j),
                    "kind": "n_in_pi_ring", "severity": sev,
                    "reason": (f"N inside an eta{r['hapticity']} ring "
                               f"[{', '.join(r['ring_labels'])}] bound face-on "
                               f"to {model.labels[i]} (M-N {d_m:.2f} A)"),
                    "suggestion": ("Cp/arene carbons carry the placeholder "
                                   "composition's N labels: retype as C (an "
                                   "eta5-pyrrolyl / eta6-pyridine complex "
                                   "needs synthesis evidence); ring bond "
                                   "lengths and Ueq must agree after refinement"),
                    "candidates": ["C (ring carbon)"],
                })

    # ---- metal environments ----------------------------------------------
    for i in range(n):
        if not model.is_metal[i]:
            continue
        m_el = model.elems[i]
        rings = pi_of_metal.get(i, [])
        ring_images = {(j, str(op)) for r in rings for j, op in r["_members"]}
        s_c = covalent_radius(m_el) + covalent_radius("C")
        donors: list[tuple[str, str, float]] = []
        skeleton_contacts: list[str] = []
        for j, op, d in model.nbrs[i]:
            el = model.elems[j]
            if el == "H" or model.is_metal[j]:
                continue
            lo, hi = _mx_window(m_el, el)
            if not lo <= d <= hi:
                continue
            if (j, str(op)) in ring_images:
                continue
            v = verdict.get(j, {"verdict": "none"})
            if el == "C":
                if v["verdict"] == "suspect" or v["verdict"] == "plausible":
                    donors.append((model.labels[j], el, d))
                else:
                    skeleton_contacts.append(_fmt(model.labels[j], d))
                continue
            if el == "N" and v["verdict"] == "skeleton":
                skeleton_contacts.append(_fmt(model.labels[j], d))
                continue
            donors.append((model.labels[j], el, d))
        for j, _op, d in extra_donors.get(i, []):
            donors.append((model.labels[j] + "(halide?)", model.elems[j], d))
        donors.sort(key=lambda t: t[2])
        counts: dict[str, int] = {}
        for _lb, el, _d in donors:
            counts[el] = counts.get(el, 0) + 1
        if rings:
            counts["pi"] = len(rings)
        cn_atoms = len(donors) + sum(r["hapticity"] for r in rings)
        cn_ligands = len(donors) + len(rings)
        cn_sites = len(donors) + sum(r["sites"] for r in rings)
        prof = profile_for(m_el)
        expected = list(prof.cn_range) if prof else None
        # three-state (D9): None = no window for this element, NOT checked
        plausible_cn = (None if prof is None
                        else prof.cn_range[0] <= cn_sites <= prof.cn_range[1])
        env: dict[str, Any] = {
            "metal": model.labels[i], "element": m_el,
            "cn_atoms": cn_atoms, "cn_ligands": cn_ligands, "cn_sites": cn_sites,
            "cn": cn_sites,
            "donors": counts,
            "neighbours": ([_fmt(lb, d) for lb, _el, d in donors]
                           + [f"eta{r['hapticity']}-{'C' if not r['n_members_labelled_N'] else 'C/N'}"
                              f"{r['ring_size']}:{r['centroid_d']:.2f}" for r in rings]),
            "expected_cn": expected, "cn_plausible": plausible_cn,
            "h_excluded": True,
            "cn_convention": ("cn_sites = donor atoms + 3 per eta>=5 ring, 2 per "
                              "eta3/4, 1 per eta2 (what the CN window is compared "
                              "with); cn_ligands counts every eta ring once; "
                              "H never counted"),
        }
        if rings:
            env["pi_rings"] = [f"eta{r['hapticity']}-{r['ring_size']}-ring "
                               f"[{', '.join(r['ring_labels'])}] M-C "
                               f"{r['m_c_range'][0]}-{r['m_c_range'][1]} A"
                               + ("" if r["ring_closed"] else " (open fragment)")
                               for r in rings]
        if skeleton_contacts:
            env["skeleton_contacts_not_counted"] = sorted(skeleton_contacts)
        n_susp = [s["label"] for s in out["suspect_elements"]
                  if any(t.rsplit(":", 1)[0] == model.labels[i]
                         for t in s["metals"])]
        if n_susp:
            env["suspect_donors"] = n_susp
        out["metal_environments"].append(env)

    # ---- bonds: N-N outside azide/azole, carbonyl-length C-C ----------------
    suspect_idx = {s["label"] for s in out["suspect_elements"]}
    seen_pairs: set[tuple] = set()
    for j in range(n):
        ej = model.elems[j]
        if ej not in ("N", "C"):
            continue
        for k, op, d in model.heavy[j]:
            ek = model.elems[k]
            if k < j:
                continue
            if k == j:
                key = (j, j, min(str(op), str(op.inverse())))
                if key in seen_pairs:
                    continue
                seen_pairs.add(key)
            others_j = [(k2, op2, d2) for k2, op2, d2 in model.heavy[j]
                        if not (k2 == k and str(op2) == str(op))]
            inv = op.inverse()
            others_k = [(k2, op2, d2) for k2, op2, d2 in model.heavy[k]
                        if not (k2 == j and str(op2) == str(inv))]
            p_j, p_k = model.cart[j], model.pos(k, op)
            if ej == "N" and ek == "N" and _NN_MIN <= d <= _NN_MAX:
                rec = _judge_nn(model, j, k, op, d, p_j, p_k, others_j,
                                others_k, pi_member_atoms)
                if rec is not None:
                    out["suspect_bonds"].append(rec)
            elif ej == "C" and ek == "C" and _CC_SHORT_MIN <= d <= _CC_SHORT_MAX:
                if model.labels[j] in suspect_idx or model.labels[k] in suspect_idx:
                    continue        # the element verdict already names the fix
                bent = False
                for k2, op2, _d2 in others_j:
                    if _angle(p_k, p_j, model.pos(k2, op2)) < _LINEAR_DEG:
                        bent = True
                for k2, op2, _d2 in others_k:
                    if _angle(p_j, p_k, model.pos(k2, model.compose(op, op2))) < _LINEAR_DEG:
                        bent = True
                if not bent and (others_j or others_k):
                    continue        # alkyne, terminal or internal
                out["suspect_bonds"].append({
                    "a": model.labels[j], "b": model.labels[k], "d": round(d, 3),
                    "kind": "C-C", "severity": "medium",
                    "reason": (f"C-C {d:.2f} A is a carbonyl length, not a C-C "
                               "bond (an alkyne at 1.20 A is linear; C=C >= 1.31)"
                               + ("" if others_j or others_k else
                                  "; a lone C2 pair is an acetylide or a "
                                  "mislabelled diatomic (CO, CN-, N2)")),
                    "suggestion": ("one end is probably O (C=O 1.20-1.27 A) or a "
                                   "nitrile N (1.14-1.16 A): retype by geometry "
                                   "and re-refine"),
                })

    # ---- summary ------------------------------------------------------------
    susp = out["suspect_elements"]
    n_high = sum(1 for s in susp if s["severity"] == "high")
    n_cn_off = sum(1 for e in out["metal_environments"]
                   if e["cn_plausible"] is False)
    n_cn_unchecked = sum(1 for e in out["metal_environments"]
                         if e["cn_plausible"] is None)
    parts_txt = [
        f"{len(out['pi_ligands'])} eta-bound ring(s)/fragment(s)",
        f"{len(susp)} suspect element label(s) ({n_high} high)",
        f"{len(out['suspect_bonds'])} suspect bond(s)",
        f"{len(out['metal_environments'])} metal(s), {n_cn_off} with CN outside "
        "the plausible window"
        + (f", {n_cn_unchecked} with no CN window (not checked)"
           if n_cn_unchecked else "")]
    summary = "; ".join(parts_txt)
    top = sorted(susp, key=lambda s: (s["severity"] != "high", s["d"]))
    if top:
        t = top[0]
        summary += (f". Heaviest: {t['label']} ({t['element']}) {t['d']:.2f} A "
                    f"from {t['metal']} - {t['suggestion'].split(' - ')[0]}")
    out["summary"] = summary
    return out


def _judge_nn(model: _Model, j: int, k: int, op, d: float, p_j, p_k,
              others_j, others_k, pi_member_atoms: set[int]) -> dict | None:
    """The N-N bond rule: azide / N2 / azole exempt; everything else is
    graded by how much skeleton the two N carry."""
    a, b = model.labels[j], model.labels[k]
    base = {"a": a, "b": b, "d": round(d, 3), "kind": "N-N"}
    if j in pi_member_atoms and k in pi_member_atoms:
        return {**base, "severity": "high",
                "reason": "N-N edge inside a ring bound face-on to a metal",
                "suggestion": ("two Cp/arene carbons labelled N: retype both "
                               "as C and re-refine")}
    sizes = model.ring_sizes_through_edge(j, k, op)
    if 5 in sizes:
        return None                     # pyrazole / triazole / tetrazole
    if 6 in sizes:
        return {**base, "severity": "medium",
                "reason": f"N-N {d:.2f} A in a six-membered ring",
                "suggestion": ("pyridazine / tetrazine-type ring, or two "
                               "adjacent carbons of a benzene ring labelled N "
                               "(C-C 1.39 A fits): ring Ueq pattern and "
                               "substituents decide")}
    if d <= 1.15 and not others_j and not others_k:
        return None                     # dinitrogen
    # azide / diazo: linear at either N through a third short-bonded atom
    for k2, op2, d2 in others_j:
        if d2 <= 1.30 and _angle(p_k, p_j, model.pos(k2, op2)) >= _LINEAR_DEG:
            return None
    for k2, op2, d2 in others_k:
        if d2 <= 1.30 and _angle(p_j, p_k, model.pos(k2, model.compose(op, op2))) >= _LINEAR_DEG:
            return None
    generic = ("N-N bonds at 1.2-1.8 A outside azide/azole rings are almost "
               "always mislabelled C-C / C-N: retype by geometry")
    if d <= _DOUBLE_MAX and len(others_j) == 1 and len(others_k) == 1:
        return {**base, "severity": "medium",
                "reason": f"N=N {d:.2f} A with one substituent on each N",
                "suggestion": ("an azo linker (N=N 1.24-1.26 A) fits; a "
                               "mislabelled C=C (1.33 A) or C=N does too - "
                               + generic + " unless the azo group is known "
                               "from synthesis")}
    if d <= 1.50 and len(others_j) <= 1 and len(others_k) <= 1:
        return {**base, "severity": "medium",
                "reason": f"N-N {d:.2f} A, each N with at most one other neighbour",
                "suggestion": ("hydrazine / hydrazide / hydrazone (N-N 1.38-1.45 "
                               "A) fits; so does a mislabelled C-C / C-N chain - "
                               + generic + " unless the N-N unit is known from "
                               "synthesis; Ueq and H-bonding decide")}
    return {**base, "severity": "high",
            "reason": (f"N-N {d:.2f} A with skeleton neighbours on the N "
                       f"({len(others_j)} / {len(others_k)}); a three-connected "
                       "N-N exists only in azoles"),
            "suggestion": generic}
