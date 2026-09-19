"""Per-project Codex sub-agent roles (round-2 R7).

Codex 0.147 reads custom agent roles from `<project>/.codex/agents/*.toml`
(project level) and `$CODEX_HOME/agents/*.toml` (personal level). CrystalPilot
writes PROJECT-level roles, for one reason: a role file may carry its own
`[mcp_servers.crystalpilot]` table, and that table needs the project path in
its argv - which is the only place the read-only MCP gate can live.

Probe evidence (2026-09-05, workdir/r7-probe/run2.log, throwaway project
H:/CrystalPilot-campaigns/r7-probe/p-probe):

* `spawn_agent(agent_type="validation_ro", fork_turns="none")` resolved the
  project-level role through the app-server path the workbench drives. The
  default full-history fork refuses a typed role ("Full-history forked agents
  inherit the parent agent type; omit agent_type, or spawn without a
  full-history fork") - the template tells the agent to pass
  fork_turns="none".
* The role's MCP override spawned a SEPARATE MCP server process for the
  sub-agent thread: .crystalpilot/mcp_server.jsonl shows pid 55932
  `readonly: true` beside the parent's pid 56808 `readonly: false`, and the
  sub-agent's `edit_atoms` came back `tool 'edit_atoms' is blocked: this
  workbench is in READ-ONLY mode`. A personal-level role WITHOUT the override
  (first probe, run.log) also got its own MCP process - a writable copy of
  the parent's - so personal-level roles are never written by this module
  and codex-home/agents stays empty.

Policy (owner's decision, plan R7): sub-agents are OFF by default. The roles
exist on disk only while the project's delegation tier is active (effective
reasoning effort == the top tier and the `subagents` setting is not "off");
when it is not, this module removes the files it wrote, so no typed role can
be spawned at all. Every file we write starts with ROLE_MARKER; a file
without it is the user's own and is never touched.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from ..runtime_paths import engine_python

ENGINE_ROOT = Path(__file__).resolve().parents[2]
ENGINE_PY = engine_python(ENGINE_ROOT)

#: package data: the four read-only audit roles (name = file stem)
ROLES_DIR = Path(__file__).resolve().parent / "agent_roles"

#: first line of every role file this module writes
ROLE_MARKER = "# crystalpilot-role-v1"

#: the `subagents` project setting (round-3 R7): "top_tier" (default)
#: writes the roles and injects the delegation HINT only at the top
#: reasoning tier; "aggressive" does the same and, at the aggressive
#: efforts (max/ultra), switches to the PROACTIVE variant (five audits at
#: fixed checkpoints); "off" never does anything. There is deliberately no
#: "always": below the top tier the model has no budget for consultants.
SUBAGENT_POLICIES = ("top_tier", "aggressive", "off")
DEFAULT_SUBAGENT_POLICY = "top_tier"
#: what a policy x effort combination yields
DELEGATION_TIERS = ("off", "hint", "aggressive")


def normalize_subagent_policy(v: str | None) -> str:
    s = (v or DEFAULT_SUBAGENT_POLICY).strip().lower()
    if s not in SUBAGENT_POLICIES:
        raise ValueError(
            f"subagents must be one of {SUBAGENT_POLICIES}, got {v!r}")
    return s


def delegation_tier(policy: str | None, effort: str | None,
                    top_effort: str | tuple[str, ...] | list[str],
                    aggressive_efforts: tuple[str, ...] | list[str] = ()
                    ) -> str:
    """The single rule that decides whether roles exist and which
    delegation paragraph the template carries: "off", "hint" (the
    top-tier reminder that consultants exist) or "aggressive" (the
    proactive checkpoints). `top_effort` is one effort name or the whole
    top tier (every effort at or above the tier floor - round-3 R0 added
    max/ultra above xhigh, and those must not switch delegation off);
    `aggressive_efforts` is the subset where the aggressive policy goes
    proactive (below it the policy behaves like top_tier)."""
    tops = (top_effort,) if isinstance(top_effort, str) else tuple(top_effort)
    pol = normalize_subagent_policy(policy)
    eff = effort or ""
    if pol == "off" or eff not in tops:
        return "off"
    if pol == "aggressive" and eff in tuple(aggressive_efforts):
        return "aggressive"
    return "hint"


def delegation_active(policy: str | None, effort: str | None,
                      top_effort: str | tuple[str, ...] | list[str],
                      aggressive_efforts: tuple[str, ...] | list[str] = ()
                      ) -> bool:
    """Roles exist and the template carries a delegation paragraph."""
    return delegation_tier(policy, effort, top_effort,
                           aggressive_efforts) != "off"


def role_names() -> list[str]:
    return sorted(p.stem for p in ROLES_DIR.glob("*.toml"))


def _toml_lit(s: str) -> str:
    """TOML literal string (single quotes): backslash-safe for Windows."""
    if "'" in s:
        raise ValueError(f"path contains a single quote: {s!r}")
    return f"'{s}'"


def _config_default_model() -> str | None:
    """The `model` of the isolated codex config (codex-home/config.toml),
    None when unreadable."""
    try:
        import tomllib
        cfg = tomllib.loads((ENGINE_ROOT / "codex-home" / "config.toml")
                            .read_text(encoding="utf-8"))
        m = cfg.get("model")
        return str(m) if m else None
    except Exception:  # noqa: BLE001 - best effort
        return None


def effective_model(settings: dict | None) -> str | None:
    """The model a NEW thread of this project runs on: the project's
    model_override, else the config default. Sub-agent role files carry
    it explicitly because codex does not inherit an unknown (third-party)
    parent model: the R7 A2 cell (2026-09-06 14:49) ran on
    z-ai/glm-5.3-flash and its two auditors were spawned on codex's own
    default gpt-5.5 ("You are Codex, a coding agent based on GPT-5")."""
    ov = (settings or {}).get("model_override") or None
    return str(ov) if ov else _config_default_model()


def render_role(name: str, project_dir: str | Path,
                knowledge_mode: str | None = None,
                model: str | None = None) -> str:
    """The package role text plus the per-project read-only MCP override.

    The override mirrors workbench.core._mcp_overrides (same interpreter,
    module, cwd and timeouts) with CRYSTALPILOT_MCP_READONLY=1 added, and
    CRYSTALPILOT_KNOWLEDGE_MODE forwarded so a tools_only ablation project
    gives its sub-agents the same tool list as the parent. `model` pins the
    sub-agent to the parent's model (see effective_model); it is a
    top-level key and must precede the [mcp_servers] table."""
    src = ROLES_DIR / f"{name}.toml"
    base = src.read_text(encoding="utf-8").rstrip("\n")
    if base.startswith(ROLE_MARKER):
        base = base[len(ROLE_MARKER):].lstrip("\n")
    if model:
        base += ("\n# the parent thread's model (codex would otherwise fall back to "
                 "its own default for a third-party model)\n"
                 f"model = {_toml_lit(str(model))}")
    project = str(Path(project_dir).resolve())
    env = ['PYTHONUTF8 = "1"', 'CRYSTALPILOT_MCP_READONLY = "1"']
    if (knowledge_mode or "").strip() == "tools_only":
        env.append('CRYSTALPILOT_KNOWLEDGE_MODE = "tools_only"')
    override = "\n".join([
        "",
        "# --- written by CrystalPilot for THIS project: the sub-agent gets its",
        "# own MCP server process, started read-only (server-side gate; the",
        "# codex sandbox does not cover MCP tool calls). Regenerated on every",
        "# project open / effort change; edit the package copy, not this file.",
        "[mcp_servers.crystalpilot]",
        f"command = {_toml_lit(str(ENGINE_PY))}",
        "args = ['-X', 'utf8', '-m', 'crystalpilot.mcp', '--project', "
        f"{_toml_lit(project)}]",
        f"cwd = {_toml_lit(str(ENGINE_ROOT))}",
        "startup_timeout_sec = 180",
        "tool_timeout_sec = 3900",
        "",
        "[mcp_servers.crystalpilot.env]",
        *env,
        "",
    ])
    return f"{ROLE_MARKER}\n{base}\n{override}"


def ensure_agent_roles(project_dir: str | Path, enabled: bool,
                       knowledge_mode: str | None = None,
                       model: str | None = None) -> dict[str, Any]:
    """Make `<project>/.codex/agents/` carry exactly our roles when
    `enabled`, and none of them when not. Foreign files (no ROLE_MARKER)
    are reported and left alone in both directions. `model` is written
    into every role (effective_model of the project)."""
    d = Path(project_dir) / ".codex" / "agents"
    out: dict[str, Any] = {"dir": str(d), "enabled": bool(enabled),
                           "roles": role_names(), "written": [],
                           "current": [], "removed": [], "kept_foreign": [],
                           "model": model}
    existing: dict[str, str] = {}
    if d.is_dir():
        for f in d.glob("*.toml"):
            try:
                existing[f.stem] = f.read_text(encoding="utf-8",
                                               errors="replace")
            except OSError:
                existing[f.stem] = ""
    if enabled:
        d.mkdir(parents=True, exist_ok=True)
        for name in role_names():
            text = render_role(name, project_dir, knowledge_mode, model)
            cur = existing.get(name)
            if cur is not None and not cur.startswith(ROLE_MARKER):
                out["kept_foreign"].append(name)
                continue
            if cur is not None and cur.replace("\r\n", "\n") == text:
                out["current"].append(name)
                continue
            (d / f"{name}.toml").write_text(text, encoding="utf-8")
            out["written"].append(name)
    for stem, cur in existing.items():
        if not cur.startswith(ROLE_MARKER):
            if stem not in out["kept_foreign"]:
                out["kept_foreign"].append(stem)
            continue
        if not enabled or stem not in role_names():
            try:
                os.remove(d / f"{stem}.toml")
                out["removed"].append(stem)
            except OSError:
                pass
    return out
