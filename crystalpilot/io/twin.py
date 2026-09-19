"""Shared SHELX TWIN/BASF shape checks (no crystallographic computation)."""
from __future__ import annotations

import math
from typing import Any


def twin_component_count(n: Any) -> int:
    """TWIN's signed n: a negative even n includes inversion partners."""
    if (isinstance(n, bool) or not isinstance(n, (int, float))
            or not math.isfinite(n) or n != int(n) or abs(n) < 2
            or (n < 0 and int(n) % 2)):
        raise ValueError(
            "TWIN n must be an integer >= 2, or a negative even integer "
            "for components paired with their inversion twins")
    return abs(int(n))


def twin_basf_error(twin: dict | None) -> str | None:
    """Reject incomplete TWIN/BASF cards, preserving other SHELX conventions.

    An absent BASF means a fixed equal-fraction TWIN. Without a matrix,
    HKLF5 uses independent batch scales, so TWIN n does not set their count.
    Refined negative/oversized fractions must remain available for diagnosis;
    physical starting-fraction bounds belong to set_twin, not serialization.
    """
    if not twin or not twin.get("matrix"):
        return None
    n = twin.get("n", 2)
    try:
        count = twin_component_count(n)
    except ValueError as exc:
        return str(exc)
    basf = twin.get("basf")
    if basf is None:
        return None
    if not isinstance(basf, (list, tuple)):
        return "TWIN basf must be a list of coefficients"
    if basf and len(basf) != count - 1:
        return (f"TWIN n={n} requires {count - 1} BASF coefficients "
                f"when fractions are refined; got {len(basf)}")
    if any(isinstance(b, bool) or not isinstance(b, (int, float))
           or not math.isfinite(b) for b in basf):
        return "TWIN basf coefficients must be finite numbers"
    return None
