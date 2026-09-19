"""Known answers from the literature: net symbol, node connectivity,
interpenetration, LCD / PLD / channel dimensionality on real frameworks.

Everything else in `tests/test_topology.py` and `tests/test_pores.py` is
synthetic - correct by construction. This file is the other half: the same
code run on deposited CIFs whose answer a crystallographer already knows,
so a regression that keeps the synthetic fixtures green still gets caught.

WHAT IS COMPARED, AND WHY THE TOLERANCES ARE WHAT THEY ARE
----------------------------------------------------------
Net symbol / node connectivity / interpenetration are DISCRETE - they are
asserted exactly. The pore numbers are not, so they carry a bar:

  LCD +- 0.6 A, PLD +- 0.8 A against CoRE MOF 2019 (Chung et al.,
  J. Chem. Eng. Data 64 (2019) 5985, DOI 10.1021/acs.jced.9b00835; data
  Zenodo DOI 10.5281/zenodo.3677685, file 2019-11-01-ASR-public_12020.csv),
  which is Zeo++ run at high accuracy on the all-solvent-removed structure.

Three things move the number by design, none of them a bug:

1. vdW RADII SET. We use `cctbx.eltbx.van_der_waals_radii` (C 1.775,
   H 1.20, O 1.45, N 1.50); Zeo++ defaults to a CCDC-derived set and the
   Sarkisov benchmark forces UFF (C 1.7155, H 1.2855). A 0.08 A radius
   difference is 0.16 A of diameter, and a window bounded by two atoms
   doubles that.
2. WHICH CRYSTAL. CoRE's row is a DIFFERENT determination of the same
   material (other cell, temperature, disorder treatment). UiO-66 alone
   spans LCD 8.49-8.97 A across its own refcodes in the same database.
3. METHOD. Ours is a grid bisection over the solvent-mask voxels, error =
   the grid step (~0.29 A at the 0.3 A default); Zeo++ is an analytic
   Voronoi decomposition. This hits PLD hardest, because a narrow window is
   a few voxels wide - which is why the PLD bar is looser than the LCD bar.

Second opinions are recorded next to each number in
`benchmark/known_answers/<slug>/SOURCES.md`: the primary papers
(Nature 402 (1999) 276 for MOF-5, PNAS 103 (2006) 10186 for ZIF-8) and the
PoreBlazer-v4.0-vs-Zeo++ benchmark files deposited by Sarkisov et al.
(Chem. Mater. 32 (2020) 9849).

WHY THESE STRUCTURES DO NOT GO THROUGH `RefineProject`
------------------------------------------------------
`import_cif_model` refuses a CIF with no reflection data ("no reflection
data: the project has no crystal.hkl ..."), and COD publishes no .hkl for
any of these five entries. So the CIF is converted here with the SAME
production converter the tool uses (`_small_structure_to_xray` + the SHELX
writer), and the topology/pore modules are called on the resulting .res.
`test_nu1000_*` does use the full product path, because that benchmark
ships an sf.cif. See the report for the consequence: a CIF-only structure
cannot reach `build_void_ccp4` at all.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import numpy as np
import pytest

from crystalpilot.chem.topology import (parse_systre_error,
                                        parse_systre_symbols, systre_jar)

REPO = Path(__file__).resolve().parents[1]
KNOWN = REPO / "benchmark" / "known_answers"
PUBLIC = REPO / "benchmark" / "public"

LCD_TOL = 0.6
PLD_TOL = 0.8

#: slug -> everything the literature already says about it. `lcd`/`pld` are
#: the CoRE MOF 2019 ASR row named in `core_row`; `lit` is the primary
#: paper's own figure, carried for the report (not asserted - it uses other
#: radii). `hist` is {connectivity: how many nodes per cell}.
CASES = {
    "MOF-5_IRMOF-1": dict(
        n_nets=1, dims=[3], interpenetrated=False, hist={6: 8},
        symbol="pcu", pore_dim=3, lcd=15.051, pld=7.916,
        core_row="EDUSIF_clean",
        lit="Nature 402 (1999) 276: 15.1 A cavity, 8.0 A aperture"),
    "HKUST-1": dict(
        n_nets=1, dims=[3], interpenetrated=False, hist={4: 24, 3: 32},
        symbol="tbo", pore_dim=3, lcd=13.190, pld=6.657,
        core_row="FIQCEN_clean",
        lit="Science 283 (1999) 1148: '1 nanometer' channels (convention "
            "unstated); Zeo++/UFF 12.9998 / 6.3377"),
    "ZIF-8": dict(
        n_nets=1, dims=[3], interpenetrated=False, hist={4: 12},
        symbol="sod", pore_dim=3, lcd=11.393, pld=3.409,
        core_row="VELVOY_clean",
        lit="PNAS 103 (2006) 10186: 11.6 A cage, 3.4 A aperture"),
    "UiO-66": dict(
        n_nets=1, dims=[3], interpenetrated=False, hist={12: 4},
        symbol="fcu", pore_dim=3, lcd=8.739, pld=3.867,
        core_row="RUBTAK04_clean",
        lit="Zeo++/UFF on RUBTAK02: 8.966 / 3.850"),
    "interpenetrated_MOF-5": dict(
        n_nets=2, dims=[3, 3], interpenetrated=True, hist={6: 12},
        symbol="pcu", pore_dim=3, lcd=None, pld=None, core_row=None,
        lit="Inorg. Chem. 50 (2011) 3691: doubly interpenetrated MOF-5; "
            "no tabulated LCD/PLD found, so the pore numbers are recorded, "
            "not asserted"),
}

HAVE_SYSTRE = systre_jar() is not None and shutil.which("java") is not None


# ------------------------------------------------------------- machinery --

def _cif_to_res(cif: Path, out: Path) -> Path:
    """The production CIF -> .res conversion, minus the reflection-data gate.

    Same two calls `refine/tools_ingest.py::ImportCifModel` makes on its
    gemmi path, so what the modules see below is what a user's project
    would hold."""
    import gemmi

    from crystalpilot.io.shelx_writer import ShelxModel, write_res
    from crystalpilot.refine.tools_ingest import _small_structure_to_xray

    small = gemmi.read_small_structure(str(cif))
    xs, notes = _small_structure_to_xray(small)
    assert xs is not None, notes
    write_res(ShelxModel(xray_structure=xs,
                         wavelength=small.wavelength or 0.71073, z=None,
                         title=f"known answer {cif.parent.name}"), out)
    return out


def _p1_atoms(xs):
    p1 = xs.expand_to_p1()
    frac = np.array([[float(v) for v in s.site]
                     for s in p1.scatterers()]).reshape(-1, 3)
    els = [str(s.scattering_type).strip().capitalize()
           for s in p1.scatterers()]
    return frac, els


def _analyse(res: Path, *, pores: bool = True) -> dict:
    """Topology (+ pores) of one .res, exactly as the product computes them.

    Pores go through `chem.guests.host_void_map` - the documented no-data
    mask path - plus `chem.pores.pore_limiting_diameter`, because
    `scene.build_void_ccp4` needs a session (i.e. reflection data) and
    `host_void_map` computes no PLD of its own.
    """
    from crystalpilot.io.shelx_model import load_res_model
    from crystalpilot.refine.analysis import topology_from_res

    parsed = load_res_model(res)
    out = {"topology": topology_from_res(res), "xs": parsed.structure}
    if not pores:
        return out
    from crystalpilot.chem.guests import host_void_map
    from crystalpilot.chem.pores import pore_limiting_diameter

    xs = parsed.structure
    hv = host_void_map(xs, parts=parsed.parts)
    frac, els = _p1_atoms(xs)
    voids = []
    for v in hv["voids"]:
        pld = pore_limiting_diameter(hv["labels"], v["id"] + 1,
                                     xs.unit_cell(), frac, els)
        voids.append(dict(v, pld_A=pld["pld_A"],
                          pld_error_A=pld["pld_error_A"],
                          pld_directions=pld["pld_directions"]))
    out["pores"] = dict(hv, voids=voids, labels=None)
    return out


@pytest.fixture(scope="module")
def bench(tmp_path_factory):
    """slug -> analysis, computed at most once per slug per session."""
    root = tmp_path_factory.mktemp("known-answers")
    cache: dict[str, dict] = {}

    def get(slug: str, *, pores: bool = True) -> dict:
        key = f"{slug}:{pores}"
        if key not in cache:
            cif = KNOWN / slug / "ref.cif"
            if not cif.exists():
                pytest.skip(f"{cif} not present - see {KNOWN / slug}"
                            f"/SOURCES.md for the COD download command")
            cache[key] = _analyse(_cif_to_res(cif, root / f"{slug}.res"),
                                  pores=pores)
        return cache[key]

    return get


def _main_void(pores: dict) -> dict:
    """The void the literature number is about: the biggest one."""
    kept = [v for v in pores["voids"] if not v["below_min_volume"]]
    assert kept, "no solvent-accessible void above the minimum volume"
    return max(kept, key=lambda v: v["volume_A3"])


# --------------------------------------------------------------- topology --

@pytest.mark.parametrize("slug", sorted(CASES))
def test_nets_and_interpenetration(bench, slug):
    """How many independent nets, of what dimensionality, related how."""
    want = CASES[slug]
    nets = bench(slug, pores=False)["topology"]["nets"]
    assert nets["n_nets"] == want["n_nets"]
    assert [n["dimensionality"] for n in nets["nets"]] == want["dims"]
    # symmetry relation between the nets is one fact ...
    assert nets["symmetry_related"] is want["interpenetrated"]
    # ... and interpenetration is DECIDED by ring threading (round-3 R5):
    # the doubly interpenetrated MOF-5 threads, single nets are False
    assert nets["interpenetrated"] is want["interpenetrated"]
    if want["n_nets"] > 1:
        assert nets["interpenetration_status"] == "tested"
        assert any(p["status"] == "threaded" for p in nets["threading"]["pairs"])
    assert nets["symmetry_related_1d"] is False


def test_interpenetrated_mof5_nets_are_related_by_the_inversion_centre(bench):
    """COD 4324900 is doubly interpenetrated MOF-5 in R-3: the second pcu
    net is the first one through the inversion centre, so the verdict must
    be `space_group_op`, not `translation` and not `independent`."""
    nets = bench("interpenetrated_MOF-5", pores=False)["topology"]["nets"]
    assert len(nets["relations"]) == 1
    rel = nets["relations"][0]
    assert rel["relation"] == "space_group_op"
    assert rel["op"] == "-x,-y,-z"
    # the DEF/water guests must have been taken out before the nets were cut
    assert any("客体" in n for n in nets["notes"]), nets["notes"]


@pytest.mark.parametrize("slug", sorted(CASES))
def test_node_connectivity_histogram(bench, slug):
    """Zn4O 6-c / Cu2 paddlewheel 4-c + btc 3-c / Zn 4-c / Zr6 12-c."""
    want = CASES[slug]
    net = bench(slug, pores=False)["topology"]["simplified_net"]
    assert net["node_connectivity_histogram"] == want["hist"]
    # a link counted twice would be invisible in the histogram alone
    assert net["n_parallel_edges"] == 0


@pytest.mark.skipif(not HAVE_SYSTRE,
                    reason="needs vendor/gavrog/*.jar and java on PATH")
@pytest.mark.parametrize("slug", sorted(CASES))
def test_systre_names_the_net(bench, slug):
    """Systre, on OUR quotient graph, must reach the published symbol."""
    want = CASES[slug]
    net = bench(slug, pores=False)["topology"]["simplified_net"]
    assert net["rcsr_symbol"] == want["symbol"], net["rcsr_status"]
    # one symbol per connected component: interpenetration gives two
    assert net["rcsr_symbols"] == [want["symbol"]] * want["n_nets"]
    assert "systre_error" not in net


# ------------------------------------------------------------------ pores --

@pytest.mark.parametrize("slug", [s for s in sorted(CASES)
                                  if CASES[s]["lcd"] is not None])
def test_lcd_and_pld_match_the_literature(bench, slug):
    want = CASES[slug]
    void = _main_void(bench(slug)["pores"])
    assert abs(void["lcd_A"] - want["lcd"]) <= LCD_TOL, (
        f"{slug} LCD {void['lcd_A']} vs CoRE MOF 2019 {want['core_row']} "
        f"{want['lcd']} ({want['lit']})")
    assert void["pld_A"] is not None
    assert abs(void["pld_A"] - want["pld"]) <= PLD_TOL, (
        f"{slug} PLD {void['pld_A']} +- {void['pld_error_A']} vs CoRE MOF "
        f"2019 {want['core_row']} {want['pld']} ({want['lit']})")


@pytest.mark.parametrize("slug", sorted(CASES))
def test_channel_dimensionality(bench, slug):
    """All five are 3-D pore networks running along all three axes."""
    void = _main_void(bench(slug)["pores"])
    assert void["dimensionality"] == CASES[slug]["pore_dim"]
    assert len(void["directions"]) == CASES[slug]["pore_dim"]
    assert int(np.linalg.matrix_rank(np.array(void["directions"], float))) \
        == CASES[slug]["pore_dim"]


def test_mof5_pore_geometry_reproduces_the_nature_1999_distances():
    """The 1999 paper prints the distances, not just the diameters, so the
    expected answer can be recomputed in OUR radii instead of trusting a
    diameter measured in someone else's.

    Nature 402 (1999) 276, p. 279: the large cavity centre has 72 C at
    9.26 A and 48 H at 9.47 A; the aperture has 8 C at 5.70 A and 8 H at
    5.10 A. With cctbx radii (C 1.775, H 1.20) that is LCD = 14.97 A and
    PLD = 7.80 A - the paper's own 15.1 / 8.0 come from r(C) = 1.70.
    """
    from cctbx.eltbx import van_der_waals_radii as vdw
    r_c = float(vdw.vdw.table["C"])
    r_h = float(vdw.vdw.table["H"])
    assert round(2 * min(9.26 - r_c, 9.47 - r_h), 2) == 14.97
    assert round(2 * min(5.70 - r_c, 5.10 - r_h), 2) == 7.80


# ------------------------------- synthetic interpenetration control -------

def test_mof5_plus_a_shifted_copy_is_interpenetration_by_translation(
        bench, tmp_path):
    """MOF-5 alone is one net; MOF-5 + a copy of itself is two, related by
    the translation that made the copy.

    The shift is (1/4, 1/4, 1/4), NOT (1/2, 1/2, 1/2): MOF-5 is F-centred,
    so (1/2,1/2,1/2) = (1/2,1/2,0) + (0,0,1/2) is (0,0,1/2) modulo the
    lattice and maps the structure back onto ITSELF (measured closest
    approach between the two copies: 0.000 A) - the "copy" would be the
    same atoms written twice, which is one net, not two. At (1/4,1/4,1/4) -
    half the body diagonal of the pcu cube, which is how real
    doubly-interpenetrated MOF-5 sits - the closest approach is 3.67 A, far
    outside every bonding criterion, so the two nets thread without
    touching.
    """
    from cctbx import crystal, xray

    from crystalpilot.chem.topology import independent_nets, simplified_net

    alone = bench("MOF-5_IRMOF-1", pores=False)
    assert alone["topology"]["nets"]["n_nets"] == 1
    assert alone["topology"]["nets"]["interpenetrated"] is False

    p1 = alone["xs"].expand_to_p1()
    cs = crystal.symmetry(unit_cell=p1.unit_cell().parameters(),
                          space_group_symbol="P 1")
    doubled = xray.structure(crystal_symmetry=cs)
    for tag, off in (("A", (0.0, 0.0, 0.0)), ("B", (0.25, 0.25, 0.25))):
        for k, sc in enumerate(p1.scatterers(), start=1):
            el = str(sc.scattering_type).strip()
            doubled.add_scatterer(xray.scatterer(
                label=f"{el}{tag}{k}",
                site=tuple((np.array(sc.site) + np.array(off)) % 1.0),
                scattering_type=el, u=0.02))
    doubled.scattering_type_registry(table="it1992")

    nets = independent_nets(doubled)
    assert nets["n_nets"] == 2
    assert [n["dimensionality"] for n in nets["nets"]] == [3, 3]
    assert nets["symmetry_related"] is True
    # round-3 R5: the two pcu nets thread each other's square windows -
    # the ring test says so (closest approach 3.67 A, no bond between them)
    assert nets["interpenetrated"] is True
    assert nets["interpenetration_status"] == "tested"
    pair = nets["threading"]["pairs"][0]
    assert pair["status"] == "threaded" and pair["rule"] == ["metal_clusters", "metal_clusters"]
    assert pair["a_windows_threaded_by_b"] > 0
    assert nets["symmetry_related_1d"] is False
    assert [r["relation"] for r in nets["relations"]] == ["translation"]
    assert nets["relations"][0]["shift"] == [0.25, 0.25, 0.25]
    # two pcu nets: twice the nodes of one MOF-5 cell, all still 6-connected
    assert simplified_net(doubled)["node_connectivity_histogram"] == {6: 16}


# ------------------------------------- repo benchmarks (full product path) --

@pytest.mark.skipif(not (PUBLIC / "NU-1000_Zr_MOF" / "ref_cif.cif").exists(),
                    reason="NU-1000 benchmark not present")
def test_nu1000_through_the_whole_product(tmp_path):
    """The one case with reflection data, so `import_cif_model` accepts it
    and `scene.build_void_ccp4` can run: csq net, Zr6 node 8-connected.

    Mondloch, Bury, Fairen-Jimenez, ... Farha, Hupp, J. Am. Chem. Soc. 135
    (2013) 10294, DOI 10.1021/ja4050828: "Eight of the twelve octahedral
    edges are connected to TBAPy units", and the DFT pore-size distribution
    peaks at 12 A (triangular micropore) and 30 A (hexagonal mesopore). The
    30 A is an NLDFT pore width from the N2 isotherm, so it is compared
    loosely - only that the mesopore is resolved at tens of angstroms, not
    to +-0.6 A.
    """
    import json

    from crystalpilot.refine.analysis import topology_from_res
    from crystalpilot.refine.nodes import NodeStore
    from crystalpilot.refine.project import RefineProject
    from crystalpilot.refine.scene import build_void_ccp4

    src = PUBLIC / "NU-1000_Zr_MOF"
    d = tmp_path / "nu1000"
    d.mkdir()
    (d / "context.json").write_text(json.dumps({"chemistry": {}}),
                                    encoding="utf-8")
    proj = RefineProject(d)
    proj.open()
    r = proj.invoke_tool("import_cif_model", {
        "cif_path": str(src / "ref_cif.cif"),
        "hkl_path": str(src / "sf.cif")})
    assert r.ok, r.error

    res = NodeStore(d).node_dir("n0000") / "model.res"
    top = topology_from_res(res)
    assert top["nets"]["n_nets"] == 1
    assert top["nets"]["nets"][0]["dimensionality"] == 3
    assert top["nets"]["interpenetrated"] is False
    net = top["simplified_net"]
    # 3 Zr6 nodes 8-connected + 6 tetratopic pyrene linkers 4-connected
    assert net["node_connectivity_histogram"] == {8: 3, 4: 6}
    if HAVE_SYSTRE:
        assert net["rcsr_symbol"] == "csq", net["rcsr_status"]

    info = build_void_ccp4(d, "n0000", d / "voids.ccp4")
    assert info["n_voids"] >= 1
    void = max(info["voids"], key=lambda v: v["volume_A3"])
    assert void["dimensionality"] == 3
    assert 20.0 < void["lcd_A"] < 35.0, void        # the 30 A mesopore
    assert void["pld_A"] is not None and void["pld_A"] > 8.0


@pytest.mark.skipif(not (PUBLIC / "Zn3_2D_MOF" / "ref_cif.cif").exists(),
                    reason="Zn3 2-D benchmark not present")
def test_a_2d_mof_is_reported_2d_not_3d(tmp_path):
    """Dimensionality sanity in the other direction: COD 2100591 is a
    layered (2-D) Zn3 framework, and its host net must come out dim 2 with
    the DMF/solvent fragments taken out first."""
    import json

    from crystalpilot.refine.analysis import topology_from_res
    from crystalpilot.refine.nodes import NodeStore
    from crystalpilot.refine.project import RefineProject

    src = PUBLIC / "Zn3_2D_MOF"
    d = tmp_path / "zn3"
    d.mkdir()
    (d / "context.json").write_text(json.dumps({"chemistry": {}}),
                                    encoding="utf-8")
    proj = RefineProject(d)
    proj.open()
    r = proj.invoke_tool("import_cif_model", {
        "cif_path": str(src / "ref_cif.cif"),
        "hkl_path": str(src / "sf.cif")})
    assert r.ok, r.error
    top = topology_from_res(NodeStore(d).node_dir("n0000") / "model.res")
    assert top["nets"]["n_nets"] == 1
    assert top["nets"]["nets"][0]["dimensionality"] == 2
    assert top["nets"]["interpenetrated"] is False


# ------------------------------------------- regressions for the bugs found

class TestSystreBridgeRegressions:
    """Three failures the known-answer run exposed, each fixed generically
    and pinned here on SYNTHETIC input - canned Systre text and a two-node
    fixture, so nothing depends on a downloaded crystal."""

    def test_a_parallel_link_is_written_once(self):
        """Gavrog's EDGES list is a SET: repeating `u v du dv dw` aborts the
        WHOLE file with `IllegalArgumentException: duplicate edge`, so every
        structure in it is lost. Found on a Mn-terephthalate rod MOF whose
        two carboxylates bridge the same pair of rods with the same lattice
        shift (COD 2204276) - Systre could not read our .cgd at all."""
        from crystalpilot.chem.topology import write_cgd
        net = {"edges": [[1, 2, [0, 0, 0]], [1, 2, [0, 0, 0]],
                         [1, 2, [1, 0, 0]], [2, 1, [-1, 0, 0]]]}
        text = write_cgd(net, "multi")
        body = [ln.strip() for ln in text.splitlines()[3:-1]]
        # existing order: vertex pair, then the first cell axis the edge
        # crosses (a shift of 0 0 0 crosses none, so it comes last)
        assert body == ["1 2 1 0 0", "1 2 0 0 0"], text
        # ...and `2 1 -1 0 0` is the SAME edge as `1 2 1 0 0`, so it went
        assert len(body) == len(set(body))

    def test_parallel_links_are_counted_not_hidden(self):
        """The histogram counts LINKS, the .cgd carries EDGES; when they
        differ the net says so instead of letting the two disagree."""
        from crystalpilot.chem.topology import simplified_net
        net = simplified_net(_double_linked_pair())
        assert net["n_edges_per_cell"] > net["n_simple_edges_per_cell"]
        assert net["n_parallel_edges"] == (net["n_edges_per_cell"]
                                           - net["n_simple_edges_per_cell"])
        assert "重边" in net["confidence"]

    def test_systre_errors_are_reported_not_swallowed(self):
        """`!!! ERROR (STRUCTURE) - ...` used to come back as the bland
        'no RCSR symbol in the output', hiding both Systre's reason and the
        fact that OUR .cgd was the problem."""
        from crystalpilot.chem.topology import _read_systre
        out = ("Structure #1 - \"crystalpilot_net\".\n"
               "!!! ERROR (STRUCTURE) - Structure has collisions between "
               "next-nearest neighbors. Systre does not currently support "
               "such structures..\n")
        assert parse_systre_error(out).startswith("STRUCTURE: Structure has")
        got = _read_systre(out)
        assert got["rcsr_symbol"] is None and got["rcsr_symbols"] == []
        assert "collisions" in got["rcsr_status"]
        assert got["systre_error"] == parse_systre_error(out)

    def test_a_net_systre_finished_but_could_not_name_is_not_a_failure(self):
        """'Structure is new for this run' is an ANSWER (the net is not in
        the RCSR archive), not a crash - the status must say which."""
        from crystalpilot.chem.topology import _read_systre
        out = ("   Coordination sequences:\n      Node 1:    4 12\n"
               "   Structure is new for this run.\n")
        got = _read_systre(out)
        assert got["rcsr_symbol"] is None and got["systre_error"] is None
        assert "不在 RCSR 档案里" in got["rcsr_status"]

    def test_every_component_of_a_disconnected_net_is_named(self):
        """An interpenetrated net makes Systre process the components
        separately; taking the FIRST 'Name:' silently threw the others away
        - two dia nets and a pcu net would have been reported as 'dia'."""
        from crystalpilot.chem.topology import _read_systre
        head = "Structure is not connected.\n   Processing components separately.\n"
        two_same = head + ("RCSR symbol:\n       Name:\t\tpcu\n" * 2)
        got = _read_systre(two_same)
        assert parse_systre_symbols(two_same) == ["pcu", "pcu"]
        assert got["rcsr_symbol"] == "pcu"
        assert "2 个分量" in got["rcsr_status"]
        mixed = (head + "RCSR symbol:\n       Name:\t\tdia\n"
                 + "RCSR symbol:\n       Name:\t\tpcu\n")
        got = _read_systre(mixed)
        assert got["rcsr_symbols"] == ["dia", "pcu"]
        assert got["rcsr_symbol"] is None       # no single answer to give
        assert "符号不同" in got["rcsr_status"]

    def test_the_gated_answers_all_have_the_same_shape(self):
        """A caller must never have to test whether a key is there."""
        from crystalpilot.chem.topology import (_read_systre,
                                                _systre_unavailable)
        keys = {"rcsr_symbol", "rcsr_symbols", "rcsr_status",
                "systre_error", "systre_output"}
        assert set(_systre_unavailable("未算（测试）")) == keys
        assert set(_read_systre("Structure is new for this run.")) == keys


class TestInscribedSphereRegressions:
    def test_a_finer_scan_never_gives_a_smaller_sphere(self):
        """`points[::k]` thinned a lexicographically ordered voxel list
        along its FASTEST axis only, so refining the grid could make the
        answer WORSE: UiO-66's octahedral cage measured 8.463 A on a
        0.288 A mask grid but 8.222 A on the finer 0.144 A grid, because
        the finer grid needed a 26x list stride and the cage centre fell
        between two sampled planes. Synthetic version of exactly that: one
        atom at the origin of a cubic cell, so R is largest at the body
        centre and the answer is known in closed form."""
        from cctbx import uctbx

        from crystalpilot.chem.pores import _vdw_radius, inscribed_sphere
        uc = uctbx.unit_cell((12.0, 12.0, 12.0, 90, 90, 90))
        atoms = np.array([[0.0, 0.0, 0.0]])
        exact = 12.0 * np.sqrt(3) / 2.0 - _vdw_radius("C")
        got = []
        for n in (24, 48, 96):
            ix, iy, iz = np.indices((n, n, n))
            pts = np.stack([ix, iy, iz], -1).reshape(-1, 3) / float(n)
            # budget forces thinning on every one of the three grids
            r = inscribed_sphere(pts, uc, atoms, ["C"], max_points=4000)
            got.append(r["radius_A"])
            assert r["centre_frac"] == [0.5, 0.5, 0.5], (n, r)
            assert abs(r["radius_A"] - exact) < 12.0 / n
            assert r["exact"] is True and r["stride"] == 1
            assert r["bins_per_axis"] > 0 and r["n_points"] == n ** 3
        assert got == sorted(got), (
            f"radius must not fall as the grid is refined: {got}")

    def test_no_thinning_below_the_budget(self):
        from cctbx import uctbx

        from crystalpilot.chem.pores import inscribed_sphere
        uc = uctbx.unit_cell((10.0, 10.0, 10.0, 90, 90, 90))
        pts = np.array([[0.5, 0.5, 0.5], [0.1, 0.1, 0.1]])
        r = inscribed_sphere(pts, uc, np.array([[0.0, 0.0, 0.0]]), ["C"])
        assert r["bins_per_axis"] == 0 and r["n_scanned"] == 2
        assert r["centre_frac"] == [0.5, 0.5, 0.5]


def _double_linked_pair():
    """Two metals bridged TWICE by the same kind of three-atom linker: the
    smallest net with a parallel link.

    Geometry (Cartesian, 20 A cubic P1 cell so no image is in range):
    Zn1 (0,0,0) and Zn2 (6,0,0), joined by O-C-O bridges at y = +-1.4.
    Zn-O = 1.98 A (inside `chem.bonding`'s Zn-O window), O-C = 1.79 A
    (inside C+O covalent + 0.45), and every other pair is out of range - so
    no bridging atom touches two metals (which would fold it into the
    cluster instead) and the two bridges stay two separate linkers, each
    contracting to an edge between the same pair of nodes with the same
    lattice shift. Element-generic: nothing here is tuned to a real crystal.
    """
    from cctbx import crystal, xray
    a = 20.0
    cs = crystal.symmetry(unit_cell=(a, a, a, 90, 90, 90),
                          space_group_symbol="P 1")
    xs = xray.structure(crystal_symmetry=cs)
    cart = [("Zn1", "Zn", (0.0, 0.0, 0.0)), ("Zn2", "Zn", (6.0, 0.0, 0.0))]
    for tag, sign in (("A", 1.0), ("B", -1.0)):
        cart += [(f"O1{tag}", "O", (1.4, sign * 1.4, 0.0)),
                 (f"C1{tag}", "C", (3.0, sign * 2.2, 0.0)),
                 (f"O2{tag}", "O", (4.6, sign * 1.4, 0.0))]
    for label, el, xyz in cart:
        xs.add_scatterer(xray.scatterer(
            label=label, site=tuple(v / a for v in xyz),
            scattering_type=el, u=0.02))
    xs.scattering_type_registry(table="it1992")
    return xs


# --------------------------------------------------------------------------
# round-3 R5-F: a real helical chain (COD 4115425)
# --------------------------------------------------------------------------

def test_helix_known_answer_cod4115425(tmp_path):
    """Yamaguchi, Yamazaki & Ito, J. Am. Chem. Soc. 123 (2001) 743, COD
    4115425: an infinite Pt->Ag metal-metal bonded chain in P6(1), c =
    41.608 (2) A. In that space group a chain along c that is one
    fragment per cell can only be a 6_1 helix: right-handed, pitch = c,
    no left-handed partner (P6(1) has no improper operation). The engine
    has to see one 1-D fragment and read exactly that off the group."""
    cif = KNOWN / "helix_ptag_chain_cod4115425" / "ref.cif"
    if not cif.exists():
        pytest.skip("COD 4115425 not present")
    out = _analyse(_cif_to_res(cif, tmp_path / "helix.res"), pores=False)
    topo = out["topology"]
    nets = topo["nets"]
    assert nets["n_nets"] == 1 and nets["nets"][0]["dimensionality"] == 1
    hel = topo["helices"]
    assert len(hel) == 1, hel
    h = hel[0]
    assert h["screw"] == "6_1" and h["order"] == 6
    assert h["handedness"] == "right" and h["racemic"] is False
    assert h["axis_direction"] == [0, 0, 1] == h["chain_direction"]
    assert abs(h["pitch_A"] - 41.608) <= 0.01
    assert h["pitch_A"] == h["axis_repeat_A"]
    # both metals of the asymmetric unit ride on the same chain
    assert {"PT1", "PT2", "AG1", "AG2"} <= {str(x).upper() for x in h["asu_labels"]}
