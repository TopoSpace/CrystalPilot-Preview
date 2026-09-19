"""RefineProject + NodeStore tests (M3 gate): commit, branch, checkout,
cross-process resume, mask/H/weights survival, R1 reproduction."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
CASE = (REPO / "benchmark" / "data" /
        "重复SJTU-9_SJTU-9_or_post_晶体数据_原始SJTU-9_olex2_temp_sjtu-9")

pytestmark = pytest.mark.skipif(not CASE.exists(), reason="SJTU-9 case missing")


@pytest.fixture()
def project_dir(tmp_path):
    d = tmp_path / "proj"
    d.mkdir()
    shutil.copy(CASE / "hkl.hkl", d / "crystal.hkl")
    shutil.copy(CASE / "ref_res.res", d / "start.res")
    (d / "context.json").write_text(json.dumps({
        "chemistry": {"metal": "Zr"},
        "data": {"hkl": "crystal.hkl", "start_model": "start.res"},
    }), encoding="utf-8")
    return d


def open_project(project_dir):
    from crystalpilot.refine.project import RefineProject
    return RefineProject(project_dir)


def test_import_commit_refine_branch_checkout(project_dir):
    p = open_project(project_dir)
    opened = p.open()
    assert opened["resumed"] is False and opened["node"] == "n0000"
    # riding H were re-derived from the AFIX groups of the start model
    assert p.session.flags.get("h_riding_meta")
    n_h = sum(1 for sc in p.session.model.scatterers()
              if sc.scattering_type.strip().upper() == "H")
    assert n_h == 5

    r = p.invoke_tool("refine", {"mode": "anisotropic", "n_cycles": 4})
    assert r.ok
    node_refine = r.summary["node"]
    r1_recorded = r.summary["r1_strong"]
    assert r1_recorded < 0.12          # sane unmasked R1 for this model

    # a model edit commits another node
    r2 = p.invoke_tool("edit_atoms",
                       {"operations": [{"action": "set_u_iso",
                                        "atoms": ["O007"], "u_iso": 0.08}]})
    assert r2.ok
    node_edit = r2.summary["node"]
    assert node_edit != node_refine

    # branch from the refine node, checkout moves the session back
    p.nodes.branch("alt", from_ref=node_refine)
    out = p.checkout(node_refine)
    assert out["node"] == node_refine
    r3 = p.invoke_tool("refine", {"mode": "anisotropic", "n_cycles": 1})
    assert abs(r3.summary["r1_strong"] - r1_recorded) < 5e-4

    listing = p.nodes.list_nodes()
    ids = [n["id"] for n in listing["nodes"]]
    assert {"n0000", node_refine, node_edit}.issubset(set(ids))
    assert "alt" in listing["branches"]
    # a geometry-only commit has no measurement of its own; the listing
    # names the nearest measured ancestor instead of leaving "—" (usertest
    # test3-2 2026-09-08 read the dashes as "the refinement was lost")
    rows = {n["id"]: n for n in listing["nodes"]}
    edit = rows[node_edit]
    if edit["r1"] is None:
        assert edit["metrics_inherited"]["from"] == node_refine
        assert edit["metrics_inherited"]["distance"] == 1
        assert edit["metrics_inherited"]["r1"] == rows[node_refine]["r1"]
    assert "metrics_inherited" not in rows[node_refine]


def test_cross_process_resume_with_mask(project_dir):
    p = open_project(project_dir)
    p.open()
    mask = p.invoke_tool("solvent_mask", {})
    assert mask.ok, mask.error
    r = p.invoke_tool("refine", {"mode": "anisotropic", "n_cycles": 4})
    assert r.ok and r.summary["solvent_mask_used"]
    r1_masked = r.summary["r1_strong"]
    active = p.nodes.state()["active_node"]

    # simulate a fresh MCP server process
    q = open_project(project_dir)
    resumed = q.open()
    assert resumed["resumed"] and resumed["node"] == active
    assert any("mask" in n for n in resumed["notes"])
    assert q.session.flags.get("f_mask") is not None
    assert q.session.flags.get("weights")
    r2 = q.invoke_tool("refine", {"mode": "anisotropic", "n_cycles": 1})
    assert r2.ok and r2.summary["solvent_mask_used"]
    assert abs(r2.summary["r1_strong"] - r1_masked) < 5e-4


def test_compare_nodes_reports_structural_diff(project_dir):
    p = open_project(project_dir)
    p.open()
    p.invoke_tool("refine", {"mode": "isotropic", "n_cycles": 2})
    a = p.nodes.state()["active_node"]
    r = p.invoke_tool("edit_atoms",
                      {"operations": [{"action": "delete", "atoms": ["O003"]},
                                      {"action": "reassign", "atoms": ["ZR01"],
                                       "element": "Fe"}]})
    assert r.ok, r.error
    b = r.summary["node"]
    cmp = p.compare_nodes(a, b)
    assert "O003" in cmp["structure_diff"]["atoms_removed_in_b"]
    assert any(c["atom"] == "ZR01" and c["to"] == "Fe"
               for c in cmp["structure_diff"]["element_changed"])


def test_node_res_runs_in_shelxl_format(project_dir):
    """Every node's model.res must re-parse (writer robustness under real use)."""
    from crystalpilot.io.shelx_model import load_res_model
    p = open_project(project_dir)
    p.open()
    p.invoke_tool("refine", {"mode": "anisotropic", "n_cycles": 2})
    st = p.nodes.state()
    for node_id in [f"n{i:04d}" for i in range(st["seq"])]:
        m = load_res_model(p.nodes.node_dir(node_id) / "model.res")
        assert m.structure.scatterers().size() > 0


def test_node_records_the_data_it_was_fitted_against(project_dir):
    """Rint bounds what R1 can be, but it lived only in a chat chip that
    scrolled away. Every commit now carries the data state, so the viewer
    can show it beside the R factors - and so a data swap leaves a
    visible trail in the node history."""
    p = open_project(project_dir)
    p.open()
    nodes = p.nodes.list_nodes(limit=5)["nodes"]
    d = nodes[0]["data"]
    assert d is not None, "n0000 carries no data block"
    assert 0.0 <= d["r_int"] <= 1.0
    assert d["n_unique"] > 100
    assert d["space_group"]
    assert d["d_min"] > 0
    # redundancy is derivable in the UI: observations / unique
    assert d["n_obs"] >= d["n_unique"]


def test_data_block_survives_a_commit_without_a_session_merge(tmp_path):
    """A viewer field must never be able to fail a commit."""
    from crystalpilot.refine.nodes import _data_block

    class _Bare:
        pass
    assert _data_block(_Bare()) is None            # nothing to report

    class _Odd:
        merge_info = "not a dict"
        flags = {"hklf": 5,
                 "data_cards": ["SHEL 999 0.81", "OMIT -3 50"]}
    out = _data_block(_Odd())
    assert out["hklf"] == 5 and out["shel"] == "SHEL 999 0.81"


def test_checkout_accepts_target_alias_and_explains_a_missing_one(project_dir):
    """reg3-rz: checkout({target: 'solve_c2c'}) was schema-rejected with a
    bare "'node' is a required property"."""
    p = open_project(project_dir)
    p.open()
    r = p.invoke_tool("refine", {"mode": "isotropic", "n_cycles": 1})
    assert r.ok
    node = r.summary["node"]
    p.nodes.branch("alt", from_ref=node)
    r2 = p.invoke_tool("edit_atoms",
                       {"operations": [{"action": "set_u_iso",
                                        "atoms": ["O007"], "u_iso": 0.08}]})
    assert r2.ok
    # `branch` made alt active, so the edit landed on alt's head
    chk = p.invoke_tool("checkout", {"target": "alt"})
    assert chk.ok, chk.error
    assert chk.summary["node"] == r2.summary["node"]
    chk2 = p.invoke_tool("checkout", {"branch": node})
    assert chk2.ok, chk2.error
    assert chk2.summary["node"] == node
    bare = p.invoke_tool("checkout", {})
    assert not bare.ok
    assert "node=" in bare.error and "alt" in bare.error
    assert node in bare.error


def test_compare_nodes_accepts_node_a_node_b_aliases(project_dir):
    """reg7-dbu: compare_nodes({node_a, node_b}) was schema-rejected twice."""
    p = open_project(project_dir)
    p.open()
    r = p.invoke_tool("refine", {"mode": "isotropic", "n_cycles": 1})
    assert r.ok
    node = r.summary["node"]
    r2 = p.invoke_tool("edit_atoms",
                       {"operations": [{"action": "set_u_iso",
                                        "atoms": ["O007"], "u_iso": 0.08}]})
    assert r2.ok
    c = p.invoke_tool("compare_nodes", {"node_a": node, "node_b": r2.summary["node"]})
    assert c.ok, c.error
    bare = p.invoke_tool("compare_nodes", {"a": node})
    assert not bare.ok and "b=<node" in bare.error

