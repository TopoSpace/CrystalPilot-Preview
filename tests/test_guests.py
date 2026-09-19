"""`chem/guests.py` (round-2 R3.4): where a guest sits in the host's void
map - cage cavity, channel, inter-molecular cavity, interstitial.

Six synthetic crystals, all deterministic, all built from carbon and one
chloride so nothing here can be special-cased to a real structure:

  pcu_framework   a = 12 A, C chains every 1.5 A along x, y and z through
                  the origin: ONE 3-D bonded fragment, one 3-D void of
                  1428.9 A^3 whose inscribed sphere sits at the cell centre.
  pcu_with_slot   the same net plus one c-chain at (5.0, 3.0), which forms
                  a 5.0 A slot with the b-chain: the slot's midpoint is
                  2.5 A from two carbons - too far to bond, too tight for
                  the 1.2 A probe plus its shrink radius.
  carbon_shell    60 C on a Fibonacci sphere of radius 3.55 A (nearest
                  neighbours 1.42-1.52 A, so ONE 0-D fragment), a = 14 A.
  capsule         P-1, a = 16 A: the 30 C of one hemispherical bowl, its
                  inversion image completing a closed capsule. The two
                  bowls are copies of ONE fragment (`copies` 2) and are
                  2.8 A apart at the seam - not bonded, and no probe path
                  between inside and outside.

Why the interstitial fixture is a slot and not "a Cl 1.3 A from a carbon":
for a Cl on carbon there is NO distance that is both inside carbon's van
der Waals radius (1.775 A) and outside the C-Cl bond cutoff (sum of
covalent radii + 0.45 = 2.20 A), so a guest jammed against a single atom
is a bonded part of the host, not an interstitial guest. An interstitial
site is a POCKET too tight for the probe, which is what the slot is.
"""
from __future__ import annotations

import math

import pytest
from cctbx import crystal, xray

from crystalpilot.chem.guests import (CRITERIA_EN, CRITERIA_VERBATIM,
                                      DEFAULT_MIN_VOID_VOLUME_A3,
                                      DEFAULT_PROBE_A, SITES, host_void_map,
                                      locate_guests)


CELL = 12.0          # pcu fixtures
SPACING = 1.5        # C-C along a chain
SHELL_A = 14.0
SHELL_R = 3.55
CAPSULE_A = 16.0
CAPSULE_GAP = 1.4    # each bowl pushed this far off the equator


# --------------------------------------------------------------- fixtures --

def _structure(atoms, cell, sg="P 1"):
    """atoms: (label, element, cartesian xyz)."""
    cs = crystal.symmetry(unit_cell=cell, space_group_symbol=sg)
    xs = xray.structure(crystal_symmetry=cs)
    uc = cs.unit_cell()
    for label, el, cart in atoms:
        xs.add_scatterer(xray.scatterer(
            label=label, site=uc.fractionalize(cart), scattering_type=el,
            u=0.03))
    xs.scattering_type_registry(table="it1992")
    return xs


def _fibonacci_sphere(n, radius, centre=(0.0, 0.0, 0.0)):
    """n points spread evenly over a sphere (golden-angle spiral)."""
    ga = math.pi * (3.0 - math.sqrt(5.0))
    out = []
    for i in range(n):
        z = 1.0 - 2.0 * (i + 0.5) / n
        rho = math.sqrt(max(0.0, 1.0 - z * z))
        th = ga * i
        out.append((centre[0] + radius * rho * math.cos(th),
                    centre[1] + radius * rho * math.sin(th),
                    centre[2] + radius * z))
    return out


def _pcu_atoms(slot=False):
    atoms = [("C0", "C", (0.0, 0.0, 0.0))]
    k = 1
    for axis in range(3):
        for i in range(1, 8):
            p = [0.0, 0.0, 0.0]
            p[axis] = i * SPACING
            atoms.append((f"C{k}", "C", tuple(p)))
            k += 1
    if slot:
        for i in range(8):
            atoms.append((f"D{i + 1}", "C", (5.0, 3.0, i * SPACING)))
    return atoms


def _cubic(atoms, a):
    return _structure(atoms, (a, a, a, 90, 90, 90))


@pytest.fixture(scope="module")
def channel_guest():
    """Cl at the body centre of the pcu net: 8.485 A from the nearest C."""
    return locate_guests(_cubic(
        _pcu_atoms() + [("CL1", "Cl", (6.0, 6.0, 6.0))], CELL))


@pytest.fixture(scope="module")
def interstitial_guest():
    """Cl in the 5.0 A slot between the b-chain atom (0, 3, 0) and the
    added c-chain at (5, 3, z): 2.5 A from both."""
    return locate_guests(_cubic(
        _pcu_atoms(slot=True) + [("CL1", "Cl", (2.5, 3.0, 0.0))], CELL))


def _shell_model(centre):
    atoms = [(f"C{i + 1}", "C", p) for i, p in
             enumerate(_fibonacci_sphere(60, SHELL_R, centre))]
    return _cubic(atoms + [("CL1", "Cl", centre)], SHELL_A)


@pytest.fixture(scope="module")
def cage_guest():
    """Cl at the centre of the shell, the shell at the centre of the cell."""
    return locate_guests(_shell_model((SHELL_A / 2,) * 3))


@pytest.fixture(scope="module")
def cavity_guest():
    """Cl at the centre of the two-bowl capsule (on the inversion centre)."""
    bowl = [(x, y, z + CAPSULE_GAP)
            for (x, y, z) in _fibonacci_sphere(60, SHELL_R) if z >= 0]
    atoms = [(f"C{i + 1}", "C", p) for i, p in enumerate(bowl)]
    return locate_guests(_structure(
        atoms + [("CL1", "Cl", (0.0, 0.0, 0.0))],
        (CAPSULE_A, CAPSULE_A, CAPSULE_A, 90, 90, 90), sg="P -1"))


# ------------------------------------------------------------- 1. channel --

class TestChannel:
    def test_host_is_the_one_periodic_fragment(self, channel_guest):
        host = channel_guest["host"]
        assert host["n_atoms"] == 22
        assert [(f["key"], f["formula"], f["dimensionality"], f["role"])
                for f in host["fragments"]] == [("F1", "C22", 3, "main")]

    def test_guest_sits_in_a_three_dimensional_channel(self, channel_guest):
        (g,) = channel_guest["guests"]
        assert (g["formula"], g["copies"], g["identity"]) == ("Cl", 1, "Cl-")
        assert g["site"] == "channel"
        assert g["void_id"] == 1
        assert g["region"]["dimensionality"] == 3
        assert sorted(g["region"]["directions"]) == [[0, 0, 1], [0, 1, 0],
                                                     [1, 0, 0]]
        assert channel_guest["summary"] == {"cage_cavity": 0, "channel": 1,
                                            "cavity": 0, "interstitial": 0}

    def test_body_centre_is_the_inscribed_sphere_centre(self, channel_guest):
        """The Cl sits where the free sphere is largest, so the distance to
        the inscribed centre is under one grid step."""
        (g,) = channel_guest["guests"]
        assert g["d_to_inscribed_centre_A"] <= 2 * channel_guest["grid_step_A"]
        assert g["region"]["inscribed_radius_A"] > 6.0

    def test_contact_and_clearance_are_the_analytic_numbers(self,
                                                            channel_guest):
        """(6, 6, 6) is 8.485 A = sqrt(72) from the nearest chain atom;
        clearance is that minus carbon's van der Waals radius, 1.775."""
        (g,) = channel_guest["guests"]
        near = g["nearest_host_contacts"][0]
        assert near["atom"] == "CL1"
        assert near["d"] == round(math.sqrt(72.0), 3) == 8.485
        assert g["clearance_A"] == 6.710
        assert "," in near["sym"]           # a real operator string
        assert not g["straddles_regions"]

    def test_the_grid_answer_is_cross_checked_off_the_grid(self,
                                                           channel_guest):
        """`refine.tools_probe.void_membership` asks the same question
        analytically (26 directions, same vdW table); the two must agree."""
        (g,) = channel_guest["guests"]
        assert g["void_membership"]["inside"] is True
        assert g["void_membership"]["agrees_with_grid"] is True


# -------------------------------------------------------- 2. interstitial --

class TestInterstitial:
    def test_added_chain_is_host_because_it_is_periodic(self,
                                                        interstitial_guest):
        host = interstitial_guest["host"]
        assert host["n_atoms"] == 30
        assert [(f["key"], f["formula"], f["dimensionality"])
                for f in host["fragments"]] == [("F1", "C22", 3),
                                                ("F2", "C8", 1)]

    def test_guest_in_the_slot_is_in_no_region(self, interstitial_guest):
        (g,) = interstitial_guest["guests"]
        assert g["site"] == "interstitial"
        assert g["void_id"] is None
        assert g["d_to_inscribed_centre_A"] is None
        assert g["atoms_in_regions"] == {"CL1": 0}
        assert interstitial_guest["summary"]["interstitial"] == 1

    def test_the_cell_does_have_a_region_the_guest_is_not_in(self,
                                                             interstitial_guest):
        """Not "there are no voids": the cell has a 1294 A^3 channel, and
        the guest is still interstitial - the probe cannot roll into ITS
        slot."""
        voids = interstitial_guest["voids"]
        assert len(voids) == 1
        assert voids[0]["volume_A3"] > DEFAULT_MIN_VOID_VOLUME_A3
        assert voids[0]["dimensionality"] == 3

    def test_clearance_is_positive_but_below_the_probe(self,
                                                       interstitial_guest):
        """2.5 A from carbon: 0.725 A outside its van der Waals surface,
        yet no point within the 1.2 A shrink radius is probe-accessible."""
        (g,) = interstitial_guest["guests"]
        assert g["nearest_host_contacts"][0]["d"] == 2.500
        assert g["clearance_A"] == 0.725
        assert g["clearance_A"] < DEFAULT_PROBE_A
        # the analytic cross-check agrees the site is outside every region
        assert g["void_membership"]["inside"] is False
        assert g["void_membership"]["agrees_with_grid"] is True
        assert g["void_membership"]["nearest_d_A"] == 2.5


# -------------------------------------------------------- 3. cage cavity --

class TestCageCavity:
    def test_shell_is_one_zero_dimensional_fragment(self, cage_guest):
        assert [(f["formula"], f["dimensionality"], f["copies"], f["role"])
                for f in cage_guest["host"]["fragments"]] == \
            [("C60", 0, 1, "main")]

    def test_guest_inside_the_shell(self, cage_guest):
        (g,) = cage_guest["guests"]
        assert g["site"] == "cage_cavity"
        assert g["host_fragment"] is not None
        assert g["host_fragment"].startswith("F1#")
        assert g["region"]["dimensionality"] == 0
        assert g["d_to_inscribed_centre_A"] == 0.0
        assert cage_guest["summary"]["cage_cavity"] == 1

    def test_the_whole_wall_is_that_one_molecule(self, cage_guest):
        (g,) = cage_guest["guests"]
        share = g["region"]["enclosing_fragments"]
        assert list(share) == [g["host_fragment"]]
        assert share[g["host_fragment"]] == 1.0

    def test_interior_free_radius_is_the_analytic_one(self, cage_guest):
        """Every shell atom is 3.55 A from the centre, so the largest free
        sphere there has radius 3.55 - 1.775 = 1.775 A."""
        (g,) = cage_guest["guests"]
        assert g["region"]["inscribed_radius_A"] == round(
            SHELL_R - 1.775, 3) == 1.775
        assert g["nearest_host_contacts"][0]["d"] == 3.550
        assert g["region"]["volume_A3"] >= DEFAULT_MIN_VOID_VOLUME_A3

    def test_min_void_volume_is_a_reported_parameter_not_a_hidden_one(self):
        """The 18.5 A^3 cavity is a region at the default 8 A^3 floor and no
        region above 25: the same guest is then interstitial, and the
        criteria block says which floor was used."""
        out = locate_guests(_shell_model((SHELL_A / 2,) * 3),
                            min_void_volume_A3=25.0)
        (g,) = out["guests"]
        assert g["site"] == "interstitial"
        assert g["void_id"] is None
        assert out["criteria"]["min_void_volume_A3"] == 25.0
        assert "25.0" in g["criteria_used"]
        # the region is still THERE on the grid - it was dropped by volume,
        # which is not a disagreement with the analytic check
        assert g["void_membership"]["inside"] is True
        assert g["void_membership"]["agrees_with_grid"] is True

    def test_a_cage_on_the_cell_corner_is_still_a_cage(self):
        """D17 one level down: the cavity of a shell at the origin is stored
        as eight pieces at eight corners of the grid. Counting its wall
        piece by piece would find eight molecules where there is one."""
        out = locate_guests(_shell_model((0.0, 0.0, 0.0)))
        (g,) = out["guests"]
        assert g["site"] == "cage_cavity"
        assert g["region"]["enclosing_fragments"][g["host_fragment"]] == 1.0
        assert g["region"]["inscribed_radius_A"] == 1.775


# ------------------------------------------- 4. cavity between molecules --

class TestCavityBetweenMolecules:
    def test_the_two_bowls_are_copies_of_one_host_fragment(self,
                                                           cavity_guest):
        assert [(f["formula"], f["dimensionality"], f["copies"], f["role"])
                for f in cavity_guest["host"]["fragments"]] == \
            [("C30", 0, 2, "main")]

    def test_guest_between_the_two_bowls(self, cavity_guest):
        (g,) = cavity_guest["guests"]
        assert g["site"] == "cavity"
        assert g["host_fragment"] is None
        assert g["region"]["dimensionality"] == 0
        assert cavity_guest["summary"] == {"cage_cavity": 0, "channel": 0,
                                           "cavity": 1, "interstitial": 0}

    def test_the_wall_is_two_molecules_of_the_same_kind(self, cavity_guest):
        """The share that decides the call is per MOLECULE: both bowls are
        copies of fragment F1, so counting by fragment TYPE would say
        "100 % F1" and call a capsule a cage."""
        (g,) = cavity_guest["guests"]
        share = g["region"]["enclosing_fragments"]
        assert len(share) == 2
        assert all(0.4 <= v <= 0.6 for v in share.values())
        assert max(share.values()) < 0.95
        (void,) = [v for v in cavity_guest["voids"] if v["id"] == g["void_id"]]
        assert void["enclosing_fragment_keys"] == {"F1": 1.0}

    def test_the_guest_is_inside_the_closed_capsule(self, cavity_guest):
        """The nearest wall atom is the seam atom just above the equator,
        at z = R/60 on the sphere before the bowl is pushed up by 1.4 A:
        |(x, y, z + gap)| = sqrt(R^2 + 2*gap*z + gap^2) = 3.838 A."""
        (g,) = cavity_guest["guests"]
        z_seam = SHELL_R / 60.0
        assert g["nearest_host_contacts"][0]["d"] == round(math.sqrt(
            SHELL_R ** 2 + 2 * CAPSULE_GAP * z_seam + CAPSULE_GAP ** 2),
            3) == 3.838
        assert g["clearance_A"] == 2.063
        assert g["region"]["volume_A3"] >= DEFAULT_MIN_VOID_VOLUME_A3


# ----------------------------------------------------- 5. host-only model --

class TestHostOnlyModel:
    def test_desolvated_model_still_reports_its_pores(self):
        """The de-solvated model: nothing to locate, everything to look at."""
        out = locate_guests(_cubic(_pcu_atoms(), CELL))
        assert out["guests"] == []
        assert out["summary"] == {s: 0 for s in SITES}
        (void,) = out["voids"]
        assert void["dimensionality"] == 3
        assert void["volume_A3"] == 1428.9
        assert void["inscribed_centre_frac"] is not None
        assert void["centre_frac"] is None       # no centroid for a 3-D void

    def test_host_void_map_alone_needs_no_reflection_data(self):
        """`host_void_map` is usable on its own, on a model with no data at
        all: the mask comes from the atoms."""
        xs = _cubic(_pcu_atoms(), CELL)
        vmap = host_void_map(xs)
        assert vmap["probe_A"] == DEFAULT_PROBE_A
        assert vmap["grid_step_A"] > 0
        assert vmap["labels"].shape == tuple(vmap["gridding"])
        assert vmap["n_host_atoms"] == 22
        assert len(vmap["voids"]) == 1
        assert vmap["solvent_volume_pct_of_cell"] > 50
        assert vmap["grid_source"].startswith("step")

    def test_d_min_reproduces_the_viewers_resolution_gridding(self):
        """With data in hand the caller can ask for the grid the viewer
        uses (resolution_factor 0.25) instead of a fixed step; the answer
        says which was used."""
        xs = _cubic(_pcu_atoms(), CELL)
        vmap = host_void_map(xs, d_min=0.84)
        assert vmap["grid_source"].startswith("resolution")
        assert vmap["grid_step_A"] < 0.25          # 0.25 x 0.84 A
        assert len(vmap["voids"]) == 1
        assert vmap["voids"][0]["dimensionality"] == 3

    def test_a_model_with_no_void_at_all_reports_none(self):
        """A 1.5 A simple-cubic carbon block: the probe fits nowhere, so
        there is no region and no crash."""
        atoms = [(f"C{i * 16 + j * 4 + k}", "C", (i * 1.5, j * 1.5, k * 1.5))
                 for i in range(4) for j in range(4) for k in range(4)]
        vmap = host_void_map(_cubic(atoms, 6.0))
        assert vmap["voids"] == []
        assert vmap["solvent_volume_A3"] == 0.0
        assert vmap["n_host_atoms"] == 64

    def test_selection_may_be_labels_or_indices(self):
        xs = _cubic(_pcu_atoms() + [("CL1", "Cl", (6.0, 6.0, 6.0))], CELL)
        by_label = host_void_map(xs, [f"C{i}" for i in range(22)])
        by_index = host_void_map(xs, list(range(22)))
        assert by_label["n_host_atoms"] == by_index["n_host_atoms"] == 22
        assert by_label["voids"][0]["volume_A3"] == \
            by_index["voids"][0]["volume_A3"] == 1428.9
        # with the Cl included the void shrinks: that is exactly why the map
        # is built from the host alone
        whole = host_void_map(xs)
        assert whole["voids"][0]["volume_A3"] < 1428.9


# ------------------------------------------------------- 6. PART awareness --

def _part_model():
    """A C-Cl guest modelled in two positions, PART 1 and PART 2, in the
    channel of the pcu net. The two positions are 0.4 A apart, so without
    PART information the bonding truth joins them into one 4-atom lump."""
    guest = [("C1A", "C", (6.0, 6.0, 6.0)), ("CL1A", "Cl", (7.75, 6.0, 6.0)),
             ("C1B", "C", (6.0, 6.0, 6.4)), ("CL1B", "Cl", (7.75, 6.0, 6.4))]
    xs = _cubic(_pcu_atoms() + guest, CELL)
    part_kwargs = {"conformer_indices": [0] * 22 + [1, 1, 2, 2],
                   "sym_excl_indices": [0] * 26}
    return xs, part_kwargs


class TestParts:
    def test_the_two_positions_stay_two_components(self):
        xs, part_kwargs = _part_model()
        out = locate_guests(xs, part_kwargs=part_kwargs)
        assert [(g["formula"], g["copies"], g["parts"], g["site"])
                for g in out["guests"]] == [("CCl", 1, [1], "channel"),
                                            ("CCl", 1, [2], "channel")]
        assert [g["asu_labels"] for g in out["guests"]] == \
            [["C1A", "CL1A"], ["C1B", "CL1B"]]
        assert out["guest_parts"] == [1, 2]
        assert out["host"]["n_atoms"] == 22

    def test_without_parts_the_two_positions_fuse(self):
        """What the PART information buys: no cross-PART bond is ever used."""
        xs, _ = _part_model()
        out = locate_guests(xs)
        assert [g["formula"] for g in out["guests"]] == ["C2Cl2"]
        assert out["guest_parts"] == []

    def test_parts_may_also_be_given_as_shelx_numbers(self):
        xs, part_kwargs = _part_model()
        by_kwargs = locate_guests(xs, part_kwargs=part_kwargs)
        by_label = locate_guests(xs, parts={"C1A": 1, "CL1A": 1,
                                            "C1B": 2, "CL1B": 2})
        assert [g["asu_labels"] for g in by_label["guests"]] == \
            [g["asu_labels"] for g in by_kwargs["guests"]]


# --------------------------------------------------------- the criteria --

class TestCriteria:
    def test_the_four_definitions_travel_with_every_answer(self,
                                                           channel_guest):
        crit = channel_guest["criteria"]
        assert set(crit["definitions"]) == set(SITES) | {"host"}
        for site in SITES:
            assert crit["definitions"][site] == CRITERIA_VERBATIM[site]
            assert site in crit["definitions"][site]
            assert crit["definitions_en"][site]


    def test_the_numbers_behind_the_call_are_reported(self, channel_guest):
        crit = channel_guest["criteria"]
        assert crit["probe_A"] == DEFAULT_PROBE_A == 1.2
        assert crit["shrink_A"] == 1.2
        assert crit["grid_step_A"] == channel_guest["grid_step_A"] > 0
        assert crit["min_void_volume_A3"] == DEFAULT_MIN_VOID_VOLUME_A3
        assert crit["cage_share"] == 0.95
        assert "around_atoms" in crit["mask_source"]
        assert "no reflection data" in crit["mask_source"]

    def test_every_guest_carries_the_criterion_it_was_judged_by(
            self, channel_guest, interstitial_guest, cage_guest,
            cavity_guest):
        for out in (channel_guest, interstitial_guest, cage_guest,
                    cavity_guest):
            for g in out["guests"]:
                assert g["site"] in SITES
                used = g["criteria_used"]
                assert CRITERIA_VERBATIM[g["site"]] in used
                assert CRITERIA_EN[g["site"]] in used
                # the measured numbers, not just the rule
                measured = used.rsplit(": ", 1)[-1]
                assert any(ch.isdigit() for ch in measured), measured

    def test_no_verdict_words_beyond_the_four_labels(self, cage_guest):
        sites = {g["site"] for g in cage_guest["guests"]}
        assert sites <= set(SITES)
        assert set(cage_guest["summary"]) == set(SITES)


class TestHostRule:
    """host_min_fraction: a 0-D fragment with >= 50 % of the largest host
    fragment's atoms is host (the cage project's second independent Zr3
    cage had been read as a guest in the first one's channel)."""

    def test_a_second_big_molecule_is_host_not_guest(self):
        from crystalpilot.chem.guests import HOST_MIN_FRACTION
        assert HOST_MIN_FRACTION == 0.5
        a = 20.0
        c1, c2 = (a * 0.25,) * 3, (a * 0.75,) * 3
        big = [(f"A{i + 1}", "C", p) for i, p in
               enumerate(_fibonacci_sphere(60, SHELL_R, c1))]
        small = [(f"B{i + 1}", "C", p) for i, p in
                 enumerate(_fibonacci_sphere(50, 3.4, c2))]
        xs = _cubic(big + small + [("CL1", "Cl", c1), ("CL2", "Cl", c2)], a)
        out = locate_guests(xs)
        hosts = sorted(f["formula"] for f in out["host"]["fragments"])
        assert hosts == ["C50", "C60"], hosts
        assert "50%" in out["host"]["selection_rule"]
        assert sorted(g["site"] for g in out["guests"]) == \
            ["cage_cavity", "cage_cavity"], out["guests"]
        assert {g["formula"] for g in out["guests"]} == {"Cl"}
        # each Cl belongs to its own shell
        assert len({g["host_fragment"] for g in out["guests"]}) == 2

    def test_a_small_fragment_stays_guest(self):
        out = locate_guests(_shell_model((SHELL_A / 2,) * 3))
        assert [f["formula"] for f in out["host"]["fragments"]] == ["C60"]
        assert len(out["guests"]) == 1
        assert out["guests"][0]["site"] == "cage_cavity"
