"""Directional PLD (round-3 R5-D): the pore-limiting diameter ALONG each cell
axis of a percolating void, as attached to every void of the per-node voids
product by `refine.scene._pld_along_axes` - a channel wide along c and
closed along a/b reads c = number, a = b = null, never a single number
that hides the anisotropy."""
from __future__ import annotations

import math

import numpy as np

from crystalpilot.chem.pores import distance_field, pore_limiting_diameter
from crystalpilot.refine.scene import PLD_AXES_BUDGET_S, _pld_along_axes

N = 20
R_C = 1.775


def _cubic(a=10.0):
    from cctbx import uctbx

    return uctbx.unit_cell((a, a, a, 90, 90, 90))


def _one_c_labels(n=N):
    uc = _cubic()
    atoms = np.array([[0.0, 0.0, 0.0]])
    ix, iy, iz = np.indices((n, n, n))
    frac = np.stack([ix / n, iy / n, iz / n], axis=-1).reshape(-1, 3)
    r, _ = distance_field(frac, uc, atoms, ["C"])
    labels = np.where(r.reshape(n, n, n) >= 0.0, 2, 0).astype(np.int32)
    return uc, atoms, ["C"], labels


def test_cubic_cell_reads_the_same_pld_along_every_axis():
    uc, atoms, els, labels = _one_c_labels()
    full = pore_limiting_diameter(labels, 2, uc, atoms, els)
    out = _pld_along_axes(labels, 2, uc, atoms, els, 3, 0.0)
    along = out["pld_along"]
    assert set(along) == {"a", "b", "c"}
    step = full["pld_error_A"]
    for ax in "abc":
        assert along[ax] is not None
        # constrained to one axis the sphere still detours through the
        # (1/2, 1/2, 0) window: same supremum as the free percolation
        assert abs(along[ax] - full["pld_A"]) <= step + 1e-9
        assert abs(along[ax] - 2.0 * (10.0 / math.sqrt(2.0) - R_C)) < 2 * step
    assert out["pld_along_error_A"] == step
    assert "pld_along_note" not in out


def test_channel_along_c_is_open_along_c_and_closed_along_a_b():
    """A cylinder of void along c only: the axial PLDs say c = number and
    a = b = null (the void does not repeat along them) - the anisotropy a
    single PLD cannot express."""
    uc = _cubic()
    atoms = np.array([[0.0, 0.0, 0.0]])
    x, y, _z = np.indices((N, N, N))
    labels = np.zeros((N, N, N), dtype=np.int32)
    labels[(x - 10) ** 2 + (y - 10) ** 2 < 9] = 2
    out = _pld_along_axes(labels, 2, uc, atoms, ["C"], 1, 0.0)
    along = out["pld_along"]
    assert along["a"] is None and along["b"] is None
    assert along["c"] is not None and along["c"] > 0
    full = pore_limiting_diameter(labels, 2, uc, atoms, ["C"])
    assert abs(along["c"] - full["pld_A"]) <= full["pld_error_A"] + 1e-9


def test_cavities_get_no_axial_entry():
    uc, atoms, els, labels = _one_c_labels()
    assert _pld_along_axes(labels, 2, uc, atoms, els, 0, 0.0) == {}


def test_a_slow_full_pld_skips_the_axes_with_a_note():
    """Three more bisections cost about as much as the first; when the
    first already blew the budget the product says so instead of hanging."""
    uc, atoms, els, labels = _one_c_labels()
    out = _pld_along_axes(labels, 2, uc, atoms, els, 3, PLD_AXES_BUDGET_S + 1)
    assert "pld_along" not in out
    assert "skipped" in out["pld_along_note"]
    assert f"{PLD_AXES_BUDGET_S:.0f} s budget" in out["pld_along_note"]
