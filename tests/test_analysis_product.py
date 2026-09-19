"""refine/analysis.py (round-2 R3.5): the per-node analysis product -
canonical interaction tables with their criteria and hydrogen provenance,
the node's pores, and explicit pending blocks - cached next to voids.json.

Synthetic .res files for the pure function; the committed mvp-sjtu9 node
store (copied to tmp, cache excluded) for the cached product."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "workbench" / "mvp-sjtu9"

# O1-H1...O2 along +x: O-H 0.96, H...O 1.84, D...A 2.80 A, angle 180 deg
WATER_PAIR = (
    "TITL two hydroxyls, primitive cubic\n"
    "CELL 0.71073 10 10 10 90 90 90\n"
    "ZERR 1 0 0 0 0 0 0\n"
    "LATT -1\n"
    "SFAC H O\n"
    "UNIT 1 2\n"
    "O1 2 0.200 0.500 0.500 11 0.05\n"
    "{afix_on}"
    "H1 1 0.296 0.500 0.500 11 0.05\n"
    "{afix_off}"
    "O2 2 {x2:.3f} 0.500 0.500 11 0.05\n"
    "HKLF 4\n"
    "END\n"
)


def _res(tmp_path, x2=0.480, riding=False):
    p = tmp_path / "pair.res"
    p.write_text(WATER_PAIR.format(
        x2=x2, afix_on="AFIX 147\n" if riding else "",
        afix_off="AFIX 0\n" if riding else ""), encoding="ascii")
    return p


class TestInteractionsFromRes:
    def test_canonical_hbond_table(self, tmp_path):
        from crystalpilot.refine.analysis import interactions_from_res

        out = interactions_from_res(_res(tmp_path))
        assert out["scope"] == "canonical" and out["h_source"] == "refined"
        rows = out["unique"]["hbond"]
        assert len(rows) == 1
        r = rows[0]
        assert (r["d"], r["h"], r["a"]) == ("O1", "H1", "O2")
        assert r["d_DA"] == pytest.approx(2.80, abs=1e-3)
        assert r["angle"] == pytest.approx(180.0, abs=0.05)
        assert r["passes"] is True
        assert out["counts"]["unique"]["hbond"] == 1
        assert out["counts"]["passing"]["hbond"] == 1
        assert out["counts"]["n_unique"] == 1
        assert out["criteria"]["hbond"]["set"] == "olex2"
        assert out["truncated"] == {}
        # every kind is present even when empty: "none found" is a result
        assert set(out["unique"]) == {"hbond", "pipi", "chpi", "chx",
                                      "halogen", "anion_pi"}
        # display-only keys never leak into the canonical table
        assert not ({"sym", "xyz", "boundary", "i", "j"} & set(r))

    def test_partner_across_the_cell_face_is_one_row_with_its_operator(
            self, tmp_path):
        """O2 at x = 0.920 is 7.2 A from O1 directly and 2.8 A through the
        image at x - 1: the canonical table has exactly one row and its
        operator is that translation, not the identity."""
        from crystalpilot.refine.analysis import interactions_from_res

        out = interactions_from_res(_res(tmp_path, x2=0.920))
        rows = out["unique"]["hbond"]
        assert len(rows) == 1
        assert rows[0]["op"].replace(" ", "") != "x,y,z"
        assert rows[0]["d_DA"] == pytest.approx(2.80, abs=1e-3)

    def test_riding_h_is_declared(self, tmp_path):
        from crystalpilot.refine.analysis import interactions_from_res

        out = interactions_from_res(_res(tmp_path, riding=True))
        assert out["h_source"] == "riding"
        assert out["h_source_note"]

    def test_cap_is_reported_not_silent(self, tmp_path, monkeypatch):
        from crystalpilot.refine import analysis

        monkeypatch.setattr(analysis, "MAX_UNIQUE_ROWS", 0)
        out = analysis.interactions_from_res(_res(tmp_path))
        assert out["unique"]["hbond"] == []
        assert out["truncated"]["hbond"] == {"cap": 0, "found": 1}


@pytest.mark.skipif(not (FIXTURE / "start.res").exists(),
                    reason="mvp-sjtu9 fixture not present")
def test_cached_product_on_the_fixture_store(tmp_path):
    from crystalpilot.refine.analysis import (ANALYSIS_CACHE_V,
                                              cached_analysis)
    from crystalpilot.refine.scene import VOIDS_CACHE_V

    proj = tmp_path / "proj"
    shutil.copytree(FIXTURE, proj,
                    ignore=shutil.ignore_patterns("scene-cache"))
    path = cached_analysis(proj, "n0013")
    d = json.loads(path.read_text(encoding="utf-8"))
    assert d["v"] == ANALYSIS_CACHE_V and d["voids_v"] == VOIDS_CACHE_V
    assert d["node"] == "n0013"
    inter = d["interactions"]
    assert inter["scope"] == "canonical"
    assert inter["h_source"] in ("riding", "refined", "absent", "mixed")
    assert set(inter["unique"]) == {"hbond", "pipi", "chpi", "chx",
                                    "halogen", "anion_pi"}
    assert set(inter["criteria"]) >= set(inter["unique"])
    # pores = this node's voids.json, verbatim, plus the pending block
    assert d["pores"]["v"] == VOIDS_CACHE_V and d["pores"]["node"] == "n0013"
    pk = d["pores"]["packing"]
    assert pk["packing_index_pct"] > 0 and pk["volume_per_non_h_atom_A3"] > 0
    assert "packing_note" not in d["pores"]
    g = d["guests"]
    assert g is not None and "guests_error" not in d, d.get("guests_error")
    assert set(g) >= {"criteria", "host", "guests", "summary", "grid_step_A"}
    assert set(g["summary"]) == {"cage_cavity", "channel", "cavity", "interstitial"}
    # R4: the topology block rides in the same product
    top = d["topology"]
    assert top is not None and "topology_error" not in d, d.get("topology_error")
    assert set(top) >= {"nets", "simplified_net", "helices", "finite_fragments"}
    # The Systre answer always carries its own status - but WHICH status
    # depends on whether this machine has a jar, and vendor/ is gitignored,
    # so pinning "未算" here made the product test fail the moment someone
    # installed Gavrog. Assert the contract instead: one of the three honest
    # prefixes, and a symbol only ever alongside 已算.
    st = top["simplified_net"]["rcsr_status"]
    assert st.startswith(("未算", "已算", "已跑")), st
    if top["simplified_net"]["rcsr_symbol"] is not None:
        assert st.startswith("已算"), st
    # second call is a cache hit (same file, untouched)
    stamp = path.stat().st_mtime_ns
    assert cached_analysis(proj, "n0013") == path
    assert path.stat().st_mtime_ns == stamp
    # a file from another product version is rebuilt, not trusted
    path.write_text(json.dumps({"v": -1, "voids_v": VOIDS_CACHE_V}),
                    encoding="utf-8")
    cached_analysis(proj, "n0013")
    assert json.loads(path.read_text(encoding="utf-8"))["v"] == \
        ANALYSIS_CACHE_V


def test_topology_block_of_the_pair(tmp_path):
    """Two hydroxyls in a box: no periodic net, no metal node, no helix; two
    finite fragments (O1-H1 and O2) with no ring and no polyhedron, and the
    Systre answer is 未算 with its reason - never a raise."""
    from crystalpilot.refine.analysis import topology_from_res
    top = topology_from_res(_res(tmp_path))
    assert top["nets"]["n_nets"] == 0 and top["nets"]["interpenetrated"] is False
    net = top["simplified_net"]
    assert net["nodes"] == [] and net["edges"] == []
    assert "金属" in net["note"] and net["rcsr_symbol"] is None
    assert net["rcsr_status"].startswith("未算")
    assert top["helices"] == []
    ff = top["finite_fragments"]
    assert [(f["fragment"], f["n_atoms"], f["asu_labels"]) for f in ff] == [
        ("F1", 2, ["H1", "O1"]), ("F2", 1, ["O2"])]
    assert all(f["largest_cycle"]["size"] is None and f["shape"] is None for f in ff)
    assert all(f["copies"] == 1 for f in ff)
