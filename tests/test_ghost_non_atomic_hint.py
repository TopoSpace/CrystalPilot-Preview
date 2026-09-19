"""ghost_test's real_kind hint: a 'real' verdict is not an atom licence.

ka1 cage (2026-09): every 'real' row was read as "an atom belongs here".
But the delete-and-refine test answers "is this density genuine?", never
"is this density an atom?" - and density that is real in the Fourier
sense can be an average no atom label represents: an average over
stacking faults / layer offsets, the satellites of a modulated or
superstructure integrated into the Bragg data, or diffuse scattering
folded into it. All three give back a peak at the vacated site and all
three raise R1 when removed. Naming them produced the lane's anonymous
atoms and its forced-deletion loops.

Every fence tested here is read against the MODEL's own scale (its
framework median Ueq / median electron count) or against the pair's own
covalent radii, so nothing is tuned to a crystal, an element or a
structure class - the counter-examples below (a floppy framework, a real
aliphatic chain, a general position, a partially occupied site) are as
much the point as the cases that fire. All structures are synthetic.
"""
from __future__ import annotations

import re

import pytest

cctbx = pytest.importorskip("cctbx")

from cctbx import crystal, xray  # noqa: E402

from crystalpilot.refine import ghost_ledger  # noqa: E402
from crystalpilot.refine.tools_batch import (  # noqa: E402
    CHAIN_SPACING_TOL, DISPOSITION, GHOST_PEAK_NONE, NON_ATOMIC_NOTE,
    OFF_SITE_FRACTION, REAL_KIND_CRITERION, SMEAR_FULL_OCC, SMEAR_UEQ_FACTOR,
    SMEAR_UEQ_MIN_A2, SUB_ATOMIC_E_FRACTION, _atoms_info, _attach_real_kind,
    _ghost_verdict, _model_non_atomic_signals, _real_kind)
from test_batch_tests import _open, make_project  # noqa: E402

CELL = (20.0, 20.0, 20.0, 90.0, 90.0, 90.0)
#: a peak that came back nicely centred on the vacated site
CENTRED = [{"max": 1.8, "min": -0.3, "at_site": 1.7}]


def _structure(atoms, sg="P 1", cell=CELL, fractional=False):
    """atoms: (label, element, xyz, u_iso, occupancy); xyz cartesian
    unless fractional=True."""
    cs = crystal.symmetry(unit_cell=cell, space_group_symbol=sg)
    uc = cs.unit_cell()
    xs = xray.structure(crystal_symmetry=cs)
    for lbl, el, xyz, u, occ in atoms:
        xs.add_scatterer(xray.scatterer(
            label=lbl, site=(xyz if fractional else uc.fractionalize(xyz)),
            scattering_type=el, u=u, occupancy=occ))
    xs.scattering_type_registry(table="it1992")
    return xs


def _framework(n=8, u=0.03, element="C", start=2.0, step=1.5):
    """A row of ordinary bonded framework atoms - the model's own scale."""
    return [(f"{element}{i}", element, (start + step * i, 2.0, 2.0), u, 1.0)
            for i in range(n)]


def _kind(xs, labels, residuals=CENTRED):
    return _real_kind(_model_non_atomic_signals(xs, _atoms_info(xs, labels)),
                      residuals)


def _fired(kind) -> dict[str, dict]:
    return {i["indicator"]: i for i in kind["non_atomic_indicators"]}


def _unavailable(kind) -> set[str]:
    return {u["indicator"] for u in kind["non_atomic_checks_unavailable"]}


# ==========================================================================
class TestOrdinaryRealAtom:
    """The common case must stay quiet: a bonded guest atom with an
    ordinary ADP is atom_like and carries no indicator at all."""

    def test_a_bonded_guest_atom_is_atom_like(self):
        xs = _structure(_framework() + [("O1G", "O", (2.0, 3.3, 2.0),
                                         0.05, 1.0)])
        kind = _kind(xs, ["O1G"])
        assert kind["real_kind_hint"] == "atom_like"
        assert kind["non_atomic_indicators"] == []
        assert "non_atomic_note" not in kind

    def test_peak_shape_is_reported_unmeasured_never_assumed_absent(self):
        xs = _structure(_framework() + [("O1G", "O", (2.0, 3.3, 2.0),
                                         0.05, 1.0)])
        kind = _kind(xs, ["O1G"])
        why = [u["why"] for u in kind["non_atomic_checks_unavailable"]
               if u["indicator"] == "peak_shape"][0]
        assert "cannot be measured" in why and "not absent" in why
        assert "inspect_map" in why


# ==========================================================================
class TestSmearedSite:
    """Density spread over positions: a full-occupancy site whose ADP is
    far above the framework's. The fence is the model's OWN median, so a
    floppy structure is judged on its own scale."""

    @pytest.mark.parametrize("element,u_frame,u_site",
                             [("O", 0.03, 0.32), ("Cl", 0.08, 0.30)])
    def test_high_uiso_at_full_occupancy_fires(self, element, u_frame, u_site):
        xs = _structure(_framework(u=u_frame)
                        + [("X9", element, (2.0, 3.3, 2.0), u_site, 1.0)])
        kind = _kind(xs, ["X9"])
        assert kind["real_kind_hint"] == "possibly_non_atomic"
        hit = _fired(kind)["smeared_adp"]
        assert hit["weight"] == "primary"
        assert hit["ueq"] == pytest.approx(u_site, abs=1e-3)
        assert hit["framework_median_ueq"] == pytest.approx(u_frame, abs=1e-3)
        assert hit["ratio_to_framework"] >= SMEAR_UEQ_FACTOR
        # the numbers and the rule travel with the indicator
        assert f"{SMEAR_UEQ_FACTOR:g}x" in hit["criterion"]
        assert str(SMEAR_UEQ_MIN_A2) in hit["criterion"]
        assert "spread over positions" in hit["reading"]

    def test_the_fence_is_the_models_own_scale_not_a_fixed_u(self):
        # 0.20 A^2 is a large ADP in absolute terms and above the floor,
        # but only 2.5x the median of THIS (floppy) framework: no fire
        xs = _structure(_framework(u=0.08)
                        + [("O9", "O", (2.0, 3.3, 2.0), 0.20, 1.0)])
        assert _kind(xs, ["O9"])["non_atomic_indicators"] == []
        # ...and a small ratio on a very tight framework is not enough
        # either while the ADP itself stays below the floor
        xs = _structure(_framework(u=0.01)
                        + [("O9", "O", (2.0, 3.3, 2.0), 0.10, 1.0)])
        assert _kind(xs, ["O9"])["non_atomic_indicators"] == []

    def test_partial_occupancy_is_the_ordinary_occupancy_adp_correlation(self):
        xs = _structure(_framework()
                        + [("O9", "O", (2.0, 3.3, 2.0), 0.32, 0.5)])
        kind = _kind(xs, ["O9"])
        assert "smeared_adp" not in _fired(kind)
        assert SMEAR_FULL_OCC == 0.98


# ==========================================================================
class TestRegularSubAtomicChain:
    """A row or sheet of weak, evenly spaced maxima is what a continuous
    ridge looks like once a peak search samples it."""

    def _chain(self, spacing, occ=0.25, n=5, element="C"):
        return [(f"Q{i}", element, (2.0 + spacing * i, 9.0, 9.0), 0.06, occ)
                for i in range(n)]

    @pytest.mark.parametrize("spacing", [1.0, 3.2])
    def test_regular_sub_atomic_spacing_outside_the_bond_window_fires(
            self, spacing):
        chain = self._chain(spacing)
        xs = _structure(_framework() + chain)
        kind = _kind(xs, [c[0] for c in chain])
        assert kind["real_kind_hint"] == "possibly_non_atomic"
        hit = _fired(kind)["regular_sub_atomic_chain"]
        assert hit["weight"] == "primary"
        assert hit["n_members"] == 5
        assert hit["spacing_A"] == pytest.approx(spacing, abs=0.02)
        assert hit["spacing_spread"] <= CHAIN_SPACING_TOL
        lo, hi = hit["bond_window_A"]
        assert spacing < lo or spacing > hi
        assert max(hit["electrons_per_site"]) <= (
            SUB_ATOMIC_E_FRACTION * hit["framework_median_electrons"])

    def test_a_real_aliphatic_chain_is_regular_too_and_must_not_fire(self):
        # bonded C-C at 1.53 A, full occupancy: inside the bond window and
        # not sub-atomic - the counter-example that keeps the rule generic
        chain = self._chain(1.53, occ=1.0)
        xs = _structure(_framework() + chain)
        kind = _kind(xs, [c[0] for c in chain])
        assert "regular_sub_atomic_chain" not in _fired(kind)
        assert kind["real_kind_hint"] == "atom_like"

    def test_an_irregular_cluster_of_weak_peaks_does_not_fire(self):
        sites = [0.0, 1.0, 2.4, 4.3, 5.4]
        atoms = [(f"Q{i}", "C", (2.0 + x, 9.0, 9.0), 0.06, 0.25)
                 for i, x in enumerate(sites)]
        xs = _structure(_framework() + atoms)
        kind = _kind(xs, [a[0] for a in atoms])
        assert "regular_sub_atomic_chain" not in _fired(kind)

    def test_two_candidates_are_not_a_chain(self):
        chain = self._chain(1.0, n=2)
        xs = _structure(_framework() + chain)
        kind = _kind(xs, [c[0] for c in chain])
        assert "regular_sub_atomic_chain" not in _fired(kind)


# ==========================================================================
class TestSymmetryImageOverlap:
    """A site whose own symmetry image sits closer than any bond between
    two such atoms. Read with cctbx's site-symmetry machinery, and the
    element's own covalent radius is the fence."""

    def _near_element(self, sg, site):
        atoms = [(f"C{i}", "C", (6.0 + 1.5 * i, 6.0, 6.0), 0.03, 1.0)
                 for i in range(4)]
        xs = _structure(atoms, sg=sg)
        uc = xs.unit_cell()
        xs.add_scatterer(xray.scatterer(label="C0X", site=site,
                                        scattering_type="C", u=0.04,
                                        occupancy=1.0))
        # a bonded partner, so isolation is not what fires
        xs.add_scatterer(xray.scatterer(
            label="C0Y", site=uc.fractionalize(
                tuple(c + d for c, d in zip(uc.orthogonalize(site),
                                            (1.5, 0.2, 0.0)))),
            scattering_type="C", u=0.04, occupancy=1.0))
        xs.scattering_type_registry(table="it1992")
        return xs

    @pytest.mark.parametrize("sg,site", [("P -1", (0.02, 0.0, 0.0)),
                                         ("P 2", (0.02, 0.30, 0.0))])
    def test_a_site_just_off_a_symmetry_element_fires(self, sg, site):
        xs = self._near_element(sg, site)
        kind = _kind(xs, ["C0X"])
        assert kind["real_kind_hint"] == "possibly_non_atomic"
        hit = _fired(kind)["symmetry_image_overlap"]
        assert hit["weight"] == "primary"
        assert hit["image_distance_A"] == pytest.approx(0.8, abs=0.05)
        # the fence is the element's own covalent radius, not a constant
        assert hit["fence_A"] == pytest.approx(1.52, abs=0.05)
        # cctbx's own reading of the site comes with it
        assert hit["site_symmetry_ops"] == 2
        assert hit["distance_to_special_position_A"] == pytest.approx(
            0.4, abs=0.05)
        assert "symmetry element" in hit["reading"]

    def test_a_general_position_far_from_any_element_does_not_fire(self):
        xs = self._near_element("P -1", (0.30, 0.20, 0.15))
        assert "symmetry_image_overlap" not in _fired(_kind(xs, ["C0X"]))

    def test_p1_has_no_images_and_the_check_is_silent(self):
        xs = self._near_element("P 1", (0.02, 0.0, 0.0))
        kind = _kind(xs, ["C0X"])
        assert "symmetry_image_overlap" not in _fired(kind)
        # not applicable is not the same as unmeasurable
        assert "symmetry_image_overlap" not in _unavailable(kind)


# ==========================================================================
class TestSupportingIndicatorsNeedASecond:
    """An ordinary lattice solvent is isolated, and a slightly misplaced
    atom leaves its density off-centre: neither may raise the flag alone."""

    def _lone_site(self):
        return _structure(_framework() + [("O5", "O", (2.0, 12.0, 12.0),
                                           0.05, 1.0)])

    def test_isolation_alone_is_reported_but_does_not_flag(self):
        kind = _kind(self._lone_site(), ["O5"])
        hit = _fired(kind)["isolated_density"]
        assert hit["weight"] == "supporting"
        assert hit["neighbour_search_radius_A"] == 2.8
        assert "raises the flag only together with a second" in hit["reading"]
        assert kind["real_kind_hint"] == "atom_like"

    def test_two_supporting_indicators_flag(self):
        kind = _kind(self._lone_site(), ["O5"],
                     residuals=[{"max": 2.0, "min": -0.2, "at_site": 0.4}])
        fired = _fired(kind)
        assert set(fired) == {"isolated_density", "returning_density_off_site"}
        off = fired["returning_density_off_site"]
        assert off["ratio"] < OFF_SITE_FRACTION
        assert off["peak_in_sphere"] == 2.0 and off["value_at_site"] == 0.4
        assert kind["real_kind_hint"] == "possibly_non_atomic"

    def test_a_bonded_site_is_never_isolated(self):
        xs = _structure(_framework() + [("O1G", "O", (2.0, 3.3, 2.0),
                                         0.05, 1.0)])
        assert "isolated_density" not in _fired(_kind(xs, ["O1G"]))

    def test_off_site_is_unmeasurable_when_nothing_came_back(self):
        for residuals in ([], [{"max": GHOST_PEAK_NONE - 0.1, "min": -0.1,
                                "at_site": 0.0}]):
            kind = _kind(self._lone_site(), ["O5"], residuals=residuals)
            assert "returning_density_off_site" in _unavailable(kind)
            assert "returning_density_off_site" not in _fired(kind)


# ==========================================================================
class TestTheHintNeverTouchesTheVerdict:
    def _signals(self):
        xs = _structure(_framework() + [("O9", "O", (2.0, 3.3, 2.0),
                                         0.32, 1.0)])
        return _model_non_atomic_signals(xs, _atoms_info(xs, ["O9"]))

    def _row(self, verdict):
        return {"atoms": "O9", "verdict": verdict, "reason": "as measured",
                "disposition": DISPOSITION[verdict]}

    def test_every_real_row_carries_the_hint(self):
        xs = _structure(_framework() + [("O1G", "O", (2.0, 3.3, 2.0),
                                         0.05, 1.0)])
        clean = _model_non_atomic_signals(xs, _atoms_info(xs, ["O1G"]))
        row = self._row("real")
        _attach_real_kind(row, clean, CENTRED)
        assert row["real_kind_hint"] == "atom_like"
        assert row["non_atomic_indicators"] == []
        assert row["verdict"] == "real" and row["reason"] == "as measured"
        assert row["disposition"] == DISPOSITION["real"]

    def test_an_inconclusive_row_with_the_same_indicators_carries_it_too(self):
        row = self._row("inconclusive")
        _attach_real_kind(row, self._signals(), CENTRED)
        assert row["real_kind_hint"] == "possibly_non_atomic"
        assert "smeared_adp" in {i["indicator"]
                                 for i in row["non_atomic_indicators"]}
        assert "non_atomic_note" in row
        # the verdict, its reason and its disposition are untouched
        assert row["verdict"] == "inconclusive"
        assert row["reason"] == "as measured"
        assert row["disposition"] == DISPOSITION["inconclusive"]

    def test_a_clean_inconclusive_row_stays_as_it_was(self):
        xs = _structure(_framework() + [("O1G", "O", (2.0, 3.3, 2.0),
                                         0.05, 1.0)])
        row = self._row("inconclusive")
        before = dict(row)
        _attach_real_kind(row, _model_non_atomic_signals(
            xs, _atoms_info(xs, ["O1G"])), CENTRED)
        assert row == before

    @pytest.mark.parametrize("verdict", ["ghost", "ripple"])
    def test_ghost_and_ripple_rows_are_never_annotated(self, verdict):
        row = self._row(verdict)
        before = dict(row)
        _attach_real_kind(row, self._signals(), CENTRED)
        assert row == before

    def test_the_verdict_function_knows_nothing_about_the_hint(self):
        # same numbers, same verdicts as before T1.7b
        assert _ghost_verdict(+0.010, 3.2, None)[0] == "real"
        assert _ghost_verdict(-0.001, 0.1, None)[0] == "ghost"
        assert _ghost_verdict(+0.0005, 2.5, None)[0] == "inconclusive"


# ==========================================================================
class TestDispositionAndCriterion:
    def test_real_disposition_says_genuine_is_not_an_atom(self):
        real = DISPOSITION["real"]
        assert real.startswith("keep")
        assert "acknowledge_real" in real and "free occupancy" in real
        assert ("real means the density is genuine, not that it is an atom"
                in real)
        assert "if `real_kind_hint` is possibly_non_atomic, do not label it"\
            in real
        assert "check the data-side indicators first" in real

    def test_the_combination_rule_is_disclosed(self):
        assert "atom_like" in REAL_KIND_CRITERION
        assert "possibly_non_atomic" in REAL_KIND_CRITERION
        assert "PRIMARY" in REAL_KIND_CRITERION
        assert "two SUPPORTING" in REAL_KIND_CRITERION
        assert "never changes it" in REAL_KIND_CRITERION
        assert "non_atomic_checks_unavailable" in REAL_KIND_CRITERION

    def test_the_note_names_the_physical_origins_and_the_data_checks(self):
        for origin in ("stacking fault", "layer offset", "modulated",
                       "superstructure", "satellites", "diffuse scattering"):
            assert origin in NON_ATOMIC_NOTE, origin
        for tool in ("reflection_statistics", "audit_reflection_data",
                     "check_symmetry", "inspect_map"):
            assert tool in NON_ATOMIC_NOTE, tool


# ==========================================================================
class TestOnTheLiveTool:
    """One real ghost_test call on the synthetic five-atom P-1 project of
    test_batch_tests: the verdicts must be exactly what they were, the
    hint must ride along, and the note may not name a tool that does not
    exist."""

    @pytest.fixture()
    def project(self, tmp_path):
        from test_batch_tests import GHOST, TRUE_ATOMS
        return _open(make_project(tmp_path, TRUE_ATOMS + [GHOST]))

    def test_the_real_row_and_the_ledger_carry_the_hint(self, project):
        p = project
        r = p.invoke_tool("ghost_test", {"atoms": ["C1", "C9G"], "cycles": 2})
        assert r.ok, r.error
        s = r.summary
        # verdicts unchanged by T1.7b
        assert s["verdicts"] == {"C1": "real", "C9G": "ghost"}
        rows = {row["atoms"]: row for row in s["rows"]}
        c1, ghost = rows["C1"], rows["C9G"]
        # a bonded, ordinary-ADP framework atom reads as an atom
        assert c1["real_kind_hint"] == "atom_like"
        assert c1["non_atomic_indicators"] == []
        assert "peak_shape" in {u["indicator"]
                                for u in c1["non_atomic_checks_unavailable"]}
        assert "real_kind_criterion" in s and "real_kind_note" not in s
        # a ghost row is a deletion licence and gets no hint at all
        assert "real_kind_hint" not in ghost
        # the hint outlives the call, like the verdict
        entry = [e for e in ghost_ledger.load(p.dir)
                 if e["verdict"] == "real"][0]
        assert entry["real_kind_hint"] == "atom_like"

    def test_the_note_names_only_registered_tools(self, project):
        named = set(re.findall(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b",
                               NON_ATOMIC_NOTE))
        assert {"reflection_statistics", "audit_reflection_data",
                "check_symmetry", "inspect_map"} <= named
        assert named <= set(project.registry.names()), (
            named - set(project.registry.names()))
