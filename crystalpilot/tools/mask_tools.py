"""Solvent masking (SQUEEZE / BYPASS equivalent) via smtbx.masks.

Computes the solvent-accessible void region of the current model, derives the
scattering contribution of the disordered solvent in those voids (van der Sluis
& Spek, Acta Cryst. (1990) A46, 194-201) and stores the resulting f_mask miller
array in session.flags["f_mask"].  RefineLS picks it up automatically so the
least squares refine against  |F_calc(model) + F_mask|^2.

The mask is NOT recomputed automatically when the model or data change: after
editing atoms / re-merging, call solvent_mask again (or refine with
use_solvent_mask=false).

The BYPASS loop itself is re-implemented here (BypassMask) on top of
smtbx.masks.mask, for three things smtbx does silently: it records the
per-cycle electron-count trajectory and an explicit converged flag, it stops a
runaway iteration instead of letting f_000_s climb for max_cycles (pa1 hex-l3-r3:
1636 -> 7479 e over 2000 cycles), and it reports WHICH voids it dropped for
negative first-pass density and when - smtbx just sets exclude_void_flags and
returns 0 electrons, which three pa1 agents read as "the data do not support a
mask" for a 17,490 A^3 channel.
"""
from __future__ import annotations

import time
import uuid
from typing import Any

from cctbx import maptbx, miller, sgtbx
from cctbx.array_family import flex
from libtbx.utils import xfrange
from scitbx.math import approx_equal_relatively
from smtbx import masks

from ..chem.knowledge import is_metal
from ..io.shelx_writer import anomalous_terms_of
from . import mask_diagnosis
from .base import Tool, ToolContext, ToolResult
from .budget import Budget, BudgetStop, timeout_param

# expert iron rule: coordinated solvent must be MODELLED, never masked.
# A masked void reaching into a metal's coordination sphere is the
# mechanical signature of that mistake (or of an open metal site whose
# guest ought to be modelled) - warn and put it on the obligations trail.
COORD_INNER_A = 2.2
COORD_OUTER_A = 2.7

#: voids dropped by BYPASS for negative density that together exceed this
#: fraction of the cell make the whole call a failure (below it the drop is
#: reported but "nothing masked" is a legitimate answer for a tight structure)
NEGATIVE_DROP_FAIL_FRACTION = 0.10


def runaway_series(tr, window: int, growth: float) -> bool:
    """True when the last `window` steps of the f_000_s series all rise, the
    rise over the window exceeds `growth`, AND the series stands above its
    own first-cycle estimate.

    The third test separates a runaway from a series climbing back to its
    fixed point after an undershoot: r4-mof n0108 rebuilt without anomalous
    terms went 1737 -> 414 -> ... -> 1369 over 163 cycles, monotone for
    150 of them, and converged - the two-part test called it diverged at
    cycle 14 and handed back cycle 12. The first estimate is the integral
    of the raw difference density over the void, which the BYPASS fixed
    point sits below; a runaway climbs past it (pa1 hex-l3-r3: 1636 ->
    7479 over 2000 cycles)."""
    if len(tr) <= window:
        return False
    win = tr[-window - 1:]
    return (all(b > a for a, b in zip(win, win[1:]))
            and win[-1] > (1.0 + growth) * win[0]
            and win[-1] > tr[0])


class BypassMask(masks.mask):
    """smtbx.masks.mask with an instrumented, bounded BYPASS loop.

    Identical arithmetic to smtbx's structure_factors() (same scale scan,
    same convergence test, same per-void exclusion rule) plus:

    * ``trajectory``  - f_000_s after every cycle
    * ``residuals``   - the min-residual of the epsilon scan per cycle
    * ``converged``   - True only when smtbx's 1e-4 relative test passed
    * ``diverged``    - True when f_000_s rose on ``divergence_window``
                        consecutive cycles by more than ``divergence_growth``
                        overall AND stands above its first-cycle estimate
                        (runaway_series); the loop stops and keeps the
                        best-residual cycle's f_mask instead of the runaway one
    * ``excluded_negative`` - {void index: cycle} for voids smtbx dropped
                        because their integrated first-pass difference density
                        was negative (the caller decides what that means)
    * ``per_void_electrons`` - per-void f_000_s of the cycle whose f_mask is
                        kept, so the counts always sum to f_000_s without the
                        map-buffer aliasing correction the old path needed
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.trajectory: list[float] = []
        self.residuals: list[float] = []
        self.excluded_negative: dict[int, int] = {}
        self.converged = False
        self.diverged = False
        self.n_cycles = 0
        self.kept_cycle: int | None = None
        self.per_void_electrons: list[float] | None = None

    def structure_factors(self, max_cycles: int = 10,
                          divergence_window: int = 8,
                          divergence_growth: float = 0.20,
                          stop_check=None):
        """P. van der Sluis and A. L. Spek, Acta Cryst. (1990). A46, 194-201.

        `stop_check(cycle)` is called BETWEEN cycles; when it raises
        tools.budget.BudgetStop the loop ends like an exhausted max_cycles
        (best cycle kept, converged False) and `stopped_by` records why."""
        assert self.mask is not None
        if self.n_voids() == 0:
            return None
        f_calc_set = self.complete_set if self.use_set_completion \
            else self.fo2.set()
        self.f_calc = f_calc_set.structure_factors_from_scatterers(
            self.xray_structure, algorithm="direct").f_calc()
        f_obs = self.f_obs()
        self.scale_factor = flex.sum(f_obs.data()) / flex.sum(
            flex.abs(self.f_calc.data()))
        f_obs_minus_f_calc = f_obs.f_obs_minus_f_calc(
            1 / self.scale_factor, self.f_calc)
        volume = self.xray_structure.unit_cell().volume()
        n_grid = self.crystal_gridding.n_grid_points()
        self.fft_scale = volume / n_grid
        epsilon_for_min_residual = 2
        best: tuple | None = None      # (residual, cycle, f_mask, f_000_s, e)
        self.stopped_by = None
        for i in range(max_cycles):
            if stop_check is not None and i > 0:
                try:
                    stop_check(i)
                except BudgetStop as exc:
                    self.stopped_by = exc.__class__.__name__.lower()
                    break
            self.n_cycles = i + 1
            self.diff_map = miller.fft_map(self.crystal_gridding,
                                           f_obs_minus_f_calc)
            self.diff_map.apply_volume_scaling()
            masked_diff_map = self.diff_map.real_map_unpadded().set_selected(
                self.mask.data.as_double() == 0, 0)
            n_solvent_grid_points = self.n_solvent_grid_points()
            per_void: list[float] = []
            for j in range(self.n_voids()):
                selection = self.mask.data == j + 2
                if self.exclude_void_flags[j]:
                    masked_diff_map.set_selected(selection, 0)
                    per_void.append(0.0)
                    continue
                diff_map_ = masked_diff_map.deep_copy().set_selected(
                    ~selection, 0)
                f_000 = flex.sum(diff_map_) * self.fft_scale
                f_000_s = f_000 * (n_grid / (n_grid - n_solvent_grid_points))
                if f_000_s < 0:
                    # smtbx rule: a void whose first-pass density integrates
                    # negative is dropped for good - recorded, not silent
                    masked_diff_map.set_selected(selection, 0)
                    f_000_s = 0
                    self.exclude_void_flags[j] = True
                    self.excluded_negative[j] = i
                per_void.append(float(f_000_s))
            self.f_000 = flex.sum(masked_diff_map) * self.fft_scale
            f_000_s = self.f_000 * (masked_diff_map.size() / (
                masked_diff_map.size() - self.n_solvent_grid_points()))
            self.trajectory.append(float(f_000_s))
            if (self.f_000_s is not None and
                    approx_equal_relatively(self.f_000_s, f_000_s, 0.0001)):
                self.converged = True
                self.per_void_electrons = per_void
                self.kept_cycle = i
                break
            self.f_000_s = f_000_s
            self.per_void_electrons = per_void
            if runaway_series(self.trajectory, divergence_window,
                              divergence_growth):
                self.diverged = True
                break
            masked_diff_map.add_selected(
                self.mask.data.as_double() > 0, self.f_000_s / volume)
            self._f_mask = f_obs.structure_factors_from_map(map=masked_diff_map)
            self._f_mask *= self.fft_scale
            min_residual = 1000
            scale_for_min_residual = self.scale_factor
            for epsilon in xfrange(epsilon_for_min_residual, 0.9, -0.2):
                f_model_ = self.f_model(epsilon=epsilon)
                scale = flex.sum(f_obs.data()) / flex.sum(
                    flex.abs(f_model_.data()))
                residual = flex.sum(flex.abs(
                    1 / scale * flex.abs(f_obs.data())
                    - flex.abs(f_model_.data()))) \
                    / flex.sum(1 / scale * flex.abs(f_obs.data()))
                min_residual = min(min_residual, residual)
                if min_residual == residual:
                    scale_for_min_residual = scale
                    epsilon_for_min_residual = epsilon
            self.residuals.append(float(min_residual))
            self.scale_factor = scale_for_min_residual
            if best is None or min_residual < best[0]:
                best = (float(min_residual), i, self._f_mask.deep_copy(),
                        float(self.f_000_s), list(per_void))
            self.kept_cycle = i
            f_model = self.f_model(epsilon=epsilon_for_min_residual)
            f_obs = self.f_obs()
            f_obs_minus_f_calc = f_obs.phase_transfer(f_model) \
                .f_obs_minus_f_calc(1 / self.scale_factor, self.f_calc)
        if not self.converged and best is not None:
            # exhausted max_cycles or diverged: the last cycle is the
            # runaway end of a drifting series - hand back the cycle whose
            # scaled model fitted the data best, and say which one
            _, self.kept_cycle, self._f_mask, self.f_000_s, \
                self.per_void_electrons = best
        return self._f_mask


def consistent_void_electrons(mask_obj, gp, raw_e, total_e: float
                              ) -> list[float]:
    """Per-void electron counts that sum to f_000_s over the masked voids.

    smtbx's electron_counts_per_void() re-reads mask.diff_map, and
    fft_map.real_map_unpadded() hands out the SAME buffer that
    structure_factors() mutated.  When that loop ends by exhausting
    max_cycles rather than by converging, its closing
    `add_selected(mask > 0, f_000_s/V)` is still sitting in the map, and
    every per-void count comes back inflated by exactly
    n_grid/(n_grid - n_solvent) - measured to three decimals on two
    different griddings.  The injected term is uniform per grid point, so
    removing the surplus in proportion to each void's grid points is exact;
    when the loop converged there is no surplus and this is a no-op.

    Both paths now drive BypassMask and read its per_void_electrons (the
    kept cycle's), so this is a no-op safety net kept for the viewer path.
    """
    n_solv = int(mask_obj.n_solvent_grid_points())
    excl = list(mask_obj.exclude_void_flags)
    raw = [float(x) for x in raw_e]
    if n_solv <= 0:
        return raw
    surplus = sum(raw[i] for i in range(len(raw)) if not excl[i]) - total_e
    return [raw[i] - surplus * gp[i] / n_solv if not excl[i] else 0.0
            for i in range(len(raw))]


def _coordination_encroachment(mask_obj, xs) -> list[dict[str, Any]]:
    """Masked voids whose grid points fall inside a metal's coordination
    sphere: [{metal, void, within_A}] with the tighter shell reported."""
    from scitbx.array_family import flex as sflex

    data = mask_obj.mask.data          # flood-fill labels: 0 crystal, >=2 void
    uc = xs.unit_cell()
    out: list[dict[str, Any]] = []
    excl = list(mask_obj.exclude_void_flags)
    for sc in xs.scatterers():
        elem = "".join(c for c in sc.scattering_type if c.isalpha())[:2]
        if not is_metal(elem.capitalize()):
            continue
        cart = uc.orthogonalize(sc.site)
        hits: dict[int, float] = {}
        for radius in (COORD_INNER_A, COORD_OUTER_A):
            sel = maptbx.grid_indices_around_sites(
                unit_cell=uc, fft_n_real=data.focus(), fft_m_real=data.all(),
                sites_cart=sflex.vec3_double([cart]),
                site_radii=sflex.double(1, radius))
            for lab in set(data.select(sel)):
                lab = int(lab)
                if lab >= 2 and not excl[lab - 2]:
                    hits.setdefault(lab - 1, radius)
        for void_id, within in sorted(hits.items()):
            out.append({"metal": sc.label, "void": void_id,
                        "within_A": within})
    return out


def negative_density_diagnosis(n_dropped: int, dropped_vol: float,
                               cell_vol: float, cycles: list[int]) -> str:
    """Why BYPASS dropped a void, in terms the agent can act on.

    The difference map has zero mean (F000 is not observed), so a void
    whose integral is negative is one the map had to make negative to
    balance a framework region that is too heavy in Fo relative to the
    model - the model is too LIGHT there. That is a statement about the
    model, never about the void being empty."""
    pct = 100.0 * dropped_vol / max(cell_vol, 1e-6)
    when = (f" (in cycle{'s' if len(set(cycles)) > 1 else ''} "
            f"{', '.join(str(c + 1) for c in sorted(set(cycles)))})"
            if cycles else "")
    return (
        f"BYPASS dropped {n_dropped} void(s) totalling {dropped_vol:.0f} A^3 "
        f"({pct:.0f}% of the cell){when} because the first-pass difference "
        "density integrated NEGATIVE over them. This is a property of the "
        "current model, not evidence that the void is empty: the difference "
        "map has zero mean, so a negative void integral means the model is "
        "too LIGHT in the framework region relative to the void (atoms or H "
        "missing, elements assigned too light, isotropic or absent ADPs, a "
        "poor scale). Finish the framework first (all atoms placed, elements "
        "verified, heavy atoms anisotropic, H added) and mask again; if it "
        "persists, try d_min ~1.0 or resolution_factor 0.33 for the mask "
        "grid. This result does not say 'the data do not support a solvent "
        "mask'. Whether to deliver unmasked is a model decision, not this "
        "diagnosis's: if an earlier mask on this project converged, keep "
        "it (checkout that node, or refine with refresh_mask=false) rather "
        "than dropping it because of this pass; if no mask has converged "
        "yet, say so in the delivery and decide between masked and "
        "unmasked on R1/wR2 and the residual map of the two refinements. "
        "For scale: on a ~50% void an unmasked model carries about +0.1 in "
        "R1 and every ADP/occupancy absorbs the solvent density (pa2 cage: "
        "masked nodes at R1 0.12 were abandoned for unmasked deliveries at "
        "0.23).")


MASK_DECISION_NOTE = (
    "whether to KEEP the mask is decided by the refinement, not by this "
    "number: refine/run_shelxl with it and compare R1/wR2 and the residual "
    "map against the unmasked node. While the framework model is still "
    "changing the electron count swings by tens of percent between calls "
    "(it absorbs whatever the model lacks) - that is expected and is not "
    "a reason to drop the mask; quote the count only from the final model, "
    "with its confidence.")


def electron_count_confidence(converged: bool, diverged: bool,
                              r1: float | None,
                              change_pct: float | None) -> dict[str, Any]:
    """How far the electron count can be trusted as a composition
    measurement (never a verdict on whether to mask)."""
    reasons: list[str] = []
    level = "high"
    if diverged:
        level = "none"
        reasons.append("BYPASS series diverged")
    elif not converged:
        level = "low"
        reasons.append("BYPASS loop did not converge")
    if r1 is not None:
        if r1 > 0.15:
            level = "none" if level == "none" else "low"
            reasons.append(f"model R1 {r1:.3f} > 0.15: the mask absorbs "
                           "model error, not just solvent")
        elif r1 > 0.08 and level == "high":
            level = "medium"
            reasons.append(f"model R1 {r1:.3f}")
    if change_pct is not None and abs(change_pct) > 30 and level != "none":
        level = "low" if level in ("high", "medium") else level
        reasons.append(f"count moved {change_pct:+.0f}% since the previous "
                       "mask on this model")
    return {"level": level, "reasons": reasons}


class SolventMask(Tool):
    name = "solvent_mask"
    description = (
        "Compute a solvent mask (SQUEEZE/BYPASS equivalent) for disordered solvent in "
        "structural voids and store its structure-factor contribution (f_mask) for "
        "subsequent refinement. Use when R1 stays high (e.g. >0.15) with a chemically "
        "complete framework and large residual density spread through pores/channels - "
        "typical for MOFs and other porous crystals with unmodelled pore solvent. "
        "After running this, 'refine' automatically includes the solvent contribution. "
        "IMPORTANT: the mask is a snapshot; if atoms are added/deleted/moved afterwards, "
        "run solvent_mask again to refresh it. Reports void volumes and electron counts "
        "(compare with plausible solvent: H2O 10 e, MeCN 22 e, DMF 40 e, CH2Cl2 42 e) - "
        "but check solvent_mask_converged first: a mask that hit max_cycles gives an "
        "electron count that is still climbing, so a solvent composition read off it "
        "is a lower bound, not a measurement. A void that BYPASS drops for negative "
        "first-pass density is reported as a FAILURE with a diagnosis (the model is "
        "too light in the framework region) - it never means the void is empty. "
        "Every non-success (negative integral, nothing masked, diverged, not "
        "converged) and every success on a project that already has a mask "
        "carries mask_diagnosis: the node of the last successful mask, the model "
        "delta against it (atoms added/removed/reassigned, occupancy/ADP/H "
        "changes, non-H electrons) and a reading. After a failed mask read that "
        "delta first: checkout the last converged-mask node and compare; do not "
        "delete atoms and recompute the mask in the same step. CONVERGENCE MATTERS "
        "FOR R1: an unconverged BYPASS mask under-corrects the solvent contribution, so "
        "the refined R1 is an UPPER bound and the electron count a LOWER bound (reg1 "
        "hex: the same model refined to 0.134 with a 30-cycle mask and 0.083 with a "
        "converged one). Convergence usually needs hundreds of cycles on a large cell "
        "(each cycle is one FFT, ~0.1 s on a 17 000 A^3 cell), so max_cycles defaults "
        "to 1000 and the call stops itself at timeout_s (BUDGET, default 600 s) between "
        "cycles, keeping the best cycle and saying so. Deliver only with a converged "
        "mask, or say in unresolved why it could not converge (a diverging series is "
        "a model problem, not a cycle-count problem).")
    params_schema = {
        "type": "object",
        "properties": {
            "solvent_radius": {
                "type": "number", "default": 1.2,
                "description": "probe radius (A) for the solvent-accessible surface"},
            "shrink_truncation_radius": {
                "type": "number", "default": 1.2,
                "description": "shrink radius (A) applied after probing (BYPASS scheme)"},
            "resolution_factor": {
                "type": "number", "default": 0.25,
                "minimum": 0.10, "maximum": 0.34,
                "description": "grid step = d_min * resolution_factor for the mask FFT grid (0.10-0.34)"},
            "d_min": {
                "type": "number",
                "description": "optional resolution (A) for the mask gridding; "
                               "defaults to the data resolution"},
            "min_void_volume": {
                "type": "number", "default": 8.0,
                "description": "voids smaller than this (A^3) are excluded from the mask"},
            "max_cycles": {"type": "integer", "default": 1000,
                           "description": "max BYPASS iterations for the f_mask "
                                          "calculation (convergence = f_000_s stable "
                                          "to 1e-4, usually reached within a few "
                                          "hundred cycles; a runaway series is "
                                          "stopped early and reported as diverged). "
                                          "Lowering it below convergence inflates R1 "
                                          "- use timeout_s to bound wall clock instead"},
            "timeout_s": timeout_param(
                "solvent_mask",
                on_exhaustion="the best cycle so far is stored as the mask, "
                              "solvent_mask_converged=false, bypass.stopped_by="
                              "'budgetexceeded' and convergence_advice says how "
                              "to continue"),
        },
    }

    def run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        ses = ctx.session
        if ses.model is None:
            return ToolResult.failure("no model - solve/interpret first")
        if ses.fo_sq is None:
            return ToolResult.failure("no merged data")
        xs = ses.model
        fo_sq = ses.fo_sq
        prev_info = dict(ses.flags.get("solvent_mask_info") or {})
        # the model the session's current mask was computed on (fallback
        # for the diagnosis when the session has no project node store)
        prev_snapshot = ses.flags.get("solvent_mask_model")

        solvent_radius = float(params.get("solvent_radius", 1.2))
        shrink = float(params.get("shrink_truncation_radius", 1.2))
        res_factor = float(params.get("resolution_factor", 0.25))
        if not 0.10 <= res_factor <= 0.34:
            # pa1 cage: 0.4 and 0.5 both died deep in the FFT with "Miller
            # index not in structure factor map" - the grid must sample
            # d_min at least three times per period (Shannon)
            return ToolResult.failure(
                f"resolution_factor {res_factor} is outside 0.10-0.34: the "
                "mask grid must sample d_min at least three times per "
                "period, coarser grids fail inside the FFT ('Miller index "
                "not in structure factor map'). To make the mask cheaper "
                "or smoother raise d_min instead (e.g. d_min 1.0-1.2 A) "
                "and keep resolution_factor at 0.25-0.33")
        d_min = params.get("d_min")
        min_void_volume = float(params.get("min_void_volume", 8.0))
        max_cycles = int(params.get("max_cycles", 1000))
        budget = Budget.for_tool(ctx, "solvent_mask", params,
                                 label="solvent_mask")
        mask_params = {
            "solvent_radius": solvent_radius,
            "shrink_truncation_radius": shrink,
            "resolution_factor": res_factor,
            "d_min": d_min, "min_void_volume": min_void_volume,
            "max_cycles": max_cycles}

        def _diagnose(outcome: str, current_e: float | None,
                      kept: bool) -> dict[str, Any]:
            """mask_diagnosis block: the node of the last successful mask
            and the model delta against it (pa2 cage: 'NEGATIVE/diverged'
            was read as 'the mask is unstable' because nobody diffed the
            model that had converged against the one that failed). An
            advisory block: it never fails the call."""
            try:
                return mask_diagnosis.diagnose(
                    ctx, ses, outcome=outcome, prev_info=prev_info,
                    prev_snapshot=prev_snapshot, current_electrons=current_e,
                    params=mask_params, kept_previous=kept)
            except Exception as e:  # noqa: BLE001 - advisory block
                return {"outcome": outcome,
                        "error": f"{type(e).__name__}: {e}",
                        "rule": mask_diagnosis.RULE}

        def _drop_flags() -> None:
            for k in ("f_mask", "solvent_mask_info", "solvent_mask_params",
                      "solvent_mask_model"):
                ses.flags.pop(k, None)

        def _clear(note: str, outcome: str | None = None) -> ToolResult:
            _drop_flags()
            summary: dict[str, Any] = {"n_voids_masked": 0, "note": note}
            if outcome is not None and (prev_info or prev_snapshot):
                # a session that HAD a mask and now finds no void: say
                # what changed in the model since that mask
                diag = _diagnose(outcome, None, False)
                summary["mask_diagnosis"] = diag
                if diag.get("reading"):
                    summary["note"] = (note + " Model check vs the last "
                                       "mask: " + diag["reading"])
            return ToolResult(ok=True, summary=summary)

        # use_set_completion=True: missing reflections are filled with scaled
        # |F_model| so the void difference map is not distorted by data gaps.
        mask_obj = BypassMask(xs, fo_sq, use_set_completion=True)
        crystal_gridding = None
        if d_min:
            crystal_gridding = maptbx.crystal_gridding(
                unit_cell=xs.unit_cell(),
                space_group_info=xs.space_group_info(),
                d_min=float(d_min), resolution_factor=res_factor,
                symmetry_flags=sgtbx.search_symmetry_flags(
                    use_space_group_symmetry=False))
        mask_obj.compute(solvent_radius=solvent_radius,
                         shrink_truncation_radius=shrink,
                         resolution_factor=res_factor,
                         crystal_gridding=crystal_gridding)

        uc_vol = xs.unit_cell().volume()
        n_voids = mask_obj.n_voids()
        if n_voids == 0:
            return _clear("no solvent-accessible voids found; nothing masked",
                          outcome="no_voids")

        n_grid = mask_obj.crystal_gridding.n_grid_points()
        gp_per_void = mask_obj.flood_fill.grid_points_per_void()
        void_vols = [uc_vol * gp_per_void[i] / n_grid for i in range(n_voids)]
        dropped_small = []
        for i, vol in enumerate(void_vols):
            if vol < min_void_volume:
                mask_obj.exclude_void_flags[i] = True
                dropped_small.append(i + 1)
        if all(mask_obj.exclude_void_flags):
            return _clear(
                f"{n_voids} voids found but all below min_void_volume="
                f"{min_void_volume} A^3; nothing masked", outcome="no_voids")

        f_mask_raw = mask_obj.structure_factors(
            max_cycles=max_cycles,
            stop_check=lambda i: budget.check(f"BYPASS cycle {i}/{max_cycles}"))

        # -- what BYPASS dropped on its own, and what that means ----------
        neg = sorted(mask_obj.excluded_negative)
        neg_vol = sum(void_vols[i] for i in neg)
        n_masked = sum(1 for f in mask_obj.exclude_void_flags if not f)
        diagnosis = (negative_density_diagnosis(
            len(neg), neg_vol, uc_vol,
            [mask_obj.excluded_negative[i] for i in neg]) if neg else "")
        if n_masked == 0 or f_mask_raw is None:
            # a failed re-mask must not erase the mask the session already
            # refines with: pa2 cage-l0-r2 lost its stored mask to one
            # NEGATIVE-integral failure and refined unmasked for the last
            # 39 minutes (R1 0.12 -> 0.22). The previous mask belongs to a
            # slightly older model - stale, but a far smaller error than
            # none on a 50% void
            kept_prev = None
            if ses.flags.get("f_mask") is not None and prev_info:
                kept_prev = {
                    "total_solvent_electrons_per_cell":
                        prev_info.get("total_solvent_electrons_per_cell"),
                    "solvent_volume_A3": prev_info.get("solvent_volume_A3"),
                    "note": ("the PREVIOUS mask stays active for refine "
                             "(computed on an earlier state of this model; "
                             "re-run solvent_mask once the framework is "
                             "complete)")}
            else:
                _drop_flags()
            kept_txt = (" The previous mask is KEPT in the session ("
                        f"{kept_prev['total_solvent_electrons_per_cell']} e, "
                        f"{kept_prev['solvent_volume_A3']} A^3) - refine "
                        "continues with it; do not deliver unmasked."
                        if kept_prev else "")
            # the crystallographer's first move: diff this model against
            # the one the last successful mask was computed on
            diag = _diagnose("negative_dropped" if neg else "nothing_masked",
                             None, bool(kept_prev))
            diag_txt = (" Model check vs the last mask: " + diag["reading"]
                        if diag.get("reading") else "")
            if neg and neg_vol / uc_vol >= NEGATIVE_DROP_FAIL_FRACTION:
                return ToolResult(
                    ok=False, summary={
                        **({"previous_mask_kept": kept_prev}
                           if kept_prev else {}),
                        "mask_diagnosis": diag},
                    artifacts={},
                    error=("no NEW mask stored - every void was dropped. "
                           + diagnosis + kept_txt + diag_txt))
            note = (("nothing NEW masked: " if kept_prev else
                     "nothing masked: ")
                    + (diagnosis if neg else
                       "mask produced no structure factors")
                    + kept_txt + diag_txt)
            if not kept_prev:
                res = _clear(note)
                res.summary["mask_diagnosis"] = diag
                return res
            return ToolResult(
                ok=True, summary={"n_voids_masked": 0,
                                  "previous_mask_kept": kept_prev,
                                  "note": note, "mask_diagnosis": diag})

        # Map f_mask onto the *exact* fo_sq indices/order the refinement uses
        # (the mask works on an averaged, Friedel-merged / completed set internally).
        if fo_sq.anomalous_flag() and not f_mask_raw.anomalous_flag():
            # solvent density is real: F_mask(-h) = conj(F_mask(h))
            f_mask_raw = f_mask_raw.generate_bijvoet_mates()
        elif f_mask_raw.anomalous_flag() != fo_sq.anomalous_flag():
            _drop_flags()
            return ToolResult.failure(
                "anomalous-flag mismatch between mask set and fo_sq")
        n_missing = fo_sq.lone_set(f_mask_raw).size()
        f_mask = f_mask_raw.matching_set(other=fo_sq, data_substitute=0j)

        com = mask_obj.flood_fill.centres_of_mass_frac()
        solvent_vol = float(mask_obj.solvent_accessible_volume)
        total_e = float(mask_obj.f_000_s or 0.0)
        electrons = [float(x) for x in
                     (mask_obj.per_void_electrons or [0.0] * n_voids)]
        voids = []
        for i in range(n_voids):
            v = {
                "void": i + 1,
                "volume_A3": round(void_vols[i], 1),
                "electrons": round(electrons[i], 1),
                "centre_frac": [round(x, 3) for x in com[i]],
                "masked": not mask_obj.exclude_void_flags[i],
            }
            if i in mask_obj.excluded_negative:
                v["excluded_reason"] = (
                    "negative first-pass density (BYPASS dropped it in "
                    f"cycle {mask_obj.excluded_negative[i] + 1})")
            voids.append(v)
        sum_void_e = sum(v["electrons"] for v in voids if v["masked"])

        try:
            encroach = _coordination_encroachment(mask_obj, xs)
        except Exception:  # noqa: BLE001 - guardrail must not kill masking
            encroach = []

        tr = mask_obj.trajectory
        summary = {
            "n_voids": n_voids,
            "n_voids_masked": n_masked,
            "voids": voids,
            "total_solvent_electrons_per_cell": round(total_e, 1),
            "solvent_volume_A3": round(solvent_vol, 1),
            "solvent_volume_pct_of_cell": round(100.0 * solvent_vol / uc_vol, 1),
            "dropped_small_voids": dropped_small,
            "gridding": list(mask_obj.crystal_gridding.n_real()),
            "n_reflections_without_f_mask": int(n_missing),
            "solvent_radius": solvent_radius,
            "shrink_truncation_radius": shrink,
            "solvent_mask_converged": bool(mask_obj.converged),
            # the f'/f'' the mask integrated the difference density with:
            # a recount on a model rebuilt without them is another number
            # (Zr K-edge data 2026-09-06, 591.6 vs 1193.2 e/cell)
            "anomalous_terms": anomalous_terms_of(xs),
            "bypass": {
                "cycles_run": mask_obj.n_cycles,
                "max_cycles": max_cycles,
                "converged": bool(mask_obj.converged),
                "diverged": bool(mask_obj.diverged),
                "kept_cycle": (None if mask_obj.kept_cycle is None
                               else mask_obj.kept_cycle + 1),
                "f000s_first": round(tr[0], 1) if tr else None,
                "f000s_last": round(tr[-1], 1) if tr else None,
                "stopped_by": getattr(mask_obj, "stopped_by", None),
                "f000s_min": round(min(tr), 1) if tr else None,
                "f000s_max": round(max(tr), 1) if tr else None,
                "residual_best": (round(min(mask_obj.residuals), 4)
                                  if mask_obj.residuals else None),
            },
            "note": ("f_mask stored; subsequent 'refine' calls include the solvent "
                     "contribution. Re-run solvent_mask after any model change."),
            "guest_search_note": (
                "peaks inside the masked void are suppressed by construction: "
                "any search for a pore guest must use the PRE-mask difference "
                "map - probe_site does this automatically (it refines with "
                "the mask off on a diagnostic branch); inspect_map / "
                "integrate_difference_density on a masked node cannot find a "
                "guest"),
        }
        r1_now = None
        try:
            snap = ses.last_refinement()
            r1_now = None if snap is None else snap.as_dict().get("r1_strong")
        except Exception:  # noqa: BLE001 - advisory
            r1_now = None
        prev_e = prev_info.get("total_solvent_electrons_per_cell")
        change_pct = None
        try:
            if prev_e and float(prev_e) > 0:
                change_pct = round(100.0 * (total_e - float(prev_e))
                                   / float(prev_e), 1)
        except (TypeError, ValueError):
            change_pct = None
        summary["electron_count_confidence"] = electron_count_confidence(
            bool(mask_obj.converged), bool(mask_obj.diverged), r1_now,
            change_pct)
        if change_pct is not None:
            summary["previous_total_solvent_electrons_per_cell"] = prev_e
            summary["count_change_vs_previous_pct"] = change_pct
        summary["mask_decision_note"] = MASK_DECISION_NOTE
        summary["budget"] = budget.report()
        if not mask_obj.converged and not mask_obj.diverged:
            per_cycle = (budget.elapsed() / mask_obj.n_cycles
                         if mask_obj.n_cycles else None)
            how = (f"stopped by the {budget.timeout_s:.0f} s budget after "
                   f"{mask_obj.n_cycles} cycles"
                   if getattr(mask_obj, "stopped_by", None) == "budgetexceeded"
                   and budget.timeout_s
                   else f"hit max_cycles={max_cycles}")
            summary["convergence_advice"] = (
                f"NOT converged ({how}; f_000_s still moving "
                f"{summary['bypass']['f000s_first']} -> "
                f"{summary['bypass']['f000s_last']} e). The stored mask is "
                f"the best cycle so far: the electron count is a LOWER bound "
                f"and the R1 refined with it an UPPER bound. Before delivery "
                f"call solvent_mask again with a larger "
                + ("timeout_s" if getattr(mask_obj, "stopped_by", None)
                   == "budgetexceeded" else "max_cycles")
                + (f" (about {per_cycle:.2f} s per cycle here)" if per_cycle
                   else "")
                + "; if it still does not settle, the series is the model's "
                  "problem (see mask_diagnosis), not the cycle count's.")
        # diverged / not converged always carry the diagnosis; a converged
        # mask carries it whenever the project has an earlier mask to diff
        # against (a count that moved > 30% is a model-change signal, and
        # the delta says which change)
        outcome = ("diverged" if mask_obj.diverged else
                   "not_converged" if not mask_obj.converged else "converged")
        # WP1: ok:true means the mask was computed and applied; whether
        # the electron-count series settled is the scientific outcome, and
        # a mask that never converged is inconclusive, not a finding
        summary["scientific_outcome"] = {
            "verdict": {"converged": "supports", "not_converged": "inconclusive",
                        "diverged": "against"}[outcome],
            "reasons": [f"mask iteration {outcome}",
                        f"{total_e:.0f} e per cell in the masked void(s)"],
            "measured_by": "solvent-mask electron-count series convergence"}
        diag = _diagnose(outcome, total_e, False)
        if outcome != "converged" or diag.get("previous_mask") is not None:
            summary["mask_diagnosis"] = diag
            if (change_pct is not None
                    and abs(change_pct) > mask_diagnosis.CHANGE_SIGNAL_PCT
                    and diag.get("reading")):
                summary["count_change_note"] = diag["reading"]
        if neg:
            summary["voids_dropped_negative_density"] = [i + 1 for i in neg]
            summary["warning"] = (
                f"only {n_masked} of {n_voids} voids are masked: " + diagnosis)
        if mask_obj.diverged:
            summary["electron_count_note"] = (
                f"the BYPASS series DIVERGED: f_000_s rose on every one of "
                f"the last cycles and climbed past its first-cycle estimate "
                f"({summary['bypass']['f000s_first']} -> "
                f"{summary['bypass']['f000s_last']} e over "
                f"{mask_obj.n_cycles} cycles) instead of settling, so the "
                f"electron count is not a measurement of anything. The "
                f"stored f_mask is from cycle {summary['bypass']['kept_cycle']} "
                f"(best scaled-model residual). A runaway mask usually means "
                f"the framework model is incomplete or mis-scaled - improve "
                f"the model before quoting solvent electrons")
        elif not mask_obj.converged:
            summary["electron_count_note"] = (
                f"the BYPASS loop hit max_cycles ({max_cycles}) without "
                f"converging (f_000_s {summary['bypass']['f000s_first']} -> "
                f"{summary['bypass']['f000s_last']} e); the stored f_mask is "
                f"from cycle {summary['bypass']['kept_cycle']} (best "
                f"residual) and total_solvent_electrons_per_cell is NOT a "
                f"settled number - raise max_cycles before quoting the "
                f"electron count as a solvent composition")
        elif total_e > 0 and abs(sum_void_e - total_e) > 0.05 * total_e:
            summary["electron_count_note"] = (
                f"per-void counts sum to {sum_void_e:.1f} e against "
                f"f_000_s = {total_e:.1f} e; treat both as provisional")
        if encroach:
            summary["coordination_encroachment"] = encroach
            summary["coordination_encroachment_note"] = (
                "masked void grid reaches into a metal coordination sphere - "
                "coordinated solvent must be MODELLED, never masked. Inspect "
                "the difference density at each flagged metal: model the "
                "bound solvent (aqua/MeCN/DMF...) explicitly, or justify a "
                "genuinely open metal site in the report "
                "(read_skill mof-solvent-mask-discipline). On polynuclear "
                "nodes (Zr6, paddlewheels...) the terminal OH/aqua and "
                "capping sites sit 2.0-2.3 A from the metal and every call "
                "flags every metal until they are modelled - a to-do list "
                "for the framework, not a reason to drop the mask")
        ses.flags["f_mask"] = f_mask
        computed_at = time.strftime("%Y-%m-%dT%H:%M:%S")
        ses.flags["solvent_mask_info"] = {
            # identity first: node.json keeps a truncated copy of this dict
            # on many-void structures, and the diagnosis tells "the same
            # mask carried forward" from "recomputed" by this key
            "mask_id": uuid.uuid4().hex[:12],
            "computed_at": computed_at,
            **{k: summary[k] for k in
               ("n_voids", "n_voids_masked", "voids",
                "total_solvent_electrons_per_cell",
                "solvent_volume_A3", "solvent_volume_pct_of_cell",
                "solvent_mask_converged", "anomalous_terms", "bypass")},
            **({"coordination_encroachment": encroach} if encroach else {})}
        # exact params used: the node store re-runs the mask on checkout
        # when no snapshot of f_mask is cached next to the node
        ses.flags["solvent_mask_params"] = dict(mask_params)
        # the model this mask was computed on: the next call's diagnosis
        # diffs against it when the session has no project node store
        try:
            ses.flags["solvent_mask_model"] = {
                **mask_diagnosis.model_snapshot(xs),
                "timestamp": computed_at,
                "electrons": round(total_e, 1),
                "n_voids": n_voids, "n_voids_masked": n_masked,
                "solvent_volume_A3": round(solvent_vol, 1),
                "converged": bool(mask_obj.converged),
                "r1": r1_now, "params": dict(mask_params)}
        except Exception:  # noqa: BLE001 - advisory snapshot only
            ses.flags.pop("solvent_mask_model", None)
        return ToolResult(ok=True, summary=summary)
