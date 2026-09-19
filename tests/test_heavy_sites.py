"""audit_heavy_sites (pa1 backflow, P1-10): evidence, edge flag, readiness.

pa1 hex-l1-r1 typed a Zr6 node Zn after two R-vs-Z rounds on an unmasked,
incomplete model at lambda = 0.68883 A - the Zr K edge, where f'(Zr) =
-9 e makes Zr scatter like Zn. The audit must (1) put Zr into the
candidate set from geometry alone, (2) flag the edge from the wavelength,
(3) read a positive residual ON the site as "typed too light", (4) refuse
to call an R-vs-Z comparison meaningful on an incomplete model, and (5)
never touch the model.
"""
from __future__ import annotations

import math
from types import SimpleNamespace

import pytest
from cctbx import crystal, xray
from cctbx.array_family import flex

from crystalpilot.core.dataset import ReflectionDataset
from crystalpilot.pipeline.session import SolveSession
from crystalpilot.refine.tools_heavysites import (AuditHeavySites,
                                                  _geometry_verdict,
                                                  anomalous_terms)
from crystalpilot.tools.base import ToolContext

ZR_EDGE_LAMBDA = 0.68883      # pa1 synchrotron wavelength = Zr K edge
MO_LAMBDA = 0.71073


class _Store:
    def record(self, *a, **k):
        return None

    def log(self, *a, **k):
        return None

    def emit(self, *a, **k):
        return SimpleNamespace(event_id="ev")


def _cube_site(cell: float, n_c: int = 10):
    """One metal at the cell centre, eight O at 2.20 A (cube vertices) and
    n_c carbons parked away from the node - a Zr6-node-like sphere (CN 8,
    M-O 2.20 A: inside the Zr window 2.05-2.30, outside Zn 1.95-2.10)."""
    atoms = [("M1", (0.5, 0.5, 0.5), 0.010)]
    r = 2.20 / math.sqrt(3.0)
    k = 0
    for sx in (-1, 1):
        for sy in (-1, 1):
            for sz in (-1, 1):
                k += 1
                atoms.append((f"O{k}", tuple(0.5 + s * r / cell
                                             for s in (sx, sy, sz)), 0.030))
    # carbons on a line along x at y=z=0.15 (well away from the node)
    for j in range(n_c):
        atoms.append((f"C{j + 1}", (0.05 + 0.09 * j, 0.15, 0.15), 0.040))
    return atoms


def _structure(cell: float, metal: str, atoms=None):
    cs = crystal.symmetry(unit_cell=(cell, cell, cell, 90, 90, 90),
                          space_group_symbol="P 1")
    xs = xray.structure(crystal_symmetry=cs)
    for lbl, site, u in (atoms or _cube_site(cell)):
        el = metal if lbl.startswith("M") else lbl[0]
        xs.add_scatterer(xray.scatterer(label=lbl, site=site, u=u,
                                        scattering_type=el, occupancy=1.0))
    xs.scattering_type_registry(table="it1992")
    return xs


def _intensities(xs, wavelength: float, d_min: float = 0.85):
    """Fc^2 of `xs` WITH the anomalous terms at `wavelength` - what a real
    crystal of that composition scatters."""
    xs_t = xs.deep_copy_scatterers()
    xs_t.set_inelastic_form_factors(wavelength, "sasaki")
    fc = xs_t.structure_factors(d_min=d_min, algorithm="direct").f_calc()
    ii = fc.as_intensity_array()
    return ii.customized_copy(
        sigmas=flex.double(ii.size(), 1.0)).set_observation_type_xray_intensity()


def _session(model_xs, data_xs=None, wavelength=MO_LAMBDA, with_data=True):
    ses = SolveSession(dataset=ReflectionDataset(intensities=None,
                                                 wavelength=wavelength))
    ses.model = model_xs
    ses.symmetry = model_xs.crystal_symmetry()
    if with_data:
        ses.fo_sq = _intensities(data_xs or model_xs, wavelength or MO_LAMBDA)
    return ses


def _run(ses, project=None, **params):
    tool = AuditHeavySites(project or SimpleNamespace(session=ses))
    return tool.run(ToolContext(store=_Store(), session=ses), **params)


# ---------------------------------------------------------------- physics

def test_zr_k_edge_flagged_from_wavelength_alone():
    terms = anomalous_terms(["Zr", "Zn", "Cu", "Fe", "Cd"], ZR_EDGE_LAMBDA)
    zr = terms["Zr"]
    assert "edge_at_lambda" in zr["flags"] and "strong_fp" in zr["flags"]
    assert zr["fp"] < -8.0                       # Sasaki: -9.04 e
    assert abs(zr["edge_A"] - ZR_EDGE_LAMBDA) / ZR_EDGE_LAMBDA < 0.001
    assert 30 <= zr["z_eff"] <= 32               # scatters like Zn (30)
    for el in ("Zn", "Cu", "Fe"):
        assert terms[el]["flags"] == []
    # Mo K-alpha: Zr is off its edge, no flag
    assert "edge_at_lambda" not in anomalous_terms(["Zr"], MO_LAMBDA)["Zr"]["flags"]


def test_geometry_windows_separate_zr_from_zn_and_handle_cu_jahn_teller():
    donors8 = [("O", 2.20)] * 8
    assert _geometry_verdict("Zr", 8, donors8)["status"] == "fits"
    zn = _geometry_verdict("Zn", 8, donors8)
    assert zn["status"] == "outside"
    assert zn["per_donor"]["O"]["fit"] == "outside"
    assert zn["cn"]["fit"] == "outside"          # Zn CN window 3-6
    # Cu 4+2: four equatorial 1.95 + two axial 2.40 is a textbook Cu(II)
    cu = _geometry_verdict("Cu", 6, [("O", 1.95)] * 4 + [("O", 2.40)] * 2)
    assert cu["status"] == "fits"
    assert cu["jahn_teller_axial"]["fit"] == "fits"
    assert cu["per_donor"]["O"]["mean"] == 1.95  # axial excluded from the mean


# ---------------------------------------------------------------- the tool

def test_zr_site_typed_zn_gets_zr_candidate_and_too_light_residual():
    # data from a Zr crystal at Mo K-alpha; model says Zn at the same site
    cell = 10.0
    truth = _structure(cell, "Zr")
    model = _structure(cell, "Zn")
    ses = _session(model, truth, wavelength=MO_LAMBDA)
    r = _run(ses)
    assert r.ok, r.error
    s = r.summary
    assert s["n_sites"] == 1
    site = s["sites"][0]
    assert site["label"] == "M1" and site["element"] == "Zn" and site["cn"] == 8
    assert 2.19 <= site["bonds"]["mean"] <= 2.21
    cands = {c["element"]: c for c in site["candidates"]}
    # Zr entered the candidate set from geometry alone (pa1: it never did)
    assert "Zr" in cands and cands["Zr"]["geometry"] == "fits"
    assert cands["Zn"]["geometry"] == "outside"
    assert site["candidates"][0]["element"] != "Zn"
    assert cands["Zr"]["evidence_score"] > cands["Zn"]["evidence_score"]
    # 7 missing electrons show up as a positive residual ON the site
    assert site["residual"]["rho_at_site"] > 1.0
    assert "偏轻" in site["residual_note"] or "偏少" in site["residual_note"]
    el = site["electrons"]
    # the scale factor absorbs most of the 6.7 e mismatch: only the sign
    # of the calibrated estimate is trustworthy, and the note says so
    assert el["delta_e_from_residual"] > 0
    assert el["observed_estimate"] > el["modelled_occ_x_z_eff"]
    assert "只看符号" in el["note"]
    assert "位点残差方向一致" in cands["Zr"]["evidence"]
    assert any("残差估计" in e for e in cands["Zr"]["evidence"])
    assert cands["Zr"]["delta_e_expected"] > 5
    # Cu-O typical is 1.93-2.00 A: Cu is rightly absent from the default
    # candidates of a 2.20 A site; asked for explicitly it is within 2 e
    # of Zn, so the residual cannot separate the two
    assert "Cu" not in cands
    r2 = _run(ses, candidates=["Zn", "Cu", "Zr"])
    cu = {c["element"]: c for c in r2.summary["sites"][0]["candidates"]}["Cu"]
    assert cu["geometry"] == "outside"
    assert any("不可区分" in e for e in cu["evidence"])
    # Mo K-alpha: f'(Zr) = -3 e is an R caveat, not a direction blocker
    assert "fp_direction_note" not in site
    assert s["residual_map"]["anomalous_applied"] is True
    # the tally is evidence, never a verdict - said in the statement and
    # on the default candidate list, with the chemistry-first rule
    assert any("证据不是判决" in line for line in s["statement"])
    assert any("元素身份由化学定" in line for line in s["statement"])
    assert "不是判决" in site["candidates_note"]


def test_edge_wavelength_warning_and_engine_note():
    cell = 10.0
    truth = _structure(cell, "Zr")
    model = _structure(cell, "Zn")
    ses = _session(model, truth, wavelength=ZR_EDGE_LAMBDA)
    r = _run(ses)
    assert r.ok, r.error
    an = r.summary["anomalous"]
    assert an["wavelength_A"] == ZR_EDGE_LAMBDA
    assert "Zr" in an["edge_at_lambda"]
    assert any("Zr" in w and "吸收边" in w for w in an["warnings"])
    assert "DISP" in an["engines"]["run_shelxl"]
    # at the edge Zr scatters like Zn: the residual can no longer separate
    # them, and the tool must say the comparison needs f'
    site = r.summary["sites"][0]
    zr = {c["element"]: c for c in site["candidates"]}["Zr"]
    assert abs(zr["z_eff"] - 31) < 1.5
    assert zr["geometry"] == "fits"
    assert any("f'" in e for e in zr["evidence"])
    # the f' spike makes the central residual NEGATIVE on a Zr site typed
    # Zn: direction heuristics must be voided, not scored
    assert site["residual"]["rho_at_site"] < -1.0
    assert "fp_direction_note" in site
    assert all("方向一致" not in e and "方向相反" not in e
               for c in site["candidates"] for e in c["evidence"])
    assert any("f'" in c for c in r.summary["readiness"]["cautions"])
    assert any("Zr" in line for line in r.summary["statement"])


def test_not_ready_on_incomplete_unmasked_model_with_reasons():
    # 19 atoms in a 1000 A^3 cell: far below the 18 A^3/atom expectation,
    # no mask, no refinement metrics -> R-vs-Z is refused with reasons
    ses = _session(_structure(10.0, "Zr"), wavelength=MO_LAMBDA)
    ses.flags["weights"] = {"a": 0.1, "b": 0.0}
    r = _run(ses)
    assert r.ok, r.error
    rd = r.summary["readiness"]
    assert rd["ready_for_r_vs_z"] is False
    assert any("模型只占" in b for b in rd["blockers"])
    assert any("溶剂既未掩膜也未建模" in b for b in rd["blockers"])
    assert any("WGHT" in c for c in rd["cautions"])
    assert any("H 未放置" in c for c in rd["cautions"])
    assert "未就绪" in rd["verdict"] and "hex-l1-r1" in rd["verdict"]
    assert rd["checks"]["completeness"]["ratio"] < 0.7


def test_ready_on_dense_complete_model():
    # 19 atoms in a 7 A cube (343 A^3 -> 19 expected): complete, dense,
    # correct element -> no blockers; cautions may remain (no metrics)
    cell = 7.0
    xs = _structure(cell, "Zr")
    ses = _session(xs, wavelength=MO_LAMBDA)
    ses.flags["weights"] = {"a": 0.05, "b": 1.2}
    ses.flags["h_riding_meta"] = {"per_carrier": [{"carrier": "C1"}]}
    r = _run(ses)
    assert r.ok, r.error
    rd = r.summary["readiness"]
    assert rd["blockers"] == []
    assert rd["ready_for_r_vs_z"] is True
    assert "不能推翻化学" in rd["verdict"]
    site = r.summary["sites"][0]
    # correct element: residual on the site is flat
    assert abs(site["residual"]["rho_at_site"]) < 0.5
    assert "residual_note" not in site
    assert rd["checks"]["weights"]["default_scheme"] is False


def test_far_unmodelled_density_blocks():
    # data contain an extra heavy atom the model lacks -> far residual peak
    cell = 7.0
    atoms = _cube_site(cell) + [("Br1", (0.85, 0.85, 0.85), 0.03)]
    truth = _structure(cell, "Zr", atoms)
    model = _structure(cell, "Zr")
    ses = _session(model, truth, wavelength=MO_LAMBDA)
    r = _run(ses)
    assert r.ok, r.error
    rd = r.summary["readiness"]
    assert any("未建模密度" in b for b in rd["blockers"])
    assert rd["checks"]["completeness"]["largest_far_peak"]["height"] > 1.5


def test_candidates_param_validated_and_respected():
    ses = _session(_structure(10.0, "Zr"), wavelength=MO_LAMBDA)
    bad = _run(ses, candidates=["Zr", "Xx"])
    assert not bad.ok and "Xx" in bad.error
    r = _run(ses, candidates=["Zn", "Zr", "Cu"])
    assert r.ok
    assert [c["element"] for c in sorted(r.summary["sites"][0]["candidates"],
                                         key=lambda c: c["Z"])] == \
        ["Cu", "Zn", "Zr"]
    assert "candidates_note" not in r.summary["sites"][0]


def test_unknown_wavelength_skips_anomalous_block_instead_of_assuming():
    ses = _session(_structure(10.0, "Zr"), wavelength=None)
    r = _run(ses)
    assert r.ok, r.error
    an = r.summary["anomalous"]
    assert an["wavelength_A"] is None and "skipped" in an
    assert "elements" not in an
    assert any("波长未知" in line for line in r.summary["statement"])
    assert any("波长未知" in c for c in r.summary["readiness"]["cautions"])


def test_no_data_degrades_gracefully_and_ueq_direction():
    # no reflections: residual block skipped, Ueq evidence still works.
    # M1 U = 0.001 against O donors at 0.030 -> collapsed = typed too light
    atoms = [("M1", (0.5, 0.5, 0.5), 0.001)] + _cube_site(10.0)[1:]
    ses = _session(_structure(10.0, "Zn", atoms), wavelength=MO_LAMBDA,
                   with_data=False)
    r = _run(ses)
    assert r.ok, r.error
    assert r.summary["residual_map"]["skipped"] == "no reflection data in session"
    site = r.summary["sites"][0]
    assert "residual" not in site
    assert "塌陷" in site["ueq_note"]
    zr = {c["element"]: c for c in site["candidates"]}["Zr"]
    assert "Ueq 方向一致" in zr["evidence"]


def test_read_only():
    truth = _structure(10.0, "Zr")
    model = _structure(10.0, "Zn")
    ses = _session(model, truth, wavelength=ZR_EDGE_LAMBDA)
    before = [(sc.label, sc.scattering_type, tuple(sc.site), sc.fp, sc.fdp,
               sc.u_iso) for sc in ses.model.scatterers()]
    r = _run(ses)
    assert r.ok
    after = [(sc.label, sc.scattering_type, tuple(sc.site), sc.fp, sc.fdp,
              sc.u_iso) for sc in ses.model.scatterers()]
    assert before == after          # f' applied on a copy, never in place
    assert "f_mask" not in ses.flags


def test_no_heavy_sites_is_a_clean_result():
    atoms = [("C1", (0.1, 0.1, 0.1), 0.03), ("O1", (0.1, 0.1, 0.24), 0.03)]
    ses = _session(_structure(10.0, "C", atoms), wavelength=MO_LAMBDA,
                   with_data=False)
    r = _run(ses)
    assert r.ok and r.summary["n_sites"] == 0
    assert any("没有 Z" in line for line in r.summary["statement"])


# ---------------------------------------------------------------- registry

def test_registered_read_only_and_not_mutating():
    from crystalpilot.mcp.server import READ_ONLY_TOOLS
    from crystalpilot.refine.registry import MUTATING_TOOLS, refinement_registry
    from crystalpilot.refine.tools_analysis import register_analysis_tools
    reg = refinement_registry(None)
    register_analysis_tools(reg, None)
    assert "audit_heavy_sites" in reg.names()
    assert "audit_heavy_sites" in READ_ONLY_TOOLS
    assert "audit_heavy_sites" not in MUTATING_TOOLS
    spec = reg.get("audit_heavy_sites")
    assert set(spec.params_schema["properties"]) == {
        "node_id", "candidates", "z_min", "radius_A", "n_peaks"}


# ---------------------------------------------------------------- real data

REPO = __import__("pathlib").Path(__file__).resolve().parents[1]
SJTU9 = (REPO / "benchmark" / "data" /
         "重复SJTU-9_SJTU-9_or_post_晶体数据_原始SJTU-9_olex2_temp_sjtu-9")


@pytest.mark.skipif(not SJTU9.exists(), reason="SJTU-9 case missing")
def test_live_project_and_node_id_on_zr_mof(tmp_path):
    import json
    import shutil

    from crystalpilot.refine.project import RefineProject
    d = tmp_path / "proj"
    d.mkdir()
    shutil.copy(SJTU9 / "hkl.hkl", d / "crystal.hkl")
    shutil.copy(SJTU9 / "ref_res.res", d / "start.res")
    (d / "context.json").write_text(json.dumps({
        "data": {"hkl": "crystal.hkl", "start_model": "start.res"}}),
        encoding="utf-8")
    p = RefineProject(d)
    p.open()
    r = p.invoke_tool("audit_heavy_sites", {})
    assert r.ok, r.error
    s = r.summary
    zr_rows = [row for row in s["sites"] if row["element"] == "Zr"]
    assert zr_rows, s["site_summaries"]
    for row in zr_rows:
        assert row["cn"] >= 6
        cands = {c["element"]: c for c in row["candidates"]}
        assert cands["Zr"]["geometry"] in ("fits", "borderline")
        assert "residual" in row
    assert s["anomalous"]["wavelength_A"] is not None
    # the same audit on the stored start node, read-only, no checkout
    active = p.nodes.state()["active_node"]
    r2 = p.invoke_tool("audit_heavy_sites", {"node_id": active})
    assert r2.ok, r2.error
    assert r2.summary["source"]["node"] == active
    assert r2.summary["n_sites"] == s["n_sites"]
    assert p.nodes.state()["active_node"] == active
