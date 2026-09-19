"""Read-only audit of published H carriers in the working-cell setting."""

from pathlib import Path
import json

import gemmi
import numpy as np


ROOT = Path(__file__).resolve().parents[2]
PUB = ROOT / "CrystalPilot Results" / "task_20260830_151405" / "reference_COD_7135354.cif"
CUR = ROOT / ".crystalpilot" / "refine" / "nodes" / "n0115" / "model.cif"
MAP = ROOT / "CrystalPilot Results" / "task_20260830_151405" / "published_disorder_mapping.json"


def atoms(path):
    st = gemmi.make_small_structure_from_block(gemmi.cif.read_file(str(path)).sole_block())
    return st.cell, [
        {"label": s.label, "element": s.element.name, "site": np.array([s.fract.x, s.fract.y, s.fract.z]), "occ": float(s.occ)}
        for s in st.sites
    ]


def d2(a, b, cell):
    delta = a - b
    delta -= np.round(delta)
    v = cell.orth.mat.multiply(gemmi.Vec3(*delta))
    return v.x * v.x + v.y * v.y + v.z * v.z


def main():
    pc, pa = atoms(PUB)
    cc, ca = atoms(CUR)
    cfg = json.loads(MAP.read_text(encoding="utf-8"))
    m_inv = np.linalg.inv(np.array(cfg["basis_matrix_pub_to_current"], dtype=float))
    shift = np.array(cfg["origin_shift_current"], dtype=float)
    p_heavy = [a for a in pa if a["element"] != "H"]
    c_heavy = [a for a in ca if a["element"] != "H"]

    carriers = {}
    for h in (a for a in pa if a["element"] == "H"):
        carrier = min(p_heavy, key=lambda a: d2(h["site"], a["site"], pc))
        if d2(h["site"], carrier["site"], pc) > 1.35 ** 2:
            carriers.setdefault("INDEPENDENT", []).append(h["label"])
            continue
        raw = m_inv @ carrier["site"]
        ranked = []
        for sign in (1.0, -1.0):
            x = sign * raw + shift
            for a in c_heavy:
                if a["element"] not in {carrier["element"], "C", "N"}:
                    continue
                ranked.append((d2(x, a["site"], cc), a["label"]))
        _, label = min(ranked)
        carriers.setdefault(label, []).append(h["label"])

    for label, hs in sorted(carriers.items()):
        print(f"{label:>12} {len(hs):2d}  {' '.join(hs)}")
    print("site_level_H", sum(len(v) for v in carriers.values()))
    h33 = next(a for a in pa if a["label"] == "H33")
    print("published_H33_neighbours", sorted((round(d2(h33["site"], a["site"], pc) ** 0.5, 3), a["label"], a["element"]) for a in p_heavy)[:8])
    for hsign in (1.0, -1.0):
        h33x = hsign * (m_inv @ h33["site"]) + shift
        print("published_H33_working_site", int(hsign), [round(float(x), 7) for x in h33x],
              sorted((round(d2(h33x, a["site"], cc) ** 0.5, 3), a["label"], a["element"]) for a in c_heavy)[:8])

    # Find the smallest enclosing Cartesian sphere for each phosphine's C
    # substituents.  This is a diagnostic only; it tells us whether a temporary
    # P-site shift can bring all genuine P-C contacts below the H-classifier's
    # generic 1.80 A cutoff without changing the carbon geometry.
    from scipy.optimize import minimize
    by_label = {a["label"]: a for a in ca}
    for p_label, c_labels in {
        "P1": ["C7", "C16", "C16B", "C22", "C22B"],
        "P2": ["C15", "C19", "C24"],
    }.items():
        p0v = cc.orthogonalize(gemmi.Fractional(*by_label[p_label]["site"]))
        p0 = np.array([p0v.x, p0v.y, p0v.z])
        pts = []
        for label in c_labels:
            f = by_label[label]["site"] - by_label[p_label]["site"]
            f -= np.round(f)
            dv = cc.orthogonalize(gemmi.Fractional(*f))
            pts.append(p0 + np.array([dv.x, dv.y, dv.z]))
        pts = np.array(pts)
        x0 = np.r_[p0, np.max(np.linalg.norm(pts - p0, axis=1))]
        out = minimize(lambda x: x[3], x0, method="SLSQP",
                       constraints=[{"type": "ineq", "fun": lambda x, q=q: x[3] - np.linalg.norm(x[:3] - q)} for q in pts],
                       options={"maxiter": 200, "ftol": 1e-10})
        fv = cc.fractionalize(gemmi.Position(*out.x[:3]))
        fnew = np.array([fv.x, fv.y, fv.z])
        ds = np.sqrt(np.sum((pts - out.x[:3]) ** 2, axis=1))
        print(p_label, "temporary_site", [round(float(x), 7) for x in fnew],
              "distances", [round(float(x), 3) for x in ds])
        near = minimize(lambda x: np.sum((x - p0) ** 2), out.x[:3], method="SLSQP",
                        constraints=[{"type": "ineq", "fun": lambda x, q=q: 1.799 - np.linalg.norm(x - q)} for q in pts],
                        options={"maxiter": 500, "ftol": 1e-12})
        nfv = cc.fractionalize(gemmi.Position(*near.x))
        nds = np.linalg.norm(pts - near.x, axis=1)
        print(p_label, "nearest_cutoff_site", [round(nfv.x, 7), round(nfv.y, 7), round(nfv.z, 7)],
              "shift_A", round(float(np.linalg.norm(near.x - p0)), 3),
              "distances", [round(float(x), 3) for x in nds])
        if p_label == "P1":
            limits = [1.799, 1.799, 1.70, 1.799, 1.799]
            biased = minimize(lambda x: np.sum((x - p0) ** 2), out.x[:3], method="SLSQP",
                              constraints=[{"type": "ineq", "fun": lambda x, q=q, lim=lim: lim - np.linalg.norm(x - q)} for q, lim in zip(pts, limits)],
                              options={"maxiter": 500, "ftol": 1e-12})
            bfv = cc.fractionalize(gemmi.Position(*biased.x))
            bds = np.linalg.norm(pts - biased.x, axis=1)
            print("P1 biased_site", [round(bfv.x, 7), round(bfv.y, 7), round(bfv.z, 7)],
                  "shift_A", round(float(np.linalg.norm(biased.x - p0)), 3),
                  "distances", [round(float(x), 3) for x in bds])


if __name__ == "__main__":
    main()
