"""Olex2 `grow` (grow all, round-3 R5): grow bonded images until a symmetry
element already used for that atom in the same fragment would repeat.
Finite molecules complete - across the cell boundary and through symmetry
elements - while chains / layers / frameworks stop after one period per
direction and the scene says so.
"""
from __future__ import annotations

import pytest

# a two-atom molecule that straddles the a boundary: C1 at 9.25 A and C2 at
# 0.75 A of a 10 A cell are 1.5 A apart THROUGH the boundary and 8.5 A
# apart inside it - the ASU as stored holds two unbonded halves
STRADDLE_P1 = (
    "TITL molecule across the cell boundary\n"
    "CELL 0.71073 10 10 10 90 90 90\n"
    "ZERR 1 0 0 0 0 0 0\n"
    "LATT -1\n"
    "SFAC C\n"
    "UNIT 2\n"
    "C1 1 0.925 0.50 0.50 11 0.05\n"
    "C2 1 0.075 0.50 0.50 11 0.05\n"
    "HKLF 4\n"
    "END\n"
)

# infinite -C-C- chain along a (test_scene_range's fixture)
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

# half a benzene on the inversion centre of P-1: three carbons, the ring
# closes on -x,-y,-z
BENZENE_PM1 = (
    "TITL benzene on an inversion centre\n"
    "CELL 0.71073 10 10 10 90 90 90\n"
    "ZERR 1 0 0 0 0 0 0\n"
    "LATT 1\n"
    "SFAC C\n"
    "UNIT 6\n"
    "C1 1 0.1390 0.0000 0.0000 11 0.05\n"
    "C2 1 0.0695 0.1204 0.0000 11 0.05\n"
    "C3 1 -0.0695 0.1204 0.0000 11 0.05\n"
    "HKLF 4\n"
    "END\n"
)

# a body-centred C/N net: every C is bonded (1.39 A) to eight N lattice
# images and vice versa - topology only, no chemistry is claimed for it.
# (An atom is never bonded to its OWN lattice image in the scene, so a
# one-atom "net" would draw no bonds at all.)
NET_P1 = (
    "TITL body-centred C/N net\n"
    "CELL 0.71073 1.6 1.6 1.6 90 90 90\n"
    "ZERR 1 0 0 0 0 0 0\n"
    "LATT -1\n"
    "SFAC C N\n"
    "UNIT 1 1\n"
    "C1 1 0.00 0.00 0.00 11 0.05\n"
    "N1 2 0.50 0.50 0.50 11 0.05\n"
    "HKLF 4\n"
    "END\n"
)


def _res(tmp_path, text, name="m.res"):
    p = tmp_path / name
    p.write_text(text, encoding="ascii")
    return p


def _scene(path, **kw):
    from crystalpilot.refine.scene import build_scene
    return build_scene(path, **kw)


def _xyz(scene):
    return [tuple(a["xyz"]) for a in scene["atoms"]]


def test_molecule_across_the_boundary_completes(tmp_path):
    p = _res(tmp_path, STRADDLE_P1)
    plain = _scene(p, mode="asu")
    assert plain["meta"]["n_atoms"] == 2 and plain["meta"]["n_bonds"] == 0
    s = _scene(p, mode="asu", grow_all=True)
    g = s["grow_all"]
    assert g["complete"] is True and g["periodic_edges"] == 0
    assert g["budget_hit"] is False
    # the two halves are joined: C2 arrives through +a next to C1 (and C1
    # through -a next to C2); every drawn bond is the 1.5 A one
    assert s["meta"]["n_atoms"] == 4 and g["n_added"] == 2
    assert s["meta"]["n_bonds"] == 2
    xs = sorted(round(x, 2) for x, _y, _z in _xyz(s))
    assert xs == [-0.75, 0.75, 9.25, 10.75]


def test_chain_stops_after_one_period_with_caps(tmp_path):
    p = _res(tmp_path, CHAIN_P1)
    s = _scene(p, mode="asu", grow_all=True)
    g = s["grow_all"]
    assert g["complete"] is False
    assert g["periodic_edges"] >= 2          # +a and -a repeats met
    assert g["caps"] == 2                    # one cap per direction
    assert g["budget_hit"] is False
    # ASU (2) + one cap on each side, and nothing grown beyond the caps
    assert s["meta"]["n_atoms"] == 4
    xs = sorted(round(x, 2) for x, _y, _z in _xyz(s))
    assert xs == [-1.5, 0.0, 1.5, 3.0]
    # the periodic bonds are drawn (caps are bonded)
    assert s["meta"]["n_bonds"] == 3


def test_ring_on_an_inversion_centre_completes_through_symmetry(tmp_path):
    p = _res(tmp_path, BENZENE_PM1)
    s = _scene(p, mode="asu", grow_all=True)
    g = s["grow_all"]
    assert g["complete"] is True and g["periodic_edges"] == 0
    assert s["meta"]["n_atoms"] == 6 and g["n_added"] == 3
    assert s["meta"]["n_bonds"] == 6
    # one shell of ordinary growth reaches only five of the six carbons
    # (C2' is two bonds from the asymmetric unit): grow-all finishes what a
    # shell count cannot know to finish
    one = _scene(p, mode="asu", hops=1)
    assert one["meta"]["n_atoms"] == 5


def test_three_dimensional_net_stops_at_lattice_repeats(tmp_path):
    p = _res(tmp_path, NET_P1)
    s = _scene(p, mode="asu", grow_all=True)
    g = s["grow_all"]
    assert g["complete"] is False and g["budget_hit"] is False
    # the first N image is new to the fragment; every further N image is a
    # lattice repeat of it (same rotation part) and is drawn once as a cap,
    # never grown from - so the net stops after one period per direction
    assert g["periodic_edges"] > 0 and g["caps"] == g["periodic_edges"]
    assert s["meta"]["n_atoms"] == 2 + g["caps"]
    assert s["meta"]["n_atoms"] < 40
    # from a packed cell the same rule holds
    c = _scene(p, mode="cell", grow_all=True)
    assert c["grow_all"]["complete"] is False
    assert c["meta"]["n_atoms"] < 40


def test_budget_is_reported_not_hidden(tmp_path, monkeypatch):
    import crystalpilot.refine.scene as sc
    monkeypatch.setattr(sc, "MAX_ATOMS", 4)
    p = _res(tmp_path, BENZENE_PM1)
    s = _scene(p, mode="asu", grow_all=True)
    g = s["grow_all"]
    assert g["budget_hit"] is True and g["complete"] is False
    assert s["meta"]["truncated"] is True
    assert s["meta"]["n_atoms"] == 4


def test_cache_key_separates_grow_all(tmp_path):
    """A grown-all scene must never be served from the plain scene's cache
    entry (and vice versa)."""
    import json

    from crystalpilot.refine import scene as sc
    nodes = tmp_path / ".crystalpilot" / "refine" / "nodes"
    d = nodes / "n0001"
    d.mkdir(parents=True)
    (d / "model.res").write_text(STRADDLE_P1, encoding="ascii")
    (d / "node.json").write_text(json.dumps({"id": "n0001", "parent": None,
                                             "revision": 1}), encoding="utf-8")
    (tmp_path / ".crystalpilot" / "refine" / "state.json").write_text(
        json.dumps({"active_node": "n0001", "active_branch": "main",
                    "branches": {"main": "n0001"}, "seq": 1}), encoding="utf-8")
    plain = sc.cached_scene(tmp_path, "n0001", mode="asu", n=1, hops=0,
                            polyhedra=False, diff=False)
    grown = sc.cached_scene(tmp_path, "n0001", mode="asu", n=1, hops=0,
                            polyhedra=False, diff=False, grow_all=True)
    assert plain["meta"]["n_atoms"] == 2 and "grow_all" not in plain
    assert grown["meta"]["n_atoms"] == 4 and grown["grow_all"]["complete"] is True
    files = sorted(f.name for f in sc.cache_dir(tmp_path, "n0001").iterdir())
    assert any("_ga1" in f for f in files) and any("_ga1" not in f for f in files)


@pytest.mark.parametrize("text", [STRADDLE_P1, CHAIN_P1, BENZENE_PM1, NET_P1])
def test_without_the_flag_nothing_changes(tmp_path, text):
    p = _res(tmp_path, text)
    s = _scene(p, mode="asu")
    assert "grow_all" not in s
