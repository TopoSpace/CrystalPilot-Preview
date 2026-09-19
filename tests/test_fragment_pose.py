"""Round-3 WP5: whole-fragment pose search + group-level acceptance.

Synthetic P-1 cell: a five-atom "framework" in both data and model, and a
benzene ring present in the DATA only (0.3 occupancy at a general
position; full occupancy centred on the inversion centre for the folding
case). No campaign crystal, no element-specific constant: the ring is
found from its peak geometry and the difference density.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from tests.test_probe_site import _open, _state, _sym_distance, make_project  # noqa: E402

CELL = (10.0, 11.0, 12.0, 90.0, 95.0, 90.0)
SG = "P -1"
FRAME = [("S1", "S", (0.15, 0.20, 0.30)),
         ("S2", "S", (0.65, 0.15, 0.75)),
         ("O1", "O", (0.20, 0.35, 0.15)),
         ("O2", "O", (0.75, 0.30, 0.85)),
         ("N1", "N", (0.40, 0.10, 0.55))]


def _ring(cell, centre_frac, normal, n=6, radius=1.39):
    from cctbx import uctbx
    uc = uctbx.unit_cell(cell)
    c = np.array(uc.orthogonalize(tuple(centre_frac)), float)
    nrm = np.array(normal, float)
    nrm /= np.linalg.norm(nrm)
    u = np.cross(nrm, [1.0, 0.0, 0.0])
    u /= np.linalg.norm(u)
    v = np.cross(nrm, u)
    out = []
    for k in range(n):
        th = 2.0 * math.pi * k / 6.0
        p = c + radius * (math.cos(th) * u + math.sin(th) * v)
        out.append(tuple(float(x) for x in uc.fractionalize(tuple(p))))
    return out


GUEST_CENTRE = (0.30, 0.55, 0.62)
RING = _ring(CELL, GUEST_CENTRE, (0.3, 0.5, 0.8))
GUEST = [(f"C{k + 1}G", "C", RING[k], 0.3, 0.03) for k in range(6)]
# three unique atoms; the inversion centre at (1/2,1/2,1/2) makes the ring
CENTRE_RING = _ring(CELL, (0.5, 0.5, 0.5), (0.2, 0.9, 0.4))[:3]
GUEST_CENTRED = [(f"C{k + 1}G", "C", CENTRE_RING[k], 1.0, 0.03) for k in range(3)]
BENZENE = "c1ccccc1"


@pytest.fixture
def project_general(tmp_path):
    return _open(make_project(tmp_path, CELL, SG, FRAME, FRAME + GUEST, z=2))


@pytest.fixture
def project_centred(tmp_path):
    return _open(make_project(tmp_path, CELL, SG, FRAME, FRAME + GUEST_CENTRED, z=2))


def _search(p, **params):
    return p.invoke_tool("search_fragment_pose", {"smiles": BENZENE, **params})


def _min_truth_distance(site, truth):
    return min(_sym_distance(CELL, SG, site, t) for t in truth)


# ==========================================================================
class TestSearch:
    def test_finds_the_hidden_ring(self, project_general):
        p = project_general
        before = _state(p)["active_node"]
        r = _search(p)
        assert r.ok, r.error
        s = r.summary
        assert s["fragment"]["n_heavy"] == 6 and s["fragment"]["n_rotatable"] == 0
        assert s["fragment"]["n_conformers"] == 1
        assert s["peaks_used"] >= 6 and s["n_seeds"] > 0
        cands = s["candidates"]
        assert cands and cands[0]["id"] == "c01"
        top = cands[0]
        assert len(top["per_atom"]) == 6 and top["symmetry_folded"] is None
        for a in top["per_atom"]:
            assert _min_truth_distance(a["site_frac"], RING) <= 0.4, a
            assert a["evidence"] in ("direct_peak", "weak_density"), a
            assert a["sigma_level"] >= 1.0
        assert top["n_direct"] >= 4 and top["n_geometry_only"] == 0
        assert top["clashes"] == [] and top["constraints_satisfied"] == []
        assert top["score_terms"]["anchor_penalty"] == 0
        assert s["tool_status"]["scientific_outcome"]["verdict"] == "supports"
        assert s["map"]["sigma_e_A3"] > 0
        # read-only: no node, candidates cached for accept
        assert _state(p)["active_node"] == before
        cache = json.loads(Path(s["cache"]).read_text(encoding="utf-8"))
        assert cache["node"] == before and cache["candidates"][0]["id"] == "c01"
        assert len(cache["candidates"][0]["sites"]) == 6
        # duplicates of the same pose (six-fold symmetric ring, many seeds)
        # were merged: every other candidate differs from the top one
        for c in cands[1:]:
            far = [a for a in c["per_atom"]
                   if _min_truth_distance(a["site_frac"], RING) > 0.4]
            assert far or c["symmetry_folded"], c["id"]

    def test_unsatisfiable_anchor_names_itself(self, project_general):
        p = project_general
        r = _search(p, anchors=[{"kind": "bond", "template_index": 0,
                                 "to_element": "Zr"}])
        assert not r.ok and "Zr" in r.error and "anchor 0" in r.error
        r = _search(p, anchors=[{"kind": "bond", "template_index": 9,
                                 "to_atom": "S1"}])
        assert not r.ok and "out of range" in r.error
        # a bond no pose can make: the ring is > 3 A from S1
        r = _search(p, anchors=[{"kind": "bond", "template_index": 0,
                                 "to_atom": "S1", "range_A": [1.6, 2.0]}])
        assert r.ok, r.error
        s = r.summary
        assert s["tool_status"]["scientific_outcome"]["verdict"] != "supports"
        if s["candidates"]:
            top = s["candidates"][0]
            assert top["constraints_satisfied"][0]["satisfied"] is False
            assert top["constraints_satisfied"][0]["label"].startswith("bond template[0]")
            assert top["score_terms"]["anchor_penalty"] > 0
            assert "anchor" in " ".join(s["tool_status"]["scientific_outcome"]["reasons"])

    def test_on_peak_anchor_is_honoured(self, project_general):
        p = project_general
        r0 = _search(p)
        assert r0.ok, r0.error
        # the peak nearest to a true ring atom (session table, as the tool used)
        peaks = p.session.flags.get("diff_map_peaks") or []
        if not peaks:
            from crystalpilot.tools.refinement_tools import _difference_map_analysis
            peaks = _difference_map_analysis(p.session, p.session.model, n_peaks=60)["peaks"]
        k = min(range(len(peaks)),
                key=lambda i: _sym_distance(CELL, SG, peaks[i]["site"], RING[0]))
        assert _sym_distance(CELL, SG, peaks[k]["site"], RING[0]) < 0.5
        r = _search(p, anchors=[{"kind": "on_peak", "template_index": 0,
                                 "peak_index": k, "tolerance_A": 0.5}])
        assert r.ok, r.error
        top = r.summary["candidates"][0]
        cs = top["constraints_satisfied"]
        assert len(cs) == 1 and cs[0]["satisfied"] is True and cs[0]["d_A"] <= 0.5
        assert r.summary["tool_status"]["scientific_outcome"]["verdict"] == "supports"

    def test_region_seeds_find_the_ring_without_peaks(self, project_general):
        r = _search(project_general, use_peaks=False,
                    region={"center": list(GUEST_CENTRE), "radius_A": 1.5},
                    n_random_seeds=400, n_refine=30)
        assert r.ok, r.error
        s = r.summary
        assert s["n_seeds"] == 400
        top = s["candidates"][0]
        assert top["seed"] == {"region": "random pose"}
        for a in top["per_atom"]:
            assert _min_truth_distance(a["site_frac"], RING) <= 0.45, a
        assert top["n_geometry_only"] == 0

    def test_ring_on_the_inversion_centre_folds_to_its_unique_atoms(self, project_centred):
        r = _search(project_centred)
        assert r.ok, r.error
        s = r.summary
        assert s["candidates"], s["rejected"]
        top = s["candidates"][0]
        assert top["symmetry_folded"] is not None
        assert top["symmetry_folded"]["n_placed"] == 6
        assert top["symmetry_folded"]["n_unique"] == 3
        assert len(top["per_atom"]) == 3
        for a in top["per_atom"]:
            assert _min_truth_distance(a["site_frac"], CENTRE_RING) <= 0.4, a
            assert a["evidence"] == "direct_peak", a
            assert a["on_special_position"] is False
        # the folded halves are not counted twice: the cache carries 3 sites
        cache = json.loads(Path(s["cache"]).read_text(encoding="utf-8"))
        assert len(cache["candidates"][0]["sites"]) == 3

    def test_budget_exhaustion_returns_partial(self, project_general):
        r = _search(project_general, timeout_s=0.001)
        assert r.ok, r.error
        assert "timeout" in r.summary
        assert r.summary["budget"].get("stopped_by") == "timeout"
        assert r.summary["tool_status"]["execution"] == "timeout"


# ==========================================================================
class TestAccept:
    def test_accept_makes_one_node_with_shared_fvar_part_and_eadp(self, project_general):
        p = project_general
        r = _search(p)
        assert r.ok, r.error
        before = _state(p)
        n_before = p.session.model.scatterers().size()
        a = p.invoke_tool("accept_fragment_pose", {
            "candidate_id": "c01", "occupancy": 0.3, "part": 1, "eadp": True})
        assert a.ok, a.error
        s = a.summary
        assert len(s["added"]) == 6 and s["fvar_index"] == 2 and s["part"] == 1
        assert s["labels"] == [f"C{i}" for i in range(1, 7)]
        assert s["cards_added"] == ["EADP " + " ".join(s["labels"])]
        assert s["tool_status"]["scientific_outcome"]["verdict"] == "supports"
        assert p.session.model.scatterers().size() == n_before + 6
        after = _state(p)
        assert after["active_node"] != before["active_node"]
        assert after["seq"] == before["seq"] + 1
        assert s["node"] == after["active_node"]
        flags = p.session.flags
        g = flags["disorder_groups"][-1]
        assert g["fvar_index"] == 2 and g["value"] == 0.3
        assert [m["label"] for m in g["members"]] == s["labels"]
        assert all(m["part"] == 1 for m in g["members"])
        assert flags["effective_cards"] == s["cards_added"]
        res = (p.nodes.node_dir(after["active_node"]) / "model.res").read_text(
            encoding="utf-8")
        assert "PART 1" in res and "EADP C1 C2 C3 C4 C5 C6" in res
        fvar_line = next(ln for ln in res.splitlines() if ln.startswith("FVAR"))
        assert any(abs(float(x) - 0.3) < 1e-6 for x in fvar_line.split()[1:])
        # the atoms sit where the data put the ring
        for row in s["added"]:
            assert _min_truth_distance(row["site"], RING) <= 0.4, row
        # the cache belongs to the previous node: a second accept is refused
        again = p.invoke_tool("accept_fragment_pose", {"candidate_id": "c01"})
        assert not again.ok and "rerun search_fragment_pose" in again.error
        assert p.session.model.scatterers().size() == n_before + 6
        # the shared free variable is not a split: undo says so
        u = p.invoke_tool("model_disorder", {"undo": "fvar2"})
        assert not u.ok and "accept_fragment_pose" in u.error
        # deleting a member clears its PART / group record (WP3 hygiene)
        d = p.invoke_tool("edit_atoms", {"operations": [
            {"action": "delete", "atoms": ["C6"]}]})
        assert d.ok, d.error
        members = [m["label"] for m in p.session.flags["disorder_groups"][-1]["members"]]
        assert members == s["labels"][:5]
        assert d.summary["cards_pruned"] == s["cards_added"]

    def test_accept_without_shared_occupancy_uses_parts_extra(self, project_general):
        p = project_general
        assert _search(p).ok
        a = p.invoke_tool("accept_fragment_pose", {
            "candidate_id": "c01", "occupancy": 0.3, "shared_occupancy": False,
            "part": -1})
        assert a.ok, a.error
        assert a.summary["fvar_index"] is None
        assert "disorder_groups" not in p.session.flags or not p.session.flags["disorder_groups"]
        assert p.session.flags["parts_extra"] == {lb: -1 for lb in a.summary["labels"]}
        assert all(abs(sc.occupancy - 0.3) < 1e-9 for sc in p.session.model.scatterers()
                   if sc.label in a.summary["labels"])

    def test_accept_refuses_unknown_or_stale(self, project_general, tmp_path):
        p = project_general
        r = p.invoke_tool("accept_fragment_pose", {"candidate_id": "c01"})
        assert not r.ok and "run the search first" in r.error
        assert _search(p).ok
        r = p.invoke_tool("accept_fragment_pose", {"candidate_id": "c99"})
        assert not r.ok and "c99" in r.error and "c01" in r.error
        r = p.invoke_tool("accept_fragment_pose", {"candidate_id": "c01", "occupancy": 1.5})
        assert not r.ok and "0.01..1.0" in r.error


# ==========================================================================
class TestRegistration:
    def test_tools_are_registered_and_classified(self):
        from crystalpilot.mcp.server import READ_ONLY_TOOLS
        from crystalpilot.refine.registry import MUTATING_TOOLS, refinement_registry
        from crystalpilot.refine.tools_extra import register_refine_tools
        from crystalpilot.tools.budget import BUDGET_PARAMS
        from crystalpilot.workbench.agents_md import render_agents_md
        reg = refinement_registry(None)
        register_refine_tools(reg, None)
        names = set(reg.names())
        assert {"search_fragment_pose", "accept_fragment_pose"} <= names
        assert "search_fragment_pose" in READ_ONLY_TOOLS
        assert "accept_fragment_pose" in MUTATING_TOOLS
        assert "search_fragment_pose" not in MUTATING_TOOLS
        assert BUDGET_PARAMS["search_fragment_pose"]["timeout_s"] == 600.0
        text = render_agents_md()
        assert "search_fragment_pose" in text and "accept_fragment_pose" in text

    def test_pure_helpers(self):
        from crystalpilot.refine.tools_pose import (evidence_class, kabsch,
                                                     rotation_matrix,
                                                     template_triples)
        P = np.array([[0, 0, 0], [1.5, 0, 0], [0, 1.5, 0], [0, 0, 1.5]], float)
        R = rotation_matrix([0.3, -0.2, 0.5])
        Q = P @ R.T + np.array([1.0, 2.0, 3.0])
        R2, t2, rms = kabsch(P, Q)
        assert rms < 1e-9 and np.allclose(R2, R) and np.allclose(t2, [1, 2, 3])
        assert evidence_class(3.0) == "direct_peak"
        assert evidence_class(1.2) == "weak_density"
        assert evidence_class(0.9) == "geometry_only"
        tri = template_triples(P)
        assert (0, 1, 2) in tri and len(tri) == 4
        collinear = np.array([[0, 0, 0], [1.5, 0, 0], [3.0, 0, 0]], float)
        assert template_triples(collinear) == []

    def test_conformer_library_prunes_duplicates(self):
        from crystalpilot.refine.tools_pose import fragment_conformers
        benz = fragment_conformers(BENZENE, n_conformers=8)
        assert benz["n_rotatable"] == 0 and len(benz["conformers"]) == 1
        assert benz["elements"] == ["C"] * 6
        flex_ = fragment_conformers("OC(=O)CCc1ccccc1", n_conformers=6)
        assert flex_["n_rotatable"] >= 3
        assert 1 <= len(flex_["conformers"]) <= 6
        assert len(flex_["rmsd_to_reference"]) == len(flex_["conformers"])
        assert flex_["rmsd_to_reference"][0] == 0.0
