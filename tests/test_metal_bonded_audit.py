"""Metal-bonded light-atom audit (pa2 backflow, 2026-09-02).

pa2 cage-l0-r1/r2, cage-l2-r2: SHELXT's placeholder composition "C H N O"
handed out C/N labels that the agent kept - 10-13 Zr-C at 2.1-2.6 A, 18
Zr-N <= 2.6 A (mu3-O/OH and carboxylate O in the reference), 30 N-N
"bonds" of 1.2-1.8 A, eta5-Cp rings read as an "unrecognised C4 fragment",
Zr CN=11 with three O-H hydrogens counted, and a 'Zr2' adjudication that
stopped matching once SHELXL upper-cased the labels. These tests pin the
audit rules - element-generic (covalent radii + the chem.knowledge donor
windows, any metal, any ring size), with the true metal-carbon chemistry
(carbonyl, alkynyl, sigma-alkyl, carbene, nitrile) left alone.
"""
from __future__ import annotations

import math

from cctbx import crystal, xray

from crystalpilot.benchmark import grade as G
from crystalpilot.chem.metal_bonded_audit import (audit_metal_bonded_light_atoms,
                                                  donor_candidates)
from crystalpilot.core.dataset import ReflectionDataset
from crystalpilot.pipeline.session import SolveSession
from crystalpilot.tools.base import ToolContext
from crystalpilot.tools.validation_tools import ValidateStructure


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


def _validate(xs_or_ses, **params):
    ses = xs_or_ses if isinstance(xs_or_ses, SolveSession) else _session(xs_or_ses)
    return ValidateStructure().run(ToolContext(store=_Store(), session=ses), **params)


def _codes(alerts):
    return {a["code"] for a in alerts}


def _labels(rows):
    return [r["label"] for r in rows]


# ------------------------------------------------------------ fixtures ----

def _cp_ring(centre, m_c=2.50, labels=("C1", "C2", "C3", "C4", "C5")):
    """Regular C5 ring (C-C 1.42 A) with every atom m_c from `centre`,
    stacked above it; a label starting with N makes that member an N."""
    r = 1.42 / (2 * math.sin(math.radians(36)))
    h = math.sqrt(m_c ** 2 - r ** 2)
    out = []
    for k, lb in enumerate(labels):
        a = math.radians(72 * k)
        out.append((lb, "N" if lb.startswith("N") else "C",
                    (centre[0] + r * math.cos(a), centre[1] + r * math.sin(a),
                     centre[2] + h)))
    return out


def _five_o(centre, m_o=2.15, prefix="O", n0=1):
    out = []
    for k in range(5):
        a = math.radians(72 * k + 36)
        out.append((f"{prefix}{n0 + k}", "O",
                    (centre[0] + 1.6 * math.cos(a), centre[1] + 1.6 * math.sin(a),
                     centre[2] - math.sqrt(m_o ** 2 - 1.6 ** 2))))
    return out


def _cp_zr_o5(zr=(10.0, 10.0, 10.0), **ring_kw):
    """CpZr(O)5: the pa1/pa2 cage node motif."""
    return [("ZR1", "Zr", zr)] + _cp_ring(zr, **ring_kw) + _five_o(zr)


def _m3_mu3(metal="Zr", mu_label="C1", mu_el="C", m_m=3.5, m_x=2.1, m_o=2.2):
    """Three metals in a triangle, one mu3 atom above the centroid at m_x
    from each, four O donors per metal placed AWAY from the mu3 site."""
    r_c = m_m / math.sqrt(3)
    ms = [(10.0 + r_c * math.cos(math.radians(90 + 120 * k)),
           10.0 + r_c * math.sin(math.radians(90 + 120 * k)), 10.0) for k in range(3)]
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


def _zr_with_four_o(zr=(5.0, 5.0, 5.0), n0=20):
    atoms = [("ZR1", "Zr", zr)]
    for k in range(4):
        a = math.radians(90 * k + 45)
        atoms.append((f"O{n0 + k}", "O",
                      (zr[0] - 0.8, zr[1] + 2.05 * math.cos(a), zr[2] + 2.05 * math.sin(a))))
    return atoms


def _benzoate_on_zr(o_label="O", o_el="O"):
    """Zr-O 2.20 to a carboxylate whose second O and ipso carbon complete
    the trigonal carbon; the ring carries two more C. `o_label`/`o_el`
    relabel the bound O (the pa2 mislabel)."""
    o1 = (7.2, 5.0, 5.0)
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


def _cu_paddlewheel(relabel=None):
    """Cu2(O2CR)4(H2O)2: Cu-Cu 2.65, Cu-O 1.97, axial water 2.15."""
    relabel = relabel or {}
    atoms = [("CU1", "Cu", (10.0, 10.0, 11.325)), ("CU2", "Cu", (10.0, 10.0, 8.675))]
    rho = math.sqrt(1.97 ** 2 - 0.215 ** 2)
    for k in range(4):
        a = math.radians(90 * k)
        ox, oy = 10 + rho * math.cos(a), 10 + rho * math.sin(a)
        atoms += [(f"O{2 * k + 1}", "O", (ox, oy, 11.11)),
                  (f"O{2 * k + 2}", "O", (ox, oy, 8.89))]
        cx, cy = 10 + (rho + 0.59) * math.cos(a), 10 + (rho + 0.59) * math.sin(a)
        atoms += [(f"C{3 * k + 1}", "C", (cx, cy, 10.0)),
                  (f"C{3 * k + 2}", "C", (10 + (rho + 2.09) * math.cos(a),
                                           10 + (rho + 2.09) * math.sin(a), 10.0)),
                  (f"C{3 * k + 3}", "C", (10 + (rho + 2.09) * math.cos(a)
                                           + 0.7 * math.cos(a + math.pi / 2),
                                           10 + (rho + 2.09) * math.sin(a)
                                           + 0.7 * math.sin(a + math.pi / 2), 11.2))]
    atoms += [("O1W", "O", (10.0, 10.0, 13.475)), ("O2W", "O", (10.0, 10.0, 6.525))]
    return [(relabel.get(lb, (lb, el))[0], relabel.get(lb, (lb, el))[1], c)
            for lb, el, c in atoms]


def _flat_ring(n, bond, centre, labels):
    r = bond / (2 * math.sin(math.pi / n))
    return [(lb, "N" if lb.startswith("N") else "C",
             (centre[0] + r * math.cos(2 * math.pi * k / n),
              centre[1] + r * math.sin(2 * math.pi * k / n), centre[2]))
            for k, lb in enumerate(labels)]


# ------------------------------------------------------- rule 1: elements ----

class TestSuspectElements:
    def test_mu3_o_labelled_c_on_a_zr3_node(self):
        # (a) the pa2 case: a "C" at 2.1 A from three Zr with no skeleton
        r = audit_metal_bonded_light_atoms(_structure(_m3_mu3()))
        assert _labels(r["suspect_elements"]) == ["C1"]
        s = r["suspect_elements"][0]
        assert s["severity"] == "high" and s["n_metals"] == 3
        assert s["element"] == "C" and s["n_skeleton_neighbours"] == 0
        assert s["candidates"][0].startswith("O")
        assert "mu-O/OH" in s["suggestion"] and "omit-map" in s["suggestion"]
        assert "carbon skeleton" in s["suggestion"] or "not organic" in s["suggestion"]
        # it IS a donor (an O by geometry): counted in every Zr's CN
        for env in r["metal_environments"]:
            assert env["donors"] == {"C": 1, "O": 4}
            assert "C1" in env["suspect_donors"]
        assert "C1" in r["summary"]

    def test_mu3_o_labelled_n_on_a_mn3_cluster(self):
        # non-Zr: Mn3(mu3-O) carboxylate cluster with the O read as N
        r = audit_metal_bonded_light_atoms(_structure(
            _m3_mu3(metal="Mn", mu_label="N1", mu_el="N", m_m=3.3, m_x=1.9, m_o=2.1)))
        assert _labels(r["suspect_elements"]) == ["N1"]
        s = r["suspect_elements"][0]
        assert s["severity"] == "high" and s["metal_element"] == "Mn"
        assert "carbon skeleton" in s["suggestion"]
        # candidates follow the metal class, not a fixed "O"
        assert s["candidates"] == list(donor_candidates("Mn"))
        assert donor_candidates("Zr")[0].startswith("O")
        assert donor_candidates("Ag")[0].startswith("S")
        assert donor_candidates("Cu")[1].startswith("N")

    def test_carboxylate_o_under_a_c_or_n_label(self):
        # (d) the real benzoate: nothing to say, carboxylate C never a donor
        clean = audit_metal_bonded_light_atoms(_structure(_benzoate_on_zr()))
        assert clean["suspect_elements"] == [] and clean["suspect_bonds"] == []
        env = clean["metal_environments"][0]
        assert env["donors"] == {"O": 5} and env["cn_atoms"] == 5
        for lb, el in (("C", "C"), ("N", "N")):
            r = audit_metal_bonded_light_atoms(_structure(_benzoate_on_zr(lb, el)))
            assert _labels(r["suspect_elements"]) == [f"{lb}1"], lb
            s = r["suspect_elements"][0]
            assert s["severity"] == "high" and s["kind"] == "carboxylate_o"
            assert "carboxylate" in s["reason"] and "retype as O" in s["suggestion"]
            # the element verdict carries the fix: no second flag on the
            # 1.26 A "C-C"
            assert r["suspect_bonds"] == []

    def test_cu_paddlewheel_clean_and_mislabelled(self):
        clean = audit_metal_bonded_light_atoms(_structure(_cu_paddlewheel()))
        assert clean["suspect_elements"] == []
        for env in clean["metal_environments"]:
            assert env["cn_sites"] == 5 and env["donors"] == {"O": 5}
            assert env["cn_plausible"]
        r = audit_metal_bonded_light_atoms(_structure(_cu_paddlewheel(
            {"O1": ("N1", "N"), "O1W": ("C1W", "C")})))
        by = {s["label"]: s for s in r["suspect_elements"]}
        assert set(by) == {"N1", "C1W"}
        assert by["N1"]["kind"] == "carboxylate_o" and by["N1"]["severity"] == "high"
        # a lone C on ONE metal: aqua O vs a terminal alkyl cannot be told
        # apart by geometry - medium, with both readings named
        assert by["C1W"]["severity"] == "medium"
        assert "M-CH3" in by["C1W"]["suggestion"]
        assert "Cl-" in by["C1W"]["suggestion"]

    def test_compressed_ueq_promotes_and_names_the_heavier_candidate(self):
        atoms = _zr_with_four_o() + [("C1", "C", (7.15, 5.0, 5.0), 0.008)]
        r = audit_metal_bonded_light_atoms(_structure(atoms))
        s = r["suspect_elements"][0]
        assert s["label"] == "C1" and s["severity"] == "high"
        assert s["ueq_over_metal_light_neighbours"] < 0.6
        assert s["suggestion"].startswith("Ueq is")
        assert "Cl-/Br-" in s["suggestion"]

    def test_lone_o_in_the_halide_range_with_collapsed_ueq(self):
        # rule 1d: beyond the M-O window, inside M-Cl, Ueq collapsed
        atoms = _zr_with_four_o() + [("O1", "O", (7.55, 5.0, 5.0), 0.008)]
        r = audit_metal_bonded_light_atoms(_structure(atoms))
        s = r["suspect_elements"][0]
        assert s["label"] == "O1" and s["kind"] == "lone_halide_candidate"
        assert s["severity"] == "medium" and "integrate_difference_density" in s["suggestion"]
        assert any(n.startswith("O1(halide?)") for n in r["metal_environments"][0]["neighbours"])
        # the same atom with a normal Ueq is just a long contact
        normal = audit_metal_bonded_light_atoms(_structure(
            _zr_with_four_o() + [("O1", "O", (7.55, 5.0, 5.0), 0.03)]))
        assert normal["suspect_elements"] == []
        assert normal["metal_environments"][0]["cn_atoms"] == 4


class TestTrueMetalCarbonBonds:
    """Real organometallic chemistry must not be reported as mislabels."""

    def test_zr_alkyl(self):
        zr = (5.0, 5.0, 5.0)
        atoms = _zr_with_four_o() + [
            ("C1", "C", (7.28, 5.0, 5.0)),
            ("C2", "C", (7.28 + 1.53 * math.cos(math.radians(65)),
                         5.0 + 1.53 * math.sin(math.radians(65)), 5.0))]
        r = audit_metal_bonded_light_atoms(_structure(atoms))
        assert r["suspect_elements"] == []
        pm = r["plausible_metal_bonds"]
        assert [p["label"] for p in pm] == ["C1"] and "sigma-alkyl" in pm[0]["kind"]
        assert r["metal_environments"][0]["donors"] == {"O": 4, "C": 1}
        assert zr == (5.0, 5.0, 5.0)

    def test_cu_alkynyl_and_fe_carbonyl(self):
        cu = (5.0, 5.0, 5.0)
        atoms = [("CU1", "Cu", cu), ("C1", "C", (6.90, 5.0, 5.0)),
                 ("C2", "C", (8.10, 5.0, 5.0)), ("C3", "C", (9.54, 5.0, 5.0)),
                 ("C4", "C", (10.235, 6.2, 5.0)), ("C5", "C", (10.235, 3.8, 5.0)),
                 ("N1", "N", (3.0, 5.0, 5.0)), ("C6", "C", (2.3, 6.2, 5.0)),
                 ("C7", "C", (2.3, 3.8, 5.0))]
        r = audit_metal_bonded_light_atoms(_structure(atoms))
        assert r["suspect_elements"] == [] and r["suspect_bonds"] == []
        assert any(p["label"] == "C1" and "alkynyl" in p["kind"]
                   for p in r["plausible_metal_bonds"])
        fe = (5.0, 5.0, 5.0)
        atoms = [("FE1", "Fe", fe)]
        for k, (dx, dy, dz) in enumerate(((1, 0, 0), (-1, 0, 0), (0, 1, 0),
                                          (0, -1, 0), (0, 0, 1))):
            atoms += [(f"C{k + 1}", "C", (fe[0] + 1.80 * dx, fe[1] + 1.80 * dy, fe[2] + 1.80 * dz)),
                      (f"O{k + 1}", "O", (fe[0] + 2.94 * dx, fe[1] + 2.94 * dy, fe[2] + 2.94 * dz))]
        r = audit_metal_bonded_light_atoms(_structure(atoms))
        assert r["suspect_elements"] == []
        assert sorted(p["label"] for p in r["plausible_metal_bonds"]) == [f"C{k}" for k in range(1, 6)]
        assert all("carbonyl" in p["kind"] for p in r["plausible_metal_bonds"])
        env = r["metal_environments"][0]
        assert env["cn_sites"] == 5 and env["cn_plausible"]

    def test_cu_nitrile_carbene_ammine(self):
        cu = (5.0, 5.0, 5.0)
        atoms = [("CU1", "Cu", cu),
                 ("N1", "N", (6.95, 5, 5)), ("C1", "C", (8.09, 5, 5)), ("C2", "C", (9.55, 5, 5)),
                 ("C10", "C", (3.10, 5, 5)), ("N2", "N", (2.5, 6.2, 5)), ("N3", "N", (2.5, 3.8, 5)),
                 ("C11", "C", (1.1, 5.7, 5)), ("C12", "C", (1.1, 4.3, 5)),
                 ("N4", "N", (5, 7.0, 5))]
        r = audit_metal_bonded_light_atoms(_structure(atoms))
        kinds = {p["label"]: p["kind"] for p in r["plausible_metal_bonds"]}
        assert "nitrile" in kinds["N1"] and "carbene" in kinds["C10"]
        # NH3 vs H2O is a genuine ambiguity: medium, never high
        assert _labels(r["suspect_elements"]) == ["N4"]
        assert r["suspect_elements"][0]["severity"] == "medium"
        assert "ammine" in r["suspect_elements"][0]["suggestion"]


# ----------------------------------------------------------- pi ligands ----

class TestPiLigands:
    def test_eta5_cp_is_one_ligand_not_five_suspects(self):
        # (b)
        r = audit_metal_bonded_light_atoms(_structure(_cp_zr_o5()))
        assert r["suspect_elements"] == []
        assert len(r["pi_ligands"]) == 1
        ring = r["pi_ligands"][0]
        assert ring["hapticity"] == 5 and ring["ring_closed"]
        assert set(ring["ring_labels"]) == {"C1", "C2", "C3", "C4", "C5"}
        assert 2.4 <= ring["mean_M_C"] <= 2.6
        env = r["metal_environments"][0]
        assert (env["cn_atoms"], env["cn_ligands"], env["cn_sites"]) == (10, 6, 8)
        assert env["donors"] == {"O": 5, "pi": 1} and env["cn_plausible"]

    def test_ferrocene_any_metal_any_ring(self):
        fe = (10.0, 10.0, 10.0)
        top = _cp_ring(fe, m_c=2.05)
        bottom = [(lb + "B", el, (x, y, 2 * fe[2] - z)) for lb, el, (x, y, z) in top]
        r = audit_metal_bonded_light_atoms(_structure([("FE1", "Fe", fe)] + top + bottom))
        assert len(r["pi_ligands"]) == 2 and r["suspect_elements"] == []
        env = r["metal_environments"][0]
        assert env["cn_ligands"] == 2 and env["cn_sites"] == 6 and env["cn_plausible"]
        # eta6-arene on Cr: a six-ring at 2.14 A
        cr = (10.0, 10.0, 10.0)
        r6 = 1.39
        h = math.sqrt(2.14 ** 2 - r6 ** 2)
        arene = [(f"C{k + 1}", "C", (cr[0] + r6 * math.cos(math.radians(60 * k)),
                                     cr[1] + r6 * math.sin(math.radians(60 * k)), cr[2] + h))
                 for k in range(6)]
        r = audit_metal_bonded_light_atoms(_structure([("CR1", "Cr", cr)] + arene))
        assert r["pi_ligands"][0]["hapticity"] == 6 and r["pi_ligands"][0]["ring_closed"]

    def test_broken_cp_is_an_open_pi_fragment_not_four_suspects(self):
        # pa2 cage-l0-r1: [C22, C35, C40, C46] "unrecognised C4 fragment"
        r = audit_metal_bonded_light_atoms(_structure(
            [("ZR1", "Zr", (10.0, 10.0, 10.0))] + _cp_ring((10.0, 10.0, 10.0))[:4]
            + _five_o((10.0, 10.0, 10.0))))
        assert r["suspect_elements"] == []
        frag = r["pi_ligands"][0]
        assert frag["hapticity"] == 4 and not frag["ring_closed"]
        assert "missing atoms" in frag["note"]
        assert r["metal_environments"][0]["cn_ligands"] == 6

    def test_cp_carbons_labelled_n(self):
        r = audit_metal_bonded_light_atoms(_structure(
            _cp_zr_o5(labels=("N1", "N2", "C3", "C4", "C5"))))
        assert r["pi_ligands"][0]["n_members_labelled_N"] == ["N1", "N2"]
        by = {s["label"]: s for s in r["suspect_elements"]}
        assert set(by) == {"N1", "N2"}
        assert all(s["severity"] == "high" and s["kind"] == "n_in_pi_ring"
                   for s in by.values())
        assert "retype as C" in by["N1"]["suggestion"]
        nn = r["suspect_bonds"]
        assert len(nn) == 1 and {nn[0]["a"], nn[0]["b"]} == {"N1", "N2"}
        assert nn[0]["severity"] == "high" and "face-on" in nn[0]["reason"]

    def test_ring_closing_through_a_mirror_plane(self):
        # symmetry-aware: Zr on the mirror of P m, three ASU ring carbons
        # and three ASU oxygens complete the eta5-Cp and the O5 set
        zr = (10.0, 0.0, 10.0)
        r_ring = 1.42 / (2 * math.sin(math.radians(36)))
        h = math.sqrt(2.5 ** 2 - r_ring ** 2)
        atoms = [("ZR1", "Zr", zr)]
        for lb, ang in (("C1", 0), ("C2", 72), ("C4", 144)):
            atoms.append((lb, "C", (zr[0] + r_ring * math.cos(math.radians(ang)),
                                    r_ring * math.sin(math.radians(ang)), zr[2] + h)))
        h_o = math.sqrt(2.15 ** 2 - 1.6 ** 2)
        for lb, ang in (("O1", 180), ("O2", 36), ("O3", 108)):
            atoms.append((lb, "O", (zr[0] + 1.6 * math.cos(math.radians(ang)),
                                    1.6 * math.sin(math.radians(ang)), zr[2] - h_o)))
        xs = _structure(atoms, cell=(20, 20, 20, 90, 90, 90), sg="P m")
        assert xs.scatterers().size() == 7
        r = audit_metal_bonded_light_atoms(xs)
        ring = r["pi_ligands"][0]
        assert ring["hapticity"] == 5 and ring["n_symmetry_images"] == 2
        assert sorted(ring["ring_labels"]) == ["C1", "C2", "C2", "C4", "C4"]
        env = r["metal_environments"][0]
        assert env["cn_atoms"] == 10 and env["cn_sites"] == 8 and env["cn_plausible"]
        assert r["suspect_elements"] == []


# --------------------------------------------------------- rule 2: bonds ----

class TestSuspectBonds:
    def test_nn_ladder(self):
        # (c) tetrazole: exempt
        tet = _flat_ring(5, 1.36, (5, 5, 5), ["C1", "N1", "N2", "N3", "N4"]) \
            + [("C2", "C", (5 + 1.157 + 1.47, 5, 5))]
        assert audit_metal_bonded_light_atoms(_structure(tet))["suspect_bonds"] == []
        # azide: exempt; dinitrogen: exempt
        az = [("C1", "C", (5, 5, 5)), ("N1", "N", (6.47, 5, 5)),
              ("N2", "N", (7.65, 5, 5)), ("N3", "N", (8.80, 5, 5))]
        assert audit_metal_bonded_light_atoms(_structure(az))["suspect_bonds"] == []
        n2 = [("N1", "N", (5, 5, 5)), ("N2", "N", (6.10, 5, 5))]
        assert audit_metal_bonded_light_atoms(_structure(n2))["suspect_bonds"] == []
        # chain N-N 1.45 A where one N carries a skeleton: high
        chain = [("C1", "C", (5, 5, 5)), ("N1", "N", (6.45, 5, 5)),
                 ("C2", "C", (7.15, 3.75, 5)), ("N2", "N", (7.15, 6.3, 5)),
                 ("C3", "C", (8.45, 7.0, 5)), ("C4", "C", (9.85, 7.5, 5))]
        r = audit_metal_bonded_light_atoms(_structure(chain))
        assert len(r["suspect_bonds"]) == 1
        b = r["suspect_bonds"][0]
        assert {b["a"], b["b"]} == {"N1", "N2"} and b["severity"] == "high"
        assert "mislabelled C-C / C-N" in b["suggestion"]
        # six-ring N-N (pyridazine or a benzene wearing two N): medium
        pyd = _flat_ring(6, 1.39, (5, 5, 5), ["N1", "N2", "C1", "C2", "C3", "C4"])
        r = audit_metal_bonded_light_atoms(_structure(pyd))
        assert r["suspect_bonds"][0]["severity"] == "medium"
        assert "six-membered" in r["suspect_bonds"][0]["reason"]
        # N-N 1.60 A: nothing real at that length
        long = [("C1", "C", (5, 5, 5)), ("N1", "N", (6.45, 5, 5)),
                ("N2", "N", (8.05, 5, 5)), ("C2", "C", (9.5, 5, 5))]
        assert audit_metal_bonded_light_atoms(_structure(long))["suspect_bonds"][0]["severity"] == "high"

    def test_parts_never_see_each_other(self):
        atoms = [("C1", "C", (5, 5, 5)), ("N1", "N", (6.4, 5, 5)),
                 ("N2", "N", (7.3, 5.9, 5)), ("C2", "C", (7.4, 7.3, 5)),
                 ("C3", "C", (8.8, 7.8, 5))]
        assert audit_metal_bonded_light_atoms(_structure(atoms))["suspect_bonds"]
        assert audit_metal_bonded_light_atoms(
            _structure(atoms), parts={"n1": 1, "N2": 2})["suspect_bonds"] == []

    def test_carbonyl_length_cc_vs_alkyne(self):
        ket = [("C1", "C", (5, 5, 5)), ("C2", "C", (6.5, 5, 5)),
               ("C3", "C", (7.25, 6.3, 5)), ("C9", "C", (7.12, 3.93, 5))]
        r = audit_metal_bonded_light_atoms(_structure(ket))
        assert len(r["suspect_bonds"]) == 1
        b = r["suspect_bonds"][0]
        assert b["kind"] == "C-C" and b["severity"] == "medium"
        assert "carbonyl" in b["reason"] and "C9" in (b["a"], b["b"])
        alk = [("C1", "C", (5, 5, 5)), ("C2", "C", (6.46, 5, 5)),
               ("C3", "C", (7.66, 5, 5)), ("C4", "C", (9.12, 5, 5))]
        assert audit_metal_bonded_light_atoms(_structure(alk))["suspect_bonds"] == []


# ------------------------------------------------------ validate_structure ----

class TestValidateStructure:
    def test_alert_codes_and_advice(self):
        r = _validate(_structure(_m3_mu3()))
        assert r.ok, r.error
        alerts = [a for a in r.summary["alerts"] if a["code"] == "metal_bonded_light_atom"]
        assert len(alerts) == 1 and alerts[0]["severity"] == "critical"
        msg = alerts[0]["message"]
        assert msg.startswith("C1 (C) 2.10 A from ZR")
        assert "do NOT hide it behind add_hydrogens exclude" in msg
        assert "edit_atoms reassign" in msg
        mba = r.summary["metal_bonded_audit"]
        assert mba["n_suspect_elements"] == 1 and "SHELXT" in mba["note"]
        assert mba["suspect_elements"][0]["label"] == "C1"

    def test_suspect_bond_alerts(self):
        chain = [("ZN1", "Zn", (2.0, 2.0, 2.0)), ("O1", "O", (4.0, 2.0, 2.0)),
                 ("C1", "C", (12, 5, 5)), ("N1", "N", (13.45, 5, 5)),
                 ("C2", "C", (14.15, 3.75, 5)), ("N2", "N", (14.15, 6.3, 5)),
                 ("C3", "C", (15.45, 7.0, 5)), ("C4", "C", (16.85, 7.5, 5))]
        codes = _codes(_validate(_structure(chain)).summary["alerts"])
        assert "suspect_nn_bond" in codes
        ket = [("C1", "C", (5, 5, 5)), ("C2", "C", (6.5, 5, 5)),
               ("C3", "C", (7.25, 6.3, 5)), ("C9", "C", (7.12, 3.93, 5))]
        assert "suspect_cc_bond" in _codes(_validate(_structure(ket)).summary["alerts"])

    def test_cp_complex_one_pi_alert_and_no_suspects(self):
        r = _validate(_structure(_cp_zr_o5()))
        codes = _codes(r.summary["alerts"])
        assert "metal_bonded_light_atom" not in codes and "metal_cn" not in codes
        assert sum(1 for a in r.summary["alerts"] if a["code"] == "pi_ligand") == 1
        # a broken Cp adds the audit's open-fragment alert, once
        r2 = _validate(_structure([("ZR1", "Zr", (10.0, 10.0, 10.0))]
                                  + _cp_ring((10.0, 10.0, 10.0))[:4]
                                  + _five_o((10.0, 10.0, 10.0))))
        pi = [a for a in r2.summary["alerts"] if a["code"] == "pi_ligand"]
        assert len(pi) == 1 and "open fragment" in pi[0]["message"]
        assert "metal_bonded_light_atom" not in _codes(r2.summary["alerts"])

    def test_hydrogens_never_count_in_the_metal_cn(self):
        # (e) pa2 hex-l0-r1: O-H hydrogens at 2.6 A made Zr2 "CN=11"
        zr = (10.0, 10.0, 10.0)
        atoms = _cp_zr_o5(zr)
        for lb, el, (x, y, z) in _five_o(zr):
            v = (x - zr[0], y - zr[1], z - zr[2])
            n = math.sqrt(sum(c * c for c in v))
            atoms.append(("H" + lb[1:], "H", (x + 0.85 * v[0] / n, y + 0.85 * v[1] / n,
                                              z + 0.85 * v[2] / n)))
        r = _validate(_structure(atoms))
        assert "metal_cn" not in _codes(r.summary["alerts"])
        env = r.summary["metal_bonded_audit"]["metal_environments"][0]
        assert env["cn_atoms"] == 10 and env["cn_sites"] == 8
        assert not any(n.startswith("H") for n in env["neighbours"])
        assert env["h_excluded"] is True
        # and a genuinely under-coordinated metal still says so, in sites
        low = _validate(_structure(_zr_with_four_o()))
        cn = next(a for a in low.summary["alerts"] if a["code"] == "metal_cn")
        assert "CN=4" in cn["message"] and "H never counted" in cn["message"]

    def test_mark_adjudicated_matches_labels_case_insensitively(self):
        # (e) pa2 hex-l0-r1: SHELXL adopt upper-cased the labels and the
        # 'Zr2' adjudication stopped matching
        ses = _session(_structure(_m3_mu3()))
        t = ValidateStructure()
        base = t.run(ToolContext(store=_Store(), session=ses))
        assert "metal_bonded_light_atom" in _codes(base.summary["alerts"])
        r = t.run(ToolContext(store=_Store(), session=ses), mark_adjudicated=[{
            "code": "metal_bonded_light_atom", "subject": "c1",
            "reason": "omit map integrates to 8 e: retyped as O and re-refined"}])
        assert "metal_bonded_light_atom" not in _codes(r.summary["alerts"])
        assert "metal_bonded_light_atom" in _codes(r.summary["adjudicated"])
        # removal with a differently-cased subject hits the same record
        r2 = t.run(ToolContext(store=_Store(), session=ses), mark_adjudicated=[{
            "code": "metal_bonded_light_atom", "subject": "C1", "reason": None}])
        assert "metal_bonded_light_atom" in _codes(r2.summary["alerts"])
        assert ses.validation["metal_bonded_audit"]["suspect_elements"][0]["label"] == "C1"


# ------------------------------------------------- audit_element_assignment ----

def test_audit_element_assignment_carries_the_same_audit():
    from types import SimpleNamespace

    from crystalpilot.refine.tools_chemaudit import AuditElementAssignment
    ses = _session(_structure(_m3_mu3()))
    tool = AuditElementAssignment(SimpleNamespace(session=ses))
    r = tool.run(ToolContext(store=_Store(), session=ses), elements=["C"])
    assert r.ok, r.error
    mba = r.summary["metal_bonded_audit"]
    assert mba["n_suspect_elements"] == 1 and mba["n_high"] == 1
    assert mba["suspect_elements"][0]["label"] == "C1"
    assert "SHELXT 组成串不是证据" in mba["note"]
    assert "SHELXT" in r.summary["caveat"] and "exclude" in r.summary["caveat"]
    row = next(a for a in r.summary["atoms"] if a["label"] == "C1")
    assert row["metal_bonded_verdict"].startswith("[high]")


# ------------------------------------------------------------- grade.py ----

class TestGradeChemistryFlags:
    def test_eta5_ring_is_not_cn_5(self):
        # (f)
        ch = G.chemistry_flags(_structure(_cp_zr_o5()))
        assert not any("CN=" in f for f in ch["flags"])
        row = next(m for m in ch["metal_coordination"] if m["atom"] == "ZR1")
        assert (row["cn"], row["cn_ligands"], row["cn_atoms"]) == (8, 6, 10)
        assert row["donors"] == {"O": 5, "pi": 1}
        mb = ch["metal_bonded_light_atoms"]
        assert mb["n"] == 0 and mb["n_pi_ligands"] == 1
        assert mb["pi_ligands"][0].startswith("eta5-5 [")
        # ferrocene: six sites, inside the Fe window - no flag
        fe = (10.0, 10.0, 10.0)
        top = _cp_ring(fe, m_c=2.05)
        bottom = [(lb + "B", el, (x, y, 2 * fe[2] - z)) for lb, el, (x, y, z) in top]
        ch = G.chemistry_flags(_structure([("FE1", "Fe", fe)] + top + bottom))
        assert not any(f.startswith("FE1") for f in ch["flags"])
        assert ch["metal_coordination"][0]["cn"] == 6

    def test_metal_bonded_light_atoms_flag(self):
        ch = G.chemistry_flags(_structure(_m3_mu3()))
        flag = next(f for f in ch["flags"] if f.startswith("metal_bonded_light_atoms"))
        assert "1 (1 high)" in flag and "C1 (C) 2.10 A from ZR" in flag
        mb = ch["metal_bonded_light_atoms"]
        assert mb["n_high"] == 1 and mb["atoms"][0]["label"] == "C1"
        # medium-only findings are notes, never blocking flags
        ch2 = G.chemistry_flags(_structure(_cu_paddlewheel({"O1W": ("C1W", "C")})))
        assert not any(f.startswith("metal_bonded_light_atoms") for f in ch2["flags"])
        assert any(n.startswith("metal_bonded_light_atoms") for n in ch2["notes"])
        # a high-severity N-N bond is a flag too
        chain = [("C1", "C", (5, 5, 5)), ("N1", "N", (6.45, 5, 5)),
                 ("C2", "C", (7.15, 3.75, 5)), ("N2", "N", (7.15, 6.3, 5)),
                 ("C3", "C", (8.45, 7.0, 5)), ("C4", "C", (9.85, 7.5, 5))]
        ch3 = G.chemistry_flags(_structure(chain))
        assert any(f.startswith("suspect_bonds") and "N1-N2" in f for f in ch3["flags"])
