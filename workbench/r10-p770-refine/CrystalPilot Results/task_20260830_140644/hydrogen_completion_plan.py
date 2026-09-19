from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from iotbx import cif


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / ".crystalpilot" / "refine" / "nodes" / "n0056" / "model.cif"
TARGET_DISTANCE = 1.75
PARENTS = {
    "C7": "P1",
    "C16": "P1",
    "C22": "P1",
    "C15": "P2",
    "C19": "P2",
    "C24": "P2",
}


xs = next(iter(cif.reader(file_path=str(SOURCE)).build_crystal_structures().values()))
cell = xs.unit_cell()
sites = {s.label: np.array(s.site, dtype=float) for s in xs.scatterers()}


def nearest_image(reference: np.ndarray, moving: np.ndarray) -> np.ndarray:
    best = None
    best_distance = float("inf")
    ref_cart = np.asarray(cell.orthogonalize(reference))
    for i in (-1, 0, 1):
        for j in (-1, 0, 1):
            for k in (-1, 0, 1):
                candidate = moving + np.array([i, j, k], dtype=float)
                distance = float(
                    np.linalg.norm(np.asarray(cell.orthogonalize(candidate)) - ref_cart)
                )
                if distance < best_distance:
                    best_distance = distance
                    best = candidate
    assert best is not None
    return best


temporary = {}
restored = {}
diagnostics = {}
for carbon, phosphorus in PARENTS.items():
    c_frac = sites[carbon]
    p_frac = nearest_image(c_frac, sites[phosphorus])
    c_cart = np.asarray(cell.orthogonalize(c_frac))
    p_cart = np.asarray(cell.orthogonalize(p_frac))
    vector = c_cart - p_cart
    distance = float(np.linalg.norm(vector))
    moved_cart = p_cart + vector * (TARGET_DISTANCE / distance)
    moved_frac = np.asarray(cell.fractionalize(moved_cart))
    temporary[carbon] = [float(x) for x in moved_frac]
    restored[carbon] = [float(x) for x in c_frac]
    diagnostics[carbon] = {
        "parent": phosphorus,
        "original_P_C_A": distance,
        "temporary_P_C_A": TARGET_DISTANCE,
        "temporary_shift_A": float(np.linalg.norm(moved_cart - c_cart)),
    }

print(
    json.dumps(
        {
            "source": str(SOURCE),
            "temporary_sites": temporary,
            "restore_sites": restored,
            "diagnostics": diagnostics,
        },
        ensure_ascii=False,
        indent=2,
    )
)
