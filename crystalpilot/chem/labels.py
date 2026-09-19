"""Atom label <-> element conventions (SHELX labels, CIF readers).

A SHELX atom label announces its element in the leading letters: every
reader that does not see the SFAC table - PLATON/checkCIF, the ASU
viewer, the benchmark grader, a referee - types the atom from the label.
When the label says one element and the scatterer another, those readers
audit a different structure than the one refined (pa2/pa3: SHELXT's
placeholder composition left mu3-O/OH atoms as N62 / C1; some were
retyped in place, none relabelled, and nothing at delivery time said
"label N62 is typed O").

The rule, as SHELX/PLATON apply it:
  * leading letters, one or two characters, case-insensitive;
  * the two-letter symbol wins when it is an element (CL1 -> Cl, ZR1 ->
    Zr, BR6 -> Br, CO1 -> Co), otherwise the first letter (OW1 -> O,
    OH2 -> O, C1A -> C, N2' -> N, Cl1_2 -> Cl);
  * Q labels (Q1, QA, Q12) are Fourier peaks, not atoms - no element
    starts with Q;
  * D announces hydrogen (deuterium) when no two-letter element fits.

Pure functions, periodic-table generic, no cctbx dependency.
"""
from __future__ import annotations

import re
from typing import NamedTuple

ELEMENT_SYMBOLS: tuple[str, ...] = (
    "H", "He", "Li", "Be", "B", "C", "N", "O", "F", "Ne",
    "Na", "Mg", "Al", "Si", "P", "S", "Cl", "Ar", "K", "Ca",
    "Sc", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn",
    "Ga", "Ge", "As", "Se", "Br", "Kr", "Rb", "Sr", "Y", "Zr",
    "Nb", "Mo", "Tc", "Ru", "Rh", "Pd", "Ag", "Cd", "In", "Sn",
    "Sb", "Te", "I", "Xe", "Cs", "Ba", "La", "Ce", "Pr", "Nd",
    "Pm", "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er", "Tm", "Yb",
    "Lu", "Hf", "Ta", "W", "Re", "Os", "Ir", "Pt", "Au", "Hg",
    "Tl", "Pb", "Bi", "Po", "At", "Rn", "Fr", "Ra", "Ac", "Th",
    "Pa", "U", "Np", "Pu", "Am", "Cm", "Bk", "Cf", "Es", "Fm",
    "Md", "No", "Lr", "Rf", "Db", "Sg", "Bh", "Hs", "Mt", "Ds",
    "Rg", "Cn", "Nh", "Fl", "Mc", "Lv", "Ts", "Og",
)
_ELEMENTS = frozenset(ELEMENT_SYMBOLS)

#: scattering types that are hydrogen for every labelling purpose
#: (riding-H labels follow their carrier - H12A - and announce nothing)
HYDROGEN_TYPES = frozenset({"H", "D"})

_LEADING_LETTERS = re.compile(r"^\s*([A-Za-z]+)")


class LabelElement(NamedTuple):
    """What a label announces. kind: 'element' | 'peak' | 'unknown'."""
    element: str | None
    kind: str
    prefix: str


def _symbol_from_letters(letters: str) -> str | None:
    """Two-letter symbol when valid, else the one-letter symbol, else
    None. 'D' (deuterium) reads as hydrogen."""
    if len(letters) >= 2:
        two = letters[0].upper() + letters[1].lower()
        if two in _ELEMENTS:
            return two
    if letters:
        one = letters[0].upper()
        if one in _ELEMENTS:
            return one
        if one == "D":
            return "H"
    return None


def parse_label(label: str) -> LabelElement:
    """Element announced by a SHELX/CIF atom label (see module doc)."""
    m = _LEADING_LETTERS.match(str(label or ""))
    if not m:
        return LabelElement(None, "unknown", "")
    letters = m.group(1)
    if letters[0].upper() == "Q":
        return LabelElement(None, "peak", letters[:2])
    sym = _symbol_from_letters(letters)
    if sym is None:
        return LabelElement(None, "unknown", letters[:2])
    # the prefix actually consumed: 'Cl' for CL1, 'O' for OW1, 'D' for D1
    return LabelElement(sym, "element", letters[:1 if len(sym) == 1 else 2])


def label_element(label: str) -> str | None:
    """'CL1' -> 'Cl', 'OW1' -> 'O', 'c1a' -> 'C', 'Q1' -> None."""
    return parse_label(label).element


def is_peak_label(label: str) -> bool:
    return parse_label(label).kind == "peak"


def normalize_element(scattering_type: str | None) -> str | None:
    """Element of a scattering type / CIF type symbol: 'O2-' -> 'O',
    'Zr4+' -> 'Zr', 'Cval' -> 'C', 'Sival' -> 'Si', 'cl' -> 'Cl',
    'D' -> 'H'; None when no element can be read."""
    m = _LEADING_LETTERS.match(str(scattering_type or ""))
    if not m:
        return None
    return _symbol_from_letters(m.group(1))


def label_matches_element(label: str, scattering_type: str | None) -> bool:
    """True when the label can be read as the scatterer's element.

    The two-letter reading is ambiguous by construction (CA1 is a calcium
    or an alpha carbon, CO1 a cobalt or a carbonyl carbon, OS1 an osmium
    or a solvent oxygen, NA1 a sodium or a nitrogen): a label is accepted
    when EITHER reading agrees with the type, so a conventional label
    never blocks a delivery, while N62 typed O (neither N nor Nd-style
    two-letter reads as O) still does. Peak and unreadable labels never
    match; an unreadable TYPE cannot be judged and counts as a match."""
    el = normalize_element(scattering_type)
    if el is None:
        return True
    pl = parse_label(label)
    if pl.kind != "element":
        return False
    if pl.element == el:
        return True
    one = _symbol_from_letters(pl.prefix[:1])
    return one is not None and one == el
