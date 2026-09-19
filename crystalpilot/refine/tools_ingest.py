"""Ingest tools: import an externally refined CIF as a session
start model, and record experimental metadata (set_experiment).

Split out of tools_analysis (r12 module split); registration stays in
tools_analysis.register_analysis_tools.
"""
from __future__ import annotations

import json
import math
import re
import time
from pathlib import Path
from typing import Any

from ..tools.base import ToolContext, ToolResult
from .toolbase import _VAL_ESD, _ProjectTool
from .data_versions import input_directory, capture_source


class ImportCifModel(_ProjectTool):
    name = "import_cif_model"
    description = (
        "Import an externally refined structure (CIF) as this project's "
        "start model - the entry point for VALIDATING or IMPROVING someone "
        "else's refinement. When the CIF embeds the SHELX model "
        "(_shelx_res_file, common in IUCr/COD deposits) that is used "
        "verbatim - PART/FVAR disorder linkage, TWIN/BASF, restraints and "
        "riding H all survive. Otherwise the atom loop is converted via "
        "gemmi (aniso ADPs + occupancies; riding-H constraints NOT carried "
        "- re-derive with add_hydrogens before refining). Experimental "
        "metadata (temperature, crystal size/colour, absorption, "
        "instrument) is pulled into context.json either way. Reflection "
        "data, in order of preference: crystal.hkl in the project, "
        "hkl_path= (SHELX .hkl or fcf/sf-CIF, auto-converted), the CIF's "
        "embedded _shelx_hkl_file, or - Olex2's IUCr export, which has "
        "neither - the whole .fcf embedded as _iucr_refine_fcf_details "
        "(merged data: reproduces the deposit, cannot redo the reduction). "
        "For a CIF without observed reflections, explicitly "
        "set structure_only=true in a new project: geometry is available "
        "but the model is read-only and published R values are only "
        "reference metadata. Later supply hkl_path to explicitly import "
        "real observations and enable refinement.")
    params_schema = {
        "type": "object",
        "properties": {
            "cif_path": {"type": "string",
                         "description": "CIF file (absolute or project-"
                                        "relative)"},
            "hkl_path": {"type": "string",
                         "description": "SHELX .hkl to copy in as "
                                        "crystal.hkl (when absent)"},
            "data_block": {"type": "string",
                           "description": "which data block to import when "
                                          "the CIF holds several compounds "
                                          "(one deposit per block). The "
                                          "error message lists the names."},
            "wavelength": {"type": "number"},
            "structure_only": {"type": "boolean", "default": False},
        },
        "required": ["cif_path"],
    }

    def run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        p = self.project
        if params.get("structure_only"):
            if params.get("hkl_path"):
                return ToolResult.failure("Choose either structure_only=true or an explicit hkl_path, not both")
            try:
                summary = p.import_structure_only(
                    params["cif_path"], block_name=params.get("data_block"))
            except (ValueError, OSError, RuntimeError) as exc:
                return ToolResult.failure(str(exc))
            return ToolResult(ok=True, summary=summary)
        if not getattr(p, "structure_only", False):
            return self._run_refinement(ctx, **params)
        if not params.get("hkl_path"):
            from .structure_document import STRUCTURE_ONLY_PRECONDITION
            return ToolResult.failure(STRUCTURE_ONLY_PRECONDITION)
        supplied_hkl = Path(params["hkl_path"])
        if not supplied_hkl.is_absolute():
            supplied_hkl = p.dir / supplied_hkl
        hkl_destination = input_directory(p) / "crystal.hkl"
        hkl_existed = hkl_destination.exists()
        if hkl_existed and supplied_hkl.resolve() != (p.dir / "crystal.hkl").resolve():
            return ToolResult.failure("crystal.hkl already exists; explicitly select that file or use a new project")

        context_path = input_directory(p) / "context.json"
        previous_text = context_path.read_text(encoding="utf-8")
        previous_session, previous_ctx = p.session, p.ctx
        previous_inputs = p.hkl_path, p.start_model_path
        context = {**p.context, "mode": "refinement"}
        context_path.write_text(json.dumps(context, indent=2, ensure_ascii=False),
                                encoding="utf-8")
        p.context = context
        result = None
        try:
            result = self._run_refinement(ctx, **params)
            return result
        finally:
            if result is None or not result.ok:
                context_path.write_text(previous_text, encoding="utf-8")
                p.context = json.loads(previous_text)
                p.session, p.ctx = previous_session, previous_ctx
                p.hkl_path, p.start_model_path = previous_inputs
                if not hkl_existed:
                    hkl_destination.unlink(missing_ok=True)

    def _run_refinement(self, ctx: ToolContext, **params: Any) -> ToolResult:
        import shutil

        # local, like the other io imports here: keeps cctbx off the
        # module-import path
        from ..io.cif_sf import _EMBEDDED_FCF_TAG

        p = self.project
        cif = Path(params["cif_path"])
        if not cif.is_absolute():
            cif = p.dir / cif
        if not cif.exists():
            return ToolResult.failure(f"no such CIF: {cif}")
        cif = capture_source(p, cif)
        cif_text = cif.read_text(encoding="utf-8", errors="replace")

        # DDLm dialect (dotted _cell.length_a tags): normalize to DDL1 once
        # up front, so every downstream path-based reader (gemmi loader,
        # experiment block, embedded-res extraction) sees names it knows
        ddlm_note = None
        from ..io.cif_compat import looks_like_ddlm, normalize_ddlm_tags
        if looks_like_ddlm(cif_text):
            cif_text = normalize_ddlm_tags(cif_text)
            norm = input_directory(p) / f"ddl1_{cif.name}"
            norm.parent.mkdir(parents=True, exist_ok=True)
            norm.write_text(cif_text, encoding="utf-8")
            cif = norm
            ddlm_note = ("DDLm-style dotted tags detected - normalized to "
                         f"DDL1 names into {norm.name} and imported from "
                         "there")

        # Multi-datablock deposits (one file, several compounds). Every
        # extractor below is a whole-file regex or a single-block reader:
        # unsliced, the regexes silently return block 1 and gemmi refuses
        # the file outright. Never guess which compound was meant.
        blocks = _cif_data_blocks(cif_text)
        block_note = None
        if len(blocks) > 1:
            want = params.get("data_block")
            names = [b[0] for b in blocks]
            if not want:
                return ToolResult.failure(
                    f"{cif.name} holds {len(blocks)} data blocks "
                    f"({', '.join(names)}) - one deposit per compound. "
                    "Pass data_block=<name> to say which one; importing "
                    "the first silently would give you a different "
                    "structure than you asked for.")
            hit = next((b for b in blocks if b[0] == want), None)
            if hit is None:
                return ToolResult.failure(
                    f"no data block '{want}' in {cif.name}; available: "
                    f"{', '.join(names)}")
            cif_text = hit[1]
            sliced = input_directory(p) / f"block_{want}_{cif.name}"
            sliced.parent.mkdir(parents=True, exist_ok=True)
            sliced.write_text(cif_text, encoding="utf-8")
            cif = sliced
            block_note = (f"multi-block CIF: imported block '{want}' of "
                          f"{len(blocks)} ({', '.join(names)})")

        hkl_note = None
        hkl_from_fcf = False
        hkl_osf = None       # OSF matching a crystal.hkl we built from an fcf
        hkl_dst = input_directory(p) / "crystal.hkl"
        if params.get("hkl_path") and getattr(p, "_input_stage", None) is not None:
            hkl_dst.unlink(missing_ok=True)
        if not hkl_dst.exists():
            src = params.get("hkl_path")
            if src:
                src = Path(src)
                if not src.is_absolute():
                    src = p.dir / src
                if not src.exists():
                    return ToolResult.failure(f"no such hkl: {src}")
                src = capture_source(p, src)
                head = src.read_text(encoding="utf-8",
                                     errors="replace")[:4000]
                if "_refln" in head or src.suffix.lower() in (".fcf",
                                                              ".cif"):
                    from ..io.cif_sf import load_cif_sf_dataset, write_hklf4
                    try:
                        ds = load_cif_sf_dataset(src, ref_cif_path=cif)
                    except Exception as e:  # noqa: BLE001
                        return ToolResult.failure(
                            f"could not read structure factors from "
                            f"{src.name}: {e}")
                    info = write_hklf4(ds.intensities, hkl_dst)
                    hkl_osf = _fcf_osf(ds, info)
                    if getattr(p, "_input_stage", None) is not None:
                        p._input_stage.processing = ["structure-factor CIF converted to HKLF4"]
                        p._input_stage.scale_applied = info["scale_applied"]
                    hkl_note = (f"converted {src.name} (structure-factor "
                                f"CIF) to HKLF4; "
                                f"n={info['n_reflections']}, "
                                f"scale={info['scale_applied']}; the overall "
                                "scale and processing of published structure "
                                "factors may differ from the original HKL. "
                                "Check paired data/weights/mask conditions "
                                "before treating a zero-cycle R1 difference "
                                "as an import error; do not silently alter "
                                "the supplied observations to match it.")
                else:
                    shutil.copy(src, hkl_dst)
            else:
                embedded_hkl = _semicolon_field(cif_text, "_shelx_hkl_file")
                if embedded_hkl and embedded_hkl.count("\n") > 10:
                    hkl_dst.write_text(embedded_hkl, encoding="ascii",
                                       errors="replace")
                    if getattr(p, "_input_stage", None) is not None:
                        p._input_stage.processing = ["CIF embedded _shelx_hkl_file extracted"]
                        p._input_stage.scale_applied = 1.0
                    hkl_note = ("extracted the CIF's embedded "
                                "_shelx_hkl_file as crystal.hkl")
                elif _EMBEDDED_FCF_TAG in cif_text:
                    # Olex2's IUCr export deposits no _shelx_hkl_file: the
                    # reflections are the whole .fcf, embedded as the text
                    # value of _iucr_refine_fcf_details. Second choice on
                    # purpose - the fcf is the MERGED set the deposit
                    # refined against, the raw hkl would be the measurement.
                    from ..io.cif_sf import load_cif_sf_dataset, write_hklf4
                    try:
                        ds = load_cif_sf_dataset(cif)
                    except Exception as e:  # noqa: BLE001
                        return ToolResult.failure(
                            f"the CIF embeds an fcf ({_EMBEDDED_FCF_TAG}) "
                            f"but its reflections could not be read: {e}")
                    info = write_hklf4(ds.intensities, hkl_dst)
                    hkl_from_fcf = True
                    hkl_osf = _fcf_osf(ds, info)
                    if getattr(p, "_input_stage", None) is not None:
                        p._input_stage.processing = [
                            f"CIF embedded {_EMBEDDED_FCF_TAG} (merged fcf) "
                            "converted to HKLF4"]
                        p._input_stage.scale_applied = info["scale_applied"]
                    code = ds.instrument_meta.get("shelx_refln_list_code")
                    hkl_note = (
                        f"no _shelx_hkl_file - took the reflections from "
                        f"the CIF's embedded fcf ({_EMBEDDED_FCF_TAG}"
                        + (f", LIST {code}" if code else "") + ") and wrote "
                        f"HKLF4; n={info['n_reflections']}, "
                        f"scale={info['scale_applied']}. IMPORTANT: this is "
                        "the "
                        + ("MERGED " if ds.instrument_meta.get("merged")
                           else "") +
                        "F^2 set the deposit refined against, already "
                        "scaled to its Fc - not the raw measurement. "
                        "Reflections the deposit omitted are gone, and "
                        "Rint / absorption / merging cannot be "
                        "re-examined from it. Enough to reproduce and "
                        "audit the published refinement; ask for the "
                        "original .hkl to redo the data reduction.")
                else:
                    return ToolResult.failure(
                        "no reflection data: the project has no "
                        "crystal.hkl, no hkl_path was given, and the CIF "
                        "embeds neither _shelx_hkl_file nor "
                        f"{_EMBEDDED_FCF_TAG}. hkl_path accepts a "
                        "SHELX .hkl or a structure-factor CIF/.fcf")

        exp = _cif_experiment_block(cif)
        z = _cif_number(cif, "_cell_formula_units_Z")
        notes: list[str] = [n for n in (ddlm_note, block_note) if n]

        # Fidelity path: the deposited SHELX res, verbatim - disorder
        # linkage / twin / restraints / riding H all survive our parser.
        embedded_res = (_semicolon_field(cif_text, "_shelx_res_file")
                        or _semicolon_field(
                            cif_text, "_iucr_refine_instructions_details"))
        imported_via = None
        if embedded_res and "HKLF" in embedded_res.upper():
            (input_directory(p) / "start.res").write_text(embedded_res,
                                             encoding="ascii",
                                             errors="replace")
            try:
                from ..io.shelx_model import load_res_model
                parsed_probe = load_res_model(input_directory(p) / "start.res")
                n_atoms = parsed_probe.structure.scatterers().size()
                if n_atoms == 0:
                    raise ValueError("embedded res has no atoms")
                if parsed_probe.hklf == 5:
                    # the model demands twin-batch data; a batch-less hkl
                    # (e.g. derived from the fcf) would hard-fail SHELXL.
                    # The deposit's own hkl is the consistent source.
                    emb = _semicolon_field(cif_text, "_shelx_hkl_file")
                    if emb and emb.count("\n") > 10:
                        hkl_dst.write_text(emb, encoding="ascii",
                                           errors="replace")
                        if getattr(p, "_input_stage", None) is not None:
                            p._input_stage.processing = ["CIF embedded HKLF5 selected; supplied data not used"]
                            p._input_stage.scale_applied = 1.0
                        hkl_note = ("model is HKLF5 (twin-batch): used the "
                                    "CIF's embedded _shelx_hkl_file "
                                    "instead of the provided hkl - a "
                                    "batch-less file cannot represent "
                                    "these composite observations")
                    elif hkl_from_fcf:
                        # an fcf is one merged row per unique hkl; HKLF5
                        # needs the un-merged composite rows plus a batch
                        # number. No repair is possible from this file.
                        notes.append(
                            "WARNING: model is HKLF5 (twin-batch) but the "
                            f"only reflections in this CIF are the merged "
                            f"fcf ({_EMBEDDED_FCF_TAG}), which has no batch "
                            "column and cannot represent composite "
                            "observations - SHELXL will reject it. Get the "
                            "deposit's original HKLF5 .hkl and re-import "
                            "with hkl_path=, or drop TWIN/BASF and accept "
                            "that this is no longer the published "
                            "refinement.")
                    else:
                        notes.append("WARNING: model is HKLF5 but no "
                                     "embedded _shelx_hkl_file - the "
                                     "provided hkl must carry the batch "
                                     "column or SHELXL will reject it")
                imported_via = "embedded_shelx_res"
                notes.append(
                    f"used the CIF's embedded SHELX res verbatim "
                    f"({n_atoms} atoms"
                    + (", TWIN/BASF present" if parsed_probe.twin else "")
                    + (f", {len(parsed_probe.sof_codes)} coded sofs"
                       if parsed_probe.sof_codes else "") + ")")
                if parsed_probe.uses_abin:
                    notes.append(
                        "IMPORTANT: the deposit refined WITH a solvent "
                        "mask (ABIN) whose .fab is not in the CIF - the "
                        "current R is missing the mask contribution and "
                        "will look too high. Run solvent_mask to "
                        "recompute it before judging the model.")
                if parsed_probe.h_riding:
                    notes.append(f"{len(parsed_probe.h_riding)} riding-H "
                                 f"groups preserved")
                if parsed_probe.custom_sfac:
                    els = ", ".join(parsed_probe.custom_sfac)
                    notes.append(
                        "IMPORTANT: the deposit carries CUSTOM scattering "
                        f"factors (long-form SFAC for {els})"
                        + (f" and lambda={parsed_probe.wavelength} A - this "
                           "is ELECTRON diffraction (3D ED/microED). "
                           if parsed_probe.is_electron_diffraction
                           else " - ")
                        + "Every engine here (smtbx, SHELXL, olex2) will "
                        "use its built-in X-RAY tables instead, so R "
                        "factors and ADPs are not comparable with the "
                        "deposited ones. Treat this as a geometry/model "
                        "import and say so in the report.")
            except Exception as e:  # noqa: BLE001 - fall back to gemmi
                (input_directory(p) / "start.res").unlink(missing_ok=True)
                notes.append(f"embedded res unusable ({e}); converted the "
                             f"atom loop instead")
                imported_via = None

        wl = params.get("wavelength")
        if imported_via is None:
            import gemmi
            try:
                small = gemmi.read_small_structure(str(cif))
            except Exception as e:  # noqa: BLE001
                return ToolResult.failure(
                    f"gemmi could not read the CIF: {e}")
            if not small.sites:
                return ToolResult.failure("CIF contains no atom sites")
            xs, conv = _small_structure_to_xray(small)
            if xs is None:
                return ToolResult.failure(conv)
            notes.extend(conv)
            wl = wl or small.wavelength or None
            from ..io.shelx_writer import ShelxModel, write_res
            write_res(ShelxModel(
                xray_structure=xs, wavelength=wl or 0.71073,
                z=int(z) if z else None,
                title=f"import {cif.stem}",
                rem_lines=[f"CrystalPilot import_cif_model from "
                           f"{cif.name}"]),
                input_directory(p) / "start.res")
            imported_via = "gemmi_atom_loop"

        # the model's scale factor has to belong to the reflections we
        # actually wrote: both engines refit it, but a res that contradicts
        # its own crystal.hkl is a trap for anything reading FVAR as given
        if hkl_osf is not None:
            old_osf = _set_res_osf(input_directory(p) / "start.res", hkl_osf)
            if old_osf is not None and abs(old_osf - hkl_osf) > 1e-6:
                notes.append(
                    f"overall scale factor FVAR {old_osf:.5f} -> "
                    f"{hkl_osf:.5f}: the model's scale must match the "
                    f"fcf-derived crystal.hkl written here, not the "
                    f"reflection file the deposit refined against")

        from .tools_frames import _update_context
        # start_model pointer MUST follow the file we just wrote: r22 live
        # failure - ingest_vendor_data had set data.start_model to the
        # atomless bootstrap start.ins, this tool wrote start.res but left
        # the pointer alone, and reload_inputs faithfully rebuilt an EMPTY
        # session from the stale pointer ('0 atoms - atom loop was not
        # read' pointed at the wrong suspect)
        patch: dict[str, Any] = {
            "data": {"start_model": "start.res",
                     "note": f"start model imported from {cif.name} "
                             f"({imported_via})"}}
        if hkl_from_fcf:
            # durable, not just a one-off tool note: every later judgement
            # about Rint / absorption / omitted reflections depends on
            # knowing crystal.hkl is the deposit's merged fcf
            patch["data"]["reflections"] = (
                f"crystal.hkl derived from {cif.name}'s embedded "
                f"{_EMBEDDED_FCF_TAG} - merged F^2 as refined, NOT the raw "
                "measurement")
        if getattr(p, "_input_stage", None) is not None:
            from .nodes import atomic_write_json
            imported_context = {**p.context, "experiment": exp or {}}
            atomic_write_json(input_directory(p) / "context.json", imported_context, indent=2)
            p.context = imported_context
        elif exp:
            patch["experiment"] = exp
        _update_context(p, patch)

        p._import_h_policy = "keep"     # deposited H are part of the model
        try:
            opened = p.reload_inputs()
        finally:
            p._import_h_policy = "rederive"
        ses = p.session
        flags = ses.flags if ses is not None else {}
        n_imported = (ses.model.scatterers().size()
                      if ses is not None and ses.model is not None else 0)
        if not n_imported:
            # a zero-atom "success" cost a whole debugging detour in p780
            # (agent had to read engine source to find the silent fallback)
            return ToolResult.failure(
                "import produced a session with 0 atoms - the CIF's atom "
                "loop was not read (unsupported tags? wrong file? DDLm "
                "dotted names were already normalized before parsing). "
                "The session is now an EMPTY model: fix the input and "
                "re-run import_cif_model before any refinement step.")
        summary = {
            "imported_via": imported_via,
            "imported_atoms": n_imported,
            "space_group": (str(ses.model.space_group_info())
                            if ses is not None else None),
            "twin_active": bool(flags.get("twin")),
            "disorder_groups": len(flags.get("disorder_groups") or []),
            "z": z,
            "experiment_metadata": exp or {
                "note": "CIF carried no temperature/size/absorption values"},
            "start_node": (opened or {}).get("node"),
            "conversion_notes": notes + ([hkl_note] if hkl_note else []),
            "next": ("inspect_model + run_checkcif to audit the imported "
                     "refinement. Compare run_shelxl(mode='check') with "
                     "published metrics only after confirming matching "
                     "reflection data, scale, weights, hydrogen and mask "
                     "conditions; geometric import alone does not establish "
                     "that equivalence."),
        }
        return ToolResult(ok=True, summary=summary)


def _fcf_osf(ds, info) -> float | None:
    """The SHELX overall scale factor that matches a crystal.hkl we just wrote
    out of an fcf, or None when the scale cannot be reasoned about.

    An fcf refinement listing (_shelx_refln_list_code) carries Fo^2 already on
    the deposit's Fc scale, and write_hklf4 then multiplies by a power of ten
    to fit the F8.2 field. SHELXL divides by osf^2, so osf = sqrt(that factor)
    puts the data back exactly where the published R1 was computed. A plain
    sf-CIF of raw measurements has no such anchor - leave its scale alone and
    let the refinement find it.
    """
    if not ds.instrument_meta.get("shelx_refln_list_code"):
        return None
    scale = info.get("scale_applied")
    if not scale or scale <= 0:
        return None
    return math.sqrt(scale)


def _set_res_osf(res_path: Path, osf: float) -> float | None:
    """Replace the overall scale factor (first FVAR value) in a SHELX res;
    returns the value that was there. Free variables after it are untouched.

    The deposited FVAR scales the deposit's OWN hkl. Paired with reflections
    taken from its fcf it is simply the wrong number, and the res then
    contradicts the crystal.hkl sitting next to it.

    Measured 2026-09-08 on the four survey deposits: this does NOT move the
    recomputed R1 (Q.cif 0.2291 rewritten vs 0.2292 with the deposited FVAR),
    because SHELXL and smtbx both fit the overall scale themselves - node
    conditions record it as 'fitted_overall_scale'. Keep the rewrite for
    self-consistency of the written inputs (export, and any path that takes
    the scale as given), not as a precondition for reproducing the deposit.
    """
    try:
        text = res_path.read_text(encoding="ascii", errors="replace")
    except OSError:
        return None
    lines = text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        toks = line.split()
        if not toks or toks[0].upper() != "FVAR" or len(toks) < 2:
            continue
        try:
            old = float(toks[1])
        except ValueError:
            return None
        eol = ("\r\n" if line.endswith("\r\n")
               else "\n" if line.endswith("\n") else "")
        lines[i] = " ".join(["FVAR", "%.6f" % osf, *toks[2:]]) + eol
        res_path.write_text("".join(lines), encoding="ascii",
                            errors="replace")
        return old
    return None


def _small_structure_to_xray(small):
    """gemmi SmallStructure -> cctbx xray.structure (+ notes)."""
    from cctbx import adptbx, crystal, sgtbx, xray
    notes: list[str] = []
    cell = small.cell
    uc = (cell.a, cell.b, cell.c, cell.alpha, cell.beta, cell.gamma)
    ops = [op if isinstance(op, str) else op.triplet()
           for op in small.symops] or None
    try:
        if ops:
            g = sgtbx.space_group()
            for t in ops:
                g.expand_smx(sgtbx.rt_mx(t))
            sgi = sgtbx.space_group_info(group=g)
        else:
            sgi = sgtbx.space_group_info(
                symbol=small.spacegroup_hm or "P 1")
            notes.append("no symop loop in CIF - used H-M symbol")
    except Exception as e:  # noqa: BLE001
        return None, f"could not build the space group: {e}"
    cs = crystal.symmetry(unit_cell=uc, space_group_info=sgi)
    xs = xray.structure(crystal_symmetry=cs)
    ucell = xs.unit_cell()
    n_aniso = 0
    for site in small.sites:
        el = site.element.name or "C"
        if el.lower() in ("d", "x"):
            el = "H"
        occ = site.occ if site.occ > 0 else 1.0
        sc = xray.scatterer(
            label=site.label[:4] or el,
            site=(site.fract.x, site.fract.y, site.fract.z),
            occupancy=occ, u=site.u_iso if site.u_iso > 0 else 0.03,
            scattering_type=el)
        aniso = site.aniso
        if aniso.nonzero():
            u_cif = (aniso.u11, aniso.u22, aniso.u33,
                     aniso.u12, aniso.u13, aniso.u23)
            try:
                sc.u_star = adptbx.u_cif_as_u_star(ucell, u_cif)
                sc.flags.set_use_u_aniso(True)
                n_aniso += 1
            except Exception:  # noqa: BLE001 - keep isotropic on failure
                notes.append(f"{site.label}: bad aniso ADP, kept isotropic")
        xs.add_scatterer(sc)
    xs.scattering_type_registry(table="it1992")
    if n_aniso:
        notes.append(f"{n_aniso} anisotropic ADPs imported")
    # gemmi gives occupancies as chemical occupancy; cctbx wants
    # occupancy*special-position factor handled at refinement time - the
    # session import path re-derives sof, so nothing to do here.
    return xs, notes


def _cif_data_blocks(cif_text: str) -> list[tuple[str, str]]:
    """[(block_name, block_text), ...]. A `data_` line inside a
    semicolon-delimited text field is not a block header, so the scan is
    line-based and tracks whether it is inside such a field."""
    blocks: list[tuple[str, str]] = []
    name, buf, in_text = None, [], False
    for line in cif_text.splitlines(keepends=True):
        if line.startswith(";"):
            in_text = not in_text
        if not in_text and line.lstrip().lower().startswith("data_"):
            if name is not None:
                blocks.append((name, "".join(buf)))
            name, buf = line.strip()[5:], [line]
            continue
        buf.append(line)
    if name is not None:
        blocks.append((name, "".join(buf)))
    return blocks


def _semicolon_field(cif_text: str, tag: str) -> str | None:
    """Extract a CIF multi-line (semicolon-delimited) field's raw text."""
    m = re.search(re.escape(tag) + r"[ \t]*\r?\n;\r?\n?(.*?)\r?\n;",
                  cif_text, re.DOTALL)
    return m.group(1) if m else None


def _cif_number(cif_path: Path, tag: str):
    m = re.search(re.escape(tag) + r"\s+([-\d.]+)",
                  cif_path.read_text(encoding="utf-8", errors="replace"))
    return float(m.group(1)) if m else None


def _cif_value(text: str, tag: str) -> str | None:
    m = re.search(re.escape(tag) + r"[ \t]+(?:'([^']*)'|(\S+))", text)
    if not m:
        return None
    raw = (m.group(1) or m.group(2)).strip()
    return None if raw in ("?", ".", "") else raw


def _cif_float(text: str, tag: str) -> float | None:
    raw = _cif_value(text, tag)
    if raw is None:
        return None
    mm = _VAL_ESD.match(raw)
    try:
        return float(mm.group(1)) if mm else float(raw)
    except ValueError:
        return None


# canonical context.json `experiment` schema: what set_experiment accepts
# and _cif_experiment_block / the publication assembler produce/consume
_EXPERIMENT_SCHEMA: dict[str, Any] = {
    "temperature_K": float,
    "crystal": {"description": str, "colour": str, "size_mm": list},
    "instrument": {"source": str, "diffractometer": str, "method": str},
    "absorption": {"type": str, "t_min": float, "t_max": float,
                   "details": str},
    "cell_measurement": {"reflns_used": int, "theta_min": float,
                         "theta_max": float},
    "computing": {"data_collection": str, "cell_refinement": str,
                  "data_reduction": str,
                  # pa2 hex: solve_superflip's citation obligation asks
                  # the agent to record the program, and the whitelist
                  # refused it
                  "structure_solution": str, "structure_refinement": str,
                  "molecular_graphics": str, "publication_material": str},
}

#: IUCr _exptl_absorpt_correction_type enumeration (core CIF dictionary)
_ABSORPT_TYPES = {
    "analytical", "cylinder", "empirical", "gaussian", "integration",
    "multi-scan", "none", "numerical", "psi-scan", "refdelf", "sphere",
}


def _stale_temperature_deliveries(project: Any,
                                   new_temp_K: float | None) -> list[str]:
    """final.cif files already written to disk whose
    _diffrn_ambient_temperature no longer matches what the experiment block
    now implies. set_experiment only edits context.json; it never touches a
    final.cif a prior write_outputs already produced, so a temperature
    change here can leave a stale delivery on disk showing the old (or a
    SHELXL-default) value until write_outputs is re-run. WP4."""
    expected = "?" if new_temp_K is None else f"{float(new_temp_K):.0f}"
    stale: list[str] = []
    root = getattr(project, "dir", None)
    if root is None:
        return stale
    root = Path(root)
    for cif_path in sorted(root.rglob("final.cif")):
        try:
            cif_text = cif_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        m = re.search(r"^_diffrn_ambient_temperature\s+(\S+)", cif_text,
                       re.MULTILINE)
        if m and m.group(1).strip("'\"") != expected:
            try:
                stale.append(str(cif_path.relative_to(root)))
            except ValueError:
                stale.append(str(cif_path))
    return stale


class SetExperiment(_ProjectTool):
    name = "set_experiment"
    description = (
        "Record experimental metadata into context.json `experiment` - the "
        "auditable path for facts the vendor files did not carry (crystal "
        "colour/size from the mount notes, temperature, absorption T "
        "range...). AUTO-IMPORT: a project-root context.json that already "
        "carries an `experiment` block (written by the user/runner: "
        "instrument, radiation, temperature, crystal colour/habit) is "
        "applied automatically to every SHELXL job and the publication "
        "CIF; call set_experiment() with NO arguments early to normalise "
        "it, put the import on the provenance trail and see exactly which "
        "fields came from the file (plus a wavelength cross-check against "
        "the data) - no need to re-key those values. Explicit experiment= "
        "values always win over the file. Keys are whitelisted to the "
        "canonical schema (temperature_K, crystal{description,colour,"
        "size_mm}, instrument{source,diffractometer,method}, absorption{"
        "type,t_min,t_max,details}, cell_measurement{reflns_used,theta_min,"
        "theta_max}, computing{...}); absorption.type must be an IUCr "
        "keyword. provenance is REQUIRED with explicit values - say where "
        "each fact comes from (e.g. 'user email 2026-08-30', 'TWINABS "
        "listing'). Values merge over existing ones; a null value REMOVES "
        "the key (use it to declare a fact unknown or to purge a bogus "
        "placeholder, e.g. temperature_K: null - the publication CIF then "
        "carries '?'). This feeds TEMP/SIZE cards in SHELXL jobs and "
        "_exptl_* in the publication CIF. Never invent values. Any call "
        "that puts radiation on the record (and every no-argument import) "
        "returns an `absorption_edge` block: whether the wavelength now on "
        "file sits on an absorption edge of a declared element - f' then "
        "lowers that element's apparent electron count, so element_scan / "
        "e-count arguments must use z_eff = Z + f' - or the explicit "
        "statement that it does not, or that the check has no wavelength "
        "or no element list yet.")
    params_schema = {
        "type": "object",
        "properties": {
            "experiment": {
                "type": "object",
                "description": "subset of the canonical experiment schema "
                               "to merge (see tool description). Omit it "
                               "(no arguments at all) to import/normalise "
                               "the block context.json already carries"},
            "provenance": {
                "type": "string",
                "description": "where these values come from (required "
                               "with experiment=, appended to the audit "
                               "trail; optional note in import mode)"},
        },
        "required": [],
    }

    def run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        exp = params.get("experiment")
        prov = str(params.get("provenance") or "").strip()
        if exp is None or exp == {}:
            return self._import_from_context(ctx, prov)
        if not isinstance(exp, dict) or not exp:
            return ToolResult.failure("experiment must be a non-empty object")
        if len(prov) < 8:
            return ToolResult.failure(
                "provenance is required and must actually say where the "
                "values come from (>= 8 chars)")

        errors: list[str] = []
        # null value = REMOVE the key ('this fact is unknown'). Two live
        # cases forced hand-editing context.json before this existed:
        # r15 deleting a bogus 293 K placeholder a CIF import injected,
        # r11_c trying set_experiment(temperature_K=null) and being told
        # 'must be float'. Unknown facts belong ABSENT (publication CIF
        # then carries '?'), never invented.
        removals: list[str] = []
        exp = dict(exp)
        for key in list(exp):
            val = exp[key]
            if val is None:
                if key not in _EXPERIMENT_SCHEMA:
                    errors.append(f"unknown key {key!r} (allowed: "
                                  f"{sorted(_EXPERIMENT_SCHEMA)})")
                else:
                    removals.append(key)
                del exp[key]
            elif isinstance(val, dict):
                spec = _EXPERIMENT_SCHEMA.get(key)
                for k2 in list(val):
                    if val[k2] is None:
                        if not isinstance(spec, dict) or k2 not in spec:
                            errors.append(f"unknown key {key}.{k2}")
                        else:
                            removals.append(f"{key}.{k2}")
                        del val[k2]
                if not val:
                    del exp[key]

        clean: dict[str, Any] = {}
        for key, val in exp.items():
            spec = _EXPERIMENT_SCHEMA.get(key)
            if spec is None:
                errors.append(f"unknown key {key!r} (allowed: "
                              f"{sorted(_EXPERIMENT_SCHEMA)})")
                continue
            if isinstance(spec, dict):
                if not isinstance(val, dict):
                    errors.append(f"{key} must be an object")
                    continue
                sub: dict[str, Any] = {}
                for k2, v2 in val.items():
                    t2 = spec.get(k2)
                    if t2 is None:
                        errors.append(f"unknown key {key}.{k2} (allowed: "
                                      f"{sorted(spec)})")
                        continue
                    try:
                        sub[k2] = (t2(v2) if t2 in (float, int)
                                   else v2 if isinstance(v2, t2)
                                   else t2(v2))
                    except (TypeError, ValueError):
                        errors.append(f"{key}.{k2} must be {t2.__name__}")
                if sub:
                    clean[key] = sub
            else:
                try:
                    clean[key] = spec(val)
                except (TypeError, ValueError):
                    errors.append(f"{key} must be {spec.__name__}")

        ab = clean.get("absorption") or {}
        if "type" in ab and ab["type"] not in _ABSORPT_TYPES:
            errors.append(
                f"absorption.type {ab['type']!r} is not an IUCr keyword "
                f"({sorted(_ABSORPT_TYPES)})")
        sz = (clean.get("crystal") or {}).get("size_mm")
        if sz is not None:
            try:
                sz = [float(x) for x in sz]
                assert len(sz) == 3 and all(0 < x < 5 for x in sz)
                clean["crystal"]["size_mm"] = sz
            except (TypeError, ValueError, AssertionError):
                errors.append("crystal.size_mm must be 3 positive mm values")
        if errors:
            return ToolResult.failure("; ".join(errors))
        if not clean and not removals:
            return ToolResult.failure("nothing to record after validation")

        from .tools_frames import _update_context
        old_prov = ((self.project.context or {}).get("experiment") or {}) \
            .get("provenance")
        stamp = time.strftime("%Y-%m-%d")
        what = sorted(clean) + [f"-{r}" for r in removals]
        entry = f"{stamp} set_experiment({', '.join(what)}): {prov}"
        clean["provenance"] = (f"{old_prov}\n{entry}" if old_prov else entry)
        _update_context(self.project, {"experiment": clean})
        removed: list[str] = []
        if removals:
            import os as _os
            path = self.project.dir / "context.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            expd = data.get("experiment") or {}
            for dotted in removals:
                cur: Any = expd
                parts = dotted.split(".")
                for pt in parts[:-1]:
                    cur = cur.get(pt) if isinstance(cur, dict) else None
                    if cur is None:
                        break
                if isinstance(cur, dict) and parts[-1] in cur:
                    cur.pop(parts[-1])
                    removed.append(dotted)
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                           encoding="utf-8")
            _os.replace(tmp, path)
            self.project.context = data
        # WP4: temperature_K touched (set or removed) - check whether a
        # final.cif already on disk now disagrees with the updated
        # experiment block. set_experiment only edits context.json; it
        # cannot reach back into a delivery write_outputs already produced.
        stale_temp: list[str] = []
        if "temperature_K" in clean or "temperature_K" in removals:
            new_temp = (self.project.experiment()
                        if hasattr(self.project, "experiment") else {}
                        ).get("temperature_K")
            stale_temp = _stale_temperature_deliveries(self.project, new_temp)
        note = ("merged into context.json experiment; null values remove "
                "keys (unknown facts stay absent - the NEXT write_outputs "
                "then fills the publication CIF's matching slots with '?', "
                "never copying a SHELXL default forward as if it were "
                "measured). Takes effect on the next run_shelxl (TEMP/SIZE "
                "cards) and the next write_outputs (_exptl_*/_diffrn_*); "
                "does not retroactively change a final.cif already written "
                "to disk.")
        if stale_temp:
            note += (" STALE DELIVERY: " + ", ".join(stale_temp) +
                     " still show the pre-change temperature - re-run "
                     "write_outputs to regenerate them.")
        # radiation touched -> the absorption-edge statement belongs in THIS
        # return, not only in a heavy-site audit somebody may never call
        touched_radiation = ("instrument" in clean
                             or any(r.split(".")[0] == "instrument"
                                    for r in removals))
        return ToolResult(ok=True, summary={
            "recorded": {k: v for k, v in clean.items()
                         if k != "provenance"},
            **({"removed": removed} if removed else {}),
            **({"remove_requested_but_absent":
                [r for r in removals if r not in removed]}
               if len(removed) != len(removals) else {}),
            "provenance": entry,
            **({"stale_deliveries": stale_temp} if stale_temp else {}),
            **({"absorption_edge": self._absorption_edge(ctx)}
               if touched_radiation else {}),
            "note": note})

    def _absorption_edge(self, ctx: ToolContext,
                         wavelength: float | None = None,
                         wavelength_source: str | None = None,
                         ) -> dict[str, Any]:
        """The X-ray absorption-edge statement at the wavelength this call
        just put on the record, against the elements the session already
        declares (T1.7a).

        ka1: lambda sat ON the Zr K edge (f' = -9 e, a Zr site scattering
        like ~31 e) and both arms found out only when they happened to
        call audit_heavy_sites, after R-vs-Z ladders that fact voids. The
        wavelength is known here, at set_experiment time - so is the
        SFAC list - so the warning is issued here. Shared implementation
        with audit_heavy_sites (refine/tools_heavysites.py); it states
        explicitly when it cannot run instead of staying silent."""
        from .tools_heavysites import project_absorption_edge_brief
        ses = getattr(ctx, "session", None) or getattr(self.project,
                                                       "session", None)
        try:
            return project_absorption_edge_brief(
                self.project, ses, wavelength=wavelength,
                wavelength_source=wavelength_source)
        except Exception as e:  # noqa: BLE001 - a side note must not fail
            return {"status": "unavailable",
                    "error": f"{type(e).__name__}: {e}",
                    "statement": ("the absorption-edge check could not run "
                                  "- this is not a 'no edge' verdict; "
                                  "audit_heavy_sites reports the same "
                                  "physics")}

    def _import_from_context(self, ctx: ToolContext, prov: str) -> ToolResult:
        """set_experiment() with no arguments: adopt the `experiment` block
        the project-root context.json already carries.

        pa1 L3 runs shipped exactly this block (runner-written: instrument
        source, temperature, crystal colour) and it already flowed into
        TEMP cards and _exptl_* silently - yet 5/8 L3 agents re-keyed the
        same facts through set_experiment after checkcif flagged metadata,
        one re-transcribed a non-ASCII source string by hand, and every one
        of them wrote 'project context.json supplied by the user' as the
        provenance. This makes the import visible and auditable: the
        block is normalised to the schema (types coerced, unknown keys
        reported, IUCr vocabulary checked), the wavelength named in the
        file is compared with the data, and the provenance trail records
        the import once. Explicit experiment= values always win."""
        p = self.project
        path = p.dir / "context.json"
        raw = dict((p.context or {}).get("experiment") or {})
        old_prov = raw.pop("provenance", None)
        model_exp = dict(getattr(p, "_model_experiment", {}) or {})
        if (getattr(getattr(p, "session", None), "_crystalpilot_data_revision", None)
                and "experiment" in p.context):
            model_exp = {}
        if not raw:
            where = (f"{path.name} has no `experiment` block"
                     if path.exists() else "no context.json in the project "
                                           "root")
            return ToolResult(ok=True, summary={
                "imported_from_context_json": {},
                **({"from_start_model": model_exp} if model_exp else {}),
                "absorption_edge": self._absorption_edge(ctx),
                "note": (f"nothing to import: {where}. Record known facts "
                         "explicitly - set_experiment(experiment={...}, "
                         "provenance='...'); unknown facts stay absent and "
                         "the publication CIF carries '?'.")})
        clean, ignored, warnings = _normalise_context_experiment(raw)
        imported = _flatten_experiment(clean)
        # radiation cross-check: the file names a wavelength in free text
        # ('Cu, 1.54178 A', 'synchrotron lambda = 0.68883 A'); the CIF
        # takes the CELL-line wavelength of the data - they must agree
        lam_ctx = _wavelength_hint(raw)
        ses = getattr(ctx, "session", None) or getattr(p, "session", None)
        ds = getattr(ses, "dataset", None)
        lam_data = (float(ds.wavelength)
                    if ds is not None and getattr(ds, "wavelength", None)
                    else None)
        radiation: dict[str, Any] | None = None
        if lam_ctx is not None or lam_data is not None:
            radiation = {"context_json_A": lam_ctx, "data_A": lam_data}
            if lam_ctx is not None and lam_data is not None:
                agrees = abs(lam_ctx - lam_data) <= 0.001
                radiation["agrees"] = agrees
                if not agrees:
                    warnings.append(
                        f"context.json names lambda = {lam_ctx} A but the "
                        f"reflection data / CELL line carry {lam_data} A - "
                        "the CIF takes the CELL wavelength; resolve which "
                        "is right before delivery")
        src = (clean.get("instrument") or {}).get("source")
        if isinstance(src, str) and any(ord(ch) > 127 for ch in src):
            warnings.append(
                f"instrument.source {src!r} is not ASCII: the CIF assembler "
                "transliterates it, but checkCIF reads _diffrn_source best "
                "as an IUCr-style ASCII phrase ('synchrotron', 'sealed "
                "X-ray tube', 'rotating-anode X-ray tube') - override with "
                "set_experiment(experiment={'instrument': {'source': ...}}) "
                "if you want that")
        marker = "set_experiment(): imported from context.json"
        recorded = False
        if imported and marker not in (old_prov or ""):
            stamp = time.strftime("%Y-%m-%d")
            entry = (f"{stamp} {marker} - fields "
                     f"{', '.join(sorted(imported))}"
                     + (f"; {prov}" if prov else ""))
            clean["provenance"] = f"{old_prov}\n{entry}" if old_prov else entry
            recorded = True
        if imported:
            from .tools_frames import _update_context
            _update_context(p, {"experiment": clean})
        # the wavelength the data carries is the one the CIF and both
        # engines use; the free-text one is the fallback when there is no
        # data yet (this call can happen before ingest)
        return ToolResult(ok=True, summary={
            "imported_from_context_json": imported,
            **({"ignored_keys": ignored} if ignored else {}),
            **({"warnings": warnings} if warnings else {}),
            **({"from_start_model": model_exp} if model_exp else {}),
            **({"radiation_check": radiation} if radiation else {}),
            "absorption_edge": self._absorption_edge(
                ctx, lam_data or lam_ctx,
                "dataset (CELL / export metadata)" if lam_data else
                "context.json experiment free text "
                "(instrument.source / radiation)"),
            "effective": (p.experiment() if hasattr(p, "experiment")
                          else clean),
            "provenance_recorded": recorded,
            "note": ("context.json experiment values apply automatically "
                     "(TEMP/SIZE cards in every run_shelxl job, _exptl_*/"
                     "_diffrn_* in the publication CIF); this call "
                     "normalised them and put the import on the provenance "
                     "trail. Explicit set_experiment(experiment={...}) "
                     "values override the file; null removes a key.")})


def _coerce_experiment_value(t: Any, v: Any) -> Any:
    if t in (float, int):
        return t(v)
    if t is list:
        if isinstance(v, (list, tuple)):
            return list(v)
        raise TypeError("expected a list")
    if t is str:
        return v if isinstance(v, str) else str(v)
    return t(v)


def _normalise_context_experiment(raw: dict[str, Any]) -> tuple[
        dict[str, Any], list[str], list[str]]:
    """Coerce a hand/runner-written context.json experiment block to the
    canonical schema without failing: unknown keys are reported (they stay
    in the file, harmless), bad values are dropped with a warning."""
    clean: dict[str, Any] = {}
    ignored: list[str] = []
    warnings: list[str] = []
    for key, val in raw.items():
        spec = _EXPERIMENT_SCHEMA.get(key)
        if spec is None:
            ignored.append(key)
            continue
        if val is None:
            continue
        if isinstance(spec, dict):
            if not isinstance(val, dict):
                warnings.append(f"{key}: expected an object, ignored")
                continue
            sub: dict[str, Any] = {}
            for k2, v2 in val.items():
                t2 = spec.get(k2)
                if t2 is None:
                    ignored.append(f"{key}.{k2}")
                    continue
                if v2 is None:
                    continue
                try:
                    sub[k2] = _coerce_experiment_value(t2, v2)
                except (TypeError, ValueError):
                    warnings.append(f"{key}.{k2}={v2!r} is not "
                                    f"{t2.__name__}, ignored")
            if sub:
                clean[key] = sub
        else:
            try:
                clean[key] = _coerce_experiment_value(spec, val)
            except (TypeError, ValueError):
                warnings.append(f"{key}={val!r} is not {spec.__name__}, "
                                "ignored")
    ab = clean.get("absorption") or {}
    if "type" in ab and ab["type"] not in _ABSORPT_TYPES:
        warnings.append(
            f"absorption.type {ab['type']!r} is not an IUCr keyword "
            f"({sorted(_ABSORPT_TYPES)}) - ignored; re-record it with "
            "set_experiment(experiment={'absorption': {'type': ...}})")
        ab.pop("type")
        if not ab:
            clean.pop("absorption", None)
    cr = clean.get("crystal") or {}
    if cr.get("size_mm") is not None:
        try:
            sz = [float(x) for x in cr["size_mm"]]
            assert len(sz) == 3 and all(0 < x < 5 for x in sz)
            cr["size_mm"] = sz
        except (TypeError, ValueError, AssertionError):
            warnings.append("crystal.size_mm must be 3 positive mm values "
                            "- ignored")
            cr.pop("size_mm")
            if not cr:
                clean.pop("crystal", None)
    return clean, ignored, warnings


def _flatten_experiment(exp: dict[str, Any]) -> dict[str, Any]:
    """{'crystal': {'colour': 'green'}, 'temperature_K': 173.0} ->
    {'crystal.colour': 'green', 'temperature_K': 173.0}."""
    out: dict[str, Any] = {}
    for k, v in exp.items():
        if k == "provenance":
            continue
        if isinstance(v, dict):
            for k2, v2 in v.items():
                out[f"{k}.{k2}"] = v2
        else:
            out[k] = v
    return out


_WAVELENGTH_IN_TEXT = re.compile(r"(?<![\d.])([0-3]\.\d{3,6})(?![\d])")


def _wavelength_hint(raw: dict[str, Any]) -> float | None:
    """A wavelength named anywhere in the experiment block: dedicated keys
    (wavelength_A / wavelength / radiation, numeric or text) or the
    instrument.source / instrument.radiation free text."""
    cands: list[Any] = [raw.get("wavelength_A"), raw.get("wavelength"),
                        raw.get("radiation")]
    inst = raw.get("instrument")
    if isinstance(inst, dict):
        cands += [inst.get("wavelength_A"), inst.get("wavelength"),
                  inst.get("radiation"), inst.get("source")]
    for c in cands:
        if c is None:
            continue
        if isinstance(c, (int, float)) and 0.1 < float(c) < 3.0:
            return float(c)
        if isinstance(c, str):
            m = _WAVELENGTH_IN_TEXT.search(c)
            if m:
                return float(m.group(1))
    return None


def _cif_experiment_block(cif_path: Path) -> dict[str, Any]:
    """Pull honest experimental metadata out of the source CIF into the
    canonical context.json `experiment` schema the publication assembler
    consumes (temperature_K / crystal{description,colour,size_mm} /
    instrument{source,diffractometer,method} / absorption{type,t_min,t_max})."""
    text = cif_path.read_text(encoding="utf-8", errors="replace")
    out: dict[str, Any] = {}
    t = (_cif_float(text, "_diffrn_ambient_temperature")
         or _cif_float(text, "_cell_measurement_temperature"))
    if t:
        out["temperature_K"] = t
    crystal: dict[str, Any] = {}
    for tag, key in (("_exptl_crystal_description", "description"),
                     ("_exptl_crystal_colour", "colour")):
        v = _cif_value(text, tag)
        if v:
            crystal[key] = v
    sizes = [_cif_float(text, f"_exptl_crystal_size_{k}")
             for k in ("max", "mid", "min")]
    if all(s is not None for s in sizes):
        crystal["size_mm"] = sizes
    if crystal:
        out["crystal"] = crystal
    absorption: dict[str, Any] = {}
    v = _cif_value(text, "_exptl_absorpt_correction_type")
    if v:
        absorption["type"] = v
    for tag, key in (("_exptl_absorpt_correction_T_min", "t_min"),
                     ("_exptl_absorpt_correction_T_max", "t_max")):
        f = _cif_float(text, tag)
        if f is not None:
            absorption[key] = f
    if absorption:
        out["absorption"] = absorption
    instrument: dict[str, Any] = {}
    for tag, key in (("_diffrn_source", "source"),
                     ("_diffrn_measurement_device_type", "diffractometer"),
                     ("_diffrn_measurement_method", "method")):
        v = _cif_value(text, tag)
        if v:
            instrument[key] = v
    if instrument:
        out["instrument"] = instrument
    if out:
        out["provenance"] = f"imported from {cif_path.name}"
    return out


# ==========================================================================
# reflection-data audit: twin symptoms, absences, duplicate consistency
# ==========================================================================

