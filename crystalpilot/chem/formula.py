"""Formula / Z bookkeeping audit.

SHELXL derives _chemical_formula_sum and _chemical_formula_weight by
dividing the UNIT cell content by the ZERR Z. CrystalPilot always
serializes UNIT from the live model (occupancy-weighted), so UNIT never
drifts - but Z can be wrong: the frames route guesses it with the
18 A^3 rule, imports carry whatever the source CIF declared, and the
writer falls back to the symmetry-op count (the Z' = 1 assumption).
A wrong Z prints a fractional or doubled formula in the final CIF,
which referees catch instantly. This audit divides the actual cell
content by Z and reports what the CIF will say.
"""
from __future__ import annotations

from typing import Any

# Z candidates worth testing when the declared Z leaves fractions:
# molecules on special positions give Z = order/m (m = site multiplicity
# divisor 2/3/4/6), extra independent molecules give Z = order * Z'.
_ZPRIME_NUM = (2, 3, 4)          # Z' = 2, 3, 4
_ZPRIME_DEN = (2, 3, 4, 6, 8)    # Z' = 1/2 ... 1/8


def _element_of(scattering_type: str) -> str:
    """'Zr' -> 'Zr', 'O2-' -> 'O' (same convention as the SHELX writer)."""
    import re
    m = re.match(r"([A-Za-z]{1,2})", scattering_type.strip())
    if not m:
        return scattering_type.strip()
    e = m.group(1)
    return e[0].upper() + e[1:].lower() if len(e) == 2 else e.upper()


def _hill_order(elements) -> list[str]:
    """C, H first, then alphabetical (Hill convention)."""
    rest = sorted(e for e in elements if e not in ("C", "H"))
    return [e for e in ("C", "H") if e in elements] + rest


def _near_integer(counts: dict[str, float], tol: float = 0.05) -> bool:
    return all(abs(v - round(v)) <= tol for v in counts.values())


def _fmt_count(v: float) -> str:
    return str(int(round(v))) if abs(v - round(v)) <= 0.05 else f"{v:.2f}"


def formula_audit(xs, z: int | None = None) -> dict[str, Any]:
    """Audit the model's cell content against the declared Z.

    xs: cctbx xray.structure (the live model). z: the ZERR Z if the
    project carries one; None means the writer's Z'=1 fallback applies.
    Returns a dict safe to embed in a tool summary (advisory only).
    """
    from cctbx.eltbx import tiny_pse

    sg_order = xs.space_group().order_z()
    raw = xs.unit_cell_content()          # scattering type -> atoms/cell
    content: dict[str, float] = {}
    for st, n in raw.items():
        e = _element_of(str(st))
        content[e] = content.get(e, 0.0) + float(n)
    z_eff = int(z) if z else sg_order

    per_fu = {e: v / z_eff for e, v in content.items() if v > 1e-6}
    formula = " ".join(f"{e}{_fmt_count(per_fu[e])}"
                       for e in _hill_order(per_fu))
    fractional = {e: round(v, 3) for e, v in per_fu.items()
                  if abs(v - round(v)) > 0.05}

    mass_cell = 0.0
    for e, v in content.items():
        try:
            mass_cell += tiny_pse.table(e).weight() * v
        except Exception:  # noqa: BLE001 - unknown symbol: skip its mass
            pass
    volume = xs.unit_cell().volume()
    density = mass_cell * 1.66054 / volume if volume > 0 else None

    out: dict[str, Any] = {
        "z": z_eff,
        "z_source": ("model file (ZERR)" if z else
                     "assumed = symmetry-op count (Z' = 1)"),
        "n_symmetry_ops": sg_order,
        "formula_per_z": formula,
        "formula_weight": round(mass_cell / z_eff, 2),
        # model content only: occupancy-weighted, no solvent-mask electrons
        "density_model_gcm3": round(density, 3) if density else None,
    }
    if fractional:
        out["fractional_counts"] = fractional
        clean = []
        cands = [sg_order] + [sg_order * m for m in _ZPRIME_NUM]
        cands += [sg_order // d for d in _ZPRIME_DEN if sg_order % d == 0]
        for zc in sorted(set(cands)):
            if zc >= 1 and zc != z_eff and _near_integer(
                    {e: v / zc for e, v in content.items() if v > 1e-6}):
                clean.append(zc)
        if clean:
            out["z_candidates_clean"] = clean
            out["note"] = (
                f"cell content / Z={z_eff} leaves non-integer counts "
                f"{fractional} but divides cleanly at Z={clean} - the "
                f"declared Z is probably wrong (molecule on a special "
                f"position or Z' != 1). SHELXL will print this fractional "
                f"_chemical_formula_sum in the CIF and referees will flag "
                f"it; fix Z before write_outputs.")
        else:
            out["note"] = (
                f"cell content / Z={z_eff} leaves non-integer counts "
                f"{fractional} and no plausible Z makes them integral - "
                f"partial-occupancy species are present. If intended "
                f"(disordered/partial solvent), document the chemical "
                f"reasoning in VALIDATION.md; if not, fix the occupancies.")
    return out
