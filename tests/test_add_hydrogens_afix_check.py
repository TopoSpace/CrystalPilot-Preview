"""add_hydrogens checks SHELXL's AFIX connectivity rule at placement time.

ka1 cage-tools-r1 (2026-09-03): 8 of the arm's 16 tool failures were one
defect. add_hydrogens emitted AFIX groups SHELXL refuses -

    ** BAD AFIX  43  CONNECTIVITY OR PART NUMBERS: CKA BONDS TO CX NF CB Zr3
    ** TERMINATING BECAUSE OF BAD HFIX OR AFIX INSTRUCTIONS **

- and the error surfaced only at the NEXT run_shelxl, naming ONE bad
carrier per run, so the agent sawtoothed through six rounds of
add_hydrogens(exclude=[... one more ...]) -> run_shelxl (the exclude list
grew from [CN] to twelve labels) and finally gave up on hydrogens
altogether. Three ghost_test and three element_scan calls died on the
same baseline.

The rules encoded in io.shelx_writer were MEASURED on
vendor/shelx/shelxl.exe (SHELXL 2019/3), not read off a manual:

  * bonded when d <= r_i + r_j + 0.5 A with SHELXL's OWN SFAC radii
    (C-C bonded at 2.00 A, not at 2.05; C-Zr at 2.80, not at 3.00);
  * per m code, the pivot's bonded-neighbour count it demands;
  * when that count does not fit, SHELXL retries after dropping the
    bonds to elements outside Z 6-10 ("Bond(s) to Fe1 ignored in
    idealizing H-atoms") - which is how a ferrocene Cp CH keeps AFIX 43,
    and why the rule is an atomic-number window and not a metal list.

Everything here is synthetic, and the mismatch cases use two unrelated
heavy elements with two unrelated droppable main-group neighbours.
"""
from __future__ import annotations

import numpy as np
import pytest

cctbx = pytest.importorskip("cctbx")

from cctbx import crystal, xray  # noqa: E402

from crystalpilot.core.dataset import ReflectionDataset  # noqa: E402
from crystalpilot.io.shelx_writer import (  # noqa: E402
    AFIX_NEIGHBOUR_RULE, AFIX_OF_KIND, SHELXL_SFAC_RADII_A, shelxl_bonded,
    shelxl_counts_as_neighbour, shelxl_radius)
from crystalpilot.pipeline.session import SolveSession  # noqa: E402
from crystalpilot.tools.base import ToolContext  # noqa: E402
from crystalpilot.tools.hydrogen_tools import (  # noqa: E402
    AddHydrogens, _afix_mismatch)


class _Store:
    def record(self, *a, **k):
        return None

    def log(self, *a, **k):
        return None


def _session(atoms, cell=(30, 30, 30, 90, 90, 90)):
    cs = crystal.symmetry(unit_cell=cell, space_group_symbol="P 1")
    uc = cs.unit_cell()
    xs = xray.structure(crystal_symmetry=cs)
    for label, el, cart in atoms:
        xs.add_scatterer(xray.scatterer(
            label=label, site=uc.fractionalize(cart), scattering_type=el,
            u=0.03, occupancy=1.0))
    xs.scattering_type_registry(table="it1992")
    ses = SolveSession(dataset=ReflectionDataset(
        intensities=None, wavelength=0.71073))
    ses.model = xs
    ses.symmetry = cs
    return ses


def _run(atoms, **params):
    ses = _session(atoms)
    params.setdefault("elements", ["C"])
    return AddHydrogens().run(ToolContext(store=_Store(), session=ses),
                              **params), ses


def _kinds(r):
    return {p["carrier"]: p["kind"] for p in r.summary["per_carrier"]}


def _rows(r):
    return {d["label"]: d for d in r.summary["decisions"]}


def _nb(j, element, d):
    """One neighbour record in the shape _classify passes around."""
    return {"j": j, "element": element, "d": d}


# ==========================================================================
class TestMeasuredShelxlRules:
    """The rules themselves, as read off the binary."""

    def test_bond_rule_reproduces_the_measured_ladder(self):
        # C-C: bonded at 2.00 A, not at 2.05 (radii sum 1.54 + 0.5)
        assert shelxl_bonded("C", "C", 2.00)
        assert not shelxl_bonded("C", "C", 2.05)
        # C-Zr: bonded at 2.80, not at 3.00 (sum 2.36 + 0.5)
        assert shelxl_bonded("C", "Zr", 2.80)
        assert not shelxl_bonded("C", "Zr", 3.00)

    def test_shelxl_radii_are_shelxls_not_cctbxs(self):
        from crystalpilot.chem.connectivity import covalent_radius
        # light atoms agree, metals do not - and that difference decides
        # whether a long M...C contact counts against an AFIX group
        assert abs(shelxl_radius("C") - covalent_radius("C")) < 0.05
        assert abs(shelxl_radius("O") - covalent_radius("O")) < 0.05
        assert shelxl_radius("Zr") < covalent_radius("Zr") - 0.1
        assert shelxl_radius("Ca") > covalent_radius("Ca") + 0.1
        # unlisted (Z > 96) falls back to cctbx rather than raising
        assert shelxl_radius("Cf") > 0

    def test_droppable_partners_are_a_z_window_not_a_metal_list(self):
        for el in ("C", "N", "O", "F"):
            assert shelxl_counts_as_neighbour(el), el
        # metals AND heavy main-group AND the light metals: all droppable
        for el in ("Li", "Be", "B", "Na", "Mg", "Al", "Si", "P", "S",
                   "Cl", "Ca", "Fe", "Zn", "As", "Se", "Br", "Zr", "Sn",
                   "Sb", "I", "Pb"):
            assert not shelxl_counts_as_neighbour(el), el
        assert not shelxl_counts_as_neighbour("H")

    def test_every_kind_the_writer_emits_has_a_rule(self):
        for kind, afix in AFIX_OF_KIND.items():
            assert afix in AFIX_NEIGHBOUR_RULE, kind
        assert set(SHELXL_SFAC_RADII_A) >= {"H", "C", "N", "O", "Zr"}


# ==========================================================================
class TestAfixMismatchRule:
    """_afix_mismatch against the measured accept/reject table."""

    LABELS = ["P0", "A0", "A1", "A2", "A3"]

    def _check(self, kind, nbs):
        return _afix_mismatch(kind, "P0", "C", nbs, self.LABELS)

    @pytest.mark.parametrize("kind,ok_n", [
        ("aromatic_CH", 2), ("CH2", 2), ("tertiary_CH", 3),
        ("linear_CH", 1), ("CH3", 1), ("vinyl_CH2", 1)])
    def test_the_right_count_passes(self, kind, ok_n):
        nbs = [_nb(k + 1, "C", 1.45) for k in range(ok_n)]
        assert self._check(kind, nbs) is None

    @pytest.mark.parametrize("kind,bad_ns", [
        ("aromatic_CH", (0, 1, 3, 4)), ("CH2", (0, 1, 3, 4)),
        ("tertiary_CH", (0, 1, 2, 4)), ("linear_CH", (0, 2, 3)),
        # 33/137 and 93 tolerate extra bonds: only "no atoms" is fatal
        ("CH3", (0,)), ("vinyl_CH2", (0,))])
    def test_the_wrong_count_is_a_mismatch(self, kind, bad_ns):
        for n in bad_ns:
            m = self._check(kind, [_nb(k + 1, "C", 1.45) for k in range(n)])
            assert m is not None, (kind, n)
            assert m["problem"] == "count"
            assert m["afix"] == AFIX_OF_KIND[kind]
            assert m["n_bonded"] == n

    @pytest.mark.parametrize("kind,extra_n", [("CH3", (2, 3)),
                                              ("vinyl_CH2", (2, 3))])
    def test_extra_bonds_are_tolerated_where_shelxl_tolerates_them(
            self, kind, extra_n):
        for n in extra_n:
            assert self._check(
                kind, [_nb(k + 1, "C", 1.45) for k in range(n)]) is None

    @pytest.mark.parametrize("heavy,d", [("Zr", 2.30), ("Fe", 2.05)])
    def test_a_droppable_neighbour_is_dropped_to_make_the_count_fit(
            self, heavy, d):
        # the ferrocene case: 2 ring C + a metal, AFIX 43 needs 2
        nbs = [_nb(1, "C", 1.42), _nb(2, "C", 1.42), _nb(3, heavy, d)]
        assert self._check("aromatic_CH", nbs) is None

    @pytest.mark.parametrize("heavy,d", [("Zr", 2.30), ("Pb", 2.40)])
    def test_a_droppable_neighbour_is_kept_when_the_full_count_fits(
            self, heavy, d):
        # P-CH2-N and M-CH2-C both pass AFIX 23 untouched: full count 2
        assert self._check("CH2", [_nb(1, "N", 1.47),
                                   _nb(2, "P", 1.85)]) is None
        assert self._check("CH2", [_nb(1, "C", 1.52),
                                   _nb(2, heavy, d)]) is None

    @pytest.mark.parametrize("heavy,light", [("Zr", "S"), ("Pb", "Cl")])
    def test_only_as_many_bonds_are_dropped_as_are_needed(self, heavy, light):
        # measured: a C bonded to C + S + Zr keeps AFIX 43 - SHELXL drops
        # the metal and KEEPS the sulfur, landing on 2. An all-or-nothing
        # reading (3 or 1, neither of them 2) would refuse it wrongly.
        nbs = [_nb(1, "C", 1.40), _nb(2, light, 1.75), _nb(3, heavy, 2.70)]
        assert self._check("aromatic_CH", nbs) is None

    @pytest.mark.parametrize("light", ["S", "Cl"])
    def test_too_many_light_neighbours_cannot_be_dropped_away(self, light):
        # three C/N/O/F neighbours and an AFIX 43 group: those bonds are
        # not droppable at any price, so SHELXL refuses however many
        # heavy contacts are around
        nbs = [_nb(1, "C", 1.40), _nb(2, "C", 1.42), _nb(3, "N", 1.45),
               _nb(4, light, 1.75)]
        m = self._check("aromatic_CH", nbs)
        assert m is not None and m["problem"] == "count"
        assert m["n_bonded"] == 4 and m["n_after_dropping_heavy"] == 3
        assert any(light in s for s in m["droppable"])

    def test_a_contact_outside_shelxls_bond_sphere_is_not_a_neighbour(self):
        # the round-5 P-CH2-N next to a La at 3.22 A: cctbx radii put that
        # inside the bond sphere, SHELXL's do not, and the group is fine
        nbs = [_nb(1, "N", 1.47), _nb(2, "P", 1.88), _nb(3, "La", 3.22)]
        assert self._check("CH2", nbs) is None

    def test_the_plane_of_an_afix_93_group_needs_a_substituent(self):
        nbs = [_nb(1, "C", 1.34)]
        assert _afix_mismatch("vinyl_CH2", "P0", "C", nbs, self.LABELS,
                              lambda nb: "C7") is None
        m = _afix_mismatch("vinyl_CH2", "P0", "C", nbs, self.LABELS,
                           lambda nb: None)
        assert m is not None and m["problem"] == "substituent"


# ==========================================================================
def _donor_fragment(x0, metal, donor, d):
    """Cl-M-X: a metal donor at distance `d`, plus a chloride so the
    metal is not a bare atom. Whether X counts as bonded at all depends
    on which side is asked - this project's M-X coordination window
    (chem.knowledge, through the metal-bonded audit) reaches further than
    SHELXL's bond sphere for the late transition metals, and an atom
    "BONDED TO NO ATOMS" is the ka1 cage lane's most frequent BAD AFIX."""
    tag = metal.upper()[:2]
    m = np.array([x0, 15.0, 15.0])
    return [(f"M{tag}", metal, tuple(m)),
            (f"L{tag}", "Cl", tuple(m - 2.2 * np.array([0.0, 1.0, 0.0]))),
            (f"{donor}{tag}", donor,
             tuple(m + d * np.array([0.0, 1.0, 0.0])))]


def _organic(x0):
    """A three-carbon chain: ordinary carriers that must keep their H."""
    return [("C1", "C", (x0, 5.0, 5.0)),
            ("C2", "C", (x0 + 1.20, 5.90, 5.0)),
            ("C3", "C", (x0 + 2.40, 5.00, 5.0))]


class TestAddHydrogensReportsThemAllAtOnce:
    @pytest.mark.parametrize("metal,donor,kind,d_out,d_in", [
        ("Ta", "O", "OH", 2.62, 2.20), ("Cu", "N", "NH2_planar", 2.50, 2.00)])
    def test_a_donor_outside_shelxls_sphere_is_skipped(
            self, metal, donor, kind, d_out, d_in):
        tag, label = metal.upper()[:2], donor + metal.upper()[:2]
        r, ses = _run(_donor_fragment(6.0, metal, donor, d_out)
                      + _organic(20.0), elements=["C"],
                      force_kind={label: kind})
        assert r.ok, r.error
        mm = r.summary["afix_connectivity_mismatches"]
        assert [m["atom"] for m in mm] == [label]
        assert mm[0]["problem"] == "count" and mm[0]["n_bonded"] == 0
        row = _rows(r)[label]
        assert row["decision"] == "skipped"
        assert "afix_connectivity_mismatch" in row["reason"]
        # the ordinary carbons are protonated exactly as before
        assert set(_kinds(r)) == {"C1", "C2", "C3"}
        assert any("SHELXL" in n and "AFIX" in n for n in r.summary["notes"])

    @pytest.mark.parametrize("metal,donor,kind,d_out,d_in", [
        ("Ta", "O", "OH", 2.62, 2.20), ("Cu", "N", "NH2_planar", 2.50, 2.00)])
    def test_the_same_donor_inside_the_sphere_keeps_its_hydrogen(
            self, metal, donor, kind, d_out, d_in):
        label = donor + metal.upper()[:2]
        r, ses = _run(_donor_fragment(6.0, metal, donor, d_in),
                      elements=["C"], force_kind={label: kind})
        assert r.ok, r.error
        assert "afix_connectivity_mismatches" not in r.summary
        assert _kinds(r) == {label: kind}

    def test_every_offender_is_reported_in_one_call(self, monkeypatch):
        # the rule itself is measured above; this is the contract that
        # made the ka1 lane sawtooth - when it fires it must fire for ALL
        # of them at once, never one carrier per run
        import crystalpilot.tools.hydrogen_tools as HT
        real = HT._afix_mismatch

        def fake(kind, label, el, nbs, labels, substituent_of=None):
            if label in ("C1", "C3"):
                return {"atom": label, "afix": AFIX_OF_KIND[kind],
                        "kind": kind, "expected": "exactly 1",
                        "n_bonded": 0, "n_after_dropping_heavy": 0,
                        "bonded": [], "droppable": [], "problem": "count"}
            return real(kind, label, el, nbs, labels, substituent_of)

        monkeypatch.setattr(HT, "_afix_mismatch", fake)
        r, ses = _run(_organic(5.0), elements=["C"])
        assert r.ok, r.error
        assert {m["atom"] for m in r.summary["afix_connectivity_mismatches"]} \
            == {"C1", "C3"}
        assert set(_kinds(r)) == {"C2"}
        for bad in ("C1", "C3"):
            assert _rows(r)[bad]["decision"] == "skipped"
            assert "afix_connectivity_mismatch" in _rows(r)[bad]["reason"]

    def test_a_correct_molecule_is_untouched(self):
        # C1-C2-C3 chain with a terminal methyl and a hydroxyl: the
        # classic fixture, no mismatch anywhere
        atoms = [("C1", "C", (3.80, 5.90, 5.0)),
                 ("C2", "C", (5.00, 5.00, 5.0)),
                 ("C3", "C", (6.20, 5.90, 5.0)),
                 ("C4", "C", (3.00, 4.60, 5.0)),
                 ("O1", "O", (7.00, 4.70, 5.0))]
        r, ses = _run(atoms, elements=["C"], force_kind={"O1": "OH"})
        assert r.ok, r.error
        assert "afix_connectivity_mismatches" not in r.summary
        assert _kinds(r) == {"C1": "CH2", "C2": "CH2", "C3": "CH2",
                             "C4": "CH3", "O1": "OH"}

    def test_ferrocene_cp_carbons_keep_their_hydrogen(self):
        # SHELXL drops the Fe bond to make AFIX 43 fit; so must this check
        atoms = [("FE1", "Fe", (10.0, 10.0, 11.66))]
        for k in range(5):
            a = 2 * np.pi * k / 5
            atoms.append((f"C{k + 1}", "C",
                          (10.0 + 1.21 * np.cos(a), 10.0 + 1.21 * np.sin(a),
                           10.0)))
        r, ses = _run(atoms, elements=["C"])
        assert r.ok, r.error
        assert "afix_connectivity_mismatches" not in r.summary
        assert len(_kinds(r)) == 5


# ==========================================================================
class TestStaleAfixIsCaughtBeforeShelxlRuns:
    """run_shelxl replays h_riding_meta verbatim, so a model that changed
    after add_hydrogens can carry AFIX groups SHELXL refuses - and SHELXL
    then aborts the whole job. That is where the ka1 cage lane's eight
    failures came from, and it is checked before the .ins is written."""

    def _ring(self):
        atoms = []
        for k in range(6):
            a = 2 * np.pi * k / 6
            atoms.append((f"C{k + 1}", "C",
                          (15.0 + 1.39 * np.cos(a), 15.0 + 1.39 * np.sin(a),
                           15.0)))
        return atoms

    def test_an_atom_added_next_to_a_carrier_invalidates_its_group(self):
        from crystalpilot.io.shelx_writer import afix_connectivity_problems
        from crystalpilot.refine.tools_shelxl import _stale_afix_message
        r, ses = _run(self._ring(), elements=["C"])
        assert r.ok, r.error
        meta = ses.flags["h_riding_meta"]["per_carrier"]
        assert len(meta) == 6
        # nothing wrong yet
        assert afix_connectivity_problems(ses.model, meta) == []
        # fourier_complete-style: two new carbons land on two ring atoms,
        # which now have three C neighbours each - AFIX 43 wants two, and
        # a carbon bond is not one SHELXL is allowed to drop
        uc = ses.model.unit_cell()
        for k, (lbl, base) in enumerate((("C97", 0), ("C98", 3))):
            a = 2 * np.pi * base / 6
            ses.model.add_scatterer(xray.scatterer(
                label=lbl, scattering_type="C", u=0.03,
                site=uc.fractionalize(
                    (15.0 + 2.79 * np.cos(a), 15.0 + 2.79 * np.sin(a), 15.0))))
        bad = afix_connectivity_problems(ses.model, meta)
        assert {b["atom"] for b in bad} == {"C1", "C4"}
        for b in bad:
            assert b["afix"] == 43 and b["expected"] == "exactly 2"
            assert b["n_bonded"] == 3 and b["droppable"] == []
        # one message names every offender and points at the one fix
        msg = _stale_afix_message(bad)
        assert "C1" in msg and "C4" in msg
        assert "2 riding-H group(s)" in msg
        assert "TERMINATING BECAUSE OF BAD HFIX OR AFIX" in msg
        assert "Re-run add_hydrogens" in msg
        assert "exclude=" in msg

    def test_a_droppable_neighbour_appearing_is_not_a_problem(self):
        # the same experiment with a metal instead of a carbon: SHELXL
        # drops that bond and keeps the group, so neither may this
        from crystalpilot.io.shelx_writer import afix_connectivity_problems
        r, ses = _run(self._ring(), elements=["C"])
        meta = ses.flags["h_riding_meta"]["per_carrier"]
        uc = ses.model.unit_cell()
        ses.model.add_scatterer(xray.scatterer(
            label="ZR1", scattering_type="Zr", u=0.03,
            site=uc.fractionalize((15.0 + 1.39, 15.0, 17.3))))
        assert afix_connectivity_problems(ses.model, meta) == []


# ==========================================================================
class TestWarningsMatchWhatHappened:
    """ka1 hex readout section 7 defect 2: warnings claimed six O were
    protonated while `skipped` listed the same six, and one message
    carried a stray brace."""

    def _metal_oxo(self):
        # a bare Zr with six terminal O: every one of them is a
        # metal-coordinated donor the riding geometry cannot settle
        atoms = [("ZR1", "Zr", (10.0, 10.0, 10.0))]
        for k, v in enumerate([(1, 0, 0), (-1, 0, 0), (0, 1, 0),
                               (0, -1, 0), (0, 0, 1), (0, 0, -1)]):
            atoms.append((f"O{k + 1}", "O",
                          (10.0 + 2.15 * v[0], 10.0 + 2.15 * v[1],
                           10.0 + 2.15 * v[2])))
        return atoms

    @pytest.mark.parametrize("include_metal", [False, True])
    def test_no_warning_names_a_carrier_that_was_skipped(self, include_metal):
        r, ses = _run(self._metal_oxo(), elements=["O"],
                      include_metal_bonded=include_metal)
        assert r.ok, r.error
        skipped = {s["atom"] for s in r.summary["skipped"]}
        assert skipped >= {f"O{k}" for k in range(1, 7)}
        protonated = set(_kinds(r))
        for w in r.summary["warnings"]:
            named = {lbl for lbl in skipped if w.startswith(lbl + ":")}
            assert not named, f"warning about a skipped carrier: {w}"
        assert protonated.isdisjoint(skipped)

    @pytest.mark.parametrize("include_metal", [False, True])
    def test_the_skipped_donors_get_one_informational_line(self,
                                                           include_metal):
        r, ses = _run(self._metal_oxo(), elements=["O"],
                      include_metal_bonded=include_metal)
        notes = r.summary["notes"]
        line = next(n for n in notes if "metal-coordinated" in n)
        assert "6 metal-coordinated N/O carrier(s)" in line
        assert "force_kind" in line and "difference map" in line
        if include_metal:
            assert "include_metal_bonded does not settle it" in line

    def test_no_message_carries_a_stray_brace(self):
        r, ses = _run(self._metal_oxo(), elements=["O"])
        texts = ([s["reason"] for s in r.summary["skipped"]]
                 + list(r.summary["warnings"]) + list(r.summary["notes"])
                 + [d.get("reason") or "" for d in r.summary["decisions"]])
        for t in texts:
            assert "}}" not in t and "{{" not in t, t
            assert t.count("{") == t.count("}"), t
        # the force_kind hint is still there, spelled correctly
        assert any("{'O1': 'OH'}" in t for t in texts)
