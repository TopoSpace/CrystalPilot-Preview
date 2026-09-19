"""chem/labels: what a SHELX/CIF atom label announces - the label/element
gate of write_outputs reads labels the way checkCIF, the viewer and the
grader do. Periodic-table generic; synthetic labels only."""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from crystalpilot.chem.labels import (  # noqa: E402
    ELEMENT_SYMBOLS, is_peak_label, label_element, label_matches_element,
    normalize_element, parse_label)


def test_periodic_table_is_complete():
    assert len(ELEMENT_SYMBOLS) == 118
    assert len(set(ELEMENT_SYMBOLS)) == 118
    assert ELEMENT_SYMBOLS[0] == "H" and ELEMENT_SYMBOLS[-1] == "Og"


@pytest.mark.parametrize("label,element", [
    # one-letter elements, digits and suffixes
    ("C1", "C"), ("N2", "N"), ("O17", "O"), ("S1", "S"), ("P3", "P"),
    ("C1A", "C"), ("N2'", "N"), ("C12B", "C"), ("O1'", "O"), ("U1", "U"),
    ("W1", "W"), ("K1", "K"), ("F2", "F"), ("I1", "I"),
    # two-letter elements win when valid
    ("CL1", "Cl"), ("Cl1", "Cl"), ("Cl1_2", "Cl"), ("ZR1", "Zr"),
    ("BR6", "Br"), ("CU2", "Cu"), ("FE01", "Fe"), ("AG1", "Ag"),
    ("Zn3", "Zn"), ("SI1", "Si"), ("MN1", "Mn"), ("PB1", "Pb"),
    # water / hydroxyl style labels: OW, OH are not elements -> O
    ("OW1", "O"), ("OW", "O"), ("O1W", "O"), ("OH2", "O"), ("OWA", "O"),
    # lowercase
    ("c1a", "C"), ("zr1", "Zr"), ("ow1", "O"), ("cl1", "Cl"),
    # the convention's traps: a valid two-letter symbol IS that element
    ("CO1", "Co"), ("NA1", "Na"), ("HO1", "Ho"), ("BA1", "Ba"),
    # deuterium announces hydrogen
    ("D1", "H"), ("D2A", "H"),
])
def test_label_element(label, element):
    assert label_element(label) == element
    assert parse_label(label).kind == "element"


@pytest.mark.parametrize("label", ["Q1", "QA", "Q12", "q3", "Q", "Q1A"])
def test_peak_labels(label):
    assert is_peak_label(label)
    assert label_element(label) is None
    assert parse_label(label).kind == "peak"


@pytest.mark.parametrize("label", ["", "1C", "X1", "J2", "?", "_1", "  "])
def test_unreadable_labels(label):
    p = parse_label(label)
    assert p.kind == "unknown" and p.element is None
    assert not is_peak_label(label)


def test_prefix_is_what_was_consumed():
    assert parse_label("CL1").prefix == "CL"
    assert parse_label("OW1").prefix == "O"
    assert parse_label("c1a").prefix == "c"
    assert parse_label("D1").prefix == "D"


@pytest.mark.parametrize("typ,element", [
    ("O", "O"), ("O2-", "O"), ("Zr", "Zr"), ("Zr4+", "Zr"), ("ZR", "Zr"),
    ("cl", "Cl"), ("Cval", "C"), ("Sival", "Si"), ("D", "H"), ("H", "H"),
    ("Cu", "Cu"), ("", None), (None, None), ("?", None), ("X", None),
])
def test_normalize_element(typ, element):
    assert normalize_element(typ) == element


def test_label_matches_element():
    assert label_matches_element("CL1", "Cl")
    assert label_matches_element("OW1", "O")
    assert label_matches_element("c1a", "C")
    assert label_matches_element("D1", "H")
    assert label_matches_element("ZR1", "Zr4+")
    assert not label_matches_element("N62", "O")      # pa2/pa3 mu3-O as N
    assert not label_matches_element("C1", "Zr")
    assert not label_matches_element("C1", "Cu")
    # two-letter ambiguity never blocks a conventional label: the one-letter
    # reading agrees with the type
    assert label_matches_element("CO1", "C")          # carbonyl carbon
    assert label_matches_element("CA1", "C")          # alpha carbon
    assert label_matches_element("OS1", "O")          # solvent oxygen
    assert label_matches_element("NA1", "N")
    assert label_matches_element("CO1", "Co")         # and the cobalt
    assert not label_matches_element("CO1", "O")      # neither reading is O
    assert not label_matches_element("Q1", "C")       # a peak, never an atom
    assert not label_matches_element("X1", "O")
    assert label_matches_element("X1", "?")           # unreadable type: no verdict


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
