"""validate_structure's post-refinement element check for LIGHT atoms.

reg1-ext2 case rz (twin_rz5267_iucr, C2/c, 2026-09-04): interpret_peaks'
metal-free branch never guesses C vs N (17 % in Z) and hands such sites
out labelled C with element_uncertain. The agent refined that model,
delivered a nitro group's nitrogen as a carbon and defended it as a
carboxylate ("C1(O4)(O5)"), giving C30H24N2O9 against a reference
C28H22N4O9. Geometry cannot separate the two motifs - nitro N-O 1.21-1.23
A vs carboxylate C-O 1.25-1.28 A - but the refinement can: a label with
too few electrons is compensated by a Ueq that comes out too small.

Every structure below is synthetic and built from ordinary organic
geometry (C-C 1.39/1.50, C-O 1.25, N-O 1.22 A), and every Ueq that
carries a verdict is produced by ACTUALLY REFINING u_iso against Fo^2
computed from the correctly-typed structure - the mislabel is introduced
only in the model that is refined. Nothing here is tuned to one crystal:
five different motifs (nitro, carboxylate, secondary amide, a partly
occupied site and a metal complex) go through the same rule.
"""
from __future__ import annotations

import math

import pytest
import smtbx.utils
from cctbx import crystal, xray
from cctbx.array_family import flex
from scitbx.lstbx import normal_eqns_solving
from smtbx.refinement import constraints, least_squares

from crystalpilot.chem.light_atom_adp import (_REF_Z_FACTOR, _UEQ_RATIO_HIGH,
                                              _UEQ_RATIO_LOW,
                                              audit_light_atom_elements,
                                              one_step_in_z)
from crystalpilot.core.dataset import ReflectionDataset
from crystalpilot.pipeline.session import RefinementSnapshot, SolveSession
from crystalpilot.tools.base import ToolContext
from crystalpilot.tools.validation_tools import ValidateStructure

D_MIN = 0.83
CELL = (13.0, 14.0, 15.0, 90, 90, 90)


class _Store:
    def record(self, *a, **k):
        return None

    def log(self, *a, **k):
        return None


# --------------------------------------------------------------------- #
# synthetic structures (cartesian A, built from bond lengths only)
# --------------------------------------------------------------------- #

def _structure(atoms, cell=CELL, sg="P 1"):
    """atoms: (label, element, cartesian xyz, u[, occupancy])."""
    cs = crystal.symmetry(unit_cell=cell, space_group_symbol=sg)
    xs = xray.structure(crystal_symmetry=cs)
    uc = cs.unit_cell()
    for atom in atoms:
        label, el, cart, u = atom[:4]
        occ = atom[4] if len(atom) > 4 else 1.0
        xs.add_scatterer(xray.scatterer(
            label=label, site=uc.fractionalize(cart), scattering_type=el,
            u=u, occupancy=occ))
    xs.scattering_type_registry(table="it1992")
    return xs


def _ring(centre=(6.0, 6.0, 6.0), u=0.024, prefix="C"):
    """Flat C6 ring, C-C 1.39 A, in the z = centre[2] plane."""
    r = 1.39
    return [(f"{prefix}{k + 1}", "C",
             (centre[0] + r * math.cos(math.radians(60 * k)),
              centre[1] + r * math.sin(math.radians(60 * k)), centre[2]), u)
            for k in range(6)]


def _xo2_on_ring(x_el, d_cx, d_xo, u_x, u_o, centre=(6.0, 6.0, 6.0),
                 u_ring=0.024, occ_x=1.0):
    """Ring + a planar X(O)2 group on C1: nitro (X = N, 1.47/1.22 A) or
    carboxylate (X = C, 1.50/1.25 A). Same skeleton, same angles - only
    the element and the two distances differ, which is exactly why
    geometry cannot tell them apart."""
    atoms = _ring(centre, u_ring)
    x = (centre[0] + 1.39 + d_cx, centre[1], centre[2])
    atoms.append(("X1", x_el, x, u_x, occ_x))
    for s, name in ((+1, "O1"), (-1, "O2")):
        atoms.append((name, "O",
                      (x[0] + d_xo * math.cos(math.radians(60)),
                       x[1] + s * d_xo * math.sin(math.radians(60)),
                       x[2]), u_o))
    return atoms


def nitro_on_ring(**kw):
    return _xo2_on_ring("N", 1.47, 1.22, kw.pop("u_x", 0.026),
                        kw.pop("u_o", 0.041), **kw)


def carboxylate_on_ring(**kw):
    return _xo2_on_ring("C", 1.50, 1.25, kw.pop("u_x", 0.024),
                        kw.pop("u_o", 0.038), **kw)


def n_methyl_acetamide(origin=(6.0, 6.0, 6.0)):
    """CH3-C(=O)-NH-CH3: the amide N has TWO non-H neighbours, so it is a
    skeleton atom the rule can compare (a primary amide N is terminal and
    is deliberately skipped)."""
    x, y, z = origin
    return [
        ("C1", "C", (x, y, z), 0.036),                       # methyl
        ("C2", "C", (x + 1.50, y, z), 0.023),                # carbonyl
        ("O1", "O", (x + 1.50 + 1.23 * math.cos(math.radians(60)),
                     y + 1.23 * math.sin(math.radians(60)), z), 0.034),
        ("N1", "N", (x + 1.50 + 1.34 * math.cos(math.radians(60)),
                     y - 1.34 * math.sin(math.radians(60)), z), 0.026),
        ("C3", "C", (x + 1.50 + 1.34 * math.cos(math.radians(60)) + 1.46,
                     y - 1.34 * math.sin(math.radians(60)) - 0.30, z), 0.037),
    ]


def methylpyridine(centre=(6.0, 6.0, 6.0), n_element="N", u=0.024,
                   u_n=0.026, sub_at=3):
    """3-methylpyridine: a six-ring whose position 1 is a nitrogen, with NO
    terminal neighbour on the heteroatom, so the rule works off two ring
    carbons alone. The methyl breaks the ring's pseudo-hexagonal symmetry -
    see test_a_bare_symmetric_ring_delocalises_the_error for why that
    matters."""
    atoms = _ring(centre, u)
    atoms[0] = (f"{n_element}1", n_element, atoms[0][2], u_n)
    a = math.radians(60 * (sub_at - 1))
    atoms.append(("C7", "C", (centre[0] + 2.89 * math.cos(a),
                              centre[1] + 2.89 * math.sin(a), centre[2]),
                  0.038))
    return atoms


def zn_aqua_complex(origin=(7.0, 7.0, 7.0)):
    """Zn with four donors at the M-O distance, one of them labelled C
    with no carbon skeleton - the case metal_bonded_light_atom exists for.
    Untouched by the new light-atom rule (it needs two non-H neighbours)."""
    x, y, z = origin
    d = 2.05
    return [
        ("ZN1", "Zn", (x, y, z), 0.020),
        ("O1", "O", (x + d, y, z), 0.030),
        ("O2", "O", (x - d, y, z), 0.031),
        ("O3", "O", (x, y + d, z), 0.030),
        ("C9", "C", (x, y - d, z), 0.029),
    ]


# --------------------------------------------------------------------- #
# real refinement of synthetic Fo^2
# --------------------------------------------------------------------- #

def _fo_sq(xs, d_min=D_MIN):
    fc = xs.structure_factors(d_min=d_min, algorithm="direct").f_calc()
    i = fc.as_intensity_array()
    return i.customized_copy(
        sigmas=flex.double(i.size(), 1.0)).set_observation_type_xray_intensity()


def _refine_u_iso(xs, data, n_cycles=30):
    """Refine u_iso only (sites and occupancies fixed) - the cleanest way
    to see what the ADP absorbs when a label carries the wrong Z."""
    xs = xs.deep_copy_scatterers()
    for sc in xs.scatterers():
        sc.flags.set_grad_site(False)
        sc.flags.set_grad_u_iso(True)
        sc.flags.set_grad_u_aniso(False)
        sc.flags.set_grad_occupancy(False)
    ct = smtbx.utils.connectivity_table(xs)
    rep = constraints.reparametrisation(structure=xs, constraints=[],
                                        connectivity_table=ct)
    ls = least_squares.crystallographic_ls(
        data.as_xray_observations(), rep,
        weighting_scheme=least_squares.mainstream_shelx_weighting(a=0.0, b=0.0))
    normal_eqns_solving.levenberg_marquardt_iterations(
        ls, n_max_iterations=n_cycles, gradient_threshold=1e-9,
        step_threshold=1e-9)
    return xs


def refined_model(atoms, mislabel: dict[str, str] | None = None,
                  u_start: float = 0.028, d_min: float = D_MIN):
    """Fo^2 from the TRUE structure, then refine u_iso of a model whose
    labels may be wrong. Returns the refined structure."""
    true = _structure(atoms)
    data = _fo_sq(true, d_min)
    trial = true.deep_copy_scatterers()
    for sc in trial.scatterers():
        sc.u_iso = u_start
        if mislabel and sc.label in mislabel:
            sc.scattering_type = mislabel[sc.label]
    trial.scattering_type_registry(table="it1992")
    return _refine_u_iso(trial, data)


def _ueq(xs, label):
    uc = xs.unit_cell()
    for sc in xs.scatterers():
        if sc.label == label:
            return float(sc.u_iso_or_equiv(uc))
    raise KeyError(label)


# --------------------------------------------------------------------- #
# session plumbing
# --------------------------------------------------------------------- #

def _session(xs, n_refinements=1, d_min=D_MIN):
    ses = SolveSession(dataset=ReflectionDataset(intensities=None,
                                                 wavelength=0.71073))
    ses.model = xs
    ses.symmetry = xs.crystal_symmetry()
    ses.merge_info = {"d_min": d_min}
    for k in range(n_refinements):
        ses.refinement_history.append(RefinementSnapshot(
            label=f"r{k}", r1_strong=0.04, r1_all=0.05, wr2=0.10, goof=1.0,
            n_params=50, n_reflections=2000))
    return ses


def _validate(xs, **params):
    return ValidateStructure().run(
        ToolContext(store=_Store(), session=_session(xs)), **params)


def _check(xs, **kw):
    return audit_light_atom_elements(xs, n_refinements=1, d_min=D_MIN, **kw)


def _flag(result, label):
    for f in result["flags"]:
        if f["label"] == label:
            return f
    return None


def _motif(result, label):
    for m in result["nitro_vs_carboxylate_candidates"]:
        if m["label"] == label:
            return m
    return None


# --------------------------------------------------------------------- #
# (i) a nitro nitrogen delivered as a carbon
# --------------------------------------------------------------------- #

def test_nitro_nitrogen_labelled_carbon_is_flagged_too_light():
    xs = refined_model(nitro_on_ring(), mislabel={"X1": "C"})
    # the refinement really did eat the missing electron into the ADP
    assert _ueq(xs, "X1") < 0.5 * _ueq(xs, "C1"), _ueq(xs, "X1")

    r = _check(xs)
    assert r["status"] == "checked"
    f = _flag(r, "X1")
    assert f is not None, r["flags"]
    assert f["kind"] == "too_light_label"
    assert f["suggested_element"] == "N"
    assert "nitro" in f["suggested_element_note"]
    assert f["ratio"] < _UEQ_RATIO_LOW
    assert f["confidence"] in ("medium", "high")
    # the numbers the agent needs to judge for itself
    assert f["ueq"] == pytest.approx(_ueq(xs, "X1"), abs=1e-4)
    assert f["neighbour_median_ueq"] > 0
    assert {n["label"] for n in f["neighbours"]} == {"C1", "O1", "O2"}
    # implied electron count lands on nitrogen, not on carbon
    assert 6.4 <= f["implied_electron_count"] <= 8.0, f


def test_the_nitro_motif_reads_nitro_not_carboxylate():
    xs = refined_model(nitro_on_ring(), mislabel={"X1": "C"})
    m = _motif(_check(xs), "X1")
    assert m is not None
    assert m["suspect"] is True
    assert "NITRO" in m["reading"]
    assert m["ratio_over_terminal_o"] < _UEQ_RATIO_LOW
    assert m["third_neighbour"]["element"] == "C"
    assert len(m["terminal_oxygens"]) == 2
    assert m["planarity_angle_sum_deg"] > 350
    # the hint says why geometry could not have decided it
    assert "1.21" in m["geometry_note"] and "1.25" in m["geometry_note"]


def test_validate_structure_raises_both_alerts_and_never_relabels():
    xs = refined_model(nitro_on_ring(), mislabel={"X1": "C"})
    before = [(sc.label, sc.scattering_type) for sc in xs.scatterers()]
    res = _validate(xs)
    codes = {a["code"] for a in res.summary["alerts"]}
    assert "light_atom_element_check" in codes
    assert "nitro_vs_carboxylate" in codes
    assert res.summary["light_atom_element_check"]["n_flagged"] >= 1
    # a hint, never an edit
    assert [(sc.label, sc.scattering_type) for sc in xs.scatterers()] == before


# --------------------------------------------------------------------- #
# (ii) the same group, correctly labelled
# --------------------------------------------------------------------- #

def test_correctly_labelled_nitro_group_is_not_flagged():
    xs = refined_model(nitro_on_ring())
    r = _check(xs)
    assert r["status"] == "checked"
    assert _flag(r, "X1") is None, _flag(r, "X1")
    assert r["n_flagged"] == 0, r["flags"]
    m = _motif(r, "X1")
    assert m is not None and m["suspect"] is False
    assert "consistent with a nitro" in m["reading"]


# --------------------------------------------------------------------- #
# (iii) a carboxylate, correctly labelled C
# --------------------------------------------------------------------- #

def test_correct_carboxylate_carbon_is_not_flagged():
    xs = refined_model(carboxylate_on_ring())
    r = _check(xs)
    assert _flag(r, "X1") is None, _flag(r, "X1")
    assert r["n_flagged"] == 0, r["flags"]
    m = _motif(r, "X1")
    assert m is not None and m["suspect"] is False
    assert "carboxylate" in m["reading"]


def test_hard_librating_carboxylate_oxygens_do_not_manufacture_a_nitro():
    """The false positive this check must not have. A carboxylate whose two
    oxygens librate hard (2.2x the ring) drops the C/O ratio below the band
    on its own, with nothing wrong with the element. The wider,
    non-terminal reference vetoes it: no flag, no alert, and the motif hint
    says out loud that the oxygens' libration explains it."""
    xs = refined_model(carboxylate_on_ring(u_x=0.024, u_o=0.055))
    r = _check(xs)
    m = _motif(r, "X1")
    assert m is not None
    assert m["ratio_over_terminal_o"] < _UEQ_RATIO_LOW      # the naive reading
    assert _flag(r, "X1") is None                            # ... is vetoed
    assert m["flagged_by_ueq_band"] is False
    assert m["confidence"] == "low"
    assert "libration explains this" in m["reading"]
    res = _validate(xs)
    assert "nitro_vs_carboxylate" not in {a["code"]
                                          for a in res.summary["alerts"]}


def test_a_carboxylate_carbon_labelled_nitrogen_is_flagged_too_heavy():
    """The other direction of the same motif: too many electrons in the
    label inflate Ueq instead of shrinking it."""
    xs = refined_model(carboxylate_on_ring(), mislabel={"X1": "N"})
    f = _flag(_check(xs), "X1")
    assert f is not None
    assert f["kind"] == "too_heavy_label"
    assert f["suggested_element"] == "C"
    assert "carboxylate" in f["suggested_element_note"]
    assert f["ratio"] > _UEQ_RATIO_HIGH


# --------------------------------------------------------------------- #
# (iv) an amide nitrogen delivered as an oxygen
# --------------------------------------------------------------------- #

def test_amide_nitrogen_labelled_oxygen_is_flagged_too_heavy():
    xs = refined_model(n_methyl_acetamide(), mislabel={"N1": "O"})
    assert _ueq(xs, "N1") > 1.5 * _ueq(xs, "C2"), _ueq(xs, "N1")
    f = _flag(_check(xs), "N1")
    assert f is not None
    assert f["kind"] == "too_heavy_label"
    assert f["suggested_element"] == "N"
    assert f["ratio"] > _UEQ_RATIO_HIGH
    assert 6.0 <= f["implied_electron_count"] <= 7.6, f
    # no X(O)2 motif here: the amide N carries no terminal oxygen
    assert _motif(_check(xs), "N1") is None


def test_correct_amide_is_not_flagged():
    xs = refined_model(n_methyl_acetamide())
    r = _check(xs)
    assert r["n_flagged"] == 0, r["flags"]


# --------------------------------------------------------------------- #
# a fifth motif with no terminal neighbour at all: a ring heteroatom
# --------------------------------------------------------------------- #

def test_ring_nitrogen_labelled_carbon_is_flagged_with_no_motif_at_all():
    """No X(O)2 here and no librating terminal neighbour to lean on - just
    two ring carbons as the reference. The Ueq rule alone has to carry it,
    which is what makes it general rather than a nitro detector."""
    xs = refined_model(methylpyridine(), mislabel={"N1": "C"})
    r = _check(xs)
    f = _flag(r, "N1")
    assert f is not None, r["flags"]
    assert f["kind"] == "too_light_label"
    assert f["suggested_element"] == "N"
    assert f["motif"] is None
    assert r["nitro_vs_carboxylate_candidates"] == []
    assert f["confidence"] == "high"
    assert 6.3 <= f["implied_electron_count"] <= 7.6, f
    # and nothing else in the ring is dragged along with it
    assert r["n_flagged"] == 1, r["flags"]


def test_all_carbon_ring_is_clean():
    xs = refined_model(methylpyridine(n_element="C", u_n=0.024))
    assert _check(xs)["n_flagged"] == 0


def test_a_bare_symmetric_ring_delocalises_the_error_and_is_not_flagged():
    """An honest limit of the method, pinned so it is not mistaken for a
    bug. In a bare regular hexagon the mislabelled site and the atom
    opposite it are pseudo-equivalent, so least squares splits the missing
    electron between them (0.0167 and 0.0166 instead of 0.026) and the
    ratio only reaches 0.59. The check stays silent rather than guessing;
    one substituent anywhere on the ring is enough to localise it."""
    atoms = _ring((6.0, 6.0, 6.0), 0.024)
    atoms[0] = ("N1", "N", atoms[0][2], 0.026)
    xs = refined_model(atoms, mislabel={"N1": "C"})
    r = _check(xs)
    assert _ueq(xs, "N1") < 0.7 * _ueq(xs, "C2")     # the shift IS there
    assert _flag(r, "N1") is None                    # ... just not by enough
    assert r["n_flagged"] == 0, r["flags"]           # and no collateral flags


# --------------------------------------------------------------------- #
# (v) a partly occupied site carries no element information
# --------------------------------------------------------------------- #

def test_partial_occupancy_site_is_excluded():
    atoms = nitro_on_ring(occ_x=0.5)
    xs = refined_model(atoms, mislabel={"X1": "C"})
    r = _check(xs)
    assert _flag(r, "X1") is None
    assert any(s.startswith("X1:") for s in r["skipped"]["partial_occupancy"])
    # and it is not used as a reference for its own neighbours either
    full = refined_model(nitro_on_ring(), mislabel={"X1": "C"})
    assert _check(full)["n_atoms_checked"] >= r["n_atoms_checked"]


# --------------------------------------------------------------------- #
# (vi) an unrefined model
# --------------------------------------------------------------------- #

def test_unrefined_model_reports_not_applicable():
    """A model straight out of interpret_peaks: one shared u, no
    refinement on record. The ADPs cannot carry element information yet
    and the check must say so instead of inventing flags."""
    xs = _structure([(lb, el, xyz, 0.05)
                     for lb, el, xyz, _u, *_ in nitro_on_ring()])
    r = audit_light_atom_elements(xs, n_refinements=0, d_min=D_MIN)
    assert r["status"] == "not_applicable"
    assert "not been refined" in r["reason"] or "no refinement" in r["reason"]
    assert r["flags"] == [] and r["nitro_vs_carboxylate_candidates"] == []
    assert r["model_state"]["refined"] is False

    # even with a refinement on record, flat ADPs are not evidence
    flat = audit_light_atom_elements(xs, n_refinements=3, d_min=D_MIN)
    assert flat["status"] == "not_applicable"
    assert "same Ueq" in flat["reason"]

    # and validate_structure passes that through instead of alerting
    ses = _session(xs, n_refinements=0)
    res = ValidateStructure().run(ToolContext(store=_Store(), session=ses))
    lac = res.summary["light_atom_element_check"]
    assert lac["status"] == "not_applicable"
    assert not [a for a in res.summary["alerts"]
                if a["code"] in ("light_atom_element_check",
                                 "nitro_vs_carboxylate")]


def test_isotropic_but_refined_model_is_checked():
    """"refined" is anisotropic OR an isotropic refinement on record - the
    probe above is isotropic and the rule works on it."""
    xs = refined_model(nitro_on_ring(), mislabel={"X1": "C"})
    assert not any(sc.flags.use_u_aniso() for sc in xs.scatterers())
    r = audit_light_atom_elements(xs, n_refinements=1, d_min=D_MIN)
    assert r["status"] == "checked"
    assert r["model_state"]["n_anisotropic"] == 0
    # no refinement on record and isotropic -> withheld
    assert audit_light_atom_elements(
        xs, n_refinements=0, d_min=D_MIN)["status"] == "not_applicable"


# --------------------------------------------------------------------- #
# (vii) the metal-bonded check is untouched
# --------------------------------------------------------------------- #

def test_metal_complex_still_fires_the_metal_bonded_check():
    xs = _structure(zn_aqua_complex())
    res = _validate(xs)
    codes = {a["code"] for a in res.summary["alerts"]}
    assert "metal_bonded_light_atom" in codes, codes
    mba = res.summary["metal_bonded_audit"]
    assert any(s["label"] == "C9" for s in mba["suspect_elements"])
    # the metal itself and its lone donors are outside the new rule: a
    # metal is skipped, and a donor with one non-H neighbour has no median
    lac = res.summary["light_atom_element_check"]
    assert lac["skipped"]["metal"] == 1
    assert _flag(lac, "C9") is None


# --------------------------------------------------------------------- #
# the rule itself: element-generic, no per-crystal constants
# --------------------------------------------------------------------- #

def test_one_step_in_z_is_generic_and_refuses_nonsense():
    assert one_step_in_z("C", +1) == "N"
    assert one_step_in_z("N", +1) == "O"
    assert one_step_in_z("O", +1) == "F"
    assert one_step_in_z("S", +1) == "Cl"
    assert one_step_in_z("Se", -1) == "As"
    assert one_step_in_z("O", -1) == "N"
    assert one_step_in_z("F", +1) is None       # Ne: not a bonding element
    assert one_step_in_z("B", -1) is None       # Be: a metal
    assert one_step_in_z("Zz", +1) is None


def test_bands_are_named_constants_outside_the_libration_contrast():
    # the physics: a one-step Z error moves an ordinary light-atom Ueq by
    # far more than the 12-17 % electron-count step it comes from, while
    # terminal-atom libration only reaches ~1.5x - the bands sit between
    assert 0.4 < _UEQ_RATIO_LOW < 0.7
    assert 1.3 < _UEQ_RATIO_HIGH < 2.0
    assert _REF_Z_FACTOR < 2.0                  # keeps S/Cl out of a C/N/O reference


def test_the_check_is_reported_with_its_bands_and_rule():
    xs = refined_model(nitro_on_ring(), mislabel={"X1": "C"})
    r = _check(xs)
    assert r["bands"]["too_light_below"] == _UEQ_RATIO_LOW
    assert r["bands"]["too_heavy_above"] == _UEQ_RATIO_HIGH
    assert r["bands"]["min_occupancy"] == 0.9
    assert r["bands"]["d_min_assumed"] == D_MIN
    assert "8 pi^2" in r["rule"]
    assert "never an element decision" in r["note"]


def test_heavier_neighbours_are_not_used_as_an_adp_yardstick():
    """A sulfonate-like S over three O is NOT a mislabel: heavier atoms
    simply move less. The mass-matching rule keeps that out of the flags
    without naming a single element."""
    x, y, z = 6.0, 6.0, 6.0
    d = 1.45
    atoms = [("S1", "S", (x, y, z), 0.018),
             ("O1", "O", (x + d, y, z), 0.036),
             ("O2", "O", (x - d * 0.5, y + d * 0.87, z), 0.037),
             ("O3", "O", (x - d * 0.5, y - d * 0.87, z), 0.036),
             ("C1", "C", (x, y, z + 1.77), 0.026)]
    r = _check(_structure(atoms))
    assert _flag(r, "S1") is None, _flag(r, "S1")
    assert r["skipped"]["no_mass_matched_reference"] >= 1


def test_the_tool_description_tells_the_agent_about_the_new_keys():
    d = ValidateStructure.description
    for phrase in ("light_atom_element_check", "too_light_label",
                   "too_heavy_label", "nitro_vs_carboxylate_candidates"):
        assert phrase in d, phrase
