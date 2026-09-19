"""Synchronous packing-tool adaptation of partial products; no scientific engines."""
from __future__ import annotations

import copy
import json
from types import SimpleNamespace

import pytest

from crystalpilot.refine import analysis
from crystalpilot.refine.tools_packing import AnalyzePacking, _topology_reading
from crystalpilot.tools.base import ToolContext


KINDS = ("hbond", "pipi", "chpi", "chx", "halogen", "anion_pi")


@pytest.fixture
def product():
    return {
        "v": analysis.ANALYSIS_CACHE_V, "node": "n0001",
        "interactions": {
            "unique": {kind: [] for kind in KINDS},
            "criteria": {kind: {"set": "olex2"} for kind in KINDS},
            "h_source": "absent", "h_source_note": "no H atoms", "truncated": {},
        },
        "pores": {
            "n_voids": 1,
            "voids": [{"void": 1, "volume_A3": 15.5, "dimensionality": 0,
                       "electrons": None}],
            "total_solvent_electrons_per_cell": None,
            "electron_count_status": "unsupported",
            "electron_count_note": "No observed reflections", "mode": "geometric",
            "packing": {"packing_index_pct": 52.0, "packing_index_error_pct": 0.2,
                        "volume_per_non_h_atom_A3": 24.5},
        },
        "guests": {"guests": [], "summary": {}, "host": {"selection_rule": "host"}},
        "topology": {
            "nets": {"n_nets": 2, "nets": [{"dimensionality": 3}, {"dimensionality": 3}],
                     "symmetry_related": False, "relations": []},
            "simplified_net": {"n_nodes_per_cell": 2, "n_edges_per_cell": 6,
                               "rcsr_symbol": "sql", "rcsr_symbols": ["sql", "dia"],
                               "rcsr_status": "已算", "node_connectivity_histogram": {4: 2}},
            "helices": [], "finite_fragments": [],
        },
        "stages": {stage: {"status": "ready", "elapsed_s": 0.01,
                           "error": None, "note": None}
                   for stage in analysis.ANALYSIS_STAGES},
    }


def unavailable(product, block, status="error"):
    product[block] = None
    product["stages"][block] = {
        "status": status, "elapsed_s": 1.5,
        "error": f"RuntimeError: {block} failed" if status == "error" else None,
        "note": f"{block} has no available calculation ({status})",
    }


@pytest.fixture
def run_tool(tmp_path, monkeypatch):
    from crystalpilot.refine import shelx_cards

    project = tmp_path / "project"
    root = project / ".crystalpilot" / "refine"
    node = root / "nodes" / "n0001"
    node.mkdir(parents=True)
    (node / "model.res").write_text("unused model", encoding="utf-8")
    (node / "node.json").write_text(json.dumps({"id": "n0001", "revision": 1}),
                                    encoding="utf-8")
    (root / "state.json").write_text(json.dumps({
        "active_node": "n0001", "branches": {"main": "n0001"}, "seq": 1,
    }), encoding="utf-8")
    path = tmp_path / "analysis.json"
    monkeypatch.setattr(analysis, "cached_analysis", lambda *args, **kwargs: path)
    monkeypatch.setattr(shelx_cards, "htab_cards", lambda *args: {
        "cards": [], "skipped": [], "note": "No H atoms",
    })

    def run(product, **params):
        path.write_text(json.dumps(product), encoding="utf-8")
        return AnalyzePacking(SimpleNamespace(dir=project)).run(
            ToolContext(store=None, session=None), **params)

    run.node_dir = node
    return run


@pytest.mark.parametrize("staged", [False, True])
def test_complete_legacy_and_staged_products_keep_synchronous_output(product, run_tool, staged):
    if not staged:
        product.pop("stages")
    result = run_tool(product)
    assert result.ok and result.error is None
    assert result.summary["status"] == "ready"
    assert result.summary["failed_blocks"] == []
    assert result.summary["unavailable_blocks"] == []
    assert result.summary["interactions"]["criteria_set"] == "olex2"
    assert result.summary["pores"]["n_voids"] == 1
    assert result.summary["packing"]["packing_index_pct"] == 52.0
    assert result.summary["guests"]["guests"] == []
    assert result.summary["topology"]["nets"]["n_nets"] == 2
    assert result.summary["suggested_cards"]["n_cards"] == 0


@pytest.mark.parametrize("status", ["error", "unsupported", "waiting", "running", "cancelled"])
def test_missing_interactions_and_pores_keep_independent_blocks(product, run_tool, status):
    unavailable(product, "interactions", status)
    unavailable(product, "pores", status)
    result = run_tool(product)
    assert result.ok
    summary = result.summary
    assert summary["status"] == "partial"
    assert summary["interactions"] is None
    assert summary["pores"] is None
    assert summary["packing"] is None
    assert summary["suggested_cards"] is None
    assert summary["guests"] is not None
    assert summary["topology"]["nets"]["n_nets"] == 2
    assert summary["block_status"]["interactions"]["status"] == status
    assert summary["block_status"]["pores"]["status"] == status
    assert summary["block_status"]["packing"]["status"] == status
    assert summary["unavailable_blocks"] == ["interactions", "pores", "packing"]
    assert summary["failed_blocks"] == (
        ["interactions", "pores", "packing"] if status == "error" else [])
    assert summary["pores_note"]
    assert "pores" in summary["packing_note"]
    assert not any("未检出溶剂可及孔道" in line or "该模型无溶剂可及孔道" in line
                   for line in summary["reading"])


def test_failed_unrequested_blocks_do_not_make_requested_topology_partial(product, run_tool):
    unavailable(product, "interactions")
    unavailable(product, "pores")
    unavailable(product, "guests")
    result = run_tool(product, blocks=["topology"])
    assert result.ok and result.summary["status"] == "ready"
    assert set(result.summary["block_status"]) == {"topology"}
    assert result.summary["failed_blocks"] == []
    assert result.summary["unavailable_blocks"] == []
    assert result.summary["filters"]["blocks"] == ["topology"]
    assert not any(key in result.summary for key in (
        "interactions", "pores", "packing", "guests", "suggested_cards", "pores_note"))


@pytest.mark.parametrize("status", ["error", "unsupported"])
def test_only_unavailable_requested_block_fails_without_dropping_summary(product, run_tool, status):
    unavailable(product, "pores", status)
    result = run_tool(product, blocks=["pores"])
    assert not result.ok
    assert result.summary["status"] == status
    assert result.summary["pores"] is None
    assert result.summary["pores_note"]
    assert result.error and "pores" in result.error
    assert set(result.summary["block_status"]) == {"pores"}
    assert "packing" not in result.summary


def test_packing_only_carries_failed_pore_dependency_without_unrequested_payload(product, run_tool):
    unavailable(product, "pores")
    result = run_tool(product, blocks=["packing"])
    assert not result.ok
    assert result.summary["packing"] is None
    assert "pores" in result.summary["packing_note"]
    assert result.summary["packing_error"] == "RuntimeError: pores failed"
    assert result.summary["failed_blocks"] == ["packing"]
    assert "pores" not in result.summary


def test_all_failed_blocks_remain_explicit(product, run_tool):
    for stage in analysis.ANALYSIS_STAGES:
        unavailable(product, stage)
    result = run_tool(product)
    assert not result.ok
    assert result.summary["status"] == "error"
    assert set(result.summary["failed_blocks"]) == {
        "interactions", "pores", "packing", "guests", "topology",
    }
    assert all(result.summary[block] is None for block in result.summary["failed_blocks"])


def test_legacy_missing_block_does_not_invent_error_or_zero_counts(product, run_tool):
    product.pop("stages")
    product["pores"] = None
    result = run_tool(product, blocks=["pores", "topology"])
    assert result.ok and result.summary["status"] == "partial"
    assert result.summary["block_status"]["pores"]["status"] == "unavailable"
    assert result.summary["pores"] is None
    assert result.summary["pores_error"] is None
    assert result.summary["pores_note"]
    assert result.summary["failed_blocks"] == []


def test_sparse_pore_payload_keeps_missing_count_and_details_null(product, run_tool):
    product["pores"] = {}
    result = run_tool(product, blocks=["pores"])
    assert result.ok
    assert result.summary["pores"]["n_voids"] is None
    assert result.summary["pores"]["voids"] is None
    assert any("逐项明细未提供" in line for line in result.summary["reading"])
    assert not any("未检出溶剂可及孔道" in line for line in result.summary["reading"])


def test_actual_zero_void_result_is_still_a_measured_zero(product, run_tool):
    product["pores"].update({"n_voids": 0, "voids": []})
    result = run_tool(product, blocks=["pores"])
    assert result.ok and result.summary["status"] == "ready"
    assert result.summary["pores"]["n_voids"] == 0
    assert result.summary["pores"]["voids"] == []
    assert any("未检出溶剂可及孔道" in line for line in result.summary["reading"])


def test_missing_packing_numbers_do_not_blame_an_unrelated_cache_version(product, run_tool):
    product["pores"].pop("packing")
    result = run_tool(product, blocks=["pores", "packing"])
    assert result.ok and result.summary["status"] == "partial"
    assert result.summary["packing"] is None
    assert result.summary["block_status"]["packing"]["status"] == "unavailable"
    assert "早于 v4" not in result.summary["packing_note"]


def test_geometry_pores_keep_nullable_electrons_and_capability_note(product, run_tool):
    result = run_tool(product, blocks=["pores"])
    assert result.ok
    pores = result.summary["pores"]
    assert pores["mode"] == "geometric"
    assert pores["electron_count_status"] == "unsupported"
    assert pores["electron_count_note"] == "No observed reflections"
    assert pores["total_solvent_electrons_per_cell"] is None
    assert pores["voids"][0]["electrons"] is None
    assert pores["voids"][0]["volume_A3"] == 15.5


def test_alternate_criteria_failure_is_isolated_and_never_falls_back(product, run_tool, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("PLATON computation failed")

    monkeypatch.setattr(analysis, "interactions_from_res", fail)
    result = run_tool(product, criteria="platon", blocks=["interactions", "topology"])
    assert result.ok and result.summary["status"] == "partial"
    assert result.summary["interactions"] is None
    assert result.summary["topology"] is not None
    assert result.summary["suggested_cards"] is None
    assert "PLATON computation failed" in result.summary["interactions_error"]
    assert "未回退" in result.summary["interactions_note"]


def test_alternate_criteria_can_recover_interactions_using_cif_fallback(product, run_tool, monkeypatch):
    replacement = copy.deepcopy(product["interactions"])
    for definition in replacement["criteria"].values():
        definition["set"] = "steiner"
    unavailable(product, "interactions", "unsupported")
    node = run_tool.node_dir
    (node / "node.json").write_text(json.dumps({
        "id": "n0001", "revision": 1, "structure_only": True,
    }), encoding="utf-8")
    (node / "model.cif").write_text("canonical CIF", encoding="utf-8")
    (node / "model.res").unlink()

    def recompute(path, *, criteria):
        assert path == node / "model.cif"
        assert criteria == "platon"
        return replacement

    monkeypatch.setattr(analysis, "interactions_from_res", recompute)
    result = run_tool(product, criteria="platon", blocks=["interactions"])
    assert result.ok and result.summary["status"] == "ready"
    assert result.summary["interactions"]["criteria_set"] == "steiner"
    assert result.summary["block_status"]["interactions"]["error"] is None
    assert "interactions_error" not in result.summary
    assert "pores" not in result.summary


def test_unrequested_interactions_are_not_recomputed(product, run_tool, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("unrequested interactions were recomputed")

    monkeypatch.setattr(analysis, "interactions_from_res", forbidden)
    result = run_tool(product, criteria="platon", blocks=["topology"])
    assert result.ok and result.summary["status"] == "ready"


def test_successful_interaction_filters_keep_existing_counts(product, run_tool):
    product["interactions"]["unique"]["chx"] = [
        {"passes": True, "intra": False, "dist": 2.7, "op": "x,y,z", "_seq": 1},
        {"passes": True, "intra": True, "dist": 2.6, "op": "x,y,z"},
        {"passes": False, "intra": False, "dist": 3.0, "op": "x,y,z"},
    ]
    result = run_tool(product, blocks=["interactions"], kinds=["chx"], max_rows=1)
    assert result.ok and result.summary["status"] == "ready"
    inter = result.summary["interactions"]
    assert inter["counts"]["chx"] == {
        "unique": 3, "passing": 2, "intra": 1, "kept": 1, "shown": 1,
    }
    assert set(inter["rows"]) == {"chx"}
    assert "_seq" not in inter["rows"]["chx"][0]
    assert "suggested_cards" not in result.summary


def test_topology_shape_preserves_component_symbols_and_unknown_net_count(product, run_tool):
    result = run_tool(product, blocks=["topology"])
    assert result.summary["topology"]["simplified_net"]["rcsr_symbols"] == ["sql", "dia"]
    assert any("RCSR sql/dia" in line for line in result.summary["reading"])
    unknown = _topology_reading({}, {}, [], [])
    assert "计数未提供" in unknown
    assert "没有周期性网（分子晶体）" not in unknown
    measured_zero = _topology_reading({"n_nets": 0}, {}, [], [])
    assert "没有周期性网（分子晶体）" in measured_zero
