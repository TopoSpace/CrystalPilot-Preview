"""Vendor data reduction with CrysAlisPro, driven over LISTEN MODE.

Why this exists (measured, not assumed): the r24 model-transplant verdict
froze the agent's final model and re-refined it against different
reductions of the SAME frames. The model was publication-grade - it
reproduced the published R1 to the fourth decimal on the published data -
and the ENTIRE 0.16 -> 0.09 gap was data reduction. On that dataset a
CrysAlisPro reduction we drove ourselves scored R1 0.0747 / Rint 0.088,
beating the author's own (0.0811), the published data (0.0904) and the
DIALS route (0.1625) with the identical model.

The engine is io/crysalis_cap.cap_reduce (chain and traps documented
there). This module is the agent-facing surface, and adds the two things
a tool needs that a library call does not: a liveness check that fails
fast with instructions instead of hanging, and a refusal to reduce an
experiment directory that already contains someone's answer."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..tools.base import ToolContext, ToolResult, progress_heartbeat
from .toolbase import _ProjectTool


def register_cap_tools(reg, project) -> None:
    reg.register(ReduceWithCrysalis(project))


#: files that mean the directory holds a finished structure, not just data
_ANSWER_SUFFIXES = {".res", ".cif", ".fcf"}


def scan_for_answers(exp_dir: Path) -> list[str]:
    """Solved-structure files sitting in the experiment directory.

    A vendor experiment folder that has been worked in already contains
    the previous crystallographer's model. Reducing there is not wrong in
    itself, but reading the products back is how a 'blind' reduction
    quietly stops being blind, so the tool names what it found and makes
    the caller say it is intentional."""
    hits: list[str] = []
    for p in sorted(exp_dir.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in _ANSWER_SUFFIXES:
            continue
        try:
            head = p.read_text(encoding="utf-8", errors="replace")[:120_000]
        except OSError:
            continue
        if p.suffix.lower() == ".cif":
            if "_atom_site_fract_x" in head:
                hits.append(p.name)
            continue
        if p.suffix.lower() == ".fcf":
            hits.append(p.name)
            continue
        if len(re.findall(r"^[A-Za-z]{1,2}[A-Za-z0-9_]*\s+\d+\s+-?\d*\.\d+\s+"
                          r"-?\d*\.\d+\s+-?\d*\.\d+", head, re.M)) >= 5:
            hits.append(p.name)
    return hits


class ReduceWithCrysalis(_ProjectTool):
    name = "reduce_with_crysalis"
    description = (
        "Reduce raw frames with CrysAlisPro (the Rigaku/Oxford vendor "
        "pipeline) instead of DIALS: peak hunt -> multi-domain indexing "
        "(Duisenberg direct space, which finds twin domains on a "
        "contaminated peak table where reciprocal-space indexing returns "
        "junk cells) -> profile-fitted integration with the vendor's "
        "background and outlier treatment. Produces <name>_autored.hkl "
        "plus the vendor metadata files. Takes an experiment .par (a "
        "CrysAlisPro experiment directory - .par + .run + frames), not a "
        "plain frames folder. This is a SECOND reduction route, not a "
        "replacement: on the reference twin it beat both our DIALS route "
        "and the published data with the same model, but DIALS gives you "
        "per-stage control and works on any detector. Reach for it when "
        "the data are Rigaku/Oxford in origin, when the DIALS reduction "
        "looks like the limiting factor (high Rint, R1 stuck while the "
        "model is chemically sound), or when you want an independent "
        "reduction to compare. The CrysAlisPro LISTEN channel must be up "
        "(the tool says so if it is not). BUDGET: it usually runs 3-5 min "
        "and is abandoned at timeout_s, whose default 5400 s is LONGER than "
        "the 3900 s the client allows a single tool call - so on a big "
        "experiment pass a timeout_s under 3600 s and let the tool, not the "
        "transport, decide; at the budget it returns ok=false naming the "
        "stage reached, and the vendor files written so far are kept.")
    params_schema = {
        "type": "object",
        "properties": {
            "exp_par": {
                "type": "string",
                "description": "path to the experiment .par file "
                               "(absolute, or relative to the project)"},
            "acknowledge_existing_model": {
                "type": "boolean", "default": False,
                "description": "proceed even though the experiment "
                               "directory already contains a solved "
                               "structure (res/cif/fcf). Say why in your "
                               "report: reading those products back would "
                               "stop the work being independent."},
            "timeout_s": {"type": "integer", "default": 5400},
        },
        "required": ["exp_par"],
    }

    def run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        from ..io.crysalis_cap import HangSuspected, cap_reduce
        from ..io.crysalis_listen import ListenModeClient

        par = Path(str(params["exp_par"]))
        if not par.is_absolute():
            par = self.project.dir / par
        # CAP resolves relative paths against ITS own cwd, not ours
        par = par.resolve()
        if not par.exists():
            return ToolResult.failure(f"no such experiment file: {par}")
        if par.suffix.lower() != ".par":
            return ToolResult.failure(
                f"expected a CrysAlisPro experiment .par, got {par.name}. "
                "A CAP experiment directory holds <name>.par, <name>.run "
                "and the frames; import_frames is the tool for a bare "
                "frames folder.")

        client = ListenModeClient()
        if not client.channel_alive():
            return ToolResult.failure(
                "the CrysAlisPro LISTEN channel is not up (expected at "
                f"{client.root}). CrysAlisPro must be running with listen "
                "mode enabled - that needs one manual step at the console "
                "and cannot be started from here. Use the DIALS route "
                "(import_frames -> find_spots -> index_frames -> "
                "integrate_frames -> scale_and_export) instead.")

        answers = scan_for_answers(par.parent)
        if answers and not params.get("acknowledge_existing_model"):
            return ToolResult.failure(
                f"{par.parent} already contains a solved structure "
                f"({', '.join(answers[:6])}"
                + (f" and {len(answers) - 6} more" if len(answers) > 6
                   else "")
                + "). Reducing here is fine, but reading those products "
                "back would end any claim that your solution is "
                "independent. Re-run with acknowledge_existing_model=true "
                "and say so in the report, or point at a clean copy of "
                "the experiment.")

        steps_seen: list[str] = []

        def _progress(line: str) -> None:
            steps_seen.append(line)
            sink = getattr(ctx, "progress", None)
            if sink is not None:
                try:
                    sink(line)
                except Exception:  # noqa: BLE001 - progress is best-effort
                    pass

        try:
            with progress_heartbeat(ctx, f"crysalis reduction of {par.name}"):
                out = cap_reduce(par, client=client, progress=_progress)
        except HangSuspected as e:
            return ToolResult.failure(
                f"{e} The reduction is stuck behind a dialog on the "
                "CrysAlisPro window; it needs a human to dismiss it. "
                "Nothing was written back to the session.")

        steps = [{"step": s.name, "status": s.status,
                  "elapsed_s": s.elapsed_s,
                  **({"evidence": s.log_extract} if s.log_extract else {})}
                 for s in out.get("steps", [])]
        if not out.get("ok"):
            return ToolResult(ok=False, summary={"steps": steps},
                              error=out.get("error", "reduction failed"))

        summary: dict[str, Any] = {
            "engine": "CrysAlisPro (vendor, LISTEN MODE)",
            "experiment": str(par),
            "hkl": out.get("hkl"),
            "n_hkl_rows": out.get("n_hkl_rows"),
            "steps": steps,
            "no_state_change": True,
            "next": ("the reduced data are NOT in the session yet: point "
                     "ingest_vendor_data at the experiment directory (it "
                     "reads the vendor metadata too), or "
                     "swap_reflection_data if you already have a model "
                     "and want to compare reductions on it"),
        }
        if answers:
            summary["existing_model_in_directory"] = answers[:6]
            summary["independence_note"] = (
                "this experiment directory contains a previous solution - "
                "disclose that in the report and do not read those files")
        return ToolResult(ok=True, summary=summary)
