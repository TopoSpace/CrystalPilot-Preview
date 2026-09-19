from __future__ import annotations

import json
from pathlib import Path

from cctbx import maptbx
from crystalpilot.io.shelx import load_shelx_dataset
from crystalpilot.pipeline.session import SolveSession


PROJECT = Path(__file__).resolve().parents[2]
TASK = Path(__file__).resolve().parent
dataset = load_shelx_dataset(PROJECT / "crystal.hkl", PROJECT / "crystal.ins")
session = SolveSession(dataset)
session.set_symmetry(dataset.symmetry_hint)

fft = session.fo_sq.patterson_map(
    resolution_factor=0.25,
    symmetry_flags=maptbx.use_space_group_symmetry,
    origin_peak_removal=True,
)
fft.apply_sigma_scaling()
peaks = fft.peak_search(
    maptbx.peak_search_parameters(
        interpolate=True,
        min_distance_sym_equiv=0.6,
        min_cross_distance=0.6,
        max_clusters=160,
    ),
    verify_symmetry=False,
).all()

sites = [list(s) for s in peaks.sites()]
heights = list(peaks.heights())
rows = []
uc = session.symmetry.unit_cell()
for index, (site, height) in enumerate(zip(sites, heights)):
    wrapped = [x % 1.0 for x in site]
    centred = [x - round(x) for x in wrapped]
    rows.append({
        "index": index,
        "site": wrapped,
        "centred_vector": centred,
        "height_sigma": height,
        "vector_length_A": uc.length(centred),
    })

def nearest_peak(target):
    best = None
    for row in rows:
        delta = [row["site"][i] - target[i] for i in range(3)]
        delta = [x - round(x) for x in delta]
        distance = uc.length(delta)
        if best is None or distance < best[0]:
            best = (distance, row)
    return {"target": [x % 1 for x in target], "distance_A": best[0],
            "nearest": best[1]}

top = [row["site"] for row in rows[:3]]
relations = []
for i in range(3):
    relations.append({
        "source_peak": i,
        "half_vector": nearest_peak([x / 2 for x in top[i]]),
    })
for i in range(3):
    for j in range(i + 1, 3):
        relations.append({
            "pair": [i, j],
            "half_difference": nearest_peak([(top[i][k] - top[j][k]) / 2
                                               for k in range(3)]),
            "half_sum": nearest_peak([(top[i][k] + top[j][k]) / 2
                                        for k in range(3)]),
        })

payload = {
    "space_group": "P -1",
    "unit_cell": list(uc.parameters()),
    "n_reflections": session.fo_sq.size(),
    "peaks": rows,
    "relations": relations,
}
(TASK / "patterson_peaks.json").write_text(
    json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
)
print(json.dumps({**payload, "peaks": rows[:50]}, indent=2, ensure_ascii=False))
