"""Bonded-graph analysis of a crystal structure: coordination environments,
framework dimensionality, isolated fragments, eta-bound rings (Cp/arene)
and the system-type call (framework / molecular / salt / unknown) that
decides WHICH validation criteria apply. Core of chemistry-aware validation.

Why the system type exists (pa1 cage-l3-r1, 2026-09-02): a discrete Zr6
molecular cage was scored with MOF criteria - "framework dimensionality 0
... structure may be incomplete", 56 "free" atoms (three eta5-Cp rings and
the counter-ions are not bonded at the 2.15 A M-C cutoff), confidence 27 -
and the agent discarded a trial that matched 149/154 published atoms as
"chemically invalid". A 0-D molecule is not an incomplete framework.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np
from cctbx.eltbx import covalent_radii, tiny_pse

from .knowledge import COMMON_GUESTS, cn_status, is_metal, profile_for

_RADIUS_CACHE: dict[str, float] = {}
_WATER_LABEL = re.compile(r"O\d*W\d*")

# --- eta-bound ring (Cp / arene) recognition, purely geometric -------------
# M-C window: Fe-C(Cp) 2.03-2.06, Ru 2.17-2.22, Ti 2.35-2.40, Zr/Hf 2.45-2.60,
# lanthanide/actinide Cp 2.60-2.80 A. Everything a ring bound side-on to one
# metal does: all ring atoms roughly equidistant from that metal, the metal
# sitting on the ring normal above the centroid, the ring flat.
_ETA_MC_MIN, _ETA_MC_MAX = 1.85, 2.85
_ETA_SPREAD_MAX = 0.40           # max-min M-C inside one ring (slipped rings tolerated)
_ETA_CENTROID_MIN, _ETA_CENTROID_MAX = 1.40, 2.70
_ETA_PLANE_RMS_MAX = 0.12        # out-of-plane rms of the ring atoms (A)
_ETA_TILT_MAX = 30.0             # ring normal vs centroid->metal (deg)
_ETA_RING_SIZES = (5, 6)
_RING_SEARCH_BUDGET = 2_000_000  # DFS steps; ghost-peak clusters must not hang validation

# Elements whose lone atoms are recognised counter-ions on their own (a free
# halide or alkali cation has no bonded partner by definition).
LONE_ION_ELEMENTS = frozenset({"F", "Cl", "Br", "I", "Li", "Na", "K", "Rb",
                               "Cs", "Mg", "Ca", "Sr", "Ba"})

# Non-H element-count signatures of fragments a molecular crystal legitimately
# contains besides the main molecule. (role, name) per signature; matching is
# exact on the non-H counts of a bonded fragment.
_FRAGMENT_SIGNATURES: list[tuple[dict[str, int], str, str]] = [
    ({"F": 1}, "counter_ion", "F-"), ({"Cl": 1}, "counter_ion", "Cl-"),
    ({"Br": 1}, "counter_ion", "Br-"), ({"I": 1}, "counter_ion", "I-"),
    ({"Li": 1}, "counter_ion", "Li+"), ({"Na": 1}, "counter_ion", "Na+"),
    ({"K": 1}, "counter_ion", "K+"), ({"Rb": 1}, "counter_ion", "Rb+"),
    ({"Cs": 1}, "counter_ion", "Cs+"), ({"Mg": 1}, "counter_ion", "Mg2+"),
    ({"Ca": 1}, "counter_ion", "Ca2+"), ({"Sr": 1}, "counter_ion", "Sr2+"),
    ({"Ba": 1}, "counter_ion", "Ba2+"),
    ({"O": 1}, "solvent", "H2O / OH- / oxide"),
    ({"N": 1, "O": 3}, "counter_ion", "NO3-"),
    ({"Cl": 1, "O": 4}, "counter_ion", "ClO4-"),
    ({"S": 1, "O": 4}, "counter_ion", "SO42-"),
    ({"P": 1, "O": 4}, "counter_ion", "PO43-"),
    ({"C": 1, "O": 3}, "counter_ion", "CO32-"),
    ({"B": 1, "F": 4}, "counter_ion", "BF4-"),
    ({"P": 1, "F": 6}, "counter_ion", "PF6-"),
    ({"Sb": 1, "F": 6}, "counter_ion", "SbF6-"),
    ({"As": 1, "F": 6}, "counter_ion", "AsF6-"),
    ({"Si": 1, "F": 6}, "counter_ion", "SiF62-"),
    ({"C": 1, "F": 3, "S": 1, "O": 3}, "counter_ion", "CF3SO3- (triflate)"),
    ({"C": 2, "F": 6, "S": 2, "O": 4, "N": 1}, "counter_ion", "NTf2-"),
    ({"B": 1, "C": 24}, "counter_ion", "BPh4-"),
    ({"C": 1, "N": 1, "S": 1}, "counter_ion", "SCN-"),
    ({"C": 1, "N": 1}, "counter_ion", "CN-"),
    ({"N": 3}, "counter_ion", "N3-"),
    ({"C": 1, "O": 2}, "counter_ion", "formate"),
    ({"C": 2, "O": 2}, "counter_ion", "acetate"),
    ({"C": 4, "O": 1}, "solvent", "THF / Et2O"),
    ({"C": 4, "O": 2}, "solvent", "dioxane / EtOAc"),
    ({"C": 1, "Cl": 2}, "solvent", "CH2Cl2"),
    ({"C": 1, "Cl": 3}, "solvent", "CHCl3"),
    ({"C": 3, "O": 1}, "solvent", "acetone / iPrOH"),
    ({"C": 2, "S": 1, "O": 1}, "solvent", "DMSO"),
    ({"C": 5, "N": 1}, "solvent", "pyridine"),
    ({"C": 5, "N": 1, "O": 1}, "solvent", "NMP / DEF"),
    ({"C": 6}, "solvent", "benzene / hexane"),
    ({"C": 7}, "solvent", "toluene"),
    ({"C": 1, "N": 1, "O": 2}, "solvent", "MeNO2"),
]
for _name, _formula in COMMON_GUESTS.items():
    _sig = {e: n for e, n in _formula.items() if e != "H"}
    if not any(s == _sig for s, _r, _n in _FRAGMENT_SIGNATURES):
        _FRAGMENT_SIGNATURES.append(
            (_sig, "counter_ion" if _name.endswith("-") else "solvent", _name))


def covalent_radius(el: str) -> float:
    el = el.capitalize()
    if el not in _RADIUS_CACHE:
        try:
            _RADIUS_CACHE[el] = covalent_radii.table(el).radius()
        except RuntimeError:
            _RADIUS_CACHE[el] = 0.77
    return _RADIUS_CACHE[el]


@dataclass
class Bond:
    i: int
    j: int
    shift: tuple[int, int, int]     # cell translation of atom j relative to atom i
    length: float
    kind: str = "sigma"             # "sigma" (covalent / dative), "eta" (ring-metal), "metal_metal"


@dataclass
class ConnectivityReport:
    n_atoms_p1: int = 0
    bonds: list[Bond] = field(default_factory=list)
    coordination: list[dict] = field(default_factory=list)   # per metal (P1)
    isolated_atoms: list[str] = field(default_factory=list)
    short_contacts: list[dict] = field(default_factory=list)
    fragments: list[dict] = field(default_factory=list)      # size + dimensionality
    framework_dimensionality: int = 0
    pi_ligands: list[dict] = field(default_factory=list)     # eta-bound rings, unique per ASU
    fragment_census: list[dict] = field(default_factory=list)  # unique fragments + identity
    system_type: str = "unknown"    # framework | molecular | salt | unknown
    system_type_evidence: dict = field(default_factory=dict)

    def summary(self) -> dict:
        return {
            "n_atoms_p1": self.n_atoms_p1,
            "n_bonds": len(self.bonds),
            "framework_dimensionality": self.framework_dimensionality,
            "system_type": self.system_type,
            "system_type_evidence": self.system_type_evidence,
            "fragments": self.fragments[:12],
            "fragment_census": self.fragment_census[:20],
            "pi_ligands": self.pi_ligands[:20],
            "metal_coordination": self.coordination[:20],
            "isolated_atoms": self.isolated_atoms[:20],
            "short_contacts": self.short_contacts[:15],
        }


def _bond_cutoff(el_i: str, el_j: str, tol: float = 0.45) -> float:
    """Max plausible bond length; metal-X uses knowledge windows when available.

    No longer the bond criterion of `analyze_connectivity` (bonding
    migration 5: `chem.bonding` is); still used by `asu_sanity` and the
    offline benchmark grader as a coarse search radius."""
    prof = profile_for(el_i) or profile_for(el_j)
    metal_involved = is_metal(el_i) or is_metal(el_j)
    base = covalent_radius(el_i) + covalent_radius(el_j) + tol
    if metal_involved and prof:
        other = el_j if is_metal(el_i) else el_i
        if other == "O":
            return prof.m_o_range[1] + 0.05
        if other == "N" and prof.m_n_range:
            return prof.m_n_range[1] + 0.05
        if other == "C":
            # M-C bonds are rare in MOFs (organometallics only); keep tight so
            # chelating carboxylate carbons (~2.3-2.6 A) don't count as bonds
            return 2.15
        return max(base, prof.m_o_range[1] + 0.2)
    return base


def _short_factor(el_i: str, el_j: str) -> float:
    """Fraction of the covalent-radii sum below which a pair is physically
    impossible rather than bonded. Metal-metal multiple bonds are short
    (Mo-Mo 2.1 A), so that class gets the loosest fence."""
    mi, mj = is_metal(el_i), is_metal(el_j)
    if mi and mj:
        return 0.5
    if mi or mj:
        return 0.7
    return 0.75


def _canonical_pair(i: int, j: int, shift: tuple) -> tuple:
    """One key per physical pair. (i, j, s) and (j, i, -s) are the same
    contact seen from the other atom; the previous key kept both, so every
    bond closing across a cell face was counted twice - metal CN inflated
    for atoms near a face (duplicated 'O:2.26' neighbours in the pa1 cage
    runs) and n_bonds over-reported."""
    neg = tuple(-s for s in shift)
    if i < j or (i == j and shift >= neg):
        return (i, j, tuple(shift))
    return (j, i, neg)


def _carbocycles(elements: list[str], bonds: list[Bond],
                 sizes: tuple[int, ...] = _ETA_RING_SIZES
                 ) -> tuple[list[tuple[list[int], list[tuple]]], bool]:
    """5/6-membered all-carbon rings of the P1 sigma graph, each as (atom
    indices, cumulative cell shifts from the first atom). Returns (rings,
    truncated). Carbons with >4 carbon neighbours (ghost-peak clusters)
    cannot be ring members and are skipped so the DFS stays bounded."""
    cadj: dict[int, list[tuple[int, tuple]]] = {
        i: [] for i, e in enumerate(elements) if e == "C"}
    for b in bonds:
        if b.kind != "sigma" or elements[b.i] != "C" or elements[b.j] != "C":
            continue
        cadj[b.i].append((b.j, b.shift))
        cadj[b.j].append((b.i, tuple(-s for s in b.shift)))
    for i in list(cadj):
        if len(cadj[i]) > 4:
            cadj[i] = []
    rings: list[tuple[list[int], list[tuple]]] = []
    seen_sets: set[frozenset] = set()
    max_size = max(sizes)
    steps = 0
    truncated = False

    def dfs(path: list[int], cum: list[tuple]) -> None:
        nonlocal steps, truncated
        if truncated:
            return
        steps += 1
        if steps > _RING_SEARCH_BUDGET:
            truncated = True
            return
        u = path[-1]
        for v, s in cadj[u]:
            cs = tuple(a + b for a, b in zip(cum[-1], s))
            if v == path[0]:
                if len(path) in sizes and cs == (0, 0, 0):
                    key = frozenset(path)
                    if key not in seen_sets:
                        seen_sets.add(key)
                        rings.append((list(path), list(cum)))
            elif v > path[0] and v not in path and len(path) < max_size:
                dfs(path + [v], cum + [cs])

    for start in sorted(cadj):
        if cadj[start]:
            dfs([start], [(0, 0, 0)])
    return rings, truncated


def _eta_rings(elements, labels, frac, ortho, bonds) -> tuple[list[dict], bool]:
    """Rings bound side-on to a metal: flat, every ring atom inside the M-C
    window from the SAME metal image, metal on the ring normal. Returns
    per-P1-ring records (with the metal image shift so edges can be added
    to the graph) and the DFS-truncated flag."""
    rings, truncated = _carbocycles(elements, bonds)
    metals = [i for i, e in enumerate(elements) if is_metal(e)]
    if not rings or not metals:
        return [], truncated
    inv_ortho = np.linalg.inv(ortho)
    local = [(dx, dy, dz) for dx in (-1, 0, 1) for dy in (-1, 0, 1)
             for dz in (-1, 0, 1)]
    found: list[dict] = []
    for idx, cum in rings:
        pos = np.array([(frac[k] + np.array(s)) @ ortho.T
                        for k, s in zip(idx, cum)])
        centroid = pos.mean(axis=0)
        x = pos - centroid
        _, _, vt = np.linalg.svd(x, full_matrices=False)
        normal = vt[-1]
        rms = float(np.sqrt(np.mean((x @ normal) ** 2)))
        if rms > _ETA_PLANE_RMS_MAX:
            continue
        c_frac = centroid @ inv_ortho.T
        for m in metals:
            base = np.round(c_frac - frac[m])
            best = None
            for dl in local:
                s = base + np.array(dl)
                pm = (frac[m] + s) @ ortho.T
                dc = float(np.linalg.norm(pm - centroid))
                if best is None or dc < best[0]:
                    best = (dc, s, pm)
            dc, s, pm = best
            if not (_ETA_CENTROID_MIN <= dc <= _ETA_CENTROID_MAX):
                continue
            dists = np.linalg.norm(pos - pm, axis=1)
            if (dists.min() < _ETA_MC_MIN or dists.max() > _ETA_MC_MAX
                    or dists.max() - dists.min() > _ETA_SPREAD_MAX):
                continue
            cosang = abs(float(np.dot(normal, (pm - centroid) / dc)))
            tilt = float(np.degrees(np.arccos(min(1.0, cosang))))
            if tilt > _ETA_TILT_MAX:
                continue
            found.append({
                "metal_index": m, "metal_shift": tuple(int(v) for v in s),
                "ring_indices": list(idx),
                "ring_shifts": [tuple(int(v) for v in c) for c in cum],
                "metal": labels[m], "metal_element": elements[m],
                "hapticity": len(idx), "ring_size": len(idx),
                "ring_atoms": [labels[k] for k in idx],
                "m_c_range": [round(float(dists.min()), 2),
                              round(float(dists.max()), 2)],
                "centroid_d": round(dc, 2), "plane_rms": round(rms, 3),
                "tilt_deg": round(tilt, 1),
                "_spread": float(dists.max() - dists.min()),
            })
    # one ring per set of atoms per metal: a spurious peak bonded into a
    # Cp makes alternative 5- and 6-cycles over the same carbons (cage
    # trial: ZR02 "eta6 + eta5 + eta5" over six atoms); keep the most
    # regular ring and drop any other sharing >1 atom with it
    kept: list[dict] = []
    by_metal: dict[int, list[dict]] = {}
    for rec in found:
        by_metal.setdefault(rec["metal_index"], []).append(rec)
    for recs in by_metal.values():
        recs.sort(key=lambda r: (r["_spread"], r["plane_rms"]))
        accepted: list[dict] = []
        for rec in recs:
            atoms = set(rec["ring_indices"])
            if all(len(atoms & set(a["ring_indices"])) <= 1 for a in accepted):
                accepted.append(rec)
        kept.extend(accepted)
    for rec in kept:
        rec.pop("_spread", None)
    return kept, truncated


def fragment_identity(el_counts: dict[str, int]) -> tuple[str, str] | None:
    """(role, name) for a bonded fragment whose non-H element counts match a
    recognised counter-ion / solvent signature, else None."""
    counts = {e: n for e, n in el_counts.items() if e not in ("H", "D")}
    for sig, role, name in _FRAGMENT_SIGNATURES:
        if counts == sig:
            return role, name
    return None


def _fragment_census(fragments: list[dict]) -> list[dict]:
    """Collapse P1 copies (same ASU label set) and name what each unique
    fragment looks like. Roles: main (largest), counter_ion, solvent,
    lone_atom (unrecognised single atom), small_unrecognised (2-5 atoms
    matching nothing), molecule / metal_complex (>= 6 atoms)."""
    uniq: dict[frozenset, dict] = {}
    for f in fragments:
        key = frozenset(f["asu_labels"])
        if key in uniq:
            uniq[key]["copies"] += 1
            continue
        uniq[key] = {
            "n_atoms": f["n_atoms"], "elements": dict(f["elements"]),
            "asu_labels": list(f["asu_labels"][:10]),
            "n_asu_labels": len(f["asu_labels"]),
            "dimensionality": f["dimensionality"], "copies": 1,
            "has_metal": any(is_metal(e) for e in f["elements"]),
        }
    census = sorted(uniq.values(), key=lambda c: -c["n_atoms"])
    for k, c in enumerate(census):
        ident = fragment_identity(c["elements"])
        if (ident and c["n_atoms"] == 1 and c["elements"].get("O") == 1
                and not _WATER_LABEL.fullmatch(c["asu_labels"][0].upper())):
            # anonymous lone O is not "water" - the expert rule bans
            # anonymous atoms; a declared O1W is solvent, an O9 is not
            ident = None
        c["identity"] = ident[1] if ident else None
        if k == 0:
            c["role"] = "main"
        elif ident:
            c["role"] = ident[0]
        elif c["n_atoms"] == 1:
            c["role"] = "lone_atom"
        elif c["n_atoms"] <= 5:
            c["role"] = "small_unrecognised"
        else:
            c["role"] = "metal_complex" if c["has_metal"] else "molecule"
    return census


def classify_system(fragments: list[dict], census: list[dict],
                    n_bonds: int, n_pi_ligands: int) -> tuple[str, dict]:
    """System-type call from the bonded graph.

    framework  - a fragment periodic in >= 1 direction carries metal AND
                 carbon (coordination polymer) or carbon only (covalent
                 framework / polymer); reported with its dimensionality.
    salt       - periodic carbon-free metal lattice (NaCl-type), or 0-D
                 carbon-free metal fragments of <= 8 atoms (hexaaqua ions..).
    molecular  - everything 0-D whose largest fragment is a molecule:
                 organic, coordination complex, cluster/cage, organometallic.
    unknown    - no bonds at all, or the only metal fragments are carbon-
                 free and bigger than an ion (Zr6O8-type core without its
                 ligands: an inorganic cluster OR a model whose ligands are
                 still missing - the caller must not read periodicity or
                 free-fragment criteria into it).
    """
    dim = max((f["dimensionality"] for f in fragments), default=0)
    ev: dict = {"dimensionality": dim, "n_unique_fragments": len(census),
                "n_pi_ligands": n_pi_ligands}
    if not fragments or n_bonds == 0:
        ev["rationale"] = ("no bonded pairs at all - too sparse to classify; "
                           "complete the model before reading periodicity "
                           "or fragment criteria")
        ev["label"] = "undetermined (no bonds)"
        return "unknown", ev
    main = census[0]
    ev["main_fragment"] = {
        "n_atoms": main["n_atoms"], "elements": main["elements"],
        "n_metals": sum(n for e, n in main["elements"].items() if is_metal(e)),
        "copies_in_cell": main["copies"]}
    for role in ("counter_ion", "solvent"):
        tally: dict[str, int] = {}
        for c in census:
            if c["role"] == role:
                tally[c["identity"]] = tally.get(c["identity"], 0) + 1
        ev["counter_ions" if role == "counter_ion" else "solvent"] = tally
    ev["unrecognised_lone_atoms"] = sum(
        1 for c in census if c["role"] == "lone_atom")
    ev["unrecognised_small_fragments"] = sum(
        1 for c in census if c["role"] == "small_unrecognised")
    periodic = [f for f in fragments if f["dimensionality"] >= 1]
    if periodic:
        with_metal = [f for f in periodic if any(is_metal(e) for e in f["elements"])]
        with_carbon = [f for f in periodic if "C" in f["elements"]]
        if with_metal and with_carbon:
            ev["label"] = f"{dim}-D coordination polymer / framework"
            ev["rationale"] = (f"a bonded fragment is periodic in {dim} "
                               "direction(s) and carries metal and carbon")
            return "framework", ev
        if with_metal:
            ev["label"] = f"{dim}-D ionic / inorganic lattice"
            ev["rationale"] = (f"periodic in {dim} direction(s) through "
                               "metal-anion bonds only, no carbon")
            return "salt", ev
        ev["label"] = f"{dim}-D covalent framework / polymer"
        ev["rationale"] = (f"a carbon fragment is periodic in {dim} "
                           "direction(s) without metal")
        return "framework", ev
    metal_frags = [c for c in census if c["has_metal"]]
    if not metal_frags:
        if main["n_atoms"] >= 3:
            ev["label"] = "0-D organic molecular crystal"
            ev["rationale"] = ("no metal, no periodic fragment; largest "
                               f"fragment {main['n_atoms']} atoms")
            return "molecular", ev
        ev["label"] = "undetermined (only tiny fragments)"
        ev["rationale"] = "no fragment of 3+ atoms yet"
        return "unknown", ev
    big = metal_frags[0]
    n_metals = sum(n for e, n in big["elements"].items() if is_metal(e))
    if "C" in big["elements"]:
        kind = ("organometallic" if n_pi_ligands else
                "cluster / cage" if n_metals >= 3 else "coordination complex")
        ev["label"] = (f"0-D molecular {kind} ({n_metals} metal atom(s), "
                       f"{big['n_atoms']} atoms"
                       + (f", {n_pi_ligands} eta-bound ring(s)"
                          if n_pi_ligands else "") + ")")
        ev["rationale"] = ("no periodic fragment; the largest metal-"
                           "containing fragment is a discrete molecule "
                           "with organic ligands")
        return "molecular", ev
    if big["n_atoms"] <= 8:
        ev["label"] = "0-D ionic salt (carbon-free metal ions + anions)"
        ev["rationale"] = ("no periodic fragment; metal fragments are "
                           "small and carbon-free")
        return "salt", ev
    ev["label"] = (f"undetermined: carbon-free metal fragment of "
                   f"{big['n_atoms']} atoms")
    ev["rationale"] = ("largest metal fragment carries no carbon - an "
                       "inorganic cluster, or a partial model whose "
                       "ligands are not yet placed; periodicity and "
                       "free-fragment criteria are not meaningful yet")
    return "unknown", ev


def analyze_connectivity(xs, max_cutoff: float = 3.2,
                         parts: dict[str, int] | None = None) -> ConnectivityReport:
    """Expand to P1, build the bonded graph with cell-shift edges, analyze.

    Bonds are the one bonding truth (`chem.bonding.bond_table`) placed on
    the P1 expansion; this module keeps the periodic fragment /
    dimensionality / census / system-type analysis on top of it.

    Eta-bound rings (Cp/arene) are recognised geometrically and joined to
    their metal as "eta" edges: they count as ONE ligand in the metal CN,
    belong to the metal's fragment (not "free fragments"), and are listed
    in pi_ligands. The fragment census and the system-type call feed the
    per-system-type validation criteria.

    parts: optional {label: SHELX PART} - atoms in different non-zero PARTs
    are disorder alternatives and never see each other (neither bonded nor
    a short contact), same semantics as refine.nodes.part_connectivity_kwargs.
    """
    from cctbx import sgtbx

    rep = ConnectivityReport()
    p1 = xs.expand_to_p1()
    uc = p1.unit_cell()
    scs = list(p1.scatterers())
    rep.n_atoms_p1 = len(scs)
    if not scs:
        return rep
    elements = [sc.scattering_type.strip().capitalize() for sc in scs]
    labels = [sc.label for sc in scs]
    frac = np.array([[x % 1.0 for x in sc.site] for sc in scs])
    ortho = np.array(uc.orthogonalization_matrix()).reshape(3, 3)
    part_of = {str(k).upper(): int(v or 0) for k, v in (parts or {}).items()}
    part = [part_of.get(lb.upper(), 0) for lb in labels]

    # ---- bonds: the one bonding truth, placed on the P1 expansion ---------
    # chem.bonding classifies every ASU pair once (symmetry-exact operator,
    # SHELX PART semantics, MetalProfile windows, chelate bite, eta ring,
    # metal-metal). Each classified ASU edge (i, j, op) is placed on every
    # P1 image of i and its partner located by wrapped site + integer cell
    # shift, so the periodic graph below IS the truth's graph (bonding
    # migration 5). Before this the module had its own criterion
    # (`_bond_cutoff`: sum(r_cov)+0.45, profile windows, a flat 2.15 A M-C
    # ceiling that only applied to metals with a profile - D9).
    from .bonding import KIND_ETA, KIND_METAL_METAL, bond_table

    asu_scs = list(xs.scatterers())
    asu_index = {sc.label.upper(): k for k, sc in enumerate(asu_scs)}
    table = bond_table(xs, parts)
    ops = list(xs.space_group())
    copies: dict[int, list[int]] = {}
    for k, lb in enumerate(labels):
        copies.setdefault(asu_index[lb.upper()], []).append(k)
    # the operator (and wrap shift) that generated each P1 atom; any
    # operator of the coset will do - the truth already lists every image
    # the site symmetry produces
    gen_op: list = [None] * len(scs)
    gen_shift = np.zeros((len(scs), 3))
    for a, ks in copies.items():
        site = asu_scs[a].site
        todo = list(ks)
        for g in ops:
            if not todo:
                break
            pos = np.array(g * site, float)
            for k in list(todo):
                delta = frac[k] - pos
                if np.all(np.abs(delta - np.round(delta)) < 1e-4):
                    gen_op[k] = g
                    gen_shift[k] = np.round(delta)
                    todo.remove(k)

    def _find_copy(j: int, q: np.ndarray):
        """P1 index of ASU atom j at fractional position q (mod lattice)
        and the integer shift that takes the stored copy there."""
        for m in copies.get(j, ()):
            delta = q - frac[m]
            sh = np.round(delta)
            if np.all(np.abs(delta - sh) < 1e-4):
                return m, tuple(int(v) for v in sh)
        return None, None

    bonds: list[Bond] = []
    seen: set[tuple] = set()
    bond_by_key: dict[tuple, Bond] = {}
    for k in range(len(scs)):
        g = gen_op[k]
        if g is None:
            continue
        a = asu_index[labels[k].upper()]
        for e in table.by_atom(a):
            # impossible contacts (undeclared split sites, ghost peaks) are
            # not bonds under any criterion: they go to short_contacts below
            if e.d < _short_factor(elements[k], table.elements[e.j]) * (
                    covalent_radius(elements[k])
                    + covalent_radius(table.elements[e.j])):
                continue
            op2 = g.multiply(sgtbx.rt_mx(e.op))
            q = np.array(op2 * asu_scs[e.j].site, float) + gen_shift[k]
            m, shift = _find_copy(e.j, q)
            if m is None:
                continue
            key = _canonical_pair(k, m, shift)
            if key in seen:
                continue
            seen.add(key)
            kind = ("eta" if e.kind == KIND_ETA
                    else "metal_metal" if e.kind == KIND_METAL_METAL
                    else "sigma")
            b = Bond(k, m, shift, round(float(e.d), 3), kind=kind)
            bonds.append(b)
            bond_by_key[key] = b

    # ---- impossible contacts: 27-image scan, short pairs only -------------
    shifts = [(dx, dy, dz) for dx in (-1, 0, 1) for dy in (-1, 0, 1) for dz in (-1, 0, 1)]
    cart0 = frac @ ortho.T
    short_seen: set[tuple] = set()
    short_keys: set[tuple] = set()
    short_of: dict[int, list[str]] = {}
    for shift in shifts:
        cart_s = (frac + np.array(shift)) @ ortho.T
        d2 = ((cart0[:, None, :] - cart_s[None, :, :]) ** 2).sum(axis=2)
        ii, jj = np.where((d2 < max_cutoff ** 2) & (d2 > 1e-6))
        for i, j in zip(ii.tolist(), jj.tolist()):
            if shift == (0, 0, 0) and j <= i:
                continue
            if part[i] and part[j] and abs(part[i]) != abs(part[j]):
                continue
            key = _canonical_pair(i, j, shift)
            if key in short_keys:
                continue
            d = float(np.sqrt(d2[i, j]))
            if d < _short_factor(elements[i], elements[j]) * (
                    covalent_radius(elements[i]) + covalent_radius(elements[j])):
                short_keys.add(key)
                short_of.setdefault(i, []).append(f"{elements[j]}:{d:.2f}")
                short_of.setdefault(j, []).append(f"{elements[i]}:{d:.2f}")
                # P1 copies of one ASU pair are the same chemical contact
                lk = (tuple(sorted((labels[i], labels[j]))), round(d, 2))
                if lk not in short_seen:
                    short_seen.add(lk)
                    rep.short_contacts.append(
                        {"atoms": [labels[i], labels[j]], "d": round(d, 2)})

    # eta-bound rings -> "eta" edges metal-ring atom (or relabel the sigma
    # edge when the M-C distance already passed the cutoff, e.g. Fe-Cp)
    eta_p1, ring_search_truncated = _eta_rings(elements, labels, frac, ortho, bonds)
    rings_of_metal: dict[int, list[dict]] = {}
    for rec in eta_p1:
        m, ms = rec["metal_index"], np.array(rec["metal_shift"])
        pm = (frac[m] + ms) @ ortho.T
        for k, cs in zip(rec["ring_indices"], rec["ring_shifts"]):
            rel = tuple(int(v) for v in (np.array(cs) - ms))
            key = _canonical_pair(m, k, rel)
            if key in bond_by_key:
                bond_by_key[key].kind = "eta"
                continue
            d = float(np.linalg.norm((frac[k] + np.array(cs)) @ ortho.T - pm))
            b = Bond(m, k, rel, round(d, 3), kind="eta")
            bonds.append(b)
            bond_by_key[key] = b
            seen.add(key)
        rings_of_metal.setdefault(m, []).append(rec)
    rep.bonds = bonds
    uniq_rings: dict[tuple, dict] = {}
    for rec in eta_p1:
        k = (rec["metal"], frozenset(rec["ring_atoms"]))
        if k not in uniq_rings:
            uniq_rings[k] = {kk: v for kk, v in rec.items()
                             if kk not in ("metal_index", "metal_shift",
                                           "ring_indices", "ring_shifts")}
    rep.pi_ligands = list(uniq_rings.values())

    # adjacency
    adj: dict[int, list[tuple[int, tuple, str]]] = {i: [] for i in range(len(scs))}
    for b in bonds:
        adj[b.i].append((b.j, b.shift, b.kind))
        adj[b.j].append((b.i, tuple(-s for s in b.shift), b.kind))

    # metal coordination environments (one entry per unique ASU label):
    # CN = ligand count - eta rings count once, metal-metal contacts are
    # listed apart and never counted, impossible contacts (undeclared split
    # sites, pa1 cage 'Fe:0.78') are listed apart and never counted.
    # cn_plausible is three-state: None means NOT CHECKED (no MetalProfile
    # window for this element) and must never be read as a pass (D9).
    seen_labels: set[str] = set()
    for i, el in enumerate(elements):
        if not is_metal(el):
            continue
        if labels[i] in seen_labels:
            continue
        seen_labels.add(labels[i])
        nd = []
        mm = []
        suspect = []
        for j, shift, kind in adj[i]:
            if kind == "eta":
                continue
            p_j = (frac[j] + np.array(shift)) @ ortho.T
            d = float(np.linalg.norm(cart0[i] - p_j))
            if kind == "metal_metal":
                mm.append((elements[j], d))
            elif short_of.get(j):
                # a neighbour that itself sits impossibly close to another
                # atom (undeclared split site, a ghost peak bonded into a
                # ring) is a modelling defect, not a donor - listed apart
                suspect.append((elements[j], d))
            else:
                nd.append((elements[j], d))
        rings = rings_of_metal.get(i, [])
        cn = len(nd) + len(rings)
        st = cn_status(el, cn)
        entry = {
            "atom": labels[i], "element": el, "cn": cn,
            "neighbors": ([f"{e}:{d:.2f}" for e, d in sorted(nd, key=lambda t: t[1])]
                          + [f"eta{r['hapticity']}-C{r['ring_size']}:{r['centroid_d']:.2f}"
                             for r in rings]),
            "cn_plausible": st["plausible"],
            "expected_cn": st["expected_cn"],
        }
        if st["plausible"] is None:
            entry["cn_note"] = st["note"]
        if mm:
            entry["metal_metal"] = [f"{e}:{d:.2f}"
                                    for e, d in sorted(mm, key=lambda t: t[1])]
        if suspect:
            entry["suspect_ligands"] = [
                f"{e}:{d:.2f}" for e, d in sorted(suspect, key=lambda t: t[1])]
        if rings:
            entry["eta_rings"] = [
                f"eta{r['hapticity']}-C{r['ring_size']} [{', '.join(r['ring_atoms'])}] "
                f"M-C {r['m_c_range'][0]}-{r['m_c_range'][1]} A, "
                f"centroid {r['centroid_d']} A (counted as one ligand)"
                for r in rings]
        if short_of.get(i):
            entry["impossible_contacts"] = sorted(short_of[i])
        rep.coordination.append(entry)

    # fragments + dimensionality (rank of translation mismatch lattice per fragment)
    visited = [False] * len(scs)
    isolated_seen: set[str] = set()
    for start in range(len(scs)):
        if visited[start]:
            continue
        comp, mismatches = [], []
        pos: dict[int, np.ndarray] = {start: np.zeros(3)}
        stack = [start]
        visited[start] = True
        while stack:
            u = stack.pop()
            comp.append(u)
            for v, shift, _kind in adj[u]:
                v_pos = pos[u] + np.array(shift)
                if not visited[v]:
                    visited[v] = True
                    pos[v] = v_pos
                    stack.append(v)
                else:
                    dv = v_pos - pos[v]
                    if np.any(np.abs(dv) > 1e-6):
                        mismatches.append(dv)
        dim = int(np.linalg.matrix_rank(np.array(mismatches))) if mismatches else 0
        el_counts: dict[str, int] = {}
        for u in comp:
            el_counts[elements[u]] = el_counts.get(elements[u], 0) + 1
        rep.fragments.append({"n_atoms": len(comp), "dimensionality": dim,
                              "elements": el_counts,
                              "asu_labels": sorted({labels[u] for u in comp})})
        # one entry per ASU label: the P1 copies of a lone atom are not
        # four different problems ('O007' x4 in the pa1 cage alert)
        if len(comp) == 1 and labels[comp[0]] not in isolated_seen:
            isolated_seen.add(labels[comp[0]])
            rep.isolated_atoms.append(labels[comp[0]])
    rep.fragments.sort(key=lambda f: -f["n_atoms"])
    rep.framework_dimensionality = max((f["dimensionality"] for f in rep.fragments),
                                       default=0)
    rep.fragment_census = _fragment_census(rep.fragments)
    rep.system_type, rep.system_type_evidence = classify_system(
        rep.fragments, rep.fragment_census, len(bonds), len(rep.pi_ligands))
    if ring_search_truncated:
        rep.system_type_evidence["ring_search_truncated"] = (
            "ring census stopped at the step budget (dense ghost-peak "
            "cluster?) - eta rings may be missed")
    return rep
