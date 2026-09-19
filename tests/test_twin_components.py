"""Multi-component TWIN/BASF contracts and a real SHELXL regression.

All structures/reflections are generated in pytest's external temporary root;
no user project, reference structure or licensed binary is bundled here.
"""
from __future__ import annotations

import copy
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from cctbx import crystal, xray
from cctbx.array_family import flex

from crystalpilot.io.shelx_model import load_res_model
from crystalpilot.io.shelx_writer import ShelxModel, write_res, write_res_text
from crystalpilot.refine.nodes import disorder_from_parsed, serialization_extras
from crystalpilot.refine.tools_disorder import SetTwin

REPO = Path(__file__).resolve().parents[1]
SHELXL = Path(os.environ.get(
    "CRYSTALPILOT_SHELXL", str(REPO / "vendor" / "shelx" / "shelxl.exe")))
# Threefold rotation about [111] in a cubic metric: (h,k,l) -> (l,h,k).
THREEFOLD = [0, 0, 1, 1, 0, 0, 0, 1, 0]


def _model():
    xs = xray.structure(crystal_symmetry=crystal.symmetry(
        unit_cell=(10, 10, 10, 90, 90, 90), space_group_symbol="P 1"))
    for label, element, site in (
        ("C1", "C", (0.123, 0.234, 0.345)),
        ("C2", "C", (0.254, 0.284, 0.351)),
        ("O1", "O", (0.343, 0.213, 0.412)),
        ("N1", "N", (0.461, 0.682, 0.753)),
        ("C3", "C", (0.582, 0.721, 0.714)),
    ):
        xs.add_scatterer(xray.scatterer(
            label=label, scattering_type=element, site=site, u=0.03))
    return xs


@pytest.fixture
def session():
    return SimpleNamespace(model=_model(), flags={})


def _set(session, **params):
    return SetTwin(None).run(
        SimpleNamespace(session=session), law="matrix", matrix=THREEFOLD,
        **params)


@pytest.mark.parametrize("params", [{}, {"basf": 0.2}, {"basf": [0.2, 0.15]}])
def test_mcp_schema_accepts_scalar_and_per_component_fractions(params):
    import jsonschema
    jsonschema.validate(
        {"law": "matrix", "matrix": THREEFOLD, "n": 3, **params},
        SetTwin.params_schema)


@pytest.mark.parametrize("n,params,expected", [
    (2, {}, [0.3]),
    (2, {"basf": 0.2}, [0.2]),
    (3, {"basf": 0.2}, [0.2, 0.2]),
    (3, {"basf": [0.2, 0.15]}, [0.2, 0.15]),
    (3, {}, [1 / 3, 1 / 3]),
    (4, {}, [0.25, 0.25, 0.25]),
    (-6, {}, [1 / 6] * 5),
])
def test_component_fractions_survive_shelx_roundtrip(session, tmp_path,
                                                    n, params, expected):
    result = _set(session, n=n, **params)
    assert result.ok, result.error
    assert session.flags["twin"]["basf"] == pytest.approx(expected)
    write_res(ShelxModel(session.model, **serialization_extras(session.flags)),
              tmp_path / "model.res")
    parsed = load_res_model(tmp_path / "model.res")
    _, restored = disorder_from_parsed(parsed)
    assert restored["n"] == n
    assert restored["basf"] == pytest.approx(expected, abs=5e-6)


@pytest.mark.parametrize("params,message", [
    ({"n": 1}, "n"),
    ({"n": 0}, "n"),
    ({"n": 3.5}, "n"),
    ({"n": True}, "n"),
    ({"n": -3}, "n"),
    ({"n": 3, "basf": [0.2]}, "2 BASF"),
    ({"n": 3, "basf": [0.2, 0.2, 0.2]}, "2 BASF"),
    ({"n": 3, "basf": []}, "2 BASF"),
    ({"n": 3, "basf": [0.5, 0.5]}, "sum"),
    ({"n": 5, "basf": 0.3}, "sum"),
    ({"n": 3, "basf": [0.2, -0.1]}, "basf"),
    ({"n": 3, "basf": [0.2, 0]}, "basf"),
    ({"n": 3, "basf": [0.2, float("nan")]}, "basf"),
    ({"n": 3, "basf": float("inf")}, "basf"),
    ({"n": 3, "basf": True}, "basf"),
    ({"n": 3, "basf": "0.2"}, "basf"),
    ({"n": 2, "basf": 0.6}, "basf"),
    ({"n": 3, "basf": [0.499999, 0.5]}, "sum"),
])
def test_invalid_request_preserves_previous_twin(session, params, message):
    session.flags["twin"] = {"matrix": THREEFOLD, "n": 2, "basf": [0.2]}
    before = copy.deepcopy(session.flags)
    result = _set(session, **params)
    assert not result.ok
    assert message.lower() in result.error.lower()
    assert session.flags == before


def test_inversion_cannot_declare_three_domains(session):
    result = SetTwin(None).run(SimpleNamespace(session=session),
                               law="inversion", n=3)
    assert not result.ok and "n=2" in result.error
    assert session.flags == {}


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True])
def test_nonfinite_or_boolean_matrix_is_rejected(session, value):
    matrix = list(THREEFOLD)
    matrix[0] = value
    result = SetTwin(None).run(SimpleNamespace(session=session),
                               law="matrix", matrix=matrix, n=3)
    assert not result.ok and "finite numbers" in result.error
    assert session.flags == {}


def test_writer_refuses_legacy_wrong_basf_count(session):
    with pytest.raises(ValueError, match="2 BASF"):
        write_res_text(ShelxModel(session.model, twin={
            "matrix": THREEFOLD, "n": 3, "basf": [0.3]}))


@pytest.mark.parametrize("twin,expected", [
    # SHELXL permits a fixed equal-fraction TWIN without a BASF card.
    ({"matrix": THREEFOLD, "n": 3, "basf": []}, None),
    # HKLF5 batch scales are independent of the TWIN n default.
    ({"matrix": None, "n": 2, "basf": [0.2, 0.7]}, "BASF 0.20000 0.70000"),
    # Preserve refined out-of-range fractions for scientific diagnosis.
    ({"matrix": THREEFOLD, "n": 3, "basf": [-0.01, 0.2]},
     "BASF -0.01000 0.20000"),
])
def test_writer_preserves_valid_shelx_conventions(session, twin, expected):
    text, _ = write_res_text(ShelxModel(session.model, twin=twin))
    if expected:
        assert expected in text
    else:
        assert "BASF" not in text


def test_legacy_bad_state_stops_before_launch(session, monkeypatch):
    from crystalpilot.refine.tools_shelxl import RunShelxl
    session.flags["twin"] = {"matrix": THREEFOLD, "n": 3, "basf": [0.3]}
    before = copy.deepcopy(session.flags)
    tool = RunShelxl(SimpleNamespace())
    monkeypatch.setenv("CRYSTALPILOT_SHELXL", __file__)
    monkeypatch.setattr(tool, "_new_job_dir",
                        lambda: pytest.fail("invalid twin started a SHELXL job"))
    result = tool.run(SimpleNamespace(session=session))
    assert not result.ok
    assert "2 BASF" in result.error and "set_twin" in result.error
    assert session.flags == before


def _write_three_domain_project(directory):
    """Known 65:20:15 intensity mixture; coordinates have no threefold symmetry."""
    xs = _model()
    intensities = xs.structure_factors(
        d_min=1.2, anomalous_flag=False).f_calc().norm()
    lookup = {}
    for h, value in zip(intensities.indices(), intensities.data()):
        lookup[tuple(h)] = value
        lookup[tuple(-v for v in h)] = value
    mixed = flex.double([
        0.65 * lookup[(h, k, l)] + 0.2 * lookup[(l, h, k)]
        + 0.15 * lookup[(k, l, h)]
        for h, k, l in intensities.indices()
    ])
    observations = intensities.customized_copy(
        data=mixed, sigmas=flex.sqrt(mixed) + 1
    ).set_observation_type_xray_intensity()
    with (directory / "crystal.hkl").open("w") as stream:
        observations.export_as_shelx_hklf(file_object=stream)
    write_res(ShelxModel(xs, wavelength=0.71073), directory / "start.res")


def test_legacy_project_can_be_repaired_without_rewriting_history(tmp_path, monkeypatch):
    from crystalpilot.io import shelx_writer
    from crystalpilot.refine.project import RefineProject
    from crystalpilot.tools.base import ToolResult
    _write_three_domain_project(tmp_path)
    project = RefineProject(tmp_path)
    project.open()

    def legacy_set_twin(self, ctx, **params):
        ctx.session.flags["twin"] = {"matrix": THREEFOLD, "n": 3, "basf": [0.1]}
        return ToolResult(ok=True, summary={"twin": ctx.session.flags["twin"]})

    # Recreate the old release's persisted node through the real transaction.
    with monkeypatch.context() as old_release:
        old_release.setattr(SetTwin, "run", legacy_set_twin)
        old_release.setattr(shelx_writer, "twin_basf_error", lambda _: None)
        legacy = project.invoke_tool("set_twin", {"law": "matrix"})
    assert legacy.ok, legacy.error
    old_node = project.nodes.node_dir(legacy.summary["node"])
    original_files = {name: (old_node / name).read_bytes()
                      for name in ("model.res", "node.json")}

    reopened = RefineProject(tmp_path)
    reopened.open()
    monkeypatch.setenv("CRYSTALPILOT_SHELXL", __file__)
    refused = reopened.invoke_tool("run_shelxl", {"mode": "adopt"})
    assert not refused.ok and "2 BASF" in refused.error
    assert reopened.nodes.state()["active_node"] == legacy.summary["node"]
    repaired = reopened.invoke_tool("set_twin", {
        "law": "matrix", "matrix": THREEFOLD, "n": 3, "basf": [0.2, 0.15]})
    assert repaired.ok, repaired.error
    assert repaired.summary["node"] != legacy.summary["node"]
    assert reopened.session.flags["twin"]["basf"] == [0.2, 0.15]
    assert all((old_node / name).read_bytes() == value
               for name, value in original_files.items())


@pytest.mark.skipif(not SHELXL.exists(), reason="licensed SHELXL not installed")
def test_real_shelxl_three_domain_adopt_and_reopen(tmp_path, monkeypatch):
    from crystalpilot.refine.project import RefineProject
    monkeypatch.setenv("CRYSTALPILOT_SHELXL", str(SHELXL))
    _write_three_domain_project(tmp_path)
    project = RefineProject(tmp_path)
    project.open()
    set_result = project.invoke_tool("set_twin", {
        "law": "matrix", "matrix": THREEFOLD, "n": 3, "basf": 0.1})
    assert set_result.ok, set_result.error
    result = project.invoke_tool("run_shelxl", {"mode": "adopt", "l_s": 6})
    assert result.ok, result.error
    fractions = result.summary["twin_basf_refined"]
    assert fractions == pytest.approx([0.2, 0.15], abs=0.01)
    assert result.summary["shelxl"]["r1_strong"] < 0.01
    node = result.summary["node"]
    parsed = load_res_model(project.nodes.node_dir(node) / "model.res")
    assert parsed.twin["n"] == 3
    assert parsed.basf == pytest.approx(fractions, abs=1e-5)
    reopened = RefineProject(tmp_path)
    reopened.open()
    assert reopened.session.flags["twin"]["basf"] == pytest.approx(fractions)
