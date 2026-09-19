"""chem/pores.py (round-2 R3.0-R3.3): channel dimensionality and direction
from the flood-fill label grid, the largest inscribed sphere, the
pore-limiting diameter and the packing numbers - analytic fixtures on
synthetic grids and a one-atom cubic cell (plan section 3.7)."""
from __future__ import annotations

import math

import numpy as np
import pytest

from crystalpilot.chem.pores import (distance_field, grid_step_A,
                                     inscribed_sphere, lattice_basis,
                                     packing_index, pore_limiting_diameter,
                                     void_topology)

N = 20

#: cctbx van_der_waals_radii table values used by the analytic expectations
R_C = 1.775
R_O = 1.45
R_H = 1.2


def _grid():
    return np.zeros((N, N, N), dtype=np.int32)


def _idx():
    return np.indices((N, N, N))


class TestVoidTopology:
    def test_cylinder_along_c_is_a_1d_channel(self):
        g = _grid()
        x, y, _z = _idx()
        g[(x - 10) ** 2 + (y - 10) ** 2 < 9] = 2
        t = void_topology(g, 2)
        assert t == {"dimensionality": 1, "directions": [[0, 0, 1]],
                     "n_components": 1}

    def test_slab_is_a_2d_layer(self):
        g = _grid()
        _x, _y, z = _idx()
        g[np.abs(z - 10) <= 2] = 2
        t = void_topology(g, 2)
        assert t["dimensionality"] == 2
        assert t["directions"] == [[0, 1, 0], [1, 0, 0]] or \
            t["directions"] == [[1, 0, 0], [0, 1, 0]]

    def test_isolated_sphere_is_a_cavity(self):
        g = _grid()
        x, y, z = _idx()
        g[(x - 10) ** 2 + (y - 10) ** 2 + (z - 10) ** 2 < 16] = 2
        assert void_topology(g, 2) == {"dimensionality": 0, "directions": [],
                                       "n_components": 1}

    def test_sphere_on_the_corner_is_still_one_cavity(self):
        """Eight pieces inside the cell, sewn across all faces without a
        cycle mismatch: the D17 case (a wrapped cavity) is still 0-D."""
        g = _grid()
        x, y, z = _idx()
        dx = np.minimum(x, N - x)
        dy = np.minimum(y, N - y)
        dz = np.minimum(z, N - z)
        g[dx ** 2 + dy ** 2 + dz ** 2 < 16] = 2
        t = void_topology(g, 2)
        assert t["dimensionality"] == 0 and t["directions"] == []
        assert t["n_components"] == 8

    def test_whole_cell_is_3d(self):
        g = _grid()
        g[:] = 2
        t = void_topology(g, 2)
        assert t["dimensionality"] == 3
        assert sorted(t["directions"]) == [[0, 0, 1], [0, 1, 0], [1, 0, 0]]

    def test_diagonal_channel_direction(self):
        """A channel along a+b: the mismatch closes through BOTH the a and b
        faces at once and the direction comes out as [1, 1, 0]."""
        g = _grid()
        x, y, z = _idx()
        d = (x - y) % N
        near = np.minimum(d, N - d) <= 1
        g[near & (np.abs(z - 10) <= 1)] = 2
        t = void_topology(g, 2)
        assert t["dimensionality"] == 1
        assert t["directions"] == [[1, 1, 0]]

    def test_two_voids_are_independent(self):
        g = _grid()
        x, y, _z = _idx()
        g[(x - 5) ** 2 + (y - 5) ** 2 < 4] = 2          # channel along c
        g[(x - 14) ** 2 + (y - 14) ** 2 + (_z - 10) ** 2 < 9] = 3  # cavity
        assert void_topology(g, 2)["dimensionality"] == 1
        assert void_topology(g, 3)["dimensionality"] == 0
        assert void_topology(g, 4)["n_components"] == 0


class TestLatticeBasis:
    def test_rank_and_primitive_vectors(self):
        assert lattice_basis([]) == (0, [])
        assert lattice_basis([[0, 0, 2], [0, 0, -4]]) == (1, [[0, 0, 1]])
        assert lattice_basis([[2, 2, 0], [-1, -1, 0]]) == (1, [[1, 1, 0]])
        rank, basis = lattice_basis([[1, 0, 0], [0, 1, 0], [1, 1, 0]])
        assert rank == 2 and len(basis) == 2


class TestInscribedSphere:
    def test_one_atom_cubic_cell(self):
        """Simple cubic a = 10 A, one C at the origin (r_vdW 1.775 from the
        cctbx table): the free sphere sits at (1/2, 1/2, 1/2), 8.660 A from
        the atom, radius 8.660 - 1.775 = 6.885 A, LCD 13.770 A."""
        from cctbx import uctbx

        uc = uctbx.unit_cell((10, 10, 10, 90, 90, 90))
        n = 20
        ix, iy, iz = np.indices((n, n, n))
        pts = np.stack([ix, iy, iz], axis=-1).reshape(-1, 3) / n
        # the void: every grid point farther than 3 A from the atom
        d = np.linalg.norm(((pts + 0.5) % 1.0 - 0.5) * 10.0, axis=1)
        void = pts[d > 3.0]
        out = inscribed_sphere(void, uc, np.array([[0.0, 0.0, 0.0]]), ["C"])
        assert out["centre_frac"] == [0.5, 0.5, 0.5]
        assert abs(out["radius_A"] - (math.sqrt(75.0) - 1.775)) < 1e-3
        assert abs(out["lcd_A"] - 2 * out["radius_A"]) < 2e-3   # both rounded to 3 dp
        assert out["nearest_atom"] == "C" and out["stride"] == 1

    def test_periodic_images_count(self):
        """The nearest atom may be an IMAGE: a point near the corner sees
        the atom through the lattice, not 15 A away."""
        from cctbx import uctbx

        uc = uctbx.unit_cell((10, 10, 10, 90, 90, 90))
        out = inscribed_sphere(np.array([[0.95, 0.95, 0.95]]), uc,
                               np.array([[0.0, 0.0, 0.0]]), ["C"])
        assert abs(out["radius_A"] - (math.sqrt(0.75) - 1.775)) < 1e-3

    def test_thinning_is_reported_and_still_finds_the_true_maximum(self):
        """Over the budget the scan is thinned to one point per cell of a
        regular fractional LATTICE and then refined back (R is 1-Lipschitz,
        so the bin holding the maximum cannot be dropped) - so the answer is
        the exact maximum over the points handed in, not over a subsample.
        `stride` is gone as a concept and pinned at 1 for older callers."""
        from cctbx import uctbx

        from crystalpilot.chem.pores import distance_field

        uc = uctbx.unit_cell((10, 10, 10, 90, 90, 90))
        pts = np.random.default_rng(0).random((5000, 3))
        atoms = np.array([[0.0, 0.0, 0.0]])
        out = inscribed_sphere(pts, uc, atoms, ["C"], max_points=1000)
        brute, _el = distance_field(pts, uc, atoms, ["C"])
        assert out["radius_A"] == round(float(brute.max()), 3)
        assert out["n_points"] == 5000 and out["bins_per_axis"] > 0
        assert out["n_refine_rounds"] >= 2 and out["exact"] is True
        assert out["stride"] == 1

    def test_empty(self):
        from cctbx import uctbx

        uc = uctbx.unit_cell((10, 10, 10, 90, 90, 90))
        out = inscribed_sphere(np.zeros((0, 3)), uc, np.zeros((1, 3)), ["C"])
        assert out["centre_frac"] is None and out["lcd_A"] is None


# --------------------------------------------------------- shared fixtures --

def _cubic():
    from cctbx import uctbx

    return uctbx.unit_cell((10, 10, 10, 90, 90, 90))


def _one_c_labels(n: int):
    """Simple cubic a = 10 with one C at the origin, on an n^3 grid: the
    void is every grid point outside the van der Waals surface (what a
    flood fill with a zero-radius probe would label)."""
    uc = _cubic()
    atoms = np.array([[0.0, 0.0, 0.0]])
    ix, iy, iz = np.indices((n, n, n))
    frac = np.stack([ix / n, iy / n, iz / n], axis=-1).reshape(-1, 3)
    r, _ = distance_field(frac, uc, atoms, ["C"])
    labels = np.where(r.reshape(n, n, n) >= 0.0, 2, 0).astype(np.int32)
    return uc, atoms, ["C"], labels


@pytest.fixture(scope="module")
def constricted_channel():
    """A real-geometry 1-D channel with a neck: a 1.4 x 1.4 x 1.5 A mesh of
    C atoms fills a 14 x 14 x 6 cell except a cylinder of radius 5 A round
    (1/2, 1/2, z) - and in the single mesh layer at z = 0 the cylinder is
    only 3 A wide, which is the constriction. The mesh is dense enough
    (largest hole 1.243 A < r_vdW 1.775) that the framework is solid, so
    the void really is the cylinder and nothing else.

    Returns (uc, atoms, elements, labels, n_grid, r_neck, r_wall) where the
    two radii are the closest atom to the channel axis in the neck plane
    and everywhere else - the bottleneck and the wall."""
    from cctbx import uctbx

    a, c = 14.0, 6.0
    nx = ny = 10
    nz = 4
    uc = uctbx.unit_cell((a, a, c, 90, 90, 90))
    xs = (np.arange(nx) + 0.5) * a / nx
    ys = (np.arange(ny) + 0.5) * a / ny
    zs = np.arange(nz) * c / nz              # a mesh layer exactly at z = 0
    sites = []
    for z in zs:
        for x in xs:
            for y in ys:
                rad = math.hypot(x - a / 2, y - a / 2)
                if rad >= (3.0 if abs(z) < 1e-9 else 5.0):
                    sites.append((x / a, y / a, z / c))
    atoms = np.array(sites)
    els = ["C"] * len(atoms)
    cart = atoms * np.array([a, a, c])
    rad = np.hypot(cart[:, 0] - a / 2, cart[:, 1] - a / 2)
    neck = np.abs(cart[:, 2]) < 1e-9

    n_grid = (56, 56, 24)                    # 0.25 A step
    ix, iy, iz = np.indices(n_grid)
    frac = np.stack([ix / n_grid[0], iy / n_grid[1], iz / n_grid[2]],
                    axis=-1).reshape(-1, 3)
    r, _ = distance_field(frac, uc, atoms, els)
    labels = np.where(r.reshape(n_grid) >= 0.0, 2, 0).astype(np.int32)
    return (uc, atoms, els, labels, n_grid,
            float(rad[neck].min()), float(rad[~neck].min()))


# ------------------------------------------------------------ R3.2 field --

class TestDistanceField:
    def test_anchor_points_of_the_one_atom_cubic_cell(self):
        """R(x) = min over the 27 images of |x - r_a| - r_vdW. Three exact
        points of the simple cubic cell, a = 10, one C at the origin:
        body centre sqrt(75), cell-face centre sqrt(50), edge midpoint 5
        (the atom row along [100])."""
        uc = _cubic()
        pts = np.array([[0.5, 0.5, 0.5], [0.5, 0.5, 0.0], [0.5, 0.0, 0.0]])
        r, el = distance_field(pts, uc, np.array([[0.0, 0.0, 0.0]]), ["C"])
        assert r.shape == (3,) and el.shape == (3,)
        assert abs(r[0] - (math.sqrt(75.0) - R_C)) < 1e-9
        assert abs(r[1] - (math.sqrt(50.0) - R_C)) < 1e-9
        assert abs(r[2] - (5.0 - R_C)) < 1e-9          # == 3.225 exactly
        assert list(el) == ["C", "C", "C"]

    def test_the_radius_is_per_element(self):
        """Halfway between a C and an O 5 A apart both are 2.5 A away, so
        the minimum is set by the LARGER radius - the C."""
        uc = _cubic()
        r, el = distance_field(np.array([[0.25, 0.0, 0.0]]), uc,
                               np.array([[0.0, 0.0, 0.0], [0.5, 0.0, 0.0]]),
                               ["C", "O"])
        assert abs(r[0] - (2.5 - R_C)) < 1e-9
        assert el[0] == "C"
        assert 2.5 - R_C < 2.5 - R_O           # the O would have been looser

    def test_negative_inside_the_vdw_surface(self):
        uc = _cubic()
        r, _ = distance_field(np.array([[0.1, 0.0, 0.0]]), uc,
                              np.array([[0.0, 0.0, 0.0]]), ["C"])
        assert abs(r[0] - (1.0 - R_C)) < 1e-9 and r[0] < 0

    def test_no_atoms_and_no_points(self):
        uc = _cubic()
        r, el = distance_field(np.array([[0.5, 0.5, 0.5]]), uc,
                               np.zeros((0, 3)), [])
        assert not np.isfinite(r[0]) and el[0] is None
        r, el = distance_field(np.zeros((0, 3)), uc, np.zeros((1, 3)), ["C"])
        assert len(r) == 0 and len(el) == 0


# -------------------------------------------------------------- R3.2 PLD --

class TestPoreLimitingDiameter:
    @pytest.mark.parametrize("n", [20, 30, 40])
    def test_one_atom_cubic_cell(self, n):
        """Simple cubic a = 10, one C at the origin. The free sphere gets
        through the window at (1/2, 1/2, 0), where the four surrounding
        atoms are a/sqrt(2) = 7.071 A away:

            rho* = 10/sqrt(2) - 1.775 = 5.296  ->  PLD = 10.592 A

        NOT the 6.450 A of the (1/2, 0, 0) edge midpoint (5 - 1.775 =
        3.225, pinned in TestDistanceField): that is the narrowest point of
        the straight [100] LINE, which runs into the atom row, and a
        percolation supremum is over all paths - the sphere detours through
        the window instead. Plan section 3.7 quotes the straight-line
        number; see test_the_straight_row_is_not_the_bottleneck."""
        uc, atoms, els, labels = _one_c_labels(n)
        step = round(10.0 / n, 3)
        out = pore_limiting_diameter(labels, 2, uc, atoms, els)
        expect = 2.0 * (10.0 / math.sqrt(2.0) - R_C)
        assert abs(out["pld_A"] - expect) < step
        assert out["pld_error_A"] == step == out["grid_step_A"]
        assert out["stride"] == 1 and out["n_rounds"] == 12
        assert out["dimensionality"] == 3
        assert sorted(out["pld_directions"]) == [[0, 0, 1], [0, 1, 0],
                                                 [1, 0, 0]]
        assert out["method"].startswith("网格渗流二分")
        assert out["n_voxels"] == int((labels == 2).sum())

    def test_the_straight_row_is_not_the_bottleneck(self):
        """The percolation PLD is strictly larger than twice the free
        radius of the tightest point on the [100] row - the point of doing
        it by percolation and not along an axis."""
        uc, atoms, els, labels = _one_c_labels(40)
        r_row, _ = distance_field(np.array([[0.5, 0.0, 0.0]]), uc, atoms, els)
        r_win, _ = distance_field(np.array([[0.5, 0.5, 0.0]]), uc, atoms, els)
        assert abs(r_row[0] - 3.225) < 1e-9 and r_win[0] > r_row[0]
        out = pore_limiting_diameter(labels, 2, uc, atoms, els)
        assert out["pld_A"] > 2.0 * r_row[0] + 1.0
        assert abs(out["pld_A"] - 2.0 * r_win[0]) < out["pld_error_A"]

    def test_pld_never_exceeds_the_lcd(self):
        uc, atoms, els, labels = _one_c_labels(40)
        pts = np.argwhere(labels == 2) / 40.0
        lcd = inscribed_sphere(pts, uc, atoms, els)["lcd_A"]
        out = pore_limiting_diameter(labels, 2, uc, atoms, els)
        assert abs(lcd - 2 * (math.sqrt(75.0) - R_C)) < 1e-3
        assert out["pld_A"] < lcd

    def test_isolated_cavity_has_no_pld(self):
        """A 0-D void: the sphere has nowhere to go, so PLD is undefined -
        not zero, not the LCD."""
        uc = _cubic()
        g = _grid()
        x, y, z = _idx()
        g[(x - 10) ** 2 + (y - 10) ** 2 + (z - 10) ** 2 < 16] = 2
        out = pore_limiting_diameter(g, 2, uc, np.array([[0.0, 0.0, 0.0]]),
                                     ["C"])
        assert out["pld_A"] is None
        assert out["pld_note"] == "孤立空腔无渗流路径，PLD 无定义"
        assert out["pld_directions"] == [] and out["dimensionality"] == 0
        assert out["n_rounds"] == 0
        assert out["pld_error_A"] == grid_step_A(uc, g.shape) == 0.5

    def test_label_absent_from_the_grid(self):
        uc = _cubic()
        out = pore_limiting_diameter(_grid(), 7, uc,
                                     np.array([[0.0, 0.0, 0.0]]), ["C"])
        assert out["pld_A"] is None and out["n_voxels"] == 0
        assert "没有标签 7" in out["pld_note"]

    def test_constricted_channel(self, constricted_channel):
        """Real geometry: the neck ring sits 3.569 A from the channel axis
        and the wall 5.331 A, so PLD = 2 x (3.569 - 1.775) = 3.589 A while
        the free sphere in the wide part is much bigger."""
        uc, atoms, els, labels, n_grid, r_neck, r_wall = constricted_channel
        step = grid_step_A(uc, n_grid)
        assert step == 0.25
        assert void_topology(labels, 2)["dimensionality"] == 1
        out = pore_limiting_diameter(labels, 2, uc, atoms, els)
        assert abs(out["pld_A"] - 2.0 * (r_neck - R_C)) < step
        assert abs(out["pld_A"] - 3.589) < step
        assert out["pld_directions"] == [[0, 0, 1]]
        assert out["dimensionality"] == 1 and out["stride"] == 1
        pts = np.argwhere(labels == 2) / np.array(n_grid, float)
        lcd = inscribed_sphere(pts, uc, atoms, els)["lcd_A"]
        assert out["pld_A"] < lcd            # the neck, not the wide part
        assert 2.0 * (r_neck - R_C) < 2.0 * (r_wall - R_C)

    def test_direction_filter(self, constricted_channel):
        """`directions` asks for percolation along a given vector: the
        c channel answers for [001] and is undefined for [100]."""
        uc, atoms, els, labels, _n, _rn, _rw = constricted_channel
        free = pore_limiting_diameter(labels, 2, uc, atoms, els)
        along_c = pore_limiting_diameter(labels, 2, uc, atoms, els,
                                         directions=[[0, 0, 1]])
        assert along_c["pld_A"] == free["pld_A"]
        along_a = pore_limiting_diameter(labels, 2, uc, atoms, els,
                                         directions=[[1, 0, 0]])
        assert along_a["pld_A"] is None
        assert "不沿指定方向" in along_a["pld_note"]
        assert along_a["pld_directions"] == [[0, 0, 1]]

    def test_coarsening_is_reported_and_widens_the_error(self):
        """Over the voxel budget the WHOLE label grid is strided (a random
        subsample would cut the connections percolation is testing), the
        stride is reported and the error bar grows with it."""
        uc, atoms, els, labels = _one_c_labels(40)
        fine = pore_limiting_diameter(labels, 2, uc, atoms, els)
        coarse = pore_limiting_diameter(labels, 2, uc, atoms, els,
                                        max_points=10_000)
        assert fine["stride"] == 1 and fine["grid_step_A"] == 0.25
        assert coarse["stride"] == 2
        assert coarse["grid_step_A"] == coarse["pld_error_A"] == 0.5
        assert coarse["n_voxels"] < fine["n_voxels"] <= 40 ** 3
        expect = 2.0 * (10.0 / math.sqrt(2.0) - R_C)
        assert abs(coarse["pld_A"] - expect) < coarse["pld_error_A"]
        assert coarse["dimensionality"] == 3

    def test_bisection_round_count_is_configurable(self):
        uc, atoms, els, labels = _one_c_labels(20)
        out = pore_limiting_diameter(labels, 2, uc, atoms, els, rounds=4)
        assert out["n_rounds"] == 4
        # 4 rounds bracket rho* to 1/16 of [min R, max R] ~ 8.7 A wide
        expect = 2.0 * (10.0 / math.sqrt(2.0) - R_C)
        assert abs(out["pld_A"] - expect) < 2 * (8.7 / 16.0)


# ---------------------------------------------------------- R3.3 packing --

class TestPackingIndex:
    def test_occupancy_weights_both_numbers(self):
        """Two half-occupied C (a disorder pair) are ONE atom: the ball sum
        and the non-H count both halve, so the numbers equal one full C."""
        uc = _cubic()
        full = packing_index(uc, np.zeros((1, 3)), ["C"])
        half = packing_index(uc, np.zeros((2, 3)), ["C", "C"],
                             occupancies=[0.5, 0.5])
        assert half["vdw_sum_pct"] == full["vdw_sum_pct"]
        assert half["packing_index_pct"] == full["packing_index_pct"]
        assert half["volume_per_non_h_atom_A3"] == 1000.0
        assert half["n_non_h_atoms_p1"] == 1.0 and half["occupancy_weighted"]
        assert not full["occupancy_weighted"]
        with pytest.raises(ValueError):
            packing_index(uc, np.zeros((2, 3)), ["C", "C"], occupancies=[1.0])

    def test_single_atom_is_exact(self):
        """One C in a = 10: (4/3) pi 1.775^3 / 1000 x 100 = 2.343 %, and
        1000 A^3 for the single non-hydrogen atom."""
        uc = _cubic()
        out = packing_index(uc, np.array([[0.0, 0.0, 0.0]]), ["C"])
        expect = 4.0 / 3.0 * math.pi * R_C ** 3 / 1000.0 * 100.0
        assert abs(out["vdw_sum_pct"] - expect) < 1e-3
        # one sphere: union == sum, to within the grid-counting bound
        assert abs(out["packing_index_pct"] - expect) \
            <= out["packing_index_error_pct"]
        assert out["packing_index_error_pct"] < 0.5
        assert out["packing_grid_step_A"] <= 0.2 + 1e-9
        assert abs(out["vdw_volume_A3"]
                   - 4.0 / 3.0 * math.pi * R_C ** 3) < 1e-3
        assert out["cell_volume_A3"] == 1000.0
        assert out["volume_per_non_h_atom_A3"] == 1000.0
        assert out["n_atoms_p1"] == 1 and out["n_non_h_atoms_p1"] == 1

    def test_hydrogen_is_in_the_sum_but_not_in_the_per_atom_volume(self):
        uc = _cubic()
        out = packing_index(uc, np.array([[0.0, 0.0, 0.0], [0.1, 0.0, 0.0],
                                          [0.2, 0.0, 0.0]]), ["C", "H", "D"])
        expect = (4.0 / 3.0 * math.pi * (R_C ** 3 + 2 * R_H ** 3)
                  / 1000.0 * 100.0)
        assert abs(out["vdw_sum_pct"] - expect) < 1e-3
        assert out["n_atoms_p1"] == 3 and out["n_non_h_atoms_p1"] == 1
        assert out["volume_per_non_h_atom_A3"] == 1000.0   # not 333.333

    def test_the_18_A3_reading_and_the_5_7_caveat_are_present(self):
        """The two numbers are never a complement of the solvent-accessible
        volume: knowledge base 5.7 says the corner space a probe cannot
        reach is ~30 % of the cell while the solvent volume is zero."""
        uc = _cubic()
        out = packing_index(uc, np.array([[0.0, 0.0, 0.0]]), ["C"])
        assert "18 Å³" in out["reading"] and "§12.4" in out["reading"]
        assert "不是 100 − 溶剂可及体积%" in out["note"]
        assert "30%" in out["note"] and "§5.7" in out["note"]
        assert "未做重叠修正" in out["note"]
        assert "Kitaigorodskii" in out["method"]

    def test_unknown_element_falls_back_to_2_A(self):
        """Element-generic: an element missing from the cctbx table uses
        the 2.0 A fallback rather than dropping the atom."""
        uc = _cubic()
        out = packing_index(uc, np.array([[0.0, 0.0, 0.0]]), ["Xx"])
        expect = 4.0 / 3.0 * math.pi * 8.0 / 1000.0 * 100.0
        assert abs(out["vdw_sum_pct"] - expect) < 1e-3
        assert out["n_non_h_atoms_p1"] == 1

    def test_length_mismatch_raises(self):
        uc = _cubic()
        with pytest.raises(ValueError):
            packing_index(uc, np.zeros((2, 3)), ["C"])

    def test_a_dense_cell_lands_near_the_65_pct_anchor(self):
        """Sanity of the magnitude, not a verdict: 27 C on a 3 x 3 x 3 mesh
        of a 10 A cell is 63.3 % - the order PLATON calls typical."""
        uc = _cubic()
        g = np.stack(np.meshgrid(*[np.arange(3) / 3.0] * 3, indexing="ij"),
                     axis=-1).reshape(-1, 3)
        out = packing_index(uc, g, ["C"] * 27)
        expect = 27 * 4.0 / 3.0 * math.pi * R_C ** 3 / 1000.0 * 100.0
        assert abs(out["vdw_sum_pct"] - expect) < 1e-3
        assert 60.0 < out["vdw_sum_pct"] < 70.0
        # 3.33 A spacing < 2 r_vdW: every atom overlaps its 6 mesh
        # neighbours in a lens of height h = r - d/2 (no triple overlaps,
        # the diagonal neighbours at 4.71 A are clear), so the envelope is
        # 27 spheres minus 81 lenses - the union reproduces that
        d = 10.0 / 3.0
        h = R_C - d / 2.0
        lens = 2.0 * math.pi * h ** 2 * (3.0 * R_C - h) / 3.0
        union = 27 * 4.0 / 3.0 * math.pi * R_C ** 3 - 81 * lens
        assert out["packing_index_pct"] < out["vdw_sum_pct"]
        assert abs(out["packing_index_pct"] - 100.0 * union / 1000.0) \
            <= max(out["packing_index_error_pct"], 0.2)
        assert abs(out["volume_per_non_h_atom_A3"] - 1000.0 / 27) < 1e-3

    def test_two_coincident_spheres_are_one_envelope(self):
        """The raw sum doubles, the union does not - the difference between
        the two numbers is exactly the overlap the note warns about."""
        uc = _cubic()
        one = packing_index(uc, np.zeros((1, 3)), ["C"])
        two = packing_index(uc, np.zeros((2, 3)), ["C", "C"])
        assert abs(two["vdw_sum_pct"] - 2 * one["vdw_sum_pct"]) < 2e-3  # 3 dp
        assert two["packing_index_pct"] == one["packing_index_pct"]
        assert two["vdw_union_volume_A3"] == one["vdw_union_volume_A3"]

    def test_grid_cap_is_reported(self):
        uc = _cubic()
        out = packing_index(uc, np.zeros((1, 3)), ["C"], max_points=1000)
        assert out["packing_grid_points"] <= 1331 and \
            out["packing_grid_step_A"] >= 0.9
        assert out["packing_index_error_pct"] >= 0.01
