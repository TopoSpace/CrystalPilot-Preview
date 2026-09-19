"""Round-3 WP3: PART state follows the atoms.

Forensic thread T-b: deleting a split component left its PART in
parts_extra and its member record in the disorder group, a same-name atom
added later inherited the block, and model_disorder(undo=) went on
describing atoms that no longer existed. PART was also implicit - only a
split could assign it - and a DFIX written across two PARTs registered
silently and vanished in SHELXL.

Synthetic P-1 cell; no campaign crystal."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from crystalpilot.refine.nodes import serialization_extras  # noqa: E402
from crystalpilot.refine.parts import part_of_labels  # noqa: E402
from crystalpilot.tools.model_tools import EditAtoms  # noqa: E402


def _xs(extra=()):
    from cctbx import crystal, xray
    cs = crystal.symmetry(unit_cell=(10, 10, 10, 90, 90, 90),
                          space_group_symbol="P -1")
    xs = xray.structure(crystal_symmetry=cs)
    atoms = [("C1", "C", (0.10, 0.10, 0.10)), ("C2", "C", (0.25, 0.10, 0.10)),
             ("C3", "C", (0.10, 0.25, 0.10)), ("C4", "C", (0.10, 0.10, 0.25)),
             ("C5", "C", (0.25, 0.25, 0.10)), ("C9", "C", (0.40, 0.40, 0.40)),
             ("O1A", "O", (0.60, 0.30, 0.20)), ("O1B", "O", (0.64, 0.34, 0.22)),
             ("N1A", "N", (0.70, 0.70, 0.70)), ("N1B", "N", (0.74, 0.74, 0.72)),
             *extra]
    for lbl, el, site in atoms:
        xs.add_scatterer(xray.scatterer(label=lbl, site=site, u=0.03,
                                        occupancy=1.0, scattering_type=el))
    return xs


def _session(flags=None):
    return SimpleNamespace(model=_xs(), flags=dict(flags or {}), dataset=None)


def _ctx(ses):
    # no store -> no project dir -> no ghost ledger, like a bare test context
    return SimpleNamespace(session=ses, store=None)


def _edit(ses, *ops, **extra):
    return EditAtoms().run(_ctx(ses), operations=list(ops), **extra)


def _undo(ses, ref):
    from crystalpilot.refine.tools_disorder import ModelDisorder
    return ModelDisorder(None).run(SimpleNamespace(session=ses), undo=ref)


def _split_flags():
    """Two FVAR groups the way model_disorder records them, one loose PART
    atom, and the origins that make the splits undoable."""
    return {
        "disorder_groups": [
            {"fvar_index": 2, "value": 0.6, "members": [
                {"label": "O1A", "part": 1, "sign": 1, "mult": 1.0},
                {"label": "O1B", "part": 2, "sign": -1, "mult": 1.0}]},
            {"fvar_index": 3, "value": 0.7, "members": [
                {"label": "N1A", "part": 1, "sign": 1, "mult": 1.0},
                {"label": "N1B", "part": 2, "sign": -1, "mult": 1.0}]}],
        "parts_extra": {"C9": 1},
        "disorder_origins": [
            {"fvar_index": 2, "created": ["O1B"], "linked_existing": [],
             "image_labels": [], "restore": [{"label": "O1A", "occupancy": 1.0}],
             "occupancy_a": 0.6, "node_before": "n0003", "ts": 1.0},
            {"fvar_index": 3, "created": ["N1B"], "linked_existing": [],
             "image_labels": [], "restore": [{"label": "N1A", "occupancy": 1.0}],
             "occupancy_a": 0.7, "node_before": "n0004", "ts": 2.0}],
    }


# ==========================================================================
class TestDeleteHygiene:
    def test_deleting_a_component_clears_its_part_state(self):
        ses = _session(_split_flags())
        r = _edit(ses, {"action": "delete", "atoms": ["O1B"]})
        assert r.ok, r.error
        flags = ses.flags
        members = [m["label"] for m in flags["disorder_groups"][0]["members"]]
        assert members == ["O1A"]
        assert flags["parts_extra"] == {"C9": 1}
        o = flags["disorder_origins"][0]
        assert o["stale"] is True and "O1B" in o["stale_reason"] \
            and "edit_atoms" in o["stale_reason"]
        assert flags["disorder_origins"][1].get("stale") is None
        hyg = r.summary["part_hygiene"]
        assert hyg["disorder_members_removed"] == ["O1B"]
        assert hyg["disorder_origins_stale"][0]["atoms"] == ["O1B"]
        assert "stale" in r.summary["part_note"]
        # PART lookups and the PART cards no longer know the label
        assert "O1B" not in part_of_labels(flags)
        assert "O1B" not in serialization_extras(flags)["parts"]

    def test_same_label_added_later_does_not_inherit_the_part(self):
        from cctbx import xray
        ses = _session({"parts_extra": {"C9": -1, "O1B": 2}})
        assert _edit(ses, {"action": "delete", "atoms": ["O1B"]}).ok
        assert ses.flags["parts_extra"] == {"C9": -1}
        ses.model.add_scatterer(xray.scatterer(
            label="O1B", site=(0.5, 0.5, 0.5), u=0.03, scattering_type="O"))
        assert part_of_labels(ses.flags).get("O1B") is None
        assert "O1B" not in serialization_extras(ses.flags).get("parts", {})

    def test_group_that_loses_every_member_is_dropped_and_fvars_renumbered(self):
        ses = _session(_split_flags())
        r = _edit(ses, {"action": "delete", "atoms": ["O1A", "O1B"]})
        assert r.ok, r.error
        groups = ses.flags["disorder_groups"]
        assert len(groups) == 1
        assert groups[0]["fvar_index"] == 2 and groups[0]["value"] == 0.7
        assert [m["label"] for m in groups[0]["members"]] == ["N1A", "N1B"]
        hyg = r.summary["part_hygiene"]
        assert hyg["disorder_groups_dropped"] == [2]
        assert hyg["fvar_renumbered"] == {"3": 2}
        o_origin, n_origin = ses.flags["disorder_origins"]
        assert o_origin["stale"] is True and o_origin["fvar_index"] is None
        assert n_origin["fvar_index"] == 2 and n_origin.get("stale") is None
        # the serialized FVAR card is the contiguous block SHELXL needs
        ex = serialization_extras(ses.flags)
        assert ex["fvars"] == [0.7]
        assert ex["sof_codes"] == {"N1A": 21.0, "N1B": -21.0}

    def test_stale_split_refuses_undo_even_when_the_label_is_back(self):
        from cctbx import xray
        ses = _session(_split_flags())
        assert _edit(ses, {"action": "delete", "atoms": ["O1B"]}).ok
        ses.model.add_scatterer(xray.scatterer(
            label="O1B", site=(0.5, 0.5, 0.5), u=0.03, scattering_type="O"))
        n_before = ses.model.scatterers().size()
        r = _undo(ses, "fvar2")
        assert not r.ok
        assert "no longer be undone" in r.error and "O1B" in r.error
        assert "n0003" in r.error
        assert ses.model.scatterers().size() == n_before
        # the untouched split is still undoable by reference
        assert ses.flags["disorder_origins"][1].get("stale") is None


# ==========================================================================
class TestSetPart:
    def test_set_part_on_a_loose_atom_is_recorded_and_undone(self):
        ses = _session()
        r = _edit(ses, {"action": "set_part", "atoms": ["C9"], "part": 2})
        assert r.ok, r.error
        assert r.summary["parts"]["parts"] == {"C9": 2}
        assert "model_disorder(undo='C9')" in r.summary["parts"]["undo"]
        assert ses.flags["parts_extra"] == {"C9": 2}
        assert serialization_extras(ses.flags)["parts"] == {"C9": 2}
        o = ses.flags["disorder_origins"][-1]
        assert o["kind"] == "part_edit" and o["labels"] == ["C9"]
        assert o["before"] == {"C9": {"source": None, "part": None}}
        u = _undo(ses, "C9")
        assert u.ok, u.error
        assert u.summary["mode"] == "part_edit"
        assert u.summary["parts"] == {"C9": None}
        assert "parts_extra" not in ses.flags
        assert "disorder_origins" not in ses.flags

    def test_set_part_on_a_group_member_changes_the_member_only(self):
        ses = _session(_split_flags())
        r = _edit(ses, {"action": "set_part", "atoms": ["o1a"], "part": -1})
        assert r.ok, r.error
        assert r.summary["case_folded"] == ["o1a->O1A"]
        members = ses.flags["disorder_groups"][0]["members"]
        assert members[0]["part"] == -1 and members[0]["sign"] == 1
        assert ses.flags["parts_extra"] == {"C9": 1}
        assert part_of_labels(ses.flags)["O1A"] == -1
        u = _undo(ses, "O1A")
        assert u.ok, u.error
        assert ses.flags["disorder_groups"][0]["members"][0]["part"] == 1
        # the split's own origin is intact and still first in line
        assert ses.flags["disorder_origins"][0]["fvar_index"] == 2
        assert len(ses.flags["disorder_origins"]) == 2

    def test_clear_part_then_undo_restores_the_previous_block(self):
        ses = _session({"parts_extra": {"C9": 1}})
        r = _edit(ses, {"action": "clear_part", "atoms": ["C9"]})
        assert r.ok, r.error
        assert "parts_extra" not in ses.flags
        assert r.summary["parts"]["parts"] == {"C9": None}
        u = _undo(ses, "C9")
        assert u.ok, u.error
        assert ses.flags["parts_extra"] == {"C9": 1}

    def test_set_part_zero_clears(self):
        ses = _session({"parts_extra": {"C9": 1}})
        assert _edit(ses, {"action": "set_part", "atoms": ["C9"], "part": 0}).ok
        assert "parts_extra" not in ses.flags

    def test_set_part_without_an_integer_changes_nothing(self):
        ses = _session({"parts_extra": {"C9": 1}})
        r = _edit(ses, {"action": "reassign", "atoms": ["C1"], "element": "N"},
                  {"action": "set_part", "atoms": ["C9"], "part": 1.5})
        assert not r.ok and "integer" in r.error
        assert ses.flags == {"parts_extra": {"C9": 1}}
        assert ses.model.scatterers()[0].scattering_type == "C"
        r = _edit(ses, {"action": "set_part", "atoms": ["C9"]})
        assert not r.ok and "nothing was changed" in r.error

    def test_delete_and_part_edit_in_one_call_leaves_no_stale_part(self):
        ses = _session()
        r = _edit(ses, {"action": "set_part", "atoms": ["C9"], "part": 2},
                  {"action": "delete", "atoms": ["C9"]})
        assert r.ok, r.error
        assert "parts_extra" not in ses.flags
        assert ses.flags["disorder_origins"][-1]["stale"] is True


# ==========================================================================
class TestPreflight:
    SPECS = [
        {"kind": "DFIX", "atoms": [["C1", "C2"]], "target": 1.5},
        {"kind": "DFIX", "atoms": [["C1", "C3"]], "target": 1.5},
        {"kind": "FLAT", "atoms": ["C1", "C2", "C3", "C4"]},
        {"kind": "SADI", "atoms": [["C1", "C3"], ["C2", "C3"]]},
        {"kind": "SIMU", "atoms": ["C1", "C2"]},
        {"kind": "EADP", "atoms": ["C1", "C2"]},
    ]

    def test_cross_part_terms_are_named_and_the_rest_apply(self):
        from crystalpilot.refine.restraints import preflight
        ses = _session({"parts_extra": {"C1": 1, "C2": 2}})
        pf = preflight(ses.model, self.SPECS, ses.flags)
        assert pf["requested"] == 6
        conflicts = pf["shelx_part_conflicts"]
        assert [c["kind"] for c in conflicts] == ["DFIX", "FLAT"]
        assert conflicts[0]["atoms"] == ["C1", "C2"]
        assert conflicts[0]["parts"] == [1, 2]
        assert conflicts[0]["rule"] == "would_be_ignored_by_shelxl"
        assert conflicts[1]["parts"] == [1, 2, 0, 0]
        assert pf["not_representable"] == [
            {"kind": "EADP", "reason": pf["not_representable"][0]["reason"]}]
        assert "EADP" in pf["not_representable"][0]["reason"]
        assert pf["n_geometry"] and pf["applied_in_process"]
        assert any(a.startswith("DFIX") for a in pf["applied_in_process"])

    def test_component_sign_does_not_split_a_component(self):
        from crystalpilot.refine.restraints import preflight
        ses = _session({"parts_extra": {"C1": 1, "C2": -1}})
        pf = preflight(ses.model, self.SPECS[:1], ses.flags)
        assert pf["shelx_part_conflicts"] == []

    def test_group_membership_wins_over_parts_extra(self):
        flags = {"disorder_groups": [{"fvar_index": 2, "value": 0.5, "members": [
                     {"label": "C1", "part": 1, "sign": 1, "mult": 1.0}]}],
                 "parts_extra": {"C1": 2, "C2": 2}}
        assert part_of_labels(flags) == {"C1": 1, "C2": 2}

    def test_tool_is_read_only_and_reports(self):
        from crystalpilot.mcp.server import READ_ONLY_TOOLS
        from crystalpilot.refine.tools_extra import PreflightRestraints
        assert "preflight_restraints" in READ_ONLY_TOOLS
        ses = _session({"parts_extra": {"C1": 1, "C2": 2},
                        "restraints": [self.SPECS[1]]})
        tool = PreflightRestraints(None)
        r = tool.run(SimpleNamespace(session=ses), restraints=self.SPECS[:1])
        assert r.ok, r.error
        assert r.summary["source"] == "proposed"
        assert r.summary["verdict"] == "findings"
        assert len(r.summary["restraints_preflight"]["shelx_part_conflicts"]) == 1
        assert "PART" in r.summary["applicability"][0]
        # the session's own list was neither read as the target nor changed
        assert ses.flags["restraints"] == [self.SPECS[1]]
        r2 = tool.run(SimpleNamespace(session=ses))
        assert r2.ok and r2.summary["source"] == "session"
        assert r2.summary["verdict"] == "clean"
        assert r2.summary["restraints_preflight"]["requested"] == 1

    def test_set_restraints_registers_and_warns(self):
        from crystalpilot.refine.tools_extra import SetRestraints
        ses = _session({"parts_extra": {"C1": 1, "C2": 2}})
        r = SetRestraints(None).run(SimpleNamespace(session=ses), action="add",
                                    restraints=self.SPECS[:2])
        assert r.ok, r.error
        assert r.summary["added"] == 2
        assert len(ses.flags["restraints"]) == 2
        pf = r.summary["restraints_preflight"]
        assert len(pf["shelx_part_conflicts"]) == 1
        assert pf["shelx_part_conflicts"][0]["atoms"] == ["C1", "C2"]
        assert "will not apply" in r.summary["applicability"][0]
        # a clean list carries the block but no applicability line
        ses2 = _session()
        r2 = SetRestraints(None).run(SimpleNamespace(session=ses2), action="add",
                                     restraints=self.SPECS[1:2])
        assert r2.ok and r2.summary["restraints_preflight"]["shelx_part_conflicts"] == []
        assert "applicability" not in r2.summary


# ==========================================================================
def test_preflight_tool_is_in_the_template_and_has_a_card():
    import re
    from crystalpilot.workbench.agents_md import render_agents_md
    assert "preflight_restraints" in render_agents_md()
    src = (REPO / "ui" / "src" / "lib" / "toolCards.tsx").read_text(encoding="utf-8")
    assert re.search(r"^  preflight_restraints: \{", src, re.M)


@pytest.mark.parametrize("action", ["set_part", "clear_part"])
def test_actions_are_in_the_schema(action):
    assert action in EditAtoms.params_schema["properties"]["operations"][
        "items"]["properties"]["action"]["enum"]
