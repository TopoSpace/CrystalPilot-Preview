"""Deterministic standard solve route (no LLM): the baseline the agent supervises.

load -> set symmetry (hint or determined) -> charge flipping (retry ladder)
-> interpret peaks -> isotropic LS -> deterministic cleanup rounds
-> aniso metals -> aniso all -> validate -> CIF + report.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from ..core.dataset import ReflectionDataset
from ..core.events import RunStore
from ..report.cif import structure_to_cif
from ..tools.base import ToolContext, ToolRegistry, invoke
from ..tools.mask_tools import SolventMask
from ..tools.model_tools import (AddAtomsFromDifferenceMap, EditAtoms,
                                 FourierComplete, InterpretPeaks)
from ..tools.hydrogen_tools import AddHydrogens, OptimizeWeights
from ..tools.refinement_tools import RefineLS
from ..tools.solution_tools import ChargeFlippingSolve
from ..tools.symmetry_tools import DetermineSpaceGroup, SetSpaceGroup, determine_and_set_best
from ..tools.trajectory_tools import RestoreState, SnapshotState
from ..tools.validation_tools import ValidateStructure
from .session import SolveSession


def default_registry() -> ToolRegistry:
    reg = ToolRegistry()
    for tool in (DetermineSpaceGroup(), SetSpaceGroup(),
                 ChargeFlippingSolve(), InterpretPeaks(), EditAtoms(),
                 AddAtomsFromDifferenceMap(), FourierComplete(), RefineLS(),
                 AddHydrogens(), OptimizeWeights(),
                 ValidateStructure(), SolventMask(), SnapshotState(),
                 RestoreState()):
        reg.register(tool)
    return reg


CF_LADDER = [
    {"d_min": 1.0, "seeds": [1, 2, 3, 4]},
    {"d_min": 0.9, "seeds": [1, 2, 3]},
    {"d_min": 1.1, "seeds": [1, 2, 3]},
    {"d_min": 0.8, "seeds": [5, 6]},
    {"d_min": 1.25, "seeds": [7, 8]},
]

# shorter ladder for space-group tie-break trials (speed over exhaustiveness)
CF_LADDER_TRIAL = [
    {"d_min": 1.0, "seeds": [1, 2]},
    {"d_min": 0.9, "seeds": [1, 2]},
]


def _trial_solve_current_sg(reg, ctx) -> dict[str, Any] | None:
    """CF + interpret + quick isotropic LS in the session's CURRENT space group.
    Returns {'r1': float, 'model': structure} or None if no refinement."""
    for attempt in CF_LADDER_TRIAL:
        r = invoke(reg, ctx, "solve_charge_flipping", attempt)
        if r.ok:
            break
    else:
        return None
    if not invoke(reg, ctx, "interpret_peaks", {}).ok:
        return None
    rr = invoke(reg, ctx, "refine", {"mode": "isotropic", "label": "sg_trial"})
    if not rr.ok or rr.summary.get("r1_strong") is None:
        return None
    model = ctx.session.model
    return {"r1": rr.summary["r1_strong"],
            "model": model.deep_copy_scatterers() if model is not None else None}


def _inversion_match_fraction(model, tol: float = 0.45) -> float:
    """ADDSYM-lite: best fraction of atoms having a same-element inversion
    mate, over candidate centres = midpoints of heavy-atom pairs (+ half
    lattice translations). NOTE: emma cannot be used for this - the Euclidean
    normalizer of every space group contains -1, so matching a model against
    its own inverted image via emma is always trivially perfect."""
    import numpy as np
    if model is None or model.scatterers().size() == 0:
        return 0.0
    p1 = model.expand_to_p1()
    if p1.scatterers().size() > 600:
        return 0.0                     # too big for a trial-stage verdict
    from cctbx.eltbx import tiny_pse
    sites, elems, zs = [], [], []
    for sc in p1.scatterers():
        sites.append(sc.site)
        el = sc.element_symbol() or "C"
        elems.append(el)
        try:
            zs.append(tiny_pse.table(el).atomic_number())
        except (RuntimeError, ValueError):
            zs.append(6)
    X = np.array(sites) % 1.0
    zs = np.array(zs)
    ortho = np.array(p1.unit_cell().orthogonalization_matrix()).reshape(3, 3)
    # candidate centres from the heaviest element's atoms (<=8 of them)
    zmax = zs.max()
    anchors = X[zs == zmax][:8]
    halves = np.array([[h / 2, k / 2, l / 2] for h in (0, 1)
                       for k in (0, 1) for l in (0, 1)])
    cands = []
    for i in range(len(anchors)):
        for j in range(i, len(anchors)):
            mid = (anchors[i] + anchors[j]) / 2.0
            cands.extend((mid + halves) % 1.0)
    if not cands:
        return 0.0
    elem_groups = {}
    for idx, el in enumerate(elems):
        elem_groups.setdefault(el, []).append(idx)
    best = 0.0
    for c in cands:
        matched = 0
        for el, idxs in elem_groups.items():
            Xi = X[idxs]
            Y = (2.0 * c - Xi) % 1.0
            d = Xi[:, None, :] - Y[None, :, :]
            d -= np.round(d)
            cart = d @ ortho.T
            dist = np.sqrt((cart ** 2).sum(axis=2))
            # greedy row-wise: each atom needs SOME inversion mate within tol
            matched += int((dist.min(axis=1) < tol).sum())
        best = max(best, matched / len(X))
        if best >= 0.999:
            break
    return best


def _model_has_inversion(model, tol: float = 0.45,
                         frac_needed: float = 0.9) -> bool:
    try:
        return _inversion_match_fraction(model, tol) >= frac_needed
    except Exception:  # noqa: BLE001 - detection failure = no evidence
        return False


def _enantiomorph_pair(sym1: str, sym2: str) -> bool:
    """True for pairs like P61/P65 where only trial R1 can discriminate."""
    from cctbx import sgtbx
    try:
        i1 = sgtbx.space_group_info(sym1)
        i2 = sgtbx.space_group_info(sym2)
        if not i1.type().is_enantiomorphic():
            return False
        return i1.change_hand().type().number() == i2.type().number() \
            and i1.type().number() != i2.type().number()
    except Exception:  # noqa: BLE001
        return False


def _resolve_sg_ties(reg, ctx, store, stats: dict[str, Any]) -> dict[str, Any]:
    """Trial-solve statistically tied space-group candidates and adopt the best.

    Intensity statistics cannot separate e.g. Cc/C2/c, P1/P-1, P21/P21m or
    enantiomorph screw pairs; the discriminator is which one actually solves
    and refines. Marsh's rule: prefer the centrosymmetric candidate unless the
    acentric one is clearly better.
    """
    ses = ctx.session
    det = stats.get("determined") or {}
    if not det.get("ambiguous_with_top") or not getattr(ses, "sg_candidates", None):
        return stats
    cands = ses.sg_candidates
    top_score = cands[0]["total_score"]
    tied = [c for c in cands[1:] if abs(c["total_score"] - top_score) < 20.0][:3]
    if not tied:
        return stats

    trials = []
    for cand in [cands[0]] + tied:
        symbol = ("hall: " + cand["hall_input_basis"]) \
            if cand.get("hall_input_basis") else cand["space_group"]
        display = cand.get("space_group_input_basis", cand["space_group"])
        if not invoke(reg, ctx, "set_space_group", {"space_group": symbol}).ok:
            continue
        outcome = _trial_solve_current_sg(reg, ctx)
        trials.append({"space_group": display, "symbol": symbol,
                       "centrosymmetric": bool(cand.get("centrosymmetric")),
                       "r1": outcome["r1"] if outcome else None,
                       "model": outcome["model"] if outcome else None})
        store.emit("sg_trial", {"space_group": display,
                                "r1": outcome["r1"] if outcome else None})

    solved = [t for t in trials if t["r1"] is not None]
    top = trials[0] if trials else None
    winner = top
    if solved and top is not None:
        # Asymmetric selection calibrated case-by-case on the ext benchmark.
        # The statistics ranking is the prior; flipping away from the top
        # candidate needs evidence scaled to how unfair the R1 comparison is:
        #   - enantiomorph partners: R1 is the only signal, take the lower
        #   - same centricity: small edge required (0.02)
        #   - centro alternate vs acentric top: may be slightly WORSE and
        #     still win (+0.025 tolerance, Marsh: acentric has 2x parameters)
        #   - acentric alternate vs centro top: must win by 0.10
        # (Structure-level inversion detection was tried and abandoned: emma
        # is blind to it - the Euclidean normalizer contains -1 - and trial-
        # quality models are too dirty for a direct ADDSYM-lite verdict.)
        def _penalty(t):
            if t is top:
                return 0.0
            if t["centrosymmetric"] == top["centrosymmetric"]:
                return 0.0 if _enantiomorph_pair(t["space_group"],
                                                 top["space_group"]) else 0.02
            return -0.025 if t["centrosymmetric"] else 0.10

        if top["r1"] is not None:
            ranked = sorted((t for t in solved if t["r1"] < 0.35 or t is top),
                            key=lambda t: t["r1"] + _penalty(t))
            if ranked:
                winner = ranked[0]
        else:
            flippable = [t for t in solved if t["r1"] < 0.35]
            winner = min(flippable or solved, key=lambda t: t["r1"])
        if winner is not top:
            store.emit("sg_trial", {"note": "flipped from top candidate",
                                    "space_group": winner["space_group"],
                                    "top": top["space_group"]})
    if winner is None:
        return stats
    setter = invoke(reg, ctx, "set_space_group", {"space_group": winner["symbol"]})
    stats["sg_trials"] = [{k: t[k] for k in ("space_group", "r1", "centrosymmetric")}
                          for t in trials]
    stats["sg_trial_selected"] = winner["space_group"]
    if setter.ok:
        stats.update(setter.summary)
        stats["space_group"] = winner["space_group"]
    return stats


_PRUNE_MAX_Z = 16          # only light atoms (<= S) are pruning candidates
_PRUNE_MAX_FRACTION = 0.3  # never delete more than this per round


def _prune_ghost_atoms(reg, ctx, store, result: dict[str, Any]):
    """Delete high-ADP light atoms (difference-map noise kept as 'atoms').

    Benchmark evidence: the most common near-miss signature is recall 1.0 with
    precision ~0.5 - every real atom present plus as many ghosts. Ghosts refine
    to nonphysical displacement parameters; prune them and re-refine.
    Physically motivated even if R1 rises slightly (ghosts absorb noise).
    """
    from cctbx.eltbx import sasaki  # noqa: F401 - ensure eltbx loaded
    ses = ctx.session
    last = ses.last_refinement()
    r1_now = last.as_dict().get("r1_strong") if last else None
    # Pruning is precision repair for the mid-quality window only:
    # above R1 0.18 the ADPs are untrustworthy (deleted a real Co at 0.22);
    # below 0.06 the model is already right (deleted real disordered linker
    # carbons in a clean MOF at 0.046)
    if r1_now is None or r1_now > 0.18 or r1_now < 0.06:
        return
    prune_heavy = r1_now < 0.10
    invoke(reg, ctx, "snapshot_state", {"name": "pre_prune"})
    r1_before = r1_now
    pruned_total: list[str] = []
    for round_no in range(3):
        if ses.model is None:
            break
        u_eqs, labels, zs = [], [], []
        uc = ses.model.unit_cell()
        from cctbx import adptbx
        from cctbx.eltbx import tiny_pse
        for sc in ses.model.scatterers():
            try:
                z = tiny_pse.table(sc.element_symbol() or "C").atomic_number()
            except (RuntimeError, ValueError):
                z = 6
            u = adptbx.u_star_as_u_iso(uc, sc.u_star) \
                if sc.flags.use_u_aniso() else sc.u_iso
            u_eqs.append(u)
            labels.append(sc.label)
            zs.append(z)
        if not u_eqs:
            break
        finite = sorted(u for u in u_eqs if u == u)
        median_u = finite[len(finite) // 2] if finite else 0.05
        # floor 0.20: genuine disorder sits at u_eq 0.15-0.20, ghosts balloon
        thr = max(0.20, 5.0 * median_u)
        heavy_thr = max(0.2, 6.0 * median_u)   # a 'metal' with u_eq>0.2 is bogus
        doomed = [lab for lab, u, z in zip(labels, u_eqs, zs)
                  if (z <= _PRUNE_MAX_Z and (u != u or u < -0.005 or u > thr))
                  or (prune_heavy and z > _PRUNE_MAX_Z
                      and (u != u or u < -0.005 or u > heavy_thr))]
        max_del = max(1, int(_PRUNE_MAX_FRACTION * len(labels)))
        if not doomed:
            break
        doomed = sorted(doomed, key=lambda l: -u_eqs[labels.index(l)])[:max_del]
        if len(doomed) >= len(labels):
            break
        r = invoke(reg, ctx, "edit_atoms",
                   {"operations": [{"action": "delete", "atoms": doomed}]})
        if not r.ok:
            break
        pruned_total.extend(doomed)
        store.emit("ghost_prune", {"round": round_no + 1, "n_deleted": len(doomed),
                                   "u_threshold": round(thr, 3)})
        if ses.flags.get("f_mask") is not None:
            invoke(reg, ctx, "solvent_mask", {})
        rr = invoke(reg, ctx, "refine", {"mode": "anisotropic",
                                         "label": f"prune_{round_no + 1}"})
        if not rr.ok:
            break
        result["refinement"] = rr.summary
    if pruned_total:
        last = ses.last_refinement()
        r1_after = last.as_dict().get("r1_strong") if last else None
        # ghosts absorb noise, so a small R1 rise is expected and physical -
        # but a big rise means we deleted real structure: roll back
        if r1_after is None or r1_after > r1_before + 0.03:
            restored = invoke(reg, ctx, "restore_state", {"name": "pre_prune"})
            if restored.ok:
                rr = invoke(reg, ctx, "refine", {"mode": "anisotropic",
                                                 "label": "prune_reverted"})
                if rr.ok:
                    result["refinement"] = rr.summary
                store.emit("ghost_prune", {"reverted": True,
                                           "r1_before": r1_before,
                                           "r1_after": r1_after})
                result["ghost_pruning"] = {"n_pruned": 0, "reverted": True}
                return
        result["ghost_pruning"] = {"n_pruned": len(pruned_total),
                                   "atoms": pruned_total[:40]}


def run_standard(dataset: ReflectionDataset, runs_root: Path,
                 run_id: str | None = None,
                 symmetry_mode: str = "hint") -> dict[str, Any]:
    """symmetry_mode: 'hint' = trust input symmetry when present;
    'auto' = always determine the space group from intensities."""
    t0 = time.time()
    store = RunStore(runs_root, run_id)
    ses = SolveSession(dataset=dataset)
    reg = default_registry()
    ctx = ToolContext(store=store, session=ses)
    result: dict[str, Any] = {"run_id": store.run_id, "ok": False}

    store.emit("stage_start", {"stage": "load", "dataset": dataset.summary()})

    # --- symmetry ---------------------------------------------------------
    if symmetry_mode == "hint" and dataset.symmetry_hint is not None:
        stats = ses.set_symmetry(dataset.symmetry_hint)
        store.emit("stage_end", {"stage": "symmetry", "mode": "hint", **stats})
    else:
        stats = determine_and_set_best(ctx)
        stats = _resolve_sg_ties(reg, ctx, store, stats)
        store.emit("stage_end", {"stage": "symmetry", "mode": "determined",
                                 **{k: v for k, v in stats.items()
                                    if k != "determined"}})
    result["symmetry"] = stats

    # --- solve (retry ladder) --------------------------------------------
    solved = False
    for attempt in CF_LADDER:
        r = invoke(reg, ctx, "solve_charge_flipping", attempt)
        if r.ok:
            solved = True
            result["solution"] = r.summary
            break
    def _fail(error: str, stage: str | None = None) -> dict[str, Any]:
        # early failures still hand the live session to in-process consumers:
        # the agent needs symmetry+data context to attempt a repair
        result["error"] = error
        if stage:
            store.emit("stage_end", {"stage": stage, "ok": False})
        store.save_json("report.json", result)
        result["_session"] = ses
        result["_store"] = store
        result["_registry"] = reg
        return result

    if not solved:
        return _fail("structure solution failed on all charge-flipping attempts",
                     stage="solution")

    r = invoke(reg, ctx, "interpret_peaks", {})
    if not r.ok:
        return _fail(f"peak interpretation failed: {r.error}")
    result["interpretation"] = r.summary

    # --- refinement ladder ------------------------------------------------
    r = invoke(reg, ctx, "refine", {"mode": "isotropic", "label": "iso_initial"})
    if not r.ok:
        return _fail(f"initial refinement failed: {r.error}")

    # grow the model by Fourier recycling (no mask yet)
    invoke(reg, ctx, "fourier_complete", {"max_rounds": 4})

    # model pore solvent, then complete again against the cleaned map
    mask_r = invoke(reg, ctx, "solvent_mask", {})
    if mask_r.ok and (mask_r.summary.get("n_voids") or 0) > 0:
        result["solvent_mask"] = {k: mask_r.summary.get(k) for k in
                                  ("n_voids", "n_voids_masked",
                                   "total_solvent_electrons_per_cell",
                                   "solvent_volume_pct_of_cell")}
        invoke(reg, ctx, "fourier_complete", {"max_rounds": 3})
        invoke(reg, ctx, "solvent_mask", {})   # refresh for the final model

    r_aniso = invoke(reg, ctx, "refine", {"mode": "aniso_heavy", "label": "aniso_heavy"})
    r_final = invoke(reg, ctx, "refine", {"mode": "anisotropic", "label": "aniso_all"})
    final_ref = r_final if r_final.ok else (r_aniso if r_aniso.ok else r)
    result["refinement"] = final_ref.summary

    # --- ghost-atom pruning (high-ADP light atoms = kept map noise) -------
    _prune_ghost_atoms(reg, ctx, store, result)

    # --- validation + guarded isolated-ghost cleanup ----------------------
    v = invoke(reg, ctx, "validate_structure", {})
    if v.ok:
        isolated = sorted(set(
            ses.validation.get("connectivity", {}).get("isolated_atoms") or []))
        n_atoms = ses.model.scatterers().size() if ses.model is not None else 0
        # guards: never gut the model - isolated "atoms" may be all we have when
        # the solution itself is bad; deleting them all hides the real failure
        if isolated and n_atoms and len(isolated) <= max(2, int(0.3 * n_atoms)):
            invoke(reg, ctx, "edit_atoms",
                   {"operations": [{"action": "delete", "atoms": isolated}]})
            if ses.flags.get("f_mask") is not None:
                invoke(reg, ctx, "solvent_mask", {})
            r_post = invoke(reg, ctx, "refine",
                            {"mode": "anisotropic", "label": "aniso_postclean"})
            if r_post.ok:
                result["refinement"] = r_post.summary
            v = invoke(reg, ctx, "validate_structure", {})

    # --- finishing touches: riding hydrogens + weighting scheme -----------
    h_r = invoke(reg, ctx, "add_hydrogens", {})
    if h_r.ok and h_r.summary.get("n_h_added"):
        result["hydrogens"] = {k: h_r.summary.get(k)
                               for k in ("n_h_added", "n_carriers")}
        invoke(reg, ctx, "refine", {"mode": "anisotropic", "label": "aniso_h"})
    w_r = invoke(reg, ctx, "optimize_weights", {})
    if w_r.ok:
        result["weights"] = w_r.summary.get("weights") or w_r.summary
        r_w = invoke(reg, ctx, "refine", {"mode": "anisotropic",
                                          "label": "final_weighted"})
        if r_w.ok:
            result["refinement"] = r_w.summary
    v = invoke(reg, ctx, "validate_structure", {})
    if v.ok:
        result["validation"] = v.summary

    if ses.model is not None:
        last = ses.last_refinement()
        cif_path = store.artifact_path("final.cif")
        structure_to_cif(ses.model, cif_path,
                         wavelength=dataset.wavelength,
                         stats=last.as_dict() if last else None,
                         mask_info=result.get("solvent_mask"))
        result["cif"] = str(cif_path)
        try:
            from ..report.html import write_html_report
            result["refinement_history"] = [s.as_dict() for s in ses.refinement_history]
            html_path = store.artifact_path("report.html")
            write_html_report(html_path, title=store.run_id, report=result,
                              cif_text=cif_path.read_text(encoding="utf-8"))
            result["html_report"] = str(html_path)
        except Exception:  # noqa: BLE001 - report generation must not fail the run
            pass
    result["ok"] = bool(ses.model is not None and ses.last_refinement())
    result["elapsed_s"] = round(time.time() - t0, 1)
    result["refinement_history"] = [s.as_dict() for s in ses.refinement_history]
    store.save_json("report.json", result)
    store.emit("stage_end", {"stage": "done", "ok": result["ok"],
                             "elapsed_s": result["elapsed_s"]})
    # in-process consumers (benchmark, agent) get the live session; not serialized
    result["_session"] = ses
    result["_store"] = store
    result["_registry"] = reg
    return result
