"""R4 wiring: `inspect.metal_environments` reports the continuous shape
measure next to tau4/tau5 for sigma-bound spheres of 4-6 vertices, and says
why not for hapto spheres and untabulated vertex counts."""
from __future__ import annotations

import math

import numpy as np
from cctbx import crystal, xray


def _p1(atoms, a=16.0):
    cs = crystal.symmetry(unit_cell=(a, a, a, 90, 90, 90), space_group_symbol="P 1")
    xs = xray.structure(crystal_symmetry=cs)
    uc = cs.unit_cell()
    for lb, el, cart in atoms:
        xs.add_scatterer(xray.scatterer(label=lb, site=uc.fractionalize(tuple(cart)),
                                        scattering_type=el, u=0.02))
    return xs


def test_ideal_octahedron_reports_oc6():
    from crystalpilot.refine.inspect import metal_environments
    c = np.array([8.0, 8.0, 8.0])
    atoms = [("Zn1", "Zn", tuple(c))]
    for k, v in enumerate([(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)]):
        atoms.append((f"O{k + 1}", "O", tuple(c + 2.1 * np.array(v, float))))
    env = metal_environments(_p1(atoms))
    assert len(env) == 1
    row = env[0]
    assert row["cn"] == 6 and row["closest_shape"] == "OC-6"
    assert row["closest_cshm"] < 0.001
    assert abs(row["cshm"]["TPR-6"] - 16.737) < 0.01
    assert "shape_note" not in row


def test_square_planar_versus_tetrahedral():
    from crystalpilot.refine.inspect import metal_environments
    c = np.array([8.0, 8.0, 8.0])
    sq = [("Cu1", "Cu", tuple(c))] + [
        (f"N{k + 1}", "N", tuple(c + 2.0 * np.array(v, float)))
        for k, v in enumerate([(1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0)])]
    row = metal_environments(_p1(sq))[0]
    assert row["closest_shape"] == "SP-4" and abs(row["cshm"]["T-4"] - 33.333) < 0.01
    assert row["tau4"] == 0.0
    r = 2.0 / math.sqrt(3)
    td = [("Zn1", "Zn", tuple(c))] + [
        (f"O{k + 1}", "O", tuple(c + r * np.array(v, float)))
        for k, v in enumerate([(1, 1, 1), (1, -1, -1), (-1, 1, -1), (-1, -1, 1)])]
    row = metal_environments(_p1(td))[0]
    assert row["closest_shape"] == "T-4" and row["closest_cshm"] < 0.001


def test_hapto_sphere_is_not_measured():
    """Ferrocene: cn 2 (two eta rings) but ten ligand atoms - the vertex
    measure does not apply and the row says so instead of guessing."""
    from crystalpilot.refine.inspect import metal_environments
    c = np.array([8.0, 8.0, 8.0])
    atoms = [("Fe1", "Fe", tuple(c))]
    n = 0
    for z in (1.66, -1.66):
        for k in range(5):
            a = 2 * math.pi * k / 5
            n += 1
            atoms.append((f"C{n}", "C", (c[0] + 1.21 * math.cos(a),
                                         c[1] + 1.21 * math.sin(a), c[2] + z)))
    row = metal_environments(_p1(atoms))[0]
    assert row.get("n_eta_atoms") == 10 and row["cn"] == 2
    assert "cshm" not in row and "eta" in row["shape_note"]


def test_seven_vertices_say_untabulated():
    from crystalpilot.refine.inspect import metal_environments
    c = np.array([8.0, 8.0, 8.0])
    atoms = [("La1", "La", tuple(c))]
    # pentagonal bipyramid, 2.5 A
    for k in range(5):
        a = 2 * math.pi * k / 5
        atoms.append((f"O{k + 1}", "O", (c[0] + 2.5 * math.cos(a), c[1] + 2.5 * math.sin(a), c[2])))
    atoms += [("O6", "O", (c[0], c[1], c[2] + 2.5)), ("O7", "O", (c[0], c[1], c[2] - 2.5))]
    row = metal_environments(_p1(atoms))[0]
    assert row["cn"] == 7 and "cshm" not in row and "7 vertices" in row["shape_note"]
