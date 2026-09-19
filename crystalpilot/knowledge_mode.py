"""Knowledge-layer mode of the running process (ka1 ablation, 2026-09-03).

Dependency-free on purpose: read by refine.registry (which tools exist),
refine.tools_deliver (whether run_checkcif attaches skill pointers) and
mcp.spec_cache (the tools/list cache key) - the last of these must stay
importable without the cctbx chain.

The value is set per MCP process by workbench.core._mcp_overrides from the
project setting `knowledge_mode`; anything not exactly "tools_only" is the
full stack, so a missing or mistyped variable can only ever give the agent
MORE knowledge, never silently strip it from a production project.
"""
from __future__ import annotations

import os

ENV_VAR = "CRYSTALPILOT_KNOWLEDGE_MODE"
MODES = ("full", "tools_only")


def current() -> str:
    return "tools_only" if os.environ.get(ENV_VAR) == "tools_only" else "full"
