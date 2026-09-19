"""`chem/shape.py`: continuous shape measures, macrocycle census, shape evidence.

Everything here is an ANALYTIC fixture - ideal polyhedra, synthetic rings,
points on a line - and every expected number is either a published constant or
derived in the test that asserts it. No crystal, no data file, no element
special-cased.

The sharpest of the checks are the four literature constants of the CShM
definition, because they only come out right if the permutation search, the
Kabsch rotation and the scale minimisation are all correct at once:

    ideal octahedron        S(TPR-6) = 16.737     (Alvarez 2005 / SHAPE)
    ideal trigonal prism    S(OC-6)  = 16.737
    ideal square            S(T-4)   = 33.333
    ideal tetrahedron       S(SP-4)  = 33.333

Get the permutations wrong and the octahedron measures against some skew
vertex pairing (S far above 16.737); forget the scale minimisation and every
measure inherits the arbitrary size of the reference; drop the det > 0 branch
of Kabsch and a reflection sneaks in.
"""
from __future__ import annotations

import math
import time

import numpy as np
import pytest
from cctbx import crystal, sgtbx, xray

from crystalpilot.chem.shape import (REFERENCE_SHAPES, SHAPES_BY_CN,
                                     SPY5_APICAL_BASAL_DEG,
                                     crystallographic_point_symmetry, cshm,
                                     largest_cycle, shape_evidence)

# --------------------------------------------------------------- helpers --


def rotation(axis, angle_deg):
    """Rodrigues rotation matrix (right-handed, active)."""
    k = np.asarray(axis, float)
    k = k / np.linalg.norm(k)
    a = math.radians(angle_deg)
    kx = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    return np.eye(3) + math.sin(a) * kx + (1 - math.cos(a)) * (kx @ kx)


def ring_graph(n, offset=0):
    """`{i: set(j)}` of an n-membered ring, atoms offset..offset+n-1."""
    adj = {offset + i: set() for i in range(n)}
    for i in range(n):
        a, b = offset + i, offset + (i + 1) % n
        adj[a].add(b)
        adj[b].add(a)
    return adj


def link(adj, *pairs):
    for a, b in pairs:
        adj.setdefault(a, set()).add(b)
        adj.setdefault(b, set()).add(a)
    return adj


def structure(cart, elements, cell=(10.0, 11.0, 12.0, 90.0, 90.0, 90.0), sg="P -1"):
    """cartesian positions + element symbols -> cctbx.xray.structure."""
    cs = crystal.symmetry(unit_cell=cell, space_group_symbol=sg)
    xs = xray.structure(crystal_symmetry=cs)
    uc = cs.unit_cell()
    for k, (c, e) in enumerate(zip(cart, elements)):
        xs.add_scatterer(xray.scatterer(label=f"{e}{k}", site=uc.fractionalize(c),
                                        scattering_type=e, u=0.03))
    return xs


def berry(t, apical_basal=SPY5_APICAL_BASAL_DEG):
    """One point on the Berry pseudorotation path, t in [0, 1].

    Pivot ligand fixed on +x. The two axial ligands of the trigonal
    bipyramid bend away from the pivot (their polar angle measured from +x
    opens 90 -> `apical_basal`) while the two non-pivot equatorial ligands
    close in (azimuth from +x 120 -> `apical_basal`). At t = 0 this is the
    ideal D3h trigonal bipyramid, at t = 1 the ideal C4v square pyramid with
    the pivot as its apex - which is why the SAME angle drives both ends.
    """
    th = math.radians(90.0 + (apical_basal - 90.0) * t)
    psi = math.radians(120.0 - (120.0 - apical_basal) * t)
    return np.array([
        (1.0, 0.0, 0.0),                                    # pivot
        (math.cos(th), 0.0, math.sin(th)),                  # axial
        (math.cos(th), 0.0, -math.sin(th)),                 # axial
        (math.cos(psi), math.sin(psi), 0.0),                # equatorial
        (math.cos(psi), -math.sin(psi), 0.0),               # equatorial
    ], float)


# ============================================================ 1. CShM ======

def test_ideal_octahedron_hits_both_literature_constants():
    """S(OC-6) = 0 and S(TPR-6) = 16.737 for a regular octahedron."""
    got = cshm((0, 0, 0), REFERENCE_SHAPES["OC-6"])
    assert got["cn"] == 6
    assert got["cshm"]["OC-6"] < 0.01
    assert got["cshm"]["TPR-6"] == pytest.approx(16.737, abs=0.01)
    assert got["closest_shape"] == "OC-6"
    assert got["closest_cshm"] < 0.01


def test_ideal_trigonal_prism_hits_the_same_constant():
    """The measure is symmetric in this pair: S(OC-6) of a regular trigonal
    prism is the same 16.737. (It is not symmetric in general - S is not a
    metric - but both shapes have the same number of vertices and the same
    vertex spread, so here it is.)"""
    got = cshm((0, 0, 0), REFERENCE_SHAPES["TPR-6"])
    assert got["cshm"]["TPR-6"] < 0.01
    assert got["cshm"]["OC-6"] == pytest.approx(16.737, abs=0.01)
    assert got["closest_shape"] == "TPR-6"


def test_perfect_square_against_the_tetrahedron_is_33_33():
    got = cshm((0, 0, 0), REFERENCE_SHAPES["SP-4"])
    assert got["cn"] == 4
    assert got["cshm"]["SP-4"] < 0.01
    assert got["cshm"]["T-4"] == pytest.approx(33.33, abs=0.02)
    assert got["closest_shape"] == "SP-4"


def test_regular_tetrahedron_against_the_square_is_33_33():
    got = cshm((0, 0, 0), REFERENCE_SHAPES["T-4"])
    assert got["cshm"]["T-4"] < 0.01
    assert got["cshm"]["SP-4"] == pytest.approx(33.33, abs=0.02)
    assert got["closest_shape"] == "T-4"


def test_square_and_tetrahedron_constant_is_exactly_100_over_3():
    """Both 33.33 values are 100/3 exactly, which is the arithmetic that pins
    the scale step. For the square Q (four unit vectors, centroid at the
    origin) and the tetrahedron P (four unit vectors, centroid at the
    origin), the best permutation gives H = P^T Q with singular values
    (sqrt(8/3), sqrt(8/3), 0), so max_R tr(RH) = 2 sqrt(8/3) and

        S = 100 (1 - (2 sqrt(8/3))^2 / (4 x 4)) = 100 (1 - 2/3) = 100/3.
    """
    assert cshm((0, 0, 0), REFERENCE_SHAPES["SP-4"])["cshm"]["T-4"] == \
        pytest.approx(100.0 / 3.0, abs=0.002)
    assert cshm((0, 0, 0), REFERENCE_SHAPES["T-4"])["cshm"]["SP-4"] == \
        pytest.approx(100.0 / 3.0, abs=0.002)


def test_trigonal_bipyramid_pins_the_derived_spy5_value():
    """S(TBPY-5) = 0 and S(SPY-5) = 5.375 for an ideal trigonal bipyramid.

    DERIVATION of the 5.375 (it is computed here, not quoted): the SPY-5
    reference of this module is the C4v square pyramid whose apical-basal
    angle is 104.9 deg (Alvarez 2005), i.e. apex on +z and four basal
    vertices at polar angle 104.9 deg and azimuths 0/90/180/270, all on the
    unit sphere, central atom at the origin. Measuring the ideal D3h trigonal
    bipyramid (axial +-z, three equatorial at 120 deg) against it under this
    module's convention - central atom as an extra unpermuted vertex, both
    sets centred on their own centroid, 5! = 120 permutations - gives
    5.3752.

    The value is shallow in the reference angle: 5.383 at 104.5 deg, 5.375 at
    104.9 deg, 5.374 at 105.0 deg. That is why it is pinned to three decimals
    WITH the angle attached, and why comparing against a published SHAPE
    table means checking that table's SPY-5 angle first. The test asserts the
    angle it depends on.
    """
    assert SPY5_APICAL_BASAL_DEG == 104.9
    got = cshm((0, 0, 0), REFERENCE_SHAPES["TBPY-5"])
    assert got["cn"] == 5
    assert got["cshm"]["TBPY-5"] < 0.01
    assert got["cshm"]["SPY-5"] == pytest.approx(5.375, abs=0.01)
    assert got["cshm"]["vOC-5"] == pytest.approx(7.342, abs=0.01)
    assert got["closest_shape"] == "TBPY-5"

    # and the reverse direction, same number
    back = cshm((0, 0, 0), REFERENCE_SHAPES["SPY-5"])
    assert back["cshm"]["TBPY-5"] == pytest.approx(5.375, abs=0.01)
    assert back["cshm"]["SPY-5"] < 0.01


def test_berry_midpoint_is_equidistant_from_both_cn5_references():
    """Halfway along the Berry pseudorotation the two CN-5 references are
    equally far away, and both are far below the 5.375 that separates the
    ideal ends - the shape sits on the interconversion path, not at either
    end of it."""
    ends_t = cshm((0, 0, 0), berry(0.0))
    ends_s = cshm((0, 0, 0), berry(1.0))
    assert ends_t["cshm"]["TBPY-5"] < 0.01
    assert ends_s["cshm"]["SPY-5"] < 0.01

    mid = cshm((0, 0, 0), berry(0.5))["cshm"]
    assert mid["TBPY-5"] == pytest.approx(mid["SPY-5"], abs=0.01)
    assert 0.5 < mid["TBPY-5"] < 5.375
    # the path is monotone in each measure
    quarter = cshm((0, 0, 0), berry(0.25))["cshm"]
    assert quarter["TBPY-5"] < mid["TBPY-5"] < cshm((0, 0, 0), berry(0.75))["cshm"]["TBPY-5"]


def test_invariant_under_rotation_uniform_scaling_translation_and_reordering():
    """A distorted sphere (so the numbers are not trivially 0) measured four
    ways gives the same measures to the last reported decimal."""
    rng = np.random.default_rng(20260904)
    lig = REFERENCE_SHAPES["OC-6"] * 2.05 + rng.normal(0.0, 0.08, (6, 3))
    centre = np.array([0.03, -0.02, 0.05])
    base = cshm(centre, lig)["cshm"]

    r = rotation((0.3, -0.7, 0.6), 47.0)
    t = np.array([12.0, -3.5, 8.25])
    moved = cshm(centre @ r.T + t, lig @ r.T + t)["cshm"]
    assert moved == base

    scaled = cshm(centre * 3.7, lig * 3.7)["cshm"]
    assert scaled == base

    order = [4, 0, 5, 2, 1, 3]
    assert cshm(centre, lig[order])["cshm"] == base


def test_no_reference_shapes_outside_cn_4_to_6_is_a_note_not_an_exception():
    for n in (0, 1, 2, 3, 7, 8, 12):
        got = cshm((0, 0, 0), np.linspace(1.0, 2.0, 3 * n).reshape(n, 3) if n else
                   np.zeros((0, 3)))
        assert got["cn"] == n
        assert got["cshm"] == {}
        assert got["closest_shape"] is None
        assert got["closest_cshm"] is None
        assert got["note"] == f"no reference shapes for CN {n}"
    assert set(SHAPES_BY_CN) == {4, 5, 6}


def test_requested_shapes_are_filtered_and_unusable_names_are_reported():
    got = cshm((0, 0, 0), REFERENCE_SHAPES["OC-6"], shapes=["OC-6", "T-4", "banana"])
    assert set(got["cshm"]) == {"OC-6"}
    assert "T-4 has 4 vertices, not 6 - skipped" in got["note"]
    assert "no reference shape named 'banana' - skipped" in got["note"]

    none_apply = cshm((0, 0, 0), REFERENCE_SHAPES["OC-6"], shapes=["T-4"])
    assert none_apply["cshm"] == {}
    assert none_apply["closest_shape"] is None


def test_coincident_ligands_are_reported_not_raised():
    got = cshm((0, 0, 0), np.zeros((6, 3)))
    assert got["cshm"] == {}
    assert "no spread" in got["note"]


def test_method_text_names_the_convention_and_carries_no_verdict():
    got = cshm((0, 0, 0), REFERENCE_SHAPES["OC-6"])
    method = got["method"]
    assert "Pinsky & Avnir 1998" in method
    assert "Alvarez 2005" in method
    assert "6! = 720" in method
    assert "Kabsch" in method
    assert "Central atom included as an extra unpermuted vertex" in method
    assert f"SPY-5 apical-basal angle {SPY5_APICAL_BASAL_DEG} deg" in method
    blob = (method + " " + got["note"]).lower()
    for verdict in ("distorted", "ideal geometry", "good", "bad", "poor",
                    "acceptable", "suspicious"):
        assert verdict not in blob


def test_excluding_the_centre_is_available_and_named_in_the_method():
    """Both conventions agree on an ideal polyhedron (the central atom sits
    at the centroid, so the extra vertex adds nothing) and differ once the
    centre is off the polyhedron centre - which is exactly what including it
    is for."""
    ideal_with = cshm((0, 0, 0), REFERENCE_SHAPES["OC-6"])["cshm"]
    ideal_without = cshm((0, 0, 0), REFERENCE_SHAPES["OC-6"], include_centre=False)["cshm"]
    assert ideal_with == ideal_without

    off = (0.35, 0.0, 0.0)
    assert cshm(off, REFERENCE_SHAPES["OC-6"])["cshm"]["OC-6"] > \
        cshm(off, REFERENCE_SHAPES["OC-6"], include_centre=False)["cshm"]["OC-6"]
    assert "central atom excluded" in \
        cshm(off, REFERENCE_SHAPES["OC-6"], include_centre=False)["method"].lower()


def test_cn6_720_permutations_stay_far_under_a_second():
    rng = np.random.default_rng(11)
    lig = REFERENCE_SHAPES["OC-6"] * 2.1 + rng.normal(0.0, 0.07, (6, 3))
    best = min(_timed(lambda: cshm((0, 0, 0), lig)) for _ in range(3))
    assert best < 1.0, f"CN 6 CShM took {best:.3f} s"


def _timed(fn):
    t0 = time.perf_counter()
    fn()
    return time.perf_counter() - t0


def test_the_wiring_next_to_tau4_tau5_works_on_what_metal_environments_has():
    """The API contract with `refine.inspect.metal_environments` (which this
    branch does not edit): that function already holds the metal's fractional
    site, the fractional sites of its classified ligands and the unit cell,
    and `cshm` takes exactly those, orthogonalised. Here is the whole wiring,
    run on a synthetic ZnO6 octahedron, ligands read through the ONE bonding
    truth."""
    from crystalpilot.refine.inspect import _neighbor_table, metal_environments

    cart = [(10.0, 10.0, 10.0)]
    for axis in range(3):
        for sign in (1.0, -1.0):
            v = [10.0, 10.0, 10.0]
            v[axis] += sign * 2.10
            cart.append(tuple(v))
    xs = structure(cart, ["Zn"] + ["O"] * 6,
                   cell=(20.0, 20.0, 20.0, 90.0, 90.0, 90.0), sg="P 1")

    nbt = _neighbor_table(xs)
    rows = metal_environments(xs, nbt)
    assert len(rows) == 1 and rows[0]["cn"] == 6

    uc = xs.unit_cell()
    sc = list(xs.scatterers())[0]
    coord = [n for n in nbt[0] if n.get("kind") == "coordination"]
    got = cshm(uc.orthogonalize(sc.site),
               [uc.orthogonalize(n["site_frac"]) for n in coord])
    assert got["cn"] == 6
    assert got["cshm"]["OC-6"] < 0.01
    assert got["cshm"]["TPR-6"] == pytest.approx(16.737, abs=0.01)
    assert got["closest_shape"] == "OC-6"


# ================================================== 2. macrocycle census ===

def test_benzene_ring_is_six():
    got = largest_cycle(ring_graph(6))
    assert got["size"] == 6
    assert sorted(got["atoms"]) == list(range(6))
    assert got["n_cycles_basis"] == 1
    assert got["truncated"] is False


def test_naphthalene_largest_chordless_cycle_is_six_not_ten():
    """The 10-membered perimeter is a cycle, but the ring-fusion bond joins
    two of its vertices that are four bonds apart along it - a chord. The
    largest CHORDLESS cycle is therefore one of the two six-rings, which is
    the ring size a crystallographer reads off naphthalene. The cycle space
    still counts two independent cycles."""
    adj = link(ring_graph(6), (0, 6), (6, 7), (7, 8), (8, 9), (9, 1))
    got = largest_cycle(adj)
    assert got["size"] == 6
    assert got["n_cycles_basis"] == 2
    assert got["truncated"] is False
    assert len(got["atoms"]) == 6


def test_synthetic_24_membered_macrocycle():
    got = largest_cycle(ring_graph(24))
    assert got["size"] == 24
    assert sorted(got["atoms"]) == list(range(24))
    assert got["truncated"] is False
    assert got["n_cycles_basis"] == 1


def test_a_30_ring_under_a_cap_of_24_reports_truncation_and_no_size():
    got = largest_cycle(ring_graph(30), cap=24)
    assert got["size"] is None
    assert got["atoms"] == []
    assert got["truncated"] is True
    assert "cap" in got["note"]
    assert got["n_cycles_basis"] == 1
    # the same ring with room to look is found whole
    assert largest_cycle(ring_graph(30), cap=64)["size"] == 30


def test_an_open_chain_has_no_ring():
    chain = {i: set() for i in range(6)}
    link(chain, *[(i, i + 1) for i in range(5)])
    got = largest_cycle(chain)
    assert got["size"] is None
    assert got["atoms"] == []
    assert got["n_cycles_basis"] == 0
    assert got["truncated"] is False
    assert "acyclic" in got["note"]


def test_the_dfs_budget_truncates_and_says_so():
    got = largest_cycle(ring_graph(24), budget=5)
    assert got["truncated"] is True
    assert "budget" in got["note"]


def test_comp_restricts_the_search_to_one_component():
    both = {**ring_graph(6), **ring_graph(24, offset=100)}
    assert largest_cycle(both)["size"] == 24
    assert largest_cycle(both, comp=range(6))["size"] == 6
    assert largest_cycle(both, comp=range(100, 124))["size"] == 24
    # a disconnected selection is reported, and the basis still adds up
    whole = largest_cycle(both)
    assert whole["n_cycles_basis"] == 2
    assert "not connected" in whole["note"]


def test_fused_bicyclics_count_their_independent_cycles():
    """Bicyclo[2.2.2]octane: two bridgeheads joined by three 2-carbon
    bridges. Three cycles in the graph, cyclomatic number 2, and every
    chordless cycle is a 6-ring."""
    adj: dict[int, set[int]] = {i: set() for i in range(8)}
    link(adj, (0, 1), (1, 2), (2, 7),      # bridge A: 0-1-2-7
         (0, 3), (3, 4), (4, 7),           # bridge B
         (0, 5), (5, 6), (6, 7))           # bridge C
    got = largest_cycle(adj)
    assert got["n_cycles_basis"] == 2
    assert got["size"] == 6
    assert got["truncated"] is False


def test_a_triangle_is_found():
    got = largest_cycle(ring_graph(3))
    assert got["size"] == 3
    assert sorted(got["atoms"]) == [0, 1, 2]


def test_a_one_way_adjacency_map_is_repaired_and_reported():
    """A half-filled map would silently lose rings, so it is symmetrised and
    the repair is named."""
    one_way = {i: {(i + 1) % 6} for i in range(6)}
    got = largest_cycle(one_way)
    assert got["size"] == 6
    assert "not symmetric (6 one-way entries)" in got["note"]
    assert largest_cycle(ring_graph(6))["note"] == ""


def test_degenerate_selections_are_reported_not_raised():
    assert largest_cycle({}, [])["size"] is None
    assert "empty" in largest_cycle({}, [])["note"]
    assert "empty" in largest_cycle(ring_graph(6), comp=[900, 901])["note"]
    tiny_cap = largest_cycle(ring_graph(6), cap=2)
    assert tiny_cap["size"] is None and tiny_cap["truncated"] is True
    assert "below the smallest possible ring" in tiny_cap["note"]


# ==================================================== 3. shape evidence ====

def test_regular_octahedron_of_points():
    """Analytic reference values for a regular octahedron of unit vectors:

        inertia (unit masses)  I1 = I2 = I3 = 4        -> ratios [1, 1]
        convex hull            V = 4/3, A = 2 sqrt(3) x (sqrt(2))^2 = 6.9282
        sphericity             pi^(1/3)(6V)^(2/3)/A = pi^(1/3)/sqrt(3)
                                                     = 0.845583
        bounding box           2 x 2 x 2               -> aspect [1, 1]
        longest axis           2.0
    """
    got = shape_evidence(REFERENCE_SHAPES["OC-6"])
    assert got["inertia_ratios"] == [1.0, 1.0]
    assert got["aspect"] == [1.0, 1.0]
    assert got["longest_axis_A"] == pytest.approx(2.0, abs=1e-6)
    assert got["hull_volume_A3"] == pytest.approx(4.0 / 3.0, abs=1e-3)
    assert got["sphericity"] == pytest.approx(math.pi ** (1 / 3) / math.sqrt(3), abs=1e-3)
    assert got["sphericity"] == pytest.approx(0.8456, abs=1e-3)


def test_sphericity_is_one_for_a_sphere_and_matches_the_platonic_solids():
    """The implemented formula is Wadell's, pi^(1/3)(6V)^(2/3)/A, which is
    1 for a sphere. (The round-2 plan transcribes it as
    4 pi^(1/3)(3V)^(2/3)/A, which is larger by 4^(2/3) = 2.5198 and gives
    2.520 for a sphere - see the module docstring.)"""
    n = 800                                  # Fibonacci sphere, deterministic
    k = np.arange(n) + 0.5
    phi = np.arccos(1.0 - 2.0 * k / n)
    theta = math.pi * (1.0 + 5.0 ** 0.5) * k
    sphere = np.column_stack([np.cos(theta) * np.sin(phi),
                              np.sin(theta) * np.sin(phi), np.cos(phi)])
    assert shape_evidence(sphere)["sphericity"] == pytest.approx(1.0, abs=0.01)

    cube = np.array([(x, y, z) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)], float)
    assert shape_evidence(cube)["sphericity"] == pytest.approx((math.pi / 6) ** (1 / 3),
                                                              abs=1e-3)
    assert shape_evidence(REFERENCE_SHAPES["T-4"])["sphericity"] == \
        pytest.approx((math.pi / 2) ** (1 / 3) / math.sqrt(3), abs=1e-3)


def test_a_rod_is_thin_in_every_measure():
    rng = np.random.default_rng(7)
    rod = np.zeros((10, 3))
    rod[:, 0] = np.linspace(0.0, 9.0, 10)
    rod += rng.normal(0.0, 0.05, rod.shape)
    got = shape_evidence(rod)
    assert got["sphericity"] < 0.4
    assert got["aspect"][0] < 0.05 and got["aspect"][1] < 0.05
    assert got["inertia_ratios"][0] < 0.01          # nothing about the rod axis
    assert got["inertia_ratios"][1] == pytest.approx(1.0, abs=0.01)
    assert got["longest_axis_A"] == pytest.approx(9.0, abs=0.3)


def test_degenerate_inertia_is_flagged_because_the_aspect_frame_is_arbitrary():
    got = shape_evidence(REFERENCE_SHAPES["OC-6"])
    assert "principal axes" in got["note"]
    # a shape with three distinct moments carries no such caveat
    brick = np.array([(x, y, z) for x in (-3, 3) for y in (-2, 2) for z in (-1, 1)], float)
    plain = shape_evidence(brick)
    assert plain["note"] == ""
    assert plain["aspect"] == pytest.approx([1 / 3, 2 / 3], abs=1e-4)


def test_too_few_or_coplanar_points_return_none_fields_with_a_note():
    triangle = shape_evidence([(0, 0, 0), (1, 0, 0), (0, 1, 0)])
    assert triangle["hull_volume_A3"] is None
    assert triangle["hull_area_A2"] is None
    assert triangle["sphericity"] is None
    assert "convex hull needs four non-coplanar points" in triangle["note"]
    assert triangle["inertia_ratios"] is not None          # still well defined

    square = shape_evidence([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)])
    assert square["sphericity"] is None
    assert "coplanar" in square["note"]

    single = shape_evidence([(1.0, 2.0, 3.0)])
    assert single["inertia_ratios"] is None
    assert single["aspect"] is None
    assert single["longest_axis_A"] is None
    assert "no shape to measure" in single["note"]

    assert shape_evidence(np.zeros((0, 3)))["note"] == "no finite coordinates"


def test_mass_weighting_uses_cctbx_weights_and_reports_when_it_cannot():
    unit = shape_evidence([(0, 0, 0), (2, 0, 0), (0, 1, 0)])
    heavy = shape_evidence([(0, 0, 0), (2, 0, 0), (0, 1, 0)], ["W", "H", "H"])
    assert unit["mass_weighted"] is False
    assert heavy["mass_weighted"] is True
    assert heavy["inertia_ratios"] != unit["inertia_ratios"]
    # the hull does not depend on the masses
    assert heavy["longest_axis_A"] == unit["longest_axis_A"]

    bad = shape_evidence(REFERENCE_SHAPES["OC-6"], ["C"] * 5 + ["Zz"])
    assert bad["mass_weighted"] is False
    assert "no atomic weight for Zz" in bad["note"]

    wrong_length = shape_evidence(REFERENCE_SHAPES["OC-6"], ["C"])
    assert "1 element symbols for 6 points" in wrong_length["note"]


def test_method_text_states_the_sphericity_formula():
    method = shape_evidence(REFERENCE_SHAPES["OC-6"])["method"]
    assert "pi^(1/3)(6V)^(2/3)/A" in method
    assert "no van der Waals radii" in method


# ======================================= 4. crystallographic site symmetry ==

def _half_molecule():
    """Three atoms; their inversion images through the origin complete it."""
    return [(1.2, 0.5, 0.4), (2.4, 1.1, -0.3), (0.4, 1.9, 1.1)], ["C", "N", "O"]


def test_molecule_on_an_inversion_centre_in_p_minus_1():
    half, els = _half_molecule()
    xs = structure(half + [(-x, -y, -z) for x, y, z in half], els + els)
    got = crystallographic_point_symmetry(xs, range(6))
    assert got["ops"] == ["x,y,z", "-x,-y,-z"]
    assert got["order"] == 2
    assert got["symbol_hint"] == "-1"
    assert got["space_group_order"] % got["order"] == 0
    assert "SUBGROUP of the true molecular point group" in got["note"]


def test_the_same_molecule_in_a_general_position_is_order_one():
    half, els = _half_molecule()
    shift = np.array([0.7, 0.33, 1.31])
    cart = [tuple(np.array(c) + shift) for c in half]
    cart += [tuple(-np.array(c) + 2 * shift) for c in half]   # still centrosymmetric,
    # but its centre is not a crystallographic inversion centre
    xs = structure(cart, els + els)
    got = crystallographic_point_symmetry(xs, range(6))
    assert got["ops"] == ["x,y,z"]
    assert got["order"] == 1
    assert got["symbol_hint"] == "1"


def test_the_asu_half_of_a_centrosymmetric_molecule_is_order_one():
    """Documented input requirement: the function needs a COMPLETE fragment
    instance. Handed the asymmetric-unit half, inversion maps it onto the
    other half, not onto itself, and the honest answer is the trivial
    group."""
    half, els = _half_molecule()
    xs = structure(half + [(-x, -y, -z) for x, y, z in half], els + els)
    assert crystallographic_point_symmetry(xs, [0, 1, 2])["order"] == 1


def test_an_inversion_centre_away_from_the_origin_gives_the_same_operator():
    """`ops` names the TYPE and orientation of the operator, not where in the
    cell its element sits: the comparison is modulo lattice translations, so
    a molecule on the inversion centre at (1/2,1/2,1/2) reports the same
    `-x,-y,-z` as one on the centre at the origin. The note says so, and the
    strings stay members of the space group's own operator list."""
    half, els = _half_molecule()
    cell = (10.0, 11.0, 12.0, 90.0, 90.0, 90.0)
    centre = np.array([5.0, 5.5, 6.0])                 # fractional (1/2,1/2,1/2)
    cart = [tuple(np.array(c) + centre) for c in half]
    cart += [tuple(-np.array(c) + centre) for c in half]
    xs = structure(cart, els + els, cell=cell)
    got = crystallographic_point_symmetry(xs, range(6))
    assert got["order"] == 2
    assert got["symbol_hint"] == "-1"
    assert got["ops"] == ["x,y,z", "-x,-y,-z"]
    assert "does not say where in the cell" in got["note"]


def test_a_high_symmetry_site_and_the_order_divides_the_space_group_order():
    """An MX6 octahedron on the origin of Pm-3m: every one of the 48
    operators maps it onto itself."""
    cart = [(0.0, 0.0, 0.0)]
    for axis in range(3):
        for sign in (1.0, -1.0):
            v = [0.0, 0.0, 0.0]
            v[axis] = sign * 2.0
            cart.append(tuple(v))
    xs = structure(cart, ["Fe"] + ["O"] * 6, cell=(10.0, 10.0, 10.0, 90.0, 90.0, 90.0),
                   sg="P m -3 m")
    got = crystallographic_point_symmetry(xs, range(7))
    assert got["order"] == 48
    assert got["space_group_order"] == 48
    assert got["space_group_order"] % got["order"] == 0
    assert got["symbol_hint"] == "m -3 m"
    assert "x,y,z" in got["ops"]

    # break the octahedron with an element swap and the site symmetry drops
    xs2 = structure(cart, ["Fe"] + ["O"] * 5 + ["N"],
                    cell=(10.0, 10.0, 10.0, 90.0, 90.0, 90.0), sg="P m -3 m")
    dropped = crystallographic_point_symmetry(xs2, range(7))
    assert dropped["order"] < 48
    assert got["space_group_order"] % dropped["order"] == 0


def test_every_returned_operator_really_is_a_space_group_operator():
    half, els = _half_molecule()
    xs = structure(half + [(-x, -y, -z) for x, y, z in half], els + els)
    got = crystallographic_point_symmetry(xs, range(6))
    known = {sgtbx.rt_mx(o.as_xyz()).as_xyz() for o in xs.space_group().all_ops()}
    for op in got["ops"]:
        rot_only = sgtbx.rt_mx(sgtbx.rt_mx(op).r().as_xyz()).as_xyz()
        assert rot_only in {sgtbx.rt_mx(k).r().as_xyz() for k in known}


def test_empty_and_out_of_range_selections_are_reported_not_raised():
    half, els = _half_molecule()
    xs = structure(half, els)
    assert crystallographic_point_symmetry(xs, [])["order"] == 0
    assert "empty fragment" in crystallographic_point_symmetry(xs, [])["note"]
    assert crystallographic_point_symmetry(xs, [99])["order"] == 0
    assert "out of range" in crystallographic_point_symmetry(xs, [99])["note"]
