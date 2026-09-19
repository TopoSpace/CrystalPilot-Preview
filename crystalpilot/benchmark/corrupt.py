"""Deterministic corruption of a human reference into a realistic bad coarse
model, plus the ground-truth defect ledger for honest post-hoc evaluation.

The corrupted start.res + data copies + synthesis-priors context.json go into
an agent-visible PROJECT directory; defects.json (ground truth) goes into a
SEPARATE truth directory the agent never sees. Original benchmark/E: files
are read-only inputs - corruption only ever touches the new copies.

Preset `sjtu9` (Zr6-TCPB MOF, I4_1/amd, human R1=0.0617):
  - strip riding H, all ADPs -> isotropic U=0.05  (coarse-model realism)
  - D1_element:  ZR01 -> Fe, relabeled FE01       (wrong metal assignment)
  - D2_ligand:   delete C00C + C00G               (breaks the aryl ring)
  - D3_node:     delete O003                      (mu3-O -> incomplete Zr6 node)
  - WGHT reset to 0.1 0

Usage:
    python -X utf8 -m crystalpilot.benchmark.corrupt sjtu9 <project_dir> <truth_dir>
"""
from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

SJTU9_CASE = (REPO / "benchmark" / "data" /
              "重复SJTU-9_SJTU-9_or_post_晶体数据_原始SJTU-9_olex2_temp_sjtu-9")

TCPB_SMILES = ("OC(=O)c1ccc(cc1)-c1cc(-c2ccc(cc2)C(O)=O)c(-c2ccc(cc2)C(O)=O)"
               "cc1-c1ccc(cc1)C(O)=O")


def build_sjtu9(project_dir: Path, truth_dir: Path) -> dict:
    from cctbx.array_family import flex
    from ..io.shelx_model import load_res_model
    from ..io.shelx_writer import ShelxModel, write_res

    ref_res = SJTU9_CASE / "ref_res.res"
    hkl = SJTU9_CASE / "hkl.hkl"
    parsed = load_res_model(ref_res)
    xs = parsed.structure

    truth_sites: dict[str, list[float]] = {
        sc.label: [float(x) for x in sc.site] for sc in xs.scatterers()}

    # 1) strip H
    h_sel = flex.bool([sc.scattering_type.strip().upper() == "H"
                       for sc in xs.scatterers()])
    xs = xs.select(~h_sel)
    # 2) all isotropic, honest coarse-model U
    xs.convert_to_isotropic()
    for sc in xs.scatterers():
        sc.u_iso = 0.05
    # 3) D1: ZR01 -> Fe (relabel like a wrong SHELXT assignment would)
    for sc in xs.scatterers():
        if sc.label == "ZR01":
            sc.scattering_type = "Fe"
            sc.label = "FE01"
    # 4) D2+D3: delete ring carbons + mu3-O
    doomed = {"C00C", "C00G", "O003"}
    keep = flex.bool([sc.label not in doomed for sc in xs.scatterers()])
    xs = xs.select(keep)
    xs.scattering_type_registry(table="it1992")

    project_dir.mkdir(parents=True, exist_ok=True)
    truth_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(hkl, project_dir / "crystal.hkl")
    write_res(ShelxModel(
        xray_structure=xs, wavelength=parsed.wavelength, z=parsed.z,
        title="coarse solution (deliberately corrupted for the MVP test)",
        rem_lines=["coarse model: check element assignments, ligand "
                   "completeness and the metal node before trusting anything"],
        weights=(0.1, 0.0), scale=parsed.scale,
        cell_esd=parsed.cell_esd),   # instrument metadata, not a defect target
        project_dir / "start.res")

    context = {
        "chemistry": {
            "metal_source": "ZrCl4 (Zr(IV))",
            "metals": ["Zr"],
            "ligands": [{
                "name": "1,2,4,5-四(4-羧基苯基)苯 (H4TCPB)",
                "smiles": TCPB_SMILES,
                "note": "四齿羧酸连接体，脱质子后 -4 价"}],
            "expected_metal_node": ("Zr6(μ3-O)4(μ3-OH)4 羧酸簇（可能形成，"
                                    "未确证）"),
            "solvents": ["DMF", "H2O"],
            "synthesis_notes": "溶剂热合成 Zr-MOF；孔道内可能残留无序溶剂",
        },
        "data": {"hkl": "crystal.hkl", "start_model": "start.res"},
    }
    (project_dir / "context.json").write_text(
        json.dumps(context, indent=2, ensure_ascii=False), encoding="utf-8")

    defects = {
        "case": "sjtu9",
        "reference": str(ref_res),
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "reference_metrics": {"r1": 0.0617, "wr2": 0.2048, "goof": 1.062,
                              "n_non_h_atoms": 16, "n_riding_h": 5},
        "global_degradation": ["H stripped", "all ADPs isotropic U=0.05",
                               "WGHT reset"],
        "defects": [
            {"id": "D1_element", "kind": "element_misassignment",
             "atom": "FE01", "wrong_element": "Fe", "true_element": "Zr",
             "site": truth_sites["ZR01"],
             "recovered_if": "a Zr atom within 0.3 A of this site"},
            {"id": "D2_ligand_break", "kind": "ligand_fragmentation",
             "deleted_atoms": ["C00C", "C00G"],
             "sites": [truth_sites["C00C"], truth_sites["C00G"]],
             "recovered_if": "a C atom within 0.5 A of each deleted site"},
            {"id": "D3_node_incomplete", "kind": "metal_node_incomplete",
             "deleted_atoms": ["O003"],
             "sites": [truth_sites["O003"]],
             "recovered_if": "an O atom within 0.5 A of the mu3-O site"},
        ],
    }
    (truth_dir / "defects.json").write_text(
        json.dumps(defects, indent=2, ensure_ascii=False), encoding="utf-8")

    return {"project": str(project_dir), "truth": str(truth_dir),
            "n_atoms_start": xs.scatterers().size(),
            "defects": [d["id"] for d in defects["defects"]]}


def sanity_check(project_dir: Path) -> dict:
    """The corrupted start must be refinable but visibly bad.

    Runs on a throwaway COPY so the agent's project keeps a clean node store.
    """
    import tempfile
    from ..refine.project import RefineProject
    tmp = Path(tempfile.mkdtemp(prefix="cp_sanity_",
                                dir=str(project_dir.parent)))
    for f in ("crystal.hkl", "start.res", "context.json"):
        shutil.copy(project_dir / f, tmp / f)
    try:
        return _sanity_in(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _sanity_in(project_dir: Path) -> dict:
    from ..refine.project import RefineProject
    p = RefineProject(project_dir)
    p.open()
    r = p.invoke_tool("refine", {"mode": "isotropic", "n_cycles": 4})
    if not r.ok:
        raise RuntimeError(f"sanity refine failed: {r.error}")
    r1 = r.summary["r1_strong"]
    if not (0.10 <= r1 <= 0.45):
        raise RuntimeError(f"corrupted start R1={r1} outside the target "
                           "window [0.10, 0.45] - adjust the preset")
    return {"start_r1": r1,
            "adp_suspects": r.summary.get("adp_suspects", []),
            "diff_map_max": r.summary.get("diff_map_max")}


P24CU_CASE = REPO / "benchmark" / "data" / "P2-4_Cu_xia2_xds_x_dummy_sq"


def build_p24cu(project_dir: Path, truth_dir: Path) -> dict:
    """Secondary experiment: NO injected defects - the start model is the
    deterministic engine's own coarse solution (CF + peak interpretation +
    isotropic refine + Fourier growth), i.e. a realistic software coarse
    product. The agent's job is genuine improvement toward the human
    SHELXL-2019/3 reference (R1 0.0576; NOTE: reference reports Flack
    0.413(2) - unmodelled inversion twinning - and PART disorder, both
    outside this round's engine scope; honest partial improvement expected).
    """
    from ..core.events import RunStore
    from ..io.shelx import load_shelx_dataset
    from ..io.shelx_writer import ShelxModel, write_res
    from ..pipeline.session import SolveSession
    from ..pipeline.standard import default_registry
    from ..tools.base import ToolContext, invoke

    hkl = P24CU_CASE / "hkl.hkl"
    ins = P24CU_CASE / "ins.ins"
    ref = P24CU_CASE / "ref_res.res"
    dataset = load_shelx_dataset(hkl, ins_path=ins)
    ses = SolveSession(dataset=dataset)
    ses.set_symmetry(dataset.symmetry_hint)
    project_dir.mkdir(parents=True, exist_ok=True)
    truth_dir.mkdir(parents=True, exist_ok=True)
    reg = default_registry()
    ctx = ToolContext(store=RunStore(truth_dir / "coarse_runs"), session=ses)
    r = invoke(reg, ctx, "solve_charge_flipping", {})
    if not r.ok:
        raise RuntimeError(f"coarse CF failed: {r.error}")
    invoke(reg, ctx, "interpret_peaks", {})
    invoke(reg, ctx, "refine", {"mode": "isotropic", "n_cycles": 6})
    invoke(reg, ctx, "fourier_complete", {"max_rounds": 3})
    r = invoke(reg, ctx, "refine", {"mode": "isotropic", "n_cycles": 6})
    coarse_r1 = r.summary.get("r1_strong")

    shutil.copy(hkl, project_dir / "crystal.hkl")
    write_res(ShelxModel(
        xray_structure=ses.model, wavelength=dataset.wavelength or 0.68914,
        z=8, title="engine coarse solution (charge flipping + isotropic)",
        rem_lines=[f"coarse R1 = {coarse_r1}"],
        weights=(0.1, 0.0)), project_dir / "start.res")
    context = {
        "chemistry": {
            "metal_source": "Cu(NO3)2 (Cu(II))",
            "metals": ["Cu"],
            "ligands": [{
                "name": "P2-4（课题组编号的芳香多羧酸连接体；具体结构式未提供）",
                "smiles": None,
                "note": "羧酸配体，预期通过 COO- 桥连 Cu"}],
            "expected_metal_node": "Cu 羧酸节点（可能为 paddle-wheel 或链状，未确证）",
            "solvents": ["DMF（推测）", "H2O"],
            "synthesis_notes": "溶剂热合成 Cu-MOF；孔道可能有无序溶剂；"
                               "数据在同步辐射波长 0.689 Å 采集",
        },
        "data": {"hkl": "crystal.hkl", "start_model": "start.res"},
    }
    (project_dir / "context.json").write_text(
        json.dumps(context, indent=2, ensure_ascii=False), encoding="utf-8")
    defects = {
        "case": "p24cu",
        "reference": str(ref),
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "reference_metrics": {"r1": 0.0576, "wr2": 0.1729, "goof": 1.063,
                              "n_non_h_atoms": 39, "n_riding_h": 0},
        "global_degradation": [
            f"start = engine coarse solution R1={coarse_r1} "
            "(no deliberate corruption)",
            "reference caveats: Flack 0.413(2) unmodelled twin; PART disorder"],
        "defects": [],
    }
    (truth_dir / "defects.json").write_text(
        json.dumps(defects, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"project": str(project_dir), "truth": str(truth_dir),
            "coarse_r1": coarse_r1,
            "n_atoms_start": ses.model.scatterers().size(), "defects": []}


def build_frames_lcyst(project_dir: Path, truth_dir: Path) -> dict:
    """Raw-to-publication case: NO reduced data at all - the agent must run
    the DIALS frames toolchain itself (import -> ... -> create_start_model)
    before any refinement. Frames = the validated l-cysteine tutorial set
    (Diamond I19, 1700 Pilatus CBF images); stays in place, never copied."""
    frames = REPO / "workdir" / "dials" / "lcyst" / "data"
    ref = (REPO / "benchmark" / "data_frames"
           / "frames_pilatus2m_lcysteine_existing" / "ref"
           / "cod_1575356_lcysteine_100K.cif")
    if not frames.exists():
        raise FileNotFoundError(f"l-cysteine frames not found at {frames}")
    project_dir.mkdir(parents=True, exist_ok=True)
    truth_dir.mkdir(parents=True, exist_ok=True)
    context = {
        "chemistry": {
            "metals": [],
            "ligands": [{"name": "L-cysteine",
                         "smiles": "NC(CS)C(O)=O",
                         "note": "氨基酸小分子晶体，非 MOF"}],
            "solvents": [],
            "synthesis_notes": "L-半胱氨酸单晶（教程级测试晶体）；"
                               "同步辐射 Diamond I19 采集，λ≈0.6889 Å",
        },
        "experiment": {
            "instrument": {"diffractometer": "Diamond I19 (synchrotron)",
                           "source": "synchrotron",
                           "method": "phi scans"},
        },
        # deliberately NO "data" block: the agent must produce it
    }
    (project_dir / "context.json").write_text(
        json.dumps(context, indent=2, ensure_ascii=False), encoding="utf-8")
    defects = {
        "case": "frames_lcyst",
        "reference": str(ref),
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "reference_metrics": {"r1": 0.0138, "wr2": 0.0307, "goof": 1.13,
                              "n_non_h_atoms": 7, "n_riding_h": None},
        "global_degradation": [
            "start = RAW diffraction frames (agent must reduce the data "
            "itself; no injected defects)",
            "reference caveats: COD 1575356 was measured at 100 K "
            "(quantum-crystallography quality, R1 0.0138); the tutorial "
            "dataset's collection temperature is unrecorded - thermal cell "
            "differences are expected"],
        "defects": [],
        "frames_dir": str(frames),
    }
    (truth_dir / "defects.json").write_text(
        json.dumps(defects, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"project": str(project_dir), "truth": str(truth_dir),
            "frames": str(frames), "defects": []}


PRESETS = {"sjtu9": build_sjtu9, "p24cu": build_p24cu,
           "frames_lcyst": build_frames_lcyst}


def main(argv: list[str]) -> int:
    if len(argv) != 3 or argv[0] not in PRESETS:
        print(__doc__)
        return 2
    preset, proj, truth = argv[0], Path(argv[1]), Path(argv[2])
    info = PRESETS[preset](proj, truth)
    print(json.dumps(info, ensure_ascii=False, indent=2))
    check = sanity_check(proj)
    print(json.dumps(check, ensure_ascii=False, indent=2))
    print("CORRUPT-OK")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
