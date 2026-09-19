"""Absence evidence with a null comparison (pa2 hex-l2-r2 R-3 trap)."""
from __future__ import annotations

import random

from cctbx import crystal, miller, sgtbx
from cctbx.array_family import flex

from crystalpilot.refine import absence_test as at

CELL = (10.0, 12.0, 14.0, 90.0, 90.0, 90.0)


def _data(absent_scale: float, noise_only: bool = False, seed: int = 1):
    """Unmerged-like P1 intensities on a P-lattice; reflections in the
    C-centring 'absent' class (h+k odd) get `absent_scale` x the signal."""
    rng = random.Random(seed)
    cs = crystal.symmetry(unit_cell=CELL, space_group_symbol="P 1")
    ms = miller.build_set(cs, anomalous_flag=False, d_min=1.2)
    idx = ms.indices()
    data, sig = flex.double(), flex.double()
    for h, k, l in idx:
        s = 1.0
        if noise_only:
            i = rng.gauss(0.0, 1.0)
        else:
            i = rng.expovariate(1.0 / 50.0)
            if (h + k) % 2:
                i *= absent_scale
            i += rng.gauss(0.0, 1.0)
        data.append(i)
        sig.append(s)
    return miller.array(ms, data, sig).set_observation_type_xray_intensity()


def test_true_centring_absence_is_confirmed():
    c = at.absence_contrast(_data(0.0), sgtbx.space_group("C 2y"))
    assert c["verdict"] == "absent"
    assert c["ratio_mean"] < 0.3 and c["ratio_strong"] < 0.3
    assert c["centring"]["verdict"] == "absent"
    assert 0.4 < c["discarded_fraction"] < 0.6


def test_fake_centring_is_violated_when_the_class_carries_signal():
    c = at.absence_contrast(_data(1.0), sgtbx.space_group("C 2y"))
    assert c["verdict"] == "violated"


def test_noise_only_data_is_undecidable_not_consistent():
    # the hex trap: everything averages noise, absent and present alike
    c = at.absence_contrast(_data(1.0, noise_only=True),
                            sgtbx.space_group("C 2y"))
    assert c["verdict"] == "undecidable"
    assert c["present_data_too_weak"] is True
    assert "UNDECIDABLE" in at.describe(c)


def test_primitive_group_has_no_absence_conditions():
    c = at.absence_contrast(_data(0.0), sgtbx.space_group("P 2y"))
    assert c["verdict"] == "no_absence_conditions"
    assert c["centring"]["lattice"] == "P"
    assert at.describe(c) == "no absence conditions"
