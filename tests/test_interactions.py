"""Interaction engine (R2.3): synthetic fixtures with analytic answers.

Every structure here is built in code from cartesian coordinates whose
geometry is known exactly, so each assertion is a closed-form value rather
than a regression snapshot. No external data, no fixture-specific criteria.
"""
from __future__ import annotations

import math
import time

import numpy as np
import pytest
from cctbx import crystal, sgtbx, xray

from crystalpilot.chem.interactions import find_interactions

#: the plan's exact wording for a hydrogen bond measured without hydrogen
NO_H = "no_H_D···A_only"


# --------------------------------------------------------------------------
# fixture builders
# --------------------------------------------------------------------------

def _structure(atoms, cell=(30, 30, 30, 90, 90, 90), sg="P 1"):
    """atoms: (label, element, cartesian xyz)."""
    cs = crystal.symmetry(unit_cell=cell, space_group_symbol=sg)
    xs = xray.structure(crystal_symmetry=cs)
    uc = cs.unit_cell()
    for label, el, cart in atoms:
        xs.add_scatterer(xray.scatterer(
            label=label, site=uc.fractionalize(tuple(cart)),
            scattering_type=el, u=0.03))
    xs.scattering_type_registry(table="it1992")
    return xs


def _hexagon(centre, r=1.39, rot_deg=0.0, tilt_deg=0.0, tilt_axis=(1, 0, 0)):
    """Regular hexagon (side == circumradius == r) in the xy-plane, rotated
    in its own plane by `rot_deg` and then tilted by `tilt_deg`."""
    pts = [np.array([r * math.cos(math.radians(60 * k + rot_deg)),
                     r * math.sin(math.radians(60 * k + rot_deg)), 0.0])
           for k in range(6)]
    if tilt_deg:
        ax = np.array(tilt_axis, dtype=float)
        ax /= np.linalg.norm(ax)
        t = math.radians(tilt_deg)
        kmat = np.array([[0, -ax[2], ax[1]], [ax[2], 0, -ax[0]],
                         [-ax[1], ax[0], 0]], dtype=float)
        rot = np.eye(3) + math.sin(t) * kmat + (1 - math.cos(t)) * (kmat @ kmat)
        pts = [rot @ p for p in pts]
    return [np.array(centre, dtype=float) + p for p in pts]


def _stacked_rings(**kw):
    """Ring A in the xy-plane; ring B translated 3.5 A along A's normal and
    1.5 A in plane, so d_cc = sqrt(3.5^2 + 1.5^2) = 3.807886..."""
    a = _hexagon((10.0, 10.0, 10.0))
    b = _hexagon((11.5, 10.0, 13.5), **kw)
    atoms = [(f"C{i + 1}", "C", p) for i, p in enumerate(a)]
    atoms += [(f"C{i + 7}", "C", p) for i, p in enumerate(b)]
    return _structure(atoms)


def _h_offset(d_da, d_dh, angle_dha_deg):
    """D->H vector placing H so that D...A = d_da (A along +x from D),
    D-H = d_dh and the angle at H is exactly `angle_dha_deg`."""
    at_a = math.asin(d_dh * math.sin(math.radians(angle_dha_deg)) / d_da)
    at_d = math.pi - math.radians(angle_dha_deg) - at_a
    return np.array([d_dh * math.cos(at_d), d_dh * math.sin(at_d), 0.0])


def _one(rows, kind=None):
    sel = [r for r in rows if kind is None or r["kind"] == kind]
    assert len(sel) == 1, sel
    return sel[0]


# --------------------------------------------------------------------------
# pi-pi geometry
# --------------------------------------------------------------------------

def test_pipi_parallel_offset_stack_is_analytic():
    """d_cc, alpha, both perpendicular distances and both slips, exact."""
    r = find_interactions(_stacked_rings(), kinds=["pipi"])
    assert r["counts"]["rows"]["pipi"] == 1
    assert r["counts"]["unique"]["pipi"] == 1
    row = _one(r["rows"])
    assert round(row["d_cc"], 3) == 3.808           # sqrt(3.5^2 + 1.5^2)
    assert round(row["alpha"], 3) == 0.0
    assert round(row["d_perp_ab"], 3) == 3.500
    assert round(row["d_perp_ba"], 3) == 3.500
    assert round(row["slip_ab"], 3) == 1.500
    assert round(row["slip_ba"], 3) == 1.500
    assert row["passes"] is True
    assert row["boundary"] is False
    # both rings were found and judged aromatic by peak_chemistry's test
    assert [g["aromatic"] for g in r["rings"]] == [True, True]


def test_pipi_alpha_is_the_normal_angle_not_an_atom_pairing():
    """Spinning ring B 35 degrees about its OWN normal changes every atom
    pairing and no plane: alpha must stay 0."""
    r = find_interactions(_stacked_rings(rot_deg=35.0), kinds=["pipi"])
    row = _one(r["rows"])
    assert round(row["alpha"], 3) == 0.0
    assert round(row["d_cc"], 3) == 3.808
    assert round(row["slip_ab"], 3) == 1.500


def test_pipi_tilted_rings_report_both_perpendicular_distances():
    """Tilting B by 25 degrees about the slip direction: alpha = 25 and the
    two centroid-to-plane distances differ (3.5 vs 3.5*cos25)."""
    r = find_interactions(_stacked_rings(tilt_deg=25.0, tilt_axis=(1, 0, 0)),
                          kinds=["pipi"])
    row = _one(r["rows"])
    assert round(row["alpha"], 3) == 25.0
    assert round(row["d_cc"], 3) == 3.808
    assert round(row["d_perp_ab"], 3) == 3.500
    assert round(row["d_perp_ba"], 3) == round(3.5 * math.cos(
        math.radians(25.0)), 3) == 3.172
    assert row["d_perp_ab"] != row["d_perp_ba"]
    assert round(row["slip_ab"], 3) == 1.500
    assert round(row["slip_ba"], 3) == round(
        math.sqrt(14.5 - (3.5 * math.cos(math.radians(25.0))) ** 2), 3)
    # the criteria block echoes the thresholds and where they come from
    crit = r["criteria"]["pipi"]
    assert crit["d_cc_max_A"] == 4.0 and crit["alpha_max_deg"] == 30.0
    assert crit["slip_max_A"] == 3.0 and "Olex2" in crit["source"]


# --------------------------------------------------------------------------
# hydrogen bonds
# --------------------------------------------------------------------------

def _oho(d_da=2.75, angle=165.0, with_h=True):
    d = np.array([10.0, 10.0, 10.0])
    a = d + np.array([d_da, 0.0, 0.0])
    atoms = [("O1", "O", d)]
    if with_h:
        atoms.append(("H1", "H", d + _h_offset(d_da, 0.98, angle)))
    atoms.append(("O2", "O", a))
    return _structure(atoms)


def test_hbond_distance_and_angle_are_reported_exactly():
    r = find_interactions(_oho(), kinds=["hbond"], h_source="refined")
    row = _one(r["rows"])
    assert round(row["d_DA"], 2) == 2.75
    assert round(row["angle"], 2) == 165.00
    assert row["passes"] is True
    assert (row["d"], row["h"], row["a"]) == ("O1", "H1", "O2")
    assert row["status"] is None
    assert r["h_source"] == "refined"
    # the canonical table carries the same interaction once
    assert r["counts"]["unique"]["hbond"] == 1
    # and the viewer gets a drawable edge because both ends are displayed
    assert r["edges"]["hbond"] == [[row["i"], row["j"], row["dist"]]]


def test_hbond_presets_disagree_only_where_they_should():
    """Olex2 htab and Steiner both accept this one; the echoed criteria say
    which numbers were used."""
    xs = _oho()
    olex2 = find_interactions(xs, kinds=["hbond"], h_source="refined")
    steiner = find_interactions(xs, kinds=["hbond"], criteria="steiner",
                                h_source="refined")
    assert _one(olex2["rows"])["passes"] is True
    row = _one(steiner["rows"])
    assert row["passes"] is True
    assert round(row["d_HA"], 2) == 1.79            # law of cosines
    assert olex2["criteria"]["hbond"]["d_DA_max_A"] == 2.9
    assert olex2["criteria"]["hbond"]["angle_DHA_min_deg"] == 150.0
    assert steiner["criteria"]["hbond"]["angle_DHA_min_deg"] == 110.0
    assert steiner["criteria"]["hbond"]["set"] == "steiner"
    # "platon" is an alias, not a third set of numbers
    platon = find_interactions(xs, kinds=["hbond"], criteria="platon",
                               h_source="refined")
    assert platon["criteria"]["hbond"] == steiner["criteria"]["hbond"]


def test_hbond_without_hydrogen_degrades_to_D_A_only():
    r = find_interactions(_oho(with_h=False), kinds=["hbond"])
    row = _one(r["rows"])
    assert row["status"] == NO_H
    assert row["angle"] is None
    assert row["h"] is None and row["d_HA"] is None
    assert round(row["d_DA"], 2) == 2.75
    # h_source is inferred, never guessed, and says no HTAB may be emitted
    assert r["h_source"] == "absent"
    assert "HTAB" in r["h_source_note"]


def test_h_source_is_required_and_never_guessed():
    """With H present but no AFIX information the answer is 'unknown' plus
    the riding-H bias sentence - not a guess between riding and refined."""
    r = find_interactions(_oho(), kinds=["hbond"])
    assert r["h_source"] == "unknown"
    assert "riding vs refined" in r["h_source_note"]
    assert "0.95-0.98" in r["h_source_note"]
    riding = find_interactions(_oho(), kinds=["hbond"], h_source="riding")
    assert riding["h_source"] == "riding"
    assert "systematically" in riding["h_source_note"]
    with pytest.raises(ValueError):
        find_interactions(_oho(), kinds=["hbond"], h_source="idealised")


def test_hbond_across_a_symmetry_image_carries_the_operator():
    """P2_1/c with the acceptor only reachable through -x,y+1/2,-z+1/2."""
    cell = (9.0, 11.0, 13.0, 90.0, 95.0, 90.0)
    cs = crystal.symmetry(unit_cell=cell, space_group_symbol="P 21/c")
    uc = cs.unit_cell()
    op = sgtbx.rt_mx("-x,y+1/2,-z+1/2")
    donor = np.array([2.0, 1.0, 3.0])
    target = donor + np.array([2.75, 0.0, 0.0])
    xs = xray.structure(crystal_symmetry=cs)
    for lbl, el, frac in [
            ("O1", "O", uc.fractionalize(tuple(donor))),
            ("H1", "H", uc.fractionalize(
                tuple(donor + _h_offset(2.75, 0.98, 165.0)))),
            ("O2", "O", tuple(op.inverse() * uc.fractionalize(tuple(target))))]:
        xs.add_scatterer(xray.scatterer(label=lbl, site=frac,
                                        scattering_type=el, u=0.03))
    xs.scattering_type_registry(table="it1992")

    r = find_interactions(xs, kinds=["hbond"], h_source="refined")
    assert r["counts"]["unique"]["hbond"] == 1
    scs = list(xs.scatterers())
    # the row hanging off the asymmetric-unit donor names the operator
    row = _one([x for x in r["rows"] if x["sym_i"] == "x,y,z"])
    assert row["sym"] == "-x,y+1/2,-z+1/2"
    assert row["op"] == row["sym"]
    ref = uc.distance(scs[row["i_seq"]].site,
                      sgtbx.rt_mx(row["sym"]) * scs[row["j_seq"]].site)
    assert abs(row["dist"] - ref) < 1e-6
    assert abs(row["d_DA"] - ref) < 1e-6
    assert row["boundary"] is True              # the partner is not displayed
    assert r["counts"]["n_boundary"] == len(r["rows"])
    # every row, whichever image it hangs off, satisfies the same identity
    for x in r["rows"]:
        d = uc.distance(scs[x["i_seq"]].site,
                        sgtbx.rt_mx(x["op"]) * scs[x["j_seq"]].site)
        assert abs(x["dist"] - d) < 1e-6


# --------------------------------------------------------------------------
# the boundary rule
# --------------------------------------------------------------------------

def _stacked_on_inversion():
    """P-1 benzene whose centroid sits 1.8 A above the inversion centre, so
    the ring and its own image stack face to face at exactly 3.6 A."""
    cs = crystal.symmetry(unit_cell=(14, 14, 14, 90, 90, 90),
                          space_group_symbol="P -1")
    uc = cs.unit_cell()
    xs = xray.structure(crystal_symmetry=cs)
    for i, p in enumerate(_hexagon((0.0, 0.0, 1.8))):
        xs.add_scatterer(xray.scatterer(
            label=f"C{i + 1}", site=uc.fractionalize(tuple(p)),
            scattering_type="C", u=0.03))
    xs.scattering_type_registry(table="it1992")
    return xs


def test_halo_recovers_the_partner_the_bare_asu_would_lose():
    """count(asu) <= count(asu+halo) == count(cell), and the row whose
    partner is not instantiated is flagged boundary."""
    xs = _stacked_on_inversion()
    bare = find_interactions(xs, kinds=["pipi"], halo_A=0.0)
    haloed = find_interactions(xs, kinds=["pipi"], halo_A=8.0)
    cell = find_interactions(
        xs, kinds=["pipi"], halo_A=8.0,
        range_atoms=[(i, "x,y,z") for i in range(6)]
        + [(i, "-x,-y,-z") for i in range(6)])

    n_bare = bare["counts"]["rows"]["pipi"]
    n_halo = haloed["counts"]["rows"]["pipi"]
    n_cell = cell["counts"]["rows"]["pipi"]
    assert n_bare == 0                      # searching the ASU alone loses it
    assert n_bare <= n_halo == n_cell == 1

    # the canonical table is a property of the crystal, not of the view
    assert (bare["counts"]["unique"]["pipi"]
            == haloed["counts"]["unique"]["pipi"]
            == cell["counts"]["unique"]["pipi"] == 1)

    row = _one(haloed["rows"])
    assert row["boundary"] is True and row["sym"] == "-x,-y,-z"
    assert haloed["counts"]["n_boundary"] == 1
    assert round(row["d_cc"], 3) == 3.600
    assert round(row["alpha"], 3) == 0.0 and round(row["slip_ab"], 3) == 0.0
    # xyz lets the viewer draw the partner it did not materialize
    assert len(row["xyz"]) == 3
    # ...and with the whole cell displayed the same contact is internal
    assert _one(cell["rows"])["boundary"] is False
    assert cell["counts"]["n_boundary"] == 0

    # every row whose partner is not instantiated is flagged
    for res in (bare, haloed, cell):
        for r in res["rows"]:
            partner_shown = res["rings"][r["ring_b_inst"]]["in_range"]
            assert r["boundary"] is not partner_shown


def test_range_block_describes_the_halo_it_used():
    r = find_interactions(_stacked_on_inversion(), kinds=["pipi"],
                          halo_A=8.0)
    assert r["range"]["source"] == "asu"
    assert r["range"]["n_range"] == 6
    assert r["range"]["n_halo"] > 0
    assert r["range"]["halo_A"] == 8.0
    assert "at least one end in range" in r["range"]["boundary_rule"]
    assert r["range"]["work_truncated"] is False
    # the halo it needed is reported, not assumed
    assert r["range"]["halo_advised_A"] <= 8.0
    assert r["range"]["halo_sufficient"] is True
    assert find_interactions(_stacked_on_inversion(), kinds=["pipi"],
                             halo_A=1.0)["range"]["halo_sufficient"] is False
    assert len(r["range"]["frac_lo"]) == 3 and len(r["range"]["frac_hi"]) == 3
    # instances are addressable: edges/rows index into this list
    assert r["counts"]["n_instances"] == len(r["instances"])
    assert all(i["in_range"] for i in r["instances"][:6])


# --------------------------------------------------------------------------
# PART awareness (D19)
# --------------------------------------------------------------------------

def _disorder_pair():
    """One O-H donor and two acceptor alternatives 1.0 A apart, both at
    exactly 2.75 A from the donor and at the same D-H...A angle."""
    phi = math.asin(0.5 / 2.75)             # half-separation 0.5 A
    d = np.array([10.0, 10.0, 10.0])
    return _structure([
        ("O1", "O", d),
        ("H1", "H", d + np.array([0.98, 0.0, 0.0])),
        ("O3", "O", d + 2.75 * np.array([math.cos(phi), math.sin(phi), 0.0])),
        ("O2", "O", d + 2.75 * np.array([math.cos(phi), -math.sin(phi), 0.0])),
    ])


def test_no_hydrogen_bond_is_drawn_between_part_1_and_part_2():
    xs = _disorder_pair()
    scs = list(xs.scatterers())
    sep = xs.unit_cell().distance(scs[2].site, scs[3].site)
    assert abs(sep - 1.0) < 1e-6            # the two alternatives, 1.0 A apart

    both = find_interactions(xs, kinds=["hbond"], h_source="riding")
    assert {r["a"] for r in both["rows"]} == {"O2", "O3"}

    parted = find_interactions(xs, kinds=["hbond"], h_source="riding",
                               parts={"O1": 1, "H1": 1, "O3": 1, "O2": 2})
    row = _one(parted["rows"])
    assert row["a"] == "O3"                 # never the PART 2 alternative
    assert parted["counts"]["unique"]["hbond"] == 1
    # a negative SHELX PART is the same disorder component (abs)
    signed = find_interactions(xs, kinds=["hbond"], h_source="riding",
                               parts={"O1": 1, "H1": 1, "O3": 1, "O2": -2})
    assert [r["a"] for r in signed["rows"]] == ["O3"]
    # a per-scatterer list is accepted too
    listed = find_interactions(xs, kinds=["hbond"], h_source="riding",
                               parts=[1, 1, 1, 2])
    assert [r["a"] for r in listed["rows"]] == ["O3"]


# --------------------------------------------------------------------------
# C-H...X, C-H...pi, halogen bonds, anion-pi
# --------------------------------------------------------------------------

def test_ch_o_contact_is_found_and_its_geometry_reported():
    """H...O 2.45 A (inside r_vdW(H)+r_vdW(O) = 2.65) at 140 degrees."""
    c = np.array([10.0, 10.0, 10.0])
    h = c + np.array([1.08, 0.0, 0.0])
    o = h + 2.45 * np.array([math.cos(math.radians(40.0)),
                             math.sin(math.radians(40.0)), 0.0])
    xs = _structure([("C1", "C", c), ("H1", "H", h), ("O1", "O", o)])
    r = find_interactions(xs, kinds=["chx", "hbond"], criteria="steiner",
                          h_source="riding")
    assert r["counts"]["rows"]["hbond"] == 0        # C is not a polar donor
    row = _one(r["rows"], "chx")
    assert round(row["d_HA"], 2) == 2.45
    assert round(row["angle"], 2) == 140.00
    assert row["passes"] is True
    assert (row["d"], row["h"], row["a"]) == ("C1", "H1", "O1")
    assert round(row["d_DA"], 2) == round(
        float(np.linalg.norm(o - c)), 2)            # the C...O distance too
    crit = r["criteria"]["chx"]
    assert crit["angle_CHA_min_deg"] == 120.0
    assert crit["d_HA_max_rule"] == "r_vdW(H) + r_vdW(A)"
    assert "van_der_waals_radii" in crit["vdw_table"]


def test_ch_pi_contact_over_the_ring_centroid():
    atoms = [(f"C{i + 1}", "C", p)
             for i, p in enumerate(_hexagon((10.0, 10.0, 10.0)))]
    atoms += [("C9", "C", np.array([10.0, 10.0, 14.08])),
              ("H9", "H", np.array([10.0, 10.0, 13.0]))]
    r = find_interactions(_structure(atoms), kinds=["chpi"], h_source="riding")
    row = _one(r["rows"])
    assert round(row["d_HCg"], 3) == 3.000
    assert round(row["angle"], 2) == 180.00
    assert round(row["offset"], 3) == 0.0           # right over the centroid
    assert row["passes"] is True
    assert r["criteria"]["chpi"]["d_HCg_max_A"] == 3.2
    assert "Nishio" in r["criteria"]["chpi"]["source"]


def test_ring_substituent_hydrogens_are_not_ch_pi_to_their_own_ring():
    """Aromatic H sit 2.47 A from their own centroid - inside the distance
    window - so without the 1-2 exclusion every benzene reports six."""
    atoms = [(f"C{i + 1}", "C", p)
             for i, p in enumerate(_hexagon((10.0, 10.0, 10.0)))]
    for i, p in enumerate(_hexagon((10.0, 10.0, 10.0), r=1.39 + 1.08)):
        atoms.append((f"H{i + 1}", "H", p))
    r = find_interactions(_structure(atoms), kinds=["chpi"], h_source="riding")
    assert r["counts"]["rows"]["chpi"] == 0


def test_halogen_bond_needs_a_carrier_and_a_linear_sigma_hole():
    c = np.array([10.0, 10.0, 10.0])
    cl = c + np.array([1.74, 0.0, 0.0])
    o = cl + 3.1 * np.array([math.cos(math.radians(10.0)),
                             math.sin(math.radians(10.0)), 0.0])
    r = find_interactions(_structure([("C1", "C", c), ("CL1", "Cl", cl),
                                      ("O1", "O", o)]),
                          kinds=["halogen", "hbond"])
    row = _one(r["rows"], "halogen")
    assert round(row["d_XA"], 2) == 3.10            # < 1.75 + 1.45 = 3.20
    assert round(row["angle"], 2) == 170.00
    assert row["passes"] is True
    assert (row["c"], row["x"], row["a"]) == ("C1", "CL1", "O1")
    # 3.1 A is outside the htab D...A window, so it is not also a hydrogen bond
    assert r["counts"]["rows"]["hbond"] == 0
    assert r["criteria"]["halogen"]["angle_CXY_min_deg"] == 155.0
    assert "IUPAC" in r["criteria"]["halogen"]["source"]

    # a bare halide has no sigma hole: no carrier, no halogen bond
    bare = find_interactions(_structure([("CL1", "Cl", cl), ("O1", "O", o)]),
                             kinds=["halogen"])
    assert bare["counts"]["rows"]["halogen"] == 0


def test_anion_pi_says_how_the_anion_was_identified():
    atoms = [(f"C{i + 1}", "C", p)
             for i, p in enumerate(_hexagon((10.0, 10.0, 10.0)))]
    atoms.append(("CL1", "Cl", np.array([10.0, 10.0, 13.5])))
    r = find_interactions(_structure(atoms), kinds=["anion_pi"])
    crit = r["criteria"]["anion_pi"]
    assert crit["n_anion_fragments"] == 1
    assert "_FRAGMENT_SIGNATURES" in crit["anion_identification"]
    assert crit["strength"].startswith("weak reading")
    row = _one(r["rows"])
    assert row["anion_name"] == "Cl-"
    assert round(row["d_cc"], 3) == 3.500
    assert round(row["offset"], 3) == 0.0
    assert row["strength"] == "weak_reading"
    # a neutral fragment is never called an anion, and the signatures whose
    # names carry no charge are named rather than guessed at
    neutral = find_interactions(
        _structure([(f"C{i + 1}", "C", p)
                    for i, p in enumerate(_hexagon((10.0, 10.0, 10.0)))]
                   + [("O1", "O", np.array([10.0, 10.0, 13.5]))]),
        kinds=["anion_pi"])
    assert neutral["counts"]["rows"]["anion_pi"] == 0
    assert "formate" in neutral["criteria"]["anion_pi"]["anion_identification"]


# --------------------------------------------------------------------------
# caps, kinds, criteria echo
# --------------------------------------------------------------------------

def _stacked_column(n=4):
    """P1 benzene stacked along c at 3.6 A, materialized n cells deep."""
    cs = crystal.symmetry(unit_cell=(12, 12, 3.6, 90, 90, 90),
                          space_group_symbol="P 1")
    uc = cs.unit_cell()
    xs = xray.structure(crystal_symmetry=cs)
    for i, p in enumerate(_hexagon((6.0, 6.0, 0.0))):
        xs.add_scatterer(xray.scatterer(
            label=f"C{i + 1}", site=uc.fractionalize(tuple(p)),
            scattering_type="C", u=0.03))
    xs.scattering_type_registry(table="it1992")
    rng = [(i, sgtbx.rt_mx(sgtbx.rot_mx(), sgtbx.tr_vec([0, 0, 12 * t], 12)))
           for t in range(n) for i in range(6)]
    return xs, rng


def test_cap_keeps_the_closest_rows_and_says_what_it_cut():
    xs, rng = _stacked_column(n=6)
    full = find_interactions(xs, kinds=["pipi"], range_atoms=rng)
    capped = find_interactions(xs, kinds=["pipi"], range_atoms=rng,
                               caps={"pipi": 2})
    assert full["counts"]["rows"]["pipi"] > 2
    assert capped["counts"]["rows"]["pipi"] == 2
    assert capped["truncated"]["pipi"] == {
        "cap": 2, "found": full["counts"]["rows"]["pipi"]}
    assert full["truncated"] == {}
    assert all(round(r["d_cc"], 3) == 3.600 for r in capped["rows"])


def test_kind_selection_and_output_shape():
    r = find_interactions(_oho(), h_source="refined")
    for key in ("criteria", "h_source", "h_source_note", "range", "rings",
                "unique", "edges", "rows", "counts", "truncated",
                "instances"):
        assert key in r, key
    assert set(r["criteria"]) == set(r["unique"]) == set(r["edges"]) == {
        "hbond", "pipi", "chpi", "chx", "halogen", "anion_pi"}
    for kind, block in r["criteria"].items():
        assert block.get("source"), kind      # every threshold cites a source
    assert "n_boundary" in r["counts"]
    only = find_interactions(_oho(), kinds=["hbond"], h_source="refined")
    assert set(only["criteria"]) == {"hbond"}
    with pytest.raises(ValueError):
        find_interactions(_oho(), kinds=["hbond", "vdw"])
    with pytest.raises(ValueError):
        find_interactions(_oho(), criteria="mercury")


# --------------------------------------------------------------------------
# performance
# --------------------------------------------------------------------------

def _phenol_cell():
    """Phenol-like molecule (13 atoms) in a 9 x 9 x 3.7 A P1 cell, so the
    rings stack along c and the pi-pi / C-H...X paths both carry load."""
    ring = _hexagon((4.5, 4.5, 1.85))
    atoms = [(f"C{i + 1}", "C", p) for i, p in enumerate(ring)]
    centre = np.array([4.5, 4.5, 1.85])
    u = (ring[0] - centre) / np.linalg.norm(ring[0] - centre)
    o = ring[0] + 1.36 * u
    rot = np.array([u[0] * math.cos(1.9) - u[1] * math.sin(1.9),
                    u[0] * math.sin(1.9) + u[1] * math.cos(1.9), 0.0])
    atoms += [("O1", "O", o), ("H1", "H", o + 0.84 * rot)]
    for i in range(1, 6):
        v = (ring[i] - centre) / np.linalg.norm(ring[i] - centre)
        atoms.append((f"H{i + 1}", "H", ring[i] + 1.08 * v))
    return _structure(atoms, cell=(9.0, 9.0, 3.7, 90, 90, 90))


def test_twenty_thousand_instances_stay_interactive():
    """22 464 displayed instances + an 8 A halo, all six kinds, one call."""
    xs = _phenol_cell()
    n_atoms = xs.scatterers().size()
    rng = [(i, sgtbx.rt_mx(sgtbx.rot_mx(),
                           sgtbx.tr_vec([12 * ta, 12 * tb, 12 * tc], 12)))
           for ta in range(12) for tb in range(12) for tc in range(12)
           for i in range(n_atoms)]
    assert len(rng) >= 20000
    t0 = time.perf_counter()
    r = find_interactions(xs, range_atoms=rng, halo_A=8.0, h_source="riding")
    elapsed = time.perf_counter() - t0
    assert r["range"]["n_range"] == len(rng)
    assert r["range"]["n_halo"] > 0
    assert r["counts"]["rows"]["pipi"] > 0
    assert not r["range"]["work_truncated"]
    assert elapsed < 3.0, f"{elapsed:.2f} s for {len(rng)} instances"


class TestIntraInter:
    """`intra`: same bonded fragment on the identity operator. A 1-4
    O-H...O inside one chain is intramolecular; the same donor reaching the
    acceptor of the NEXT cell (a = 5.6 A puts O2' 2.8 A behind O1) is a
    different molecule even though it is the same fragment."""

    ATOMS = [
        ("O1", "O", (1.00, 5.00, 5.00)),
        ("H1", "H", (1.96, 5.00, 5.00)),
        ("C1", "C", (1.70, 6.25, 5.00)),
        ("C2", "C", (3.10, 6.25, 5.00)),
        ("O2", "O", (3.80, 5.00, 5.00)),
    ]

    def test_flag_on_both_rows(self):
        xs = _structure(self.ATOMS, cell=(5.6, 10, 10, 90, 90, 90))
        # olex2 preset: rows are emitted on D...A alone, so the image row
        # (D...A 2.8, angle ~0) is present and fails; steiner would not even
        # list it (H...A 3.76 > sum of vdW radii)
        res = find_interactions(xs, h_source="refined", kinds=["hbond"])
        rows = res["unique"]["hbond"]
        by_op = {r["op"].replace(" ", ""): r for r in rows}
        assert "x,y,z" in by_op, sorted(by_op)
        own = by_op["x,y,z"]
        assert own["intra"] is True and own["passes"] is True
        assert own["d_DA"] == pytest.approx(2.80, abs=1e-3)
        others = [r for k, r in by_op.items() if k != "x,y,z"]
        assert others and all(r["intra"] is False for r in others)
        assert all(r["passes"] is False for r in others)
        assert res["counts"]["intra_unique"]["hbond"] == 1
        # display rows carry it too
        assert any(r["intra"] for r in res["rows"])

    def test_two_separate_molecules_are_never_intra(self):
        atoms = [("O1", "O", (2.0, 5.0, 5.0)), ("H1", "H", (2.96, 5.0, 5.0)),
                 ("O2", "O", (4.8, 5.0, 5.0))]
        xs = _structure(atoms, cell=(10, 10, 10, 90, 90, 90))
        res = find_interactions(xs, h_source="refined", kinds=["hbond"])
        rows = res["unique"]["hbond"]
        assert len(rows) == 1 and rows[0]["intra"] is False


class TestRingsThatCloseThroughSymmetry:
    """The rings `find_rings` cannot represent are named by the census
    (`criteria.pipi.rings_closing_through_symmetry`) AND, since round-3 R5,
    BUILT from the closing operator's powers so they take part in the pi-pi
    / C-H...pi / anion-pi tables like any other ring.

    A benzene sitting on an inversion centre is three carbons in the
    asymmetric unit whose cycle closes on `-x,-y,-z`; find_rings drops it by
    construction, and before R5 every pi-pi and C-H...pi row through that
    ring was absent from the tables (the Zn2-dhtp benchmark lost its whole
    pi-pi table this way).  The walk is pure topology plus space-group
    operators: no element, no fixture."""

    @staticmethod
    def _half_hexagon(sg="P -1", cell=(30, 30, 30, 90, 90, 90)):
        """Half a regular hexagon centred on the origin: the other half is
        the inversion image, so the ring closes on -x,-y,-z."""
        pts = _hexagon((0.0, 0.0, 0.0))
        return _structure([(f"C{i + 1}", "C", p)
                           for i, p in enumerate(pts[:3])], cell=cell, sg=sg)

    def test_benzene_on_an_inversion_centre_is_named(self):
        r = find_interactions(self._half_hexagon(), kinds=["pipi", "chpi"])
        crit = r["criteria"]["pipi"]
        through = crit["rings_closing_through_symmetry"]
        assert len(through) == 1, through
        assert through[0]["size"] == 6 and through[0]["asu_atoms"] == 3
        assert through[0]["op_order"] == 2
        assert through[0]["op"].replace(" ", "") == "-x,-y,-z"
        assert set(through[0]["key"].split(",")) == {"C1", "C2", "C3"}
        # round-3 R5: the ring is BUILT from the operator's powers - six
        # atoms, aromatic, with its provenance on the row and in the census
        assert len(r["rings"]) == 1
        ring = r["rings"][0]
        assert ring["aromatic"] is True and len(ring["atoms"]) == 6
        assert ring["through_symmetry"]["order"] == 2
        assert ring["through_symmetry"]["asu_atoms"] == 3
        assert ring["through_symmetry"]["op"].replace(" ", "") == "-x,-y,-z"
        assert abs(ring["radius"] - 1.39) < 0.01
        assert through[0]["built"] is True and through[0]["aromatic"] is True
        assert r["counts"]["unique"]["pipi"] == 0   # a lone ring: no partner
        assert "THIS STRUCTURE HAS 1 of them" in crit["ring_note"]
        assert "take part in every pi-pi" in crit["ring_note"]
        assert crit["ring_note"] == r["criteria"]["chpi"]["ring_note"]

    def test_a_symmetry_closed_ring_stacks_with_its_lattice_image(self):
        """The whole point: the built ring enters the pi-pi table. A benzene
        on the inversion centre of a 3.6 A-short cell stacks face to face
        with its own translation image (d_cc 3.6 A, alpha 0, no slip) - a
        row that was silently missing before R5."""
        r = find_interactions(self._half_hexagon(cell=(30, 30, 3.6, 90, 90, 90)),
                              kinds=["pipi"])
        rows = r["unique"]["pipi"]
        assert rows, r["criteria"]["pipi"]["ring_note"]
        row = min(rows, key=lambda x: x["d_cc"])
        assert abs(row["d_cc"] - 3.6) < 0.01
        assert row["alpha"] < 0.5
        assert abs(row["d_perp_ab"] - 3.6) < 0.01
        assert set(row["ring_a"].split(",")) == {"C1", "C2", "C3"}
        assert set(row["ring_b"].split(",")) == {"C1", "C2", "C3"}

    def test_a_ring_on_a_threefold_axis_is_built_from_two_atoms(self):
        """Order-3 closure: a benzene on a 3-fold axis has two carbons in
        the asymmetric unit (C1 and C2 = one C-C edge); the closing
        operator is the rotation, the ring is 2 x 3 = 6 atoms."""
        import math

        cell = (30, 30, 30, 90, 90, 120)
        # hexagon centred on the origin in the ab plane; with gamma = 120
        # the 3-fold axis along c maps the hexagon onto itself
        pts = _hexagon((0.0, 0.0, 0.0))
        xs = _structure([("C1", "C", pts[0]), ("C2", "C", pts[1])],
                        cell=cell, sg="P 3")
        r = find_interactions(xs, kinds=["pipi"])
        through = r["criteria"]["pipi"]["rings_closing_through_symmetry"]
        assert len(through) == 1 and through[0]["op_order"] == 3
        assert through[0]["asu_atoms"] == 2 and through[0]["size"] == 6
        assert len(r["rings"]) == 1
        ring = r["rings"][0]
        assert len(ring["atoms"]) == 6 and ring["aromatic"] is True
        assert ring["through_symmetry"]["order"] == 3
        assert math.isclose(ring["radius"], 1.39, abs_tol=0.02)

    def test_a_whole_ring_in_the_cell_reports_none(self):
        """Control: the same hexagon written out in full in P1 is an
        ordinary ring, and nothing is claimed to be missing."""
        xs = _structure([(f"C{i + 1}", "C", p)
                         for i, p in enumerate(_hexagon((10.0, 10.0, 10.0)))])
        r = find_interactions(xs, kinds=["pipi"])
        crit = r["criteria"]["pipi"]
        assert crit["rings_closing_through_symmetry"] == []
        assert "No ring closes through a symmetry element" in crit["ring_note"]
        assert len(r["rings"]) == 1 and r["rings"][0]["aromatic"] is True
        assert "through_symmetry" not in r["rings"][0]

    def test_a_lattice_loop_is_not_counted_as_a_ring(self):
        """A 1-D chain closes on a pure TRANSLATION, which has no finite
        order: it is a lattice loop, not a ring, and must not be reported as
        a missing one - the distinction find_rings makes, carried over."""
        xs = _structure([("C1", "C", (0.0, 0.0, 0.0))],
                        cell=(1.5, 20, 20, 90, 90, 90), sg="P 1")
        crit = find_interactions(xs, kinds=["pipi"])["criteria"]["pipi"]
        assert crit["rings_closing_through_symmetry"] == []
