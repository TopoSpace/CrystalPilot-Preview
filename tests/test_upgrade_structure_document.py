"""CIF-only projects expose real geometry, never fabricated observations."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from crystalpilot.refine.project import ProjectError, RefineProject
from crystalpilot.refine.structure_document import load_structure_document

REPO = Path(__file__).resolve().parents[1]
CIF = """data_geometry
_cell_length_a 8
_cell_length_b 9
_cell_length_c 10
_cell_angle_alpha 85
_cell_angle_beta 95
_cell_angle_gamma 105
_cell_formula_units_Z 1
_space_group_name_H-M_alt 'P 1'
_refine_ls_R_factor_gt 0.042(1)
_refine_ls_wR_factor_ref 0.107
_refine_ls_goodness_of_fit_ref 1.012
_refine_diff_density_max 0.45
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_occupancy
_atom_site_U_iso_or_equiv
C1 C 0.96 0.2 0.3 1 0.025
O1 O 0.13 0.2 0.3 1 0.031
"""


@pytest.fixture
def cif_file(tmp_path):
    path = tmp_path / "published.cif"
    path.write_text(CIF, encoding="utf-8")
    return path


@pytest.fixture
def structure_project(tmp_path, cif_file):
    return RefineProject.create_structure_only(tmp_path / "project", cif_file)


def test_import_creates_real_node_without_data_or_calculated_metrics(structure_project, cif_file):
    p = structure_project
    assert p.structure_only
    assert p.session.dataset is None
    assert p.session.fo_sq is None
    assert p.hkl_path is None
    assert p.session.last_refinement() is None
    assert p.session.model.scatterers().size() == 2
    assert not list(p.dir.rglob("*.hkl"))
    meta = p.nodes.node_meta(p.nodes.state()["active_node"])
    source_state = {"node": meta["id"], "revision": 1, "data_revision": None}
    assert p.nodes.source_state() == source_state
    assert meta["metrics"] is None
    assert not meta["metrics_current"]
    assert meta["data"] is None
    assert meta["reported_reference"]["values"]["r1"] == "0.042(1)"
    assert (p.dir / "source.cif").read_text(encoding="utf-8") == CIF
    assert cif_file.read_text(encoding="utf-8") == CIF
    opened = RefineProject(p.dir)
    out = opened.open()
    assert out["read_only"] and out["mode"] == "structure_only"
    assert opened.session.dataset is None and opened.session.fo_sq is None
    assert opened.nodes.source_state() == source_state
    assert opened.nodes.state()["seq"] == 1
    assert out["metrics"] is None and not out["metrics_current"]
    assert out["reported_reference"]["status"] == "reported_reference"
    assert out["capabilities"]["geometry"]
    assert not out["capabilities"]["refinement"]
    assert list(opened.session.model.sites_frac())[0] == pytest.approx((.96, .2, .3), abs=1e-6)


def test_mode_polling_reads_only_persisted_metadata(structure_project, monkeypatch):
    import crystalpilot.refine.structure_document as documents
    p = structure_project
    before = p.nodes.state()

    def engine_must_not_run(*args, **kwargs):
        raise AssertionError("Polling must not parse a model or merge reflections")

    monkeypatch.setattr(RefineProject, "_build_session", engine_must_not_run)
    monkeypatch.setattr(documents, "load_structure_document", engine_must_not_run)
    info = documents.project_mode_info(p.dir)
    assert info["mode"] == "structure_only" and info["read_only"]
    assert info["source"] == "node"
    assert info["canonical_model"] == "model.cif"
    assert info["block_name"] == "geometry"
    assert p.nodes.node_meta(info["node"])["canonical_model"] == "model.cif"
    assert info["source_state"] == p.nodes.source_state()
    assert info["capabilities"] == p.nodes.node_meta(info["node"])["capabilities"]
    unopened = RefineProject(p.dir)
    assert unopened.session is None and unopened.structure_only
    assert unopened.capabilities == info["capabilities"]
    assert p.nodes.state() == before


def test_explicit_legacy_res_remains_canonical_and_preserves_mixed_case_parts(tmp_path):
    from crystalpilot.refine.scene import build_scene
    from crystalpilot.refine.structure_document import load_model_document, project_mode_info
    directory = tmp_path / "legacy-res"
    root = directory / ".crystalpilot" / "refine"
    node_dir = root / "nodes" / "n0000"
    node_dir.mkdir(parents=True)
    (directory / "context.json").write_text('{"mode":"structure_only"}', encoding="utf-8")
    (root / "state.json").write_text(json.dumps({
        "active_node": "n0000", "active_branch": "main", "seq": 1,
        "branches": {"main": "n0000"}}), encoding="utf-8")
    (node_dir / "node.json").write_text(json.dumps({
        "id": "n0000", "tool": "import_structure_only", "mode": "structure_only",
        "canonical_model": "model.res", "metrics": None,
        "model": {"n_atoms": 2, "reported_z": 1},
        "parts_extra": {"CA1": 1, "O1": 2}}), encoding="utf-8")
    text = ("TITL legacy\nCELL 0.71073 10 10 10 90 90 90\n"
            "ZERR 1 0 0 0 0 0 0\nLATT -1\nSFAC C O\nUNIT 1 1\n"
            "PART 1\nCa1 1 .1 .1 .1 11 .02\n"
            "PART 2\nO1 2 .22 .1 .1 11 .03\nPART 0\nHKLF 4\nEND\n")
    (node_dir / "model.res").write_text(text, encoding="utf-8")
    (node_dir / "model.cif").write_text("unusable legacy viewer copy", encoding="utf-8")
    parsed = load_model_document(node_dir / "model.cif")
    assert parsed.parts == {"CA1": 1, "O1": 2}
    project = RefineProject(directory)
    summary = project.open()
    assert summary["canonical_model"] == "model.res"
    assert project.session.flags["parts_extra"] == parsed.parts
    assert project_mode_info(directory)["source_state"] == {"node": "n0000", "revision": None, "data_revision": None}
    scene = build_scene(node_dir / "model.cif", polyhedra=False)
    assert not scene["bonds"]
    assert {a["label"]: a["part"] for a in scene["atoms"]} == parsed.parts
    assert (node_dir / "model.res").read_text(encoding="utf-8") == text


def test_empty_project_mode_has_no_model_capabilities(tmp_path):
    from crystalpilot.refine.structure_document import project_mode_info
    info = project_mode_info(tmp_path)
    assert info["mode"] == "awaiting_data"
    assert info["source_state"] == {"node": None, "revision": None, "data_revision": None}
    assert not any(info["capabilities"].values())


@pytest.mark.parametrize("suffix", [".res", ".ins", ".hkl"])
def test_instance_import_does_not_replace_existing_model_files(tmp_path, cif_file, suffix):
    directory = tmp_path / "existing"
    directory.mkdir()
    existing = directory / ("crystal" + suffix)
    existing.write_text("user-owned input", encoding="utf-8")
    p = RefineProject(directory)
    with pytest.raises(ProjectError, match="existing models/nodes/data"):
        p.import_structure_only(cif_file)
    assert existing.read_text(encoding="utf-8") == "user-owned input"
    assert p.nodes.state()["active_node"] is None


def test_model_geometry_symmetry_and_scene_consumers(structure_project):
    from crystalpilot.refine.scene import build_scene, cached_scene, cached_data_block
    p = structure_project
    node = p.nodes.state()["active_node"]
    for name in ("get_project_brief", "inspect_model", "get_geometry"):
        result = p.invoke_tool(name)
        assert result.ok, result.error
    symmetry = p.invoke_tool("check_symmetry", {"timeout_s": 0.1})
    assert symmetry.ok, symmetry.error
    path = p.nodes.node_dir(node) / "model.cif"
    assert not path.with_suffix(".res").exists()
    asu = build_scene(path, polyhedra=False)
    grown = build_scene(path, mode="grow", hops=1, polyhedra=False)
    packed = cached_scene(p.dir, node, mode="cell", n=2, hops=0,
                          polyhedra=False, diff=False, interactions=True)
    assert asu["meta"]["n_atoms"] == 2
    assert grown["meta"]["n_atoms"] > asu["meta"]["n_atoms"]
    assert grown["meta"]["n_bonds"] > 0
    assert packed["read_only"] and packed["capabilities"]["pack"]
    assert "interactions" in packed and "sym_elements" in packed
    assert cached_data_block(p.dir, node)["data"] is None


@pytest.mark.parametrize("tool", [
    "refine", "edit_atoms", "add_hydrogens", "run_shelxl", "solvent_mask",
    "inspect_map", "write_outputs", "change_space_group", "solve_superflip",
    "set_weights", "swap_reflection_data", "import_cif_model",
])
def test_read_only_gate_precedes_engine_calls(structure_project, tool):
    p = structure_project
    before = p.nodes.state()
    result = p.invoke_tool(tool)
    assert not result.ok
    assert "read-only structure-only" in result.error
    assert "hkl_path" in result.error
    assert p.nodes.state() == before
    assert p.session.model.scatterers().size() == 2
    with pytest.raises(ProjectError, match="read-only"):
        p.reload_inputs()


def test_residual_products_rejected_even_if_cache_exists(structure_project):
    from crystalpilot.refine.scene import cache_dir, cached_fofc, cached_peaks, build_fofc_ccp4
    p = structure_project
    node = p.nodes.state()["active_node"]
    cache = cache_dir(p.dir, node)
    cache.mkdir(parents=True, exist_ok=True)
    (cache / "fofc.ccp4").write_text("stale fixture", encoding="utf-8")
    (cache / "peaks.json").write_text('{"peaks": []}', encoding="utf-8")
    for call in (lambda: cached_fofc(p.dir, node), lambda: cached_peaks(p.dir, node),
                 lambda: build_fofc_ccp4(p.dir, node, cache / "new.ccp4")):
        with pytest.raises(ValueError, match="read-only"):
            call()
    assert not (cache / "new.ccp4").exists()


def test_geometric_pores_have_nullable_electrons(structure_project):
    from crystalpilot.refine.scene import cached_voids
    p = structure_project
    node = p.nodes.state()["active_node"]
    ccp4, metadata = cached_voids(p.dir, node)
    info = json.loads(metadata.read_text(encoding="utf-8"))
    assert info["mode"] == "geometric"
    assert info["electron_count_status"] == "unsupported"
    assert info["total_solvent_electrons_per_cell"] is None
    assert info["n_voids"] > 0
    assert all(v["electrons"] is None for v in info["voids"])
    assert any(v["volume_A3"] > 0 for v in info["voids"])
    assert all(not v["masked"] for v in info["voids"])
    # round-3 R5-D: percolating voids carry the PLD along each cell axis
    # (or a note saying why not); cavities carry neither
    for v in info["voids"]:
        if (v.get("dimensionality") or 0) >= 1:
            assert set(v.get("pld_along") or {}) == {"a", "b", "c"} or v.get("pld_along_note")
        else:
            assert "pld_along" not in v
    assert info["map"] and ccp4.exists()
    assert "f_mask" not in p.session.flags
    assert p.session.fo_sq is None
    ccp4.unlink()
    assert cached_voids(p.dir, node)[0].exists()


@pytest.mark.parametrize("style", ["absent_columns", "unknown_cells"])
def test_missing_adps_remain_unknown_after_reopen_and_in_scene(tmp_path, style):
    from crystalpilot.refine.scene import cache_dir, cached_scene
    from crystalpilot.refine.structure_document import project_mode_info
    if style == "absent_columns":
        text = CIF.replace("_atom_site_U_iso_or_equiv\n", "").replace(
            "1 0.025", "1").replace("1 0.031", "1")
    else:
        text = CIF.replace("1 0.025", "1 ?").replace("1 0.031", "1 .")
    source = tmp_path / "no-adps.cif"
    source.write_text(text, encoding="utf-8")
    assert load_structure_document(source).unknown_adp_labels == ["C1", "O1"]
    p = RefineProject.create_structure_only(tmp_path / "no-adps", source)
    reopened = RefineProject(p.dir)
    summary = reopened.open()
    assert summary["unknown_adp_labels"] == ["C1", "O1"]
    assert reopened.session.flags["unknown_adp_labels"] == ["C1", "O1"]
    assert all(sc.u_iso == 0 for sc in reopened.session.model.scatterers())
    assert p.nodes.node_meta(summary["node"])["unknown_adp_labels"] == ["C1", "O1"]
    assert project_mode_info(p.dir)["unknown_adp_labels"] == ["C1", "O1"]
    cache = cache_dir(p.dir, summary["node"])
    cache.mkdir(parents=True, exist_ok=True)
    (cache / "scene8_asu_n2_h0_p0_d0.json").write_text(
        '{"atoms": [{"label": "C1", "u_eq": 0}]}', encoding="utf-8")
    scene = cached_scene(p.dir, summary["node"], mode="asu", n=2, hops=0,
                         polyhedra=False, diff=False)
    assert len(scene["atoms"]) == 2
    assert all(a["adp_known"] is False and a["u_eq"] is None for a in scene["atoms"])
    assert all(a["adp_note"] == "ADP not reported" and "ell" not in a for a in scene["atoms"])
    assert source.read_text(encoding="utf-8") == text
    inspected = reopened.invoke_tool("inspect_model", {"detail": "atoms"})
    assert inspected.ok, inspected.error
    assert all(atom["u_eq"] is None and atom["adp_known"] is False
               for atom in inspected.summary["atoms"])
    assert not inspected.summary["suspects"]


def test_explicit_zero_adp_is_known_not_missing(tmp_path):
    from crystalpilot.refine.scene import build_scene
    source = tmp_path / "zero-adp.cif"
    source.write_text(CIF.replace("1 0.025", "1 0").replace("1 0.031", "1 ?"), encoding="utf-8")
    document = load_structure_document(source)
    assert document.unknown_adp_labels == ["O1"]
    scene = build_scene(source, polyhedra=False)
    atoms = {a["label"]: a for a in scene["atoms"]}
    assert atoms["C1"]["adp_known"] and atoms["C1"]["u_eq"] == 0
    assert not atoms["O1"]["adp_known"] and atoms["O1"]["u_eq"] is None


def test_reported_b_iso_counts_as_a_known_adp(tmp_path):
    import math
    source = tmp_path / "b-iso.cif"
    text = CIF.replace("_atom_site_U_iso_or_equiv", "_atom_site_B_iso_or_equiv")
    text = text.replace("1 0.025", f"1 {8 * math.pi ** 2 * .025:.12f}")
    text = text.replace("1 0.031", f"1 {8 * math.pi ** 2 * .031:.12f}")
    source.write_text(text, encoding="utf-8")
    document = load_structure_document(source)
    assert document.unknown_adp_labels == []
    assert [sc.u_iso for sc in document.structure.scatterers()] == pytest.approx([.025, .031])


@pytest.mark.parametrize("u33", ["0.031", "0", "?"])
def test_aniso_columns_distinguish_reported_values_from_unknown(tmp_path, u33):
    from crystalpilot.refine.scene import build_scene
    text = CIF.replace("_atom_site_U_iso_or_equiv\n", "").replace(
        "1 0.025", "1").replace("1 0.031", "1")
    text += ("\nloop_\n_atom_site_aniso_label\n"
             "_atom_site_aniso_U_11\n_atom_site_aniso_U_22\n_atom_site_aniso_U_33\n"
             "_atom_site_aniso_U_12\n_atom_site_aniso_U_13\n_atom_site_aniso_U_23\n"
             f"C1 0 0 {u33} 0 0 0\n")
    source = tmp_path / "only-aniso.cif"
    source.write_text(text, encoding="utf-8")
    document = load_structure_document(source)
    expected = ["C1", "O1"] if u33 == "?" else ["O1"]
    assert document.unknown_adp_labels == expected
    scene = build_scene(source, polyhedra=False)
    carbon = scene["atoms"][0]
    assert carbon["adp_known"] == (u33 != "?")
    assert (carbon["u_eq"] is None) == (u33 == "?")


def test_parser_preserves_zero_occupancy_labels_and_explicit_symmetry(tmp_path):
    path = tmp_path / "explicit.cif"
    path.write_text(CIF.replace("C1 C", "CarbonLong C").replace("1 0.025", "0 0.025")
                    + "\nloop_\n_space_group_symop_operation_xyz\n'x,y,z'\n'-x,-y,-z'\n",
                    encoding="utf-8")
    doc = load_structure_document(path)
    sc = doc.structure.scatterers()[0]
    assert sc.label == "CarbonLong"
    assert sc.occupancy == 0
    assert doc.structure.space_group().is_centric()


def test_disorder_aniso_and_long_labels_survive_restart_and_scene(tmp_path, monkeypatch):
    path = tmp_path / "aniso.cif"
    text = CIF.replace("C1 C", "CarbonLong C").replace("1 0.025", "0 0.025 1")
    text = text.replace("_atom_site_U_iso_or_equiv\n", "_atom_site_U_iso_or_equiv\n_atom_site_disorder_group\n")
    text = text.replace("1 0.031", "1 0.031 2")
    text += """\nloop_
_atom_site_aniso_label
_atom_site_aniso_U_11
_atom_site_aniso_U_22
_atom_site_aniso_U_33
_atom_site_aniso_U_12
_atom_site_aniso_U_13
_atom_site_aniso_U_23
CarbonLong 0.023 0.027 0.031 0.001 0.002 0.003
"""
    path.write_text(text, encoding="utf-8")
    p = RefineProject.create_structure_only(tmp_path / "aniso-project", path)
    restored = RefineProject(p.dir)
    summary = restored.open()
    assert summary["label_renames"] == {}
    label = "CarbonLong"
    sc = next(s for s in restored.session.model.scatterers() if s.label == label)
    assert sc.occupancy == 0 and sc.flags.use_u_aniso()
    from cctbx import adptbx
    assert adptbx.u_star_as_u_cif(restored.session.model.unit_cell(), sc.u_star) == pytest.approx(
        (0.023, 0.027, 0.031, 0.001, 0.002, 0.003), abs=1e-12)
    assert restored.session.flags["parts_extra"][label] == 1
    from crystalpilot.refine.structure_document import load_model_document
    model_path = restored.nodes.node_dir(summary["node"]) / "model.cif"
    parsed = load_model_document(model_path)
    assert parsed.parts == restored.session.flags["parts_extra"]
    assert parsed.parts[label] == 1
    assert not model_path.with_suffix(".res").exists()
    from crystalpilot.refine.scene import build_scene
    scene = build_scene(model_path, mode="grow", hops=1,
                        polyhedra=False, interactions=True)
    assert [a["label"] for a in scene["atoms"]] == ["CarbonLong", "O1"]
    assert not scene["bonds"]  # Different disorder PARTs must not bond.
    import crystalpilot.chem.guests as guests
    from crystalpilot.refine.analysis import AnalysisStages
    monkeypatch.setattr(guests, "locate_guests", lambda xs, **kwargs: kwargs)
    observed = AnalysisStages(p.dir, summary["node"]).compute("guests")
    assert observed["parts"] == parsed.parts
    assert path.read_text(encoding="utf-8") == text


def test_non_origin_inversion_survives_import_restart_and_scene(tmp_path, monkeypatch):
    path = tmp_path / "shifted.cif"
    text = CIF.replace("C1 C", "cArbonLong C")
    text += "\nloop_\n_space_group_symop_operation_xyz\n'x,y,z'\n'-x+1/2,-y,-z'\n"
    path.write_text(text, encoding="utf-8")
    document = load_structure_document(path)
    assert not document.structure.space_group().is_origin_centric()
    import crystalpilot.io.shelx_writer as writer

    def no_shelx_conversion(*args, **kwargs):
        raise AssertionError("Read-only CIF geometry must not require SHELX serialization")

    monkeypatch.setattr(writer, "write_res_text", no_shelx_conversion)
    p = RefineProject.create_structure_only(tmp_path / "shifted-project", path)
    reopened = RefineProject(p.dir)
    summary = reopened.open()
    model = reopened.session.model
    assert model.space_group() == document.structure.space_group()
    assert not model.space_group().is_origin_centric()
    assert [s.label for s in model.scatterers()] == ["cArbonLong", "O1"]
    assert list(model.sites_frac()) == list(document.structure.sites_frac())
    from crystalpilot.refine.scene import build_scene, cached_scene
    model_path = reopened.nodes.node_dir(summary["node"]) / "model.cif"
    asu = build_scene(model_path, polyhedra=False)
    cell = cached_scene(p.dir, summary["node"], mode="cell", n=2,
                        hops=0, polyhedra=False, diff=False)
    assert [a["label"] for a in asu["atoms"]] == ["cArbonLong", "O1"]
    assert cell["meta"]["n_atoms"] == 4
    assert not model_path.with_suffix(".res").exists()
    assert summary["canonical_model"] == "model.cif"
    assert summary["block_name"] == "geometry"
    assert path.read_text(encoding="utf-8") == text


def test_ddlm_and_metadata_blocks_are_read_without_rewriting(tmp_path):
    path = tmp_path / "ddlm.cif"
    text = "data_publication\n_journal_paper_doi '10.example/test'\n" + CIF
    text = text.replace("_cell_", "_cell.").replace("_atom_site_", "_atom_site.")
    path.write_text(text, encoding="utf-8")
    doc = load_structure_document(path)
    assert doc.block_name == "geometry"
    assert doc.structure.unit_cell().parameters()[0] == pytest.approx(8)
    assert path.read_text(encoding="utf-8") == text


def test_parser_requires_cell_symmetry_and_block_choice(tmp_path):
    path = tmp_path / "multi.cif"
    path.write_text(CIF + CIF.replace("data_geometry", "data_second"), encoding="utf-8")
    with pytest.raises(ValueError, match="block_name"):
        load_structure_document(path)
    assert load_structure_document(path, block_name="second").block_name == "second"
    path.write_text(CIF.replace("_cell_length_a 8\n", ""), encoding="utf-8")
    with pytest.raises(ValueError, match="six finite"):
        load_structure_document(path)
    path.write_text(CIF.replace("_space_group_name_H-M_alt 'P 1'\n", ""), encoding="utf-8")
    with pytest.raises(ValueError, match="P1 is not assumed"):
        load_structure_document(path)


def test_selected_block_is_the_canonical_node_not_the_whole_deposit(tmp_path):
    import gemmi
    from crystalpilot.refine.scene import build_scene
    source = tmp_path / "multi.cif"
    text = CIF + CIF.replace("data_geometry", "data_second").replace(
        "_cell_length_a 8", "_cell_length_a 12").replace("C1 C", "cArbonSecond C")
    source.write_text(text, encoding="utf-8")
    p = RefineProject.create_structure_only(tmp_path / "selected", source, block_name="second")
    node = p.nodes.state()["active_node"]
    meta = p.nodes.node_meta(node)
    model = p.nodes.node_dir(node) / "model.cif"
    assert [block.name for block in gemmi.cif.read_file(str(model))] == ["second"]
    assert meta["block_name"] == meta["params"]["data_block"] == "second"
    assert (p.dir / "source.cif").read_text(encoding="utf-8") == text
    reopened = RefineProject(p.dir)
    assert reopened.open()["block_name"] == "second"
    assert reopened.session.model.unit_cell().parameters()[0] == pytest.approx(12)
    scene = build_scene(model.with_suffix(".res"), polyhedra=False)
    assert scene["cell"]["a"] == pytest.approx(12)
    assert scene["atoms"][0]["label"] == "cArbonSecond"
    assert source.read_text(encoding="utf-8") == text


def test_explicit_tool_import_and_failed_attachment(tmp_path, cif_file):
    from crystalpilot.refine.tools_ingest import ImportCifModel
    from crystalpilot.refine.tools_analysis import ImportCifModel as ReexportedImport
    assert ReexportedImport is ImportCifModel
    assert "structure_only" in ImportCifModel.params_schema["properties"]
    directory = tmp_path / "tool_project"
    directory.mkdir()
    p = RefineProject(directory)
    p.open()
    result = p.invoke_tool("import_cif_model", {"cif_path": str(cif_file), "structure_only": True})
    assert result.ok, result.error
    before = p.nodes.state()
    failed = p.invoke_tool("import_cif_model", {
        "cif_path": str(cif_file), "hkl_path": str(tmp_path / "missing.hkl")})
    assert not failed.ok
    assert p.structure_only and p.context["mode"] == "structure_only"
    assert p.nodes.state() == before
    assert not (directory / "crystal.hkl").exists()


def test_explicit_existing_hkl_can_upgrade_structure_only(tmp_path):
    from crystalpilot.io.cif_sf import load_cif_sf_dataset, write_hklf4
    reference = REPO / "benchmark" / "public" / "sucrose" / "ref_cif.cif"
    p = RefineProject.create_structure_only(tmp_path / "attach-existing", reference)
    dataset = load_cif_sf_dataset(reference.with_name("sf.cif"), ref_cif_path=reference)
    write_hklf4(dataset.intensities, p.dir / "crystal.hkl")
    original = (p.dir / "crystal.hkl").read_bytes()
    result = p.invoke_tool("import_cif_model", {"cif_path": str(reference), "hkl_path": "crystal.hkl"})
    assert result.ok, result.error
    assert p.nodes.state()["active_data_revision"]
    assert p.hkl_path.read_bytes() == original
    assert not p.structure_only


def test_existing_cif_plus_real_reflections_and_explicit_upgrade(tmp_path):
    reference = REPO / "benchmark" / "public" / "paracetamol_formI" / "ref_cif.cif"
    reflections = reference.with_name("sf.cif")
    if not reference.exists() or not reflections.exists():
        pytest.skip("real small-molecule reflection fixture absent")
    p = RefineProject.create_structure_only(tmp_path / "attach", reference)
    old_node = p.nodes.state()["active_node"]
    result = p.invoke_tool("import_cif_model", {
        "cif_path": str(reference), "hkl_path": str(reflections)})
    assert result.ok, result.error
    assert not p.structure_only
    assert p.session.dataset is not None and p.session.fo_sq.size() > 0
    new_node = p.nodes.state()["active_node"]
    assert new_node != old_node
    assert p.nodes.source_state() == {"node": new_node, "revision": 2,
                                     "data_revision": p.nodes.node_meta(new_node)["data_revision"]}
    from crystalpilot.refine.structure_document import project_mode_info
    assert project_mode_info(p.dir)["mode"] == "refinement"
    assert project_mode_info(p.dir, old_node)["mode"] == "structure_only"
    assert not p.checkout(old_node)["capabilities"]["reflections"]
    assert p.nodes.source_state() == {"node": old_node, "revision": 1, "data_revision": None}
    assert p.context["mode"] == "refinement"
    assert project_mode_info(p.dir)["mode"] == "structure_only"
    assert RefineProject(p.dir).structure_only
    assert p.nodes.state()["seq"] == 2
    assert p.session.dataset is None
    fresh_dir = tmp_path / "legacy_import"
    fresh_dir.mkdir()
    fresh = RefineProject(fresh_dir)
    imported = fresh.invoke_tool("import_cif_model", {
        "cif_path": str(reference), "hkl_path": str(reflections)})
    assert imported.ok, imported.error
    assert fresh.session.fo_sq.size() > 0 and not fresh.structure_only


def test_real_framework_import_supports_geometry_and_topology(tmp_path):
    from crystalpilot.refine.analysis import topology_from_res, interactions_from_res
    reference = REPO / "benchmark" / "known_answers" / "ZIF-8" / "ref.cif"
    if not reference.exists():
        pytest.skip("known-answer ZIF-8 fixture absent")
    p = RefineProject.create_structure_only(tmp_path / "zif", reference)
    node = p.nodes.state()["active_node"]
    model = p.nodes.node_dir(node) / "model.cif"
    assert not model.with_suffix(".res").exists()
    original = load_structure_document(reference)
    assert [sc.label for sc in p.session.model.scatterers()] == [
        sc.label for sc in original.structure.scatterers()]
    assert p.session.model.space_group().type().number() == 217
    assert p.session.model.scatterers().size() == 9
    reopened = RefineProject(p.dir)
    reopened.open()
    assert [sc.label for sc in reopened.session.model.scatterers()] == [
        sc.label for sc in original.structure.scatterers()]
    from crystalpilot.refine.scene import build_scene
    scene = build_scene(model, polyhedra=False)
    assert [a["label"] for a in scene["atoms"]] == [
        sc.label for sc in original.structure.scatterers()]
    topology = topology_from_res(model, systre=False)
    assert [net["dimensionality"] for net in topology["nets"]["nets"]] == [3]
    assert topology["simplified_net"]["edges"]
    assert interactions_from_res(model)["h_source"] == "unknown"
    assert not list(p.dir.rglob("*.hkl"))


def test_create_refuses_nonempty_or_repository_directory(cif_file, tmp_path):
    with pytest.raises(ProjectError, match="outside"):
        RefineProject.create_structure_only(REPO / "forbidden-project", cif_file)
    target = tmp_path / "occupied"
    target.mkdir()
    (target / "user.txt").write_text("keep", encoding="utf-8")
    with pytest.raises(ProjectError, match="empty"):
        RefineProject.create_structure_only(target, cif_file)
    assert (target / "user.txt").read_text(encoding="utf-8") == "keep"
