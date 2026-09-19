"""Restraints-in-RefineLS tests (M2 gate) on the SJTU-9 reference data."""
from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
CASE = (REPO / "benchmark" / "data" /
        "重复SJTU-9_SJTU-9_or_post_晶体数据_原始SJTU-9_olex2_temp_sjtu-9")

pytestmark = pytest.mark.skipif(not CASE.exists(), reason="SJTU-9 case missing")


def make_session(tmp_path):
    """SolveSession on SJTU-9 data with the human reference model (H stripped)."""
    from cctbx.array_family import flex
    from crystalpilot.core.events import RunStore
    from crystalpilot.io.shelx import load_shelx_dataset
    from crystalpilot.io.shelx_model import load_res_model
    from crystalpilot.pipeline.session import SolveSession
    from crystalpilot.tools.base import ToolContext

    dataset = load_shelx_dataset(CASE / "hkl.hkl", ins_path=CASE / "ref_res.res")
    ses = SolveSession(dataset=dataset)
    ses.set_symmetry(dataset.symmetry_hint)
    m = load_res_model(CASE / "ref_res.res")
    xs = m.structure
    h_sel = flex.bool([sc.scattering_type.strip().upper() == "H"
                       for sc in xs.scatterers()])
    xs = xs.select(~h_sel)
    xs.scattering_type_registry(table="it1992")
    ses.model = xs
    ses.flags["weights"] = {"a": m.weights[0], "b": m.weights[1]}
    ctx = ToolContext(store=RunStore(tmp_path / "runs"), session=ses)
    return ctx, m


def refine(ctx, **kw):
    from crystalpilot.tools.refinement_tools import RefineLS
    res = RefineLS().run(ctx, **kw)
    assert res.ok, res.error
    return res.summary


def u11_of(xs, label):
    from cctbx import adptbx
    for sc in xs.scatterers():
        if sc.label == label:
            u = adptbx.u_star_as_u_cif(xs.unit_cell(), sc.u_star)
            return u[0]
    raise KeyError(label)


def dist(xs, a, b):
    uc = xs.unit_cell()
    site = {sc.label: sc.site for sc in xs.scatterers()}
    pa, pb = uc.orthogonalize(site[a]), uc.orthogonalize(site[b])
    return sum((x - y) ** 2 for x, y in zip(pa, pb)) ** 0.5


def test_no_restraints_baseline_unchanged(tmp_path):
    """Empty restraints flag must leave the refinement numerically identical."""
    ctx1, _ = make_session(tmp_path / "a")
    s1 = refine(ctx1, mode="anisotropic", n_cycles=3)
    ctx2, _ = make_session(tmp_path / "b")
    ctx2.session.flags["restraints"] = []          # present but empty
    s2 = refine(ctx2, mode="anisotropic", n_cycles=3)
    assert s1["r1_strong"] == s2["r1_strong"]
    assert s1["wr2"] == s2["wr2"]
    assert "n_restraints" not in s2


def test_isor_tames_wild_adp(tmp_path):
    """O007 has U11=0.355 in the reference; a tight ISOR must pull it down and
    the summary must report restraint bookkeeping."""
    ctx, _ = make_session(tmp_path)
    base = refine(ctx, mode="anisotropic", n_cycles=3)
    u11_before = u11_of(ctx.session.model, "O007")
    assert u11_before > 0.30
    # O007's big U11 is genuinely data-supported (disordered/aqua O), so a
    # nominal SHELX sigma is a gentle prior; a hard sigma must visibly win.
    ctx.session.flags["restraints"] = [
        {"kind": "ISOR", "atoms": ["O007"], "sigma": 0.0001}]
    s = refine(ctx, mode="anisotropic", n_cycles=10)
    u11_after = u11_of(ctx.session.model, "O007")
    assert u11_after < u11_before - 0.05
    assert s["n_restraints"] > 0
    assert s["goof_restrained"] is not None
    assert any("ISOR" in a for a in s["restraints_applied"])
    assert s["r1_strong"] > base["r1_strong"]   # honesty: forcing iso costs R1


def test_dfix_has_teeth(tmp_path):
    """A harsh DFIX toward a wrong target must move the bond away from the
    data-optimal distance - proves restraints enter the minimization."""
    ctx, _ = make_session(tmp_path)
    refine(ctx, mode="anisotropic", n_cycles=2)
    d0 = dist(ctx.session.model, "C008", "C009")
    assert 1.30 < d0 < 1.48
    ctx.session.flags["restraints"] = [
        {"kind": "DFIX", "atoms": [["C008", "C009"]], "target": 1.60,
         "sigma": 0.001}]
    refine(ctx, mode="anisotropic", n_cycles=8)
    d1 = dist(ctx.session.model, "C008", "C009")
    assert d1 > d0 + 0.06


def test_symmetry_pair_guard(tmp_path):
    """A pair bonded only through symmetry (long direct distance) is refused
    with a warning instead of silently restraining the wrong geometry."""
    ctx, _ = make_session(tmp_path)
    ctx.session.flags["restraints"] = [
        {"kind": "DFIX", "atoms": [["ZR01", "C00B"]], "target": 2.2,
         "sigma": 0.02}]
    s = refine(ctx, mode="isotropic", n_cycles=2)
    assert any("symmetry" in w for w in s.get("restraint_warnings", []))
    assert "n_restraints" not in s      # nothing was actually applied


def test_fix_atoms(tmp_path):
    ctx, _ = make_session(tmp_path)
    before = {sc.label: tuple(sc.site) for sc in ctx.session.model.scatterers()}
    s = refine(ctx, mode="isotropic", n_cycles=3, fix_atoms=["ZR01", "ZR02"])
    after = {sc.label: tuple(sc.site) for sc in ctx.session.model.scatterers()}

    def moved_by(lbl):   # special-position projection adds ~1e-17 float noise
        return max(abs(a - b) for a, b in zip(before[lbl], after[lbl]))

    assert moved_by("ZR01") < 1e-12
    assert moved_by("ZR02") < 1e-12
    assert s["fixed_atoms"] == ["ZR01", "ZR02"]
    assert any(moved_by(l) > 1e-6 for l in before)   # everything else refined


def test_cards_roundtrip():
    from crystalpilot.refine.restraints import (emit_shelx_cards,
                                                normalize_spec,
                                                parse_shelx_cards)
    specs = [normalize_spec(s) for s in [
        {"kind": "DFIX", "atoms": [["C1", "C2"]], "target": 1.39},
        {"kind": "SADI", "atoms": [["C1", "C2"], ["C3", "C4"]]},
        {"kind": "FLAT", "atoms": ["C1", "C2", "C3", "C4", "C5", "C6"]},
        {"kind": "SIMU", "atoms": None},
        {"kind": "DELU", "atoms": ["C1", "C2"]},
        {"kind": "ISOR", "atoms": ["O7"], "sigma": 0.05},
    ]]
    cards = emit_shelx_cards(specs)
    joined = []
    for c in cards:
        joined.extend([ln for ln in c.replace(" =\n ", " ").splitlines()])
    parsed, warnings = parse_shelx_cards(joined)
    assert not warnings
    assert parsed == specs
