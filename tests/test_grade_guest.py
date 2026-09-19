"""Partial-occupancy reference atoms (post-synthetic guests, minor
disorder components) are scored as a guest layer, not as framework: the
group's manual NU-1000 structure carries a 9-atom bromophenylacetate at
occupancy 0.125 bonded to the Zr node, and its Br made every correct
P6/mmm framework 'not reproduced' (heavy recall 2/3)."""
from __future__ import annotations

from cctbx import crystal, xray

from crystalpilot.benchmark.evaluate import evaluate_against_reference

CS = crystal.symmetry(unit_cell=(10, 11, 12, 90, 90, 90),
                      space_group_symbol="P -1")
# one connected fragment: Zr-O 2.2 A, O-C 1.3 A
FRAME = [("Zr1", "Zr", (0.20, 0.20, 0.20), 1.0),
         ("O1", "O", (0.42, 0.20, 0.20), 1.0),
         ("O2", "O", (0.20, 0.40, 0.20), 1.0),
         ("O3", "O", (0.20, 0.20, 0.383), 1.0),
         ("C1", "C", (0.55, 0.20, 0.20), 1.0),
         ("C2", "C", (0.20, 0.52, 0.20), 1.0)]
# a carboxylate-like guest BONDED to the node (O9-Zr1 2.2 A, O9-C9 1.4 A,
# C9-Br6 1.8 A) at occupancy 0.125: one fragment with the framework, so
# only the occupancy rule can tell it apart
GUEST = [("O9", "O", (0.20, 0.20, 0.02), 0.125),
         ("C9", "C", (0.20, 0.30, -0.05), 0.125),
         ("Br6", "Br", (0.20, 0.45, -0.10), 0.125)]


def _xs(atoms):
    xs = xray.structure(crystal_symmetry=CS)
    for lbl, el, site, occ in atoms:
        xs.add_scatterer(xray.scatterer(label=lbl, scattering_type=el,
                                        site=site, occupancy=occ, u=0.03))
    return xs


def test_framework_without_the_guest_is_still_solved():
    e = evaluate_against_reference(_xs(FRAME), _xs(FRAME + GUEST))
    assert e["solved"] is True
    assert e["heavy_match_rate"] == 1.0            # Zr only; Br is guest
    assert e["n_ref_partial_excluded"] == 3
    assert e["guest"]["n_ref"] == 3 and e["guest"]["n_matched"] == 0
    assert set(e["guest"]["labels"]) == {"Br6", "C9", "O9"}


def test_guest_layer_counts_what_the_model_reproduced():
    e = evaluate_against_reference(_xs(FRAME + GUEST[:2]), _xs(FRAME + GUEST))
    assert e["solved"] is True
    assert e["guest"]["n_matched"] == 2 and e["guest"]["recall"] == 0.667


def test_full_occupancy_reference_has_no_guest_layer():
    e = evaluate_against_reference(_xs(FRAME), _xs(FRAME))
    assert e["n_ref_partial_excluded"] == 0 and "guest" not in e
