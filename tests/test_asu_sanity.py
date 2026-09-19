"""ASU coherence / assembly (expert-review red flags, 2026-08-29).

Synthetic P-1 fixture: an ethane-like C-C fragment plus atoms deliberately
refined into a symmetry image (detached) and a ghost-signature lone oxygen.
"""
from __future__ import annotations

import pytest

cctbx = pytest.importorskip("cctbx")

from cctbx import crystal, sgtbx, xray  # noqa: E402

from crystalpilot.chem.asu_sanity import (  # noqa: E402
    apply_assembly_plan, asu_assembly_plan, asu_coherence)


def _structure(scatterers):
    sps = crystal.special_position_settings(
        crystal.symmetry(unit_cell=(10, 11, 12, 90, 100, 90),
                         space_group_symbol="P 21/c"),
        min_distance_sym_equiv=0.5)
    xs = xray.structure(special_position_settings=sps)
    for label, site, u, occ in scatterers:
        elem = label.rstrip("0123456789W")
        xs.add_scatterer(xray.scatterer(
            label=label, site=site, u=u, occupancy=occ,
            scattering_type=elem))
    xs.scattering_type_registry(table="it1992")
    return xs


def _coherent_pair():
    # C1-C2 bonded (1.5 A apart along x: 0.15 fractional of a=10)
    return [("C1", (0.10, 0.10, 0.10), 0.03, 1.0),
            ("C2", (0.25, 0.10, 0.10), 0.03, 1.0)]


def test_coherent_asu_is_clean():
    xs = _structure(_coherent_pair())
    rep = asu_coherence(xs)
    assert len(rep["fragments"]) == 1
    assert rep["detached"] == [] and rep["ghost_suspects"] == []
    assert asu_assembly_plan(xs) == []


def test_detached_fragment_detected_and_reassembled():
    # O3 bonded to C2 only through the 21/c symmetry image: place it at
    # op*(bonded position). op = -x, y+1/2, -z+1/2 in P 21/c.
    op = sgtbx.rt_mx("-x,y+1/2,-z+1/2")
    bonded = (0.25 + 0.14, 0.10, 0.10)          # 1.4 A from C2 -> C-O bond
    image = op * bonded
    xs = _structure(_coherent_pair() + [("O3", tuple(image), 0.04, 1.0)])

    rep = asu_coherence(xs)
    assert rep["n_detached_atoms"] == 1
    assert rep["detached"][0]["labels"] == ["O3"]
    assert rep["detached"][0]["attachment"] == "symmetry"
    # ordered full-occupancy O with normal Ueq is NOT a ghost suspect
    assert rep["ghost_suspects"] == []

    plan = asu_assembly_plan(xs)
    assert len(plan) == 1 and plan[0]["labels"] == ["O3"]
    assert plan[0]["n_bonds"] >= 1
    new, moved = apply_assembly_plan(xs, plan)
    after = asu_coherence(new)
    assert after["n_detached_atoms"] == 0
    assert len(after["fragments"]) == 1
    assert new.scatterers().size() == xs.scatterers().size()
    # symmetry-equivalent move: same unit cell + space group
    assert new.space_group() == xs.space_group()


def test_ghost_signature_two_flags():
    # lone O far from everything, half-occupied, inflated Ueq vs O median
    ghost = ("O9", (0.60, 0.60, 0.60), 0.20, 0.5)
    normals = [("O5", (0.40, 0.10, 0.10), 0.03, 1.0),
               ("O6", (0.10, 0.30, 0.10), 0.03, 1.0),
               ("O7", (0.10, 0.10, 0.35), 0.03, 1.0)]
    xs = _structure(_coherent_pair() + normals + [ghost])
    rep = asu_coherence(xs)
    labels = [g["label"] for g in rep["ghost_suspects"]]
    assert "O9" in labels
    g = next(g for g in rep["ghost_suspects"] if g["label"] == "O9")
    assert len(g["reasons"]) >= 2
    assert "delete-and-refine" in g["advice"]
    # the two-branch verdict must be spelled out (real density != delete)
    assert "guest solvent" in g["advice"]


def test_aniso_adp_rotated_on_reassembly():
    op = sgtbx.rt_mx("-x,y+1/2,-z+1/2")
    bonded = (0.25 + 0.14, 0.10, 0.10)
    image = op * bonded
    xs = _structure(_coherent_pair())
    xs.add_scatterer(xray.scatterer(
        label="O3", site=tuple(image), occupancy=1.0, scattering_type="O",
        u=(0.02, 0.04, 0.06, 0.001, 0.002, 0.003)))
    xs.scattering_type_registry(table="it1992")
    uc = xs.unit_cell()
    ueq_before = xs.scatterers()[2].u_iso_or_equiv(uc)
    new, _ = apply_assembly_plan(xs, asu_assembly_plan(xs))
    sc = new.scatterers()[2]
    assert sc.flags.use_u_aniso()
    # Ueq is invariant under the symmetry rotation; the tensor itself changes
    assert abs(sc.u_iso_or_equiv(uc) - ueq_before) < 1e-6
    assert tuple(sc.u_star) != (0.02, 0.04, 0.06, 0.001, 0.002, 0.003)


def test_water_labelled_o_not_ghost():
    # declared solvent water (O1W) is exempt; anonymous O9 still flags
    ghost = ("O9", (0.60, 0.60, 0.60), 0.20, 0.5)
    water = ("O1W", (0.80, 0.20, 0.40), 0.20, 0.5)
    normals = [("O5", (0.40, 0.10, 0.10), 0.03, 1.0),
               ("O6", (0.10, 0.30, 0.10), 0.03, 1.0),
               ("O7", (0.10, 0.10, 0.35), 0.03, 1.0)]
    xs = _structure(_coherent_pair() + normals + [ghost, water])
    rep = asu_coherence(xs)
    labels = [g["label"] for g in rep["ghost_suspects"]]
    assert "O9" in labels and "O1W" not in labels
