"""solvent_mask: instrumented BYPASS loop and truthful void reporting.

pa1 hex: three agents received `n_voids_masked 0 / electrons 0.0 /
solvent_mask_converged true / "f_mask stored"` for a 17,490 A^3 channel -
smtbx had dropped the void for negative first-pass density and the tool
called that success - and wrote "the data do not support a mask" into their
reports; all three delivered the unmasked R1 0.185 model (masked: 0.09).
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
from cctbx import crystal, xray
from cctbx.array_family import flex
from smtbx import masks

from crystalpilot.tools.mask_tools import (BypassMask, SolventMask,
                                           negative_density_diagnosis)

REPO = Path(__file__).resolve().parents[1]
HEX_L2_R1 = REPO / "workbench" / "pa1" / "hex-l2-r1"


def _framework_and_solvent():
    """A hollow cube of carbons with 'solvent' O atoms in the middle."""
    cs = crystal.symmetry(unit_cell=(11.0, 11.0, 11.0, 90, 90, 90),
                          space_group_symbol="P 1")
    full = xray.structure(crystal_symmetry=cs)
    model = xray.structure(crystal_symmetry=cs)
    i = 0
    for x in (0.08, 0.92):
        for y in (0.08, 0.92):
            for z in (0.08, 0.92):
                for xs_ in (full, model):
                    i += 1
                    xs_.add_scatterer(xray.scatterer(
                        label=f"C{i}", site=(x, y, z),
                        scattering_type="C", u=0.03))
    for k, site in enumerate(((0.5, 0.5, 0.5), (0.5, 0.5, 0.62),
                              (0.42, 0.55, 0.45))):
        full.add_scatterer(xray.scatterer(
            label=f"O{k + 1}", site=site, scattering_type="O", u=0.08))
    for xs_ in (full, model):
        xs_.scattering_type_registry(table="it1992")
    fc = full.structure_factors(d_min=0.9).f_calc()
    fo_sq = fc.intensities().customized_copy(
        sigmas=flex.double(fc.size(), 1.0)) \
        .set_observation_type_xray_intensity()
    return model, fo_sq


class TestBypassParity:
    def test_same_numbers_as_smtbx(self):
        model, fo_sq = _framework_and_solvent()
        ref = masks.mask(model, fo_sq, use_set_completion=True)
        ours = BypassMask(model, fo_sq, use_set_completion=True)
        for m in (ref, ours):
            m.compute(solvent_radius=1.2, shrink_truncation_radius=1.2,
                      resolution_factor=0.25)
        f_ref = ref.structure_factors(max_cycles=10)
        f_ours = ours.structure_factors(max_cycles=10)
        assert ours.n_voids() == ref.n_voids() >= 1
        assert list(ours.exclude_void_flags) == list(ref.exclude_void_flags)
        assert ours.f_000_s == pytest.approx(ref.f_000_s, rel=1e-9)
        d = flex.abs(f_ours.data() - f_ref.data())
        assert flex.max(d) < 1e-6 * max(1.0, flex.max(flex.abs(f_ref.data())))
        # the instrumented loop reports what smtbx only implies
        assert ours.n_cycles >= 1 and len(ours.trajectory) == ours.n_cycles
        assert ours.converged or ours.n_cycles == 10
        masked = [e for e, x in zip(ours.per_void_electrons,
                                    ours.exclude_void_flags) if not x]
        # per-void counts are the converging cycle's; f_000_s is the
        # previous cycle's (smtbx breaks before assigning) - equal to the
        # 1e-4 convergence tolerance, which is the point: no map-buffer
        # aliasing correction is needed any more
        assert sum(masked) == pytest.approx(ours.f_000_s, rel=1e-3)

    def test_divergence_guard_stops_and_keeps_best_residual(self):
        model, fo_sq = _framework_and_solvent()
        m = BypassMask(model, fo_sq, use_set_completion=True)
        m.compute(solvent_radius=1.2, shrink_truncation_radius=1.2,
                  resolution_factor=0.25)
        # a window of 1 with negative growth tolerance turns ANY rise
        # between consecutive cycles into "diverged" - exercises the stop
        f = m.structure_factors(max_cycles=10, divergence_window=1,
                                divergence_growth=-1.0)
        assert f is not None
        assert m.n_cycles <= 10
        if m.diverged:
            assert not m.converged
            assert m.kept_cycle is not None
            assert m.kept_cycle + 1 <= m.n_cycles
            assert m.residuals[m.kept_cycle] == pytest.approx(
                min(m.residuals))
        else:
            assert m.converged


class TestRunawayGuard:
    # r4-mof n0108 rebuilt WITHOUT anomalous terms: an undershoot that climbs
    # back towards a fixed point (1369 e, reached at cycle 163) - not a runaway
    RECOVERY = [1737.5, 594.6, 441.5, 414.2, 431.3, 421.6, 446.8, 473.9,
                500.9, 527.2, 552.8, 577.7, 602.8, 627.3]

    def test_recovery_from_an_undershoot_is_not_divergence(self):
        from crystalpilot.tools.mask_tools import runaway_series
        for n in range(1, len(self.RECOVERY) + 1):
            assert not runaway_series(self.RECOVERY[:n], 8, 0.20), n

    def test_a_climb_past_the_first_estimate_is_divergence(self):
        from crystalpilot.tools.mask_tools import runaway_series
        # pa1 hex-l3-r3 shape: monotone growth from the first estimate
        tr = [1636.0 * (1.05 ** i) for i in range(12)]
        assert runaway_series(tr, 8, 0.20)
        # the same growth pattern still below the first estimate: not yet
        low = [1636.0] + [400.0 * (1.05 ** i) for i in range(11)]
        assert not runaway_series(low, 8, 0.20)
        # window not filled / a flat window: never
        assert not runaway_series(tr[:5], 8, 0.20)
        assert not runaway_series([1636.0] + [1700.0] * 9, 8, 0.20)


class TestToolReporting:
    def _session(self):
        model, fo_sq = _framework_and_solvent()
        return SimpleNamespace(model=model, fo_sq=fo_sq, flags={})

    def _ctx(self, ses):
        return SimpleNamespace(session=ses, store=None, progress=None)

    def test_success_reports_bypass_block(self):
        ses = self._session()
        r = SolventMask().run(self._ctx(ses), max_cycles=10)
        assert r.ok, r.error
        s = r.summary
        assert s["n_voids_masked"] >= 1
        assert "bypass" in s and s["bypass"]["cycles_run"] >= 1
        assert s["solvent_mask_converged"] == s["bypass"]["converged"]
        assert ses.flags.get("f_mask") is not None
        assert ses.flags["solvent_mask_info"]["bypass"] == s["bypass"]
        # the f'/f'' the mask integrated with travel with the record
        assert s["anomalous_terms"] == {"C": [0.0, 0.0]}
        assert ses.flags["solvent_mask_info"]["anomalous_terms"] == s["anomalous_terms"]
        # the solvent O atoms are 24 e: the mask must see electrons there
        assert s["total_solvent_electrons_per_cell"] > 5

    def test_negative_drop_becomes_failure_with_diagnosis(self, monkeypatch):
        """Force the smtbx drop rule and check it is not called success."""
        ses = self._session()
        orig = BypassMask.structure_factors

        def dropping(self, max_cycles=10, **kw):
            f = orig(self, max_cycles=max_cycles, **kw)
            # pretend BYPASS dropped every void in cycle 1
            for j in range(self.n_voids()):
                self.exclude_void_flags[j] = True
                self.excluded_negative[j] = 0
            return f

        monkeypatch.setattr(BypassMask, "structure_factors", dropping)
        r = SolventMask().run(self._ctx(ses), max_cycles=5)
        assert not r.ok
        assert "NEGATIVE" in r.error and "too LIGHT" in r.error
        assert "do not support" in r.error       # the sentence it forbids
        assert "f_mask" not in ses.flags

    def test_failed_remask_keeps_the_previous_mask(self, monkeypatch):
        """pa2 cage-l0-r2: one NEGATIVE failure erased the stored mask and
        the last 39 minutes refined unmasked (R1 0.12 -> 0.22)."""
        ses = self._session()
        first = SolventMask().run(self._ctx(ses), max_cycles=10)
        assert first.ok and ses.flags.get("f_mask") is not None
        prev_e = ses.flags["solvent_mask_info"]["total_solvent_electrons_per_cell"]
        orig = BypassMask.structure_factors

        def dropping(self, max_cycles=10, **kw):
            f = orig(self, max_cycles=max_cycles, **kw)
            for j in range(self.n_voids()):
                self.exclude_void_flags[j] = True
                self.excluded_negative[j] = 0
            return f

        monkeypatch.setattr(BypassMask, "structure_factors", dropping)
        r = SolventMask().run(self._ctx(ses), max_cycles=5)
        assert not r.ok and "NEGATIVE" in r.error
        assert "previous mask is KEPT" in r.error
        assert r.summary["previous_mask_kept"][
            "total_solvent_electrons_per_cell"] == prev_e
        assert ses.flags.get("f_mask") is not None      # still refining with it
        assert ses.flags["solvent_mask_info"][
            "total_solvent_electrons_per_cell"] == prev_e

    def test_diagnosis_text(self):
        t = negative_density_diagnosis(1, 17490.0, 22100.0, [0])
        assert "17490 A^3" in t and "79%" in t and "cycle 1" in t
        assert "not evidence that the void is empty" in t
        # round-3 WP8: a condition, not an order - keep a converged mask if
        # there is one, otherwise compare honestly
        assert "if an earlier mask on this project converged, keep it" in t
        assert "if no mask has converged yet, say so in the delivery" in t


SJTU9 = (REPO / "benchmark" / "data" /
         "重复SJTU-9_SJTU-9_or_post_晶体数据_原始SJTU-9_olex2_temp_sjtu-9")


@pytest.mark.skipif(not SJTU9.exists(), reason="SJTU-9 case missing")
def test_checkout_restores_mask_snapshot_instead_of_recomputing(
        tmp_path, monkeypatch):
    """A masked node carries f_mask.pkl; checkout loads it and never calls
    solvent_mask again (pa1: 70-138 s per checkout/branch on masked nodes)."""
    from crystalpilot.refine.project import RefineProject
    from crystalpilot.tools import mask_tools

    d = tmp_path / "proj"
    d.mkdir()
    shutil.copy(SJTU9 / "hkl.hkl", d / "crystal.hkl")
    shutil.copy(SJTU9 / "ref_res.res", d / "start.res")
    (d / "context.json").write_text(json.dumps({
        "data": {"hkl": "crystal.hkl", "start_model": "start.res"}}),
        encoding="utf-8")
    p = RefineProject(d)
    p.open()
    r = p.invoke_tool("solvent_mask", {"max_cycles": 5})
    assert r.ok, r.error
    node = r.summary["node"]
    assert (p.nodes.node_dir(node) / "f_mask.pkl").exists()
    f_mask_committed = p.session.flags["f_mask"].deep_copy()
    info_committed = dict(p.session.flags["solvent_mask_info"])

    # leave the node, then come back: the mask must be restored, not rebuilt
    r2 = p.invoke_tool("edit_atoms", {"operations": [
        {"action": "set_u_iso", "atoms": ["O007"], "u_iso": 0.08}]})
    assert r2.ok

    def boom(self, ctx, **params):
        raise AssertionError("solvent_mask recomputed on checkout")
    monkeypatch.setattr(mask_tools.SolventMask, "run", boom)
    out = p.checkout(node)
    assert any("restored from the node snapshot" in n for n in out["notes"])
    f_mask = p.session.flags["f_mask"]
    assert f_mask.size() == f_mask_committed.size()
    assert flex.max(flex.abs(f_mask.data() - f_mask_committed.data())) < 1e-9
    assert p.session.flags["solvent_mask_info"]["n_voids_masked"] == \
        info_committed["n_voids_masked"]
    assert p.session.flags["solvent_mask_params"]["max_cycles"] == 5


def _hex_n0024_project(tmp_path):
    proj = tmp_path / "hex"
    (proj / ".crystalpilot" / "refine" / "nodes").mkdir(parents=True)
    for f in ("crystal.hkl", "start.ins", "context.json"):
        if (HEX_L2_R1 / f).exists():
            shutil.copy(HEX_L2_R1 / f, proj / f)
    shutil.copytree(HEX_L2_R1 / ".crystalpilot" / "refine" / "nodes" / "n0024",
                    proj / ".crystalpilot" / "refine" / "nodes" / "n0024")
    (proj / ".crystalpilot" / "refine" / "state.json").write_text(json.dumps({
        "active_node": "n0024", "active_branch": "main",
        "branches": {"main": "n0024"}, "seq": 25}), encoding="utf-8")
    return proj


_HEX_SKIP = pytest.mark.skipif(
    not (HEX_L2_R1 / "crystal.hkl").exists()
    or not (HEX_L2_R1 / ".crystalpilot" / "refine" / "nodes"
            / "n0024" / "model.res").exists(),
    reason="pa1 hex-l2-r1 evidence workspace not present")


@_HEX_SKIP
def test_hex_l2_r1_node_n0024_masks_once_the_anomalous_terms_are_back(tmp_path):
    """The exact call three pa1 agents made on the 79%-void NU-1000 model
    (params from node n0024). The data sit on the Zr K edge (0.68883 A,
    f' = -9.0 e on Zr): a session rebuilt from model.res WITHOUT the
    anomalous terms over-scatters on Zr, the first-pass void density
    integrates negative and BYPASS drops the 17,490 A^3 channel - which is
    what the agents saw. With the terms applied on every rebuild (round-3,
    2026-09-06) the same call masks the channel."""
    from crystalpilot.refine.project import RefineProject
    from helpers_binding import bind_legacy_project

    p = RefineProject(_hex_n0024_project(tmp_path))
    p.open()
    # n0024 predates data revisions: bind it to the workspace's own
    # crystal.hkl first (the model is unchanged; only the binding is stated)
    bind_legacy_project(p)
    r = p.invoke_tool("solvent_mask", {"d_min": 0.997, "max_cycles": 30,
                                       "min_void_volume": 50})
    assert r.ok, r.error
    s = r.summary
    assert s["n_voids_masked"] == 1 and s["total_solvent_electrons_per_cell"] > 0
    assert s["anomalous_terms"]["Zr"][0] == pytest.approx(-9.04, abs=0.2)
    assert p.session.flags.get("f_mask") is not None


@_HEX_SKIP
def test_hex_l2_r1_node_n0024_without_the_terms_is_still_a_diagnosed_failure(
        tmp_path, monkeypatch):
    """The pa1 failure mode itself stays covered: a model rebuilt without
    the terms must come back as a failure with the model-too-light
    diagnosis, never as ok/converged/0 e."""
    import crystalpilot.io.shelx_writer as sw
    from crystalpilot.refine.project import RefineProject

    monkeypatch.setattr(sw, "apply_anomalous_terms",
                        lambda xs, wavelength, table="sasaki": None)
    from helpers_binding import bind_legacy_project
    p = RefineProject(_hex_n0024_project(tmp_path))
    p.open()
    bind_legacy_project(p)          # see the test above
    assert all(sc.fp == 0.0 for sc in p.session.model.scatterers())
    r = p.invoke_tool("solvent_mask", {"d_min": 0.997, "max_cycles": 30,
                                       "min_void_volume": 50})
    assert not r.ok, r.summary
    assert "NEGATIVE" in r.error and "too LIGHT" in r.error
    assert "f_mask" not in p.session.flags
