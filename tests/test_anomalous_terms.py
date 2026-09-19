"""The anomalous terms travel with the model (round-3, 2026-09-06).

Live Zr-MOF: the data were measured at 0.68883 A, on the Zr K edge
(f' = -9.0 e). The in-process engine set the terms, the solvent mask
computed with them read 591.6 e/cell; every session rebuild from model.res
(checkout, viewer recount) dropped them, and the recount on the SAME model
read 1193.2 e/cell. One helper now sets them everywhere and both mask
products say which terms they used."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from cctbx import crystal, xray

from crystalpilot.io.shelx_writer import (anomalous_terms_of,
                                           apply_anomalous_terms)

ZR_EDGE_A = 0.68883


def _structure():
    cs = crystal.symmetry(unit_cell=(9.0, 10.0, 11.0, 90, 95, 90),
                          space_group_symbol="P 21/c")
    xs = xray.structure(crystal_symmetry=cs)
    for lab, el, site in (("Zr1", "Zr", (0.12, 0.20, 0.15)),
                          ("O1", "O", (0.30, 0.25, 0.10)),
                          ("C1", "C", (0.40, 0.35, 0.05))):
        xs.add_scatterer(xray.scatterer(label=lab, site=site,
                                        scattering_type=el, u=0.03))
    xs.scattering_type_registry(table="it1992")
    return xs


def _project(tmp_path: Path, wavelength: float) -> Path:
    from crystalpilot.io.cif_sf import write_hklf4
    from crystalpilot.io.shelx_writer import ShelxModel, write_res
    xs = _structure()
    fc = xs.structure_factors(d_min=0.85, algorithm="direct").f_calc()
    i_obs = fc.as_intensity_array()
    i_obs = i_obs.customized_copy(sigmas=0.02 * i_obs.data() + 0.5)
    d = tmp_path / "proj"
    d.mkdir(parents=True)
    write_hklf4(i_obs, d / "crystal.hkl")
    write_res(ShelxModel(xray_structure=xs, wavelength=wavelength, z=4,
                         weights=(0.1, 0.0)), d / "start.res")
    (d / "context.json").write_text(json.dumps({
        "data": {"hkl": "crystal.hkl", "start_model": "start.res"}}),
        encoding="utf-8")
    return d


def _zr(xs):
    return next(sc for sc in xs.scatterers() if sc.scattering_type == "Zr")


def test_helper_sets_sasaki_terms_and_refuses_non_xray():
    xs = _structure()
    terms = apply_anomalous_terms(xs, ZR_EDGE_A)
    assert terms["Zr"][0] == pytest.approx(-9.04, abs=0.2)
    assert terms["Zr"][1] == pytest.approx(2.77, abs=0.2)
    assert abs(terms["O"][0]) < 0.05 and abs(terms["C"][0]) < 0.05
    assert _zr(xs).fp == pytest.approx(terms["Zr"][0], abs=1e-3)
    # no wavelength / an electron beam: nothing applied, nothing touched
    assert apply_anomalous_terms(xs, None) is None
    assert apply_anomalous_terms(xs, 0.0251) is None
    assert anomalous_terms_of(xs)["Zr"] == terms["Zr"]
    # the numbers are exactly what the engine's own call sets
    ref = _structure()
    ref.set_inelastic_form_factors(ZR_EDGE_A, "sasaki")
    assert _zr(ref).fp == pytest.approx(_zr(xs).fp, abs=1e-9)
    assert _zr(ref).fdp == pytest.approx(_zr(xs).fdp, abs=1e-9)


def test_session_rebuild_and_checkout_carry_the_terms(tmp_path):
    from crystalpilot.refine.project import RefineProject
    d = _project(tmp_path, ZR_EDGE_A)
    p = RefineProject(d)
    p.open()
    assert _zr(p.session.model).fp == pytest.approx(-9.04, abs=0.2)
    node = p.nodes.state()["active_node"]
    p.checkout(node)
    assert _zr(p.session.model).fp == pytest.approx(-9.04, abs=0.2)
    assert _zr(p.session.model).fdp > 2.0
    # Mo K-alpha data: small terms, still set (not zero) so both engines agree
    d2 = _project(tmp_path / "mo", 0.71073)
    p2 = RefineProject(d2)
    p2.open()
    assert _zr(p2.session.model).fp == pytest.approx(-2.965, abs=0.3)


def test_recount_integrates_with_the_terms_and_reports_its_series(tmp_path):
    from crystalpilot.refine.project import RefineProject
    from crystalpilot.refine.scene import VOIDS_CACHE_V, build_void_ccp4
    d = _project(tmp_path, ZR_EDGE_A)
    p = RefineProject(d)
    p.open()
    node = p.nodes.state()["active_node"]
    info = build_void_ccp4(d, node, tmp_path / "voids.ccp4")
    assert info["v"] == VOIDS_CACHE_V >= 7
    assert info["anomalous_terms"]["Zr"][0] == pytest.approx(-9.04, abs=0.2)
    assert info["n_voids"] >= 1, "three atoms in a 990 A^3 cell leave a void"
    if info.get("total_solvent_electrons_per_cell") is not None:
        b = info["bypass"]
        assert set(b) >= {"converged", "diverged", "n_cycles", "kept_cycle",
                          "f000s_first", "f000s_last"}
        assert b["n_cycles"] >= 1
        assert (b["converged"], b["diverged"]) != (True, True)


def test_session_model_setter_applies_the_dataset_terms():
    """Every structure a tool puts into the session gets the terms - SHELXL
    adopt, a symmetry change, an import or a select() copy - not only the
    one the in-process engine refined."""
    from types import SimpleNamespace

    from crystalpilot.pipeline.session import SolveSession
    ses = SolveSession(dataset=SimpleNamespace(wavelength=ZR_EDGE_A))
    assert ses.model is None
    ses.model = _structure()
    assert _zr(ses.model).fp == pytest.approx(-9.04, abs=0.2)
    ses.model = ses.model.select(ses.model.scatterers().extract_scattering_types() == "Zr")
    assert ses.model.scatterers().size() == 1
    assert _zr(ses.model).fp == pytest.approx(-9.04, abs=0.2)
    # constructor keyword goes through the same setter
    ses2 = SolveSession(dataset=SimpleNamespace(wavelength=ZR_EDGE_A), model=_structure())
    assert _zr(ses2.model).fp == pytest.approx(-9.04, abs=0.2)
    # no dataset (structure-only) / electron beam: the model is left alone
    ses3 = SolveSession(dataset=None, model=_structure())
    assert _zr(ses3.model).fp == 0.0
    ses4 = SolveSession(dataset=SimpleNamespace(wavelength=0.0251), model=_structure())
    assert _zr(ses4.model).fp == 0.0
    ses4.model = None
    assert ses4.model is None
