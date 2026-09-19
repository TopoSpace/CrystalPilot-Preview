"""Structure solution tools. Backends: smtbx charge flipping (in-process)
and the external Superflip executable (vendor/superflip) as an independent
second engine - same algorithm family, fully independent implementation,
so agreement between the two is real cross-validation and Superflip's
symmetry agreement factors double as a density-space space-group check."""
from __future__ import annotations

import math
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from cctbx import maptbx
from cctbx.array_family import flex
from smtbx.ab_initio import charge_flipping

from ..chem import solvability
from ..procutil import NO_WINDOW, canonical_child_env
from .base import Tool, ToolContext, ToolResult
from .budget import (BudgetStop, Cancelled, budget_for, default_timeout_s,
                     timeout_param)

REPO_ROOT = Path(__file__).resolve().parents[2]
SUPERFLIP_EXE = REPO_ROOT / "vendor" / "superflip" / "superflip.exe"


class _PatchedSolvingIterator(charge_flipping.solving_iterator):
    """smtbx py3 bug workaround: keeps max_solving_iterations an int
    (upstream multiplies it by 1.5 which breaks itertools.islice)."""

    _msi = 500

    @property
    def max_solving_iterations(self):  # noqa: D102
        return int(self._msi)

    @max_solving_iterations.setter
    def max_solving_iterations(self, value):  # noqa: D102
        self._msi = value


def _completeness_guard(fo_sq, params: dict, engine: str) -> str | None:
    """Charge flipping needs dense coverage - measured boundary from the
    process audit: 6 recorded attempts at <=55% completeness ALL failed
    (r16 purified subset 22% - two timeouts, 9 min; r18 55% - two
    timeouts, 14 min; r13 major-domain approximation - three
    no-phase-transition runs, 10 min). Refuse below 70% unless the
    caller explicitly overrides."""
    if params.get("allow_low_completeness"):
        return None
    try:
        comp = float(fo_sq.completeness(d_max=float("inf")))
    except Exception:  # noqa: BLE001 - guard is advisory
        return None
    if comp >= 0.70:
        return None
    return (
        f"completeness {comp:.0%} in the working group - {engine} charge "
        f"flipping below ~70% has a measured 0/6 success record "
        f"(~33 min of timeouts across r13/r16/r18). Spend the budget on "
        f"the SHELXT ladder or Fourier completion instead; to try anyway "
        f"pass allow_low_completeness=true together with a SHORT timeout_s "
        f"(both solvers take one; a few minutes is enough to see whether "
        f"the map skewness moves at all).")


def solver_capability(ses, d_min: float | None, d_min_source: str,
                      elements=None, elements_source: str = ""
                      ) -> dict[str, Any] | None:
    """The `solution_capability` disclosure for one solver call.

    Same skeleton as _completeness_guard above - the measurement, then
    what the physics makes of it - except that this one NEVER refuses and
    never changes what the call does. It exists so a failure can be read
    correctly: in the coarse-data light-atom regime this platform has no
    success record at all, so a failure there says nothing about the
    structure. Completeness is measured on the data the solver actually
    sees (after any d_min truncation), which is the same number the
    completeness guard talks about."""
    try:
        completeness = None
        source = ""
        try:
            arr = ses.fo_sq
            if arr is not None and d_min is not None:
                arr = arr.resolution_filter(d_min=float(d_min))
                source = f"working group truncated to {float(d_min):g} A"
            if arr is not None:
                completeness = float(arr.completeness(d_max=float("inf")))
                source = source or "working group, all data"
        except Exception:  # noqa: BLE001 - disclosure is best effort
            completeness, source = None, ""
        return solvability.session_capability(
            ses, d_min=d_min, d_min_source=d_min_source,
            elements=elements, elements_source=elements_source,
            completeness=completeness, completeness_source=source)
    except Exception:  # noqa: BLE001 - a disclosure must not fail a call
        return None


#: sphere the peak density is integrated over. Same radius the ghost
#: ledger reads a vacated site with (refine.tools_batch.SITE_RADIUS_A):
#: wide enough to hold one atom's density, narrow enough that a bonded
#: neighbour at >= 1.2 A does not leak in.
PEAK_DENSITY_RADIUS_A = 0.7


def _peak_density(real_map, unit_cell, sites) -> list[float]:
    """Positive-density integral in a PEAK_DENSITY_RADIUS_A sphere per peak.

    A peak HEIGHT is one grid value; the integral is the site's electron
    count (on a volume-scaled map) and is what tells a C tier from an O
    tier - interpret_peaks' metal-free branch ranks on it. Best effort:
    an empty result simply leaves the branch on heights."""
    from ..refine.tools_probe import sphere_stats
    try:
        rows = sphere_stats(real_map, unit_cell, list(sites),
                            PEAK_DENSITY_RADIUS_A)
    except Exception:  # noqa: BLE001 - a ranking aid never fails a solve
        return []
    if any("error" in r for r in rows):
        return []
    return [float(r["electrons_positive"]) for r in rows]


_LOW_COMPLETENESS_PARAM = {
    "type": "boolean", "default": False,
    "description": "override the <70% completeness refusal (measured 0/6 "
                   "success record below that line) - keep the timeout "
                   "short and treat a failure as expected"}


#: hard ceiling on len(seeds) x max_attempts_per_seed. A seed does NOT
#: accumulate knowledge - every attempt restarts the density from random
#: phases - so the sweep is a lottery with a measured record: the org-tools
#: case bought 8 x 20 = 160 attempts and got nothing but a dead case, and the
#: three recorded blind d_min/seed scans (r13) yielded zero solutions in
#: 10 min. Past ~40 attempts the productive move is a different rung of the
#: ladder (run_shelxt / solve_superflip) or a different space group, never
#: more attempts of the same kind.
MAX_TOTAL_ATTEMPTS = 40

_NEXT_STEPS = (
    "adding seeds or attempts is NOT the move (every attempt restarts from "
    "random phases; 160 attempts bought one dead case and 3 recorded blind "
    "scans yielded zero). Change one of these instead: (1) the WORKING SPACE "
    "GROUP - charge flipping searches the group you declared, and a "
    "centrosymmetric placeholder cannot produce a non-centrosymmetric "
    "structure (check_symmetry / screen_space_groups(laue_group='all')); "
    "(2) d_min, ONE step in 0.8-1.2 A; (3) the rung: run_shelxt("
    "composition='C H N O ...', detach=true) - a placeholder composition is "
    "a legitimate guess, not an element claim - or solve_superflip as the "
    "independent engine, or Patterson/heavy-atom + fourier_complete when a "
    "metal is present")


class ChargeFlippingSolve(Tool):
    name = "solve_charge_flipping"
    description = (
        "Solve the structure ab initio by charge flipping in the current working space "
        "group. Produces an electron-density map and a peak list stored in the session. "
        "Key knobs: the working space group (it searches THAT group), resolution "
        "truncation (d_min), random seeds, iteration budget. Typical d_min 0.9-1.1 for "
        f"MOFs. BUDGET: an isolated worker is stopped after timeout_s (default "
        f"{default_timeout_s('solve_charge_flipping'):.0f} s) and after at most "
        f"{MAX_TOTAL_ATTEMPTS} seed-attempts in total, and then returns ok=false with "
        "the per-seed attempt table (iterations, best map skewness), timed_out=true and "
        "a verdict on whether the skewness was still climbing - it never runs "
        "unbounded. The total covers initialization, native iterations and peak "
        "extraction, with at most 2s additional worker cleanup. Incomplete results "
        "are discarded; the last available stage/attempt table is reported. Every result also "
        "carries a solution_capability block (d_min, heaviest declared Z, "
        "completeness, tier routine/harder/no_record) stating what the physics "
        "expects of THIS data before the attempt: a failure in the tier the "
        "platform has no record for is not evidence about the structure.")
    params_schema = {
        "type": "object",
        "properties": {
            "d_min": {"type": "number", "default": 1.0,
                      "description": "resolution truncation for flipping (Angstrom)"},
            "seeds": {"type": "array", "items": {"type": "integer"},
                      "default": [1, 2, 3, 4],
                      "description": "random seeds tried until phase transition"},
            "max_solving_iterations": {"type": "integer", "default": 400},
            "max_attempts_per_seed": {
                "type": "integer", "default": 2,
                "description": (
                    f"restarts per seed. len(seeds) x max_attempts_per_seed "
                    f"is capped at {MAX_TOTAL_ATTEMPTS} total attempts - a "
                    f"larger product is trimmed (seeds first) and the trim "
                    f"is reported in the result. Attempts do not accumulate "
                    f"knowledge, so more of them is not a strategy")},
            "delta": {"type": ["number", "null"], "default": None,
                      "description": "flipping threshold; null = auto-guess"},
            "max_peaks": {"type": "integer", "default": 0,
                          "description": "peak-search cap; 0 = auto from composition"},
            "timeout_s": {"type": "number", "default": default_timeout_s("solve_charge_flipping"),
                "description": "Total computation budget including worker startup, initialization, native iterations and map/peak extraction. Worker cleanup gets at most 2 additional seconds. <=0 means no time limit; cancellation still works."},
            "time_budget_s": {"type": "number", "description": "alias of timeout_s; conflicting values are refused"},
            "max_iterations": {"type": "integer", "description": "alias of max_solving_iterations; conflicting values are refused"},
            "allow_low_completeness": _LOW_COMPLETENESS_PARAM,
        },
    }

    @staticmethod
    def _cap_attempts(seeds: list, max_attempts: int) -> tuple[list, int, dict | None]:
        """Trim seeds x attempts to MAX_TOTAL_ATTEMPTS, and say so."""
        max_attempts = max(1, min(int(max_attempts), MAX_TOTAL_ATTEMPTS))
        keep = max(1, MAX_TOTAL_ATTEMPTS // max_attempts)
        if len(seeds) * max_attempts <= MAX_TOTAL_ATTEMPTS:
            return seeds, max_attempts, None
        trimmed = list(seeds)[:keep]
        return trimmed, max_attempts, {
            "requested": f"{len(seeds)} seeds x {max_attempts} attempts = "
                         f"{len(seeds) * max_attempts}",
            "running": f"{len(trimmed)} seeds x {max_attempts} attempts = "
                       f"{len(trimmed) * max_attempts}",
            "cap": MAX_TOTAL_ATTEMPTS,
            "why": ("attempts restart from random phases and do not "
                    "accumulate, so the trimmed tail carries the same "
                    "information as the part that runs. If this run fails, "
                    + _NEXT_STEPS)}

    @staticmethod
    def _flip(it, budget, seed, row: dict[str, Any], progress=None) -> None:
        """charge_flipping.loop() with a budget check at every yield.

        The state machine suspends between flipping iterations (every 10 in
        the solving phase), so a check here - and an exception out of the
        for-body, which closes the generator and runs its clean_up() - stops
        at a point where nothing is half-written."""
        attempt = 1
        previous = None
        for _flipping in it:
            state = it.state
            if state is it.finished:
                break
            if state is it.starting and previous is it.solving:
                attempt += 1          # a restart = the next attempt
            if state is it.solving:
                row["iterations"] = int(getattr(it, "iteration_index", 0) or 0)
                try:
                    vals = it.skewness_evolution.raw_values
                    if vals.size():
                        row["best_skewness"] = round(
                            max(row.get("best_skewness", float("-inf")),
                                float(flex.max(vals))), 3)
                except Exception:  # noqa: BLE001 - reporting is best-effort
                    pass
            row["attempts"] = attempt
            if progress:
                progress(f"seed {seed}, attempt {attempt}, iteration {row.get('iterations', 0)}")
            budget.check(f"seed {seed}, attempt {attempt}, "
                         f"iteration {row.get('iterations', 0)}")
            previous = state

    def run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        params = dict(params)
        for alias, canonical in (("time_budget_s", "timeout_s"), ("max_iterations", "max_solving_iterations")):
            if alias in params:
                value = params.pop(alias)
                if canonical in params and params[canonical] != value:
                    return ToolResult.failure(f"{alias} conflicts with {canonical}")
                params[canonical] = value
        for key in ("timeout_s", "d_min"):
            if key in params and (isinstance(params[key], bool) or not isinstance(params[key], (int, float)) or not math.isfinite(params[key])):
                return ToolResult.failure(f"{key} must be a finite number")
        from .charge_flipping_worker import run_supervised
        return run_supervised(ctx, params)

    def _run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        ses = ctx.session
        if ses.fo_sq is None:
            return ToolResult.failure("no merged data; set a working space group first")
        d_min = float(params.get("d_min", 1.0))
        seeds = list(params.get("seeds") or [1, 2, 3, 4])
        max_iter = int(params.get("max_solving_iterations", 400))
        seeds, max_attempts, capped = self._cap_attempts(
            seeds, params.get("max_attempts_per_seed", 2))
        delta = params.get("delta")

        fo_sq_cf = ses.fo_sq.resolution_filter(d_min=d_min)
        f_obs = fo_sq_cf.f_sq_as_f()
        if f_obs.size() < 100:
            return ToolResult.failure(
                f"only {f_obs.size()} reflections to {d_min} A - data too sparse")
        guard = _completeness_guard(fo_sq_cf, params, "built-in")
        if guard:
            return ToolResult.failure(guard)

        t0 = time.time()
        solving = None
        used_seed = None
        table: list[dict[str, Any]] = []
        progress = getattr(ctx, "solver_progress", lambda *_: None)
        with budget_for(ctx, "solve_charge_flipping", params) as budget:
            if capped:
                budget.ping(f"seed x attempt product trimmed to "
                            f"{capped['running']} (cap {MAX_TOTAL_ATTEMPTS})")
            try:
                for seed in seeds:
                    budget.check(f"seed {seed}")
                    row: dict[str, Any] = {"seed": int(seed), "attempts": 0,
                                           "iterations": 0}
                    table.append(row)
                    progress(f"initialization for seed {seed}", table)
                    ts = time.time()
                    flex.set_random_seed(int(seed))
                    flipping = charge_flipping.weak_reflection_improved_iterator(
                        delta=delta)
                    it = _PatchedSolvingIterator(
                        flipping, f_obs,
                        yield_during_delta_guessing=True,
                        yield_solving_interval=1,
                        normalisations_for=(
                            charge_flipping.amplitude_quasi_normalisations),
                        max_solving_iterations=max_iter,
                        max_attempts_to_get_phase_transition=max_attempts)
                    try:
                        self._flip(it, budget, seed, row, lambda stage: progress(stage, table))
                    finally:
                        row["elapsed_s"] = round(time.time() - ts, 1)
                        row["phase_transition"] = bool(
                            getattr(it, "had_phase_transition", False))
                    if it.had_phase_transition and it.f_calc_solutions:
                        solving, used_seed = it, seed
                        break
            except BudgetStop as stop:
                return self._stopped(stop, budget, table, seeds, params,
                                     d_min, f_obs.size(), capped)
        elapsed = round(time.time() - t0, 1)
        if solving is None:
            return ToolResult(ok=False, error="charge flipping: no phase transition",
                              summary={"seeds_tried": seeds, "d_min": d_min,
                                       "n_reflections": f_obs.size(),
                                       "elapsed_s": elapsed,
                                       "attempt_table": table,
                                       **({"attempts_capped": capped}
                                          if capped else {}),
                                       "hint": (
                                           "one d_min variation (0.8-1.2) is a "
                                           "legitimate retry; beyond that, "
                                           + _NEXT_STEPS)})

        f_calc, _shift, cc = solving.f_calc_solutions[0]
        progress("Fourier map and peak extraction", table)
        fft_map = f_calc.fft_map(symmetry_flags=maptbx.use_space_group_symmetry)
        fft_map.apply_volume_scaling()

        n_peaks = int(params.get("max_peaks") or 0)
        if n_peaks <= 0:
            comp = ses.dataset.composition
            order_z = ses.symmetry.space_group().order_z()
            if comp and comp.z:
                n_asu = sum(comp.elements.values()) * comp.z / order_z
                n_peaks = int(math.ceil(n_asu * 1.6)) + 8
            else:
                n_peaks = 120
        peaks = fft_map.peak_search(
            maptbx.peak_search_parameters(
                interpolate=True, min_distance_sym_equiv=0.8,
                min_cross_distance=0.9, max_clusters=n_peaks),
            verify_symmetry=False).all()
        sites = list(peaks.sites())
        heights = list(peaks.heights())
        integrated = _peak_density(fft_map.real_map_unpadded(),
                                   ses.symmetry.unit_cell(), sites)

        ses.cf_info = {
            "seed": used_seed, "cc_map": round(cc, 3), "d_min": d_min,
            "n_reflections": f_obs.size(), "elapsed_s": elapsed,
            "peak_sites": sites, "peak_heights": heights,
            **({"peak_integrated_density": [round(v, 3) for v in integrated],
                "peak_density_radius_A": PEAK_DENSITY_RADIUS_A,
                "peak_density_units": "electrons (volume-scaled map)"}
               if integrated else {}),
        }
        return ToolResult(ok=True, summary={
            "converged": True, "seed": used_seed, "map_correlation": round(cc, 3),
            "d_min": d_min, "n_reflections": f_obs.size(), "elapsed_s": elapsed,
            "n_peaks": len(sites),
            "top_peak_heights": [round(h, 1) for h in heights[:12]],
        })

    # ------------------------------------------------------------------
    @staticmethod
    def _skewness_verdict(table: list[dict[str, Any]]) -> str:
        """Was the map skewness still climbing when the clock ran out?

        The phase transition IS a jump in map skewness, so a trace that has
        not moved across the attempts run so far is the no-transition
        signature and more wall clock cannot change it. Same decidability
        rule as solve_superflip's R-trajectory readout."""
        vals = [r["best_skewness"] for r in table if "best_skewness" in r]
        if len(vals) < 2:
            return ("too few attempts finished to say whether the map "
                    "skewness was moving - the budget was spent before the "
                    "first attempts completed, so a LONGER timeout_s is the "
                    "one legitimate repeat of the same call; if you would "
                    "rather not spend it, note that " + _NEXT_STEPS)
        if max(vals[-2:]) <= 1.05 * max(vals[:2]):
            return ("the best map skewness did NOT move across the attempts "
                    "that ran - that is the no-phase-transition signature, "
                    "so a longer timeout_s would buy nothing. " + _NEXT_STEPS)
        return ("the best map skewness was still climbing when the budget "
                "ran out: re-running the SAME call with a larger timeout_s "
                "is justified once. Keep seeds and max_attempts_per_seed as "
                "they are - " + _NEXT_STEPS)

    def _stopped(self, stop: BudgetStop, budget, table, seeds, params,
                 d_min: float, n_reflections: int,
                 capped: dict | None) -> ToolResult:
        """Budget/cancel stop: ok=false, everything that WAS measured, and
        the one knob worth changing."""
        cancelled = isinstance(stop, Cancelled)
        return ToolResult(
            ok=False,
            error=(f"solve_charge_flipping stopped: {stop}. No phases were "
                   f"produced, the session is unchanged and no process was "
                   f"killed - the call ended itself at its own budget."),
            summary={
                "timed_out": not cancelled,
                "cancelled": cancelled,
                "budget": budget.report(),
                "seeds_requested": [int(s) for s in seeds],
                "seeds_started": len(table),
                "d_min": d_min, "n_reflections": n_reflections,
                "attempt_table": table,
                **({"attempts_capped": capped} if capped else {}),
                "next_step": self._skewness_verdict(table),
                "cheap_alternative": (
                    "run_shelxt(detach=true) returns a job handle at once "
                    "and is polled with run_shelxt(job_status=<job>), so it "
                    "never holds this project's lock while it phases"),
            })


def _auto_n_peaks(ses) -> int:
    """peak-search cap from composition (shared by both solvers)."""
    comp = ses.dataset.composition
    order_z = ses.symmetry.space_group().order_z()
    if comp and comp.z:
        n_asu = sum(comp.elements.values()) * comp.z / order_z
        return int(math.ceil(n_asu * 1.6)) + 8
    return 120


class SolveSuperflip(Tool):
    name = "solve_superflip"
    description = (
        "Solve ab initio with the EXTERNAL Superflip program (Palatinus & "
        "Chapuis) - an independent charge-flipping implementation, so use it "
        "as the second rung of the solve ladder when solve_charge_flipping / "
        "run_shelxt struggle, or to cross-validate a doubtful solution. Its "
        "per-operator symmetry agreement factors are a density-space "
        "space-group check independent of extinction statistics (<~0.25 = "
        "operator confirmed in the density). Peaks land in the session "
        "exactly like solve_charge_flipping - continue with interpret_peaks. "
        "BUDGET: the external process is killed at timeout_s (default "
        f"{default_timeout_s('solve_superflip'):.0f} s) and the tool then "
        "returns ok=false with the R trajectory from the partial log plus a "
        "verdict on whether it was still moving (FLAT = more time will not "
        "help), so it never runs unbounded. "
        "Every result also carries a solution_capability block (d_min, "
        "heaviest declared Z, completeness, tier routine/harder/no_record) "
        "saying what the physics expects of THIS data before the attempt. "
        "Publication obligation: cite Palatinus & Chapuis, J. Appl. Cryst. "
        "40 (2007) 786-790 when a Superflip solution is adopted.")
    params_schema = {
        "type": "object",
        "properties": {
            "d_min": {"type": ["number", "null"], "default": None,
                      "description": "resolution truncation; null = all data"},
            "maxcycles": {"type": "integer", "default": 0,
                          "description": "iteration cap; 0 = Superflip default"},
            "timeout_s": {"type": "integer", "default": 600},
            "max_peaks": {"type": "integer", "default": 0,
                          "description": "peak-search cap; 0 = auto from composition"},
            "randomseed": {"type": "integer", "default": 0,
                           "description": "fixed RNG seed for reproducible "
                                          "runs; 0 = superflip picks"},
            "allow_low_completeness": _LOW_COMPLETENESS_PARAM,
        },
    }

    def run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        d_min = params.get("d_min")
        block = solver_capability(
            ctx.session, float(d_min) if d_min is not None else None,
            ("d_min truncation this call phases at" if d_min is not None
             else "no truncation - superflip sees all merged data"))
        return solvability.attach(self._run(ctx, **params), block)

    def _run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        ses = ctx.session
        if ses.fo_sq is None:
            return ToolResult.failure("no merged data; set a working space group first")
        if not SUPERFLIP_EXE.exists():
            return ToolResult.failure(
                f"superflip not installed at {SUPERFLIP_EXE} - see "
                "vendor/VENDOR-STATUS.md for the download recipe")

        fo_sq = ses.fo_sq
        d_min = params.get("d_min")
        if d_min is not None:
            fo_sq = fo_sq.resolution_filter(d_min=float(d_min))
        if fo_sq.size() < 100:
            return ToolResult.failure(
                f"only {fo_sq.size()} reflections - data too sparse")
        guard = _completeness_guard(fo_sq, params, "superflip")
        if guard:
            return ToolResult.failure(guard)

        job = REPO_ROOT / "workdir" / "superflip_jobs" / time.strftime(
            "job_%Y%m%d_%H%M%S")
        job.mkdir(parents=True, exist_ok=True)
        uc = ses.symmetry.unit_cell()
        sg = ses.symmetry.space_group()
        ops = [str(op.as_xyz()).replace(",", " ") for op in sg.all_ops()]
        sigmas = fo_sq.sigmas()
        lines = [
            "title crystalpilot",
            "cell " + " ".join(f"{p:.4f}" for p in uc.parameters()),
            "outputfile density.xplor",
            "symmetry",
            *ops,
            "endsymmetry",
        ]
        if int(params.get("maxcycles") or 0) > 0:
            lines.append(f"maxcycles {int(params['maxcycles'])}")
        if int(params.get("randomseed") or 0) > 0:
            lines.append(f"randomseed {int(params['randomseed'])}")
        lines.append("dataformat intensity")
        lines.append("fbegin")
        # expand the unique set to the P1 sphere including Friedel mates:
        # superflip iterates in P1 and a merged hemisphere alone leaves the
        # reconstruction free to break inversion symmetry (synthetic-fixture
        # lesson - the symmetry agreement factor was meaningless without it)
        fo_p1 = fo_sq.expand_to_p1()
        sig_p1 = fo_p1.sigmas()
        for hkl, i_obs, sig in zip(fo_p1.indices(), fo_p1.data(),
                                   sig_p1 if sig_p1 is not None
                                   else [1.0] * fo_p1.size()):
            lines.append(f"{hkl[0]} {hkl[1]} {hkl[2]} {i_obs:.3f} {sig:.3f}")
            lines.append(f"{-hkl[0]} {-hkl[1]} {-hkl[2]} "
                         f"{i_obs:.3f} {sig:.3f}")
        lines.append("endf")
        (job / "in.inflip").write_text("\n".join(lines) + "\n",
                                       encoding="ascii", newline="\n")

        t0 = time.time()
        try:
            # stdin=DEVNULL is load-bearing, not hygiene: without it the
            # child inherits the MCP server's stdin PIPE, on which the
            # stdio transport keeps a synchronous ReadFile pending. Windows
            # serialises operations on a synchronous pipe object, so the
            # Fortran runtime's start-up probe of unit 5 blocks until the
            # next JSON-RPC message - which cannot arrive while this tool
            # call is running. 17/17 agent-driven superflip calls (r16-pa1)
            # sat like that for the full timeout with 0 bytes of output
            # and no in.sflog; the identical input converges in ~20 s
            # once stdin is detached (pa1 bisect 2026-09-02).
            proc = subprocess.run(
                [str(SUPERFLIP_EXE), "in.inflip"], cwd=str(job),
                stdin=subprocess.DEVNULL, capture_output=True, text=True,
                timeout=int(params.get("timeout_s") or 600),
                env=canonical_child_env(),
                creationflags=NO_WINDOW)
        except subprocess.TimeoutExpired as e:
            # attach the convergence trajectory so 'is more time worth it?'
            # is decidable - 4 recorded timeouts burned ~23 min with zero
            # information (process-audit T2/r16+r18)
            partial = (e.stdout if isinstance(e.stdout, str)
                       else (e.stdout or b"").decode("utf-8", "replace"))
            (job / "superflip_partial.log").write_text(
                partial or "", encoding="utf-8", errors="replace")
            traj = ""
            r_vals = [float(v) for v in
                      re.findall(r"R:\s*([\d.]+)", partial or "")]
            if r_vals:
                flat = (len(r_vals) >= 5
                        and min(r_vals[-3:]) >= 0.95 * min(r_vals[:3]))
                traj = (f"; R trajectory over {len(r_vals)} reports: "
                        f"start {r_vals[0]:g} -> last {r_vals[-1]:g}"
                        + (" - FLAT (no phase transition in sight; more "
                           "time is unlikely to help, treat as a failed "
                           "rung and move on the solve ladder)" if flat
                           else " - still moving; a longer timeout_s "
                                "could finish"))
            elif not (partial or "").strip() and not (job / "in.sflog").exists():
                # superflip opens in.sflog within its first second; no log
                # and no stdout means the process never started computing
                traj = ("; the process produced NO output and never created "
                        "in.sflog - it never started computing (a launch/"
                        "environment problem, not a hard structure); this "
                        "is not evidence about the data, retry once and "
                        "report it if it repeats")
            else:
                traj = ("; no R reports in the partial log - likely spun "
                        "without iterating (see superflip_partial.log)")
            return ToolResult.failure(
                f"superflip timed out after {params.get('timeout_s', 600)}s "
                f"(job kept at {job}){traj}")
        elapsed = round(time.time() - t0, 1)
        log = (proc.stdout or "") + (proc.stderr or "")
        (job / "superflip.log").write_text(log, encoding="utf-8",
                                           errors="replace")

        m = re.search(r"successfully converged after\s+(\d+) cycles", log)
        converged = m is not None
        n_cycles = int(m.group(1)) if m else None
        agree_rows = re.findall(r"^\s*(\d+)\s+(-?\d+)\s+([\d.]+)\s*$", log,
                                re.M)
        overall = re.search(r"Overall agreement factor:\s*([\d.]+)", log)
        overall_af = float(overall.group(1)) if overall else None
        r_vals = re.findall(r"R:\s*([\d.]+)", log)
        final_r = float(r_vals[-1]) if r_vals else None

        base = {"converged": converged, "n_cycles": n_cycles,
                "final_r_percent": final_r, "elapsed_s": elapsed,
                "n_reflections": fo_sq.size(),
                "symmetry_agreement": {
                    "per_operator": [{"op_number": int(a), "symbol": b,
                                      "agreement": float(c)}
                                     for a, b, c in agree_rows],
                    "overall": overall_af,
                    "note": ("<~0.25 = operator confirmed in the density; "
                             "large values mean the density does NOT obey "
                             "that operator - an independent space-group "
                             "alarm")},
                "job_dir": str(job),
                "citation_obligation": (
                    "Superflip solution adopted => cite Palatinus & Chapuis, "
                    "J. Appl. Cryst. 40 (2007) 786-790 and record the "
                    "program in computing/structure_solution via "
                    "set_experiment")}
        if not converged:
            return ToolResult(ok=False, error="superflip did not converge",
                              summary={**base,
                                       "hint": "try d_min truncation, more "
                                               "maxcycles, or check the "
                                               "space group"})

        # density -> peaks (same downstream contract as solve_charge_flipping)
        xplor_path = job / "density.xplor"
        if not xplor_path.exists():
            return ToolResult(ok=False, summary=base,
                              error="converged but density.xplor missing")
        import iotbx.xplor.map as xplor_map
        from cctbx import sgtbx
        rdr = xplor_map.reader(file_name=str(xplor_path))
        data = rdr.data
        # peak-search in P1: superflip picks its own grid, which need not
        # satisfy cctbx's space-group gridding constraints. Symmetry copies
        # in the peak list are harmless - interpret_peaks deduplicates
        # symmetry-aware downstream.
        gridding = maptbx.crystal_gridding(
            unit_cell=uc,
            space_group_info=sgtbx.space_group_info("P 1"),
            pre_determined_n_real=data.focus(),
            symmetry_flags=maptbx.use_space_group_symmetry)
        n_peaks = (int(params.get("max_peaks") or 0) or _auto_n_peaks(ses)) \
            * sg.order_z()
        psr = gridding.tags().peak_search(
            parameters=maptbx.peak_search_parameters(
                interpolate=True, min_distance_sym_equiv=0.8,
                min_cross_distance=0.9, max_clusters=n_peaks),
            map=data).all()
        sites = list(psr.sites())
        heights = list(psr.heights())
        # superflip's density carries its own scale, so the integral is
        # comparable BETWEEN peaks (which is all the tiers need) but is
        # not an absolute electron count
        integrated = _peak_density(data, uc, sites)
        ses.cf_info = {
            "engine": "superflip", "d_min": d_min,
            "n_reflections": fo_sq.size(), "elapsed_s": elapsed,
            "symmetry_agreement_overall": overall_af,
            "peak_sites": sites, "peak_heights": heights,
            **({"peak_integrated_density": [round(v, 3) for v in integrated],
                "peak_density_radius_A": PEAK_DENSITY_RADIUS_A,
                "peak_density_units": "arbitrary (Superflip density scale; "
                                      "peak-to-peak ratios are meaningful, "
                                      "absolute values are not)"}
               if integrated else {}),
        }
        return ToolResult(ok=True, summary={
            **base, "n_peaks": len(sites),
            "top_peak_heights": [round(h, 1) for h in heights[:12]],
            "next": "interpret_peaks to convert the peak list into atoms"})
