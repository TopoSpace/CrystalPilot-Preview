"""Capability-boundary analysis over benchmark results.

Joins runner result rows with manifest_ext metadata and produces breakdowns by
chemistry category, vendor, crystal system, data size and difficulty tags, plus
a failure taxonomy and a worst-first case table. Honest by construction: only
aggregates what the runner measured.

Usage:
  python -m crystalpilot.benchmark.analyze results=<results.json>[,more.json] \
      [manifest=benchmark/manifest_ext.json] [out=benchmark/results_ext/analysis.md]
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

CRYSTAL_SYSTEMS = [
    (range(1, 3), "triclinic"), (range(3, 16), "monoclinic"),
    (range(16, 75), "orthorhombic"), (range(75, 143), "tetragonal"),
    (range(143, 168), "trigonal"), (range(168, 195), "hexagonal"),
    (range(195, 231), "cubic"),
]


def crystal_system(sg_symbol: str | None) -> str:
    if not sg_symbol:
        return "unknown"
    try:
        from cctbx import sgtbx
        n = sgtbx.space_group_info(sg_symbol).type().number()
        for rng, name in CRYSTAL_SYSTEMS:
            if n in rng:
                return name
    except Exception:  # noqa: BLE001
        pass
    return "unknown"


def classify_failure(row: dict) -> str:
    """One primary failure label per unsolved case."""
    if row.get("solved"):
        return "solved"
    if row.get("error"):
        err = str(row["error"])
        if "Exception" in err or "Error" in err:
            return "crash: " + err.split(":")[0]
        return "pipeline-error"
    if not row.get("pipeline_ok"):
        return "no-solution (charge flipping failed)"
    if row.get("sg_correct") is False:
        return "wrong space group"
    m = row.get("match") or {}
    heavy = m.get("heavy_match_rate")
    allr = m.get("all_match_rate")
    if heavy is not None and heavy >= 0.8 and (allr or 0) < 0.7:
        return "heavy ok, light atoms wrong/missing"
    if row.get("r1") is not None and row["r1"] > 0.20:
        return "solution did not refine (R1>0.20)"
    if allr is not None and allr < 0.5:
        return "wrong solution (low atom match)"
    return "near miss (metric threshold)"


def _rate(rows, key="solved"):
    n = len(rows)
    return f"{sum(1 for r in rows if r.get(key)) / n:.0%} ({sum(1 for r in rows if r.get(key))}/{n})" if n else "-"


def _mean(vals):
    vals = [v for v in vals if v is not None]
    return round(sum(vals) / len(vals), 3) if vals else None


def breakdown(rows: list[dict], keyfn, title: str) -> list[str]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        groups[str(keyfn(r) or "unknown")].append(r)
    lines = [f"### By {title}", "",
             "| group | n | solved | SG top-1 | mean R1 | mean ΔR1 vs human |",
             "|---|---|---|---|---|---|"]
    for g in sorted(groups, key=lambda g: -len(groups[g])):
        rs = groups[g]
        dr1 = _mean([r["r1"] - r["human_r1"] for r in rs
                     if r.get("r1") is not None and r.get("human_r1") is not None])
        lines.append(f"| {g} | {len(rs)} | {_rate(rs)} "
                     f"| {_rate(rs, 'sg_correct')} | {_mean([r.get('r1') for r in rs])} "
                     f"| {dr1 if dr1 is not None else '-'} |")
    lines.append("")
    return lines


def analyze(results_paths: list[Path], manifest_path: Path | None,
            out_path: Path) -> str:
    rows: list[dict] = []
    for p in results_paths:
        data = json.loads(p.read_text(encoding="utf-8"))
        rows.extend(data.get("rows", []))
    meta: dict[str, dict] = {}
    if manifest_path and manifest_path.exists():
        for e in json.loads(manifest_path.read_text(encoding="utf-8")):
            meta[e["id"]] = e
    for r in rows:
        m = meta.get(r["name"], {})
        r.setdefault("category", m.get("category"))
        r.setdefault("vendor_family", m.get("vendor_family"))
        r["volume_A3"] = m.get("volume_A3")
        r["n_reflections"] = m.get("n_reflections_hkl")
        if r.get("human_r1") is None:
            r["human_r1"] = m.get("human_R1")
        r["failure"] = classify_failure(r)

    n = len(rows)
    solved = sum(1 for r in rows if r.get("solved"))
    lines = ["# CrystalPilot capability-boundary analysis", "",
             f"{n} cases | solved {solved}/{n} ({solved / max(1, n):.0%}) | "
             f"SG top-1 {_rate(rows, 'sg_correct')} | "
             f"mean R1 {_mean([r.get('r1') for r in rows])} | "
             f"mean human R1 {_mean([r.get('human_r1') for r in rows])}", ""]

    lines += breakdown(rows, lambda r: r.get("category"), "chemistry category")
    lines += breakdown(rows, lambda r: r.get("vendor_family"), "vendor family")
    lines += breakdown(rows, lambda r: crystal_system(r.get("true_sg")),
                       "crystal system (reference)")
    lines += breakdown(
        rows, lambda r: ("<2k" if (r.get("n_reflections") or 0) < 2000 else
                         "<5k" if r["n_reflections"] < 5000 else
                         "<15k" if r["n_reflections"] < 15000 else ">=15k")
        if r.get("n_reflections") else None, "reflection count")
    lines += breakdown(
        rows, lambda r: ("<1k" if (r.get("volume_A3") or 0) < 1000 else
                         "<3k" if r["volume_A3"] < 3000 else
                         "<10k" if r["volume_A3"] < 10000 else ">=10k")
        if r.get("volume_A3") else None, "cell volume (Å³)")

    fails: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if r["failure"] != "solved":
            fails[r["failure"]].append(r)
    lines += ["### Failure taxonomy", "", "| failure mode | n | example cases |",
              "|---|---|---|"]
    for f in sorted(fails, key=lambda f: -len(fails[f])):
        ex = ", ".join(r["name"] for r in fails[f][:4])
        lines.append(f"| {f} | {len(fails[f])} | {ex} |")
    lines.append("")

    lines += ["### Worst cases (unsolved, by atom-match)", "",
              "| case | category | true SG | used SG | R1 | human R1 | match | failure |",
              "|---|---|---|---|---|---|---|---|"]
    unsolved = [r for r in rows if not r.get("solved")]
    unsolved.sort(key=lambda r: ((r.get("match") or {}).get("all_match_rate") or 0))
    for r in unsolved[:40]:
        m = r.get("match") or {}
        lines.append(
            f"| {r['name'][:34]} | {r.get('category') or '-'} | {r.get('true_sg') or '?'} "
            f"| {r.get('used_sg') or '-'} | {r.get('r1') if r.get('r1') is not None else '-'} "
            f"| {r.get('human_r1') if r.get('human_r1') is not None else '-'} "
            f"| {m.get('all_match_rate', '-')} | {r['failure']} |")

    text = "\n".join(lines)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")
    print(f"analysis -> {out_path}")
    return text


def main(argv: list[str]) -> None:
    kwargs = dict(a.split("=", 1) for a in argv if "=" in a)
    results = [Path(p) for p in kwargs.get(
        "results", "").split(",") if p.strip()]
    if not results:
        res_dir = ROOT / "benchmark" / "results_ext"
        cands = sorted(res_dir.glob("results_*.json"))
        if not cands:
            raise SystemExit("no results JSON given/found")
        results = [cands[-1]]
    analyze(results,
            Path(kwargs.get("manifest", ROOT / "benchmark" / "manifest_ext.json")),
            Path(kwargs.get("out", ROOT / "benchmark" / "results_ext" / "analysis.md")))


if __name__ == "__main__":
    import sys
    main(sys.argv[1:])
