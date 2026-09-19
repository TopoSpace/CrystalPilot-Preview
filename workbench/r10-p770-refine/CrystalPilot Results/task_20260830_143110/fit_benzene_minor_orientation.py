from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from iotbx import cif


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / ".crystalpilot" / "refine" / "nodes" / "n0027" / "model.cif"
OUT = ROOT / "CrystalPilot Results" / "task_20260830_143110" / "benzene_minor_sites.json"
RING = ["C28", "C40", "C42", "C34", "C39", "C43"]

# The two local residual peaks nearest the most anisotropic benzene atoms.
# Add one lattice translation in x so they are in the same molecular image.
TARGET_FRAC = {
    "C43": np.array([1.1332, 0.7858, 0.4372]),
    "C34": np.array([1.0369, 0.8817, 0.3907]),
}

xs = next(iter(cif.reader(file_path=str(SOURCE)).build_crystal_structures().values()))
cell = xs.unit_cell()
sites = {s.label: np.array(s.site, dtype=float) for s in xs.scatterers()}

p = np.vstack([cell.orthogonalize(sites[label]) for label in ("C43", "C34")])
q = np.vstack([cell.orthogonalize(TARGET_FRAC[label]) for label in ("C43", "C34")])
u = p[1] - p[0]
v = q[1] - q[0]
u /= np.linalg.norm(u)
v /= np.linalg.norm(v)
cross = np.cross(u, v)
sine = np.linalg.norm(cross)
cosine = float(np.dot(u, v))
if sine < 1e-12:
    rotation = np.eye(3)
else:
    k = np.array(
        [[0.0, -cross[2], cross[1]], [cross[2], 0.0, -cross[0]], [-cross[1], cross[0], 0.0]]
    )
    rotation = np.eye(3) + k + k @ k * ((1.0 - cosine) / (sine * sine))
translation = q.mean(axis=0) - rotation @ p.mean(axis=0)

minor_sites = {}
displacements = {}
for label in RING:
    cart = np.asarray(cell.orthogonalize(sites[label]))
    moved = rotation @ cart + translation
    frac = np.asarray(cell.fractionalize(moved))
    minor_sites[label] = [float(x) for x in frac]
    displacements[label] = float(np.linalg.norm(moved - cart))

payload = {
    "method": "rigid minimum rotation/translation fit to the C43 and C34 difference peaks",
    "ring_order": RING,
    "anchor_targets_fractional": {k: v.tolist() for k, v in TARGET_FRAC.items()},
    "second_sites": minor_sites,
    "displacement_A": displacements,
    "rotation_angle_deg": float(np.degrees(np.arccos(np.clip((np.trace(rotation) - 1) / 2, -1, 1)))),
}
OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(payload, ensure_ascii=False, indent=2))
