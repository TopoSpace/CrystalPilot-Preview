"""Coordinated-solvent mask guardrail (专家铁律 "绝不遮配位" mechanized).

A masked void whose grid reaches into a metal coordination sphere is the
signature of masking a coordinated ligand (or an open metal site whose
guest should be modelled). The geometric probe is unit-tested against a
stub mask object; live smtbx masks are exercised by campaigns.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from cctbx import crystal, xray
from cctbx.array_family import flex

from crystalpilot.tools.mask_tools import _coordination_encroachment


def _structure():
    cs = crystal.symmetry(unit_cell=(12, 12, 12, 90, 90, 90),
                          space_group_symbol="P 1")
    xs = xray.structure(crystal_symmetry=cs)
    # Zn 0.4 A below the void boundary plane (inner-shell hit);
    # C far from the void (and not a metal anyway)
    for lbl, site, el in (("ZN1", (0.5, 0.5, 0.30), "Zn"),
                          ("C1", (0.5, 0.5, 0.05), "C")):
        xs.add_scatterer(xray.scatterer(
            label=lbl, site=site, scattering_type=el, u=0.03, occupancy=1.0))
    xs.scattering_type_registry(table="it1992")
    return xs


def _stub_mask(exclude: bool):
    n = 24
    grid = flex.int(flex.grid(n, n, n), 0)
    # void label 2 fills the z >= 1/3 slab (boundary at z = 4.0 A)
    for i in range(n):
        for j in range(n):
            for k in range(n // 3, n):
                grid[(i, j, k)] = 2
    return SimpleNamespace(mask=SimpleNamespace(data=grid),
                           exclude_void_flags=[exclude])


def test_metal_near_masked_void_is_flagged():
    enc = _coordination_encroachment(_stub_mask(exclude=False), _structure())
    assert enc == [{"metal": "ZN1", "void": 1, "within_A": 2.2}]


def test_excluded_void_does_not_warn():
    assert _coordination_encroachment(_stub_mask(exclude=True),
                                      _structure()) == []


def test_obligation_line_from_encroachment():
    from crystalpilot.refine.tools_deliver import _mask_obligations
    rec = {"n_voids_masked": 1,
           "coordination_encroachment": [
               {"metal": "ZN1", "void": 1, "within_A": 2.2}]}
    duties = _mask_obligations(rec, "C10 H20 Zn", "_platon_squeeze yes")
    assert any("配位球" in d and "ZN1" in d for d in duties)
    # and without encroachment the duty is absent
    duties0 = _mask_obligations({"n_voids_masked": 1}, "C10 H20 Zn",
                                "_platon_squeeze yes")
    assert not any("配位球" in d for d in duties0)


class TestVoidElectronConsistency:
    """The solvent_mask TOOL and the viewer must report the same electron
    counts. They used to differ by n_grid/(n_grid-n_solvent) because only
    the viewer corrected for smtbx's map-buffer aliasing, and the tool's
    number is the one the agent divides by 40 to name a solvent."""

    class _FakeMask:
        def __init__(self, gp, excluded=()):
            self._gp = list(gp)
            self.exclude_void_flags = [i in excluded
                                       for i in range(len(gp))]

        def n_solvent_grid_points(self):
            return sum(g for i, g in enumerate(self._gp)
                       if not self.exclude_void_flags[i])

    def test_display_and_tool_share_one_implementation(self):
        # not "give the same answer" - literally the same function, so a
        # future fix to one cannot silently miss the other
        from crystalpilot.refine.scene import _consistent_void_electrons
        from crystalpilot.tools.mask_tools import consistent_void_electrons

        gp = [600, 200]
        m = self._FakeMask(gp)
        raw = [3000.0, 1200.0]
        total = 840.0
        assert _consistent_void_electrons(m, gp, raw, total) == \
            pytest.approx(consistent_void_electrons(m, gp, raw, total))

    def test_surplus_removed_in_proportion_to_void_size(self):
        from crystalpilot.tools.mask_tools import consistent_void_electrons

        gp, n_grid = [600, 200], 1000
        m = self._FakeMask(gp)
        rescale = n_grid / (n_grid - sum(gp))       # 5.0
        truth = [5.0, 3.0]                         # deliberately not ∝ gp
        total = sum(truth) * rescale
        raw = [(truth[i] + total * gp[i] / n_grid) * rescale
               for i in range(2)]
        out = consistent_void_electrons(m, gp, raw, total)
        assert sum(out) == pytest.approx(total)
        assert out == pytest.approx([t * rescale for t in truth])

    def test_converged_run_passes_through_untouched(self):
        from crystalpilot.tools.mask_tools import consistent_void_electrons

        gp = [600, 200]
        m = self._FakeMask(gp)
        conv = [25.0, 15.0]
        assert consistent_void_electrons(m, gp, conv, sum(conv)) == \
            pytest.approx(conv)

    def test_excluded_voids_are_zero_on_both_sides_of_the_books(self):
        from crystalpilot.tools.mask_tools import consistent_void_electrons

        gp = [600, 200]
        m = self._FakeMask(gp, excluded={1})
        out = consistent_void_electrons(m, gp, [800.0, 999.0], 800.0)
        assert out[1] == 0.0
        assert sum(out) == pytest.approx(800.0)

    def test_tool_description_warns_before_naming_a_solvent(self):
        # the description tells the agent to divide by 40 for DMF; without
        # the convergence caveat that reads as a measurement
        from crystalpilot.tools.mask_tools import SolventMask

        desc = SolventMask.description
        assert "DMF 40 e" in desc
        assert "solvent_mask_converged" in desc
