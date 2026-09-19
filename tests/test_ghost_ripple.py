"""ghost_test's ripple pre-verdict: a Fourier ripple is not a real atom.

ka1 cage-tools-r1 (2026-09-03): 113 sites tested by ghost_test, 0 ghost.
Among them, sites 0.72-1.05 A from a Zr with Uiso = -0.001 came back
'real' - because the delete-and-refine criterion asks "does a peak come
back at the vacated site?" and a series-termination ripple of a heavy
atom of course comes back: it is the heavy atom's own artefact, not an
independent atom. The only deletion licence therefore sat behind
acknowledge_real and the agent pushed 96 deletes through it.

The fence here is read from the BASELINE model before anything is
deleted, and it is radii/Z-based - covalent radii of the actual pair and
the two atomic numbers - so it reads the same next to Zn, Zr, Pb or U and
never fires between two atoms of comparable weight. The structures below
are synthetic and two different heavy elements are used in every
distance/ADP case.
"""
from __future__ import annotations

import pytest

cctbx = pytest.importorskip("cctbx")

from cctbx import crystal, xray  # noqa: E402

from crystalpilot.refine import ghost_ledger  # noqa: E402
from crystalpilot.refine.tools_batch import (  # noqa: E402
    DISPOSITION, GHOST_CRITERION, RIPPLE_BOND_SLACK_A,
    RIPPLE_ELECTRON_FRACTION, RIPPLE_Z_FACTOR, _atoms_info, _fence_note,
    _ghost_verdict, _group_ripple, _ripple_check)
from crystalpilot.tools.base import ToolContext  # noqa: E402
from crystalpilot.tools.model_tools import EditAtoms  # noqa: E402

#: two unrelated heavy elements (Z >= 30) - the rule may not be tuned to one
HEAVY = ["Zn", "Zr"]
CELL = (20.0, 20.0, 20.0, 90.0, 90.0, 90.0)


def _structure(atoms):
    """atoms: (label, element, cartesian xyz, u_iso, occupancy)."""
    cs = crystal.symmetry(unit_cell=CELL, space_group_symbol="P 1")
    uc = cs.unit_cell()
    xs = xray.structure(crystal_symmetry=cs)
    for lbl, el, cart, u, occ in atoms:
        xs.add_scatterer(xray.scatterer(
            label=lbl, site=uc.fractionalize(cart), scattering_type=el,
            u=u, occupancy=occ))
    xs.scattering_type_registry(table="it1992")
    return xs


def _site_info(heavy_el, d, u_light, occ_light=1.0, light_el="C",
               partner_el=None):
    """One _atoms_info row for a light site `d` A from a heavy atom (plus
    an ordinary organic neighbour so the site is not isolated)."""
    partner = partner_el or heavy_el
    xs = _structure([
        ("M1", partner, (5.0, 5.0, 5.0), 0.02, 1.0),
        ("C9", light_el, (5.0 + d, 5.0, 5.0), u_light, occ_light),
        ("C10", "C", (5.0 + d + 1.45, 5.0, 5.0), 0.03, 1.0),
    ])
    return _atoms_info(xs, ["C9"])[0]


# ==========================================================================
class TestRippleFence:
    @pytest.mark.parametrize("heavy", HEAVY)
    def test_light_site_inside_the_heavy_atom_with_negative_uiso(self, heavy):
        info = _site_info(heavy, 0.9, -0.001)
        hit = _ripple_check(info)
        assert hit is not None, f"0.9 A from {heavy} must read as a ripple"
        assert hit["neighbour"] == "M1"
        assert hit["neighbour_element"] == heavy
        assert hit["d_A"] == 0.9
        # the fence is the pair's own covalent radii, not a constant
        assert hit["fence_A"] == round(hit["covalent_sum_A"]
                                       - RIPPLE_BOND_SLACK_A, 2)
        assert hit["z_neighbour"] >= RIPPLE_Z_FACTOR * hit["z_site"]
        assert "Uiso" in hit["trigger"]
        assert "ripple" in hit["reading"] and "acknowledge_real" in hit["reading"]

    @pytest.mark.parametrize("heavy", HEAVY)
    def test_same_site_further_out_with_a_normal_uiso_is_not_a_ripple(
            self, heavy):
        # 1.6 A, Uiso 0.03, full occupancy: a short contact worth looking
        # at, but not something the fence may dispose of - it falls
        # through to the ordinary delete/refine logic
        assert _ripple_check(_site_info(heavy, 1.6, 0.03)) is None

    @pytest.mark.parametrize("heavy", HEAVY)
    def test_partial_light_site_close_in_trips_the_electron_leg(self, heavy):
        # a positive, ordinary Uiso but only a sliver of the neighbour's
        # electrons: still the heavy atom's own density
        info = _site_info(heavy, 0.9, 0.03, occ_light=0.1)
        hit = _ripple_check(info)
        assert hit is not None
        assert hit["electron_fraction"] <= RIPPLE_ELECTRON_FRACTION
        assert "electrons" in hit["trigger"]

    def test_light_site_near_another_light_atom_is_never_a_ripple(self):
        # counter-example: O next to C at 0.9 A with a negative Uiso is a
        # broken model, not a ripple - there is no much-heavier neighbour
        info = _site_info("C", 0.9, -0.001, light_el="O")
        assert _ripple_check(info) is None
        # and neither is a light site next to a merely somewhat heavier one
        info = _site_info("Si", 0.9, -0.001, light_el="O")
        assert _ripple_check(info) is None

    @pytest.mark.parametrize("heavy", HEAVY)
    def test_a_real_bond_distance_is_not_a_ripple(self, heavy):
        # at the covalent-radii sum the site is a bonded atom by any
        # reading; only well inside it does the fence fire
        from crystalpilot.chem.connectivity import covalent_radius
        d = covalent_radius(heavy) + covalent_radius("C")
        assert _ripple_check(_site_info(heavy, round(d, 2), -0.001)) is None

    def test_group_is_a_ripple_only_when_every_member_is(self):
        xs = _structure([
            ("ZR1", "Zr", (5.0, 5.0, 5.0), 0.02, 1.0),
            ("C1", "C", (5.9, 5.0, 5.0), -0.001, 1.0),
            ("C2", "C", (12.0, 12.0, 12.0), 0.03, 1.0),
            ("C3", "C", (13.45, 12.0, 12.0), 0.03, 1.0),
        ])
        assert _group_ripple(_atoms_info(xs, ["C1"])) is not None
        assert _group_ripple(_atoms_info(xs, ["C1", "C2"])) is None


# ==========================================================================
class TestRippleVerdict:
    def test_ripple_beats_the_returning_peak(self):
        ripple = {"reading": "0.90 A from ZR1 - a ripple, not an atom"}
        # the numbers that used to say 'real': a big peak comes back and
        # R1 rises. For a ripple that is exactly what is expected.
        v, why = _ghost_verdict(+0.010, 3.2, None, ripple=ripple)
        assert v == "ripple"
        assert "not an atom" in why and "exactly what a ripple does" in why

    def test_without_a_ripple_the_old_criterion_is_untouched(self):
        assert _ghost_verdict(+0.010, 3.2, None, ripple=None)[0] == "real"
        assert _ghost_verdict(-0.001, 0.1, None)[0] == "ghost"

    def test_disposition_and_criterion_state_the_licence(self):
        assert DISPOSITION["ripple"].startswith("delete")
        assert "WITHOUT acknowledge_real" in DISPOSITION["ripple"]
        assert "ripple" in GHOST_CRITERION
        assert "no acknowledge_real" in GHOST_CRITERION


# ==========================================================================
class TestNoDiscriminatingPower:
    def _rows(self, verdicts, informative=False):
        return [{"atoms": f"A{i}", "verdict": v,
                 "r1_fence_informative": informative}
                for i, v in enumerate(verdicts)]

    def test_says_so_when_the_fence_decided_nothing(self):
        note = _fence_note(self._rows(["real", "inconclusive",
                                       "inconclusive"]), 1.8)
        assert note is not None
        assert "NO DISCRIMINATING POWER" in note
        assert "r1_fence_informative=false" in note
        # what CAN discriminate here
        assert "1.8 e/A^3" in note and "probe_site" in note
        assert "free_occupancy" in note
        # no verdict inflation: it hands back the question, it does not
        # promote or demote a single row
        assert "before calling anything real or deleting it" in note
        assert "ghost" in note and "not one came back 'ghost'" in note

    def test_silent_when_a_ghost_came_back(self):
        assert _fence_note(self._rows(["ghost", "inconclusive"]), 1.8) is None

    def test_silent_when_the_fence_could_see(self):
        assert _fence_note(self._rows(["real"], informative=True), 1.8) is None
        assert _fence_note([], 1.8) is None

    def test_silent_when_every_row_failed(self):
        assert _fence_note([{"atoms": "A", "verdict": "inconclusive",
                             "error": "boom",
                             "r1_fence_informative": False}], 1.8) is None


# ==========================================================================
class TestEditAtomsTakesARipple:
    """A 'ripple' ledger entry is not a protection - and a later ripple
    verdict releases an earlier 'real' one on the same site."""

    class _Store:
        def __init__(self, d):
            self.dir = d

        def record(self, *a, **k):
            return None

        def log(self, *a, **k):
            return None

    def _project(self, tmp_path):
        d = tmp_path / "proj"
        (d / ".crystalpilot" / "refine" / "runs" / "r1").mkdir(parents=True)
        return d, d / ".crystalpilot" / "refine" / "runs" / "r1"

    def _ctx(self, store_dir, xs):
        from crystalpilot.core.dataset import ReflectionDataset
        from crystalpilot.pipeline.session import SolveSession
        ses = SolveSession(dataset=ReflectionDataset(
            intensities=None, wavelength=0.71073))
        ses.model = xs
        ses.symmetry = xs.crystal_symmetry()
        return ToolContext(store=self._Store(store_dir), session=ses)

    def _model(self):
        return _structure([("ZR1", "Zr", (5.0, 5.0, 5.0), 0.02, 1.0),
                           ("C9", "C", (5.9, 5.0, 5.0), -0.001, 1.0)])

    def test_ripple_entry_does_not_block_the_delete(self, tmp_path):
        pdir, rundir = self._project(tmp_path)
        xs = self._model()
        ghost_ledger.record(pdir, {
            "labels": ["C9"], "site_frac": [list(xs.scatterers()[1].site)],
            "verdict": "ripple", "reason": "ripple of ZR1"})
        r = EditAtoms().run(self._ctx(rundir, xs), operations=[
            {"action": "delete", "atoms": ["C9"]}])
        assert r.ok, r.error
        assert r.summary["applied"] == [{"action": "delete", "n": 1}]

    def test_a_later_ripple_releases_an_earlier_real(self, tmp_path):
        pdir, rundir = self._project(tmp_path)
        xs = self._model()
        site = [list(xs.scatterers()[1].site)]
        ghost_ledger.record(pdir, {"labels": ["C9"], "site_frac": site,
                                   "verdict": "real", "reason": "peak came back"})
        blocked = EditAtoms().run(self._ctx(rundir, self._model()), operations=[
            {"action": "delete", "atoms": ["C9"]}])
        assert not blocked.ok and "judged REAL" in blocked.error
        ghost_ledger.record(pdir, {"labels": ["C9"], "site_frac": site,
                                   "verdict": "ripple",
                                   "reason": "0.90 A from ZR1"})
        assert ghost_ledger.real_matches(pdir, xs, ["C9"]) == []
        r = EditAtoms().run(self._ctx(rundir, self._model()), operations=[
            {"action": "delete", "atoms": ["C9"]}])
        assert r.ok, r.error
