"""Round-3 WP8: a numeric bound a tool enforces at run time must be declared
in its JSON schema, so the agent (and the parameter line built from the
schema) can see it before calling. The forensic case: integrate_difference_
density refused radius_A outside 0.5-6.0 while its schema said only
"number" - a bound learned by being refused.

The guard scans every registered tool's run() source for the idiom

    if not LO <= var <= HI:          (or  if not (LO <= var <= HI):)

where `var` is assigned from params.get("name") / params["name"] in the
same function, resolves LO / HI (literals or module constants) and asserts
the schema property `name` carries a matching minimum / maximum."""
from __future__ import annotations

import ast
import inspect
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

BOUND_RE = re.compile(
    r"if\s+not\s+\(?\s*([\w.\[\]\-]+)\s*<=\s*([A-Za-z_]\w*)\s*<=\s*([\w.\[\]\-]+)\s*\)?\s*:")


def _registry():
    """Every registered tool, built the way test_agents_md.py builds it
    (no project, no session)."""
    from crystalpilot.refine.registry import refinement_registry
    from crystalpilot.refine.tools_analysis import register_analysis_tools
    from crystalpilot.refine.tools_batch import register_batch_tools
    from crystalpilot.refine.tools_cap import register_cap_tools
    from crystalpilot.refine.tools_disorder import register_disorder_tools
    from crystalpilot.refine.tools_extra import register_refine_tools
    from crystalpilot.refine.tools_frames import register_frames_tools
    from crystalpilot.refine.tools_probe import register_probe_tools
    from crystalpilot.refine.tools_skills import register_skills_tools
    reg = refinement_registry(None)
    register_refine_tools(reg, None)
    register_analysis_tools(reg, None)
    register_disorder_tools(reg, None)
    register_frames_tools(reg, None)
    register_cap_tools(reg, None)
    register_skills_tools(reg, None)
    register_batch_tools(reg, None)
    register_probe_tools(reg, None)
    return reg


def _resolve(expr: str, module):
    """A literal, or a module-level constant (optionally indexed)."""
    try:
        return ast.literal_eval(expr)
    except (ValueError, SyntaxError):
        pass
    m = re.match(r"([A-Za-z_]\w*)(?:\[(\d+)\])?$", expr)
    if not m:
        return None
    value = getattr(module, m.group(1), None)
    if value is None:
        return None
    if m.group(2) is not None:
        try:
            return value[int(m.group(2))]
        except (TypeError, IndexError):
            return None
    return value


def enforced_bounds(tool) -> list[tuple[str, float, float]]:
    """[(param_name, lo, hi)] for every runtime bound in run() whose
    variable comes straight from a parameter."""
    try:
        src = inspect.getsource(tool.run)
    except (OSError, TypeError):
        return []
    module = sys.modules[type(tool).__module__]
    out = []
    for lo_s, var, hi_s in BOUND_RE.findall(src):
        m = re.search(
            rf"\b{re.escape(var)}\s*=\s*[^\n]*?params(?:\.get\(|\[)\s*[\"'](\w+)[\"']",
            src)
        if not m:
            continue
        lo, hi = _resolve(lo_s, module), _resolve(hi_s, module)
        if not isinstance(lo, (int, float)) or not isinstance(hi, (int, float)):
            continue
        out.append((m.group(1), float(lo), float(hi)))
    return out


def _all_bounds():
    reg = _registry()
    rows = []
    for name in reg.names():
        tool = reg.get(name)
        for param, lo, hi in enforced_bounds(tool):
            rows.append((name, param, lo, hi, tool))
    return rows


BOUNDS = _all_bounds()


def test_the_scan_finds_the_known_cases():
    # the scan reads run() only; bounds enforced in helpers (probe_site's
    # _starts) are outside its reach and are covered by their own tests
    names = {(t, p) for t, p, *_ in BOUNDS}
    assert ("integrate_difference_density", "radius_A") in names
    assert ("solvent_mask", "resolution_factor") in names
    assert ("set_weights", "a") in names
    assert len(BOUNDS) >= 8


@pytest.mark.parametrize("tool, param, lo, hi, obj", BOUNDS,
                         ids=[f"{t}.{p}" for t, p, *_ in BOUNDS])
def test_runtime_bound_is_declared_in_the_schema(tool, param, lo, hi, obj):
    props = (obj.params_schema or {}).get("properties") or {}
    assert param in props, f"{tool}: {param} is bounded at run time but not a schema property"
    prop = props[param]
    assert prop.get("minimum") is not None and prop.get("maximum") is not None, (
        f"{tool}.{param}: run() rejects values outside {lo}..{hi} but the "
        f"schema declares no minimum/maximum - the agent learns the bound "
        f"by being refused")
    assert float(prop["minimum"]) == pytest.approx(lo), f"{tool}.{param} minimum"
    assert float(prop["maximum"]) == pytest.approx(hi), f"{tool}.{param} maximum"


def test_parameter_line_shows_declared_bounds():
    from crystalpilot.tools.base import schema_summary
    line = schema_summary({"type": "object", "properties": {
        "radius_A": {"type": "number", "minimum": 0.5, "maximum": 6.0,
                     "default": 2.0},
        "cycles": {"type": "integer", "minimum": 1, "maximum": 30},
        "free": {"type": "number"},
    }})
    assert "radius_A: number[0.5..6] = 2.0" in line
    assert "cycles: integer[1..30]" in line
    assert "free: number;" in line or line.endswith("free: number.")
