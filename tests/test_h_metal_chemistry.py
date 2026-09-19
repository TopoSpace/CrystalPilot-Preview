"""add_hydrogens decides per atom, by chemistry, and says what it decided.

pa2 (2026-09-02, cage lanes): SHELXT's placeholder composition labelled the
mu3-O/OH and carboxylate O of a six-metal node as C and N; add_hydrogens put
riding H on those "carbons", and the agent's fix was exclude=[13 labels] -
hiding the mislabelling instead of resolving it. Meanwhile the real eta5-Cp
on the same node (five C at 2.3-2.8 A from the metal) carries H and must get
them, and a lone "C" bound only to a metal is either a mislabelled donor or
a genuine M-CH3 - ambiguous, so no H count may be guessed.

The rule is the atom's own skeleton, read through chem.metal_bonded_audit
(never re-derived here, never keyed on label text); every non-H atom the
call considered gets a decision row. Nothing in these fixtures is tuned to
the pa2 crystals: ferrocene, Cr-arene, Fe(CO)5, a Cu paddlewheel, a Zr
alkyl, organolithium - the rules are covalent radii, coordination and the
audit's generic classes.
"""
from __future__ import annotations

import math

import pytest
from cctbx import crystal, xray

from crystalpilot.core.dataset import ReflectionDataset
from crystalpilot.pipeline.session import SolveSession
from crystalpilot.tools import hydrogen_tools as HT
from crystalpilot.tools.base import ToolContext
from crystalpilot.tools.hydrogen_tools import AddHydrogens


class _Store:
    def record(self, *a, **k):
        return None

    def log(self, *a, **k):
        return None


def _structure(atoms, cell=(25, 25, 25, 90, 90, 90), sg="P 1"):
    """atoms: (label, element, cartesian xyz[, u])."""
    cs = crystal.symmetry(unit_cell=cell, space_group_symbol=sg)
    xs = xray.structure(crystal_symmetry=cs)
    uc = cs.unit_cell()
    for atom in atoms:
        label, el, cart = atom[:3]
        u = atom[3] if len(atom) > 3 else 0.03
        xs.add_scatterer(xray.scatterer(
            label=label, site=uc.fractionalize(cart),
            scattering_type=el, u=u, occupancy=1.0))
    xs.scattering_type_registry(table="it1992")
    return xs


def _session(xs):
    ses = SolveSession(dataset=ReflectionDataset(
        intensities=None, wavelength=0.71073))
    ses.model = xs
    ses.symmetry = xs.crystal_symmetry()
    return ses


def _run(atoms_or_ses, **params):
    ses = (atoms_or_ses if isinstance(atoms_or_ses, SolveSession)
           else _session(_structure(atoms_or_ses)))
    params.setdefault("elements", ["C"])
    r = AddHydrogens().run(ToolContext(store=_Store(), session=ses), **params)
    return r, ses


def _rows(r):
    return {d["label"]: d for d in r.summary["decisions"]}


def _kinds(r):
    return {p["carrier"]: p["kind"] for p in r.summary["per_carrier"]}


def _n_h(ses):
    return sum(1 for sc in ses.model.scatterers()
               if sc.scattering_type.strip().upper() == "H")


# ------------------------------------------------------------ fixtures ----

def _cp_ring(centre, m_c, labels=("C1", "C2", "C3", "C4", "C5"), c_c=1.42):
    """Regular C5 ring (C-C c_c) with every atom m_c from `centre`."""
    r = c_c / (2 * math.sin(math.radians(36)))
    h = math.sqrt(m_c ** 2 - r ** 2)
    return [(lb, "C", (centre[0] + r * math.cos(math.radians(72 * k)),
                       centre[1] + r * math.sin(math.radians(72 * k)),
                       centre[2] + h)) for k, lb in enumerate(labels)]


def _ferrocene(m_c=2.05):
    fe = (10.0, 10.0, 10.0)
    top = _cp_ring(fe, m_c)
    bottom = [(lb + "B", el, (x, y, 2 * fe[2] - z)) for lb, el, (x, y, z) in top]
    return [("FE1", "Fe", fe)] + top + bottom


def _five_o(centre, m_o=2.15, n0=1):
    out = []
    for k in range(5):
        a = math.radians(72 * k + 36)
        out.append((f"O{n0 + k}", "O",
                    (centre[0] + 1.6 * math.cos(a), centre[1] + 1.6 * math.sin(a),
                     centre[2] - math.sqrt(m_o ** 2 - 1.6 ** 2))))
    return out


def _zr_with_four_o(zr=(5.0, 5.0, 5.0), n0=20):
    atoms = [("ZR1", "Zr", zr)]
    for k in range(4):
        a = math.radians(90 * k + 45)
        atoms.append((f"O{n0 + k}", "O",
                      (zr[0] - 0.8, zr[1] + 2.05 * math.cos(a),
                       zr[2] + 2.05 * math.sin(a))))
    return atoms


def _m3_mu3(metal="Zr", mu_label="C1", mu_el="C", m_m=3.5, m_x=2.1, m_o=2.2):
    """Three metals in a triangle, one mu3 atom above the centroid at m_x
    from each, four O donors per metal placed away from the mu3 site."""
    r_c = m_m / math.sqrt(3)
    ms = [(10.0 + r_c * math.cos(math.radians(90 + 120 * k)),
           10.0 + r_c * math.sin(math.radians(90 + 120 * k)), 10.0)
          for k in range(3)]
    cen = (10.0, 10.0, 10.0)
    h = math.sqrt(max(m_x ** 2 - r_c ** 2, 0.0))
    atoms = [(f"{metal.upper()}{i + 1}", metal, p) for i, p in enumerate(ms)]
    atoms.append((mu_label, mu_el, (cen[0], cen[1], cen[2] + h)))
    n = 1
    for p in ms:
        out = ((p[0] - cen[0]) / r_c, (p[1] - cen[1]) / r_c)
        perp = (-out[1], out[0])
        for u, v, w in ((1.0, 0.0, 0.6), (1.0, 0.0, -0.6), (0.3, 1.0, 0.5),
                        (0.3, -1.0, 0.5)):
            vec = (u * out[0] + v * perp[0], u * out[1] + v * perp[1], w)
            norm = math.sqrt(sum(c * c for c in vec))
            atoms.append((f"O{n}", "O", tuple(p[i] + m_o * vec[i] / norm
                                              for i in range(3))))
            n += 1
    return atoms


def _benzoate_on_zr(zr_o=2.20, o_label="O", o_el="O"):
    """Zr-O(1) carboxylate whose second O and ipso carbon complete the
    trigonal carbon; the ring carries two more C. o_label/o_el relabel
    the bound O (the pa2 mislabel); zr_o sets the Zr-O(1) distance."""
    o1 = (5.0 + zr_o, 5.0, 5.0)
    c = (o1[0] + 1.26 * math.cos(math.radians(45)),
         o1[1] + 1.26 * math.sin(math.radians(45)), 5.0)

    def at(ang, dist):
        return (c[0] + dist * math.cos(math.radians(ang)),
                c[1] + dist * math.sin(math.radians(ang)), 5.0)
    o2, cipso = at(105, 1.26), at(345, 1.50)
    ca = (cipso[0] + 1.39 * math.cos(math.radians(45)),
          cipso[1] + 1.39 * math.sin(math.radians(45)), 5.0)
    cb = (cipso[0] + 1.39 * math.cos(math.radians(-75)),
          cipso[1] + 1.39 * math.sin(math.radians(-75)), 5.0)
    return _zr_with_four_o() + [(o_label + "1", o_el, o1), ("O2", "O", o2),
                                ("C10", "C", c), ("C11", "C", cipso),
                                ("C12", "C", ca), ("C13", "C", cb)]


def _cu_paddlewheel(relabel=None, axial=2.15):
    """Cu2(O2CR)4(H2O)2: Cu-Cu 2.65, Cu-O 1.97, axial water at `axial`."""
    relabel = relabel or {}
    atoms = [("CU1", "Cu", (10.0, 10.0, 11.325)), ("CU2", "Cu", (10.0, 10.0, 8.675))]
    rho = math.sqrt(1.97 ** 2 - 0.215 ** 2)
    for k in range(4):
        a = math.radians(90 * k)
        ox, oy = 10 + rho * math.cos(a), 10 + rho * math.sin(a)
        atoms += [(f"O{2 * k + 1}", "O", (ox, oy, 11.11)),
                  (f"O{2 * k + 2}", "O", (ox, oy, 8.89))]
        atoms += [(f"C{3 * k + 1}", "C", (10 + (rho + 0.59) * math.cos(a),
                                           10 + (rho + 0.59) * math.sin(a), 10.0)),
                  (f"C{3 * k + 2}", "C", (10 + (rho + 2.09) * math.cos(a),
                                           10 + (rho + 2.09) * math.sin(a), 10.0)),
                  (f"C{3 * k + 3}", "C", (10 + (rho + 2.09) * math.cos(a)
                                           + 0.7 * math.cos(a + math.pi / 2),
                                           10 + (rho + 2.09) * math.sin(a)
                                           + 0.7 * math.sin(a + math.pi / 2), 11.2))]
    atoms += [("O1W", "O", (10.0, 10.0, 11.325 + axial)),
              ("O2W", "O", (10.0, 10.0, 8.675 - axial))]
    return [(relabel.get(lb, (lb, el))[0], relabel.get(lb, (lb, el))[1], c)
            for lb, el, c in atoms]


def _organic():
    """C1-C2-C3 chain (CH2 x3), methyl C4 on C1, hydroxyl O1 on C3 - the
    test_h_overrides molecule: 9 H on the carbons, 1 more with O."""
    return [("C1", "C", (3.80, 5.90, 5.0)), ("C2", "C", (5.00, 5.00, 5.0)),
            ("C3", "C", (6.20, 5.90, 5.0)), ("C4", "C", (3.00, 4.60, 5.0)),
            ("O1", "O", (7.00, 4.70, 5.0))]


# ------------------------------------------------- eta rings carry H ----

class TestEtaRingsCarryH:
    def test_ferrocene_gets_ten_h_without_any_flag(self):
        # Fe-C 2.05 A is INSIDE the Fe+C covalent-radii sum: the old
        # distance rule called every Cp carbon "sigma-bonded to metal"
        # and skipped it
        assert 2.05 < HT._rcov("Fe") + HT._rcov("C")
        r, ses = _run(_ferrocene())
        assert r.ok, r.error
        assert r.summary["n_h_added"] == 10 and _n_h(ses) == 10
        kinds = _kinds(r)
        assert len(kinds) == 10 and set(kinds.values()) == {"aromatic_CH"}
        rows = _rows(r)
        for lb in ("C1", "C3B"):
            row = rows[lb]
            assert row["decision"] == "added" and row["n_h"] == 1
            assert row["geometry"].startswith("eta5-ring")
            assert row["n_heavy_neighbours"] == 2
            assert any(t.startswith("FE1:2.05") and t.endswith("(pi)")
                       for t in row["neighbours"])
        assert r.summary["decision_counts"] == {
            "considered": 10, "added": 10, "skipped": 0, "excluded": 0,
            "already_has_H": 0}
        mba = r.summary["metal_bonded_audit"]
        assert mba["n_pi_ligands"] == 2 and mba["n_suspect_elements"] == 0
        # no include_metal_bonded, no force_kind, no per-atom warning spam
        assert not any("include_metal_bonded" in w for w in r.summary["warnings"])

    def test_cp_ring_angle_does_not_read_as_sp3(self):
        # a Cp with C-C 1.44 A (108 deg ring angle, mean bond above the
        # sp2 length threshold) is still a planar CH: the ring verdict
        # beats the sp2/sp3 thresholds written for open chains
        fe = (10.0, 10.0, 10.0)
        ring = _cp_ring(fe, 2.06, c_c=1.44)
        r, _ = _run([("FE1", "Fe", fe)] + ring + _five_o(fe, m_o=2.1))
        assert r.ok, r.error
        assert set(_kinds(r).values()) == {"aromatic_CH"}
        assert r.summary["n_h_added"] == 5

    def test_eta6_arene_on_chromium(self):
        cr = (10.0, 10.0, 10.0)
        r6, h = 1.39, math.sqrt(2.14 ** 2 - 1.39 ** 2)
        arene = [(f"C{k + 1}", "C", (cr[0] + r6 * math.cos(math.radians(60 * k)),
                                     cr[1] + r6 * math.sin(math.radians(60 * k)),
                                     cr[2] + h)) for k in range(6)]
        assert 2.14 < HT._rcov("Cr") + HT._rcov("C")
        r, _ = _run([("CR1", "Cr", cr)] + arene)
        assert r.ok and r.summary["n_h_added"] == 6, r.summary["skipped"]
        assert all(d["geometry"].startswith("eta6-ring")
                   for d in r.summary["decisions"])

    def test_zr_cp_node_ring_h_and_o_donors_skipped_with_a_hint(self):
        # the pa1/pa2 cage motif with a non-mislabelled model: five ring
        # H; the five O donors, when asked for, are skipped with the
        # force_kind hint rather than silently
        zr = (10.0, 10.0, 10.0)
        atoms = [("ZR1", "Zr", zr)] + _cp_ring(zr, 2.50) + _five_o(zr)
        r, _ = _run(atoms, elements=["C", "O"])
        assert r.ok, r.error
        assert r.summary["n_h_added"] == 5
        rows = _rows(r)
        assert rows["O3"]["decision"] == "skipped"
        assert rows["O3"]["geometry"] == "metal-coordinated"
        assert "force_kind" in rows["O3"]["reason"]
        assert "ZR1 2.15 A" in rows["O3"]["reason"]
        # and the hint works: one riding H on the hydroxo candidate
        r2, ses2 = _run(atoms, elements=["C"], force_kind={"O3": "OH"})
        assert r2.ok and r2.summary["n_h_added"] == 6, r2.summary["skipped"]
        assert _kinds(r2)["O3"] == "OH"
        assert any("O3: force_kind=OH on a metal-bonded carrier" in w
                   for w in r2.summary["warnings"])


# ------------------------------------------ real sigma M-C by geometry ----

class TestSigmaMetalCarbon:
    def test_carbonyl_carbon_never_gets_h(self):
        fe = (5.0, 5.0, 5.0)
        atoms = [("FE1", "Fe", fe)]
        for k, (dx, dy, dz) in enumerate(((1, 0, 0), (-1, 0, 0), (0, 1, 0),
                                          (0, -1, 0), (0, 0, 1))):
            atoms += [(f"C{k + 1}", "C", (fe[0] + 1.80 * dx, fe[1] + 1.80 * dy,
                                          fe[2] + 1.80 * dz)),
                      (f"O{k + 1}", "O", (fe[0] + 2.94 * dx, fe[1] + 2.94 * dy,
                                          fe[2] + 2.94 * dz))]
        for flag in (False, True):
            r, ses = _run(atoms, include_metal_bonded=flag)
            assert r.ok and r.summary["n_h_added"] == 0 and _n_h(ses) == 0
            rows = _rows(r)
            assert len(rows) == 5
            for row in rows.values():
                assert row["decision"] == "skipped"
                assert "carbonyl" in row["reason"]
                assert row["geometry"] == "sp linear on metal"
        assert r.summary["metal_bonded_audit"]["n_plausible_metal_bonds"] == 5

    def test_zr_ethyl_ch2_and_ch3_by_their_own_geometry(self):
        # Zr-CH2-CH3: the audit calls C1 a sigma-alkyl M-C, so the metal
        # is a geometric neighbour and C1 is a CH2 (two H), C2 a CH3
        c1 = (7.28, 5.0, 5.0)
        c2 = (c1[0] + 1.53 * math.cos(math.radians(70.5)),
              c1[1] + 1.53 * math.sin(math.radians(70.5)), 5.0)
        atoms = _zr_with_four_o() + [("C1", "C", c1), ("C2", "C", c2)]
        r, ses = _run(atoms)
        assert r.ok, r.error
        assert _kinds(r) == {"C1": "CH2", "C2": "CH3"}, r.summary["skipped"]
        assert r.summary["n_h_added"] == 5 and _n_h(ses) == 5
        row = _rows(r)["C1"]
        assert row["n_heavy_neighbours"] == 2 and row["geometry"] == "sp3"
        assert any(t == "ZR1:2.28(M)" for t in row["neighbours"])
        assert any("C1: metal-bonded carrier" in w and "sigma-alkyl" in w
                   for w in r.summary["warnings"])
        assert "sigma-alkyl" in r.summary["metal_bonded_audit"][
            "plausible_metal_bonds"][0]

    def test_sigma_aryl_ipso_gets_none_ring_ch_get_theirs(self):
        # Pd-C(ipso) of a phenyl: the ipso carbon is a planar junction
        # (metal + two ring C), the ortho carbons are ordinary ring CH
        pd = (5.0, 5.0, 5.0)
        ring_c = (7.0 + 1.39, 5.0, 5.0)
        ring = [(f"C{k + 1}", "C", (ring_c[0] + 1.39 * math.cos(math.radians(180 + 60 * k)),
                                    ring_c[1] + 1.39 * math.sin(math.radians(180 + 60 * k)),
                                    5.0)) for k in range(6)]
        atoms = [("PD1", "Pd", pd), ("CL1", "Cl", (5.0, 7.3, 5.0)),
                 ("CL2", "Cl", (5.0, 2.7, 5.0)), ("CL3", "Cl", (2.7, 5.0, 5.0))] + ring
        r, _ = _run(atoms)
        assert r.ok, r.error
        rows = _rows(r)
        assert rows["C1"]["decision"] == "skipped"
        assert "planar sp2 junction" in rows["C1"]["reason"]
        assert rows["C1"]["n_heavy_neighbours"] == 3
        assert r.summary["n_h_added"] == 5
        assert all(rows[f"C{k}"]["kind"] == "aromatic_CH" for k in range(2, 7))

    def test_metal_the_audit_does_not_classify_keeps_the_gate(self):
        # organolithium: Li (Z=3) is outside the audit's metal set, so a
        # Li-C at sigma distance has no verdict - the covalent-radii gate
        # of old applies (skip unless include_metal_bonded), with the
        # reason saying which flag opens it
        atoms = [("LI1", "Li", (5.0, 5.0, 5.0)), ("C1", "C", (7.0, 5.0, 5.0)),
                 ("C2", "C", (7.0 + 1.53 * math.cos(math.radians(70.5)),
                              5.0 + 1.53 * math.sin(math.radians(70.5)), 5.0))]
        assert 2.0 <= HT._rcov("Li") + HT._rcov("C")
        r, _ = _run(atoms)
        assert r.ok
        row = _rows(r)["C1"]
        assert row["decision"] == "skipped" and row["geometry"] == "metal-bonded"
        assert "include_metal_bonded=true" in row["reason"]
        assert "LI1 2.00 A" in row["reason"]
        assert _kinds(r) == {"C2": "CH3"}
        r2, _ = _run(atoms, include_metal_bonded=True)
        assert r2.ok and _kinds(r2) == {"C1": "CH2", "C2": "CH3"}


# ------------------------------------ mislabelled donors are not carriers ----

class TestMislabelledDonors:
    def test_mu3_o_labelled_c_is_skipped_with_the_audit_reason(self):
        atoms = _m3_mu3()
        r, ses = _run(atoms)
        assert r.ok, r.error
        assert r.summary["n_h_added"] == 0 and _n_h(ses) == 0
        row = _rows(r)["C1"]
        assert row["decision"] == "skipped"
        assert row["geometry"] == "metal-bonded, 0 skeleton neighbour(s)"
        reason = row["reason"]
        assert "metal-bonded audit" in reason and "isolated_c" in reason
        assert "high" in reason and "no C/N/O neighbour" in reason
        assert "Candidates: O (oxo/mu-O/OH" in reason
        assert "validate_structure metal_bonded_light_atom" in reason
        assert "edit_atoms" in reason and "do NOT exclude" in reason
        assert r.summary["skipped"][0] == {"atom": "C1", "reason": reason}
        mba = r.summary["metal_bonded_audit"]
        assert mba["n_suspect_elements"] == 1
        assert mba["suspect_elements"][0]["label"] == "C1"
        assert mba["suspect_elements"][0]["candidates"][0].startswith("O")
        # the blanket flag does not reach an audit suspect either (the
        # old code gave this "C" a tertiary H once the flag was on)
        r2, ses2 = _run(atoms, include_metal_bonded=True)
        assert r2.ok and r2.summary["n_h_added"] == 0 and _n_h(ses2) == 0
        assert _rows(r2)["C1"]["decision"] == "skipped"
        # force_kind is the per-atom opt-in, and it says so
        r3, ses3 = _run(atoms, force_kind={"C1": "tertiary_CH"})
        assert r3.ok and r3.summary["n_h_added"] == 1 and _n_h(ses3) == 1
        assert any("C1: force_kind=tertiary_CH overrides the metal-bonded "
                   "audit's high isolated_c flag" in w
                   for w in r3.summary["warnings"])

    def test_mu3_o_labelled_n_on_a_manganese_cluster(self):
        # non-Zr, N label: with N requested the tool skips it for the
        # audit's reason instead of hanging an NH on it
        atoms = _m3_mu3(metal="Mn", mu_label="N1", mu_el="N", m_m=3.3,
                        m_x=1.9, m_o=2.1)
        r, ses = _run(atoms, elements=["C", "N"])
        assert r.ok and r.summary["n_h_added"] == 0 and _n_h(ses) == 0
        row = _rows(r)["N1"]
        assert row["decision"] == "skipped" and "isolated_n" in row["reason"]
        assert "carbon skeleton" in row["reason"]

    def test_carboxylate_o_labelled_c_beyond_the_covalent_sum(self):
        # the pa2 path: Zr-"C" 2.60 A is BEYOND the Zr+C covalent sum, so
        # the old rule ignored the metal, saw one 1.26 A neighbour and
        # placed a linear CH hydrogen on a carboxylate oxygen
        atoms = _benzoate_on_zr(zr_o=2.60, o_label="C", o_el="C")
        assert 2.60 > HT._rcov("Zr") + HT._rcov("C")
        r, _ = _run(atoms)
        assert r.ok, r.error
        row = _rows(r)["C1"]
        assert row["decision"] == "skipped"
        assert "carboxylate_o" in row["reason"] and "high" in row["reason"]
        assert "retype" in row["reason"].lower() or "edit_atoms" in row["reason"]
        assert "C1" not in _kinds(r)
        # the organic carbons of the same call were processed normally
        assert r.summary["n_h_added"] > 0
        assert _rows(r)["C10"]["decision"] == "skipped"     # carboxylate C
        # and with the label corrected nothing is flagged
        clean, _ = _run(_benzoate_on_zr(zr_o=2.60))
        assert clean.ok and "metal_bonded_audit" not in clean.summary

    def test_lone_metal_bonded_c_is_ambiguous_not_a_methyl(self):
        # Cu paddlewheel whose axial water wears a C label at 2.00 A: the
        # old code with include_metal_bonded read "terminal C, long bond"
        # and hung three H on it. Aqua O vs M-CH3 cannot be told apart by
        # geometry, so no H count is guessed - by default or by flag
        mis = _cu_paddlewheel({"O1W": ("C1W", "C")}, axial=2.00)
        clean = _cu_paddlewheel(axial=2.00)
        rc, _ = _run(clean)
        assert rc.ok and rc.summary["n_h_added"] > 0
        for flag in (False, True):
            r, _ = _run(mis, include_metal_bonded=flag)
            assert r.ok, r.error
            row = _rows(r)["C1W"]
            assert row["decision"] == "skipped" and row["n_h"] == 0
            assert "isolated_c" in row["reason"] and "medium" in row["reason"]
            assert "Candidates:" in row["reason"]
            assert "force_kind" in row["reason"]
            # every other carbon decided exactly as in the clean model
            mine = {k: v for k, v in _rows(r).items() if k != "C1W"}
            assert mine == _rows(rc)
            assert r.summary["n_h_added"] == rc.summary["n_h_added"]
        # the genuine M-CH3 reading is an explicit per-atom opt-in
        r3, ses3 = _run(mis, force_kind={"C1W": "CH3"})
        assert r3.ok, r3.error
        assert _kinds(r3)["C1W"] == "CH3"
        assert r3.summary["n_h_added"] == rc.summary["n_h_added"] + 3

    def test_no_decision_is_keyed_on_the_label_text(self):
        # the same aqua-labelled-C skip whatever the label says: "OW1"
        # typed C is still a lone metal-bonded C, "C1W" typed O is an O
        r, _ = _run(_cu_paddlewheel({"O1W": ("OW1", "C")}, axial=2.00))
        assert _rows(r)["OW1"]["decision"] == "skipped"
        assert "isolated_c" in _rows(r)["OW1"]["reason"]
        r2, _ = _run(_cu_paddlewheel({"O1W": ("C1W", "O")}, axial=2.00),
                     elements=["C", "O"])
        row = _rows(r2)["C1W"]
        assert row["element"] == "O" and row["decision"] == "skipped"
        assert row["geometry"] == "metal-coordinated"


# ---------------------------------------------------- the decision table ----

class TestDecisionTable:
    KEYS = {"label", "element", "n_heavy_neighbours", "geometry", "decision",
            "n_h", "kind", "reason"}

    def test_every_considered_atom_has_one_row(self):
        r, _ = _run(_organic())
        assert r.ok and r.summary["n_h_added"] == 9
        rows = r.summary["decisions"]
        assert [d["label"] for d in rows] == ["C1", "C2", "C3", "C4"]
        for d in rows:
            assert self.KEYS <= set(d)
            assert d["decision"] == "added"
            assert d["n_heavy_neighbours"] in (1, 2)
            assert d["reason"]
        assert sum(d["n_h"] for d in rows) == r.summary["n_h_added"]
        assert {d["label"]: d["kind"] for d in rows} == _kinds(r)
        assert _rows(r)["C1"]["geometry"] == "sp3"
        assert _rows(r)["C4"]["geometry"] == "terminal sp3"
        assert r.summary["decision_counts"] == {
            "considered": 4, "added": 4, "skipped": 0, "excluded": 0,
            "already_has_H": 0}
        # no metals: no audit block to read
        assert "metal_bonded_audit" not in r.summary
        # O requested: one more row, an OH
        r2, _ = _run(_organic(), elements=["C", "O"])
        assert _rows(r2)["O1"]["decision"] == "added"
        assert _rows(r2)["O1"]["kind"] == "OH"
        assert _rows(r2)["O1"]["geometry"] == "terminal on C (single bond)"

    def test_excluded_and_kept_explicit_h_rows(self):
        r, _ = _run(_organic(), exclude=["C4"])
        row = _rows(r)["C4"]
        assert row["decision"] == "excluded" and row["n_h"] == 0
        assert "exclude=" in row["reason"]
        assert r.summary["decision_counts"]["excluded"] == 1
        # an explicit H on a carrier outside elements= is kept and the
        # table says so (pa2 hex-l0-r1: water H from the difference map)
        atoms = _organic() + [("H1O", "H", (7.75, 4.30, 5.0))]
        r2, ses2 = _run(atoms)
        row = _rows(r2)["O1"]
        assert row["decision"] == "already_has_H" and row["n_h"] == 1
        assert "H1O" in row["reason"]
        assert r2.summary["decision_counts"]["already_has_H"] == 1
        assert r2.summary["kept_explicit_h"] == [
            {"h": "H1O", "carrier": "O1", "carrier_element": "O"}]
        assert _n_h(ses2) == 10

    def test_skip_reasons_reach_the_table(self):
        # a nitrile carbon and a saturated one, both skipped with the
        # same reason the skipped= list carries
        atoms = [("N1", "N", (8.16, 7.02, 7.0)), ("C1", "C", (7.0, 7.0, 7.0)),
                 ("C2", "C", (5.56, 7.08, 7.0))]
        r, _ = _run(atoms)
        row = _rows(r)["C1"]
        assert row["decision"] == "skipped" and row["n_h"] == 0
        assert row["geometry"].startswith("sp linear")
        assert "near-linear sp carbon" in row["reason"]
        assert {"atom": "C1", "reason": row["reason"]} in r.summary["skipped"]
        assert row["neighbours"] == ["N1:1.16", "C2:1.44"]

    def test_cross_part_carrier_row(self):
        cs = crystal.symmetry(unit_cell=(12, 12, 12, 90, 90, 90),
                              space_group_symbol="P 1")
        xs = xray.structure(crystal_symmetry=cs)
        uc = cs.unit_cell()
        for label, el, cart, occ in (("C5", "C", (3.5, 5.0, 5.0), 1.0),
                                     ("C6", "C", (5.0, 5.0, 5.0), 1.0),
                                     ("O6A", "O", (5.9, 5.9, 5.0), 0.6),
                                     ("O6B", "O", (5.9, 5.9, 5.8), 0.4)):
            xs.add_scatterer(xray.scatterer(
                label=label, site=uc.fractionalize(cart),
                scattering_type=el, u=0.03, occupancy=occ))
        xs.scattering_type_registry(table="it1992")
        ses = _session(xs)
        ses.flags["disorder_groups"] = [{
            "fvar_index": 2, "value": 0.6,
            "members": [{"label": "O6A", "part": 1, "sign": 1, "mult": 1.0},
                        {"label": "O6B", "part": 2, "sign": -1, "mult": 1.0}]}]
        r, _ = _run(ses)
        assert r.ok
        row = _rows(r)["C6"]
        assert row["decision"] == "skipped" and row["geometry"] == "cross-PART"
        assert "disorder PARTs" in row["reason"]
        assert _rows(r)["C5"]["decision"] == "added"

    def test_cap_is_generous_and_announced(self, monkeypatch):
        monkeypatch.setattr(HT, "DECISION_TABLE_CAP", 2)
        r, _ = _run(_organic())
        assert r.ok and r.summary["n_h_added"] == 9
        assert len(r.summary["decisions"]) == 2
        assert "capped at 2 of 4" in r.summary["decisions_note"]
        assert r.summary["decision_counts"]["considered"] == 4
        # the real cap does not bite a large organic model
        assert HT.DECISION_TABLE_CAP == 2      # patched in this test only
        monkeypatch.undo()
        assert HT.DECISION_TABLE_CAP >= 400


# ---------------------------------------------------------- robustness ----

class TestOneBadCarrierDoesNotAbort:
    def test_classifier_exception_is_a_per_carrier_skip(self, monkeypatch):
        real = HT._h_directions

        def boom(kind, u_vecs, ref_perp):
            if kind == "CH3":
                raise RuntimeError("synthetic generator failure")
            return real(kind, u_vecs, ref_perp)
        monkeypatch.setattr(HT, "_h_directions", boom)
        r, ses = _run(_organic())
        assert r.ok, r.error
        assert r.summary["n_h_added"] == 6 and _n_h(ses) == 6
        row = _rows(r)["C4"]
        assert row["decision"] == "skipped"
        assert "classifier raised RuntimeError: synthetic generator failure" \
            in row["reason"]
        assert "the others were processed" in row["reason"]
        assert {d["label"] for d in r.summary["decisions"]
                if d["decision"] == "added"} == {"C1", "C2", "C3"}

    def test_constraint_builder_exception_leaves_no_orphan_h(self, monkeypatch):
        class _Boom:
            room_temperature_bond_length = {"C": 0.96}

            def __init__(self, **kw):
                raise RuntimeError("no constraint for you")
        monkeypatch.setitem(HT._KINDS, "CH3", (_Boom, 3, 1.5))
        r, ses = _run(_organic())
        assert r.ok, r.error
        assert r.summary["n_h_added"] == 6 and _n_h(ses) == 6
        row = _rows(r)["C4"]
        assert row["decision"] == "skipped" and row["n_h"] == 0
        assert "H generator _Boom raised RuntimeError" in row["reason"]
        assert "C4" not in _kinds(r)
        # the riding constraints that were built are consistent: 3
        # carriers, 6 H, a fixup in front
        assert len(ses.flags["h_constraints"]) == 1 + 3 + 6

    def test_nothing_processable_is_a_failure_with_the_table(self, monkeypatch):
        def boom(kind, u_vecs, ref_perp):
            raise RuntimeError("every carrier fails")
        monkeypatch.setattr(HT, "_h_directions", boom)
        r, ses = _run(_organic())
        assert not r.ok
        assert "could not classify any carrier" in r.error
        assert "every carrier fails" in r.error
        assert len(r.summary["decisions"]) == 4
        assert r.summary["decision_counts"]["skipped"] == 4
        assert _n_h(ses) == 0

    def test_audit_failure_falls_back_to_the_gate_with_a_warning(self, monkeypatch):
        def boom(xs, parts=None):
            raise RuntimeError("audit exploded")
        monkeypatch.setattr(HT, "audit_metal_bonded_light_atoms", boom)
        r, ses = _run(_ferrocene())
        assert r.ok, r.error
        # without the audit a Cp carbon is back to "sigma-bonded to
        # metal" - honest about it, no H guessed
        assert r.summary["n_h_added"] == 0 and _n_h(ses) == 0
        assert any("audit did not run (RuntimeError: audit exploded)" in w
                   for w in r.summary["warnings"])
        assert r.summary["metal_bonded_audit"]["error"].startswith("RuntimeError")
        row = _rows(r)["C1"]
        assert row["decision"] == "skipped" and "include_metal_bonded" in row["reason"]
        # the old opt-in still works in that degraded mode
        r2, ses2 = _run(_ferrocene(), include_metal_bonded=True)
        assert r2.ok and r2.summary["n_h_added"] == 10 and _n_h(ses2) == 10


# ------------------------------------------------------- no regression ----

class TestOrganicRegression:
    def test_plain_molecule_gets_exactly_the_h_it_always_got(self):
        r, ses = _run(_organic())
        assert r.ok and r.summary["n_h_added"] == 9 and _n_h(ses) == 9
        assert _kinds(r) == {"C1": "CH2", "C2": "CH2", "C3": "CH2", "C4": "CH3"}
        assert r.summary["kinds"] == {"CH2": 3, "CH3": 1}
        # re-run replaces, never accumulates
        r2 = AddHydrogens().run(ToolContext(store=_Store(), session=ses),
                                elements=["C"])
        assert r2.ok and r2.summary["n_h_removed"] == 9
        assert r2.summary["n_h_added"] == 9 and _n_h(ses) == 9

    def test_kept_explicit_h_survive_placement(self):
        # found by the decision table: the placement loop stripped EVERY
        # H (kept explicit ones included) while n0 still counted them, so
        # the fresh H landed at shifted indices, every carrier failed
        # verification ("2 -> 3 neighbours") and the kept water H was
        # lost - the hex-l0-r1 "keep the difference-map water H" path
        # never survived placement
        atoms = _organic() + [("H1O", "H", (7.75, 4.30, 5.0))]
        r, ses = _run(atoms)
        assert r.ok, r.error
        assert r.summary["n_h_added"] == 9 and r.summary["n_h_removed"] == 0
        assert r.summary.get("note") is None
        labels = [sc.label for sc in ses.model.scatterers()]
        assert "H1O" in labels and _n_h(ses) == 10
        # the kept H keeps its index and site; the riding fixup's index
        # checks still name the right atoms
        assert labels.index("H1O") == 5
        fix = ses.flags["h_constraints"][0]
        assert all(labels[i] == lbl for i, lbl in fix.checks)
        # and the constraints survive a reparametrisation
        import smtbx.utils
        from smtbx.refinement import constraints as smtbx_constraints
        smtbx_constraints.reparametrisation(
            structure=ses.model, constraints=list(ses.flags["h_constraints"]),
            connectivity_table=smtbx.utils.connectivity_table(ses.model))

    def test_long_metal_contact_still_treated_as_pi(self):
        # La...C 3.16 A (practice-770): beyond the covalent sum, no audit
        # verdict - a non-valence contact, H placed from the ring
        atoms = [("C1", "C", (8.0, 8.0, 8.0)), ("C2", "C", (9.204, 8.695, 8.0)),
                 ("C3", "C", (6.796, 8.695, 8.0)), ("LA1", "La", (8.0, 7.0, 5.0))]
        r, _ = _run(atoms)
        assert r.ok
        assert _kinds(r)["C1"] == "aromatic_CH"
        assert any("pi/non-valence" in w for w in r.summary["warnings"])
        assert any(t.endswith("(pi)") for t in _rows(r)["C1"]["neighbours"])

    def test_riding_meta_and_constraints_unchanged_in_shape(self):
        r, ses = _run(_ferrocene())
        meta = ses.flags["h_riding_meta"]
        assert meta["elements"] == ["C"] and len(meta["per_carrier"]) == 10
        assert meta["params"] == {"elements": ["C"]}
        assert all(set(g) == {"carrier", "kind", "n_h", "h", "x_h"}
                   for g in meta["per_carrier"])
        assert len(ses.flags["h_constraints"]) == 1 + 10 + 10


@pytest.mark.parametrize("m_c", [2.05, 2.30, 2.50])
def test_ring_verdict_is_distance_independent(m_c):
    # eta5 on Fe at 2.05, Zr at 2.30 / 2.50: the ring decides, not the
    # metal-carbon distance against a covalent sum
    metal = "Fe" if m_c < 2.2 else "Zr"
    m = (10.0, 10.0, 10.0)
    r, _ = _run([(metal.upper() + "1", metal, m)] + _cp_ring(m, m_c))
    assert r.ok and r.summary["n_h_added"] == 5, r.summary["skipped"]
