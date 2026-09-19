"""Intermolecular interaction engine: one computation, three consumers.

The three consumers are

  * the VIEWER (`refine/scene.py` -> the layered interaction pills): needs
    display rows whose endpoints are materialized atom instances, plus the
    partner's symmetry code and position when the partner is not on screen;
  * `analyze_packing` (the R5 analysis tool): needs the symmetry-unique
    canonical table, so the number an agent quotes does not change when the
    user grows the picture;
  * the HTAB card / CIF path: needs the canonical hydrogen-bond table as
    `(donor, acceptor, symmetry operator)` triples, which `run_shelxl` turns
    into `EQIV $n <op>` + `HTAB D A_$n` so SHELXL - not this module -
    computes `_geom_hbond_*` WITH esds.

THE BOUNDARY RULE (the correctness point this module exists for).  Computing
interactions on the displayed instance set alone silently drops every partner
that happens to sit just outside it, so the surface of any view under-reports.
Instead:

  1. the displayed set (`range_atoms`, default = the asymmetric unit) is
     surrounded by a halo of every symmetry image within `halo_A` (8 A by
     default).  A halo is big enough when it covers the longest criterion
     plus the radius of the biggest ring/anion group, because a group only
     counts once all of its atoms are materialized; the value that structure
     actually needs is reported as `range.halo_advised_A` and
     `range.halo_sufficient` - it is never assumed;
  2. all searching happens on `range union halo`;
  3. only rows with AT LEAST ONE end inside `range` are emitted.  The other
     end carries `sym` (the operator string) and `xyz` (its cartesian
     position) so the viewer can draw a stub and an agent can quote it;
  4. every row carries `boundary: bool` - True when the partner is not in
     `range` - and `counts` carries `n_boundary`.  A caller that passes
     `halo_A=0` gets only the interactions internal to the displayed set,
     which is exactly the defect this rule fixes, made explicit.

CANONICAL vs DISPLAY.  `unique[kind]` is the symmetry-unique table keyed by
`(i_seq, j_seq, rt_mx)` (rings: `(ring_a, ring_b, rt_mx)`).  It is computed in
a separate pass over `ASU + shell` and is therefore INDEPENDENT of
`range_atoms` and `halo_A` - it is a property of the crystal.  `rows` is the
display table.  Both come out of the same geometry code (`_scan_*`), which is
the only way to guarantee the two tables cannot disagree; the plan allows the
canonical atom-pair table to come from `cctbx pair_asu_table` instead, but a
ring centroid cannot be expressed in a pair table, so a single tree-based path
serves both and `pair_asu_table` (through `smtbx.utils.connectivity_table`) is
used only for what it is good at: the covalent 1-2 / 1-3 exclusion sets and
the SHELX PART semantics.

H ATOMS.  `h_source` is a REQUIRED output field.  SHELXL riding hydrogens sit
at idealised X-ray bond lengths (~0.95-0.98 A) rather than neutron ones
(~1.09 A), so H...A distances from a riding model are systematically ~0.1-0.15
A too long and the D-H...A angle is imposed by the constraint, not measured.
Nothing downstream may quote a riding H...A distance without saying so.  When
the caller does not pass `h_source` this module infers `absent` if the model
has no H at all and otherwise reports `unknown` - it will not guess riding vs
refined without AFIX / `h_riding_meta` information.

PART awareness (D19): a donor in PART 1 never pairs with an acceptor in PART 2.
Comparison is on `abs(part)` so the SHELX negative-PART convention (which only
adds a symmetry-exclusion meaning) cannot change which alternatives interact.

INTRA / INTER.  `intra` on every row = the two ends belong to the same
bonded fragment of the asymmetric unit AND the row's operator is the
identity; a contact to another symmetry image of the same molecule is
intermolecular.  For a framework (a fragment that spans the cell) `intra`
means "within the same connected piece as written in the ASU", which is the
only meaning the ASU can carry.

Not attempted here, on purpose: esds (only
SHELXL has them), and rings that close THROUGH a symmetry element with a
repeated asymmetric-unit index - `find_rings` rejects those by construction
(its symmetry-composition check) and this module reports the limitation in
`criteria.pipi.ring_note` rather than inventing a second ring finder.  What
it does do is COUNT them (`_rings_through_symmetry` ->
`criteria.pipi.rings_closing_through_symmetry`), because "such rings can
exist" and "this structure has two of them, here they are" are different
statements and only the second lets a reader tell whether the pi-pi table in
front of them is complete.
"""
from __future__ import annotations

import itertools
import math
from typing import Any

# --------------------------------------------------------------------------
# element rules - all general, all from cctbx tables; no fixture ever appears
# --------------------------------------------------------------------------

KINDS: tuple[str, ...] = ("hbond", "pipi", "chpi", "chx", "halogen",
                          "anion_pi")

#: htab donor/acceptor elements (Olex2 `htab` treats these as polar).
HBOND_ELEMS = frozenset({"N", "O", "F", "Cl", "S", "Br"})
#: C-H...X acceptors.
CHX_ACCEPTOR_ELEMS = frozenset({"O", "N", "F", "Cl", "S"})
#: the C-H...X donor carrier is carbon by definition of the kind; a polar
#: carrier makes it a hydrogen bond and it is reported as one.
CHX_CARRIER_ELEMS = frozenset({"C"})
#: sigma-hole donors (F's sigma hole is not usable, so F is not one).
HALOGEN_DONOR_ELEMS = frozenset({"Cl", "Br", "I"})
#: Lewis bases a sigma hole can point at.
HALOGEN_ACCEPTOR_ELEMS = frozenset({"N", "O", "F", "P", "S", "Se",
                                    "Cl", "Br", "I"})
HYDROGEN = frozenset({"H", "D"})

#: van der Waals radius used when cctbx has no entry for the element; every
#: use of it is reported in `criteria[kind]["vdw_fallback_used"]`.
VDW_FALLBACK = 2.0

DEFAULT_CAP = 2000
DEFAULT_HALO_A = 8.0
#: hard ceiling on materialized instances, so a huge range + halo degrades
#: loudly (`range.work_truncated`) instead of swapping the machine.
MAX_WORK_INSTANCES = 400_000

#: exact status string for the degraded, hydrogen-free hydrogen bond.
NO_H_STATUS = "no_H_D···A_only"

_IDENTITY_STR = "x,y,z"

_SRC_OLEX2_HTAB = (
    "Olex2 `htab` defaults: donor D in {N,O,F,Cl,S,Br} carrying a bonded H, "
    "D...A <= 2.9 A, D-H...A >= 150 deg")
_SRC_STEINER = (
    "Steiner, Angew. Chem. Int. Ed. 41 (2002) 48 (PLATON's intermolecular "
    "convention): H...A within the sum of the van der Waals radii, "
    "D-H...A >= 110 deg - the widest defensible hydrogen bond")
_SRC_OLEX2_PIPI = (
    "Olex2 `pipi` defaults: centroid-centroid <= 4.0 A, angle between ring "
    "NORMALS <= 30 deg, slip <= 3.0 A; interpretation follows Janiak, "
    "J. Chem. Soc. Dalton Trans. (2000) 3885")
_SRC_NISHIO = (
    "Nishio, Phys. Chem. Chem. Phys. 13 (2011) 13873: H...Cg <= 3.2 A, "
    "C-H...Cg >= 120 deg, and the normal projection of H onto the ring plane "
    "inside the ring radius + 0.5 A")
_SRC_VDW_ANGLE = (
    "van der Waals overlap plus a directionality gate: H...A <= "
    "r_vdW(H)+r_vdW(A), C-H...A >= 120 deg")
_SRC_IUPAC_XB = (
    "IUPAC definition of the halogen bond, Desiraju et al., Pure Appl. Chem. "
    "85 (2013) 1711: X...Y <= r_vdW(X)+r_vdW(Y) with C-X...Y >= 155 deg, i.e. "
    "the acceptor on the sigma hole opposite the covalent bond")
_SRC_ANION_PI = (
    "anion-pi weak reading: anion centroid to ring centroid <= 4.5 A with the "
    "normal projection inside the ring radius; the anion is identified by "
    "chem.connectivity.fragment_identity (_FRAGMENT_SIGNATURES) and only a "
    "signature whose NAME carries a negative charge counts as an anion")
_SRC_VDW_TABLE = "cctbx.eltbx.van_der_waals_radii.vdw.table"
_SRC_RINGS = (
    "crystalpilot.tools.peak_chemistry.find_rings (chordless 5/6-rings whose "
    "composed symmetry operators return the identity - a lattice loop is not "
    "a ring) + its aromaticity test: every ring bond <= "
    "DELOCALISED_BOND_FRAC of the covalent-radius sum of its own element "
    "pair, rms from the best plane <= RING_PLANE_RMS_A")

_H_BIAS_NOTE = (
    "riding H: positions are constrained to idealised X-ray bond lengths "
    "(~0.95-0.98 A vs ~1.09 A from neutron data), so H...A is systematically "
    "0.1-0.15 A too long and D-H...A is imposed by the constraint, not "
    "measured - quote D...A, not H...A, from a riding model")


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------

def _elem(scattering_type: str) -> str:
    """Element symbol of a cctbx scattering type ('C1-' -> 'C', 'Cl' -> 'Cl')."""
    return "".join(c for c in scattering_type if c.isalpha())[:2].capitalize()


class _Vdw:
    """cctbx van der Waals radii with a counted fallback."""

    def __init__(self) -> None:
        from cctbx.eltbx import van_der_waals_radii
        self._t = van_der_waals_radii.vdw.table
        self.fallback_used: set[str] = set()

    def __call__(self, el: str) -> float:
        r = self._t.get(el)
        if r is None:
            self.fallback_used.add(el)
            return VDW_FALLBACK
        return float(r)


def _angle_deg(a, b, c) -> float:
    """Angle a-b-c in degrees from three cartesian points (vertex b)."""
    ux, uy, uz = a[0] - b[0], a[1] - b[1], a[2] - b[2]
    vx, vy, vz = c[0] - b[0], c[1] - b[1], c[2] - b[2]
    nu = math.sqrt(ux * ux + uy * uy + uz * uz)
    nv = math.sqrt(vx * vx + vy * vy + vz * vz)
    if nu < 1e-9 or nv < 1e-9:
        return float("nan")
    cos = (ux * vx + uy * vy + uz * vz) / (nu * nv)
    return math.degrees(math.acos(max(-1.0, min(1.0, cos))))


def _dist(a, b) -> float:
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2
                     + (a[2] - b[2]) ** 2)


def _site_key(i: int, site) -> tuple:
    """Instance key, same convention as scene._Instances (4-decimal frac)."""
    return (i, round(float(site[0]), 4), round(float(site[1]), 4),
            round(float(site[2]), 4))


def _as_op(op):
    from cctbx import sgtbx
    if isinstance(op, str):
        return sgtbx.rt_mx(str(op))
    return op


def _translation_op(t):
    from cctbx import sgtbx
    return sgtbx.rt_mx(sgtbx.rot_mx(),
                       sgtbx.tr_vec([12 * int(x) for x in t], 12))


def _canonical_pair_op(a: int, b: int, op):
    """Canonical (a, b, op) for a SYMMETRIC relation between two objects.

    "a at identity, b at op" is the same relation as "b at identity,
    a at op^-1"; the lower object id wins, and for a self-pair the
    lexicographically smaller operator string does."""
    if a < b:
        return a, b, op
    if a > b:
        return b, a, op.inverse()
    inv = op.inverse()
    return (a, b, op) if str(op) <= str(inv) else (a, b, inv)


# --------------------------------------------------------------------------
# model-level facts (parts, connectivity, rings, fragments) - computed once
# --------------------------------------------------------------------------

class _Model:
    """Everything about `xs` that does not depend on the displayed range."""

    def __init__(self, xs, parts=None) -> None:
        import numpy as np
        from cctbx import sgtbx

        self.xs = xs
        self.uc = xs.unit_cell()
        self.sg = xs.space_group()
        self.scs = list(xs.scatterers())
        self.n = len(self.scs)
        self.labels = [sc.label for sc in self.scs]
        self.elems = [_elem(sc.scattering_type) for sc in self.scs]
        self.is_h = [e in HYDROGEN for e in self.elems]
        self.identity = sgtbx.rt_mx()
        self.vdw = _Vdw()
        self.parts = _normalise_parts(parts, self.scs)
        self.frac = np.array([tuple(sc.site) for sc in self.scs],
                             dtype=float).reshape(self.n, 3)
        self.omx = np.array(self.uc.orthogonalization_matrix(),
                            dtype=float).reshape(3, 3)
        self.omx_inv = np.linalg.inv(self.omx)
        self.ops_all = list(self.sg.all_ops())

        self.pst = _pair_sym_table(xs, self.parts)
        self.excl = _exclusion_sets(self.pst)
        # bonded fragment of every atom (ASU-level union-find over the pair
        # table): an interaction whose ends share a fragment AND sit on the
        # identity operator is intramolecular; everything else is between
        # molecules / images (`intra` on every row)
        self.frag = _fragment_ids(self.n, self.pst)
        self.h_of, self.carrier_of = _hydrogen_maps(self.pst, self.is_h)
        self.n_h = sum(1 for f in self.is_h if f)
        # polar atoms that could be donors but carry no H: disclosed rather
        # than silently demoted to acceptors
        self.polar_without_h = [i for i in range(self.n)
                                if self.elems[i] in HBOND_ELEMS
                                and not self.h_of.get(i)]
        self.max_dh = _max_bond_to_h(self)
        self.rings, self.ring_note, self.rings_through_symmetry = \
            _ring_defs(self)
        self.ring_r_max = max((r["radius"] for r in self.rings), default=0.0)
        self.anions, self.anion_note = _anion_fragments(self)

    def ortho(self, frac):
        import numpy as np
        return np.asarray(frac, dtype=float) @ self.omx.T

    def ortho1(self, site):
        """Cartesian position of a single fractional site."""
        f0, f1, f2 = float(site[0]), float(site[1]), float(site[2])
        m = self.omx
        return (m[0, 0] * f0 + m[0, 1] * f1 + m[0, 2] * f2,
                m[1, 0] * f0 + m[1, 1] * f1 + m[1, 2] * f2,
                m[2, 0] * f0 + m[2, 1] * f1 + m[2, 2] * f2)

    def part_conflict(self, *seqs: int) -> bool:
        """True when two of the atoms belong to DIFFERENT non-zero PARTs.

        abs() so a negative SHELX PART (which only adds symmetry exclusion)
        is the same disorder component as its positive twin (D10/D19)."""
        seen = {abs(self.parts[s]) for s in seqs if self.parts[s]}
        return len(seen) > 1


def _normalise_parts(parts, scs) -> list[int]:
    """`parts` may be a per-scatterer list or a {label: part} mapping."""
    n = len(scs)
    if not parts:
        return [0] * n
    if isinstance(parts, dict):
        up = {str(k).upper(): int(v or 0) for k, v in parts.items()}
        return [int(up.get(sc.label.upper(), 0)) for sc in scs]
    out = [int(p or 0) for p in parts]
    if len(out) != n:
        raise ValueError(f"parts has {len(out)} entries for {n} scatterers")
    return out


def _pair_sym_table(xs, parts: list[int]):
    """Covalent connectivity with SHELX PART semantics (D19).

    smtbx's connectivity_table is the engine everywhere in this codebase; the
    conformer_indices / sym_excl_indices mapping is
    nodes.part_kwargs_from_parts, so PART handling cannot drift between the
    viewer and this module."""
    import smtbx.utils

    from ..refine.nodes import part_kwargs_from_parts
    kw = part_kwargs_from_parts(parts) if any(parts) else {}
    ct = smtbx.utils.connectivity_table(xs, **kw)
    return ct.pair_asu_table.extract_pair_sym_table(
        skip_j_seq_less_than_i_seq=False, all_interactions_from_inside_asu=True)


def _exclusion_sets(pst) -> list[set[tuple[int, str]]]:
    """Per atom i: the (j, op-string) pairs that are covalent 1-2 or 1-3.

    A donor's own bonded neighbour is not its acceptor, and neither is the
    third atom of an angle; same convention as scene._contact_sym_table."""
    out: list[set[tuple[int, str]]] = [set() for _ in range(len(pst))]
    for i in range(len(pst)):
        for j, ops in pst[i].items():
            for rt in ops:
                out[i].add((int(j), str(rt)))
                for k, ops2 in pst[j].items():
                    for rt2 in ops2:
                        out[i].add((int(k), str(rt.multiply(rt2))))
    return out


def _hydrogen_maps(pst, is_h: list[bool]):
    """h_of[i] = [(h_seq, op)] bonded H of atom i; carrier_of[h] = [(c, op)]."""
    h_of: dict[int, list[tuple[int, Any]]] = {}
    carrier_of: dict[int, list[tuple[int, Any]]] = {}
    for i in range(len(pst)):
        for j, ops in pst[i].items():
            j = int(j)
            for rt in ops:
                if is_h[j] and not is_h[i]:
                    h_of.setdefault(i, []).append((j, rt))
                elif is_h[i] and not is_h[j]:
                    carrier_of.setdefault(i, []).append((j, rt))
    return h_of, carrier_of


def _max_bond_to_h(mdl: _Model) -> float:
    best = 0.0
    for i, hs in mdl.h_of.items():
        for h, op in hs:
            best = max(best, float(mdl.uc.distance(mdl.scs[i].site,
                                                   op * mdl.scs[h].site)))
    return best or 1.15


# --------------------------------------------------------------------------
# rings: reuse peak_chemistry.find_rings and its aromaticity criteria
# --------------------------------------------------------------------------

#: sizes `find_rings` looks for, and therefore the sizes the
#: symmetry-closed census below has to reproduce
_RING_SIZES = (5, 6)
#: DFS budget of the symmetry-closed census, same shape as find_rings'
_SYM_RING_BUDGET = 20_000


def _heavy_graph(mdl: _Model) -> list[list[tuple]]:
    """graph[i] = [(j, op, d)] over heavy atoms, in find_rings' shape."""
    uc, scs = mdl.uc, mdl.scs
    graph: list[list[tuple]] = []
    for i in range(mdl.n):
        nb: list[tuple] = []
        if not mdl.is_h[i]:
            for j, ops in mdl.pst[i].items():
                j = int(j)
                if mdl.is_h[j]:
                    continue
                for op in ops:
                    d = float(uc.distance(scs[i].site, op * scs[j].site))
                    nb.append((j, op, d))
            nb.sort(key=lambda t: t[2])
        graph.append(nb)
    return graph


def _op_order(op, limit: int = 8) -> int | None:
    """Order of `op` in the space group, or None when it has none.

    A symmetry element with a screw / glide component never returns to the
    identity, so a cycle closing on one is a lattice loop, not a ring - the
    same distinction find_rings makes, carried one step further."""
    p = op
    for k in range(1, limit + 1):
        if p.is_unit_mx():
            return k
        p = p.multiply(op)
    return None


def _rings_through_symmetry(mdl: _Model, graph) -> list[dict[str, Any]]:
    """The rings `find_rings` cannot see, found by the same walk.

    A benzene sitting on an inversion centre appears in the asymmetric unit
    as three carbons whose cycle closes on `-x,-y,-z`: the composed operator
    is not the identity, so find_rings rejects it ("a lattice loop is not a
    ring").  This walk is the same walk, accepting exactly the closures
    find_rings drops: a NON-identity operator of finite order n whose n-fold
    repeat of an L-atom path is a ring of one of the sizes find_rings looks
    for.  Each record carries the walk (`_build`: the path and the operator
    accumulated at every path atom, plus the closing operator) so that
    `_ring_defs` can BUILD the whole ring from the operator's powers; the
    private key is stripped before the census is published as
    `criteria.pipi.rings_closing_through_symmetry`.

    Element-generic by construction: only bond topology and space-group
    operators are used."""
    found: dict[frozenset, dict[str, Any]] = {}
    left = [_SYM_RING_BUDGET]
    limit = max(_RING_SIZES)

    def walk(start: int, node: int, op, path: list[int], path_ops: list,
             visited: set) -> None:
        if left[0] <= 0:
            return
        for j, nop, _d in graph[node]:
            left[0] -= 1
            if left[0] <= 0:
                return
            composed = op.multiply(nop) if op is not None else nop
            if j == start:
                if composed.is_unit_mx():
                    continue                 # an ordinary ring: find_rings'
                n = _op_order(composed)
                if not n or n < 2 or len(path) * n not in _RING_SIZES:
                    continue
                key = frozenset((s, k) for k in range(n) for s in path)
                found.setdefault(key, {
                    "key": ",".join(mdl.labels[s] for s in path),
                    "size": len(path) * n,
                    "asu_atoms": len(path),
                    "op": str(composed), "op_order": n,
                    "_build": {"path": list(path), "walk_ops": list(path_ops),
                               "closure": composed}})
                continue
            if j in visited or len(path) >= limit:
                continue
            walk(start, j, composed, path + [j], path_ops + [composed],
                 visited | {j})

    for i in range(mdl.n):
        if not mdl.is_h[i]:
            walk(i, i, None, [i], [None], {i})
    return sorted(found.values(), key=lambda r: (r["size"], r["key"]))


def _ring_geometry(mdl: _Model, seqs: list[int], sites: list[tuple]):
    """Plane geometry + aromaticity of one ring given its atoms' fractional
    sites in a coherent frame; None when the plane is degenerate."""
    import numpy as np

    from ..chem.connectivity import covalent_radius
    from ..tools.peak_chemistry import DELOCALISED_BOND_FRAC, RING_PLANE_RMS_A

    uc = mdl.uc
    ratios, bonds = [], []
    for k in range(len(seqs)):
        a, b = sites[k], sites[(k + 1) % len(seqs)]
        d = float(uc.distance(a, b))
        pair = (covalent_radius(mdl.elems[seqs[k]])
                + covalent_radius(mdl.elems[seqs[(k + 1) % len(seqs)]]))
        bonds.append(d)
        ratios.append(d / pair if pair else 1.0)
    pts = mdl.ortho(np.array(sites, dtype=float))
    centroid = pts.mean(axis=0)
    centred = pts - centroid
    try:
        normal = np.linalg.svd(centred)[2][-1]
    except np.linalg.LinAlgError:
        return None
    rms = float(np.sqrt(np.mean((centred @ normal) ** 2)))
    radius = float(np.mean(np.linalg.norm(centred, axis=1)))
    aromatic = (max(ratios) <= DELOCALISED_BOND_FRAC
                and rms <= RING_PLANE_RMS_A)
    return {
        "normal0": normal / float(np.linalg.norm(normal)),
        "radius": round(radius, 4),
        "plane_rms": round(rms, 4),
        "bond_range": [round(min(bonds), 3), round(max(bonds), 3)],
        "aromatic": bool(aromatic),
    }


def _ring_defs(mdl: _Model):
    """Rings of the asymmetric unit walked into a coherent frame.

    Ring finding, the symmetry-composition check that stops a lattice loop
    from counting as a ring, and the aromaticity test are all
    peak_chemistry's - this module only adds the plane geometry, and (for
    the rings find_rings cannot represent) the census that says how many of
    them this structure has."""
    from ..tools.peak_chemistry import find_rings

    scs = mdl.scs
    graph = _heavy_graph(mdl)

    out: list[dict[str, Any]] = []
    for ring in find_rings(graph):
        ops = [mdl.identity]
        sites = [tuple(scs[ring[0]].site)]
        op = None
        prev = ring[0]
        for nxt in ring[1:]:
            edge = min((e for e in graph[prev] if e[0] == nxt),
                       key=lambda e: e[2], default=None)
            if edge is None:
                break
            op = op.multiply(edge[1]) if op is not None else edge[1]
            ops.append(op)
            sites.append(tuple(op * scs[nxt].site))
            prev = nxt
        if len(sites) != len(ring):
            continue
        seqs = [int(k) for k in ring]
        geo = _ring_geometry(mdl, seqs, sites)
        if geo is None:
            continue
        out.append({
            "ring": len(out),
            "key": ",".join(mdl.labels[k] for k in ring),
            "seqs": seqs,
            "atom_ops": ops,
            "sites_frac": sites,
            **geo,
        })
    n_asu = len(out)
    # round-3 R5: the rings find_rings cannot represent are BUILT here from
    # the closing operator's powers over the asymmetric-unit path (lap k of
    # the ring is closure^k applied to the walked path) and take part in
    # every ring table like any other ring. Zn2-dhtp lost its whole pi-pi
    # table (16 PLATON rows) to this before.
    through_sym = _rings_through_symmetry(mdl, graph)
    built: list[str] = []
    for r in through_sym:
        b = r.pop("_build", None)
        if not b:
            continue
        n = int(r["op_order"])
        closure, path, wops = b["closure"], b["path"], b["walk_ops"]
        seqs, ops, sites = [], [], []
        lap = None
        for _k in range(n):
            for s_idx, wop in zip(path, wops):
                if lap is None:
                    aop = wop if wop is not None else mdl.identity
                else:
                    aop = lap.multiply(wop) if wop is not None else lap
                seqs.append(int(s_idx))
                ops.append(aop)
                sites.append(tuple(aop * scs[s_idx].site))
            lap = closure if lap is None else lap.multiply(closure)
        geo = _ring_geometry(mdl, seqs, sites)
        if geo is None:
            continue
        out.append({
            "ring": len(out),
            "key": ",".join(mdl.labels[k] for k in seqs),
            "seqs": seqs,
            "atom_ops": ops,
            "sites_frac": sites,
            "through_symmetry": {"op": r["op"], "order": n,
                                 "asu_atoms": len(path)},
            **geo,
        })
        r["built"] = True
        r["aromatic"] = geo["aromatic"]
        built.append(f"{r['key']} x {r['op']}")
    note = (f"{n_asu} ring(s) found inside the asymmetric unit, "
            f"{sum(1 for r in out[:n_asu] if r['aromatic'])} aromatic.")
    if through_sym:
        note += (" THIS STRUCTURE HAS "
                 + str(len(through_sym))
                 + " of them closing THROUGH a symmetry element ("
                 + "; ".join(f"{r['key']} x {r['op']}" for r in through_sym)
                 + "): a ring sitting on an inversion centre or a rotation "
                   "axis, which find_rings cannot see. ")
        if len(built) == len(through_sym):
            note += ("They are built here from the operator's powers over "
                     "the asymmetric-unit path and take part in every "
                     "pi-pi / C-H...pi / anion-pi row below like any other "
                     "ring; their aromaticity is judged by the same "
                     "bond-ratio and planarity criteria.")
        else:
            note += (f"{len(built)} of them could be built "
                     f"({'; '.join(built) or 'none'}); the rest have a "
                     f"degenerate plane and are absent from the tables.")
    else:
        note += (" No ring closes through a symmetry element in this "
                 "structure (the asymmetric-unit bond graph was searched "
                 "for cycles closing on a non-identity operator of finite "
                 "order).")
    return out, note, through_sym


# --------------------------------------------------------------------------
# anion fragments (anion-pi). fragment_identity is a pure function, so this
# needs no session; only a signature whose NAME carries a negative charge is
# called an anion, and the unlabelled ones are reported rather than guessed.
# --------------------------------------------------------------------------

def _fragment_charge(name: str) -> int | None:
    tok = name.split("(")[0].strip()
    if tok.endswith("-"):
        return -1
    if tok.endswith("+"):
        return +1
    return None


def _fragment_ids(n: int, pst) -> list[int]:
    """Union-find over the pair table: one id per bonded fragment of the
    asymmetric unit (ids are the smallest member index)."""
    parent = list(range(n))

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for i in range(n):
        for j in pst[i]:
            ra, rb = find(i), find(int(j))
            if ra != rb:
                parent[max(ra, rb)] = min(ra, rb)
    return [find(i) for i in range(n)]


def _anion_fragments(mdl: _Model):
    """Bonded fragments of the asymmetric unit named by fragment_identity."""
    from ..chem.connectivity import _FRAGMENT_SIGNATURES, fragment_identity

    groups: dict[int, list[int]] = {}
    for i in range(mdl.n):
        groups.setdefault(mdl.frag[i], []).append(i)

    anions: list[dict[str, Any]] = []
    for members in groups.values():
        counts: dict[str, int] = {}
        for i in members:
            counts[mdl.elems[i]] = counts.get(mdl.elems[i], 0) + 1
        ident = fragment_identity(counts)
        if not ident or ident[0] != "counter_ion":
            continue
        if _fragment_charge(ident[1]) != -1:
            continue
        frag_ops = _fragment_ops(mdl, members)
        if frag_ops is None:
            continue
        anions.append({
            "anion": len(anions),
            "name": ident[1],
            "key": ",".join(mdl.labels[i] for i, _ in frag_ops),
            "seqs": [i for i, _ in frag_ops],
            "atom_ops": [op for _, op in frag_ops],
        })
    unlabelled = sorted({n for _s, r, n in _FRAGMENT_SIGNATURES
                         if r == "counter_ion" and _fragment_charge(n) is None})
    note = (f"{len(anions)} anionic fragment(s) identified from "
            f"_FRAGMENT_SIGNATURES by a negative charge in the signature "
            f"NAME. Signatures registered as counter_ion but carrying no "
            f"charge annotation are NOT classified either way: "
            f"{', '.join(unlabelled) if unlabelled else 'none'}.")
    return anions, note


def _fragment_ops(mdl: _Model, members: list[int]):
    """Walk a bonded fragment so its atoms sit in one coherent frame."""
    seen = {members[0]: mdl.identity}
    stack = [members[0]]
    allowed = set(members)
    while stack:
        i = stack.pop()
        for j, ops in mdl.pst[i].items():
            j = int(j)
            if j not in allowed or j in seen:
                continue
            seen[j] = seen[i].multiply(min(ops, key=str))
            stack.append(j)
    if len(seen) != len(members):
        return None
    return [(i, seen[i]) for i in members]


# --------------------------------------------------------------------------
# the work set: range instances + halo, materialized once per pass
# --------------------------------------------------------------------------

class _Work:
    """Materialized instances plus the ring/anion instances built on them."""

    def __init__(self, mdl: _Model, canonical: bool) -> None:
        self.mdl = mdl
        self.canonical = canonical
        self.items: list[tuple[int, Any]] = []
        self.keys: dict[tuple, int] = {}
        self.in_range: list[bool] = []
        self.frac: list[tuple[float, float, float]] = []
        self.truncated = False
        self.n_range = 0

    def add(self, i: int, op, in_range: bool) -> int | None:
        site = op * self.mdl.scs[i].site
        k = _site_key(i, site)
        idx = self.keys.get(k)
        if idx is not None:
            if in_range and not self.in_range[idx]:
                self.in_range[idx] = True
            return idx
        if len(self.items) >= MAX_WORK_INSTANCES:
            self.truncated = True
            return None
        idx = len(self.items)
        self.keys[k] = idx
        self.items.append((i, op))
        self.in_range.append(bool(in_range))
        self.frac.append((float(site[0]), float(site[1]), float(site[2])))
        return idx

    def lookup(self, i: int, site) -> int | None:
        return self.keys.get(_site_key(i, site))

    def __len__(self) -> int:
        return len(self.items)

    def finish(self) -> None:
        import numpy as np
        self.fracs = np.array(self.frac, dtype=float).reshape(
            len(self.items), 3)
        self.cart = self.fracs @ self.mdl.omx.T
        self.seqs = np.array([i for i, _ in self.items], dtype=int)
        self.range_mask = np.array(self.in_range, dtype=bool)
        self.ops_used: dict[str, Any] = {}
        for _i, op in self.items:
            self.ops_used.setdefault(str(op), op)


def _build_work(mdl: _Model, base: list[tuple[int, Any]], halo_A: float,
                canonical: bool) -> _Work:
    """`base` = the displayed instances; add every image within `halo_A`."""
    import numpy as np
    from scipy.spatial import cKDTree

    w = _Work(mdl, canonical)
    for i, op in base:
        w.add(int(i), op, True)
    w.n_range = len(w)
    if halo_A > 0 and w.n_range:
        base_cart = np.array(w.frac, dtype=float).reshape(w.n_range, 3) \
            @ mdl.omx.T
        tree = cKDTree(base_cart)
        reach = float(halo_A)
        lo_c = base_cart.min(axis=0) - reach
        hi_c = base_cart.max(axis=0) + reach
        corners = np.array(list(itertools.product(*zip(lo_c, hi_c))),
                           dtype=float)
        corners_f = corners @ mdl.omx_inv.T
        flo, fhi = corners_f.min(axis=0), corners_f.max(axis=0)

        cand_sites: list = []
        cand_ops: list = []
        for g in mdl.ops_all:
            rg = np.array(g.r().as_double(), dtype=float).reshape(3, 3)
            tg = np.array(g.t().as_double(), dtype=float)
            gs = mdl.frac @ rg.T + tg
            glo, ghi = gs.min(axis=0), gs.max(axis=0)
            rng = [range(int(math.floor(flo[k] - ghi[k])),
                         int(math.ceil(fhi[k] - glo[k])) + 1)
                   for k in range(3)]
            for t in itertools.product(*rng):
                shifted = gs + np.array(t, dtype=float)
                inside = np.all((shifted >= flo) & (shifted <= fhi), axis=1)
                if not inside.any():
                    continue
                idx = np.flatnonzero(inside)
                cand_sites.append(shifted[idx])
                cand_ops.append((_translation_op(t).multiply(g), idx))
        if cand_sites:
            allc = np.vstack(cand_sites) @ mdl.omx.T
            d, _ = tree.query(allc, k=1, distance_upper_bound=reach)
            keep = np.isfinite(d)
            pos = 0
            for op, idx in cand_ops:
                nsel = len(idx)
                sel = idx[keep[pos:pos + nsel]]
                pos += nsel
                for i in sel:
                    w.add(int(i), op, False)
    w.finish()
    _materialize_groups(mdl, w)
    return w


def _materialize_groups(mdl: _Model, w: _Work) -> None:
    """Ring and anion instances.

    A group instance exists only when EVERY one of its atoms is in the work
    set - that is what makes `halo_A=0` mean "only what is on screen": a ring
    whose partner ring is one image away then has no partner to pair with."""
    w.rings = _instantiate(mdl, w, mdl.rings, "ring")
    w.anions = _instantiate(mdl, w, mdl.anions, "anion")


def _instantiate(mdl: _Model, w: _Work, defs, kind: str) -> list[dict]:
    import numpy as np

    out: list[dict] = []
    if not defs:
        return out
    seen: set[frozenset] = set()
    for op in w.ops_used.values():
        rc = None
        for d in defs:
            idxs = []
            ok = True
            for seq, aop in zip(d["seqs"], d["atom_ops"]):
                k = w.lookup(seq, op.multiply(aop) * mdl.scs[seq].site)
                if k is None:
                    ok = False
                    break
                idxs.append(k)
            if not ok:
                continue
            tag = frozenset(idxs)
            if tag in seen:
                continue        # two operators can place the same group
            seen.add(tag)
            pts = np.array([tuple(op.multiply(aop) * mdl.scs[seq].site)
                            for seq, aop in zip(d["seqs"], d["atom_ops"])],
                           dtype=float) @ mdl.omx.T
            rec = {"idx": len(out), "key": d["key"], "inst": str(op),
                   "op": op, "atoms": idxs,
                   "centroid": pts.mean(axis=0),
                   "in_range": (str(op) == _IDENTITY_STR if w.canonical
                                else all(bool(w.range_mask[k]) for k in idxs))}
            if kind == "ring":
                if rc is None:
                    rc = mdl.omx @ np.array(
                        op.r().as_double(), dtype=float).reshape(3, 3) \
                        @ mdl.omx_inv
                normal = rc @ d["normal0"]
                nn = float(np.linalg.norm(normal))
                rec.update({"ring": d["ring"], "radius": d["radius"],
                            "aromatic": d["aromatic"],
                            "normal": normal / nn if nn else normal,
                            "through_symmetry": d.get("through_symmetry")})
            else:
                rec.update({"anion": d["anion"], "name": d["name"]})
            out.append(rec)
    return out


# --------------------------------------------------------------------------
# criteria presets
# --------------------------------------------------------------------------

def _criteria_block(mdl: _Model, preset: str, kinds) -> dict[str, Any]:
    olex2 = preset == "olex2"
    out: dict[str, Any] = {}
    if "hbond" in kinds:
        blk = {
            "set": preset,
            "donor_elements": sorted(HBOND_ELEMS),
            "acceptor_elements": sorted(HBOND_ELEMS),
            "excludes": "covalent 1-2 and 1-3 pairs; cross-PART pairs",
            "emitted_when": ("the distance test passes; `passes` is distance "
                             "AND angle, so an angularly bad short contact is "
                             "still reported as a measurement"),
            "no_H_rule": (f"a model with no H at all degrades to D...A only: "
                          f"status '{NO_H_STATUS}', angle null"),
            "polar_atoms_without_bonded_H": len(mdl.polar_without_h),
        }
        if olex2:
            blk.update({"d_DA_max_A": 2.9, "angle_DHA_min_deg": 150.0,
                        "source": _SRC_OLEX2_HTAB})
        else:
            blk.update({"d_HA_max_rule": "r_vdW(H) + r_vdW(A)",
                        "angle_DHA_min_deg": 110.0,
                        "d_DA_max_rule_when_no_H": "r_vdW(D) + r_vdW(A)",
                        "source": _SRC_STEINER, "vdw_table": _SRC_VDW_TABLE})
        out["hbond"] = blk
    if "pipi" in kinds:
        out["pipi"] = {
            "set": "olex2", "d_cc_max_A": 4.0, "alpha_max_deg": 30.0,
            "slip_max_A": 3.0, "slip_rule": "min(slip_ab, slip_ba)",
            "rings": "aromatic only",
            "alpha_definition": ("angle between the ring NORMALS, folded into "
                                 "[0, 90] - never an angle between atom pairs"),
            "reports": ("d_cc, alpha, d_perp_ab (centroid of ring B to the "
                        "PLANE of ring A), d_perp_ba, "
                        "slip_ab = sqrt(d_cc^2 - d_perp_ab^2), slip_ba - "
                        "always, pass or fail"),
            "excludes": "ring pairs sharing an atom (fused rings)",
            "emitted_when": "d_cc passes; `passes` is the full criterion",
            "ring_method": _SRC_RINGS, "ring_note": mdl.ring_note,
            "rings_closing_through_symmetry": mdl.rings_through_symmetry,
            "edges": "endpoints are centroids, not atoms: see rows/rings",
            "source": _SRC_OLEX2_PIPI,
        }
    if "chpi" in kinds:
        out["chpi"] = {
            "set": "nishio", "d_HCg_max_A": 3.2, "angle_CHCg_min_deg": 120.0,
            "offset_max_rule": "ring radius + 0.5 A",
            "rings": "aromatic only",
            "carrier_elements": sorted(CHX_CARRIER_ELEMS),
            "excludes": "an H whose carrier is an atom of the ring itself",
            "emitted_when": "H...Cg passes; `passes` is the full criterion",
            "ring_method": _SRC_RINGS, "ring_note": mdl.ring_note,
            "rings_closing_through_symmetry": mdl.rings_through_symmetry,
            "edges": "endpoints are centroids, not atoms: see rows/rings",
            "source": _SRC_NISHIO,
        }
    if "chx" in kinds:
        out["chx"] = {
            "set": "vdw_sum", "d_HA_max_rule": "r_vdW(H) + r_vdW(A)",
            "angle_CHA_min_deg": 120.0,
            "acceptor_elements": sorted(CHX_ACCEPTOR_ELEMS),
            "carrier_elements": sorted(CHX_CARRIER_ELEMS),
            "excludes": "acceptors 1-2 or 1-3 from the H; cross-PART pairs",
            "emitted_when": "H...A passes; `passes` is distance AND angle",
            "source": _SRC_VDW_ANGLE, "vdw_table": _SRC_VDW_TABLE,
        }
    if "halogen" in kinds:
        out["halogen"] = {
            "set": "iupac_2013", "donor_elements": sorted(HALOGEN_DONOR_ELEMS),
            "acceptor_elements": sorted(HALOGEN_ACCEPTOR_ELEMS),
            "d_XY_max_rule": "r_vdW(X) + r_vdW(Y)",
            "angle_CXY_min_deg": 155.0,
            "emitted_when": "X...Y passes; `passes` is distance AND angle",
            "requires": "a covalent, non-H carrier on X (a bare halide has no "
                        "sigma hole and is never a halogen-bond donor)",
            "source": _SRC_IUPAC_XB, "vdw_table": _SRC_VDW_TABLE,
        }
    if "anion_pi" in kinds:
        out["anion_pi"] = {
            "set": "weak_reading", "d_max_A": 4.5,
            "offset_max_rule": "ring radius",
            "rings": "aromatic only",
            "strength": "weak reading - evidence, never a verdict",
            "anion_identification": mdl.anion_note,
            "n_anion_fragments": len(mdl.anions),
            "edges": "endpoints are centroids, not atoms: see rows/rings",
            "source": _SRC_ANION_PI,
        }
    return out


# --------------------------------------------------------------------------
# the scans. Each returns rows in the SAME shape for the canonical pass and
# the display pass; `op` is the operator relative to the row's first object.
# --------------------------------------------------------------------------

def _pairs(a_cart, b_cart, r: float):
    """cKDTree ball query: for each row of a_cart, the b_cart hits within r."""
    from scipy.spatial import cKDTree
    if len(a_cart) == 0 or len(b_cart) == 0:
        return []
    return cKDTree(a_cart).query_ball_tree(cKDTree(b_cart), r)


def _subset(w, mask):
    import numpy as np
    idx = np.flatnonzero(mask)
    return idx, w.cart[idx]


def _rel_op(origin_op, partner_op):
    return origin_op.inverse().multiply(partner_op)


def _bonded_positions(mdl: _Model, w: _Work, k: int, want_h: bool):
    """(seq, op, cartesian) of the atoms covalently bonded to instance k."""
    seq, op = w.items[k]
    table = mdl.h_of if want_h else mdl.carrier_of
    out = []
    for j, jop in table.get(seq, ()):
        comp = op.multiply(jop)
        out.append((j, comp, mdl.ortho1(comp * mdl.scs[j].site)))
    return out


def _all_neighbours(mdl: _Model, w: _Work, k: int):
    seq, op = w.items[k]
    out = []
    for j, ops in mdl.pst[seq].items():
        j = int(j)
        for rt in ops:
            comp = op.multiply(rt)
            out.append((j, comp, mdl.ortho1(comp * mdl.scs[j].site)))
    return out


def _scan_hbond(mdl: _Model, w: _Work, crit: dict) -> list[dict]:
    import numpy as np

    olex2 = crit["set"] == "olex2"
    elems = mdl.elems
    mask = np.array([elems[s] in HBOND_ELEMS for s in w.seqs], dtype=bool) \
        if len(w.seqs) else np.zeros(0, dtype=bool)
    p_idx, p_cart = _subset(w, mask)
    if len(p_idx) < 1:
        return []
    no_h = mdl.n_h == 0
    present = {elems[int(s)] for s in w.seqs[p_idx]}
    max_polar_vdw = max(mdl.vdw(e) for e in present)
    if olex2:
        r_query = crit["d_DA_max_A"]
    elif no_h:
        r_query = 2 * max_polar_vdw
    else:
        r_query = mdl.vdw("H") + max_polar_vdw + mdl.max_dh
    rows: list[dict] = []
    hcache: dict[int, list] = {}
    for a, hits in enumerate(_pairs(p_cart, p_cart, r_query)):
        di = int(p_idx[a])
        d_seq, d_op = w.items[di]
        for b in hits:
            ai = int(p_idx[b])
            if ai == di:
                continue
            a_seq, a_op = w.items[ai]
            rel = _rel_op(d_op, a_op)
            if (a_seq, str(rel)) in mdl.excl[d_seq]:
                continue
            if mdl.part_conflict(d_seq, a_seq):
                continue
            d_da = _dist(w.cart[di], w.cart[ai])
            if no_h:
                # with no H the relation is undirected: emit it once, from
                # its canonical end, so D...A is not double counted
                ci, cj, crel = _canonical_pair_op(d_seq, a_seq, rel)
                if (ci, cj, str(crel)) != (d_seq, a_seq, str(rel)):
                    continue
                if str(rel) == str(rel.inverse()) and di > ai:
                    continue
                limit = (2.9 if olex2
                         else mdl.vdw(elems[d_seq]) + mdl.vdw(elems[a_seq]))
                if d_da > limit:
                    continue
                rows.append(_row(w, "hbond", di, ai, rel, d_da, {
                    "d": mdl.labels[d_seq], "h": None, "a": mdl.labels[a_seq],
                    "d_DA": round(d_da, 4), "d_HA": None, "angle": None,
                    "status": NO_H_STATUS, "passes": True,
                    "d_seq": int(d_seq), "h_seq": None, "a_seq": int(a_seq),
                    "h_op": None}))
                continue
            if di not in hcache:
                hcache[di] = _bonded_positions(mdl, w, di, want_h=True)
            for h_seq, h_op, h_xyz in hcache[di]:
                if mdl.part_conflict(d_seq, h_seq, a_seq):
                    continue
                if (a_seq, str(_rel_op(h_op, a_op))) in mdl.excl[h_seq]:
                    continue
                d_ha = _dist(h_xyz, w.cart[ai])
                ang = _angle_deg(w.cart[di], h_xyz, w.cart[ai])
                if olex2:
                    if d_da > crit["d_DA_max_A"]:
                        continue
                else:
                    if d_ha > mdl.vdw("H") + mdl.vdw(elems[a_seq]):
                        continue
                rows.append(_row(w, "hbond", di, ai, rel, d_da, {
                    "d": mdl.labels[d_seq], "h": mdl.labels[h_seq],
                    "a": mdl.labels[a_seq],
                    "d_DA": round(d_da, 4), "d_HA": round(d_ha, 4),
                    "angle": round(ang, 3), "status": None,
                    "passes": bool(ang >= crit["angle_DHA_min_deg"]),
                    "d_seq": int(d_seq), "h_seq": int(h_seq),
                    "a_seq": int(a_seq), "h_op": str(h_op),
                    "h_xyz": [round(float(x), 4) for x in h_xyz]}))
    return rows


def _scan_chx(mdl: _Model, w: _Work, crit: dict) -> list[dict]:
    import numpy as np

    elems = mdl.elems
    if not len(w.seqs):
        return []
    h_mask = np.array([mdl.is_h[s] for s in w.seqs], dtype=bool)
    a_mask = np.array([elems[s] in CHX_ACCEPTOR_ELEMS for s in w.seqs],
                      dtype=bool)
    h_idx, h_cart = _subset(w, h_mask)
    a_idx, a_cart = _subset(w, a_mask)
    if len(h_idx) == 0 or len(a_idx) == 0:
        return []
    r_query = mdl.vdw("H") + max(mdl.vdw(e) for e in CHX_ACCEPTOR_ELEMS)
    rows: list[dict] = []
    ccache: dict[int, list] = {}
    for p, hits in enumerate(_pairs(h_cart, a_cart, r_query)):
        if not hits:
            continue
        hi = int(h_idx[p])
        h_seq, h_op = w.items[hi]
        if hi not in ccache:
            ccache[hi] = [c for c in _bonded_positions(mdl, w, hi, False)
                          if elems[c[0]] in CHX_CARRIER_ELEMS]
        if not ccache[hi]:
            continue
        for b in hits:
            ai = int(a_idx[b])
            a_seq, a_op = w.items[ai]
            if (a_seq, str(_rel_op(h_op, a_op))) in mdl.excl[h_seq]:
                continue
            d_ha = _dist(w.cart[hi], w.cart[ai])
            if d_ha > mdl.vdw("H") + mdl.vdw(elems[a_seq]):
                continue
            for c_seq, c_op, c_xyz in ccache[hi]:
                if mdl.part_conflict(c_seq, h_seq, a_seq):
                    continue
                ang = _angle_deg(c_xyz, w.cart[hi], w.cart[ai])
                rows.append(_row(w, "chx", hi, ai, _rel_op(c_op, a_op), d_ha, {
                    "d": mdl.labels[c_seq], "h": mdl.labels[h_seq],
                    "a": mdl.labels[a_seq],
                    "d_DA": round(_dist(c_xyz, w.cart[ai]), 4),
                    "d_HA": round(d_ha, 4), "angle": round(ang, 3),
                    "status": None,
                    "passes": bool(ang >= crit["angle_CHA_min_deg"]),
                    "d_seq": int(c_seq), "h_seq": int(h_seq),
                    "a_seq": int(a_seq), "c_seq": int(c_seq),
                    "c_xyz": [round(float(x), 4) for x in c_xyz]},
                    canon_i=int(c_seq), origin_op=c_op, origin_xyz=c_xyz))
    return rows


def _scan_halogen(mdl: _Model, w: _Work, crit: dict) -> list[dict]:
    import numpy as np

    elems = mdl.elems
    if not len(w.seqs):
        return []
    x_mask = np.array([elems[s] in HALOGEN_DONOR_ELEMS for s in w.seqs],
                      dtype=bool)
    y_mask = np.array([elems[s] in HALOGEN_ACCEPTOR_ELEMS for s in w.seqs],
                      dtype=bool)
    x_idx, x_cart = _subset(w, x_mask)
    y_idx, y_cart = _subset(w, y_mask)
    if len(x_idx) == 0 or len(y_idx) == 0:
        return []
    r_query = (max(mdl.vdw(e) for e in HALOGEN_DONOR_ELEMS)
               + max(mdl.vdw(e) for e in HALOGEN_ACCEPTOR_ELEMS))
    rows: list[dict] = []
    ccache: dict[int, list] = {}
    for p, hits in enumerate(_pairs(x_cart, y_cart, r_query)):
        if not hits:
            continue
        xi = int(x_idx[p])
        x_seq, x_op = w.items[xi]
        if xi not in ccache:
            # the sigma hole sits opposite a COVALENT bond: a bare halide
            # has no carrier and therefore no halogen bond
            ccache[xi] = [c for c in _all_neighbours(mdl, w, xi)
                          if not mdl.is_h[c[0]]]
        if not ccache[xi]:
            continue
        for b in hits:
            yi = int(y_idx[b])
            if yi == xi:
                continue
            y_seq, y_op = w.items[yi]
            rel = _rel_op(x_op, y_op)
            if (y_seq, str(rel)) in mdl.excl[x_seq]:
                continue
            if mdl.part_conflict(x_seq, y_seq):
                continue
            d_xy = _dist(w.cart[xi], w.cart[yi])
            if d_xy > mdl.vdw(elems[x_seq]) + mdl.vdw(elems[y_seq]):
                continue
            for c_seq, _c_op, c_xyz in ccache[xi]:
                ang = _angle_deg(c_xyz, w.cart[xi], w.cart[yi])
                rows.append(_row(w, "halogen", xi, yi, rel, d_xy, {
                    "c": mdl.labels[c_seq], "x": mdl.labels[x_seq],
                    "a": mdl.labels[y_seq], "d_XA": round(d_xy, 4),
                    "angle": round(ang, 3),
                    "passes": bool(ang >= crit["angle_CXY_min_deg"]),
                    "c_seq": int(c_seq), "x_seq": int(x_seq),
                    "a_seq": int(y_seq),
                    "c_xyz": [round(float(v), 4) for v in c_xyz]}))
    return rows


def _scan_pipi(mdl: _Model, w: _Work, crit: dict) -> list[dict]:
    import numpy as np
    from scipy.spatial import cKDTree

    rings = [r for r in w.rings if r["aromatic"]]
    if len(rings) < 2:
        return []
    cen = np.array([r["centroid"] for r in rings], dtype=float)
    rows: list[dict] = []
    for a, b in sorted(cKDTree(cen).query_pairs(crit["d_cc_max_A"])):
        ra, rb = rings[a], rings[b]
        if set(ra["atoms"]) & set(rb["atoms"]):
            continue                         # fused / shared ring, not a pair
        rel = _rel_op(ra["op"], rb["op"])
        ci, cj, crel = _canonical_pair_op(ra["ring"], rb["ring"], rel)
        if (ci, cj, str(crel)) != (ra["ring"], rb["ring"], str(rel)):
            ra, rb = rb, ra                  # report from the canonical end
            rel = _rel_op(ra["op"], rb["op"])
        if mdl.part_conflict(*(mdl.rings[ra["ring"]]["seqs"]
                               + mdl.rings[rb["ring"]]["seqs"])):
            continue
        ca, cb = ra["centroid"], rb["centroid"]
        v = cb - ca
        d_cc = float(np.linalg.norm(v))
        alpha = math.degrees(math.acos(max(0.0, min(
            1.0, abs(float(np.dot(ra["normal"], rb["normal"])))))))
        d_ab = abs(float(np.dot(v, ra["normal"])))
        d_ba = abs(float(np.dot(v, rb["normal"])))
        slip_ab = math.sqrt(max(0.0, d_cc * d_cc - d_ab * d_ab))
        slip_ba = math.sqrt(max(0.0, d_cc * d_cc - d_ba * d_ba))
        ok = (alpha <= crit["alpha_max_deg"]
              and min(slip_ab, slip_ba) <= crit["slip_max_A"])
        rows.append(_ring_row(w, "pipi", rb, d_cc, {
            "ring_a": ra["key"], "ring_b": rb["key"],
            "d_cc": round(d_cc, 4), "alpha": round(alpha, 3),
            "d_perp_ab": round(d_ab, 4), "d_perp_ba": round(d_ba, 4),
            "slip_ab": round(slip_ab, 4), "slip_ba": round(slip_ba, 4),
            "passes": bool(ok)},
            i_seq=ra["ring"], j_seq=rb["ring"], rel=rel,
            i_inst=None, i_in_range=ra["in_range"], other=ra,
            origin_op=ra["op"], origin_xyz=ra["centroid"]))
    return rows


def _scan_chpi(mdl: _Model, w: _Work, crit: dict) -> list[dict]:
    import numpy as np

    rings = [r for r in w.rings if r["aromatic"]]
    if not rings or not len(w.seqs):
        return []
    h_idx, h_cart = _subset(
        w, np.array([mdl.is_h[s] for s in w.seqs], dtype=bool))
    if len(h_idx) == 0:
        return []
    cen = np.array([r["centroid"] for r in rings], dtype=float)
    rows: list[dict] = []
    ccache: dict[int, list] = {}
    for p, hits in enumerate(_pairs(h_cart, cen, crit["d_HCg_max_A"])):
        if not hits:
            continue
        hi = int(h_idx[p])
        h_seq, _h_op = w.items[hi]
        if hi not in ccache:
            ccache[hi] = [c for c in _bonded_positions(mdl, w, hi, False)
                          if mdl.elems[c[0]] in CHX_CARRIER_ELEMS]
        if not ccache[hi]:
            continue
        for b in hits:
            rb = rings[b]
            if hi in rb["atoms"]:
                continue
            v = rb["centroid"] - w.cart[hi]
            d_h = float(np.linalg.norm(v))
            perp = abs(float(np.dot(v, rb["normal"])))
            offset = math.sqrt(max(0.0, d_h * d_h - perp * perp))
            for c_seq, c_op, c_xyz in ccache[hi]:
                ci = w.lookup(c_seq, c_op * mdl.scs[c_seq].site)
                if ci is not None and ci in rb["atoms"]:
                    continue                 # H is a substituent OF this ring
                if mdl.part_conflict(*([c_seq, h_seq]
                                       + mdl.rings[rb["ring"]]["seqs"])):
                    continue
                ang = _angle_deg(c_xyz, w.cart[hi], rb["centroid"])
                ok = (ang >= crit["angle_CHCg_min_deg"]
                      and offset <= rb["radius"] + 0.5)
                rows.append(_ring_row(w, "chpi", rb, d_h, {
                    "c": mdl.labels[c_seq], "h": mdl.labels[h_seq],
                    "ring": rb["key"], "d_HCg": round(d_h, 4),
                    "angle": round(ang, 3), "d_perp": round(perp, 4),
                    "offset": round(offset, 4), "passes": bool(ok),
                    "c_seq": int(c_seq), "h_seq": int(h_seq),
                    "c_xyz": [round(float(x), 4) for x in c_xyz]},
                    i_seq=int(c_seq), j_seq=rb["ring"],
                    rel=_rel_op(c_op, rb["op"]), i_inst=hi,
                    i_in_range=bool(w.range_mask[hi]),
                    origin_op=c_op, origin_xyz=c_xyz))
    return rows


def _scan_anion_pi(mdl: _Model, w: _Work, crit: dict) -> list[dict]:
    import numpy as np

    rings = [r for r in w.rings if r["aromatic"]]
    if not rings or not w.anions:
        return []
    cen = np.array([r["centroid"] for r in rings], dtype=float)
    acen = np.array([a["centroid"] for a in w.anions], dtype=float)
    rows: list[dict] = []
    for p, hits in enumerate(_pairs(acen, cen, crit["d_max_A"])):
        an = w.anions[p]
        for b in hits:
            rb = rings[b]
            if set(an["atoms"]) & set(rb["atoms"]):
                continue
            v = rb["centroid"] - acen[p]
            d = float(np.linalg.norm(v))
            perp = abs(float(np.dot(v, rb["normal"])))
            offset = math.sqrt(max(0.0, d * d - perp * perp))
            rows.append(_ring_row(w, "anion_pi", rb, d, {
                "anion": an["key"], "anion_name": an["name"],
                "ring": rb["key"], "d_cc": round(d, 4),
                "d_perp": round(perp, 4), "offset": round(offset, 4),
                "passes": bool(offset <= rb["radius"]),
                "strength": "weak_reading"},
                i_seq=an["anion"], j_seq=rb["ring"],
                rel=_rel_op(an["op"], rb["op"]), i_inst=an["atoms"][0],
                i_in_range=an["in_range"],
                origin_op=an["op"], origin_xyz=acen[p]))
    return rows


# --------------------------------------------------------------------------
# row construction: one shape, both passes
# --------------------------------------------------------------------------

def _finish_row(row: dict, kind: str, d: float, i_seq: int, j_seq: int,
                rel, sym: str, xyz, i_in_range: bool, j_in_range: bool,
                extra_key, sym_i: str, xyz_i,
                same_fragment: bool = False) -> dict:
    """`sym_i`/`xyz_i` place the FIRST object, `sym`/`xyz` the second, and
    `op` = sym_i^-1 . sym is the canonical operator, so for every row
    uc.distance(site[i_seq], rt_mx(op) * site[j_seq]) reproduces the
    crystallographic distance of the pair whatever image the row sits on."""
    row.update({
        "kind": kind, "dist": round(float(d), 4),
        "i_seq": int(i_seq), "j_seq": int(j_seq), "op": str(rel),
        "sym": sym, "xyz": [round(float(x), 4) for x in xyz],
        "sym_i": sym_i, "xyz_i": [round(float(x), 4) for x in xyz_i],
        "i_in_range": bool(i_in_range), "j_in_range": bool(j_in_range),
    })
    row["boundary"] = not (i_in_range and j_in_range)
    # intramolecular = same bonded fragment on the identity operator; a
    # contact to another IMAGE of the same molecule is intermolecular
    row["intra"] = bool(same_fragment
                        and str(rel).replace(" ", "") == _IDENTITY_STR)
    row["_key"] = (kind, int(i_seq), int(j_seq), str(rel)) + tuple(extra_key)
    return row


def _row(w: _Work, kind: str, i_inst: int, j_inst: int, rel, d: float,
         body: dict, canon_i: int | None = None, origin_op=None,
         origin_xyz=None) -> dict:
    i_seq, i_op = w.items[i_inst]
    j_seq, j_op = w.items[j_inst]
    row = dict(body)
    row.update({"i": i_inst, "j": j_inst})
    ci = canon_i if canon_i is not None else i_seq
    return _finish_row(
        row, kind, d, ci, j_seq, rel,
        str(j_op), w.cart[j_inst], bool(w.range_mask[i_inst]),
        bool(w.range_mask[j_inst]),
        (body.get("h_seq"), body.get("c_seq")),
        str(origin_op if origin_op is not None else i_op),
        origin_xyz if origin_xyz is not None else w.cart[i_inst],
        same_fragment=w.mdl.frag[int(ci)] == w.mdl.frag[int(j_seq)])


def _ring_row(w: _Work, kind: str, rb: dict, d: float, body: dict, *,
              i_seq: int, j_seq: int, rel, i_inst, i_in_range: bool,
              origin_op, origin_xyz, other: dict | None = None) -> dict:
    """A row whose partner is a ring centroid (pipi / chpi / anion_pi)."""
    row = dict(body)
    row.update({"i": i_inst, "j": None, "ring_inst": rb["idx"],
                "ring_key": rb["key"]})
    if other is not None:
        row["ring_a_inst"] = other["idx"]
        row["ring_b_inst"] = rb["idx"]
    return _finish_row(row, kind, d, i_seq, j_seq, rel, str(rb["op"]),
                       rb["centroid"], i_in_range, bool(rb["in_range"]),
                       (body.get("h_seq"), body.get("c_seq")),
                       str(origin_op), origin_xyz,
                       same_fragment=w.mdl.frag[int(i_seq)] == w.mdl.frag[int(j_seq)])


_SCANS = {
    "hbond": _scan_hbond, "chx": _scan_chx, "halogen": _scan_halogen,
    "pipi": _scan_pipi, "chpi": _scan_chpi, "anion_pi": _scan_anion_pi,
}

_DISPLAY_ONLY = ("i", "j", "sym", "xyz", "sym_i", "xyz_i", "boundary",
                 "ring_inst", "ring_a_inst", "ring_b_inst")


def _clean(row: dict, display: bool) -> dict:
    out = {k: v for k, v in row.items()
           if not k.startswith("_") and k not in ("i_in_range", "j_in_range")}
    if not display:
        for k in _DISPLAY_ONLY:
            out.pop(k, None)
    return out


# --------------------------------------------------------------------------
# public entry
# --------------------------------------------------------------------------

def find_interactions(xs, *, parts=None, h_source=None, kinds=None,
                      criteria: str = "olex2", range_atoms=None,
                      halo_A: float = DEFAULT_HALO_A,
                      caps=None) -> dict[str, Any]:
    """Hydrogen bonds, pi-pi, C-H...pi, C-H...X, halogen and anion-pi.

    Parameters
    ----------
    xs : cctbx.xray.structure
        Typically `crystalpilot.io.shelx_model.load_res_model(...).structure`.
    parts : dict[label, int] | list[int] | None
        SHELX PART numbers. Signed values are accepted; comparison is on
        `abs()`, and the covalent connectivity behind the exclusion sets goes
        through `nodes.part_kwargs_from_parts` so SHELX semantics are exact.
    h_source : {"riding", "refined", "absent", "mixed"} | None
        Where the H positions come from. REQUIRED information for any consumer
        that quotes an H...A distance; when omitted it is inferred as
        "absent" (no H in the model) or reported as "unknown".
    kinds : iterable[str] | None
        Subset of `KINDS`; default all of them.
    criteria : {"olex2", "platon", "steiner"}
        Hydrogen-bond preset. `platon` is an alias of `steiner`.
    range_atoms : list[(i_seq, rt_mx | str)] | None
        The displayed instances. None = the asymmetric unit at identity.
    halo_A : float
        Radius of the symmetry-image halo around `range_atoms`. See the
        module docstring's boundary rule; 0 means "only what is on screen".
    caps : dict[str, int] | None
        Per-kind display-row cap, default 2000. Rows are sorted by distance,
        so a cap keeps the closest and `truncated[kind]` says what was cut.

    Returns
    -------
    dict with keys `criteria`, `h_source`, `h_source_note`, `range`,
    `instances`, `rings`, `unique`, `edges`, `rows`, `counts`, `truncated`.

    Every row carries `dist` - the kind's primary distance, the one rows are
    sorted and capped on (D...A for hbond, H...A for C-H...X, X...Y for a
    halogen bond, centroid-centroid for pi-pi and anion-pi, H...Cg for
    C-H...pi) - alongside the named geometry of its own kind.  `d`, `h` and
    `a` are the donor / hydrogen / acceptor LABELS of the plan's row shape,
    never distances.
    """
    from cctbx import sgtbx

    preset = "steiner" if criteria in ("platon", "steiner") else criteria
    if preset not in ("olex2", "steiner"):
        raise ValueError(f"unknown criteria preset: {criteria!r}")
    unknown = set(kinds or ()) - set(KINDS)
    if unknown:
        raise ValueError(f"unknown interaction kinds: {sorted(unknown)}")
    want = tuple(k for k in KINDS if k in set(kinds or KINDS))
    cap_of = {k: int((caps or {}).get(k, DEFAULT_CAP)) for k in want}

    mdl = _Model(xs, parts=parts)
    crit = _criteria_block(mdl, preset, want)

    # ---- h_source: required output, never guessed -------------------------
    allowed = ("riding", "refined", "absent", "mixed")
    if h_source is not None:
        if h_source not in allowed:
            raise ValueError(f"h_source must be one of {allowed}")
        h_note = ("as declared by the caller"
                  + ("; " + _H_BIAS_NOTE if h_source in ("riding", "mixed")
                     else ""))
    elif mdl.n_h == 0:
        h_source, h_note = "absent", (
            "no H atoms in the model: hydrogen bonds degrade to D...A only "
            f"(status '{NO_H_STATUS}', angle null) and no HTAB may be emitted")
    else:
        h_source = "unknown"
        h_note = (f"{mdl.n_h} H atoms present but the caller passed no "
                  f"h_source; riding vs refined cannot be told from "
                  f"coordinates alone - pass ses.flags['h_riding_meta'] / "
                  f"AFIX status. " + _H_BIAS_NOTE)

    # ---- reach of the enabled criteria ------------------------------------
    ring_reach = 0.0
    if mdl.rings:
        ring_reach = max((4.0 if "pipi" in want else 0.0),
                         (3.2 if "chpi" in want else 0.0),
                         (4.5 if "anion_pi" in want else 0.0)) \
            + 2 * mdl.ring_r_max
    pair_reach = 0.0
    for k in want:
        if k == "hbond":
            pair_reach = max(pair_reach, 2.9 if preset == "olex2"
                             else mdl.vdw("H") + 2.1 + mdl.max_dh)
        elif k == "chx":
            pair_reach = max(pair_reach, mdl.vdw("H") + 2.1 + mdl.max_dh)
        elif k == "halogen":
            pair_reach = max(pair_reach, 4.0)
    # tightest halo that cannot lose a partner: the longest criterion, plus
    # (for the group kinds) twice the group radius, because a ring counts
    # only once ALL of its atoms are materialized and the halo is measured
    # from the nearest range ATOM
    reach = max(pair_reach, ring_reach, 3.0)
    shell = reach + 0.5

    # ---- canonical pass: ASU + shell, independent of the displayed range --
    identity = sgtbx.rt_mx()
    asu_base = [(i, identity) for i in range(mdl.n)]
    canon_work = _build_work(mdl, asu_base, shell, canonical=True)
    unique: dict[str, list[dict]] = {}
    for k in want:
        seen: set = set()
        rows = []
        for r in _SCANS[k](mdl, canon_work, crit[k]):
            if not (r["i_in_range"] or r["j_in_range"]):
                continue
            if r["_key"] in seen:
                continue
            seen.add(r["_key"])
            rows.append(_clean(r, display=False))
        rows.sort(key=lambda r: (r["dist"], r["op"]))
        unique[k] = rows

    # ---- display pass -----------------------------------------------------
    if range_atoms is None:
        base, range_src = asu_base, "asu"
    else:
        base = [(int(i), _as_op(op)) for i, op in range_atoms]
        range_src = "given"
    work = _build_work(mdl, base, float(halo_A), canonical=False)

    rows_by_kind: dict[str, list[dict]] = {}
    truncated: dict[str, dict[str, int]] = {}
    for k in want:
        seen = set()
        found = []
        for r in _SCANS[k](mdl, work, crit[k]):
            if not (r["i_in_range"] or r["j_in_range"]):
                continue                     # boundary rule: one end in range
            key = (r["_key"], r.get("i"), r.get("j"), r.get("sym"),
                   r.get("ring_a_inst"), r.get("ring_inst"))
            if key in seen:
                continue
            seen.add(key)
            found.append(r)
        found.sort(key=lambda r: (r["dist"], r["op"]))
        if len(found) > cap_of[k]:
            truncated[k] = {"cap": cap_of[k], "found": len(found)}
            found = found[:cap_of[k]]
        rows_by_kind[k] = [_clean(r, display=True) for r in found]

    # ---- outputs ----------------------------------------------------------
    rings_out = [{"key": r["key"], "ring": r["ring"], "inst": r["inst"],
                  "centroid": [round(float(x), 4) for x in r["centroid"]],
                  "normal": [round(float(x), 5) for x in r["normal"]],
                  "radius": r["radius"], "aromatic": r["aromatic"],
                  "atoms": list(r["atoms"]), "in_range": r["in_range"],
                  **({"through_symmetry": r["through_symmetry"]}
                     if r.get("through_symmetry") else {})}
                 for r in work.rings]

    edges: dict[str, list[list]] = {}
    for k in want:
        e = []
        if k in ("hbond", "chx", "halogen"):
            for r in rows_by_kind[k]:
                if r.get("i") is None or r.get("j") is None or r["boundary"]:
                    continue                 # a stub, not a drawable segment
                e.append([int(r["i"]), int(r["j"]), r["dist"]])
        edges[k] = e

    all_rows = [r for k in want for r in rows_by_kind[k]]
    all_rows.sort(key=lambda r: (r["kind"], r["dist"]))
    counts = {
        "rows": {k: len(rows_by_kind[k]) for k in want},
        "unique": {k: len(unique[k]) for k in want},
        "boundary": {k: sum(1 for r in rows_by_kind[k] if r["boundary"])
                     for k in want},
        "passing": {k: sum(1 for r in rows_by_kind[k] if r["passes"])
                    for k in want},
        "intra": {k: sum(1 for r in rows_by_kind[k] if r["intra"])
                  for k in want},
        "intra_unique": {k: sum(1 for r in unique[k] if r["intra"])
                         for k in want},
        "n_rows": len(all_rows),
        "n_unique": sum(len(unique[k]) for k in want),
        "n_boundary": sum(1 for r in all_rows if r["boundary"]),
        "n_rings": len(work.rings),
        "n_instances": len(work),
    }
    if mdl.vdw.fallback_used:
        for k in want:
            crit[k]["vdw_fallback_used"] = sorted(mdl.vdw.fallback_used)
            crit[k]["vdw_fallback_A"] = VDW_FALLBACK

    fr = work.fracs
    return {
        "criteria": crit,
        "h_source": h_source,
        "h_source_note": h_note,
        "range": {
            "source": range_src, "n_range": work.n_range,
            "n_halo": len(work) - work.n_range, "n_instances": len(work),
            "halo_A": float(halo_A),
            "boundary_rule": (
                "searched on range + halo; only rows with at least one end "
                "in range are emitted; boundary=True means the partner is "
                "outside range and is quoted by sym/xyz instead"),
            "frac_lo": ([round(float(x), 4) for x in fr.min(axis=0)]
                        if len(work) else None),
            "frac_hi": ([round(float(x), 4) for x in fr.max(axis=0)]
                        if len(work) else None),
            "work_truncated": bool(work.truncated),
            "halo_advised_A": round(float(reach), 3),
            "halo_sufficient": bool(float(halo_A) >= reach),
        },
        "instances": [{"i_seq": int(i), "label": mdl.labels[i],
                       "elem": mdl.elems[i], "part": mdl.parts[i],
                       "sym": str(op),
                       "xyz": [round(float(x), 4) for x in work.cart[k]],
                       "in_range": bool(work.range_mask[k])}
                      for k, (i, op) in enumerate(work.items)],
        "rings": rings_out,
        "unique": unique,
        "edges": edges,
        "rows": all_rows,
        "counts": counts,
        "truncated": truncated,
    }
