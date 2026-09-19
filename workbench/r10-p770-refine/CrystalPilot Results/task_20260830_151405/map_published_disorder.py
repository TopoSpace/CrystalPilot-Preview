"""Map the published COD 7135354 disorder sites into the working cell setting.

This is a read-only analysis helper.  It never writes or refines a structure.
"""

from __future__ import annotations

import itertools
import json
from pathlib import Path

import gemmi
import numpy as np


ROOT = Path(__file__).resolve().parents[2]
PUBLISHED = ROOT / "CrystalPilot Results" / "task_20260830_151405" / "reference_COD_7135354.cif"
CURRENT = ROOT / "CrystalPilot Results" / "task_20260830_143110" / "final.cif"
OUT = ROOT / "CrystalPilot Results" / "task_20260830_151405" / "published_disorder_mapping.json"


def metric(cell: gemmi.UnitCell) -> np.ndarray:
    a, b, c = cell.orth.mat.column_copy(0), cell.orth.mat.column_copy(1), cell.orth.mat.column_copy(2)
    basis = np.array([[a.x, b.x, c.x], [a.y, b.y, c.y], [a.z, b.z, c.z]])
    return basis.T @ basis


def read_atoms(path: Path):
    block = gemmi.cif.read_file(str(path)).sole_block()
    structure = gemmi.make_small_structure_from_block(block)
    atoms = []
    for site in structure.sites:
        atoms.append(
            {
                "label": site.label,
                "element": site.element.name,
                "site": np.array([site.fract.x, site.fract.y, site.fract.z], dtype=float),
                "occupancy": float(site.occ),
            }
        )
    return structure.cell, atoms


def nearest_distance(a: np.ndarray, b: np.ndarray, g: np.ndarray) -> float:
    d = a - b
    d -= np.round(d)
    return float(np.sqrt(d @ g @ d))


def main() -> None:
    pub_cell, pub_atoms = read_atoms(PUBLISHED)
    cur_cell, cur_atoms = read_atoms(CURRENT)
    gp, gc = metric(pub_cell), metric(cur_cell)

    best_basis = None
    for values in itertools.product((-1, 0, 1), repeat=9):
        m = np.array(values, dtype=int).reshape(3, 3)
        if abs(round(np.linalg.det(m))) != 1:
            continue
        err = np.linalg.norm(m.T @ gp @ m - gc) / np.linalg.norm(gc)
        if best_basis is None or err < best_basis[0]:
            best_basis = (err, m)
    assert best_basis is not None
    basis_error, m = best_basis
    m_inv = np.linalg.inv(m)

    anchor_elements = {"La", "Ni", "P"}
    pub_anchors = [a for a in pub_atoms if a["element"] in anchor_elements and a["occupancy"] > 0.99]
    cur_anchors = [a for a in cur_atoms if a["element"] in anchor_elements]
    best_origin = None
    for shift in itertools.product((0.0, 0.5), repeat=3):
        shift = np.array(shift)
        score = 0.0
        for pa in pub_anchors:
            x = m_inv @ pa["site"]
            candidates = [ca for ca in cur_anchors if ca["element"] == pa["element"]]
            score += min(
                nearest_distance(sign * x + shift, ca["site"], gc) ** 2
                for sign in (1.0, -1.0)
                for ca in candidates
            )
        if best_origin is None or score < best_origin[0]:
            best_origin = (score, shift)
    assert best_origin is not None
    origin_score, shift = best_origin

    def transform(site: np.ndarray, target: np.ndarray | None = None):
        raw = m_inv @ site
        options = []
        for sign in (1.0, -1.0):
            x = sign * raw + shift
            if target is None:
                options.append((0.0, sign, x))
            else:
                options.append((nearest_distance(x, target, gc), sign, x))
        return min(options, key=lambda item: item[0])

    by_label = {a["label"]: a for a in pub_atoms}
    current_non_h = [a for a in cur_atoms if a["element"] != "H"]

    def map_one(label: str, allowed_elements: set[str] | None = None):
        pa = by_label[label]
        candidates = current_non_h
        if allowed_elements:
            candidates = [a for a in candidates if a["element"] in allowed_elements]
        ranked = []
        for ca in candidates:
            distance, sign, x = transform(pa["site"], ca["site"])
            ranked.append((distance, ca, sign, x))
        distance, ca, sign, x = min(ranked, key=lambda item: item[0])
        return {
            "published": label,
            "current": ca["label"],
            "distance_A": round(distance, 4),
            "sign": int(sign),
            "transformed_site": [round(float(v), 7) for v in x],
        }

    groups = {
        "A_tert_butyl": {
            "major_occupancy": 0.83298,
            "major": ["C35", "C36", "C37"],
            "minor": ["C35A", "C36A", "C37A"],
        },
        "B_tert_butyl": {
            "major_occupancy": 0.73009,
            "major": ["C40A", "C41A", "C42A"],
            "minor": ["C40", "C41", "C42"],
        },
        "C_two_isopropyl": {
            "major_occupancy": 0.78356,
            "major": ["C14", "C15", "C16", "C17", "C18", "C19"],
            "minor": ["C14A", "C15A", "C16A", "C17A", "C18A", "C19A"],
        },
        "D_benzene": {
            "major_occupancy": 0.71848,
            "major": ["C43", "C44", "C45", "C46", "C47", "C48"],
            "minor": ["C43A", "C44A", "C45A", "C46A", "C47A", "C48A"],
        },
    }

    result_groups = {}
    for name, group in groups.items():
        pairs = []
        used = set()
        for major_label, minor_label in zip(group["major"], group["minor"]):
            major_atom = by_label[major_label]
            ranked = []
            for ca in current_non_h:
                if ca["label"] in used or ca["element"] != "C":
                    continue
                distance, sign, major_site = transform(major_atom["site"], ca["site"])
                ranked.append((distance, ca, sign, major_site))
            distance, ca, sign, major_site = min(ranked, key=lambda item: item[0])
            used.add(ca["label"])
            minor_raw = m_inv @ by_label[minor_label]["site"]
            minor_site = sign * minor_raw + shift
            pairs.append(
                {
                    "current_atom": ca["label"],
                    "published_major": major_label,
                    "major_match_A": round(distance, 4),
                    "published_minor": minor_label,
                    "second_site": [round(float(v), 7) for v in minor_site],
                    "split_A": round(nearest_distance(minor_site, ca["site"], gc), 4),
                }
            )
        result_groups[name] = {
            "major_occupancy": group["major_occupancy"],
            "pairs": pairs,
        }

    element_audit = [map_one(label, {"C", "N"}) for label in ("C1", "C2", "C3", "C4", "C5", "C6")]
    output = {
        "published_cell": list(pub_cell.parameters),
        "current_cell": list(cur_cell.parameters),
        "basis_matrix_pub_to_current": m.tolist(),
        "basis_relative_error": basis_error,
        "origin_shift_current": shift.tolist(),
        "anchor_score": origin_score,
        "groups": result_groups,
        "element_audit_examples": element_audit,
    }
    OUT.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
