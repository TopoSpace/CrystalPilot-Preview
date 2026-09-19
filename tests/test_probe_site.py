"""probe_site: a candidate atom refined at FREE occupancy on a throw-away
branch, plus the mask-aware reading of integrate_difference_density.

pa3: the brief announced a low-occupancy heavy atom in the pore; the agent
integrated the void peaks, measured them against the FULL-occupancy
electron count and wrote "absent" - the referee put the atom in, freed its
occupancy and got 0.125. The data here are synthetic (Fc^2 of small
models, 1% noise) in three space groups, with different elements, so the
in-process engine refines every stage in well under a second and nothing
is tuned to one crystal: a complete P-1 Zr/O/C model (re-typing at a real
site, an empty site) and a P21/c Cu/N/C/Cl framework whose data hold a
0.25-occupancy Br guest the model lacks (the pa3 situation in miniature),
the latter also with its 60%-void masked so the mask swallows the guest
and has to be switched off to see it.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from crystalpilot.refine.tools_probe import (OCC_ABSENT, ProbeSite,
                                             bond_plausibility,
                                             expected_electrons_table,
                                             occupancy_note, probe_verdict,
                                             void_membership)

# -- crystal A: complete model, P -1 (same skeleton as test_batch_tests)
CELL_A = (7.0, 8.0, 9.0, 85.0, 95.0, 100.0)
ATOMS_A = [("ZR1", "Zr", (0.25, 0.10, 0.15)),
           ("O1", "O", (0.40, 0.20, 0.30)),
           ("O2", "O", (0.10, 0.25, 0.05)),
           ("C1", "C", (0.55, 0.30, 0.40)),
           ("C2", "C", (0.65, 0.42, 0.55))]
EMPTY_A = (0.50, 0.75, 0.10)          # >= 3 A from every atom

# -- crystal B: P 21/c framework + a 0.25-occupancy Br guest in the data only
CELL_B = (10.0, 11.0, 12.0, 90.0, 100.0, 90.0)
SG_B = "P 1 21/c 1"
FRAME_B = [("CU1", "Cu", (0.25, 0.20, 0.25)),
           ("N1", "N", (0.45, 0.20, 0.25)),
           ("N2", "N", (0.25, 0.38, 0.25)),
           ("C1", "C", (0.53, 0.30, 0.25)),
           ("C2", "C", (0.35, 0.48, 0.25)),
           ("CL1", "Cl", (0.25, 0.20, 0.07))]
GUEST_B = ("BR1", "Br", (0.60, 0.40, 0.55), 0.25, 0.03)

GUEST_SITE = GUEST_B[2]
#: 1.0 A from CU1 (and from N1): inside their vdW spheres, never masked
NEAR_CU = (0.35, 0.20, 0.25)


def _structure(cell, sg, atoms):
    from cctbx import crystal, xray
    cs = crystal.symmetry(unit_cell=cell, space_group_symbol=sg)
    xs = xray.structure(crystal_symmetry=cs)
    for a in atoms:
        lbl, el, site = a[:3]
        occ = a[3] if len(a) > 3 else 1.0
        u = a[4] if len(a) > 4 else 0.02
        xs.add_scatterer(xray.scatterer(label=lbl, site=site, u=u,
                                        occupancy=occ, scattering_type=el))
    return xs


def make_project(tmp_path: Path, cell, sg, model_atoms, data_atoms, z,
                 d_min: float = 0.8) -> Path:
    """Project dir with HKLF4 data computed from data_atoms and a start
    model made of model_atoms (1% multiplicative noise)."""
    from cctbx.array_family import flex

    from crystalpilot.io.cif_sf import write_hklf4
    from crystalpilot.io.shelx_writer import ShelxModel, write_res
    d = tmp_path / "proj"
    d.mkdir()
    truth = _structure(cell, sg, data_atoms)
    i_obs = truth.structure_factors(
        d_min=d_min, algorithm="direct").f_calc().as_intensity_array()
    flex.set_random_seed(11)
    noise = 1.0 + 0.01 * (flex.random_double(i_obs.size()) - 0.5)
    data = i_obs.data() * noise
    i_obs = i_obs.customized_copy(data=data, sigmas=0.02 * data + 0.5)
    write_hklf4(i_obs, d / "crystal.hkl")
    write_res(ShelxModel(xray_structure=_structure(cell, sg, model_atoms),
                         wavelength=0.71073, z=z, weights=(0.1, 0.0)),
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
def project_a(tmp_path):
    return _open(make_project(tmp_path, CELL_A, "P -1", ATOMS_A, ATOMS_A,
                              z=2, d_min=0.75))


@pytest.fixture()
def project_b(tmp_path):
    return _open(make_project(tmp_path, CELL_B, SG_B, FRAME_B,
                              FRAME_B + [GUEST_B], z=4, d_min=0.8))


@pytest.fixture()
def project_masked(tmp_path):
    """Crystal B with a solvent mask stored on the baseline: the framework
    fills a third of the cell, the void (with the Br in it) is masked -
    the pa3 situation, guest density inside the mask."""
    p = _open(make_project(tmp_path, CELL_B, SG_B, FRAME_B,
                           FRAME_B + [GUEST_B], z=4, d_min=0.8))
    r = p.invoke_tool("solvent_mask", {"max_cycles": 10})
    assert r.ok, r.error
    assert r.summary["n_voids_masked"] >= 1
    assert r.summary["solvent_volume_pct_of_cell"] > 30
    assert p.session.flags.get("f_mask") is not None
    return p, r.summary


def _state(p):
    return p.nodes.state()


def _sym_distance(cell, sg, a, b) -> float:
    """Shortest distance between two fractional sites over all symmetry
    images of b."""
    from cctbx import crystal
    cs = crystal.symmetry(unit_cell=cell, space_group_symbol=sg)
    uc = cs.unit_cell()
    best = float("inf")
    for op in cs.space_group().all_ops():
        s = op * tuple(b)
        s = tuple(s[k] - round(s[k] - a[k]) for k in range(3))
        best = min(best, uc.distance(tuple(a), s))
    return best


# ==========================================================================
class TestPureHelpers:
    def test_expected_electrons_table_is_occupancy_times_z_for_any_element(self):
        assert expected_electrons_table("Br") == {
            "0.1": 3.5, "0.125": 4.4, "0.25": 8.8, "0.5": 17.5, "1.0": 35.0}
        assert expected_electrons_table("I")["0.5"] == 26.5
        assert expected_electrons_table("c")["1.0"] == 6.0
        assert expected_electrons_table("Xx") is None

    def test_occupancy_note_names_the_element_and_the_ladder(self):
        note = occupancy_note()
        assert "0.125-occupancy Br is 4.4 e, not 35 e" in note
        assert "never with the full-occupancy value" in note
        assert "0.125-occupancy I is 6.6 e, not 53 e" in occupancy_note("I")

    def test_verdict_fences_are_generic_refinement_criteria(self):
        base = {"occupancy_at_fixed_u": 0.13, "occupancy_refined": 0.125,
                "electrons_refined": 4.4, "u_iso_refined": 0.08,
                "delta_r1": -0.003, "delta_wr2": -0.006,
                "residual_before": {"max": 1.4}, "residual_after": {"max": 0.3},
                "site_shift_A": 0.05}
        v, why = probe_verdict(base)
        assert v == "supported" and "converged" in why
        v, why = probe_verdict({**base, "occupancy_at_fixed_u": 0.004,
                                "occupancy_refined": 0.003})
        assert v == "not_supported" and "no occupancy" in why
        v, why = probe_verdict({**base, "u_iso_refined": 0.9})
        assert v == "not_supported" and "smeared" in why
        v, why = probe_verdict({**base, "delta_r1": 0.004, "delta_wr2": 0.01})
        assert v == "not_supported" and "worsened" in why
        v, why = probe_verdict({**base, "occupancy_at_fixed_u": 1.4,
                                "occupancy_refined": 1.33,
                                "electrons_refined": 39.9})
        assert v == "borderline" and "too LIGHT" in why
        v, why = probe_verdict({**base, "site_shift_A": 0.9})
        assert v == "borderline" and "drifted" in why
        v, why = probe_verdict({**base, "occupancy_at_fixed_u": 0.40})
        assert v == "borderline" and "depends on Uiso" in why
        v, _ = probe_verdict({**base, "delta_r1": 0.0, "delta_wr2": 0.0})
        assert v == "borderline"
        v, _ = probe_verdict({"occupancy_refined": None, "delta_r1": None})
        assert v == "inconclusive"

    def test_bond_plausibility_is_covalent_radius_sums_for_any_pair(self):
        rows = bond_plausibility("Br", [
            {"label": "C7", "element": "C", "d_A": 1.91},
            {"label": "C8", "element": "C", "d_A": 2.80},
            {"label": "O3", "element": "O", "d_A": 1.20}])
        by = {r["partner"]: r for r in rows}
        assert by["C7"]["assessment"] == "bond-length match"
        assert "covalent radii" in by["C7"]["reference"]
        assert by["C8"]["assessment"].startswith("longer than a bond")
        assert by["O3"]["assessment"] == "too short: clash"
        # a metal meeting O/N uses the coordination window of the
        # chemistry table (Zr-O 2.00-2.45), any other pair the radii
        zr = bond_plausibility("O", [{"label": "ZR1", "element": "Zr",
                                      "d_A": 2.15}])[0]
        assert zr["assessment"] == "bond-length match"
        assert "coordination window" in zr["reference"]
        cu = bond_plausibility("Cl", [{"label": "CU1", "element": "Cu",
                                       "d_A": 2.25}])[0]
        assert cu["assessment"] == "bond-length match"
        xx = bond_plausibility("Xx", [{"label": "C1", "element": "C",
                                       "d_A": 1.5}])[0]
        assert "no reference" in xx["assessment"]

    def test_void_membership_follows_the_around_atoms_rule(self):
        """One C in a 20 A P1 cell, default mask radii 1.2/1.2: masked
        region = points from which a point within the shrink radius is
        farther than vdW + solvent radius from the atom, i.e. everything
        beyond the vdW surface (1.775 A)."""
        xs = _structure((20.0, 20.0, 20.0, 90, 90, 90), "P 1",
                        [("C1", "C", (0.5, 0.5, 0.5))])
        near = void_membership(xs, (0.5 + 1.2 / 20, 0.5, 0.5), 1.2, 1.2)
        assert near["inside"] is False and near["nearest_atom"] == "C1"
        assert near["clearance_A"] < 0
        edge = void_membership(xs, (0.5 + 2.2 / 20, 0.5, 0.5), 1.2, 1.2)
        assert edge["inside"] is True and edge["nearest_d_A"] == 2.2
        far = void_membership(xs, (0.0, 0.0, 0.0), 1.2, 1.2)
        assert far["inside"] is True
        # a larger shrink radius reaches further back towards the atom
        assert void_membership(xs, (0.5 + 1.2 / 20, 0.5, 0.5), 1.2,
                               2.0)["inside"] is True

    def test_chem_hint_terminal_o_carbon_and_metal_donor(self):
        from crystalpilot.tools.refinement_tools import (
            CHEM_HINT_METAL_DONOR, CHEM_HINT_TERMINAL_O_CARBON, annotate_peaks,
            peak_chem_hint)
        a = 20.0
        xs = _structure((a, a, a, 90, 90, 90), "P 1", [
            ("ZR1", "Zr", (0.0, 0.0, 0.0)),
            ("O1", "O", (2.1 / a, 0.0, 0.0)),            # terminal on Zr1
            ("O2", "O", (0.0, 0.0, 2.1 / a)),            # carboxylate O...
            ("C1", "C", (0.0, 0.0, (2.1 + 1.25) / a)),   # ...with its C
        ])
        # a peak 1.4 A beyond the terminal O: carboxylate / formate carbon
        assert peak_chem_hint(xs, "O1", 1.4) == CHEM_HINT_TERMINAL_O_CARBON
        # 2.2 A from the metal: a donor atom
        assert peak_chem_hint(xs, "ZR1", 2.2) == CHEM_HINT_METAL_DONOR
        # O2 already carries a carbon: not terminal, no hint
        assert peak_chem_hint(xs, "O2", 1.4) is None
        # outside the windows: nothing
        assert peak_chem_hint(xs, "O1", 0.9) is None
        assert peak_chem_hint(xs, "ZR1", 3.2) is None
        assert peak_chem_hint(xs, "C1", 1.4) is None
        rows = annotate_peaks(xs, [((2.1 + 1.4) / a, 0.0, 0.0),
                                   (0.0, 2.2 / a, 0.0),
                                   (0.0, 1.4 / a, 2.1 / a)],
                              [1.8, 1.2, 1.0])
        assert rows[0]["nearest_atom"] == "O1"
        assert rows[0]["chem_hint"] == CHEM_HINT_TERMINAL_O_CARBON
        assert rows[1]["chem_hint"] == CHEM_HINT_METAL_DONOR
        assert "chem_hint" not in rows[2]
        # the table's existing keys are untouched
        assert set(rows[0]) == {"site", "height", "nearest_atom",
                                "nearest_d", "chem_hint"}


# ==========================================================================
class TestRegistration:
    def test_probe_site_is_registered_and_classified(self, project_a):
        from crystalpilot.mcp.server import READ_ONLY_TOOLS
        from crystalpilot.refine.registry import MUTATING_TOOLS
        assert "probe_site" in project_a.registry.names()
        # commits diagnostic nodes and restores the baseline: neither a
        # model mutation nor a pure read (same class as ghost_test)
        assert "probe_site" not in MUTATING_TOOLS
        assert "probe_site" not in READ_ONLY_TOOLS
        spec = project_a.registry.get("probe_site")
        props = spec.params_schema["properties"]
        assert {"element", "elements", "site", "peak", "near_atom",
                "occupancy_start", "u_iso_start", "cycles", "node_id",
                "mask", "time_budget_s"} == set(props)
        assert props["mask"]["enum"] == ["auto", "off", "on"]
        assert ProbeSite.tag == "probe_site"


# ==========================================================================
class TestProbeSiteZr:
    """Crystal A (P -1, complete model): re-typing a real atom and probing
    an empty site."""

    def test_near_atom_with_the_right_element_is_supported(self, project_a):
        p = project_a
        baseline = _state(p)["active_node"]
        r = p.invoke_tool("probe_site", {"element": "C", "near_atom": "c1",
                                         "cycles": 5})
        assert r.ok, r.error
        s = r.summary
        assert s["position"]["mode"] == "near_atom"
        assert s["position"]["omit"]["label"] == "C1"
        assert s["position"]["omit"]["element"] == "C"
        assert s["baseline"]["reference"]["omitted"] == "C1"
        assert s["baseline"]["reference"]["n_atoms"] == 4
        row = s["rows"][0]
        assert row["element"] == "C" and row["z"] == 6
        assert row["label"] == "CP1"
        assert row["verdict"] == "supported", row["reason"]
        assert s["verdicts"] == {"C": "supported"}
        assert row["occupancy_refined"] == pytest.approx(1.0, abs=0.1)
        assert row["occupancy_at_fixed_u"] > 0.5
        assert row["electrons_refined"] == pytest.approx(
            row["occupancy_refined"] * 6, abs=0.05)
        assert 0.005 < row["u_iso_refined"] < 0.1
        assert row["site_shift_A"] < 0.2
        assert row["delta_r1"] < -0.0005
        assert row["residual_after"]["max"] < row["residual_before"]["max"]
        # the omit map at the site holds most of a carbon's 6 electrons
        assert 2.5 < row["omit_map_electrons"] < 9.0
        assert row["expected_electrons_at_occupancy"]["1.0"] == 6.0
        assert row["stage_a"]["what"].startswith("occupancy only")
        assert row["stage_b"]["what"].startswith("probe site, Uiso and "
                                                "occupancy free")
        assert row["stage_c"]["what"] == "everything free"
        assert row["stage_c"]["node"] == row["node"]
        assert row["nearest_atoms"] and all(
            nb["label"] != "C1" for nb in row["nearest_atoms"])
        assert any(b["assessment"] == "bond-length match"
                   for b in row["bond_plausibility"])
        assert "add_atoms_from_difference_map" in row["disposition"]
        assert "solvent_mask" in row["disposition"]
        assert "4.4 e, not 35 e" not in s["note"]      # the note names C
        assert "0.125-occupancy C is 0.8 e, not 6 e" in s["note"]
        assert "occupancy x Z" in s["how_to_read"]
        # no mask in the session: nothing to switch, said plainly
        assert s["mask_handling"]["session_has_mask"] is False
        assert s["mask_handling"]["mask_used"] is False
        # tree discipline: diagnostic branches, baseline restored intact
        st = _state(p)
        assert st["active_node"] == baseline and st["active_branch"] == "main"
        assert st["branches"]["main"] == baseline
        assert f"diag/probe_site/{baseline}/reference" in st["branches"]
        assert row["branch"] == f"diag/probe_site/{baseline}/C@0.550,0.300,0.400"
        assert row["branch"] in st["branches"]
        meta = p.nodes.node_meta(row["node"])
        assert meta["diagnostic"] == {"tool": "probe_site",
                                      "baseline": baseline,
                                      "candidate": "C@0.550,0.300,0.400",
                                      "step": "refine[free]"}
        assert "not a delivery" in meta["note"]
        assert p.session.model.scatterers().size() == 5
        assert {sc.label for sc in p.session.model.scatterers()} == {
            "ZR1", "O1", "O2", "C1", "C2"}
        assert not any(sc.flags.grad_occupancy()
                       for sc in p.session.model.scatterers())
        assert s["restore"] == {"restored": True, "node": baseline,
                                "branch": "main"}

    def test_heavy_atom_at_an_empty_site_is_not_supported(self, project_a):
        p = project_a
        baseline = _state(p)["active_node"]
        r = p.invoke_tool("probe_site", {"element": "Br",
                                         "site": list(EMPTY_A), "cycles": 4})
        assert r.ok, r.error
        s = r.summary
        assert s["position"]["mode"] == "site"
        row = s["rows"][0]
        assert row["verdict"] == "not_supported", row["reason"]
        assert row["occupancy_at_fixed_u"] < OCC_ABSENT
        assert row["occupancy_refined"] < OCC_ABSENT
        assert row["stage_b"] is None and row["stage_c"] is None
        assert row["u_iso_refined"] is None
        assert "nothing to free" in row["stage_note"]
        assert row["stage_a"]["cycles"] == 3
        assert abs(row["electrons_refined"]) < 1.0
        assert row["omit_map_electrons"] < 1.5
        assert "diffuse guest stays in the mask" in row["disposition"]
        assert row["expected_electrons_at_occupancy"] == {
            "0.1": 3.5, "0.125": 4.4, "0.25": 8.8, "0.5": 17.5, "1.0": 35.0}
        assert row["nearest_atoms"] == []        # nothing within 3 A
        assert row["bond_plausibility"] == []
        assert "4.4 e, not 35 e" in s["note"]
        st = _state(p)
        assert st["active_node"] == baseline and st["active_branch"] == "main"
        assert p.session.model.scatterers().size() == 5

    def test_too_light_element_reads_as_occupancy_above_one(self, project_a):
        """Zr re-typed as Zn: occupancy x Z stays ~40 e, so the occupancy
        lands well above 1 - flagged, never called 'supported'."""
        p = project_a
        r = p.invoke_tool("probe_site", {"element": "Zn", "near_atom": "ZR1",
                                         "cycles": 6})
        assert r.ok, r.error
        row = r.summary["rows"][0]
        assert row["occupancy_refined"] > 1.05
        assert row["electrons_refined"] == pytest.approx(40.0, rel=0.15)
        assert row["verdict"] == "borderline", row["reason"]
        assert "too LIGHT" in row["reason"]
        assert "do not conclude" in row["disposition"]
        assert p.session.model.scatterers()[0].scattering_type.strip() == "Zr"

    def test_refusals_run_nothing(self, project_a):
        p = project_a
        baseline = _state(p)["active_node"]
        cases = [
            ({"site": list(EMPTY_A)}, "candidate element"),
            ({"element": "Xx", "site": list(EMPTY_A)}, "unknown element"),
            ({"element": "Br"}, "exactly one position"),
            ({"element": "Br", "site": [0.1, 0.2]}, "three fractional"),
            ({"element": "Br", "site": "0.1,0.2,0.3"}, "three fractional"),
            ({"element": "Br", "site": list(EMPTY_A), "near_atom": "C1"},
             "exactly one position"),
            ({"element": "Br", "peak": 0}, "no difference-map peak table"),
            ({"element": "Br", "near_atom": "NOPE"}, "not in the baseline"),
            ({"element": "Br", "site": list(EMPTY_A), "mask": "maybe"},
             "mask must be"),
            ({"element": "Br", "site": list(EMPTY_A), "cycles": 0}, "cycles"),
            ({"element": "Br", "site": list(EMPTY_A), "occupancy_start": 5},
             "occupancy_start"),
            ({"element": "Br", "site": list(EMPTY_A), "u_iso_start": 0.0},
             "u_iso_start"),
            ({"element": "Br", "site": list(EMPTY_A), "time_budget_s": 5},
             "time_budget_s"),
            ({"elements": ["Br", "Cl", "I", "S", "P"], "site": list(EMPTY_A)},
             "per-call maximum"),
            # ON an existing atom is not a new site
            ({"element": "N", "site": [0.40, 0.20, 0.30]}, "near_atom='O1'"),
        ]
        for params, needle in cases:
            r = p.invoke_tool("probe_site", params)
            assert not r.ok, params
            assert needle in r.error, (params, r.error)
        st = _state(p)
        assert not any(b.startswith("diag/") for b in st["branches"])
        assert st["active_node"] == baseline and st["active_branch"] == "main"

    def test_peak_out_of_range_names_the_table(self, project_a):
        p = project_a
        assert p.invoke_tool("inspect_map", {"n_peaks": 5}).ok
        r = p.invoke_tool("probe_site", {"element": "Br", "peak": 99})
        assert not r.ok and "outside the stored table" in r.error
        assert "indices 0-" in r.error

    def test_time_budget_lists_untested_elements(self, project_a, monkeypatch):
        p = project_a
        calls = {"n": 0}

        def exhausted(elapsed, estimate, budget):
            calls["n"] += 1
            return calls["n"] > 1

        monkeypatch.setattr(ProbeSite, "_budget_exhausted",
                            staticmethod(exhausted))
        baseline = _state(p)["active_node"]
        r = p.invoke_tool("probe_site", {"elements": ["Br", "Cl", "I"],
                                         "site": list(EMPTY_A), "cycles": 2,
                                         "time_budget_s": 90})
        assert r.ok, r.error
        s = r.summary
        assert [row["element"] for row in s["rows"]] == ["Br"]
        assert s["n_tested"] == 1 and s["not_tested"] == ["Cl", "I"]
        assert "elements=['Cl', 'I']" in s["timeout"]
        assert "probe_site tested 1 of 3" in s["timeout"]
        st = _state(p)
        assert st["active_node"] == baseline and st["active_branch"] == "main"

    def test_failed_reference_aborts_before_any_candidate(self, project_a,
                                                          monkeypatch):
        from crystalpilot.tools.base import ToolResult
        p = project_a
        orig = p.invoke_tool

        def broken(name, params=None, progress=None):
            if name == "refine":
                return ToolResult.failure("singular matrix (simulated)")
            return orig(name, params, progress=progress)

        monkeypatch.setattr(p, "invoke_tool", broken)
        baseline = _state(p)["active_node"]
        r = p.invoke_tool("probe_site", {"element": "Br",
                                         "site": list(EMPTY_A)})
        assert not r.ok
        assert "reference refinement" in r.error
        assert "singular matrix" in r.error
        assert "no candidate was run" in r.error
        assert r.summary["restore"]["restored"] is True
        st = _state(p)
        assert st["active_node"] == baseline and st["active_branch"] == "main"
        assert not any(b.startswith("diag/probe_site/") and "@" in b
                       for b in st["branches"])


# ==========================================================================
class TestProbeSiteGuest:
    """Crystal B (P 21/c): the data hold a 0.25-occupancy Br the model
    lacks - the pa3 situation without any pa3 numbers."""

    def test_partial_occupancy_guest_is_recovered_and_z_is_not_resolved(
            self, project_b):
        p = project_b
        baseline = _state(p)["active_node"]
        r = p.invoke_tool("probe_site", {"elements": ["Br", "Cl"],
                                         "site": list(GUEST_B[2]),
                                         "cycles": 6})
        assert r.ok, r.error
        s = r.summary
        rows = {row["element"]: row for row in s["rows"]}
        br, cl = rows["Br"], rows["Cl"]
        assert br["verdict"] == "supported", br["reason"]
        assert br["occupancy_refined"] == pytest.approx(0.25, abs=0.06)
        assert br["electrons_refined"] == pytest.approx(8.75, abs=2.0)
        assert 0.01 <= br["u_iso_refined"] <= 0.12
        assert br["site_shift_A"] < 0.2
        assert br["delta_r1"] < -0.005
        assert br["residual_before"]["max"] > 1.0
        assert br["residual_after"]["max"] < br["residual_before"]["max"]
        # the omit map holds electrons on the order of 0.25 x 35, and the
        # table says what 0.25 of a Br is - the full-occupancy 35 e is
        # never the yardstick
        assert 3.5 < br["omit_map_electrons"] < 13.0
        assert br["expected_electrons_at_occupancy"]["0.25"] == 8.8
        assert br["label"] == "BRP1"
        # Cl fits the same electrons at a higher occupancy: this test pins
        # occupancy x Z, not the element
        assert cl["electrons_refined"] == pytest.approx(
            br["electrons_refined"], rel=0.25)
        assert cl["occupancy_refined"] > br["occupancy_refined"]
        assert "NOT distinguished" in s["how_to_read"]
        assert s["mask_handling"]["session_has_mask"] is False
        # an isolated guest: the nearest framework atom (a symmetry image
        # of C2, 2.7 A) is a contact, not a bond - said as such
        assert [nb["label"] for nb in br["nearest_atoms"]] == ["C2"]
        assert br["nearest_atoms"][0]["d_A"] > 2.5
        assert br["bond_plausibility"][0]["pair"] == "Br-C"
        assert br["bond_plausibility"][0]["assessment"].startswith(
            "longer than a bond")
        st = _state(p)
        assert st["active_node"] == baseline and st["active_branch"] == "main"
        assert p.session.model.scatterers().size() == 6
        assert f"diag/probe_site/{baseline}/Br@0.600,0.400,0.550" in \
            st["branches"]
        assert f"diag/probe_site/{baseline}/Cl@0.600,0.400,0.550" in \
            st["branches"]

    def test_peak_mode_reads_the_session_table(self, project_b):
        """inspect_map on the baseline puts the guest's peak first; peak=0
        is that peak, exactly as inspect_map lists it under 'i'."""
        p = project_b
        m = p.invoke_tool("inspect_map", {"n_peaks": 10})
        assert m.ok, m.error
        top = m.summary["peaks"][0]
        assert top["i"] == 0 and top["height"] > 1.0
        # the peak search reports whichever symmetry image it likes
        assert _sym_distance(CELL_B, SG_B, tuple(top["site"]),
                             GUEST_SITE) < 0.3
        r = p.invoke_tool("probe_site", {"element": "Br", "peak": 0,
                                         "cycles": 5})
        assert r.ok, r.error
        s = r.summary
        assert s["position"]["mode"] == "peak"
        assert s["position"]["peak_index"] == 0
        assert s["position"]["peak_height"] == top["height"]
        assert _sym_distance(CELL_B, SG_B, tuple(s["position"]["site_frac"]),
                             GUEST_SITE) < 0.3
        row = s["rows"][0]
        assert row["verdict"] == "supported", row["reason"]
        assert row["occupancy_refined"] == pytest.approx(0.25, abs=0.06)


# ==========================================================================
class TestMaskHandling:
    """Crystal B with its void masked: the mask has swallowed the Br."""

    def test_solvent_mask_says_it_cannot_find_a_guest(self, project_masked):
        _, mask_summary = project_masked
        note = mask_summary["guest_search_note"]
        assert "suppressed by construction" in note
        assert "PRE-mask" in note and "probe_site" in note
        assert "cannot find a guest" in note

    def test_auto_switches_the_mask_off_inside_the_void(self, project_masked):
        p, _ = project_masked
        baseline = _state(p)["active_node"]
        r = p.invoke_tool("probe_site", {"element": "Br",
                                         "site": list(GUEST_SITE), "cycles": 6})
        assert r.ok, r.error
        s = r.summary
        mh = s["mask_handling"]
        assert mh["mode"] == "auto" and mh["session_has_mask"] is True
        assert mh["sites_in_masked_void"] == [True]
        assert mh["mask_used"] is False
        assert "switched OFF automatically" in mh["note"]
        assert "suppressed by construction" in mh["note"]
        assert "around_atoms" in mh["rule"]
        assert mh["void_test"][0]["nearest_atom"] == "C2"
        assert mh["void_test"][0]["clearance_A"] > 0
        # reference and candidate were refined WITHOUT the mask, and the
        # diagnostic nodes say so (no mask block, no f_mask snapshot)
        assert s["baseline"]["reference"]["solvent_mask"] is False
        ref_node = s["baseline"]["reference"]["node"]
        assert p.nodes.node_meta(ref_node)["mask"] is None
        assert not (p.nodes.node_dir(ref_node) / "f_mask.pkl").exists()
        row = s["rows"][0]
        assert p.nodes.node_meta(row["node"])["mask"] is None
        assert row["verdict"] == "supported", row["reason"]
        assert row["occupancy_refined"] == pytest.approx(0.25, abs=0.08)
        assert row["electrons_refined"] == pytest.approx(8.75, rel=0.35)
        assert row["omit_map_electrons"] > 3.0
        assert "0.125-occupancy Br is 4.4 e, not 35 e" in s["note"]
        # the baseline came back WITH its mask
        st = _state(p)
        assert st["active_node"] == baseline and st["active_branch"] == "main"
        assert p.session.flags.get("f_mask") is not None
        assert p.session.flags.get("solvent_mask_params") is not None
        assert p.session.model.scatterers().size() == 6

    def test_mask_on_is_honoured_and_warned(self, project_masked):
        p, _ = project_masked
        r = p.invoke_tool("probe_site", {"element": "Br",
                                         "site": list(GUEST_SITE), "cycles": 4,
                                         "mask": "on"})
        assert r.ok, r.error
        mh = r.summary["mask_handling"]
        assert mh["mask_used"] is True
        assert "INSIDE the masked void" in mh["warning"]
        assert "not evidence of absence" in mh["warning"]
        assert r.summary["baseline"]["reference"]["solvent_mask"] is True
        ref_node = r.summary["baseline"]["reference"]["node"]
        assert p.nodes.node_meta(ref_node)["mask"] is not None
        # with the mask left in Fc the probe sees only what the mask left
        row = r.summary["rows"][0]
        off = p.invoke_tool("probe_site", {"element": "Br",
                                           "site": list(GUEST_SITE),
                                           "cycles": 4, "mask": "off"})
        assert off.ok, off.error
        assert off.summary["mask_handling"]["mask_used"] is False
        assert "switched OFF on request" in off.summary["mask_handling"]["note"]
        assert row["occupancy_at_fixed_u"] < \
            off.summary["rows"][0]["occupancy_at_fixed_u"]
        assert row["omit_map_electrons"] < \
            off.summary["rows"][0]["omit_map_electrons"]

    def test_integrate_auto_matches_probe_and_keeps_mask_near_framework(
            self, project_masked):
        p, _ = project_masked
        baseline = _state(p)["active_node"]
        # auto on the masked baseline: the site is in the void -> mask off
        auto = p.invoke_tool("integrate_difference_density", {
            "site_frac": list(GUEST_SITE), "radius_A": 1.0, "element": "Br"})
        assert auto.ok, auto.error
        a = auto.summary
        assert a["mask_handling"]["mask_used"] is False
        assert a["mask_handling"]["sites_in_masked_void"] == [True]
        assert "switched OFF automatically" in a["mask_handling"]["note"]
        assert a["solvent_mask_included"] is False
        assert a["sites"][0]["site"] == "site_frac"
        assert a["sites"][0]["in_masked_void"] is True
        assert a["sites"][0]["electrons_positive"] == pytest.approx(
            a["electrons_positive"], abs=0.06)      # 2 vs 1 decimals
        assert a["sites"][0]["expected_electrons_at_occupancy"]["0.25"] == 8.8
        assert a["expected_electrons_at_occupancy"] == {
            "0.1": 3.5, "0.125": 4.4, "0.25": 8.8, "0.5": 17.5, "1.0": 35.0}
        assert "0.125-occupancy Br is 4.4 e, not 35 e" in a["occupancy_note"]
        assert any("left OUT of Fc" in n for n in a["notes"])
        assert a["electrons_positive"] > 3.0
        # forced on: the mask has eaten (most of) the guest
        on = p.invoke_tool("integrate_difference_density", {
            "site_frac": list(GUEST_SITE), "radius_A": 1.0, "mask": "on"})
        assert on.ok, on.error
        assert on.summary["mask_handling"]["mask_used"] is True
        assert on.summary["solvent_mask_included"] is True
        assert on.summary["electrons_positive"] < a["electrons_positive"]
        assert "INSIDE the masked void" in on.summary["mask_handling"]["warning"]
        assert any("understates" in n for n in on.summary["notes"])
        # a site inside a framework atom's vdW sphere keeps the mask
        keep = p.invoke_tool("integrate_difference_density", {
            "site_frac": list(NEAR_CU), "radius_A": 1.0})
        assert keep.ok, keep.error
        assert keep.summary["mask_handling"]["mask_used"] is True
        assert keep.summary["sites"][0]["in_masked_void"] is False
        assert keep.summary["sites"][0]["nearest_atom"] in ("CU1", "N1")
        assert keep.summary["sites"][0]["nearest_d_A"] == 1.0
        assert "mask kept" in keep.summary["mask_handling"]["note"]
        assert "expected_electrons_at_occupancy" not in keep.summary
        # labels: a modelled atom's own site is never 'in the void' (the
        # mask was built around it), so the omit integral keeps the mask
        lab = p.invoke_tool("integrate_difference_density", {
            "labels": ["CL1"], "radius_A": 1.2})
        assert lab.ok, lab.error
        assert lab.summary["mask_handling"]["mask_used"] is True
        assert lab.summary["sites"][0]["site"] == "CL1"
        assert lab.summary["sites"][0]["in_masked_void"] is False
        assert lab.summary["omitted_from_fc"] is True
        # off on the probe's reference node = the probe's own omit-map read
        # (same model, same function, same radius). Not bit-identical: a
        # checkout rebuilds the model from model.res without the Sasaki
        # f'/f'' that refine had set on the live model (6.22 vs 6.31 e
        # here) - a session-state difference, not a different integral
        r = p.invoke_tool("probe_site", {"element": "Br",
                                         "site": list(GUEST_SITE), "cycles": 4})
        assert r.ok, r.error
        ref_node = r.summary["baseline"]["reference"]["node"]
        assert p.invoke_tool("checkout", {"node": ref_node}).ok
        off = p.invoke_tool("integrate_difference_density", {
            "site_frac": list(GUEST_SITE), "radius_A": 1.0, "mask": "off"})
        assert off.ok, off.error
        assert off.summary["mask_handling"]["session_has_mask"] is False
        assert off.summary["sites"][0]["electrons_positive"] == pytest.approx(
            r.summary["rows"][0]["omit_map_electrons"], rel=0.03)
        assert off.summary["sites"][0]["max"] == pytest.approx(
            r.summary["rows"][0]["residual_before"]["max"], rel=0.03)
        p.session.model.set_inelastic_form_factors(0.71073, "sasaki")
        same = p.invoke_tool("integrate_difference_density", {
            "site_frac": list(GUEST_SITE), "radius_A": 1.0, "mask": "off"})
        assert same.summary["sites"][0]["electrons_positive"] == \
            r.summary["rows"][0]["omit_map_electrons"]
        assert same.summary["sites"][0]["max"] == \
            r.summary["rows"][0]["residual_before"]["max"]
        assert p.invoke_tool("checkout", {"node": baseline}).ok
        assert p.session.flags.get("f_mask") is not None

    def test_integrate_refuses_a_bad_mask_mode_and_element(self,
                                                           project_masked):
        p, _ = project_masked
        r = p.invoke_tool("integrate_difference_density", {
            "site_frac": list(GUEST_SITE), "mask": "sometimes"})
        assert not r.ok and "mask must be" in r.error
        r = p.invoke_tool("integrate_difference_density", {
            "site_frac": list(GUEST_SITE), "element": "Xx"})
        assert not r.ok and "not an element" in r.error


# ==========================================================================
class TestElectronCountCalibration:
    """ka1 cage (2026-09): a model at R1 0.16-0.23 measured ~8-10 e at a
    site the published structure has as Cl (17 e), and the agent read
    '~8 e supports O'. An electron count on an incomplete model is a LOWER
    BOUND; the tools that report one now say so, and propose the elements
    whose Z brackets the count instead of leaving the reading open."""

    def test_probe_site_is_silent_on_a_converged_model(self, project_a):
        p = project_a
        r = p.invoke_tool("probe_site", {"element": "Br",
                                         "site": list(EMPTY_A), "cycles": 3})
        assert r.ok, r.error
        ref = r.summary["baseline"]["reference"]
        assert ref["r1_strong"] < 0.15
        assert "electron_count_calibration" not in r.summary

    def test_probe_site_calibrates_on_an_incomplete_model(self, project_b):
        """Crystal B without its guest refines to R1 ~0.25 - exactly the
        regime where the omit-map count under-reads."""
        p = project_b
        r = p.invoke_tool("probe_site", {"element": "Br",
                                         "site": list(GUEST_SITE),
                                         "cycles": 4})
        assert r.ok, r.error
        assert r.summary["baseline"]["reference"]["r1_strong"] > 0.15
        note = r.summary["electron_count_calibration"]
        assert "disclosed heuristic, not a verdict" in note
        assert "LOWER BOUND" in note
        # the count still brackets candidates, and the proposal spans it
        measured = r.summary["rows"][0]["omit_map_electrons"]
        proposed = r.summary["candidates_bracketing_the_count"]
        assert proposed and "O" in proposed
        assert "cannot tell them apart" in r.summary["bracket_note"]
        assert str(round(measured, 1)) in r.summary["bracket_note"]
        # nothing about the existing reading changed
        assert r.summary["rows"][0]["occupancy_refined"] is not None
        assert r.summary["verdicts"]["Br"] in ("supported", "borderline",
                                               "not_supported")

    def test_integrate_follows_the_session_r1_both_ways(self, project_a):
        import dataclasses
        p = project_a
        assert p.invoke_tool("refine", {"mode": "isotropic",
                                        "n_cycles": 4}).ok
        args = {"site_frac": list(EMPTY_A), "radius_A": 1.0}
        good = p.invoke_tool("integrate_difference_density", args)
        assert good.ok, good.error
        assert "electron_count_calibration" not in good.summary
        assert not any("LOWER BOUND" in n for n in good.summary["notes"])
        # same region, same map: only the model's R1 changes
        hist = p.session.refinement_history
        hist.append(dataclasses.replace(hist[-1], r1_strong=0.23))
        bad = p.invoke_tool("integrate_difference_density", args)
        assert bad.ok, bad.error
        assert bad.summary["electrons_positive"] == \
            good.summary["electrons_positive"]
        note = bad.summary["electron_count_calibration"]
        assert "LOWER BOUND" in note and "0.230" in note
        assert note in bad.summary["notes"]

    def test_integrate_brackets_only_a_single_region(self, project_a):
        p = project_a
        assert p.invoke_tool("refine", {"mode": "isotropic",
                                        "n_cycles": 4}).ok
        one = p.invoke_tool("integrate_difference_density",
                            {"labels": ["ZR1"], "radius_A": 1.0})
        assert one.ok, one.error
        assert one.summary["candidates_bracketing_the_count"]
        # a region spanning several atoms has no single site to bracket
        many = p.invoke_tool("integrate_difference_density",
                             {"labels": ["ZR1", "O1", "O2"], "radius_A": 1.0})
        assert many.ok, many.error
        assert "candidates_bracketing_the_count" not in many.summary


# ==========================================================================
class TestLedgerIsolation:
    """Round-3 WP6: a diagnostic omit neither fights the ghost ledger nor
    disposes of anything on it."""

    def test_probe_on_a_ledger_real_atom_runs_and_leaves_the_verdict(self, project_a):
        from crystalpilot.refine import ghost_ledger
        p = project_a
        xs = p.session.model
        c1 = next(sc for sc in xs.scatterers() if sc.label == "C1")
        ghost_ledger.record(p.dir, {"labels": ["C1"], "site_frac": [list(c1.site)],
                                    "verdict": "real", "delta_r1": 0.02})
        baseline = _state(p)["active_node"]
        r = p.invoke_tool("probe_site", {"element": "C", "near_atom": "c1",
                                         "cycles": 3})
        assert r.ok, r.error
        assert s_omit(r) == "C1"
        assert _state(p)["active_node"] == baseline
        entries = ghost_ledger.load(p.dir)
        assert entries[0]["verdict"] == "real" and entries[0]["disposed"] == {}
        touches = entries[0]["diagnostic_touches"]
        assert touches and touches[0]["labels"] == ["C1"]
        assert "probe_site" in touches[0]["reason"]
        # the main line is still protected: a plain delete needs acknowledge_real
        d = p.invoke_tool("edit_atoms", {"operations": [{"action": "delete",
                                                         "atoms": ["C1"]}]})
        assert not d.ok and "real" in (d.error or "").lower()
        assert _state(p)["active_node"] == baseline
        assert ghost_ledger.load(p.dir)[0]["disposed"] == {}


def s_omit(r):
    return r.summary["position"]["omit"]["label"]
