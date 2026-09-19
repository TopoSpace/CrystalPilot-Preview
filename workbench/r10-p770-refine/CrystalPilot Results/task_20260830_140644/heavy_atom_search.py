from __future__ import annotations

import json
import math
from pathlib import Path

from cctbx import crystal, xray
from cctbx.array_family import flex
from crystalpilot.io.shelx import load_shelx_dataset
from crystalpilot.pipeline.session import SolveSession


PROJECT = Path(__file__).resolve().parents[2]
TASK = Path(__file__).resolve().parent
dataset = load_shelx_dataset(PROJECT / "crystal.hkl", PROJECT / "crystal.ins")
session = SolveSession(dataset)
session.set_symmetry(dataset.symmetry_hint)
fo_sq = session.fo_sq
fo_nonnegative = fo_sq.data().deep_copy()
fo_nonnegative.set_selected(fo_nonnegative < 0, 0)
f_obs = flex.sqrt(fo_nonnegative)
selection = fo_sq.data() > (2 * fo_sq.sigmas())

pat = json.loads((TASK / "patterson_peaks.json").read_text(encoding="utf-8"))
peaks = pat["peaks"]
sps = crystal.special_position_settings(session.symmetry, min_distance_sym_equiv=0.5)


def score(sites, elements):
    xs = xray.structure(special_position_settings=sps)
    for i, (site, element) in enumerate(zip(sites, elements), start=1):
        xs.add_scatterer(xray.scatterer(
            label=f"{element}{i}", site=site, scattering_type=element, u=0.03
        ))
    fc = fo_sq.structure_factors_from_scatterers(
        xray_structure=xs, algorithm="direct"
    ).f_calc().amplitudes().data()
    den = flex.sum(fc.select(selection) * fc.select(selection))
    if den <= 0:
        return None
    k = flex.sum(f_obs.select(selection) * fc.select(selection)) / den
    r1 = flex.sum(flex.abs(f_obs.select(selection) - k * fc.select(selection))) / flex.sum(f_obs.select(selection))
    corr = flex.linear_correlation(f_obs.select(selection), fc.select(selection)).coefficient()
    return float(r1), float(corr), float(k)


single = []
for peak in peaks:
    site = [(x % 1.0) / 2.0 for x in peak["site"]]
    result = score([site], ["La"])
    if result is not None:
        single.append({
            "patterson_index": peak["index"],
            "patterson_height_sigma": peak["height_sigma"],
            "site": site,
            "r1_obs": result[0],
            "correlation_obs": result[1],
            "scale": result[2],
        })
single.sort(key=lambda x: x["r1_obs"])

payload = {
    "method": "single-La fixed-site trials from half Patterson vectors",
    "n_observed_I_gt_2sigma": selection.count(True),
    "best": single[:30],
}
(TASK / "heavy_atom_single_site_trials.json").write_text(
    json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
)
print(json.dumps(payload, indent=2, ensure_ascii=False))
