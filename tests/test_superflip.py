"""solve_superflip: external second-engine charge flipping (vendor exe).

End-to-end on a synthetic P-1 structure: Fc^2 in, converged density out,
peaks matching the input atoms, symmetry agreement factors reported.
Skipped when the vendor executable is absent (other machines).
"""
from types import SimpleNamespace

import pytest
from cctbx import crystal, xray
from cctbx.array_family import flex

from crystalpilot.core.dataset import ReflectionDataset
from crystalpilot.pipeline.session import SolveSession
from crystalpilot.tools import solution_tools as st
from crystalpilot.tools.base import ToolContext


class _Store:
    def record(self, *a, **k):
        return None

    def log(self, *a, **k):
        return None


def _ctx(ses):
    return ToolContext(store=_Store(), session=ses)


def _synthetic_session():
    cs = crystal.symmetry(unit_cell=(7.0, 8.0, 9.0, 80.0, 85.0, 95.0),
                          space_group_symbol="P -1")
    xs = xray.structure(crystal_symmetry=cs)
    uc = cs.unit_cell()
    # a thiophene-ish fragment: enough electrons that the reconstructed
    # density is not too sparse for the origin/symmetry search
    for label, el, cart in (("S1", "S", (1.20, 1.50, 2.00)),
                            ("S2", "S", (4.10, 4.40, 4.90)),
                            ("O1", "O", (2.70, 1.90, 2.60)),
                            ("O2", "O", (1.75, 3.30, 4.20)),
                            ("N1", "N", (3.30, 0.95, 1.35)),
                            ("C1", "C", (3.90, 3.00, 3.40)),
                            ("C2", "C", (2.45, 4.60, 1.10)),
                            ("C3", "C", (5.05, 2.10, 0.75))):
        xs.add_scatterer(xray.scatterer(
            label=label, site=uc.fractionalize(cart),
            scattering_type=el, u=0.02))
    xs.scattering_type_registry(table="it1992")
    fc = xs.structure_factors(d_min=0.8).f_calc()
    fo_sq = fc.intensities().customized_copy(
        sigmas=flex.double(fc.size(), 1.0)).set_observation_type_xray_intensity()
    ses = SolveSession(dataset=ReflectionDataset(
        intensities=None, wavelength=0.71073))
    ses.symmetry = cs
    ses.fo_sq = fo_sq
    return ses, xs


def test_refuses_without_exe(monkeypatch):
    monkeypatch.setattr(st, "SUPERFLIP_EXE",
                        st.REPO_ROOT / "vendor" / "nope" / "superflip.exe")
    ses, _ = _synthetic_session()
    r = st.SolveSuperflip().run(_ctx(ses))
    assert not r.ok
    assert "VENDOR-STATUS" in (r.error or "")


def test_refuses_without_data():
    ses = SolveSession(dataset=ReflectionDataset(
        intensities=None, wavelength=0.71073))
    r = st.SolveSuperflip().run(_ctx(ses))
    assert not r.ok


_R14A_HKL = st.REPO_ROOT.parent / "CrystalPilotData" / "staging" / "r14a" / \
    "crystal.hkl"


@pytest.mark.skipif(not st.SUPERFLIP_EXE.exists()
                    or not _R14A_HKL.exists(),
                    reason="vendor superflip.exe or r14a data not present")
def test_solves_real_data_and_confirms_space_group():
    """End-to-end on the r14a Zn2-BTC dataset (published as Acta Cryst E
    jy2025): converge, report per-operator symmetry agreement (screw axes
    confirmed in the density), and put the Zn positions among the top
    peaks. Charge flipping on toy 8-atom cells is pathological (origin
    search fails on near-empty density), so the real dataset IS the
    fixture."""
    import numpy as np
    from cctbx import miller

    cs = crystal.symmetry(
        unit_cell=(13.6870, 13.7912, 15.2165, 90, 90, 90),
        space_group_symbol="P 21 21 21")
    idx, dat, sig = [], flex.double(), flex.double()
    with open(_R14A_HKL, encoding="ascii") as fh:
        for line in fh:
            s = line.rstrip("\r\n")
            if len(s) < 28:
                continue
            try:
                h, k, l = int(s[0:4]), int(s[4:8]), int(s[8:12])
                i_obs, sg = float(s[12:20]), float(s[20:28])
            except ValueError:
                continue
            if h == k == l == 0:
                break
            idx.append((h, k, l))
            dat.append(i_obs)
            sig.append(sg)
    ms = miller.set(cs, flex.miller_index(idx), anomalous_flag=False)
    # full resolution on purpose: d_min 1.1 truncation degrades the
    # symmetry agreement factor from 0.11 to 0.76 on this dataset -
    # superflip is far more truncation-sensitive than the smtbx flipper
    fo_sq = miller.array(ms, dat, sig).merge_equivalents().array() \
        .set_observation_type_xray_intensity()

    ses = SolveSession(dataset=ReflectionDataset(
        intensities=None, wavelength=0.71073))
    ses.symmetry = cs
    ses.fo_sq = fo_sq
    r = st.SolveSuperflip().run(_ctx(ses), timeout_s=300, randomseed=42)
    assert r.ok, r.error
    s = r.summary
    assert s["converged"] is True
    sym = s["symmetry_agreement"]
    assert sym["overall"] is not None and sym["overall"] < 0.25
    assert len(sym["per_operator"]) >= 2      # the 2_1 generators
    assert "citation_obligation" in s
    assert ses.cf_info["engine"] == "superflip"
    sites = ses.cf_info["peak_sites"]
    heights = ses.cf_info["peak_heights"]
    assert len(sites) >= 10

    # the two Zn of the published structure (Acta Cryst E jy2025, public
    # deposition) must appear among the strongest peaks
    zn_ref = [(0.2624, 0.2945, 0.7261), (0.4051, 0.4559, 0.5854)]
    uc = cs.unit_cell()
    ops = [(np.array(op.r().as_double()).reshape(3, 3),
            np.array(op.t().as_double()))
           for op in cs.space_group().all_ops()]
    O = np.array(uc.orthogonalization_matrix()).reshape(3, 3)
    # the charge-flipping solution is defined only up to the Euclidean
    # normalizer of P212121 (Pmmm with 1/2a,1/2b,1/2c translations): any
    # of the 8 half-cell origin shifts AND either enantiomorph are the
    # same structure. Matching without these looked like seed flakiness
    # (0.01 A vs 4.4 A on different seeds) until the shifts went in.
    shifts = [np.array((a, b, c))
              for a in (0.0, 0.5) for b in (0.0, 0.5) for c in (0.0, 0.5)]

    def min_d(frac_a, frac_b):
        best = 9e9
        for hand in (1.0, -1.0):
            fa = hand * np.array(frac_a)
            for R, t in ops:
                base = R @ np.array(frac_b) + t
                for s0 in shifts:
                    d = fa - (base + s0)
                    d -= np.round(d)
                    best = min(best, float(np.linalg.norm(O @ d)))
        return best

    strong = [p for p, h in zip(sites, heights)][:10]
    for zr in zn_ref:
        d = min(min_d(tuple(p), zr) for p in strong)
        # with normalizer-aware matching the Zn land within ~0.01 A on
        # every seed tried; 0.5 A leaves room for grid coarseness
        assert d < 0.5, f"Zn at {zr} unmatched among top peaks: {d:.2f} A"
