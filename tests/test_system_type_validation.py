"""Per-system-type validation + eta-ring (Cp/arene) recognition (pa1 P1-11).

pa1 cage-l3-r1 (2026-09-02): validate_structure judged a discrete Zr6
molecular cage by MOF criteria - "framework dimensionality 0 ... structure
may be incomplete", three eta5-Cp rings and the Cl- counter-ions counted
among 56 "free" atoms, confidence 27 - and the agent discarded a trial
that matched 149/154 published atoms. These tests pin the per-type
behaviour: a 0-D molecule is judged by molecular criteria, a framework
keeps the MOF criteria, an eta-bound ring is one ligand.
"""
from __future__ import annotations

import math

from cctbx import crystal, xray

from crystalpilot.chem.asu_sanity import asu_coherence
from crystalpilot.chem.connectivity import analyze_connectivity, fragment_identity
from crystalpilot.core.dataset import ReflectionDataset
from crystalpilot.pipeline.session import SolveSession
from crystalpilot.tools.base import ToolContext
from crystalpilot.tools.validation_tools import ValidateStructure, compute_confidence


class _Store:
    def record(self, *a, **k):
        return None

    def log(self, *a, **k):
        return None


def _structure(atoms, cell=(20, 20, 20, 90, 90, 90), sg="P 1"):
    """atoms: (label, element, cartesian xyz[, u[, occupancy]])."""
    cs = crystal.symmetry(unit_cell=cell, space_group_symbol=sg)
    xs = xray.structure(crystal_symmetry=cs)
    uc = cs.unit_cell()
    for atom in atoms:
        label, el, cart = atom[:3]
        u = atom[3] if len(atom) > 3 else 0.03
        occ = atom[4] if len(atom) > 4 else 1.0
        xs.add_scatterer(xray.scatterer(
            label=label, site=uc.fractionalize(cart),
            scattering_type=el, u=u, occupancy=occ))
    xs.scattering_type_registry(table="it1992")
    return xs


def _session(xs):
    ses = SolveSession(dataset=ReflectionDataset(
        intensities=None, wavelength=0.71073))
    ses.model = xs
    ses.symmetry = xs.crystal_symmetry()
    return ses


def _run(xs, **params):
    return ValidateStructure().run(
        ToolContext(store=_Store(), session=_session(xs)), **params)


def _codes(alerts):
    return {a["code"] for a in alerts}


def _cp_ring(centre, m_c=2.50, prefix="C", z_sign=+1, pucker=0.0):
    """Regular C5 pentagon (C-C 1.42 A) whose atoms are all m_c from centre."""
    r = 1.42 / (2 * math.sin(math.radians(36)))
    h = math.sqrt(m_c ** 2 - r ** 2)
    atoms = []
    for k in range(5):
        a = math.radians(72 * k)
        dz = pucker * (1 if k % 2 else -1)
        atoms.append((f"{prefix}{k + 1}", "C",
                      (centre[0] + r * math.cos(a), centre[1] + r * math.sin(a),
                       centre[2] + z_sign * h + dz)))
    return atoms


def _five_o(centre, m_o=2.15):
    atoms = []
    for k in range(5):
        a = math.radians(72 * k + 36)
        atoms.append((f"O{k + 1}", "O",
                      (centre[0] + 1.6 * math.cos(a), centre[1] + 1.6 * math.sin(a),
                       centre[2] - math.sqrt(m_o ** 2 - 1.6 ** 2))))
    return atoms


def _zr_cp_complex(zr=(10.0, 10.0, 10.0), **ring_kw):
    """CpZr(O)5: the pa1 cage node motif (5 O at 2.0-2.3 + eta5-Cp at 2.4-2.6)."""
    return [("ZR1", "Zr", zr)] + _cp_ring(zr, **ring_kw) + _five_o(zr)


def _carboxylate_bridge(axis: int, origin=(0.0, 0.0, 0.0), n0=1):
    """O-C-O bridge from a metal at origin to its image one cell along axis
    (cell edge 6 A): M-O 1.96, C-O 1.21 - a bonded coordination polymer."""
    def pt(along, side):
        p = list(origin)
        p[axis] += along
        p[(axis + 1) % 3] += side
        return tuple(p)
    return [(f"O{n0}", "O", pt(1.9, 0.5)), (f"C{n0}", "C", pt(3.0, 0.0)),
            (f"O{n0 + 1}", "O", pt(4.1, 0.5))]


# ---------------------------------------------------------------- graph ----

class TestConnectivity:
    def test_cross_face_bond_counted_once(self):
        # C1-C2 1.5 A closing through the a face: one bond, not two
        xs = _structure([("C1", "C", (0.5, 5, 5)), ("C2", "C", (9.0, 5, 5))],
                        cell=(10, 20, 20, 90, 90, 90))
        rep = analyze_connectivity(xs)
        assert len(rep.bonds) == 1

    def test_eta5_cp_ring_is_one_ligand_of_the_metal(self):
        rep = analyze_connectivity(_structure(_zr_cp_complex()))
        assert len(rep.pi_ligands) == 1
        ring = rep.pi_ligands[0]
        assert ring["metal"] == "ZR1" and ring["hapticity"] == 5
        assert set(ring["ring_atoms"]) == {"C1", "C2", "C3", "C4", "C5"}
        assert 2.4 <= ring["m_c_range"][0] <= ring["m_c_range"][1] <= 2.6
        env = rep.coordination[0]
        # 5 O + one ring = 6, inside the Zr window - not "CN 10" or "CN 5"
        assert env["cn"] == 6 and env["cn_plausible"]
        assert any(n.startswith("eta5-C5") for n in env["neighbors"])
        # the ring belongs to the metal's fragment: no "free" carbons
        assert rep.fragments[0]["n_atoms"] == 11
        assert rep.isolated_atoms == []
        assert rep.short_contacts == []

    def test_puckered_ring_is_not_an_eta_ligand(self):
        rep = analyze_connectivity(_structure(_zr_cp_complex(pucker=0.3)))
        assert rep.pi_ligands == []

    def test_ring_beside_the_metal_is_not_an_eta_ligand(self):
        # flat pentagon with its centroid 2.19 A from Zr but IN the ring
        # plane (tilt 90 deg): atoms are not equidistant -> not side-on
        zr = (10.0, 10.0, 10.0)
        r = 1.42 / (2 * math.sin(math.radians(36)))
        ring = [(f"C{k + 1}", "C",
                 (zr[0] + 2.19 + r * math.cos(math.radians(72 * k)),
                  zr[1] + r * math.sin(math.radians(72 * k)), zr[2]))
                for k in range(5)]
        rep = analyze_connectivity(_structure([("ZR1", "Zr", zr)] + ring))
        assert rep.pi_ligands == []

    def test_sigma_range_cp_is_relabelled_eta(self):
        # Fe-C(Cp) 2.05 A is inside the 2.15 A M-C sigma cutoff: without the
        # relabel the five carbons would count as five ligands (CN 8)
        fe = (10.0, 10.0, 10.0)
        atoms = [("FE1", "Fe", fe)] + _cp_ring(fe, m_c=2.05)
        for k in range(3):
            a = math.radians(120 * k)
            atoms.append((f"O{k + 1}", "O",
                          (fe[0] + 1.4 * math.cos(a), fe[1] + 1.4 * math.sin(a),
                           fe[2] - math.sqrt(2.0 ** 2 - 1.4 ** 2))))
        rep = analyze_connectivity(_structure(atoms))
        assert len(rep.pi_ligands) == 1
        assert rep.coordination[0]["cn"] == 4
        assert any(b.kind == "eta" for b in rep.bonds)

    @staticmethod
    def _split_metal():
        # ZR1 with six O below it and an undeclared alternative ZR1B 0.8 A
        # away (its nearest O is 1.75 A: bonded, not an impossible contact)
        zr = (10.0, 10.0, 10.0)
        atoms = [("ZR1", "Zr", zr), ("ZR1B", "Zr", (10.8, 10.0, 10.0))]
        for k in range(6):
            a = math.radians(30 + 60 * k)
            atoms.append((f"O{k + 1}", "O",
                          (zr[0] + 1.6 * math.cos(a), zr[1] + 1.6 * math.sin(a),
                           zr[2] - (2.15 ** 2 - 1.6 ** 2) ** 0.5)))
        return atoms

    def test_undeclared_split_site_is_an_impossible_contact_not_a_ligand(self):
        # pa1 cage-l0-r1: 'Fe:0.78' inside the CN of a split metal site;
        # short-contact test runs BEFORE the bond cutoff now
        rep = analyze_connectivity(_structure(self._split_metal()))
        env = next(e for e in rep.coordination if e["atom"] == "ZR1")
        assert env["cn"] == 6
        assert env["impossible_contacts"] == ["Zr:0.80"]
        assert [sorted(s["atoms"]) for s in rep.short_contacts] == [["ZR1", "ZR1B"]]

    def test_declared_parts_never_see_each_other(self):
        rep = analyze_connectivity(_structure(self._split_metal()),
                                   parts={"ZR1": 1, "ZR1B": 2})
        assert rep.short_contacts == []
        env = next(e for e in rep.coordination if e["atom"] == "ZR1")
        assert env["cn"] == 6 and "impossible_contacts" not in env

    def test_impossible_metal_carbon_contact_is_not_a_bond(self):
        # the cage trial's Zr-C 0.77-1.05 A "bonds": under the 2.15 A M-C
        # cutoff they inflated CN and never reached short_contacts
        rep = analyze_connectivity(_structure(
            _zr_cp_complex() + [("C77", "C", (10.0, 10.0, 8.95))]))
        assert rep.coordination[0]["cn"] == 6
        assert rep.coordination[0]["impossible_contacts"] == ["C:1.05"]
        assert rep.short_contacts[0]["d"] == 1.05
        assert not any(b.i == 0 and b.j == 11 for b in rep.bonds)

    def test_spurious_peak_in_a_cp_gives_one_ring(self):
        # a peak bonded into the ring makes a second, overlapping 5-cycle
        # (cage trial ZR02: eta6 + eta5 + eta5 over six atoms); one ring
        # per metal and atom set is reported, the regular one
        zr = (10.0, 10.0, 10.0)
        r = 1.42 / (2 * math.sin(math.radians(36)))
        h = math.sqrt(2.5 ** 2 - r ** 2)
        mid = 0.373          # C1..C3 midpoint radius in a regular pentagon
        extra = ("C6", "C", (zr[0] + mid * math.cos(math.radians(72)),
                             zr[1] + mid * math.sin(math.radians(72)),
                             zr[2] + h + 0.25))
        rep = analyze_connectivity(_structure(_zr_cp_complex() + [extra]))
        assert len(rep.pi_ligands) == 1
        assert set(rep.pi_ligands[0]["ring_atoms"]) == {"C1", "C2", "C3", "C4", "C5"}
        # the peak sits 2.47 A from Zr (inside sum(r_cov) 2.51, so the
        # bonding truth lists it) but 0.87 A from C2: an atom with an
        # impossible contact is a modelling defect, listed apart, not a donor
        assert rep.coordination[0]["cn"] == 6
        assert rep.coordination[0]["suspect_ligands"] == ["C:2.47"]

    def test_isolated_labels_deduped_over_p1_copies(self):
        # a lone Cl on a general position in P21/c has 4 P1 copies; the
        # pa1 alert listed 'O007' four times as if it were four problems
        xs = _structure([("C1", "C", (1.0, 1.0, 1.0)), ("C2", "C", (2.5, 1.0, 1.0)),
                         ("CL1", "Cl", (4.0, 8.0, 9.5))],
                        cell=(12, 13, 14, 90, 95, 90), sg="P 21/c")
        rep = analyze_connectivity(xs)
        assert rep.isolated_atoms == ["CL1"]
        census = {c["role"]: c for c in rep.fragment_census}
        assert census["counter_ion"]["copies"] == 4


# --------------------------------------------------------- system type ----

class TestSystemType:
    def test_molecular_complex_with_counter_ion(self):
        rep = analyze_connectivity(_structure(
            _zr_cp_complex() + [("CL1", "Cl", (3.0, 3.0, 3.0))]))
        assert rep.system_type == "molecular"
        ev = rep.system_type_evidence
        assert ev["dimensionality"] == 0
        assert ev["counter_ions"] == {"Cl-": 1}
        assert "organometallic" in ev["label"]
        roles = {c["role"]: c for c in rep.fragment_census}
        assert roles["main"]["n_atoms"] == 11
        assert roles["counter_ion"]["identity"] == "Cl-"

    def test_3d_coordination_polymer_is_framework(self):
        atoms = [("ZN1", "Zn", (0.0, 0.0, 0.0))]
        for axis in range(3):
            atoms += _carboxylate_bridge(axis, n0=2 * axis + 1)
        rep = analyze_connectivity(_structure(atoms, cell=(6, 6, 6, 90, 90, 90)))
        assert rep.system_type == "framework"
        assert rep.framework_dimensionality == 3
        assert rep.coordination[0]["cn"] == 6

    def test_1d_chain_is_framework_1d(self):
        atoms = [("ZN1", "Zn", (0.0, 5.0, 5.0))] + _carboxylate_bridge(
            0, origin=(0.0, 5.0, 5.0))
        rep = analyze_connectivity(_structure(atoms, cell=(6, 15, 15, 90, 90, 90)))
        assert rep.system_type == "framework"
        assert rep.framework_dimensionality == 1

    def test_carbon_free_lattice_is_salt(self):
        rep = analyze_connectivity(_structure(
            [("ZN1", "Zn", (0, 0, 0)), ("O1", "O", (2, 0, 0)),
             ("O2", "O", (0, 2, 0)), ("O3", "O", (0, 0, 2))],
            cell=(4, 4, 4, 90, 90, 90)))
        assert rep.system_type == "salt"
        assert rep.framework_dimensionality == 3

    def test_no_bonds_is_unknown(self):
        rep = analyze_connectivity(_structure(
            [("ZN1", "Zn", (2, 2, 2)), ("O1", "O", (12, 12, 12))]))
        assert rep.system_type == "unknown"
        assert "no bonded pairs" in rep.system_type_evidence["rationale"]

    def test_carbon_free_metal_core_is_unknown_not_incomplete_framework(self):
        # the Zr6O15 core cage-l3-r1 delivered: ligands not yet placed
        zr = (10.0, 10.0, 10.0)
        atoms = [("ZR1", "Zr", zr)]
        for k in range(9):
            a = math.radians(40 * k)
            z = 10.0 + (1.2 if k % 2 else -1.2)
            atoms.append((f"O{k + 1}", "O",
                          (zr[0] + 1.85 * math.cos(a), zr[1] + 1.85 * math.sin(a), z)))
        rep = analyze_connectivity(_structure(atoms))
        assert rep.system_type == "unknown"
        assert "ligands" in rep.system_type_evidence["rationale"]

    def test_fragment_identity_table(self):
        assert fragment_identity({"Cl": 1}) == ("counter_ion", "Cl-")
        assert fragment_identity({"C": 3, "N": 1, "O": 1, "H": 7})[0] == "solvent"
        assert fragment_identity({"B": 1, "F": 4}) == ("counter_ion", "BF4-")
        assert fragment_identity({"C": 2}) is None


# ---------------------------------------------------- validate_structure ----

class TestValidateStructure:
    def test_molecule_is_not_an_incomplete_framework(self):
        r = _run(_structure(_zr_cp_complex() + [("CL1", "Cl", (3.0, 3.0, 3.0))]))
        assert r.ok, r.error
        codes = _codes(r.summary["alerts"])
        assert "low_dimensionality" not in codes
        assert "isolated_atoms" not in codes          # Cl- is a counter-ion
        assert "asu_detached" not in codes            # nothing bonds via symmetry
        assert "ghost_atom_suspect" not in codes      # a free Cl- is not a ghost
        assert "metal_cn" not in codes                # 5 O + Cp = 6
        assert "short_contact" not in codes
        assert "pi_ligand" in codes and "lone_ions_solvent" in codes
        assert r.summary["system_type"] == "molecular"
        assert "molecular" in r.summary["system_type_label"]
        assert "0-D" in r.summary["criteria_applied"]
        conf = r.summary["confidence"]
        assert conf["system_type"] == "molecular"
        assert conf["breakdown"]["alerts"] == 0.0
        assert r.summary["pi_ligands"][0]["metal"] == "ZR1"
        lone = next(a for a in r.summary["alerts"] if a["code"] == "lone_ions_solvent")
        assert "CL1 (Cl-)" in lone["message"]

    def test_forced_framework_still_flags_a_molecule(self):
        r = _run(_structure(_zr_cp_complex()), expect_framework=True)
        low = next(a for a in r.summary["alerts"] if a["code"] == "low_dimensionality")
        assert "forced" in low["message"] and "framework" in low["message"]
        assert r.summary["system_type"] == "framework"
        assert r.summary["system_type_evidence"]["inferred_type"] == "molecular"

    def test_1d_chain_framework_flagged_unless_molecular_forced(self):
        xs = _structure([("ZN1", "Zn", (0.0, 5.0, 5.0))]
                        + _carboxylate_bridge(0, origin=(0.0, 5.0, 5.0)),
                        cell=(6, 15, 15, 90, 90, 90))
        r = _run(xs)
        low = next(a for a in r.summary["alerts"] if a["code"] == "low_dimensionality")
        assert "dimensionality = 1" in low["message"]
        assert "inferred" in low["message"]
        assert "low_dimensionality" not in _codes(
            _run(xs, expect_framework=False).summary["alerts"])

    def test_3d_framework_keeps_framework_criteria(self):
        atoms = [("ZN1", "Zn", (0.0, 0.0, 0.0))]
        for axis in range(3):
            atoms += _carboxylate_bridge(axis, n0=2 * axis + 1)
        r = _run(_structure(atoms, cell=(6, 6, 6, 90, 90, 90)))
        assert r.summary["system_type"] == "framework"
        assert "low_dimensionality" not in _codes(r.summary["alerts"])
        assert "periodicity expected" in r.summary["criteria_applied"]

    def test_framework_lone_atom_stays_a_warning(self):
        # framework criteria unchanged: a lone O in a MOF is ghost/solvent
        atoms = [("ZN1", "Zn", (0.0, 0.0, 0.0)), ("O9", "O", (3.0, 3.0, 3.0))]
        for axis in range(3):
            atoms += _carboxylate_bridge(axis, n0=2 * axis + 1)
        r = _run(_structure(atoms, cell=(6, 6, 6, 90, 90, 90)))
        iso = next(a for a in r.summary["alerts"] if a["code"] == "isolated_atoms")
        assert "O9" in iso["message"] and "framework" in iso["message"]

    def test_unrecognised_lone_atom_in_molecule_gets_the_ghost_verdict(self):
        # a lone C is nothing a 0-D crystal explains: it keeps the critical
        # ghost verdict (one verdict per atom, with the two-branch advice)
        # and is never read as counter-ion / solvent
        r = _run(_structure(_zr_cp_complex() + [("C99", "C", (3.0, 3.0, 3.0))]))
        ghost = next(a for a in r.summary["alerts"] if a["code"] == "ghost_atom_suspect")
        assert ghost["message"].startswith("C99")
        codes = _codes(r.summary["alerts"])
        assert "lone_ions_solvent" not in codes and "isolated_atoms" not in codes
        assert r.summary["system_type_evidence"]["unrecognised_lone_atoms"] == 1
        assert r.summary["confidence"]["breakdown"]["alerts"] == -12.0

    def test_lone_atom_the_asu_graph_cannot_judge_is_still_a_warning(self):
        # asu_coherence never judges its own main fragment: a lone Zn that
        # IS the main ASU fragment must still surface as an isolated atom
        r = _run(_structure([("ZN1", "Zn", (2, 2, 2)), ("CL1", "Cl", (12, 12, 12))]))
        iso = next(a for a in r.summary["alerts"] if a["code"] == "isolated_atoms")
        assert "ZN1" in iso["message"]
        lone = next(a for a in r.summary["alerts"] if a["code"] == "lone_ions_solvent")
        assert "CL1 (Cl-)" in lone["message"]

    def test_unrecognised_small_fragment_in_molecule_is_flagged(self):
        r = _run(_structure(_zr_cp_complex()
                            + [("C98", "C", (3.0, 3.0, 3.0)),
                               ("C99", "C", (4.4, 3.0, 3.0))]))
        frag = next(a for a in r.summary["alerts"]
                    if a["code"] == "unrecognised_fragments")
        assert "C98" in frag["message"] and "C2" in frag["message"]

    def test_solvent_fragment_in_molecule_is_not_flagged(self):
        # a DMF (C3 N O) next to the complex: recognised, no warning
        dmf = [("N9", "N", (3.0, 3.0, 3.0)), ("C91", "C", (4.4, 3.0, 3.0)),
               ("C92", "C", (2.3, 4.2, 3.0)), ("C93", "C", (2.3, 1.8, 3.0)),
               ("O9", "O", (5.1, 4.0, 3.0))]
        r = _run(_structure(_zr_cp_complex() + dmf))
        codes = _codes(r.summary["alerts"])
        assert "unrecognised_fragments" not in codes
        assert "isolated_atoms" not in codes
        assert "DMF" in r.summary["system_type_evidence"]["solvent"]

    def test_anonymous_lone_o_in_molecule_is_a_ghost_not_solvent(self):
        # one verdict per atom: the ghost alert (with its two-branch
        # advice) - not also "consistent with water"
        r = _run(_structure(_zr_cp_complex() + [("O9", "O", (3.0, 3.0, 3.0))]))
        codes = _codes(r.summary["alerts"])
        assert "ghost_atom_suspect" in codes
        assert "lone_ions_solvent" not in codes
        assert "isolated_atoms" not in codes
        assert r.summary["system_type_evidence"]["unrecognised_lone_atoms"] == 1

    def test_declared_water_in_molecule_is_recognised(self):
        r = _run(_structure(_zr_cp_complex() + [("O1W", "O", (3.0, 3.0, 3.0))]))
        codes = _codes(r.summary["alerts"])
        assert "ghost_atom_suspect" not in codes
        assert "isolated_atoms" not in codes
        lone = next(a for a in r.summary["alerts"] if a["code"] == "lone_ions_solvent")
        assert "O1W" in lone["message"]

    def test_declared_part_split_metal_is_not_a_short_contact(self):
        zr = (10.0, 10.0, 10.0)
        atoms = [("ZR1", "Zr", zr), ("ZR1B", "Zr", (10.8, 10.0, 10.0))] + _five_o(zr)
        ses = _session(_structure(atoms))
        ses.flags["disorder_groups"] = [{"members": [
            {"label": "ZR1", "part": 1}, {"label": "ZR1B", "part": 2}]}]
        r = ValidateStructure().run(ToolContext(store=_Store(), session=ses))
        assert "short_contact" not in _codes(r.summary["alerts"])
        undeclared = _run(_structure(atoms))
        short = next(a for a in undeclared.summary["alerts"] if a["code"] == "short_contact")
        assert "0.8 A" in short["message"]

    def test_unknown_type_is_said_not_scored_as_framework(self):
        r = _run(_structure([("ZN1", "Zn", (2, 2, 2)), ("O1", "O", (12, 12, 12))]))
        codes = _codes(r.summary["alerts"])
        assert r.summary["system_type"] == "unknown"
        assert "system_type_undetermined" in codes
        assert "low_dimensionality" not in codes
        assert "isolated_atoms" in codes                # ZN1 has no identity
        assert "unrecognised_fragments" not in codes

    def test_validation_state_carries_the_type(self):
        ses = _session(_structure(_zr_cp_complex()))
        ValidateStructure().run(ToolContext(store=_Store(), session=ses))
        assert ses.validation["system_type"] == "molecular"
        assert ses.validation["pi_ligands"][0]["hapticity"] == 5
        assert ses.validation["criteria_applied"].startswith("molecular criteria")
        assert ses.validation["connectivity"]["system_type"] == "molecular"


class TestConfidence:
    def test_breakdown_and_criteria(self):
        c = compute_confidence({"r1_strong": 0.27}, [], 0, "molecular")
        assert c["system_type"] == "molecular"
        assert set(c["breakdown"]) == {"r1", "goof", "diff_map", "alerts"}
        # cage-l3-r1 arithmetic: R1 0.27 alone costs 45.5 of the 73 lost
        assert c["breakdown"]["r1"] == -45.5
        assert c["score"] == 54.5

    def test_same_alerts_same_score_regardless_of_type(self):
        alerts = [{"severity": "warning", "code": "x"}]
        a = compute_confidence({"r1_strong": 0.08}, alerts, 3, "framework")
        b = compute_confidence({"r1_strong": 0.08}, alerts, 0, "molecular")
        assert a["score"] == b["score"]
        assert a["criteria"] != b["criteria"]

    def test_default_system_type_is_framework(self):
        assert compute_confidence({}, [], 3)["system_type"] == "framework"


# ------------------------------------------------------- asu_sanity ions ----

def _p21c(atoms):
    return _structure(atoms, cell=(12, 13, 14, 90, 95, 90), sg="P 21/c")


class TestAsuSanityIons:
    _pair = [("C1", "C", (1.0, 1.0, 1.0)), ("C2", "C", (2.5, 1.0, 1.0))]

    def test_free_halide_is_not_a_ghost(self):
        rep = asu_coherence(_p21c(self._pair + [("CL1", "Cl", (4.0, 8.0, 9.5), 0.04)]))
        assert rep["ghost_suspects"] == []
        assert rep["detached"][0]["attachment"] == "none"

    def test_anonymous_lone_oxygen_is_still_a_ghost(self):
        rep = asu_coherence(_p21c(self._pair + [("O9", "O", (4.0, 8.0, 9.5), 0.04)]))
        assert [g["label"] for g in rep["ghost_suspects"]] == ["O9"]

    def test_collapsed_u_lone_oxygen_hints_at_a_halide(self):
        # cage-l3-r1: "ghost" O007 with Ueq -0.001 where the published
        # structure has a free Cl-
        rep = asu_coherence(_p21c(self._pair + [("O7", "O", (4.0, 8.0, 9.5), -0.001)]))
        g = rep["ghost_suspects"][0]
        assert g["label"] == "O7"
        assert any("too light" in r for r in g["reasons"])
        assert "heavier candidate" in g["advice"]

    def test_partial_halide_is_still_a_ghost(self):
        rep = asu_coherence(_p21c(self._pair
                                  + [("CL1", "Cl", (4.0, 8.0, 9.5), 0.04, 0.5)]))
        assert [g["label"] for g in rep["ghost_suspects"]] == ["CL1"]
