"""AGENTS.md template drift guards (v22 slimming).

The template is paid every agent turn, so it stays lean - but every
registered MCP tool must remain discoverable in its tool map, and the
skill-layer pointers that received the downshifted protocols must not
silently vanish.
"""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _registered_names() -> set[str]:
    from crystalpilot.refine.registry import refinement_registry
    from crystalpilot.refine.tools_analysis import register_analysis_tools
    from crystalpilot.refine.tools_disorder import register_disorder_tools
    from crystalpilot.refine.tools_extra import register_refine_tools
    from crystalpilot.refine.tools_cap import register_cap_tools
    from crystalpilot.refine.tools_frames import register_frames_tools
    from crystalpilot.refine.tools_skills import register_skills_tools
    from crystalpilot.refine.tools_batch import register_batch_tools
    from crystalpilot.refine.tools_probe import register_probe_tools
    reg = refinement_registry(None)
    register_refine_tools(reg, None)
    register_analysis_tools(reg, None)
    register_disorder_tools(reg, None)
    register_frames_tools(reg, None)
    register_cap_tools(reg, None)
    register_skills_tools(reg, None)
    register_batch_tools(reg, None)
    register_probe_tools(reg, None)
    return {s["name"] for s in reg.specs()}


def _registered_specs_text() -> str:
    """Every registered tool's name, description and parameter schema as one
    string - what the agent reads besides the template."""
    import json

    from crystalpilot.refine.registry import refinement_registry
    from crystalpilot.refine.tools_analysis import register_analysis_tools
    from crystalpilot.refine.tools_disorder import register_disorder_tools
    from crystalpilot.refine.tools_extra import register_refine_tools
    from crystalpilot.refine.tools_cap import register_cap_tools
    from crystalpilot.refine.tools_frames import register_frames_tools
    from crystalpilot.refine.tools_skills import register_skills_tools
    from crystalpilot.refine.tools_batch import register_batch_tools
    from crystalpilot.refine.tools_probe import register_probe_tools
    reg = refinement_registry(None)
    for f in (register_refine_tools, register_analysis_tools,
              register_disorder_tools, register_frames_tools,
              register_cap_tools, register_skills_tools,
              register_batch_tools, register_probe_tools):
        f(reg, None)
    return json.dumps(reg.specs(), ensure_ascii=False)


def test_every_registered_tool_is_in_the_template():
    from crystalpilot.workbench.agents_md import render_agents_md
    text = render_agents_md()
    missing = {n for n in _registered_names() if n not in text}
    assert not missing, f"tool map lost: {sorted(missing)}"


def test_referenced_skill_cards_exist():
    """Every skill name the template tells agents to read must exist on
    disk (a pointer to a deleted card is worse than no pointer)."""
    import re

    from crystalpilot.workbench.agents_md import render_agents_md
    text = render_agents_md()
    have = {p.stem for p in (REPO / "knowledge" / "skills").glob("*.md")}
    have |= {p.stem for p in
             (REPO / "knowledge").rglob("*.md")}          # rulesets etc.
    body = "\n".join(ln for ln in text.splitlines()
                     if "crystalpilot-agents-v" not in ln)
    # Worktree slugs in the absolute interpreter path are not skill names.
    body = body.replace(str(REPO), "")
    referenced = set(re.findall(r"技能 ([a-z0-9-]{4,})", body))
    referenced |= {m for m in re.findall(r"\b([a-z]+(?:-[a-z0-9]+){2,})\b",
                                         body)}
    dangling = {r for r in referenced if "-" in r and r not in have}
    assert not dangling, f"dangling skill refs: {sorted(dangling)}"


def test_template_stays_lean_and_keeps_teeth():
    from crystalpilot.workbench.agents_md import (VERSION_MARKER,
                                                  render_agents_md)
    text = render_agents_md()
    assert VERSION_MARKER in text
    # budget: the v21 template was 11.3 KB; slimming must not regress.
    # Raised 8500 -> 8800 on 2026-09-01: the tool count grew 56 -> 62 and
    # the every-tool-in-template test forces one entry each; after three
    # trim passes the next cut would cost information, not fat.
    # Raised 8800 -> 9400 on 2026-09-02 (v28): the deferred-tool-surface
    # rule (4/32 pa1 cells lost to the old CLI clause), the SHELXT budget
    # rule and the element-by-chemistry rule are 32-run lessons; the CLI
    # recipe they displace was the thing costing cells.
    # Raised 9400 -> 12500 on 2026-09-02 (v29): six new tools and five new
    # modes (the pa1 fix wave) each need their one-line entry, and the
    # readiness / absorption-edge rule is what would have stopped the two
    # wrong-metal deliveries. Every entry replaces a hand-rolled loop the
    # agents ran for minutes; the template still costs less than one such
    # loop's tool output.
    # Raised 12500 -> 14000 on 2026-09-03 (v31): the second pa2/pa3 fix
    # wave - ghost verdicts with a sensitivity floor and a ledger,
    # probe_site + guest searches before the mask, the metal-bonded C/N
    # audit, SHELXT budget/grace/detach - each replaces a way an agent
    # threw a correct solution or a real atom away; the SHELXT entry alone
    # displaces the "raise -m" reflex that cost three cage lanes.
    # Measured WITHOUT the interpolated absolute paths: the identical
    # template rendered from a git worktree 42 characters deeper came out
    # at 14010 and tripped the old `len(text) < 14000` guard (2026-09-03,
    # T1.1 branch) - a fact about the checkout location, not the template.
    from crystalpilot.workbench.agents_md import ENGINE_PY, ENGINE_ROOT
    kb_dir = str(ENGINE_ROOT / "knowledge" / "expert-cases")
    path_chars = (text.count(str(ENGINE_PY)) * len(str(ENGINE_PY))
                  + text.count(kb_dir) * len(kb_dir))
    body = len(text) - path_chars
    # v33 (2026-09-04): 13 968 -> ~7 500 chars after the ka1 ablation showed
    # the judgment prose was redundant with the tool returns. The bar is
    # set just above the v33 size so growth is a deliberate decision again.
    # v35 (2026-09-04, round-2 R5): analyze_packing gets its one-line entry;
    # the owner approved ~9000 for the round (one new tool, no new prose).
    assert body < 9000, f"template regrew to {body} chars (paths excluded)"
    # hard rules that must never be slimmed away
    for tooth in ("诚实守则", "专家评审铁律", "幽灵原子禁令", "ASU 连贯性",
                  "无序纪律",            # v34: refinement decides a split
                  "溶剂纪律", "testAPI.txt", "慢≠卡死", "等用户审批",
                  "必须先 run_shelxl", "VALIDATION.md",
                  "工具面是延迟加载的", "串行执行", "元素身份由化学定"):
        assert tooth.replace("\n  ", "") in text.replace("\n  ", ""), tooth
    # the licence four pa1 agents used to walk away from the tool face
    assert "后备 CLI" not in text
    assert "crystalpilot.cli solve" not in text


def test_every_registered_tool_has_a_ui_card():
    """The chat stream humanizes tools from ui/src/lib/toolCards.tsx; a
    tool with no card renders its raw JSON payload. That is how
    view_structure and situation_report - the two tools whose whole point
    is a picture - showed up as JSON blobs until 2026-09."""
    import re
    src = (REPO / "ui" / "src" / "lib" / "toolCards.tsx").read_text(
        encoding="utf-8")
    carded = set(re.findall(r"^  ([a-z_0-9]+): \{", src, re.M))
    missing = _registered_names() - carded - {
        # deliberately generic: registered only when the user opts in
        "consult_specialist",
    }
    assert not missing, f"tools with no UI card: {sorted(missing)}"


# ----------------------------------------------------------- knowledge_mode
SKILL_TOOLS = {"list_skills", "read_skill", "save_skill", "delete_skill"}


def test_tools_only_variant_is_an_operational_contract():
    """ka1 ablation arm A: the operational contract + honesty rules and
    NOTHING that tells the agent how to judge. Every phrase in `judgment`
    is a v32 rule or a skill-layer pointer; if one leaks in, the arm no
    longer measures what it claims to."""
    from crystalpilot.workbench.agents_md import (VERSION_MARKER,
                                                  VERSION_MARKER_TOOLS_ONLY,
                                                  render_agents_md)
    text = render_agents_md("tools_only")
    assert text.startswith(VERSION_MARKER_TOOLS_ONLY)
    assert VERSION_MARKER not in text
    for tooth in ("工具面是延迟加载的", "串行执行", "等用户审批", "慢≠卡死",
                  "testAPI.txt", "诚实守则", "VALIDATION.md", "SUMMARY.md",
                  "finalize_delivery", "run_checkcif", "write_outputs",
                  "不做静默改判", "unresolved"):
        assert tooth in text, tooth
    judgment = ("技能", "skill", "list_skills", "read_skill", "GooF", "R1<",
                "0.05", "0.10", "0.68", "专家评审铁律", "幽灵原子", "溶剂纪律",
                "ASU 连贯性", "孪晶", "吸收边", "element_scan", "ghost_test",
                "质量标尺", "后备 CLI", "crystalpilot.cli solve",
                "estimate_resolution", "screen_space_groups")
    for phrase in judgment:
        assert phrase not in text, phrase
    assert not SKILL_TOOLS & {w.strip("`(),") for w in text.split()}
    # a contract, not a manual: well under a fifth of the full template
    assert len(text.encode("utf-8")) < 5000, len(text.encode("utf-8"))


def test_knowledge_mode_values_are_validated():
    import pytest

    from crystalpilot.workbench.agents_md import (KNOWLEDGE_MODES,
                                                  normalize_knowledge_mode)
    assert normalize_knowledge_mode(None) == "full"
    assert normalize_knowledge_mode("") == "full"
    assert set(KNOWLEDGE_MODES) == {"full", "tools_only"}
    with pytest.raises(ValueError):
        normalize_knowledge_mode("tools-only")


def test_byte_budget_including_repo_root_pointer():
    """codex 0.147 caps the concatenated AGENTS.md chain at
    project_doc_max_bytes = 32768 BYTES (the old guard counted chars, and
    the v32 template is 26 KB in UTF-8). The repo-root file rides along
    for any project opened inside the repo, so it is budgeted here too -
    and it must stay a pointer, never a second set of instructions."""
    from crystalpilot.workbench.agents_md import render_agents_md
    root = REPO / "AGENTS.md"
    assert root.is_file(), "repo-root AGENTS.md pointer must be tracked"
    root_bytes = root.read_bytes()
    assert len(root_bytes) < 1024, "repo-root AGENTS.md must stay a pointer"
    root_text = root_bytes.decode("utf-8")
    for leak in ("Typical quality bars", "crystalpilot.cli solve", "R1",
                 "solve <data.hkl>"):
        assert leak not in root_text, leak
    for mode in ("full", "tools_only"):
        total = len(render_agents_md(mode).encode("utf-8")) + len(root_bytes)
        assert total < 32768 - 2048, f"{mode}: {total} bytes"


def test_ensure_agents_md_three_states(tmp_path):
    from crystalpilot.workbench.agents_md import (VERSION_MARKER,
                                                  VERSION_MARKER_TOOLS_ONLY,
                                                  ensure_agents_md,
                                                  render_agents_md)
    f = tmp_path / "AGENTS.md"
    # absent -> written
    r = ensure_agents_md(tmp_path)
    assert r["action"] == "written" and r["mode"] == "full"
    assert f.read_text(encoding="utf-8") == render_agents_md("full")
    # current -> untouched
    assert ensure_agents_md(tmp_path)["action"] == "current"
    # stale CrystalPilot copy -> rewritten
    f.write_text("<!-- crystalpilot-agents-v27 -->\nold\n", encoding="utf-8")
    assert ensure_agents_md(tmp_path)["action"] == "written"
    assert VERSION_MARKER in f.read_text(encoding="utf-8")
    # mode switch both ways -> rewritten with the other marker
    r = ensure_agents_md(tmp_path, "tools_only")
    assert r["action"] == "written"
    assert f.read_text(encoding="utf-8").startswith(VERSION_MARKER_TOOLS_ONLY)
    assert ensure_agents_md(tmp_path, "tools_only")["action"] == "current"
    assert ensure_agents_md(tmp_path, "full")["action"] == "written"
    # the user's own marker-less file -> kept, with a warning
    f.write_text("# my own instructions\n", encoding="utf-8")
    r = ensure_agents_md(tmp_path, "tools_only")
    assert r["action"] == "kept_foreign" and r["warning"]
    assert f.read_text(encoding="utf-8") == "# my own instructions\n"


def test_agents_md_record_reports_chain_and_hash(tmp_path):
    """Campaign accounting: which template ran (by hash) and what else
    codex would inject. Inside a fake repo the toplevel's AGENTS.md is in
    the chain; outside, only the project's own."""
    from crystalpilot.workbench.agents_md import (agents_md_record,
                                                  agents_md_sha256,
                                                  ensure_agents_md)
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / "AGENTS.md").write_text("stale root rules\n", encoding="utf-8")
    proj = repo / "wb" / "p1"
    proj.mkdir(parents=True)
    ensure_agents_md(proj, "tools_only")
    rec = agents_md_record(proj, "tools_only")
    assert rec["agents_matches_template"]
    assert rec["agents_sha256"] == rec["agents_expected_sha256"]
    assert rec["agents_version"].startswith("<!-- crystalpilot-agents-tools")
    assert rec["root_agents_sha256"] is not None
    assert [c["is_project"] for c in rec["agents_chain"]] == [False, True]
    # same project under the wrong mode label: hash mismatch is visible
    assert not agents_md_record(proj, "full")["agents_matches_template"]
    assert agents_md_sha256("full") != agents_md_sha256("tools_only")
    # a project whose nearest toplevel has no AGENTS.md: nothing rides
    # along (pytest's basetemp sits inside the engine repo, whose root
    # pointer would otherwise show up here - which is exactly the pa1-pa4
    # contamination this function exists to make visible)
    outside = tmp_path / "campaigns" / "p2"
    outside.mkdir(parents=True)
    (tmp_path / "campaigns" / ".git").mkdir()
    ensure_agents_md(outside)
    rec2 = agents_md_record(outside)
    assert rec2["root_agents_sha256"] is None
    assert len(rec2["agents_chain"]) == 1


def test_registry_omits_skill_tools_in_tools_only_mode(monkeypatch):
    """The MCP process learns the arm from CRYSTALPILOT_KNOWLEDGE_MODE
    (set by workbench.core._mcp_overrides); in tools_only the four skill
    tools are simply not registered, so the agent cannot read a card."""
    from crystalpilot.refine.registry import knowledge_mode
    from crystalpilot.refine.tools_skills import register_skills_tools
    from crystalpilot.tools.base import ToolRegistry

    def _names(env: str | None) -> set[str]:
        if env is None:
            monkeypatch.delenv("CRYSTALPILOT_KNOWLEDGE_MODE", raising=False)
        else:
            monkeypatch.setenv("CRYSTALPILOT_KNOWLEDGE_MODE", env)
        reg = ToolRegistry()
        # mirror refinement_registry's gate (it needs a project for the
        # optional modules; the gate itself is what is under test)
        if knowledge_mode() != "tools_only":
            register_skills_tools(reg, None)
        return {s["name"] for s in reg.specs()}

    assert SKILL_TOOLS <= _names(None)
    assert SKILL_TOOLS <= _names("full")
    assert not SKILL_TOOLS & _names("tools_only")


def test_mcp_overrides_carry_knowledge_mode(tmp_path, monkeypatch):
    monkeypatch.delenv("CRYSTALPILOT_DISABLE_MCP", raising=False)
    from crystalpilot.workbench.core import _mcp_overrides
    env_full = [o for o in _mcp_overrides(tmp_path) if ".env=" in o][0]
    assert "CRYSTALPILOT_KNOWLEDGE_MODE" not in env_full
    env_ro = [o for o in _mcp_overrides(tmp_path, readonly=True,
                                        knowledge_mode="tools_only")
              if ".env=" in o][0]
    assert env_ro.endswith("{PYTHONUTF8='1',CRYSTALPILOT_MCP_READONLY='1',"
                           "CRYSTALPILOT_KNOWLEDGE_MODE='tools_only'}")


def test_delegate_variant_is_a_distinct_marked_rendering(tmp_path):
    """Round-2 R7: the delegation section rides only in the `delegate`
    variant (top reasoning tier), under its own marker, within budget, and
    it states the two facts the probe established - fork_turns="none" and
    one read-only MCP process per sub-agent."""
    from crystalpilot.workbench.agents_md import (ENGINE_PY, ENGINE_ROOT,
                                                  VERSION_MARKER,
                                                  VERSION_MARKER_DELEGATE,
                                                  agents_md_record,
                                                  agents_md_sha256,
                                                  ensure_agents_md,
                                                  render_agents_md)
    plain = render_agents_md("full")
    deleg = render_agents_md("full", delegate=True)
    assert deleg.startswith(VERSION_MARKER_DELEGATE)
    assert VERSION_MARKER not in deleg and VERSION_MARKER_DELEGATE not in plain
    assert "可委派的只读审计子代理" in deleg and "可委派的只读审计子代理" not in plain
    for fact in ('fork_turns="none"', "只读", "space_group", "chemistry",
                 "density", "validation", "同时最多 2 个", "唯一的写者"):
        assert fact in deleg, fact
    kb_dir = str(ENGINE_ROOT / "knowledge" / "expert-cases")
    body = (len(deleg) - deleg.count(str(ENGINE_PY)) * len(str(ENGINE_PY))
            - deleg.count(kb_dir) * len(kb_dir))
    # 2026-09-06: +~120 chars two-step spawn (sub-agent first turn has no MCP tools)
    # 2026-09-08 (v43): 9200 -> 9500 for the delivery-flow rewrite the two
    # usertest sessions demanded (adopt-then-write_outputs, the seven
    # hand-over files, never move atoms to obtain a CIF, diagnostic seals)
    assert body < 9500, body
    assert agents_md_sha256("full") != agents_md_sha256("full", True)
    # the tools_only contract gets the same section under its own marker
    assert "可委派的只读审计子代理" in render_agents_md("tools_only", True)
    # ensure_agents_md swaps between the variants and the record says which
    f = tmp_path / "AGENTS.md"
    assert ensure_agents_md(tmp_path, "full", delegate=True)["action"] == "written"
    assert f.read_text(encoding="utf-8").startswith(VERSION_MARKER_DELEGATE)
    assert ensure_agents_md(tmp_path, "full", delegate=True)["action"] == "current"
    rec = agents_md_record(tmp_path, "full", delegate=True)
    assert rec["delegation"] is True and rec["agents_matches_template"]
    assert not agents_md_record(tmp_path, "full")["agents_matches_template"]
    assert ensure_agents_md(tmp_path, "full")["action"] == "written"
    assert f.read_text(encoding="utf-8").startswith(VERSION_MARKER)


def test_aggressive_variant_is_a_distinct_proactive_rendering(tmp_path):
    """Round-3 R7: the aggressive tier swaps the delegation hint for the
    proactive section (five roles, three fixed checkpoints, a verdict
    table, a wall-clock cap) under its own marker; the hint variant stays
    within the 9000 budget and the aggressive one within a deliberate
    extra allowance for its checkpoint text."""
    from crystalpilot.workbench.agents_md import (ENGINE_PY, ENGINE_ROOT,
                                                  VERSION_MARKER_AGGRESSIVE,
                                                  VERSION_MARKER_DELEGATE,
                                                  agents_md_record,
                                                  agents_md_sha256,
                                                  ensure_agents_md,
                                                  render_agents_md)
    hint = render_agents_md("full", delegate=True)
    agg = render_agents_md("full", delegate=True, aggressive=True)
    assert agg.startswith(VERSION_MARKER_AGGRESSIVE)
    assert VERSION_MARKER_DELEGATE not in agg and VERSION_MARKER_AGGRESSIVE not in hint
    assert "主动委派的只读审计子代理" in agg and "主动委派" not in hint
    for fact in ("refinement_strategy", "① 采纳空间群之前", "② 骨架建成、掩膜之前",
                 "③ 交付之前", "裁决表", "15 分钟", 'fork_turns="none"', "唯一的写者"):
        assert fact in agg, fact
    # the fifth role is named in the hint variant too
    assert "refinement_strategy" in hint
    kb_dir = str(ENGINE_ROOT / "knowledge" / "expert-cases")

    def body(t: str) -> int:
        return (len(t) - t.count(str(ENGINE_PY)) * len(str(ENGINE_PY))
                - t.count(kb_dir) * len(kb_dir))
    # 2026-09-06: +~120 chars in both variants for the two-step spawn (the
    # sub-agent's first turn has no MCP tools yet - R7 A2 evidence)
    assert body(hint) < 9500, body(hint)     # v43: see the delegate test
    assert body(agg) < 9800, body(agg)      # ~600 chars of checkpoints, max tier only
    for t in (hint, agg):
        assert 'message="回复 READY"' in t and "send_input" in t
    assert agents_md_sha256("full", True) != agents_md_sha256("full", True, True)
    # aggressive without delegate is not a thing: it renders the plain template
    assert render_agents_md("full", delegate=False, aggressive=True) == render_agents_md("full")
    info = ensure_agents_md(tmp_path, "full", delegate=True, aggressive=True)
    assert info["action"] == "written" and info["aggressive"] is True
    assert (tmp_path / "AGENTS.md").read_text(encoding="utf-8").startswith(VERSION_MARKER_AGGRESSIVE)
    # switching back to the hint variant rewrites; the record names the tier
    assert ensure_agents_md(tmp_path, "full", delegate=True)["action"] == "written"
    rec = agents_md_record(tmp_path, "full", delegate=True)
    assert rec["delegation_tier"] == "hint" and rec["agents_matches_template"]
    rec2 = agents_md_record(tmp_path, "full", delegate=True, aggressive=True)
    assert rec2["delegation_tier"] == "aggressive" and not rec2["agents_matches_template"]
    # the tools_only contract gets the proactive section under its own marker
    assert "主动委派的只读审计子代理" in render_agents_md("tools_only", True, True)
