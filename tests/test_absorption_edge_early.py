"""T1.7a: the absorption-edge warning fires EARLY - at set_experiment and
in get_project_brief - not only inside audit_heavy_sites.

ka1 (2026-09, both arms): lambda = 0.68883 A sat ON the Zr K edge, where
f'(Zr) = -9 e makes a Zr site scatter like ~31 electrons. Both arms found
that out only when they happened to call audit_heavy_sites - 12.8 and 18.6
minutes in, after R-vs-Z ladders the fact voids. The wavelength and the
SFAC list are known much earlier, so the statement is issued there too.

Coverage here is deliberately synthetic and element-generic (owner rule:
no criterion tuned to a test crystal). Combinations exercised:

  Zr  @ 0.68883 A (synchrotron, ON the Zr K edge)  -> edge_at_lambda
  Zr  @ 0.71073 A (Mo K-alpha, edge 3% away)       -> strong_fp
  Ni  @ 1.54178 A (Cu K-alpha, Co/Ni/Fe region)    -> strong_fp
  Ho  @ 1.54178 A (Cu K-alpha, ON the Ho L3 edge)  -> edge_at_lambda
  Ru  @ 0.56087 A (Ag K-alpha, ON the Ru K edge)   -> edge_at_lambda
  Lu  @ 1.34139 A (Ga K-alpha, ON the Lu L3 edge)  -> edge_at_lambda
  Th  @ 0.71073 A (element Sasaki omits -> Henke)  -> strong_fp
  C H N O S @ 0.71073 A (light-atom organic)       -> no_edge_nearby
  any @ unknown lambda / unknown elements          -> explicit "NOT run"
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from cctbx import crystal, xray

from crystalpilot.refine.tools_extra import GetProjectBrief
from crystalpilot.refine.tools_heavysites import (absorption_edge_brief,
                                                  anomalous_terms,
                                                  project_absorption_edge_brief)
from crystalpilot.refine.tools_ingest import SetExperiment

ZR_EDGE = 0.68883        # ka1 synchrotron wavelength = Zr K edge
MO = 0.71073
CU = 1.54178
AG = 0.56087
GA = 1.34139

CELL = (10.0, 10.0, 10.0, 90, 90, 90)


# ------------------------------------------------------------------ fixtures

class _Nodes:
    def list_nodes(self, limit=50):
        return {"nodes": [], "active_node": None, "active_branch": "main",
                "branches": {}}


class _Proj:
    """The minimum get_project_brief / set_experiment touch: a directory, a
    context.json dict, an experiment() accessor, a node store."""

    def __init__(self, d: Path, context: dict | None = None, session=None):
        d.mkdir(parents=True, exist_ok=True)
        self.dir = d
        self.context = context or {}
        self.hkl_path = d / "crystal.hkl"
        self.start_model_path = d / "start.ins"
        self.merge_stats = {}
        self.nodes = _Nodes()
        self.session = session
        if self.context:
            (d / "context.json").write_text(json.dumps(self.context),
                                            encoding="utf-8")

    def experiment(self):
        return dict(self.context.get("experiment") or {})


def _model(elements=()):
    cs = crystal.symmetry(unit_cell=CELL, space_group_symbol="P 1")
    xs = xray.structure(crystal_symmetry=cs)
    for i, el in enumerate(elements):
        xs.add_scatterer(xray.scatterer(
            label=f"{el}{i + 1}", site=(0.1 * i, 0.2, 0.3),
            scattering_type=el, u=0.02))
    return xs


def _session(wavelength=None, elements=(), ins_elements=None):
    flags: dict = {}
    if ins_elements is not None:
        flags["ins_elements"] = {"elements": list(ins_elements),
                                 "unit": [1.0] * len(ins_elements),
                                 "unit_is_placeholder": True,
                                 "source": "start.ins SFAC/UNIT",
                                 "note": "vendor/cold-start declaration"}
    return SimpleNamespace(
        model=_model(elements),
        symmetry=crystal.symmetry(unit_cell=CELL, space_group_symbol="P 1"),
        dataset=SimpleNamespace(wavelength=wavelength),
        flags=flags, merge_info={})


def _brief(proj, ses):
    r = GetProjectBrief(proj).run(SimpleNamespace(session=ses))
    assert r.ok, r.error
    return r.summary


def _set_experiment(proj, ctx=None, **kw):
    return SetExperiment(proj).run(ctx or SimpleNamespace(session=None), **kw)


# ------------------------------------------------------- the physics itself

class TestCriterionIsElementGeneric:
    """Same rule, any element, any wavelength: an edge within 1% of lambda
    (located by the f'' jump scan) or |f'| >= 2 e. Nothing here knows what
    a MOF is."""

    @pytest.mark.parametrize("element,lam,expect_edge", [
        ("Zr", ZR_EDGE, True),     # synchrotron, ON the K edge
        ("Ho", CU, True),          # Cu K-alpha, ON the L3 edge
        ("Ru", AG, True),          # Ag K-alpha, ON the K edge
        ("Lu", GA, True),          # Ga K-alpha, ON the L3 edge
        ("Zr", MO, False),         # Mo K-alpha: edge 3% away, f' still -3 e
        ("Ni", CU, False),         # Cu K-alpha: the Co/Ni/Fe region
        ("Co", CU, False),
        ("Th", MO, False),         # Sasaki has no Th - Henke must catch it
    ])
    def test_flagged_with_a_conditional_statement(self, element, lam,
                                                  expect_edge):
        r = absorption_edge_brief(["C", "H", "N", "O", element], lam)
        assert r["applies"] is True
        assert r["status"] == ("edge_at_lambda" if expect_edge
                               else "strong_fp")
        assert [f["element"] for f in r["flagged"]] == [element]
        f = r["flagged"][0]
        assert f["fp"] <= -2.0                      # f' lowers the count
        assert f["z_eff"] < f["Z"]
        if expect_edge:
            assert "edge_at_lambda" in f["flags"]
            assert abs(f["edge_A"] - lam) / lam <= 0.01
        else:
            assert f["flags"] == ["strong_fp"]
        # never asserts the element is there, always says what it costs
        assert f["statement"].startswith(
            f"IF {element} is present as declared")
        assert "electrons instead of Z" in f["statement"]
        # light atoms travel along untouched
        assert set(r["no_anomalous_effect"]) >= {"C", "N", "O"}

    def test_consequence_names_the_corrected_count_and_its_tool(self):
        r = absorption_edge_brief(["C", "O", "Zr"], ZR_EDGE)
        c = r["consequence"]
        assert "z_eff = Z + f'" in c
        assert "LOWER" in c                      # the direction, spelled out
        assert "element_scan" in c
        assert "audit_heavy_sites" in c          # the tool that corrects
        assert "DISP" in c and "run_shelxl" in c
        # on an edge the direction heuristics die too
        assert "s-independent" in c

    def test_criterion_is_stated_and_matches_the_shared_thresholds(self):
        from crystalpilot.refine import tools_heavysites as th
        r = absorption_edge_brief(["Zr"], MO)
        assert r["criterion"] == th.EDGE_CRITERION
        assert f"{100 * th._EDGE_REL:.0f}%" in r["criterion"]
        assert f"{th._FP_STRONG_E:.1f} e" in r["criterion"]
        # one implementation: the numbers are anomalous_terms', unchanged
        assert r["flagged"][0]["fp"] == anomalous_terms(["Zr"], MO)["Zr"]["fp"]

    def test_light_atom_organic_at_mo_says_so_explicitly(self):
        """The case that must NOT stay silent: nothing to flag is a
        statement, not an absence."""
        r = absorption_edge_brief(["C", "H", "N", "O", "S"], MO)
        assert r["applies"] is True
        assert r["status"] == "no_edge_nearby"
        assert r["flagged"] == []
        s = r["statement"]
        assert "No absorption-edge problem" in s
        assert "0.71073" in s
        assert "C, H, N, O, S" in s
        assert "may use plain atomic numbers" in s
        # and it does not over-claim: only the declared elements are covered
        assert "says nothing about an element nobody has declared" in s
        assert "consequence" not in r

    def test_same_element_flips_with_the_wavelength_only(self):
        """Zr is not special: it is flagged where the table says so and
        cleared where it does not."""
        on = absorption_edge_brief(["Zr"], ZR_EDGE)["flagged"][0]
        off = absorption_edge_brief(["Zr"], AG)
        assert on["z_eff"] < 32                       # ~31 e at the edge
        assert off["status"] == "no_edge_nearby"      # Ag K-alpha: |f'| < 2
        assert "Zr" in off["no_anomalous_effect"]

    def test_henke_fallback_is_named_and_gaps_are_declared(self):
        r = absorption_edge_brief(["Th"], MO)
        assert "Henke" in r["flagged"][0]["table"]
        r2 = absorption_edge_brief(["Zr"], ZR_EDGE)
        assert "Sasaki" in r2["flagged"][0]["table"]
        # an unknown symbol is reported, never silently dropped
        r3 = absorption_edge_brief(["C", "Xx"], MO)
        assert r3["no_tabulation"]["elements"] == ["Xx"]
        assert "NOT checked" in r3["no_tabulation"]["note"]


class TestCannotRunIsStatedNotSilent:
    def test_wavelength_unknown(self):
        r = absorption_edge_brief(["C", "O", "Zr"], None)
        assert r["applies"] is False
        assert r["status"] == "wavelength_unknown"
        assert "NOT run" in r["statement"]
        assert "NOT 'no edge here'" in r["statement"]
        assert "set_experiment" in r["statement"]
        assert "flagged" not in r

    def test_elements_unknown(self):
        r = absorption_edge_brief([], MO)
        assert r["applies"] is False
        assert r["status"] == "elements_unknown"
        assert "NOT run" in r["statement"]
        assert "NOT 'no edge here'" in r["statement"]
        assert r["wavelength_A"] == MO
        assert "flagged" not in r


# ------------------------------------------------- project-level resolution

class TestProjectResolution:
    def test_ins_sfac_is_the_element_source_and_is_labelled_a_declaration(
            self, tmp_path):
        proj = _Proj(tmp_path / "p", {"data": {"ins_elements": {
            "elements": ["C", "H", "N", "O", "Zr"], "unit": [1, 1, 1, 1, 1],
            "unit_is_placeholder": True, "source": "start.ins SFAC/UNIT"}}})
        ses = _session(wavelength=ZR_EDGE)          # atomless session
        r = project_absorption_edge_brief(proj, ses)
        assert r["status"] == "edge_at_lambda"
        assert r["elements_considered"] == ["C", "H", "N", "O", "Zr"]
        assert "not evidence" in r["elements_source"]
        assert r["wavelength_source"] == "dataset (CELL / export metadata)"

    def test_model_elements_are_the_fallback_and_extend_the_ins_list(
            self, tmp_path):
        """No ins record -> the model's scattering types. With an ins
        record -> anything the solver added on top (ka1: SHELXT invented
        Br7/I12) is still checked."""
        proj = _Proj(tmp_path / "a", {})
        ses = _session(wavelength=CU, elements=("C", "O", "Ho"))
        r = project_absorption_edge_brief(proj, ses)
        assert r["elements_considered"] == ["C", "O", "Ho"]
        assert "current model scattering types" in r["elements_source"]
        assert [f["element"] for f in r["flagged"]] == ["Ho"]

        proj2 = _Proj(tmp_path / "b", {})
        ses2 = _session(wavelength=AG, elements=("C", "O", "Ru"),
                        ins_elements=["C", "H", "N", "O"])
        r2 = project_absorption_edge_brief(proj2, ses2)
        assert r2["elements_considered"] == ["C", "H", "N", "O", "Ru"]
        assert "beyond the ins list: Ru" in r2["elements_source"]
        assert [f["element"] for f in r2["flagged"]] == ["Ru"]

    def test_context_json_free_text_wavelength_when_there_is_no_data(
            self, tmp_path):
        proj = _Proj(tmp_path / "p", {
            "experiment": {"instrument": {"source": "synchrotron lambda = "
                                                    "0.68883 A"}},
            "data": {"ins_elements": {"elements": ["C", "O", "Zr"],
                                      "source": "start.ins SFAC/UNIT"}}})
        r = project_absorption_edge_brief(proj, session=None)
        assert r["wavelength_A"] == ZR_EDGE
        assert "free text" in r["wavelength_source"]
        assert r["status"] == "edge_at_lambda"

    def test_no_session_no_context_says_it_cannot_run(self, tmp_path):
        proj = _Proj(tmp_path / "p", {})
        r = project_absorption_edge_brief(proj, session=None)
        assert r["status"] == "wavelength_unknown"
        assert r["applies"] is False


# --------------------------------------------------------- get_project_brief

class TestProjectBriefCarriesIt:
    def test_edge_is_standing_in_the_brief(self, tmp_path):
        proj = _Proj(tmp_path / "p", {"data": {"ins_elements": {
            "elements": ["C", "H", "N", "O", "Zr"],
            "source": "start.ins SFAC/UNIT"}}})
        ses = _session(wavelength=ZR_EDGE, elements=("C", "O", "Zr"))
        s = _brief(proj, ses)
        edge = s["absorption_edge"]
        assert edge["status"] == "edge_at_lambda"
        assert edge["flagged"][0]["element"] == "Zr"
        assert edge["flagged"][0]["fp"] < -8.0
        assert 30 <= edge["flagged"][0]["z_eff"] <= 32
        assert "audit_heavy_sites" in edge["consequence"]

    def test_brief_says_no_edge_for_a_light_organic_at_mo(self, tmp_path):
        proj = _Proj(tmp_path / "p", {})
        ses = _session(wavelength=MO, elements=("C", "H", "N", "O"))
        edge = _brief(proj, ses)["absorption_edge"]
        assert edge["status"] == "no_edge_nearby"
        assert "No absorption-edge problem" in edge["statement"]

    def test_brief_before_any_data_states_the_check_cannot_run(self,
                                                               tmp_path):
        """Raw-frames project: no session at all. The field is still
        there, saying why it is empty."""
        proj = _Proj(tmp_path / "p", {})
        proj.session = None
        r = GetProjectBrief(proj).run(SimpleNamespace(session=None))
        assert r.ok, r.error
        assert r.summary["state"] == "awaiting_data"
        edge = r.summary["absorption_edge"]
        assert edge["applies"] is False
        assert edge["status"] == "wavelength_unknown"

    def test_description_announces_the_field(self):
        d = GetProjectBrief.description
        assert "absorption_edge" in d and "z_eff" in d


# ------------------------------------------------------------ set_experiment

class TestSetExperimentCarriesIt:
    def test_auto_import_of_a_synchrotron_block_warns_immediately(
            self, tmp_path):
        """The pa1/ka1 shape: the runner's context.json names the
        wavelength in free text and the ins declared SFAC C H N O Zr. The
        very first set_experiment() must already say 'Zr is on its edge'."""
        proj = _Proj(tmp_path / "p", {
            "experiment": {"instrument": {"source": "synchrotron, lambda = "
                                                    "0.68883 A"},
                           "temperature_K": 100},
            "data": {"ins_elements": {"elements": ["C", "H", "N", "O", "Zr"],
                                      "source": "start.ins SFAC/UNIT"}}})
        r = _set_experiment(proj)
        assert r.ok, r.error
        edge = r.summary["absorption_edge"]
        assert edge["status"] == "edge_at_lambda"
        assert edge["flagged"][0]["element"] == "Zr"
        assert "IF Zr is present as declared" in edge["statement"]
        assert edge["wavelength_A"] == ZR_EDGE

    def test_auto_import_prefers_the_data_wavelength(self, tmp_path):
        """context.json says Cu, the data says Mo: the CIF and both
        engines take the data's CELL wavelength, so the edge check does
        too (and radiation_check still flags the disagreement)."""
        proj = _Proj(tmp_path / "p", {
            "experiment": {"instrument": {"source": "Cu, 1.54178 A"}},
            "data": {"ins_elements": {"elements": ["C", "O", "Ni"],
                                      "source": "start.ins SFAC/UNIT"}}})
        ctx = SimpleNamespace(session=_session(wavelength=MO))
        r = _set_experiment(proj, ctx)
        assert r.ok, r.error
        assert r.summary["radiation_check"]["agrees"] is False
        edge = r.summary["absorption_edge"]
        assert edge["wavelength_A"] == MO
        assert edge["wavelength_source"] == "dataset (CELL / export metadata)"
        # Ni is strongly anomalous at Cu K-alpha but clean at Mo K-alpha
        assert edge["status"] == "no_edge_nearby"
        assert "Ni" in edge["no_anomalous_effect"]

    def test_cu_source_with_a_ni_model_warns_at_import(self, tmp_path):
        proj = _Proj(tmp_path / "p", {
            "experiment": {"instrument": {"source": "Cu, 1.54178 A"}}})
        ctx = SimpleNamespace(session=_session(wavelength=CU,
                                               elements=("C", "N", "Ni")))
        r = _set_experiment(proj, ctx)
        assert r.ok, r.error
        edge = r.summary["absorption_edge"]
        assert edge["status"] == "strong_fp"
        assert edge["flagged"][0]["element"] == "Ni"
        assert edge["flagged"][0]["z_eff"] < 28

    def test_recording_radiation_explicitly_returns_the_block(self,
                                                              tmp_path):
        proj = _Proj(tmp_path / "p", {"data": {"ins_elements": {
            "elements": ["C", "O", "Ru"], "source": "start.ins SFAC/UNIT"}}})
        ctx = SimpleNamespace(session=_session(wavelength=AG))
        r = _set_experiment(
            proj, ctx,
            experiment={"instrument": {"source": "sealed X-ray tube, "
                                                 "Ag K-alpha"}},
            provenance="instrument log 2026-09-04")
        assert r.ok, r.error
        edge = r.summary["absorption_edge"]
        assert edge["status"] == "edge_at_lambda"
        assert edge["flagged"][0]["element"] == "Ru"

    def test_explicit_radiation_without_data_reads_the_wavelength_back(
            self, tmp_path):
        """No reduced data yet (set_experiment can run before ingest): the
        wavelength the call just wrote into context.json is the one the
        edge check uses."""
        proj = _Proj(tmp_path / "p", {"data": {"ins_elements": {
            "elements": ["C", "H", "N", "O", "Zr"],
            "source": "start.ins SFAC/UNIT"}}})
        r = _set_experiment(
            proj,
            experiment={"instrument": {"source": "synchrotron, lambda = "
                                                 "0.68883 A"}},
            provenance="beamline logbook 2026-09-04")
        assert r.ok, r.error
        edge = r.summary["absorption_edge"]
        assert edge["wavelength_A"] == ZR_EDGE
        assert "free text" in edge["wavelength_source"]
        assert edge["status"] == "edge_at_lambda"
        assert edge["flagged"][0]["element"] == "Zr"

    def test_a_temperature_only_call_does_not_carry_the_block(self,
                                                              tmp_path):
        """The warning belongs where radiation is on the record, not on
        every metadata edit."""
        proj = _Proj(tmp_path / "p", {})
        r = _set_experiment(proj, experiment={"temperature_K": 100.0},
                            provenance="mount notes 2026-09-04")
        assert r.ok, r.error
        assert "absorption_edge" not in r.summary

    def test_nothing_to_import_still_states_the_check_cannot_run(self,
                                                                 tmp_path):
        proj = _Proj(tmp_path / "p", {})
        r = _set_experiment(proj)
        assert r.ok, r.error
        assert "nothing to import" in r.summary["note"]
        edge = r.summary["absorption_edge"]
        assert edge["applies"] is False
        assert edge["status"] == "wavelength_unknown"
        assert "NOT 'no edge here'" in edge["statement"]

    def test_description_announces_the_field(self):
        d = SetExperiment.description
        assert "absorption_edge" in d and "z_eff = Z + f'" in d


# --------------------------------------------------- no drift from the audit

def test_audit_heavy_sites_and_the_early_warning_agree(tmp_path):
    """Same table, same thresholds, one implementation: the early block's
    numbers must be the ones audit_heavy_sites would print."""
    early = absorption_edge_brief(["C", "O", "Zr"], ZR_EDGE)["flagged"][0]
    terms = anomalous_terms(["Zr"], ZR_EDGE)["Zr"]
    assert early["fp"] == terms["fp"]
    assert early["fdp"] == terms["fdp"]
    assert early["z_eff"] == terms["z_eff"]
    assert early["edge_A"] == terms["edge_A"]
    assert early["flags"] == terms["flags"]
