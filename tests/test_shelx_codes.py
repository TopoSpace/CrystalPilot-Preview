"""SHELX parameter-coding guards (reg1-mof cage n0152, 2026-09-04).

An anisotropic refinement drove C010 to U33 = 16.58 A^2; the node was
written and every SHELX reader then decoded the card as "-3.42 x free
variable 2" - checkout/ghost_test died with an IndexError inside iotbx and
the agent lost its best node. Three guards: the writer refuses, the loader
names the atom, and `refine` reverts the runaway before committing."""
from __future__ import annotations

import pytest
from cctbx import adptbx

from crystalpilot.io.shelx_codes import (code_of, dangling_free_variable_refs,
                                         free_encodable,
                                         unencodable_free_params)

HEAD = """TITL t in P -1
CELL 0.71073 10.0 11.0 12.0 90.0 90.0 90.0
ZERR 2 0 0 0 0 0 0
LATT 1
SFAC C O
UNIT 4 4
"""
FOOT = "HKLF 4\nEND\n"

DIVERGED = HEAD + """FVAR 0.10694
C1   1   0.100000   0.200000   0.300000    11.00000     0.05000
O1   2   0.400000   0.500000   0.600000    11.00000     0.69110     6.33906 =
     16.58169    -9.96284    -2.38409     1.73432
""" + FOOT

DISORDER = HEAD + """FVAR 0.10694 0.60000
C1   1   0.100000   0.200000   0.300000    21.00000     0.05000
O1   2   0.400000   0.500000   0.600000   -21.00000     0.06000
""" + FOOT


def test_code_of_follows_the_nearest_multiple_of_ten():
    assert code_of(21.0) == (2, 1.0)
    assert code_of(11.0) == (1, 1.0)
    assert code_of(16.58169)[0] == 2            # what iotbx/SHELXL see
    assert code_of(6.33906)[0] == 1             # silently "fixed at -3.66"
    assert code_of(-21.0) == (-2, -1.0)
    assert code_of(0.05) == (0, 0.05)
    assert free_encodable(4.99) and free_encodable(-4.99)
    assert not free_encodable(5.0) and not free_encodable(16.58)


def test_unencodable_and_dangling_helpers():
    assert unencodable_free_params((0.1, 0.2, 0.3), u_iso=0.05) == []
    bad = unencodable_free_params((0.1, 7.3, 0.3), u_cif=(0.05, 6.3, 16.6, -9.96, 0, 0))
    assert [n for n, _ in bad] == ["y", "U22", "U33", "U23"]
    fields = [0.4, 0.5, 0.6, 11.0, 0.6911, 6.33906, 16.58169, -9.96284, -2.38409, 1.73432]
    assert dangling_free_variable_refs(fields, 1) == [("U33", 16.58169, 2)]
    assert dangling_free_variable_refs([0.1, 0.2, 0.3, 21.0, 0.05], 2) == []
    assert dangling_free_variable_refs([0.1, 0.2, 0.3, 21.0, 0.05], 1) == [("sof", 21.0, 2)]


def test_loader_names_the_diverged_atom(tmp_path):
    from crystalpilot.io.shelx_model import load_res_model
    p = tmp_path / "model.res"
    p.write_text(DIVERGED, encoding="ascii")
    with pytest.raises(ValueError) as ei:
        load_res_model(p)
    msg = str(ei.value)
    assert "O1 U33 = 16.58169" in msg
    assert "free variable 2" in msg and "FVAR defines 1" in msg
    assert "ADP diverged" in msg and "parent node" in msg


def test_loader_still_accepts_real_free_variable_codes(tmp_path):
    from crystalpilot.io.shelx_model import load_res_model
    p = tmp_path / "model.res"
    p.write_text(DISORDER, encoding="ascii")
    m = load_res_model(p)
    assert m.structure.scatterers().size() == 2
    assert m.sof_codes == {"C1": 21.0, "O1": -21.0}
    assert m.fvar_extra == [0.6]


def _runaway(sc, uc, u33=16.6):
    sc.u_star = adptbx.u_cart_as_u_star(uc, (0.05, 0.05, u33, 0.0, 0.0, 0.0))
    sc.set_use_u_aniso_only()


def test_writer_refuses_an_unencodable_adp(tmp_path):
    from crystalpilot.io.shelx_model import load_res_model
    from crystalpilot.io.shelx_writer import ShelxModel, write_res_text
    p = tmp_path / "model.res"
    p.write_text(DISORDER, encoding="ascii")
    xs = load_res_model(p).structure
    text, _ = write_res_text(ShelxModel(xray_structure=xs, scale=0.1,
                                        fvars=[0.6]))
    assert "C1 " in text
    _runaway(xs.scatterers()[1], xs.unit_cell())
    with pytest.raises(ValueError) as ei:
        write_res_text(ShelxModel(xray_structure=xs, scale=0.1, fvars=[0.6]))
    assert "O1: U33 = 16.6" in str(ei.value)
    assert "diverged" in str(ei.value)


def test_refine_reverts_runaway_parameters(tmp_path):
    from crystalpilot.io.shelx_model import load_res_model
    from crystalpilot.tools.refinement_tools import (_revert_unencodable,
                                                     _snapshot_params)
    p = tmp_path / "model.res"
    p.write_text(DISORDER, encoding="ascii")
    xs = load_res_model(p).structure
    uc = xs.unit_cell()
    start = _snapshot_params(xs)
    c1, o1 = xs.scatterers()
    xs.convert_to_anisotropic()                  # what mode='anisotropic' does
    c1.flags.set_grad_u_aniso(True)
    o1.flags.set_grad_u_aniso(True)
    _runaway(o1, uc)
    o1.site = (0.4, 7.3, 0.6)                    # coordinate ran away too
    recs = _revert_unencodable(xs, start)
    assert [r["atom"] for r in recs] == ["O1"]
    assert set(recs[0]["runaway"]) == {"y", "U33"}
    assert not o1.flags.use_u_aniso()
    assert o1.u_iso == pytest.approx(0.06)
    assert o1.flags.grad_u_iso() and not o1.flags.grad_u_aniso()
    assert tuple(o1.site) == pytest.approx((0.4, 0.5, 0.6))
    assert "isotropic Uiso 0.0600" in recs[0]["adp"]
    assert c1.flags.use_u_aniso()                # untouched neighbour
    # an atom that was anisotropic BEFORE the cycles goes back to that ADP
    start2 = _snapshot_params(xs)
    _runaway(c1, uc)
    recs = _revert_unencodable(xs, start2)
    assert [r["atom"] for r in recs] == ["C1"]
    assert c1.flags.use_u_aniso()
    assert tuple(c1.u_star) == pytest.approx(start2["C1"]["u_star"])
    assert "anisotropic ADP" in recs[0]["adp"]


def test_objective_only_pass_yields_the_metrics_the_tool_reports():
    """After a revert the tool rebuilds the LS and calls build_up
    (objective_only) once: R1 / wR2 / GooF must come out of that pass."""
    from smtbx.refinement import constraints, least_squares
    import smtbx.utils
    from test_mask_bypass import _framework_and_solvent
    xs, fo_sq = _framework_and_solvent()
    for sc in xs.scatterers():                 # what the tool does per atom
        sc.flags.set_grad_site(True)
        sc.flags.set_grad_u_iso(not sc.flags.use_u_aniso())
        sc.flags.set_grad_u_aniso(sc.flags.use_u_aniso())
    ct = smtbx.utils.connectivity_table(xs)
    rep = constraints.reparametrisation(structure=xs, constraints=[],
                                        connectivity_table=ct)
    ls = least_squares.crystallographic_ls(
        fo_sq.as_xray_observations(), rep,
        weighting_scheme=least_squares.mainstream_shelx_weighting(a=0.1, b=0.0))
    ls.build_up(objective_only=True)
    r1, n = ls.r1_factor(cutoff_factor=2)
    assert 0.0 <= r1 <= 1.0 and n > 0
    assert ls.wR2() > 0 and ls.goof() > 0
    assert rep.n_independents > 0


def test_long_sfac_unit_fvar_cards_are_continued_and_round_trip(tmp_path):
    """22 element types (a mixed-metal element_scan) used to overflow the
    80-column SFAC/UNIT cards; SHELXL then read a truncated element list."""
    from cctbx import crystal, sgtbx, xray
    from crystalpilot.io.shelx_model import load_res_model
    from crystalpilot.io.shelx_writer import ShelxModel, write_res_text
    elements = ["C", "H", "N", "O", "F", "Na", "Mg", "Al", "Si", "P", "S",
                "Cl", "K", "Ca", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu"]
    xs = xray.structure(crystal_symmetry=crystal.symmetry(
        unit_cell=(20, 21, 22, 90, 90, 90),
        space_group_info=sgtbx.space_group_info("P 1")))
    for i, el in enumerate(elements):
        xs.add_scatterer(xray.scatterer(
            label=f"{el.upper()}{i}", scattering_type=el,
            site=(0.03 * i, 0.5, 0.25), u=0.03, occupancy=1.0))
    text, _ = write_res_text(ShelxModel(xray_structure=xs, scale=0.1,
                                        fvars=[0.5] * 14))
    assert max(len(ln) for ln in text.splitlines()) <= 80
    assert text.count("SFAC") == 1 and "=\n" in text
    p = tmp_path / "wide.res"
    p.write_text(text, encoding="ascii")
    m = load_res_model(p)
    assert m.sfac == ["C", "H"] + sorted(
        (e for e in elements if e not in ("C", "H")),
        key=lambda e: elements.index(e))    # ascending Z = list order here
    assert m.structure.scatterers().size() == 22
    assert len(m.fvar_extra) == 14
