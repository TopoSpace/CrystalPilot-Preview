"""`chem/bonding.py`: one engine, one post-processor, one classified edge set.

Same four synthetic fixtures as `test_bonding_status_quo.py` (imported from
there so the two files cannot drift apart): a Cu carboxylate chain with a
chelating carboxylate, a centrosymmetric organic molecule with riding H and a
PART 1 / PART 2 pair, a NaCl-type lattice, and an organometallic box with
eta5-Cp rings, a Zr-CH3 sigma bond, an unlisted metal (Os) and the two false
metal-carbon bonds `refine.nodes.prune_long_metal_contacts` records in its
docstring.

What is being pinned here is the KIND of every metal-incident edge, not just
its existence: `covalent` / `coordination` / `eta` / `metal_metal` /
`non_bonded_close`, each carrying the rule that decided it.
"""
from __future__ import annotations

import math

from cctbx import sgtbx

from crystalpilot.chem.bonding import (KIND_CODE, TOL_COVALENT, BondEdge,
                                       bond_table, is_metal_element)
from crystalpilot.chem.knowledge import cn_status
from test_bonding_status_quo import (ORGANIC_PARTS, _structure, ionic_salt,
                                     mof_chain, organic_p_1, organometallic)


def kinds(xs, parts=None, include_non_bonded=True):
    """{(label_a, label_b, round(d, 2)): kind} - the same normalisation the
    status-quo photograph uses, plus the kind."""
    t = bond_table(xs, parts, include_non_bonded=include_non_bonded)
    out: dict[tuple[str, str, float], str] = {}
    for e in t.edges:
        a, b = t.labels[e.i], t.labels[e.j]
        key = (min(a, b), max(a, b), round(e.d, 2))
        assert out.get(key, e.kind) == e.kind, f"{key} got two kinds"
        out[key] = e.kind
    return out


def basis_of(t, label_a, label_b):
    for e in t.edges:
        if {t.labels[e.i], t.labels[e.j]} == {label_a, label_b}:
            return e.basis
    return None


# ------------------------------------------------------------ (i) MOF chain --

class TestMofChain:
    def test_kinds(self):
        assert kinds(mof_chain()) == {
            # the carboxylate skeleton
            ("C1", "O1", 1.25): "covalent",
            ("C1", "O2", 1.25): "covalent",
            ("C2", "O3", 1.25): "covalent",
            ("C2", "O4", 1.25): "covalent",
            ("C2", "C3", 1.52): "covalent",
            # every Cu-O is dative, inside the MetalProfile Cu-O window
            # (1.85-2.60): a bridging pair, and the asymmetric chelate
            ("CU1", "O1", 1.95): "coordination",
            ("CU1", "O2", 1.95): "coordination",
            ("CU1", "O3", 1.98): "coordination",
            ("CU1", "O4", 2.41): "coordination",
            # the chelating carboxylate carbon: reportable, never a bond
            ("C2", "CU1", 2.50): "non_bonded_close",
        }

    def test_chelating_metal_cn_counts_oxygen_only(self):
        t = bond_table(mof_chain(), include_non_bonded=True)
        cu = t.labels.index("CU1")
        assert t.cn(cu) == 4
        neighbours = sorted(t.labels[e.j] for e in t.by_atom(cu)
                            if e.kind != "non_bonded_close")
        assert neighbours == ["O1", "O2", "O3", "O4"]
        assert t.is_metal(cu) and not t.is_metal(t.labels.index("O1"))
        assert "chelate bite Cu-O-C" in basis_of(t, "CU1", "C2")

    def test_non_bonded_close_is_hidden_by_default_but_counted(self):
        t = bond_table(mof_chain())          # include_non_bonded=False
        assert all(e.kind != "non_bonded_close" for e in t.edges)
        s = t.summary()
        assert s["kinds"]["non_bonded_close"] == 0
        assert s["n_non_bonded_close_hidden"] == 2   # both orientations
        assert s["n_metals"] == 1 and s["parts_applied"] is False
        # cn is the same whether or not the kind is materialised
        assert t.cn(t.labels.index("CU1")) == 4


# --------------------------------------------------------- (ii) organic P-1 --

class TestOrganicCentrosymmetric:
    def test_kinds_and_no_metal(self):
        got = kinds(organic_p_1(), ORGANIC_PARTS)
        assert set(got.values()) == {"covalent"}
        assert ("C1", "C1", 1.54) in got            # through the inversion
        assert len(got) == 13

    def test_zero_edges_between_part_1_and_part_2(self):
        t = bond_table(organic_p_1(), ORGANIC_PARTS, include_non_bonded=True)
        a, b = t.labels.index("C7A"), t.labels.index("C7B")
        assert [e for e in t.edges if {e.i, e.j} == {a, b}] == []
        # both alternatives still bond their common pivot
        assert {t.labels[e.j] for e in t.by_atom(a)} == {"C4"}
        assert {t.labels[e.j] for e in t.by_atom(b)} == {"C4"}
        assert t.summary()["parts_applied"] is True
        # without the PART numbers the same 1.00 A pair IS an edge - the
        # difference is the engine's conformer_indices, not a distance rule
        t0 = bond_table(organic_p_1(), include_non_bonded=True)
        assert [e.kind for e in t0.edges if {e.i, e.j} == {a, b}] == [
            "covalent", "covalent"]

    def test_symmetry_image_edge_carries_its_operator(self):
        xs = organic_p_1()
        uc = xs.unit_cell()
        scs = list(xs.scatterers())
        t = bond_table(xs, ORGANIC_PARTS)
        sym = [e for e in t.edges if e.is_symmetry_image]
        # one entry, not two: C1 bonds its OWN image, and an inversion is its
        # own inverse, so the pair table lists the self-pair once
        assert len(sym) == 1
        for e in sym:
            assert t.labels[e.i] == t.labels[e.j] == "C1"
            assert e.op == "-x,-y,-z"
            d = uc.distance(scs[e.i].site, sgtbx.rt_mx(e.op) * scs[e.j].site)
            assert abs(e.d - d) < 1e-6
        # every other edge is a direct one and says so
        assert {e.op for e in t.edges if not e.is_symmetry_image} == {"x,y,z"}


# ----------------------------------------------------------- (iii) NaCl-type --

class TestIonicSalt:
    def test_rock_salt_is_coordination_not_covalent(self):
        t = bond_table(ionic_salt())
        assert kinds(ionic_salt()) == {("CL1", "NA1", 2.85): "coordination"}
        # 6 images from Na + 6 from Cl: both endpoints see CN 6
        assert len(t.edges) == 12
        assert t.cn(t.labels.index("NA1")) == 6
        assert t.cn(t.labels.index("CL1")) == 6
        assert t.is_metal(t.labels.index("NA1"))
        assert not t.is_metal(t.labels.index("CL1"))
        # Na has no MetalProfile, so the window is the documented fallback
        assert "unlisted metal Na" in basis_of(t, "NA1", "CL1")

    def test_no_covalent_edge_anywhere(self):
        t = bond_table(ionic_salt())
        assert t.summary()["kinds"] == {
            "covalent": 0, "coordination": 12, "eta": 0, "metal_metal": 0,
            "non_bonded_close": 0}


# ------------------------------------------------------ (iv) organometallic --

class TestOrganometallic:
    def test_metal_edge_kinds(self):
        xs = organometallic()
        got = {k: v for k, v in kinds(xs).items()
               if any(lb in ("FE1", "ZR1", "OS1", "LA1") for lb in k[:2])}
        assert got == {
            # ferrocene: ten Fe-C at 2.05 A, all of them eta ring members
            **{(f"C{k}", "FE1", 2.05): "eta" for k in range(1, 11)},
            # OsCl4: Os has no MetalProfile -> the unlisted-metal window
            **{(f"CL{k}", "OS1", 2.30): "coordination" for k in range(1, 5)},
            # the chelating acetate on Zr: two dative O...
            ("O31", "ZR1", 1.98): "coordination",
            ("O41", "ZR1", 2.41): "coordination",
            # ...its carboxylate carbon is 1-3 through O31, never a bond
            ("C12", "ZR1", 2.50): "non_bonded_close",
            # ...and the methyl carbon is a real sigma bond
            ("C11", "ZR1", 2.28): "covalent",
            # LA1 ... C(arene) 3.20 A does not appear at all (see below)
        }

    def test_zr_methyl_is_a_covalent_sigma_bond(self):
        """Zr-CH3 2.28 A is `covalent`, not `coordination`.

        Chemically it is an X-type, two-electron M-C sigma bond (an alkyl is
        an anionic ligand, not a lone-pair donor), so `covalent` is the
        honest label and `coordination` is reserved for dative L->M bonds -
        which is also what makes the kind useful downstream: a viewer may
        draw dative bonds differently, and a valence consumer counts an alkyl
        the way it counts a C-C bond.

        The rule that admits it is element-general: d <= sum(r_cov), i.e.
        2.28 <= 1.75 + 0.76 = 2.51. The flat 2.15 A ceiling in
        `connectivity._bond_cutoff` refuses this real bond (see
        test_bonding_status_quo) and would refuse Mo-CH3 (2.20) and Ti-CH3
        (2.18) as well.
        """
        t = bond_table(organometallic())
        e = [x for x in t.edges
             if {t.labels[x.i], t.labels[x.j]} == {"ZR1", "C11"}]
        assert len(e) == 2 and {x.kind for x in e} == {"covalent"}
        assert "M-C sigma" in e[0].basis
        assert KIND_CODE[e[0].kind] == 0

    def test_zr_carboxylate_carbon_is_non_bonded_close(self):
        """Zr...C(carboxylate) 2.50 A: reportable, but not a bond and not in
        the CN. It survives `prune_long_metal_contacts` today by 0.01 A."""
        t = bond_table(organometallic(), include_non_bonded=True)
        e = [x for x in t.edges
             if {t.labels[x.i], t.labels[x.j]} == {"ZR1", "C12"}]
        assert {x.kind for x in e} == {"non_bonded_close"}
        assert "chelate bite Zr-O-C" in e[0].basis
        zr = t.labels.index("ZR1")
        assert sorted(t.labels[x.j] for x in t.by_atom(zr)) == [
            "C11", "C12", "O31", "O41"]
        assert t.cn(zr) == 3           # methyl C + two O; the bite excluded

    def test_la_arene_contact_is_not_an_edge_at_all(self):
        """La...C(arene) 3.20 A: beyond sum(r_cov) (2.83 A) for a pair that
        is neither an eta ring nor a chelate bite -> dropped, exactly what
        `prune_long_metal_contacts` was written to do."""
        t = bond_table(organometallic(), include_non_bonded=True)
        la = t.labels.index("LA1")
        assert t.by_atom(la) == []
        assert t.cn(la) == 0
        assert not any("LA1" in (t.labels[e.i], t.labels[e.j])
                       for e in t.edges)

    def test_eta_rings_count_as_one_ligand_each(self):
        t = bond_table(organometallic())
        fe = t.labels.index("FE1")
        assert len(t.by_atom(fe)) == 10          # ten eta edges...
        assert t.cn(fe) == 2                     # ...but two ligands
        rings = t.summary()["eta_rings"]
        assert len(rings) == 2
        assert {r["hapticity"] for r in rings} == {5}
        assert {r["metal"] for r in rings} == {"FE1"}
        assert sorted(sorted(r["ring_atoms"]) for r in rings) == [
            ["C1", "C2", "C3", "C4", "C5"], ["C10", "C6", "C7", "C8", "C9"]]

    def test_summary_counts(self):
        s = bond_table(organometallic(), include_non_bonded=True).summary()
        assert s["kinds"] == {"covalent": 46, "coordination": 12, "eta": 20,
                              "metal_metal": 0, "non_bonded_close": 2}
        assert s["n_metals"] == 4 and s["n_atoms"] == 32


class TestChelateBiteAcrossACellFace:
    def test_the_bite_is_recognised_through_a_symmetry_operator(self):
        """The same chelate, positioned so that it closes across the a face:
        the metal sees its carboxylate through `x+1,y,z` and the carbon sees
        the metal through `x-1,y,z`. The 1-3 test has to move into the metal's
        own frame to compare O...C, so both orientations must agree."""
        from cctbx.array_family import flex

        from test_bonding_status_quo import _chelate
        m = (5.0, 8.0, 8.0)
        c, o3, o4 = _chelate(m, (1, 0, 0), (0, 0, 1))
        xs = _structure([("CU1", "Cu", m), ("C2", "C", tuple(c)),
                         ("O3", "O", tuple(o3)), ("O4", "O", tuple(o4))],
                        (6.0, 16, 16, 90, 90, 90))
        xs.set_sites_frac(flex.vec3_double(
            [tuple(v % 1.0 for v in s) for s in xs.sites_frac()]))
        t = bond_table(xs, include_non_bonded=True)
        got = {(t.labels[e.i], t.labels[e.j]): (e.op, e.kind) for e in t.edges}
        assert got[("CU1", "C2")] == ("x+1,y,z", "non_bonded_close")
        assert got[("C2", "CU1")] == ("x-1,y,z", "non_bonded_close")
        assert got[("CU1", "O3")] == ("x+1,y,z", "coordination")
        assert t.cn(t.labels.index("CU1")) == 2


def _ferrocene_on_an_inversion_centre():
    """The real ferrocene setting: Fe on the inversion centre of P-1, ONE Cp
    in the asymmetric unit, the second ring generated by `-x,-y,-z`."""
    r = 1.42 / (2 * math.sin(math.radians(36)))
    h = math.sqrt(2.05 ** 2 - r ** 2)
    atoms = [("FE1", "Fe", (0.0, 0.0, 0.0))]
    for k in range(5):
        a = math.radians(72 * k)
        atoms.append((f"C{k + 1}", "C", (r * math.cos(a), r * math.sin(a), h)))
    return _structure(atoms, (16, 16, 16, 90, 90, 90), sg="P -1")


class TestEtaThroughSymmetry:
    def test_symmetry_generated_cp_is_a_second_ligand_not_the_same_one(self):
        """Both Cp rings carry the SAME atom labels here, so counting eta
        RECORDS would give CN 1; the ring instances are found from the graph
        (which ring-atom images are bonded to each other) and give CN 2."""
        t = bond_table(_ferrocene_on_an_inversion_centre())
        fe = t.labels.index("FE1")
        edges = t.by_atom(fe)
        assert len(edges) == 10
        assert {e.kind for e in edges} == {"eta"}
        assert {e.op for e in edges} == {"x,y,z", "-x,-y,-z"}
        assert t.cn(fe) == 2
        # one symmetry-unique record, as in connectivity.pi_ligands
        assert len(t.summary()["eta_rings"]) == 1
        # each ring carbon sees the metal once
        assert t.cn(t.labels.index("C1")) == 3     # two ring C + the metal


# ------------------------------------------------ three-state CN (knowledge) --

class TestCnStatus:
    def test_unlisted_metal_is_never_a_silent_pass(self):
        t = bond_table(organometallic())
        os1 = t.labels.index("OS1")
        st = cn_status("Os", t.cn(os1))
        assert st["checked"] is False
        assert st["plausible"] is None
        assert st["expected_cn"] is None
        assert "NOT checked" in st["note"]

    def test_listed_metal_gets_a_verdict_either_way(self):
        assert cn_status("Cu", 4) == {
            "checked": True, "plausible": True, "expected_cn": [2, 6],
            "note": cn_status("Cu", 4)["note"]}
        assert cn_status("Cu", 4)["plausible"] is True
        assert cn_status("Zr", 3)["plausible"] is False
        assert cn_status("Zr", 3)["expected_cn"] == [6, 9]
        assert cn_status("Zr", 7)["plausible"] is True

    def test_non_metal_and_missing_cn(self):
        st = cn_status("C", 4)
        assert st["checked"] is False and st["plausible"] is None
        assert "not a metal" in st["note"]
        st = cn_status("Zr", None)
        assert st["checked"] is False and st["plausible"] is None
        assert st["expected_cn"] == [6, 9]

    def test_the_three_states_are_distinguishable(self):
        states = {(cn_status(*a)["checked"], cn_status(*a)["plausible"])
                  for a in (("Os", 6), ("Zr", 7), ("Zr", 2))}
        assert states == {(False, None), (True, True), (True, False)}


# ---------------------------------------------------------- element handling --

class TestMetalWhitelist:
    def test_whitelist_covers_the_periodic_table_not_a_blacklist(self):
        for el in ("Na", "Cu", "Zr", "La", "Os", "U", "Pb", "Bi", "Ca", "Al"):
            assert is_metal_element(el), el
        for el in ("H", "D", "C", "N", "O", "F", "Cl", "Br", "I", "S", "P",
                   "Si", "B", "Se", "As", "Te", "Ge", "Sb", "Xe", "He"):
            assert not is_metal_element(el), el

    def test_an_unknown_scattering_type_is_not_a_metal(self):
        """The old blacklist (`element not in NON_METALS`) promoted every
        typo, every Q peak label and every unknown symbol to a metal."""
        for el in ("Q", "Xx", "", "Zz"):
            assert not is_metal_element(el)

    def test_one_definition_charged_types_and_metalloids(self):
        """knowledge.is_metal IS the whitelist (migration 5b): every consumer
        that used the blacklist now agrees with chem.bonding; a charged
        scattering type is reduced to its element; Ge / Sb / Te / As / B / Si
        (metals under the old blacklist, or never) are metalloids."""
        from crystalpilot.chem.knowledge import is_metal
        assert is_metal is is_metal_element
        assert is_metal("Cu2+") and is_metal("zr") and is_metal("Fe3+")
        assert not is_metal("O-1") and not is_metal("Ge") and not is_metal("Sb")
        assert is_metal("Bi") and is_metal("Po") and not is_metal("At")


# ------------------------------------------------------- metal-hydrogen rule --

def _zr_hydroxide_and_hydride():
    """Zr with (a) an O-H whose H leans to 2.450 A from the metal and (b) a
    terminal hydride at 2.000 A. Both are inside the engine's search radius
    for Zr-H (1.75 + 0.31 + 0.5 = 2.56 A); only the second is a ligand."""
    theta = math.degrees(math.acos(
        (2.45 ** 2 - 2.0 ** 2 - 0.95 ** 2) / (2 * 2.0 * 0.95)))
    return _structure(
        [("ZR1", "Zr", (0.0, 0.0, 0.0)),
         ("O1", "O", (2.0, 0.0, 0.0)),
         ("H1", "H", (2.0 + 0.95 * math.cos(math.radians(theta)),
                      0.95 * math.sin(math.radians(theta)), 0.0)),
         ("H2", "H", (-2.0, 0.0, 0.0))],
        (20, 20, 20, 90, 90, 90))


class TestMetalHydrogen:
    def test_riding_oh_is_not_a_ligand_but_a_terminal_hydride_is(self):
        xs = _zr_hydroxide_and_hydride()
        assert kinds(xs) == {
            ("O1", "ZR1", 2.00): "coordination",
            ("H1", "O1", 0.95): "covalent",
            # the O-H hydrogen leaning at the metal: reported, not counted
            ("H1", "ZR1", 2.45): "non_bonded_close",
            # a hydride with no other heavy partner is a real ligand
            ("H2", "ZR1", 2.00): "coordination",
        }
        t = bond_table(xs)
        assert t.cn(t.labels.index("ZR1")) == 2

    def test_connectivity_no_longer_counts_the_riding_h(self):
        """The defect this rule closes (pa2 cage runs: "Zr CN=11 with three
        O-H hydrogens counted"): `connectivity._bond_cutoff` gave Zr-H the
        M-O window + 0.2 = 2.65 A, so the riding H at 2.45 became a ligand
        (CN 3 before migration 5). The hydride still counts."""
        from crystalpilot.chem.connectivity import analyze_connectivity
        rep = analyze_connectivity(_zr_hydroxide_and_hydride())
        assert rep.coordination[0]["cn"] == 2
        assert rep.coordination[0]["neighbors"] == ["H:2.00", "O:2.00"]


# --------------------------------------------------------------- public shape --

class TestApiShape:
    def test_bond_edge_fields_and_wire_format(self):
        t = bond_table(mof_chain())
        e = t.edges[0]
        assert isinstance(e, BondEdge)
        assert (e.i, e.j) == (t.edges[0].i, t.edges[0].j)
        assert isinstance(e.op, str) and isinstance(e.d, float)
        assert e.kind in KIND_CODE and isinstance(e.basis, str) and e.basis
        i, j, code = e.as_tuple()               # viewer triple
        assert (i, j) == (e.i, e.j) and code == KIND_CODE[e.kind]

    def test_parts_accepts_a_dict_or_a_sequence(self):
        xs = organic_p_1()
        by_label = bond_table(xs, ORGANIC_PARTS)
        seq = [ORGANIC_PARTS.get(sc.label, 0) for sc in xs.scatterers()]
        by_seq = bond_table(xs, seq)
        assert len(by_label.edges) == len(by_seq.edges)
        # a NEGATIVE part means the same conformer plus sym_excl (D10:
        # |PART| decides who bonds whom, the sign only adds the symmetry
        # suppression) - it must not silently split the conformers
        neg = bond_table(xs, {"C7A": -1, "C7B": -2})
        assert len(neg.edges) == len(by_label.edges)

    def test_empty_and_single_atom_structures(self):
        xs = _structure([("C1", "C", (0.0, 0.0, 0.0))], (30, 30, 30, 90, 90, 90))
        t = bond_table(xs)
        assert t.edges == [] and t.cn(0) == 0
        assert t.summary()["n_edges"] == 0

    def test_criteria_are_reported_with_the_table(self):
        s = bond_table(mof_chain()).summary()
        assert f"sum(r_cov) + {TOL_COVALENT}" in s["criteria"]["covalent"]
        assert "smtbx.utils.connectivity_table" in s["engine"]
        assert "prune_long_metal_contacts" in s["criteria"]["dropped"]


# ------------------------------------------------------- metal-metal contacts --

def _cu_paddlewheel_stub():
    """Two Cu 2.60 A apart (a paddlewheel core), each with two O at 1.95 A:
    the Cu...Cu contact is a `metal_metal` edge and is NOT a ligand."""
    return _structure(
        [("CU1", "Cu", (0.0, 0.0, 0.0)), ("CU2", "Cu", (0.0, 0.0, 2.60)),
         ("O1", "O", (1.95, 0.0, 0.0)), ("O2", "O", (-1.95, 0.0, 0.0)),
         ("O3", "O", (1.95, 0.0, 2.60)), ("O4", "O", (-1.95, 0.0, 2.60))],
        (20, 20, 20, 90, 90, 90))


class TestMetalMetal:
    def test_metal_metal_edge_is_listed_but_never_a_ligand(self):
        xs = _cu_paddlewheel_stub()
        assert kinds(xs) == {
            ("CU1", "CU2", 2.60): "metal_metal",
            ("CU1", "O1", 1.95): "coordination", ("CU1", "O2", 1.95): "coordination",
            ("CU2", "O3", 1.95): "coordination", ("CU2", "O4", 1.95): "coordination",
        }
        t = bond_table(xs)
        cu1 = t.labels.index("CU1")
        assert t.kinds_of(cu1) == {"metal_metal": 1, "coordination": 2}
        assert t.cn(cu1) == 2
        assert t.summary()["kinds"]["metal_metal"] == 2     # both orientations

    def test_connectivity_lists_the_contact_apart_too(self):
        from crystalpilot.chem.connectivity import analyze_connectivity
        rep = analyze_connectivity(_cu_paddlewheel_stub())
        env = {e["atom"]: e for e in rep.coordination}
        assert env["CU1"]["cn"] == 2
        assert env["CU1"]["metal_metal"] == ["Cu:2.60"]
        assert {b.kind for b in rep.bonds} == {"sigma", "metal_metal"}

    def test_inspect_lists_the_contact_apart_and_counts_oxygen_only(self):
        from crystalpilot.refine.inspect import metal_environments
        env = {e["atom"]: e for e in metal_environments(_cu_paddlewheel_stub())}
        assert env["CU1"]["cn"] == 2
        assert env["CU1"]["metal_metal"] == ["CU2:2.6"]
        assert env["CU1"]["neighbors"] == ["O1:1.95", "O2:1.95"]
