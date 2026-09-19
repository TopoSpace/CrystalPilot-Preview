"""Grader robustness found by reg1-ext2 (2026-09-04).

Three defects, three fixtures:

  * hsl  - the delivered CIF named `P 21 21 21` beside the operators of
    `P 21 21 21 (a+1/4,b,c-1/4)`. iotbx refused it, the gemmi fallback
    took the NAME, and a perfect structure (13/13, rms 0.001 A) was graded
    "framework not reproduced". The operator loop must win, the conflict
    must be REPORTED, and the framework comparison must survive it.
  * dbu  - 26/28 reference non-H atoms matched; the two misses were the
    0.265-occupancy minor component. "framework not reproduced" is the
    wrong sentence for that.
  * nm   - "a better node existed: n0012 R1 0.0807 vs delivered 0.0948",
    where n0012 was a P1 descent (74 atoms / 414 parameters) against the
    delivered P-1 model (37 / 207). Rejecting it was right.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from crystalpilot.benchmark import grade as G  # noqa: E402


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #

def _xs(symbol, cell, sites, cb=None):
    from cctbx import crystal, sgtbx, xray
    info = sgtbx.space_group_info(symbol)
    if cb:
        info = info.change_basis(sgtbx.change_of_basis_op(cb))
    xs = xray.structure(crystal_symmetry=crystal.symmetry(
        unit_cell=cell, space_group_info=info))
    for lab, el, site, occ in sites:
        xs.add_scatterer(xray.scatterer(label=lab, scattering_type=el,
                                        site=site, u=0.02, occupancy=occ))
    return xs


def _cif(xs, path, r1=0.04, n_params=50):
    from crystalpilot.report.cif import structure_to_cif
    return structure_to_cif(xs, path, z=4, stats={
        "r1_strong": r1, "wr2": 0.10, "goof": 1.05, "n_params": n_params})


def _fcf(r1_target: float) -> str:
    fo = 100.0
    fc = (fo ** 0.5 * (1 - r1_target)) ** 2
    return "\n".join(f"   {i}   0   0 {fc:9.2f} {fo:9.2f}      1.00"
                     for i in range(1, 11)) + "\n"


_RES = """\
TITL synthetic
CELL 0.71073 10.000 11.000 12.000 90.000 90.000 90.000
ZERR 4 0.001 0.001 0.001 0.0 0.0 0.0
LATT -1
SFAC C N O
UNIT 8 4 8
HKLF 4
END
"""


def _delivery(tmp_path, cif_text, r1=0.04):
    proj = tmp_path / "proj"
    d = proj / "CrystalPilot Results" / "task_1"
    d.mkdir(parents=True)
    (d / "final.cif").write_text(cif_text, encoding="utf-8")
    (d / "final.fcf").write_text(_fcf(r1), encoding="utf-8")
    (d / "final.res").write_text(_RES, encoding="utf-8")
    (d / "REPORT.json").write_text(json.dumps(
        {"metrics": {"r1_strong": r1}, "final_node": "n0016",
         "model": {"n_atoms": 5}, "unresolved": []}), encoding="utf-8")
    (d / "checkcif.json").write_text(json.dumps({"counts": {}, "alerts": []}),
                                     encoding="utf-8")
    (d / "VALIDATION.md").write_text("# VALIDATION\n", encoding="utf-8")
    (d / "SUMMARY.md").write_text("# SUMMARY\n", encoding="utf-8")
    return proj


def _grade(proj, ref, tmp_path, name="out"):
    return G.grade_delivery(proj, reference=ref, out_dir=tmp_path / name,
                            run_checkcif=False, run_reproduce=False)


P212121_CELL = (9.0, 11.0, 13.0, 90, 90, 90)
#: a BONDED chain (~1.45 A steps): the reference layer's solvent-fairness
#: filter keeps only the largest bonded fragment, so scattered atoms would
#: measure the filter instead of the fix
P212121_SITES = [("O1", "O", (0.100, 0.200, 0.150), 1.0),
                 ("C1", "C", (0.261, 0.200, 0.150), 1.0),
                 ("C2", "C", (0.422, 0.200, 0.150), 1.0),
                 ("N1", "N", (0.422, 0.332, 0.150), 1.0),
                 ("O2", "O", (0.422, 0.200, 0.262), 1.0)]
#: two split sites hanging off that chain, PART-labelled
P212121_DISORDER = [("C5A", "C", (0.583, 0.200, 0.150), 1.0),
                    ("C5B", "C", (0.583, 0.240, 0.170), 1.0),
                    ("C6A", "C", (0.422, 0.332, 0.262), 1.0),
                    ("C6B", "C", (0.400, 0.360, 0.270), 1.0)]
#: twenty more ordered atoms bonded to that chain (1.45 A steps along b
#: and c), so that "everything but the split sites" is >= the 0.85
#: match-fraction floor of `framework_reproduced_disorder_incomplete`
#: (dbu was 26/28; a 5/9 toy would be graded as a missing framework)
P212121_CHAIN_EXT = (
    [(f"C{10 + i}", "C", (0.100, 0.332 + 0.132 * i, 0.150), 1.0)
     for i in range(5)]
    + [(f"C{20 + i}", "C", (0.422, 0.200, 0.374 + 0.112 * i), 1.0)
       for i in range(5)]
    + [(f"C{30 + i}", "C", (0.100, 0.200, 0.262 + 0.112 * i), 1.0)
       for i in range(5)]
    + [(f"C{40 + i}", "C", (0.422, 0.464 + 0.132 * i, 0.150), 1.0)
       for i in range(4)]
    + [("C50", "C", (0.100, 0.332, 0.262), 1.0)])


# --------------------------------------------------------------------------- #
# 1. hsl: a symbol that contradicts the operator loop
# --------------------------------------------------------------------------- #

def _lying_shifted_cif(tmp_path) -> str:
    """The hsl defect, rebuilt: a model in P 21 21 21 (a+1/4,b,c-1/4)
    carrying the REFERENCE-setting name beside its shifted operators."""
    from cctbx import sgtbx
    ref = _xs("P 21 21 21", P212121_CELL, P212121_SITES)
    shifted = ref.change_basis(sgtbx.change_of_basis_op("x-1/4,y,z+1/4"))
    text = _cif(shifted, tmp_path / "shift.cif").read_text(encoding="utf-8")
    assert "_space_group_name_H-M_alt     ?" in text      # written honestly
    text = text.replace("_space_group_name_H-M_alt     ?",
                        "_space_group_name_H-M_alt     'P 21 21 21'")
    text = re.sub(r"^_space_group_name_Hall.*$",
                  "_space_group_name_Hall        ?", text, flags=re.M)
    return text


def test_symbol_operator_conflict_is_reported_but_does_not_poison_emma(
        tmp_path):
    ref_cif = _cif(_xs("P 21 21 21", P212121_CELL, P212121_SITES),
                   tmp_path / "ref.cif")
    proj = _delivery(tmp_path, _lying_shifted_cif(tmp_path))
    r = _grade(proj, ref_cif, tmp_path)

    assert r["cif_symmetry_inconsistent"] is True
    rl = r["reference_layer"]
    assert rl["cif_symmetry_inconsistent"] is True
    # the setting is named for what it is, and the structure still matches
    assert rl["sg_agent"] == "P 21 21 21 (a+1/4,b,c-1/4)"
    assert rl["emma"]["solved"] is True
    assert rl["emma_match_fraction"] == 1.0
    assert rl["framework_verdict"] == "framework_reproduced"
    assert not any("framework not reproduced" in s
                   for s in r["grade_reasons"])
    # ... and the defect is still held against the delivery
    assert any("operator loop" in s for s in r["grade_reasons"])
    assert any("CIF symmetry inconsistent" in s for s in r["grade_reasons"])
    assert r["grade"] != "publication"


def test_the_same_delivery_named_truthfully_reaches_publication(tmp_path):
    """Control: only the NAMES differ between this and the test above."""
    from crystalpilot.io.cif_symmetry import rewrite_symmetry_tags
    ref_cif = _cif(_xs("P 21 21 21", P212121_CELL, P212121_SITES),
                   tmp_path / "ref.cif")
    honest = rewrite_symmetry_tags(_lying_shifted_cif(tmp_path))[0]
    proj = _delivery(tmp_path, honest)
    r = _grade(proj, ref_cif, tmp_path)
    assert r["cif_symmetry_inconsistent"] is False
    assert r["reference_layer"]["emma"]["solved"] is True
    assert r["grade"] == "publication"


# --------------------------------------------------------------------------- #
# 2. dbu: the misses are a disorder component
# --------------------------------------------------------------------------- #

def test_disorder_component_reasons_reads_occupancy_and_part_labels():
    xs = _xs("P 1", (12, 13, 14, 90, 90, 90), [
        ("C1", "C", (0.10, 0.10, 0.10), 1.0),
        ("C9A", "C", (0.20, 0.20, 0.20), 0.735),
        ("C13A", "C", (0.22, 0.21, 0.21), 0.265),
        ("C5A", "C", (0.40, 0.40, 0.40), 1.0),
        ("C5B", "C", (0.42, 0.41, 0.41), 1.0)])
    got = G._disorder_component_reasons(xs, ["C1", "C13A", "C5A", "C5B"])
    assert "C1" not in got                       # ordered, full occupancy
    assert "occupancy 0.265" in got["C13A"]
    assert "PART-style" in got["C5A"] and "C5B" in got["C5A"]
    assert "PART-style" in got["C5B"]


P21C_ORDERED = [("O1", "O", (0.310, 0.201, 0.107), 1.0),
                ("N1", "N", (0.104, 0.503, 0.311), 1.0),
                ("C1", "C", (0.407, 0.404, 0.402), 1.0)]
#: more ordered atoms, scattered: the diagnosis does no bonded-fragment
#: filtering, it only counts matches
P21C_MORE = [(f"C{2 + i}", "C", (0.05 + 0.09 * i, 0.62 + 0.03 * i,
                                 0.55 + 0.04 * i), 1.0) for i in range(9)]
P21C_SPLIT = [("C9A", "C", (0.221, 0.115, 0.488), 0.735),
              ("C13A", "C", (0.251, 0.140, 0.470), 0.265),
              ("C12A", "C", (0.180, 0.330, 0.260), 0.265)]


def test_framework_diagnosis_names_the_missing_disorder_component(tmp_path):
    """The dbu shape: everything matched except two partial-occupancy
    atoms of a split site (12/14 matched, above the 0.85 floor)."""
    ref = _xs("P 21/c", (10, 11, 12, 90, 95, 90),
              P21C_ORDERED + P21C_MORE + P21C_SPLIT)
    model = _xs("P 21/c", (10, 11, 12, 90, 95, 90),
                P21C_ORDERED + P21C_MORE
                + [("C9A", "C", (0.221, 0.115, 0.488), 1.0)])
    d = G._framework_diagnosis(model, ref)
    assert d["n_reference_non_h"] == 15 and d["n_matched"] == 13
    assert d["match_fraction"] == pytest.approx(13 / 15, abs=0.001)
    assert sorted(d["unmatched_reference_atoms"]) == ["C12A", "C13A"]
    assert set(d["unmatched_disorder_components"]) == {"C12A", "C13A"}
    assert d["verdict"] == "framework_reproduced_disorder_incomplete"


def test_disorder_incomplete_needs_most_of_the_reference_matched():
    """Same misses, but the model holds only 4 of 6 reference atoms: every
    miss is a disorder component, yet a third of the reference is absent -
    that is not 'the framework with an incomplete disorder model'."""
    ref = _xs("P 21/c", (10, 11, 12, 90, 95, 90), P21C_ORDERED + P21C_SPLIT)
    model = _xs("P 21/c", (10, 11, 12, 90, 95, 90),
                P21C_ORDERED + [("C9A", "C", (0.221, 0.115, 0.488), 1.0)])
    d = G._framework_diagnosis(model, ref)
    assert d["match_fraction"] == pytest.approx(0.667, abs=0.001)
    assert set(d["unmatched_disorder_components"]) == {"C12A", "C13A"}
    assert d["verdict"] == "framework_not_reproduced"
    assert "floor 0.85" in d["verdict_note"]
    assert G.DISORDER_INCOMPLETE_MIN_FRACTION == 0.85


def test_framework_not_reproduced_when_an_ordered_atom_is_missing():
    ref = _xs("P 21/c", (10, 11, 12, 90, 95, 90),
              [("O1", "O", (0.310, 0.201, 0.107), 1.0),
               ("N1", "N", (0.104, 0.503, 0.311), 1.0),
               ("C1", "C", (0.407, 0.404, 0.402), 1.0),
               ("C2", "C", (0.221, 0.115, 0.488), 1.0)])
    model = _xs("P 21/c", (10, 11, 12, 90, 95, 90),
                [("O1", "O", (0.310, 0.201, 0.107), 1.0),
                 ("N1", "N", (0.104, 0.503, 0.311), 1.0)])
    d = G._framework_diagnosis(model, ref)
    assert d["verdict"] == "framework_not_reproduced"
    assert set(d["unmatched_reference_atoms"]) >= {"C1", "C2"}


def test_grade_reports_disorder_incomplete_instead_of_not_reproduced(
        tmp_path):
    """End to end: emma says solved=false because the model cannot account
    for the reference's PART components; the grade must say WHICH atoms
    and must not call the framework wrong."""
    # the split site is a PART-labelled chloride pair: emma's heavy-atom
    # gate (Z >= Na) then says solved=false while 25/29 of the reference
    # is matched - above the 0.85 floor, so the miss is "disorder
    # incomplete", not a missing framework
    split = [("CL1A", "Cl", (0.583, 0.200, 0.150), 1.0),
             ("CL1B", "Cl", (0.583, 0.240, 0.170), 1.0)] + P212121_DISORDER[2:]
    ref_sites = P212121_SITES + P212121_CHAIN_EXT + split
    ref_cif = _cif(_xs("P 21 21 21", P212121_CELL, ref_sites),
                   tmp_path / "ref.cif")
    model = _xs("P 21 21 21", P212121_CELL,
                P212121_SITES + P212121_CHAIN_EXT)
    proj = _delivery(tmp_path, _cif(model, tmp_path / "m.cif"
                                    ).read_text(encoding="utf-8"))
    r = _grade(proj, ref_cif, tmp_path)
    rl = r["reference_layer"]
    assert rl["emma"]["solved"] is False
    assert rl["framework_verdict"] == "framework_reproduced_disorder_incomplete"
    assert rl["emma_match_fraction"] == pytest.approx(25 / 29, abs=0.01)
    assert any(s.startswith("framework_reproduced_disorder_incomplete")
               for s in r["grade_reasons"])
    assert not any("framework not reproduced" in s
                   for s in r["grade_reasons"])
    assert r["grade"] != "publication"           # still short of complete


def test_the_emma_rule_is_disclosed_with_the_verdict(tmp_path):
    ref_cif = _cif(_xs("P 21 21 21", P212121_CELL, P212121_SITES),
                   tmp_path / "ref.cif")
    model = _xs("P 21 21 21", P212121_CELL,
                [("Zz1", "C", (0.02, 0.03, 0.04), 1.0)])
    proj = _delivery(tmp_path, _cif(model, tmp_path / "m.cif"
                                    ).read_text(encoding="utf-8"))
    r = _grade(proj, ref_cif, tmp_path)
    rl = r["reference_layer"]
    assert rl["emma_framework_rule"] == G.EMMA_FRAMEWORK_RULE
    assert "recall" in rl["emma_framework_rule"]
    assert rl["framework_verdict"] == "framework_not_reproduced"
    reason = next(s for s in r["grade_reasons"]
                  if s.startswith("framework not reproduced"))
    assert "reference non-H atoms matched" in reason
    assert G.EMMA_FRAMEWORK_RULE in reason


# --------------------------------------------------------------------------- #
# 3. nm: a lower R1 that is not a better answer
# --------------------------------------------------------------------------- #

def _node(nid, r1, sg, n_params, n_atoms, branch="main", tool="refine",
          label=None):
    return {"id": nid, "parent": None, "tool": tool, "branch": branch,
            "metrics": ({"label": label or f"{tool} {nid}", "r1_strong": r1,
                         "n_params": n_params} if r1 is not None else None),
            "metrics_current": r1 is not None, "mask": None,
            "data": {"space_group": sg},
            "model": {"n_atoms": n_atoms}}


NM_NODES = {
    "n0008": _node("n0008", 0.0951, "P -1", 207, 37, "pbar1_solve"),
    "n0012": _node("n0012", 0.0807, "P 1", 414, 74, "p1_trial",
                   label="P1 fully independent anisotropic trial"),
    "n0013": _node("n0013", 0.0948, "P -1", -1, 37, "pbar1_solve",
                   tool="run_shelxl"),
    "n0016": _node("n0016", None, "P -1", None, 37, "pbar1_solve", "set_z"),
}


def test_a_p1_descent_is_not_a_better_node():
    nt = G.node_tree_report(NM_NODES, 0.0948, "n0016", delivered_sg="P -1",
                            delivered_n_params=207, delivered_n_atoms=37)
    assert nt["better_node_existed"] is False
    assert nt["best_node_id"] == "n0013"          # the best P-1 node
    skipped = {s["node"]: s for s in nt["better_nodes_skipped"]}
    assert "n0012" in skipped
    assert skipped["n0012"]["r1"] == 0.0807
    assert "space group P 1" in skipped["n0012"]["reason"]
    assert nt["delivered_model"] == {"space_group": "P -1", "n_params": 207,
                                     "n_atoms": 37}


def test_a_same_group_node_with_too_many_parameters_is_skipped():
    nodes = {
        "n1": _node("n1", 0.10, "P -1", 200, 30),
        # same group, but 400 parameters against the delivered 200
        "n2": _node("n2", 0.06, "P -1", 400, 60),
        "n3": _node("n3", 0.085, "P -1", 260, 34),
    }
    nt = G.node_tree_report(nodes, 0.10, "n1", delivered_sg="P -1",
                            delivered_n_params=200, delivered_n_atoms=30)
    assert nt["best_node_id"] == "n3"             # 260 params is within 1.5x
    assert nt["better_node_existed"] is True
    reasons = {s["node"]: s["reason"] for s in nt["better_nodes_skipped"]}
    assert "n2" in reasons and "400 parameters" in reasons["n2"]


def test_settings_of_one_group_still_compare():
    """P 21/n and P 21/c are the same group: a node in the other setting is
    a fair comparison, not a different structure."""
    nodes = {"d": _node("d", 0.10, "P 1 21/c 1", 200, 30),
             "o": _node("o", 0.07, "P 21/n", 210, 31)}
    nt = G.node_tree_report(nodes, 0.10, "d", delivered_sg="P 1 21/c 1",
                            delivered_n_params=200, delivered_n_atoms=30)
    assert nt["better_node_existed"] is True and nt["best_node_id"] == "o"
    assert not nt.get("better_nodes_skipped")


def test_missing_facts_never_disqualify_a_node():
    """A node that records neither space group nor parameters is compared
    as before - a gap in the record is not evidence against it."""
    bare = {"a": {"id": "a", "metrics": {"r1_strong": 0.10, "label": "a"},
                  "metrics_current": True, "model": {"n_atoms": 26}},
            "b": {"id": "b", "metrics": {"r1_strong": 0.05, "label": "b"},
                  "metrics_current": True, "model": {"n_atoms": 26}}}
    nt = G.node_tree_report(bare, 0.10, "a")
    assert nt["best_node_id"] == "b" and nt["better_node_existed"] is True
    assert not nt.get("better_nodes_skipped")


def test_grade_delivery_lists_the_skipped_node_with_its_reason(tmp_path):
    ref_cif = _cif(_xs("P 21 21 21", P212121_CELL, P212121_SITES),
                   tmp_path / "ref.cif")
    model_cif = _cif(_xs("P 21 21 21", P212121_CELL, P212121_SITES),
                     tmp_path / "m.cif", n_params=207)
    proj = _delivery(tmp_path, model_cif.read_text(encoding="utf-8"))
    nodes = {
        "n0016": _node("n0016", 0.0948, "P 21 21 21", 207, 5),
        "n0012": _node("n0012", 0.0807, "P 1", 414, 10, "p1_trial"),
    }
    for nid, n in nodes.items():
        nd = proj / ".crystalpilot" / "refine" / "nodes" / nid
        nd.mkdir(parents=True)
        (nd / "node.json").write_text(json.dumps(n), encoding="utf-8")
    r = _grade(proj, ref_cif, tmp_path)
    nt = r["node_tree"]
    assert nt["better_node_existed"] is False
    assert nt["delivered_model"]["space_group"] == "P 21 21 21"
    assert nt["delivered_model"]["n_params"] == 207
    assert [s["node"] for s in nt["better_nodes_skipped"]] == ["n0012"]
    assert not any(s.startswith("a better node existed")
                   for s in r["grade_reasons"])
    assert any("lower-R1 node n0012" in s for s in r["grade_reasons"])
