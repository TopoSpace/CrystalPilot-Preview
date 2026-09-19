"""CrystalPilot command-line interface."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def cmd_solve(args: argparse.Namespace) -> int:
    from .io.shelx import load_shelx_dataset
    from .pipeline.standard import run_standard

    hkl = Path(args.data)
    ins = Path(args.ins) if args.ins else hkl.with_suffix(".ins")
    if not ins.exists():
        ins = None
    ds = load_shelx_dataset(hkl, ins)
    print(f"Loaded: {json.dumps(ds.summary(), ensure_ascii=False)[:400]}")
    if args.agent or args.copilot:
        from .agent.crystal_agent import run_auto
        result = run_auto(ds, Path(args.runs), symmetry_mode=args.symmetry,
                          copilot=args.copilot)
    else:
        result = run_standard(ds, Path(args.runs), symmetry_mode=args.symmetry)
    print(json.dumps({k: v for k, v in result.items()
                      if k not in ("refinement_history", "interpretation")
                      and not k.startswith("_")},
                     indent=2, ensure_ascii=False, default=str))
    return 0 if result.get("ok") else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="crystalpilot",
                                 description="AI-native SCXRD structure solution")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("solve", help="solve a structure from reflection data")
    sp.add_argument("data", help="reflection data file (.hkl)")
    sp.add_argument("--ins", help="metadata file (.ins/.res)", default=None)
    sp.add_argument("--runs", help="runs output dir", default="runs")
    sp.add_argument("--agent", action="store_true",
                    help="enable the LLM Crystal Agent (Auto Mode repair loop)")
    sp.add_argument("--copilot", action="store_true",
                    help="agent mode with approval gates (approve via the web UI)")
    sp.add_argument("--symmetry", choices=["hint", "auto"], default="hint",
                    help="space group: trust input hint, or determine from data")
    sp.set_defaults(fn=cmd_solve)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
