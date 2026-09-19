"""Shared base for project-scoped refinement tools (r12 module split).

Tool-class conventions across the codebase (P3 基类统一文档化):

- ``crystalpilot.tools.base.Tool`` - the root contract: ``name``,
  ``description``, ``params_schema``, ``run(ctx, **params) -> ToolResult``.
  Session-scoped tools (crystalpilot/tools/*.py: hydrogen, model, mask,
  disorder, refinement...) subclass it directly and reach state via
  ``ctx.session``; they are constructed with no arguments.

- ``_ProjectTool`` (this module) - refinement-workbench tools that need
  the whole project (node store, context.json, hkl path, SHELXL job dirs).
  Constructed as ``cls(project)`` by the ``register_*_tools(reg, project)``
  functions in refine/tools_*.py; inside ``run`` the session is reached as
  ``ctx.session or self.project.session``.

- ``_FramesTool`` (refine/tools_frames.py) - same shape as _ProjectTool
  for the raw-frames pipeline stages; kept separate because frames tools
  may run before any session/model exists.

Capability sets (MUTATING_TOOLS, SESSIONLESS...) live in
refine/registry.py as explicit name sets rather than class attributes -
deriving them from attributes was considered (P3) and deferred: the
drift tests in tests/test_agents_md.py and the registry's own assertions
already catch a tool that is registered but missing from the AGENTS map,
and an attribute scheme would only relocate the list, not remove the
judgement of what belongs in it. Revisit if the sets start drifting.
"""
from __future__ import annotations

import re

from ..tools.base import Tool


class _ProjectTool(Tool):
    def __init__(self, project) -> None:
        self.project = project


# CIF value-with-esd pattern, e.g. "1.234(5)" (shared by geometry
# parsing and CIF ingest)
_VAL_ESD = re.compile(r"([-\d.]+)\((\d+)\)")
