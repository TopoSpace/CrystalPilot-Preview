"""A PHOTOGRAPH of the five bonding criteria that exist today (R2.0).

This file is not a wish list. Every set below is what the current code
actually returns; several of them are wrong chemistry and are asserted here
precisely so that the `chem/bonding.py` migration (R2.1, one consumer per
commit) can prove, edge by edge, what it changed. When a migration commit
changes one of these numbers, that is the diff to explain in the commit
message - not a test to silently update.

The five criteria (plan §1.5 D8 + D18):

  1. `chem.connectivity.analyze_connectivity`  27-image P1 search,
     sum(r_cov)+0.45, metal windows from `MetalProfile`, flat 2.15 A M-C
     ceiling that only applies to metals that HAVE a profile (D9)
  2. `refine.scene._pair_sym_table`            raw smtbx table (tol 0.5 A)
  3. `report.structviews._bonds`               private `_COVALENT_R` table,
     (r_i + r_j) x 1.2, no symmetry in the `asu` state, no PART awareness
  4. `refine.inspect._neighbor_table`          raw smtbx table (tol 0.5 A)
  5. `refine.nodes.prune_long_metal_contacts`  smtbx table minus EVERY metal
     pair longer than the plain covalent sum (refine / chemaudit only, D18)

Four synthetic fixtures, built in code, no external data:

  (i)   `mof_chain`        1-D Cu carboxylate coordination polymer with a
                           chelating carboxylate: second O 2.41 A, carboxylate
                           C 2.50 A from the metal
  (ii)  `organic_p_1`      centrosymmetric aromatic molecule with riding H,
                           bonded to its own inversion image, plus a
                           PART 1 / PART 2 pair 1.00 A apart
  (iii) `ionic_salt`       NaCl-type lattice, no covalent M-X bond expected
  (iv)  `organometallic`   ferrocene-like Fe(eta5-C5H0)2, Zr-CH3 2.28 A with
                           a chelating acetate (Zr...C 2.50 A), OsCl4 (a metal
                           with NO MetalProfile entry) and the La...C(arene)
                           3.2 A contact that `prune_long_metal_contacts`
                           records as a false bond

MIGRATION LOG (one consumer per commit; the numbers below move only here)

  1. 2026-09-04  `refine.inspect._neighbor_table` (and with it
     `metal_environments`, `organic_fragments`, `inspect_model`,
     `get_geometry`, `disorder_accept`, `audit_heavy_sites`) reads
     `chem.bonding.bond_table`. Criterion 4 below is therefore no longer the
     raw smtbx table: the chelating carboxylate carbon, the La...C(arene)
     contacts and any metal pair beyond the classified window are gone, an
     eta ring counts as one ligand, and `cn_plausible` is three-state.
  1b. 2026-09-04  `refine.nodes.prune_long_metal_contacts` (refine /
     chemaudit riding-H valence semantics) keeps exactly the classified
     metal edges instead of everything within the plain covalent sum:
     criterion 5 now coincides with criterion 4 on every fixture (D18).
  2. 2026-09-04  `report.structviews` (view_structure / situation_report
     images) reads `chem.bonding.bond_table`: `_COVALENT_R`, `_is_metalish`
     and the x1.2 rule are gone, the `asu` state is symmetry-exact for the
     pairs it draws, PART keywords are honoured, and the packed states wrap
     finite molecules whole (the viewer's `_wrapped_groups`) instead of
     tearing them at the cell faces.
  3. 2026-09-04  `refine.scene` (the viewer's scene JSON) reads
     `chem.bonding.bond_table`: `_pair_sym_table` is the classified table in
     pair_sym_table shape, drawn bonds are `[i, j, kind]` triples, metal
     atoms carry `m: true`, cache key scene6_ -> scene7_. Criterion 2 now
     coincides with 1b / 4 on the metal edges.
  5. 2026-09-04  `chem.connectivity.analyze_connectivity` places the
     classified ASU edges on its P1 expansion (the periodic fragment /
     dimensionality / census / system-type analysis is untouched); the
     27-image scan only finds impossible contacts now. The flat 2.15 A M-C
     ceiling is gone (Zr-CH3 2.28 is a bond), a riding X-H hydrogen is no
     longer a ligand, metal-metal contacts are listed apart and never in the
     CN, and `cn_plausible` is three-state. Five criteria, one truth.

Edge sets are normalised to {(label_a, label_b, round(d, 2))} with the labels
sorted: that is the only shape in which criteria working in P1 (1), on the
ASU with symmetry operators (2, 4, 5) and on plain Cartesian points (3) can
be compared at all. It collapses the symmetry images of one label pair at one
distance into a single entry (NaCl's six Na-Cl images -> one row); the
coordination numbers, where that collapse matters, are pinned separately in
`test_coordination_numbers_status_quo`.
"""
from __future__ import annotations

import math

import numpy as np
from cctbx import crystal, xray

# --------------------------------------------------------------- fixtures --

def _structure(atoms, cell, sg="P 1"):
    """atoms: (label, element, cartesian xyz[, occupancy])."""
    cs = crystal.symmetry(unit_cell=cell, space_group_symbol=sg)
    xs = xray.structure(crystal_symmetry=cs)
    uc = cs.unit_cell()
    for atom in atoms:
        label, el, cart = atom[:3]
        occ = atom[3] if len(atom) > 3 else 1.0
        xs.add_scatterer(xray.scatterer(
            label=label, site=uc.fractionalize(cart), scattering_type=el,
            u=0.03, occupancy=occ))
    xs.scattering_type_registry(table="it1992")
    return xs


def _chelate(metal, e1, e2, d_mc=2.50, d_co=1.25, half=61.4, tilt=-9.9):
    """Chelating (bidentate) carboxylate: returns (C, O_short, O_long).

    C sits `d_mc` from the metal along e1; the two O sit at +-`half` degrees
    from the C->outward direction, the whole group rotated by `tilt` in the
    (e1, e2) plane so the two M...O distances differ - a real chelating
    carboxylate is asymmetric. With the defaults: M-O 1.980, M...O 2.410,
    M...C 2.500, C-O 1.250, O-C-O 122.8 deg.
    """
    metal = np.asarray(metal, float)
    e1 = np.asarray(e1, float)
    e1 = e1 / np.linalg.norm(e1)
    e2 = np.asarray(e2, float)
    e2 = e2 - e1 * float(np.dot(e1, e2))
    e2 = e2 / np.linalg.norm(e2)
    c = metal + d_mc * e1

    def at(deg):
        a = math.radians(deg)
        return c + d_co * (math.cos(a) * e1 + math.sin(a) * e2)

    return c, at(180 + half + tilt), at(180 - half + tilt)


def mof_chain():
    """(i) 1-D Cu carboxylate chain along a + one chelating carboxylate.

    Cu1 at the origin is bridged to its own image at x + 6.0 A by a syn-syn
    carboxylate (Cu-O 1.950), which makes the fragment periodic in one
    direction (`system_type == "framework"`, dimensionality 1). The chelating
    carboxylate on the same metal puts O4 at 2.410 A and its carboxylate
    carbon C2 at 2.500 A - the 2.3-2.6 A band the plan singles out.
    """
    a = 6.0
    atoms = [("CU1", "Cu", (0.0, 0.0, 0.0)),
             ("O1", "O", (1.90, 0.4387, 0.0)),
             ("C1", "C", (3.00, 1.0387, 0.0)),
             ("O2", "O", (4.10, 0.4387, 0.0))]
    c2, o3, o4 = _chelate((0, 0, 0), (0, 1, 0), (0, 0, 1))
    atoms += [("C2", "C", tuple(c2)), ("O3", "O", tuple(o3)),
              ("O4", "O", tuple(o4)),
              ("C3", "C", tuple(c2 + np.array([0.0, 1.52, 0.0])))]
    return _structure(atoms, (a, 16, 16, 90, 90, 90))


def organic_p_1():
    """(ii) P-1 aromatic molecule, riding H, one PART 1 / PART 2 pair.

    C1 sits 0.77 A from the inversion centre at the origin, so C1 is bonded
    to its own image through `-x,-y,-z` at 1.540 A (a biphenyl-type pivot):
    the only bond in these fixtures that exists ONLY as a symmetry image.
    C7A (PART 1) and C7B (PART 2) are two positions of one substituent,
    1.000 A apart, both bonded to C4 at 1.500 A.
    """
    cx = 2.16
    atoms = []
    for k in range(6):
        ang = math.radians(180 + 60 * k)
        atoms.append((f"C{k + 1}", "C",
                      (cx + 1.39 * math.cos(ang), 1.39 * math.sin(ang), 0.0)))
    for k in (1, 2, 4, 5):          # H on every ring carbon but C1 and C4
        ang = math.radians(180 + 60 * k)
        atoms.append((f"H{k + 1}", "H",
                      (cx + 2.34 * math.cos(ang), 2.34 * math.sin(ang), 0.0)))
    atoms.append(("C7A", "C", (3.55 + 1.4142, 0.5, 0.0), 0.5))
    atoms.append(("C7B", "C", (3.55 + 1.4142, -0.5, 0.0), 0.5))
    return _structure(atoms, (16, 16, 16, 90, 90, 90), sg="P -1")


#: SHELX PART numbers of the `organic_p_1` disorder pair
ORGANIC_PARTS = {"C7A": 1, "C7B": 2}


def ionic_salt():
    """(iii) NaCl-type lattice, a = 5.70 A, Na-Cl 2.850 A, CN 6.

    a is 5.70 rather than the real 5.64 on purpose: at 5.64 the Na...Na
    distance (3.988 A) sits 0.004 A above the structviews x1.2 cutoff
    (3.984 A), and a status-quo photograph must not balance on a knife edge.
    """
    a = 5.70
    return _structure([("NA1", "Na", (0.0, 0.0, 0.0)),
                       ("CL1", "Cl", (a / 2, 0.0, 0.0))],
                      (a, a, a, 90, 90, 90), sg="F m -3 m")


def organometallic():
    """(iv) four separated fragments in one 40 A P1 box.

    FE1  ferrocene-like, two staggered C5 rings, Fe-C 2.050 A (eta5)
    ZR1  Zr-CH3 2.280 A (a real sigma-alkyl bond) plus a chelating acetate
         whose carboxylate carbon C12 is 2.500 A from Zr (NOT a bond: it is
         1-3 through O31 at 1.980 A) - `nodes.prune_long_metal_contacts`
         names exactly this pattern, "Zr...C(carboxylate) 2.5 A"
    OS1  OsCl4; Os has NO MetalProfile entry, so its coordination number is
         the three-state case (checked=False, plausible=None)
    LA1  a bare La 2.880 A above the centroid of a C6 ring, i.e. La...C
         3.200 A for all six carbons - the other false bond recorded in
         `prune_long_metal_contacts`, "La...C(arene) 3.2 A"
    """
    atoms = []
    fe = np.array([8.0, 8.0, 8.0])
    r = 1.42 / (2 * math.sin(math.radians(36)))
    h = math.sqrt(2.05 ** 2 - r ** 2)
    atoms.append(("FE1", "Fe", tuple(fe)))
    for k in range(5):
        a = math.radians(72 * k)
        atoms.append((f"C{k + 1}", "C",
                      tuple(fe + [r * math.cos(a), r * math.sin(a), h])))
    for k in range(5):
        a = math.radians(72 * k + 36)
        atoms.append((f"C{k + 6}", "C",
                      tuple(fe + [r * math.cos(a), r * math.sin(a), -h])))

    zr = np.array([24.0, 8.0, 8.0])
    atoms.append(("ZR1", "Zr", tuple(zr)))
    methyl_c = zr + np.array([2.28, 0.0, 0.0])
    atoms.append(("C11", "C", tuple(methyl_c)))
    for k in range(3):             # umbrella pointing away from the metal
        a = math.radians(120 * k)
        v = np.array([math.cos(math.radians(70.5)),
                      math.sin(math.radians(70.5)) * math.cos(a),
                      math.sin(math.radians(70.5)) * math.sin(a)])
        atoms.append((f"H11{'ABC'[k]}", "H", tuple(methyl_c + 0.98 * v)))
    c12, o31, o41 = _chelate(zr, (-1, 0, 0), (0, 0, 1))
    atoms += [("C12", "C", tuple(c12)), ("O31", "O", tuple(o31)),
              ("O41", "O", tuple(o41)),
              ("C13", "C", tuple(c12 + np.array([-1.52, 0.0, 0.0])))]

    os_c = np.array([8.0, 24.0, 8.0])
    atoms.append(("OS1", "Os", tuple(os_c)))
    for k, v in enumerate([(1, 1, 1), (1, -1, -1), (-1, 1, -1), (-1, -1, 1)]):
        u = np.array(v, float) / math.sqrt(3.0)
        atoms.append((f"CL{k + 1}", "Cl", tuple(os_c + 2.30 * u)))

    la = np.array([24.0, 24.0, 8.0])
    atoms.append(("LA1", "La", tuple(la)))
    z = math.sqrt(3.2 ** 2 - 1.39 ** 2)
    for k in range(6):
        a = math.radians(60 * k)
        atoms.append((f"C2{k}", "C",
                      tuple(la + [1.39 * math.cos(a), 1.39 * math.sin(a), z])))
    return _structure(atoms, (40, 40, 40, 90, 90, 90))


# ------------------------------------------------- the five criteria, today --

def _norm(triples):
    return {(min(a, b), max(a, b), round(float(d), 2)) for a, b, d in triples}


def edges_connectivity(xs, parts=None):
    """1. chem.connectivity.analyze_connectivity (works in P1)."""
    from crystalpilot.chem.connectivity import analyze_connectivity
    labels = [sc.label for sc in xs.expand_to_p1().scatterers()]
    rep = analyze_connectivity(xs, parts=parts)
    return _norm((labels[b.i], labels[b.j], b.length) for b in rep.bonds)


def _from_pair_sym_table(xs, pst):
    uc = xs.unit_cell()
    scs = list(xs.scatterers())
    return _norm(
        (scs[i].label, scs[int(j)].label,
         uc.distance(scs[i].site, op * scs[int(j)].site))
        for i, row in enumerate(pst) for j, ops in row.items() for op in ops)


def _part_kwargs(xs, parts):
    from crystalpilot.refine.nodes import part_kwargs_from_parts
    if not parts:
        return {}
    return part_kwargs_from_parts(
        [int(parts.get(sc.label.upper(), parts.get(sc.label, 0)) or 0)
         for sc in xs.scatterers()])


def edges_scene(xs, parts=None):
    """2. refine.scene._pair_sym_table (the raw smtbx table)."""
    from crystalpilot.refine.scene import _pair_sym_table
    return _from_pair_sym_table(xs, _pair_sym_table(xs, parts))


def edges_structviews(xs, state="asu", parts=None):
    """3. report.structviews._bonds over the drawn instances (since
    migration 2: the classified table on the viewer's closure)."""
    from crystalpilot.report.structviews import _bonds, _expand
    pts, _elems, labels, _corners, inst, table = _expand(
        xs, state, _part_kwargs(xs, parts))
    return _norm((labels[i], labels[j],
                  float(np.linalg.norm(pts[i] - pts[j])))
                 for i, j, _kind in _bonds(table, inst))


def edges_inspect(xs, parts=None):
    """4. refine.inspect._neighbor_table."""
    from crystalpilot.refine.inspect import _neighbor_table
    scs = list(xs.scatterers())
    return _norm((scs[i].label, n["label"], n["d"])
                 for i, nbrs in enumerate(_neighbor_table(xs, _part_kwargs(xs, parts)))
                 for n in nbrs)


def edges_prune(xs, parts=None):
    """5. refine.nodes.prune_long_metal_contacts on the smtbx table."""
    import smtbx.utils

    from crystalpilot.refine.nodes import prune_long_metal_contacts
    ct = smtbx.utils.connectivity_table(xs, **_part_kwargs(xs, parts))
    prune_long_metal_contacts(ct, xs)
    return _from_pair_sym_table(xs, ct.pair_asu_table.extract_pair_sym_table(
        skip_j_seq_less_than_i_seq=False, all_interactions_from_inside_asu=True))


def metal_edges(edges, xs):
    """Sub-set of an edge set that touches a metal (labels read off `xs`)."""
    from crystalpilot.chem.knowledge import is_metal
    metals = {sc.label.upper() for sc in xs.scatterers()
              if is_metal(sc.scattering_type.strip().capitalize())}
    return {e for e in edges if e[0].upper() in metals or e[1].upper() in metals}


# ------------------------------------------------------------ fixture check --

class TestFixtureGeometry:
    """The fixtures must mean what the docstrings say before anything else."""

    def test_mof_distances(self):
        xs = mof_chain()
        uc = xs.unit_cell()
        d = {sc.label: sc.site for sc in xs.scatterers()}
        assert round(uc.distance(d["CU1"], d["O1"]), 3) == 1.950
        assert round(uc.distance(d["CU1"], d["O3"]), 3) == 1.980
        assert round(uc.distance(d["CU1"], d["O4"]), 3) == 2.410
        assert round(uc.distance(d["CU1"], d["C2"]), 3) == 2.500
        # the chelating O and C are inside the 2.3-2.6 A band from the plan
        assert 2.3 <= uc.distance(d["CU1"], d["O4"]) <= 2.6
        assert 2.3 <= uc.distance(d["CU1"], d["C2"]) <= 2.6

    def test_organic_distances(self):
        from cctbx import sgtbx
        xs = organic_p_1()
        uc = xs.unit_cell()
        d = {sc.label: sc.site for sc in xs.scatterers()}
        inv = sgtbx.rt_mx("-x,-y,-z")
        assert round(uc.distance(d["C1"], inv * d["C1"]), 3) == 1.540
        assert round(uc.distance(d["C7A"], d["C7B"]), 3) == 1.000
        assert round(uc.distance(d["C4"], d["C7A"]), 3) == 1.500
        assert round(uc.distance(d["C2"], d["H2"]), 3) == 0.950

    def test_organometallic_distances(self):
        xs = organometallic()
        uc = xs.unit_cell()
        d = {sc.label: sc.site for sc in xs.scatterers()}
        assert round(uc.distance(d["FE1"], d["C1"]), 3) == 2.050
        assert round(uc.distance(d["ZR1"], d["C11"]), 3) == 2.280
        assert round(uc.distance(d["ZR1"], d["C12"]), 3) == 2.500
        assert round(uc.distance(d["ZR1"], d["O31"]), 3) == 1.980
        assert round(uc.distance(d["OS1"], d["CL1"]), 3) == 2.300
        assert round(uc.distance(d["LA1"], d["C20"]), 3) == 3.200


# ------------------------------------------------------- (i) MOF-like chain --

class TestMofChainStatusQuo:
    BACKBONE = {
        ("C1", "O1", 1.25), ("C1", "O2", 1.25), ("C2", "C3", 1.52),
        ("C2", "O3", 1.25), ("C2", "O4", 1.25), ("CU1", "O1", 1.95),
    }

    def test_five_criteria(self):
        xs = mof_chain()
        # 1. connectivity: the Cu-O window (MetalProfile 1.85-2.60) takes both
        #    chelating O; the carboxylate C is refused by the flat 2.15 M-C
        #    cutoff - the only one of the five that gets this pair right
        assert edges_connectivity(xs) == self.BACKBONE | {
            ("CU1", "O2", 1.95), ("CU1", "O3", 1.98), ("CU1", "O4", 2.41)}
        truth = self.BACKBONE | {
            ("CU1", "O2", 1.95), ("CU1", "O3", 1.98), ("CU1", "O4", 2.41)}
        # 2. scene (migration 3): the classified table. Before: the raw
        #    smtbx table bonded Cu...C 2.50 A (sum(r_cov) 2.08 + 0.5 = 2.58)
        #    -> a false bond in the viewer, Cu CN 5
        assert edges_scene(xs) == truth
        # 4. inspect (migration 1): the carboxylate carbon is a chelate-bite
        #    contact (`non_bonded_close`), hidden from the neighbour table;
        #    the edge set equals criterion 1's
        assert edges_inspect(xs) == truth
        # 3. structviews (asu state, migration 2): the classified table on
        #    the ASU instances - the bridging Cu-O2 that closes the chain
        #    through the cell face is a symmetry image and is NOT drawn in
        #    the asu state (its partner instance is not on screen), but the
        #    chelating O4 at 2.41 is a bond again (the old x1.2 rule cut it
        #    at 2.376) and the carboxylate carbon is not
        assert edges_structviews(xs) == self.BACKBONE | {
            ("CU1", "O3", 1.98), ("CU1", "O4", 2.41)}
        # ...and the packed cell draws FEWER of them: this fixture is a 1-D
        #    polymer, and polymeric components are wrapped atom by atom (the
        #    viewer's convention, `_wrapped_groups`), so a partner that wraps
        #    to the far face of the cell is not on screen and its bond is not
        #    drawn (O3 at z = -0.06 -> 0.94: Cu-O3 and C2-O3 vanish, Cu-O2
        #    closes only through the x-1 image). Whole-molecule wrapping is
        #    for FINITE molecules (see the organic fixture).
        cell = edges_structviews(xs, "cell")
        assert cell < edges_inspect(xs)
        assert ("CU1", "O1", 1.95) in cell and ("CU1", "O3", 1.98) not in cell
        # 5. prune_long_metal_contacts (migration 1b): the classified metal
        #    edges survive - before, sum(r_cov) 1.98 A deleted the chelating
        #    Cu-O3 (1.9804) and Cu-O4 (2.4101), two REAL coordination bonds
        #    (D18); a Jahn-Teller axial Cu-O can legitimately reach 2.6 A
        assert edges_prune(xs) == edges_inspect(xs)

    def test_the_metal_edge_set_differs_two_ways(self):
        """Four distinct answers among the five criteria before migration 1,
        three after 1b, two after 3: connectivity, scene, inspect and prune
        agree (4 edges); structviews (asu state) draws 3 of those 4 because
        the fourth closes through an undrawn symmetry image (migration 2)."""
        xs = mof_chain()
        got = {name: sorted(metal_edges(fn(xs), xs))
               for name, fn in (("connectivity", edges_connectivity),
                                ("scene", edges_scene),
                                ("structviews", edges_structviews),
                                ("inspect", edges_inspect),
                                ("prune", edges_prune))}
        assert [len(v) for v in got.values()] == [4, 4, 3, 4, 4]
        assert len({tuple(v) for v in got.values()}) == 2
        assert (got["connectivity"] == got["scene"] == got["inspect"]
                == got["prune"])
        # structviews (asu state) is the truth minus the undrawn image
        assert set(got["structviews"]) < set(got["inspect"])


# --------------------------------------------------- (ii) organic, P-1, PART --

class TestOrganicStatusQuo:
    RING = {
        ("C1", "C2", 1.39), ("C1", "C6", 1.39), ("C2", "C3", 1.39),
        ("C3", "C4", 1.39), ("C4", "C5", 1.39), ("C5", "C6", 1.39),
        ("C2", "H2", 0.95), ("C3", "H3", 0.95), ("C5", "H5", 0.95),
        ("C6", "H6", 0.95), ("C4", "C7A", 1.50), ("C4", "C7B", 1.50),
    }
    SYM_BOND = ("C1", "C1", 1.54)
    DISORDER_PAIR = ("C7A", "C7B", 1.00)

    def test_without_parts(self):
        xs = organic_p_1()
        # connectivity is alone in refusing the 1.00 A C7A...C7B pair, and it
        # refuses it as an IMPOSSIBLE contact (0.75 * sum(r_cov) = 1.14 A),
        # not as a disorder alternative - it never sees the PART numbers here
        assert edges_connectivity(xs) == self.RING | {self.SYM_BOND}
        from crystalpilot.chem.connectivity import analyze_connectivity
        rep = analyze_connectivity(xs)
        assert [(s["atoms"], s["d"]) for s in rep.short_contacts] == [
            (["C7A", "C7B"], 1.0)]
        # everything else bonds the two disorder components to each other
        assert edges_scene(xs) == self.RING | {self.SYM_BOND, self.DISORDER_PAIR}
        assert edges_inspect(xs) == self.RING | {self.SYM_BOND, self.DISORDER_PAIR}
        assert edges_prune(xs) == self.RING | {self.SYM_BOND, self.DISORDER_PAIR}
        # structviews (asu state): the C1-C1' bond across the inversion
        # centre is a symmetry image whose partner is not drawn in the asu
        # state, so it is absent here and present in the packed cell
        assert edges_structviews(xs) == self.RING | {self.DISORDER_PAIR}
        assert self.SYM_BOND in edges_structviews(xs, "cell")

    def test_with_parts(self):
        xs = organic_p_1()
        p = ORGANIC_PARTS
        # smtbx conformer_indices do the right thing for the three consumers
        # that pass PART numbers down at all...
        for fn in (edges_scene, edges_inspect, edges_prune):
            assert fn(xs, p) == self.RING | {self.SYM_BOND}
        assert edges_connectivity(xs, p) == self.RING | {self.SYM_BOND}
        # ...and structviews too since migration 2 (it drew a 1.00 A bond
        # between PART 1 and PART 2 before, `_bonds` had no PART parameter
        # at all - D8/D10); without the PART numbers it still does
        assert self.DISORDER_PAIR not in edges_structviews(xs, "asu", p)
        assert self.DISORDER_PAIR in edges_structviews(xs)

    def test_structviews_cell_state_keeps_the_molecule_whole(self):
        """Before migration 2 `_expand(state="cell")` wrapped every atom
        into [0,1) on its own, so a molecule sitting on the origin came
        apart: 9 of the 14 bonds survived and the ring was cut open. The
        packed states now reuse the viewer's centroid wrapping
        (`refine.scene._wrapped_groups`): all 14 bonds, ring closed, and the
        inversion-related pivot bond drawn."""
        cell = edges_structviews(organic_p_1(), "cell")
        assert cell == self.RING | {self.SYM_BOND, self.DISORDER_PAIR}
        assert len(cell) == 14


# ---------------------------------------------------------- (iii) ionic salt --

class TestIonicSaltStatusQuo:
    NACL = {("CL1", "NA1", 2.85)}

    def test_all_five_criteria_agree(self):
        xs = ionic_salt()
        assert edges_connectivity(xs) == self.NACL
        assert edges_scene(xs) == self.NACL
        assert edges_structviews(xs) == self.NACL
        assert edges_inspect(xs) == self.NACL
        # sum(r_cov) for Na-Cl is 2.68 A and the lattice sits at 2.85, so
        # prune_long_metal_contacts used to remove all 12 listed pairs (rock
        # salt had no bonds at all, D18); since migration 1b the unlisted-
        # metal window sum(r_cov)+0.45 keeps them
        assert edges_prune(xs) == self.NACL

    def test_connectivity_calls_it_a_3d_salt(self):
        from crystalpilot.chem.connectivity import analyze_connectivity
        rep = analyze_connectivity(ionic_salt())
        assert rep.system_type == "salt"
        assert rep.framework_dimensionality == 3
        assert rep.coordination[0]["cn"] == 6


# ------------------------------------------------------- (iv) organometallic --

class TestOrganometallicStatusQuo:
    """Only the metal-incident edges are written out: the 22 C-C / C-H edges
    are identical under all five criteria and would drown the interesting
    rows. The totals below pin them anyway."""

    ETA_CP = {(f"C{k}", "FE1", 2.05) for k in range(1, 11)}
    OS_CL = {(f"CL{k}", "OS1", 2.30) for k in range(1, 5)}
    ZR_O = {("O31", "ZR1", 1.98), ("O41", "ZR1", 2.41)}
    ZR_METHYL = ("C11", "ZR1", 2.28)
    ZR_CARBOXYLATE_C = ("C12", "ZR1", 2.50)
    LA_ARENE = {(f"C2{k}", "LA1", 3.20) for k in range(6)}

    def test_five_criteria_on_the_metal_edges(self):
        xs = organometallic()
        truth = self.ETA_CP | self.OS_CL | self.ZR_O | {self.ZR_METHYL}
        # 1. connectivity (migration 5): the classified set. Before: the
        #    flat 2.15 A M-C cutoff refused the REAL Zr-CH3 sigma bond
        #    (2.28) together with the false Zr...C(carboxylate) (2.50) and
        #    the false La...C(arene) (3.20) - one constant doing the work of
        #    three different chemical judgements (D9)
        assert metal_edges(edges_connectivity(xs), xs) == truth
        # 2. scene (migration 3): the classified set. Before: everything
        #    within sum(r_cov)+0.5 (smtbx) was drawn as a bond, including
        #    all six La...C(arene) 3.20 A contacts and the carboxylate carbon
        assert metal_edges(edges_scene(xs), xs) == truth
        # 3. structviews (migration 2): the classified set, as inspect
        #    (before: the x1.2 rule gave the same loose set as smtbx)
        assert metal_edges(edges_structviews(xs), xs) == truth
        # 4. inspect (migration 1): the classified table - eta ring atoms,
        #    OsCl4 through the unlisted-metal window, both acetate O, the
        #    Zr-CH3 sigma bond; the carboxylate C (chelate bite) and the six
        #    La...C(arene) contacts (beyond sum(r_cov), not eta) are gone
        assert metal_edges(edges_inspect(xs), xs) == (
            self.ETA_CP | self.OS_CL | self.ZR_O | {self.ZR_METHYL})
        # 5. prune (migration 1b): the same classified set as inspect.
        #    Before: dropped the six La...C (3.20 > 2.83) as its docstring
        #    promised, but kept the Zr...C(carboxylate) at 2.50 by 0.01 A
        #    (sum(r_cov) 2.51) and deleted the real Zr-O41 at 2.41
        #    (sum(r_cov) 2.4100) - the pattern was right, the constant not
        assert metal_edges(edges_prune(xs), xs) == (
            self.ETA_CP | self.OS_CL | self.ZR_O | {self.ZR_METHYL})

    def test_totals(self):
        xs = organometallic()
        assert len(edges_connectivity(xs)) == 39   # 38 before migration 5
        assert len(edges_scene(xs)) == 39        # 46 before migration 3
        assert len(edges_structviews(xs)) == 39  # 46 before migration 2
        assert len(edges_inspect(xs)) == 39      # 46 before migration 1
        assert len(edges_prune(xs)) == 39        # same 39 by coincidence
        #   before 1b: 46 - 6 La...C - 1 Zr-O41; after: 46 - 6 La...C - 1 Zr...C12

    def test_only_connectivity_knows_the_cp_rings_are_eta(self):
        from crystalpilot.chem.connectivity import analyze_connectivity
        rep = analyze_connectivity(organometallic())
        assert len(rep.pi_ligands) == 2
        assert {r["hapticity"] for r in rep.pi_ligands} == {5}
        assert {b.kind for b in rep.bonds} == {"sigma", "eta"}
        # the other four criteria have no notion of hapticity: for them the
        # ten Fe-C contacts are ten separate ligands


# ------------------------------------------------------ coordination numbers --

class TestCoordinationNumbersStatusQuo:
    """Where the disagreement actually reaches the user: two different CN for
    the same atom, and a metal with no knowledge entry passing validation."""

    def test_mof_metal(self):
        from crystalpilot.chem.connectivity import analyze_connectivity
        from crystalpilot.refine.inspect import metal_environments
        xs = mof_chain()
        assert analyze_connectivity(xs).coordination[0]["cn"] == 4
        # inspect counted the carboxylate carbon as a ligand (CN 5) until
        # migration 1; both read 4 now, and inspect's verdict is three-state
        env = metal_environments(xs)[0]
        assert env["cn"] == 4
        assert env["cn_plausible"] is True and env["expected_cn"] == [2, 6]

    def test_organometallic_metals(self):
        from crystalpilot.chem.connectivity import analyze_connectivity
        from crystalpilot.refine.inspect import metal_environments
        xs = organometallic()
        conn = {e["atom"]: e for e in analyze_connectivity(xs).coordination}
        insp = {e["atom"]: e for e in metal_environments(xs)}
        # eta ring = one ligand in both now (inspect said 10 before
        # migration 1: ten separate carbons)
        assert (conn["FE1"]["cn"], insp["FE1"]["cn"]) == (2, 2)
        assert insp["FE1"]["n_eta_atoms"] == 10
        # Zr: 2 O + the methyl sigma bond, not the chelate carbon (before
        # migration 5 connectivity refused both M-C with its flat 2.15 A:
        # 2; inspect said 4 before migration 1: 2 O + methyl + carboxylate C)
        assert (conn["ZR1"]["cn"], insp["ZR1"]["cn"]) == (3, 3)
        # La: nothing at all in both (inspect said 6 before migration 1)
        assert (conn["LA1"]["cn"], insp["LA1"]["cn"]) == (0, 0)
        assert (conn["OS1"]["cn"], insp["OS1"]["cn"]) == (4, 4)
        # the unlisted metal is "not checked" in inspect, never a pass
        assert insp["OS1"]["cn_plausible"] is None
        assert insp["OS1"]["expected_cn"] is None

    def test_unlisted_metal_is_not_checked_not_passed(self):
        """D9: Os has no MetalProfile. Before migration 5 `cn_plausible`
        was True - a silent pass; it is now None ("not checked") with a
        note, and `validate_structure` reports it as an info alert."""
        from crystalpilot.chem.connectivity import analyze_connectivity
        conn = {e["atom"]: e for e in analyze_connectivity(organometallic()).coordination}
        assert conn["OS1"]["cn_plausible"] is None
        assert conn["OS1"]["expected_cn"] is None
        assert "NOT checked" in conn["OS1"]["cn_note"]
        # while a listed metal with the same CN gets a real verdict
        assert conn["ZR1"]["cn_plausible"] is False
        assert conn["ZR1"]["expected_cn"] == [6, 9]
