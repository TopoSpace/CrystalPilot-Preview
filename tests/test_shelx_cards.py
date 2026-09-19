"""The run_shelxl(extra_cards=...) gate and the HTAB builder (D11).

Everything here is pure: no SHELXL, no project, no fixture-specific
chemistry. The end-to-end proof that a gated HTAB card really produces a
`_geom_hbond_*` loop with esds lives in tests/test_shelxl_tools.py.
"""
from __future__ import annotations

import pytest

from crystalpilot.io.shelx_model import EXTRA_CARD_KEYWORDS
from crystalpilot.refine.shelx_cards import (CARD_FAMILIES, MAX_EQIV_INDEX,
                                             SHELX_LINE_LIMIT,
                                             extra_cards_help, htab_cards,
                                             op_to_shelx,
                                             validate_extra_cards)

LABELS = ["O1", "H1", "C1", "O2", "C2", "N1"]
ELEMENTS = {"O", "H", "C", "N"}
#: what shelxl_command_block writes into every .ins
BASE = ["L.S. 8", "BOND $H", "CONF", "ACTA", "FMAP 2", "PLAN 20"]


def _sg(symbol="P 21/c"):
    from cctbx import sgtbx
    return sgtbx.space_group_info(symbol).group()


def gate(cards, *, labels=LABELS, rename=None, base=BASE, sg="P 21/c",
         elements=ELEMENTS):
    return validate_extra_cards(cards, labels=labels, elements=elements,
                                rename=rename, base_cards=base,
                                space_group=_sg(sg) if sg else None)


class TestWhitelistIsShared:
    def test_one_constant_lives_in_shelx_model(self):
        """The gate and the .res reader must never drift apart: the
        whitelist is defined once, next to shelx_model's _KNOWN."""
        from crystalpilot.io import shelx_model
        from crystalpilot.refine import shelx_cards
        assert shelx_cards.EXTRA_CARD_KEYWORDS is \
            shelx_model.EXTRA_CARD_KEYWORDS
        # every accepted card is an instruction load_res_model recognizes
        # when SHELXL echoes it back into the .res
        assert EXTRA_CARD_KEYWORDS <= shelx_model._KNOWN

    def test_the_plan_families_are_exactly_the_whitelist(self):
        # FREE / BIND added 2026-09-08: the delivery's bond_table_audit
        # names a `FREE <metal> <atom>` card for radius-table bonds SHELXL
        # lists that the model's own bonding does not (usertest test3-1
        # Zn02-C21 2.52 A drawn as a seventh ligand in Olex2)
        assert EXTRA_CARD_KEYWORDS == {
            "HTAB", "RTAB", "MPLA", "CONF", "EADP", "EXYZ", "SAME", "SUMP",
            "EQIV", "BOND", "ACTA", "FREE", "BIND"}

    def test_every_family_is_documented_for_the_agent(self):
        assert set(CARD_FAMILIES) == set(EXTRA_CARD_KEYWORDS)
        help_text = extra_cards_help()
        for kw in EXTRA_CARD_KEYWORDS:
            assert kw in help_text

    def test_the_tool_schema_carries_that_documentation(self):
        from crystalpilot.refine.tools_shelxl import RunShelxl
        props = RunShelxl.params_schema["properties"]
        desc = props["extra_cards"]["description"]
        for kw in EXTRA_CARD_KEYWORDS:
            assert kw in desc, kw
        assert props["extra_cards"]["type"] == "array"
        assert props["reason"]["type"] == "string"


class TestAcceptance:
    def test_htab_pair_and_its_eqiv(self):
        lines, applied, err = gate(["EQIV $1 -x,y+1/2,-z+1/2",
                                    "HTAB O1 O2_$1"])
        assert err is None
        assert lines == ["EQIV $1 -X, Y+1/2, -Z+1/2", "HTAB O1 O2_$1"]
        assert applied == lines

    def test_eqiv_is_emitted_first_whatever_the_caller_ordered(self):
        """A card may reference $n before the list defines it."""
        lines, _a, err = gate(["HTAB O1 O2_$1", "HTAB N1 O2",
                               "EQIV $1 -x,-y,-z"])
        assert err is None
        assert lines[0].startswith("EQIV $1")
        # the rest keep the order they were given in
        assert lines[1:] == ["HTAB O1 O2_$1", "HTAB N1 O2"]

    def test_rtab_first_argument_is_a_name_not_an_atom(self):
        lines, _a, err = gate(["RTAB OHO O1 H1 O2"])
        assert err is None and lines == ["RTAB OHO O1 H1 O2"]

    def test_mpla_takes_a_leading_count(self):
        lines, _a, err = gate(["MPLA 4 O1 C1 O2 C2"])
        assert err is None and lines == ["MPLA 4 O1 C1 O2 C2"]

    def test_sump_is_all_numbers(self):
        lines, _a, err = gate(["SUMP 1 0.01 1 2 1 3"])
        assert err is None and lines == ["SUMP 1 0.01 1 2 1 3"]

    def test_element_class_reference(self):
        lines, _a, err = gate(["BOND $N"])
        assert err is None and lines == ["BOND $N"]

    def test_residue_suffixes_survive(self):
        lines, _a, err = gate(["EQIV $1 -x,-y,-z", "HTAB O1_2 O2_1_$1"])
        assert err is None
        assert lines[1] == "HTAB O1_2 O2_1_$1"

    def test_residue_form_of_the_instruction_name(self):
        lines, _a, err = gate(["SAME_2 O1 C1 O2"])
        assert err is None and lines == ["SAME_2 O1 C1 O2"]

    def test_session_labels_are_rewritten_to_the_ins_spelling(self):
        """The writer sanitizes labels to <=4 characters; a card quoting
        the session label must still point at the right atom."""
        lines, _a, err = gate(["HTAB OWATER1 O2"],
                              labels=["OWATER1", "O2"],
                              rename={"OWATER1": "O0"})
        assert err is None and lines == ["HTAB O0 O2"]
        # the sanitized spelling works too
        lines2, _a2, err2 = gate(["HTAB O0 O2"], labels=["OWATER1", "O2"],
                                 rename={"OWATER1": "O0"})
        assert err2 is None and lines2 == ["HTAB O0 O2"]

    def test_exact_duplicates_collapse(self):
        lines, _a, err = gate(["HTAB O1 O2", "htab o1 o2"])
        assert err is None and lines == ["HTAB O1 O2"]

    def test_none_and_empty_are_no_ops(self):
        assert validate_extra_cards(None, labels=LABELS) == ([], [], None)
        assert validate_extra_cards([], labels=LABELS) == ([], [], None)


class TestRejection:
    def _err(self, cards, **kw):
        lines, applied, err = gate(cards, **kw)
        assert err, f"expected a rejection for {cards}"
        assert lines == [] and applied == []
        return err

    def test_unknown_keyword_quotes_the_card_and_lists_the_whitelist(self):
        err = self._err(["FMAP 4"])
        assert "'FMAP 4'" in err and "FMAP" in err
        for kw in ("HTAB", "MPLA", "EQIV"):
            assert kw in err

    def test_an_unknown_atom_is_named(self):
        err = self._err(["HTAB O1 O9"])
        assert "'HTAB O1 O9'" in err and "'O9'" in err

    def test_undefined_symmetry_code(self):
        err = self._err(["HTAB O1 O2_$3"])
        assert "$3" in err and "EQIV" in err

    def test_eqiv_operator_must_belong_to_the_space_group(self):
        """SHELXL applies any operator it is given, so a typo silently
        publishes a wrong _geom_hbond_site_symmetry_A."""
        err = self._err(["EQIV $1 -x+1/3,y,z"])
        assert "space group" in err
        # ... and the real one is accepted
        assert gate(["EQIV $1 -x,y+1/2,-z+1/2"])[2] is None

    def test_lattice_translation_of_a_group_operator_is_fine(self):
        lines, _a, err = gate(["EQIV $1 -x+1,y+1/2,-z+1/2"])
        assert err is None and lines == ["EQIV $1 -X+1, Y+1/2, -Z+1/2"]

    def test_centring_translation_is_a_group_operator(self):
        lines, _a, err = gate(["EQIV $1 x+1/2,y+1/2,z"], sg="C 2/c")
        assert err is None, err
        assert lines == ["EQIV $1 X+1/2, Y+1/2, Z"]

    def test_no_space_group_means_no_membership_check(self):
        lines, _a, err = gate(["EQIV $1 -x+1/3,y,z"], sg=None)
        assert err is None and lines == ["EQIV $1 -X+1/3, Y, Z"]

    def test_eqiv_index_range(self):
        assert gate([f"EQIV ${MAX_EQIV_INDEX} -x,-y,-z"])[2] is None
        err = self._err([f"EQIV ${MAX_EQIV_INDEX + 1} -x,-y,-z"])
        assert f"${MAX_EQIV_INDEX}" in err

    def test_eqiv_needs_a_code_and_an_operator(self):
        assert "$n" in self._err(["EQIV -x,-y,-z"])
        assert "symmetry code" in self._err(["EQIV 1 -x,-y,-z"])
        assert "symmetry operator" in self._err(["EQIV $1 sideways"])

    def test_redefining_one_code_two_ways_is_refused(self):
        err = self._err(["EQIV $1 -x,-y,-z", "EQIV $1 -x,y+1/2,-z+1/2"])
        assert "$1" in err and "already defined" in err

    def test_acta_is_not_duplicated(self):
        err = self._err(["ACTA"])
        assert "ACTA" in err and "already" in err

    def test_acta_with_zero_cycles_is_refused_with_shelxls_reason(self):
        """run_shelxl leaves ACTA out at l_s = 0 because SHELXL aborts on
        it; asking for it by hand must not walk into that abort."""
        err = self._err(["ACTA 50"], base=["L.S. 0", "FMAP 2"])
        assert "L.S. 0" in err and "l_s" in err

    def test_acta_is_accepted_when_the_block_has_none(self):
        lines, _a, err = gate(["ACTA 50"], base=["L.S. 8", "FMAP 2"])
        assert err is None and lines == ["ACTA 50"]

    def test_a_card_the_command_block_already_writes_is_refused(self):
        assert "duplicate" in self._err(["BOND $H"])
        assert "duplicate" in self._err(["CONF"])

    def test_element_class_must_exist_in_the_model(self):
        err = self._err(["BOND $Fe"])
        assert "$Fe" in err and "C, H, N, O" in err

    def test_rtab_name_longer_than_four_characters(self):
        assert "RTAB" in self._err(["RTAB HYDROGEN O1 H1 O2"])

    def test_sump_refuses_an_atom(self):
        assert "numbers only" in self._err(["SUMP 1 0.01 O1"])

    def test_multi_line_entries_are_refused(self):
        assert "one instruction per list entry" in self._err(
            ["HTAB O1 O2\nHTAB N1 O2"])

    def test_empty_entry(self):
        assert "empty" in self._err(["  "])

    def test_non_string_entry(self):
        assert "strings" in self._err([42])

    def test_not_a_list(self):
        _l, _a, err = validate_extra_cards("HTAB O1 O2", labels=LABELS)
        assert err and "list" in err


class TestEightyColumns:
    def test_a_long_card_is_split_with_shelx_continuation(self):
        card = "MPLA 6 " + " ".join(LABELS * 12)
        lines, applied, err = gate([card])
        assert err is None
        physical = lines[0].split("\n")
        assert len(physical) > 1
        assert all(len(p) <= SHELX_LINE_LIMIT for p in physical)
        # SHELX continuation: '=' ends the line, the next one starts with a
        # space, and no token is lost
        assert all(p.endswith("=") for p in physical[:-1])
        assert all(p.startswith(" ") for p in physical[1:])
        assert lines[0].replace("=\n", "").split() == card.split()
        # the summary shows the card as one line
        assert applied == [card]

    def test_a_card_with_no_break_point_is_refused_not_truncated(self):
        long_label = "L" * 120
        err = validate_extra_cards(
            ["MPLA " + long_label], labels=[long_label], elements={"C"},
            base_cards=BASE)[2]
        assert err and str(SHELX_LINE_LIMIT) in err

    def test_a_card_that_just_fits_is_left_alone(self):
        card = "HTAB " + " ".join(["O1"] * 20)          # 65 characters
        assert len(card) < 76
        lines, _a, err = gate([card])
        assert err is None and "\n" not in lines[0]


class TestOperatorConversion:
    def test_identity(self):
        assert op_to_shelx("x,y,z") == "X, Y, Z"

    def test_integral_translation_comes_last(self):
        assert op_to_shelx("-x,-y+1,-z") == "-X, -Y+1, -Z"

    def test_fractional_translations_stay_exact_fractions(self):
        """0.5 rounded is not what SHELXL's SYMM/EQIV parser expects from
        us; the writer emits SYMM the same way."""
        assert op_to_shelx("-x+1/2,y+1/2,-z+1/2") == "-X+1/2, Y+1/2, -Z+1/2"
        assert op_to_shelx("-y+1/4,x+3/4,z+1/4") == "-Y+1/4, X+3/4, Z+1/4"

    def test_accepts_an_rt_mx_object(self):
        from cctbx import sgtbx
        assert op_to_shelx(sgtbx.rt_mx("-x,-y,-z")) == "-X, -Y, -Z"

    def test_matches_the_symm_cards_the_writer_writes(self):
        from cctbx import sgtbx
        sg = sgtbx.space_group_info("P 41 21 2").group()
        for i in range(sg.n_smx()):
            rt = sg(0, 0, i)
            assert op_to_shelx(rt) == rt.as_xyz(
                decimal=False, t_first=False, symbol_letters="XYZ",
                separator=", ")


# ==========================================================================
# htab_cards: the canonical hydrogen-bond table -> EQIV/HTAB
# ==========================================================================

def _row(d, a, op="x,y,z", dist=2.8, passes=True, status=None, **kw):
    return {"d": d, "a": a, "op": op, "dist": dist, "passes": passes,
            "status": status, "kind": "hbond", **kw}


class TestHtabCards:
    def test_same_molecule_rows_need_no_eqiv(self):
        out = htab_cards([_row("O1", "O2")], "refined")
        assert out["cards"] == ["HTAB O1 O2"]
        assert out["skipped"] == []

    def test_rows_come_out_shortest_first(self):
        out = htab_cards([_row("N1", "O5", dist=3.10),
                          _row("O1", "O2", dist=2.65),
                          _row("N2", "O3", dist=2.90)], "refined")
        assert out["cards"] == ["HTAB O1 O2", "HTAB N2 O3", "HTAB N1 O5"]

    def test_an_image_row_gets_an_eqiv_and_the_suffix(self):
        out = htab_cards([_row("O1", "O2", op="-x,-y+1,-z")], "refined")
        assert out["cards"] == ["EQIV $1 -X, -Y+1, -Z", "HTAB O1 O2_$1"]

    def test_one_eqiv_per_distinct_operator_reused(self):
        op1, op2 = "-x,y+1/2,-z+1/2", "x,-y+1/2,z+1/2"
        out = htab_cards([_row("O1", "O2", op=op1, dist=2.6),
                          _row("N1", "O3", op=op2, dist=2.7),
                          _row("N2", "O4", op=op1, dist=2.8),
                          _row("N3", "O5", dist=2.9)], "refined")
        assert out["cards"] == [
            "EQIV $1 -X, Y+1/2, -Z+1/2",
            "EQIV $2 X, -Y+1/2, Z+1/2",
            "HTAB O1 O2_$1", "HTAB N1 O3_$2", "HTAB N2 O4_$1",
            "HTAB N3 O5"]

    def test_fractional_translations_reach_the_eqiv_card(self):
        out = htab_cards([_row("O1", "O2", op="-y+1/4,x+3/4,z+1/4")],
                         "refined")
        assert out["cards"][0] == "EQIV $1 -Y+1/4, X+3/4, Z+1/4"

    def test_the_hydrogen_is_never_named(self):
        """SHELXL finds the H itself - which is what makes a donor with
        several H work."""
        out = htab_cards([_row("N1", "O1", h="H1A")], "refined")
        assert out["cards"] == ["HTAB N1 O1"]

    def test_absent_hydrogen_emits_nothing_and_says_why(self):
        rows = [_row("O1", "O2"), _row("N1", "O3")]
        out = htab_cards(rows, "absent")
        assert out["cards"] == []
        assert len(out["skipped"]) == 2
        assert "no hydrogen" in out["note"]
        assert "add_hydrogens" in out["note"]

    def test_the_no_h_status_row_is_skipped_with_its_reason(self):
        from crystalpilot.chem.interactions import NO_H_STATUS
        out = htab_cards([_row("O1", "O2", status=NO_H_STATUS),
                          _row("N1", "O3")], "mixed")
        assert out["cards"] == ["HTAB N1 O3"]
        assert out["skipped"][0]["d"] == "O1"
        assert NO_H_STATUS in out["skipped"][0]["reason"]

    def test_a_failing_row_is_skipped_with_its_reason(self):
        out = htab_cards([_row("C9", "O5", passes=False, angle=118.0)],
                         "riding")
        assert out["cards"] == []
        assert out["skipped"][0]["reason"].startswith("fails")
        assert "none of the 1 canonical" in out["note"]

    def test_riding_hydrogens_are_disclosed_in_the_note(self):
        for src in ("riding", "mixed"):
            note = htab_cards([_row("O1", "O2")], src)["note"]
            assert "riding" in note and "1.09" in note
        assert "riding" not in htab_cards([_row("O1", "O2")],
                                          "refined")["note"]

    def test_unknown_h_source_is_disclosed_too(self):
        for src in (None, "unknown"):
            assert "h_source is unknown" in htab_cards(
                [_row("O1", "O2")], src)["note"]

    def test_the_operator_cap_reports_what_it_left_out(self):
        rows = [_row(f"N{i}", f"O{i}", op=f"x,y,z+{i}", dist=2.5 + i * 0.01)
                for i in range(1, 8)]
        out = htab_cards(rows, "refined", max_eqiv=3)
        assert len([c for c in out["cards"] if c.startswith("EQIV")]) == 3
        assert len([c for c in out["cards"] if c.startswith("HTAB")]) == 3
        assert len(out["skipped"]) == 4
        assert all("max_eqiv=3" in s["reason"] for s in out["skipped"])
        # the cards that WERE made are the shortest contacts
        assert out["cards"][3:] == ["HTAB N1 O1_$1", "HTAB N2 O2_$2",
                                    "HTAB N3 O3_$3"]
        assert "4 row(s) left out" in out["note"]
        assert f"${MAX_EQIV_INDEX}" in out["note"]

    def test_the_default_cap_is_48(self):
        rows = [_row(f"N{i}", f"O{i}", op=f"x,y,z+{i}", dist=2.5 + i * 0.001)
                for i in range(1, 60)]
        out = htab_cards(rows, "refined")
        assert len([c for c in out["cards"] if c.startswith("EQIV")]) == 48
        assert len(out["skipped"]) == 11

    def test_identical_cards_are_not_repeated(self):
        out = htab_cards([_row("O1", "O2", dist=2.7),
                          _row("O1", "O2", dist=2.8)], "refined")
        assert out["cards"] == ["HTAB O1 O2"]

    def test_a_row_without_labels_is_skipped_not_written(self):
        out = htab_cards([{"d": None, "a": "O2", "op": "x,y,z",
                           "dist": 2.7, "passes": True, "status": None}],
                         "refined")
        assert out["cards"] == []
        assert "no donor/acceptor label" in out["skipped"][0]["reason"]

    def test_empty_input(self):
        out = htab_cards([], "refined")
        assert out["cards"] == [] and out["skipped"] == []

    def test_the_output_passes_the_gate(self):
        """The builder and the gate are two halves of one path."""
        out = htab_cards([_row("O1", "O2", op="-x,y+1/2,-z+1/2"),
                          _row("N1", "C1")], "refined")
        lines, applied, err = gate(out["cards"])
        assert err is None
        assert applied == out["cards"]
        assert lines == out["cards"]


@pytest.mark.parametrize("op", ["x,y,z", "X, Y, Z", " x, y, z "])
def test_identity_never_gets_an_eqiv(op):
    out = htab_cards([_row("O1", "O2", op=op)], "refined")
    assert out["cards"] == ["HTAB O1 O2"]
