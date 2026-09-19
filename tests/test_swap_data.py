"""swap_reflection_data: replace crystal.hkl mid-session, model intact.

Functional on real cctbx objects: a synthetic P-1 session whose fo_sq
came from structure A gets swapped to a differently-sized HKLF4 file and
to an HKLF5 twin-batch file; the model must never move, the dataset and
merge must rebuild, flags must track the HKLF code, and a stale solvent
mask must be cleared."""
from types import SimpleNamespace

import pytest
from cctbx import crystal, xray
from cctbx.array_family import flex

from crystalpilot.core.dataset import ReflectionDataset
from crystalpilot.pipeline.session import SolveSession
from crystalpilot.refine.tools_analysis import SwapReflectionData
from crystalpilot.tools.base import ToolContext


class _Store:
    def record(self, *a, **k):
        return None

    def log(self, *a, **k):
        return None


def _session_with_model():
    cs = crystal.symmetry(unit_cell=(7.0, 8.0, 9.0, 90.0, 95.0, 90.0),
                          space_group_symbol="P -1")
    xs = xray.structure(crystal_symmetry=cs)
    uc = cs.unit_cell()
    for label, el, cart in (("S1", "S", (1.2, 1.5, 2.0)),
                            ("O1", "O", (2.7, 1.9, 2.6)),
                            ("C1", "C", (3.9, 3.0, 3.4))):
        xs.add_scatterer(xray.scatterer(
            label=label, site=uc.fractionalize(cart),
            scattering_type=el, u=0.02))
    xs.scattering_type_registry(table="it1992")
    fc = xs.structure_factors(d_min=1.0).f_calc()
    fo_sq = fc.intensities().customized_copy(
        sigmas=flex.double(fc.size(), 1.0)).set_observation_type_xray_intensity()
    ses = SolveSession(dataset=ReflectionDataset(
        intensities=fo_sq.expand_to_p1(), wavelength=0.71073))
    ses.set_symmetry(cs)
    ses.model = xs
    return ses, fo_sq


def _write_hkl(path, fo_sq, n, batch=None):
    with open(path, "w", encoding="ascii", newline="\n") as fh:
        rows = 0
        for hkl, i in zip(fo_sq.indices(), fo_sq.data()):
            if rows >= n:
                break
            tail = f"{batch:4d}" if batch is not None else ""
            fh.write(f"{hkl[0]:4d}{hkl[1]:4d}{hkl[2]:4d}"
                     f"{min(i, 99000.0):8.2f}{1.0:8.2f}{tail}\n")
            rows += 1
        tail = f"{0:4d}" if batch is not None else ""
        fh.write(f"{0:4d}{0:4d}{0:4d}{0.0:8.2f}{0.0:8.2f}{tail}\n")


def _write_hklf5(path, fo_sq, n):
    with open(path, "w", encoding="ascii", newline="\n") as fh:
        rows = 0
        for hkl, i in zip(fo_sq.indices(), fo_sq.data()):
            if rows >= n:
                break
            if rows % 5 == 0:
                # composite pair: minor component line then major
                fh.write(f"{hkl[0]:4d}{hkl[1]:4d}{-hkl[2]:4d}"
                         f"{min(i, 99000.0):8.2f}{1.0:8.2f}{-2:4d}\n")
            fh.write(f"{hkl[0]:4d}{hkl[1]:4d}{hkl[2]:4d}"
                     f"{min(i, 99000.0):8.2f}{1.0:8.2f}{1:4d}\n")
            rows += 1
        fh.write(f"{0:4d}{0:4d}{0:4d}{0.0:8.2f}{0.0:8.2f}{0:4d}\n")


def _proj(tmp_path, ses):
    return SimpleNamespace(dir=tmp_path, session=ses)


def _ctx(ses):
    return ToolContext(store=_Store(), session=ses)


def _sites(xs):
    return [(sc.label, tuple(round(x, 6) for x in sc.site))
            for sc in xs.scatterers()]


def test_refusals(tmp_path):
    ses, fo = _session_with_model()
    t = SwapReflectionData(_proj(tmp_path, ses))
    r = t.run(_ctx(ses), hkl="nope.hkl", reason="x")
    assert not r.ok and "not found" in (r.error or "")
    r = t.run(_ctx(ses), hkl="../evil.hkl", reason="x")
    assert not r.ok
    _write_hkl(tmp_path / "a.hkl", fo, 30)
    r = t.run(_ctx(ses), hkl="a.hkl", reason="")
    assert not r.ok and "reason" in (r.error or "")


def test_swap_hklf4_preserves_model_and_backs_up(tmp_path):
    ses, fo = _session_with_model()
    _write_hkl(tmp_path / "crystal.hkl", fo, 60)
    _write_hkl(tmp_path / "other.hkl", fo, 30)
    before = _sites(ses.model)
    t = SwapReflectionData(_proj(tmp_path, ses))
    r = t.run(_ctx(ses), hkl="other.hkl", reason="cleansed export test")
    assert r.ok, r.error
    s = r.summary
    assert s["hklf"] == 4
    assert s["n_obs"] == 30
    assert s["previous"]["backup"] and \
        (tmp_path / s["previous"]["backup"]).exists()
    assert _sites(ses.model) == before          # model untouched
    assert ses.fo_sq is not None and ses.fo_sq.size() <= 30
    assert int(ses.flags.get("hklf") or 4) == 4


def test_swap_hklf5_sets_twin_flags_and_clears_mask(tmp_path):
    ses, fo = _session_with_model()
    _write_hkl(tmp_path / "crystal.hkl", fo, 60)
    _write_hklf5(tmp_path / "twin5.hkl", fo, 40)
    ses.flags["f_mask"] = object()              # stale mask stand-in
    t = SwapReflectionData(_proj(tmp_path, ses))
    r = t.run(_ctx(ses), hkl="twin5.hkl", reason="twin refinement stage")
    assert r.ok, r.error
    s = r.summary
    assert s["hklf"] == 5 and s["n_domains"] == 2
    assert "hklf5_note" in s and "run_shelxl" in s["hklf5_note"]
    assert "mask_cleared" in s
    assert "f_mask" not in ses.flags
    assert int(ses.flags["hklf"]) == 5
    tw = ses.flags.get("twin")
    assert tw and tw["basf"] == [0.5] and not tw.get("matrix")
    # positive-batch composite view: negative rows excluded from merge
    assert ses.fo_sq.size() <= 40
