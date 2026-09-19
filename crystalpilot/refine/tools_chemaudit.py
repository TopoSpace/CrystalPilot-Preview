"""Element-assignment evidence audit (r13 backflow).

X-ray scattering barely separates C/N/O (one electron apart): r13-p770
solved the full La/Ni skeleton yet typed six atoms N where the literature
(with synthesis knowledge) has C - including a lattice benzene read as
pyridine. That call is often genuinely underdetermined, so this tool does
NOT decide elements. It collects the three kinds of evidence a reviewer
would ask about and leaves the judgement (or the honest disclosure of
ambiguity) to the agent:

  1. Ueq vs bonded neighbours - an atom typed too HEAVY refines to an
     inflated ADP (excess model electrons smear out), typed too LIGHT to a
     compressed one. Thermal motion of terminal groups mimics the first
     signature, so ratios come annotated, never verdicts.
  2. Acceptor environment - a typed N/O carrying no H, coordinating no
     metal and accepting no short contact is chemically idle; a lattice
     "pyridine" whose N does nothing is the classic benzene misread.
  3. Bond-length compatibility - each bond of a suspect atom against
     covalent ranges for the assigned pair AND for the C<->N swap.

Read-only: never mutates the model, never registered in MUTATING_TOOLS.
"""
from __future__ import annotations

from typing import Any

from ..tools.base import ToolContext, ToolResult
from .toolbase import _ProjectTool

#: covalent-range table (A) per unordered element pair: (kind, lo, hi).
#: deliberately coarse - evidence framing, not assignment.
_BOND_RANGES: dict[tuple[str, str], list[tuple[str, float, float]]] = {
    ("C", "C"): [("单键", 1.48, 1.58), ("芳香", 1.36, 1.44), ("双键", 1.29, 1.36)],
    ("C", "N"): [("单键", 1.44, 1.50), ("芳香", 1.31, 1.36), ("双键/亚胺", 1.25, 1.31)],
    ("N", "N"): [("单键", 1.40, 1.47), ("双键/偶氮", 1.20, 1.28)],
    ("C", "O"): [("单键", 1.39, 1.46), ("双键/羰基", 1.18, 1.26)],
    ("N", "O"): [("N-O", 1.20, 1.42)],
    ("O", "O"): [("过氧", 1.44, 1.50)],
}

_ORGANIC = {"C", "N", "O", "H", "D", "B", "F", "Cl", "Br", "I", "S", "P", "Se"}

#: Ueq ratio fences (atom / mean of bonded non-H same-PART neighbours)
_RATIO_HI = 1.5
_RATIO_LO = 0.67
#: acceptor-environment cutoffs
_METAL_COORD_A = 3.0
_CONTACT_A = 3.3


def _bond_kinds(el_a: str, el_b: str, d: float) -> list[str]:
    key = tuple(sorted((el_a, el_b)))
    out = []
    for kind, lo, hi in _BOND_RANGES.get(key, ()):  # type: ignore[arg-type]
        if lo <= d <= hi:
            out.append(f"{key[0]}-{key[1]} {kind} {lo}-{hi}")
    return out


class AuditElementAssignment(_ProjectTool):
    name = "audit_element_assignment"
    description = (
        "Evidence audit for C/N/O element assignments (read-only). For every "
        "organic atom: Ueq vs bonded neighbours (typed-too-heavy inflates the "
        "ADP, typed-too-light compresses it), acceptor environment of typed "
        "N/O (no H, no metal, no short contact = chemically idle - the "
        "classic benzene-read-as-pyridine tell), and bond-length "
        "compatibility for the assignment vs the C<->N swap. X-ray alone "
        "often CANNOT settle these calls - use this to decide where to "
        "seek synthesis input or to disclose the ambiguity honestly. "
        "Geometry, however, DOES settle the metal-bonded cases: the "
        "metal_bonded_audit section lists every C/N sitting at a metal "
        "with no carbon skeleton (a mislabelled O / halide), carboxylate O "
        "wearing a C/N label, N-N and carbonyl-length C-C bonds outside "
        "azide/azole/alkyne chemistry, and eta-bound rings (with N members "
        "= Cp carbons labelled N), each with ranked candidates.")
    params_schema = {
        "type": "object",
        "properties": {
            "elements": {
                "type": "array", "items": {"type": "string"},
                "description": "restrict the report to these typed elements "
                               "(default: N and O, the usual suspects)"},
        },
    }

    def run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        import numpy as np
        import smtbx.utils

        ses = ctx.session or self.project.session
        if ses is None or ses.model is None:
            return ToolResult.failure("no model in session")
        xs = ses.model
        uc = xs.unit_cell()
        scs = xs.scatterers()
        cart = [np.array(uc.orthogonalize(sc.site)) for sc in scs]
        elems = [sc.scattering_type.strip().capitalize().rstrip("+-0123456789")
                 for sc in scs]
        labels = [sc.label for sc in scs]
        u_eqs = [float(sc.u_iso_or_equiv(uc)) for sc in scs]
        asu_sites = [tuple(sc.site) for sc in scs]

        # SHELX PART semantics, same recipe as add_hydrogens: alternatives in
        # different non-zero parts never see each other
        from .nodes import part_kwargs_from_parts
        part_of: dict[str, int] = {}
        for g in ses.flags.get("disorder_groups") or []:
            for m in g.get("members", ()):
                part_of[str(m.get("label", "")).upper()] = int(m.get("part") or 0)
        for lbl, p in (ses.flags.get("parts_extra") or {}).items():
            part_of.setdefault(str(lbl).upper(), int(p or 0))
        parts = [part_of.get(lb.upper(), 0) for lb in labels]

        ct = smtbx.utils.connectivity_table(xs, **part_kwargs_from_parts(parts))
        pst = ct.pair_asu_table.extract_pair_sym_table(
            skip_j_seq_less_than_i_seq=False)

        def bonded(i: int) -> list[tuple[int, float]]:
            out = []
            for j, ops in pst[i].items():
                if parts[i] and parts[j] and abs(parts[i]) != abs(parts[j]):
                    continue
                for op in ops:
                    p = np.array(uc.orthogonalize(op * asu_sites[j]))
                    d = float(np.linalg.norm(p - cart[i]))
                    if 0.1 < d:
                        out.append((j, d))
            return out

        # nonbonded short contacts (H-bond/coordination proxy) via a wider
        # distance table; heavy-heavy <= 3.3 A stands in for X-H...A since
        # H may be absent or riding
        contact_pat = xs.pair_asu_table(distance_cutoff=_CONTACT_A)
        cst = contact_pat.extract_pair_sym_table(
            skip_j_seq_less_than_i_seq=False)

        # index-level adjacency for the 1-2/1-3/1-4 exclusion: contacts
        # separated by <=3 bonds are torsion geometry (ring meta 2.4 A,
        # para 2.8 A), not acceptor chemistry. BFS ignores symmetry ops -
        # a genuine intermolecular contact to a symmetry copy of a
        # nearby-bonded atom is excluded too, which only bites in tiny
        # cells and errs toward NOT flagging (safe direction).
        adj: list[set[int]] = [set() for _ in range(len(labels))]
        for i in range(len(labels)):
            for j in pst[i].keys():
                if j != i:
                    adj[i].add(j)
                    adj[j].add(i)

        def within_3_bonds(i: int) -> set[int]:
            seen = {i}
            frontier = {i}
            for _ in range(3):
                frontier = {k for f in frontier for k in adj[f]} - seen
                seen |= frontier
            return seen

        focus = {str(e).capitalize()
                 for e in (params.get("elements") or ["N", "O"])}
        rows: list[dict[str, Any]] = []
        idle_no_acceptor: list[str] = []
        ueq_hi: list[str] = []
        ueq_lo: list[str] = []

        for i, el in enumerate(elems):
            if el == "H" or el not in _ORGANIC:
                continue
            nb = bonded(i)
            heavy_nb = [(j, d) for j, d in nb if elems[j] != "H"]
            h_count = len(nb) - len(heavy_nb)
            row: dict[str, Any] = {
                "label": labels[i], "element": el,
                "u_eq": round(u_eqs[i], 4), "n_h": h_count,
                "bonds": [{"to": labels[j], "d": round(d, 3),
                           "fits": _bond_kinds(el, elems[j], d) or ["无标准范围相容"],
                           "if_swapped": (_bond_kinds(
                               "C" if el == "N" else "N", elems[j], d)
                               if el in ("N", "C") else [])}
                          for j, d in heavy_nb],
            }
            if heavy_nb:
                mean_nb = sum(u_eqs[j] for j, _ in heavy_nb) / len(heavy_nb)
                ratio = u_eqs[i] / mean_nb if mean_nb > 1e-6 else None
                if ratio is not None:
                    row["u_eq_over_neighbours"] = round(ratio, 2)
                    terminal = len(heavy_nb) == 1
                    if ratio >= _RATIO_HI:
                        row["ueq_note"] = (
                            "ADP 偏大：" + ("端基热运动常见；" if terminal else "")
                            + f"或真实元素比 {el} 轻（如 N→C）")
                        ueq_hi.append(labels[i])
                    elif ratio <= _RATIO_LO:
                        row["ueq_note"] = f"ADP 偏小：真实元素可能比 {el} 重（如 C→N/O）"
                        ueq_lo.append(labels[i])
            if el in focus and el in ("N", "O") and h_count == 0:
                metal_near = any(
                    elems[j] not in _ORGANIC and d <= _METAL_COORD_A
                    for j, d in heavy_nb)
                near_graph = within_3_bonds(i)
                acceptor_contacts = 0
                for j, ops in cst[i].items():
                    if j in near_graph or elems[j] == "H":
                        continue
                    for op in ops:
                        p = np.array(uc.orthogonalize(op * asu_sites[j]))
                        d = float(np.linalg.norm(p - cart[i]))
                        if 0.5 < d <= _CONTACT_A:
                            acceptor_contacts += 1
                row["acceptor_contacts_le_3.3A"] = acceptor_contacts
                if not metal_near and acceptor_contacts == 0:
                    row["environment_note"] = (
                        f"typed-{el} 无质子、无配位、无 ≤{_CONTACT_A} Å 受体接触"
                        "，化学上闲置。晶格环分子中这是苯被读成吡啶的经典征象；"
                        "仅凭 X 射线常无法定论，应寻求合成信息或如实披露替代指认")
                    idle_no_acceptor.append(labels[i])
            if el in focus or "ueq_note" in row or "environment_note" in row:
                rows.append(row)

        # metal-bonded light atoms: the same geometry audit validate_structure
        # runs (pa2: Zr-C / Zr-N at M-O distances, N-N "bonds", Cp carbons
        # labelled N - all inherited from a placeholder SHELXT composition)
        from ..chem.metal_bonded_audit import audit_metal_bonded_light_atoms
        try:
            mba: dict[str, Any] = audit_metal_bonded_light_atoms(xs, parts=part_of)
        except Exception as e:  # noqa: BLE001 - evidence arm never blocks
            mba = {"error": f"{type(e).__name__}: {e}", "suspect_elements": [],
                   "suspect_bonds": [], "pi_ligands": [], "metal_environments": []}
        verdict_of = {s["label"].upper(): s for s in mba["suspect_elements"]}
        for row in rows:
            s = verdict_of.get(row["label"].upper())
            if s is not None:
                row["metal_bonded_verdict"] = (
                    f"[{s['severity']}] {s['reason']} -> {s['suggestion']}")
        n_high = sum(1 for s in mba["suspect_elements"] if s["severity"] == "high")

        return ToolResult(ok=True, summary={
            "caveat": ("C/N/O 相差 1 个电子，X 射线常不能单独定论元素指认；"
                       "本表只给证据。定论优先级：合成/谱学信息 > 键长+环境"
                       "+ADP 汇证 > 单一指标。判读规程 read_skill "
                       "element-assignment-audit。"
                       "SHELXT 组成串（尤其占位的 'C H N O'）给出的 C/N 标签只是"
                       "峰高启发，不是元素证据：金属键合原子的身份由 M–X 距离、"
                       "有无碳骨架、Ueq 和省略图电子数决定（见 metal_bonded_audit），"
                       "这类原子放进 add_hydrogens 的 exclude 不是处理，"
                       "edit_atoms reassign 改判并重精修才是。"),
            "n_examined": len(rows),
            "idle_n_o": idle_no_acceptor,
            "ueq_high_vs_neighbours": ueq_hi,
            "ueq_low_vs_neighbours": ueq_lo,
            "atoms": rows,
            "metal_bonded_audit": {
                **mba,
                "n_suspect_elements": len(mba["suspect_elements"]),
                "n_high": n_high,
                "note": (mba.get("note", "") + "；SHELXT 组成串不是证据，"
                         "金属键合的 C/N 先按几何改判为该金属常见给体，再精修核对"),
            },
        })


def _lm_report(lm, n_max: int) -> dict[str, Any]:
    """What a trial least-squares run actually did (round-3 WP4): a test
    that made no cycle measured nothing, and a verdict built on it is a
    fabrication. scitbx counts completed iterations; the stop reason is
    reconstructed from the iterator's own flags."""
    n = int(getattr(lm, "n_iterations", 0) or 0)
    if int(n_max) <= 0:
        term = "no_cycles_requested"
    elif n >= int(n_max):
        term = "max_cycles"
    elif getattr(lm, "had_too_small_a_step", False):
        term = "step_below_threshold"
    else:
        try:
            term = ("gradient_converged" if lm.has_gradient_converged_to_zero()
                    else "stopped")
        except Exception:  # noqa: BLE001 - a report, never a failure
            term = "stopped"
    return {"cycles_done": n, "cycles_requested": int(n_max),
            "terminated_by": term}


def _npd_labels(xs, idx, uc) -> list[str]:
    """Guest atoms whose ADP is not positive definite after a trial."""
    from cctbx import adptbx
    out: list[str] = []
    for i in idx:
        sc = xs.scatterers()[i]
        if sc.flags.use_u_aniso():
            try:
                ok = adptbx.is_positive_definite(
                    adptbx.u_star_as_u_cart(uc, sc.u_star))
            except Exception:  # noqa: BLE001
                ok = True
            if not ok:
                out.append(sc.label)
        elif float(sc.u_iso) <= 0.0:
            out.append(sc.label)
    return out


class AuditGuestEvidence(_ProjectTool):
    name = "audit_guest_evidence"
    description = (
        "The three guest-evidence tests from the masking discipline, run on "
        "COPIES of the model (read-only). 1) omit-region electron count: "
        "delete the proposed guest atoms from a copy, integrate the "
        "difference density over spheres at their sites, compare with the "
        "electrons the guest should have; 2) occupancy collapse: free ONLY "
        "the guest occupancies (all else frozen) and see whether they hold "
        "up or refine toward zero; 3) restraint withdrawal: re-refine a copy "
        "without the restraints that touch the guest and measure how far it "
        "drifts. Use before committing to a modelled guest, when a reviewer "
        "would ask how you know that solvent is really there, or to decide "
        "between modelling and masking. Every electron comparison is "
        "labelled with its denominator (working occupancy / full-occupancy "
        "formula / full-occupancy model) and judged against the WORKING "
        "hypothesis; occupancy readings are per atom, never a mean; each "
        "trial refinement reports cycles_done and terminated_by (0 cycles "
        "= inconclusive). Judgement stays with you: read_skill "
        "mof-guest-evidence-rule for the decision framework.")
    params_schema = {
        "type": "object",
        "properties": {
            "atoms": {
                "type": "array", "items": {"type": "string"},
                "description": "labels of the proposed guest atoms "
                               "(one guest molecule/fragment)"},
            "expected_formula": {
                "type": "string",
                "description": "what the guest is claimed to be, e.g. "
                               "C6H6, H2O, CHCl3 - enables the electron "
                               "comparison against the claim"},
            "radius": {
                "type": "number", "default": 1.2,
                "description": "integration sphere radius per atom (A)"},
            "n_cycles": {"type": "integer", "default": 8,
                         "description": "trial-refinement cycles for "
                                        "tests 2 and 3 (0 measures "
                                        "nothing: both report inconclusive)"},
        },
        "required": ["atoms"],
    }

    def run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        import re as _re

        import numpy as np
        import smtbx.utils
        from cctbx import maptbx
        from cctbx.array_family import flex
        from cctbx.eltbx import tiny_pse
        from scitbx.lstbx import normal_eqns_solving
        from smtbx.refinement import constraints, least_squares

        from ..tools.refinement_tools import difference_map_real

        ses = ctx.session or self.project.session
        if ses is None or ses.model is None:
            return ToolResult.failure("no model in session")
        if ses.fo_sq is None:
            return ToolResult.failure("no merged data in session")
        xs = ses.model
        uc = xs.unit_cell()
        scs = xs.scatterers()
        by_label = {sc.label.strip().upper(): i for i, sc in enumerate(scs)}
        want = [str(a).strip().upper() for a in (params.get("atoms") or [])]
        missing = [a for a in want if a not in by_label]
        if missing:
            return ToolResult.failure(f"atoms not in the model: {missing}")
        guest_idx = [by_label[a] for a in want]
        guest_set = set(guest_idx)
        radius = float(params.get("radius") or 1.2)
        n_cycles = (int(params["n_cycles"])
                    if params.get("n_cycles") is not None else 8)

        def elem_of(i: int) -> str:
            return (scs[i].scattering_type.strip().capitalize()
                    .rstrip("+-0123456789"))

        def z_of(el: str) -> int:
            return int(tiny_pse.table(el).atomic_number())

        # cctbx occupancy is the chemical site occupancy (the site-symmetry
        # factor lives in scatterer.weight), so Z*occ is the electrons of
        # ONE instance of the atom and Z*occ*multiplicity its electrons
        # per cell. Round-3 WP4: every denominator is labelled - the
        # forensic thread compared a 0.2-occupancy guest against its
        # full-occupancy formula and read the shortfall as "against"
        n_ops = xs.space_group().order_z()
        per_atom: list[dict[str, Any]] = []
        for i in guest_idx:
            sc = scs[i]
            el = elem_of(i)
            z = z_of(el)
            occ = float(sc.occupancy)
            mult = int(sc.multiplicity())
            per_atom.append({
                "label": sc.label, "element": el, "Z": z,
                "occupancy": round(occ, 4), "multiplicity": mult,
                "special_position": mult < n_ops,
                "electrons_at_site": round(z * occ, 2),
                "electrons_per_cell": round(z * occ * mult, 2),
                "electrons_full_occupancy": z})
        modeled_e = sum(a["Z"] * float(scs[i].occupancy)
                        for a, i in zip(per_atom, guest_idx))
        model_full_e = float(sum(a["Z"] for a in per_atom))
        heavy_occ = [float(scs[i].occupancy) for i in guest_idx
                     if elem_of(i) != "H"]
        working_occ = heavy_occ or [float(scs[i].occupancy) for i in guest_idx]
        working_occ_mean = sum(working_occ) / len(working_occ)

        expected_e = None
        formula = params.get("expected_formula")
        if formula:
            try:
                expected_e = 0.0
                for el, n in _re.findall(r"([A-Z][a-z]?)([\d.]*)",
                                         str(formula)):
                    if not el:
                        continue
                    expected_e += z_of(el) * (float(n) if n else 1.0)
            except Exception:  # noqa: BLE001 - unknown element symbol etc.
                return ToolResult.failure(
                    f"cannot parse expected_formula {formula!r}")

        mask_warning = None
        if ses.flags.get("f_mask") is not None:
            mask_warning = (
                "solvent mask is ACTIVE: mask and modelled guest are "
                "mutually exclusive (the same density cannot be absorbed "
                "by the mask AND explained by atoms). Test 1 uses "
                "mask-free Fc; tests 2/3 are skipped - drop the mask "
                "before auditing a modelled guest, or go the mask route "
                "with its disclosure obligations instead.")

        summary: dict[str, Any] = {
            "guest_atoms": want,
            "modeled_electrons": round(modeled_e, 1),
        }
        if expected_e is not None:
            summary["expected_formula"] = str(formula)
            summary["expected_electrons"] = round(expected_e, 1)
        denominators: dict[str, Any] = {
            "working_occupancy": {
                "electrons": round(modeled_e, 1),
                "occupancy_mean": round(working_occ_mean, 3),
                "meaning": "the guest as modelled: Z x occupancy summed "
                           "over the named atoms (one instance each)"},
            "full_occupancy_model": {
                "electrons": round(model_full_e, 1),
                "meaning": "the same atoms at occupancy 1.0 - a claim the "
                           "model makes only if its occupancies are 1.0"},
        }
        if expected_e is not None:
            denominators["full_occupancy_formula"] = {
                "electrons": round(expected_e, 1), "formula": str(formula),
                "meaning": "the claimed formula at occupancy 1.0"}
            denominators["formula_at_working_occupancy"] = {
                "electrons": round(expected_e * working_occ_mean, 1),
                "formula": str(formula),
                "occupancy_mean": round(working_occ_mean, 3),
                "meaning": "the claimed formula at the model's working "
                           "occupancy - the hypothesis the model states"}
        summary["accounting"] = {
            "per_atom": per_atom,
            "totals": {
                "electrons_at_working_occupancy": round(modeled_e, 1),
                "electrons_per_cell": round(sum(a["electrons_per_cell"]
                                                for a in per_atom), 1),
                "electrons_full_occupancy_model": round(model_full_e, 1),
                "n_special_position_atoms": sum(
                    1 for a in per_atom if a["special_position"]),
                "space_group_order": n_ops},
            "denominators": denominators,
        }
        if mask_warning:
            summary["mask_warning"] = mask_warning
        verdict: list[str] = []

        # ---- test 1: omit-region electron integration -------------------
        try:
            keep = flex.bool([i not in guest_set for i in range(len(scs))])
            xs_omit = xs.select(keep)
            fft_map, real, k = difference_map_real(ses, xs_omit)
            cart = flex.vec3_double(
                [uc.orthogonalize(scs[i].site) for i in guest_idx])
            sel = maptbx.grid_indices_around_sites(
                unit_cell=uc, fft_n_real=real.focus(), fft_m_real=real.all(),
                sites_cart=cart,
                site_radii=flex.double(len(guest_idx), radius))
            vals = real.select(sel)
            voxel = uc.volume() / real.size()
            net = float(flex.sum(vals)) * voxel
            pos = float(flex.sum(vals.select(vals > 0))) * voxel
            t1 = {"map_provenance": getattr(fft_map, "crystalpilot_map_provenance", None),
                  "region_electrons_net": round(net, 1),
                  "region_electrons_positive": round(pos, 1),
                  "radius_A": radius,
                  "n_voxels": int(sel.size())}
            t1["integration_region"] = {
                "spheres": len(guest_idx), "radius_A": radius,
                "meaning": "omit-map electrons inside the union of spheres "
                           "at the named sites: one instance of each atom, "
                           "so the comparable denominators are per-instance "
                           "(not per cell)"}
            bases = [("working_occupancy", modeled_e),
                     ("full_occupancy_model", model_full_e)]
            if expected_e is not None:
                bases += [("full_occupancy_formula", expected_e),
                          ("formula_at_working_occupancy",
                           expected_e * working_occ_mean)]
            t1["ratio_by_denominator"] = {
                k: round(net / b, 2) for k, b in bases if b and b > 0}
            # legacy keys (pre-WP4 readers)
            if expected_e is not None and expected_e > 0:
                t1["ratio_vs_formula"] = round(net / expected_e, 2)
            elif modeled_e > 0:
                t1["ratio_vs_model"] = round(net / modeled_e, 2)
            # the verdict reads the WORKING hypothesis - what the model
            # claims (formula at its occupancy, or the atoms as modelled);
            # the full-occupancy figures are stated, not judged
            hyp_key = ("formula_at_working_occupancy"
                       if expected_e is not None else "working_occupancy")
            hyp_base = (expected_e * working_occ_mean
                        if expected_e is not None else modeled_e)
            t1["verdict_denominator"] = hyp_key
            if hyp_base and hyp_base > 0:
                ratio = net / hyp_base
                t1["ratio_vs_hypothesis"] = round(ratio, 2)
                what = (f"{formula} at occupancy {working_occ_mean:.2f}"
                        if expected_e is not None else
                        f"the atoms as modelled (mean occupancy "
                        f"{working_occ_mean:.2f})")
                label = f"the working hypothesis {what} = {hyp_base:.1f} e"
                if ratio >= 0.6:
                    verdict.append(
                        "test1 SUPPORTS: omit-map net electrons "
                        f"{net:.1f} e reach {100 * ratio:.0f}% of "
                        f"{label}")
                elif ratio < 0.3:
                    verdict.append(
                        f"test1 AGAINST: only {net:.1f} e in the omit "
                        f"region ({100 * ratio:.0f}% of {label}) - the "
                        "density does not carry the guest as modelled")
                else:
                    verdict.append(
                        f"test1 PARTIAL: {net:.1f} e against {label} "
                        f"({100 * ratio:.0f}%) - consider a lower "
                        "occupancy or a lighter identity")
                if expected_e is not None and working_occ_mean < 0.95:
                    t1["note"] = (
                        f"as a FULL-occupancy {formula} ({expected_e:.1f} "
                        f"e) the region holds {100 * net / expected_e:.0f}% "
                        f"- that figure tests a claim the model does not "
                        f"make (its occupancy is {working_occ_mean:.2f})")
            summary["test1_omit_region"] = t1
        except Exception as e:  # noqa: BLE001 - report, don't kill the audit
            summary["test1_omit_region"] = {
                "error": f"{type(e).__name__}: {e}"}

        # ---- test 2: occupancy collapse ---------------------------------
        occ_targets = [i for i in guest_idx if elem_of(i) != "H"]
        if mask_warning:
            summary["test2_occupancy"] = {"skipped": "mask active"}
        elif not occ_targets:
            summary["test2_occupancy"] = {
                "skipped": "guest selection is H-only"}
        else:
            try:
                xs2 = xs.deep_copy_scatterers()
                occ_set = set(occ_targets)
                for i, sc in enumerate(xs2.scatterers()):
                    sc.flags.set_grad_site(False)
                    sc.flags.set_grad_u_iso(False)
                    sc.flags.set_grad_u_aniso(False)
                    sc.flags.set_grad_occupancy(i in occ_set)
                ct2 = smtbx.utils.connectivity_table(xs2)
                rep2 = constraints.reparametrisation(
                    structure=xs2, constraints=[], connectivity_table=ct2)
                w = ses.flags.get("weights") or {}
                ls2 = least_squares.crystallographic_ls(
                    ses.fo_sq.as_xray_observations(), rep2,
                    weighting_scheme=least_squares.mainstream_shelx_weighting(
                        a=float(w.get("a", 0.1)), b=float(w.get("b", 0.0))))
                lm2 = normal_eqns_solving.levenberg_marquardt_iterations(
                    ls2, n_max_iterations=n_cycles,
                    gradient_threshold=1e-8, step_threshold=1e-8)
                run2 = _lm_report(lm2, n_cycles)
                occ0 = {scs[i].label: float(scs[i].occupancy)
                        for i in occ_targets}
                occ1 = {xs2.scatterers()[i].label:
                        float(xs2.scatterers()[i].occupancy)
                        for i in occ_targets}
                mean1 = sum(occ1.values()) / len(occ1)
                mean0 = sum(occ0.values()) / len(occ0)
                # per-atom readings (round-3 WP4): a mean over a group
                # that is half real and half noise reads "partial" and
                # says nothing true about either half
                rows: list[dict[str, Any]] = []
                for i in occ_targets:
                    lb = scs[i].label
                    a, b = occ0[lb], occ1[lb]
                    at_bound = ("zero" if b <= 0.0 else
                                "above_one" if (b > 1.05 and a <= 1.0)
                                else None)
                    if a <= 1e-6:
                        reading = "undefined"
                    elif b >= 0.7 * a:
                        reading = "holds"
                    elif b < 0.3 * a:
                        reading = "collapses"
                    else:
                        reading = "partial"
                    rows.append({"label": lb, "occ_start": round(a, 3),
                                 "occ_refined": round(b, 3),
                                 "ratio": (round(b / a, 2) if a > 1e-6
                                           else None),
                                 "at_bound": at_bound, "reading": reading})
                t2 = {"per_atom": rows,
                      "start": {k: round(v, 3) for k, v in occ0.items()},
                      "refined": {k: round(v, 3) for k, v in occ1.items()},
                      "refined_mean": round(mean1, 3),
                      "engine": "smtbx LM on a copy: guest occupancies "
                                "free, every other parameter frozen",
                      **run2}
                pinned = [r for r in rows if r["at_bound"]]
                classes = {r["reading"] for r in rows}
                if run2["cycles_done"] == 0:
                    t2["reading"] = "inconclusive"
                    verdict.append(
                        "test2 INCONCLUSIVE: the trial refinement made no "
                        f"cycle (terminated_by={run2['terminated_by']}) - "
                        "nothing was measured; the occupancies shown are "
                        "the starting values")
                elif pinned:
                    t2["reading"] = "inconclusive"
                    rest = {c: [r["label"] for r in rows
                                if r["reading"] == c and not r["at_bound"]]
                            for c in sorted(classes)}
                    rest = {c: v for c, v in rest.items() if v}
                    verdict.append(
                        "test2 INCONCLUSIVE: " + ", ".join(
                            f"{r['label']} pinned at "
                            f"{'<= 0' if r['at_bound'] == 'zero' else '> 1'}"
                            f" (occupancy {r['occ_refined']:.2f})"
                            for r in pinned)
                        + " - a free occupancy through 0 or above 1 is a "
                          "model/data problem (wrong element, absorbed ADP, "
                          "unmodelled disorder), not a measurement of the "
                          "guest"
                        + ("; the other atoms read - " + "; ".join(
                            f"{c}: {', '.join(v)}" for c, v in rest.items())
                           if rest else ""))
                elif classes == {"holds"}:
                    t2["reading"] = "supports"
                    low = min(r["ratio"] for r in rows)
                    verdict.append(
                        f"test2 SUPPORTS: every freed occupancy holds "
                        f"(min {100 * low:.0f}% of its start; {len(rows)} "
                        f"atom(s)) - the density wants these atoms at the "
                        "working occupancy")
                elif classes == {"collapses"}:
                    t2["reading"] = "against"
                    high = max(r["ratio"] for r in rows)
                    verdict.append(
                        f"test2 AGAINST: every freed occupancy collapses "
                        f"(max {100 * high:.0f}% of its start; {len(rows)} "
                        f"atom(s)) - the guest as modelled is fitted noise "
                        "at this occupancy")
                elif len(classes) > 1:
                    t2["reading"] = "inconclusive"
                    by = {c: [r["label"] for r in rows if r["reading"] == c]
                          for c in sorted(classes)}
                    verdict.append(
                        "test2 INCONCLUSIVE: the atoms do not read as one "
                        "guest at one occupancy - " + "; ".join(
                            f"{c}: {', '.join(v)}" for c, v in by.items())
                        + " - judge atom by atom (per_atom), not by the mean")
                else:
                    t2["reading"] = "partial"
                    verdict.append(
                        f"test2 PARTIAL: every freed occupancy drops to "
                        f"30-70% of its start (mean {mean1:.2f} from "
                        f"{mean0:.2f}) - consider modelling at the lower "
                        "occupancy and disclosing")
                summary["test2_occupancy"] = t2
            except Exception as e:  # noqa: BLE001
                summary["test2_occupancy"] = {
                    "error": f"{type(e).__name__}: {e}"}

        # ---- test 3: restraint withdrawal -------------------------------
        specs = list(ses.flags.get("restraints") or [])
        want_set = set(want)

        def _touches(spec: dict) -> bool:
            atoms = spec.get("atoms")
            if atoms is None:
                return True      # global SIMU/DELU/RIGU/ISOR hit guests too
            flat: list[str] = []
            for a in atoms:
                if isinstance(a, (list, tuple)):
                    flat.extend(str(x) for x in a)
                else:
                    flat.append(str(a))
            return any(x.strip().upper() in want_set for x in flat)

        touching = [s for s in specs if _touches(s)]
        if mask_warning:
            summary["test3_restraints"] = {"skipped": "mask active"}
        elif not touching:
            summary["test3_restraints"] = {
                "applicable": False,
                "note": "no restraints touch the guest - it is not held "
                        "together by restraints; test 3 passes trivially"}
        else:
            try:
                others = [s for s in specs if s not in touching]
                from .nodes import (part_connectivity_kwargs,
                                    prune_long_metal_contacts)
                h_constraints = list(ses.flags.get("h_constraints") or [])
                w = ses.flags.get("weights") or {}

                def _trial(xs_t):
                    """One trial LS on a copy: sites and ADPs free,
                    occupancies fixed, guest restraints withdrawn."""
                    for sc in xs_t.scatterers():
                        sc.flags.set_grad_site(True)
                        if sc.flags.use_u_aniso():
                            sc.flags.set_grad_u_aniso(True)
                            sc.flags.set_grad_u_iso(False)
                        else:
                            sc.flags.set_grad_u_iso(True)
                            sc.flags.set_grad_u_aniso(False)
                        sc.flags.set_grad_occupancy(False)
                    part_kw_t = part_connectivity_kwargs(ses.flags,
                                                         xs_t.scatterers())
                    ct_t = smtbx.utils.connectivity_table(xs_t, **part_kw_t)
                    if h_constraints:
                        prune_long_metal_contacts(ct_t, xs_t, part_kw_t)
                    ls_kwargs: dict[str, Any] = {}
                    info_t: dict[str, Any] = {}
                    if others:
                        from .restraints import build_restraints_manager
                        mgr, info_t = build_restraints_manager(xs_t, others)
                        if mgr is not None:
                            ls_kwargs["restraints_manager"] = mgr
                    rep_t = constraints.reparametrisation(
                        structure=xs_t, constraints=h_constraints,
                        connectivity_table=ct_t)
                    ls_t = least_squares.crystallographic_ls(
                        ses.fo_sq.as_xray_observations(), rep_t,
                        weighting_scheme=least_squares.mainstream_shelx_weighting(
                            a=float(w.get("a", 0.1)), b=float(w.get("b", 0.0))),
                        **ls_kwargs)
                    lm_t = normal_eqns_solving.levenberg_marquardt_iterations(
                        ls_t, n_max_iterations=n_cycles,
                        gradient_threshold=1e-8, step_threshold=1e-8)
                    return _lm_report(lm_t, n_cycles), info_t, rep_t

                xs3 = xs.deep_copy_scatterers()
                run3, info3, rep3 = _trial(xs3)
                cart0 = {i: np.array(uc.orthogonalize(scs[i].site))
                         for i in guest_idx}
                cart1 = {i: np.array(uc.orthogonalize(
                    xs3.scatterers()[i].site)) for i in guest_idx}
                shifts = {scs[i].label:
                          float(np.linalg.norm(cart1[i] - cart0[i]))
                          for i in guest_idx}
                max_shift = max(shifts.values())
                pairs = [(i, j) for ai, i in enumerate(guest_idx)
                         for j in guest_idx[ai + 1:]
                         if np.linalg.norm(cart0[i] - cart0[j]) < 1.8]
                drift = 0.0
                for i, j in pairs:
                    d0 = float(np.linalg.norm(cart0[i] - cart0[j]))
                    d1 = float(np.linalg.norm(cart1[i] - cart1[j]))
                    drift = max(drift, abs(d1 - d0))
                u0 = {i: float(scs[i].u_iso_or_equiv(uc)) for i in guest_idx}
                u1 = {i: float(xs3.scatterers()[i].u_iso_or_equiv(uc))
                      for i in guest_idx}
                u_ratio = max((u1[i] / u0[i]) if u0[i] > 1e-6 else 1.0
                              for i in guest_idx)
                t3 = {"n_restraints_withdrawn": len(touching),
                      "withdrawn_kinds": sorted({str(s.get("kind"))
                                                 for s in touching}),
                      "max_site_shift_A": round(max_shift, 3),
                      "max_bond_drift_A": round(drift, 3),
                      "max_ueq_inflation": round(u_ratio, 2),
                      "site_shifts_A": {k: round(v, 3)
                                        for k, v in shifts.items()}}
                if info3.get("warnings"):
                    t3["restraint_warnings"] = info3["warnings"]
                npd = _npd_labels(xs3, guest_idx, uc)
                t3.update({
                    "engine": "smtbx LM on a copy: sites and ADPs free, "
                              "occupancies fixed, guest restraints withdrawn",
                    "n_free_params": getattr(rep3, "n_independents", None),
                    "n_reflections": int(ses.fo_sq.size()),
                    "d_min": round(float(ses.fo_sq.d_min()), 3),
                    "npd_after": npd,
                    **run3})
                # displacement control (round-3 R4, from the Zr-MOF rerun): a
                # 0.07-occupancy guest read "stays put (max shift 0.00 A)"
                # while SHELXL let the same guest drift 5 A. With weak site
                # gradients an LM run that moves nothing is inertia, not a
                # grip: displace a copy of the guest rigidly by 0.3 A and
                # measure how far the map pulls it back.
                ctrl: dict[str, Any] | None = None
                if run3["cycles_done"] > 0:
                    try:
                        disp_A = 0.3
                        xs4 = xs.deep_copy_scatterers()
                        direction = np.array([1.0, 1.0, 1.0]) / np.sqrt(3.0)
                        for i in guest_idx:
                            sc4 = xs4.scatterers()[i]
                            moved = np.array(uc.orthogonalize(sc4.site)) + disp_A * direction
                            sc4.site = tuple(uc.fractionalize(tuple(moved)))
                        run4, _info4, _rep4 = _trial(xs4)
                        d_after = [float(np.linalg.norm(
                            np.array(uc.orthogonalize(xs4.scatterers()[i].site))
                            - cart0[i])) for i in guest_idx]
                        mean_after = float(np.mean(d_after)) if d_after else disp_A
                        frac = 1.0 - mean_after / disp_A
                        ctrl = {"displacement_A": disp_A,
                                "mean_distance_after_A": round(mean_after, 3),
                                "return_fraction": round(max(0.0, min(1.0, frac)), 2),
                                "cycles_done": run4["cycles_done"],
                                "terminated_by": run4["terminated_by"],
                                "reading": ("held" if frac >= 0.5 else
                                            "not_held" if frac < 0.25 else
                                            "partial"),
                                "note": "the guest copy was displaced rigidly "
                                        "and refined the same way; return "
                                        "1.0 = pulled all the way back by the "
                                        "map, 0.0 = stays where it was put"}
                        t3["displacement_control"] = ctrl
                    except Exception as e:  # noqa: BLE001 - control only
                        t3["displacement_control"] = {
                            "error": f"{type(e).__name__}: {e}"}
                grip = ctrl.get("return_fraction") if ctrl else None
                if run3["cycles_done"] == 0:
                    t3["reading"] = "inconclusive"
                    verdict.append(
                        "test3 INCONCLUSIVE: the trial refinement made no "
                        f"cycle (terminated_by={run3['terminated_by']}) - "
                        "the withdrawal was not measured")
                elif max_shift > 0.3 or drift > 0.15 or u_ratio > 3.0 or npd:
                    t3["reading"] = "warns"
                    verdict.append(
                        f"test3 WARNS: withdrawing {len(touching)} guest "
                        f"restraints moves atoms up to {max_shift:.2f} A, "
                        f"bonds drift {drift:.2f} A, Ueq inflates "
                        f"{u_ratio:.1f}x"
                        + (f", ADPs go non-positive-definite on "
                           f"{', '.join(npd)}" if npd else "")
                        + f" ({run3['cycles_done']} cycle(s), "
                          f"{run3['terminated_by']}) - the guest geometry "
                          "is held together mainly by the restraints")
                elif grip is not None and grip < 0.5:
                    # support needs the positive control to work: a map
                    # that holds a guest pulls a displaced copy back most
                    # of the way; one that does not is not holding it
                    t3["reading"] = "inconclusive"
                    verdict.append(
                        "test3 INCONCLUSIVE: the guest stays put without its "
                        f"restraints (max shift {max_shift:.2f} A) but a copy "
                        f"displaced by {ctrl['displacement_A']} A comes back "
                        f"only {grip * 100:.0f}% of the way "
                        f"({ctrl['cycles_done']} cycle(s)) - the data hold "
                        "the guest neither firmly in place nor out of it, so "
                        "'stays put' is inertia, not evidence")
                else:
                    t3["reading"] = "supports"
                    verdict.append(
                        "test3 SUPPORTS: guest stays put without its "
                        f"restraints (max shift {max_shift:.2f} A, bond "
                        f"drift {drift:.2f} A; {run3['cycles_done']} "
                        f"cycle(s), {run3['terminated_by']})"
                        + (f"; a copy displaced by {ctrl['displacement_A']} A "
                           f"returns {grip * 100:.0f}% of the way"
                           if grip is not None else ""))
                summary["test3_restraints"] = t3
            except Exception as e:  # noqa: BLE001
                summary["test3_restraints"] = {
                    "error": f"{type(e).__name__}: {e}"}

        # what else holds the guest besides the data (round-3 WP4): a
        # restraint set or a shared free variable that survives into the
        # delivered model conditions every reading above
        fvar_groups = [
            g.get("fvar_index")
            for g in (ses.flags.get("disorder_groups") or [])
            if any(str(m.get("label", "")).upper() in want_set
                   for m in g.get("members", ()))]
        riding = any(
            str(g.get("carrier", "")).upper() in want_set
            or any(str(h).upper() in want_set for h in g.get("h", []))
            for g in ((ses.flags.get("h_riding_meta") or {})
                      .get("per_carrier") or []))
        conditioned = bool(touching or fvar_groups)
        summary["conditioned_by_prior"] = {
            "value": conditioned,
            "restraints": sorted({str(s.get("kind")) for s in touching}),
            "fvar_groups": [f"fvar{k}" for k in fvar_groups if k],
            "riding_h": riding,
            "note": ("the guest's geometry / occupancy in the working model "
                     "is shaped by prior knowledge (restraints or a shared "
                     "free variable), so tests 1-2 read a model that was "
                     "not free to disagree; say so when reporting"
                     if conditioned else
                     "no restraint or shared free variable touches the "
                     "guest; its geometry and occupancy are the data's")}
        # WP1: the audit's reading as a verdict. Two supporting tests are
        # the minimum the discipline asks for; one against is enough
        words = [v.split(":", 1)[0].split()[-1] for v in verdict]
        if "AGAINST" in words:
            sci = "against"
        elif words and all(w == "SUPPORTS" for w in words) and len(words) >= 2:
            sci = "supports"
        else:
            sci = "inconclusive"
        summary["scientific_outcome"] = {
            "verdict": sci,
            "reasons": list(verdict),
            "measured_by": ("omit-map electron integration at the named "
                            "sites; free-occupancy trial refinement (all "
                            "else frozen); restraint-withdrawal trial "
                            "refinement - all on model copies")}
        summary["verdict"] = verdict
        summary["caveat"] = (
            "三检验是证据不是判决：两项同向才有底气，单项异常先查数据侧。"
            "身份指认（是苯还是吡啶、是水还是铵）X 射线常定不了，结合 "
            "TGA/元素分析/合成记录；判读规程 read_skill "
            "mof-guest-evidence-rule。")
        return ToolResult(ok=True, summary=summary)
