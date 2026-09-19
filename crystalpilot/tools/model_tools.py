"""Model-building and model-editing tools.

Peak interpretation has two branches, chosen by whether the expected
composition holds a METAL:

* metal present - the MOF lens: metals from the formula go to the
  strongest peaks, atoms at M-O/M-N distances prefer O/N, the rest
  default to C.
* no metal - the density-tier lens (tools.peak_chemistry): heavy
  non-metals like Cl/S/P/Br are anchors rather than centres, O is
  separated from C by the 33 % step in Z, C vs N is never guessed, and
  the organic motifs are read from the geometry.

The agent can then re-assign elements, delete ghosts, set occupancies etc.
through explicit, logged edit operations.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
from cctbx import crystal, xray
from cctbx.eltbx import tiny_pse

from ..chem.knowledge import is_metal, profile_for
from .base import Tool, ToolContext, ToolResult
from .peak_chemistry import assign_metal_free, organic_motifs


def _atomic_number(el: str) -> int:
    try:
        return tiny_pse.table(el).atomic_number()
    except RuntimeError:
        return 6


def _sym_expanded_cart(symmetry, sites_frac: list) -> np.ndarray:
    """All symmetry copies of given fractional sites, as cartesian coords (one cell)."""
    ops = symmetry.space_group().all_ops()
    uc = symmetry.unit_cell()
    out = []
    for site in sites_frac:
        for op in ops:
            s = op * site
            s = [x % 1.0 for x in s]
            out.append(uc.orthogonalize(s))
    return np.array(out) if out else np.zeros((0, 3))


def _min_dist_to(symmetry, targets_cart: np.ndarray, site_frac) -> float:
    """Min distance from a fractional site to target cartesian points, over 27 images."""
    if len(targets_cart) == 0:
        return float("inf")
    uc = symmetry.unit_cell()
    best = float("inf")
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for dz in (-1, 0, 1):
                p = np.array(uc.orthogonalize(
                    (site_frac[0] + dx, site_frac[1] + dy, site_frac[2] + dz)))
                d = float(np.min(np.linalg.norm(targets_cart - p, axis=1)))
                best = min(best, d)
    return best


class InterpretPeaks(Tool):
    name = "interpret_peaks"
    description = (
        "Convert the charge-flipping peak list into an atomic model. With a metal in "
        "the composition it assigns elements the old way: strongest peaks -> metals, "
        "peaks at plausible M-O distance -> O, rest -> C. With NO metal (organics, "
        "organic salts, S/P/Cl/Br/I compounds) it takes a metal-free branch instead - "
        "peaks ranked by integrated density in a 0.7 A sphere, heavy non-metals placed "
        "as anchors, O separated from C by density tier and C vs N never guessed: those "
        "sites return element_uncertain plus a per-atom element_confidence, the "
        "composition's nitrogen allowance is DISCLOSED in nitrogen_budget instead of "
        "being spent, and chem_hint lists the organic motifs (carboxylate, aromatic "
        "ring, halide, sulfonate ...) read from the geometry alone. "
        "Creates the session's working model.")
    params_schema = {
        "type": "object",
        "properties": {
            "height_cutoff_frac": {"type": "number", "default": 0.07,
                                   "description": "drop peaks below this fraction of the top peak"},
            "max_atoms_factor": {"type": "number", "default": 3.0,
                                 "description": "cap = factor * (expected non-H atoms "
                                                "per ASU-equivalent); generous because "
                                                "special positions inflate the distinct "
                                                "site count in high-symmetry MOFs"},
            "metal_override": {"type": ["string", "null"], "default": None,
                               "description": "force this element as the heavy "
                                              "metal (also forces the metal-"
                                              "coordination branch on a "
                                              "metal-free composition)"},
        },
    }

    def run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        ses = ctx.session
        info = ses.cf_info
        if not info.get("peak_sites"):
            # pa1 x4: agents hit this right after branch/checkout and re-ran
            # charge flipping (12-50 s). The list now travels with the node
            # (peaks.json) and comes back on checkout - say so, and say
            # what the map-level alternative is.
            return ToolResult.failure(
                "no charge-flipping peak list in this session. "
                "solve_charge_flipping / solve_superflip produce it; it is "
                "saved with the active node (peaks.json beside model.res) "
                "and restored by checkout/branch, and cleared by "
                "change_space_group. Run a solver first. To read residual "
                "peaks of the CURRENT model instead, use inspect_map "
                "(then add_atoms_from_difference_map with its indices).")
        sites, heights = info["peak_sites"], info["peak_heights"]
        cutoff = float(params.get("height_cutoff_frac", 0.07)) * heights[0]

        comp = ses.dataset.composition
        order_z = ses.symmetry.space_group().order_z()
        # expected per-ASU non-H composition
        asu_budget: dict[str, float] = {}
        if comp and comp.z:
            for el, n in comp.elements.items():
                if el != "H":
                    asu_budget[el] = n * comp.z / order_z
        # the branch: a METAL centre in the composition (or a forced one) keeps
        # the coordination lens; a metal-free composition - including one whose
        # heaviest atom is a non-metal like Cl/S/P/Br - takes the density-tier
        # branch, where those heavy non-metals are anchors, not centres.
        metal_centres = [el for el in asu_budget if is_metal(el)]
        forced = str(params.get("metal_override") or "").strip()
        metal_branch = bool(metal_centres or forced)
        # "heavy" = metals plus heavy non-metals (I, Br, Se, Te...) that dominate
        # the density map exactly like metals do
        metals = sorted((el for el in asu_budget
                         if is_metal(el) or _atomic_number(el) >= 17),
                        key=_atomic_number, reverse=True)
        if forced:
            metals = [forced.capitalize()]
        if not metal_branch:
            metals = []
        if asu_budget:
            n_expected = sum(asu_budget.values())
        else:
            # no credible composition: ~1 non-H atom per 18 A^3 of cell volume
            n_expected = ses.symmetry.unit_cell().volume() / 18.0 / order_z
        max_atoms = int(math.ceil(n_expected * float(params.get("max_atoms_factor", 1.15))))

        # greedy symmetry-aware acceptance: drop satellites of stronger peaks
        kept: list[tuple] = []
        kept_idx: list[int] = []
        accepted_cart = np.zeros((0, 3))
        n_ghosts = 0
        for k, (s, h) in enumerate(zip(sites, heights)):
            if h < cutoff or len(kept) >= max_atoms:
                break
            d = _min_dist_to(ses.symmetry, accepted_cart, s)
            if d < 1.05:
                n_ghosts += 1
                continue
            kept.append((s, h))
            kept_idx.append(k)
            accepted_cart = np.vstack(
                [accepted_cart, _sym_expanded_cart(ses.symmetry, [s])])
        if not kept:
            return ToolResult.failure("all peaks below cutoff")

        # --- element assignment -------------------------------------------
        extra: dict[str, Any] = {}
        atom_rows: list[dict[str, Any]] = []
        if metal_branch:
            assignments = self._metal_assignment(ses, kept, metals, asu_budget)
        else:
            assignments, atom_rows, extra = self._metal_free_assignment(
                ses, info, kept, kept_idx, asu_budget)

        # --- build structure ----------------------------------------------
        sps = crystal.special_position_settings(ses.symmetry, min_distance_sym_equiv=0.5)
        xs = xray.structure(special_position_settings=sps)
        counters: dict[str, int] = {}
        labels: list[str] = []
        for (site, h), el in zip(kept, assignments):
            counters[el] = counters.get(el, 0) + 1
            labels.append(f"{el}{counters[el]}")
            xs.add_scatterer(xray.scatterer(
                label=labels[-1], site=site, scattering_type=el, u=0.05))
        ses.model = xs

        if atom_rows:
            for label, row in zip(labels, atom_rows):
                row["atom"] = label
            # strongest first: the sites whose identity carries the model
            extra["element_assignment"] = sorted(
                atom_rows, key=lambda r: -r.get("density_ratio", 0.0))
            extra["n_element_uncertain"] = sum(
                1 for r in atom_rows if r.get("element_uncertain"))
            try:
                extra["chem_hint"] = {
                    "motifs": organic_motifs(xs),
                    "read_from": (
                        "interatomic distances and ring planarity of the "
                        "sites just placed - no label, file or composition "
                        "was consulted; a motif that would need a nitrogen "
                        "appears in its geometry-only form because C/N is "
                        "not typed at this stage")}
            except Exception as exc:  # noqa: BLE001 - a hint never fails the tool
                extra["chem_hint"] = {"motifs": [], "error": str(exc)}
            # where the C/N sites this branch refuses to guess DO get
            # settled. No Ueq hint can be given here: every site above was
            # just created with the same u, so an ADP comparison at this
            # stage is empty by construction (reg1-ext2 case rz: a nitro N
            # left as C here was refined and delivered as a "carboxylate").
            extra["ueq_hint"] = {
                "available": False,
                "why": ("the sites were just placed with one shared u - the "
                        "displacement parameters carry no element "
                        "information until they have been refined"),
                "after_refinement": (
                    "validate_structure's light_atom_element_check compares "
                    "each atom's refined Ueq with the median of its bonded "
                    "neighbours: a C label on a nitrogen site refines LOW "
                    "(too_light_label), an over-heavy label HIGH "
                    "(too_heavy_label), and a planar X(O)2 site is read as "
                    "nitro or carboxylate from the same numbers "
                    "(nitro_vs_carboxylate_candidates). Run it before "
                    "delivering anything whose formula depends on these "
                    "sites")}

        # flag probable-heavy sites when composition is unknown so the agent can
        # reason about their identity (huge peak + C label => wrong element).
        # A site the metal-free branch already gave a heavy element to is not
        # "unassigned" - only the ones still carrying a light label count.
        n_probable_heavy = 0
        if not metals and len(kept) > 3:
            hs = sorted((h for _, h in kept), reverse=True)
            h_med = hs[len(hs) // 2]
            if h_med > 0:
                n_probable_heavy = sum(
                    1 for (_, h), el in zip(kept, assignments)
                    if h / h_med > 3.0 and _atomic_number(el) <= 8)
        return ToolResult(ok=True, summary={
            "n_atoms": xs.scatterers().size(),
            "element_counts": counters,
            "expected_asu_budget": {k: round(v, 1) for k, v in asu_budget.items()},
            "composition_known": bool(asu_budget),
            "branch": ("metal_coordination" if metal_branch
                       else "metal_free_density_tier"),
            "n_probable_unassigned_heavy_sites": n_probable_heavy,
            "n_peaks_dropped": len(sites) - len(kept),
            "n_symmetry_ghosts_removed": n_ghosts,
            **extra,
            "note": (
                ("C/N ambiguity unresolved; O assigned by metal-coordination "
                 "distance"
                 + ("; composition unknown - heavy sites left as C, element "
                    "identity must be reasoned/assigned" if not asu_budget
                    else "")) if metal_branch else
                "no metal in the composition, so no coordination window was "
                "used: elements come from the density tier. O is separated "
                "from C by the 33 % step in Z; C vs N (17 %) is NOT decided "
                "here - every such site is labelled C with "
                "element_uncertain=true. Give those sites an identity with "
                "edit_atoms once chemistry (connectivity, H count, the "
                "chem_hint motifs) or a converged Ueq (element_scan, "
                "probe_site, and validate_structure's "
                "light_atom_element_check after refinement - see ueq_hint) "
                "supports it"),
        })

    # ------------------------------------------------------------------
    @staticmethod
    def _metal_assignment(ses, kept: list[tuple], metals: list[str],
                          asu_budget: dict[str, float]) -> list[str]:
        """The metal-coordination lens, unchanged.

        Heavy-site count is adaptive: UNIT/order_z is only a lower bound because
        atoms on special positions occupy fewer general equivalents (a Zr6 node in
        I41/amd can put 24 Zr/cell on 2-3 distinct sites of order-32 symmetry).
        """
        assignments: list[str] = []
        metal_sites: list = []
        if metals:
            main = metals[0]
            expected = max(asu_budget.get(main, 1.0), 0.5)
            n_min = max(1, int(expected))
            n_max = max(n_min, int(math.ceil(expected * 2)) + 1)
            h_top = kept[0][1]
            for i, (site, h) in enumerate(kept):
                heavy = (i < n_min) or (i < n_max and h > 0.55 * h_top)
                if heavy:
                    assignments.append(main)
                    metal_sites.append(site)
                else:
                    assignments.append("?")
        else:
            assignments = ["?"] * len(kept)

        metal_cart = _sym_expanded_cart(ses.symmetry, metal_sites)
        # generous budgets: special positions inflate distinct-site counts
        o_budget = int(math.ceil(asu_budget.get("O", 0) * 2.5))
        m_prof = profile_for(metals[0]) if metals else None
        d_lo, d_hi = (m_prof.m_o_range if m_prof else (1.8, 2.6))
        n_o = 0
        for i, (site, h) in enumerate(kept):
            if assignments[i] != "?":
                continue
            d_m = _min_dist_to(ses.symmetry, metal_cart, site)
            if d_lo - 0.15 <= d_m <= d_hi + 0.1 and n_o < o_budget:
                assignments[i] = "O"
                n_o += 1
            else:
                assignments[i] = "C"
        return assignments

    # ------------------------------------------------------------------
    @staticmethod
    def _metal_free_assignment(ses, info: dict[str, Any], kept: list[tuple],
                               kept_idx: list[int],
                               asu_budget: dict[str, float]
                               ) -> tuple[list[str], list[dict[str, Any]],
                                          dict[str, Any]]:
        """Density-tier branch: no metal, therefore no coordination window."""
        integrated = info.get("peak_integrated_density")
        radius = info.get("peak_density_radius_A", 0.7)
        if (isinstance(integrated, (list, tuple))
                and len(integrated) == len(info["peak_sites"])):
            dens = [float(integrated[k]) for k in kept_idx]
            measure = {
                "density_measure": f"integrated density in a {radius} A "
                                   f"sphere around each peak",
                "density_units": info.get("peak_density_units") or "unknown",
                "ranked_by": ("integrated density (peak acceptance and the "
                              "symmetry-ghost filter still run in height "
                              "order, where a satellite is always the "
                              "weaker peak)")}
        else:
            dens = [float(h) for _, h in kept]
            measure = {
                "density_measure": "peak HEIGHT only",
                "density_units": "map value at the peak",
                "ranked_by": "peak height",
                "density_note": (
                    "no integrated peak density travelled with this peak "
                    "list - it is written by solve_charge_flipping / "
                    "solve_superflip and rides along in peaks.json - so the "
                    "tiers were read from peak heights instead. A height is "
                    "noisier than a 0.7 A integral; re-run the solver in "
                    "this session if a tier decision looks marginal")}

        elements, rows, context = assign_metal_free(
            dens, asu_budget, list(asu_budget), bool(asu_budget))
        for row, d in zip(rows, dens):
            row["density"] = round(float(d), 3)
        n_allow = asu_budget.get("N", 0.0)
        # the N budget is DISCLOSED, never spent; 2.5x is the same generous
        # distinct-site allowance the metal branch's O budget uses
        extra: dict[str, Any] = {
            **measure,
            "tier_context": context,
            "nitrogen_budget": {
                "n_allowed_per_asu": round(n_allow, 1),
                "distinct_site_allowance": int(math.ceil(n_allow * 2.5)),
                "n_assigned": 0,
                "note": ("disclosure only. The composition allows this much "
                         "nitrogen per ASU and none of it was assigned: N "
                         "and C differ by 17 % in Z (N and O by 14 %), which "
                         "an unrefined solution map cannot resolve. Place N "
                         "from chemistry - connectivity, H count, planarity, "
                         "the chem_hint motifs - or after a converged Ueq "
                         "(element_scan, probe_site), then edit_atoms "
                         "reassign" if n_allow > 0 else
                         "the composition declares no nitrogen; C-labelled "
                         "sites are still flagged element_uncertain, because "
                         "the composition is a hint and not a measurement")},
        }
        return elements, rows, extra


def adp_sweep(suspects, heavy_els, u_demote: float, u_delete: float):
    """Sort the refine engine's `adp_suspects` into (demote, delete, no_u):
    a heavy atom with a blown-up U is a mis-promoted light site (demote to
    O), a light atom with a huge U is a ghost (delete). An entry without a
    U value (`u_equiv: None` - the engine REVERTED the atom after a runaway
    cycle and has no ADP to report) carries no evidence either way and is
    only named: comparing that None crashed the whole tool on the R7 A1
    cage cell (2026-09-06 13:14) and cost the agent its completion route."""
    to_demote, to_delete, no_u = [], [], []
    for s in suspects or ():
        u = s.get("u_equiv")
        if u is None:
            no_u.append(s.get("atom", "?"))
            continue
        if s.get("element") in heavy_els:
            if u > u_demote:
                to_demote.append(s["atom"])
        elif u > u_delete:
            to_delete.append(s["atom"])
    return to_demote, to_delete, no_u


class FourierComplete(Tool):
    name = "fourier_complete"
    description = (
        "Iterative Fourier model completion (like repeated difference-map cycling in "
        "SHELXL/Olex2): refine -> add strong residual peaks as atoms -> delete atoms "
        "that refine badly -> repeat until stable. Use to grow a partial model to the "
        "full framework without spending many separate steps. Runs isotropic refinement "
        "internally; do a final anisotropic refine afterwards. BUDGET: no wall clock of "
        "its own - the cost is max_rounds (default 6) x (one internal refine + one "
        "difference map), and each internal refine carries refine's own timeout_s "
        "budget, so on a large model expect minutes (329 s measured on a 337-atom "
        "model). To bound it, lower max_rounds rather than waiting.")
    params_schema = {
        "type": "object",
        "properties": {
            "max_rounds": {"type": "integer", "default": 6},
            "min_peak_height": {"type": "number", "default": 1.2,
                                "description": "e/A^3 threshold for adding atoms"},
            "max_add_per_round": {"type": "integer", "default": 10},
            "element_default": {"type": "string", "default": "C"},
            "bonded_only": {"type": "boolean", "default": True,
                            "description": "only add peaks within bonding distance "
                                           "(2.3 A) of the existing model; isolated "
                                           "solvent density is left for solvent_mask"},
            "u_max_delete": {"type": "number", "default": 0.25,
                             "description": "delete atoms with Uiso above this"},
            "u_max_demote_heavy": {
                "type": "number", "default": 0.12,
                "description": "demote heavy-element atoms whose Uiso "
                               "exceeds this to a lighter element instead "
                               "of deleting"},
            "occupancy": {"type": "number", "default": 1.0},
        },
    }

    def run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        from .refinement_tools import RefineLS
        ses = ctx.session
        if ses.model is None:
            return ToolResult.failure("no model")
        refine = RefineLS()
        el = params.get("element_default", "C").capitalize()
        rounds = []
        last_r1 = None
        mask_active = ses.flags.get("f_mask") is not None
        for rnd in range(int(params.get("max_rounds", 6))):
            if mask_active:
                # model changed since the last mask -> recompute (cheap, ~1s)
                from .mask_tools import SolventMask
                SolventMask().run(ctx)
            r = refine.run(ctx, mode="isotropic", n_cycles=8,
                           label=f"fourier_cycle_{rnd}")
            if not r.ok:
                return ToolResult(ok=bool(rounds), summary={
                    "rounds": rounds, "stopped": f"refinement failed: {r.error}"})
            r1 = r.summary["r1_strong"]
            heavy_els = sorted(
                (e for e in ((ses.dataset.composition.elements if
                              ses.dataset.composition else {}) or {})
                 if is_metal(e) or _atomic_number(e) >= 17),
                key=_atomic_number, reverse=True)
            # element escalation: a strong difference peak sitting ON an atom means
            # that atom's element is too light (typically a metal modeled as C);
            # collapsed U is the same signal from the ADP side. Hard-capped by the
            # composition's plausible heavy-site count so escalation can't run away.
            ops = []
            if heavy_els:
                comp = ses.dataset.composition
                order_z = ses.symmetry.space_group().order_z()
                exp_heavy = sum((comp.elements.get(e, 0) * (comp.z or 1) / order_z)
                                for e in heavy_els) if comp else 1.0
                max_heavy = max(1, int(math.ceil(exp_heavy * 3)) + 1)
                n_heavy_now = sum(
                    1 for sc in ses.model.scatterers()
                    if sc.scattering_type.strip().capitalize() in heavy_els)
                budget = max(0, max_heavy - n_heavy_now)
                by_label = {sc.label: sc for sc in ses.model.scatterers()}
                too_light = set()
                for p in r.summary.get("diff_map_peaks", []):
                    if (p.get("height", 0) >= 4.0
                            and (p.get("nearest_d") or 9) <= 0.7):
                        lbl = p.get("nearest_atom")
                        sc = by_label.get(lbl)
                        if sc is not None and (sc.scattering_type.strip().capitalize()
                                               not in heavy_els):
                            too_light.add(lbl)
                for s in r.summary.get("adp_suspects", []):
                    if "too small" in s["issue"] and s["element"] not in heavy_els:
                        too_light.add(s["atom"])
                too_light = set(sorted(too_light)[:budget])
                if too_light:
                    ops.append({"action": "reassign", "atoms": sorted(too_light),
                                "element": heavy_els[0]})
                    ops.append({"action": "set_u_iso", "atoms": sorted(too_light),
                                "u_iso": 0.05})
            # delete unstable atoms (huge U = ghosts); a HEAVY atom with a blown-up
            # U is a mis-promoted light site - demote it instead of keeping it
            to_demote, to_delete, no_u = adp_sweep(
                r.summary.get("adp_suspects", []), heavy_els,
                float(params.get("u_max_demote_heavy", 0.12)),
                float(params.get("u_max_delete", 0.25)))
            if to_demote:
                ops.append({"action": "reassign", "atoms": to_demote, "element": "O"})
                ops.append({"action": "set_u_iso", "atoms": to_demote, "u_iso": 0.05})
            kept_real: list[str] = []
            if to_delete:
                # an atom the ghost ledger holds as REAL is not deleted by
                # an automatic sweep either - it is reported instead
                from ..refine import ghost_ledger
                pd = ghost_ledger.project_dir_from_ctx(ctx)
                if pd is not None:
                    protected = {
                        m["label"].upper()
                        for h in ghost_ledger.real_matches(pd, ses.model,
                                                           to_delete)
                        for m in h["match"]}
                    if protected:
                        kept_real = [lb for lb in to_delete
                                     if lb.upper() in protected]
                        to_delete = [lb for lb in to_delete
                                     if lb.upper() not in protected]
            if to_delete:
                ops.append({"action": "delete", "atoms": to_delete})
            if ops:
                EditAtoms().run(ctx, operations=ops)
            # add new atoms from residual density
            add = AddAtomsFromDifferenceMap().run(
                ctx, element=el,
                min_height=float(params.get("min_peak_height", 1.2)),
                max_add=int(params.get("max_add_per_round", 10)),
                occupancy=float(params.get("occupancy", 1.0)),
                max_dist_to_existing=(2.3 if params.get("bonded_only", True)
                                      else None))
            n_added = len(add.summary.get("added", [])) if add.ok else 0
            n_edits = sum(len(op["atoms"]) for op in ops)
            rounds.append({"round": rnd, "r1": r1, "edited": n_edits,
                           "added": n_added,
                           "n_atoms": ses.model.scatterers().size(),
                           **({"reverted_without_u": no_u,
                               "reverted_note": "the refinement reverted these "
                               "atoms after a runaway cycle and reports no U for "
                               "them; the sweep left them in place - judge them "
                               "with ghost_test / probe_site"} if no_u else {}),
                           **({"kept_real": kept_real,
                               "kept_real_note": "high-Uiso atoms the ghost "
                               "ledger holds as REAL were not deleted; give "
                               "them an identity or delete them yourself "
                               "with acknowledge_real"} if kept_real else {})})
            last_r1 = r1
            if n_added == 0 and n_edits == 0:
                break
        final = refine.run(ctx, mode="isotropic", n_cycles=10,
                           label="fourier_complete_final")
        summary = {"rounds": rounds,
                   "final": {k: final.summary.get(k) for k in
                             ("r1_strong", "r1_all", "wr2", "goof", "n_atoms",
                              "diff_map_max", "diff_map_min")} if final.ok else None,
                   "adp_suspects": (final.summary.get("adp_suspects") or [])[:10]
                   if final.ok else []}
        return ToolResult(ok=True, summary=summary)


#: acknowledge_real.reason must say something
ACK_REASON_MIN_CHARS = 15


def _check_acknowledgement(ack: Any, hit_labels: list[str]) -> str | None:
    """Why an acknowledge_real does not cover the ledger hits (None = ok)."""
    if ack is None:
        return "no acknowledge_real was given"
    if not isinstance(ack, dict):
        return ("acknowledge_real must be an object {labels: [...], "
                "reason: '...'}")
    labels = ack.get("labels")
    reason = ack.get("reason")
    if not isinstance(labels, list) or not labels:
        return ("acknowledge_real.labels must be a non-empty list of the "
                "atoms you are knowingly deleting")
    if not isinstance(reason, str) or len(reason.strip()) < ACK_REASON_MIN_CHARS:
        return (f"acknowledge_real.reason must say why (at least "
                f"{ACK_REASON_MIN_CHARS} characters)")
    acked = {str(lb).upper() for lb in labels}
    not_acked = [lb for lb in hit_labels if lb.upper() not in acked]
    if not_acked:
        return f"acknowledge_real.labels does not cover {not_acked}"
    return None


def _fmt_delta(v: Any) -> str:
    return f"{v:+.4f}" if isinstance(v, (int, float)) else "n/a"


def _ledger_refusal(hits: list[dict[str, Any]], hit_labels: list[str],
                    problem: str, had_ack: bool) -> str:
    from ..refine.tools_batch import GROUP_REAL_NOTE
    lines = [
        f"edit_atoms refused: {len(hit_labels)} atom(s) you asked to delete "
        f"({hit_labels}) were judged REAL by ghost_test and have not been "
        f"disposed of. A 'real' verdict is not a deletion licence - the "
        f"density is there and deleting the atom silently only hides it. "
        f"Nothing was changed (the other operations of this call were not "
        f"applied either)."]
    if had_ack:
        lines.append(f"acknowledge_real was given but {problem}.")
    lines.append("Evidence on the ghost ledger:")
    for h in hits:
        how = (f"as part of the group {'+'.join(h.get('labels') or [])}"
               if h.get("group") else "in a single-atom test")
        for m in h.get("match") or []:
            line = (f"  - {m['label']}: real {how} on baseline "
                    f"{h.get('baseline')} ({h.get('engine')}, "
                    f"{h.get('cycles')} cycles, {h.get('timestamp')}): dR1 "
                    f"{_fmt_delta(h.get('delta_r1'))}, peak "
                    f"{h.get('peak_at_site')} e/A^3 returned at the vacated "
                    f"site")
            if h.get("r1_fence_informative") is False:
                line += (" [dR1 fence below the detectability floor - the "
                         "verdict rested on the returning peak]")
            if m.get("by") == "site":
                line += (f" [matched by site: {m.get('d_A')} A from ledger "
                         f"atom {m.get('ledger_label')}]")
            if h.get("group"):
                line += f"; {GROUP_REAL_NOTE}"
            lines.append(line)
    lines.append("Three ways forward:")
    lines.append(
        "  (a) reassign / rename - give the density a chemical identity: "
        "edit_atoms reassign to the element the site's chemistry and "
        "electron count say (a lone O/N with collapsed Ueq is often a "
        "halide; a channel atom may be guest, solvent or a disorder "
        "component), or rename_atoms(mode='map') to a label that states "
        "what it is (OW for water);")
    lines.append(
        "  (b) refine it at free occupancy - element_scan(site=<label>, "
        "elements=[...], free_occupancy=true) or probe_site reads occupancy "
        "x Z, the electron count the data actually pin down;")
    lines.append(
        "  (c) if it really must go (e.g. the solvent mask will absorb this "
        "density), re-issue this SAME call with acknowledge_real="
        "{\"labels\": [" + ", ".join(f"\"{lb}\"" for lb in hit_labels)
        + "], \"reason\": \"...\"} - both fields required, reason >= "
        f"{ACK_REASON_MIN_CHARS} characters; the deletion and your reason "
        "are then written to the ledger.")
    return "\n".join(lines)


class EditAtoms(Tool):
    name = "edit_atoms"
    description = (
        "Apply explicit edits to the working model: delete atoms, reassign element, "
        "set occupancy, set u_iso, move, set_part / clear_part (SHELX PART "
        "block; reversible with model_disorder(undo=<label>)). Use after "
        "diagnosing problems (ghost peaks, wrong element, disorder). Atom "
        "labels refer to the current model summary. Deleting an atom also "
        "clears its PART state and marks splits that included it as stale. "
        "Deleting an atom that ghost_test judged REAL (alone or as a group "
        "member; matched by label or by site) is refused with the evidence "
        "unless the call carries acknowledge_real={labels, reason}.")
    params_schema = {
        "type": "object",
        "properties": {
            "operations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string",
                                   "enum": ["delete", "reassign", "set_occupancy",
                                            "set_u_iso", "move", "set_part",
                                            "clear_part"]},
                        "atoms": {"type": "array", "items": {"type": "string"},
                                  "description": "atom labels, e.g. ['C12','O3']"},
                        "element": {"type": "string", "description": "for reassign"},
                        "occupancy": {"type": "number"},
                        "u_iso": {"type": "number"},
                        "part": {"type": "integer",
                                 "description": "for set_part: SHELX PART "
                                                "number (0 clears; n > 0 = "
                                                "component n, which bonds "
                                                "only to PART 0 and its own "
                                                "component; negative = the "
                                                "component also does not "
                                                "bond to its symmetry "
                                                "equivalents)"},
                        "site": {"type": "array", "items": {"type": "number"},
                                 "description": "fractional x,y,z for move (one atom "
                                                "per operation); occupancy is auto-"
                                                "scaled to conserve atom count when "
                                                "site multiplicity changes (e.g. "
                                                "moving off a special position to "
                                                "model a split/disordered site)"},
                    },
                    "required": ["action", "atoms"],
                },
            },
            "acknowledge_real": {
                "type": "object",
                "description": (
                    "needed to delete an atom the ghost ledger holds as REAL "
                    "(ghost_test verdict 'real', alone or as a group member): "
                    "the labels you are knowingly deleting and why (>= "
                    f"{ACK_REASON_MIN_CHARS} characters, e.g. 'absorbed into "
                    "the solvent mask: diffuse channel density, no fragment "
                    "fits'). Without it such a delete is refused with the "
                    "evidence and the alternatives (name it / refine it at "
                    "free occupancy); with it the reason is written to the "
                    "ledger."),
                "properties": {
                    "labels": {"type": "array", "items": {"type": "string"}},
                    "reason": {"type": "string"},
                },
                "required": ["labels", "reason"],
            },
        },
        "required": ["operations"],
    }

    @staticmethod
    def _ledger_guard(ctx: ToolContext, xs, to_delete: set[int],
                      params: dict[str, Any]) -> dict[str, Any] | None:
        """Consult the ghost ledger before a delete. None = nothing to say
        (no project, no hits, or an internal diagnostic delete); otherwise
        {ok: False, error} or {ok: True, ...} with what to write back."""
        from ..refine import ghost_ledger
        project_dir = ghost_ledger.project_dir_from_ctx(ctx)
        if project_dir is None:
            return None
        labels = [xs.scatterers()[i].label for i in sorted(to_delete)]
        hits = ghost_ledger.real_matches(project_dir, xs, labels)
        if not hits:
            return None
        if params.get("_diagnostic"):
            # round-3 WP6: a diagnostic delete (probe_site / ghost_test on an
            # isolated branch) is the test itself, not a disposition. The
            # 'real' verdicts stand and keep protecting the atoms on the
            # main line; the touch is recorded so the audit trail shows
            # which tests re-examined a protected atom. (Before: probe_site
            # hit this guard, was refused, and recommended itself.)
            touched: list[str] = []
            for h in hits:
                for m in h["match"]:
                    if m["label"].upper() not in {x.upper() for x in touched}:
                        touched.append(m["label"])
            try:
                ghost_ledger.note_diagnostic_touch(
                    project_dir, touched,
                    str(params.get("_diagnostic_reason") or "diagnostic delete"))
            except Exception:  # noqa: BLE001 - the audit note must not block the test
                pass
            return {"ok": True, "diagnostic": True, "labels": touched,
                    "applicability": [
                        f"diagnostic delete of {', '.join(touched)}: the ghost "
                        f"ledger holds them as real; no disposition was "
                        f"written and the protection stands"]}
        hit_labels: list[str] = []
        ledger_labels: list[str] = []
        for h in hits:
            for m in h["match"]:
                if m["label"].upper() not in {x.upper() for x in hit_labels}:
                    hit_labels.append(m["label"])
                if m.get("ledger_label"):
                    ledger_labels.append(m["ledger_label"])
        ack = params.get("acknowledge_real")
        problem = _check_acknowledgement(ack, hit_labels)
        if problem:
            return {"ok": False,
                    "error": _ledger_refusal(hits, hit_labels, problem,
                                             ack is not None)}
        reason = str(ack["reason"]).strip()
        return {"ok": True, "project_dir": project_dir, "hits": hits,
                "labels": hit_labels, "ledger_labels": ledger_labels,
                "reason": reason,
                "acknowledged": [{"label": lb, "reason": reason}
                                 for lb in hit_labels]}

    def run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        ses = ctx.session
        if ses.model is None:
            return ToolResult.failure("no model to edit")
        xs = ses.model
        by_label = {sc.label: i for i, sc in enumerate(xs.scatterers())}
        # case-fold fallback: SHELX labels are case-insensitive in spirit,
        # and 'Ni1' vs 'NI1' silently no-opping burned two campaigns (r10
        # fake-Mg refinement 13:35:04, r22 blind arm's wasted Cu branch)
        by_upper: dict[str, list[int]] = {}
        for lbl, i in by_label.items():
            by_upper.setdefault(lbl.upper(), []).append(i)
        # pass 1: resolve every label BEFORE anything is touched - a refusal
        # (unknown labels, the ghost-ledger guard) must leave the model
        # exactly as it was, not with this call's reassigns half applied
        resolved: list[tuple[dict[str, Any], list[int]]] = []
        missing: list[str] = []
        case_folded: list[str] = []
        for op in params["operations"]:
            idxs = []
            for lbl in op["atoms"]:
                if lbl in by_label:
                    idxs.append(by_label[lbl])
                    continue
                fold = by_upper.get(lbl.upper())
                if fold and len(fold) == 1:
                    idxs.append(fold[0])
                    case_folded.append(
                        f"{lbl}->{xs.scatterers()[fold[0]].label}")
                else:
                    missing.append(lbl)
            resolved.append((op, idxs))
        for op, _idxs in resolved:
            if op["action"] == "set_part":
                p = op.get("part")
                if (isinstance(p, bool) or not isinstance(p, (int, float))
                        or float(p) != int(p)):
                    return ToolResult.failure(
                        "set_part needs an integer 'part' (SHELX PART "
                        "number: 0 = no block, n > 0 = component n, "
                        "negative = no bonds to symmetry equivalents; "
                        "clear_part removes the block); nothing was changed")
        applied = [{"action": op["action"], "n": len(idxs)}
                   for op, idxs in resolved]

        if missing and not any(a["n"] for a in applied):
            # every label missed: this MUST fail loudly. The old ok:true +
            # unknown_labels shape let a fake element-competition branch
            # refine the unchanged model (r10 132717: reassign Al->Mg
            # no-opped, the 'Mg test' refined pure Al)
            import difflib
            sugg = {m: [xs.scatterers()[i].label
                        for c in difflib.get_close_matches(
                            m.upper(), list(by_upper), n=2, cutoff=0.6)
                        for i in by_upper[c]]
                    for m in missing}
            return ToolResult.failure(
                f"no operation matched any atom - unknown labels "
                f"{missing}; nothing was changed. Close existing labels: "
                f"{sugg}. (Labels are matched case-insensitively when "
                f"unambiguous, so this means the atoms really are not in "
                f"the model - inspect_model detail='atoms' for the "
                f"current table.)")

        to_delete: set[int] = {i for op, idxs in resolved
                               if op["action"] == "delete" for i in idxs}
        # ghost-ledger guard: an atom ghost_test judged real is not deleted
        # without an acknowledged reason (checked before any edit lands)
        guard = (self._ledger_guard(ctx, xs, to_delete, params)
                 if to_delete else None)
        if guard is not None and not guard["ok"]:
            return ToolResult.failure(guard["error"])

        # pass 2: apply
        moved_info: list[dict[str, Any]] = []
        moves: dict[int, tuple] = {}
        part_edits: list[tuple[str, int | None]] = []
        for op, idxs in resolved:
            action = op["action"]
            for i in idxs:
                sc = xs.scatterers()[i]
                if action == "reassign":
                    sc.scattering_type = op["element"].capitalize()
                elif action == "set_occupancy":
                    sc.occupancy = float(op["occupancy"])
                elif action == "set_u_iso":
                    sc.u_iso = float(op["u_iso"])
                elif action == "move" and op.get("site"):
                    moves[i] = tuple(float(x) for x in op["site"])
                elif action == "set_part":
                    part_edits.append((sc.label, int(op["part"])))
                elif action == "clear_part":
                    part_edits.append((sc.label, None))

        if moves:
            # rebuild so site-symmetry/multiplicity are recomputed; conserve atom
            # count by rescaling occupancy when multiplicity changes (split sites)
            sps = crystal.special_position_settings(
                ses.symmetry, min_distance_sym_equiv=0.5)
            new = xray.structure(special_position_settings=sps)
            old_mults = [sc.multiplicity() for sc in xs.scatterers()]
            for i, sc in enumerate(xs.scatterers()):
                u = sc.u_star if sc.flags.use_u_aniso() else sc.u_iso
                new.add_scatterer(xray.scatterer(
                    label=sc.label, site=moves.get(i, sc.site),
                    scattering_type=sc.scattering_type, u=u,
                    occupancy=sc.occupancy))
            for i in moves:
                sc = new.scatterers()[i]
                mult_new = sc.multiplicity()
                if mult_new and old_mults[i] != mult_new:
                    sc.occupancy = sc.occupancy * old_mults[i] / mult_new
                    moved_info.append({"atom": sc.label,
                                       "multiplicity": f"{old_mults[i]}->{mult_new}",
                                       "occupancy": round(sc.occupancy, 3)})
            xs = new
            ses.model = xs
        part_changes: dict[str, Any] = {}
        if part_edits:
            # round-3 WP3: PART is explicit, recorded and reversible - the
            # previous assignment goes on disorder_origins as a part_edit
            from ..refine.parts import apply_part_edits
            part_changes = apply_part_edits(ses.flags, part_edits,
                                            by="edit_atoms")
        pruned_meta = 0
        dropped_rs: list[str] = []
        dropped_cards: list[str] = []
        part_hygiene: dict[str, Any] = {}
        if to_delete:
            from cctbx.array_family import flex
            deleted_labels = {xs.scatterers()[i].label.upper()
                              for i in to_delete}
            keep = flex.bool([i not in to_delete for i in range(xs.scatterers().size())])
            ses.model = xs.select(keep)
            # stale-metadata hygiene: a deleted H left in h_riding_meta gets
            # silently REBUILT by the next riding-H replay (live CD-MOF
            # failure: removed H6J kept coming back); riding constraints
            # hold scatterer indices that the select() just invalidated
            h_meta = ses.flags.get("h_riding_meta") or {}
            per_carrier = h_meta.get("per_carrier") or []
            if per_carrier:
                kept_groups = []
                for g in per_carrier:
                    if g.get("carrier", "").upper() in deleted_labels:
                        pruned_meta += 1
                        continue
                    hs = [h for h in g.get("h", [])
                          if h.upper() not in deleted_labels]
                    if len(hs) != len(g.get("h", [])):
                        pruned_meta += 1
                    if hs:
                        kept_groups.append({**g, "h": hs})
                h_meta["per_carrier"] = kept_groups
                ses.flags["h_riding_meta"] = h_meta
            if ses.flags.pop("h_constraints", None) is not None:
                pruned_meta += 1
            # same-fate hygiene for restraints: a spec referencing a
            # deleted atom rides into every future SHELXL job and aborts
            # it (r12 CD-MOF: author DFIX/DANG on a deleted H)
            rs = ses.flags.get("restraints")
            if isinstance(rs, list) and rs:
                from ..refine.restraints import prune_specs_for_deleted
                kept_rs, dropped_rs = prune_specs_for_deleted(
                    rs, deleted_labels)
                if dropped_rs:
                    ses.flags["restraints"] = kept_rs
            # same-fate hygiene for PART state (round-3 WP3): the label
            # leaves parts_extra and its disorder group, and every split
            # record naming it is marked stale - before this, a same-name
            # atom added later inherited the old PART and undo would have
            # "restored" it (forensic T-b)
            from ..refine.parts import prune_parts_for_deleted
            part_hygiene = prune_parts_for_deleted(
                ses.flags, deleted_labels, by="edit_atoms delete")
            # WP2: an effective instruction card naming a deleted atom
            # would abort every later SHELXL job (same policy as restraints)
            if ses.flags.get("effective_cards"):
                from ..refine.shelx_cards import prune_cards_for_deleted
                kept_c, dropped_cards = prune_cards_for_deleted(
                    ses.flags["effective_cards"], deleted_labels)
                if dropped_cards:
                    if kept_c:
                        ses.flags["effective_cards"] = kept_c
                    else:
                        ses.flags.pop("effective_cards", None)
                        ses.flags.pop("effective_cards_job", None)
        # re-register scattering tables after type changes
        ses.model.scattering_type_registry(table="it1992")
        acknowledged: list[dict[str, str]] = []
        diagnostic_note = (guard.get("applicability")
                           if guard is not None and guard.get("diagnostic")
                           else None)
        if guard is not None and to_delete and not guard.get("diagnostic"):
            # the disposal goes on the ledger with the reason, so the same
            # atom is not blocked twice and the decision is on file
            from ..refine import ghost_ledger
            acknowledged = guard["acknowledged"]
            try:
                ghost_ledger.mark_disposed(
                    guard["project_dir"],
                    guard["ledger_labels"] or guard["labels"],
                    f"deleted by edit_atoms with acknowledge_real: "
                    f"{guard['reason']}",
                    entry_ids=[h["id"] for h in guard["hits"] if h.get("id")])
            except Exception:  # noqa: BLE001 - the write-back must not undo the edit
                pass
        return ToolResult(ok=True, summary={
            "applied": applied, "unknown_labels": missing,
            **({"applicability": diagnostic_note} if diagnostic_note else {}),
            **({"real_atoms_deleted_with_reason": acknowledged,
                "ledger_note": "these atoms were on the ghost ledger as "
                "REAL; the deletion and your reason are now recorded "
                "there - report the disposal (e.g. mask electron count) "
                "in the delivery"} if acknowledged else {}),
            **({"warning": f"{len(missing)} label(s) not found and "
                           f"SKIPPED: {missing} - the other edits were "
                           f"applied; re-issue the missing ones with "
                           f"correct labels"} if missing else {}),
            **({"case_folded": case_folded} if case_folded else {}),
            "moved": moved_info,
            **({"h_metadata_pruned": pruned_meta,
                "h_metadata_note": "deleted atoms removed from riding-H "
                "metadata; in-process riding constraints cleared (indices "
                "invalidated) - re-run add_hydrogens if riding refinement "
                "is needed"} if pruned_meta else {}),
            **({"restraints_pruned": dropped_rs,
                "restraints_note": "restraints referencing deleted atoms "
                "were pruned in the same edit (they would abort the next "
                "SHELXL job); re-state replacements via set_restraints if "
                "still chemically needed"} if dropped_rs else {}),
            **({"parts": part_changes} if part_changes else {}),
            **({"cards_pruned": dropped_cards,
                "cards_note": "effective SHELXL instruction cards naming "
                "deleted atoms were dropped in the same edit (they would "
                "abort the next job); restate replacements via "
                "run_shelxl(extra_cards=...) if still needed"}
               if dropped_cards else {}),
            **({"part_hygiene": part_hygiene,
                "part_note": "PART state of the deleted atoms was cleared "
                "(parts_extra / disorder-group members); splits that "
                "included them are marked stale and can no longer be "
                "undone - checkout the pre-split node instead"}
               if part_hygiene else {}),
            "n_atoms": ses.model.scatterers().size()})


class AddAtomsFromDifferenceMap(Tool):
    name = "add_atoms_from_difference_map"
    description = (
        "Add new atoms at residual-density peaks found by the last refinement "
        "(stored difference-map peaks). Use to recover missing atoms or locate "
        "guest/solvent. Specify element and which peak indices to use. "
        "sites=[[x,y,z],...] places atoms at explicit FRACTIONAL coordinates "
        "instead - for a position you derived yourself (a symmetry image, a "
        "midpoint, a site read off another model) rather than picked from the "
        "peak list; no prior refinement is needed on that route.")
    params_schema = {
        "type": "object",
        "properties": {
            "peak_indices": {"type": "array", "items": {"type": "integer"},
                             "description": "indices into the last diff-map peak list"},
            "sites": {"type": "array",
                      "items": {"type": "array", "items": {"type": "number"}},
                      "description": "explicit fractional coordinates "
                                     "[[x,y,z],...]. Mutually exclusive with "
                                     "peak_indices. The peak-list distance "
                                     "guards do not apply (you chose the "
                                     "position deliberately) - the distance to "
                                     "the nearest atom is reported for each "
                                     "one instead, and an impossible overlap "
                                     "(<0.5 A) is refused"},
            "labels": {"type": "array", "items": {"type": "string"},
                       "description": "optional labels for sites= (same order); "
                                      "auto-numbered when omitted"},
            "element": {"type": "string", "default": "C"},
            "occupancy": {"type": "number", "default": 1.0},
            "min_height": {"type": "number", "default": 1.0,
                           "description": "e/A^3 floor when peak_indices omitted"},
            "max_add": {"type": "integer", "default": 5},
            "min_dist_to_existing": {"type": "number",
                                     "description": "skip peaks closer than this (A) to "
                                                    "any existing atom (ADP residuals). "
                                                    "Default 1.05, or 0.70 for "
                                                    "element='H' (X-H bonds are "
                                                    "0.85-1.1 A)"},
            "max_dist_to_existing": {"type": ["number", "null"], "default": None,
                                     "description": "if set, only add peaks within this "
                                                    "distance (A) of an existing atom - "
                                                    "grows the bonded framework and "
                                                    "leaves isolated solvent density "
                                                    "for masking"},
        },
    }

    def run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        ses = ctx.session
        if ses.model is None:
            return ToolResult.failure("no model")
        if params.get("sites") is not None:
            if params.get("peak_indices") is not None:
                return ToolResult.failure(
                    "pass either sites= (explicit coordinates) or "
                    "peak_indices= (from the difference map), not both")
            return self._add_at_sites(ses, params)
        peaks = ses.flags.get("diff_map_peaks") or []
        if not peaks:
            # pa1 x7: the old text recommended the dearest remedy (refine)
            # while inspect_map rebuilds the table in ~1-2 s; and the table
            # now persists with the node, so a branch no longer loses it.
            return ToolResult.failure(
                "no difference-map peak table in this session: none is "
                "stored with the active node (peaks.json beside model.res "
                "is written by refine, run_shelxl mode='adopt' and "
                "inspect_map, and restored by checkout/branch). Run "
                "inspect_map (~1-2 s) to compute the table on the current "
                "model - each listed peak's 'i' is the peak_indices value - "
                "or pass sites=[[x,y,z],...] to place atoms at coordinates "
                "you derived yourself.")
        el = params.get("element", "C").capitalize()
        idxs = params.get("peak_indices")
        if idxs is None:
            floor = float(params.get("min_height", 1.0))
            idxs = [i for i, p in enumerate(peaks) if p["height"] >= floor]
        xs = ses.model
        # X-H bonds are 0.85-1.1 A: the 1.05 A anti-ADP-noise floor would
        # reject every genuine H peak next to its carrier (round-10 #13:
        # H33 candidates at 1.04 A returned added=[])
        min_d = float(params.get("min_dist_to_existing",
                                 0.70 if el == "H" else 1.05))
        max_d = params.get("max_dist_to_existing")
        existing_cart = _sym_expanded_cart(
            ses.symmetry, [sc.site for sc in xs.scatterers()])
        heavy_cart = _sym_expanded_cart(
            ses.symmetry,
            [sc.site for sc in xs.scatterers()
             if is_metal(sc.scattering_type.strip().capitalize())
             or _atomic_number(sc.scattering_type.strip().capitalize()) >= 17])

        def _admissible(i: int) -> bool:
            if not (0 <= i < len(peaks)):
                return False
            site = peaks[i]["site"]
            d = _min_dist_to(ses.symmetry, existing_cart, site)
            if d < min_d or (max_d is not None and d > float(max_d)):
                return False
            # nothing bonds to a metal closer than ~1.8 A in a MOF; peaks in the
            # 1.0-1.75 A shell around heavy atoms are ADP/series-termination
            # noise (H peaks: keep only the metal-hydride floor)
            heavy_floor = 1.0 if el == "H" else 1.75
            if len(heavy_cart) and _min_dist_to(
                    ses.symmetry, heavy_cart, site) < heavy_floor:
                return False
            return True

        idxs = [i for i in idxs if _admissible(i)]
        idxs = idxs[: int(params.get("max_add", 5))]
        existing = sum(1 for sc in xs.scatterers()
                       if sc.scattering_type.strip().capitalize() == el)
        # collision-proof numbering: the count-based label collided with a
        # SURVIVING atom after deletions shifted the count (r22 live: two
        # C29X in one model, delivered CIF carried the duplicate and the
        # res round-trip silently collapsed them)
        taken = {sc.label.upper() for sc in xs.scatterers()}
        added = []
        n_lbl = existing
        for i in idxs:
            p = peaks[i]
            n_lbl += 1
            label = f"{el}{n_lbl}X"
            while label.upper() in taken:
                n_lbl += 1
                label = f"{el}{n_lbl}X"
            taken.add(label.upper())
            xs.add_scatterer(xray.scatterer(
                label=label, site=tuple(p["site"]), scattering_type=el,
                u=0.06, occupancy=float(params.get("occupancy", 1.0))))
            added.append({"label": label, "height": p["height"],
                          "nearest_atom": p.get("nearest_atom"),
                          "nearest_d": p.get("nearest_d")})
        pm = ses.flags.get("diff_map_peaks_meta") or {}
        return ToolResult(ok=True, summary={
            "added": added, "n_atoms": xs.scatterers().size(),
            # which table the indices were read from (a table computed on
            # an earlier node is still usable - positions do not move with
            # an element change - but the agent must know it is that one)
            "peak_table": {"n_peaks": len(peaks),
                           "source": pm.get("source"),
                           "computed_on": pm.get("node")}})

    @staticmethod
    def _add_at_sites(ses, params: dict[str, Any]) -> ToolResult:
        """Explicit fractional coordinates. The peak-list guards exist to
        filter NOISE out of an automatic pick; a site the caller computed is
        a decision, so here only a physically impossible overlap is refused
        and every distance is reported for judgement."""
        el = str(params.get("element", "C")).capitalize()
        raw = params.get("sites") or []
        sites: list[tuple[float, float, float]] = []
        for s in raw:
            try:
                x, y, z = (float(v) for v in s)
            except (TypeError, ValueError):
                return ToolResult.failure(
                    f"sites entries must be [x, y, z] fractional coordinates, "
                    f"got {s!r}")
            sites.append((x, y, z))
        if not sites:
            return ToolResult.failure("sites=[] adds nothing")
        labels_in = [str(x) for x in (params.get("labels") or [])]
        if labels_in and len(labels_in) != len(sites):
            return ToolResult.failure(
                f"labels has {len(labels_in)} entries but sites has "
                f"{len(sites)}")
        xs = ses.model
        taken = {sc.label.upper() for sc in xs.scatterers()}
        dup = [lb for lb in labels_in if lb.upper() in taken]
        if dup:
            return ToolResult.failure(f"labels already in the model: {dup}")
        existing_cart = _sym_expanded_cart(
            ses.symmetry, [sc.site for sc in xs.scatterers()])
        # check every site BEFORE touching the model: a refusal halfway
        # through would leave a half-applied edit behind
        dists = [_min_dist_to(ses.symmetry, existing_cart, s) for s in sites]
        for site, d in zip(sites, dists):
            if d < 0.5:
                return ToolResult.failure(
                    f"site {site} sits {d:.2f} A from an existing atom - that "
                    "is an overlap, not a new site; no atoms were added")
        occ = float(params.get("occupancy", 1.0))
        n_lbl = sum(1 for sc in xs.scatterers()
                    if sc.scattering_type.strip().capitalize() == el)
        added, warnings = [], []
        for k, (site, d) in enumerate(zip(sites, dists)):
            if labels_in:
                label = labels_in[k]
            else:
                n_lbl += 1
                label = f"{el}{n_lbl}X"
                while label.upper() in taken:
                    n_lbl += 1
                    label = f"{el}{n_lbl}X"
            taken.add(label.upper())
            xs.add_scatterer(xray.scatterer(
                label=label, site=site, scattering_type=el,
                u=0.06, occupancy=occ))
            added.append({"label": label, "site": [round(v, 5) for v in site],
                          "nearest_d": round(d, 3)})
            if d < 1.05 and el != "H":
                warnings.append(
                    f"{label} is only {d:.2f} A from the nearest atom - "
                    "check this is a real site and not ADP residual")
        return ToolResult(ok=True, summary={
            "added": added, "n_atoms": xs.scatterers().size(),
            "mode": "explicit_sites",
            "note": ("placed at the coordinates you gave; refine and check "
                     "the difference map - nothing validated these sites"),
            **({"warnings": warnings} if warnings else {})})
