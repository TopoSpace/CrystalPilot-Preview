from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
HKL4 = ROOT / "CrystalPilot Results" / "task_20260830_143110" / "shelxt_work" / "p770c.hkl"
HKL5 = ROOT / "CrystalPilot Results" / "task_20260830_143110" / "hklf5_work" / "twin.hkl"


def read_hkl(path: Path):
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        fields = line.split()
        if len(fields) < 5:
            continue
        h, k, l = map(int, fields[:3])
        if h == k == l == 0:
            continue
        intensity, sigma = map(float, fields[3:5])
        batch = int(fields[5]) if len(fields) > 5 else 1
        rows.append(((h, k, l), intensity, sigma, batch))
    return rows


h4 = read_hkl(HKL4)
h5 = [row for row in read_hkl(HKL5) if row[3] == 1]

# TWINABS HKLF5 intensities are ten times the XPREP HKLF4 values here.
# Match on both I and sigma after accounting for that scale; retain unique keys.
by_key_4 = defaultdict(list)
for hkl, intensity, sigma, _ in h4:
    by_key_4[(round(intensity, 2), round(sigma, 2))].append(hkl)

pairs = []
for hkl5, intensity5, sigma5, _ in h5:
    key = (round(intensity5 / 10.0, 2), round(sigma5 / 10.0, 2))
    candidates = by_key_4.get(key, [])
    if len(candidates) == 1:
        pairs.append((candidates[0], hkl5))

H4 = np.asarray([p[0] for p in pairs], dtype=float)
H5 = np.asarray([p[1] for p in pairs], dtype=float)
matrix_t, *_ = np.linalg.lstsq(H4, H5, rcond=None)
matrix = matrix_t.T
integer_matrix = np.rint(matrix).astype(int)
predicted = H4 @ integer_matrix.T
matches = np.all(predicted == H5, axis=1)

print(f"matched_unique_reflections={len(pairs)}")
print("hkl5 = M * hkl4, least-squares M:")
print(matrix)
print("nearest integer M:")
print(integer_matrix)
print(f"exact_fraction={matches.mean():.6f} ({matches.sum()}/{len(matches)})")
print("first_pairs:")
for hkl4, hkl5 in pairs[:12]:
    print(f"  {hkl4} -> {hkl5}")

# Validate the integer transform independently by direct hkl lookup rather than
# by the intensity-key pairs used to derive it.
lookup5 = {hkl: (intensity, sigma) for hkl, intensity, sigma, _ in h5}
matched = []
for hkl4, intensity4, sigma4, _ in h4:
    hkl5 = tuple((integer_matrix @ np.asarray(hkl4, dtype=int)).tolist())
    if hkl5 in lookup5:
        intensity5, sigma5 = lookup5[hkl5]
        matched.append((intensity4, sigma4, intensity5, sigma5))

matched = np.asarray(matched, dtype=float)
print(f"direct_hkl_overlap={len(matched)}/{len(h4)}")
if len(matched):
    finite = (matched[:, 0] > 0) & (matched[:, 2] > 0)
    scale_i = np.median(matched[finite, 2] / matched[finite, 0])
    scale_s = np.median(matched[:, 3] / matched[:, 1])
    corr_i = np.corrcoef(matched[:, 0], matched[:, 2])[0, 1]
    normalized_abs_error = np.median(
        np.abs(matched[:, 2] / scale_i - matched[:, 0]) / np.maximum(matched[:, 1], 0.01)
    )
    print(f"median_I_scale={scale_i:.6f}")
    print(f"median_sigma_scale={scale_s:.6f}")
    print(f"intensity_correlation={corr_i:.9f}")
    print(f"median_abs_difference_in_sigma={normalized_abs_error:.6f}")
