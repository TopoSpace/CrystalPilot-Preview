"""M4 gate: repair the corrupted SJTU-9 start using ONLY the typed tools,
with agent-like decision rules (no ground-truth peeking, no LLM).

If this scripted crystallographer cannot fix the three injected defects and
reach R1 <= 0.08, the LLM agent cannot either - fix the tools first.

Exit 0 = 3/3 defects recovered + R1 gate + emma all-atom match vs reference.

Usage: .venv\\Scripts\\python.exe -X utf8 scripts\\tst_repair_deterministic.py
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

WORK = REPO / "workdir" / "repair_gate"


def log(step: str, payload=None) -> None:
    msg = f"== {step}"
    if payload is not None:
        msg += " " + json.dumps(payload, ensure_ascii=False, default=str)[:600]
    print(msg, flush=True)


def main() -> int:
    shutil.rmtree(WORK, ignore_errors=True)
    from crystalpilot.benchmark.corrupt import build_sjtu9
    proj_dir, truth_dir = WORK / "proj", WORK / "truth"
    build_sjtu9(proj_dir, truth_dir)

    from crystalpilot.refine.project import RefineProject
    p = RefineProject(proj_dir)
    log("open", p.open())

    def tool(name, params=None, expect_ok=True):
        r = p.invoke_tool(name, params or {})
        if expect_ok and not r.ok:
            print(f"TOOL FAILED {name}: {r.error}")
            sys.exit(1)
        return r.summary

    brief = tool("get_project_brief")
    log("brief", {"priors": brief["synthesis_priors"]["metals"],
                  "model": brief["model"]})

    # ---- round 1: baseline + element diagnosis --------------------------
    s = tool("refine", {"mode": "isotropic", "n_cycles": 6})
    log("refine0", {k: s[k] for k in ("r1_strong", "diff_map_max")})
    # agent rule: a strong difference peak sitting ON an atom whose element
    # is lighter than the priors' metal => element misassignment
    prior_metal = brief["synthesis_priors"]["metals"][0]
    suspects = []
    for pk in s["diff_map_peaks"]:
        if pk["height"] > 3.0 and pk["nearest_d"] < 0.5:
            suspects.append(pk["nearest_atom"])
    insp = tool("inspect_model", {"detail": "atoms"})
    for a in insp["atoms"]:
        if a.get("issue") and "too light" in a["issue"]:
            suspects.append(a["label"])
    suspects = [x for x in dict.fromkeys(suspects)]
    log("element_suspects", suspects)
    fixed_elements = []
    for lbl in suspects:
        a = next(x for x in insp["atoms"] if x["label"] == lbl)
        if a["element"] != prior_metal and a["element"] != "O":
            tool("edit_atoms", {"operations": [
                {"action": "reassign", "atoms": [lbl], "element": prior_metal}]})
            fixed_elements.append(f"{lbl}: {a['element']} -> {prior_metal}")
    log("reassigned", fixed_elements)
    if not fixed_elements:
        print("GATE FAIL: element misassignment not detected")
        return 1

    # ---- round 2: rebuild the metal node from the map -------------------
    s = tool("refine", {"mode": "isotropic", "n_cycles": 6})
    log("refine1", {k: s[k] for k in ("r1_strong", "diff_map_max")})
    # agent rule: strong peak 1.9-2.4 A from a metal = missing coordinating O
    node_o_peaks = [i for i, pk in enumerate(s["diff_map_peaks"])
                    if pk["height"] > 1.5 and pk["nearest_atom"]
                    and pk["nearest_atom"][:2].upper() in ("ZR", "FE")
                    and 1.8 <= pk["nearest_d"] <= 2.5]
    if node_o_peaks:
        add = tool("add_atoms_from_difference_map",
                   {"peak_indices": node_o_peaks[:2], "element": "O"})
        log("node_O_added", add["added"])
        s = tool("refine", {"mode": "isotropic", "n_cycles": 6})
        log("refine2", {k: s[k] for k in ("r1_strong", "diff_map_max")})
    else:
        log("node_O_added", "no candidate peaks")

    # ---- round 3: ligand completeness ------------------------------------
    chk = tool("check_ligand", {})
    log("check_ligand", {"n_frag": chk["n_model_fragments"]})
    placed_any = False
    for frag in chk["fragments"]:
        if not frag.get("matches_ligand_subgraph"):
            continue
        missing = frag.get("missing_template_neighbors") or []
        anchors = frag.get("mapped_pairs") or []
        # agent rule: consider only missing C/O NOT explicable by symmetry
        sym_atoms = set(frag.get("sym_bonded_atoms") or [])
        todo = [m for m in missing
                if not all(b[0] in sym_atoms for b in m["bonded_to"])]
        if not todo or len(anchors) < 3:
            continue
        fit = tool("fit_fragment", {
            "anchors": [{"atom": a, "template_index": t}
                        for a, t in anchors[:6]],
            "place": [m["template_index"] for m in todo]})
        log("fit_fragment", {"frag": frag["fragment_atoms"][:4],
                             "added": fit["added"], "refused": fit["refused"]})
        placed_any = placed_any or bool(fit["added"])
    if placed_any:
        s = tool("refine", {"mode": "isotropic", "n_cycles": 6})
        log("refine3", {k: s[k] for k in ("r1_strong", "diff_map_max")})

    # ---- round 4: standard finishing ladder ------------------------------
    tool("solvent_mask", {})
    s = tool("refine", {"mode": "isotropic", "n_cycles": 6})
    log("refine_masked", {"r1": s["r1_strong"]})
    s = tool("refine", {"mode": "anisotropic", "n_cycles": 8})
    log("refine_aniso", {"r1": s["r1_strong"], "suspects": len(s["adp_suspects"])})
    tool("add_hydrogens", {"elements": ["C"]})
    s = tool("refine", {"mode": "anisotropic", "n_cycles": 6})
    tool("optimize_weights", {})
    s = tool("refine", {"mode": "anisotropic", "n_cycles": 8})
    log("refine_final", {"r1": s["r1_strong"], "wr2": s["wr2"], "goof": s["goof"]})
    final_r1 = s["r1_strong"]

    # ---- cross-engine check ----------------------------------------------
    xr = tool("run_shelxl", {"mode": "check", "l_s": 4})
    log("shelxl", {"shelxl_r1": xr["shelxl"]["r1_strong"],
                   "delta": xr["delta_r1"], "agrees": xr["agrees_with_engine"]})

    out = tool("write_outputs", {"output_dir": "CrystalPilot Results/gate",
                                 "summary_note": "deterministic gate run"})
    log("outputs", out["files"])

    # ---- evaluation vs ground truth --------------------------------------
    defects = json.loads((truth_dir / "defects.json").read_text(encoding="utf-8"))
    from crystalpilot.io.shelx_model import load_res_model
    final = load_res_model(proj_dir / "CrystalPilot Results" / "gate" / "final.res")
    xs = final.structure
    uc = xs.unit_cell()
    ops = xs.space_group().all_ops()

    def has_atom_near(site, element, tol):
        import numpy as np
        target = None
        for sc in xs.scatterers():
            if sc.scattering_type.strip().capitalize() != element:
                continue
            for op in ops:
                s2 = op * sc.site
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        for dz in (-1, 0, 1):
                            d = uc.distance(tuple(site),
                                            (s2[0] + dx, s2[1] + dy, s2[2] + dz))
                            if target is None or d < target:
                                target = d
        return target is not None and target <= tol, round(target or 999, 3)

    results = {}
    d1 = defects["defects"][0]
    ok1, d = has_atom_near(d1["site"], "Zr", 0.3)
    results["D1_element"] = {"recovered": ok1, "nearest_Zr_A": d}
    d2 = defects["defects"][1]
    oks = [has_atom_near(s2, "C", 0.5) for s2 in d2["sites"]]
    results["D2_ligand_break"] = {"recovered": all(o for o, _ in oks),
                                  "distances": [d for _, d in oks]}
    d3 = defects["defects"][2]
    ok3, d = has_atom_near(d3["sites"][0], "O", 0.5)
    results["D3_node_incomplete"] = {"recovered": ok3, "nearest_O_A": d}

    from crystalpilot.benchmark.evaluate import evaluate_against_reference
    ref = load_res_model(Path(defects["reference"])).structure
    match = evaluate_against_reference(xs, ref)
    results["emma"] = {"all_match": match.get("all_match_rate"),
                       "precision": match.get("all_precision"),
                       "solved": match.get("solved")}
    results["final_r1"] = final_r1
    results["shelxl_agrees"] = xr["agrees_with_engine"]
    print(json.dumps(results, indent=2, ensure_ascii=False))

    n_fixed = sum(1 for k in ("D1_element", "D2_ligand_break",
                              "D3_node_incomplete") if results[k]["recovered"])
    ok = (n_fixed == 3 and final_r1 <= 0.08
          and (match.get("all_match_rate") or 0) >= 0.95)
    print(f"GATE {'PASS' if ok else 'FAIL'}: {n_fixed}/3 defects, "
          f"R1={final_r1}, emma={match.get('all_match_rate')}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
