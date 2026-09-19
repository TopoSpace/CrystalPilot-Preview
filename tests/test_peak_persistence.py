"""Peak tables travel with the node; checkout is a few file reads.

pa1 (32 runs): `add_atoms_from_difference_map(peak_indices=...)` failed 7x
with "no stored difference-map peaks - refine first" and `interpret_peaks`
4x with "no peaks available" - every time right after a branch/checkout,
which rebuilt the session without the tables (hex-l2-r1 3:53, cu-l1-r2
6:40, cage-l2-r1 5:22 ...). The remedy the messages suggested was the
dearest one (a re-refine, a 12-50 s charge-flipping re-run) while
inspect_map rebuilds the table in ~1-2 s. And every checkout/branch (730
of them) re-parsed the reflection file and re-merged it: 0.65 s of the
0.75 s a switch cost on the 337k-row MOF data.
"""
from __future__ import annotations

import json
import os
import textwrap
from pathlib import Path

import pytest
from cctbx import crystal, xray

O3_SITE = (0.40, 0.58, 0.40)     # the atom the start model omits


def _full_structure():
    """Hollow cube of 8 C with three 'solvent' O inside, P1."""
    cs = crystal.symmetry(unit_cell=(11.0, 11.0, 11.0, 90, 90, 90),
                          space_group_symbol="P 1")
    full = xray.structure(crystal_symmetry=cs)
    i = 0
    for x in (0.08, 0.92):
        for y in (0.08, 0.92):
            for z in (0.08, 0.92):
                i += 1
                full.add_scatterer(xray.scatterer(
                    label=f"C{i}", site=(x, y, z), scattering_type="C",
                    u=0.03))
    for k, site in enumerate(((0.5, 0.5, 0.5), (0.5, 0.5, 0.62), O3_SITE)):
        full.add_scatterer(xray.scatterer(
            label=f"O{k + 1}", site=site, scattering_type="O", u=0.08))
    full.scattering_type_registry(table="it1992")
    return full


def synthetic_project(root: Path) -> Path:
    """A project whose data are the full structure's Fc^2 and whose start
    model omits O3 - so the difference map has exactly one honest peak."""
    d = root / "proj"
    d.mkdir()
    full = _full_structure()
    fo_sq = full.structure_factors(d_min=0.9).f_calc().intensities()
    lines = []
    for (h, k, l), i in zip(fo_sq.indices(), fo_sq.data()):
        lines.append(f"{h:4d}{k:4d}{l:4d}{i:8.2f}{max(1.0, 0.02 * i):8.2f}")
    lines.append(f"{0:4d}{0:4d}{0:4d}{0.0:8.2f}{0.0:8.2f}")
    (d / "crystal.hkl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    atoms = []
    for sc in full.scatterers():
        if sc.label == "O3":
            continue
        sfac = 1 if sc.scattering_type == "C" else 2
        x, y, z = sc.site
        atoms.append(f"{sc.label:5s}{sfac:2d} {x:9.5f} {y:9.5f} {z:9.5f} "
                     f"11.00000 {sc.u_iso:8.5f}")
    (d / "start.res").write_text(textwrap.dedent("""\
        TITL synthetic hollow cube
        CELL 0.71073 11.0 11.0 11.0 90.0 90.0 90.0
        ZERR 1 0.001 0.001 0.001 0.0 0.0 0.0
        LATT -1
        SFAC C O
        UNIT 8 3
        FVAR 1.0
        WGHT 0.1
        """) + "\n".join(atoms) + "\nHKLF 4\nEND\n", encoding="utf-8")
    (d / "context.json").write_text(json.dumps({
        "data": {"hkl": "crystal.hkl", "start_model": "start.res"}}),
        encoding="utf-8")
    return d


@pytest.fixture()
def project(tmp_path):
    from crystalpilot.refine.project import RefineProject
    p = RefineProject(synthetic_project(tmp_path))
    opened = p.open()
    assert opened["node"] == "n0000" and opened["n_atoms"] == 10
    return p


def _dist(p, a, b) -> float:
    uc = p.session.model.unit_cell()
    return uc.distance(tuple(a), tuple(b))


class TestDiffMapPeaksPersist:
    def test_refine_saves_the_table_and_checkout_restores_it(self, project):
        p = project
        r = p.invoke_tool("refine", {"mode": "isotropic", "n_cycles": 3})
        assert r.ok, r.error
        n_ref = r.summary["node"]
        peaks = p.session.flags["diff_map_peaks"]
        assert peaks and _dist(p, peaks[0]["site"], O3_SITE) < 0.3, peaks[:3]
        # the table is on disk beside model.res and announced in node.json
        doc = json.loads(p.nodes.peaks_path(n_ref).read_text(encoding="utf-8"))
        assert doc["diff_map"]["source"] == "refine"
        assert doc["diff_map"]["computed_on"] == n_ref
        assert len(doc["diff_map"]["peaks"]) == len(peaks)
        assert p.nodes.node_meta(n_ref)["peaks"]["diff_map"]["n"] == len(peaks)
        assert p.session.flags["diff_map_peaks_meta"]["node"] == n_ref

        # a model edit carries the table forward, provenance intact
        r2 = p.invoke_tool("edit_atoms", {"operations": [
            {"action": "set_u_iso", "atoms": ["O1"], "u_iso": 0.05}]})
        assert r2.ok, r2.error
        n_edit = r2.summary["node"]
        assert p.nodes.node_meta(n_edit)["peaks"]["diff_map"]["computed_on"] \
            == n_ref

        # leave and come back: the table is there without any refinement
        out = p.checkout(n_ref)
        assert any("peak table restored" in n for n in out["notes"]), out
        assert out["peaks"]["diff_map"]["n"] == len(peaks)
        assert p.session.flags["diff_map_peaks"][0]["site"] == peaks[0]["site"]
        assert p.session.flags["diff_map_peaks_meta"]["source"] == "refine"
        assert p.session.flags["diff_map_peaks_meta"]["node"] == n_ref
        add = p.invoke_tool("add_atoms_from_difference_map",
                            {"peak_indices": [0], "element": "O"})
        assert add.ok, add.error
        assert len(add.summary["added"]) == 1
        assert add.summary["peak_table"] == {
            "n_peaks": len(peaks), "source": "refine", "computed_on": n_ref}
        new = [sc for sc in p.session.model.scatterers()
               if sc.label == add.summary["added"][0]["label"]][0]
        assert _dist(p, new.site, O3_SITE) < 0.3

    def test_checkout_via_the_tool_keeps_the_provenance(self, project):
        """The checkout/branch tools rebuild the session; the tables they
        restore must not be relabelled as 'computed by checkout'."""
        p = project
        r = p.invoke_tool("refine", {"mode": "isotropic", "n_cycles": 2})
        n_ref = r.summary["node"]
        p.invoke_tool("edit_atoms", {"operations": [
            {"action": "set_u_iso", "atoms": ["O1"], "u_iso": 0.05}]})
        n_edit = p.nodes.state()["active_node"]
        chk = p.invoke_tool("checkout", {"node": n_edit})
        assert chk.ok, chk.error
        assert "peak_table_saved" not in chk.summary
        assert p.session.flags["diff_map_peaks_meta"] == {
            "source": "refine", "node": n_ref,
            "max": r.summary["diff_map_max"], "min": r.summary["diff_map_min"]}
        doc = json.loads(p.nodes.peaks_path(n_edit).read_text(encoding="utf-8"))
        assert doc["diff_map"]["computed_on"] == n_ref
        br = p.invoke_tool("branch", {"name": "trial"})
        assert br.ok, br.error
        assert any("peak table restored" in n for n in br.summary["notes"])
        assert br.summary["peaks"]["diff_map"]["computed_on"] == n_ref

    def test_inspect_map_table_survives_a_branch(self, project):
        """The exact pa1 chain: inspect_map -> branch -> add_atoms(peak_indices)."""
        p = project
        im = p.invoke_tool("inspect_map", {"n_peaks": 5})
        assert im.ok, im.error
        assert im.summary["n_peaks_in_table"] == 5
        assert im.summary["peak_table"]["computed_on"] == "n0000"
        saved = im.summary["peak_table_saved"]
        assert saved["node"] == "n0000"
        assert saved["diff_map"] == {"n": 5, "source": "inspect_map",
                                     "computed_on": "n0000"}
        assert (p.dir / saved["file"]).exists()
        top = im.summary["peaks"][0]
        assert _dist(p, top["site"], O3_SITE) < 0.3
        # node.json learned about it although nothing was committed
        assert p.nodes.node_meta("n0000")["peaks"]["diff_map"]["n"] == 5
        assert p.nodes.list_nodes()["nodes"][0]["n_peaks"] == 5

        br = p.invoke_tool("branch", {"name": "trial"})
        assert br.ok, br.error
        add = p.invoke_tool("add_atoms_from_difference_map",
                            {"peak_indices": [top["i"]], "element": "O"})
        assert add.ok, add.error
        assert len(add.summary["added"]) == 1
        assert add.summary["peak_table"]["source"] == "inspect_map"

    def test_inspect_map_node_reads_the_stored_table_without_computing(
            self, project, monkeypatch):
        p = project
        r = p.invoke_tool("refine", {"mode": "isotropic", "n_cycles": 2})
        n_ref = r.summary["node"]
        live = p.session.flags["diff_map_peaks"]
        from crystalpilot.tools import refinement_tools

        def boom(*a, **k):
            raise AssertionError("map recomputed")
        monkeypatch.setattr(refinement_tools, "_difference_map_analysis", boom)
        st = p.invoke_tool("inspect_map", {"node": n_ref, "n_peaks": 3,
                                           "min_height": 0.0})
        assert st.ok, st.error
        assert st.summary["source"] == "stored"
        assert st.summary["computed_by"] == "refine"
        assert st.summary["computed_on"] == n_ref
        assert st.summary["n_peaks_shown"] == 3
        assert st.summary["n_peaks_in_table"] == len(live)
        assert st.summary["peaks"][0]["i"] == 0
        assert st.summary["peaks"][0]["site"] == live[0]["site"]
        assert st.summary["diff_map_max"] == r.summary["diff_map_max"]
        assert p.session.flags["diff_map_peaks"] is live     # untouched
        assert "peak_table_saved" not in st.summary
        # a branch name resolves too; an unknown ref is a clean failure
        p.nodes.branch("alt", from_ref=n_ref)
        assert p.invoke_tool("inspect_map", {"node": "alt"}).ok
        bad = p.invoke_tool("inspect_map", {"node": "n9999"})
        assert not bad.ok and "unknown node" in bad.error
        none = p.invoke_tool("inspect_map", {"node": "n0000"})
        assert not none.ok and "no stored difference-map peak table" in none.error

    def test_missing_table_messages_point_at_inspect_map(self, project):
        p = project
        add = p.invoke_tool("add_atoms_from_difference_map",
                            {"peak_indices": [0]})
        assert not add.ok
        assert "inspect_map" in add.error and "peaks.json" in add.error
        assert "refine first" not in add.error
        ip = p.invoke_tool("interpret_peaks", {})
        assert not ip.ok
        assert "inspect_map" in ip.error and "peaks.json" in ip.error
        assert "solve_charge_flipping" in ip.error


class TestChargeFlippingPeaksPersist:
    def test_solver_peaks_are_saved_and_come_back_on_checkout(self, project):
        """A solver commits no node, so its peak list is synced to the
        active node right after the call and restored by checkout."""
        from crystalpilot.tools.base import Tool, ToolResult
        p = project
        full = _full_structure()
        sites = [tuple(sc.site) for sc in full.scatterers()]
        heights = [30.0 if sc.scattering_type == "O" else 20.0
                   for sc in full.scatterers()]

        class FakeSolve(Tool):
            name = "solve_charge_flipping"

            def run(self, ctx, **params):
                ctx.session.cf_info = {"engine": "charge_flipping", "seed": 7,
                                       "peak_sites": list(sites),
                                       "peak_heights": list(heights)}
                return ToolResult(ok=True, summary={"n_peaks": len(sites)})

        p.registry.register(FakeSolve())
        r = p.invoke_tool("solve_charge_flipping", {})
        assert r.ok
        assert r.summary["peak_table_saved"]["charge_flipping"] == {
            "n": len(sites), "engine": "charge_flipping"}
        doc = json.loads(p.nodes.peaks_path("n0000").read_text(encoding="utf-8"))
        assert doc["charge_flipping"]["seed"] == 7
        assert len(doc["charge_flipping"]["peak_sites"]) == len(sites)
        assert "diff_map" not in doc

        out = p.checkout("n0000")
        assert any("charge_flipping peaks for interpret_peaks" in n
                   for n in out["notes"]), out["notes"]
        cf = p.session.cf_info
        assert cf["seed"] == 7 and cf["engine"] == "charge_flipping"
        assert cf["peak_sites"][0] == pytest.approx(sites[0])
        assert cf["peak_heights"] == heights
        ip = p.invoke_tool("interpret_peaks", {})
        assert ip.ok, ip.error

    def test_a_cleared_list_removes_the_file(self, project):
        p = project
        p.session.cf_info = {"peak_sites": [(0.1, 0.2, 0.3)],
                             "peak_heights": [5.0]}
        p.nodes.save_peaks("n0000", p.session)
        assert p.nodes.peaks_path("n0000").exists()
        p.session.cf_info = {}
        assert p.nodes.save_peaks("n0000", p.session) is None
        assert not p.nodes.peaks_path("n0000").exists()
        assert p.nodes.load_peaks("n0000") is None


class TestShelxlQPeaks:
    RES = textwrap.dedent("""\
        WGHT      0.2000      0.0000
        REM Highest difference peak  3.927,  deepest hole -1.749,  1-sigma level  0.240
        Q1    1   0.0958  0.2419  0.4306  11.00000  0.05    3.93
        Q2    1  -0.0943  0.3025  0.4271  11.00000  0.05    3.54
        Q3    1   0.2008  0.2405  0.4294  11.00000  0.05    2.50
        HKLF 4
        END
        """)

    def test_parse_q_peaks_reads_sites_heights_and_extremes(self):
        from crystalpilot.refine.tools_shelxl import parse_q_peaks
        q = parse_q_peaks(self.RES)
        assert q["sites"] == [(0.0958, 0.2419, 0.4306),
                              (-0.0943, 0.3025, 0.4271),
                              (0.2008, 0.2405, 0.4294)]
        assert q["heights"] == [3.93, 3.54, 2.50]
        assert q["max"] == 3.927 and q["min"] == -1.749
        empty = parse_q_peaks("TITL nothing\nHKLF 4\nEND\n")
        assert empty == {"sites": [], "heights": [], "max": None, "min": None}

    def test_annotated_rows_have_the_session_table_shape(self):
        from crystalpilot.tools.refinement_tools import annotate_peaks
        xs = _full_structure()
        rows = annotate_peaks(xs, [(0.41, 0.58, 0.40), (0.0, 0.0, 0.5)],
                              [3.0, 1.0])
        assert rows[0]["nearest_atom"] == "O3" and rows[0]["nearest_d"] < 0.2
        assert rows[0]["height"] == 3.0 and rows[0]["site"] == [0.41, 0.58, 0.4]
        assert rows[1]["nearest_atom"].startswith("C")


class TestCheckoutCache:
    def test_checkout_reuses_the_parsed_hkl_and_the_merge(
            self, tmp_path, monkeypatch):
        import crystalpilot.io.shelx as shelx_mod
        from crystalpilot.refine.project import RefineProject
        real_init = shelx_mod.hklf.reader.__init__
        calls: list[str] = []

        def counting(self, *a, **k):
            calls.append(k.get("file_name") or "?")
            return real_init(self, *a, **k)
        monkeypatch.setattr(shelx_mod.hklf.reader, "__init__", counting)
        p = RefineProject(synthetic_project(tmp_path))
        p.open()
        assert len(calls) == 1
        first = p.session.fo_sq
        stats = dict(p.merge_stats)
        for _ in range(3):
            out = p.checkout("n0000")
            assert out["merge"] == stats
        assert len(calls) == 1, "checkout re-parsed the reflection file"
        assert p.session.fo_sq is not first          # a copy, never shared
        assert p.session.fo_sq.size() == first.size()
        assert p.session.fo_sq.indices().all_eq(first.indices())
        assert p.session.merge_info == stats

        # the cached arrays are isolated from whatever a tool does in place
        d0 = p.session.fo_sq.data()[0]
        p.session.fo_sq.data()[0] = d0 + 1234.5
        p.checkout("n0000")
        assert p.session.fo_sq.data()[0] == pytest.approx(d0)

        # since 2026-09-08 the node reads its own immutable observation
        # revision, not the working alias: the import parsed the staged
        # input once and the published copy inherits that parse, and
        # touching crystal.hkl in the project folder changes nothing the
        # session reads (a new file arrives as a new revision, i.e. a new
        # path, through swap_reflection_data)
        assert Path(p.hkl_path).parent.parent.name == "data"
        assert Path(p.hkl_path).name == "observations.hkl"
        hkl = p.dir / "crystal.hkl"
        st = hkl.stat()
        os.utime(hkl, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
        p.checkout("n0000")
        assert len(calls) == 1

    def test_node_with_another_space_group_gets_its_own_merge(
            self, tmp_path):
        from crystalpilot.refine.project import RefineProject
        p = RefineProject(synthetic_project(tmp_path))
        p.open()
        n_p1 = p.session.fo_sq.size()
        # fabricate a node whose model.res declares P-1 (LATT 1): same
        # observations (bound to the parent's revision - an unbound node
        # gets geometry only), same cell, different group -> a different merge
        src = p.nodes.node_dir("n0000") / "model.res"
        text = src.read_text(encoding="utf-8").replace("LATT -1", "LATT 1")
        ndir = p.nodes.node_dir("n0001")
        ndir.mkdir()
        (ndir / "model.res").write_text(text, encoding="utf-8")
        (ndir / "node.json").write_text(json.dumps({
            "id": "n0001", "parent": "n0000", "branch": "main",
            "tool": "test", "params": {}, "metrics": None,
            "data_revision": p.nodes.node_meta("n0000")["data_revision"],
            "hydrogens": {"present": False}}), encoding="utf-8")
        out = p.checkout("n0001")
        assert out["merge"]["space_group"] == "P -1"
        assert p.session.fo_sq.space_group().order_z() == 2
        assert p.session.symmetry.space_group().order_z() == 2
        assert p.session.fo_sq.size() <= n_p1
        out = p.checkout("n0000")
        assert out["merge"]["space_group"] == "P 1"
        assert p.session.fo_sq.space_group().order_z() == 1
        assert p.session.fo_sq.size() == n_p1


@pytest.mark.filterwarnings("ignore")
def test_fofc_map_for_the_viewer_uses_the_mask_snapshot(tmp_path, monkeypatch):
    """build_fofc_ccp4 (web viewer) rebuilt the solvent mask from its
    parameters for every node it rendered - the same 70-138 s the
    checkout path no longer pays."""
    from crystalpilot.refine.project import RefineProject
    from crystalpilot.refine.scene import build_fofc_ccp4
    from crystalpilot.tools import mask_tools
    p = RefineProject(synthetic_project(tmp_path))
    p.open()
    m = p.invoke_tool("solvent_mask", {"max_cycles": 3})
    assert m.ok, m.error
    node = m.summary["node"]
    assert (p.nodes.node_dir(node) / "f_mask.pkl").exists()

    def boom(self, ctx, **params):
        raise AssertionError("solvent_mask recomputed for the viewer map")
    monkeypatch.setattr(mask_tools.SolventMask, "run", boom)
    out = build_fofc_ccp4(p.dir, node, tmp_path / "fofc.ccp4")
    assert out["masked"] is True and out["n_peaks"] >= 1
    assert (tmp_path / "peaks.json").exists()
