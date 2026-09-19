"""analyze_packing (round-2 R5): the measurement tables of one node from
the per-node analysis product - three parts per block (measurements,
criteria, reading marked as interpretation), HTAB cards for SHELXL, filters
that only drop rows and never numbers. Driven end to end on the public
Ca-imidazolate benchmark through a fresh RefineProject."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "benchmark" / "public" / "Ca_imidazolate"


@pytest.fixture(scope="module")
def project(tmp_path_factory):
    if not (SRC / "ref_cif.cif").exists():
        pytest.skip("Ca_imidazolate benchmark not present")
    d = tmp_path_factory.mktemp("packing-proj")
    (d / "context.json").write_text(json.dumps({
        "chemistry": {"note": "analyze_packing test"}}), encoding="utf-8")
    from crystalpilot.refine.project import RefineProject
    p = RefineProject(d)
    p.open()
    r = p.invoke_tool("import_cif_model", {
        "cif_path": str(SRC / "ref_cif.cif"),
        "hkl_path": str(SRC / "sf.cif")})
    assert r.ok, r.error
    return p


class TestAnalyzePacking:
    def test_registered_read_only(self):
        from crystalpilot.mcp.server import READ_ONLY_TOOLS
        from crystalpilot.refine.registry import MUTATING_TOOLS
        assert "analyze_packing" in READ_ONLY_TOOLS
        assert "analyze_packing" not in MUTATING_TOOLS

    def test_full_product(self, project):
        r = project.invoke_tool("analyze_packing", {})
        assert r.ok, r.error
        s = r.summary
        assert s["scope"] == "canonical" and s["node"] == "n0000"
        assert s["reading_note"] and isinstance(s["reading"], list)
        # interactions: counts per kind, rows only for kept ones
        ix = s["interactions"]
        assert set(ix["counts"]) >= {"hbond", "pipi", "chx", "shown_total"}
        assert ix["criteria_set"] == "olex2"
        assert ix["h_source"] in ("riding", "refined", "absent", "mixed")
        for k, rows in ix["rows"].items():
            c = ix["counts"][k]
            assert len(rows) == c["shown"] <= c["kept"] <= c["unique"]
            for row in rows:
                assert row["passes"] is True and not row.get("intra")
                assert "op" in row and "dist" in row
                assert not any(kk.endswith("_seq") for kk in row)
        assert "hbond" in ix["criteria"] and ix["criteria"]["hbond"]["set"]
        # pores + packing + guests blocks are present with their rule text
        assert "n_voids" in s["pores"] and "criteria" in s["pores"]
        pk = s["packing"]
        assert pk["packing_index_pct"] > 0 and "note" in pk and "method" in pk
        g = s["guests"]
        assert g is None or set(g["summary"]) == {
            "cage_cavity", "channel", "cavity", "interstitial"}
        # HTAB cards: a dict with cards/skipped/note, never missing
        cards = s["suggested_cards"]
        assert set(cards) >= {"cards", "skipped", "note", "n_cards", "how"}
        assert cards["n_cards"] == len(cards["cards"])
        assert Path(s["product"]).exists()

    def test_filters_only_drop_rows(self, project):
        base = project.invoke_tool("analyze_packing", {"kinds": ["chx"]})
        loose = project.invoke_tool("analyze_packing", {
            "kinds": ["chx"], "only_passing": False, "include_intra": True,
            "max_rows": 500})
        assert base.ok and loose.ok
        cb, cl = base.summary["interactions"]["counts"]["chx"], \
            loose.summary["interactions"]["counts"]["chx"]
        assert cb["unique"] == cl["unique"]
        assert cl["kept"] == cl["unique"] >= cb["kept"]
        assert set(base.summary["interactions"]["rows"]) == {"chx"}
        assert "suggested_cards" not in base.summary   # no hbond kind asked

    def test_platon_criteria_recomputes(self, project):
        r = project.invoke_tool("analyze_packing", {
            "criteria": "platon", "blocks": ["interactions"]})
        assert r.ok, r.error
        assert r.summary["interactions"]["criteria_set"] == "steiner"
        assert "pores" not in r.summary and "packing" not in r.summary

    def test_unknown_node_fails_loud(self, project):
        r = project.invoke_tool("analyze_packing", {"node": "n9999"})
        assert not r.ok and "n9999" in (r.error or "")


def test_topology_block_rides_in_the_product(project):
    """R4: the tool's `topology` block is the product's (nets, simplified net
    with its Systre status, helices, finite fragments) and the reading is a
    labelled description; Ca-imidazolate has at least one periodic net."""
    r = project.invoke_tool("analyze_packing", {"blocks": ["topology"]})
    assert r.ok, r.error
    s = r.summary
    assert "interactions" not in s and "pores" not in s
    tp = s["topology"]
    assert tp is not None, s.get("topology_error")
    assert set(tp) == {"nets", "simplified_net", "helices", "finite_fragments", "note"}
    assert tp["nets"]["n_nets"] >= 1
    assert tp["nets"]["nets"][0]["dimensionality"] >= 1   # the bonding truth reads Ca-imidazolate as chains here
    # jar-agnostic: 未算 (no Gavrog installed), 已算 + a symbol, or 已跑
    # + Systre's own reason (this net is not in the RCSR archive).
    # vendor/ is gitignored, so the answer differs machine to machine.
    st = tp["simplified_net"]["rcsr_status"]
    assert st.startswith(("未算", "已算", "已跑")), st
    assert bool(tp["simplified_net"]["rcsr_symbol"]) == st.startswith("已算")
    assert tp["simplified_net"]["n_nodes_per_cell"] >= 1
    assert any(x.startswith("拓扑（描述，不是判定）") for x in s["reading"])


# ------------------------------------------- round-3 R5-C: electron basis --

def test_electron_count_basis_names_both_masks():
    """Two electron counts, one unit: the refinement mask snapshot (the one
    that entered Fc) and the recount on this node. The basis names both,
    says they are per cell, and above a 20 % gap says which one to quote -
    the Zr-MOF rerun read 591.6 vs 1193.2 e/cell with no way to tell."""
    from crystalpilot.refine.tools_packing import (
        ELECTRON_BASIS_DISAGREE, _electron_basis_sentence,
        _electron_count_basis)

    agree = _electron_count_basis({
        "node": "n0109", "params_source": "node",
        "total_solvent_electrons_per_cell": 600.0,
        "recorded": {"total_solvent_electrons_per_cell": 591.6,
                     "solvent_volume_A3": 5000.0, "n_voids": 1}})
    assert agree["per"] == "cell" and agree["recomputed_on_node"] == "n0109"
    assert agree["recomputed_total_e"] == 600.0
    assert agree["refinement_mask_snapshot"]["total_solvent_electrons_per_cell"] == 591.6
    assert agree["agree"] is True and agree["relative_difference"] < ELECTRON_BASIS_DISAGREE
    line = _electron_basis_sentence(agree)
    assert "600.0 e/胞" in line and "591.6 e/胞" in line and "两者一致" in line

    disagree = _electron_count_basis({
        "node": "n0109", "params_source": "node",
        "total_solvent_electrons_per_cell": 1193.2,
        "recorded": {"total_solvent_electrons_per_cell": 591.6}})
    assert disagree["agree"] is False
    assert disagree["relative_difference"] > 1.0
    assert "disagree" in disagree["note"]
    line = _electron_basis_sentence(disagree)
    assert "1193.2 e/胞" in line and "591.6 e/胞" in line
    assert "以精修掩膜快照为准" in line

    # an unconverged recount is not a number to hold against the snapshot
    unconv = _electron_count_basis({
        "node": "n0108", "params_source": "node",
        "total_solvent_electrons_per_cell": 602.8,
        "bypass": {"converged": False, "diverged": True, "n_cycles": 14,
                   "f000s_first": 1737.5, "f000s_last": 627.3},
        "anomalous_terms": {"Zr": [0.0, 0.0]},
        "recorded": {"total_solvent_electrons_per_cell": 591.6}})
    assert unconv["recomputed_converged"] is False and unconv["recomputed_cycles"] == 14
    assert unconv["anomalous_terms"] == {"Zr": [0.0, 0.0]}
    assert "did NOT converge" in unconv["note"]
    line = _electron_basis_sentence(unconv)
    assert "未收敛" in line and "14 轮" in line and "以精修掩膜快照为准" in line
    assert "两者一致" not in line

    alone = _electron_count_basis({"node": "n0001", "params_source": "defaults",
                                   "total_solvent_electrons_per_cell": 42.0})
    assert alone["refinement_mask_snapshot"] is None and "agree" not in alone
    assert "no refinement mask snapshot" in alone["note"]
    assert "42.0 e/胞" in _electron_basis_sentence(alone)

    geometric = _electron_count_basis({"node": "n0001",
                                       "total_solvent_electrons_per_cell": None,
                                       "recorded": {"total_solvent_electrons_per_cell": 10.0}})
    assert geometric["recomputed_total_e"] is None
    assert "只有精修所用掩膜快照" in _electron_basis_sentence(geometric)
    assert _electron_basis_sentence(_electron_count_basis({})) is None


def test_product_carries_the_electron_count_basis(project):
    r = project.invoke_tool("analyze_packing", {})
    assert r.ok, r.error
    pores = r.summary["pores"]
    basis = pores["electron_count_basis"]
    assert basis["per"] == "cell"
    assert basis["recomputed_on_node"] == pores["node"] if pores.get("node") else True
    assert basis["params_source"] in ("node", "defaults", None)
    assert basis["recomputed_total_e"] == pores["total_solvent_electrons_per_cell"]
    if basis["recomputed_total_e"] is not None:
        assert any("残余电子合计" in line and "e/胞" in line
                   for line in r.summary["reading"])
    for v in pores["voids"]:
        if (v.get("dimensionality") or 0) >= 1 and "pld_along" in v:
            assert set(v["pld_along"]) == {"a", "b", "c"}
