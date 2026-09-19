"""MOF chemistry knowledge tables.

Typical coordination numbers and bond-length windows for metals in MOFs/coordination
polymers, common SBU patterns, and solvent/guest signatures. Ranges are deliberately
generous (validation flags *implausible*, not merely unusual, chemistry).
Sources: survey of CSD MOF statistics and standard crystal-chemistry references.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MetalProfile:
    element: str
    cn_range: tuple[int, int]            # plausible coordination number window
    m_o_range: tuple[float, float]       # plausible M–O bond length window (Å)
    m_n_range: tuple[float, float] | None = None
    notes: str = ""


METAL_PROFILES: dict[str, MetalProfile] = {p.element: p for p in [
    MetalProfile("Cu", (2, 6), (1.85, 2.60), (1.85, 2.45),
                 "paddlewheel Cu2(O2CR)4 very common; Jahn-Teller axial up to ~2.6"),
    MetalProfile("Zn", (3, 6), (1.85, 2.45), (1.95, 2.30), "Zn4O(RCO2)6 (MOF-5 SBU); tetrahedral common"),
    MetalProfile("Zr", (6, 9), (2.00, 2.45), None, "Zr6O4(OH)4 node (UiO/NU/PCN); CN 7-8 typical"),
    MetalProfile("Hf", (6, 9), (2.00, 2.45), None, "Hf6 analogous to Zr6"),
    MetalProfile("Al", (4, 6), (1.80, 2.10), None, "MIL-53/MIL-100 chains"),
    MetalProfile("Cr", (4, 7), (1.85, 2.20), (1.95, 2.20), "MIL-101 trimers"),
    MetalProfile("Fe", (4, 7), (1.85, 2.35), (1.90, 2.30), "Fe3O trimers, MIL series"),
    MetalProfile("Co", (3, 6), (1.90, 2.35), (1.85, 2.30), "ZIF (with N), paddlewheels"),
    MetalProfile("Ni", (3, 6), (1.90, 2.30), (1.85, 2.25), ""),
    MetalProfile("Mn", (4, 7), (1.95, 2.45), (1.95, 2.40), ""),
    MetalProfile("Mg", (4, 6), (1.95, 2.25), None, "MOF-74 chains"),
    MetalProfile("Ca", (6, 9), (2.25, 2.70), None, ""),
    MetalProfile("Cd", (4, 8), (2.15, 2.65), (2.20, 2.60), ""),
    MetalProfile("Ti", (5, 7), (1.75, 2.15), None, "MIL-125"),
    MetalProfile("V", (4, 7), (1.55, 2.30), None, "vanadyl V=O short ~1.6"),
    MetalProfile("Mo", (4, 7), (1.65, 2.40), None, ""),
    MetalProfile("W", (4, 7), (1.65, 2.40), None, ""),
    MetalProfile("Ag", (2, 6), (2.15, 2.70), (2.05, 2.55), "linear/low CN common"),
    MetalProfile("Pb", (4, 10), (2.30, 2.95), None, "lone-pair hemidirected"),
    MetalProfile("In", (4, 8), (2.05, 2.40), None, ""),
    MetalProfile("Ga", (4, 6), (1.80, 2.15), None, ""),
    MetalProfile("Sc", (6, 8), (2.00, 2.35), None, ""),
    MetalProfile("Y",  (6, 9), (2.20, 2.55), None, ""),
    # generic lanthanides
    *[MetalProfile(ln, (6, 10), (2.25, 2.75), None, "high-CN lanthanide")
      for ln in ("La", "Ce", "Pr", "Nd", "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er",
                 "Tm", "Yb", "Lu")],
]}

# Common charged/neutral guests & solvents seen in MOF pores (formula fragments).
COMMON_GUESTS = {
    "DMF": {"C": 3, "H": 7, "N": 1, "O": 1},
    "DEF": {"C": 5, "H": 11, "N": 1, "O": 1},
    "DMA": {"C": 4, "H": 9, "N": 1, "O": 1},
    "MeOH": {"C": 1, "O": 1},
    "EtOH": {"C": 2, "O": 1},
    "H2O": {"O": 1},
    "MeCN": {"C": 2, "N": 1},
    "NO3-": {"N": 1, "O": 3},
    "Cl-": {"Cl": 1},
    "OH-": {"O": 1},
}

# Metals by atomic number - a whitelist read off the periodic table, not a
# blacklist of "everything that is not on this list of non-metals" (D9: the
# old blacklist silently promoted every unknown / mistyped scattering type,
# every Q-peak label, to a metal). Metalloids B, Si, Ge, As, Sb, Te, At and
# the noble gases are NOT metals here; Po (84) is.
_METAL_Z: frozenset[int] = frozenset(
    {3, 4}                                  # Li Be
    | {11, 12, 13}                          # Na Mg Al
    | {19, 20} | set(range(21, 31)) | {31}  # K Ca, Sc..Zn, Ga
    | {37, 38} | set(range(39, 49)) | {49, 50}          # Rb Sr, Y..Cd, In Sn
    | {55, 56} | set(range(57, 81)) | {81, 82, 83, 84}  # Cs Ba, La..Hg, Tl..Po
    | {87, 88} | set(range(89, 113)) | {113, 114, 115, 116}
)
_METAL_CACHE: dict[str, bool] = {}


def element_symbol(scattering_type: str) -> str:
    """'Cu2+' / 'C ' / 'zr' / 'O-1' -> 'Cu' / 'C' / 'Zr' / 'O'."""
    st = "".join(c for c in str(scattering_type) if c.isalpha())
    return st[:2].capitalize()


def is_metal(element: str) -> bool:
    """Whitelist metal test straight off the periodic table (atomic number
    from cctbx.eltbx.tiny_pse, cached). Never a blacklist: an unknown or
    mistyped symbol is NOT a metal. Charged scattering types ('Cu2+') are
    reduced to their element first."""
    el = element_symbol(element)
    hit = _METAL_CACHE.get(el)
    if hit is None:
        if not el or el in ("D", "T"):
            hit = False
        else:
            try:
                from cctbx.eltbx import tiny_pse
                hit = int(tiny_pse.table(el).atomic_number()) in _METAL_Z
            except Exception:  # noqa: BLE001 - unknown symbol is not a metal
                hit = False
        _METAL_CACHE[el] = hit
    return hit


def profile_for(element: str) -> MetalProfile | None:
    return METAL_PROFILES.get(element.capitalize())


def cn_status(element: str, cn: int | None) -> dict:
    """Three-state verdict on a coordination number (D9).

    {"checked": bool, "plausible": bool | None, "expected_cn": [lo, hi] | None,
     "note": str}

    `plausible is None` means NO VERDICT - the table has nothing to say about
    this element - and callers (validate_structure, the UI) must render it as
    "not checked", never as a pass. The old behaviour, `prof is None or
    lo <= cn <= hi`, turned every metal missing from METAL_PROFILES (Os, Ru,
    Re, Ir, Pt, Au, Bi, U ...) into a silent success, which is how a wrong CN
    on an unlisted metal survived validation.
    """
    el = str(element).capitalize()
    prof = profile_for(el)
    if prof is not None:
        lo, hi = prof.cn_range
        if cn is None:
            return {"checked": False, "plausible": None,
                    "expected_cn": [lo, hi],
                    "note": f"{el} expects CN {lo}-{hi}; no CN was supplied"}
        ok = lo <= int(cn) <= hi
        note = (f"{el} CN {int(cn)} is inside the tabulated window {lo}-{hi}"
                if ok else
                f"{el} CN {int(cn)} is outside the tabulated window {lo}-{hi}")
        if prof.notes:
            note += f" ({prof.notes})"
        return {"checked": True, "plausible": ok, "expected_cn": [lo, hi],
                "note": note}
    if not is_metal(el):
        return {"checked": False, "plausible": None, "expected_cn": None,
                "note": (f"{el} is not a metal - coordination-number windows "
                         "are tabulated for metals only")}
    return {"checked": False, "plausible": None, "expected_cn": None,
            "note": (f"no MetalProfile entry for {el}: its coordination "
                     "number was NOT checked (absence of a rule is not a "
                     "pass - add a profile or judge it by hand)")}
