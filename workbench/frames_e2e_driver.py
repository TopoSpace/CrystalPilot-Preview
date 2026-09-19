"""Throwaway e2e driver for the raw-frames toolchain (l-cysteine tutorial set).

Runs ONE stage per invocation (each in a fresh process, which also proves the
state.json resumability):

    python -X utf8 workbench/frames_e2e_driver.py setup
    python -X utf8 workbench/frames_e2e_driver.py import
    python -X utf8 workbench/frames_e2e_driver.py find_spots
    python -X utf8 workbench/frames_e2e_driver.py index
    python -X utf8 workbench/frames_e2e_driver.py integrate
    python -X utf8 workbench/frames_e2e_driver.py scale
    python -X utf8 workbench/frames_e2e_driver.py start_model
    python -X utf8 workbench/frames_e2e_driver.py refine_check
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

PROJECT = REPO / "workbench" / "frames-e2e-test"
FRAMES = Path(r"H:\CrystalPilot\workdir\dials\lcyst\data")
COMPOSITION = "C3 H7 N O2 S"


def setup() -> int:
    if PROJECT.exists():
        shutil.rmtree(PROJECT)
    PROJECT.mkdir(parents=True)
    (PROJECT / "context.json").write_text(json.dumps({
        "chemistry": {"ligands": [{"name": "L-cysteine"}],
                      "synthesis_notes": "amino acid test crystal"},
    }, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "project": str(PROJECT),
                      "frames_exist": FRAMES.is_dir()}))
    return 0


def run_stage(stage: str) -> int:
    from crystalpilot.refine.project import RefineProject
    proj = RefineProject(PROJECT)
    opened = proj.open()
    print("open:", json.dumps(opened, default=str)[:300])
    calls = {
        "import": ("import_frames", {"frames_dir": str(FRAMES)}),
        "find_spots": ("find_spots", {}),
        "index": ("index_frames", {}),
        "integrate": ("integrate_frames", {}),
        "scale": ("scale_and_export", {"composition": COMPOSITION}),
        "start_model": ("create_start_model", {}),
        "refine_check": ("refine", {"mode": "isotropic", "n_cycles": 3}),
    }
    name, params = calls[stage]
    r = proj.invoke_tool(name, params)
    print(json.dumps({"stage": stage, "tool": name, "ok": r.ok,
                      "summary": r.summary, "error": r.error},
                     indent=2, default=str))
    return 0 if r.ok else 1


def main() -> int:
    stage = sys.argv[1]
    if stage == "setup":
        return setup()
    return run_stage(stage)


if __name__ == "__main__":
    raise SystemExit(main())
