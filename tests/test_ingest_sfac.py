"""ka1 WP2 Part A: the ins file's SFAC/UNIT must be visible, disclosed as a
GUESS - never silently adopted as a formula.

ka1-org: run_shelxt failed 'no element list available' and Wilson stats
said 'no model/composition' on a session whose start.ins plainly declared
SFAC C H N O - nothing SAID the declaration existed. Separately, the cage
full arm ran ingest_vendor_data(source_dir=...) with no ins= while a real
start.ins with real SFAC sat right there unused, and the agent never
learned it existed.

Element-agnostic by construction: the placeholder rule (all UNIT counts
equal AND <= 20) is a syntactic property of the ins text, tested here
against several synthetic element lists (organic C/H/N/O, and a metal-
containing Zn/O/C/N set) - not tied to any particular test crystal.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from crystalpilot.refine import tools_frames as tf
from crystalpilot.refine.tools_extra import GetProjectBrief


# --------------------------------------------------------------------------- #
# ins_elements_declared: the placeholder rule, stated and tested
# --------------------------------------------------------------------------- #

def _ins(sfac: str, unit: str, cell="8.36 10.09 15.10 90 105.4 90") -> str:
    return (f"TITL synthetic\nCELL 0.71073 {cell}\n"
            "ZERR 1 0 0 0 0 0 0\nLATT 1\nSFAC " + sfac + "\nUNIT " + unit
            + "\nHKLF 4\nEND\n")


def test_uniform_small_unit_is_flagged_a_placeholder(tmp_path):
    p = tmp_path / "start.ins"
    p.write_text(_ins("C H N O", "1 1 1 1"), encoding="ascii")
    d = tf.ins_elements_declared(p)
    assert d["elements"] == ["C", "H", "N", "O"]
    assert d["unit"] == [1.0, 1.0, 1.0, 1.0]
    assert d["unit_is_placeholder"] is True
    assert d["source"] == "start.ins SFAC/UNIT"
    assert "not evidence" in d["note"]


def test_this_tools_own_generated_placeholder_is_caught(tmp_path):
    # the exact UNIT this tool's own gen_start branch writes (20 20 20 20) -
    # a naive '<=2' threshold would miss it, so the rule is '<= 20'
    p = tmp_path / "start.ins"
    p.write_text(_ins("C H N O", "20 20 20 20"), encoding="ascii")
    d = tf.ins_elements_declared(p)
    assert d["unit_is_placeholder"] is True


def test_uniform_unit_just_above_the_threshold_is_not_a_placeholder(tmp_path):
    # boundary of the stated rule: equal counts alone are not enough once
    # they exceed 20 - that shape stops looking like a cold-start template
    p = tmp_path / "start.ins"
    p.write_text(_ins("C H N O", "21 21 21 21"), encoding="ascii")
    d = tf.ins_elements_declared(p)
    assert d["unit_is_placeholder"] is False


def test_a_real_looking_formula_is_not_flagged(tmp_path):
    # metal-containing, unequal counts - a plausible real formula, and a
    # different element set from the organic C/H/N/O example (generality)
    p = tmp_path / "start.ins"
    p.write_text(_ins("Zn O C N", "4 32 16 8"), encoding="ascii")
    d = tf.ins_elements_declared(p)
    assert d["elements"] == ["Zn", "O", "C", "N"]
    assert d["unit"] == [4.0, 32.0, 16.0, 8.0]
    assert d["unit_is_placeholder"] is False


def test_missing_sfac_returns_none(tmp_path):
    p = tmp_path / "start.ins"
    p.write_text("TITL empty\nCELL 0.71073 8 9 10 90 90 90\n"
                 "ZERR 1 0 0 0 0 0 0\nLATT 1\nHKLF 4\nEND\n", encoding="ascii")
    assert tf.ins_elements_declared(p) is None


def test_missing_unit_card_is_disclosed_without_a_placeholder_verdict(tmp_path):
    p = tmp_path / "start.ins"
    p.write_text("TITL synthetic\nCELL 0.71073 8 9 10 90 90 90\n"
                 "ZERR 1 0 0 0 0 0 0\nLATT 1\nSFAC C H N O\nHKLF 4\nEND\n",
                 encoding="ascii")
    d = tf.ins_elements_declared(p)
    assert d["elements"] == ["C", "H", "N", "O"]
    assert d["unit"] == []
    assert d["unit_is_placeholder"] is False


# --------------------------------------------------------------------------- #
# ingest_vendor_data: the disclosure reaches context.json, and get_project_brief
# --------------------------------------------------------------------------- #

def _hkl_text(n=8) -> str:
    """A minimal valid (non-batched) SHELX hkl - >=5 fixed-width rows."""
    return "".join(f"{1:4d}{1:4d}{i:4d}{100.0:8.2f}{5.0:8.2f}\n"
                   for i in range(n))


def test_ingest_with_explicit_ins_puts_ins_elements_in_context(tmp_path):
    """Real RefineProject end to end: ingest_vendor_data(ins=...) -> the
    SFAC/UNIT disclosure survives into context.json AND into the rebuilt
    session's ephemeral ses.flags (SolveSession.flags resets to {} on every
    construction; project._build_session restores it fresh from context.json,
    the same pattern already used for symmetry_provenance/ins_guess)."""
    from crystalpilot.refine.project import RefineProject

    src = tmp_path / "vendor"
    src.mkdir()
    (src / "crystal.hkl").write_text(_hkl_text(), encoding="ascii")
    (src / "start.ins").write_text(_ins("C H N O", "1 1 1 1"), encoding="ascii")

    proj_dir = tmp_path / "proj"
    proj_dir.mkdir()
    p = RefineProject(proj_dir)
    r = p.invoke_tool("ingest_vendor_data",
                      {"source_dir": str(src), "ins": "start.ins"})
    assert r.ok, r.error

    ctx = json.loads((proj_dir / "context.json").read_text(encoding="utf-8"))
    ins_el = ctx["data"]["ins_elements"]
    assert ins_el["elements"] == ["C", "H", "N", "O"]
    assert ins_el["unit_is_placeholder"] is True

    # the rebuilt session already carries the disclosure (reload_inputs()
    # runs inside ingest_vendor_data, before invoke_tool returns)
    assert p.session is not None
    assert p.session.flags.get("ins_elements") == ins_el

    brief = p.invoke_tool("get_project_brief", {})
    assert brief.ok, brief.error
    assert brief.summary["data"]["elements_declared_in_ins"] == ins_el


def test_ingest_names_the_single_unused_ins_when_no_ins_param_is_given(tmp_path):
    """cage full arm: ingest_vendor_data(source_dir) with no ins= generated
    a placeholder while a real start.ins with real SFAC sat right there
    undeclared. The ins's stem deliberately does not match the hkl's stem
    so it is not auto-paired, and a .p4p supplies the cell for the
    generated-start path."""
    from crystalpilot.refine.project import RefineProject

    src = tmp_path / "vendor"
    src.mkdir()
    (src / "crystal.hkl").write_text(_hkl_text(), encoding="ascii")
    (src / "a.p4p").write_text(
        "CELL 8.3633 10.0945 15.0989 90.0 105.37 90.0 1227.9\n"
        "CELLSD 0.001 0.001 0.002 0.0 0.01 0.0 0.5\n"
        "SOURCE MO 0.71073 0.70930\n", encoding="ascii")
    # name deliberately does not pair with crystal.hkl by stem
    (src / "vendor_solution.ins").write_text(
        _ins("Zn O C N", "4 32 16 8"), encoding="ascii")

    proj_dir = tmp_path / "proj"
    proj_dir.mkdir()
    p = RefineProject(proj_dir)
    r = p.invoke_tool("ingest_vendor_data", {"source_dir": str(src)})
    assert r.ok, r.error
    unused = r.summary["ins_not_used"]
    assert unused["files"] == ["vendor_solution.ins"]
    assert "ins='vendor_solution.ins'" in unused["note"]
    assert "SFAC Zn O C N" in unused["note"]
    # the unused ins itself is a real-looking formula, not a placeholder
    # (only the phrase "instead of the generated placeholder" - referring
    # to what THIS tool generated - should appear, not a UNIT qualifier)
    assert "UNIT looks like a placeholder" not in unused["note"]


class _Nodes:
    def list_nodes(self, limit=50):
        return {"nodes": [], "active_node": None,
               "active_branch": "main", "branches": {}}


class _Proj:
    """Minimal GetProjectBrief fake, matching tests/test_project_brief.py's
    own _Proj (dir/context/hkl_path/start_model_path/merge_stats/nodes)."""
    def __init__(self, d: Path):
        d.mkdir(exist_ok=True)
        self.dir = d
        self.context = {}
        self.hkl_path = d / "crystal.hkl"
        self.start_model_path = d / "start.ins"
        self.merge_stats = None
        self.nodes = _Nodes()

    def experiment(self):
        return {}


def test_get_project_brief_omits_the_field_when_nothing_was_declared(tmp_path):
    """No ins_elements flag on the session (e.g. a project that started
    from frames, never from a vendor ins) -> the brief carries no
    elements_declared_in_ins key at all (nothing to disclose, so nothing
    printed - not a null placeholder)."""
    from cctbx import crystal, xray
    proj = _Proj(tmp_path / "p")
    cs = crystal.symmetry(unit_cell=(8, 9, 10, 90, 90, 90),
                          space_group_symbol="P 1")
    xs = xray.structure(crystal_symmetry=cs)
    ses = SimpleNamespace(model=xs, symmetry=cs,
                          dataset=SimpleNamespace(wavelength=0.71073),
                          flags={}, merge_info={})
    r = GetProjectBrief(proj).run(SimpleNamespace(session=ses))
    assert r.ok, r.error
    assert "elements_declared_in_ins" not in r.summary["data"]
