"""Agent-rescue pass: rerun unsolved benchmark cases in auto (agent) mode.

Selection is budget-capped and diversity-first: cases are taken round-robin
across failure modes (from analyze.classify_failure) so a fixed budget probes
the widest range of weaknesses instead of 20 copies of the same one.

Usage:
  python -m crystalpilot.benchmark.rescue results=<standard-results.json> \
      [runner_manifest=benchmark/data_ext/runner_manifest.json] \
      [max_cases=20] [out_dir=benchmark/results_ext]
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from .analyze import classify_failure

ROOT = Path(__file__).resolve().parents[2]


def select_cases(rows: list[dict], max_cases: int) -> list[str]:
    unsolved = [r for r in rows if not r.get("solved")]
    by_mode: dict[str, list[dict]] = defaultdict(list)
    for r in unsolved:
        by_mode[classify_failure(r)].append(r)
    # worst-first inside each mode: lowest atom match first
    for mode in by_mode:
        by_mode[mode].sort(
            key=lambda r: ((r.get("match") or {}).get("all_match_rate") or 0))
    picked: list[str] = []
    modes = sorted(by_mode, key=lambda m: -len(by_mode[m]))
    while len(picked) < max_cases and any(by_mode.values()):
        for m in modes:
            if by_mode[m] and len(picked) < max_cases:
                picked.append(by_mode[m].pop(0)["name"])
    return picked


def main(argv: list[str]) -> None:
    kwargs = dict(a.split("=", 1) for a in argv if "=" in a)
    results_path = Path(kwargs["results"])
    runner_manifest = Path(kwargs.get(
        "runner_manifest", ROOT / "benchmark" / "data_ext" / "runner_manifest.json"))
    max_cases = int(kwargs.get("max_cases", 20))
    out_dir = kwargs.get("out_dir", "benchmark/results_ext")

    rows = json.loads(results_path.read_text(encoding="utf-8"))["rows"]
    names = select_cases(rows, max_cases)
    print(f"rescue selection ({len(names)} of "
          f"{sum(1 for r in rows if not r.get('solved'))} unsolved):")
    for n in names:
        print("  ", n)

    manifest = json.loads(runner_manifest.read_text(encoding="utf-8"))
    sub = [e for e in manifest if e["name"] in set(names)]
    sub_path = runner_manifest.parent / "rescue_manifest.json"
    sub_path.write_text(json.dumps(sub, indent=1), encoding="utf-8")

    from .runner import main as runner_main
    runner_main(manifest_path=str(sub_path), out_dir=out_dir,
                symmetry_mode=kwargs.get("symmetry_mode", "auto"), mode="auto")


if __name__ == "__main__":
    import sys
    main(sys.argv[1:])
