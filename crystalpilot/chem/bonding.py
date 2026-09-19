"""One bonding truth for the whole system: ONE ENGINE + ONE POST-PROCESSOR +
MANY CONSUMERS.

Why this module exists (round-2 plan R2.1, defects D8/D9/D10/D18): five
different bonding criteria are in the tree today and the same structure can
come out with a different edge set in the viewer, in `get_geometry`, in
`validate_structure` and in the front-end coordination table.

    1. `chem/connectivity.py`         27-image P1 search, sum(r_cov)+0.45,
                                      metal cutoffs from `MetalProfile`,
                                      flat 2.15 A ceiling on M-C
    2. `refine/scene.py`              raw smtbx table (tolerance 0.5 A)
    3. `report/structviews.py`        private `_COVALENT_R` table, x1.2 rule,
                                      no symmetry, no PART awareness
    4. `refine/inspect.py`            raw smtbx table (tolerance 0.5 A)
    5. `refine/nodes.py`              smtbx table minus every metal pair
       ::prune_long_metal_contacts    beyond the plain covalent sum
                                      (refine / chemaudit only)

ENGINE (unchanged, and deliberately not rewritten in numpy):
`smtbx.utils.connectivity_table` gives native SHELX PART semantics through
`conformer_indices` / `sym_excl_indices` (see `refine.nodes
.part_kwargs_from_parts`) and `extract_pair_sym_table(
all_interactions_from_inside_asu=True)` gives symmetry-exact cross-image
pairs, i.e. every neighbour of every ASU atom with the operator that places
it. A hand-rolled neighbour search loses that correctness, not just speed.

POST-PROCESSOR (this module): generalises `nodes.prune_long_metal_contacts`.
The engine's tolerance (sum(r_cov) + 0.5 A) is a *search radius*, not a
bonding criterion; every pair it returns is classified here, once, with the
rule that decided it recorded in `BondEdge.basis`.

CONSUMERS that will migrate to `bond_table()` (one consumer per commit, the
migration itself is main-thread work and is NOT done in this module):
    * `refine/inspect.py::_neighbor_table`      (and `get_geometry` with it)
    * `report/structviews.py::_bonds`           (deletes `_COVALENT_R`,
                                                 `_is_metalish`)
    * `refine/scene.py::_pair_sym_table`        (cache key bump)
    * `refine/tools_analysis.py::get_geometry`
    * `chem/connectivity.py::analyze_connectivity`  (keeps its 27-image
      periodic search; only the criterion source changes - highest risk)
    * the viewer / `CoordinationSection.tsx`    (per-atom `m: true`,
      per-bond kind code, no front-end `NON_METALS` list)

DECISION ORDER (every threshold from the cctbx element tables or from
`chem/knowledge.py::MetalProfile`; no element is special-cased for a test)

    0. engine pair (i, j, op, d), PART semantics already applied
    1. metal + metal, d <= sum(r_cov) + 0.40          -> metal_metal
       (longer metal-metal pairs are dropped: prune_long_metal_contacts)
    2. pair inside an eta-bound ring (Cp / arene), recognised by
       `connectivity._eta_rings` on the P1 expansion                -> eta
    3. metal + H  (explicit addition to the plan's order, see NOTE below)
    4. metal + non-metal donor (not C, not H) inside the `MetalProfile`
       window (unlisted metal: sum(r_cov) + 0.45)          -> coordination
    5. metal + carbon, not eta:
         a. the carbon is the apex of a chelate bite (it is bonded to a
            donor X - non-H, non-C, non-metal - that is itself bonded to
            the SAME metal at a SHORTER distance): the carboxylate /
            nitrate / amidinate C at 2.3-2.6 A          -> non_bonded_close
         b. d <= sum(r_cov)                                   -> covalent
         c. otherwise no edge at all (La...C(arene) 3.2 A, the false bond
            recorded in `nodes.prune_long_metal_contacts`)
    6. any remaining metal pair: d <= sum(r_cov)          -> coordination
       (outside the profile window but inside the covalent sum), else no
       edge - this is `prune_long_metal_contacts`, generalised
    7. non-metal pair, d <= sum(r_cov) + 0.45                 -> covalent
       (H...H is never a bond), else no edge

NOTE - two places where this module does NOT take the plan's wording
literally, both reported to the caller rather than done silently:

  * The plan writes rule 5 as "M-C > 2.15 A and not eta -> non_bonded_close".
    A flat 2.15 A is not an element-general rule: it is *below* a real
    Zr-CH3 (2.28 A), Mo-CH3 (2.20 A) or Ti-CH3 (2.18 A) sigma bond and
    *above* a Zn...C or Cu...C carboxylate bite. It also cannot separate
    Zr-CH3 2.28 (a bond) from Zr...C(carboxylate) 2.50 (not a bond), which
    are both > 2.15. What separates them is not distance but the graph: the
    carboxylate carbon is a 1-3 contact through an oxygen that is itself
    bonded to the metal. Hence 5a (element-general, any metal, any chelate)
    plus sum(r_cov) as the M-C sigma ceiling (5b), which drops the 3.2 A
    La...C(arene) contact the plan also requires to disappear.
  * Rule 3 (metal + H) is not in the plan's order at all. Without it the
    `MetalProfile` fallback window (max(sum+0.45, M-O window + 0.2)) makes
    a riding O-H / C-H hydrogen leaning at a large metal a *ligand* - the
    "Zr CN=11 with three O-H hydrogens counted" defect from the pa2 cage
    runs. An H that already carries a covalent bond to a heavier non-metal
    is reported as `non_bonded_close` (agostic / riding contact) and never
    counted in CN; a real terminal hydride (d <= sum(r_cov) + 0.15, no
    other heavy partner) stays `coordination`.

WHAT THIS MODULE DOES NOT DO: it does not touch any consumer, it does not
decide chemistry (plausibility of a coordination number lives in
`chem/knowledge.py::cn_status`, three-state and never a silent pass), and
it does not replace `connectivity.analyze_connectivity`'s periodic fragment
/ dimensionality analysis - only the criterion that feeds it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from .connectivity import covalent_radius
from .knowledge import element_symbol, is_metal, profile_for

# --- criterion constants (single place, quoted back in BondEdge.basis) -----
TOL_COVALENT = 0.45        # d <= sum(r_cov) + TOL -> covalent (non-metal pair)
TOL_METAL_METAL = 0.40     # d <= sum(r_cov) + TOL -> metal_metal
TOL_HYDRIDE = 0.15         # terminal M-H window above sum(r_cov)
ETA_MATCH_TOL = 0.02       # slack on the eta ring's reported M-C range

KIND_COVALENT = "covalent"
KIND_COORDINATION = "coordination"
KIND_ETA = "eta"
KIND_METAL_METAL = "metal_metal"
KIND_NON_BONDED = "non_bonded_close"
KINDS = (KIND_COVALENT, KIND_COORDINATION, KIND_ETA, KIND_METAL_METAL,
         KIND_NON_BONDED)
#: stable integer codes for the scene / viewer wire format
KIND_CODE = {KIND_COVALENT: 0, KIND_COORDINATION: 1, KIND_ETA: 2,
             KIND_METAL_METAL: 3, KIND_NON_BONDED: 4}

def element_of(scatterer) -> str:
    """Element symbol of a scatterer: 'Cu2+' / 'C ' / 'zr' -> 'Cu' / 'C' / 'Zr'."""
    return element_symbol(scatterer.scattering_type)


#: the ONE metal test of the system (chem.knowledge.is_metal, a periodic-
#: table whitelist); kept under this name for the consumers migrated first
is_metal_element = is_metal


@dataclass(frozen=True)
class BondEdge:
    """One classified interaction, oriented as the engine reports it: atom
    `i` sits on its stored site, atom `j` sits on `op * site_j`.

    op    symmetry operator string ('x,y,z' for a direct pair)
    d     unrounded distance; `d == unit_cell.distance(site_i, op * site_j)`
    kind  one of KINDS
    basis short string naming the rule that decided this edge
    """
    i: int
    j: int
    op: str
    d: float
    kind: str
    basis: str

    @property
    def is_symmetry_image(self) -> bool:
        return self.op.replace(" ", "") != "x,y,z"

    @property
    def kind_code(self) -> int:
        return KIND_CODE[self.kind]

    def as_tuple(self) -> tuple[int, int, int]:
        """Viewer wire format: [i, j, kind_code] (a 2-tuple unpack still works)."""
        return (self.i, self.j, KIND_CODE[self.kind])


class BondTable:
    """The classified bond table of one structure.

    Edges are stored in BOTH orientations, exactly as
    `extract_pair_sym_table(all_interactions_from_inside_asu=True)` reports
    them: `by_atom(i)` is then the complete, symmetry-correct coordination
    sphere of ASU atom i. (Keeping only i < j would be wrong for coordination
    numbers whenever i and j have different site symmetries - a metal on a
    4-fold axis lists four O images while each O lists one metal.)
    """

    def __init__(self, xs, edges: list[BondEdge], *, elements: list[str],
                 labels: list[str], eta_rings: list[dict],
                 eta_ring_of: dict[tuple[int, int, str], int],
                 suppressed: list[BondEdge], parts_applied: bool) -> None:
        self.xs = xs
        self.edges = edges
        self.elements = elements
        self.labels = labels
        self.eta_rings = eta_rings
        self._eta_ring_of = eta_ring_of
        self._suppressed = suppressed          # non_bonded_close, when hidden
        self._parts_applied = parts_applied
        self._by_atom: dict[int, list[BondEdge]] = {}
        for e in edges:
            self._by_atom.setdefault(e.i, []).append(e)

    # -- access ------------------------------------------------------------
    def by_atom(self, i: int) -> list[BondEdge]:
        """Every edge whose FIRST endpoint is ASU atom i (its neighbours)."""
        return list(self._by_atom.get(int(i), ()))

    def is_metal(self, i: int) -> bool:
        return is_metal_element(self.elements[int(i)])

    def cn(self, i: int) -> int:
        """Coordination number = LIGAND count of ASU atom i.

        `non_bonded_close` never counts (that is the point of the kind); a
        `metal_metal` contact is not a ligand either (the Zr...Zr 3.5 A edges
        of a Zr6 node, the Cu...Cu 2.6 A of a paddlewheel - listed apart by
        every consumer, never in the CN); an eta-bound ring counts ONCE, as
        one ligand, the way a crystallographer counts ferrocene as CN 2.
        """
        n = 0
        eta: list[BondEdge] = []
        for e in self.by_atom(i):
            if e.kind in (KIND_NON_BONDED, KIND_METAL_METAL):
                continue
            if e.kind == KIND_ETA:
                eta.append(e)
                continue
            n += 1
        return n + self._eta_ligands(i, eta)

    def _eta_ligands(self, i: int, eta: list[BondEdge]) -> int:
        """How many eta ligands the eta edges of atom i amount to.

        Counting the distinct ring RECORDS is not enough: the second Cp of a
        ferrocene sitting on an inversion centre is the symmetry image of the
        first, so both instances carry the same atom labels and would collapse
        into one ligand (CN 1 instead of 2). The physical instances are found
        from the graph instead - two eta edges belong to the same ring exactly
        when their two ring-atom IMAGES are covalently bonded to each other.
        """
        if not eta:
            return 0
        if not self.is_metal(i):
            # a ring carbon simply sees the metal once per ring it belongs to
            return len({self._eta_ring_of.get((e.i, e.j, e.op), -1)
                        for e in eta})
        from cctbx import sgtbx
        uc = self.xs.unit_cell()
        scs = list(self.xs.scatterers())
        sites = [sgtbx.rt_mx(e.op) * scs[e.j].site for e in eta]
        parent = list(range(len(eta)))

        def find(a: int) -> int:
            while parent[a] != a:
                parent[a] = parent[parent[a]]
                a = parent[a]
            return a

        for a in range(len(eta)):
            for b in range(a + 1, len(eta)):
                lim = (covalent_radius(self.elements[eta[a].j])
                       + covalent_radius(self.elements[eta[b].j]) + TOL_COVALENT)
                if float(uc.distance(sites[a], sites[b])) <= lim:
                    parent[find(a)] = find(b)
        return len({find(a) for a in range(len(eta))})

    def as_pair_sym_table(self) -> list[dict[int, list]]:
        """The classified edges in the shape of a cctbx pair_sym_table
        (`table[i][j] -> [rt_mx, ...]`, both orientations), so consumers
        written against `extract_pair_sym_table(...)` - the scene closure,
        growth and packing loops - read the truth without changing their
        loops. `non_bonded_close` edges are never in it."""
        from cctbx import sgtbx
        out: list[dict[int, list]] = [{} for _ in self.elements]
        for e in self.edges:
            if e.kind == KIND_NON_BONDED:
                continue
            out[e.i].setdefault(e.j, []).append(sgtbx.rt_mx(e.op))
        return out

    def kinds_of(self, i: int) -> dict[str, int]:
        out: dict[str, int] = {}
        for e in self.by_atom(i):
            out[e.kind] = out.get(e.kind, 0) + 1
        return out

    # -- reporting ---------------------------------------------------------
    def summary(self) -> dict[str, Any]:
        counts: dict[str, int] = {k: 0 for k in KINDS}
        for e in self.edges:
            counts[e.kind] = counts.get(e.kind, 0) + 1
        n_hidden = len(self._suppressed)
        return {
            "n_atoms": len(self.elements),
            "n_edges": len(self.edges),
            "kinds": counts,
            "n_non_bonded_close_hidden": n_hidden,
            "n_metals": sum(1 for e in self.elements if is_metal_element(e)),
            # symmetry-UNIQUE eta records, same convention as
            # connectivity.pi_ligands: ferrocene on an inversion centre has
            # one record and two ring instances (cn() counts the instances)
            "eta_rings": [
                {"metal": r["metal"], "hapticity": r["hapticity"],
                 "ring_atoms": list(r["ring_atoms"]),
                 "m_c_range": list(r["m_c_range"])}
                for r in self.eta_rings],
            "parts_applied": self._parts_applied,
            "engine": ("smtbx.utils.connectivity_table (search radius "
                       "sum(r_cov)+0.5 A) + extract_pair_sym_table("
                       "all_interactions_from_inside_asu=True)"),
            "criteria": {
                "covalent": f"d <= sum(r_cov) + {TOL_COVALENT}",
                "metal_metal": f"d <= sum(r_cov) + {TOL_METAL_METAL}",
                "coordination": ("MetalProfile M-O/M-N window + 0.05, "
                                 f"unlisted metal sum(r_cov) + {TOL_COVALENT}"),
                "eta": "chem.connectivity._eta_rings (geometric, Cp/arene)",
                "non_bonded_close": ("chelate bite M-X-C (1-3 through a "
                                     "shorter M-X bond); M...H-X contacts"),
                "dropped": ("metal pairs beyond sum(r_cov) "
                            "(prune_long_metal_contacts, generalised)"),
            },
            "note": ("edges are listed from BOTH endpoints (all interactions "
                     "from inside the ASU); cn() counts one eta ring INSTANCE "
                     "as one ligand and never counts non_bonded_close"),
        }


# --------------------------------------------------------------------- API
def bond_table(xs, parts: dict[str, int] | Sequence[int] | None = None, *,
               part_kwargs: dict | None = None,
               include_non_bonded: bool = False) -> BondTable:
    """Classify every interaction of `xs` once, for every consumer.

    xs      cctbx.xray.structure (the ASU; symmetry is handled by the engine)
    parts   SHELX PART numbers, either {label: part} or one int per
            scatterer. The sign is handled once, here and in
            `refine.nodes.part_kwargs_from_parts` (D10): |PART| selects the
            conformer, a NEGATIVE part additionally suppresses bonds to the
            atom's own symmetry equivalents (`sym_excl_indices`).
    part_kwargs
            the smtbx keyword form of the same information
            (`conformer_indices` / `sym_excl_indices`, as
            `refine.nodes.part_connectivity_kwargs` builds it from the
            session flags). Accepted so the existing consumers can hand over
            what they already have; it is converted back to signed PART
            numbers so there is exactly one code path. Ignored when `parts`
            is given.
    include_non_bonded
            False (default, what consumers want): `non_bonded_close` edges
            are kept out of `.edges` but still counted in `.summary()`.
            True: they are returned as edges, so a report can show the
            2.3-2.6 A carboxylate carbon without ever counting it as a bond.
    """
    import smtbx.utils

    from ..refine.nodes import part_kwargs_from_parts

    scs = list(xs.scatterers())
    elements = [element_of(sc) for sc in scs]
    labels = [str(sc.label) for sc in scs]
    uc = xs.unit_cell()
    if parts is None and part_kwargs:
        parts = parts_from_part_kwargs(part_kwargs, len(scs))
    part_list = _parts_list(parts, labels)
    kw = part_kwargs_from_parts(part_list) if any(part_list) else {}

    if len(scs) < 2:
        return BondTable(xs, [], elements=elements, labels=labels,
                         eta_rings=[], eta_ring_of={}, suppressed=[],
                         parts_applied=bool(kw))

    ct = smtbx.utils.connectivity_table(xs, **kw)
    pst = ct.pair_asu_table.extract_pair_sym_table(
        skip_j_seq_less_than_i_seq=False, all_interactions_from_inside_asu=True)

    # raw pairs, both orientations, with the exact operator and distance
    raw: list[tuple[int, int, Any, float]] = []
    for i, row in enumerate(pst):
        for j, ops in row.items():
            for op in ops:
                d = float(uc.distance(scs[i].site, op * scs[j].site))
                raw.append((i, int(j), op, d))

    eta_rings, eta_lookup = _eta_ring_pairs(xs, part_list)

    # provisional donor sphere of every metal, needed by the chelate-bite
    # rule; it depends only on rules that do not themselves use the bite.
    donors: dict[int, list[tuple[int, Any, float]]] = {}
    for i, j, op, d in raw:
        if not is_metal_element(elements[i]):
            continue
        ej = elements[j]
        if ej in ("H", "D") or ej == "C" or is_metal_element(ej):
            continue
        hi, _basis = _coordination_window(elements[i], ej)
        if d <= max(hi, covalent_radius(elements[i]) + covalent_radius(ej)):
            donors.setdefault(i, []).append((j, op, d))

    h_bonded = _heavy_partners(xs, pst, elements)

    edges: list[BondEdge] = []
    suppressed: list[BondEdge] = []
    eta_ring_of: dict[tuple[int, int, str], int] = {}
    for i, j, op, d in raw:
        kind, basis, ring = _classify(
            i, j, op, d, elements=elements, labels=labels, uc=uc, scs=scs,
            eta_lookup=eta_lookup, donors=donors, h_bonded=h_bonded)
        if kind is None:
            continue
        edge = BondEdge(i=i, j=j, op=str(op), d=d, kind=kind, basis=basis)
        if ring is not None:
            eta_ring_of[(i, j, str(op))] = ring
        if kind == KIND_NON_BONDED and not include_non_bonded:
            suppressed.append(edge)
            continue
        edges.append(edge)

    return BondTable(xs, edges, elements=elements, labels=labels,
                     eta_rings=eta_rings, eta_ring_of=eta_ring_of,
                     suppressed=suppressed, parts_applied=bool(kw))


# --------------------------------------------------------------- internals
def parts_from_part_kwargs(part_kwargs: dict | None, n: int) -> list[int]:
    """smtbx `conformer_indices` / `sym_excl_indices` -> signed PART list.

    Exact inverse of `refine.nodes.part_kwargs_from_parts`: the conformer
    index is |PART| and a non-zero sym_excl entry restores the minus sign.
    """
    if not part_kwargs:
        return [0] * n
    conf = [int(v) for v in (part_kwargs.get("conformer_indices") or [])]
    excl = [int(v) for v in (part_kwargs.get("sym_excl_indices") or [])]
    if conf and len(conf) != n:
        raise ValueError(f"conformer_indices has {len(conf)} entries for {n} atoms")
    if not conf:
        conf = [0] * n
    return [-c if (k < len(excl) and excl[k]) else c for k, c in enumerate(conf)]


def _parts_list(parts: dict[str, int] | Sequence[int] | None,
                labels: list[str]) -> list[int]:
    """{label: part} or a per-scatterer sequence -> signed per-scatterer list."""
    if not parts:
        return [0] * len(labels)
    if isinstance(parts, dict):
        by_label = {str(k).upper(): int(v or 0) for k, v in parts.items()}
        return [by_label.get(lb.upper(), 0) for lb in labels]
    out = [int(p or 0) for p in parts]
    if len(out) != len(labels):
        raise ValueError(f"parts has {len(out)} entries for {len(labels)} atoms")
    return out


def _coordination_window(metal_el: str, other_el: str) -> tuple[float, str]:
    """Upper bound of the metal-donor window, and the rule that set it.

    Same boundaries `connectivity._bond_cutoff` already uses, so migrating a
    consumer does not move any M-O / M-N distance; the difference is that an
    UNLISTED metal now gets an explicit, documented window instead of the
    generic covalent rule pretending to be knowledge (D9).
    """
    prof = profile_for(metal_el)
    base = covalent_radius(metal_el) + covalent_radius(other_el) + TOL_COVALENT
    if prof is None:
        return base, (f"unlisted metal {metal_el}: no MetalProfile, "
                      f"d <= sum(r_cov)+{TOL_COVALENT}")
    if other_el == "O":
        return prof.m_o_range[1] + 0.05, (
            f"MetalProfile {metal_el}-O window <= {prof.m_o_range[1]}+0.05")
    if other_el == "N" and prof.m_n_range:
        return prof.m_n_range[1] + 0.05, (
            f"MetalProfile {metal_el}-N window <= {prof.m_n_range[1]}+0.05")
    return max(base, prof.m_o_range[1] + 0.2), (
        f"MetalProfile {metal_el}: no {metal_el}-{other_el} window, "
        f"max(sum(r_cov)+{TOL_COVALENT}, M-O window+0.2)")


def _classify(i: int, j: int, op, d: float, *, elements, labels, uc, scs,
              eta_lookup, donors, h_bonded) -> tuple[str | None, str, int | None]:
    """The whole decision order. Returns (kind|None, basis, eta_ring_index)."""
    ei, ej = elements[i], elements[j]
    mi, mj = is_metal_element(ei), is_metal_element(ej)
    r_sum = covalent_radius(ei) + covalent_radius(ej)

    # 1. metal-metal
    if mi and mj:
        if d <= r_sum + TOL_METAL_METAL:
            return (KIND_METAL_METAL,
                    f"metal-metal d<=sum(r_cov)+{TOL_METAL_METAL} "
                    f"({r_sum:.2f}+{TOL_METAL_METAL})", None)
        return None, "", None

    # 2. eta ring (Cp / arene bound side-on), recognised by connectivity
    if mi or mj:
        m_lab = labels[i] if mi else labels[j]
        o_lab = labels[j] if mi else labels[i]
        ring = _eta_match(eta_lookup, m_lab, o_lab, d)
        if ring is not None:
            return (KIND_ETA,
                    "eta ring (connectivity._eta_rings: flat all-C ring, "
                    "equidistant from one metal image, metal on the normal)",
                    ring)

    # 3. metal-hydrogen: a riding / agostic H is not a ligand
    if (mi or mj) and (ei in ("H", "D") or ej in ("H", "D")):
        h_idx = i if ei in ("H", "D") else j
        if h_bonded[h_idx]:
            return (KIND_NON_BONDED,
                    "M...H-X: the H already has a covalent heavy partner "
                    "(riding / agostic contact), never a ligand", None)
        if d <= r_sum + TOL_HYDRIDE:
            return (KIND_COORDINATION,
                    f"terminal hydride d<=sum(r_cov)+{TOL_HYDRIDE}", None)
        return None, "", None

    if mi or mj:
        # rules 4 and 5 are disjoint (carbon vs any other donor), so the
        # carbon branch is tested first even though it is numbered second
        m_idx, o_idx = (i, j) if mi else (j, i)
        m_el, o_el = elements[m_idx], elements[o_idx]
        # 5. metal-carbon
        if o_el == "C":
            bridge = _bite_bridge(i, j, op, d, mi=mi, uc=uc, scs=scs,
                                  elements=elements, donors=donors)
            if bridge is not None:
                return (KIND_NON_BONDED,
                        f"chelate bite {m_el}-{elements[bridge]}-C: the C is "
                        "1-3 through a shorter metal-donor bond, not a bond",
                        None)
            if d <= r_sum:
                return (KIND_COVALENT,
                        f"M-C sigma bond d<=sum(r_cov) ({r_sum:.2f})", None)
            return None, "", None
        # 4. metal-donor window
        hi, basis = _coordination_window(m_el, o_el)
        if d <= hi:
            return KIND_COORDINATION, basis, None
        # 6. outside the window but still inside the covalent sum
        if d <= r_sum:
            return (KIND_COORDINATION,
                    f"outside the {m_el} profile window but d<=sum(r_cov) "
                    f"({r_sum:.2f})", None)
        return None, "", None

    # 7. plain non-metal pair
    if ei in ("H", "D") and ej in ("H", "D"):
        return None, "", None
    if d <= r_sum + TOL_COVALENT:
        return (KIND_COVALENT,
                f"d<=sum(r_cov)+{TOL_COVALENT} ({r_sum:.2f}+{TOL_COVALENT})",
                None)
    return None, "", None


def _bite_bridge(i: int, j: int, op, d: float, *, mi: bool, uc, scs,
                 elements, donors) -> int | None:
    """Index of the donor X making an M...C pair the apex of a chelate bite.

    The pair is (site_i, op*site_j). Move into the metal's own frame - if the
    metal is `j`, apply op^-1 to both sites - so the metal's donor operators
    (which the pair table lists from the metal's stored site) and the carbon
    image live in one coordinate frame; then a plain unit-cell distance is
    the true X...C distance.
    """
    if mi:
        m_idx = i
        c_site = op * scs[j].site
    else:
        m_idx = j
        c_site = op.inverse() * scs[i].site
    r_c = covalent_radius("C")
    for k, op_k, d_k in donors.get(m_idx, ()):
        if d_k >= d:
            continue                       # the bridge must be the closer atom
        x_site = op_k * scs[k].site
        d_xc = float(uc.distance(x_site, c_site))
        if d_xc <= covalent_radius(elements[k]) + r_c + TOL_COVALENT:
            return k
    return None


def _eta_match(eta_lookup, metal_label: str, other_label: str,
               d: float) -> int | None:
    for lo, hi, ring in eta_lookup.get(
            (metal_label.upper(), other_label.upper()), ()):
        if lo - ETA_MATCH_TOL <= d <= hi + ETA_MATCH_TOL:
            return ring
    return None


def _eta_ring_pairs(xs, part_list: list[int]):
    """(unique eta ring records, {(metal_label, C_label): [(lo, hi, ring)]}).

    `connectivity._eta_rings` is reused as-is (imported, never modified): it
    wants a P1 expansion plus that expansion's sigma graph with integer cell
    shifts. Both are built from the SAME engine, on a P1 copy whose sites are
    wrapped into [0,1) - in P1 every symmetry operator is a pure lattice
    translation, so its translation part IS the cell shift the ring search
    needs. Skipped entirely when the structure has no metal or no carbon.

    The ring records come back naming ATOM LABELS, and an ASU pair is matched
    to a ring by (metal label, ring-atom label) plus the ring's own M-C
    distance window: that is what makes a ring generated by symmetry (both Cp
    of a ferrocene on an inversion centre carry the same labels) match from
    every image. It assumes ASU labels are unique, which SHELX guarantees.
    """
    import numpy as np
    from cctbx.array_family import flex

    from .connectivity import Bond, _eta_rings

    scs = list(xs.scatterers())
    elements = [element_of(sc) for sc in scs]
    if not any(is_metal_element(e) for e in elements) or "C" not in elements:
        return [], {}

    # wrap in place: the ring search adds integer cell shifts to these sites,
    # so they must be the [0,1) representatives (same convention as
    # analyze_connectivity). set_sites_frac keeps the scattering-type
    # registry the source structure already carries.
    wrapped = xs.expand_to_p1()
    wrapped.set_sites_frac(flex.vec3_double(
        [tuple(float(v) % 1.0 for v in s) for s in wrapped.sites_frac()]))

    labels = [str(sc.label) for sc in wrapped.scatterers()]
    els = [element_of(sc) for sc in wrapped.scatterers()]
    by_label = {lb.upper(): p for lb, p in zip(
        [str(sc.label) for sc in scs], part_list) if p}
    p1_parts = [by_label.get(lb.upper(), 0) for lb in labels]

    import smtbx.utils

    from ..refine.nodes import part_kwargs_from_parts
    kw = part_kwargs_from_parts(p1_parts) if any(p1_parts) else {}
    ct = smtbx.utils.connectivity_table(wrapped, **kw)
    pst = ct.pair_asu_table.extract_pair_sym_table(
        skip_j_seq_less_than_i_seq=True, all_interactions_from_inside_asu=True)
    uc = wrapped.unit_cell()
    w_scs = list(wrapped.scatterers())
    bonds: list[Bond] = []
    for i, row in enumerate(pst):
        for j, ops in row.items():
            for op in ops:
                d = float(uc.distance(w_scs[i].site, op * w_scs[j].site))
                if d > (covalent_radius(els[i]) + covalent_radius(els[int(j)])
                        + TOL_COVALENT):
                    continue
                t = op.t().as_double()
                shift = tuple(int(round(v)) for v in t)
                bonds.append(Bond(i, int(j), shift, d))

    frac = np.array([[float(x) for x in sc.site] for sc in w_scs])
    ortho = np.array(uc.orthogonalization_matrix()).reshape(3, 3)
    records, _truncated = _eta_rings(els, labels, frac, ortho, bonds)

    uniq: dict[tuple, dict] = {}
    lookup: dict[tuple[str, str], list[tuple[float, float, int]]] = {}
    for rec in records:
        key = (rec["metal"].upper(), frozenset(a.upper() for a in rec["ring_atoms"]))
        if key in uniq:
            continue
        idx = len(uniq)
        uniq[key] = {k: v for k, v in rec.items()
                     if k not in ("metal_index", "metal_shift",
                                  "ring_indices", "ring_shifts")}
        lo, hi = rec["m_c_range"]
        for atom in rec["ring_atoms"]:
            lookup.setdefault((rec["metal"].upper(), atom.upper()), []).append(
                (float(lo), float(hi), idx))
    return list(uniq.values()), lookup


def _heavy_partners(xs, pst, elements) -> list[bool]:
    """Per atom: is this an H with a covalent bond to a non-metal heavy atom?

    That is what separates a riding / agostic X-H leaning at a metal (never a
    ligand, however close) from a terminal hydride (which has no other
    partner) - element-general, no distance constant involved.
    """
    uc = xs.unit_cell()
    scs = list(xs.scatterers())
    out = [False] * len(elements)
    for i, row in enumerate(pst):
        if elements[i] not in ("H", "D"):
            continue
        flag = False
        for j, ops in row.items():
            ej = elements[int(j)]
            if ej in ("H", "D") or is_metal_element(ej):
                continue
            lim = covalent_radius(elements[i]) + covalent_radius(ej) + TOL_COVALENT
            for op in ops:
                if float(uc.distance(scs[i].site, op * scs[int(j)].site)) <= lim:
                    flag = True
        out[i] = flag
    return out


def bond_table_edges_for_scene(table: BondTable) -> list[list[int]]:
    """[i, j, kind_code] triples for the viewer wire format (D8 front-end
    step): `const [i, j] = bond` keeps working on a triple."""
    return [[e.i, e.j, KIND_CODE[e.kind]] for e in table.edges]
