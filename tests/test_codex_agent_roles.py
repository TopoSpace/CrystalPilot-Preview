"""R7 groundwork (docs/PLAN-2026-09-04-round2.md "R7"; see
docs/R7-SUBAGENT-GROUNDWORK.md for the sourced writeup behind every field
choice here): the four read-only Codex sub-agent role files under
codex-home/agents/ must parse, must carry the fields the workbench design
relies on, and must never let a mutating tool name leak into their
instructions - these roles are only meaningful as a *prompt-level* second
line of defense, since the actual enforcement lever is the MCP server own
CRYSTALPILOT_MCP_READONLY gate (crystalpilot/workbench/core.py
_mcp_overrides), not anything in this TOML.

This test does NOT start Codex, does not call any model/gateway, and does
not touch codex-home/config.toml.
"""
from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from crystalpilot.refine.registry import MUTATING_TOOLS

ROLES_DIR = Path(__file__).resolve().parents[1] / "crystalpilot" / "workbench" / "agent_roles"

#: role name -> expected model_reasoning_effort. Per the R7 task spec:
#: space_group/validation are narrower, more mechanical audits; chemistry
#: /density reason over more ambiguous evidence and get the higher tier.
EXPECTED_EFFORT = {
    "space_group": "medium",
    "chemistry": "high",
    "density": "high",
    "validation": "medium",
    # round-3 R7: the fifth role, the same specialty consult_specialist
    # already offered; plans over node history, so the higher tier
    "refinement_strategy": "high",
}

REQUIRED_FIELDS = ("name", "description", "developer_instructions",
                   "sandbox_mode", "model_reasoning_effort")


def _role_files() -> list[Path]:
    if not ROLES_DIR.is_dir():
        return []
    return sorted(ROLES_DIR.glob("*.toml"))


def _load(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def test_roles_dir_has_exactly_the_expected_roles():
    names = {p.stem for p in _role_files()}
    assert names == set(EXPECTED_EFFORT), (
        f"expected {sorted(EXPECTED_EFFORT)} under {ROLES_DIR}, found "
        f"{sorted(names)}")


@pytest.mark.parametrize("path", _role_files(), ids=lambda p: p.stem)
def test_role_toml_parses(path: Path):
    data = _load(path)
    assert isinstance(data, dict)


@pytest.mark.parametrize("path", _role_files(), ids=lambda p: p.stem)
def test_role_has_required_fields(path: Path):
    data = _load(path)
    for field in REQUIRED_FIELDS:
        assert field in data, f"{path.name} missing required field {field!r}"
        assert str(data[field]).strip(), (
            f"{path.name} field {field!r} is empty")


@pytest.mark.parametrize("path", _role_files(), ids=lambda p: p.stem)
def test_role_name_matches_filename(path: Path):
    # spawn_agent(agent_type=...) resolves against the role's name field
    # (GitHub openai/codex#26408 repro); keeping name == filename stem
    # avoids a foot-gun where the file is found by directory listing but
    # not by the name codex actually matches on.
    data = _load(path)
    assert data["name"] == path.stem


@pytest.mark.parametrize("path", _role_files(), ids=lambda p: p.stem)
def test_role_is_sandboxed_read_only(path: Path):
    data = _load(path)
    assert data["sandbox_mode"] == "read-only"


@pytest.mark.parametrize("path", _role_files(), ids=lambda p: p.stem)
def test_role_effort_matches_task_ladder(path: Path):
    data = _load(path)
    assert data["model_reasoning_effort"] == EXPECTED_EFFORT[path.stem]


@pytest.mark.parametrize("path", _role_files(), ids=lambda p: p.stem)
def test_role_omits_model_so_it_inherits_from_the_parent(path: Path):
    data = _load(path)
    assert "model" not in data, (
        f"{path.name}: leave model unset so the subagent inherits the "
        f"parent model (see docs/R7-SUBAGENT-GROUNDWORK.md section b)")


@pytest.mark.parametrize("path", _role_files(), ids=lambda p: p.stem)
def test_instructions_never_name_a_mutating_tool(path: Path):
    data = _load(path)
    instructions = data["developer_instructions"]
    hits = [t for t in MUTATING_TOOLS if t in instructions]
    assert not hits, (
        f"{path.name} instructions mention mutating tool(s) {hits} - "
        f"refer to forbidden tools generically, never by name")


@pytest.mark.parametrize("path", _role_files(), ids=lambda p: p.stem)
def test_instructions_length_budget(path: Path):
    data = _load(path)
    n = len(data["developer_instructions"])
    assert n <= 1600, (
        f"{path.name}: developer_instructions is {n} chars, over the "
        f"~1500 char budget the R7 task set")


# --------------------------------------------------------------------------
# per-project role files (workbench/agent_roles.py): written only while the
# delegation tier is active, each with its own READ-ONLY MCP override
# --------------------------------------------------------------------------

def test_render_role_carries_the_project_and_the_readonly_gate(tmp_path):
    from crystalpilot.workbench.agent_roles import (ENGINE_PY, ROLE_MARKER,
                                                    render_role)
    text = render_role("validation", tmp_path)
    assert text.startswith(ROLE_MARKER + "\n")
    d = tomllib.loads(text)
    assert d["name"] == "validation" and d["sandbox_mode"] == "read-only"
    mcp = d["mcp_servers"]["crystalpilot"]
    assert mcp["command"] == str(ENGINE_PY)
    assert mcp["args"][:4] == ["-X", "utf8", "-m", "crystalpilot.mcp"]
    assert mcp["args"][-2:] == ["--project", str(tmp_path.resolve())]
    assert mcp["env"]["CRYSTALPILOT_MCP_READONLY"] == "1"
    assert mcp["env"]["PYTHONUTF8"] == "1"
    assert "CRYSTALPILOT_KNOWLEDGE_MODE" not in mcp["env"]
    d2 = tomllib.loads(render_role("validation", tmp_path, "tools_only"))
    assert d2["mcp_servers"]["crystalpilot"]["env"][
        "CRYSTALPILOT_KNOWLEDGE_MODE"] == "tools_only"
    # no model given: the role file has no model key (codex picks its own
    # default - what happened on the R7 A2 cell, gpt-5.5 for a GLM parent)
    assert "model" not in d and "model" not in d2
    d3 = tomllib.loads(render_role("validation", tmp_path, None, "z-ai/glm-5.3-flash"))
    assert d3["model"] == "z-ai/glm-5.3-flash"
    assert d3["mcp_servers"]["crystalpilot"]["args"][-2:] == ["--project", str(tmp_path.resolve())]
    assert d3["sandbox_mode"] == "read-only"


def test_effective_model_prefers_the_override(tmp_path):
    import tomllib as _t
    from crystalpilot.workbench.agent_roles import (ENGINE_ROOT, effective_model,
                                                    ensure_agent_roles)
    assert effective_model({"model_override": "z-ai/glm-5.3"}) == "z-ai/glm-5.3"
    cfg = _t.loads((ENGINE_ROOT / "codex-home" / "config.toml").read_text(encoding="utf-8"))
    assert effective_model({}) == cfg["model"] and effective_model(None) == cfg["model"]
    r = ensure_agent_roles(tmp_path, True, None, "z-ai/glm-5.3-flash")
    assert r["model"] == "z-ai/glm-5.3-flash"
    text = (tmp_path / ".codex" / "agents" / "density.toml").read_text(encoding="utf-8")
    assert tomllib.loads(text)["model"] == "z-ai/glm-5.3-flash"
    # a model change rewrites the files
    assert sorted(ensure_agent_roles(tmp_path, True, None, "z-ai/glm-5.3")["written"]) == sorted(r["written"])


def test_ensure_agent_roles_writes_then_removes_and_keeps_foreign(tmp_path):
    from crystalpilot.workbench.agent_roles import (ROLE_MARKER,
                                                    ensure_agent_roles,
                                                    role_names)
    d = tmp_path / ".codex" / "agents"
    d.mkdir(parents=True)
    (d / "mine.toml").write_text('name = "mine"\n', encoding="utf-8")
    r = ensure_agent_roles(tmp_path, True)
    assert sorted(r["written"]) == role_names() == [
        "chemistry", "density", "refinement_strategy", "space_group", "validation"]
    assert r["kept_foreign"] == ["mine"]
    for n in role_names():
        assert (d / f"{n}.toml").read_text(encoding="utf-8").startswith(ROLE_MARKER)
    # idempotent
    r = ensure_agent_roles(tmp_path, True)
    assert r["written"] == [] and sorted(r["current"]) == role_names()
    # a stale file we wrote is rewritten (project path changed => content)
    (d / "density.toml").write_text(ROLE_MARKER + "\nname = 'density'\n",
                                    encoding="utf-8")
    assert ensure_agent_roles(tmp_path, True)["written"] == ["density"]
    # off: ours go, the foreign one stays
    r = ensure_agent_roles(tmp_path, False)
    assert sorted(r["removed"]) == role_names()
    assert sorted(p.name for p in d.glob("*.toml")) == ["mine.toml"]
    assert r["kept_foreign"] == ["mine"]


def test_delegation_rule():
    from crystalpilot.workbench.agent_roles import (delegation_active,
                                                    normalize_subagent_policy)
    assert delegation_active(None, "xhigh", "xhigh")
    assert delegation_active("top_tier", "xhigh", "xhigh")
    assert not delegation_active("top_tier", "high", "xhigh")
    assert not delegation_active("off", "xhigh", "xhigh")
    # round-3 R0: the tier is a set - max/ultra sit above xhigh and keep
    # delegation on; below the floor stays off
    tier = ("xhigh", "max", "ultra")
    assert delegation_active("top_tier", "max", tier)
    assert delegation_active("top_tier", "ultra", tier)
    assert delegation_active(None, "xhigh", tier)
    assert not delegation_active("top_tier", "high", tier)
    assert not delegation_active("off", "max", tier)
    assert normalize_subagent_policy(" OFF ") == "off"
    with pytest.raises(ValueError):
        normalize_subagent_policy("always")


def test_delegation_tiers():
    """Round-3 R7: policy x effort -> off | hint | aggressive. `aggressive`
    is top_tier plus a proactive variant at the aggressive efforts; it
    never activates below the top tier."""
    from crystalpilot.workbench.agent_roles import (SUBAGENT_POLICIES,
                                                    delegation_active,
                                                    delegation_tier)
    tier = ("xhigh", "max", "ultra")
    agg = ("max", "ultra")
    assert SUBAGENT_POLICIES == ("top_tier", "aggressive", "off")
    assert delegation_tier("top_tier", "xhigh", tier, agg) == "hint"
    assert delegation_tier("top_tier", "max", tier, agg) == "hint"
    assert delegation_tier("aggressive", "xhigh", tier, agg) == "hint"
    assert delegation_tier("aggressive", "max", tier, agg) == "aggressive"
    assert delegation_tier("aggressive", "ultra", tier, agg) == "aggressive"
    assert delegation_tier("aggressive", "high", tier, agg) == "off"
    assert delegation_tier("off", "ultra", tier, agg) == "off"
    assert delegation_tier(None, "xhigh", tier, agg) == "hint"
    # without an aggressive set the policy degrades to top_tier
    assert delegation_tier("aggressive", "max", tier) == "hint"
    assert delegation_active("aggressive", "max", tier, agg)
    assert not delegation_active("aggressive", "high", tier, agg)


def test_roles_warm_up_their_tools_first():
    """Every role opens with the tool warm-up (one cheap call before the
    audit): codex rebuilds a turn's tool list after each tool round-trip,
    so the crystallography tools appear on the child's second model call
    even when the parent skipped the READY handshake (A2', 2026-09-06)."""
    import tomllib
    from crystalpilot.workbench.agent_roles import ROLES_DIR, role_names
    for name in role_names():
        d = tomllib.loads((ROLES_DIR / f"{name}.toml").read_text(encoding="utf-8"))
        body = d["developer_instructions"]
        assert body.lstrip().startswith("开工第一步"), name
        assert "list_mcp_resources" in body and "mcp__crystalpilot" in body, name
