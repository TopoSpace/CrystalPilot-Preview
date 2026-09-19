"""The scene `range` contract (round-2 R2.2, defect D7): which lattice tiles
the client must instance the per-cell overlays (voids / density map / Q peaks
/ symmetry elements) over. Synthetic P1 cells with analytic tile sets; no
project data."""
from __future__ import annotations

import json
import math

import pytest

# One molecule per 10 A cubic cell, centred well inside the box so a packed
# cell never pokes into a neighbour (same fixture style as test_scene_extent).
MOL_P1 = (
    "TITL one molecule, primitive cubic\n"
    "CELL 0.71073 10 10 10 90 90 90\n"
    "ZERR 1 0 0 0 0 0 0\n"
    "LATT -1\n"
    "SFAC C N O\n"
    "UNIT 1 1 1\n"
    "C1 1 0.50 0.50 0.50 11 0.05\n"
    "N1 2 0.63 0.50 0.50 11 0.05\n"
    "O1 3 0.50 0.62 0.50 11 0.05\n"
    "HKLF 4\n"
    "END\n"
)

# Infinite -C-C- chain along a: 1.5 A bonds inside the cell AND across the
# a boundary (a = 3.0), nothing bonded along b/c. Growth therefore walks the
# chain in BOTH directions, which is what puts negative translations in the
# range.
CHAIN_P1 = (
    "TITL one-dimensional carbon chain along a\n"
    "CELL 0.71073 3.0 12 12 90 90 90\n"
    "ZERR 1 0 0 0 0 0 0\n"
    "LATT -1\n"
    "SFAC C\n"
    "UNIT 2\n"
    "C1 1 0.00 0.00 0.00 11 0.05\n"
    "C2 1 0.50 0.00 0.00 11 0.05\n"
    "HKLF 4\n"
    "END\n"
)


@pytest.fixture
def mol_res(tmp_path):
    p = tmp_path / "mol.res"
    p.write_text(MOL_P1, encoding="ascii")
    return p


@pytest.fixture
def chain_res(tmp_path):
    p = tmp_path / "chain.res"
    p.write_text(CHAIN_P1, encoding="ascii")
    return p


def _tiles(scene) -> list[tuple[int, int, int]]:
    return [tuple(t) for t in scene["range"]["tiles"]]


def test_grown_asu_reaches_negative_translations(chain_res):
    """Two hops along the chain reach C2 at x = -0.5 and C1 at x = -1.0 on
    one side and C2 at x = +1.5 on the other, so the fractional box is
    [-1.0, 1.5] on a and the tiles are -1, 0, +1. An asu scene that grew
    backwards past the origin used to draw its pore / density / symmetry
    elements only in cell 0."""
    from crystalpilot.refine.scene import build_scene

    s = build_scene(chain_res, mode="asu", hops=2)
    rng = s["range"]
    assert rng["frac_lo"][0] == pytest.approx(-1.0)
    assert rng["frac_hi"][0] == pytest.approx(1.5)
    assert _tiles(s) == [(-1, 0, 0), (0, 0, 0), (1, 0, 0)]
    assert rng["n_tiles"] == 3
    assert rng["tiles_truncated"] is False
    # ungrown, the same asu occupies the origin cell alone
    assert _tiles(build_scene(chain_res, mode="asu")) == [(0, 0, 0)]


def test_cell_is_the_origin_tile(mol_res):
    """A wrapped cell lies inside [0,1)^3, so the range is exactly the
    origin tile - the old hard-coded behaviour, now stated rather than
    assumed. (A centroid-wrapped molecule may legitimately poke into a
    neighbour; this fixture is centred so it does not.)"""
    from crystalpilot.refine.scene import build_scene

    s = build_scene(mol_res, mode="cell")
    assert _tiles(s) == [(0, 0, 0)]
    assert s["range"]["n_tiles"] == 1
    assert s["range"]["tiles_truncated"] is False
    lo, hi = s["range"]["frac_lo"], s["range"]["frac_hi"]
    assert all(0.0 <= lo[k] and hi[k] < 1.0 for k in range(3))


def test_supercell_tiles_cover_exactly_the_occupied_cells(mol_res):
    """supercell 3 draws 27 images; the range names those 27 cells and no
    others, so a client tiling the void surface over them covers the atoms
    exactly."""
    from crystalpilot.refine.scene import build_scene

    s = build_scene(mol_res, mode="supercell", n=3)
    assert s["range"]["n_tiles"] == 27
    assert _tiles(s) == [(a, b, c) for a in range(3)
                         for b in range(3) for c in range(3)]
    assert s["range"]["tiles_truncated"] is False
    # the centroid of 27 images sits in the middle cell, not at the origin
    assert s["range"]["centre_cart"][0] == pytest.approx(15.43, abs=0.05)


def test_truncation_keeps_the_centre_most_tiles(mol_res):
    """A 6x6x6 range pack needs 216 tiles. The scene reports all 216 but
    names only the 64 nearest the drawn centroid, and every named tile is
    at least as close as every dropped one."""
    from crystalpilot.refine.scene import MAX_TILES, build_scene

    s = build_scene(mol_res, mode="range", polyhedra=False,
                    frac_range=((-2.6, -2.6, -2.6), (2.6, 2.6, 2.6)))
    rng = s["range"]
    assert rng["n_tiles"] == 216
    assert rng["tiles_truncated"] is True
    kept = set(_tiles(s))
    assert len(kept) == MAX_TILES
    assert (0, 0, 0) in kept                      # the tile holding the centroid
    assert (-3, -3, -3) not in kept and (2, 2, 2) not in kept

    # the defining property, checked against the box the scene itself
    # reports rather than against hard-coded bounds
    lo = [int(math.floor(v)) for v in rng["frac_lo"]]
    hi = [int(math.floor(v)) for v in rng["frac_hi"]]
    cx, cy, cz = rng["centre_cart"]
    a = s["cell"]["a"]                            # cubic: 1 tile = a A

    def d2(t):
        return ((t[0] + 0.5) * a - cx) ** 2 + ((t[1] + 0.5) * a - cy) ** 2 \
            + ((t[2] + 0.5) * a - cz) ** 2

    allt = [(ta, tb, tc) for ta in range(lo[0], hi[0] + 1)
            for tb in range(lo[1], hi[1] + 1)
            for tc in range(lo[2], hi[2] + 1)]
    assert len(allt) == 216
    dropped = [t for t in allt if t not in kept]
    assert max(d2(t) for t in kept) <= min(d2(t) for t in dropped) + 1e-9
    # deterministic: the same scene twice names the same tiles, in order
    again = build_scene(mol_res, mode="range", polyhedra=False,
                        frac_range=((-2.6, -2.6, -2.6), (2.6, 2.6, 2.6)))
    assert again["range"]["tiles"] == s["range"]["tiles"]


def test_stale_scene7_cache_is_not_served(tmp_path, monkeypatch):
    """A cache entry written before this contract has no `range`; serving it
    would leave every per-cell overlay in the origin cell with no way to
    tell. The key prefix moved to scene8_, so the old file is simply never
    looked up."""
    from crystalpilot.refine import scene as sc

    cache = tmp_path / "cache"
    cache.mkdir()
    stale = cache / "scene7_asu_n1_h0_p1_d0.json"
    stale.write_text(json.dumps({"mode": "asu", "atoms": [], "bonds": [],
                                 "meta": {"n_atoms": 0}}), encoding="utf-8")

    class FakeStore:
        def __init__(self, project_dir):
            self.project_dir = project_dir

        def node_dir(self, node):
            d = tmp_path / "nodes" / node
            d.mkdir(parents=True, exist_ok=True)
            (d / "model.res").write_text(MOL_P1, encoding="ascii")
            return d

        def node_meta(self, node):
            return {"parent": None}

    monkeypatch.setattr("crystalpilot.refine.nodes.NodeStore", FakeStore)
    monkeypatch.setattr(sc, "_resolve_ref", lambda store, ref: ref)
    monkeypatch.setattr(sc, "cache_dir", lambda project_dir, node: cache)

    s = sc.cached_scene(tmp_path, "n0001", mode="asu", n=1, hops=0,
                        polyhedra=True, diff=False)
    assert s["meta"]["n_atoms"] == 3          # rebuilt, not the empty stale one
    assert s["range"]["tiles"] == [[0, 0, 0]]
    assert (cache / "scene8_asu_n1_h0_p1_d0.json").exists()
    # older wire formats are swept when the new one is written (best
    # effort): the directory does not keep every version of every scene
    assert not stale.exists()
