"""Benchmark runner: full autonomous solve on every manifest case, scored against
the human reference structures. Produces results JSON + a markdown summary.
"""
from __future__ import annotations

import json
import time
import traceback
from pathlib import Path
from typing import Any

from ..io.shelx import load_shelx_dataset
from ..pipeline.standard import run_standard
from .evaluate import evaluate_against_reference, load_reference, reference_r1


def run_case(entry: dict[str, Any], runs_root: Path,
             symmetry_mode: str = "auto", mode: str = "standard") -> dict[str, Any]:
    name = entry["name"]
    out: dict[str, Any] = {"name": name, "symmetry_mode": symmetry_mode,
                           "mode": mode}
    t0 = time.time()
    try:
        if entry.get("sf_cif"):
            from ..io.cif_sf import load_cif_sf_dataset
            ds = load_cif_sf_dataset(Path(entry["sf_cif"]),
                                     ref_cif_path=entry.get("ref_cif"))
        else:
            ds = load_shelx_dataset(Path(entry["hkl"]), Path(entry["ins"]))
        ref = load_reference(entry.get("ref_res"), entry.get("ref_cif"))
        out["true_sg"] = (str(ref.space_group_info()) if ref is not None
                          else (str(ds.symmetry_hint.space_group_info())
                                if ds.symmetry_hint else None))
        out["human_r1"] = reference_r1(entry.get("ref_res"), entry.get("ref_cif"))
        if mode == "auto":
            from ..agent.crystal_agent import run_auto
            result = run_auto(ds, runs_root, run_id=f"bm_{mode}_{name[:38]}",
                              symmetry_mode=symmetry_mode, max_steps=22)
            out["agent"] = {k: (result.get("agent") or {}).get(k)
                            for k in ("status", "assessment", "steps_used", "usage")}
        else:
            result = run_standard(ds, runs_root, run_id=f"bm_{name[:40]}",
                                  symmetry_mode=symmetry_mode)
        out["pipeline_ok"] = result.get("ok", False)
        out["used_sg"] = (result.get("symmetry") or {}).get("space_group")
        if out.get("true_sg") and out.get("used_sg"):
            from cctbx import sgtbx
            try:
                out["sg_correct"] = (
                    sgtbx.space_group_info(out["used_sg"]).type().number()
                    == sgtbx.space_group_info(out["true_sg"]).type().number())
            except RuntimeError:
                out["sg_correct"] = out["used_sg"] == out["true_sg"]
        else:
            out["sg_correct"] = None
        ref_hist = result.get("refinement_history") or []
        if ref_hist:
            best = min(ref_hist, key=lambda h: h.get("r1_strong", 9))
            out["r1"] = best.get("r1_strong")
        out["confidence"] = ((result.get("validation") or {}).get("confidence")
                             or {}).get("score")
        out["framework_dim"] = (result.get("validation") or {}).get(
            "framework_dimensionality")
        out["error"] = result.get("error")

        session = result.get("_session")
        model = session.model if session is not None else None
        if session is not None and session.symmetry is not None:
            # the agent may have changed the space group after the pipeline stage
            out["used_sg"] = str(session.symmetry.space_group_info())
            if out.get("true_sg"):
                from cctbx import sgtbx
                try:
                    out["sg_correct"] = (
                        sgtbx.space_group_info(out["used_sg"]).type().number()
                        == sgtbx.space_group_info(out["true_sg"]).type().number())
                except RuntimeError:
                    pass
        if ref is not None and model is not None:
            out["match"] = evaluate_against_reference(model, ref)
            out["solved"] = out["match"]["solved"]
    except Exception as e:  # noqa: BLE001 - benchmark must not die on one case
        out["error"] = f"{type(e).__name__}: {e}"
        out["traceback"] = traceback.format_exc(limit=6)
        out["pipeline_ok"] = False
    out["elapsed_s"] = round(time.time() - t0, 1)
    return out


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    def frac(key, pred=bool):
        vals = [r for r in rows if pred(r.get(key))]
        return round(len(vals) / n, 3) if n else 0
    return {
        "n_cases": n,
        "pipeline_ok_rate": frac("pipeline_ok"),
        "sg_top1_rate": frac("sg_correct", lambda v: v is True),
        "solved_rate": frac("solved", lambda v: v is True),
        "mean_r1": round(sum(r["r1"] for r in rows if r.get("r1") is not None)
                         / max(1, sum(1 for r in rows if r.get("r1") is not None)), 4),
        "mean_elapsed_s": round(sum(r["elapsed_s"] for r in rows) / max(1, n), 1),
    }


def to_markdown(rows: list[dict[str, Any]], summary: dict[str, Any]) -> str:
    lines = ["# CrystalPilot Benchmark", "",
             f"**{summary['n_cases']} cases** | solved: {summary['solved_rate']:.0%} | "
             f"SG top-1: {summary['sg_top1_rate']:.0%} | "
             f"mean R1: {summary['mean_r1']:.3f} | "
             f"mean time: {summary['mean_elapsed_s']}s", "",
             "| case | true SG | used SG | SG ok | R1 | heavy | all | solved | conf | t(s) |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        m = r.get("match") or {}
        lines.append(
            f"| {r['name'][:42]} | {r.get('true_sg') or '?'} | {r.get('used_sg') or '-'} "
            f"| {'Y' if r.get('sg_correct') else ('N' if r.get('sg_correct') is False else '?')} "
            f"| {r.get('r1') if r.get('r1') is not None else '-'} "
            f"| {m.get('heavy_match_rate', '-')} | {m.get('all_match_rate', '-')} "
            f"| {'YES' if r.get('solved') else 'no'} "
            f"| {r.get('confidence', '-')} | {r['elapsed_s']} |")
        if r.get("error"):
            lines.append(f"| &nbsp;&nbsp;error: {str(r['error'])[:100]} | | | | | | | | | |")
    return "\n".join(lines)


def main(manifest_path: str = "benchmark/data/manifest.json",
         out_dir: str = "benchmark/results",
         symmetry_mode: str = "auto",
         mode: str = "standard",
         only: str | None = None) -> dict[str, Any]:
    manifest = []
    for mp in manifest_path.split(","):
        mp = mp.strip()
        if mp and Path(mp).exists():
            manifest.extend(json.loads(Path(mp).read_text(encoding="utf-8")))
    if only:
        manifest = [e for e in manifest if only.lower() in e["name"].lower()]
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    runs_root = out / "runs"
    rows = []
    for i, entry in enumerate(manifest):
        print(f"[{i+1}/{len(manifest)}] {entry['name']}", flush=True)
        row = run_case(entry, runs_root, symmetry_mode=symmetry_mode, mode=mode)
        rows.append(row)
        status = "SOLVED" if row.get("solved") else ("ok" if row.get("pipeline_ok") else "FAIL")
        print(f"    -> {status} sg={row.get('used_sg')} r1={row.get('r1')} "
              f"match={((row.get('match') or {}).get('all_match_rate'))} "
              f"t={row['elapsed_s']}s", flush=True)
    summary = summarize(rows)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    (out / f"results_{stamp}.json").write_text(
        json.dumps({"summary": summary, "rows": rows}, indent=2, default=str),
        encoding="utf-8")
    (out / f"results_{stamp}.md").write_text(to_markdown(rows, summary), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return {"summary": summary, "rows": rows}


if __name__ == "__main__":
    import sys
    kwargs = {}
    for arg in sys.argv[1:]:
        if "=" in arg:
            k, v = arg.split("=", 1)
            kwargs[k] = v
    main(**kwargs)
