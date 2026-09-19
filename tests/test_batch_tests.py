"""ghost_test / element_scan: one call per ladder, one baseline, one table.

pa1: hex-l2-r2 ran 84 branch / 74 checkout / 82 edit_atoms / 94 refine
calls for two ghost passes over the framework; cage-l0-r1 three element
ladders (~100 calls, ~25 min) that concluded "R cannot tell"; hex-l1-r1
delivered Zn for Zr because an R ladder on an unmasked 79%-void cell
preferred the lighter metal. The data here are synthetic (Fc^2 of a
five-atom P-1 model, 1% noise) so the in-process engine refines each
candidate in well under a second and no vendor binary is needed.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from crystalpilot.refine.tools_batch import (GHOST_R1_RISE, GhostTest,
                                             _ghost_verdict, _split_group)

SHELXL = Path(__file__).resolve().parents[1] / "vendor" / "shelx" / "shelxl.exe"
CELL = (7.0, 8.0, 9.0, 85.0, 95.0, 100.0)
TRUE_ATOMS = [("ZR1", "Zr", (0.25, 0.10, 0.15)),
              ("O1", "O", (0.40, 0.20, 0.30)),
              ("O2", "O", (0.10, 0.25, 0.05)),
              ("C1", "C", (0.55, 0.30, 0.40)),
              ("C2", "C", (0.65, 0.42, 0.55))]
#: an atom the data know nothing about, >= 3 A from every real atom
#: (not 'Q9': SHELX drops Q<n> labels on read - they are peak lines)
GHOST = ("C9G", "C", (0.50, 0.75, 0.10))


def _structure(atoms):
    from cctbx import crystal, xray
    cs = crystal.symmetry(unit_cell=CELL, space_group_symbol="P -1")
    xs = xray.structure(crystal_symmetry=cs)
    for lbl, el, site in atoms:
        xs.add_scatterer(xray.scatterer(label=lbl, site=site, u=0.02,
                                        scattering_type=el))
    return xs


def make_project(tmp_path: Path, model_atoms, data_atoms=TRUE_ATOMS) -> Path:
    """Project dir with HKLF4 data computed from data_atoms and a start
    model made of model_atoms."""
    from cctbx.array_family import flex

    from crystalpilot.io.cif_sf import write_hklf4
    from crystalpilot.io.shelx_writer import ShelxModel, write_res
    d = tmp_path / "proj"
    d.mkdir()
    truth = _structure(data_atoms)
    i_obs = truth.structure_factors(
        d_min=0.75, algorithm="direct").f_calc().as_intensity_array()
    flex.set_random_seed(7)
    noise = 1.0 + 0.01 * (flex.random_double(i_obs.size()) - 0.5)
    data = i_obs.data() * noise
    i_obs = i_obs.customized_copy(data=data, sigmas=0.02 * data + 0.5)
    write_hklf4(i_obs, d / "crystal.hkl")
    write_res(ShelxModel(xray_structure=_structure(model_atoms),
                         wavelength=0.71073, z=2, weights=(0.1, 0.0)),
              d / "start.res")
    (d / "context.json").write_text(json.dumps({
        "data": {"hkl": "crystal.hkl", "start_model": "start.res"}}),
        encoding="utf-8")
    return d


def _open(d: Path):
    from crystalpilot.refine.project import RefineProject
    p = RefineProject(d)
    p.open()
    return p


@pytest.fixture()
def project(tmp_path):
    """True model plus the ghost C9G, on branch main at n0000."""
    return _open(make_project(tmp_path, TRUE_ATOMS + [GHOST]))


# ==========================================================================
class TestPureHelpers:
    def test_split_group(self):
        assert _split_group("O7") == ["O7"]
        assert _split_group("O7+O8") == ["O7", "O8"]
        assert _split_group("O7, O8 O9") == ["O7", "O8", "O9"]
        assert _split_group(["O7", "O8"]) == ["O7", "O8"]
        assert _split_group("  ") == []

    def test_verdict_fences_match_the_asu_sanity_advice(self):
        # chem/asu_sanity.py: "R1 rise < 0.002 means no real density"
        assert GHOST_R1_RISE == 0.002
        v, why = _ghost_verdict(+0.010, 3.2, None)
        assert v == "real" and "returns" in why
        v, why = _ghost_verdict(-0.001, 0.1, None)
        assert v == "ghost" and "delete" in why
        v, why = _ghost_verdict(+0.0005, 2.5, None)
        assert v == "inconclusive" and "low-weight" in why
        v, why = _ghost_verdict(+0.006, 0.3, None)
        assert v == "inconclusive" and "not localised" in why
        v, why = _ghost_verdict(None, None, None)
        assert v == "inconclusive"

    def test_ripple_zone_is_named_next_to_a_metal(self):
        metal = {"label": "FE1", "element": "Fe", "d_A": 0.7}
        v, why = _ghost_verdict(+0.0005, 1.8, metal)
        assert v == "inconclusive"
        assert "FE1" in why and "ripple zone" in why
        far = {"label": "FE1", "element": "Fe", "d_A": 2.4}
        _, why2 = _ghost_verdict(+0.0005, 1.8, far)
        assert "FE1" not in why2 and "ripple zone" not in why2


# ==========================================================================
class TestRegistration:
    def test_both_tools_are_on_the_project_registry(self, project):
        names = set(project.registry.names())
        assert {"ghost_test", "element_scan"} <= names
        # they change the tree themselves (diagnostic nodes) and must NOT
        # auto-commit a node of their own on top of the restored baseline
        from crystalpilot.refine.registry import MUTATING_TOOLS
        assert "ghost_test" not in MUTATING_TOOLS
        assert "element_scan" not in MUTATING_TOOLS


# ==========================================================================
class TestGhostTest:
    def test_one_call_separates_ghost_from_real_and_restores_baseline(
            self, project):
        p = project
        baseline = p.nodes.state()["active_node"]
        r = p.invoke_tool("ghost_test", {"atoms": ["c9g", "C1"], "cycles": 4})
        assert r.ok, r.error
        s = r.summary
        assert s["verdicts"] == {"C9G": "ghost", "C1": "real"}
        rows = {row["atoms"]: row for row in s["rows"]}
        q9, c1 = rows["C9G"], rows["C1"]
        assert q9["delta_r1"] < GHOST_R1_RISE and q9["peak_at_site"] < 0.5
        assert c1["delta_r1"] >= GHOST_R1_RISE and c1["peak_at_site"] >= 1.0
        assert c1["r1_strong"] > s["baseline"]["reference"]["r1_strong"]
        # the criterion travels with the verdicts
        assert "0.002" in s["criterion"] and "reference" in s["criterion"]
        assert "delete it" in q9["reason"] and "real" in c1["reason"]
        # neighbours carry Ueq before/after, from like-for-like refinements
        assert c1["neighbours"]
        assert all(nb["ueq_reference"] is not None and nb["ueq_after"]
                   is not None for nb in c1["neighbours"])
        assert c1["elements"] == ["C"] and c1["n_atoms"] == 5
        # the baseline is checked out again, on the branch it came from,
        # with the ghost still in the live model (the test decides nothing)
        st = p.nodes.state()
        assert st["active_node"] == baseline
        assert st["active_branch"] == "main"
        assert st["branches"]["main"] == baseline
        assert p.session.model.scatterers().size() == 6
        assert s["restore"] == {"restored": True, "node": baseline,
                                "branch": "main"}

    def test_throwaway_nodes_are_labelled_diagnostic_branches(self, project):
        p = project
        baseline = p.nodes.state()["active_node"]
        r = p.invoke_tool("ghost_test", {"atoms": ["C9G"], "cycles": 2})
        assert r.ok, r.error
        st = p.nodes.state()
        assert f"diag/ghost_test/{baseline}/reference" in st["branches"]
        assert f"diag/ghost_test/{baseline}/C9G" in st["branches"]
        row = r.summary["rows"][0]
        assert row["branch"] == f"diag/ghost_test/{baseline}/C9G"
        meta = p.nodes.node_meta(row["node"])
        assert meta["diagnostic"] == {"tool": "ghost_test",
                                      "baseline": baseline,
                                      "candidate": "C9G", "step": "refine"}
        assert "diagnostic" in meta["note"] and "not a delivery" in meta["note"]
        listing = p.nodes.list_nodes()
        notes = [n["note"] for n in listing["nodes"]]
        # reference + delete + refine nodes all say what they are
        assert sum("diagnostic ghost_test" in n for n in notes) == 3
        assert "diag/ghost_test" in r.summary["tree_note"]
        # main never advanced past the baseline
        assert listing["branches"]["main"] == baseline

    def test_group_is_deleted_as_one_candidate(self, project):
        p = project
        r = p.invoke_tool("ghost_test", {"atoms": ["O1+O2"], "cycles": 3})
        assert r.ok, r.error
        assert len(r.summary["rows"]) == 1
        row = r.summary["rows"][0]
        assert row["atoms"] == "O1+O2"
        assert row["elements"] == ["O", "O"] and row["n_atoms"] == 4
        assert len(row["residual_at_site"]) == 2
        assert row["verdict"] == "real"

    def test_unknown_label_runs_nothing(self, project):
        p = project
        baseline = p.nodes.state()["active_node"]
        r = p.invoke_tool("ghost_test", {"atoms": ["C1", "XX9"]})
        assert not r.ok
        assert "unknown atom label" in r.error and "XX9" in r.error
        assert "nothing was run" in r.error
        st = p.nodes.state()
        assert not any(b.startswith("diag/") for b in st["branches"])
        assert st["active_node"] == baseline and st["active_branch"] == "main"

    def test_candidate_cap_and_parameter_guards(self, project):
        p = project
        r = p.invoke_tool("ghost_test", {"atoms": [f"C{i}" for i in range(13)]})
        assert not r.ok and "per-call maximum" in r.error
        assert not p.invoke_tool("ghost_test", {"atoms": []}).ok
        r = p.invoke_tool("ghost_test", {"atoms": ["C1"], "cycles": 0})
        assert not r.ok and "cycles" in r.error
        r = p.invoke_tool("ghost_test", {"atoms": ["C1"], "engine": "olex"})
        assert not r.ok and "engine" in r.error
        r = p.invoke_tool("ghost_test", {"atoms": ["C1"],
                                         "time_budget_s": 99999})
        assert not r.ok and "time_budget_s" in r.error
        assert not any(b.startswith("diag/")
                       for b in p.nodes.state()["branches"])

    def test_time_budget_stops_before_a_candidate_that_will_not_fit(
            self, project, monkeypatch):
        p = project
        calls = {"n": 0}

        def exhausted(elapsed, estimate, budget):
            calls["n"] += 1
            return calls["n"] > 1           # first candidate fits, no more

        monkeypatch.setattr(GhostTest, "_budget_exhausted",
                            staticmethod(exhausted))
        baseline = p.nodes.state()["active_node"]
        r = p.invoke_tool("ghost_test", {"atoms": ["C9G", "C1", "C2"],
                                         "cycles": 2, "time_budget_s": 120})
        assert r.ok, r.error
        s = r.summary
        assert s["n_tested"] == 1 and s["verdicts"] == {"C9G": "ghost"}
        assert s["not_tested"] == ["C1", "C2"]
        assert "time budget 120 s" in s["timeout"]
        assert "did NOT start ['C1', 'C2']" in s["timeout"]
        assert "atoms=['C1', 'C2']" in s["timeout"]
        st = p.nodes.state()
        assert st["active_node"] == baseline and st["active_branch"] == "main"

    def test_one_failed_candidate_does_not_kill_the_table(self, project,
                                                          monkeypatch):
        from crystalpilot.tools.base import ToolResult
        p = project
        orig = p.invoke_tool

        def flaky(name, params=None, progress=None):
            labels = {sc.label for sc in p.session.model.scatterers()}
            if name == "refine" and "C1" not in labels:
                return ToolResult.failure("singular matrix (simulated)")
            return orig(name, params, progress=progress)

        monkeypatch.setattr(p, "invoke_tool", flaky)
        baseline = p.nodes.state()["active_node"]
        r = p.invoke_tool("ghost_test", {"atoms": ["C1", "C9G"], "cycles": 2})
        assert r.ok, r.error
        rows = {row["atoms"]: row for row in r.summary["rows"]}
        assert rows["C1"]["verdict"] == "inconclusive"
        assert "singular matrix" in rows["C1"]["error"]
        assert rows["C9G"]["verdict"] == "ghost"
        st = p.nodes.state()
        assert st["active_node"] == baseline and st["active_branch"] == "main"

    def test_failed_reference_aborts_before_any_candidate(self, project,
                                                          monkeypatch):
        from crystalpilot.tools.base import ToolResult
        p = project
        orig = p.invoke_tool

        def broken(name, params=None, progress=None):
            if name == "refine":
                return ToolResult.failure("twin law active (simulated)")
            return orig(name, params, progress=progress)

        monkeypatch.setattr(p, "invoke_tool", broken)
        baseline = p.nodes.state()["active_node"]
        r = p.invoke_tool("ghost_test", {"atoms": ["C1"]})
        assert not r.ok
        assert "reference refinement" in r.error
        assert "twin law active" in r.error
        assert "no candidate was run" in r.error
        assert r.summary["restore"]["restored"] is True
        st = p.nodes.state()
        assert st["active_node"] == baseline and st["active_branch"] == "main"
        assert f"diag/ghost_test/{baseline}/C1" not in st["branches"]

    @pytest.mark.skipif(not SHELXL.exists(), reason="vendor shelxl not deployed")
    def test_shelxl_engine_runs_the_same_ladder(self, project):
        """engine='shelxl' (run_shelxl adopt) - the route for twinned /
        HKLF5 data and the faster one on very large models."""
        p = project
        baseline = p.nodes.state()["active_node"]
        r = p.invoke_tool("ghost_test", {"atoms": ["C9G", "C1"], "cycles": 2,
                                         "engine": "shelxl"})
        assert r.ok, r.error
        s = r.summary
        assert s["baseline"]["engine"] == "shelxl"
        assert s["verdicts"] == {"C9G": "ghost", "C1": "real"}
        rows = {row["atoms"]: row for row in s["rows"]}
        # the candidate nodes are SHELXL-adopted models on diag/ branches
        assert p.nodes.node_meta(rows["C1"]["node"])["tool"] == "run_shelxl"
        assert p.nodes.node_meta(rows["C1"]["node"])["diagnostic"][
            "candidate"] == "C1"
        st = p.nodes.state()
        assert st["active_node"] == baseline and st["active_branch"] == "main"

    def test_explicit_node_id_and_pointer_restore(self, project):
        """Testing an older node: the call ends with THAT node checked out,
        and the branch the caller was on before is not silently moved."""
        p = project
        n0 = p.nodes.state()["active_node"]
        r1 = p.invoke_tool("refine", {"mode": "isotropic", "n_cycles": 2})
        assert r1.ok, r1.error
        head = r1.summary["node"]
        r = p.invoke_tool("ghost_test", {"atoms": ["C9G"], "cycles": 2,
                                         "node_id": n0})
        assert r.ok, r.error
        assert r.summary["baseline"]["node"] == n0
        st = p.nodes.state()
        assert st["active_node"] == n0
        assert st["branches"]["main"] == head       # main untouched
        assert not st["active_branch"].startswith("diag/")


# ==========================================================================
class TestElementScan:
    def test_scan_ranks_scattering_power_and_never_picks(self, project):
        p = project
        baseline = p.nodes.state()["active_node"]
        r = p.invoke_tool("element_scan", {"site": "ZR1",
                                           "elements": ["Zn", "Zr", "Hf"],
                                           "cycles": 4})
        assert r.ok, r.error
        s = r.summary
        # readiness comes FIRST in the result
        assert list(s)[0] == "readiness_warning"
        kinds = {n["kind"] for n in s["readiness"]}
        assert "weights_not_adopted" in kinds          # WGHT 0.1 0 default
        assert "weights_not_adopted" in s["readiness_warning"]
        assert s["readiness_ok"] is False
        rows = {row["element"]: row for row in s["rows"]}
        assert set(rows) == {"Zn", "Zr", "Hf"}
        # the current element is reused from the reference: no extra run
        assert rows["Zr"]["is_current"] and rows["Zr"]["delta_r1"] == 0.0
        assert rows["Zr"]["z"] == 40 and rows["Zn"]["z"] == 30
        # scattering-power evidence: too heavy digs a clear hole; too light
        # leaves density but a free ADP absorbs most of a one-row step
        # (Zn vs Zr), so the scan must SAY those two are not separated
        assert rows["Hf"]["residual_signed"] < -1.0
        assert rows["Zn"]["residual_signed"] > 0
        assert rows["Hf"]["ueq_site"] > rows["Zr"]["ueq_site"]
        assert s["evidence_ranking"][-1]["element"] == "Hf"
        assert s["evidence_ranking"][0]["element"] in ("Zr", "Zn")
        assert {"Zr", "Zn"} <= set(s["tied_at_top"])
        assert "Hf" not in s["tied_at_top"]
        assert "NOT separated" in s["ranking_note"]
        assert "chemistry" in s["ranking_note"]
        # R1 is NOT the discriminator: the lighter metal comes out with
        # the LOWER R1 on this model (which still carries a ghost atom) -
        # the pa1 hex-l1-r1 pattern in miniature; the ranking ignores it
        assert abs(rows["Zn"]["delta_r1"]) < 0.01
        # never a choice, always the rule
        assert not any(k in s for k in ("chosen", "best_element", "winner"))
        assert "not by R" in s["rule"] and "元素身份由化学定" in s["rule"]
        assert "R1 is the weakest column" in s["how_to_read"]
        # tree + baseline discipline, same as ghost_test
        st = p.nodes.state()
        assert st["active_node"] == baseline and st["active_branch"] == "main"
        assert f"diag/element_scan/{baseline}/ZR1=Zn" in st["branches"]
        assert f"diag/element_scan/{baseline}/reference" in st["branches"]
        meta = p.nodes.node_meta(rows["Hf"]["node"])
        assert meta["diagnostic"]["candidate"] == "ZR1=Hf"
        assert p.session.model.scatterers()[0].scattering_type.strip() == "Zr"

    def test_free_occupancy_reports_electrons_at_site(self, project):
        p = project
        r = p.invoke_tool("element_scan", {"site": "ZR1",
                                           "elements": ["Zn", "Zr", "Hf"],
                                           "cycles": 4, "free_occupancy": True})
        assert r.ok, r.error
        rows = {row["element"]: row for row in r.summary["rows"]}
        assert not [row for row in rows.values() if "error" in row], rows
        # a too-light element compensates with occupancy > 1, too heavy < 1
        assert rows["Zn"]["occupancy"] > rows["Zr"]["occupancy"] > \
            rows["Hf"]["occupancy"]
        for row in rows.values():
            assert row["free_occupancy_applied"] is True
            # the electron count is built from the occupancy measured with
            # the ADP held, not from the all-free refinement
            assert row["occupancy_x_z"] == pytest.approx(
                row["occupancy_at_fixed_u"] * row["z"], abs=0.11)
        assert all("occupancy_x_z" in e
                   for e in r.summary["evidence_ranking"])
        assert r.summary["baseline"]["free_occupancy"] is True
        assert r.summary["free_occupancy_applied"] is True
        # the freed occupancy never leaks into the restored baseline
        sc = p.session.model.scatterers()[0]
        assert sc.occupancy == 1.0 and not sc.flags.grad_occupancy()

    def test_occupancy_x_z_only_where_the_occupancy_was_measured(self, project):
        """Without free_occupancy the column would be occupancy(=1) x Z = Z,
        which reads as an electron count nobody measured (ka1 cage)."""
        p = project
        r = p.invoke_tool("element_scan", {"site": "ZR1",
                                           "elements": ["Zn", "Zr"],
                                           "cycles": 2})
        assert r.ok, r.error
        for row in r.summary["rows"]:
            assert "occupancy_x_z" not in row
            assert "free_occupancy_applied" not in row
        assert "electron_count_reading" not in r.summary
        assert all("occupancy_x_z" not in e
                   for e in r.summary["evidence_ranking"])

    def test_readiness_flags_an_incomplete_unmasked_model(self, tmp_path):
        """A model missing C2 on a cell with no mask: the scan must say at
        the top that R cannot be read, before any candidate row."""
        p = _open(make_project(tmp_path, [a for a in TRUE_ATOMS
                                          if a[0] != "C2"]))
        r = p.invoke_tool("element_scan", {"site": "ZR1", "elements": ["Zr"],
                                           "cycles": 3})
        assert r.ok, r.error
        s = r.summary
        kinds = [n["kind"] for n in s["readiness"]]
        assert "incomplete_model" in kinds
        assert "unmasked_void" in kinds
        note = next(n["note"] for n in s["readiness"]
                    if n["kind"] == "incomplete_model")
        assert "NOT meaningful" in note
        assert "incomplete_model" in s["readiness_warning"]
        assert s["baseline"]["reference"]["solvent_mask"] is False
        assert s["baseline"]["reference"]["packing_estimate"] < 0.5
        # only the current element was asked for: reused, nothing refined
        assert s["n_tested"] == 1 and s["rows"][0]["is_current"]
        assert not any(b.endswith("=Zr")
                       for b in p.nodes.state()["branches"])

    def test_group_of_sites_and_current_not_in_list(self, project):
        p = project
        r = p.invoke_tool("element_scan", {"site": "O1+O2",
                                           "elements": ["N"], "cycles": 2})
        assert r.ok, r.error
        s = r.summary
        assert s["site"]["atoms"] == "O1+O2"
        assert s["site"]["current_element"] == "O"
        assert [row["element"] for row in s["rows"]] == ["N"]
        row = s["rows"][0]
        assert len(row["residual_at_site"]) == 2
        assert isinstance(row["ueq_site"], list) and len(row["ueq_site"]) == 2
        assert row["residual_signed"] > 0          # N is too light for O

    def test_group_of_sites_with_free_occupancy(self, project):
        """A group is one hypothesis: its occupancies are freed together and
        occupancy x Z is reported per member plus as the group's total."""
        p = project
        r = p.invoke_tool("element_scan", {"site": "O1+O2",
                                           "elements": ["N"], "cycles": 2,
                                           "free_occupancy": True})
        assert r.ok, r.error
        row = r.summary["rows"][0]
        assert row["free_occupancy_applied"] is True
        assert len(row["occupancy_at_fixed_u"]) == 2
        assert len(row["occupancy_x_z"]) == 2
        assert row["occupancy_x_z_total"] == pytest.approx(
            sum(row["occupancy_x_z"]), abs=0.11)
        assert "the site holds" in r.summary["electron_count_reading"] or \
            "does NOT cluster" in r.summary["electron_count_reading"]

    def test_guards_run_nothing(self, project):
        p = project
        baseline = p.nodes.state()["active_node"]
        r = p.invoke_tool("element_scan", {"site": "ZR1",
                                           "elements": ["Zr", "Xx"]})
        assert not r.ok and "unknown element symbol" in r.error
        assert "Xx" in r.error
        r = p.invoke_tool("element_scan", {"site": "ZR1", "elements": [
            "Sc", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu"]})
        assert not r.ok and "per-call maximum" in r.error
        assert "chemistry" in r.error
        r = p.invoke_tool("element_scan", {"site": "ZR1", "elements": ["Zn"],
                                           "free_occupancy": True,
                                           "engine": "shelxl"})
        assert not r.ok and "engine='refine'" in r.error
        r = p.invoke_tool("element_scan", {"site": "NOPE",
                                           "elements": ["Zn"]})
        assert not r.ok and "unknown atom label" in r.error
        st = p.nodes.state()
        assert not any(b.startswith("diag/") for b in st["branches"])
        assert st["active_node"] == baseline and st["active_branch"] == "main"

    def test_time_budget_lists_untested_elements(self, project, monkeypatch):
        from crystalpilot.refine.tools_batch import ElementScan
        p = project
        calls = {"n": 0}

        def exhausted(elapsed, estimate, budget):
            calls["n"] += 1
            return calls["n"] > 1

        monkeypatch.setattr(ElementScan, "_budget_exhausted",
                            staticmethod(exhausted))
        baseline = p.nodes.state()["active_node"]
        r = p.invoke_tool("element_scan", {"site": "ZR1",
                                           "elements": ["Zn", "Hf", "Nb"],
                                           "cycles": 2, "time_budget_s": 90})
        assert r.ok, r.error
        s = r.summary
        assert [row["element"] for row in s["rows"]] == ["Zn"]
        assert s["not_tested"] == ["Hf", "Nb"]
        assert "elements=['Hf', 'Nb']" in s["timeout"]
        st = p.nodes.state()
        assert st["active_node"] == baseline and st["active_branch"] == "main"


# ==========================================================================
# crystal B: a framework with ONE site whose element is in question. The
# data hold Cl there (17 e) while the model calls it O (8 e) - the ka1 cage
# situation in miniature - or, in the counter-example, the data hold O
# there too. Nothing below is tuned to Cl: every assertion is about the
# measured electron count and the elements its Z brackets.
CELL_B = (10.0, 11.0, 12.0, 90.0, 100.0, 90.0)
SG_B = "P 1 21/c 1"
FRAME_B = [("CU1", "Cu", (0.25, 0.20, 0.25)),
           ("N1", "N", (0.45, 0.20, 0.25)),
           ("N2", "N", (0.25, 0.38, 0.25)),
           ("C1", "C", (0.53, 0.30, 0.25)),
           ("C2", "C", (0.35, 0.48, 0.25))]
X_SITE = (0.25, 0.20, 0.07)


def _z(el: str) -> int:
    from cctbx.eltbx import tiny_pse
    return int(tiny_pse.table(el).atomic_number())


def _structure_b(atoms):
    from cctbx import crystal, xray
    cs = crystal.symmetry(unit_cell=CELL_B, space_group_symbol=SG_B)
    xs = xray.structure(crystal_symmetry=cs)
    for lbl, el, site in atoms:
        xs.add_scatterer(xray.scatterer(label=lbl, site=site, u=0.02,
                                        occupancy=1.0, scattering_type=el))
    return xs


def _open_b(tmp_path: Path, true_element: str):
    """Anisotropically refined project whose X1 site is modelled as O while
    the DATA hold true_element there."""
    from cctbx.array_family import flex

    from crystalpilot.io.cif_sf import write_hklf4
    from crystalpilot.io.shelx_writer import ShelxModel, write_res
    d = tmp_path / "projB"
    d.mkdir()
    truth = _structure_b(FRAME_B + [("X1", true_element, X_SITE)])
    i_obs = truth.structure_factors(
        d_min=0.8, algorithm="direct").f_calc().as_intensity_array()
    flex.set_random_seed(11)
    noise = 1.0 + 0.01 * (flex.random_double(i_obs.size()) - 0.5)
    data = i_obs.data() * noise
    i_obs = i_obs.customized_copy(data=data, sigmas=0.02 * data + 0.5)
    write_hklf4(i_obs, d / "crystal.hkl")
    model = _structure_b(FRAME_B + [("X1", "O", X_SITE)])
    write_res(ShelxModel(xray_structure=model, wavelength=0.71073, z=4,
                         weights=(0.1, 0.0)), d / "start.res")
    (d / "context.json").write_text(json.dumps({
        "data": {"hkl": "crystal.hkl", "start_model": "start.res"}}),
        encoding="utf-8")
    p = _open(d)
    assert p.invoke_tool("refine", {"mode": "isotropic", "n_cycles": 6}).ok
    assert p.invoke_tool("refine", {"mode": "anisotropic", "n_cycles": 6}).ok
    return p


class TestFreeOccupancyActuallyRefines:
    """Regression for the ka1 cage defect (2026-09).

    ROOT CAUSE: element_scan set grad_occupancy on the scatterer and then
    ran its ordinary ALL-FREE refinement. An occupancy does not move there:
    the atom's own ADP is 1:1 correlated with it and absorbs the whole
    scattering-power mismatch, and Levenberg-Marquardt damping on a model
    with hundreds of parameters starves the lone occupancy shift. All three
    cage-lane calls came back with occupancy exactly 1.000 on every row, so
    occupancy x Z degenerated into Z, "full-occupancy Cl vs full-occupancy
    O" dug a -14 e/A^3 hole at the site, Cl was read as excluded, and the
    delivery labelled a Cl as O. probe_site never had the bug because it
    refines the occupancy ALONE first, with every site and ADP held - a
    one-parameter least squares. element_scan now runs the same stage.

    Before the fix this test fails on the first assertion: on an
    anisotropic model every occupancy comes back as exactly 1.000.
    """

    def test_occupancy_moves_and_the_count_clusters(self, tmp_path):
        p = _open_b(tmp_path, "Cl")
        r = p.invoke_tool("element_scan", {
            "site": "X1", "elements": ["O", "S", "Cl"], "cycles": 4,
            "free_occupancy": True})
        assert r.ok, r.error
        s = r.summary
        rows = {row["element"]: row for row in s["rows"]}
        # (1) the flag is honoured: the occupancy leaves its starting value
        assert s["free_occupancy_applied"] is True
        assert all(row["free_occupancy_applied"] for row in rows.values())
        assert any(abs(row["occupancy_at_fixed_u"] - 1.0) > 0.05
                   for row in rows.values()), \
            "every occupancy came back at its starting value"
        # (2) occupancy x Z measures the SITE, not the candidate's Z: the
        # light candidate needs more of itself, the heavy one less
        assert rows["O"]["occupancy_at_fixed_u"] > \
            rows["S"]["occupancy_at_fixed_u"] > 0.5
        assert rows["O"]["occupancy_x_z"] != rows["O"]["z"]
        counts = [rows[el]["occupancy_x_z"] for el in ("O", "S", "Cl")]
        assert max(counts) <= 1.6 * min(counts)
        assert min(counts) > 12.0          # the site really holds ~17 e
        # (3) the reading is one-directional: a count, never a winner
        assert "the site holds" in s["electron_count_reading"]
        assert not any(k in s for k in ("chosen", "best_element", "winner"))
        assert "Cl" in s["candidates_bracketing_the_count"]
        assert "cannot tell them apart" in s["bracket_note"]

    def test_a_site_that_really_is_o_refines_to_full_occupancy(self, tmp_path):
        """Counter-example: same cell, same labels, but the data hold O at
        the site. O must refine to ~1 and the heavier candidates below 1."""
        p = _open_b(tmp_path, "O")
        r = p.invoke_tool("element_scan", {
            "site": "X1", "elements": ["O", "S", "Cl"], "cycles": 4,
            "free_occupancy": True})
        assert r.ok, r.error
        s = r.summary
        rows = {row["element"]: row for row in s["rows"]}
        assert rows["O"]["occupancy_at_fixed_u"] == pytest.approx(1.0, abs=0.2)
        assert rows["Cl"]["occupancy_at_fixed_u"] < 0.8
        assert rows["S"]["occupancy_at_fixed_u"] < 0.9
        counts = [rows[el]["occupancy_x_z"] for el in ("O", "S", "Cl")]
        assert max(counts) < 13.0          # ~8 e, not 17
        assert "O" in s["candidates_bracketing_the_count"]

    def test_shelxl_engine_refuses_instead_of_a_fake_1_000(self, tmp_path):
        p = _open_b(tmp_path, "Cl")
        r = p.invoke_tool("element_scan", {
            "site": "X1", "elements": ["O", "Cl"], "free_occupancy": True,
            "engine": "shelxl"})
        assert not r.ok
        assert "free_occupancy_applied would be false" in r.error
        assert "engine='refine'" in r.error


class TestElectronCountCalibration:
    """P1-8: an electron count read on an incomplete model is a LOWER
    bound, and the candidates it brackets follow from Z, not from a list."""

    def test_low_count_note_only_above_the_disclosed_threshold(self):
        from crystalpilot.refine.tools_batch import (LOW_COUNT_R1,
                                                     count_is_low_biased,
                                                     low_count_note)
        assert low_count_note(LOW_COUNT_R1 - 0.01) is None
        assert low_count_note(None) is None
        assert count_is_low_biased(LOW_COUNT_R1 + 0.01)
        note = low_count_note(0.23)
        assert "disclosed heuristic, not a verdict" in note
        assert "LOWER BOUND" in note
        assert "is NOT a safe reading" in note
        assert str(LOW_COUNT_R1) in note

    def test_bracket_follows_from_z_not_from_a_fixed_list(self):
        from crystalpilot.refine.tools_batch import bracketing_elements
        # ka1 cage: ~8.8 e measured on a model at R1 0.19-0.23. The halogen
        # the reference has must be inside the proposal; on a CONVERGED
        # model the same count must not drag it in.
        wide = bracketing_elements(8.8, low_biased=True)
        assert "Cl" in wide and "O" in wide and "F" in wide
        tight = bracketing_elements(8.8, low_biased=False)
        assert "Cl" not in tight and "O" in tight
        # nothing is hard-coded to the light end: the same rule brackets a
        # metal-weight count with metals, and always spans the count
        heavy = bracketing_elements(30.0)
        assert all(el not in heavy for el in ("O", "F", "Cl"))
        assert min(_z(el) for el in heavy) <= 30 <= max(_z(el) for el in heavy)
        assert bracketing_elements(None) == [] == bracketing_elements(0)
        # noble gases are never proposed - they are not in crystals
        for n in (10, 18, 36, 54):
            assert not ({"Ne", "Ar", "Kr", "Xe"}
                        & set(bracketing_elements(n, low_biased=True)))


class TestWeightAdviceIsAdoptWght:
    """P1-13b: the cage full arm followed 'or optimize_weights' into a
    65-minute hang; the readiness note now names one route."""

    def test_readiness_recommends_adopt_wght(self, project):
        r = project.invoke_tool("element_scan", {"site": "ZR1",
                                                 "elements": ["Zr"],
                                                 "cycles": 2})
        assert r.ok, r.error
        note = next(n["note"] for n in r.summary["readiness"]
                    if n["kind"] == "weights_not_adopted")
        assert "run_shelxl(mode='adopt_wght')" in note
        assert "Do NOT reach for optimize_weights" in note
        assert "65" in note

    def test_optimize_weights_describes_itself_as_the_fallback(self):
        from crystalpilot.tools.hydrogen_tools import OptimizeWeights
        d = OptimizeWeights.description
        assert "NOT the first choice" in d
        assert "run_shelxl(mode='adopt_wght')" in d
