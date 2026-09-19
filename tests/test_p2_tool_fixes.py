"""pa1 P2 tool fixes: messages and edge cases that sent agents down the
wrong road (PA1-FINAL-ANALYSIS §10 item 13).

- change_space_group refused a descent without saying which subgroups
  exist (cage-l2-r1 wanted I2/a -> P2(1)/c, ended the run in P-1)
- ncs_audit "failed" on every framework (one identity-bond fragment)
- assemble_asu returned ok:false when there was nothing to do
- inspect_map raised a bare AssertionError on an atomless model
- check_symmetry had no timeout (476 s once, holding the project lock)
- solvent_mask resolution_factor 0.4/0.5 died inside the FFT
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from crystalpilot.refine.tools_symmetry import (ChangeSpaceGroup,
                                                CheckSymmetry, NcsAudit,
                                                _subgroup_menu)


def _ctx(xs, **extra):
    kw = {"model": xs, "flags": {}, "dataset": None, "fo_sq": None}
    kw.update(extra)
    return SimpleNamespace(session=SimpleNamespace(**kw))


def _p21c_model():
    from cctbx import crystal, xray
    cs = crystal.symmetry(unit_cell=(7.9, 9.4, 11.8, 90, 102.5, 90),
                          space_group_symbol="P 21/c")
    xs = xray.structure(crystal_symmetry=cs)
    for lbl, el, site in (("CU1", "Cu", (0.113, 0.181, 0.317)),
                          ("O1", "O", (0.352, 0.089, 0.411)),
                          ("C1", "C", (0.238, 0.457, 0.083))):
        xs.add_scatterer(xray.scatterer(
            label=lbl, site=site, u=0.025, scattering_type=el))
    xs.scattering_type_registry(table="it1992")
    return xs


def _toy_p1bar():
    from cctbx import crystal, xray
    cs = crystal.symmetry(unit_cell=(9.1, 10.3, 11.7, 92, 101, 96),
                          space_group_symbol="P -1")
    xs = xray.structure(crystal_symmetry=cs)
    for lbl, el, site in (("CU1", "Cu", (0.123, 0.234, 0.345)),
                          ("O1", "O", (0.311, 0.152, 0.421)),
                          ("N1", "N", (0.489, 0.377, 0.266)),
                          ("C1", "C", (0.271, 0.443, 0.188))):
        xs.add_scatterer(xray.scatterer(label=lbl, site=site, u=0.03,
                                        scattering_type=el))
    return xs


class TestSubgroupMenu:
    def test_menu_lists_proper_subgroups_in_the_current_setting(self):
        from cctbx import sgtbx
        g = sgtbx.space_group_info("P 21/c").group()
        menu = _subgroup_menu(g)
        numbers = {m["number"] for m in menu}
        assert {4, 7, 2, 1} <= numbers            # P21, Pc, P-1, P1
        assert all(m["index"] >= 2 for m in menu)
        assert menu[0]["index"] == 2               # maximal ones first
        assert all("space_group" in m and m["space_group"] for m in menu)

    def test_refused_descent_names_the_available_subgroups(self):
        r = ChangeSpaceGroup(None).run(_ctx(_p21c_model()),
                                       space_group="P 1 2 1")
        assert not r.ok
        assert "not a subgroup type" in r.error
        assert "available in the current setting" in r.error
        assert "21" in r.error                     # P 1 21 1 is on the menu

    def test_origin_shift_is_gone_from_the_schema(self):
        assert "origin_shift" not in ChangeSpaceGroup.params_schema[
            "properties"]


class TestNcsAuditNotApplicable:
    def test_single_fragment_is_a_verdict_not_an_error(self):
        from cctbx import crystal, xray
        cs = crystal.symmetry(unit_cell=(10, 10, 10, 90, 90, 90),
                              space_group_symbol="P 1")
        xs = xray.structure(crystal_symmetry=cs)
        for lbl, el, site in (("C1", "C", (0.10, 0.10, 0.10)),
                              ("N1", "N", (0.24, 0.10, 0.10)),
                              ("O1", "O", (0.10, 0.24, 0.10))):
            xs.add_scatterer(xray.scatterer(label=lbl, site=site, u=0.03,
                                            scattering_type=el))
        r = NcsAudit(None).run(_ctx(xs))
        assert r.ok, r.error
        assert r.summary["applicable"] is False
        assert r.summary["no_state_change"] is True
        assert "fragment_a" in r.summary["note"]


class TestAssembleAsuNoop:
    def test_plan_that_changes_nothing_is_ok(self, monkeypatch):
        from crystalpilot.chem import asu_sanity
        from crystalpilot.refine.tools_analysis import AssembleAsu
        xs = _toy_p1bar()
        monkeypatch.setattr(asu_sanity, "asu_assembly_plan",
                            lambda m: [{"atom": "O1", "op": "x,y,z+1"}])
        monkeypatch.setattr(asu_sanity, "apply_assembly_plan",
                            lambda m, plan: (m, False))
        ctx = _ctx(xs)
        r = AssembleAsu(None).run(ctx)
        assert r.ok, r.error
        assert r.summary["no_state_change"] is True
        assert "did not reduce detached atoms" in r.summary["note"]
        assert ctx.session.model is xs


class TestInspectMapPrecheck:
    def test_atomless_model_fails_with_a_reason(self):
        from cctbx import crystal, xray
        from crystalpilot.refine.tools_extra import InspectMap
        xs = xray.structure(crystal_symmetry=crystal.symmetry(
            unit_cell=(10, 10, 10, 90, 90, 90), space_group_symbol="P 1"))
        r = InspectMap(None).run(_ctx(xs))
        assert not r.ok
        assert "no atoms" in r.error and "run_shelxt" in r.error


class TestCheckSymmetryTimeout:
    def test_expired_budget_returns_a_partial_result(self):
        xs = _toy_p1bar().expand_to_p1()
        r = CheckSymmetry(None).run(_ctx(xs), timeout_s=1e-6)
        assert r.ok, r.error
        s = r.summary
        assert s["timed_out"]["stage"] == "direct"
        assert s["timed_out"]["ops_examined"] == 0
        assert s["extra_ops_matched"] == []
        assert s["verdict"].startswith("TIMED OUT")
        assert "timeout_s=" in s["verdict"]

    def test_default_budget_finds_the_inversion(self):
        xs = _toy_p1bar().expand_to_p1()
        r = CheckSymmetry(None).run(_ctx(xs))
        assert r.ok and "timed_out" not in r.summary
        assert r.summary["extra_ops_matched"]


class TestSolventMaskResolutionFactor:
    @pytest.mark.parametrize("rf", [0.4, 0.5, 0.05])
    def test_coarse_or_absurd_grid_is_refused_up_front(self, rf):
        from cctbx import miller
        from cctbx.array_family import flex
        from crystalpilot.tools.mask_tools import SolventMask
        xs = _toy_p1bar()
        ms = miller.build_set(xs.crystal_symmetry(), anomalous_flag=False,
                              d_min=1.5)
        fo_sq = ms.array(data=flex.double(ms.size(), 1.0),
                         sigmas=flex.double(ms.size(), 0.1))
        r = SolventMask().run(_ctx(xs, fo_sq=fo_sq), resolution_factor=rf)
        assert not r.ok
        assert "0.10-0.34" in r.error and "raise d_min" in r.error


def _hkl_session(cell, sg="P 1", d_min=1.2, model=None):
    from cctbx import crystal, miller
    from cctbx.array_family import flex
    cs = crystal.symmetry(unit_cell=cell, space_group_symbol=sg)
    ms = miller.build_set(cs, anomalous_flag=False, d_min=d_min)
    n = ms.indices().size()
    # intensities that fall off with resolution so shells/E-stats are not
    # degenerate: I = 1000 * exp(-8 s^2) + a parity-independent ripple
    dss = ms.d_star_sq().data()
    data = flex.double([1000.0 * (2.718281828 ** (-8.0 * x / 4.0)) + 5.0 * (i % 7)
                        for i, x in enumerate(dss)])
    arr = miller.array(ms, data=data, sigmas=flex.double(n, 10.0))
    arr = arr.set_observation_type_xray_intensity()
    return SimpleNamespace(dataset=SimpleNamespace(intensities=arr),
                           symmetry=cs, flags={}, model=model, fo_sq=None)


class TestScreenAllLaueClasses:
    def test_all_scans_every_metric_subgroup_once(self):
        from crystalpilot.refine.tools_analysis import ScreenSpaceGroups
        ses = _hkl_session((6, 7, 8, 90, 95, 90))
        r = ScreenSpaceGroups(None).run(SimpleNamespace(session=ses),
                                        laue_group="all", merge_stats=True)
        assert r.ok, r.error
        s = r.summary
        assert "scan" in s["laue_source"]
        groups = [row["laue_group"].replace(" ", "") for row in s["laue_scan"]]
        assert any("2/m" in g for g in groups) and "P-1" in groups
        assert s["laue_suggested_by_r_int"]
        assert s["n_laue_classes_screened"] >= 2
        assert s["candidates"] and all("laue_class" in c and "laue_r_int" in c
                                       for c in s["candidates"])
        # merge stats ride along per class
        screened = [row for row in s["laue_scan"] if "laue_class" in row]
        assert all("merge" in row and "r_int" in row["merge"]
                   for row in screened)

    def test_merge_stats_on_a_single_class(self):
        from crystalpilot.refine.tools_analysis import ScreenSpaceGroups
        ses = _hkl_session((6, 7, 8, 90, 90, 90))
        r = ScreenSpaceGroups(None).run(SimpleNamespace(session=ses),
                                        laue_group="mmm", merge_stats=True)
        assert r.ok, r.error
        m = r.summary["merge"]
        assert m["n_unique"] > 0 and 0.0 <= m["r_int"] < 0.05   # ripple only
        assert m["centring_assumed"] == "P"
        assert 0.9 <= m["completeness"] <= 1.0


class TestReflectionStatistics:
    def test_one_call_covers_the_hand_written_scripts(self):
        from crystalpilot.refine.tools_analysis import ReflectionStatistics
        ses = _hkl_session((6, 7, 8, 90, 95, 90))
        r = ReflectionStatistics(None).run(SimpleNamespace(session=ses))
        assert r.ok, r.error
        s = r.summary
        assert "2/m" in s["laue_class"] and "metric" in s["laue_source"]
        assert s["shells"] and s["merge"]["n_unique"] > 0
        e = s["e_statistics"]
        assert "mean_abs_e2_minus_1" in e and "n_z" in e
        assert set(e["n_z"]["0.4"]) == {"observed", "centric", "acentric"}
        parity = {row["class"]: row for row in s["parity_classes"]}
        assert 0.7 < parity["h odd"]["mean_i_ratio"] < 1.3
        assert s["centring_implied_by_file"] == "P"
        assert s["friedel"] is None                       # Friedel-merged set
        assert "skipped" in s["wilson"]
        assert "laue_scan" not in s

    def test_all_adds_the_laue_scan_and_model_gives_wilson(self):
        from crystalpilot.refine.tools_analysis import ReflectionStatistics
        ses = _hkl_session((6, 7, 8, 90, 90, 90), model=_toy_p1bar())
        r = ReflectionStatistics(None).run(SimpleNamespace(session=ses),
                                           laue_group="all", n_shells=6)
        assert r.ok, r.error
        s = r.summary
        assert s["laue_scan"] and s["laue_suggested_by_r_int"]
        assert len(s["shells"]) <= 6
        assert "B_wilson" in s["wilson"]

    def test_centred_file_is_recognised(self):
        from cctbx import crystal, miller
        from cctbx.array_family import flex
        from crystalpilot.refine.tools_analysis import (
            ReflectionStatistics, _centring_from_indices)
        cs = crystal.symmetry(unit_cell=(6, 7, 8, 90, 90, 90),
                              space_group_symbol="C 2 2 2")
        ms = miller.build_set(cs, anomalous_flag=False, d_min=1.2)
        assert _centring_from_indices(ms.indices())[0] == "C"
        n = ms.indices().size()
        arr = miller.array(ms, data=flex.double(n, 100.0),
                           sigmas=flex.double(n, 5.0))
        ses = SimpleNamespace(dataset=SimpleNamespace(
            intensities=arr.set_observation_type_xray_intensity()),
            symmetry=cs, flags={}, model=None)
        r = ReflectionStatistics(None).run(SimpleNamespace(session=ses))
        assert r.ok, r.error
        assert r.summary["centring_implied_by_file"] == "C"
        parity = {row["class"]: row for row in r.summary["parity_classes"]}
        assert parity["h+k odd"]["n"] == 0
        assert r.summary["merge"]["centring_assumed"] == "C"

    def test_bad_laue_symbol_fails_loud(self):
        from crystalpilot.refine.tools_analysis import ReflectionStatistics
        ses = _hkl_session((6, 7, 8, 90, 90, 90))
        r = ReflectionStatistics(None).run(SimpleNamespace(session=ses),
                                           laue_group="bogus")
        assert not r.ok and "all" in r.error
