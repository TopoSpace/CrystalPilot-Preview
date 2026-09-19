"""Third refinement engine: olex2.refine via the headless olex2c console
(io/olex2c.py, ConPTY-driven).

Why a third engine (process-audit T5): smtbx refuses HKLF5, so in the
twin-composite state SHELXL was the ONLY least-squares engine - no
independent cross-check existed exactly where the model is hardest to
trust. olex2.refine is Gauss-Newton (a different algorithm family from
SHELXL's damped LS), reads SHELX ins/hkl natively including HKLF 5 +
BASF, and reproduced SHELXL R1 to 0.0003 in the bring-up smoke test.

check-only by design: results are reported, never written back to the
session (adopt semantics would need olex2's H/anisotropy conventions
mapped back - a separate project)."""
from __future__ import annotations

import math
import re
import shutil
import time
from pathlib import Path
from typing import Any

from ..tools.base import ToolContext, ToolResult, progress_heartbeat
from .toolbase import _ProjectTool

REPO_ROOT = Path(__file__).resolve().parents[2]
OLEX2_APP = REPO_ROOT / "vendor" / "olex2" / "app"


class RunOlex2(_ProjectTool):
    name = "run_olex2"
    description = (
        "Independent cross-check with a THIRD engine: olex2.refine "
        "(Gauss-Newton - a different algorithm family from both the "
        "built-in and SHELXL least squares) run headlessly on the current "
        "model. Reads HKLF 5 + BASF natively, so it is the one independent "
        "check available in the twin-composite state where smtbx refuses "
        "the data. CHECK-ONLY: reports R1/wR2 and the delta vs the "
        "session, never modifies the model. Use it the way you use "
        "run_shelxl(mode='check'): before delivery, or when two engines "
        "disagreeing would change your next decision. Boot ~15 s + "
        "refinement; masked models (f_mask) are refused - the olex2 mask "
        "route is not wired, use run_shelxl there. BUDGET: the olex2 process "
        "is killed at timeout_s (default 900 s) and the tool returns "
        "ok=false with how far the log got; nothing in the session changes "
        "either way, so a timeout costs only the wall clock.")
    params_schema = {
        "type": "object",
        "properties": {
            "cycles": {"type": "integer", "default": 8,
                       "description": "refinement cycles"},
            "timeout_s": {"type": "integer", "default": 900},
        },
    }

    def run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        ses = ctx.session
        if ses is None or ses.model is None \
                or ses.model.scatterers().size() == 0:
            return ToolResult.failure("no model with atoms in the session")
        exe = OLEX2_APP / "olex2c.dll"
        if not exe.exists():
            return ToolResult.failure(
                f"olex2c not found at {exe} - vendor/olex2 is not "
                "installed (see vendor/VENDOR-STATUS.md)")
        if ses.flags.get("f_mask") is not None:
            return ToolResult.failure(
                "solvent mask (f_mask) is active: the olex2 mask route is "
                "not wired, and refining WITHOUT the mask contribution "
                "would misstate R1. Use run_shelxl for masked models.")

        from ..io.shelx_model import load_res_model
        from ..io.shelx_writer import ShelxModel, shelxl_command_block, \
            write_res
        from .nodes import serialization_extras
        from .restraints import emit_shelx_cards

        job = (self.project.dir / ".crystalpilot" / "refine" / "olex2" /
               time.strftime("job_%Y%m%d_%H%M%S"))
        job.mkdir(parents=True, exist_ok=True)
        flags = ses.flags
        weights = flags.get("weights") or {}
        scale_k = flags.get("scale_k")
        fvar = math.sqrt(scale_k) if scale_k and scale_k > 0 else 1.0
        h_meta = flags.get("h_riding_meta") or {}
        write_res(ShelxModel(
            xray_structure=ses.model,
            wavelength=ses.dataset.wavelength or 0.71073,
            z=getattr(self.project, "_z", None),
            title="CrystalPilot olex2 cross-check",
            instruction_cards=shelxl_command_block(
                l_s=int(params.get("cycles", 8)))
            # WP2: the model's effective cards go where SHELXL's went
            + list(flags.get("effective_cards") or []),
            restraint_cards=emit_shelx_cards(
                list(flags.get("restraints") or [])),
            weights=(float(weights.get("a", 0.1)),
                     float(weights.get("b", 0.0))),
            scale=fvar, cell_esd=getattr(self.project, "_cell_esd", None),
            h_riding=h_meta.get("per_carrier"),
            **{k: v for k, v in serialization_extras(flags).items()
               if k != "instruction_cards"}), job / "job.ins")
        # olex2 reap expects the model file it loads to pair with job.hkl;
        # give it .res (same SHELX text, the extension olex2 prefers)
        shutil.move(job / "job.ins", job / "job.res")
        shutil.copy(self.project.hkl_path, job / "job.hkl")

        from ..io.olex2c import refine_job
        n_atoms = ses.model.scatterers().size()
        hb = (f"run_olex2: boot + {int(params.get('cycles', 8))} cycles on "
              f"{n_atoms} atoms")
        try:
            with progress_heartbeat(ctx, hb):
                res = refine_job(job, res_name="job.res",
                                 cycles=int(params.get("cycles", 8)),
                                 refine_timeout_s=float(
                                     params.get("timeout_s", 900)))
        except Exception as e:  # noqa: BLE001 - console driver must not crash the session
            return ToolResult.failure(
                f"olex2 console failed: {type(e).__name__}: {e}")
        if not res.get("refinement_finished"):
            return ToolResult.failure(
                "olex2.refine did not finish - console tail:\n"
                + (res.get("console_tail") or "")[-600:])

        summary: dict[str, Any] = {
            "engine": "olex2.refine (Gauss-Newton, headless olex2c)",
            "r1_console": res.get("r1_console"),
            "elapsed_s": res.get("elapsed_s"),
            "job_dir": str(job),
            "no_state_change": True,
        }
        cif = Path(res.get("cif") or "")
        if cif.exists():
            text = cif.read_text(encoding="utf-8", errors="replace")
            for key, tag in (("r1_gt", "_refine_ls_R_factor_gt"),
                             ("wr2", "_refine_ls_wR_factor_ref"),
                             ("goof", "_refine_ls_goodness_of_fit_ref")):
                m = re.search(tag + r"\s+([0-9.]+)", text)
                if m:
                    summary[key] = float(m.group(1))
        node = self.project.nodes.state().get("active_node")
        ses_r1 = None
        if node:
            ses_r1 = ((self.project.nodes.node_meta(node).get("metrics")
                       or {}).get("r1_strong"))
        r1 = summary.get("r1_gt") or summary.get("r1_console")
        if ses_r1 is not None and r1 is not None:
            summary["delta_r1_vs_session"] = round(r1 - ses_r1, 4)
            if abs(r1 - ses_r1) > 0.01:
                summary["note"] = (
                    "olex2 R1 differs from the session by > 0.01 - worth "
                    "understanding before delivery (weights scheme, H "
                    "treatment and reflection filtering all differ "
                    "between engines; a LARGE gap can mean the model is "
                    "leaning on one engine's quirk)")
            else:
                summary["note"] = ("independent engine agrees with the "
                                   "session within 0.01 R1")
        return ToolResult(ok=True, summary=summary)
