from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path

import numpy as np


PROJECT = Path(__file__).resolve().parents[2]
rows = []
for line in (PROJECT / "twin_hklf5.hkl").read_text(encoding="ascii").splitlines():
    fields = line.split()
    if len(fields) < 6:
        continue
    h, k, l = map(int, fields[:3])
    fo2, sig = map(float, fields[3:5])
    batch = int(fields[5])
    if h == k == l == 0:
        continue
    rows.append((np.array([h, k, l], dtype=float), fo2, sig, batch))

pairs = []
for i in range(len(rows) - 1):
    h2, fo2b, sigb, batch2 = rows[i]
    h1, fo1, sig1, batch1 = rows[i + 1]
    if batch2 < 0 and batch1 > 0 and abs(fo2b - fo1) < 1e-5 and abs(sigb - sig1) < 1e-5:
        pairs.append((h1, h2))

H1 = np.array([p[0] for p in pairs])
H2 = np.array([p[1] for p in pairs])
A, *_ = np.linalg.lstsq(H1, H2, rcond=None)  # row h2 = row h1 @ A
pred = H1 @ A
resid = pred - H2

# P -1 permits either Friedel mate for each indexed component.  Recover the
# physical twin matrix by alternating per-pair signs with least squares.
M = np.array([
    [-1.0, 0.0, 0.0],
    [0.25, 1.0, 0.0],
    [-0.25, -1.0, 1.0],
])
for _ in range(30):
    pred_signed = H1 @ M.T
    keep_sign = np.sum((pred_signed - H2) ** 2, axis=1)
    flip_sign = np.sum((pred_signed + H2) ** 2, axis=1)
    signs = np.where(keep_sign <= flip_sign, 1.0, -1.0)
    signed_H2 = H2 * signs[:, None]
    A_signed, *_ = np.linalg.lstsq(H1, signed_H2, rcond=None)
    M_new = A_signed.T
    if np.max(np.abs(M_new - M)) < 1e-10:
        M = M_new
        break
    M = M_new
signed_resid = H1 @ M.T - signed_H2

def rational_matrix(a):
    return [[str(Fraction(float(x)).limit_denominator(24)) for x in row] for row in a]

payload = {
    "n_pairs": len(pairs),
    "row_convention_h2_equals_h1_times_A": A.tolist(),
    "column_convention_h2_equals_M_times_h1": A.T.tolist(),
    "column_convention_rational": rational_matrix(A.T),
    "max_abs_residual_index": float(np.max(np.abs(resid))),
    "rms_residual_index": float(np.sqrt(np.mean(resid ** 2))),
    "friedel_sign_corrected_matrix_M": M.tolist(),
    "friedel_sign_corrected_rational": rational_matrix(M),
    "friedel_sign_corrected_max_abs_residual_index": float(np.max(np.abs(signed_resid))),
    "friedel_sign_corrected_rms_residual_index": float(np.sqrt(np.mean(signed_resid ** 2))),
    "examples": [
        {"domain1": h1.astype(int).tolist(), "domain2": h2.astype(int).tolist()}
        for h1, h2 in pairs[:20]
    ],
}
(Path(__file__).resolve().parent / "derived_hklf5_twin_law.json").write_text(
    json.dumps(payload, indent=2), encoding="utf-8"
)
print(json.dumps(payload, indent=2))
