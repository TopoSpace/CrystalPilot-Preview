"""Two mentor-side alignment rules in grade.py.

1. The porosity verdict is PLATON's own (alerts 601/602/604/605 read back
   from its output), never a void fraction re-encoded here; with no PLATON
   result the check reports itself not_checked instead of guessing.
2. An R1 delta against the reference is only a comparison of the models
   when both were refined to the same resolution: R1 falls when weak
   high-angle data are dropped.
"""
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from crystalpilot.benchmark import grade as G
from test_grade import MINI_CIF, MINI_RES, _mk_delivery

# --------------------------------------------------------------------------- #
# 1. porosity: PLATON's verdict, read back
# --------------------------------------------------------------------------- #


def test_void_alerts_read_from_the_platon_rerun(tmp_path):
    """_checkcif_gate keeps its A/B/C alerts as 'A 602 text' strings and the
    codes only its own rerun raised as bare `rerun_only_codes`. Both are
    PLATON saying 'void'; non-void codes are left alone."""
    cc = {"available": True,
          "alerts_abc": ["B 602 VERY LARGE Solvent Accessible VOID(S)",
                         "A 601 Structure Contains Solvent Accessible VOIDS",
                         "C 220 Large Non-Solvent  C  Ueq as Compared to Neighbors"],
          "rerun_only_codes": ["604", "911"]}
    alerts, source = G._platon_void_alerts(cc, tmp_path / "final.cif")
    assert source == "platon rerun"
    assert sorted(a["code"] for a in alerts) == ["601", "602", "604"]
    by_code = {a["code"]: a for a in alerts}
    assert by_code["602"]["level"] == "B"
    assert "VERY LARGE" in by_code["602"]["text"]
    # a rerun-only code carries no level or text, only PLATON's assertion
    assert by_code["604"]["level"] is None


def test_void_alerts_fall_back_to_the_delivered_checkcif(tmp_path):
    """Without a rerun the agent's own checkcif.json is read - every level,
    because a void alert states the void is there, it is not a severity we
    re-grade."""
    cif = tmp_path / "final.cif"
    cif.write_text(MINI_CIF, encoding="utf-8")
    (tmp_path / "checkcif.json").write_text(json.dumps({"alerts": [
        {"code": "605", "type": 2, "level": "C", "text": "solvent accessible VOID"},
        {"code": "603", "type": 2, "level": "G", "text": "TOO LARGE Unit Cell"},
        {"code": "094", "type": 2, "level": "B", "text": "Ratio of Maximum"},
    ]}), encoding="utf-8")
    alerts, source = G._platon_void_alerts({"available": False}, cif)
    assert source == "delivered checkcif.json"
    # 603 says PLATON did not look; it must not be read as a void
    assert [a["code"] for a in alerts] == ["605"]
    assert alerts[0]["level"] == "C"


def test_no_platon_result_is_not_a_clean_bill(tmp_path):
    cif = tmp_path / "final.cif"
    cif.write_text(MINI_CIF, encoding="utf-8")
    assert G._platon_void_alerts(None, cif) == ([], None)
    assert G._platon_void_alerts({"available": False}, cif) == ([], None)
    # an unreadable checkcif.json is no result either, never an empty one
    (tmp_path / "checkcif.json").write_text("{not json", encoding="utf-8")
    assert G._platon_void_alerts({}, cif) == ([], None)


@pytest.mark.parametrize("source,alerts,has_mask,n_guests,expect", [
    # PLATON reported a void, nothing in the delivery answers it
    ("platon rerun", [{"code": "602"}], False, 0, True),
    ("platon rerun", [{"code": "602"}], True, 0, False),    # masked
    ("platon rerun", [{"code": "602"}], False, 2, False),   # guests modelled
    ("platon rerun", [], False, 0, False),                  # PLATON saw none
    (None, [], False, 0, None),                             # nothing to read
    (None, [], False, None, None),
    # a void stands but the model would not load: guests uncounted
    ("platon rerun", [{"code": "601"}], False, None, None),
])
def test_porosity_flag_matrix(source, alerts, has_mask, n_guests, expect):
    out = G._porosity_flag({"platon_source": source,
                            "platon_void_alerts": alerts,
                            "mask_block_in_cif": has_mask}, n_guests)
    assert out["porous_unmasked_unmodelled"] is expect
    assert out["porosity_check"] == ("not_checked" if expect is None
                                     else "platon")
    assert ("note" in out) is (expect is None)


def test_porosity_report_reports_its_platon_state_without_a_structure(tmp_path):
    """Even when the structure will not load the report must say where the
    porosity verdict came from - or that there was none."""
    cif = tmp_path / "final.cif"
    cif.write_text(MINI_CIF, encoding="utf-8")
    po = G.porosity_report(cif, None)
    assert po["skipped"] == "structure not loadable"
    assert po["platon_source"] is None and po["platon_void_alerts"] == []
    assert po["porosity_check"] == "not_checked"
    assert po["porous_unmasked_unmodelled"] is None
    assert "no PLATON result" in po["note"]

    # with PLATON's verdict in hand the negative side needs no structure
    po = G.porosity_report(cif, None, {"available": True, "alerts_abc": []})
    assert po["platon_source"] == "platon rerun"
    assert po["porous_unmasked_unmodelled"] is False
    assert po["porosity_check"] == "platon"


def test_unchecked_porosity_is_a_note_and_a_void_alert_blocks():
    """The flag drives _mentor_reasons: True blocks publication, None is
    reported as an evidence gap and blocks nothing."""
    block, notes = G._mentor_reasons({"porosity": {
        "porous_unmasked_unmodelled": True, "void_fraction": 0.79,
        "platon_void_alerts": [{"code": "602"}, {"code": "601"}]}})
    assert len(block) == 1
    assert block[0].startswith("porous delivery (PLATON void alert 601, 602")
    assert "smtbx void 79%" in block[0]
    assert notes == []

    block, notes = G._mentor_reasons({"porosity": {
        "porous_unmasked_unmodelled": None, "porosity_check": "not_checked",
        "void_fraction": 0.79, "platon_void_alerts": [],
        "note": "no PLATON result (neither an independent rerun nor a "
                "checkcif.json beside the delivery)"}})
    assert block == []
    assert len(notes) == 1
    assert notes[0].startswith("porosity not checked: no PLATON result")
    assert "smtbx void 79%" in notes[0]     # the fraction stays, as a fact

    # and a void PLATON did not report is simply not a reason at all
    block, notes = G._mentor_reasons({"porosity": {
        "porous_unmasked_unmodelled": False, "void_fraction": 0.79,
        "platon_void_alerts": []}})
    assert (block, notes) == ([], [])


def test_porosity_blocks_end_to_end_only_on_a_platon_alert(tmp_path):
    """pa1's bare framework in a 79 % void: with PLAT602 delivered beside it
    the grade carries the blocking reason; with no PLATON result the same
    delivery is a note, never a block."""
    from test_grade import POROUS_CIF
    ref = tmp_path / "ref.cif"
    ref.write_text(POROUS_CIF.replace("0.0400", "0.0380"), encoding="utf-8")

    proj = _mk_delivery(tmp_path / "a", cif=POROUS_CIF, alerts=[
        {"code": "602", "type": 2, "level": "B",
         "text": "VERY LARGE Solvent Accessible VOID(S) in Structure"}])
    r = G.grade_delivery(proj, reference=ref, out_dir=tmp_path / "oa",
                         run_checkcif=False, run_reproduce=False)
    po = r["porosity"]
    assert po["platon_source"] == "delivered checkcif.json"
    assert po["porous_unmasked_unmodelled"] is True
    assert any(s.startswith("porous delivery (PLATON void alert 602")
               for s in r["grade_reasons"])
    assert r["grade"] == "acceptable"

    # the identical 99 % void with no void alert beside it: PLATON looked
    # and said nothing, so porosity is no longer a reason at all (the one
    # remaining reason is this fixture's unrelated Cu coordination flag)
    proj = _mk_delivery(tmp_path / "b", cif=POROUS_CIF)   # no alerts at all
    r = G.grade_delivery(proj, reference=ref, out_dir=tmp_path / "ob",
                         run_checkcif=False, run_reproduce=False)
    assert r["porosity"]["platon_source"] == "delivered checkcif.json"
    assert r["porosity"]["porous_unmasked_unmodelled"] is False
    assert r["porosity"]["void_fraction"] > 0.8      # the fact still stands
    assert not any("porous" in s for s in r.get("grade_reasons") or [])

    # and with the checkcif.json gone there is no PLATON verdict to read:
    # an unknown, reported as a note, blocking nothing
    (proj / "CrystalPilot Results" / "task_1" / "checkcif.json").unlink()
    r = G.grade_delivery(proj, reference=ref, out_dir=tmp_path / "oc",
                         run_checkcif=False, run_reproduce=False)
    assert r["porosity"]["porous_unmasked_unmodelled"] is None
    assert r["porosity"]["porosity_check"] == "not_checked"
    assert any(s.startswith("porosity not checked: no PLATON result")
               for s in r["grade_reasons"])


# --------------------------------------------------------------------------- #
# 2. r1_delta needs a common resolution
# --------------------------------------------------------------------------- #

def _d(cif: str, tags: str) -> str:
    """Put resolution tags into MINI_CIF ahead of its atom loop."""
    return cif.replace("_refine_ls_R_factor_gt",
                       tags + "_refine_ls_R_factor_gt")


def test_cif_fields_d_min_direct_tag_then_bragg(tmp_path):
    p = tmp_path / "a.cif"

    p.write_text(_d(MINI_CIF, "_reflns_d_resolution_high  0.8300\n"),
                 encoding="utf-8")
    assert G._cif_fields(p)["d_min"] == pytest.approx(0.83)

    # SHELXL writes theta_max + wavelength, not a resolution: Bragg it
    p.write_text(_d(MINI_CIF, "_diffrn_radiation_wavelength  0.71073\n"
                              "_diffrn_reflns_theta_max      26.372\n"),
                 encoding="utf-8")
    assert G._cif_fields(p)["d_min"] == pytest.approx(0.80, abs=1e-3)

    # the refinement-side spelling of theta max is accepted too
    p.write_text(_d(MINI_CIF, "_diffrn_radiation_wavelength  0.71073\n"
                              "_reflns_theta_max             27.104\n"),
                 encoding="utf-8")
    assert G._cif_fields(p)["d_min"] == pytest.approx(0.78, abs=1e-3)

    # a stated resolution wins over the derived one
    p.write_text(_d(MINI_CIF, "_reflns_d_resolution_high     0.7000\n"
                              "_diffrn_radiation_wavelength  0.71073\n"
                              "_diffrn_reflns_theta_max      26.372\n"),
                 encoding="utf-8")
    assert G._cif_fields(p)["d_min"] == pytest.approx(0.70)

    # theta without a wavelength, or neither: unknown, never a guess
    p.write_text(_d(MINI_CIF, "_diffrn_reflns_theta_max  26.372\n"),
                 encoding="utf-8")
    assert G._cif_fields(p)["d_min"] is None
    p.write_text(MINI_CIF, encoding="utf-8")
    assert G._cif_fields(p)["d_min"] is None
    # '?' is not a resolution
    p.write_text(_d(MINI_CIF, "_reflns_d_resolution_high  ?\n"),
                 encoding="utf-8")
    assert G._cif_fields(p)["d_min"] is None


def _graded(tmp_path, name, agent_tags, ref_tags, agent_r1, ref_r1):
    proj = _mk_delivery(tmp_path / name,
                        cif=_d(MINI_CIF.replace("0.0400", agent_r1),
                               agent_tags),
                        r1_fcf=float(agent_r1), report_r1=float(agent_r1))
    ref = tmp_path / f"ref_{name}.cif"
    ref.write_text(_d(MINI_CIF.replace("0.0400", ref_r1), ref_tags),
                   encoding="utf-8")
    return G.grade_delivery(proj, reference=ref, out_dir=tmp_path / f"o{name}",
                            run_checkcif=False, run_reproduce=False)


D80 = "_reflns_d_resolution_high  0.8000\n"
D81 = "_reflns_d_resolution_high  0.8100\n"
D95 = "_reflns_d_resolution_high  0.9500\n"
D78 = "_reflns_d_resolution_high  0.7800\n"


def test_r1_delta_comparable_within_the_tolerance(tmp_path):
    """0.80 vs 0.81 A is the same cut for R1's purposes, so the delta scores
    exactly as before."""
    r = _graded(tmp_path, "same", D80, D81, "0.0400", "0.0380")
    rl = r["reference_layer"]
    assert (rl["d_min_agent"], rl["d_min_reference"]) == (0.80, 0.81)
    assert rl["r1_delta_comparable"] is True
    assert rl["r1_delta"] == pytest.approx(0.002, abs=1e-6)
    assert "r1_delta_incomparable" not in rl and "r1_delta_note" not in rl
    assert rl["r1_scored"] is True
    assert r["grade"] == "publication"


def test_incomparable_resolution_cannot_break_publication(tmp_path):
    """Agent 0.95 A against a 0.78 A reference: the delta (+0.02, which
    would have failed the exact-reference bar) is recorded but withdrawn as
    a criterion, the absolute R1 bar stands in, and the gap is reported."""
    r = _graded(tmp_path, "wide", D95, D78, "0.0400", "0.0200")
    rl = r["reference_layer"]
    assert (rl["d_min_agent"], rl["d_min_reference"]) == (0.95, 0.78)
    assert rl["r1_delta_comparable"] is False
    assert rl["r1_delta_incomparable"] is True
    assert rl["r1_delta"] == pytest.approx(0.02, abs=1e-6)  # still recorded
    assert rl["r1_scored"] is False
    assert "0.95" in rl["r1_delta_note"] and "0.78" in rl["r1_delta_note"]
    assert r["grade"] == "publication"
    assert any(s.startswith("r1_delta not comparable: agent d_min 0.95")
               for s in r["grade_reasons"])
    assert not any("R1 delta vs reference" in s for s in r["grade_reasons"])
    # the same delta at one resolution does block publication
    same = _graded(tmp_path, "tight", D80, D81, "0.0400", "0.0200")
    assert same["grade"] == "acceptable"
    assert any("R1 delta vs reference" in s for s in same["grade_reasons"])


def test_incomparable_resolution_cannot_make_acceptable(tmp_path):
    """The mirror image: R1 0.1050 is only acceptable because it is within
    0.02 of what the reference reached on the same data. Drop the shared
    resolution and that argument is gone - the absolute bar decides."""
    ok = _graded(tmp_path, "near", D80, D81, "0.1050", "0.0900")
    assert ok["reference_layer"]["r1_delta"] == pytest.approx(0.015, abs=1e-6)
    assert ok["grade"] == "acceptable"

    r = _graded(tmp_path, "far", D95, D78, "0.1050", "0.0900")
    assert r["reference_layer"]["r1_delta_incomparable"] is True
    assert r["grade"] == "below_bar"
    assert any("not comparable" in s and "above 0.10" in s
               for s in r["grade_reasons"])


def test_unknown_resolution_is_said_out_loud_and_changes_nothing(tmp_path):
    """A reference with no resolution field leaves the alignment unknown:
    the delta keeps scoring exactly as it did before this check existed,
    and the gap is stated rather than silently assumed away."""
    r = _graded(tmp_path, "unk", D80, "", "0.0400", "0.0380")
    rl = r["reference_layer"]
    assert rl["d_min_agent"] == 0.80 and rl["d_min_reference"] is None
    assert rl["r1_delta_comparable"] is None
    assert "r1_delta_incomparable" not in rl
    assert rl["r1_delta_note"] == ("resolution alignment not checked "
                                   "(d_min unknown on one side)")
    assert rl["r1_scored"] is True
    assert rl["r1_delta"] == pytest.approx(0.002, abs=1e-6)
    assert r["grade"] == "publication"      # unchanged from before
    assert not any("not comparable" in s for s in r.get("grade_reasons") or [])


def test_res_reference_has_no_resolution_to_compare(tmp_path):
    """A .res/.ins reference carries no resolution field at all - that is
    unknown, never 'incomparable'."""
    proj = _mk_delivery(tmp_path / "u", cif=_d(MINI_CIF, D80))
    ref = tmp_path / "ref.res"
    ref.write_text(MINI_RES, encoding="utf-8")
    r = G.grade_delivery(proj, reference=ref, out_dir=tmp_path / "ou",
                         run_checkcif=False, run_reproduce=False)
    rl = r["reference_layer"]
    assert rl["d_min_agent"] == 0.80 and rl["d_min_reference"] is None
    assert rl["r1_delta_comparable"] is None
    assert "r1_delta_incomparable" not in rl
    assert not any("not comparable" in s for s in r.get("grade_reasons") or [])
