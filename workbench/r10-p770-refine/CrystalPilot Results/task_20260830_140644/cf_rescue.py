from __future__ import annotations

import json
from pathlib import Path

from crystalpilot.core.events import RunStore
from crystalpilot.io.shelx import load_shelx_dataset
from crystalpilot.pipeline.session import SolveSession
from crystalpilot.pipeline.standard import default_registry
from crystalpilot.tools.base import ToolContext, invoke


PROJECT = Path(__file__).resolve().parents[2]
TASK = Path(__file__).resolve().parent
store = RunStore(TASK / "runs", "run_cf_rescue")
dataset = load_shelx_dataset(PROJECT / "crystal.hkl", PROJECT / "crystal.ins")
session = SolveSession(dataset)
ctx = ToolContext(store=store, session=session)
registry = default_registry()
invoke(registry, ctx, "set_space_group", {"space_group": "P -1"})

# The standard 0.8--1.25 A ladder exhausted 14 seeds without a phase
# transition.  This rescue scan extends both the resolution window and the
# iteration/attempt budget; it stops at the first reproducible transition.
trials = [
    (1.40, list(range(101, 109))),
    (1.55, list(range(109, 117))),
    (1.70, list(range(117, 125))),
    (0.75, list(range(125, 133))),
    (0.85, list(range(133, 141))),
    (0.95, list(range(141, 149))),
    (1.15, list(range(149, 157))),
]
attempts = []
solution = None
for d_min, seeds in trials:
    result = invoke(
        registry,
        ctx,
        "solve_charge_flipping",
        {
            "d_min": d_min,
            "seeds": seeds,
            "max_solving_iterations": 1500,
            "max_attempts_per_seed": 5,
            "max_peaks": 180,
        },
    )
    attempts.append({"d_min": d_min, "seeds": seeds, "ok": result.ok,
                     "summary": result.summary, "error": result.error})
    if result.ok:
        solution = {
            "summary": result.summary,
            "sites": [list(s) for s in session.cf_info["peak_sites"]],
            "heights": list(session.cf_info["peak_heights"]),
        }
        break

payload = {"ok": solution is not None, "attempts": attempts, "solution": solution}
store.save_json("cf_rescue.json", payload)
(TASK / "cf_rescue.json").write_text(
    json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
)
print(json.dumps(payload, indent=2, ensure_ascii=False))
