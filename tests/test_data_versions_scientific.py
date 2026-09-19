"""Real public-source refinement checks; no model calls or external-project mutation."""
from pathlib import Path

import pytest

from crystalpilot.refine.project import RefineProject

PUBLIC = Path(__file__).resolve().parents[1] / "benchmark" / "public"


def _import(tmp_path, name, *, sf=False):
    directory = tmp_path / "project"
    directory.mkdir()
    p = RefineProject(directory)
    p.open()
    params = {"cif_path": str(PUBLIC / name / "ref_cif.cif")}
    if sf:
        params["hkl_path"] = str(PUBLIC / name / "sf.cif")
    result = p.invoke_tool("import_cif_model", params)
    assert result.ok, result.error
    return p


def _shelxl(p, cycles=0, mode="adopt"):
    result = p.invoke_tool("run_shelxl", {"l_s": cycles, "mode": mode})
    assert result.ok, result.error
    return result.summary["shelxl"]


def test_real_sucrose_different_data_returns_to_original_metrics(tmp_path):
    from crystalpilot.io.cif_sf import load_cif_sf_dataset, write_hklf4
    p = _import(tmp_path, "sucrose")
    original = p.hkl_path.read_bytes()
    metrics_a = _shelxl(p)
    assert metrics_a["r1_strong"] == pytest.approx(.0411, abs=.0001)
    node_a = p.nodes.state()["active_node"]
    revision_a = p.nodes.state()["active_data_revision"]
    ds = load_cif_sf_dataset(PUBLIC / "sucrose" / "sf.cif", ref_cif_path=PUBLIC / "sucrose" / "ref_cif.cif")
    other = p.dir / "published.hkl"
    write_hklf4(ds.intensities, other)
    replacement = other.read_bytes()
    result = p.invoke_tool("swap_reflection_data", {"hkl": other.name, "reason": "explicit published SF scale contrast"})
    assert result.ok, result.error
    assert p.hkl_path.read_bytes() == replacement
    metrics_b = _shelxl(p)
    assert abs(metrics_b["r1_strong"] - metrics_a["r1_strong"]) > .1
    node_b = p.nodes.state()["active_node"]
    assert p.nodes.comparison(node_b, node_a)["metrics"]["r1"]["status"] == "different"
    p.checkout(node_a)
    assert p.hkl_path.read_bytes() == original
    assert (p.dir / "crystal.hkl").read_bytes() == original
    assert p.nodes.state()["active_data_revision"] == revision_a
    replay = _shelxl(p, mode="check")
    for metric in ("r1_strong", "wr2", "goof"):
        assert replay[metric] == pytest.approx(metrics_a[metric], abs=.0001)
    q = RefineProject(p.dir)
    q.open()
    assert q.hkl_path.read_bytes() == original
    assert q.session.dataset.wavelength == p.session.dataset.wavelength


def test_real_cubtc_measurement_and_bound_replay(tmp_path):
    p = _import(tmp_path, "CuBTC_framework", sf=True)
    original = p.hkl_path.read_bytes()
    measured = _shelxl(p, cycles=4)
    assert measured["r1_strong"] == pytest.approx(.0244, abs=.0005)
    node = p.nodes.state()["active_node"]
    source = p.nodes.comparison(node, node)["sources"]["node"]
    assert source["metrics_current"] and source["data_binding"] == "bound"
    assert source["metrics_source"]["engine"] == "SHELXL"
    assert p.hkl_path.read_bytes() == original
    q = RefineProject(p.dir)
    q.open()
    repeated = _shelxl(q, mode="check")
    assert repeated["r1_strong"] == pytest.approx(measured["r1_strong"], abs=.0001)


def test_real_import_return_restores_experiment_without_rewriting_notes(tmp_path):
    import json
    from crystalpilot.refine.nodes import atomic_write_json
    from crystalpilot.refine.specialist_snapshot import create_snapshot
    p = _import(tmp_path, "sucrose")
    measured = _shelxl(p)
    node_a = p.nodes.state()["active_node"]
    revision_a = p.nodes.state()["active_data_revision"]
    meta_a = p.nodes.node_meta(node_a)
    assert meta_a["experiment"]["temperature_K"] == 298.0
    used_temp = meta_a["comparison_conditions"]["experiment"]["temperature_K"]
    assert used_temp == pytest.approx(298.05, abs=.001)
    notes = p.invoke_tool("set_experiment", {"experiment": {"temperature_K": 310},
        "provenance": "later user correction, not an old calculation"})
    assert notes.ok, notes.error
    assert p.experiment()["temperature_K"] == 310
    context = {**p.context, "chemistry": {"note": "retain latest user prior"}}
    atomic_write_json(p.dir / "context.json", context)
    p.context = context
    settings = p.dir / ".crystalpilot-workbench.json"
    settings.write_text(json.dumps({"settings": {"model_override": "test-only-model", "effort_override": "xhigh"}}), encoding="utf-8")
    settings_bytes = settings.read_bytes()
    result = p.invoke_tool("import_cif_model", {"cif_path": str(PUBLIC / "CuBTC_framework" / "ref_cif.cif"),
        "hkl_path": str(PUBLIC / "CuBTC_framework" / "sf.cif")})
    assert result.ok, result.error
    node_b = p.nodes.state()["active_node"]
    assert p.experiment()["temperature_K"] == 293.0
    snapshot = create_snapshot(p, tmp_path / "historical-experiment", ref=node_a)
    snapshot_context = json.loads((snapshot.directory / "context.json").read_text(encoding="utf-8"))
    assert snapshot_context["experiment"]["temperature_K"] == used_temp
    p.checkout(node_a)
    assert p.experiment()["temperature_K"] == 298.0
    assert p.nodes.state()["working_experiments"][revision_a]["temperature_K"] == 310
    assert p.context["chemistry"] == {"note": "retain latest user prior"}
    assert settings.read_bytes() == settings_bytes
    replay = _shelxl(p, mode="check")
    assert replay["r1_strong"] == measured["r1_strong"] == .0411
    assert p.nodes.node_meta(node_a) == meta_a
    removed = p.invoke_tool("set_experiment", {"experiment": {"temperature_K": None},
        "provenance": "user now declares temperature unknown"})
    assert removed.ok, removed.error
    assert "temperature_K" not in p.experiment()
    p.checkout(node_a)
    assert p.experiment()["temperature_K"] == 298.0
    assert "temperature_K" not in p.nodes.state()["working_experiments"][revision_a]
    p.checkout(node_b)
    p.checkout(node_a)
    assert "temperature_K" not in p.nodes.state()["working_experiments"][revision_a]
    assert p.nodes.node_meta(node_a) == meta_a
    assert settings.read_bytes() == settings_bytes


def test_hklf5_batch_bytes_and_mask_interpretation_roundtrip(tmp_path):
    from tests.test_data_versions import _project
    from tests.test_swap_data import _write_hklf5
    from cctbx.array_family import flex
    from cctbx import miller
    p = _project(tmp_path)
    flags = p.session.flags
    flags["weights"] = {"a": .12, "b": .5}
    flags["data_cards"] = ["SHEL 999 1.200", "OMIT -2 1"]
    flags["f_mask"] = miller.array(p.session.fo_sq.set(), data=flex.complex_double(p.session.fo_sq.size(), complex(.2, .1)))
    flags["solvent_mask_params"] = {"solvent_radius": 1.2}
    mask_values = list(flags["f_mask"].data())
    node_a = p.nodes.commit(p.session, tool="solvent_mask", params={})["id"]
    original = p.hkl_path.read_bytes()
    twin = p.dir / "twin.hkl"
    _write_hklf5(twin, p.session.fo_sq, 40)
    twin.write_bytes(twin.read_bytes().replace(b"\n", b"\r\n") + b"REM preserved trailer\r\n")
    twin_bytes = twin.read_bytes()
    result = p.invoke_tool("swap_reflection_data", {"hkl": twin.name, "reason": "explicit twin observation set"})
    assert result.ok, result.error
    node_b = p.nodes.state()["active_node"]
    assert p.hkl_path.read_bytes() == twin_bytes
    assert p.session.flags["hklf"] == 5 and "f_mask" not in p.session.flags
    p.checkout(node_a)
    assert p.hkl_path.read_bytes() == original
    assert list(p.session.flags["f_mask"].data()) == mask_values
    assert p.session.flags["weights"] == {"a": .12, "b": .5}
    assert p.session.flags["data_cards"] == ["SHEL 999 1.200", "OMIT -2 1"]
    p.checkout(node_b)
    assert p.hkl_path.read_bytes() == twin_bytes
    assert p.session.flags["hklf"] == 5
