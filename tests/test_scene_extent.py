"""Olex2 pack/grow semantics added in round-2 R1: `pack r` (mode=radius),
`pack a1 a2 b1 b2 c1 c2` (mode=range) and `grow -w` (complete). Synthetic
cells with analytic counts; no project data."""
from __future__ import annotations

import pytest

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


@pytest.fixture
def mol_res(tmp_path):
    p = tmp_path / "mol.res"
    p.write_text(MOL_P1, encoding="ascii")
    return p


def _n_mols(scene) -> int:
    return scene["meta"]["n_atoms"] // 3


def test_radius_pack_counts_whole_molecules(mol_res):
    """Molecules sit on a 10 Å cubic lattice; the centre is atom C1. Six
    neighbours lie at exactly 10 Å, twelve at 14.14 Å: r = 6 keeps only the
    origin molecule, r = 12 adds the six, and a partial molecule is never
    drawn (the count is always a multiple of the molecule size)."""
    from crystalpilot.refine.scene import build_scene

    s6 = build_scene(mol_res, mode="radius", radius=6.0, center="C1")
    assert _n_mols(s6) == 1 and s6["meta"]["n_atoms"] == 3
    s12 = build_scene(mol_res, mode="radius", radius=12.0, center="c1")
    assert _n_mols(s12) == 7 and s12["meta"]["n_atoms"] == 21
    assert s12["meta"]["truncated"] is False
    # every molecule keeps its three bonds (N1-O1 at 1.77 A is inside the
    # smtbx tolerance too), none is torn: 7 x 3
    assert len(s12["bonds"]) == 21


def test_radius_pack_default_centre_is_the_asu_centroid(mol_res):
    """Without a centre the sphere sits on the ASU centroid; with r = 12 the
    six face neighbours are still inside (the centroid is < 1 Å off C1)."""
    from crystalpilot.refine.scene import build_scene

    s = build_scene(mol_res, mode="radius", radius=12.0)
    assert _n_mols(s) == 7


def test_range_pack_is_a_centroid_box(mol_res):
    """The molecule's centroid is (0.543, 0.540, 0.500). In the default box
    -0.5..1.5 the a and b axes admit translations -1 and 0 only (0.543 + 1
    overshoots 1.5) while c admits -1, 0, +1: 2 x 2 x 3 = 12 molecules. A
    -0.6..1.6 box admits -1, 0, +1 on every axis: 27. The box 0..1 admits
    only the origin molecule."""
    from crystalpilot.refine.scene import build_scene

    s = build_scene(mol_res, mode="range",
                    frac_range=((-0.5, -0.5, -0.5), (1.5, 1.5, 1.5)))
    assert _n_mols(s) == 12
    s27 = build_scene(mol_res, mode="range",
                      frac_range=((-0.6, -0.6, -0.6), (1.6, 1.6, 1.6)))
    assert _n_mols(s27) == 27
    s1 = build_scene(mol_res, mode="range",
                     frac_range=((0, 0, 0), (1, 1, 1)))
    assert _n_mols(s1) == 1
    # a swapped bound is tolerated (lo/hi are ordered per axis)
    s2 = build_scene(mol_res, mode="range",
                     frac_range=((1.6, 1.6, 1.6), (-0.6, -0.6, -0.6)))
    assert _n_mols(s2) == 27


def test_growth_and_stubs_compose_with_the_new_slices(mol_res):
    """Growing is an action on any slice; the isolated molecule has no
    bonded neighbours so growth adds nothing, and the new slices still emit
    grow stubs (none here) without failing."""
    from crystalpilot.refine.scene import build_scene

    s = build_scene(mol_res, mode="radius", radius=6.0, center="C1", hops=2)
    assert s["meta"]["n_atoms"] == 3
    assert s["stubs"] == []


COMPLETE_P1BAR = (
    "TITL dimer across an inversion centre plus a lone solvent atom\n"
    "CELL 0.71073 10 10 10 90 90 90\n"
    "ZERR 1 0 0 0 0 0 0\n"
    "LATT 1\n"
    "SFAC C O\n"
    "UNIT 4 2\n"
    "C1 1 0.42 0.50 0.50 11 0.05\n"
    "C2 1 0.28 0.50 0.50 11 0.05\n"
    "O1 2 0.10 0.20 0.80 11 0.05\n"
    "HKLF 4\n"
    "END\n"
)


def test_complete_applies_used_operators_to_the_whole_asu(tmp_path):
    """C1 bonds to its inversion image C1' (1.6 Å) so one shell of growth
    draws C1' and nothing else. `complete` (grow -w) then applies that same
    operator to the whole ASU: C2' and the solvent image O1' appear too."""
    from crystalpilot.refine.scene import build_scene

    res = tmp_path / "dimer.res"
    res.write_text(COMPLETE_P1BAR, encoding="ascii")
    grown = build_scene(res, mode="asu", hops=1)
    assert grown["meta"]["n_atoms"] == 4
    whole = build_scene(res, mode="asu", hops=1, complete=True)
    assert whole["meta"]["n_atoms"] == 6
    labels = sorted(a["label"] for a in whole["atoms"])
    assert labels == ["C1", "C1", "C2", "C2", "O1", "O1"]
    # without growth there is only the identity operator: complete is a no-op
    assert build_scene(res, mode="asu", complete=True)["meta"]["n_atoms"] == 3


def test_cached_scene_keys_the_new_parameters(tmp_path, monkeypatch):
    """Two radius packs with different radii must not share a cache file,
    and the key material is absent for the classic slices (old cache files
    stay valid)."""
    from crystalpilot.refine import scene as sc

    seen: list[str] = []

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
    monkeypatch.setattr(sc, "cache_dir", lambda project_dir, node: tmp_path / "cache")
    monkeypatch.setattr(sc, "_read_scene_cache", lambda path, touch=False: None)

    def fake_write(path, scene, grown=False):
        seen.append(path.name)

    monkeypatch.setattr(sc, "_write_scene_cache", fake_write)
    sc.cached_scene(tmp_path, "n0001", mode="asu", n=1, hops=0, polyhedra=True, diff=False)
    sc.cached_scene(tmp_path, "n0001", mode="radius", n=1, hops=0, polyhedra=True,
                    diff=False, radius=6.0, center="C1")
    sc.cached_scene(tmp_path, "n0001", mode="radius", n=1, hops=0, polyhedra=True,
                    diff=False, radius=12.0, center="C1")
    sc.cached_scene(tmp_path, "n0001", mode="asu", n=1, hops=1, polyhedra=True,
                    diff=False, complete=True)
    assert seen[0] == "scene8_asu_n1_h0_p1_d0.json"
    assert seen[1] != seen[2] and "_r6.0_" in seen[1] and "_r12.0_" in seen[2]
    assert seen[3].endswith("_w1.json")
