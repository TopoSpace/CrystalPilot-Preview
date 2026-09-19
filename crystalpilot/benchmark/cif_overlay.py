"""Overlay two crystal structures (CIF/RES) for a HUMAN comparison.

Mentor-side utility, deliberately outside the CrystalPilot product: the
user wants to look at the group's manual final structure and the agent's
delivery superimposed, decide what the agent got wrong, and say so.

    python -m crystalpilot.benchmark.cif_overlay REF.cif MODEL.cif -o out.html

The page is one self-contained HTML file (3Dmol.js from its CDN): both
structures expanded to the reference cell, the model brought onto the
reference by the same emma alignment the grader uses, atoms paired within
0.7 A, and the parts that do NOT pair - atoms only in the reference, atoms
only in the model, element mismatches, occupancy disagreements - marked
in the picture and listed in tables. Nothing here decides anything.
"""
from __future__ import annotations

import argparse
import html
import json
import math
from pathlib import Path
from typing import Any

from .evaluate import (load_reference, reference_r1, same_sg_type,
                       to_reference_setting)

PAIR_TOL_A = 0.7
HEAVY_Z = 11


def _load(path: str | Path):
    """Non-H atoms of a CIF/RES (hydrogens clutter the picture and pair
    badly between a riding model and a manual one)."""
    from cctbx.array_family import flex
    p = str(path)
    xs = load_reference(p, None) if p.lower().endswith((".res", ".ins")) \
        else load_reference(None, p)
    if xs is None:
        raise SystemExit(f"cannot read a structure from {p}")
    keep = flex.bool([_el(sc) not in ("H", "D") for sc in xs.scatterers()])
    return xs.select(keep)


def _el(sc) -> str:
    return "".join(c for c in sc.scattering_type if c.isalpha())[:2].capitalize()


def _z(el: str) -> int:
    from cctbx.eltbx import tiny_pse
    try:
        return int(tiny_pse.table(el).atomic_number())
    except Exception:  # noqa: BLE001
        return 0


def _heavy_subset(xs):
    from cctbx.array_family import flex
    sel = flex.bool([_z(_el(sc)) >= HEAVY_Z for sc in xs.scatterers()])
    return xs.select(sel)


def _match(ref, model, tolerance: float):
    from cctbx import euclidean_model_matching as emma
    matches = emma.model_matches(ref.as_emma_model(), model.as_emma_model(),
                                 tolerance=tolerance)
    if not matches.refined_matches:
        return None
    return matches.refined_matches[0]


def _apply_rt(xs, rt, target_cs):
    """Model scatterers moved by emma's rt (fractional, model2 -> model1
    frame) and re-housed in the reference crystal symmetry."""
    from cctbx import xray
    from scitbx import matrix
    out = xray.structure(crystal_symmetry=target_cs)
    for sc in xs.scatterers():
        x = matrix.col(sc.site)
        y = rt.r * x + rt.t
        new = sc.customized_copy(site=tuple(float(v) for v in y))
        out.add_scatterer(new)
    return out


def _cell_str(xs) -> str:
    a, b, c, al, be, ga = xs.unit_cell().parameters()
    return f"{a:.3f} {b:.3f} {c:.3f}  {al:.2f} {be:.2f} {ga:.2f}"


def _formula(xs) -> str:
    try:
        content = xs.unit_cell_content()
    except Exception:  # noqa: BLE001
        return "?"
    parts = []
    for el in sorted(content, key=lambda e: (e != "C", e != "H", e)):
        n = content[el]
        parts.append(f"{el}{n:.2f}".rstrip("0").rstrip("."))
    return " ".join(parts)


def _min_dist(cs, site_a, site_b) -> float:
    from cctbx import crystal, sgtbx
    sps = crystal.special_position_settings(cs)
    eq = sps.sym_equiv_sites(site_a)
    return float(sgtbx.min_sym_equiv_distance_info(eq, site_b).dist())


def compare(ref, model, tolerance: float = PAIR_TOL_A) -> dict[str, Any]:
    """Align model onto ref, pair atoms, list the disagreements."""
    ref_s = to_reference_setting(ref) if not same_sg_type(ref, model) \
        else ref
    mod_s = to_reference_setting(model) if not same_sg_type(ref, model) \
        else model
    out: dict[str, Any] = {
        "ref": {"n_atoms": ref.scatterers().size(),
                "space_group": str(ref.space_group_info()),
                "cell": _cell_str(ref), "formula_cell": _formula(ref)},
        "model": {"n_atoms": model.scatterers().size(),
                  "space_group": str(model.space_group_info()),
                  "cell": _cell_str(model), "formula_cell": _formula(model)},
        "same_sg_type": same_sg_type(ref, model),
    }
    if not out["same_sg_type"]:
        # emma insists on one space group for both models; a wrong-group
        # delivery (pa2 hex-l2-r2: R-3 against P6/mmm) is still worth
        # overlaying - compare the full cell contents in P1 instead
        ref_s = ref_s.expand_to_p1()
        mod_s = mod_s.expand_to_p1()
        out["compared_in_p1"] = True
        out["note"] = ("space-group types differ: both models expanded to "
                       "P1 (full cell content) before alignment; pair "
                       "counts are per CELL, not per asymmetric unit")
    # alignment on the heavy atoms first (the frame), then every atom
    hr, hm = _heavy_subset(ref_s), _heavy_subset(mod_s)
    heavy = _match(hr, hm, 1.0) if hr.scatterers().size() and \
        hm.scatterers().size() else None
    full = _match(ref_s, mod_s, tolerance)
    if full is None and heavy is None:
        out["error"] = "no alignment found (different structures?)"
        return out
    rt = (full.rt if full is not None else heavy.rt)
    if heavy is not None:
        out["heavy_match"] = {"n_ref": hr.scatterers().size(),
                              "n_model": hm.scatterers().size(),
                              "n_pairs": len(heavy.pairs),
                              "rms_A": round(float(heavy.rms), 3)}
    moved = _apply_rt(mod_s, rt, ref_s.crystal_symmetry())
    cs = ref_s.crystal_symmetry()
    rs, ms = ref_s.scatterers(), moved.scatterers()
    pairs = list(full.pairs) if full is not None else []
    paired_ref = {i for i, _ in pairs}
    paired_mod = {j for _, j in pairs}
    rows = []
    for i, j in pairs:
        a, b = rs[i], ms[j]
        d = _min_dist(cs, a.site, b.site)
        rows.append({
            "ref": a.label, "ref_el": _el(a), "ref_occ": round(a.occupancy, 3),
            "model": b.label, "model_el": _el(b),
            "model_occ": round(b.occupancy, 3), "dist_A": round(d, 3),
            "element_mismatch": _el(a) != _el(b),
            "occ_mismatch": abs(a.occupancy - b.occupancy) > 0.1,
        })
    rows.sort(key=lambda r: (-int(r["element_mismatch"]), -r["dist_A"]))

    def nearest(site, others):
        best = None
        for sc in others:
            d = _min_dist(cs, site, sc.site)
            if best is None or d < best[0]:
                best = (d, sc.label, _el(sc))
        return best

    only_ref, only_model = [], []
    for i, sc in enumerate(rs):
        if i in paired_ref:
            continue
        nb = nearest(sc.site, ms) if ms.size() else None
        only_ref.append({"label": sc.label, "el": _el(sc),
                         "occ": round(sc.occupancy, 3),
                         "nearest_model": nb and {"label": nb[1], "el": nb[2],
                                                  "dist_A": round(nb[0], 2)}})
    for j, sc in enumerate(ms):
        if j in paired_mod:
            continue
        nb = nearest(sc.site, rs) if rs.size() else None
        only_model.append({"label": sc.label, "el": _el(sc),
                           "occ": round(sc.occupancy, 3),
                           "nearest_ref": nb and {"label": nb[1], "el": nb[2],
                                                  "dist_A": round(nb[0], 2)}})
    only_ref.sort(key=lambda r: -_z(r["el"]))
    only_model.sort(key=lambda r: -_z(r["el"]))
    out.update({
        "n_pairs": len(pairs),
        "rms_A": round(float(full.rms), 3) if full is not None else None,
        "pairs": rows,
        "n_element_mismatch": sum(1 for r in rows if r["element_mismatch"]),
        "n_occ_mismatch": sum(1 for r in rows if r["occ_mismatch"]),
        "only_ref": only_ref,
        "only_model": only_model,
        "_ref_structure": ref_s,
        "_model_structure": moved,
    })
    return out


#: covalent radii (A, Cordero 2008) for the display bonds; unknown -> 1.5
_COV_R = {
    "H": 0.31, "B": 0.84, "C": 0.76, "N": 0.71, "O": 0.66, "F": 0.57,
    "Na": 1.66, "Mg": 1.41, "Al": 1.21, "Si": 1.11, "P": 1.07, "S": 1.05,
    "Cl": 1.02, "K": 2.03, "Ca": 1.76, "Ti": 1.60, "V": 1.53, "Cr": 1.39,
    "Mn": 1.39, "Fe": 1.32, "Co": 1.26, "Ni": 1.24, "Cu": 1.32, "Zn": 1.22,
    "Ga": 1.22, "Ge": 1.20, "As": 1.19, "Se": 1.20, "Br": 1.20, "Rb": 2.20,
    "Sr": 1.95, "Y": 1.90, "Zr": 1.75, "Nb": 1.64, "Mo": 1.54, "Ru": 1.46,
    "Rh": 1.42, "Pd": 1.39, "Ag": 1.45, "Cd": 1.44, "In": 1.42, "Sn": 1.39,
    "Sb": 1.39, "Te": 1.38, "I": 1.39, "Cs": 2.44, "Ba": 2.15, "La": 2.07,
    "Ce": 2.04, "Pr": 2.03, "Nd": 2.01, "Sm": 1.98, "Eu": 1.98, "Gd": 1.96,
    "Tb": 1.94, "Dy": 1.92, "Ho": 1.92, "Er": 1.89, "Tm": 1.90, "Yb": 1.87,
    "Lu": 1.87, "Hf": 1.75, "Ta": 1.70, "W": 1.62, "Re": 1.51, "Os": 1.44,
    "Ir": 1.41, "Pt": 1.36, "Au": 1.36, "Hg": 1.32, "Tl": 1.45, "Pb": 1.46,
    "Bi": 1.48, "Th": 2.06, "U": 1.96,
}
BOND_SLACK_A = 0.45
IMAGE_MARGIN = 0.12


def _is_metal_el(el: str) -> bool:
    return _z(el) >= HEAVY_Z and el not in ("P", "S", "Cl", "Br", "I", "Se",
                                            "Te", "As", "Si", "Ge", "Sb")


def _cell_atoms(xs, flags: dict[int, str]) -> list[dict[str, Any]]:
    """Every symmetry copy of every ASU atom inside the cell ('core'), plus
    the copies just outside it (within IMAGE_MARGIN) that complete bonds
    across the cell faces ('image'). Each entry remembers its ASU parent
    so the pairing flag follows every copy."""
    from cctbx import crystal
    sps = crystal.special_position_settings(xs.crystal_symmetry())
    core: list[dict[str, Any]] = []
    for idx, sc in enumerate(xs.scatterers()):
        eq = sps.sym_equiv_sites(sc.site)
        seen = set()
        for n, site in enumerate(eq.coordinates()):
            frac = tuple(v - math.floor(v) for v in site)
            key = tuple(round(v, 3) for v in frac)
            if key in seen:
                continue
            seen.add(key)
            # the first equivalent is the site as the author placed it; the
            # others are its symmetry mates (a 0.125-occupancy guest in
            # P6/mmm has 23 of them, and drawn alike they read as a smear)
            core.append({"idx": idx, "label": sc.label, "el": _el(sc),
                         "occ": float(sc.occupancy),
                         "u": float(sc.u_iso) if sc.u_iso is not None else 0.0,
                         "frac": frac, "flag": flags.get(idx, "PAR"),
                         "image": False, "asu": n == 0})
    images: list[dict[str, Any]] = []
    shifts = [(i, j, k) for i in (-1, 0, 1) for j in (-1, 0, 1)
              for k in (-1, 0, 1) if (i, j, k) != (0, 0, 0)]
    for at in core:
        for sh in shifts:
            f = tuple(at["frac"][n] + sh[n] for n in range(3))
            if all(-IMAGE_MARGIN <= v < 1.0 + IMAGE_MARGIN for v in f):
                images.append({**at, "frac": f, "image": True})
    return core + images


def _bonds(atoms: list[dict[str, Any]], cell, n_core: int) -> list[tuple]:
    """Distance bonds (covalent radii + slack) between drawn atoms; at least
    one partner must be a core atom, metal-metal pairs are not drawn."""
    import numpy as np
    if not atoms:
        return []
    xyz = np.array([cell.orthogonalize(a["frac"]) for a in atoms])
    rad = np.array([_COV_R.get(a["el"], 1.5) for a in atoms])
    metal = np.array([_is_metal_el(a["el"]) for a in atoms])
    out: list[tuple] = []
    for i in range(n_core):
        d = np.linalg.norm(xyz[i + 1:] - xyz[i], axis=1)
        cut = rad[i] + rad[i + 1:] + BOND_SLACK_A
        hit = np.nonzero((d <= cut) & (d >= 0.4)
                         & ~(metal[i] & metal[i + 1:]))[0]
        for h in hit:
            out.append((i, int(h) + i + 1))
    return out


def _pdb_text(atoms: list[dict[str, Any]], ids: list[int], bonds: list[tuple],
              cell, chain: str) -> str:
    """A PDB model of the atoms `ids` (a subset of `atoms`, renumbered) with
    explicit CONECT records for the bonds that stay inside the subset. Atoms
    are tagged by residue name so the viewer can select them: PAR = paired,
    UNM = only in this structure, MIS = element mismatch, IMG = a copy
    outside the cell drawn only to complete a bond. (The first version wrote
    the 4-letter 'PAIR' into the 3-column resName field, which shifted the
    coordinate columns of every paired atom: the framework rendered as a
    heap of misplaced atoms while the unpaired guest, tagged 'UNM', came
    out right - the picture the user could not read.)"""
    a, b, c, al, be, ga = cell.parameters()
    lines = [f"CRYST1{a:9.3f}{b:9.3f}{c:9.3f}{al:7.2f}{be:7.2f}{ga:7.2f} P 1"]
    serial: dict[int, int] = {}
    for n, i in enumerate(ids, start=1):
        at = atoms[i]
        serial[i] = n
        x, y, z = cell.orthogonalize(at["frac"])
        resn = "IMG" if at["image"] else at["flag"][:3]
        name = at["label"][:4].ljust(4)
        b_iso = at["u"] * 8 * math.pi ** 2
        lines.append(
            f"HETATM{n:5d} {name} {resn:>3} {chain}{at['idx'] % 9999 + 1:4d}"
            f"    {x:8.3f}{y:8.3f}{z:8.3f}{at['occ']:6.2f}{b_iso:6.2f}"
            f"          {at['el']:>2}")
    for i, j in bonds:
        if i in serial and j in serial:
            lines.append(f"CONECT{serial[i]:5d}{serial[j]:5d}")
    lines.append("END")
    return "\n".join(lines)


def _pdb_models(xs, chain: str, flags: dict[int, str],
                cell) -> tuple[dict[str, str], dict[str, int]]:
    """The full cell of one structure split into the layers the page draws
    with different opacities - 3Dmol applies ONE opacity per model, so a
    translucent halo and solid difference spheres cannot share a model
    (the second version tried, and the last style set won: the reference
    halo came out opaque and hid the model inside it).

      frame     every symmetry copy inside the cell, all bonds
      images    copies just outside the cell + the core atoms they bond to
      diff      unpaired / mismatched atoms, every symmetry copy
      diff_asu  the same, only the copy the author placed (one per ASU atom)
    """
    atoms = _cell_atoms(xs, flags)
    n_core = sum(1 for at in atoms if not at["image"])
    bonds = _bonds(atoms, cell, n_core)
    core = [i for i, at in enumerate(atoms) if not at["image"]]
    imgs = [i for i, at in enumerate(atoms) if at["image"]]
    img_layer = set(imgs)
    img_bonds = [(i, j) for i, j in bonds
                 if atoms[i]["image"] or atoms[j]["image"]]
    for i, j in img_bonds:            # the core end of a face-crossing bond
        img_layer.update((i, j))
    diff = [i for i in core if atoms[i]["flag"] in ("UNM", "MIS")]
    diff_asu = [i for i in diff if atoms[i]["asu"]]
    models = {
        "frame": _pdb_text(atoms, core, bonds, cell, chain),
        "images": _pdb_text(atoms, sorted(img_layer), img_bonds, cell, chain),
        "diff": _pdb_text(atoms, diff, bonds, cell, chain),
        "diff_asu": _pdb_text(atoms, diff_asu, bonds, cell, chain),
    }
    geo = {"n_core": n_core, "n_image": len(imgs), "n_bonds": len(bonds),
           "n_diff": len(diff), "n_diff_asu": len(diff_asu)}
    return models, geo


def render_html(cmp: dict[str, Any], title: str, ref_name: str,
                model_name: str, extra: dict[str, Any] | None = None) -> str:
    ref_s = cmp["_ref_structure"]
    mod_s = cmp["_model_structure"]
    cell = ref_s.unit_cell()
    rflags: dict[int, str] = {}
    mflags: dict[int, str] = {}
    rlabels = {sc.label: i for i, sc in enumerate(ref_s.scatterers())}
    mlabels = {sc.label: j for j, sc in enumerate(mod_s.scatterers())}
    for r in cmp["only_ref"]:
        rflags[rlabels[r["label"]]] = "UNM"
    for r in cmp["only_model"]:
        mflags[mlabels[r["label"]]] = "UNM"
    for p in cmp["pairs"]:
        if p["element_mismatch"]:
            rflags[rlabels[p["ref"]]] = "MIS"
            mflags[mlabels[p["model"]]] = "MIS"
    pdb_a, geo_a = _pdb_models(ref_s, "A", rflags, cell)
    pdb_b, geo_b = _pdb_models(mod_s, "B", mflags, cell)

    def tbl(rows, cols):
        if not rows:
            return "<p class='muted'>（无）</p>"
        h = "".join(f"<th>{html.escape(c[1])}</th>" for c in cols)
        body = []
        for r in rows:
            cells = []
            for key, _ in cols:
                v = r.get(key)
                if isinstance(v, dict):
                    v = f"{v.get('label')} ({v.get('el')}) {v.get('dist_A')} Å"
                elif isinstance(v, bool):
                    v = "yes" if v else ""
                cells.append(f"<td>{html.escape(str(v if v is not None else ''))}</td>")
            body.append("<tr>" + "".join(cells) + "</tr>")
        return f"<table><tr>{h}</tr>{''.join(body)}</table>"

    pair_cols = [("ref", "参考"), ("ref_el", "元素"), ("ref_occ", "占有率"),
                 ("model", "模型"), ("model_el", "元素"), ("model_occ", "占有率"),
                 ("dist_A", "距离 Å"), ("element_mismatch", "元素不符"),
                 ("occ_mismatch", "占有率不符")]
    only_ref_cols = [("label", "原子"), ("el", "元素"), ("occ", "占有率"),
                     ("nearest_model", "模型中最近原子")]
    only_model_cols = [("label", "原子"), ("el", "元素"), ("occ", "占有率"),
                       ("nearest_ref", "参考中最近原子")]
    extra = extra or {}
    summary_rows = [
        ("", "参考 A", "模型 B"),
        ("文件", ref_name, model_name),
        ("空间群", cmp["ref"]["space_group"], cmp["model"]["space_group"]),
        ("晶胞", cmp["ref"]["cell"], cmp["model"]["cell"]),
        ("ASU 非氢原子数", cmp["ref"]["n_atoms"], cmp["model"]["n_atoms"]),
        ("胞内组成（占有率加权）", cmp["ref"]["formula_cell"],
         cmp["model"]["formula_cell"]),
        ("R1", extra.get("ref_r1", "?"), extra.get("model_r1", "?")),
    ]
    summ = "".join(
        f"<tr><th>{html.escape(str(r[0]))}</th><td>{html.escape(str(r[1]))}</td>"
        f"<td>{html.escape(str(r[2]))}</td></tr>" for r in summary_rows)
    hm = cmp.get("heavy_match") or {}
    stats = (f"重原子对齐：{hm.get('n_pairs', '?')}/{hm.get('n_ref', '?')} 参考重原子配上"
             f"（rms {hm.get('rms_A', '?')} Å）；全原子配对 {cmp['n_pairs']} 对"
             f"（rms {cmp['rms_A']} Å，容差 {PAIR_TOL_A} Å）；元素不符 "
             f"{cmp['n_element_mismatch']} 对；占有率相差 >0.1 的 "
             f"{cmp['n_occ_mismatch']} 对；只在参考中 {len(cmp['only_ref'])} 个；"
             f"只在模型中 {len(cmp['only_model'])} 个。")
    data = json.dumps({"A": pdb_a, "B": pdb_b, "geo": {"A": geo_a, "B": geo_b},
                       "orth": [float(v) for v in cell.orthogonalization_matrix()]})
    drawn = (f"画面：整胞展开，A {geo_a['n_core']} 个原子 / {geo_a['n_bonds']} 根键，"
             f"B {geo_b['n_core']} 个原子 / {geo_b['n_bonds']} 根键（跨胞面的键用胞外"
             f"淡色副本补全：A {geo_a['n_image']}、B {geo_b['n_image']} 个）。"
             f"差异原子按对称性展开后 A {geo_a['n_diff']} 个（作者放置的那份 "
             f"{geo_a['n_diff_asu']} 个），B {geo_b['n_diff']} 个"
             f"（{geo_b['n_diff_asu']} 个）：实心球是作者放置的那一份，"
             f"半透明球是它的对称副本。")
    return f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<title>{html.escape(title)}</title>
<script src="https://3dmol.org/build/3Dmol-min.js"></script>
<style>
 body {{ font-family: system-ui, "Microsoft YaHei", sans-serif; margin: 0; display: grid;
        grid-template-columns: minmax(0, 1fr) minmax(300px, 36%); height: 100vh; }}
 #view {{ position: relative; height: 100vh; min-width: 0; }}
 #panel {{ overflow: auto; padding: 12px 16px; border-left: 1px solid #ddd; font-size: 13px; }}
 h1 {{ font-size: 16px; margin: 4px 0 8px; }}
 h2 {{ font-size: 14px; margin: 14px 0 6px; }}
 table {{ border-collapse: collapse; width: 100%; }}
 th, td {{ border: 1px solid #e3e3e3; padding: 2px 5px; text-align: left; font-size: 12px; }}
 th {{ background: #f6f6f6; }}
 .muted {{ color: #888; }}
 #ctl {{ position: absolute; top: 8px; left: 8px; background: rgba(255,255,255,.93);
         padding: 8px 10px; border-radius: 6px; font-size: 12px; line-height: 1.7; z-index: 5;
         max-width: 300px; border: 1px solid #ddd; }}
 #ctl fieldset {{ border: 0; padding: 0; margin: 0 0 4px; }}
 #ctl legend {{ font-weight: 600; padding: 0; }}
 #ctl button {{ font-size: 11px; margin: 2px 4px 2px 0; }}
 .sw {{ display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 4px; vertical-align: middle; }}
 .dot {{ display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 4px; vertical-align: middle; }}
 .stats {{ background: #fffbe6; border: 1px solid #ffe58f; padding: 6px 8px; border-radius: 4px; }}
</style></head>
<body>
<div id="view"><div id="ctl">
 <fieldset><legend>显示</legend>
 <label><input type="checkbox" id="showA" checked> <span class="sw" style="background:#b0b0b0"></span>参考 A（半透明粗棒，灰碳）</label><br>
 <label><input type="checkbox" id="showB" checked> <span class="sw" style="background:#ff8c00"></span>模型 B（实心球棍，橙碳）</label><br>
 <label><input type="checkbox" id="frame" checked> 骨架（配对上的原子）</label><br>
 <label><input type="checkbox" id="diff" checked> 差异原子（球）</label><br>
 <label><input type="checkbox" id="asuonly"> 差异原子只画作者放置的那份（不画对称副本）</label><br>
 <label><input type="checkbox" id="labels"> 差异原子标签</label><br>
 <label><input type="checkbox" id="images" checked> 胞外补键副本（淡色）</label><br>
 <label><input type="checkbox" id="cellbox" checked> 晶胞</label>
 <label style="margin-left:10px"><input type="checkbox" id="spin"> 旋转</label>
 </fieldset>
 <fieldset><legend>视角</legend>
 <button id="vc">沿 c 轴</button><button id="va">沿 a 轴</button><button id="vb">沿 b 轴</button><button id="vfit">复位</button><button id="vdiff">对准差异原子</button>
 </fieldset>
 <span class="muted"><span class="dot" style="background:#e02020"></span>只在 A 中　<span class="dot" style="background:#2050e0"></span>只在 B 中　<span class="dot" style="background:#8a2be2"></span>元素不符（实心 = 作者放置的那份，半透明 = 对称副本）</span>
</div></div>
<div id="panel">
 <h1>{html.escape(title)}</h1>
 <table>{summ}</table>
 <p class="stats">{html.escape(stats)}</p>
 <p class="muted">{html.escape(drawn)}</p>
 <h2>只在参考 A 中（模型漏掉 / 掩膜掉的）</h2>{tbl(cmp['only_ref'], only_ref_cols)}
 <h2>只在模型 B 中（模型多出来的）</h2>{tbl(cmp['only_model'], only_model_cols)}
 <h2>配对原子（元素不符与偏移最大的在前）</h2>{tbl(cmp['pairs'], pair_cols)}
 <p class="muted">对齐与配对用评分器同一套 emma 算法；坐标已把模型 B 变换到参考 A 的原点/设置；两者都按参考晶胞展开到 P1 显示整胞，键按共价半径判定并显式给出（不靠查看器猜键）。</p>
</div>
<script>
const D = {data};
const v = $3Dmol.createViewer("view", {{backgroundColor: "white"}});
const PDBOPT = {{assignbonds: false, assignBonds: false, keepH: true}};
const add = t => v.addModel(t, "pdb", PDBOPT);
// one 3Dmol model per layer: 3Dmol keeps ONE opacity per model
const A = {{frame: add(D.A.frame), images: add(D.A.images), diff: add(D.A.diff), asu: add(D.A.diff_asu)}};
const B = {{frame: add(D.B.frame), images: add(D.B.images), diff: add(D.B.diff), asu: add(D.B.diff_asu)}};
const $ = id => document.getElementById(id);
// B keeps the Jmol element colours (3Dmol's own orangeCarbon paints every
// element it does not know, Zr included, deep pink) with carbon in orange
const COLA = "Jmol";
const COLB = {{prop: "elem", map: Object.assign({{}}, $3Dmol.elementColors.Jmol, {{C: 0xff8c00}})}};
const RED = "#e02020", BLUE = "#2050e0", PURPLE = "#8a2be2";
function diffStyle(S, colUnm, on) {{
  // symmetry copies: translucent and smaller; the author's own copy: solid
  const asuOnly = $("asuonly").checked;
  if (!asuOnly) {{
    S.diff.setStyle({{resn: "UNM"}}, {{sphere: {{radius: 0.24, color: colUnm, opacity: 0.45}}, stick: {{radius: 0.10, color: colUnm, opacity: 0.45}}}});
    S.diff.setStyle({{resn: "MIS"}}, {{sphere: {{radius: 0.24, color: PURPLE, opacity: 0.45}}, stick: {{radius: 0.10, color: PURPLE, opacity: 0.45}}}});
  }}
  S.asu.setStyle({{resn: "UNM"}}, {{sphere: {{radius: 0.38, color: colUnm}}, stick: {{radius: 0.14, color: colUnm}}}});
  S.asu.setStyle({{resn: "MIS"}}, {{sphere: {{radius: 0.38, color: PURPLE}}, stick: {{radius: 0.14, color: PURPLE}}}});
}}
function style() {{
  const showA = $("showA").checked, showB = $("showB").checked;
  const frame = $("frame").checked, diff = $("diff").checked, imgs = $("images").checked;
  v.removeAllLabels();
  [A, B].forEach(S => Object.values(S).forEach(m => m.setStyle({{}}, {{}})));
  if (showA) {{
    // A is a translucent halo; B's solid ball-and-stick shows inside it
    if (frame) {{
      A.frame.setStyle({{}}, {{stick: {{radius: 0.21, colorscheme: COLA, opacity: 0.38}}}});
      if (imgs) A.images.setStyle({{}}, {{stick: {{radius: 0.21, colorscheme: COLA, opacity: 0.12}}}});
    }}
    if (diff) diffStyle(A, RED);
  }}
  if (showB) {{
    if (frame) {{
      B.frame.setStyle({{}}, {{stick: {{radius: 0.10, colorscheme: COLB}}, sphere: {{radius: 0.17, colorscheme: COLB}}}});
      if (imgs) B.images.setStyle({{}}, {{stick: {{radius: 0.10, colorscheme: COLB, opacity: 0.25}}, sphere: {{radius: 0.17, colorscheme: COLB, opacity: 0.25}}}});
    }}
    if (diff) diffStyle(B, BLUE);
  }}
  if ($("labels").checked && diff) {{
    const tag = (S, chain) => S.asu.selectedAtoms({{}}).forEach(a => {{
      v.addLabel(chain + ":" + a.atom.trim() + " " + a.elem, {{position: a, fontSize: 11, backgroundOpacity: 0.7}});
    }});
    if (showA) tag(A, "A"); if (showB) tag(B, "B");
  }}
  v.removeAllShapes();
  if ($("cellbox").checked) v.addUnitCell(A.frame, {{box: {{color: "#666"}}}});
  v.render();
}}
["showA","showB","frame","diff","asuonly","labels","images","cellbox"].forEach(id => $(id).addEventListener("change", style));
$("spin").addEventListener("change", e => v.spin(e.target.checked ? "y" : false));
// axis views from the orthogonalisation matrix (a along x, b in xy, c* along z):
// rotate the chosen axis onto the camera z, then turn in-plane so c points up
// (a points right for the c view)
const M = D.orth;
const cart = h => [M[0]*h[0]+M[1]*h[1]+M[2]*h[2], M[3]*h[0]+M[4]*h[1]+M[5]*h[2], M[6]*h[0]+M[7]*h[1]+M[8]*h[2]];
const unit = u => {{ const n = Math.hypot(u[0], u[1], u[2]); return [u[0]/n, u[1]/n, u[2]/n]; }};
function qFromTo(a, b) {{
  const c = [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]];
  const d = a[0]*b[0]+a[1]*b[1]+a[2]*b[2], s = Math.hypot(c[0], c[1], c[2]);
  if (s < 1e-8) return d > 0 ? [0, 0, 0, 1] : [1, 0, 0, 0];
  const h = Math.atan2(s, d) / 2, k = Math.sin(h) / s;
  return [c[0]*k, c[1]*k, c[2]*k, Math.cos(h)];
}}
function qApply(q, p) {{
  const [x, y, z, w] = q;
  const cx = y*p[2]-z*p[1]+w*p[0], cy = z*p[0]-x*p[2]+w*p[1], cz = x*p[1]-y*p[0]+w*p[2];
  return [p[0]+2*(y*cz-z*cy), p[1]+2*(z*cx-x*cz), p[2]+2*(x*cy-y*cx)];
}}
function look(axis) {{
  const dir = unit(cart(axis === "a" ? [1,0,0] : axis === "b" ? [0,1,0] : [0,0,1]));
  const q = qFromTo(dir, [0, 0, 1]);
  const cur = v.getView();
  v.setView([cur[0], cur[1], cur[2], cur[3], q[0], q[1], q[2], q[3]]);
  const s = qApply(q, unit(cart(axis === "c" ? [1,0,0] : [0,0,1])));
  const ang = axis === "c" ? Math.atan2(s[1], s[0]) : Math.atan2(-s[0], s[1]);
  v.rotate(-ang * 180 / Math.PI, "vz");
  v.zoomTo(); v.render();
}}
$("vc").addEventListener("click", () => look("c"));
$("va").addEventListener("click", () => look("a"));
$("vb").addEventListener("click", () => look("b"));
$("vfit").addEventListener("click", () => {{ v.zoomTo(); v.render(); }});
$("vdiff").addEventListener("click", () => {{ v.zoomTo({{resn: ["UNM", "MIS"]}}); v.render(); }});
// URL options, e.g. #a=0&asu=1&labels=1&view=a&zoomto=diff&zoom=1.5 (for scripted screenshots too)
const H = Object.fromEntries(location.hash.replace(/^#/, "").split("&").filter(Boolean).map(kv => kv.split("=").map(decodeURIComponent)));
const setChk = (id, key) => {{ if (key in H) $(id).checked = H[key] !== "0"; }};
setChk("showA", "a"); setChk("showB", "b"); setChk("frame", "frame"); setChk("diff", "diff");
setChk("asuonly", "asu"); setChk("labels", "labels"); setChk("images", "images"); setChk("cellbox", "cell");
style(); v.zoomTo();
if (H.view) look(H.view);
if (H.zoomto === "diff") v.zoomTo({{resn: ["UNM", "MIS"]}});
if (H.zoom) v.zoom(parseFloat(H.zoom));
v.render();
</script>
</body></html>
"""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("ref")
    ap.add_argument("model")
    ap.add_argument("-o", "--out", default=None)
    ap.add_argument("--title", default=None)
    ap.add_argument("--json", default=None, help="also dump the comparison")
    a = ap.parse_args(argv)
    ref, model = _load(a.ref), _load(a.model)
    cmp = compare(ref, model)
    if "error" in cmp:
        print("ERROR:", cmp["error"])
        return 2
    extra = {
        "ref_r1": reference_r1(a.ref if a.ref.lower().endswith((".res", ".ins"))
                               else None,
                               a.ref if a.ref.lower().endswith(".cif") else None),
        "model_r1": reference_r1(
            a.model if a.model.lower().endswith((".res", ".ins")) else None,
            a.model if a.model.lower().endswith(".cif") else None),
    }
    title = a.title or f"{Path(a.ref).name} vs {Path(a.model).name}"
    out = Path(a.out or (Path(a.model).stem + "_overlay.html"))
    out.write_text(render_html(cmp, title, Path(a.ref).name,
                               Path(a.model).name, extra), encoding="utf-8")
    if a.json:
        slim = {k: v for k, v in cmp.items() if not k.startswith("_")}
        Path(a.json).write_text(json.dumps(slim, ensure_ascii=False, indent=1),
                                encoding="utf-8")
    print(f"wrote {out}  pairs={cmp['n_pairs']} rms={cmp['rms_A']} "
          f"only_ref={len(cmp['only_ref'])} only_model={len(cmp['only_model'])} "
          f"element_mismatch={cmp['n_element_mismatch']}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys
    sys.exit(main(sys.argv[1:]))
