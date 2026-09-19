"""Scene builder: modes, symmetry-exact bonds, diff flags, polyhedra.

Uses the committed mvp-sjtu9 node store as a stable fixture.
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
NODES = REPO / "workbench" / "mvp-sjtu9" / ".crystalpilot" / "refine" / "nodes"

pytestmark = pytest.mark.skipif(not NODES.exists(),
                                reason="mvp-sjtu9 fixture not present")


def _scene(node: str, **kw):
    from crystalpilot.refine.scene import build_scene
    return build_scene(NODES / node / "model.res", **kw)


def test_modes_scale_sensibly():
    asu = _scene("n0013", mode="asu")
    grow = _scene("n0013", mode="grow", hops=1)
    cell = _scene("n0013", mode="cell")
    sup = _scene("n0013", mode="supercell", n=2)
    assert asu["meta"]["n_atoms"] == 21          # 16 non-H + 5 H
    assert grow["meta"]["n_atoms"] > asu["meta"]["n_atoms"]
    assert cell["meta"]["n_atoms"] > grow["meta"]["n_atoms"]
    assert sup["meta"]["n_atoms"] == 8 * cell["meta"]["n_atoms"]
    assert not sup["meta"]["truncated"]
    # bonds reference valid atom indices
    n = sup["meta"]["n_atoms"]
    assert all(0 <= i < n and 0 <= j < n for i, j, _k in sup["bonds"])


def test_grow_produces_metal_polyhedra():
    grow = _scene("n0013", mode="grow", hops=1, polyhedra=True)
    assert grow["meta"]["n_polyhedra"] >= 1
    poly = grow["polyhedra"][0]
    assert len(poly["vertices"]) >= 4
    assert all(len(f) == 3 for f in poly["faces"])


def test_diff_flags_added_atoms():
    # n0005 added the two ring carbons C8X/C9X relative to n0004
    s = _scene("n0005", mode="asu",
               parent_res_path=NODES / "n0004" / "model.res")
    flagged = {a["label"]: a["flag"] for a in s["atoms"] if a.get("flag")}
    assert flagged.get("C8X") == "added"
    assert flagged.get("C9X") == "added"


def test_diff_vs_arbitrary_baseline():
    """P1 节点对比泛化: cached_scene(diff_vs=...) compares against ANY
    node, not just the parent, and caches under a vs-specific key."""
    from crystalpilot.refine.scene import cache_dir, cached_scene
    project = REPO / "workbench" / "mvp-sjtu9"
    s = cached_scene(project, "n0005", mode="asu", n=2, hops=0,
                     polyhedra=False, diff=False, diff_vs="n0004")
    flagged = {a["label"]: a["flag"] for a in s["atoms"] if a.get("flag")}
    assert flagged.get("C8X") == "added"
    assert flagged.get("C9X") == "added"
    key = cache_dir(project, "n0005") / "scene8_asu_n2_h0_p0_dvs-n0004.json"
    assert key.exists()
    # plain (no-diff) scene of the same node must not pick up the flags
    s0 = cached_scene(project, "n0005", mode="asu", n=2, hops=0,
                      polyhedra=False, diff=False)
    assert not any(a.get("flag") for a in s0["atoms"])


def test_2fofc_map_variant(tmp_path):
    """P1-5: kind='2fofc' writes its own CCP4 and NO peaks.json (Q peaks
    are a residual-map concept)."""
    from crystalpilot.refine.scene import build_fofc_ccp4
    from tests.test_data_versions import _project
    project = _project(tmp_path)
    out = tmp_path / "m" / "2fofc.ccp4"
    r = build_fofc_ccp4(project.dir, "n0000", out, kind="2fofc")
    assert out.exists() and r["n_peaks"] == 0
    assert not out.with_name("peaks.json").exists()


def test_prewarm_orchestrates_and_swallows_errors(monkeypatch):
    """Turn-idle prewarm: warms asu scene / fofc / voids / grow scene for
    the active node, one failing product must not stop the rest, no active
    node = no-op."""
    import crystalpilot.refine.nodes as nodes_mod
    import crystalpilot.refine.scene as sc

    calls = []

    class FakeStore:
        def __init__(self, p):
            pass

        def state(self):
            return {"active_node": "n0007"}

    def boom(*a, **k):
        calls.append("fofc")
        raise RuntimeError("boom")

    monkeypatch.setattr(nodes_mod, "NodeStore", FakeStore)
    monkeypatch.setattr(
        sc, "cached_scene",
        lambda *a, **k: calls.append(
            f"scene:{k.get('mode')}:{k.get('hops')}"))
    monkeypatch.setattr(sc, "cached_fofc", boom)
    monkeypatch.setattr(sc, "cached_voids",
                        lambda *a, **k: calls.append("voids"))
    sc.prewarm_display_cache("X:/nonexistent")
    # the first grow shell comes last: the three products a user opens
    # first must not wait behind it, but it IS warmed - that press was the
    # cold build that actually hurt, and only the ungrown asu was warmed
    assert calls == ["scene:asu:0", "fofc", "voids", "scene:asu:1"]

    class EmptyStore(FakeStore):
        def state(self):
            return {}

    calls.clear()
    monkeypatch.setattr(nodes_mod, "NodeStore", EmptyStore)
    sc.prewarm_display_cache("X:/nonexistent")
    assert calls == []


def test_cell_mode_completes_boundary_molecules(tmp_path):
    """P1-4 跨界分子补全: a finite molecule straddling the cell boundary is
    wrapped by centroid and drawn whole (bond intact, one atom poking out of
    the box) instead of being chopped into fragments on opposite faces."""
    from crystalpilot.refine.scene import build_scene
    res = tmp_path / "mol.res"
    res.write_text(
        "TITL boundary molecule\n"
        "CELL 0.71073 10 10 10 90 90 90\n"
        "ZERR 1 0 0 0 0 0 0\n"
        "LATT -1\n"
        "SFAC C N\n"
        "UNIT 1 1\n"
        "C1 1 0.95 0.5 0.5 11 0.05\n"
        "N1 2 1.09 0.5 0.5 11 0.05\n"
        "HKLF 4\n"
        "END\n",
        encoding="ascii",
    )
    s = build_scene(res, mode="cell")
    assert s["meta"]["n_atoms"] == 2
    # per-atom wrapping would place them 8.6 A apart with no bond
    assert len(s["bonds"]) == 1
    i, j, _k = s["bonds"][0]
    d = sum((a - b) ** 2 for a, b in
            zip(s["atoms"][i]["xyz"], s["atoms"][j]["xyz"])) ** 0.5
    assert abs(d - 1.4) < 0.05
    # the molecule keeps its shape: one atom sits just outside the box
    assert min(a["xyz"][0] for a in s["atoms"]) < 0


def _write_res(path, body: str) -> None:
    path.write_text(body, encoding="ascii")


def test_short_contacts_channel(tmp_path):
    """P2-2 vdW 短接触: contacts=True emits materialized contact edges and
    (asu mode) clickable contact stubs; covalent pairs never leak in; the
    channel is off by default."""
    from crystalpilot.refine.scene import build_scene
    res = tmp_path / "cl.res"
    _write_res(res,
               "TITL contact fixture\n"
               "CELL 0.71073 5 8 8 90 90 90\n"
               "ZERR 1 0 0 0 0 0 0\n"
               "LATT -1\n"
               "SFAC CL\n"
               "UNIT 2\n"
               "CL1 1 0.1 0.0 0.0 11 0.05\n"
               "CL2 1 0.5 0.0 0.0 11 0.05\n"
               "HKLF 4\nEND\n")
    # covalent Cl1-Cl2 2.0 A; Cl2...Cl1(x+1) 3.0 A < vdW sum 3.5 A
    off = build_scene(res, mode="supercell", n=2)
    assert off["contacts"] == []
    assert not any(s.get("kind") == "contact" for s in off["stubs"])

    # the contact partner sits in the NEXT cell, so materialized edges
    # need a packing view (supercell); asu/grow offer it as a stub instead
    sup = build_scene(res, mode="supercell", n=2, contacts=True)
    assert len(sup["contacts"]) >= 1
    for i, j, d in sup["contacts"]:
        assert abs(d - 3.0) < 0.01     # never the 2.0 A covalent pair
        got = sum((a - b) ** 2 for a, b in
                  zip(sup["atoms"][i]["xyz"], sup["atoms"][j]["xyz"])) ** 0.5
        assert abs(got - d) < 0.01     # edge indices point at a real 3.0 A pair

    asu = build_scene(res, mode="asu", contacts=True)
    cstubs = [s for s in asu["stubs"] if s.get("kind") == "contact"]
    assert len(cstubs) >= 1            # packing neighbour offered for growth
    assert all("op" in s and s["elem"] == "Cl" for s in cstubs)


def test_short_contacts_exclude_hbond_range(tmp_path):
    """Polar pairs at hydrogen-bond distance stay in the hbond channel."""
    from crystalpilot.refine.scene import build_scene
    res = tmp_path / "o2.res"
    _write_res(res,
               "TITL hbond overlap\n"
               "CELL 0.71073 10 10 10 90 90 90\n"
               "ZERR 1 0 0 0 0 0 0\n"
               "LATT -1\n"
               "SFAC O\n"
               "UNIT 2\n"
               "O1 1 0.10 0.0 0.0 11 0.05\n"
               "O2 1 0.38 0.0 0.0 11 0.05\n"
               "HKLF 4\nEND\n")
    # O1...O2 2.8 A: hbond range (<= 2.9) -> excluded from contacts,
    # present in hbonds
    s = build_scene(res, mode="asu", contacts=True)
    assert s["contacts"] == []
    assert any(abs(h[2] - 2.8) < 0.05 for h in s["hbonds"])


def test_cell_mode_framework_unchanged():
    """Polymeric components (MOF framework) keep classic per-atom wrapping:
    every atom of the cell scene stays inside [0,1)."""
    cell = _scene("n0013", mode="cell")
    # n0013 is an extended framework: the closure probe must classify it
    # polymeric, so all fractional coords remain wrapped into the box
    from crystalpilot.io.shelx_model import load_res_model
    uc = load_res_model(NODES / "n0013" / "model.res").structure.unit_cell()
    for a in cell["atoms"]:
        f = uc.fractionalize(a["xyz"])
        assert all(-1e-4 <= x < 1 + 1e-4 for x in f), a["label"]


def test_symmetry_elements_p21c_and_enantiomers():
    """P2-3 对称元素: P2₁/c yields its textbook 2₁ axes along b, c-glide
    planes and inversion centres; trigonal enantiomers keep their screw
    handedness (3₁ vs 3₂); P1 has no elements."""
    import json

    from cctbx.crystal import symmetry as csym
    from cctbx.xray import structure

    from crystalpilot.refine.scene import _symmetry_elements

    def els(sg, cell):
        xs = structure(crystal_symmetry=csym(unit_cell=cell,
                                             space_group_symbol=sg))
        e = _symmetry_elements(xs)
        json.dumps(e)                     # must be JSON-serializable
        return e

    e = els("P 21/c", (8, 9, 10, 90, 95, 90))
    axes = [x for x in e if x["kind"] == "axis"]
    planes = [x for x in e if x["kind"] == "plane"]
    points = [x for x in e if x["kind"] == "point"]
    assert all(a["symbol"] == "2₁" and a["screw"] for a in axes)
    assert len(axes) >= 4
    # 2_1 runs along b: endpoints differ only in y
    for a in axes:
        p, q = a["seg"]
        assert p[0] == q[0] and p[2] == q[2] and p[1] != q[1]
    assert planes and all(p["symbol"] == "c" and p["glide"] for p in planes)
    assert len(points) >= 8               # inversion centres at 0/½ grid

    s31 = {x["symbol"] for x in els("P 31 2 1", (8, 8, 11, 90, 90, 120))}
    s32 = {x["symbol"] for x in els("P 32 2 1", (8, 8, 11, 90, 90, 120))}
    assert "3₁" in s31 and "3₂" not in s31
    assert "3₂" in s32 and "3₁" not in s32

    assert els("P 1", (7, 8, 9, 80, 95, 100)) == []


def test_bond_geometry_is_short():
    cell = _scene("n0013", mode="cell")
    atoms = cell["atoms"]
    metals = {"Zr", "Fe", "Cu", "Zn"}
    for i, j, _k in cell["bonds"]:
        d = sum((a - b) ** 2 for a, b in
                zip(atoms[i]["xyz"], atoms[j]["xyz"])) ** 0.5
        # metal-metal cluster edges (Zr...Zr in Zr6 ~3.5 A) are legitimate
        limit = 4.0 if (atoms[i]["elem"] in metals
                        and atoms[j]["elem"] in metals) else 3.2
        assert d < limit, \
            f"absurd bond {atoms[i]['label']}-{atoms[j]['label']} {d:.2f}"


def test_build_fofc_writes_peaks_json(tmp_path):
    """P0-1: the one-shot map session must produce peaks.json alongside the
    CCP4 so the web viewer can render discrete Q peaks without a second
    model+data rebuild."""
    import json

    from crystalpilot.refine.scene import build_fofc_ccp4
    from tests.test_data_versions import _project
    project = _project(tmp_path)
    out = tmp_path / "fofc.ccp4"
    info = build_fofc_ccp4(project.dir, "n0000", out)
    assert out.exists() and out.stat().st_size > 0
    pk = out.with_name("peaks.json")
    assert pk.exists()
    data = json.loads(pk.read_text(encoding="utf-8"))
    assert isinstance(data["peaks"], list)
    assert info["n_peaks"] == len(data["peaks"])
    for p0 in data["peaks"][:3]:
        assert set(p0) >= {"site", "height", "nearest_atom", "nearest_d"}
        assert len(p0["site"]) == 3


def test_build_void_ccp4_products(tmp_path):
    """P0-2: void map + metadata for the web viewer; runs on nodes that
    never executed solvent_mask (look-before-SQUEEZE scenario)."""
    import json

    from crystalpilot.refine.scene import VOIDS_CACHE_V, build_void_ccp4
    from tests.test_data_versions import _project
    project = _project(tmp_path)
    out = tmp_path / "voids.ccp4"
    info = build_void_ccp4(project.dir, "n0000", out)
    meta = json.loads(
        out.with_name("voids.json").read_text(encoding="utf-8"))
    assert meta["n_voids"] == info["n_voids"]
    if info["n_voids"] > 0:
        v0 = meta["voids"][0]
        assert v0["volume_A3"] > 0
        # R3.0 (D17): a centroid only for a 0-D cavity; every void has an
        # inscribed-sphere centre inside the cell and a periodicity
        for v in meta["voids"]:
            assert v["dimensionality"] in (0, 1, 2, 3)
            if v["dimensionality"] == 0:
                assert len(v["centre_frac"]) == 3 and v["directions"] == []
            else:
                assert v["centre_frac"] is None and "centre_note" in v
                assert len(v["directions"]) == v["dimensionality"]
            assert all(0.0 <= x < 1.0 for x in v["inscribed_centre_frac"])
            assert v["lcd_A"] > 0 and v["grid_step_A"] > 0
        # read the constant, not a literal: bumping VOIDS_CACHE_V is
        # how a shape/number change heals stale caches, and a hard 4
        # here turns every legitimate bump into a red test
        assert meta["v"] == VOIDS_CACHE_V and "pore_note" in meta
        for v in meta["voids"]:
            # v4: PLD per void (None for a cavity, with the note) and the
            # error is the grid step that produced it
            assert "pld_A" in v and "pld_error_A" in v
            if v["dimensionality"] == 0:
                assert v["pld_A"] is None and "pld_note" in v
            elif v["pld_A"] is not None:
                assert v["pld_A"] <= v["lcd_A"] + v["pld_error_A"]
                assert v["pld_directions"]
        pk = meta["packing"]
        assert pk["occupancy_weighted"] and pk["packing_index_pct"] > 0
        assert pk["volume_per_non_h_atom_A3"] > 0 and "不是 100" in pk["note"]
    # the surface exists exactly when something was masked: voids dropped
    # below min_void_volume are listed but not drawn
    assert meta["map"] is (info.get("n_voids_masked", 0) > 0)
    assert out.exists() is meta["map"]
    if meta["map"]:
        assert out.stat().st_size > 0


# ---------------------------------------------------------------------------
# grown-scene disk cache (interactive grow latency)
# ---------------------------------------------------------------------------
_GROW_RES = (
    "TITL grow cache fixture\n"
    "CELL 0.71073 6 7 8 90 90 90\n"
    "ZERR 1 0 0 0 0 0 0\n"
    "LATT -1\n"
    "SFAC C N\n"
    "UNIT 1 1\n"
    "C1 1 0.10 0.20 0.30 11 0.05\n"
    "N1 2 0.33 0.20 0.30 11 0.05\n"
    "HKLF 4\nEND\n"
)


class _FakeStore:
    """cached_scene only needs resolve/node_dir/node_meta, so a fake keeps
    these tests off the committed workbench and out of its scene-cache."""

    def __init__(self, project_dir):
        self.root = Path(project_dir)

    def state(self):
        return {"active_node": "n0001"}

    def resolve(self, ref):
        return ref

    def node_dir(self, node_id):
        return self.root / "nodes" / node_id

    def node_meta(self, node_id):
        return {}


@pytest.fixture
def grow_project(tmp_path, monkeypatch):
    """(project_dir, build_log, real_build_scene) with build_scene wrapped so
    a cache hit is distinguishable from a rebuild."""
    import crystalpilot.refine.nodes as nodes_mod
    import crystalpilot.refine.scene as sc

    ndir = tmp_path / "nodes" / "n0001"
    ndir.mkdir(parents=True)
    (ndir / "model.res").write_text(_GROW_RES, encoding="ascii")
    monkeypatch.setattr(nodes_mod, "NodeStore", _FakeStore)
    real = sc.build_scene
    log: list = []

    def counted(*a, **k):
        log.append(k.get("extra"))
        return real(*a, **k)

    monkeypatch.setattr(sc, "build_scene", counted)
    return tmp_path, log, real


def _cached(proj, **kw):
    from crystalpilot.refine.scene import cached_scene
    kw.setdefault("mode", "asu")
    kw.setdefault("n", 2)
    kw.setdefault("hops", 1)
    kw.setdefault("polyhedra", True)
    kw.setdefault("diff", False)
    return cached_scene(proj, "n0001", **kw)


def _grown_files(proj):
    import crystalpilot.refine.scene as sc
    return sorted(sc.cache_dir(proj, "n0001").glob(sc._GROWN_GLOB))


def test_grown_scene_hits_the_disk_cache(grow_project):
    """Every grow click used to re-run load_res_model + pair_sym_table +
    closure; the second request for the same fragment set must not rebuild."""
    import json as _json
    proj, log, _real = grow_project
    grown = [{"i": 0, "op": "x+1,y,z"}]
    s1 = _cached(proj, extra=grown)
    assert len(log) == 1
    s2 = _cached(proj, extra=grown)
    assert len(log) == 1
    assert _json.dumps(s2, sort_keys=True) == _json.dumps(s1, sort_keys=True)
    assert s2["node"] == "n0001" and s2["meta"]["n_atoms"] == 3
    assert len(_grown_files(proj)) == 1


def test_grown_cache_separates_fragment_sets(grow_project):
    proj, log, _real = grow_project
    a = _cached(proj, extra=[{"i": 0, "op": "x+1,y,z"}])
    b = _cached(proj, extra=[{"i": 0, "op": "x-1,y,z"}])
    assert len(log) == 2 and len(_grown_files(proj)) == 2
    assert ([x["xyz"] for x in a["atoms"]]
            != [x["xyz"] for x in b["atoms"]])
    # a set that GREW by one click is a new entry, not an overwrite
    c = _cached(proj, extra=[{"i": 0, "op": "x+1,y,z"},
                             {"i": 1, "op": "x+1,y,z"}])
    assert len(log) == 3 and len(_grown_files(proj)) == 3
    assert c["meta"]["n_atoms"] == a["meta"]["n_atoms"] + 1
    # display options still partition the key space
    _cached(proj, extra=[{"i": 0, "op": "x+1,y,z"}], contacts=True)
    assert len(log) == 4 and len(_grown_files(proj)) == 4


def test_grown_cache_is_order_independent(grow_project):
    """Regrowing the same fragments in a different click order reuses the
    entry. The orders are NOT byte-identical when built fresh - they permute
    the atom tail - but every index in a response resolves against that same
    response, and the viewer drops its selection on each scene load."""
    proj, log, real = grow_project
    g = [{"i": 0, "op": "x+1,y,z"}, {"i": 1, "op": "x,y+1,z"}]
    first = _cached(proj, extra=g)
    again = _cached(proj, extra=list(reversed(g)))
    assert len(log) == 1
    assert again["atoms"] == first["atoms"]
    assert len(_grown_files(proj)) == 1
    # the equivalence being asserted is deliberate, not vacuous: a fresh
    # build of the reversed order really does come back permuted
    res = proj / "nodes" / "n0001" / "model.res"
    flipped = real(res, mode="asu", extra=list(reversed(g)))
    assert flipped["atoms"] != first["atoms"]
    assert ({tuple(a["xyz"]) for a in flipped["atoms"]}
            == {tuple(a["xyz"]) for a in first["atoms"]})


def test_grown_cache_is_bounded(grow_project, monkeypatch):
    """A long grow session must not fill the disk with variants, and the
    sweep must never take the plain per-node entry that prewarm builds.

    Deliberately run in "grow" mode: its plain key is
    scene8_grow_n2_h1_p1_d0.json, which CONTAINS "_g" - a sweep matched on
    that marker alone would eat the entry every grow session."""
    import crystalpilot.refine.scene as sc
    monkeypatch.setattr(sc, "GROWN_CACHE_MAX", 4)
    proj, log, _real = grow_project
    d = sc.cache_dir(proj, "n0001")
    plain = _cached(proj, mode="grow")
    n_plain = plain["meta"]["n_atoms"]
    for k in range(1, 10):
        _cached(proj, mode="grow", extra=[{"i": 0, "op": f"x+{k},y,z"}])
        assert len(_grown_files(proj)) <= 4
    assert len(log) == 10
    assert len(list(d.glob("*.json"))) == 5   # 4 grown + the plain entry
    assert (d / "scene8_grow_n2_h1_p1_d0.json").exists()
    assert _cached(proj, mode="grow")["meta"]["n_atoms"] == n_plain
    assert len(log) == 10                     # plain entry served, no rebuild


def test_grown_cache_evicts_least_recently_used(grow_project, monkeypatch):
    """Eviction is by USE, not by write order: a set revisited after a mode
    toggle must outlive an older neighbour."""
    import os
    import time

    import crystalpilot.refine.scene as sc
    monkeypatch.setattr(sc, "GROWN_CACHE_MAX", 3)
    proj, log, _real = grow_project
    sets = [[{"i": 0, "op": f"x+{k},y,z"}] for k in (1, 2, 3)]
    for g in sets:
        _cached(proj, extra=g)

    d = sc.cache_dir(proj, "n0001")

    def _path(g):
        hits = list(d.glob(f"*_g{sc._extra_digest(g)}.json"))
        return hits[0] if hits else None

    # Windows' utime(None) resolution is coarse enough for a tight write
    # loop to tie, so stamp explicit ages instead of sleeping
    now = time.time()
    for age, g in enumerate(sets):
        os.utime(_path(g), (now - 300 + age, now - 300 + age))

    assert _cached(proj, extra=sets[0])["meta"]["n_atoms"] == 3
    assert len(log) == 3                     # a hit, and it refreshed mtime
    _cached(proj, extra=[{"i": 0, "op": "x+9,y,z"}])
    assert _path(sets[0]) is not None        # touched: not the victim
    assert _path(sets[1]) is None            # now the least recently used
    assert _path(sets[2]) is not None


def test_corrupt_cache_entry_heals(grow_project):
    """A truncated or half-written entry must rebuild, not 500 the viewer."""
    proj, log, _real = grow_project
    grown = [{"i": 0, "op": "x+1,y,z"}]
    _cached(proj, extra=grown)
    _grown_files(proj)[0].write_text("{not json", encoding="utf-8")
    s = _cached(proj, extra=grown)
    assert len(log) == 2 and s["meta"]["n_atoms"] == 3


def test_symmetry_elements_memo_is_per_space_group(monkeypatch):
    """_symmetry_elements ran on EVERY build although it depends only on the
    space group (all clipping is fractional) - ~0.15 s a call for a cubic
    F/I group. Distinct settings of one group must not share an entry."""
    from cctbx.crystal import symmetry as csym
    from cctbx.xray import structure

    import crystalpilot.refine.scene as sc
    monkeypatch.setattr(sc, "_SYM_MEMO", {})
    misses: list = []
    real = sc._symmetry_elements
    monkeypatch.setattr(sc, "_symmetry_elements",
                        lambda xs: (misses.append(1), real(xs))[1])

    def xs(sym, cell):
        return structure(crystal_symmetry=csym(unit_cell=cell,
                                               space_group_symbol=sym))

    a = sc._symmetry_elements_memo(xs("P 21/c", (8, 9, 10, 90, 95, 90)))
    # same group, wildly different cell: the elements are cell-independent
    b = sc._symmetry_elements_memo(xs("P 21/c", (30, 4, 77, 90, 120, 90)))
    assert a and b == a and len(misses) == 1
    c = sc._symmetry_elements_memo(xs("P 21/n", (8, 9, 10, 90, 95, 90)))
    assert len(misses) == 2
    assert {e["symbol"] for e in c} != {e["symbol"] for e in a}


def _grow_res(tmp_path):
    """P2(1) chain along a: C1-C2 are 1.5 A apart inside the cell and C2
    reaches the next C1 across the a translation, so the fragment is an
    endless polymer and growth always has somewhere to go. The 2(1) axis
    gives the packed cell more content than the asymmetric unit."""
    res = tmp_path / "chain.res"
    res.write_text(
        "TITL grow chain\n"
        "CELL 0.71073 3 12 6 90 90 90\n"
        "ZERR 2 0 0 0 0 0 0\n"
        "LATT -1\n"
        "SYMM -X,-Y,1/2+Z\n"
        "SFAC C\n"
        "UNIT 4\n"
        "C1 1 0.10 0.10 0.10 11 0.05\n"
        "C2 1 0.60 0.10 0.10 11 0.05\n"
        "HKLF 4\n"
        "END\n",
        encoding="ascii",
    )
    return res


def test_growth_is_an_action_not_a_mode(tmp_path):
    """hops composes with ANY slice, seeded from every instance the mode
    materialized - Olex2's `pack` then `grow`. It used to be reachable only
    through mode="grow", which meant "the asymmetric unit, grown", so
    growing out of a packed cell was not expressible at all."""
    from crystalpilot.refine.scene import build_scene
    res = _grow_res(tmp_path)

    asu = build_scene(res, mode="asu", hops=0)["meta"]["n_atoms"]
    cell = build_scene(res, mode="cell", hops=0)["meta"]["n_atoms"]
    assert cell > asu                      # packing alone adds images

    # each shell adds more, from either starting slice
    asu_shells = [build_scene(res, mode="asu", hops=h)["meta"]["n_atoms"]
                  for h in (0, 1, 2)]
    cell_shells = [build_scene(res, mode="cell", hops=h)["meta"]["n_atoms"]
                   for h in (0, 1, 2)]
    assert asu_shells[0] < asu_shells[1] < asu_shells[2]
    assert cell_shells[0] < cell_shells[1]
    # the whole point: growing from the cell is not the same as growing
    # from the asymmetric unit
    assert cell_shells[1] != asu_shells[1]


def test_grow_mode_still_means_asu_grown(tmp_path):
    """Older clients and cached keys say mode="grow"; it has to keep
    meaning what it did, which is the asymmetric unit with hops>=1."""
    from crystalpilot.refine.scene import build_scene
    res = _grow_res(tmp_path)
    for h in (1, 2):
        legacy = build_scene(res, mode="grow", hops=h)
        modern = build_scene(res, mode="asu", hops=h)
        assert legacy["meta"]["n_atoms"] == modern["meta"]["n_atoms"]
        assert legacy["mode"] == modern["mode"] == "asu"
    # hops=0 in the legacy spelling must not silently stop growing
    assert (build_scene(res, mode="grow", hops=0)["meta"]["n_atoms"]
            == build_scene(res, mode="asu", hops=1)["meta"]["n_atoms"])


def test_grow_stubs_reach_the_packed_cell(tmp_path):
    """Clickable grow directions used to exist only in asu/grow scenes, so
    a user who packed a cell could not grow out of it by clicking either."""
    from crystalpilot.refine.scene import build_scene
    res = _grow_res(tmp_path)
    assert build_scene(res, mode="cell", hops=0)["stubs"]


# ---------------------------------------------------------------------------
# solvent-void display: same mask the refinement applied, same numbers
# ---------------------------------------------------------------------------
_TOOL_MASK_PARAMS = {
    "solvent_radius": 1.3,
    "shrink_truncation_radius": 1.1,
    "resolution_factor": 0.3,
    "d_min": 0.997,
    "min_void_volume": 40.0,
    "max_cycles": 12,
}


def test_recorded_mask_params_are_all_forwarded():
    """The display used to read two of the six keys the solvent_mask tool
    records, so the picture was a DIFFERENT mask from the refinement's."""
    from crystalpilot.refine.scene import _void_mask_params
    params, src = _void_mask_params(
        {"mask": {"params": dict(_TOOL_MASK_PARAMS)}}, 0.80)
    assert src == "node"
    assert params == _TOOL_MASK_PARAMS
    # the session d_min must not shadow the node's own choice
    assert params["d_min"] == 0.997


def test_mask_params_without_a_record_still_carry_a_d_min():
    """No recorded mask = a preview at the tool's defaults, but d_min left
    unset would let smtbx pick one silently and the response could not name
    the gridding it drew."""
    from crystalpilot.refine.scene import (VOID_PREVIEW_DEFAULTS,
                                           _void_mask_params)
    params, src = _void_mask_params({}, 0.80)
    assert src == "defaults"
    assert params["d_min"] == 0.80
    for k, v in VOID_PREVIEW_DEFAULTS.items():
        assert params[k] == v
    # a node that ran solvent_mask WITHOUT an explicit d_min is still the
    # refinement's own mask, and still gets the session resolution
    params, src = _void_mask_params(
        {"mask": {"params": {"solvent_radius": 1.4, "d_min": None}}}, 0.80)
    assert src == "node" and params["d_min"] == 0.80
    assert params["solvent_radius"] == 1.4


class _FakeMask:
    """Just enough of smtbx.masks.mask for the electron bookkeeping."""

    def __init__(self, gp, n_grid, excluded=()):
        self._gp = list(gp)
        self._n_grid = n_grid
        self.exclude_void_flags = [i in excluded for i in range(len(gp))]

    def n_solvent_grid_points(self):
        return sum(g for i, g in enumerate(self._gp)
                   if not self.exclude_void_flags[i])


def test_void_electrons_sum_to_the_cell_total():
    """A BYPASS run that ends on max_cycles leaves f_000_s/V added over the
    whole void region, and electron_counts_per_void() reads that map - each
    per-void count then comes back scaled by n_grid/(n_grid-n_solvent)
    while the total is not. Removing the surplus is exact."""
    from crystalpilot.refine.scene import _consistent_void_electrons

    gp, n_grid = [600, 200], 1000
    m = _FakeMask(gp, n_grid)
    rescale = n_grid / (n_grid - sum(gp))          # 5.0
    # a void integral that is NOT proportional to void size, so the test
    # can tell "sums right" from "gets each void right"
    f_000 = [5.0, 3.0]
    total = sum(f_000) * rescale
    raw = [(f_000[i] + total * gp[i] / n_grid) * rescale
           for i in range(2)]
    assert sum(raw) == pytest.approx(total * rescale)
    fixed = _consistent_void_electrons(m, gp, raw, total)
    assert sum(fixed) == pytest.approx(total)
    assert fixed == pytest.approx([f * rescale for f in f_000])

    # converged run: nothing to remove, the raw numbers pass through
    conv = [f * rescale for f in f_000]
    assert _consistent_void_electrons(m, gp, conv, total) == \
        pytest.approx(conv)

    # an excluded void contributes nothing on either side of the books
    m2 = _FakeMask(gp, n_grid, excluded={1})
    out = _consistent_void_electrons(m2, gp, [total, 999.0], total)
    assert out[1] == 0.0
    assert sum(out) == pytest.approx(total)


def test_build_void_ccp4_reports_its_parameters(tmp_path):
    """Response has to say WHICH mask it drew: the node's own (what the
    refinement applied) or a default preview."""
    import json

    from crystalpilot.refine.scene import build_void_ccp4
    from tests.test_data_versions import _project
    project = _project(tmp_path)
    info = build_void_ccp4(project.dir, "n0000", tmp_path / "voids.ccp4")
    assert info["params_source"] in ("node", "defaults")
    p = info["mask_params"]
    assert set(p) >= {"solvent_radius", "shrink_truncation_radius",
                      "resolution_factor", "min_void_volume", "max_cycles",
                      "d_min"}
    assert p["d_min"] is not None
    meta = json.loads(
        (tmp_path / "voids.json").read_text(encoding="utf-8"))
    assert meta["mask_params"] == p
    # v7: the recount names the f'/f'' it integrated with and its own series
    assert "anomalous_terms" in meta and isinstance(meta["anomalous_terms"], dict)
    if info.get("total_solvent_electrons_per_cell") is not None:
        assert "converged" in info["bypass"] and info["bypass"]["n_cycles"] >= 1
    if info["n_voids"] and info.get("total_solvent_electrons_per_cell"):
        masked = [v for v in info["voids"] if v["masked"]]
        assert sum(v["electrons"] for v in masked) == pytest.approx(
            info["total_solvent_electrons_per_cell"], abs=0.2)


# ---------------------------------------------------------------------------
# lazy data block (Rint for nodes committed before RefineNode.data existed)
# ---------------------------------------------------------------------------
def test_data_block_prefers_the_node_own_record(monkeypatch, tmp_path):
    import crystalpilot.refine.scene as sc

    recorded = {"r_int": 0.0841, "n_unique": 4166, "d_min": 0.783}

    class _Store(_FakeStore):
        def node_meta(self, node_id):
            return {"data": dict(recorded)}

    class _Proj:
        def __init__(self, d):
            self.dir = Path(d)
            self.nodes = _Store(d)
            self.hkl_path = None

        def _build_session(self, path):        # pragma: no cover
            raise AssertionError("must not re-merge when the node has data")

    import crystalpilot.refine.project as proj_mod
    monkeypatch.setattr(proj_mod, "RefineProject", _Proj)
    out = sc.cached_data_block(tmp_path, "n0001")
    assert out == {"node": "n0001", "source": "node", "data": recorded, "data_revision": None}


def test_data_block_recomputed_is_labelled_and_cached(tmp_path):
    """A genuinely bound node can regenerate its optional summary, not its history."""
    import json
    from crystalpilot.refine.scene import cache_dir, cached_data_block
    from tests.test_data_versions import _project
    project = _project(tmp_path)
    meta_path = project.nodes.node_dir("n0000") / "node.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta.pop("data")
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    original = meta_path.read_bytes()
    out = cached_data_block(project.dir, "n0000")
    assert out["node"] == "n0000" and out["source"] == "computed"
    assert out["data_revision"] == meta["data_revision"]
    assert set(out["data"]) >= {"r_int", "n_unique", "d_min", "space_group"}
    assert "bound immutable" in out["note"]
    assert out["hkl"] == "observations.hkl"
    assert (cache_dir(project.dir, "n0000") / "data.json").exists()
    assert cached_data_block(project.dir, "n0000") == out
    assert meta_path.read_bytes() == original
