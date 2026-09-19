import copy

from tests.test_data_versions import _project, _inventory
from crystalpilot.refine.data_versions import DataVersions, compare_sources


def _refine(p):
    result = p.invoke_tool("refine", {"mode": "isotropic", "n_cycles": 1})
    assert result.ok, result.error
    return p.nodes.state()["active_node"]


def test_weight_changes_gate_weighted_metrics_not_r1(tmp_path):
    p = _project(tmp_path)
    a = _refine(p)
    result = p.invoke_tool("set_weights", {"a": .2, "b": .5})
    assert result.ok, result.error
    stale = p.nodes.state()["active_node"]
    comparison = p.nodes.comparison(stale, a)
    assert comparison["sources"]["node"]["metrics_source"]["node"] == a
    assert not comparison["sources"]["node"]["metrics_current"]
    assert comparison["metrics"]["r1"]["status"] == "unknown"
    b = _refine(p)
    comparison = p.nodes.comparison(b, a)
    assert comparison["metrics"]["r1"]["status"] == "comparable"
    assert comparison["metrics"]["wr2"] == {"status": "different", "reasons": ["weights_different"]}
    assert comparison["metrics"]["goof"]["status"] == "different"
    assert comparison["sources"]["node"]["metrics_source"]["node"] == b


def test_model_variables_are_disclosed_not_r1_gates(tmp_path):
    p = _project(tmp_path)
    a = _refine(p)
    result = p.invoke_tool("edit_atoms", {"operations": [{"action": "set_u_iso", "atoms": ["C1"], "u_iso": .06}]})
    assert result.ok, result.error
    b = _refine(p)
    actual = p.nodes.comparison(b, a)
    assert actual["metrics"]["r1"]["status"] == "comparable"
    left, right = copy.deepcopy(actual["sources"]["node"]), actual["sources"]["baseline"]
    left["conditions"]["hydrogens"] = {"treatment": "riding", "groups": [{"carrier": "C1"}]}
    left["conditions"]["scale"]["fitted_value"] = 77
    decision = compare_sources(left, right)
    assert decision["metrics"]["r1"]["status"] == "comparable"
    assert {row["field"] for row in decision["differences"]} >= {"hydrogens", "scale"}


def test_measurement_mask_usage_is_distinct_from_stored_mask(tmp_path, monkeypatch):
    from cctbx import miller
    from cctbx.array_family import flex
    p = _project(tmp_path)
    p.session.flags["f_mask"] = miller.array(p.session.fo_sq.set(),
        data=flex.complex_double(p.session.fo_sq.size(), complex(.02, .01)))
    p.session.flags["solvent_mask_params"] = {"solvent_radius": 1.2}
    result = p.invoke_tool("refine", {"mode": "isotropic", "n_cycles": 1,
        "use_solvent_mask": False, "refresh_mask": False})
    assert result.ok, result.error
    a = p.nodes.state()["active_node"]
    ca = p.nodes.node_meta(a)["comparison_conditions"]
    assert result.summary["solvent_mask_used"] is False
    assert ca["mask"]["state"] == "none"
    assert ca["stored_mask"]["state"] == "bound"
    result = p.invoke_tool("refine", {"mode": "isotropic", "n_cycles": 1,
        "use_solvent_mask": True, "refresh_mask": False})
    assert result.ok, result.error
    b = p.nodes.state()["active_node"]
    compared = p.nodes.comparison(b, a)
    assert compared["sources"]["node"]["conditions"]["mask"]["state"] == "bound"
    assert compared["metrics"]["r1"]["status"] == "comparable"
    assert "mask" in {row["field"] for row in compared["differences"]}
    from crystalpilot.refine.scene import build_fofc_ccp4
    from crystalpilot.tools import refinement_tools
    original = refinement_tools.difference_map_real
    masks_used = []
    def observed(session, model, f_mask=None, kind="fofc"):
        masks_used.append(f_mask)
        return original(session, model, f_mask, kind)
    monkeypatch.setattr(refinement_tools, "difference_map_real", observed)
    build_fofc_ccp4(p.dir, a, tmp_path / "map" / "2fofc.ccp4", kind="2fofc")
    assert masks_used == [None]


def test_better_nodes_requires_known_comparison_sources(tmp_path):
    from crystalpilot.refine.nodes import better_nodes
    p = _project(tmp_path)
    a, b = _refine(p), _refine(p)
    rows = p.nodes.list_nodes()["nodes"]
    # Synthetic ranking values isolate the provenance gate from optimizer progress.
    for row in rows:
        if row["id"] == a:
            row["r1"] = .1
        elif row["id"] == b:
            row["r1"] = .01
    assert [row["id"] for row in better_nodes(rows, a, .1)] == [b]
    for row in rows:
        row.pop("comparison_source", None)
    assert better_nodes(rows, a, .1) == []


def test_comparison_does_not_create_versions_or_move_active(tmp_path):
    p = _project(tmp_path)
    a = _refine(p)
    before = p.nodes.state()
    versions = _inventory(DataVersions(p.dir).directory)
    actual = p.nodes.comparison(a, "n0000")
    assert actual["metrics"]["r1"]["status"] == "unknown"
    assert p.nodes.state() == before
    assert _inventory(DataVersions(p.dir).directory) == versions
