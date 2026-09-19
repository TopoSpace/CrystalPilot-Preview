"""Audit COD 2229074 LIST-4 FCF without modifying source data."""

from __future__ import annotations

import collections
import json
import math
import statistics
import sys
from pathlib import Path


def read_rows(path: Path):
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        fields = line.split()
        if len(fields) != 7:
            continue
        try:
            h, k, l = map(int, fields[:3])
            fc2, fo2, sigma = map(float, fields[3:6])
        except ValueError:
            continue
        rows.append((h, k, l, fc2, fo2, sigma, fields[6]))
    return rows


def canonical_hkl(row):
    hkl = row[:3]
    friedel = tuple(-x for x in hkl)
    return min(hkl, friedel)


def r1(rows):
    denominator = sum(math.sqrt(max(row[4], 0.0)) for row in rows)
    numerator = sum(
        abs(math.sqrt(max(row[4], 0.0)) - math.sqrt(max(row[3], 0.0)))
        for row in rows
    )
    return numerator / denominator


def main() -> None:
    source = Path(sys.argv[1])
    rows = read_rows(source)
    strong = [row for row in rows if row[4] > 2.0 * row[5]]
    groups = collections.defaultdict(list)
    for row in rows:
        groups[canonical_hkl(row)].append(row)

    fc2_ranges = {
        hkl: max(row[3] for row in group) - min(row[3] for row in group)
        for hkl, group in groups.items()
        if len(group) > 1
    }
    worst_hkl = max(fc2_ranges, key=fc2_ranges.get)
    worst_group = groups[worst_hkl]

    result = {
        "source": str(source),
        "n_observations": len(rows),
        "n_friedel_merged_groups": len(groups),
        "median_multiplicity": statistics.median(map(len, groups.values())),
        "maximum_multiplicity": max(map(len, groups.values())),
        "n_fo2_gt_2sigma_from_rounded_fcf": len(strong),
        "r1_fo2_gt_2sigma": r1(strong),
        "r1_all": r1(rows),
        "groups_with_nonconstant_deposited_fc2": sum(
            value > 0.02 for value in fc2_ranges.values()
        ),
        "maximum_duplicate_fc2_range": fc2_ranges[worst_hkl],
        "worst_group": {
            "canonical_hkl": worst_hkl,
            "fc2": [row[3] for row in worst_group],
            "fo2": [row[4] for row in worst_group],
        },
        "interpretation": (
            "The deposited per-observation Fc2 values reproduce the paper, but are "
            "not a single-valued function of hkl. Converting to HKLF4 keeps Fo2/sigma "
            "and irreversibly discards the non-merohedral-twin observation model."
        ),
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
