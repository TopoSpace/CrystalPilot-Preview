"""PART-aware add_hydrogens (round-10 defect #9, practice-770).

The connectivity table is purely geometric: overlapping PART 1/PART 2
alternatives look bonded to each other, every disordered carrier appears
saturated, and add_hydrogens silently under-protonates (770: 26 of 69 H).
With disorder_groups in the session flags the tool must apply SHELX PART
semantics: different non-zero parts never see each other, each alternative
gets its own H with the carrier's occupancy, and the new H join the
carrier's disorder group (same FVAR linkage).
"""
import pytest
from cctbx import crystal, xray

from crystalpilot.core.dataset import ReflectionDataset
from crystalpilot.pipeline.session import SolveSession
from crystalpilot.tools.base import ToolContext
from crystalpilot.tools.hydrogen_tools import AddHydrogens


class _Store:
    def record(self, *a, **k):
        return None

    def log(self, *a, **k):
        return None


def _session():
    """N1-C2-N3 chain with C2 disordered over two sites 0.7 A apart.

    Each alternative has 2 heavy neighbours at ~1.5-1.65 A / <115 deg
    (a clean CH2 carrier); geometrically the two alternatives also fall
    within the C-C covalent cutoff of each other.
    """
    cs = crystal.symmetry(unit_cell=(12, 12, 12, 90, 90, 90),
                          space_group_symbol="P 1")
    xs = xray.structure(crystal_symmetry=cs)
    uc = cs.unit_cell()

    def add(label, el, cart, occ=1.0):
        xs.add_scatterer(xray.scatterer(
            label=label, site=uc.fractionalize(cart),
            scattering_type=el, u=0.03, occupancy=occ))

    add("N1", "N", (3.79, 5.88, 5.0))
    add("N3", "N", (6.21, 5.88, 5.0))
    add("C2A", "C", (5.0, 5.0, 5.0), 0.6)
    add("C2B", "C", (5.0, 5.0, 5.7), 0.4)
    xs.scattering_type_registry(table="it1992")
    ses = SolveSession(dataset=ReflectionDataset(
        intensities=None, wavelength=0.71073))
    ses.model = xs
    ses.symmetry = cs
    return ses


def _ctx(ses):
    return ToolContext(store=_Store(), session=ses)


class TestPartAwareH:
    def test_geometric_merge_without_flags(self):
        # control: no disorder metadata -> A/B look mutually bonded, the
        # carriers are misclassified (3 apparent neighbours) and the pair
        # cannot receive its full 2+2 H. This is the defect the flags fix.
        ses = _session()
        r = AddHydrogens().run(_ctx(ses), elements=["C"])
        assert r.ok
        assert r.summary["n_h_added"] < 4
        pc = {p["carrier"]: p for p in r.summary["per_carrier"]}
        assert "C2A" not in pc or pc["C2A"]["kind"] != "CH2"

    def test_both_parts_fully_protonated(self):
        ses = _session()
        ses.flags["disorder_groups"] = [{
            "fvar_index": 2, "value": 0.6,
            "members": [
                {"label": "C2A", "part": 1, "sign": 1, "mult": 1.0},
                {"label": "C2B", "part": 2, "sign": -1, "mult": 1.0},
            ]}]
        r = AddHydrogens().run(_ctx(ses), elements=["C"])
        assert r.ok, r.error
        s = r.summary
        assert s["n_h_added"] == 4
        assert s["n_h_in_disorder_parts"] == 4
        pc = {p["carrier"]: p for p in s["per_carrier"]}
        assert pc["C2A"]["kind"] == "CH2" and pc["C2A"]["n_h"] == 2
        assert pc["C2B"]["kind"] == "CH2" and pc["C2B"]["n_h"] == 2

        # H inherit the carrier occupancy
        occ = {sc.label: float(sc.occupancy)
               for sc in ses.model.scatterers()}
        for h in pc["C2A"]["h"]:
            assert occ[h] == pytest.approx(0.6)
        for h in pc["C2B"]["h"]:
            assert occ[h] == pytest.approx(0.4)

        # input params are stored for the run_shelxl adopt replay (#14a)
        assert ses.flags["h_riding_meta"]["params"]["elements"] == ["C"]

        # H join the carrier's disorder group with its part/sign/mult
        g = ses.flags["disorder_groups"][0]
        mem = {m["label"]: m for m in g["members"]}
        for h in pc["C2A"]["h"]:
            assert mem[h]["part"] == 1 and mem[h]["sign"] == 1
        for h in pc["C2B"]["h"]:
            assert mem[h]["part"] == 2 and mem[h]["sign"] == -1

    def test_reparametrisation_accepts_disordered_riding(self):
        # the actual round-3 failure: RefineLS fed a raw geometric
        # connectivity table to smtbx reparametrisation, phantom A<->B
        # neighbours changed the pivot counts and the riding constraints
        # were rejected (InvalidConstraint) for every disordered carrier
        import smtbx.utils
        from smtbx.refinement import constraints as smtbx_constraints

        from crystalpilot.refine.nodes import part_connectivity_kwargs

        ses = _session()
        ses.flags["disorder_groups"] = [{
            "fvar_index": 2, "value": 0.6,
            "members": [
                {"label": "C2A", "part": 1, "sign": 1, "mult": 1.0},
                {"label": "C2B", "part": 2, "sign": -1, "mult": 1.0},
            ]}]
        r = AddHydrogens().run(_ctx(ses), elements=["C"])
        assert r.ok and r.summary["n_h_added"] == 4
        ck = part_connectivity_kwargs(ses.flags, ses.model.scatterers())
        assert "conformer_indices" in ck  # H members made it into the flags
        # raw geometric table: phantom A<->B bonds -> constraint rejected
        from smtbx.refinement.constraints import InvalidConstraint
        with pytest.raises(InvalidConstraint, match="bad connectivity"):
            smtbx_constraints.reparametrisation(
                structure=ses.model,
                constraints=list(ses.flags["h_constraints"]),
                connectivity_table=smtbx.utils.connectivity_table(ses.model))
        # PART-aware table (what RefineLS now passes): accepted
        smtbx_constraints.reparametrisation(
            structure=ses.model,
            constraints=list(ses.flags["h_constraints"]),
            connectivity_table=smtbx.utils.connectivity_table(
                ses.model, **ck))

    def test_rerun_replaces_h_members(self):
        # re-running strips old H from model AND from the group members
        # before re-adding: member list must not grow run over run
        ses = _session()
        ses.flags["disorder_groups"] = [{
            "fvar_index": 2, "value": 0.6,
            "members": [
                {"label": "C2A", "part": 1, "sign": 1, "mult": 1.0},
                {"label": "C2B", "part": 2, "sign": -1, "mult": 1.0},
            ]}]
        ctx = _ctx(ses)
        r1 = AddHydrogens().run(ctx, elements=["C"])
        assert r1.ok and r1.summary["n_h_added"] == 4
        r2 = AddHydrogens().run(ctx, elements=["C"])
        assert r2.ok and r2.summary["n_h_added"] == 4
        members = ses.flags["disorder_groups"][0]["members"]
        assert len(members) == 6  # 2 carriers + 4 H, no stale duplicates
        assert ses.model.scatterers().size() == 8


class TestCovalentRadiiGate:
    def test_p_bonded_carrier_gets_h(self):
        # P-CH2-C: P-C ~1.88 A was rejected by the old fixed 1.20-1.80 A
        # gate (round-10 defect #11: practice-770 lost every isopropyl H
        # on phosphorus; the agent had to fake P positions to work around)
        cs = crystal.symmetry(unit_cell=(14, 14, 14, 90, 90, 90),
                              space_group_symbol="P 1")
        xs = xray.structure(crystal_symmetry=cs)
        uc = cs.unit_cell()

        def add(label, el, cart):
            xs.add_scatterer(xray.scatterer(
                label=label, site=uc.fractionalize(cart),
                scattering_type=el, u=0.03, occupancy=1.0))

        add("P1", "P", (8.88, 7.0, 7.0))        # C2-P1 = 1.88 A
        add("C2", "C", (7.0, 7.0, 7.0))         # angle P1-C2-C3 = 109.47
        add("C3", "C", (6.49, 8.4425, 7.0))     # C2-C3 = 1.53 A
        xs.scattering_type_registry(table="it1992")
        ses = SolveSession(dataset=ReflectionDataset(
            intensities=None, wavelength=0.71073))
        ses.model = xs
        ses.symmetry = cs
        r = AddHydrogens().run(_ctx(ses), elements=["C"])
        assert r.ok
        pc = {p["carrier"]: p for p in r.summary["per_carrier"]}
        assert pc["C2"]["kind"] == "CH2" and pc["C2"]["n_h"] == 2, (
            r.summary["skipped"])
        assert pc["C3"]["n_h"] == 3

    def test_ghost_still_rejected(self):
        # the gate must still reject chemically absurd contacts (C-C 1.05 A
        # ghost blob) - the radii-based window keeps the old C-C behaviour
        cs = crystal.symmetry(unit_cell=(14, 14, 14, 90, 90, 90),
                              space_group_symbol="P 1")
        xs = xray.structure(crystal_symmetry=cs)
        uc = cs.unit_cell()
        for lbl, el, cart in (("C1", "C", (7.0, 7.0, 7.0)),
                              ("C2", "C", (8.05, 7.0, 7.0))):
            xs.add_scatterer(xray.scatterer(
                label=lbl, site=uc.fractionalize(cart),
                scattering_type=el, u=0.03, occupancy=1.0))
        xs.scattering_type_registry(table="it1992")
        ses = SolveSession(dataset=ReflectionDataset(
            intensities=None, wavelength=0.71073))
        ses.model = xs
        ses.symmetry = cs
        r = AddHydrogens().run(_ctx(ses), elements=["C"])
        assert r.ok
        reasons = " ".join(s["reason"] for s in r.summary["skipped"])
        assert "implausible" in reasons


class TestPartKwargsHelper:
    def test_negative_part_maps_to_sym_excl(self):
        from cctbx.array_family import flex  # noqa: F401

        from crystalpilot.refine.nodes import part_kwargs_from_parts
        kw = part_kwargs_from_parts([0, 1, -1, 2])
        assert list(kw["conformer_indices"]) == [0, 1, 1, 2]
        assert list(kw["sym_excl_indices"]) == [0, 0, 1, 0]

    def test_ordered_model_is_noop(self):
        from crystalpilot.refine.nodes import part_kwargs_from_parts
        assert part_kwargs_from_parts([0, 0, 0]) == {}


class TestPartsExtra:
    """PART-block atoms with plain (non-FVAR) sofs - SHELXL writes some
    back that way; their PART must survive adopt/serialize round trips."""

    RES = (
        "TITL plain-part\n"
        "CELL 0.71073 10.0 10.0 10.0 90.0 90.0 90.0\n"
        "ZERR 1 0.001 0.001 0.001 0.0 0.0 0.0\n"
        "LATT -1\n"
        "SFAC C H O\n"
        "UNIT 2 4 2\n"
        "FVAR 1.0 0.6\n"
        "C1   1  0.100000  0.100000  0.100000  11.00000  0.02000\n"
        "O1   3  0.300000  0.300000  0.300000  11.00000  0.02500\n"
        "PART 1\n"
        "H1O  2  0.340000  0.330000  0.330000  21.00000  0.03000\n"
        "PART 2\n"
        "H2O  2  0.260000  0.330000  0.330000   0.40000  0.03000\n"
        "PART 0\n"
        "HKLF 4\n"
        "END\n")

    def _parsed(self, tmp_path):
        from crystalpilot.io.shelx_model import load_res_model
        p = tmp_path / "plain.res"
        p.write_text(self.RES, encoding="utf-8")
        return load_res_model(p)

    def test_loose_parts_captured(self, tmp_path):
        from crystalpilot.refine.nodes import (disorder_from_parsed,
                                               loose_parts_from_parsed)
        parsed = self._parsed(tmp_path)
        dg, _ = disorder_from_parsed(parsed)
        members = [m["label"] for g in dg for m in g["members"]]
        assert members == ["H1O"]  # plain-sof H2O is not FVAR-linked
        loose = loose_parts_from_parsed(parsed, dg)
        assert loose == {"H2O": 2}

    def test_connectivity_and_serialization_cover_extra(self, tmp_path):
        from crystalpilot.refine.nodes import (disorder_from_parsed,
                                               loose_parts_from_parsed,
                                               part_connectivity_kwargs,
                                               serialization_extras)
        parsed = self._parsed(tmp_path)
        dg, _ = disorder_from_parsed(parsed)
        flags = {"disorder_groups": dg,
                 "parts_extra": loose_parts_from_parsed(parsed, dg)}
        kw = part_connectivity_kwargs(flags, parsed.structure.scatterers())
        assert list(kw["conformer_indices"]) == [0, 0, 1, 2]
        extras = serialization_extras(flags)
        assert extras["parts"].get("H2O") == 2
        assert "H2O" not in extras["sof_codes"]  # plain occupancy stays plain

    def test_extra_only_no_groups(self):
        from crystalpilot.refine.nodes import part_connectivity_kwargs

        class _Sc:
            def __init__(self, lbl):
                self.label = lbl
        kw = part_connectivity_kwargs(
            {"parts_extra": {"C1A": 1, "C1B": 2}},
            [_Sc("C1A"), _Sc("C1B"), _Sc("O1")])
        assert list(kw["conformer_indices"]) == [1, 2, 0]


class TestRound4Cluster:
    """Defect #13 cluster from practice-770 round 4."""

    def test_disordered_carrier_h_labels_fit_shelx(self):
        # part-2 carrier 'C25B' used to yield 5-char H25BA/H25BB; the
        # serializer renamed them at commit and every label-keyed flag
        # (PART membership!) desynced from the live model
        ses = _session()
        # relabel to the model_disorder convention: A keeps base label
        for sc in ses.model.scatterers():
            if sc.label == "C2A":
                sc.label = "C25"
            elif sc.label == "C2B":
                sc.label = "C25B"
        ses.flags["disorder_groups"] = [{
            "fvar_index": 2, "value": 0.6,
            "members": [
                {"label": "C25", "part": 1, "sign": 1, "mult": 1.0},
                {"label": "C25B", "part": 2, "sign": -1, "mult": 1.0},
            ]}]
        r = AddHydrogens().run(_ctx(ses), elements=["C"])
        assert r.ok and r.summary["n_h_added"] == 4
        h_labels = [sc.label for sc in ses.model.scatterers()
                    if sc.scattering_type.strip() == "H"]
        assert all(len(lb) <= 4 for lb in h_labels), h_labels
        mem_labels = {m["label"] for m in
                      ses.flags["disorder_groups"][0]["members"]}
        assert set(h_labels) <= mem_labels | {"C25", "C25B"}

    def test_pi_metal_contact_does_not_block_h(self):
        # La...C 3.2 A arene contact is within the covalent-radii cutoff
        # (La 2.07 + C 0.77 + 0.5) but is NOT a valence bond: the ring CH
        # must be protonated without include_metal_bonded (770 round 4
        # lost C5/C10/C17 ring H to this)
        cs = crystal.symmetry(unit_cell=(16, 16, 16, 90, 90, 90),
                              space_group_symbol="P 1")
        xs = xray.structure(crystal_symmetry=cs)
        uc = cs.unit_cell()

        def add(label, el, cart):
            xs.add_scatterer(xray.scatterer(
                label=label, site=uc.fractionalize(cart),
                scattering_type=el, u=0.03, occupancy=1.0))

        # aromatic CH: two ring C at 1.39 A / 120 deg, La 3.2 A off-plane
        add("C1", "C", (8.0, 8.0, 8.0))
        add("C2", "C", (9.204, 8.695, 8.0))
        add("C3", "C", (6.796, 8.695, 8.0))
        add("LA1", "La", (8.0, 7.0, 5.0))     # d(C1-La) = 3.16
        xs.scattering_type_registry(table="it1992")
        ses = SolveSession(dataset=ReflectionDataset(
            intensities=None, wavelength=0.71073))
        ses.model = xs
        ses.symmetry = cs
        r = AddHydrogens().run(_ctx(ses), elements=["C"])
        assert r.ok
        pc = {p["carrier"]: p for p in r.summary["per_carrier"]}
        assert "C1" in pc and pc["C1"]["kind"] == "aromatic_CH", (
            r.summary["skipped"])
        assert any("pi/non-valence" in w for w in r.summary["warnings"])

    def test_sigma_metal_carbon_decided_by_its_own_skeleton(self):
        # pa2 (2026-09-02): a sigma M-C is no longer a blanket skip. The
        # metal-bonded audit reads Ni-C 1.80 A next to a C-C 1.53 A as a
        # sigma-alkyl M-C, so the metal counts as a geometric neighbour
        # and C1 gets H by its own geometry - with a warning naming the
        # audit verdict, and a decision row saying so. The gate survives
        # only for metals the audit does not classify (see
        # test_h_metal_chemistry: organolithium) and audit suspects are
        # skipped whatever the flags say (mislabelled donors).
        cs = crystal.symmetry(unit_cell=(16, 16, 16, 90, 90, 90),
                              space_group_symbol="P 1")
        xs = xray.structure(crystal_symmetry=cs)
        uc = cs.unit_cell()

        def add(label, el, cart):
            xs.add_scatterer(xray.scatterer(
                label=label, site=uc.fractionalize(cart),
                scattering_type=el, u=0.03, occupancy=1.0))

        add("C1", "C", (8.0, 8.0, 8.0))
        add("C2", "C", (9.53, 8.0, 8.0))      # 1.53 A
        add("NI1", "Ni", (7.0, 6.5, 8.0))     # 1.80 A sigma Ni-C
        xs.scattering_type_registry(table="it1992")
        ses = SolveSession(dataset=ReflectionDataset(
            intensities=None, wavelength=0.71073))
        ses.model = xs
        ses.symmetry = cs
        r = AddHydrogens().run(_ctx(ses), elements=["C"])
        assert r.ok
        pc = {p["carrier"]: p for p in r.summary["per_carrier"]}
        assert "C1" in pc and pc["C1"]["n_h"] >= 1, r.summary["skipped"]
        row = next(d for d in r.summary["decisions"] if d["label"] == "C1")
        assert row["decision"] == "added"
        assert row["n_heavy_neighbours"] == 2      # Ni counted, C2
        assert "NI1:1.80(M)" in row["neighbours"]
        assert any("C1: metal-bonded carrier" in w and "sigma-alkyl" in w
                   for w in r.summary["warnings"])
        assert r.summary["metal_bonded_audit"]["n_plausible_metal_bonds"] == 1

    def test_linear_sp_carbon_gets_no_h(self):
        # nitrile carbon: N at 1.16 A and C at 1.44 A, angle ~174 deg
        cs = crystal.symmetry(unit_cell=(14, 14, 14, 90, 90, 90),
                              space_group_symbol="P 1")
        xs = xray.structure(crystal_symmetry=cs)
        uc = cs.unit_cell()

        def add(label, el, cart):
            xs.add_scatterer(xray.scatterer(
                label=label, site=uc.fractionalize(cart),
                scattering_type=el, u=0.03, occupancy=1.0))

        add("N1", "N", (8.16, 7.02, 7.0))
        add("C1", "C", (7.0, 7.0, 7.0))
        add("C2", "C", (5.56, 7.08, 7.0))
        xs.scattering_type_registry(table="it1992")
        ses = SolveSession(dataset=ReflectionDataset(
            intensities=None, wavelength=0.71073))
        ses.model = xs
        ses.symmetry = cs
        r = AddHydrogens().run(_ctx(ses), elements=["C"])
        assert r.ok
        pc = {p["carrier"] for p in r.summary["per_carrier"]}
        assert "C1" not in pc
        reasons = " ".join(s["reason"] for s in r.summary["skipped"])
        assert "near-linear sp carbon" in reasons


class TestPruneMetalContacts:
    def test_reparametrisation_survives_pi_metal(self):
        # the round-5 stopper verbatim: constraint table counted the La pi
        # contact as a third neighbour of the P-CH2-N pivot ->
        # 'Invalid secondary_xh2_sites constraint involving C7:
        #  bad connectivity'
        import smtbx.utils
        from smtbx.refinement import constraints as smtbx_constraints
        from smtbx.refinement.constraints import InvalidConstraint

        from crystalpilot.refine.nodes import (part_connectivity_kwargs,
                                               prune_long_metal_contacts)
        cs = crystal.symmetry(unit_cell=(16, 16, 16, 90, 90, 90),
                              space_group_symbol="P 1")
        xs = xray.structure(crystal_symmetry=cs)
        uc = cs.unit_cell()

        def add(label, el, cart):
            xs.add_scatterer(xray.scatterer(
                label=label, site=uc.fractionalize(cart),
                scattering_type=el, u=0.03, occupancy=1.0))

        add("P1", "P", (8.88, 7.0, 7.0))         # C2-P1 = 1.88
        add("C2", "C", (7.0, 7.0, 7.0))          # the CH2 pivot
        add("N1", "N", (6.51, 8.386, 7.0))       # C2-N1 = 1.47, 109.5 deg
        add("LA1", "La", (6.2, 5.0, 4.6))        # C2...La = 3.22 (pi)
        xs.scattering_type_registry(table="it1992")
        ses = SolveSession(dataset=ReflectionDataset(
            intensities=None, wavelength=0.71073))
        ses.model = xs
        ses.symmetry = cs
        r = AddHydrogens().run(_ctx(ses), elements=["C"])
        assert r.ok
        pc = {p["carrier"]: p for p in r.summary["per_carrier"]}
        assert pc["C2"]["kind"] == "CH2", r.summary["skipped"]

        ck = part_connectivity_kwargs(ses.flags, ses.model.scatterers())
        h_constraints = list(ses.flags["h_constraints"])
        with pytest.raises(InvalidConstraint, match="bad connectivity"):
            smtbx_constraints.reparametrisation(
                structure=ses.model, constraints=h_constraints,
                connectivity_table=smtbx.utils.connectivity_table(
                    ses.model, **ck))
        ct = smtbx.utils.connectivity_table(ses.model, **ck)
        n_pruned = prune_long_metal_contacts(ct, ses.model)
        assert n_pruned >= 1
        smtbx_constraints.reparametrisation(
            structure=ses.model, constraints=h_constraints,
            connectivity_table=ct)

    def test_sigma_bonds_survive_prune(self):
        import smtbx.utils

        from crystalpilot.refine.nodes import prune_long_metal_contacts
        cs = crystal.symmetry(unit_cell=(16, 16, 16, 90, 90, 90),
                              space_group_symbol="P 1")
        xs = xray.structure(crystal_symmetry=cs)
        uc = cs.unit_cell()
        for lbl, el, cart in (("LA1", "La", (7.0, 7.0, 7.0)),
                              ("N1", "N", (9.47, 7.0, 7.0)),   # 2.47 sigma
                              ("C1", "C", (7.0, 10.2, 7.0))):  # 3.2 pi
            xs.add_scatterer(xray.scatterer(
                label=lbl, site=uc.fractionalize(cart),
                scattering_type=el, u=0.03, occupancy=1.0))
        xs.scattering_type_registry(table="it1992")
        ct = smtbx.utils.connectivity_table(xs)
        prune_long_metal_contacts(ct, xs)
        pst = ct.pair_asu_table.extract_pair_sym_table(
            skip_j_seq_less_than_i_seq=False,
            all_interactions_from_inside_asu=True)
        la_nbs = {int(j) for j in pst[0].keys()}
        assert 1 in la_nbs      # La-N sigma bond kept
        assert 2 not in la_nbs  # La...C pi contact pruned


def test_cross_part_carrier_skipped():
    """r12 backflow: a part-0 carrier bonded into BOTH alternatives of a
    disorder region (C6H/C6J vs A/B oxygens in the CD-MOF campaign) gets an
    inflated neighbour count and an auto riding H that SHELXL rejects -
    the tool must skip it with an actionable reason instead."""
    cs = crystal.symmetry(unit_cell=(12, 12, 12, 90, 90, 90),
                          space_group_symbol="P 1")
    xs = xray.structure(crystal_symmetry=cs)
    uc = cs.unit_cell()

    def add(label, el, cart, occ=1.0):
        xs.add_scatterer(xray.scatterer(
            label=label, site=uc.fractionalize(cart),
            scattering_type=el, u=0.03, occupancy=occ))

    add("C5", "C", (3.5, 5.0, 5.0))          # part-0 backbone neighbour
    add("C6", "C", (5.0, 5.0, 5.0))          # the cross-part carrier
    add("O6A", "O", (5.9, 5.9, 5.0), 0.6)    # PART 1 alternative
    add("O6B", "O", (5.9, 5.9, 5.8), 0.4)    # PART 2 alternative
    xs.scattering_type_registry(table="it1992")
    ses = SolveSession(dataset=ReflectionDataset(
        intensities=None, wavelength=0.71073))
    ses.model = xs
    ses.symmetry = cs
    ses.flags["disorder_groups"] = [{
        "fvar_index": 2, "value": 0.6,
        "members": [
            {"label": "O6A", "part": 1, "sign": 1, "mult": 1.0},
            {"label": "O6B", "part": 2, "sign": -1, "mult": 1.0},
        ]}]
    r = AddHydrogens().run(_ctx(ses), elements=["C"])
    assert r.ok
    sk = {s["atom"]: s["reason"] for s in r.summary["skipped"]}
    assert "C6" in sk and "disorder PARTs" in sk["C6"]
    assert not any(p["carrier"] == "C6" for p in r.summary["per_carrier"])
