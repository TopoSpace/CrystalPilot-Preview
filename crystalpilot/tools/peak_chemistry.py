"""Element tiering and geometric motif reading for a metal-free peak list.

`interpret_peaks` used to look at every structure through the
metal-coordination lens: the strongest peaks became the metal, everything
inside the M-O window became O, the rest became C. On an organic there is
no metal, so that lens turns a chloride into a "metal centre" and reads
C-Cl contacts as coordination. Nothing here knows about any particular
crystal; the two rules are:

* DENSITY TIER. The integrated density around a site scales with the
  atom's electron count, so a ratio against the light-atom sea says which
  Z tier a site belongs to. C -> O is a 33 % step in Z and survives an
  unrefined solution map; C -> N is 17 % and N -> O is 14 %, which do not.
  So O is assigned by tier and C/N is NEVER guessed - a site below the
  C/O line is labelled C and flagged uncertain, and the composition's
  nitrogen allowance is disclosed instead of being spent.
* DISTANCE GEOMETRY. Heavy non-metals (P, S, Cl, Br, I ...) are anchors:
  they dominate the map like a metal but they are not coordination
  centres, so they get their own element by tier and then serve as
  distance references for motif reading.

Both rules are expressed in atomic numbers and bond-length windows that
hold for any element, never in constants fitted to one structure.
"""
from __future__ import annotations

import math
from statistics import median
from typing import Any

from ..chem.connectivity import covalent_radius
from ..chem.knowledge import is_metal
from ..chem.solvability import SI_Z, atomic_number

#: a non-metal heavier than Si is a density ANCHOR, not a metal centre.
ANCHOR_Z_MIN = SI_Z + 1
#: the light-atom sea this method measures every ratio against.
REF_Z = 6                                    # carbon
#: two elements are separable by density alone only when their atomic
#: numbers differ by more than this fraction of the lighter one. C->O is
#: 33 % (resolved by an unrefined solution map); C->N is 17 % and needs a
#: converged Ueq. The line sits between the two, so it is a property of
#: the method, not of any crystal.
SEPARABLE_Z_FRAC = 0.25
#: peak integration on an unrefined solution map reproduces to about this
#: fraction, so a ratio this close to a decision line is borderline.
BORDERLINE_FRAC = 0.10

HALOGENS = frozenset({"F", "Cl", "Br", "I", "At"})


def expected_ratio(z: int) -> float:
    """Density ratio a site of atomic number `z` should show vs carbon."""
    return float(z) / REF_Z


def tier_line(z_low: int, z_high: int) -> float:
    """Even-odds line between two elements: the geometric midpoint of
    their expected ratios, i.e. the midpoint in log space, so the test is
    symmetric in both directions and carries no fitted constant."""
    return math.sqrt(expected_ratio(z_low) * expected_ratio(z_high))


def split_elements(elements) -> tuple[list[str], list[str], list[str]]:
    """(metal centres, heavy non-metal anchors, light elements)."""
    metals, anchors, light = [], [], []
    for el in elements:
        sym = str(el).strip().capitalize()
        if sym in ("H", "D", ""):
            continue
        z = atomic_number(sym) or 0
        if is_metal(sym):
            metals.append(sym)
        elif z >= ANCHOR_Z_MIN:
            anchors.append(sym)
        else:
            light.append(sym)
    metals.sort(key=lambda e: -(atomic_number(e) or 0))
    anchors.sort(key=lambda e: -(atomic_number(e) or 0))
    light.sort(key=lambda e: atomic_number(e) or 0)
    return metals, anchors, light


def _competitors(sym: str, pool: list[str]) -> list[str]:
    """Declared elements this method cannot tell `sym` apart from."""
    z = atomic_number(sym) or 0
    out = []
    for other in pool:
        if other == sym:
            continue
        zo = atomic_number(other) or 0
        if z and abs(zo - z) / float(z) < SEPARABLE_Z_FRAC:
            out.append(other)
    return out


def _judge(sym: str, ratio: float, declared: list[str], line: float
           ) -> tuple[str, bool, str]:
    """(confidence, element_uncertain, reason) for one tier assignment."""
    z = atomic_number(sym) or 0
    rivals = _competitors(sym, declared)
    borderline = ratio < line * (1.0 + BORDERLINE_FRAC)
    bits = [f"density ratio {ratio:.2f} vs the light-atom reference "
            f"(expected {expected_ratio(z):.2f} for {sym}, tier line "
            f"{line:.2f})"]
    if rivals:
        bits.append(
            f"{'/'.join(rivals)} differ from {sym} by less than "
            f"{SEPARABLE_Z_FRAC:.0%} in Z - not separable by density on an "
            f"unrefined map")
        return ("low" if borderline else "medium"), True, "; ".join(bits)
    if borderline:
        bits.append(f"within {BORDERLINE_FRAC:.0%} of the tier line - "
                    f"peak integration is not that reproducible here")
        return "medium", True, "; ".join(bits)
    return "high", False, "; ".join(bits)


def assign_metal_free(densities: list[float], budget: dict[str, float],
                      declared: list[str], composition_known: bool
                      ) -> tuple[list[str], list[dict[str, Any]],
                                 dict[str, Any]]:
    """Elements for a metal-free peak list, by density tier only.

    `densities` are per accepted peak, in the order the peaks were
    accepted. Returns (elements, per-peak rows, tier context).
    """
    n = len(densities)
    _metals, anchor_els, light_els = split_elements(declared)
    if not composition_known:
        # nothing declared: the light candidates that any organic can
        # hold, so the C/N flag below is raised rather than suppressed
        light_els = ["C", "N", "O"]
    judged_pool = anchor_els + light_els

    order = sorted(range(n), key=lambda i: -densities[i])
    anchor_plan: list[tuple[str, int]] = []
    for el in anchor_els:
        anchor_plan.append((el, max(1, int(round(budget.get(el, 1.0))))))
    n_anchor = min(sum(c for _, c in anchor_plan), n)
    n_o_budget = (max(0, int(round(budget.get("O", 0.0))))
                  if composition_known else None)

    # reference = the carbon sea: the peaks left once the anchors and the
    # O allowance are set aside. Median, so a few stragglers cannot move it.
    skip = n_anchor + (n_o_budget if n_o_budget is not None else 0)
    pool = [densities[i] for i in order[skip:]]
    if len(pool) < 3:
        pool = [densities[i] for i in order[n_anchor:]] or list(densities)
    ref = median(pool) if pool else 0.0
    if ref <= 0:
        ref = median([d for d in densities if d > 0] or [1.0])

    elements: list[str | None] = [None] * n
    rows: list[dict[str, Any]] = [{} for _ in range(n)]
    queue = list(order)

    # 1. anchors - heaviest first, each only while it stands above its
    #    own tier line over the light sea
    for el, count in anchor_plan:
        z = atomic_number(el) or 0
        line = tier_line(REF_Z, z)
        taken = 0
        for i in list(queue):
            if taken >= count:
                break
            r = densities[i] / ref if ref else 0.0
            if r < line:
                break                      # peaks only get weaker from here
            conf, unc, why = _judge(el, r, judged_pool, line)
            elements[i] = el
            rows[i] = {"element": el, "element_uncertain": unc,
                       "element_confidence": conf, "reason": why,
                       "density_ratio": round(r, 2)}
            queue.remove(i)
            taken += 1

    # 2. O by density tier; everything else is C (C/N is never guessed)
    line_co = tier_line(REF_Z, 8)
    o_allowed = ("O" in light_els) or not composition_known
    o_slots = (n_o_budget if n_o_budget is not None else len(queue))
    n_o = 0
    for i in queue:
        r = densities[i] / ref if ref else 0.0
        if o_allowed and n_o < o_slots and r >= line_co:
            conf, unc, why = _judge("O", r, judged_pool, line_co)
            if not composition_known:
                conf, unc = "low", True
                why += ("; no composition was declared, so the O tier is "
                        "read from the peak list alone")
            elements[i] = "O"
            rows[i] = {"element": "O", "element_uncertain": unc,
                       "element_confidence": conf, "reason": why,
                       "density_ratio": round(r, 2)}
            n_o += 1
            continue
        # C tier. C/N is 17 % in Z: not a decision this stage can make,
        # so the site is labelled C and flagged, never "decided".
        rivals = _competitors("C", judged_pool)
        near_line = r >= line_co / (1.0 + BORDERLINE_FRAC)
        if r >= line_co and o_allowed and n_o >= o_slots:
            # in the O tier, but the composition's O allowance is spent -
            # say which fact decided this, because it is the composition
            # and not the density
            why = (f"density ratio {r:.2f} reaches the C/O tier line "
                   f"{line_co:.2f}, but the composition's O allowance "
                   f"({o_slots} per ASU) is already taken by stronger "
                   f"peaks; this site could be the O and one of those "
                   f"could be this")
        elif r >= line_co and not o_allowed:
            why = (f"density ratio {r:.2f} reaches the C/O tier line "
                   f"{line_co:.2f}, but the composition declares no "
                   f"oxygen - either the composition is wrong or this "
                   f"site is heavier than the label says")
        else:
            why = (f"density ratio {r:.2f} vs the light-atom reference is "
                   f"below the C/O tier line {line_co:.2f}")
        if rivals:
            why += (f"; {'/'.join(rivals)} cannot be told from C by "
                    f"density (<{SEPARABLE_Z_FRAC:.0%} in Z) - labelled C "
                    f"by convention, not identified")
        else:
            why += "; no element within the unresolvable band is declared"
        if near_line and r < line_co:
            why += (f"; within {BORDERLINE_FRAC:.0%} of the C/O line, so O "
                    f"is not excluded either")
        conf = "low" if (rivals or near_line) else "medium"
        row = {"element": "C", "element_uncertain": True,
               "element_confidence": conf, "reason": why,
               "density_ratio": round(r, 2)}
        if r < tier_line(1, REF_Z):
            # below even the H/C line: not a full-weight light atom.
            # Either a partly occupied site or map noise - say so rather
            # than let it pass as an ordinary carbon.
            row["element_confidence"] = "low"
            row["below_light_atom_tier"] = True
            row["reason"] = (
                f"density ratio {r:.2f} is below the H/C line "
                f"{tier_line(1, REF_Z):.2f}: too little density for a "
                f"full-weight light atom - a partly occupied site, a "
                f"disorder component, or map noise")
        elements[i] = "C"
        rows[i] = row

    context = {
        "reference_density": round(float(ref), 3),
        "reference": ("median of the peaks left after the anchor and O "
                      "allowances - the light-atom (carbon) sea"),
        "tier_lines": {
            "C/O": round(line_co, 3),
            **{f"C/{el}": round(tier_line(REF_Z, atomic_number(el) or 0), 3)
               for el, _ in anchor_plan},
        },
        "rule": (f"a site is assigned the element whose expected density "
                 f"ratio Z/{REF_Z} its measured ratio reaches; two "
                 f"elements closer than {SEPARABLE_Z_FRAC:.0%} in Z are "
                 f"not separable this way and the lighter label is used "
                 f"with element_uncertain=true"),
        "n_anchor_sites": sum(1 for e in elements if e in anchor_els),
        "n_o_assigned": n_o,
    }
    return [e or "C" for e in elements], rows, context


# --------------------------------------------------------------------- #
# geometry -> organic vocabulary
# --------------------------------------------------------------------- #

#: distance-only neighbour cutoff: covers C-C 1.54, C-O 1.43, C-S 1.82,
#: C-Cl 1.75, C-Br 1.94, C-I 2.14 - the longest single bond an organic
#: light/anchor pair makes.
BOND_CUTOFF_A = 2.25
#: a delocalised ring bond is measurably SHORTER than the single-bond sum
#: of the pair's covalent radii, whatever the elements are: benzene C-C
#: 0.91, pyrrole C-N 0.93, thiophene C-S 0.95, furan C-O 0.96 - while a
#: saturated ring sits at ~1.01 (cyclohexane) . The line goes between.
DELOCALISED_BOND_FRAC = 0.97
#: a delocalised ring is flat; this is the rms a freshly interpreted,
#: unrefined site set can still show while being planar.
RING_PLANE_RMS_A = 0.12


def bond_graph(xs, cutoff: float = BOND_CUTOFF_A) -> list[list[tuple]]:
    """Per ASU atom: [(j, sym_op, distance)] purely by distance."""
    pat = xs.pair_asu_table(distance_cutoff=cutoff)
    pst = pat.extract_pair_sym_table(
        skip_j_seq_less_than_i_seq=False, all_interactions_from_inside_asu=True)
    uc = xs.unit_cell()
    scs = list(xs.scatterers())
    out: list[list[tuple]] = []
    for i in range(len(scs)):
        nb = []
        for j, ops in pst[i].items():
            for op in ops:
                d = float(uc.distance(scs[i].site, op * scs[j].site))
                if 0.4 < d <= cutoff:
                    nb.append((int(j), op, d))
        nb.sort(key=lambda t: t[2])
        out.append(nb)
    return out


def _is_chordless(graph, ring: list[int]) -> bool:
    """No bond between two ring members that are not ring neighbours.

    A benzene ring is chordless; a "ring" traced through a stray peak
    sitting beside a real one is not, and neither is the union of two
    fused rings. Keeps the motif count honest without a full SSSR."""
    pos = {v: k for k, v in enumerate(ring)}
    n = len(ring)
    for a in ring:
        for j, _op, _d in graph[a]:
            if j in pos and j != a:
                sep = abs(pos[a] - pos[j])
                if min(sep, n - sep) > 1:
                    return False
    return True


def find_rings(graph, sizes=(5, 6), max_paths: int = 20000
               ) -> list[list[int]]:
    """Real, chordless rings of the given sizes.

    A cycle in the ASU quotient graph is only a ring when the composed
    symmetry operators return to the identity - otherwise it is a
    translation loop through the lattice, not a molecular ring. Bounded
    by `max_paths` so a dense graph cannot turn this into a long walk.
    """
    rings: list[list[int]] = []
    seen: set[tuple[int, ...]] = set()
    budget = [max_paths]
    limit = max(sizes)

    def walk(start: int, node: int, op, path: list[int], visited: set) -> None:
        if budget[0] <= 0:
            return
        for j, nop, _d in graph[node]:
            budget[0] -= 1
            if budget[0] <= 0:
                return
            composed = op.multiply(nop) if op is not None else nop
            if j == start:
                if len(path) in sizes and composed.is_unit_mx():
                    key = tuple(sorted(path))
                    if key not in seen and _is_chordless(graph, path):
                        seen.add(key)
                        rings.append(list(path))
                continue
            if j in visited or len(path) >= limit:
                continue
            walk(start, j, composed, path + [j], visited | {j})

    for i in range(len(graph)):
        walk(i, i, None, [i], {i})
    return rings


def _plane_rms(uc, sites) -> float:
    """RMS deviation of cartesian points from their best plane."""
    import numpy as np
    pts = np.array([uc.orthogonalize(s) for s in sites], dtype=float)
    c = pts - pts.mean(axis=0)
    try:
        normal = np.linalg.svd(c)[2][-1]
    except np.linalg.LinAlgError:
        return float("nan")
    return float(np.sqrt(np.mean((c @ normal) ** 2)))


def organic_motifs(xs) -> list[dict[str, Any]]:
    """Chemical vocabulary read from the model's own geometry.

    Every test below is a bond-length or angle window that holds for the
    element pair anywhere in chemistry; nothing consults a label, a file
    or a composition. Motifs that would need a nitrogen are reported in
    their geometry-only form, because this stage never types C vs N.
    """
    scs = list(xs.scatterers())
    els = [sc.scattering_type.strip().capitalize() for sc in scs]
    labels = [sc.label for sc in scs]
    uc = xs.unit_cell()
    graph = bond_graph(xs)
    found: dict[str, dict[str, Any]] = {}

    def add(motif: str, atom: str, evidence: str) -> None:
        row = found.setdefault(motif, {"motif": motif, "n": 0, "atoms": [],
                                       "evidence": evidence})
        row["n"] += 1
        if len(row["atoms"]) < 6:
            row["atoms"].append(atom)

    light = {"C", "N", "O", "B", "F"}
    for i, el in enumerate(els):
        nbrs = graph[i]
        o_nb = [(j, d) for j, _op, d in nbrs if els[j] == "O"]
        light_nb = [(j, d) for j, _op, d in nbrs if els[j] in light]
        if el == "C":
            short_o = [(j, d) for j, d in o_nb if 1.15 <= d <= 1.45]
            if len(short_o) == 2:
                d1, d2 = sorted(d for _, d in short_o)
                if d2 - d1 <= 0.06:
                    add("carboxylate",
                        labels[i],
                        f"C bonded to 2 O at {d1:.2f}/{d2:.2f} A, equal "
                        f"within 0.06 A - a delocalised CO2 group")
                else:
                    add("carboxylic_acid_or_ester", labels[i],
                        f"C bonded to 2 O at {d1:.2f}/{d2:.2f} A - one "
                        f"short C=O and one longer C-O(H/R)")
            elif len(short_o) == 1:
                d_co = short_o[0][1]
                partners = [d for j, d in light_nb
                            if j != short_o[0][0] and 1.28 <= d <= 1.42]
                if d_co <= 1.32 and partners:
                    add("amide_or_ester_like", labels[i],
                        f"sp2 C with one C=O at {d_co:.2f} A and a "
                        f"shortened single bond at {min(partners):.2f} A "
                        f"to a light atom whose element was not typed "
                        f"(C/N undecided) - amide, ester or acid")
        if el in ("S", "P") and len([d for _, d in o_nb
                                     if 1.35 <= d <= 1.65]) >= 3:
            add("sulfonate_or_phosphonate", labels[i],
                f"{el} with {len([d for _, d in o_nb if 1.35 <= d <= 1.65])} "
                f"O at 1.35-1.65 A - a tetrahedral oxo-anion head group")
        if el == "S":
            two = [d for _, _op, d in nbrs if 1.65 <= d <= 1.90]
            if len(two) >= 2:
                add("thioether_or_thiophene", labels[i],
                    f"S with 2 bonds at {two[0]:.2f}/{two[1]:.2f} A - a "
                    f"divalent, covalently bound sulfur (not a metal "
                    f"centre and not a sulfate)")
        if el in HALOGENS:
            near = [d for _, _op, d in nbrs]
            if not near or min(near) > 2.2:
                add("halide_ion", labels[i],
                    f"{el} with no neighbour inside {BOND_CUTOFF_A} A - "
                    f"an unbound halide (counter-ion / lattice site), not "
                    f"a coordination centre")
            elif min(near) >= 1.55:
                add("covalent_halogen", labels[i],
                    f"{el} with one bond at {min(near):.2f} A - "
                    f"covalently attached halogen substituent")
        if el == "O" and (not nbrs or min(d for _, _op, d in nbrs) > 1.65):
            add("isolated_O_solvent_candidate", labels[i],
                "O with no bond inside 1.65 A - water, solvent or a "
                "counter-ion candidate rather than a framework atom")
        if el == "C" and len(o_nb) == 1 and 1.15 <= o_nb[0][1] <= 1.26:
            single = [d for j, d in light_nb
                      if j != o_nb[0][0] and 1.44 <= d <= 1.58]
            if len(single) >= 1 and not [d for j, d in light_nb
                                         if j != o_nb[0][0] and d < 1.44]:
                add("ketone_or_aldehyde", labels[i],
                    f"sp2 C with one C=O at {o_nb[0][1]:.2f} A and only "
                    f"full-length single bonds ({min(single):.2f} A) to its "
                    f"other neighbours - a ketone/aldehyde carbonyl, not an "
                    f"ester or amide")
        if el == "C":
            singles = [d for _, _op, d in nbrs if 1.48 <= d <= 1.65]
            short = [d for _, _op, d in nbrs if d < 1.48]
            if len(singles) >= 2 and not short:
                add("sp3_alkyl_carbon", labels[i],
                    f"C with {len(singles)} bonds of 1.48-1.65 A and none "
                    f"shorter - a saturated (alkyl) centre, not part of a "
                    f"conjugated system")

    try:
        for ring in find_rings(graph):
            sites = []
            op = None
            prev = ring[0]
            sites.append(scs[prev].site)
            for nxt in ring[1:]:
                edge = min((e for e in graph[prev] if e[0] == nxt),
                           key=lambda e: e[2], default=None)
                if edge is None:
                    break
                op = op.multiply(edge[1]) if op is not None else edge[1]
                sites.append(op * scs[nxt].site)
                prev = nxt
            if len(sites) != len(ring):
                continue
            bonds, ratios = [], []
            for k in range(len(ring)):
                a, b = sites[k], sites[(k + 1) % len(ring)]
                d = float(uc.distance(tuple(a), tuple(b)))
                pair = covalent_radius(els[ring[k]]) + covalent_radius(
                    els[ring[(k + 1) % len(ring)]])
                bonds.append(d)
                ratios.append(d / pair if pair else 1.0)
            rms = _plane_rms(uc, sites)
            name = ",".join(labels[k] for k in ring)
            worst = max(ratios)
            if worst <= DELOCALISED_BOND_FRAC and rms <= RING_PLANE_RMS_A:
                add("aromatic_ring", name,
                    f"{len(ring)}-membered planar ring (rms {rms:.3f} A "
                    f"from its best plane), every bond "
                    f"{min(bonds):.2f}-{max(bonds):.2f} A, i.e. "
                    f"{min(ratios):.2f}-{worst:.2f} of the single-bond sum "
                    f"of covalent radii for its own element pair - "
                    f"delocalised, not single bonds")
            elif worst <= 1.10:
                add("saturated_ring", name,
                    f"{len(ring)}-membered ring, bonds "
                    f"{min(bonds):.2f}-{max(bonds):.2f} A "
                    f"({min(ratios):.2f}-{worst:.2f} of the covalent-radius "
                    f"sum), rms {rms:.3f} A from plane - saturated, no "
                    f"delocalisation")
    except Exception:  # noqa: BLE001 - a hint must never fail the tool
        pass

    # three or more saturated centres in one model is a chain, not a
    # scattering of isolated sp3 atoms - name it that way
    sp3 = found.pop("sp3_alkyl_carbon", None)
    if sp3 is not None:
        if sp3["n"] >= 3:
            sp3["motif"] = "alkyl_chain"
        found[sp3["motif"]] = sp3
    return sorted(found.values(), key=lambda r: (-r["n"], r["motif"]))
