"""What the physics says about this data/composition BEFORE a solver runs.

Direct and dual-space methods (SHELXT, charge flipping, Superflip) all
phase from RESOLVED ATOMS. Two element-generic facts decide how hard
that is:

* d_min - around 1.0 A individual atoms are separated in the map; past
  ~1.2 A they no longer are and the atomicity constraint every one of
  these algorithms leans on becomes weak.
* the heaviest scatterer - one atom contributes ~Z electrons at one
  point, so a heavy atom pins phases the light-atom sea cannot. Two
  lines, both plain atomic numbers, no per-crystal tuning:
    - Z 14 (Si): "nothing heavier than Si" is the pure light-atom
      regime named in the physics statement below;
    - Z 20 (Ca): from about here a single scatterer carries enough of
      the total scattering to phase data that no longer resolve atoms.
      A chloride or a sulfur (Z 16-17) is a marker atom, not a phasing
      solution, so it does NOT lift a coarse-resolution case.

Nothing in this module refuses, gates or changes any behaviour. The
block it builds is a DISCLOSURE: an agent reading a solver failure must
be able to tell whether the failure carries information about the
structure or only about this platform's (absent) record in that regime.
"""
from __future__ import annotations

from typing import Any, Iterable

#: "heavier than Si" - the light-atom line of the physics statement.
SI_Z = 14
#: from here one scatterer dominates enough to phase unresolved data.
DOMINANT_Z = 20
#: atoms are cleanly separated in the map at or below this d_min.
ATOMIC_D_MIN = 1.0
#: past this d_min the atomicity constraint gets weak.
COARSE_D_MIN = 1.2

TIERS = ("routine", "harder", "no_record")

_TIER_RULE = (
    f"tier from d_min and the heaviest declared Z only: d_min <= "
    f"{ATOMIC_D_MIN:.2f} A -> routine at any composition; d_min <= "
    f"{COARSE_D_MIN:.2f} A -> routine with a scatterer of Z >= {SI_Z + 1} "
    f"(heavier than Si), harder without one; d_min > {COARSE_D_MIN:.2f} A "
    f"-> harder with a scatterer of Z >= {DOMINANT_Z} (Ca and up, which "
    f"can carry phases on its own), no_record without one. An undeclared "
    f"composition counts as light.")

_PHYSICS_ROUTINE = (
    "direct and dual-space phasing works from resolved atoms, and at this "
    "resolution they are resolved - this is the normal working range of "
    "SHELXT / charge flipping / Superflip.")

_PHYSICS_HARDER_LIGHT = (
    "direct and dual-space methods phase from resolved atoms and become "
    f"markedly harder as d_min passes ~{COARSE_D_MIN:.1f} A when no atom "
    f"heavier than Si (Z {SI_Z}) is present. This data set sits just "
    "inside that line, so a failure here is weak evidence at best.")

_PHYSICS_HARDER_HEAVY = (
    "the data no longer resolve individual atoms, but a scatterer of "
    f"Z >= {DOMINANT_Z} is declared and contributes enough of the total "
    "scattering to carry phases on its own (heavy-atom / dual-space "
    "phasing is doing the work, not atomicity).")

_PHYSICS_NO_RECORD = (
    "direct and dual-space methods phase from resolved atoms and become "
    f"markedly harder when d_min > ~{COARSE_D_MIN:.1f} A and no atom "
    f"heavier than Si (Z {SI_Z}) is present; a scatterer of Z >= "
    f"{DOMINANT_Z} could carry the phases instead, and none is declared "
    "here.")

_PHYSICS_UNKNOWN = (
    "no d_min could be read for this call, so the one measurement the "
    "grading rests on is missing - the regime is undetermined, not safe.")

_NO_RECORD_NOTE = (
    "This platform has NO measured success-rate record in this regime. A "
    "failure here is NOT evidence that the structure is unsolvable, and "
    "it is not a reason to change the space group, the composition or the "
    "data: report the attempt as inconclusive, not as a negative result.")

_HARDER_NOTE = (
    "This platform has no measured success-rate record at this "
    "resolution/composition either; treat a failure as inconclusive "
    "rather than as evidence about the structure.")


def atomic_number(element: str) -> int | None:
    """Z of an element symbol, or None when it is not an element."""
    el = str(element or "").strip().capitalize()
    if not el:
        return None
    try:
        from cctbx.eltbx import tiny_pse
        return int(tiny_pse.table(el).atomic_number())
    except Exception:  # noqa: BLE001 - an unparsable symbol is just unknown
        return None


def heaviest_declared(elements: Iterable[str]
                      ) -> tuple[str | None, int | None]:
    """(symbol, Z) of the heaviest element in a declaration, ignoring H."""
    best: tuple[str, int] | None = None
    for el in elements or ():
        sym = str(el or "").strip().capitalize()
        if sym in ("", "H", "D"):
            continue
        z = atomic_number(sym)
        if z is None:
            continue
        if best is None or z > best[1]:
            best = (sym, z)
    return best if best else (None, None)


def grade(d_min: float | None, z_heaviest: int | None) -> str:
    """routine / harder / no_record from d_min and the heaviest Z only."""
    if d_min is None:
        # nothing measured to grade on: say so rather than reassure
        return "no_record"
    z = int(z_heaviest or 0)
    if d_min <= ATOMIC_D_MIN:
        return "routine"
    if d_min <= COARSE_D_MIN:
        return "routine" if z > SI_Z else "harder"
    return "harder" if z >= DOMINANT_Z else "no_record"


def capability_block(*, d_min: float | None, d_min_source: str,
                     heaviest_element: str | None, z_heaviest: int | None,
                     heaviest_source: str,
                     completeness: float | None = None,
                     completeness_source: str = "") -> dict[str, Any]:
    """The `solution_capability` disclosure. Never refuses anything.

    Same skeleton as solution_tools._completeness_guard: the measurement
    first, then what the physics makes of it, then what it means for
    reading the outcome - only this one never turns into a refusal.
    """
    tier = grade(d_min, z_heaviest)
    block: dict[str, Any] = {
        "d_min": round(float(d_min), 3) if d_min is not None else None,
        "d_min_source": d_min_source,
        "heaviest_element": heaviest_element,
        "heaviest_element_z": z_heaviest,
        "heaviest_element_source": heaviest_source,
        "completeness": (round(float(completeness), 3)
                         if completeness is not None else None),
        "tier": tier,
    }
    if completeness_source:
        block["completeness_source"] = completeness_source
    if tier == "routine":
        block["physics"] = _PHYSICS_ROUTINE
        return block
    if tier == "harder":
        heavy = z_heaviest is not None and z_heaviest >= DOMINANT_Z
        block["physics"] = (_PHYSICS_HARDER_HEAVY if heavy
                            else _PHYSICS_HARDER_LIGHT)
        block["not_evidence"] = _HARDER_NOTE
    else:
        block["physics"] = (_PHYSICS_NO_RECORD if d_min is not None
                            else _PHYSICS_UNKNOWN)
        block["not_evidence"] = _NO_RECORD_NOTE
    block["tier_rule"] = _TIER_RULE
    return block


# --------------------------------------------------------------------- #
# session adapter
# --------------------------------------------------------------------- #

def _session_elements(ses) -> tuple[list[str], str]:
    """Declared element symbols and where they were declared."""
    comp = getattr(getattr(ses, "dataset", None), "composition", None)
    if comp is not None and getattr(comp, "elements", None):
        src = getattr(comp, "source", "") or "dataset composition hint"
        return list(comp.elements), f"declared composition ({src})"
    model = getattr(ses, "model", None)
    if model is not None and model.scatterers().size():
        return ([sc.scattering_type.strip() for sc in model.scatterers()],
                "elements present in the session model")
    ins = (getattr(ses, "flags", None) or {}).get("ins_elements") or {}
    if ins.get("elements"):
        return list(ins["elements"]), "SFAC card of the ingested ins"
    return [], "no composition declared - counted as light"


def session_capability(ses, *, d_min: float | None = None,
                       d_min_source: str = "",
                       elements: Iterable[str] | None = None,
                       elements_source: str = "",
                       completeness: float | None = None,
                       completeness_source: str = "") -> dict[str, Any]:
    """Build the block from a SolveSession, filling gaps from the session.

    Every lookup is defensive: a disclosure must never be the reason a
    tool call fails.
    """
    if elements is not None:
        els, el_src = list(elements), (elements_source
                                       or "elements given to this call")
        if not els:
            els, el_src = _session_elements(ses)
    else:
        els, el_src = _session_elements(ses)
    sym, z = heaviest_declared(els)

    merge = getattr(ses, "merge_info", None) or {}
    if d_min is None:
        if merge.get("d_min") is not None:
            d_min = float(merge["d_min"])
            d_min_source = d_min_source or "working-group merge (all data)"
        else:
            try:
                d_min = float(ses.fo_sq.d_min())
                d_min_source = d_min_source or "merged data in the session"
            except Exception:  # noqa: BLE001 - no data yet is a valid state
                d_min, d_min_source = None, (d_min_source
                                             or "no merged data in session")
    if completeness is None:
        if merge.get("completeness") is not None:
            completeness = float(merge["completeness"])
            completeness_source = (completeness_source
                                   or "working-group merge (all data)")
        else:
            try:
                completeness = float(ses.fo_sq.completeness(
                    d_max=float("inf")))
                completeness_source = (completeness_source
                                       or "merged data in the session")
            except Exception:  # noqa: BLE001
                completeness = None
    return capability_block(
        d_min=d_min, d_min_source=d_min_source or "unknown",
        heaviest_element=sym, z_heaviest=z, heaviest_source=el_src,
        completeness=completeness, completeness_source=completeness_source)


def attach(result, block: dict[str, Any] | None):
    """Put the block on a ToolResult's summary, whatever the outcome."""
    if block is None or result is None:
        return result
    try:
        if result.summary is None:
            result.summary = {}
        result.summary["solution_capability"] = block
    except Exception:  # noqa: BLE001 - disclosure must not break a result
        pass
    return result
