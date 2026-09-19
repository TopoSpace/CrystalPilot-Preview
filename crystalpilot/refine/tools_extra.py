"""Refinement-workbench tools: observation, ligand reasoning, fragment
fitting, restraints declaration, node/branch operations, SHELXL cross-engine
runs, and final deliverables.

Honesty design: fit_fragment refuses to place any atom whose difference-map
density is below min_density (default 0.8 e/A^3) - the expected ligand is
never forced into density that does not support it; every refusal is
reported with the measured density.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from ..procutil import NO_WINDOW
from ..tools.base import Tool, ToolContext, ToolResult

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SHELXL = REPO_ROOT / "vendor" / "shelx" / "shelxl.exe"


def register_refine_tools(reg, project) -> None:
    for cls in (GetProjectBrief, InspectModel, InspectMap,
                IntegrateDifferenceDensity, CheckLigand,
                FitFragment, SetRestraints, PreflightRestraints,
                ListNodes, CompareNodes,
                BranchTool, CheckoutTool, RunShelxl, RunShelxt,
                SetWeights, SetZ, SetResolutionLimit, RunOlex2,
                RunCheckcif,
                SubmitIucrCheckcif, WriteOutputs, FinalizeDelivery):
        reg.register(cls(project))
    # round-3 WP5: whole-fragment pose search + group-level acceptance
    from .tools_pose import register_pose_tools
    register_pose_tools(reg, project)
    # round-3 WP7: the investigation record (goal / tiers / ruled out / open)
    from .investigation import register_investigation_tools
    register_investigation_tools(reg, project)
    from .tools_parameters import register_parameter_tools
    register_parameter_tools(reg, project)


from .toolbase import _ProjectTool  # noqa: E402,F401 (re-export)


def _resolve_smiles(project, params: dict) -> str | None:
    smi = params.get("smiles")
    if smi:
        return str(smi)
    chem = project.context.get("chemistry") or {}
    for lig in chem.get("ligands") or []:
        if isinstance(lig, dict) and lig.get("smiles"):
            return lig["smiles"]
    return None


def _same_group(a: str | None, b: str | None) -> bool:
    """Same space group AND setting, whatever the symbol spelling
    ('R -3 m :H' vs 'R -3 m', H-M vs Hall)."""
    if not a or not b:
        return False
    try:
        from cctbx import sgtbx
        return (sgtbx.space_group_info(str(a)).type().hall_symbol()
                == sgtbx.space_group_info(str(b)).type().hall_symbol())
    except Exception:  # noqa: BLE001 - unparsable symbol: literal compare
        return str(a).replace(" ", "") == str(b).replace(" ", "")


def _start_model_group(project) -> tuple[str | None, str | None]:
    """(space group from the start model's LATT/SYMM, its file name)."""
    smp = getattr(project, "start_model_path", None)
    if not smp or not Path(smp).exists():
        return None, None
    try:
        from cctbx import sgtbx

        from ..io.shelx import parse_ins_metadata, space_group_from_latt_symm
        meta = parse_ins_metadata(Path(smp))
        if meta.get("latt") is None:
            return None, Path(smp).name
        g = space_group_from_latt_symm(meta["latt"], meta.get("symm") or [])
        return str(sgtbx.space_group_info(group=g)), Path(smp).name
    except Exception:  # noqa: BLE001 - a broken start model is not brief's job
        return None, Path(smp).name


def symmetry_brief(project, ses, listing: dict | None = None) -> dict[str, Any]:
    """The space group the project DECLARES right now (what merging,
    solvers and run_shelxt use), where it came from, and whether anything
    has confirmed it.

    pa1 hex-l2-r2: get_project_brief printed model.space_group_info() -
    'P 6/m m m' after the agent had declared R-3m on the atomless session,
    'R -3 m' after it had declared P-3m1 (the model object keeps its old
    symmetry; only ses.symmetry follows a declaration). cage-l2-r1 /
    cu-l3-r2 saw 'P 1 21/c 1' / 'P 1' with nothing saying those were the
    vendor ins's guess and a LATT placeholder. Sources, in order of
    trust: the context.json `symmetry` record (ingest / a declaring
    tool), then the start model's LATT/SYMM (change_space_group rewrites
    it on declaration), then 'in-session only'."""
    model = getattr(ses, "model", None)
    model_sg = str(model.space_group_info()) if model is not None else None
    sym = getattr(ses, "symmetry", None)
    declared = str(sym.space_group_info()) if sym is not None else model_sg
    ctx = project.context if isinstance(getattr(project, "context", None),
                                        dict) else {}
    ctx_sym = ctx.get("symmetry") or {}
    recorded = ctx_sym.get("space_group")
    start_sg, start_file = _start_model_group(project)
    out: dict[str, Any] = {"declared_space_group": declared}
    confirmed = False
    if recorded and _same_group(recorded, declared):
        source = ctx_sym.get("source") or "context.json symmetry record"
        confirmed = bool(ctx_sym.get("confirmed"))
    elif start_sg and _same_group(start_sg, declared):
        if recorded:
            source = (f"declared after ingest - change_space_group rewrote "
                      f"{start_file} LATT/SYMM (ingest had recorded "
                      f"{recorded}: {ctx_sym.get('source')}); an agent "
                      f"decision, keep its evidence in the report")
        else:
            source = (f"start model {start_file} LATT/SYMM (provenance not "
                      f"recorded - ingested before symmetry records "
                      f"existed; treat as unverified)")
    else:
        fallback = start_sg or model_sg or "?"
        source = (f"declared in this session only (change_space_group) - "
                  f"neither the start model nor context.json carries it "
                  f"yet; a restart would fall back to {fallback}")
    out["source"] = source
    if ctx_sym.get("ins_guess"):
        out["ins_guess"] = ctx_sym["ins_guess"]
    if model_sg and not _same_group(model_sg, declared):
        out["model_space_group"] = model_sg
        out["stale_model_symmetry"] = (
            f"the model object still carries {model_sg} (atomless "
            f"placeholder / pre-declaration state); data merging, solvers "
            f"and run_shelxt use the declared group above")
    n_atoms = int(model.scatterers().size()) if model is not None else 0
    active = (listing or {}).get("active_node")
    r1 = None
    for row in (listing or {}).get("nodes") or []:
        if row.get("id") == active and row.get("r1") is not None:
            r1 = row["r1"]
    if confirmed:
        status = f"confirmed ({source})"
    elif (n_atoms and r1 is not None and model_sg
          and _same_group(model_sg, declared)):
        status = (f"working confirmation only: a {n_atoms}-atom model "
                  f"refines in this group (R1 {r1}) - not a symmetry proof; "
                  f"check_symmetry / screen_space_groups evidence belongs "
                  f"in the report")
    else:
        status = ("UNCONFIRMED - a guess or a declaration, not a "
                  "verification: screen_space_groups + solution trials "
                  "decide, change_space_group(space_group=...) declares")
    out["confirmed"] = confirmed
    out["status"] = status
    return out


def experiment_line(project, ses=None) -> str:
    """One line: 'experiment: <wavelength/temperature/instrument summary>'
    when metadata exist, else the honest 'not set' with the hint that a
    context.json is present for set_experiment to import from. pa1: 25/28
    runs found out only at write_outputs that the CIF would carry '?'."""
    exp = project.experiment() if hasattr(project, "experiment") else {}
    exp = exp or {}
    ds = getattr(ses, "dataset", None) if ses is not None else None
    wl = getattr(ds, "wavelength", None)
    inst = exp.get("instrument") or {}
    wl = wl or inst.get("wavelength_A")
    has_meta = any(exp.get(k) for k in ("temperature_K", "instrument",
                                        "absorption", "crystal",
                                        "cell_measurement"))
    if not has_meta:
        ctx_present = (Path(project.dir) / "context.json").exists()
        line = ("experiment: not set (context.json present: set_experiment "
                "imports it)" if ctx_present else
                "experiment: not set (no context.json) - set_experiment "
                "records what the vendor files did not carry")
        if wl:
            line += f"; wavelength {wl} A from the data files"
        return line
    parts: list[str] = []
    if wl:
        parts.append(f"lambda {wl} A")
    if exp.get("temperature_K"):
        parts.append(f"T {exp['temperature_K']} K")
    dev = ", ".join(str(inst[k]) for k in ("source", "diffractometer")
                    if inst.get(k))
    if dev:
        parts.append(dev)
    ab = exp.get("absorption") or {}
    if ab.get("type"):
        rng = (f" T {ab['t_min']}-{ab['t_max']}"
               if ab.get("t_min") is not None and ab.get("t_max") is not None
               else "")
        parts.append(f"absorption {ab['type']}{rng}")
    cr = exp.get("crystal") or {}
    if cr.get("size_mm"):
        parts.append("size " + " x ".join(str(x) for x in cr["size_mm"])
                     + " mm")
    if cr.get("colour"):
        parts.append(str(cr["colour"]))
    missing = [k for k in ("temperature_K", "absorption", "crystal")
               if not exp.get(k)]
    if missing:
        parts.append("missing: " + ", ".join(missing))
    return "experiment: " + ", ".join(parts)


def absorption_edge_block(project, ses=None) -> dict[str, Any]:
    """The standing X-ray absorption-edge statement for this project's
    wavelength and declared element list (T1.7a).

    ka1: the fact that lambda sat ON the Zr K edge - f'(Zr) = -9 e, a Zr
    site scattering like ~31 e - only reached the agent when it happened
    to call audit_heavy_sites, 12.8 / 18.6 minutes in and after R-vs-Z
    ladders that fact voids. The brief is where a session starts, so the
    same physics belongs here, standing: the flag when it fires, and an
    explicit 'not applicable / no edge nearby' when it does not. Silence
    would be read as 'no edge'.

    One implementation, shared with audit_heavy_sites
    (refine/tools_heavysites.py); a failure here degrades to a visible
    'unavailable' rather than taking the whole brief down."""
    from .tools_heavysites import project_absorption_edge_brief
    try:
        return project_absorption_edge_brief(project, ses)
    except Exception as e:  # noqa: BLE001 - a side note must not fail a brief
        return {"status": "unavailable",
                "error": f"{type(e).__name__}: {e}",
                "statement": ("the absorption-edge check could not run - "
                              "this is not a 'no edge' verdict; "
                              "audit_heavy_sites reports the same physics")}


# ==========================================================================
class GetProjectBrief(_ProjectTool):
    name = "get_project_brief"
    description = (
        "The starting point of every session: synthesis priors (metal, ligands "
        "with SMILES, solvents, notes) supplied by the chemist, dataset "
        "statistics, current model digest, and the active node/branch. Priors "
        "are hypotheses to test against the data - never force them into "
        "density that does not support them. Also carries a standing "
        "`absorption_edge` note: whether any declared element scatters "
        "anomalously at this wavelength (f' shifts its apparent electron "
        "count away from Z, so element_scan / e-count arguments must use "
        "z_eff = Z + f'), or the explicit statement that none does / that "
        "the check has no wavelength or no element list yet.")
    params_schema = {"type": "object", "properties": {}}

    def run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        p = self.project
        ses = ctx.session or p.session
        chem = p.context.get("chemistry") or {}
        if ses is None:
            # raw-frames project: no reduced data yet
            frames_state = {}
            fs = p.dir / ".crystalpilot" / "frames" / "state.json"
            if fs.exists():
                try:
                    frames_state = json.loads(fs.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    pass
            return ToolResult(ok=True, summary={
                "state": "awaiting_data",
                "synthesis_priors": chem,
                "structure_class": declared_structure_class(p.dir),
                "experiment": (p.experiment()
                               if hasattr(p, "experiment") else {}),
                "experiment_line": experiment_line(p),
                "absorption_edge": absorption_edge_block(p, None),
                "frames_pipeline": frames_state or {
                    "note": "not started - begin with import_frames"},
                "note": ("no crystal.hkl / start model yet. Process the raw "
                         "diffraction frames: import_frames -> find_spots -> "
                         "index_frames -> integrate_frames -> "
                         "scale_and_export -> create_start_model; each stage "
                         "reports its statistics for you to judge."),
            })
        listing = p.nodes.list_nodes(limit=5)
        model = ses.model
        counts: dict[str, int] = {}
        for sc in model.scatterers():
            el = sc.scattering_type.strip().capitalize()
            counts[el] = counts.get(el, 0) + 1
        # if the data came from the staged frames chain, surface the
        # reduction health - especially unindexed-spot fraction, the
        # cheapest tell of a second twin domain / satellite lattice
        frames_note: dict[str, Any] = {}
        fs = p.dir / ".crystalpilot" / "frames" / "state.json"
        if fs.exists():
            try:
                st = json.loads(fs.read_text(encoding="utf-8"))
                stages = st.get("stages") or {}
                idx = stages.get("index_frames") or {}
                spots = stages.get("find_spots") or {}
                if idx:
                    frames_note = {
                        "n_strong_spots": spots.get("n_strong_spots"),
                        "pct_indexed": idx.get("pct_indexed"),
                        "n_lattices": idx.get("n_lattices"),
                    }
                    pct = idx.get("pct_indexed")
                    if isinstance(pct, (int, float)) and pct < 95:
                        frames_note["warning"] = (
                            f"only {pct}% of strong spots indexed on "
                            f"{idx.get('n_lattices', 1)} lattice(s) - the "
                            f"unindexed rest may be a second twin domain or "
                            f"satellite lattice. If R/wR2 stall or absence "
                            f"violations cluster (audit_reflection_data), "
                            f"consider re-running index_frames with "
                            f"max_lattices=2 before trusting single-domain "
                            f"conclusions.")
            except (OSError, json.JSONDecodeError):
                pass
        # merge numbers: the session's own record follows every
        # change_space_group declaration; project.merge_stats is frozen at
        # build time (pa1 hex-l2-r2: n_unique/R_int of the ingest-time group
        # shown after two re-declarations)
        merge = (getattr(ses, "merge_info", None)
                 or getattr(p, "merge_stats", None) or {})
        symmetry = symmetry_brief(p, ses, listing)
        return ToolResult(ok=True, summary={
            **({"frames_reduction": frames_note} if frames_note else {}),
            "synthesis_priors": chem,
            "structure_class": declared_structure_class(p.dir),
            "experiment": (p.experiment() if hasattr(p, "experiment") else {})
            or {"note": "no experimental metadata (temperature/crystal size/"
                        "absorption/instrument) - the publication CIF will "
                        "carry '?' there; ask the user if available"},
            "experiment_line": experiment_line(p, ses),
            # standing physics note, not a per-call diagnosis: which
            # declared element (if any) scatters anomalously at THIS
            # wavelength, or the explicit statement that none does /
            # that the check cannot run yet
            "absorption_edge": absorption_edge_block(p, ses),
            "data": {
                "hkl": p.hkl_path.name,
                "wavelength_A": ses.dataset.wavelength,
                **merge,
                # start.ins SFAC/UNIT as ingest_vendor_data saw it, restored
                # fresh from context.json on every checkout (project.py
                # _build_session) - a disclosed guess, independent of
                # whether the engine's own composition_from_meta trusted
                # UNIT as real evidence (ka1-org: it did not, on a UNIT
                # 1 1 1 1 placeholder, and the brief used to say nothing
                # about SFAC C H N O having been declared at all)
                **({"elements_declared_in_ins": ses.flags["ins_elements"]}
                   if ses.flags.get("ins_elements") else {}),
            },
            "symmetry": symmetry,
            "model": {"n_atoms": model.scatterers().size(),
                      "element_counts": counts,
                      # the DECLARED group is authoritative; the model's own
                      # symmetry is listed under symmetry.model_space_group
                      # when it lags behind a declaration
                      "space_group": symmetry["declared_space_group"]},
            "active_node": listing["active_node"],
            "active_branch": listing["active_branch"],
            "branches": listing["branches"],
            "workflow": ("observe (inspect_model / inspect_map / check_ligand) "
                         "-> hypothesize -> smallest chemical edit -> refine -> "
                         "validate -> compare/branch -> iterate; every mutation "
                         "auto-commits a node you can checkout/rollback"),
        })


def declared_structure_class(project_dir) -> dict:
    """The owner's declaration of what the crystal IS (workbench setting
    `structure_class`, round-2 R6): small_molecule / macrocycle / cage /
    framework / salt_cocrystal, or None when nobody has said. Read live
    from .crystalpilot-workbench.json (the app-server owns that file) so a
    change in the UI reaches the next tool call without a rebuild."""
    from pathlib import Path
    f = Path(project_dir) / ".crystalpilot-workbench.json"
    cls = None
    if f.exists():
        try:
            v = (json.loads(f.read_text(encoding="utf-8"))
                 .get("settings", {}).get("structure_class"))
            cls = str(v).strip().lower() if v else None
        except (OSError, json.JSONDecodeError, AttributeError):
            cls = None
    if cls is None:
        note = ("not declared by the user - do not assume; the analysis "
                "product still measures everything (interactions, pores, "
                "topology) and the reading tells which blocks are "
                "class-specific")
    else:
        note = ("declared by the user in the workbench; treat it as their "
                "prior about the chemistry (a declared 'framework' whose "
                "topology block finds only 0-D fragments is a finding worth "
                "reporting, not a reason to force the model)")
    return {"declared": cls, "note": note}


# ==========================================================================
class InspectModel(_ProjectTool):
    name = "inspect_model"
    description = (
        "Crystallographer's view of the current model: per-atom table (element, "
        "site, occupancy/sof, U_eq, aniso, suspicion flags), metal coordination "
        "environments (CN, distances, largest angles, tau4/tau5), organic "
        "fragments with ring census, dangling carbons (broken-ring symptom), "
        "symmetry-bonded atoms, and isolated atoms, plus a formula/Z audit "
        "(what _chemical_formula_sum the CIF will print; fractional counts "
        "mean Z is wrong or partial occupancies are present) and, when the "
        "model carries PART/FVAR disorder, one row per group with the "
        "refined occupancy AND ITS S.U., the acceptance verdict "
        "(supported / inconclusive / revoke / pending) and the undo call. "
        "detail='summary' is compact; "
        "'atoms' adds the full atom table; 'full' adds bonds per atom.")
    params_schema = {
        "type": "object",
        "properties": {
            "detail": {"type": "string", "enum": ["summary", "atoms", "full"],
                       "default": "summary"},
        },
    }

    def run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        from .inspect import inspect_model
        ses = ctx.session
        if ses.model is None:
            return ToolResult.failure("no model loaded")
        out = inspect_model(ses.model, detail=params.get("detail", "summary"),
                            flags=ses.flags)
        try:  # formula / Z bookkeeping (what the CIF will print)
            from ..chem.formula import formula_audit
            out["formula"] = formula_audit(
                ses.model, z=getattr(self.project, "_z", None))
        except Exception:  # noqa: BLE001 - advisory
            pass
        return ToolResult(ok=True, summary=out)


# ==========================================================================
class InspectMap(_ProjectTool):
    name = "inspect_map"
    description = (
        "Difference (Fo-Fc) electron density: extremes in e/A^3 and positive "
        "peaks with height, position and nearest atom. Strong peaks (>~2) far "
        "from atoms = missing atoms; strong peaks ON an atom = element too "
        "light; deep holes on an atom = element too heavy / occupancy too "
        "high. Includes the stored solvent mask automatically. Refreshes the "
        "session peak table: each peak's 'i' is the peak_indices value for "
        "add_atoms_from_difference_map; the table is saved with the active "
        "node (peaks.json) and restored by checkout/branch. node=<id> reads "
        "the table stored with that node instead of recomputing (no "
        "session change).")
    params_schema = {
        "type": "object",
        "properties": {
            "n_peaks": {"type": "integer", "default": 15},
            "min_height": {"type": "number", "default": 0.3,
                           "description": "drop peaks below this height (e/A^3)"},
            "node": {"type": ["string", "null"], "default": None,
                     "description": "read the peak table stored with this "
                                    "node/branch (written by refine, "
                                    "run_shelxl mode='adopt' and inspect_map) "
                                    "instead of computing the map on the "
                                    "live model; nothing in the session "
                                    "changes"},
        },
    }

    def run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        from ..tools.refinement_tools import _difference_map_analysis
        if params.get("node"):
            return self._stored_table(str(params["node"]), params)
        ses = ctx.session
        if ses.model is None:
            return ToolResult.failure("no model loaded")
        if ses.model.scatterers().size() == 0:
            # was a bare AssertionError from the map code (pa1 cage)
            return ToolResult.failure(
                "the model has no atoms, so there is no Fc and no "
                "difference map to inspect. Solve first (run_shelxt / the "
                "superflip solver); to look at the data itself use "
                "audit_reflection_data or screen_space_groups")
        diff = _difference_map_analysis(
            ses, ses.model, n_peaks=int(params.get("n_peaks", 15)),
            f_mask=ses.flags.get("f_mask"))
        if "error" in diff:
            return ToolResult.failure(diff["error"])
        min_h = float(params.get("min_height", 0.3))
        # single source of truth: refresh the stored peak table so
        # add_atoms_from_difference_map can reach every peak shown here
        # (round-10 #14b: a 0.58 e/A^3 H peak was visible in inspect_map
        # but absent from the refine-time top-N table -> added=[])
        ses.flags["diff_map_peaks"] = diff["peaks"]
        for i, p in enumerate(diff["peaks"]):
            p["i"] = i          # index into the stored table (peak_indices)
        peaks = [p for p in diff["peaks"] if p["height"] >= min_h]
        from .tools_analysis import peak_environment
        for p in peaks:
            p.update(peak_environment(ses.model, p["site"], p["height"]))
        active = None
        if getattr(self.project, "nodes", None) is not None:
            active = self.project.nodes.state().get("active_node")
        return ToolResult(ok=True, summary={
            "diff_map_max": diff["max"], "diff_map_min": diff["min"],
            "map_provenance": diff.get("map_provenance"),
            "solvent_mask_included": ses.flags.get("f_mask") is not None,
            "peaks": peaks,
            "n_peaks_shown": len(peaks),
            "n_peaks_in_table": len(diff["peaks"]),
            # pa1: agents lost this table on the next branch and were told
            # to refine; it now rides with the node (invoke_tool saves it
            # right after this call and adds 'peak_table_saved')
            "peak_table": {"computed_on": active,
                           "note": "peak_indices refer to this table; it "
                                   "is saved with the node (peaks.json) and "
                                   "restored by checkout/branch"},
        })

    def _stored_table(self, ref: str, params: dict[str, Any]) -> ToolResult:
        """inspect_map(node=...): the table saved with a node, read from
        disk - no map computed, no session change."""
        nodes = self.project.nodes
        try:
            node = nodes.resolve(ref)
        except KeyError as e:
            return ToolResult.failure(str(e))
        dm = (nodes.load_peaks(node) or {}).get("diff_map") or {}
        from ..tools.twin_maps import MAP_ALGORITHM_VERSION
        meta = nodes.node_meta(node)
        if ((meta.get("twin") or int(meta.get("hklf") or 4) == 5)
                and dm.get("source") != "run_shelxl"
                and (dm.get("map_provenance") or {}).get("algorithm_version") != MAP_ALGORITHM_VERSION):
            return ToolResult.failure(
                "This legacy peak table did not record twin handling; checkout "
                "the node and run inspect_map. Its density cannot establish absence.")
        if not dm.get("peaks"):
            return ToolResult.failure(
                f"node {node} has no stored difference-map peak table "
                f"(peaks.json is written by refine, run_shelxl mode='adopt' "
                f"and inspect_map for the node active at that time). "
                f"checkout {node} and run inspect_map to compute one.")
        min_h = float(params.get("min_height", 0.3))
        n = int(params.get("n_peaks", 15))
        table = [{**p, "i": i} for i, p in enumerate(dm["peaks"])]
        peaks = [p for p in table if p["height"] >= min_h][:n]
        return ToolResult(ok=True, summary={
            "source": "stored", "node": node,
            "computed_on": dm.get("computed_on"),
            "computed_by": dm.get("source"),
            "map_provenance": dm.get("map_provenance"),
            "file": f".crystalpilot/refine/nodes/{node}/{nodes.PEAKS_FILE}",
            "diff_map_max": dm.get("max"), "diff_map_min": dm.get("min"),
            "peaks": peaks,
            "n_peaks_shown": len(peaks),
            "n_peaks_in_table": len(table),
            "note": "read from disk; the live session is unchanged. "
                    "peak_indices for add_atoms_from_difference_map refer "
                    "to the SESSION's table, so checkout this node first "
                    "if you want to add atoms from it",
        })


# ==========================================================================
class IntegrateDifferenceDensity(_ProjectTool):
    name = "integrate_difference_density"
    description = (
        "Integrate the Fo-Fc residual over a region (union of spheres "
        "around given atoms, or one fractional site) and report POSITIVE "
        "and NEGATIVE electron counts separately - the electron-count test "
        "of the guest-evidence rule (test 1 of skill "
        "mof-guest-evidence-rule): integrated electrons must be on the "
        "same order as the candidate guest's expected electrons; a shortfall "
        "means insufficient support in this map, not proof of absence "
        "(especially for model-dependent detwinning). With 'labels' the "
        "atoms are OMITTED from Fc first (omit-map style) so a modeled "
        "guest's own density is measured against what the model claims; "
        "with 'site_frac' the as-is residual at an empty location is "
        "measured (pre-build test). candidate_formula ('C3H7NO') adds the "
        "expected electron count; element='Br' adds an occupancy -> "
        "electrons table (a 0.125-occupancy heavy atom is a few electrons, "
        "never the full-occupancy count). Solvent mask: with a stored mask "
        "the residual inside the masked void is suppressed by construction, "
        "so mask='auto' (default) drops the mask from Fc when a site lies "
        "inside the void and says so in mask_handling; 'off' / 'on' force "
        "it. Read-only.")
    params_schema = {
        "type": "object",
        "properties": {
            "labels": {"type": "array", "items": {"type": "string"},
                       "description": "atom labels defining the region "
                                      "(omitted from Fc unless omit=false)"},
            "site_frac": {"type": "array", "items": {"type": "number"},
                          "minItems": 3, "maxItems": 3,
                          "description": "fractional centre of an extra "
                                         "integration sphere"},
            "radius_A": {"type": "number", "default": 2.0,
                         "minimum": 0.5, "maximum": 6.0,
                         "description": "integration sphere radius in "
                                        "Angstroms (0.5-6)"},
            "candidate_formula": {
                "type": "string",
                "description": "guest formula, e.g. 'C3H7NO' or "
                               "'C3 H7 N O' - adds expected_electrons"},
            "element": {"type": "string",
                        "description": "candidate element at the site, e.g. "
                                       "'Br' - adds expected_electrons_at_"
                                       "occupancy (occupancy x Z ladder)"},
            "omit": {"type": "boolean", "default": True},
            "mask": {"type": "string", "enum": ["auto", "off", "on"],
                     "default": "auto",
                     "description": "'auto': switch the stored solvent mask "
                                    "off when a site lies inside the masked "
                                    "void (the pre-mask map is the only one "
                                    "that can show a guest there); 'off' / "
                                    "'on' force it"},
        },
    }

    def run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        from cctbx import maptbx
        from cctbx.array_family import flex
        from cctbx.eltbx import tiny_pse

        from ..tools.refinement_tools import difference_map_real
        from .tools_batch import (_Refusal, bracketing_elements,
                                  count_is_low_biased, electron_bracket_note,
                                  latest_r1, low_count_note)
        from .tools_probe import (expected_electrons_table, occupancy_note,
                                  resolve_mask_mode, sphere_stats)
        ses = ctx.session
        if ses.model is None:
            return ToolResult.failure("no model loaded")
        labels = [str(x) for x in (params.get("labels") or [])]
        site = params.get("site_frac")
        if not labels and not site:
            return ToolResult.failure("give labels and/or site_frac")
        radius = float(params.get("radius_A") or 2.0)
        if not 0.5 <= radius <= 6.0:
            return ToolResult.failure("radius_A must be 0.5-6.0")
        element = params.get("element")
        if element:
            element = re.match(r"[A-Za-z]{1,2}", str(element).strip())
            element = element.group(0).capitalize() if element else None
            if expected_electrons_table(element or "") is None:
                return ToolResult.failure(
                    f"element {params.get('element')!r} is not an element "
                    f"symbol")

        xs = ses.model
        uc = xs.unit_cell()
        scs = list(xs.scatterers())
        lset = {la.upper() for la in labels}
        idx = [i for i, sc in enumerate(scs) if sc.label.upper() in lset]
        found = {scs[i].label.upper() for i in idx}
        if labels and found != lset:
            return ToolResult.failure(
                f"labels not in model: {sorted(lset - found)}")

        sites_frac = [tuple(float(c) for c in scs[i].site) for i in idx]
        site_names = [scs[i].label for i in idx]
        if site:
            sites_frac.append(tuple(float(c) for c in site))
            site_names.append("site_frac")
        sites_cart = [uc.orthogonalize(s) for s in sites_frac]
        # the mask decision is made on the FULL model: a modelled atom's own
        # site is never in the void (the mask was built around it), an
        # empty site_frac may be
        try:
            use_mask, mask_handling = resolve_mask_mode(
                ses, xs, sites_frac, params.get("mask"))
        except _Refusal as e:
            return ToolResult.failure(str(e))

        # what the model itself claims sits in the region (occupancy-
        # weighted electrons of the omitted atoms) - the direct yardstick
        def _z(sym: str) -> float:
            try:
                return float(tiny_pse.table(
                    re.match(r"[A-Za-z]{1,2}", sym.strip()).group(0)
                    .capitalize()).atomic_number())
            except Exception:  # noqa: BLE001
                return 0.0
        modeled_e = sum(_z(scs[i].scattering_type) * float(scs[i].occupancy)
                        for i in idx)

        omit = bool(params.get("omit", True)) and bool(idx)
        model = xs
        if omit:
            keep = flex.bool(len(scs), True)
            for i in idx:
                keep[i] = False
            model = xs.select(keep)
        f_mask = ses.flags.get("f_mask") if use_mask else None
        try:
            fft_map, real, k = difference_map_real(
                ses, model, f_mask=f_mask)
        except ValueError as e:
            return ToolResult.failure(str(e))

        grid_sel = maptbx.grid_indices_around_sites(
            unit_cell=uc, fft_n_real=real.focus(), fft_m_real=real.all(),
            sites_cart=flex.vec3_double(sites_cart),
            site_radii=flex.double(len(sites_cart), radius))
        vals = real.select(grid_sel)
        if vals.size() == 0:
            return ToolResult.failure("empty integration region")
        vpp = uc.volume() / real.size()          # A^3 per grid point
        e_pos = float(flex.sum(vals.select(vals > 0))) * vpp
        e_neg = float(flex.sum(vals.select(vals < 0))) * vpp

        out: dict[str, Any] = {
            "map_provenance": getattr(fft_map, "crystalpilot_map_provenance", None),
            "region": {"n_atoms": len(idx),
                       **({"site_frac": [round(float(c), 4) for c in site]}
                          if site else {}),
                       "radius_A": radius,
                       "n_grid_points": int(vals.size()),
                       "volume_A3": round(vals.size() * vpp, 1)},
            "omitted_from_fc": omit,
            "electrons_positive": round(e_pos, 1),
            "electrons_negative": round(e_neg, 1),
            "electrons_net": round(e_pos + e_neg, 1),
            "map_max_in_region": round(float(flex.max(vals)), 2),
            "map_min_in_region": round(float(flex.min(vals)), 2),
            "solvent_mask_included": f_mask is not None,
            "mask_handling": mask_handling,
        }
        # per-site spheres from the SAME map (probe_site reads its
        # omit_map_electrons with this function - identical arithmetic)
        per_site = sphere_stats(real, uc, sites_frac, radius)
        void_tests = mask_handling.get("void_test") or []
        rows = []
        for name, s, st in zip(site_names, sites_frac, per_site):
            row = {"site": name, "site_frac": [round(c, 4) for c in s], **st}
            if void_tests:
                vt = void_tests[len(rows)]
                row["in_masked_void"] = vt["inside"]
                row["nearest_atom"] = vt["nearest_atom"]
                row["nearest_d_A"] = vt["nearest_d_A"]
            if element:
                row["expected_electrons_at_occupancy"] = \
                    expected_electrons_table(element)
            rows.append(row)
        out["sites"] = rows
        if element:
            out["element"] = element
            out["expected_electrons_at_occupancy"] = \
                expected_electrons_table(element)
        out["occupancy_note"] = occupancy_note(element)
        if omit:
            out["modeled_electrons_omitted"] = round(modeled_e, 1)
        cf = params.get("candidate_formula")
        if cf:
            expected = 0.0
            for el, n in re.findall(r"([A-Z][a-z]?)\s*(\d*\.?\d*)",
                                    str(cf).replace(",", " ")):
                expected += _z(el) * (float(n) if n else 1.0)
            out["candidate_formula"] = str(cf)
            out["expected_electrons"] = round(expected, 1)
            if expected > 0:
                out["positive_over_expected"] = round(e_pos / expected, 3)

        notes = ["judge BOTH halves: |negative| comparable to positive = "
                 "structure-free noise, not a guest (skill "
                 "mof-guest-evidence-rule)"]
        if f_mask is not None:
            notes.append(
                "solvent mask is inside Fc: masked void density does NOT "
                "appear in this residual - if the region overlaps the mask "
                "the integral understates the true content (mask='off' "
                "for an absolute count)")
        elif ses.flags.get("f_mask") is not None:
            notes.append(
                "the stored solvent mask was left OUT of Fc for this "
                "integral (see mask_handling): the residual holds everything "
                "the mask absorbs - solvent AND any guest - so read it "
                "against the occupancy table, not against the mask's "
                "electron count")
        notes.append(out["occupancy_note"])
        if omit:
            notes.append(
                "omit-map approximation: scale/phases come from the "
                "partial model; counts within ~10-20% are normal")
        # how far the count can be trusted on THIS model, and - for a single
        # region - the elements its electron count brackets
        r1_now = latest_r1(ses)
        calibration = low_count_note(r1_now)
        if calibration:
            out["electron_count_calibration"] = calibration
            notes.append(calibration)
        if len(sites_frac) == 1:
            low_biased = count_is_low_biased(r1_now)
            proposed = bracketing_elements(e_pos, low_biased=low_biased)
            if proposed:
                out["candidates_bracketing_the_count"] = proposed
                out["bracket_note"] = electron_bracket_note(
                    e_pos, proposed, low_biased)
        out["notes"] = notes
        return ToolResult(ok=True, summary=out)


# ==========================================================================
class CheckLigand(_ProjectTool):
    name = "check_ligand"
    description = (
        "Compare the expected ligand (SMILES) against the organic fragments of "
        "the current model via subgraph matching. For each fragment: does it "
        "match a piece of the ligand, which model atoms map to which template "
        "indices (usable as fit_fragment anchors), and which template "
        "neighbors are MISSING from the model (concrete repair hypotheses). "
        "Fragments bonded to symmetry copies carry a caveat - the 'missing' "
        "part may exist crystallographically.")
    params_schema = {
        "type": "object",
        "properties": {
            "smiles": {"type": "string",
                       "description": "ligand SMILES; defaults to the first "
                                      "ligand in the synthesis priors"},
            "min_fragment_atoms": {"type": "integer", "default": 3},
        },
    }

    def run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        from .inspect import organic_fragments
        from .ligand import LigandError, assess_fragment, ligand_graph
        ses = ctx.session
        smi = _resolve_smiles(self.project, params)
        if not smi:
            return ToolResult.failure(
                "no SMILES given and no ligand with smiles in synthesis priors")
        try:
            lig = ligand_graph(smi)
        except LigandError as e:
            return ToolResult.failure(str(e))
        frags = organic_fragments(ses.model)
        labels = [sc.label for sc in ses.model.scatterers()]
        min_n = int(params.get("min_fragment_atoms", 3))
        assessments = []
        for f in frags:
            if f["n_atoms"] < min_n:
                assessments.append({"fragment_atoms": f["atoms"],
                                    "n_atoms": f["n_atoms"],
                                    "skipped": "below min_fragment_atoms"})
                continue
            assessments.append(assess_fragment(f, lig, labels))
        pub = {k: v for k, v in lig.items()
               if k in ("formula", "n_heavy", "element_counts", "ring_sizes",
                        "n_aromatic_rings", "n_carboxylate")}
        return ToolResult(ok=True, summary={
            "ligand": pub,
            "n_model_fragments": len(frags),
            "fragments": assessments,
            "note": ("template_index refers to RDKit canonical atom order of "
                     "this SMILES; pass mapped_pairs as fit_fragment anchors"),
        })


# ==========================================================================
class FitFragment(_ProjectTool):
    name = "fit_fragment"
    description = (
        "Rigid-body fit of the ligand's ideal 3D geometry onto >=3 anchor "
        "atoms of the model (anchors from check_ligand's mapped_pairs), then "
        "add the requested missing template atoms at their transformed "
        "positions. HONESTY GATE: an atom is only added if the difference map "
        "at its position is >= min_density e/A^3 and it does not clash with "
        "existing atoms; refusals are reported with the measured density. "
        "Refine afterwards.")
    params_schema = {
        "type": "object",
        "properties": {
            "smiles": {"type": "string",
                       "description": "ligand SMILES (default: first prior ligand)"},
            "anchors": {
                "type": "array", "minItems": 3,
                "items": {"type": "object",
                          "properties": {
                              "atom": {"type": "string"},
                              "template_index": {"type": "integer"}},
                          "required": ["atom", "template_index"]},
                "description": "model atom -> ligand template index pairs "
                               "(>=3, not collinear)"},
            "place": {"type": "array", "items": {"type": "integer"},
                      "description": "template indices of atoms to add"},
            "min_density": {"type": "number", "default": 0.8},
            "clash_distance": {"type": "number", "default": 1.0},
        },
        "required": ["anchors", "place"],
    }

    def run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        import numpy as np
        from cctbx import xray
        from ..tools.refinement_tools import difference_map_real
        from .ligand import LigandError, ideal_geometry

        ses = ctx.session
        xs = ses.model
        smi = _resolve_smiles(self.project, params)
        if not smi:
            return ToolResult.failure("no SMILES given and none in priors")
        try:
            tpl = ideal_geometry(smi)
        except LigandError as e:
            return ToolResult.failure(str(e))
        coords = np.array(tpl["coords"])
        elements = tpl["elements"]
        anchors = params["anchors"]
        place = [int(i) for i in params["place"]]
        for t in [a["template_index"] for a in anchors] + place:
            if not (0 <= t < len(elements)):
                return ToolResult.failure(f"template_index {t} out of range "
                                          f"(ligand has {len(elements)} heavy atoms)")
        by_label = {sc.label.strip().upper(): sc for sc in xs.scatterers()}
        uc = xs.unit_cell()
        anchor_pts: dict[int, tuple] = {}      # template_index -> model cart
        for a in anchors:
            sc = by_label.get(str(a["atom"]).strip().upper())
            if sc is None:
                return ToolResult.failure(f"anchor atom {a['atom']!r} not in model")
            anchor_pts[int(a["template_index"])] = uc.orthogonalize(sc.site)
        if len(anchor_pts) < 3:
            return ToolResult.failure("need at least 3 distinct anchors")

        # template graph distances: flexible ligands (biaryl torsions) break a
        # single global superposition, so each atom is placed from a LOCAL
        # rigid fit using anchors within 3 bonds of it in the template graph
        adj = [set(x) for x in tpl["adjacency"]]

        def graph_dist_from(src: int, cutoff: int = 3) -> dict[int, int]:
            dist = {src: 0}
            frontier = [src]
            for step in range(1, cutoff + 1):
                nxt = []
                for u in frontier:
                    for v in adj[u]:
                        if v not in dist:
                            dist[v] = step
                            nxt.append(v)
                frontier = nxt
            return dist

        def kabsch(P: "np.ndarray", Q: "np.ndarray"):
            Pm, Qm = P.mean(axis=0), Q.mean(axis=0)
            Pc, Qc = P - Pm, Q - Qm
            H = Pc.T @ Qc
            U, _, Vt = np.linalg.svd(H)
            d = np.sign(np.linalg.det(Vt.T @ U.T))
            R = Vt.T @ np.diag([1, 1, d]) @ U.T
            rms = float(np.sqrt((((R @ Pc.T).T - Qc) ** 2).sum() / len(P)))
            return R, Pm, Qm, rms

        def transform_local(t_idx: int):
            """(cart position, local rms, n_local_anchors) or error string."""
            gd = graph_dist_from(t_idx)
            local = [t for t in anchor_pts if t in gd]
            if len(local) < 3:
                return f"only {len(local)} anchors within 3 bonds of template " \
                       f"atom {t_idx} - cannot fit locally"
            P = np.array([coords[t] for t in local])
            Q = np.array([anchor_pts[t] for t in local])
            R, Pm, Qm, rms = kabsch(P, Q)
            if rms > 0.35:
                return (f"local anchor fit rms {rms:.2f} A around template atom "
                        f"{t_idx} is too poor - mapping or geometry mismatch")
            v = R @ (coords[t_idx] - Pm) + Qm
            return tuple(float(x) for x in v), rms, len(local)

        # difference density sampling
        try:
            fft_map, real_map, _ = difference_map_real(
                ses, xs, f_mask=ses.flags.get("f_mask"))
        except ValueError as e:
            return ToolResult.failure(f"difference map failed: {e}")
        from cctbx import maptbx
        min_density = float(params.get("min_density", 0.8))
        clash_d = float(params.get("clash_distance", 1.0))

        # neighbor field for clash check: all atoms x symmetry x 27 cells
        ops = xs.space_group().all_ops()
        atom_cart = []
        for sc in xs.scatterers():
            for op in ops:
                s = op * sc.site
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        for dz in (-1, 0, 1):
                            atom_cart.append(uc.orthogonalize(
                                (s[0] + dx, s[1] + dy, s[2] + dz)))
        atom_cart = np.array(atom_cart)

        added, refused = [], []
        local_rms: list[float] = []
        sps = xs.crystal_symmetry().special_position_settings(
            min_distance_sym_equiv=0.5)
        existing = {sc.label.strip().upper() for sc in xs.scatterers()}
        for t in place:
            fit = transform_local(t)
            if isinstance(fit, str):
                refused.append({"template_index": t, "element": elements[t],
                                "reason": fit})
                continue
            cart_t, rms_t, n_loc = fit
            local_rms.append(rms_t)
            cart = np.array(cart_t)
            frac = uc.fractionalize(tuple(cart))
            dens = float(maptbx.eight_point_interpolation(
                real_map, [x % 1.0 for x in frac]))
            if dens < min_density:
                refused.append({"template_index": t, "element": elements[t],
                                "density_e_A3": round(dens, 2),
                                "reason": f"difference density {dens:.2f} < "
                                          f"min_density {min_density} in this map; "
                                          "insufficient evidence to place the atom, "
                                          "not proof that the fragment is absent"})
                continue
            dmin = float(np.min(np.linalg.norm(atom_cart - cart, axis=1)))
            if dmin < clash_d:
                refused.append({"template_index": t, "element": elements[t],
                                "density_e_A3": round(dens, 2),
                                "reason": f"clashes with an existing atom "
                                          f"({dmin:.2f} A)"})
                continue
            site_sym = sps.site_symmetry(frac)
            exact = site_sym.exact_site()
            on_special = not site_sym.is_point_group_1()
            snapped = on_special and uc.distance(frac, exact) < 0.25
            site = exact if snapped else frac
            el = elements[t]
            n = 0
            lbl = f"{el}{t}"[:4].upper()
            while lbl in existing:
                n += 1
                lbl = f"{el}{t}{chr(ord('A') + n)}"[:4].upper()
            existing.add(lbl)
            xs.add_scatterer(xray.scatterer(
                label=lbl, site=site, scattering_type=el, u=0.05, occupancy=1.0))
            added.append({"label": lbl, "template_index": t, "element": el,
                          "density_e_A3": round(dens, 2),
                          "local_fit_rms_A": round(rms_t, 3),
                          "n_local_anchors": n_loc,
                          "snapped_to_special_position": bool(snapped)})
        xs.scattering_type_registry(table="it1992")
        return ToolResult(ok=True, summary={
            "mean_local_anchor_rms_A": (round(sum(local_rms) / len(local_rms), 3)
                                        if local_rms else None),
            "map_provenance": getattr(fft_map, "crystalpilot_map_provenance", None),
            "added": added, "refused": refused,
            "n_atoms": xs.scatterers().size(),
            # WP1: "ran" and "placed something" are different facts - the
            # forensic thread had 15 of 27 ok:true fit_fragment calls add
            # nothing; the envelope says so instead of leaving it to the
            # reader to count `added`
            **({"no_state_change": True,
                "no_change_reason": ("no template atom found density support "
                                     "at its placed position (all refused)")}
               if not added else {}),
            "scientific_outcome": {
                "verdict": "supports" if added else "inconclusive",
                "reasons": [f"{len(added)} template atom(s) placed on density, "
                            f"{len(refused)} refused"],
                "measured_by": "difference density interpolated at the "
                               "template positions (local Kabsch fit)"},
            "next": ("run refine to settle the new atoms" if added else
                     "nothing added - reconsider the hypothesis or inspect_map "
                     "directly")})


# ==========================================================================
class SetRestraints(_ProjectTool):
    name = "set_restraints"
    description = (
        "Declare SHELX-style restraints applied in every subsequent refine "
        "(and written to .res/SHELXL jobs). Kinds: DFIX/DANG (target distance, "
        "atoms=[[a,b],...]), SADI (similar distances), FLAT (planarity), "
        "SIMU/DELU/RIGU/ISOR (ADP restraints; atoms=null means all suitable). "
        "Restraints are declarations of prior knowledge - every one you add "
        "must be scientifically justified and is reported in the final output.")
    params_schema = {
        "type": "object",
        "properties": {
            "action": {"type": "string",
                       "enum": ["add", "remove", "clear", "list"],
                       "default": "add"},
            "restraints": {
                "type": "array",
                "items": {"type": "object",
                          "properties": {
                              "kind": {"type": "string",
                                       "enum": ["DFIX", "DANG", "SADI", "FLAT",
                                                "SIMU", "DELU", "RIGU", "ISOR"]},
                              "atoms": {},
                              "target": {"type": "number"},
                              "sigma": {"type": "number"},
                              "sigma_terminal": {"type": "number"}},
                          "required": ["kind"]},
                "description": "for add/remove"},
        },
    }

    def run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        from .restraints import (emit_shelx_cards, normalize_spec, preflight,
                                 preflight_applicability, spec_key,
                                 validate_spec)
        ses = ctx.session
        action = params.get("action", "add")
        current: list = list(ses.flags.get("restraints") or [])
        if action == "list":
            return ToolResult(ok=True, summary={
                "restraints": current, "cards": emit_shelx_cards(current),
                "no_state_change": True})
        if action == "clear":
            ses.flags["restraints"] = []
            return ToolResult(ok=True, summary={"restraints": [], "cleared": len(current)})
        specs = params.get("restraints") or []
        if not specs:
            return ToolResult.failure(f"action={action} needs 'restraints'")
        errors = []
        normalized = []
        for s in specs:
            err = validate_spec(s)
            if err:
                errors.append(err)
            else:
                normalized.append(normalize_spec(s))
        if errors:
            return ToolResult.failure("; ".join(errors))
        if action == "add" and ses.model is not None:
            # existence check: a ghost-label restraint used to be accepted
            # silently and rode into every future SHELXL job (r10 live:
            # DFIX registered for a predicted 'H53' that auto-renaming
            # actually turned into 'H0'; the invalid card survived a full
            # refine round before cleanup)
            model_labels = {sc.label.upper()
                            for sc in ses.model.scatterers()}
            ghosts: list[str] = []
            for s in normalized:
                atoms = s.get("atoms")
                if not atoms:
                    continue
                flat = [a for item in atoms
                        for a in (item if isinstance(item, list) else [item])]
                ghosts += [a for a in flat
                           if a.upper() not in model_labels]
            if ghosts:
                return ToolResult.failure(
                    f"restraints reference atoms not in the model: "
                    f"{sorted(set(ghosts))} - nothing was registered. Add "
                    f"the atoms first or fix the labels (matching is "
                    f"case-insensitive; inspect_model detail='atoms' for "
                    f"the current table).")
        keys = {spec_key(s) for s in current}
        if action == "add":
            added = 0
            for s in normalized:
                if spec_key(s) not in keys:
                    current.append(s)
                    keys.add(spec_key(s))
                    added += 1
            ses.flags["restraints"] = current
            # round-3 WP3: requested vs actually applied, said here - a
            # DFIX across two PARTs used to register silently and vanish
            # in SHELXL
            pf = (preflight(ses.model, current, ses.flags)
                  if ses.model is not None else None)
            note = preflight_applicability(pf)
            return ToolResult(ok=True, summary={
                "added": added, "restraints": current,
                "cards": emit_shelx_cards(current),
                **({"restraints_preflight": pf} if pf else {}),
                **({"applicability": note} if note else {})})
        # remove
        drop = {spec_key(s) for s in normalized}
        kept = [s for s in current if spec_key(s) not in drop]
        removed = len(current) - len(kept)
        ses.flags["restraints"] = kept
        return ToolResult(ok=True, summary={
            "removed": removed, "restraints": kept,
            **({"no_state_change": True} if removed == 0 else {})})



class PreflightRestraints(_ProjectTool):
    name = "preflight_restraints"
    description = (
        "Read-only: what the current restraints (or a proposed list) would "
        "actually do before a job carries them - which terms the in-process "
        "engine applies, which it cannot represent, and which SHELXL would "
        "drop because the atoms sit in different non-zero PARTs "
        "(shelx_part_conflicts). Nothing is changed. set_restraints and "
        "run_shelxl run the same check and report it as "
        "restraints_preflight.")
    params_schema = {
        "type": "object",
        "properties": {
            "restraints": {
                "type": "array",
                "items": {"type": "object",
                          "properties": {
                              "kind": {"type": "string"},
                              "atoms": {},
                              "target": {"type": "number"},
                              "sigma": {"type": "number"}},
                          "required": ["kind"]},
                "description": "proposed specs to check (same shape as "
                               "set_restraints); omitted = the session's "
                               "current list"},
        },
    }

    def run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        from .restraints import preflight, preflight_applicability
        ses = ctx.session
        if ses is None or ses.model is None:
            return ToolResult.failure("no model loaded")
        proposed = params.get("restraints")
        specs = (list(proposed) if proposed
                 else list(ses.flags.get("restraints") or []))
        pf = preflight(ses.model, specs, ses.flags)
        note = preflight_applicability(pf)
        return ToolResult(ok=True, summary={
            "source": "proposed" if proposed else "session",
            "restraints_preflight": pf,
            **({"applicability": note} if note else {}),
            "verdict": ("clean" if not pf["shelx_part_conflicts"]
                        and not pf["not_representable"]
                        and not pf["warnings"] else "findings")})


# ==========================================================================
class ListNodes(_ProjectTool):
    name = "list_nodes"
    description = ("Node tree of this refinement session: every model state "
                   "with its creating tool, R1/wR2/GooF (marked stale if the "
                   "model changed since), atom count, branch heads.")
    params_schema = {"type": "object",
                     "properties": {"limit": {"type": "integer", "default": 30}}}

    def run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        return ToolResult(ok=True, summary=self.project.nodes.list_nodes(
            limit=int(params.get("limit", 30))))


class CompareNodes(_ProjectTool):
    name = "compare_nodes"
    description = ("Compare two nodes/branches: metric deltas (R1/wR2/GooF/"
                   "params/restraints) and structural diff (atoms added/"
                   "removed/element-changed/moved).")
    params_schema = {
        "type": "object",
        "properties": {"a": {"type": "string",
                             "description": "node id or branch name"},
                       "b": {"type": "string",
                             "description": "node id or branch name"},
                       "node_a": {"type": "string",
                                  "description": "alias of a"},
                       "node_b": {"type": "string",
                                  "description": "alias of b"}},
    }

    def run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        # reg7-dbu: compare_nodes({node_a, node_b}) was schema-rejected
        # twice - the same key-guessing as checkout({target}); aliases
        # cost nothing
        a = params.get("a") or params.get("node_a")
        b = params.get("b") or params.get("node_b")
        if not a or not b:
            return ToolResult.failure(
                "compare_nodes needs two targets: a=<node or branch>, "
                "b=<node or branch> (list_nodes shows the tree)")
        try:
            return ToolResult(ok=True, summary=self.project.compare_nodes(
                str(a), str(b)))
        except KeyError as e:
            return ToolResult.failure(str(e))


class BranchTool(_ProjectTool):
    name = "branch"
    description = ("Create/point a named branch at a node (default: current) "
                   "and make it active. Use to explore alternative hypotheses "
                   "you can later compare_nodes and checkout between.")
    params_schema = {
        "type": "object",
        "properties": {"name": {"type": "string"},
                       "from_node": {"type": "string"}},
        "required": ["name"],
    }

    def run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        try:
            out = self.project.nodes.branch(str(params["name"]),
                                            params.get("from_node"))
        except (KeyError, ValueError) as e:
            return ToolResult.failure(str(e))
        # branch moves the pointer; rebuild the live session at that node,
        # then pin the active branch (checkout's inference could pick another
        # branch whose head is the same node)
        chk = self.project.checkout(out["at"])
        self.project.nodes.set_active(out["at"], branch=str(params["name"]))
        # what the rebuilt session carries (pa1: agents assumed the peak
        # table was gone after a branch and re-refined to get it back)
        out["notes"] = chk.get("notes") or []
        out["peaks"] = chk.get("peaks")
        return ToolResult(ok=True, summary=out)


class CheckoutTool(_ProjectTool):
    name = "checkout"
    description = ("Rebuild the live session from a node or branch head "
                   "(model + restraints + weights + riding H + solvent mask). "
                   "This is the rollback mechanism. `node` takes a node id "
                   "(n0042) or a branch name; `target` / `branch` are "
                   "accepted as aliases.")
    params_schema = {"type": "object",
                     "properties": {
                         "node": {"type": "string",
                                  "description": "node id or branch name"},
                         "target": {"type": "string",
                                    "description": "alias of node"},
                         "branch": {"type": "string",
                                    "description": "alias of node"}}}

    def run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        # reg3-rz: checkout({target: "solve_c2c"}) was schema-rejected
        # with "'node' is a required property" - the agent had the right
        # intent and the wrong key. Aliases cost nothing; a call with no
        # target at all gets the tree instead of a bare refusal.
        ref = params.get("node") or params.get("target") or params.get("branch")
        if not ref:
            try:
                listing = self.project.nodes.list_nodes(limit=8)
            except Exception:  # noqa: BLE001 - the hint is best-effort
                listing = {}
            recent = ", ".join(
                f"{n.get('id')} (R1 {n.get('r1')})" if n.get("r1") is not None
                else str(n.get("id"))
                for n in (listing.get("nodes") or [])[-6:])
            return ToolResult.failure(
                "checkout needs a target: node=<node id or branch name>. "
                f"active node {listing.get('active_node')}, branches "
                f"{sorted((listing.get('branches') or {}).keys())}, recent "
                f"nodes: {recent or 'none'} (list_nodes for the full tree)")
        try:
            return ToolResult(ok=True, summary=self.project.checkout(str(ref)))
        except Exception as e:  # noqa: BLE001
            return ToolResult.failure(f"{type(e).__name__}: {e}")


# ==========================================================================

# --------------------------------------------------------------------------
# r12 module split: SHELX cross-engine and delivery tools live in their own
# modules now; re-exported here so existing imports keep working.
from .tools_shelxl import (RunShelxl, RunShelxt,          # noqa: E402,F401
                           SetResolutionLimit, SetWeights, SetZ,
                           _shelx_atom_stats, flack_verdict, parse_flack_lst)
from .tools_deliver import (FinalizeDelivery, RunCheckcif,  # noqa: E402,F401
                            SubmitIucrCheckcif, WriteOutputs,
                            _disorder_obligations, _mask_obligations)
from .tools_olex2 import RunOlex2                         # noqa: E402,F401
