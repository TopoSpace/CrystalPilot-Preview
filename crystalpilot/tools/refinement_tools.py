"""Least-squares refinement tool (smtbx crystallographic_ls, olex2.refine engine core)
with full diagnostics: R factors, GooF, difference map analysis, per-atom ADP sanity.
"""
from __future__ import annotations

from typing import Any

import numpy as np
from cctbx import adptbx, maptbx
from cctbx.array_family import flex
from scitbx.lstbx import normal_eqns_solving
from smtbx.refinement import constraints, least_squares
import smtbx.utils

from ..pipeline.session import RefinementSnapshot
from .base import Tool, ToolContext, ToolResult
from .budget import budget_for, default_timeout_s, timeout_param
from ..io.shelx_codes import unencodable_free_params


def _snapshot_params(xs) -> dict[str, dict]:
    """Per-atom site/ADP before the cycles, so a runaway parameter can be
    reverted instead of committed (see _revert_unencodable)."""
    uc = xs.unit_cell()
    out: dict[str, dict] = {}
    for sc in xs.scatterers():
        out[sc.label] = {"site": tuple(sc.site),
                         "aniso": bool(sc.flags.use_u_aniso()),
                         "u_star": tuple(sc.u_star), "u_iso": float(sc.u_iso),
                         "u_eq": float(sc.u_iso_or_equiv(uc))}
    return out


def _revert_unencodable(xs, start: dict[str, dict]) -> list[dict]:
    """Atoms whose refined site/ADP the SHELX format cannot store (|value|
    >= 5, io.shelx_codes) are reverted to their pre-cycle values and
    reported. An ADP at U33 = 16 A^2 is a diverged refinement, not a
    result: reg1-mof cage n0152 (2026-09-04) committed one and the node
    could never be read again (iotbx IndexError in checkout/ghost_test)."""
    uc = xs.unit_cell()
    reverted: list[dict] = []
    for sc in xs.scatterers():
        u_cif = (adptbx.u_star_as_u_cif(uc, sc.u_star)
                 if sc.flags.use_u_aniso() else None)
        bad = unencodable_free_params(sc.site, u_iso=sc.u_iso, u_cif=u_cif)
        if not bad:
            continue
        s0 = start.get(sc.label)
        rec: dict[str, Any] = {
            "atom": sc.label,
            "element": sc.scattering_type.strip().capitalize(),
            "runaway": {n: round(v, 3) for n, v in bad}}
        if any(n in ("x", "y", "z") for n, _ in bad):
            if s0 is not None:
                sc.site = s0["site"]
            rec["site"] = "reverted to the pre-refinement position"
        if any(n.startswith("U") for n, _ in bad):
            grad = bool(sc.flags.grad_u_aniso() or sc.flags.grad_u_iso())
            if s0 is not None and s0["aniso"]:
                sc.u_star = s0["u_star"]
                sc.set_use_u_aniso_only()
                sc.flags.set_grad_u_aniso(grad)
                sc.flags.set_grad_u_iso(False)
                rec["adp"] = ("reverted to the pre-refinement anisotropic "
                              f"ADP (Ueq {s0['u_eq']:.4f})")
            else:
                sc.set_use_u_iso_only()
                sc.u_iso = float(s0["u_iso"]) if s0 is not None else 0.05
                sc.flags.set_grad_u_iso(grad)
                sc.flags.set_grad_u_aniso(False)
                rec["adp"] = (f"reverted to isotropic Uiso {sc.u_iso:.4f}"
                              + (" (as before this call)" if s0 is not None
                                 else " (placeholder)"))
        reverted.append(rec)
    return reverted


class _BudgetedLM(normal_eqns_solving.levenberg_marquardt_iterations):
    """Levenberg-Marquardt with a wall-clock / cancel check per cycle.

    The check sits in `had_too_small_a_step()`, which upstream calls once per
    cycle right after `solve()` and BEFORE `step_forward()`. Returning True
    there ends the loop through the same door a converged refinement uses, so
    the structure is left exactly at the last COMPLETED cycle - a state the
    node store can hold safely. Nothing is half-applied and no shift is left
    dangling, which is why `refine` may commit its partial result as a node
    instead of throwing the work away."""

    budget = None
    stopped_by = None

    def had_too_small_a_step(self):  # noqa: D102
        if self.budget is not None:
            reason = self.budget.stop_reason()
            if reason is not None:
                self.stopped_by = reason
                return True
            self.budget.tick(f"least squares, cycle {self.n_iterations}")
        return super().had_too_small_a_step()


def difference_map_real(ses, xs, f_mask=None, kind: str = "fofc"):
    """FFT map. Returns (fft_map, real_map, k_scale) or raises.

    kind="fofc" (default): Fo-Fc difference amplitudes - residual peaks.
    kind="2fofc": 2Fo-Fc amplitudes - the model-phased OBSERVED density
    (Coot convention; framework density readable at low resolution).

    If f_mask (solvent mask contribution, same set/order as fo_sq) is given, it is
    added to f_calc so masked solvent density does not reappear as difference peaks.
    """
    fo_sq = ses.fo_sq
    f_calc = fo_sq.structure_factors_from_scatterers(
        xray_structure=xs, algorithm="direct").f_calc()
    if f_mask is not None:
        f_calc = f_calc.customized_copy(data=f_calc.data() + f_mask.data())
    from .twin_maps import detwinned_amplitudes
    fo, map_provenance = detwinned_amplitudes(ses, xs, f_calc, f_mask)
    fc_abs = flex.abs(f_calc.data())
    denom = flex.sum(fc_abs * fc_abs)
    if denom <= 0:
        raise ValueError("zero Fc")
    k = flex.sum(fo.data() * fc_abs) / denom
    phases = f_calc.phases().data()
    if kind == "2fofc":
        amp_diff = 2.0 * fo.data() / k - fc_abs
    else:
        amp_diff = fo.data() / k - fc_abs      # may be negative -> holes
    unit_phase = flex.polar(flex.double(amp_diff.size(), 1.0), phases)
    zeros = flex.double(amp_diff.size(), 0.0)
    diff = f_calc.customized_copy(
        data=unit_phase * flex.complex_double(amp_diff, zeros))
    fft_map = diff.fft_map(symmetry_flags=maptbx.use_space_group_symmetry,
                           resolution_factor=1 / 3)
    fft_map.apply_volume_scaling()
    fft_map.crystalpilot_map_provenance = map_provenance
    return fft_map, fft_map.real_map_unpadded(), float(k)


def _difference_map_analysis(ses, xs, n_peaks: int = 40, f_mask=None) -> dict[str, Any]:
    """(Fo-Fc) map: extremes in e/A^3 + positive peaks with nearest-atom context."""
    try:
        fft_map, real, k = difference_map_real(ses, xs, f_mask=f_mask)
    except ValueError as e:
        return {"error": str(e)}
    mn, mx = flex.min(real), flex.max(real)

    peaks = fft_map.peak_search(
        maptbx.peak_search_parameters(
            interpolate=True, min_distance_sym_equiv=0.7,
            min_cross_distance=0.9, max_clusters=n_peaks),
        verify_symmetry=False).all()
    peak_list = annotate_peaks(xs, peaks.sites(), peaks.heights())
    return {"max": round(float(mx), 2), "min": round(float(mn), 2),
            "peaks": peak_list, "scale_k": float(k),
            "map_provenance": fft_map.crystalpilot_map_provenance}


#: chem_hint fences (generic crystal chemistry, not tuned to one crystal)
TERMINAL_O_METAL_MAX_A = 2.7     # an O counts as bonded to a metal below this
TERMINAL_O_LIGHT_MAX_A = 1.9     # ...and to a non-H light atom below this
HINT_TERMINAL_O_C = (1.15, 1.65)  # peak-to-terminal-O distance of a C
HINT_METAL_DONOR = (1.9, 2.6)     # peak-to-metal distance of a donor atom

CHEM_HINT_TERMINAL_O_CARBON = (
    "C bonded to a terminal node O: carboxylate / carbonate / formate carbon "
    "candidate (a guest bound to the node?)")
CHEM_HINT_METAL_DONOR = "possible ligand donor atom (O/N/Cl) on the metal"


def _sym_min_distances(xs, i: int) -> np.ndarray:
    """Shortest distance from atom i to every atom of the model over all
    symmetry images (+/- one cell); entry i is its own nearest image
    (0 unless a symmetry copy is closer)."""
    uc = xs.unit_cell()
    scs = xs.scatterers()
    atom_cart = np.array([uc.orthogonalize(sc.site) for sc in scs])
    best = np.full(len(atom_cart), np.inf)
    for op in xs.space_group().all_ops():
        s = op * scs[i].site
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    p = np.array(uc.orthogonalize(
                        (s[0] + dx, s[1] + dy, s[2] + dz)))
                    best = np.minimum(best, np.linalg.norm(atom_cart - p,
                                                           axis=1))
    return best


def _is_terminal_o(xs, i: int, cache: dict | None = None) -> bool:
    """A terminal O: bonded to exactly ONE metal and to no other non-H
    atom (mu2/mu3 oxo, hydroxide bridges and modelled carboxylate O are
    not terminal). Symmetry-aware."""
    if cache is not None and i in cache:
        return cache[i]
    from ..chem.knowledge import is_metal
    scs = xs.scatterers()
    d = _sym_min_distances(xs, i)
    n_metal = n_light = 0
    for j, sc in enumerate(scs):
        if j == i or d[j] < 0.1:
            continue
        el = sc.scattering_type.strip().capitalize()
        el = "".join(c for c in el if c.isalpha())[:2].capitalize()
        if el in ("H", "D"):
            continue
        if is_metal(el):
            if d[j] <= TERMINAL_O_METAL_MAX_A:
                n_metal += 1
        elif d[j] <= TERMINAL_O_LIGHT_MAX_A:
            n_light += 1
    out = n_metal == 1 and n_light == 0
    if cache is not None:
        cache[i] = out
    return out


def peak_chem_hint(xs, nearest_atom: str | None, nearest_d: float | None,
                   cache: dict | None = None) -> str | None:
    """What a difference peak could be, from its nearest atom alone:
    a C at bonding distance from a TERMINAL node O (the carbon of a
    carboxylate / carbonate / formate that is missing from the model - pa3:
    the strongest peak sat 1.58 A from a terminal Zr-O, 0.38 A from the
    referee's carboxylate C, and carried no hint), or a donor atom at
    coordination distance from a metal. None when neither reading
    applies - no hint is better than a wrong one."""
    if nearest_atom is None or nearest_d is None:
        return None
    from ..chem.knowledge import is_metal
    scs = xs.scatterers()
    idx = next((k for k, sc in enumerate(scs) if sc.label == nearest_atom),
               None)
    if idx is None:
        return None
    el = "".join(c for c in scs[idx].scattering_type.strip()
                 if c.isalpha())[:2].capitalize()
    if is_metal(el):
        lo, hi = HINT_METAL_DONOR
        return CHEM_HINT_METAL_DONOR if lo <= nearest_d <= hi else None
    if el == "O":
        lo, hi = HINT_TERMINAL_O_C
        if lo <= nearest_d <= hi and _is_terminal_o(xs, idx, cache):
            return CHEM_HINT_TERMINAL_O_CARBON
    return None


def annotate_peaks(xs, sites, heights) -> list[dict[str, Any]]:
    """Peak rows in the session table's shape: fractional site, height
    (e/A^3) and the nearest model atom over all symmetry images. Shared by
    the in-process map analysis and the SHELXL Q-peak readback so both
    tables index identically for add_atoms_from_difference_map. A
    'chem_hint' key is added only when peak_chem_hint has a reading."""
    uc = xs.unit_cell()
    atom_cart = np.array([uc.orthogonalize(sc.site) for sc in xs.scatterers()])
    labels = [sc.label for sc in xs.scatterers()]
    ops = xs.space_group().all_ops()
    peak_list = []
    terminal_cache: dict = {}
    for site, h in zip(sites, heights):
        best_d, best_lbl = float("inf"), None
        if len(atom_cart):
            for op in ops:
                s = op * site
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        for dz in (-1, 0, 1):
                            p = np.array(uc.orthogonalize(
                                (s[0] + dx, s[1] + dy, s[2] + dz)))
                            d = np.linalg.norm(atom_cart - p, axis=1)
                            i = int(np.argmin(d))
                            if d[i] < best_d:
                                best_d, best_lbl = float(d[i]), labels[i]
        row = {"site": [round(x, 4) for x in site],
               "height": round(float(h), 2),
               "nearest_atom": best_lbl,
               "nearest_d": round(best_d, 2)}
        try:
            hint = (peak_chem_hint(xs, best_lbl, best_d, terminal_cache)
                    if best_lbl is not None else None)
        except Exception:  # noqa: BLE001 - a hint must never break the table
            hint = None
        if hint:
            row["chem_hint"] = hint
        peak_list.append(row)
    return peak_list


class RefineLS(Tool):
    name = "refine"
    description = (
        "Least-squares refinement of the working model against the merged intensities. "
        "Modes: 'isotropic' (all atoms Uiso), 'aniso_heavy' (metals anisotropic), "
        "'anisotropic' (all non-H anisotropic). Reports R1/wR2/GooF, difference-map "
        "extremes and peaks, and per-atom ADP anomalies. The weighting a,b follow the "
        "SHELX weighting scheme. If a solvent mask has been computed (solvent_mask "
        "tool), its f_mask contribution is included automatically unless "
        "use_solvent_mask=false; after editing the model pass refresh_mask=true "
        "to recompute it with the same parameters in the same call. BUDGET: the "
        f"cycle loop stops itself at timeout_s (default "
        f"{default_timeout_s('refine'):.0f} s, above the 1582 s of the most "
        "expensive refinement on record) and returns the model as it stands "
        "after the last COMPLETED cycle, committed as a node, with "
        "budget_exhausted=true and cycles_done - never a half-applied shift.")
    params_schema = {
        "type": "object",
        "properties": {
            "mode": {"type": "string",
                     "enum": ["isotropic", "aniso_heavy", "anisotropic"],
                     "default": "isotropic"},
            "n_cycles": {"type": "integer", "default": 12},
            "weight_a": {"type": "number", "default": 0.1},
            "weight_b": {"type": "number", "default": 0.0},
            "use_solvent_mask": {
                "type": "boolean", "default": True,
                "description": "include the stored solvent-mask f_mask (if any) "
                               "in the refinement"},
            "refresh_mask": {
                "type": "boolean", "default": False,
                "description": "recompute the solvent mask from the CURRENT "
                               "model (same parameters as the last "
                               "solvent_mask call) before refining. The mask "
                               "is a snapshot of the model it was computed "
                               "from, so every model edit staled it and the "
                               "manual solvent_mask -> refine loop had to be "
                               "repeated by hand (13x in one campaign, 16x in "
                               "another). No mask stored = no-op."},
            "fix_atoms": {
                "type": "array", "items": {"type": "string"}, "default": [],
                "description": "atom labels whose site and ADP stay FIXED this "
                               "refinement (not refined)"},
            "label": {"type": "string", "default": "",
                      "description": "snapshot label for the trajectory record"},
            "timeout_s": timeout_param(
                "refine",
                "ok=true with budget_exhausted=true, cycles_done, and the "
                "model as it stands after the last completed cycle (a "
                "consistent state, committed as a node) - re-run to continue "
                "from there, or cut the cost with fewer atoms free / "
                "mode='aniso_heavy'"),
        },
    }

    def run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        ses = ctx.session
        if ses.model is None:
            return ToolResult.failure("no model to refine")
        if ses.fo_sq is None:
            return ToolResult.failure("no merged data")
        if int(params.get("n_cycles", 12)) < 1:
            return ToolResult.failure(
                "refine requires n_cycles >= 1; use set_adp for representation-only "
                "conversion or run_shelxl(mode='check', l_s=0) for a zero-cycle check")
        if ses.flags.get("afix_groups"):
            return ToolResult.failure(
                "non-H AFIX rigid groups are active; the in-process engine "
                "does not apply these constraints. Use run_shelxl(mode='adopt') "
                "to preserve the requested rigid-group geometry.")
        if ses.flags.get("twin"):
            return ToolResult.failure(
                "a twin law is active (TWIN/BASF): the in-process smtbx "
                "engine does not refine twinned data. Use "
                "run_shelxl(mode='adopt') - SHELXL refines the twin "
                "fraction (BASF) natively - or remove the twin via "
                "set_twin(remove=true). For weight optimization under an "
                "active twin use run_shelxl(mode='adopt_wght') - it loops "
                "SHELXL's suggested WGHT to convergence and adopts it "
                "(optimize_weights cannot run here for the same reason).")
        if int(ses.flags.get("hklf") or 4) == 5:
            return ToolResult.failure(
                "the reflection data are HKLF5 twin-batch: composite "
                "observations that only SHELXL deconvolutes (via the batch "
                "column). The in-process engine would refine against "
                "twin-composite intensities. Use run_shelxl(mode='adopt'); "
                "for weights, run_shelxl(mode='adopt_wght') loops SHELXL's "
                "suggested WGHT to convergence and adopts it.")
        xs = ses.model
        mode = params.get("mode", "isotropic")
        start_state = _snapshot_params(xs)

        from ..chem.knowledge import is_metal
        heavy_sel = flex.bool([is_metal(sc.scattering_type.strip().capitalize())
                               for sc in xs.scatterers()])
        if mode == "anisotropic":
            xs.convert_to_anisotropic()
        elif mode == "aniso_heavy":
            if heavy_sel.count(True):
                xs.convert_to_anisotropic(selection=heavy_sel)

        # the same helper every session rebuild uses, so the model refined
        # here and the model reloaded from its model.res carry the same f'/f''
        from ..io.shelx_writer import apply_anomalous_terms
        apply_anomalous_terms(xs, ses.dataset.wavelength)
        fix_labels = {str(x).strip().upper() for x in (params.get("fix_atoms") or [])}
        unknown_fixes = set(fix_labels)
        for sc in xs.scatterers():
            fixed = sc.label.strip().upper() in fix_labels
            unknown_fixes.discard(sc.label.strip().upper())
            sc.flags.set_grad_site(not fixed)
            if sc.flags.use_u_aniso():
                sc.flags.set_grad_u_aniso(not fixed)
                sc.flags.set_grad_u_iso(False)
            else:
                sc.flags.set_grad_u_iso(not fixed)
                sc.flags.set_grad_u_aniso(False)
        if unknown_fixes:
            return ToolResult.failure(
                f"fix_atoms labels not in the model: {sorted(unknown_fixes)}")

        mask_refresh: dict[str, Any] | None = None
        if params.get("refresh_mask", False):
            mask_refresh = self._refresh_mask(ctx, ses)
            if mask_refresh.get("error"):
                return ToolResult.failure(
                    f"mask refresh failed: {mask_refresh['error']} - refine "
                    "again with refresh_mask=false, or re-run solvent_mask "
                    "explicitly to see the full diagnosis")

        f_mask = None
        if params.get("use_solvent_mask", True):
            f_mask = ses.flags.get("f_mask")
            if f_mask is not None and f_mask.size() != ses.fo_sq.size():
                return ToolResult.failure(
                    f"stored solvent mask is stale (f_mask has {f_mask.size()} "
                    f"reflections, data has {ses.fo_sq.size()}): the data changed "
                    "since masking. Pass refresh_mask=true to recompute it "
                    "with the stored parameters in this call, run "
                    "solvent_mask again, or refine with "
                    "use_solvent_mask=false.")

        # hydrogen riding constraints (add_hydrogens) and optimized weights
        # (optimize_weights) stored in the session, if any
        h_constraints = list(ses.flags.get("h_constraints") or [])
        w_default = ses.flags.get("weights") or {}

        # SHELX-style restraints declared via set_restraints (session flag);
        # resolved label->i_seq HERE so model edits between calls stay safe
        restraints_manager = None
        restraints_info: dict[str, Any] = {}
        specs = ses.flags.get("restraints") or []
        if specs:
            from ..refine.restraints import build_restraints_manager
            restraints_manager, restraints_info = build_restraints_manager(xs, specs)

        try:
            from ..refine.nodes import (part_connectivity_kwargs,
                                        prune_long_metal_contacts)
            part_kw = part_connectivity_kwargs(ses.flags, xs.scatterers())
            ct = smtbx.utils.connectivity_table(xs, **part_kw)
            if h_constraints:
                # valence semantics for the constraint classes: pi metal
                # contacts within the distance cutoff are not bonds
                prune_long_metal_contacts(ct, xs, part_kw)
            rep = constraints.reparametrisation(
                structure=xs, constraints=h_constraints,
                connectivity_table=ct)
            if rep.n_independents == 0:
                return ToolResult.failure(
                    "no independent model parameters are free; use "
                    "run_shelxl(mode='check', l_s=0) to evaluate this fixed model")
            ls_kwargs: dict[str, Any] = {}
            if restraints_manager is not None:
                ls_kwargs["restraints_manager"] = restraints_manager
            w_a = float(params.get("weight_a", w_default.get("a", 0.1)))
            w_b = float(params.get("weight_b", w_default.get("b", 0.0)))
            if "weight_a" in params or "weight_b" in params:
                # explicit weights persist: run_shelxl serializes WGHT from
                # the session flags, so a weight the agent tested here must
                # not silently fall back to the old scheme downstream
                ses.flags["weights"] = {"a": w_a, "b": w_b}
            from .base import progress_heartbeat
            n_cycles_max = int(params.get("n_cycles", 12))
            hb = (f"refine[{mode}]: {xs.scatterers().size()} atoms vs "
                  f"{ses.fo_sq.size()} reflections, "
                  f"{n_cycles_max} cycles max")
            with budget_for(ctx, "refine", params,
                            label=f"refine[{mode}]") as budget, \
                    progress_heartbeat(ctx, hb):
                ls = least_squares.crystallographic_ls(
                    ses.fo_sq.as_xray_observations(), rep,
                    f_mask=f_mask,
                    weighting_scheme=(
                        least_squares.mainstream_shelx_weighting(
                            a=w_a, b=w_b)),
                    **ls_kwargs)
                cycles = _BudgetedLM(
                    ls, n_max_iterations=n_cycles_max,
                    gradient_threshold=1e-8, step_threshold=1e-8,
                    budget=budget)
        except Exception as e:  # noqa: BLE001 - singular matrices etc. must reach agent
            return ToolResult.failure(f"refinement failed: {type(e).__name__}: {e}")

        reverted = _revert_unencodable(xs, start_state)
        r1_diverged = None
        if reverted:
            # the committed model is the reverted one, so its metrics are
            # recomputed from a fresh reparametrisation: one structure-
            # factor pass (objective only), no cycles
            try:
                r1_diverged = round(float(ls.r1_factor(cutoff_factor=2)[0]), 4)
                rep = constraints.reparametrisation(
                    structure=xs, constraints=h_constraints,
                    connectivity_table=ct)
                ls = least_squares.crystallographic_ls(
                    ses.fo_sq.as_xray_observations(), rep, f_mask=f_mask,
                    weighting_scheme=least_squares.mainstream_shelx_weighting(
                        a=w_a, b=w_b),
                    **ls_kwargs)
                ls.build_up(objective_only=True)
            except Exception as e:  # noqa: BLE001
                return ToolResult.failure(
                    f"refinement diverged for "
                    f"{[r['atom'] for r in reverted]} and the reverted model "
                    f"could not be re-evaluated: {type(e).__name__}: {e}")

        r1_strong, n_strong = ls.r1_factor(cutoff_factor=2)
        r1_all, n_all = ls.r1_factor()
        wr2, goof = float(ls.wR2()), float(ls.goof())
        try:
            n_params = ls.reparametrisation.n_independents
        except AttributeError:
            n_params = -1

        diff = _difference_map_analysis(ses, xs, f_mask=f_mask)
        ses.flags["diff_map_peaks"] = diff.get("peaks", [])

        # per-atom sanity
        uc = xs.unit_cell()
        suspects = []
        for sc in xs.scatterers():
            u_eq = (adptbx.u_star_as_u_iso(uc, sc.u_star)
                    if sc.flags.use_u_aniso() else sc.u_iso)
            from ..chem.knowledge import is_metal as _is_metal
            el = sc.scattering_type.strip().capitalize()
            issue = None
            if u_eq < 0.002:
                issue = "U too small (element may be too light / site partially heavier)"
            elif u_eq > 0.20:
                issue = "U very large (ghost atom, wrong element too heavy, or disorder)"
            elif u_eq > 0.12 and _is_metal(el):
                issue = ("U very large for a metal (probably a light atom "
                         "wrongly promoted, or partial occupancy)")
            if sc.flags.use_u_aniso() and not adptbx.is_positive_definite(sc.u_star):
                issue = "non-positive-definite ADP"
            if issue:
                suspects.append({"atom": sc.label,
                                 "element": sc.scattering_type.strip().capitalize(),
                                 "u_equiv": round(float(u_eq), 4), "issue": issue})

        for rec in reversed(reverted):
            suspects.insert(0, {
                "atom": rec["atom"], "element": rec["element"],
                "u_equiv": None,
                "issue": ("DIVERGED in this refinement (" + ", ".join(
                    f"{k} {v:g}" for k, v in rec["runaway"].items())
                    + "; reverted to the pre-cycle value) - probably not "
                      "an atom of this element at this position")})

        snap = RefinementSnapshot(
            label=params.get("label") or mode,
            r1_strong=round(float(r1_strong), 4), r1_all=round(float(r1_all), 4),
            wr2=round(wr2, 4), goof=round(goof, 3),
            n_params=int(n_params), n_reflections=int(n_all),
            diff_map_max=diff.get("max"), diff_map_min=diff.get("min"))
        ses.refinement_history.append(snap)

        summary: dict[str, Any] = {
            "mode": mode,
            "solvent_mask_used": f_mask is not None,
            "r1_strong": snap.r1_strong, "n_strong": int(n_strong),
            "r1_all": snap.r1_all, "wr2": snap.wr2, "goof": snap.goof,
            "n_params": snap.n_params, "n_reflections": snap.n_reflections,
            "diff_map_max": diff.get("max"), "diff_map_min": diff.get("min"),
            "diff_map_peaks": diff.get("peaks", [])[:8],
            "adp_suspects": suspects[:15],
            "n_atoms": xs.scatterers().size(),
        }
        if reverted:
            summary["diverged_atoms"] = reverted
            summary["note_diverged"] = (
                f"{len(reverted)} atom(s) ran away in this refinement: "
                + "; ".join(
                    f"{r['atom']} " + ", ".join(
                        f"{k} {v:g}" for k, v in r["runaway"].items())
                    for r in reverted)
                + f". A value the SHELX format cannot even store (|value| >= "
                  f"5) is a diverged refinement, not a result, so those "
                  f"parameters were REVERTED to their pre-cycle state before "
                  f"the node was committed (the diverged model had R1 "
                  f"{r1_diverged}; the metrics above are the committed "
                  f"model's, one structure-factor pass, no further cycles). "
                  f"A runaway ADP says the model is wrong there - a ghost or "
                  f"solvent position, a wrong element, or an atom that needs "
                  f"restraints. Decide with ghost_test / validate_structure, "
                  f"then edit_atoms (delete / reassign), set_restraints (ISOR/SIMU) or "
                  f"reassign before refining it anisotropically again.")
        if mask_refresh is not None:
            summary["mask_refresh"] = mask_refresh
        if cycles.stopped_by:
            # the loop ended at a COMPLETED cycle, so this model is a real,
            # consistent state - it is committed as a node like any other,
            # and the disclosure rides with it
            summary["budget_exhausted"] = cycles.stopped_by == "timeout"
            summary["cancelled"] = cycles.stopped_by == "cancelled"
            summary["cycles_done"] = int(cycles.n_iterations)
            summary["cycles_requested"] = n_cycles_max
            summary["budget"] = budget.report()
            summary["note_budget"] = (
                f"refinement stopped after {cycles.n_iterations} of "
                f"{n_cycles_max} cycles because its wall-clock budget ran "
                f"out; the model is the last COMPLETED cycle (nothing is "
                f"half-applied) and is committed as a node. What you can do: "
                f"re-run refine to continue from here (each call picks up "
                f"where the last one stopped), raise timeout_s deliberately, "
                f"or make a cycle cheaper (mode='aniso_heavy' instead of "
                f"'anisotropic', fewer free atoms via fix_atoms, or "
                f"run_shelxl(mode='adopt') which refines out of process). If "
                f"this number feeds a comparison between two models, re-run "
                f"BOTH sides with the same budget before comparing.")
        if ses.flags.get("data_cards"):
            summary["data_cards_note"] = (
                f"model carries {len(ses.flags['data_cards'])} SHELX data "
                f"cards (SHEL/OMIT/EXTI/...) that the in-process engine "
                f"ignores - expect a systematic offset vs run_shelxl, "
                f"which applies them; judge final numbers by SHELXL")
        try:
            summary["scale_k"] = float(ls.scale_factor())   # Io ~ k * Ic
        except Exception:  # noqa: BLE001
            summary["scale_k"] = None
        ses.flags["scale_k"] = summary["scale_k"]
        if restraints_manager is not None:
            summary["n_restraints"] = int(getattr(ls, "n_restraints", 0) or 0)
            try:
                summary["goof_restrained"] = round(float(ls.restrained_goof()), 3)
            except Exception:  # noqa: BLE001
                summary["goof_restrained"] = None
            summary["restraints_applied"] = restraints_info.get("applied", [])
        if restraints_info.get("warnings"):
            summary["restraint_warnings"] = restraints_info["warnings"]
        if fix_labels:
            summary["fixed_atoms"] = sorted(fix_labels)
        return ToolResult(ok=True, summary=summary)

    @staticmethod
    def _refresh_mask(ctx: ToolContext, ses) -> dict[str, Any]:
        """Recompute the stored solvent mask against the current model.

        Re-runs solvent_mask with the parameters of the last call (kept in
        flags for the node store's checkout replay), so a refresh is the
        SAME mask decision applied to a newer model - never a silent change
        of masking parameters."""
        if ses.flags.get("f_mask") is None:
            return {"skipped": "no solvent mask stored"}
        before = dict(ses.flags.get("solvent_mask_info") or {})
        from .mask_tools import SolventMask
        r = SolventMask().run(ctx, **(ses.flags.get("solvent_mask_params")
                                      or {}))
        if not r.ok:
            return {"error": r.error}
        after = dict(ses.flags.get("solvent_mask_info") or {})
        return {
            "n_voids_masked": r.summary.get("n_voids_masked"),
            "electrons_per_cell_before":
                before.get("total_solvent_electrons_per_cell"),
            "electrons_per_cell_after":
                after.get("total_solvent_electrons_per_cell"),
            "volume_A3_before": before.get("solvent_volume_A3"),
            "volume_A3_after": after.get("solvent_volume_A3"),
            "parameters": "same as the last solvent_mask call",
        }
