"""The UI's CRYSTAL_MUTATING set (ui/src/state/threadReducer.ts) must be the
server's MUTATING_TOOLS (crystalpilot/refine/registry.py) plus a fixed list
of UI-only extras. The reducer uses the set for two things that go wrong
silently when the sets drift: the crystal pane refresh after a
model-changing tool, and the turn digest's metrics cursor (round-2 evidence
D20: a validate_structure score breakdown `r1: -13.4` was displayed as
"R1 0.2293→-13.4000" because read-only tool results were allowed to advance
the cursor; D21: model_disorder / set_twin / change_space_group did not
refresh the crystal pane)."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TS = ROOT / "ui" / "src" / "state" / "threadReducer.ts"

#: tools that change what the pane shows without auto-committing a node
UI_ONLY_EXTRAS = {
    "branch", "checkout", "create_start_model", "import_cif_model", "write_outputs",
}


def _ui_mutating() -> set[str]:
    src = TS.read_text(encoding="utf-8")
    m = re.search(r"CRYSTAL_MUTATING[^=]*=\s*new Set\(\[(.*?)\]\)", src, re.S)
    assert m, "CRYSTAL_MUTATING literal not found in threadReducer.ts"
    body = re.sub(r"//[^\n]*", "", m.group(1))  # drop line comments
    return set(re.findall(r'"([a-z_0-9]+)"', body))


def test_ui_mutating_set_mirrors_registry():
    from crystalpilot.refine.registry import MUTATING_TOOLS

    ui = _ui_mutating()
    missing = sorted(MUTATING_TOOLS - ui)
    extra = sorted(ui - MUTATING_TOOLS - UI_ONLY_EXTRAS)
    assert not missing and not extra, (
        "threadReducer.ts CRYSTAL_MUTATING drifted from registry.MUTATING_TOOLS: "
        f"missing={missing} unexpected extras={extra}"
    )
    assert UI_ONLY_EXTRAS <= ui


def test_ui_extras_are_not_server_mutating():
    """If the server starts auto-committing one of these, move it out of the
    extras list instead of listing it twice."""
    from crystalpilot.refine.registry import MUTATING_TOOLS

    assert not (UI_ONLY_EXTRAS & MUTATING_TOOLS)
