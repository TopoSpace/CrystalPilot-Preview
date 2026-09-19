"""Tests for the structure-analysis tools (geometry / symmetry audit /
rename / import_cif_model)."""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from crystalpilot.refine.tools_analysis import (CheckSymmetry,
                                                _canonical_mapping,
                                                _direct_match_fraction)


def _toy_p1bar():
    """Small acentric-motif structure in P-1 (general positions only)."""
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


def _ctx(xs):
    return SimpleNamespace(session=SimpleNamespace(
        model=xs, flags={}, dataset=None))


class TestCheckSymmetry:
    def test_p1_expansion_finds_inversion(self):
        xs = _toy_p1bar().expand_to_p1()
        r = CheckSymmetry(None).run(_ctx(xs))
        assert r.ok
        s = r.summary
        assert s["current_space_group"].replace(" ", "") == "P1"
        assert s["metric_pseudo_symmetry"] is True
        assert s["extra_ops_matched"], "inversion must be detected"
        assert s["suggested_space_group"].replace(" ", "") == "P-1"

    def test_correct_group_is_quiet(self):
        xs = _toy_p1bar()
        r = CheckSymmetry(None).run(_ctx(xs))
        assert r.ok
        assert not r.summary["extra_ops_matched"]
        assert "complete" in r.summary["verdict"]

    def test_direct_match_rejects_random_op(self):
        from cctbx import sgtbx
        xs = _toy_p1bar().expand_to_p1()
        m = _direct_match_fraction(xs, sgtbx.rt_mx("x+1/3,y,z"))
        assert m["fraction"] < 0.9


class TestCanonicalMapping:
    def test_h_follows_carrier(self):
        from cctbx import crystal, xray
        cs = crystal.symmetry(unit_cell=(10, 10, 10, 90, 90, 90),
                              space_group_symbol="P 1")
        xs = xray.structure(crystal_symmetry=cs)
        for lbl, el in (("FE01", "Zr"), ("Q3", "C"), ("HX", "H"),
                        ("HY", "H"), ("OW", "O")):
            xs.add_scatterer(xray.scatterer(
                label=lbl, site=(0.1, 0.2, 0.3), u=0.02, scattering_type=el))
        mapping = _canonical_mapping(
            list(xs.scatterers()), {"Q3": ["HX", "HY"]})
        assert mapping["FE01"] == "Zr1"
        assert mapping["Q3"] == "C1"
        assert mapping["HX"] == "H1A" and mapping["HY"] == "H1B"
        assert mapping["OW"] == "O1"
        assert all(len(v) <= 4 for v in mapping.values())


@pytest.fixture(scope="module")
def imported_project(tmp_path_factory):
    import json
    d = tmp_path_factory.mktemp("import-proj")
    (d / "context.json").write_text(json.dumps({
        "chemistry": {"note": "imported-structure validation run"}}),
        encoding="utf-8")
    from crystalpilot.refine.project import RefineProject
    p = RefineProject(d)
    p.open()
    src = REPO / "benchmark" / "public" / "Ca_imidazolate"
    r = p.invoke_tool("import_cif_model", {
        "cif_path": str(src / "ref_cif.cif"),
        "hkl_path": str(src / "sf.cif")})
    assert r.ok, r.error
    return p, r.summary


class TestImportCifModel:
    def test_import_commits_start_node(self, imported_project):
        p, s = imported_project
        assert s["start_node"] == "n0000"
        assert s["imported_atoms"] > 5
        assert any("HKLF4" in n for n in s["conversion_notes"])

    def test_geometry_works_on_import(self, imported_project):
        p, _ = imported_project
        r = p.invoke_tool("get_geometry", {"scope": "bonds"})
        assert r.ok
        assert r.summary["n_bonds"] > 0
        # no SHELXL job yet in this fresh project -> honest esd note
        assert r.summary["esd_source"] is None
        assert "no SHELXL job" in r.summary["note"]

    def test_refine_runs_on_imported_model(self, imported_project):
        p, _ = imported_project
        r = p.invoke_tool("refine", {"mode": "isotropic", "n_cycles": 2})
        assert r.ok, r.error
        assert r.summary["r1_strong"] < 0.35


class TestIntegrateDifferenceDensity:
    """Electron-count test of the guest-evidence rule (test 1 of
    mof-guest-evidence-rule): omit-map integration around given atoms."""

    def test_omit_integral_matches_modeled_content(self, imported_project):
        p, _ = imported_project
        ses = p.session
        lbl = next(sc.label for sc in ses.model.scatterers()
                   if sc.scattering_type.strip().upper().startswith("CA"))
        r = p.invoke_tool("integrate_difference_density",
                          {"labels": [lbl], "candidate_formula": "H2O"})
        assert r.ok, r.error
        s = r.summary
        # omitting Ca (Z=20) must integrate back on the same order as the
        # model's claim (live check: 21.6 vs 20.0)
        assert s["modeled_electrons_omitted"] == pytest.approx(20.0)
        assert 0.5 * 20 < s["electrons_positive"] < 2.0 * 20
        assert s["expected_electrons"] == pytest.approx(10.0)
        assert s["omitted_from_fc"] is True
        assert any("BOTH halves" in n for n in s["notes"])

    def test_empty_site_integrates_near_zero(self, imported_project):
        p, _ = imported_project
        r = p.invoke_tool("integrate_difference_density",
                          {"site_frac": [0.5, 0.5, 0.5], "radius_A": 1.2})
        assert r.ok, r.error
        # arbitrary hole in the structure: far less density than an atom
        assert abs(r.summary["electrons_net"]) < 5.0
        assert r.summary["omitted_from_fc"] is False

    def test_unknown_label_fails_loud(self, imported_project):
        p, _ = imported_project
        r = p.invoke_tool("integrate_difference_density",
                          {"labels": ["NOPE9"]})
        assert not r.ok
        assert "NOPE9" in r.error


def test_write_hklf4_scales_wide_values(tmp_path):
    from cctbx import crystal, miller
    from cctbx.array_family import flex
    from crystalpilot.io.cif_sf import write_hklf4
    cs = crystal.symmetry(unit_cell=(10, 10, 10, 90, 90, 90),
                          space_group_symbol="P 1")
    ms = miller.set(crystal_symmetry=cs,
                    indices=flex.miller_index([(1, 0, 0), (2, 1, 3)]),
                    anomalous_flag=True)
    arr = miller.array(ms, data=flex.double([1234567.0, 12.5]),
                       sigmas=flex.double([1000.0, 1.0]))
    info = write_hklf4(arr, tmp_path / "t.hkl")
    assert info["scale_applied"] < 1.0
    lines = (tmp_path / "t.hkl").read_text().splitlines()
    assert len(lines) == 3 and lines[-1].split() == ["0", "0", "0",
                                                     "0.00", "0.00"]
    assert all(len(ln) == 28 for ln in lines)


class TestAuditReflectionData:
    @staticmethod
    def _session(flags=None, cell=(6, 7, 8, 90, 95, 90)):
        from cctbx import crystal, miller
        from cctbx.array_family import flex
        cs = crystal.symmetry(unit_cell=cell,
                              space_group_symbol="P 21/c")
        idx = flex.miller_index([(1, 2, 3), (1, 2, 3), (2, 0, 0),
                                 (0, 3, 0), (-1, -2, -3)])
        data = flex.double([100.0, 500.0, 50.0, 90.0, 102.0])
        sigs = flex.double([5.0, 5.0, 2.0, 3.0, 5.0])
        ms = miller.set(crystal_symmetry=cs, indices=idx,
                        anomalous_flag=False)
        arr = miller.array(ms, data=data, sigmas=sigs)
        arr = arr.set_observation_type_xray_intensity()
        ses = SimpleNamespace(dataset=SimpleNamespace(intensities=arr),
                              symmetry=cs, flags=flags or {})
        return ses

    def test_repeated_composites_read_as_an_hklf5_export(self):
        """nm: 3239 hkl repeated up to 8x, half of them inconsistent beyond
        sigma - the deposited model reaches 0.094 on them, not 0.0526."""
        from types import SimpleNamespace as NS

        from cctbx import crystal, miller
        from cctbx.array_family import flex
        from crystalpilot.refine.tools_analysis import AuditReflectionData
        cs = crystal.symmetry(unit_cell=(6, 7, 8, 90, 95, 90),
                              space_group_symbol="P 21/c")
        idx = flex.miller_index([(1, 2, 3)] * 4 + [(2, 1, 1)] * 3 + [(3, 0, 1)])
        data = flex.double([100.0, 250.0, 180.0, 90.0, 40.0, 75.0, 60.0, 20.0])
        sigs = flex.double([2.0] * 8)
        arr = miller.array(miller.set(crystal_symmetry=cs, indices=idx,
                                      anomalous_flag=False),
                           data=data, sigmas=sigs).set_observation_type_xray_intensity()
        ses = NS(dataset=NS(intensities=arr), symmetry=cs, flags={})
        r = AuditReflectionData(None).run(NS(session=ses))
        assert r.ok, r.error
        d = r.summary["duplicates"]
        assert d["max_multiplicity"] == 4
        assert "HKLF 5" in d["reading"] and "R1 FLOOR" in d["reading"]
        assert any("HKLF 5" in h for h in r.summary["hints"])

    def test_flags_inconsistent_duplicates_and_absences(self):
        from crystalpilot.refine.tools_analysis import AuditReflectionData
        ses = self._session()
        r = AuditReflectionData(None).run(SimpleNamespace(session=ses))
        assert r.ok, r.error
        s = r.summary
        assert s["duplicates"]["n_duplicate_groups"] == 1
        assert s["duplicates"]["n_groups_chi2_above_threshold"] == 1
        assert s["duplicates"]["worst_group"]["hkl"] == [1, 2, 3]
        # (0,3,0) violates the 2_1 screw absence at I/sig=30
        assert s["absences"]["n_violations_gt_3sig"] == 1
        assert s["absences"]["top_violators"][0]["hkl"] == [0, 3, 0]
        assert "r_int_current_laue" in s["laue_consistency"]
        assert any("inconsistent" in h for h in s["hints"])
        # (f) quiet path: beta=95 keeps the metric strictly monoclinic
        assert (s["metric_vs_laue"]["n_lattice_ops_primitive"]
                == s["metric_vs_laue"]["n_laue_ops_primitive"])

    def test_metric_vs_laue_twin_alarm(self):
        from crystalpilot.refine.tools_analysis import AuditReflectionData
        # beta = 90: monoclinic Laue class inside a metrically
        # orthorhombic lattice - the pseudo-merohedral precondition
        ses = self._session(cell=(6, 7, 8, 90, 90, 90))
        r = AuditReflectionData(None).run(SimpleNamespace(session=ses))
        assert r.ok, r.error
        s = r.summary
        mv = s["metric_vs_laue"]
        assert mv["n_lattice_ops_primitive"] > mv["n_laue_ops_primitive"]
        assert "metric_exceeds_laue" in s["twin_alarm"]["signs"]
        assert any("framework-twin-pseudosymmetry-alarm" in h
                   for h in s["hints"])

    def test_flat_e_statistics_twin_alarm(self):
        from cctbx import crystal, miller
        from cctbx.array_family import flex
        from crystalpilot.refine.tools_analysis import AuditReflectionData
        cs = crystal.symmetry(unit_cell=(6, 7, 8, 90, 95, 90),
                              space_group_symbol="P 21/c")
        ms = miller.build_set(cs, anomalous_flag=False, d_min=0.9)
        n = ms.indices().size()
        # constant intensities -> E^2 = 1 in every shell -> |E^2-1| ~ 0,
        # far below the 0.68 twin-warning line
        arr = miller.array(ms, data=flex.double(n, 100.0),
                           sigmas=flex.double(n, 1.0))
        arr = arr.set_observation_type_xray_intensity()
        ses = SimpleNamespace(dataset=SimpleNamespace(intensities=arr),
                              symmetry=cs, flags={})
        r = AuditReflectionData(None).run(SimpleNamespace(session=ses))
        assert r.ok, r.error
        s = r.summary
        assert s["e_statistics"]["mean_abs_e2_minus_1"] < 0.2
        assert "flat_e_statistics" in s["twin_alarm"]["signs"]
        assert any("0.68" in h for h in s["hints"])

    def test_hklf5_disclosure_hint(self):
        from crystalpilot.refine.tools_analysis import AuditReflectionData
        ses = self._session(flags={"hklf": 5})
        r = AuditReflectionData(None).run(SimpleNamespace(session=ses))
        assert r.ok
        assert any("HKLF5" in h for h in r.summary["hints"])

    def test_fcf_audit_detects_twin_observation_model(self, tmp_path):
        from crystalpilot.refine.tools_analysis import _audit_fcf
        fcf = tmp_path / "t.fcf"
        fcf.write_text(
            "   1   2   3   100.00   105.00     5.00 o\n"
            "  -1  -2  -3   400.00   380.00     9.00 o\n"
            "   2   0   0    50.00    52.00     2.00 o\n",
            encoding="utf-8")
        fa = _audit_fcf(fcf)
        assert fa["n_rows"] == 3
        assert fa["n_friedel_groups"] == 2
        assert fa["groups_with_nonconstant_fc2"] == 1
        assert fa["max_fc2_span"] == 300.0
        assert "TWIN" in fa["interpretation"]
        assert 0 < fa["r1_from_file_all"] < 1

    def test_fcf_audit_quiet_on_single_valued(self, tmp_path):
        from crystalpilot.refine.tools_analysis import _audit_fcf
        fcf = tmp_path / "t.fcf"
        fcf.write_text(
            "   1   2   3   100.00   105.00     5.00 o\n"
            "   2   0   0    50.00    52.00     2.00 o\n",
            encoding="utf-8")
        fa = _audit_fcf(fcf)
        assert fa["groups_with_nonconstant_fc2"] == 0
        assert "single-valued" in fa["interpretation"]

    def test_fcf_misfit_outliers_cluster_hint(self, tmp_path):
        from crystalpilot.refine.tools_analysis import _audit_fcf
        rows = []
        # 12 gross Fo2>>Fc2 outliers all in the h+l-odd class
        for i in range(12):
            h, k, l = 1, i, 2 * (i // 2)   # h+l odd (1+even)
            rows.append(f"{h:4d}{k:4d}{l:4d}{5.0:9.2f}{500.0:9.2f}{4.0:9.2f} o")
        # quiet background rows
        for i in range(20):
            rows.append(f"{2:4d}{i:4d}{2:4d}{100.0:9.2f}{101.0:9.2f}{5.0:9.2f} o")
        (tmp_path / "m.fcf").write_text("\n".join(rows) + "\n",
                                        encoding="utf-8")
        fa = _audit_fcf(tmp_path / "m.fcf")
        mo = fa["misfit_outliers"]
        assert mo["n"] == 12
        assert mo["zones"].get("h+l odd") == 12
        assert "NOT reliable space-group evidence" in mo["cluster_hint"]

    def test_fcf_sign_bias_flags_inflated_weak_medium(self, tmp_path):
        from crystalpilot.refine.tools_analysis import _audit_fcf
        rows = []
        # 40 medium reflections (I/sig 2-10), 80% with Fo2 slightly > Fc2:
        # the unmodelled-twin fingerprint from the CCDC 2416519 referee case
        for i in range(40):
            h, k, l = 3, i, 1
            fc2, sig = 20.0, 4.0
            fo2 = 24.0 if i < 32 else 16.0
            rows.append(f"{h:4d}{k:4d}{l:4d}{fc2:9.2f}{fo2:9.2f}{sig:9.2f} o")
        # healthy strong band, balanced signs
        for i in range(40):
            fo2 = 101.0 if i % 2 else 99.0
            rows.append(f"{5:4d}{i:4d}{3:4d}{100.0:9.2f}{fo2:9.2f}{2.0:9.2f} o")
        (tmp_path / "b.fcf").write_text("\n".join(rows) + "\n",
                                        encoding="utf-8")
        fa = _audit_fcf(tmp_path / "b.fcf")
        sb = fa["fo2_fc2_sign_bias"]
        assert sb["medium_2_10sig"]["frac_fo2_gt_fc2"] == 0.8
        assert "unmodelled" in fa["sign_bias_hint"]

    def test_fcf_sign_bias_quiet_on_balanced(self, tmp_path):
        from crystalpilot.refine.tools_analysis import _audit_fcf
        rows = []
        for i in range(60):
            fo2 = 22.0 if i % 2 else 18.0     # 50/50 around Fc2=20
            rows.append(f"{3:4d}{i:4d}{1:4d}{20.0:9.2f}{fo2:9.2f}{4.0:9.2f} o")
        (tmp_path / "q.fcf").write_text("\n".join(rows) + "\n",
                                        encoding="utf-8")
        fa = _audit_fcf(tmp_path / "q.fcf")
        assert fa["fo2_fc2_sign_bias"]["medium_2_10sig"][
            "frac_fo2_gt_fc2"] == 0.5
        assert "sign_bias_hint" not in fa


class TestFittedTranslationAddsym:
    """A P2_1/c structure declared in P2_1 (glide half filled in
    explicitly) with a shifted origin: only translation-fitting can
    recover the glide + inversion."""

    @staticmethod
    def _p21_sub_of_p21c(shift=(0.13, 0.0, 0.21)):
        from cctbx import crystal, sgtbx, xray
        cs_hi = crystal.symmetry(unit_cell=(7.9, 9.4, 11.8, 90, 102.5, 90),
                                 space_group_symbol="P 21/c")
        base = [("CU1", "Cu", (0.113, 0.181, 0.317)),
                ("O1", "O", (0.352, 0.089, 0.411)),
                ("N1", "N", (0.471, 0.322, 0.174)),
                ("C1", "C", (0.238, 0.457, 0.083)),
                ("C2", "C", (0.611, 0.203, 0.279))]
        cs_lo = crystal.symmetry(unit_cell=(7.9, 9.4, 11.8, 90, 102.5, 90),
                                 space_group_symbol="P 1 21 1")
        xs = xray.structure(crystal_symmetry=cs_lo)
        glide = sgtbx.rt_mx("x,-y+1/2,z+1/2")     # the op P21 is missing
        for lbl, el, site in base:
            for suf, op in (("A", None), ("B", glide)):
                s = site if op is None else tuple(op * site)
                s = tuple((s[k] + shift[k]) % 1.0 for k in range(3))
                xs.add_scatterer(xray.scatterer(
                    label=lbl + suf, site=s, u=0.025, scattering_type=el))
        return xs

    def test_recovers_glide_after_origin_shift(self):
        from crystalpilot.refine.tools_analysis import CheckSymmetry
        # shift components along each op's invariant directions cancel in
        # the fit, so this closes at the STANDARD origin - no annotation
        xs = self._p21_sub_of_p21c()
        r = CheckSymmetry(None).run(_ctx(xs))
        assert r.ok, r.error
        s = r.summary
        assert s["extra_ops_matched"], s
        assert "21/c" in (s["suggested_space_group"] or ""), s

    def test_offgrid_glide_closes_with_origin_annotation(self):
        from crystalpilot.refine.tools_analysis import CheckSymmetry
        # s_y=0.045 puts the fitted c-glide translation at y=0.59: off the
        # standard origin but snappable to 7/12, so the group must close
        # with a non-standard-origin annotation on the current-basis
        # symbol - and NO shifting of the content (P21's polar direction
        # is b, but 7/12 is reachable on the grid without it)
        xs = self._p21_sub_of_p21c(shift=(0.13, 0.045, 0.21))
        r = CheckSymmetry(None).run(_ctx(xs))
        assert r.ok, r.error
        s = r.summary
        assert s["extra_ops_matched"], s
        assert "21/c" in (s["suggested_space_group"] or ""), s
        cur = s.get("suggested_space_group_current_basis") or ""
        assert "(" in cur, s


class TestChangeSpaceGroup:
    @staticmethod
    def _ses(xs):
        return SimpleNamespace(
            session=SimpleNamespace(model=xs, symmetry=None, flags={}))

    def test_adopt_suggestion_merges_to_supergroup(self):
        from crystalpilot.refine.tools_analysis import ChangeSpaceGroup
        xs = TestFittedTranslationAddsym._p21_sub_of_p21c()
        ctx = self._ses(xs)
        r = ChangeSpaceGroup(None).run(ctx, adopt_suggestion=True)
        assert r.ok, r.error
        s = r.summary
        assert "21/c" in s["new_space_group"]
        assert s["n_atoms_before"] == 10
        assert s["n_atoms_after"] == 5
        assert ctx.session.model.scatterers().size() == 5
        assert "P 1 21/c 1" in str(ctx.session.model.space_group_info()) \
            or "21/c" in str(ctx.session.model.space_group_info())

    def test_refuses_unobeyed_symmetry(self):
        from cctbx import crystal, xray
        from crystalpilot.refine.tools_analysis import ChangeSpaceGroup
        # 4 independent atoms declared in P1 with NO inversion mates at all
        cs = crystal.symmetry(unit_cell=(9.1, 10.3, 11.7, 92, 101, 96),
                              space_group_symbol="P 1")
        xs = xray.structure(crystal_symmetry=cs)
        for sc in _toy_p1bar().scatterers():
            xs.add_scatterer(sc)
        r = ChangeSpaceGroup(None).run(self._ses(xs), space_group="P -1")
        assert not r.ok
        assert "does not obey" in r.error

    def test_self_fits_origin_without_hint(self):
        from crystalpilot.refine.tools_analysis import ChangeSpaceGroup
        # genuine P-1 content declared in P1 with an arbitrary origin:
        # the tool must fit the origin itself and succeed
        xs = _toy_p1bar().expand_to_p1().apply_shift((0.11, 0.07, 0.19))
        ctx = self._ses(xs)
        r = ChangeSpaceGroup(None).run(ctx, space_group="P -1")
        assert r.ok, r.error
        assert r.summary["n_atoms_after"] == 4

    def test_subgroup_descent_grows_asu(self):
        from crystalpilot.refine.tools_analysis import ChangeSpaceGroup
        xs = _toy_p1bar()                  # P-1, 4 atoms
        ctx = self._ses(xs)
        r = ChangeSpaceGroup(None).run(ctx, space_group="P 1")
        assert r.ok, r.error
        s = r.summary
        assert s["n_atoms_before"] == 4
        assert s["n_atoms_after"] == 8
        labels = [sc.label for sc in ctx.session.model.scatterers()]
        assert len(labels) == len(set(labels)), labels


class TestSubgroupDescentJitter:
    """Descending to a subgroup must (a) resolve the subgroup in the
    parent setting - standard-setting ops of the target usually do not
    coincide with the actual subgroup - and (b) break the least-squares
    saddle point with a small deterministic kick on general positions."""

    @staticmethod
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

    def test_descent_resolves_subgroup_applies_jitter(self):
        from crystalpilot.refine.tools_analysis import ChangeSpaceGroup
        xs = self._p21c_model()
        r = ChangeSpaceGroup(None).run(_ctx(xs), space_group="P 1 21 1")
        assert r.ok, r.error
        s = r.summary
        assert "21" in s["new_space_group"]
        assert "symmetry_break_jitter" in s, s
        # ASU doubles: P21/c (order 4) -> P21 (order 2)
        assert s["n_atoms_before"] == 3 and s["n_atoms_after"] == 6

    def test_descent_jitter_disabled_explicitly(self):
        from crystalpilot.refine.tools_analysis import ChangeSpaceGroup
        xs = self._p21c_model()
        r = ChangeSpaceGroup(None).run(_ctx(xs),
                                       space_group="P 1 21 1", jitter_A=0)
        assert r.ok, r.error
        assert "symmetry_break_jitter" not in r.summary

    def test_descent_rejects_non_subgroup(self):
        from crystalpilot.refine.tools_analysis import ChangeSpaceGroup
        xs = self._p21c_model()
        r = ChangeSpaceGroup(None).run(_ctx(xs), space_group="P 1 2 1")
        # P2 (No. 3) is not a subgroup type of P21/c (its index-2
        # subgroups are P21, Pc, P-1)
        assert not r.ok
        assert "not a subgroup type" in r.error


class TestRenamePropagatesDisorder:
    def test_map_rename_updates_disorder_members(self):
        # round-10 defect #10: canonical relabel left stale labels in
        # disorder_groups.members -> split atoms detached from their FVAR
        # and 8 ordered C inherited partial occupancies in practice-770
        from crystalpilot.refine.tools_analysis import RenameAtoms
        xs = _toy_p1bar()
        ctx = _ctx(xs)
        ctx.session.flags["disorder_groups"] = [{
            "fvar_index": 2, "value": 0.55,
            "members": [
                {"label": "C1", "part": 1, "sign": 1, "mult": 1.0},
                {"label": "N1", "part": 2, "sign": -1, "mult": 1.0},
            ]}]
        r = RenameAtoms(None).run(ctx, mode="map", map={"C1": "C9"})
        assert r.ok, r.error
        labels = [m["label"] for g in ctx.session.flags["disorder_groups"]
                  for m in g["members"]]
        assert "C9" in labels and "C1" not in labels
        assert "N1" in labels  # untouched member survives

    def test_rename_remaps_live_riding_fixup_checks(self):
        # r11 case-c: canonical rename left stale labels inside the live
        # _HRidingFixup.checks -> the very next refine hit the staleness
        # guard and refused ("expected 'H1' at index N"), forcing an
        # add_hydrogens re-run. Rename relabels in place (no reorder), so
        # the checks must be remapped, not invalidated.
        from crystalpilot.refine.tools_analysis import RenameAtoms
        from crystalpilot.tools.hydrogen_tools import _HRidingFixup
        xs = _toy_p1bar()
        ctx = _ctx(xs)
        old_labels = [sc.label for sc in xs.scatterers()]
        fixup = _HRidingFixup(
            checks=[(i, lbl) for i, lbl in enumerate(old_labels)],
            h_indices=[])
        ctx.session.flags["h_constraints"] = [fixup]
        r = RenameAtoms(None).run(
            ctx, mode="map", map={old_labels[0]: "C9"})
        assert r.ok, r.error
        assert r.summary["n_renamed"] == 1
        scs = xs.scatterers()
        for i, lbl in fixup.checks:
            assert scs[i].label == lbl, (
                f"check {i}: stored {lbl!r} vs live {scs[i].label!r}")


# --------------------------------------------------------------------------- #
# set_experiment: whitelisted, provenance-required metadata recording
# --------------------------------------------------------------------------- #

class TestSetExperiment:
    @staticmethod
    def _proj(tmp_path):
        from types import SimpleNamespace
        d = tmp_path / "proj"
        d.mkdir()
        return SimpleNamespace(dir=d, context={})

    def _run(self, proj, **kw):
        from types import SimpleNamespace

        from crystalpilot.refine.tools_analysis import SetExperiment
        return SetExperiment(proj).run(SimpleNamespace(session=None), **kw)

    def test_legal_keys_land_in_context(self, tmp_path):
        import json
        proj = self._proj(tmp_path)
        r = self._run(proj, experiment={
            "temperature_K": 150,
            "crystal": {"colour": "colourless", "size_mm": [0.2, 0.15, 0.1]},
            "absorption": {"type": "multi-scan", "t_min": 0.41,
                           "t_max": 0.75}},
            provenance="TWINABS listing + mount notes 2026-08-30")
        assert r.ok, r.error
        ctx = json.loads((proj.dir / "context.json").read_text("utf-8"))
        exp = ctx["experiment"]
        assert exp["temperature_K"] == 150.0
        assert exp["crystal"]["size_mm"] == [0.2, 0.15, 0.1]
        assert exp["absorption"]["type"] == "multi-scan"
        assert "set_experiment" in exp["provenance"]
        assert "TWINABS listing" in exp["provenance"]

    def test_unknown_key_rejected(self, tmp_path):
        proj = self._proj(tmp_path)
        r = self._run(proj, experiment={"favourite_colour": "blue"},
                      provenance="made up for the test")
        assert not r.ok and "unknown key 'favourite_colour'" in r.error
        r2 = self._run(proj, experiment={"crystal": {"mood": "shiny"}},
                       provenance="made up for the test")
        assert not r2.ok and "crystal.mood" in r2.error
        assert not (proj.dir / "context.json").exists()   # nothing written

    def test_absorption_type_must_be_iucr_keyword(self, tmp_path):
        proj = self._proj(tmp_path)
        r = self._run(proj, experiment={"absorption": {"type": "SADABS"}},
                      provenance="vendor said so, wrong vocabulary")
        assert not r.ok and "IUCr keyword" in r.error

    def test_provenance_required(self, tmp_path):
        proj = self._proj(tmp_path)
        r = self._run(proj, experiment={"temperature_K": 100}, provenance="")
        assert not r.ok and "provenance" in r.error

    def test_provenance_appends(self, tmp_path):
        import json
        proj = self._proj(tmp_path)
        assert self._run(proj, experiment={"temperature_K": 100},
                         provenance="cryostream setpoint, run log").ok
        assert self._run(proj, experiment={
            "crystal": {"colour": "yellow"}},
            provenance="microscope photo 2026-08-30").ok
        ctx = json.loads((proj.dir / "context.json").read_text("utf-8"))
        prov = ctx["experiment"]["provenance"]
        assert "cryostream" in prov and "microscope" in prov
        assert ctx["experiment"]["temperature_K"] == 100.0   # merge kept it


def test_change_space_group_refuses_empty_model():
    """r14a live-fire: atomless cold-start model crashed the verify pass
    with a raw traceback; must be a clean refusal instead. Since the T8
    declaration path, an explicit space_group on an atomless session
    declares the group - but only when reflection data exist, so this
    dataless case still refuses cleanly."""
    from types import SimpleNamespace
    from cctbx import crystal, xray
    from crystalpilot.core.dataset import ReflectionDataset
    from crystalpilot.pipeline.session import SolveSession
    from crystalpilot.refine.tools_symmetry import ChangeSpaceGroup
    from crystalpilot.tools.base import ToolContext

    cs = crystal.symmetry(unit_cell=(10, 11, 12, 90, 90, 90),
                          space_group_symbol="P 1")
    xs = xray.structure(crystal_symmetry=cs)
    ses = SolveSession(dataset=ReflectionDataset(
        intensities=None, wavelength=0.71073))
    ses.model = xs
    ses.symmetry = cs

    class _St:
        def record(self, *a, **k):
            return None

        def log(self, *a, **k):
            return None

    tool = ChangeSpaceGroup(SimpleNamespace(session=ses))
    r = tool.run(ToolContext(store=_St(), session=ses),
                 space_group="P 21 21 2")
    assert not r.ok
    assert "no reflection data" in (r.error or "")
    assert "Traceback" not in str(r.summary)


class TestHeavyAnchorFallback:
    """r16 backflow: garbage light atoms drown a real inversion in
    full-model matching; the heavy-anchor search must still find it."""

    def _p1_garbage_lights(self, invert_heavies=True):
        from cctbx import crystal, xray
        cs = crystal.symmetry(unit_cell=(10.1, 12.7, 20.7, 72.2, 75.9, 83.7),
                              space_group_symbol="P 1")
        xs = xray.structure(crystal_symmetry=cs)
        centre = (0.161, 0.391, 0.022)
        heavies = [("LA1", "La", (0.0903, 0.3696, 0.2522)),
                   ("NI1", "Ni", (0.1934, 0.2528, 0.7296))]
        for lbl, el, s in heavies:
            xs.add_scatterer(xray.scatterer(label=lbl, site=s, u=0.02,
                                            scattering_type=el))
            if invert_heavies:
                mate = tuple((2 * c - x) % 1 for c, x in zip(centre, s))
            else:
                mate = tuple((x + 0.137) % 1 for x in s)
            xs.add_scatterer(xray.scatterer(
                label=lbl.replace("1", "2"), site=mate, u=0.02,
                scattering_type=el))
        # 12 pseudo-random NON-centrosymmetric light atoms (garbage model)
        rng = [(0.71, 0.13, 0.55), (0.22, 0.86, 0.31), (0.45, 0.29, 0.09),
               (0.83, 0.57, 0.66), (0.09, 0.74, 0.48), (0.36, 0.41, 0.91),
               (0.58, 0.02, 0.27), (0.94, 0.33, 0.72), (0.17, 0.62, 0.14),
               (0.66, 0.95, 0.39), (0.31, 0.18, 0.83), (0.77, 0.49, 0.06)]
        for i, s in enumerate(rng):
            xs.add_scatterer(xray.scatterer(
                label=f"C{i+1}", site=s, u=0.04, scattering_type="C"))
        return xs

    def test_heavy_inversion_found_despite_garbage_lights(self):
        xs = self._p1_garbage_lights(invert_heavies=True)
        r = CheckSymmetry(None).run(_ctx(xs))
        assert r.ok
        s = r.summary
        assert not s["extra_ops_matched"]          # full model: silent
        assert s.get("heavy_substructure_ops"), s["verdict"]
        h0 = s["heavy_substructure_ops"][0]
        assert h0["fraction"] >= 0.99
        assert "HEAVY-SUBSTRUCTURE" in s["verdict"]
        assert "P1" in s["verdict"] or "P-1" in s["verdict"]
        anchors = s["heavy_anchor_info"]
        assert anchors["n_anchors"] == 4
        assert set(anchors["elements"]) == {"La", "Ni"}

    def test_no_false_alarm_when_heavies_not_related(self):
        xs = self._p1_garbage_lights(invert_heavies=False)
        r = CheckSymmetry(None).run(_ctx(xs))
        assert r.ok
        assert not r.summary.get("heavy_substructure_ops")
        assert "complete" in r.summary["verdict"]


class TestScreenSpaceGroups:
    """r22 gap #5: both arms shell-imported crystalpilot.refine.sg_screen
    by hand because the absence/E-statistics table only shipped inside
    scale_and_export (frames route). Now a session tool."""

    @staticmethod
    def _session(cell, sg="P 1", d_min=1.2):
        from cctbx import crystal, miller
        from cctbx.array_family import flex
        cs = crystal.symmetry(unit_cell=cell, space_group_symbol=sg)
        ms = miller.build_set(cs, anomalous_flag=False, d_min=d_min)
        n = ms.indices().size()
        arr = miller.array(ms, data=flex.double(n, 1000.0),
                           sigmas=flex.double(n, 10.0))
        arr = arr.set_observation_type_xray_intensity()
        return SimpleNamespace(dataset=SimpleNamespace(intensities=arr),
                               symmetry=cs, flags={})

    def test_metric_default_monoclinic(self):
        from crystalpilot.refine.tools_analysis import ScreenSpaceGroups
        ses = self._session((6, 7, 8, 90, 95, 90))
        r = ScreenSpaceGroups(None).run(SimpleNamespace(session=ses))
        assert r.ok, r.error
        s = r.summary
        assert "metric" in s["laue_source"]
        assert "2/m" in s["laue_class_used"]
        assert s["candidates"], "no candidates returned"
        # uniformly strong data: only condition-free groups stay consistent
        top = s["candidates"][0]
        assert top["consistent"] and top["n_absent_obs"] == 0
        by_sg = {c["space_group"]: c for c in s["candidates"]}
        p21c = next((v for k, v in by_sg.items() if "21/c" in k), None)
        if p21c is not None:
            assert not p21c["consistent"]

    def test_explicit_shorthand_orthorhombic(self):
        from crystalpilot.refine.tools_analysis import ScreenSpaceGroups
        ses = self._session((6, 7, 8, 90, 90, 90))
        r = ScreenSpaceGroups(None).run(
            SimpleNamespace(session=ses), laue_group="mmm")
        assert r.ok, r.error
        s = r.summary
        assert s["laue_source"].startswith("explicit")
        assert "m m m" in s["laue_class_used"] or "mmm" in s["laue_class_used"]
        assert s["n_candidates_total"] > 10   # full mmm table, not Sohncke

    def test_bad_laue_symbol_fails_loud(self):
        from crystalpilot.refine.tools_analysis import ScreenSpaceGroups
        ses = self._session((6, 7, 8, 90, 90, 90))
        r = ScreenSpaceGroups(None).run(
            SimpleNamespace(session=ses), laue_group="bogus-42")
        assert not r.ok
        assert "shorthand" in r.error.lower() or "mmm" in r.error

    def test_trigonal_shorthands_differ(self):
        from crystalpilot.refine.tools_analysis import _resolve_laue
        a = _resolve_laue("-3m1")
        b = _resolve_laue("-31m")
        ops_a = {str(op) for op in a.all_ops()}
        ops_b = {str(op) for op in b.all_ops()}
        assert ops_a != ops_b

    def test_no_dataset_refused(self):
        from crystalpilot.refine.tools_analysis import ScreenSpaceGroups
        ses = SimpleNamespace(dataset=None, symmetry=None)
        r = ScreenSpaceGroups(None).run(SimpleNamespace(session=ses))
        assert not r.ok and "no dataset" in r.error


class TestSetExperimentNullRemoves:
    """Process-audit T13: r15 hand-deleted a bogus 293 K placeholder from
    context.json; r11_c's set_experiment(temperature_K=null) was refused.
    null now removes the key (unknown facts stay absent)."""

    @staticmethod
    def _proj(tmp_path):
        d = tmp_path / "proj"
        d.mkdir()
        return SimpleNamespace(dir=d, context={})

    def _run(self, proj, **kw):
        from crystalpilot.refine.tools_analysis import SetExperiment
        return SetExperiment(proj).run(SimpleNamespace(session=None), **kw)

    def test_null_removes_recorded_key(self, tmp_path):
        import json
        proj = self._proj(tmp_path)
        r = self._run(proj, experiment={"temperature_K": 293,
                                        "crystal": {"colour": "green"}},
                      provenance="placeholder injected by import test")
        assert r.ok
        r2 = self._run(proj, experiment={"temperature_K": None},
                       provenance="placeholder was bogus - fact unknown")
        assert r2.ok, r2.error
        assert r2.summary["removed"] == ["temperature_K"]
        ctx = json.loads((proj.dir / "context.json").read_text("utf-8"))
        assert "temperature_K" not in ctx["experiment"]
        assert ctx["experiment"]["crystal"]["colour"] == "green"
        assert "-temperature_K" in ctx["experiment"]["provenance"]

    def test_null_subkey_and_absent_removal(self, tmp_path):
        proj = self._proj(tmp_path)
        r = self._run(proj, experiment={"crystal": {"colour": "red",
                                                    "description": None}},
                      provenance="mount notes say colour only, no habit")
        assert r.ok, r.error
        assert r.summary.get("remove_requested_but_absent") == [
            "crystal.description"]
        import json
        ctx = json.loads((proj.dir / "context.json").read_text("utf-8"))
        assert ctx["experiment"]["crystal"] == {"colour": "red"}

    def test_null_unknown_key_still_rejected(self, tmp_path):
        proj = self._proj(tmp_path)
        r = self._run(proj, experiment={"favourite_colour": None},
                      provenance="made up for the test")
        assert not r.ok and "favourite_colour" in r.error


class TestSetExperimentAutoImport:
    """pa1 L3: the runner wrote instrument/temperature/colour into the
    project-root context.json; the values flowed into TEMP cards and the
    CIF silently, yet 5/8 L3 agents re-keyed them through set_experiment
    after checkcif, one re-transcribed a non-ASCII source by hand. A
    no-argument call now imports the block visibly: normalised, on the
    provenance trail, with the wavelength cross-checked against the data.
    Explicit values still win over the file."""

    CU_BLOCK = {
        "instrument": {"diffractometer": "single-crystal diffractometer, "
                                        "Cu K-alpha",
                       "source": "Cu, 1.54178 A"},
        "temperature_K": "173",
        "crystal": {"colour": "green"},
    }

    @staticmethod
    def _proj(tmp_path, block):
        import json
        d = tmp_path / "proj"
        d.mkdir()
        ctx = {}
        if block is not None:
            ctx = {"experiment": block, "chemistry": {"note": "Cu + ligand"}}
            (d / "context.json").write_text(json.dumps(ctx, indent=2),
                                            encoding="utf-8")
        return SimpleNamespace(dir=d, context=ctx, session=None)

    @staticmethod
    def _ctx(wavelength=None):
        ds = SimpleNamespace(wavelength=wavelength)
        return SimpleNamespace(session=SimpleNamespace(dataset=ds)
                               if wavelength else None)

    def _run(self, proj, ctx=None, **kw):
        from crystalpilot.refine.tools_analysis import SetExperiment
        return SetExperiment(proj).run(ctx or self._ctx(), **kw)

    def test_no_arguments_imports_and_normalises(self, tmp_path):
        import json
        proj = self._proj(tmp_path, self.CU_BLOCK)
        r = self._run(proj, self._ctx(1.54178))
        assert r.ok, r.error
        imp = r.summary["imported_from_context_json"]
        assert imp["temperature_K"] == 173.0          # "173" coerced
        assert imp["crystal.colour"] == "green"
        assert imp["instrument.source"] == "Cu, 1.54178 A"
        assert r.summary["radiation_check"] == {
            "context_json_A": 1.54178, "data_A": 1.54178, "agrees": True}
        assert r.summary["provenance_recorded"] is True
        assert "warnings" not in r.summary
        ctx = json.loads((proj.dir / "context.json").read_text("utf-8"))
        assert ctx["experiment"]["temperature_K"] == 173.0
        assert "imported from context.json" in ctx["experiment"]["provenance"]
        assert "temperature_K" in ctx["experiment"]["provenance"]
        assert ctx["chemistry"]["note"] == "Cu + ligand"   # untouched
        # idempotent: a second import records nothing new
        r2 = self._run(proj, self._ctx(1.54178))
        assert r2.ok and r2.summary["provenance_recorded"] is False
        ctx2 = json.loads((proj.dir / "context.json").read_text("utf-8"))
        assert ctx2["experiment"]["provenance"].count(
            "imported from context.json") == 1

    def test_nothing_to_import_is_a_clear_no_op(self, tmp_path):
        proj = self._proj(tmp_path, None)
        r = self._run(proj)
        assert r.ok, r.error
        assert r.summary["imported_from_context_json"] == {}
        assert "nothing to import" in r.summary["note"]
        assert not (proj.dir / "context.json").exists()
        # an empty experiment object means the same thing
        r2 = self._run(proj, experiment={}, provenance="x")
        assert r2.ok and "nothing to import" in r2.summary["note"]

    def test_explicit_values_win_over_the_file(self, tmp_path):
        import json
        proj = self._proj(tmp_path, self.CU_BLOCK)
        assert self._run(proj).ok
        r = self._run(proj, experiment={"crystal": {"colour": "blue"}},
                      provenance="microscope photo, mount notes")
        assert r.ok, r.error
        ctx = json.loads((proj.dir / "context.json").read_text("utf-8"))
        assert ctx["experiment"]["crystal"]["colour"] == "blue"
        r2 = self._run(proj)
        assert r2.summary["imported_from_context_json"]["crystal.colour"] \
            == "blue"

    def test_unknown_keys_and_bad_values_reported_not_fatal(self, tmp_path):
        proj = self._proj(tmp_path, {
            "wavelength_A": 0.68883, "temperature_K": "cold",
            "crystal": {"habit": "block", "colour": "yellow"},
            "absorption": {"type": "SADABS"}})
        r = self._run(proj)
        assert r.ok, r.error
        assert r.summary["imported_from_context_json"] == {
            "crystal.colour": "yellow"}
        assert set(r.summary["ignored_keys"]) == {"wavelength_A",
                                                  "crystal.habit"}
        warns = " ".join(r.summary["warnings"])
        assert "temperature_K" in warns and "IUCr keyword" in warns
        assert r.summary["radiation_check"] == {"context_json_A": 0.68883,
                                                "data_A": None}

    def test_wavelength_mismatch_and_non_ascii_source_warn(self, tmp_path):
        proj = self._proj(tmp_path, {
            "instrument": {"source": "同步辐射 lambda = 0.68883 A"}})
        r = self._run(proj, self._ctx(0.71073))
        assert r.ok, r.error
        assert r.summary["radiation_check"]["agrees"] is False
        warns = " ".join(r.summary["warnings"])
        assert "CELL" in warns and "ASCII" in warns
        assert r.summary["imported_from_context_json"] == {
            "instrument.source": "同步辐射 lambda = 0.68883 A"}

    def test_description_announces_the_auto_import(self):
        from crystalpilot.refine.tools_analysis import SetExperiment
        assert "AUTO-IMPORT" in SetExperiment.description
        assert "context.json" in SetExperiment.description
        assert SetExperiment.params_schema["required"] == []


class TestImportPointerFollowsWrittenModel:
    def test_import_overrides_stale_atomless_pointer(self, tmp_path):
        """r22 live: ingest left data.start_model=start.ins (atomless);
        import_cif_model wrote start.res but kept the stale pointer, so
        reload rebuilt an EMPTY session and the tool blamed the CIF
        ('0 atoms - atom loop was not read')."""
        import json
        d = tmp_path / "proj"
        d.mkdir()
        (d / "start.ins").write_text(
            "TITL atomless bootstrap\n"
            "CELL 0.71073 10 10 10 90 90 90\n"
            "ZERR 1 0 0 0 0 0 0\nLATT 1\nSFAC C\nUNIT 4\nHKLF 4\nEND\n",
            encoding="ascii")
        (d / "context.json").write_text(json.dumps(
            {"data": {"start_model": "start.ins"}}), encoding="utf-8")
        from crystalpilot.refine.project import RefineProject
        p = RefineProject(d)
        p.open()
        src = REPO / "benchmark" / "public" / "Ca_imidazolate"
        r = p.invoke_tool("import_cif_model", {
            "cif_path": str(src / "ref_cif.cif"),
            "hkl_path": str(src / "sf.cif")})
        assert r.ok, r.error
        assert r.summary["imported_atoms"] > 5
        ctx = json.loads((d / "context.json").read_text("utf-8"))
        assert ctx["data"]["start_model"] == "start.res"


class TestCifWriterDuplicateLabels:
    def test_duplicate_labels_renamed_in_output(self, tmp_path):
        from cctbx import crystal, xray
        from crystalpilot.report.cif import structure_to_cif
        cs = crystal.symmetry(unit_cell=(10, 10, 10, 90, 90, 90),
                              space_group_symbol="P 1")
        xs = xray.structure(crystal_symmetry=cs)
        for site in ((0.1, 0.1, 0.1), (0.4, 0.4, 0.4)):
            xs.add_scatterer(xray.scatterer(
                label="C29X", site=site, scattering_type="C", u=0.03))
        out = tmp_path / "dup.cif"
        structure_to_cif(xs, out)
        text = out.read_text("utf-8")
        assert "duplicate atom labels renamed" in text
        rows = [ln.split()[0] for ln in text.splitlines()
                if ln.strip().startswith("C29X")]
        assert rows == ["C29X", "C29Xa"]


class TestSupercellSentinels:
    """Process-audit T4: move the composite-supercell alarm to the
    indexing stage (r17 sank 79 min; r18 only recovered 45 min in) and
    teach the E-statistics alarm the ABOVE-centric direction (r17's
    1.017 went unremarked)."""

    def test_volume_multiple_fires(self):
        from crystalpilot.refine.tools_frames import _supercell_sentinel
        half = (10.0, 12.0, 20.4, 90, 90, 90)
        double = (10.0, 24.05, 20.4, 90, 90, 90)     # 2.004x volume
        msg = _supercell_sentinel(double, [("earlier index run", half)])
        assert msg and "integer multiple" in msg
        assert "max_lattices=2" in msg
        # reverse direction (found the half after the super)
        msg2 = _supercell_sentinel(half, [("earlier index run", double)])
        assert msg2 and "SMALLER" in msg2

    def test_non_multiple_silent(self):
        from crystalpilot.refine.tools_frames import _supercell_sentinel
        a = (10.0, 12.0, 20.4, 90, 90, 90)
        b = (11.3, 13.1, 20.4, 90, 92, 90)           # 1.38x - not integer
        assert _supercell_sentinel(a, [("x", b)]) is None
        assert _supercell_sentinel(a, []) is None
        assert _supercell_sentinel(None, [("x", b)]) is None

    def test_hyper_dispersed_e_statistics_alarm(self):
        from types import SimpleNamespace

        from cctbx import crystal, miller
        from cctbx.array_family import flex
        from crystalpilot.refine.tools_analysis import AuditReflectionData
        cs = crystal.symmetry(unit_cell=(6, 7, 8, 90, 95, 90),
                              space_group_symbol="P 21/c")
        ms = miller.build_set(cs, anomalous_flag=False, d_min=0.9)
        n = ms.indices().size()
        # a few enormous outliers over a sea of near-zeros: |E^2-1|
        # climbs ABOVE the centric 0.968 reference
        data = flex.double([1e5 if i % 50 == 0 else 1.0 for i in range(n)])
        arr = miller.array(ms, data=data, sigmas=flex.double(n, 1.0))
        arr = arr.set_observation_type_xray_intensity()
        ses = SimpleNamespace(dataset=SimpleNamespace(intensities=arr),
                              symmetry=cs, flags={})
        r = AuditReflectionData(None).run(SimpleNamespace(session=ses))
        assert r.ok, r.error
        s = r.summary
        assert s["e_statistics"]["mean_abs_e2_minus_1"] > 1.1
        assert "hyper_dispersed_e_statistics" in s["twin_alarm"]["signs"]
        assert any("SUPERCELL" in h for h in s["hints"])


class TestAtomlessSpaceGroupDeclaration:
    """Process-audit T8/r22: both arms called change_space_group on an
    atomless session, got refused, and invented the same hand-written
    start.ins workaround. An explicit space_group now declares."""

    @staticmethod
    def _atomless(tmp_path):
        from cctbx import crystal, miller, xray
        from cctbx.array_family import flex
        cs = crystal.symmetry(unit_cell=(10.669, 28.8515, 31.1309,
                                         90, 90, 90),
                              space_group_symbol="P 1")
        ms = miller.build_set(cs, anomalous_flag=False, d_min=2.5)
        n = ms.indices().size()
        arr = miller.array(ms, data=flex.double(n, 50.0),
                           sigmas=flex.double(n, 2.0))
        arr = arr.set_observation_type_xray_intensity()
        ses = SimpleNamespace(
            model=xray.structure(crystal_symmetry=cs),
            dataset=SimpleNamespace(intensities=arr), symmetry=cs,
            flags={}, refinement_history=[],
            set_symmetry=None)
        # borrow the real re-merge behaviour
        from crystalpilot.pipeline.session import SolveSession
        ses.set_symmetry = SolveSession.set_symmetry.__get__(ses)
        smp = tmp_path / "start.ins"
        smp.write_text(
            "TITL bootstrap\nCELL 1.54178 10.669 28.8515 31.1309 90 90 90\n"
            "ZERR 4 0 0 0 0 0 0\nLATT -1\nSFAC C H N O\nUNIT 4 4 4 4\n"
            "HKLF 4\nEND\n", encoding="ascii")
        # The original input stays untouched; the canonical model is what
        # the project transaction will commit as a new declaration node.
        proj = SimpleNamespace(start_model_path=smp, dir=tmp_path)
        return ses, proj, smp

    def test_declares_canonical_group_without_rewriting_input(self, tmp_path):
        from crystalpilot.refine.tools_symmetry import ChangeSpaceGroup
        ses, proj, smp = self._atomless(tmp_path)
        original = smp.read_bytes()
        # the fixture's uniform intensities carry full signal in the
        # C-centring class: the absence gate (pa2 hex R-3 trap) refuses a
        # centring the data contradict unless the caller takes it on
        refused = ChangeSpaceGroup(proj).run(SimpleNamespace(session=ses),
                                             space_group="C c c m")
        assert not refused.ok and "lattice-centring" in refused.error
        assert str(ses.symmetry.space_group_info()) == "P 1"   # untouched
        r = ChangeSpaceGroup(proj).run(SimpleNamespace(session=ses),
                                       space_group="C c c m",
                                       accept_absences=True)
        assert r.ok, r.error
        s = r.summary
        assert s["absence_audit"]["accepted_by_caller"] is True
        assert s["mode"] == "atomless_declaration"
        assert "C c c m" in s["declared_space_group"]
        assert s["merge"]["space_group"] == "C c c m"
        assert str(ses.symmetry.space_group_info()) == "C c c m"
        assert smp.read_bytes() == original
        assert str(ses.model.space_group_info()) == "C c c m"
        from crystalpilot.io.shelx_writer import ShelxModel, write_res_text
        txt, _ = write_res_text(ShelxModel(ses.model))
        assert "LATT 7" in txt
        assert "X+1/2,Y+1/2,Z" not in txt      # centring stays in LATT
        assert txt.count("SYMM") == 3
        assert not s.get("no_state_change")

    def test_atomless_without_symbol_still_refuses_with_guidance(
            self, tmp_path):
        from crystalpilot.refine.tools_symmetry import ChangeSpaceGroup
        ses, proj, _ = self._atomless(tmp_path)
        r = ChangeSpaceGroup(proj).run(SimpleNamespace(session=ses))
        assert not r.ok
        assert "screen_space_groups" in r.error
        r2 = ChangeSpaceGroup(proj).run(SimpleNamespace(session=ses),
                                        adopt_suggestion=True)
        assert not r2.ok

    def test_bad_symbol_fails_clean(self, tmp_path):
        from crystalpilot.refine.tools_symmetry import ChangeSpaceGroup
        ses, proj, _ = self._atomless(tmp_path)
        r = ChangeSpaceGroup(proj).run(SimpleNamespace(session=ses),
                                       space_group="Q x y z")
        assert not r.ok and "cannot declare" in r.error


class TestNcsAudit:
    """Process-audit T9: the pseudo-symmetry auditor that r16 (missed
    inversion in P1) and r17 (pseudo-translation = composite supercell)
    each had to hand-write."""

    @staticmethod
    def _two_molecules(map_b, b_elements=("C", "N", "O")):
        """P1 cell with molecule A = C-N-O triangle and molecule B =
        map_b(site) per atom, far enough apart not to bond."""
        from cctbx import crystal, xray
        cs = crystal.symmetry(unit_cell=(10, 10, 10, 90, 90, 90),
                              space_group_symbol="P 1")
        xs = xray.structure(crystal_symmetry=cs)
        a_sites = ((0.10, 0.10, 0.10), (0.24, 0.10, 0.10),
                   (0.10, 0.24, 0.10))
        for lbl, el, site in zip(("C1", "N1", "O1"),
                                 ("C", "N", "O"), a_sites):
            xs.add_scatterer(xray.scatterer(label=lbl, site=site, u=0.03,
                                            scattering_type=el))
        for lbl, el, site in zip(("C2", "N2", "O2"), b_elements,
                                 [map_b(s) for s in a_sites]):
            xs.add_scatterer(xray.scatterer(label=lbl, site=site, u=0.03,
                                            scattering_type=el))
        return xs

    def test_missed_inversion_rational(self):
        from crystalpilot.refine.tools_symmetry import NcsAudit
        xs = self._two_molecules(
            lambda s: tuple(0.5 - x for x in s))     # centre (1/4,1/4,1/4)
        r = NcsAudit(None).run(_ctx(xs))
        assert r.ok
        inv = r.summary["hypotheses"]["inversion"]
        assert inv["match_fraction"] == 1.0
        assert inv["rmsd_A"] < 0.05
        assert inv["rational"]["is_rational"]
        assert "inversion centre" in inv["verdict"]
        assert "auto" in r.summary["fragments"]

    def test_pseudo_translation_half_c(self):
        from crystalpilot.refine.tools_symmetry import NcsAudit
        xs = self._two_molecules(lambda s: (s[0], s[1], s[2] + 0.5))
        r = NcsAudit(None).run(_ctx(xs))
        assert r.ok
        tr = r.summary["hypotheses"]["translation"]
        assert tr["match_fraction"] == 1.0
        assert tr["rational"]["is_rational"]
        assert "doubled/composite cell" in tr["verdict"]
        assert "element_mismatches" not in tr

    def test_irrational_translation_is_true_ncs(self):
        from crystalpilot.refine.tools_symmetry import NcsAudit
        xs = self._two_molecules(
            lambda s: (s[0] + 0.21, s[1] + 0.045, s[2] + 0.29))
        r = NcsAudit(None).run(_ctx(xs))
        assert r.ok
        tr = r.summary["hypotheses"]["translation"]
        assert tr["match_fraction"] == 1.0
        assert not tr["rational"]["is_rational"]
        assert "genuine Z" in tr["verdict"]

    def test_element_mismatch_table(self):
        from crystalpilot.refine.tools_symmetry import NcsAudit
        xs = self._two_molecules(lambda s: (s[0], s[1], s[2] + 0.5),
                                 b_elements=("C", "C", "O"))
        r = NcsAudit(None).run(_ctx(xs))
        assert r.ok
        tr = r.summary["hypotheses"]["translation"]
        assert tr["n_matched"] == 3          # position match survives
        mism = tr["element_mismatches"]
        assert len(mism) == 1
        assert mism[0]["elements"] == "N vs C"

    def test_explicit_fragments_and_bad_labels(self):
        from crystalpilot.refine.tools_symmetry import NcsAudit
        xs = self._two_molecules(lambda s: (s[0], s[1], s[2] + 0.5))
        r = NcsAudit(None).run(_ctx(xs),
                               fragment_a=["C1", "N1", "O1"],
                               fragment_b=["C2", "N2", "O2"])
        assert r.ok and r.summary["fragments"] == "explicit fragments"
        r2 = NcsAudit(None).run(_ctx(xs), fragment_a=["C1", "ZZ9"],
                                fragment_b=["C2"])
        assert not r2.ok and "ZZ9" in r2.error

    def test_no_model_refused(self):
        from crystalpilot.refine.tools_symmetry import NcsAudit
        ctx = SimpleNamespace(session=SimpleNamespace(model=None))
        r = NcsAudit(None).run(ctx)
        assert not r.ok
