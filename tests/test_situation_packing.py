"""R5: situation_report's `packing` block is read from the active node's
cached analysis.json and never computed there - absent means 未算 with the
builder named; present means the headline numbers and one narrative line."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

HEX = Path("H:/CrystalPilot-campaigns/ka1-hex/p92391ef8")


def _node_tree(tmp_path, node="n0007"):
    from crystalpilot.refine.nodes import NodeStore
    store = NodeStore(tmp_path)
    (store.nodes_dir / node).mkdir(parents=True)
    (store.nodes_dir / node / "node.json").write_text(json.dumps(
        {"id": node, "tool": "refine", "params": {}, "branch": "main"}),
        encoding="utf-8")
    st = store.state()
    st.update({"seq": 8, "active_node": node, "branches": {"main": node}})
    store._save_state(st)
    return node


def test_absent_product_is_reported_not_built(tmp_path):
    from crystalpilot.refine.tools_analysis import (_packing_sentence,
                                                    _packing_summary)
    assert _packing_summary(tmp_path)["status"].startswith("未算")
    node = _node_tree(tmp_path)
    ps = _packing_summary(tmp_path)
    assert ps["node"] == node and ps["status"].startswith("未算")
    assert "analyze_packing" in ps["status"]
    assert _packing_sentence(ps) is None
    from crystalpilot.refine.scene import cache_dir
    assert not (cache_dir(tmp_path, node) / "analysis.json").exists()


def test_cached_product_gives_the_headline(tmp_path):
    from crystalpilot.refine.analysis import ANALYSIS_CACHE_V
    from crystalpilot.refine.scene import cache_dir
    from crystalpilot.refine.tools_analysis import (_packing_sentence,
                                                    _packing_summary)
    node = _node_tree(tmp_path)
    d = cache_dir(tmp_path, node)
    d.mkdir(parents=True)
    product = {
        "v": ANALYSIS_CACHE_V, "node": node,
        "interactions": {"h_source": "riding",
                         "counts": {"unique": {"hbond": 3, "pipi": 1, "chx": 0},
                                    "passing": {"hbond": 2, "pipi": 1, "chx": 0},
                                    "intra": {"hbond": 1, "pipi": 0, "chx": 0}}},
        "pores": {"n_voids": 2, "solvent_volume_A3": 812.5,
                  "solvent_volume_pct_of_cell": 31.2,
                  "voids": [{"void": 1, "volume_A3": 800.0, "dimensionality": 1,
                             "directions": [[0, 0, 1]], "lcd_A": 7.4,
                             "pld_A": 4.1, "pld_error_A": 0.4, "electrons": 120.0},
                            {"void": 2, "volume_A3": 12.5, "dimensionality": 0}],
                  "packing": {"packing_index_pct": 61.3,
                              "packing_index_error_pct": 0.4,
                              "volume_per_non_h_atom_A3": 19.8}},
        "guests": {"summary": {"cage_cavity": 0, "channel": 2, "cavity": 0,
                               "interstitial": 1},
                   "guests": [{}, {}, {}]},
    }
    (d / "analysis.json").write_text(json.dumps(product), encoding="utf-8")
    ps = _packing_summary(tmp_path)
    assert ps["status"] == "已算" and ps["node"] == node
    assert ps["interactions"]["unique"]["hbond"] == 3
    assert ps["pores"]["largest"]["void"] == 1
    assert ps["pores"]["largest"]["pld_A"] == 4.1
    assert ps["packing"]["packing_index_pct"] == 61.3
    assert ps["guests"] == {"summary": product["guests"]["summary"], "n_guests": 3}
    line = _packing_sentence(ps)
    assert line.startswith("堆积摘要（节点 n0007")
    assert "氢键 3（合格 2）" in line and "π–π 1（合格 1）" in line
    assert "C–H···X" not in line                       # zero kinds stay silent
    assert "PLD 4.1±0.4 Å" in line and "堆积指数 61.3±0.4 %" in line
    assert "channel 2" in line and "analyze_packing" in line
    # a stale version is said, not hidden
    product["v"] = ANALYSIS_CACHE_V - 1
    (d / "analysis.json").write_text(json.dumps(product), encoding="utf-8")
    assert _packing_summary(tmp_path)["status"].startswith("旧版产物")


@pytest.mark.skipif(not (HEX / ".crystalpilot").exists(),
                    reason="ka1-hex campaign project not present")
def test_real_project_headline_reads_only():
    from crystalpilot.refine.tools_analysis import _packing_summary
    ps = _packing_summary(HEX)
    assert ps.get("node")
    if ps["status"].startswith("未算"):
        pytest.skip(ps["status"])
    assert ps["pores"]["n_voids"] >= 1
