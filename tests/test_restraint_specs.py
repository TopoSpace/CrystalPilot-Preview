"""Restraint spec surgery tests (no reference data needed)."""
from __future__ import annotations


def test_prune_specs_for_deleted():
    """r12 backflow: deleting an atom must take referencing restraints with
    it - pair kinds surgically, FLAT wholesale, ADP lists reduced but never
    emptied into the all-atoms None form."""
    from crystalpilot.refine.restraints import prune_specs_for_deleted
    specs = [
        {"kind": "DFIX", "atoms": [["O2J", "H174"], ["O3K", "H3K"]],
         "target": 0.84},
        {"kind": "DANG", "atoms": [["C2J", "H174"]], "target": 2.0},
        {"kind": "SADI", "atoms": [["C1", "C2"], ["C1", "H174"]]},
        {"kind": "FLAT", "atoms": ["C1", "C2", "C3", "H174", "C5"]},
        {"kind": "SIMU", "atoms": ["C1", "H174"]},
        {"kind": "RIGU", "atoms": None},
        {"kind": "ISOR", "atoms": ["H174"]},
    ]
    kept, dropped = prune_specs_for_deleted(specs, {"H174"})
    kinds = [(s["kind"], s.get("atoms")) for s in kept]
    # DFIX keeps the unaffected pair
    assert ("DFIX", [["O3K", "H3K"]]) in kinds
    # DANG lost its only pair; SADI fell below two pairs; FLAT wholesale
    assert all(k != "DANG" for k, _ in kinds)
    assert all(k != "SADI" for k, _ in kinds)
    assert all(k != "FLAT" for k, _ in kinds)
    # SIMU list reduced; all-atoms RIGU untouched; ISOR emptied -> dropped
    assert ("SIMU", ["C1"]) in kinds
    assert ("RIGU", None) in kinds
    assert all(k != "ISOR" for k, _ in kinds)
    assert len(dropped) == 6
