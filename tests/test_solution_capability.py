"""solution_capability: what the physics says before a solver is asked.

The four entry points into structure solution (run_shelxt,
create_start_model, solve_charge_flipping, solve_superflip) all return
this block, on success, on failure and on a refusal alike. It exists for
one reason: in the coarse-data light-atom regime this platform has NO
measured success record, so a failure there says nothing about the
structure - and an agent that cannot tell that regime apart reads its own
failure as evidence and starts changing the space group or the formula.

Nothing in the block gates anything. The tier is graded from d_min and
the heaviest declared Z only, on two plain atomic-number lines (Si Z 14 -
the light-atom regime; Ca Z 20 - a scatterer that can carry phases on its
own), so it holds for elements no test here mentions.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from crystalpilot.chem import solvability as sv
from crystalpilot.tools import solution_tools as st
from crystalpilot.tools.base import ToolContext, ToolResult

from test_interpret_peaks_organic import (_Store, _dbu_hcl_like,
                                          _solved_session, _thiophene_like)

WARNING_WORDS = ("harder", "no_record", "no measured success", "NO measured",
                 "not evidence", "unsolvable", "inconclusive", "no record")


def _block(d_min, z, el="X", completeness=0.98):
    return sv.capability_block(
        d_min=d_min, d_min_source="unit test", heaviest_element=el,
        z_heaviest=z, heaviest_source="unit test",
        completeness=completeness, completeness_source="unit test")


# --------------------------------------------------------------------- #
# 1. the tier ladder, element-generic
# --------------------------------------------------------------------- #

class TestTierGrading:
    def test_atomic_resolution_is_routine_for_any_composition(self):
        for z in (6, 8, 14, 16, 17, 20, 29, 53, 92, None):
            assert sv.grade(0.75, z) == "routine", z
            assert sv.grade(1.00, z) == "routine", z

    def test_near_the_atomic_line_a_heavier_than_Si_atom_still_helps(self):
        # 1.0-1.2 A: light atoms are already harder, a >Si scatterer is not
        assert sv.grade(1.15, 8) == "harder"
        assert sv.grade(1.15, 14) == "harder"        # Si itself is the line
        assert sv.grade(1.15, 15) == "routine"       # P and heavier
        assert sv.grade(1.15, 17) == "routine"
        assert sv.grade(1.15, None) == "harder"      # undeclared counts light

    def test_past_the_atomic_line_only_a_dominant_scatterer_lifts_it(self):
        for d in (1.25, 1.3, 1.6, 2.0):
            assert sv.grade(d, 8) == "no_record", d       # pure organic
            assert sv.grade(d, 16) == "no_record", d      # S: a marker only
            assert sv.grade(d, 17) == "no_record", d      # Cl: a marker only
            assert sv.grade(d, 19) == "no_record", d
            assert sv.grade(d, 20) == "harder", d         # Ca and up
            assert sv.grade(d, 29) == "harder", d         # Cu
            assert sv.grade(d, 53) == "harder", d         # I
            assert sv.grade(d, None) == "no_record", d

    def test_the_lines_are_the_ones_the_physics_statement_names(self):
        assert sv.SI_Z == 14 and sv.DOMINANT_Z == 20
        assert sv.COARSE_D_MIN == 1.2 and sv.ATOMIC_D_MIN == 1.0
        assert set(sv.TIERS) == {"routine", "harder", "no_record"}

    def test_an_unmeasurable_d_min_is_not_reported_as_safe(self):
        b = _block(None, 8)
        assert b["tier"] == "no_record"
        assert "no d_min could be read" in b["physics"]


# --------------------------------------------------------------------- #
# 2. what the block says
# --------------------------------------------------------------------- #

class TestBlockContent:
    def test_routine_carries_no_warning_wording(self):
        b = _block(0.75, 8, "O")
        assert b["tier"] == "routine"
        text = json.dumps(b)
        for word in WARNING_WORDS:
            assert word not in text, (word, text)
        assert "not_evidence" not in b and "tier_rule" not in b
        assert b["d_min"] == 0.75 and b["heaviest_element_z"] == 8
        assert b["completeness"] == 0.98

    def test_no_record_states_the_physics_and_the_disclaimer(self):
        b = _block(1.3, 17, "Cl")
        assert b["tier"] == "no_record"
        assert "1.2 A" in b["physics"] and "heavier than Si" in b["physics"]
        assert "Z >= 20" in b["physics"]
        assert "NO measured success-rate record" in b["not_evidence"]
        assert "NOT evidence that the structure is unsolvable" in \
            b["not_evidence"]
        assert "not a reason to change the space group" in b["not_evidence"]
        assert "d_min and the heaviest declared Z only" in b["tier_rule"]

    def test_harder_distinguishes_a_dominant_scatterer_from_light_atoms(self):
        light = _block(1.15, 8, "O")
        heavy = _block(1.4, 29, "Cu")
        assert light["tier"] == heavy["tier"] == "harder"
        assert "no atom heavier than Si" in light["physics"]
        assert "carry phases on its own" in heavy["physics"]
        assert light["not_evidence"] and heavy["not_evidence"]

    def test_heaviest_declared_ignores_hydrogen_and_unknown_symbols(self):
        assert sv.heaviest_declared(["H", "C", "N", "O"]) == ("O", 8)
        assert sv.heaviest_declared(["C", "H", "Cl", "S"]) == ("Cl", 17)
        assert sv.heaviest_declared(["H", "D"]) == (None, None)
        assert sv.heaviest_declared(["Zz", "C"]) == ("C", 6)
        assert sv.heaviest_declared([]) == (None, None)


# --------------------------------------------------------------------- #
# 3. the four tools carry it, whatever the outcome
# --------------------------------------------------------------------- #

def _ctx(ses):
    return ToolContext(store=_Store(), session=ses)


class TestChargeFlipping:
    def test_on_a_converged_solve(self):
        ses = _solved_session(_thiophene_like(),
                              {"C": 6, "H": 6, "O": 1, "S": 1}, z=1)
        r = st.ChargeFlippingSolve().run(_ctx(ses), d_min=0.9, seeds=[1],
                                         max_solving_iterations=200,
                                         timeout_s=120)
        assert r.ok, r.error
        b = r.summary["solution_capability"]
        assert b["tier"] == "routine"
        assert b["heaviest_element"] == "S" and b["heaviest_element_z"] == 16
        assert b["d_min"] == 0.9
        assert "d_min truncation" in b["d_min_source"]
        assert b["completeness"] is not None

    def test_on_a_failure_before_any_phasing(self):
        ses = _solved_session(_thiophene_like(),
                              {"C": 6, "H": 6, "O": 1, "S": 1}, z=1)
        r = st.ChargeFlippingSolve().run(_ctx(ses), d_min=6.0)
        assert not r.ok and "data too sparse" in r.error
        # the truncation this call asked for is what gets graded
        b = r.summary["solution_capability"]
        assert b["d_min"] == 6.0 and b["tier"] == "no_record"

    def test_the_block_never_refuses_a_no_record_case(self):
        """The whole point: the disclosure is not a gate. A coarse-data
        light-atom call still runs and still returns its own result."""
        ses = _solved_session(_dbu_hcl_like(),
                              {"C": 9, "H": 17, "N": 2, "Cl": 1}, z=1,
                              d_min=1.25)
        r = st.ChargeFlippingSolve().run(_ctx(ses), d_min=1.3, seeds=[1],
                                         max_solving_iterations=150,
                                         timeout_s=120)
        b = r.summary["solution_capability"]
        assert b["tier"] == "no_record"
        assert b["heaviest_element"] == "Cl"
        # whatever the solve did, it was NOT stopped by the disclosure
        if not r.ok:
            assert "solution_capability" not in (r.error or "")
            assert "no_record" not in (r.error or "")

    def test_completeness_guard_still_refuses_on_its_own(self):
        """The block reuses the guard's skeleton, not its teeth: the
        completeness refusal is untouched and now arrives WITH the
        disclosure."""
        ses = _solved_session(_thiophene_like(),
                              {"C": 6, "H": 6, "O": 1, "S": 1}, z=1)
        keep = ses.fo_sq.select(
            (ses.fo_sq.indices().as_vec3_double().as_double()[0::3]) > -1e9)
        ses.fo_sq = keep[:int(keep.size() * 0.3)]
        r = st.ChargeFlippingSolve().run(_ctx(ses), d_min=0.9)
        assert not r.ok
        assert "completeness" in r.error and "0/6 success record" in r.error
        assert "solution_capability" in r.summary


class TestSuperflip:
    def test_block_rides_on_the_missing_executable_refusal(self, monkeypatch):
        monkeypatch.setattr(st, "SUPERFLIP_EXE",
                            st.REPO_ROOT / "vendor" / "nope" / "sf.exe")
        ses = _solved_session(_dbu_hcl_like(),
                              {"C": 9, "H": 17, "N": 2, "Cl": 1}, z=1,
                              d_min=1.25)
        r = st.SolveSuperflip().run(_ctx(ses), d_min=1.3)
        assert not r.ok and "VENDOR-STATUS" in r.error
        b = r.summary["solution_capability"]
        assert b["tier"] == "no_record" and b["heaviest_element"] == "Cl"

    def test_without_a_d_min_the_source_says_all_data(self, monkeypatch):
        monkeypatch.setattr(st, "SUPERFLIP_EXE",
                            st.REPO_ROOT / "vendor" / "nope" / "sf.exe")
        ses = _solved_session(_thiophene_like(),
                              {"C": 6, "H": 6, "O": 1, "S": 1}, z=1)
        r = st.SolveSuperflip().run(_ctx(ses))
        b = r.summary["solution_capability"]
        assert "all merged data" in b["d_min_source"]
        assert b["d_min"] == pytest.approx(0.85, abs=0.02)
        assert b["tier"] == "routine"


class TestRunShelxt:
    def _project(self, tmp_path):
        hkl = tmp_path / "crystal.hkl"
        hkl.write_text("   1   1   1  100.00    1.00\n"
                       "   0   0   0    0.00    0.00\n", encoding="ascii")
        return SimpleNamespace(dir=tmp_path, hkl_path=hkl)

    def test_block_rides_on_an_early_refusal(self, tmp_path):
        from crystalpilot.refine import tools_extra as te
        r = te.RunShelxt(self._project(tmp_path)).run(
            SimpleNamespace(session=SimpleNamespace(dataset=None)),
            composition="C H N O Cl", solve_resolution=1.3)
        assert not r.ok and "no dataset in session" in r.error
        b = r.summary["solution_capability"]
        assert b["tier"] == "no_record"
        assert b["heaviest_element"] == "Cl"
        assert "SHELXT -d1.3" in b["d_min_source"]
        assert "composition given to this call" in b["heaviest_element_source"]

    def test_without_solve_resolution_it_reports_the_data_d_min(self,
                                                                tmp_path):
        from crystalpilot.refine import tools_extra as te
        ses = _solved_session(_thiophene_like(),
                              {"C": 6, "H": 6, "O": 1, "S": 1}, z=1)
        ses.model = _thiophene_like()
        ses.dataset = None                       # forces the early refusal
        r = te.RunShelxt(self._project(tmp_path)).run(
            SimpleNamespace(session=ses))
        assert not r.ok
        b = r.summary["solution_capability"]
        assert b["tier"] == "routine"
        # no composition string and no dataset hint left: the elements
        # in the session model are the next honest source
        assert b["heaviest_element"] == "S"
        assert "session model" in b["heaviest_element_source"]
        assert "SHELXT sees all of it" in b["d_min_source"]


class TestCreateStartModel:
    def test_block_rides_on_a_prerequisite_failure(self, tmp_path):
        from crystalpilot.refine.tools_frames import CreateStartModel
        proj = SimpleNamespace(dir=tmp_path, context={})
        r = CreateStartModel(proj).run(SimpleNamespace(session=None),
                                       composition="C16 H20 N4 O6")
        assert not r.ok and "scale_and_export" in r.error
        b = r.summary["solution_capability"]
        assert b["heaviest_element"] == "O"
        assert b["d_min"] is None
        assert "did not reach the scaled data" in b["d_min_source"]


# --------------------------------------------------------------------- #
# 4. the disclosure attaches without ever touching the outcome
# --------------------------------------------------------------------- #

def test_attach_preserves_ok_error_and_the_rest_of_the_summary():
    r = ToolResult(ok=False, error="something else entirely",
                   summary={"a": 1})
    out = sv.attach(r, _block(1.3, 8))
    assert out is r and out.ok is False
    assert out.error == "something else entirely"
    assert out.summary["a"] == 1
    assert out.summary["solution_capability"]["tier"] == "no_record"


def test_attach_is_a_no_op_without_a_block():
    r = ToolResult(ok=True, summary={"a": 1})
    assert sv.attach(r, None).summary == {"a": 1}


def test_all_four_descriptions_announce_the_block():
    from crystalpilot.refine.tools_frames import CreateStartModel
    from crystalpilot.refine.tools_shelxl import RunShelxt
    for tool in (st.ChargeFlippingSolve, st.SolveSuperflip, RunShelxt,
                 CreateStartModel):
        d = tool.description
        assert "solution_capability" in d, tool.name
        assert "routine/harder/no_record" in d, tool.name
        assert "heaviest declared Z" in d, tool.name
