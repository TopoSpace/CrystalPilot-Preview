"""ASU coherence analysis + reassembly planning (expert-review red flags).

An Olex2 user sees the ASU as the identity-bond graph. Atoms refined into a
symmetry image of their chemically bonded position LOOK detached ("the atom
exists but does not connect to the asymmetric unit" - reviewer feedback,
2026-08-29), and ghost atoms added to soak up residual density have no
bonding environment at all plus inflated ADPs. analyze_connectivity() works
in P1 so it can see neither problem; this module works on the ASU graph.

- asu_coherence(xs)      -> red-flag report (detached fragments, ghosts)
- asu_assembly_plan(xs)  -> compaq-style ops that reunite the ASU
- apply_assembly_plan(xs, plan) -> new xray.structure with ops applied
  (sites transformed, aniso ADPs rotated, special positions re-derived)
"""
from __future__ import annotations

from typing import Any

from .connectivity import LONE_ION_ELEMENTS, _bond_cutoff


def _pair_sym_table(xs, tol: float = 0.45):
    """pair_sym_table over the ASU with a generous element-aware cutoff."""
    from cctbx import crystal as cctbx_crystal
    scs = list(xs.scatterers())
    elements = [sc.scattering_type.strip().capitalize() for sc in scs]
    uniq = sorted(set(elements))
    max_cut = 0.0
    for ei in uniq:
        for ej in uniq:
            max_cut = max(max_cut, _bond_cutoff(ei, ej, tol))
    asu_mappings = xs.asu_mappings(buffer_thickness=max_cut + 0.2)
    pat = cctbx_crystal.pair_asu_table(asu_mappings=asu_mappings)
    pat.add_all_pairs(distance_cutoff=max_cut)
    return pat.extract_pair_sym_table(), elements


def _identity_fragments(xs, pst, elements):
    """Connected components of the identity-op bond graph.

    Returns (fragments big->small as sorted index lists, sym_links) where
    sym_links are {i, j, op, d} for pairs bonded through a NON-identity op.
    """
    scs = list(xs.scatterers())
    uc = xs.unit_cell()
    n = len(scs)
    adj: list[set[int]] = [set() for _ in range(n)]
    sym_links: list[dict] = []
    for i, pd in enumerate(pst):
        for j, ops in pd.items():
            j = int(j)
            cut = _bond_cutoff(elements[i], elements[j])
            for op in ops:
                d = uc.distance(scs[i].site, op * scs[j].site)
                if d > cut or d < 0.3:
                    continue
                if op.is_unit_mx():
                    adj[i].add(j)
                    adj[j].add(i)
                else:
                    sym_links.append({"i": i, "j": j, "op": op,
                                      "d": round(float(d), 3)})
    seen = [False] * n
    frags: list[list[int]] = []
    for s in range(n):
        if seen[s]:
            continue
        seen[s] = True
        stack, comp = [s], []
        while stack:
            k = stack.pop()
            comp.append(k)
            for m in adj[k]:
                if not seen[m]:
                    seen[m] = True
                    stack.append(m)
        frags.append(sorted(comp))
    frags.sort(key=len, reverse=True)
    return frags, sym_links


def asu_coherence(xs) -> dict:
    """Sanity report on the ASU as drawn (identity bonds only).

    {fragments: [{labels, n, main}], detached: [...], ghost_suspects: [...],
     n_detached_atoms}. Ghost signature = lone non-H atom with no identity
    bond AND (Ueq outlier vs same-element median, or no partner even via
    symmetry) - the "atom added to lower R1" pattern.
    """
    scs = list(xs.scatterers())
    if not scs:
        return {"fragments": [], "detached": [], "ghost_suspects": [],
                "n_detached_atoms": 0}
    labels = [sc.label for sc in scs]
    pst, elements = _pair_sym_table(xs)
    frags, sym_links = _identity_fragments(xs, pst, elements)
    linked_ids = {l["i"] for l in sym_links} | {l["j"] for l in sym_links}

    uc = xs.unit_cell()
    ueq = [sc.u_iso_or_equiv(uc) for sc in scs]
    by_el: dict[str, list[float]] = {}
    for e, u in zip(elements, ueq):
        by_el.setdefault(e, []).append(u)
    med = {e: sorted(v)[len(v) // 2] for e, v in by_el.items()}

    out_frags, detached = [], []
    for fi, f in enumerate(frags):
        rec = {"labels": [labels[i] for i in f], "n": len(f), "main": fi == 0}
        out_frags.append(rec)
        if fi == 0:
            continue
        via_sym = any(i in linked_ids for i in f)
        detached.append({**rec,
                         "attachment": "symmetry" if via_sym else "none",
                         "elements": sorted({elements[i] for i in f})})

    # Ghost signature is a COMBINATION - any single flag alone also matches
    # legitimate lone solvent (an ordered water is isolated on the covalent
    # graph too). Require >=2 flags, or total isolation even via symmetry.
    import re as _re
    ghosts = []
    for f in frags[1:]:
        if len(f) != 1:
            continue
        i = f[0]
        if elements[i] == "H":
            continue
        # water-labelled O (O1W/OW1/O2W...) has a declared chemical identity
        # - the expert rule bans ANONYMOUS atoms, not modelled guest solvent
        if elements[i] == "O" and _re.fullmatch(
                r"O\d*W\d*", labels[i].upper()):
            continue
        reasons = []
        u, m = ueq[i], med.get(elements[i], 0.0)
        n_same = len(by_el.get(elements[i], []))
        if n_same >= 3 and m > 0 and u > max(1.5 * m, 0.12):
            reasons.append(f"Ueq {u:.3f} high vs element median {m:.3f}")
        # collapsed U = more density than the element supplies. In the pa1
        # cage trial the "ghost" O atoms had Ueq -0.001 and sat where the
        # published structure has free Cl- - a mislabelled counter-ion,
        # not an atom to delete.
        too_light = u < 0.002
        if too_light:
            reasons.append(
                f"Ueq {u:.4f} collapsed below 0.002: more density than "
                f"{elements[i]} supplies - element too light here"
                + (" (a lone O/N this sharp is often a free halide, "
                   "Cl-/Br-, mislabelled)" if elements[i] in ("O", "N", "C")
                   else ""))
        if scs[i].occupancy < 0.95:
            reasons.append(f"partial occupancy {scs[i].occupancy:.2f} "
                           "(typical difference-map add-on)")
        isolated_everywhere = i not in linked_ids
        if isolated_everywhere:
            reasons.append("no bonded partner even via symmetry")
        # a free halide / alkali ion has no bonded partner by definition
        # (pa1 cage: three Cl- counter-ions read as ghosts); for those
        # elements isolation alone is not a ghost signature
        lone_ion = elements[i] in LONE_ION_ELEMENTS
        if len(reasons) >= 2 or (isolated_everywhere and not lone_ion):
            if too_light:
                advice = ("the density here exceeds what the element "
                          "supplies: try the heavier candidate first (lone "
                          "O/N -> Cl-/Br- counter-ion; check the omit-map "
                          "electron count with integrate_difference_density) "
                          "before any delete-and-refine test; a counter-ion "
                          "is kept and named, never left as an anonymous atom")
            else:
                # the verdict is ghost_test's (three-way, with a
                # sensitivity floor), not a fixed R1 fence quoted here:
                # a hard "<0.002 = delete" read off this advice deleted
                # real atoms wholesale on high-R1 unmasked models
                advice = ("run ghost_test on it (the delete-and-refine "
                          "test): 'ghost' is the only deletion licence; "
                          "'real' means the density is there - name it "
                          "(guest solvent e.g. OW with H-bond partners, "
                          "counter-ion, disorder component), refine it at "
                          "free occupancy or absorb it in the mask with an "
                          "acknowledged reason; 'inconclusive' means "
                          "re-test after the model is more complete, not "
                          "delete. Never keep chemistry-free atoms just to "
                          "lower R1, and never delete a 'real' one silently")
            ghosts.append({
                "label": labels[i], "element": elements[i],
                "occupancy": round(scs[i].occupancy, 2),
                "ueq": round(u, 4), "reasons": reasons,
                "advice": advice})
    return {"fragments": out_frags, "detached": detached,
            "ghost_suspects": ghosts,
            "n_detached_atoms": sum(d["n"] for d in detached)}


def asu_assembly_plan(xs) -> list[dict[str, Any]]:
    """Greedy compaq plan: for each non-main identity fragment pick the
    symmetry op that, applied to the WHOLE fragment, creates the most direct
    bonds to the already-assembled body. Fragments with no bonding op at all
    (lone solvent/ghosts) get the op+lattice shift minimising the closest
    contact to the body. Returns [{labels, op, n_bonds|closest_d}] in
    application order; ops are strings for sgtbx.rt_mx round-trip.
    """
    from cctbx import sgtbx
    scs = list(xs.scatterers())
    if len(scs) < 2:
        return []
    labels = [sc.label for sc in scs]
    uc = xs.unit_cell()
    pst, elements = _pair_sym_table(xs)
    frags, sym_links = _identity_fragments(xs, pst, elements)
    if len(frags) <= 1:
        return []
    body = set(frags[0])
    pending = [set(f) for f in frags[1:]]
    sites = {i: scs[i].site for i in range(len(scs))}
    # cumulative op already applied to each atom (identity for the main
    # fragment); links into an already-moved body atom must be re-expressed
    # in the moved frame or later fragments chase stale coordinates
    applied: dict[int, Any] = {}
    plan: list[dict] = []

    def bond_op_votes(frag: set[int]) -> dict[str, int]:
        votes: dict[str, int] = {}
        for link in sym_links:
            i, j, op = link["i"], link["j"], link["op"]
            # original geometry: |x_i - op*x_j| = bond. After the body atom
            # was moved by M, the op acting on the FRAGMENT atom becomes
            # M*op (body side i) or M*op^-1 (body side j).
            if i in body and j in frag:
                eff = op if i not in applied else applied[i].multiply(op)
                key = str(eff)
            elif j in body and i in frag:
                inv = op.inverse()
                eff = inv if j not in applied else applied[j].multiply(inv)
                key = str(eff)
            else:
                continue
            votes[key] = votes.get(key, 0) + 1
        return votes

    progressed = True
    while pending and progressed:
        progressed = False
        for frag in list(pending):
            votes = bond_op_votes(frag)
            if not votes:
                continue
            op_str = max(votes, key=lambda k: votes[k])
            op = sgtbx.rt_mx(op_str)
            body |= frag
            pending.remove(frag)
            progressed = True
            if op.is_unit_mx():
                # already adjacent to the (moved) body in place - no motion
                continue
            for i in frag:
                sites[i] = op * sites[i]
                applied[i] = op
            plan.append({"labels": [labels[i] for i in frag], "op": op_str,
                         "n_bonds": votes[op_str]})

    # leftovers: nothing bonds them anywhere - park each at the symmetry
    # image with the closest contact to the body so it renders adjacent.
    for frag in pending:
        best = None
        body_cart = [uc.orthogonalize(sites[b]) for b in body]
        for op in xs.space_group():
            for sx in (-1, 0, 1):
                for sy in (-1, 0, 1):
                    for sz in (-1, 0, 1):
                        t_den = op.t().den()
                        shift = sgtbx.tr_vec(
                            (sx * t_den, sy * t_den, sz * t_den), t_den)
                        full = sgtbx.rt_mx(op.r(), op.t().plus(shift))
                        dmin = None
                        for i in frag:
                            c = uc.orthogonalize(full * sites[i])
                            for bc in body_cart:
                                d2 = sum((a - b) ** 2
                                         for a, b in zip(c, bc))
                                dmin = d2 if dmin is None else min(dmin, d2)
                        if dmin is not None and (best is None
                                                 or dmin < best[0]):
                            best = (dmin, str(full))
        if best is not None and best[1] != "x,y,z":
            op = sgtbx.rt_mx(best[1])
            for i in frag:
                sites[i] = op * sites[i]
            plan.append({"labels": [labels[i] for i in frag], "op": best[1],
                         "closest_d": round(best[0] ** 0.5, 2)})
        body |= frag
    return plan


def apply_assembly_plan(xs, plan: list[dict]):
    """Return a new xray.structure with the plan's ops applied.

    Sites are transformed; anisotropic ADPs are rotated (u_star' = R U R^T in
    the fractional basis); the structure is rebuilt through
    special_position_settings so site symmetry/multiplicity are re-derived,
    with occupancy rescaled to conserve atom count if multiplicity changes.
    """
    from cctbx import crystal as cctbx_crystal, sgtbx, xray
    from scitbx import matrix as mx
    op_by_label: dict[str, Any] = {}
    for step in plan:
        op = sgtbx.rt_mx(step["op"])
        for lbl in step["labels"]:
            op_by_label[lbl] = op
    sps = cctbx_crystal.special_position_settings(
        xs.crystal_symmetry(), min_distance_sym_equiv=0.5)
    new = xray.structure(special_position_settings=sps)
    old_mults = [sc.multiplicity() for sc in xs.scatterers()]
    moved = []
    for idx, sc in enumerate(xs.scatterers()):
        op = op_by_label.get(sc.label)
        site = sc.site
        if sc.flags.use_u_aniso():
            u: Any = sc.u_star
        else:
            u = sc.u_iso
        if op is not None:
            site = op * site
            if sc.flags.use_u_aniso():
                r = mx.sqr(op.r().as_double())
                us = mx.sym(sym_mat3=sc.u_star)
                u = (r * us * r.transpose()).as_sym_mat3()
        new.add_scatterer(xray.scatterer(
            label=sc.label, site=site, scattering_type=sc.scattering_type,
            u=u, occupancy=sc.occupancy))
        nsc = new.scatterers()[idx]
        if op is not None and nsc.multiplicity() and \
                old_mults[idx] != nsc.multiplicity():
            nsc.occupancy = (nsc.occupancy * old_mults[idx]
                             / nsc.multiplicity())
            moved.append({"atom": sc.label, "occupancy_rescaled":
                          round(nsc.occupancy, 3)})
    new.scattering_type_registry(table="it1992")
    return new, moved
