"""Read-only metric audit of round-4 C4/H33 difference-map candidates."""

from pathlib import Path

import gemmi


ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT / ".crystalpilot" / "refine" / "nodes" / "n0150" / "model.cif"
TARGET = gemmi.Fractional(0.667, 0.169, 0.165)
PEAKS = [
    ("p_c4_1", 0.63, gemmi.Fractional(0.3686, 0.8615, 0.8519)),
    ("p_c4_2", 0.46, gemmi.Fractional(0.3773, 0.8623, 0.8093)),
]


def periodic_distance(cell, a, b):
    delta = gemmi.Fractional(a.x - b.x, a.y - b.y, a.z - b.z)
    delta.x -= round(delta.x)
    delta.y -= round(delta.y)
    delta.z -= round(delta.z)
    return cell.orthogonalize(delta).length()


st = gemmi.make_small_structure_from_block(gemmi.cif.read_file(str(MODEL)).sole_block())
by_label = {site.label: site for site in st.sites}
c4 = by_label["C4"].fract
print("cell", st.cell.a, st.cell.b, st.cell.c, st.cell.alpha, st.cell.beta, st.cell.gamma)
print("target_to_C4_A", round(periodic_distance(st.cell, TARGET, c4), 4))
for label, height, peak in PEAKS:
    for sign in (1, -1):
        mate = gemmi.Fractional(sign * peak.x, sign * peak.y, sign * peak.z)
        print(label, "height", height, "sign", sign,
              "to_target_A", round(periodic_distance(st.cell, mate, TARGET), 4),
              "to_C4_A", round(periodic_distance(st.cell, mate, c4), 4))

near = []
for site in st.sites:
    if site.element.name == "H":
        d = periodic_distance(st.cell, site.fract, c4)
        if d < 1.6:
            near.append((round(d, 4), site.label, round(site.occ, 5)))
print("current_H_near_C4", sorted(near))
print("current_H_count", sum(site.element.name == "H" for site in st.sites))
