"""Reflection-free CIF documents: geometry and reported facts, never observations."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

STRUCTURE_ONLY_PRECONDITION = (
    "This is a read-only structure-only project: no observed reflections are "
    "attached. Model edits, refinement, Fo-Fc maps and residual-electron counts "
    "are unavailable. Explicitly import a real HKL/FCF with import_cif_model "
    "(cif_path=the source CIF, hkl_path=the observed data) to enable refinement."
)


def structure_capabilities(structure_only: bool) -> dict[str, bool]:
    return {
        "scene": True, "grow": True, "pack": True,
        "inspect_model": True, "geometry": True, "model_symmetry": True,
        "topology": True, "interactions": True, "geometric_voids": True,
        "reflections": not structure_only, "edit_model": not structure_only,
        "refinement": not structure_only, "fofc": not structure_only,
        "residual_electrons": not structure_only,
    }


def is_structure_only_node(meta: dict[str, Any]) -> bool:
    return bool(meta.get("structure_only") or meta.get("mode") == "structure_only"
                or meta.get("tool") == "import_structure_only")


def project_mode_info(project_dir: str | Path, ref: str | None = None) -> dict[str, Any]:
    """Cheap node-authoritative capabilities for polling routes; no engine load."""
    import json
    from .nodes import NodeStore

    directory = Path(project_dir)
    if not directory.is_dir():
        raise ValueError(f"Project directory does not exist: {directory}")
    store = NodeStore(directory)
    state = store.state()
    node = (store.resolve(ref) if ref not in (None, "active")
            else state.get("active_node"))
    meta = store.node_meta(node) if node else {}
    if node:
        structure_only = is_structure_only_node(meta)
        mode = "structure_only" if structure_only else "refinement"
    else:
        context_path = directory / "context.json"
        context = (json.loads(context_path.read_text(encoding="utf-8"))
                   if context_path.exists() else {})
        structure_only = context.get("mode") == "structure_only"
        mode = "structure_only" if structure_only else "awaiting_data"
    binding_required = bool(node and not structure_only and not meta.get("data_revision"))
    capabilities = structure_capabilities(structure_only or binding_required)
    if node is None:
        capabilities = {name: False for name in capabilities}
    source_state = {"node": node, "revision": meta.get("revision"),
                    "data_revision": meta.get("data_revision")}
    return {"mode": mode, "read_only": structure_only, "binding_required": binding_required,
            "capabilities": capabilities, "source_state": source_state,
            "canonical_model": (meta.get("canonical_model") or "model.res") if node else None,
            "block_name": meta.get("block_name"),
            "unknown_adp_labels": meta.get("unknown_adp_labels"),
            "node": node, "revision": meta.get("revision"),
            "source": "node" if node else "context"}


@dataclass
class StructureDocument:
    structure: Any
    source: Path
    block_name: str
    reported_reference: dict[str, Any]
    wavelength: float | None = None
    z: int | None = None
    parts: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    cif_block_text: str = ""
    unknown_adp_labels: list[str] = field(default_factory=list)


def load_model_document(model_path: str | Path, *, block_name: str | None = None):
    """Load a node's declared canonical model, or a standalone CIF/RES.

    Legacy callers may still name model.res for a CIF-only node. Its
    canonical_model metadata redirects that read without a SHELX round-trip.
    """
    import json

    path = Path(model_path)
    meta_path = path.with_name("node.json")
    meta = (json.loads(meta_path.read_text(encoding="utf-8"))
            if meta_path.exists() else {})
    if path.name in ("model.res", "model.cif"):
        canonical = meta.get("canonical_model")
        if canonical is not None:
            if canonical not in ("model.res", "model.cif"):
                raise ValueError(f"Unsupported canonical model filename: {canonical!r}")
            path = path.with_name(canonical)
        elif not path.exists() and path.with_suffix(".cif").exists():
            path = path.with_suffix(".cif")
    if path.suffix.lower() == ".cif":
        selected = block_name or meta.get("block_name")
        if selected is None and meta.get("canonical_model") == "model.cif":
            selected = (meta.get("params") or {}).get("data_block")
        return load_structure_document(path, block_name=selected)
    from ..io.shelx_model import load_res_model
    parsed = load_res_model(path)
    if parsed.parts:
        parts = {label.upper(): part for label, part in parsed.parts.items()}
        parsed.parts = {sc.label: parts[sc.label.upper()]
                        for sc in parsed.structure.scatterers()
                        if sc.label.upper() in parts}
    return parsed


def commit_structure_document(store, session, document: StructureDocument) -> dict[str, Any]:
    with store.staged_node() as stage:
        return _serialize_structure_document(store, session, document, stage)


def _serialize_structure_document(store, session, document, stage) -> dict[str, Any]:
    """Initial geometry-only node using NodeStore's existing disk schema.

    The selected CIF block is canonical: original atom labels, explicit
    operators and ADPs never pass through SHELX serialization. Reported
    refinement values in that block remain reference metadata, not a
    current calculation. No RES file or observed dataset is required.
    """
    import json
    import time

    state, node, directory, _ = stage
    if state.get("active_node") or state.get("seq", 0):
        raise ValueError("A structure-only import requires a project without model nodes")
    branch = state.get("active_branch") or "main"
    if directory.exists() and any(directory.iterdir()):
        raise ValueError("Existing model-node files are not overwritten; choose a new project")
    if not document.cif_block_text:
        raise ValueError("Load the selected CIF block before creating a structure node")
    model = session.model
    parts = dict(document.parts)
    session.flags["parts_extra"] = parts
    session.flags["unknown_adp_labels"] = list(document.unknown_adp_labels)
    counts: dict[str, int] = {}
    for sc in model.scatterers():
        element = sc.scattering_type.strip().capitalize()
        counts[element] = counts.get(element, 0) + 1
    meta = {
        "id": node, "parent": None, "revision": 1,
        "branch": branch, "ts": time.time(), "tool": "import_structure_only",
        "params": {"source_cif": "source.cif", "data_block": document.block_name},
        "note": "Read-only CIF geometry; no observed reflections. " + "; ".join(document.notes),
        "mode": "structure_only", "structure_only": True, "read_only": True,
        "canonical_model": "model.cif", "block_name": document.block_name,
        "unknown_adp_labels": list(document.unknown_adp_labels),
        "capabilities": structure_capabilities(True),
        "metrics": None, "metrics_current": False, "data": None,
        "reported_reference": session.flags.get("reported_reference"),
        "model": {"n_atoms": model.scatterers().size(), "element_counts": counts,
                  "reported_z": document.z},
        "restraints": [], "weights": None, "scale_k": None,
        "mask": None, "peaks": None, "hydrogens": {"present": False},
        "disorder_groups": [], "parts_extra": parts, "twin": None,
        "label_renames": {},
    }
    (directory / "model.cif").write_text(document.cif_block_text, encoding="utf-8")
    (directory / "node.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    state.update({"active_node": node, "active_branch": branch, "seq": 1})
    state["branches"][branch] = node
    store.publish_node(stage, meta, session)
    return meta


_REPORTED_TAGS = {
    "r1": "_refine_ls_R_factor_gt",
    "r1_all": "_refine_ls_R_factor_all",
    "wr2": "_refine_ls_wR_factor_ref",
    "goof": "_refine_ls_goodness_of_fit_ref",
    "diff_map_max": "_refine_diff_density_max",
    "diff_map_min": "_refine_diff_density_min",
    "n_reflections": "_refine_ls_number_reflns",
    "temperature_K": "_diffrn_ambient_temperature",
    "chemical_formula_sum": "_chemical_formula_sum",
    "doi": "_journal_paper_doi",
}


def load_structure_document(cif_path: str | Path, *,
                            block_name: str | None = None) -> StructureDocument:
    """Read a CIF atom loop with gemmi; explicit operators retain their setting.

    Multi-structure deposits require a block name; metadata-only blocks are
    ignored. The original file is never rewritten, including DDLm input.
    """
    import gemmi
    from cctbx import adptbx, crystal, sgtbx, xray

    from ..io.cif_compat import normalize_ddlm_tags

    source = Path(cif_path).resolve()
    text = normalize_ddlm_tags(source.read_text(encoding="utf-8-sig"))
    cif = gemmi.cif.read_string(text)
    blocks = [b for b in cif if len(b.find_values("_atom_site_fract_x"))]
    if block_name is not None:
        blocks = [b for b in blocks if b.name == block_name]
    if len(blocks) != 1:
        available = [b.name for b in cif
                     if len(b.find_values("_atom_site_fract_x"))]
        raise ValueError("Choose one CIF structure using block_name; "
                         f"available atom-site blocks: {available}")
    block = blocks[0]

    def value(tag):
        raw = block.find_value(tag)
        if raw is None or raw in ("?", "."):
            return None
        return gemmi.cif.as_string(raw)

    def number(tag):
        raw = block.find_value(tag)
        if raw is None:
            return None
        val = float(gemmi.cif.as_number(raw))
        return val if math.isfinite(val) else None

    cell = [number("_cell_" + name) for name in
            ("length_a", "length_b", "length_c",
             "angle_alpha", "angle_beta", "angle_gamma")]
    if any(v is None for v in cell):
        raise ValueError("CIF requires all six finite unit-cell parameters")
    if any(v <= 0 for v in cell[:3]) or any(not 0 < v < 180 for v in cell[3:]):
        raise ValueError("CIF unit-cell lengths/angles are invalid")
    small = gemmi.make_small_structure_from_block(block)
    ops = list(small.symops)
    if ops:
        group = sgtbx.space_group()
        for op in ops:
            group.expand_smx(sgtbx.rt_mx(op if isinstance(op, str) else op.triplet()))
        sym = crystal.symmetry(unit_cell=cell, space_group=group)
    else:
        hall = value("_space_group_name_Hall") or value("_symmetry_space_group_name_Hall")
        hm = value("_space_group_name_H-M_alt") or value("_symmetry_space_group_name_H-M")
        if hall:
            sym = crystal.symmetry(unit_cell=cell, space_group=sgtbx.space_group(hall))
        elif hm:
            sym = crystal.symmetry(unit_cell=cell, space_group_symbol=hm)
        else:
            raise ValueError("CIF needs explicit symmetry operators or a Hall/H-M symbol; P1 is not assumed")
    xs = xray.structure(crystal_symmetry=sym)
    labels: set[str] = set()
    notes: list[str] = []
    occ_values = list(block.find_values("_atom_site_occupancy"))

    def column_numbers(tag):
        out = []
        for raw in block.find_values(tag):
            val = float(gemmi.cif.as_number(raw))
            out.append(val if math.isfinite(val) else None)
        return out

    iso_u = column_numbers("_atom_site_U_iso_or_equiv")
    iso_b = column_numbers("_atom_site_B_iso_or_equiv")
    aniso_labels = [gemmi.cif.as_string(v) for v in
                   block.find_values("_atom_site_aniso_label")]
    aniso_by_label = {}
    for kind in ("U", "B"):
        columns = [column_numbers(f"_atom_site_aniso_{kind}_{ij}")
                   for ij in ("11", "22", "33", "12", "13", "23")]
        for row, label in enumerate(aniso_labels):
            if all(row < len(col) and col[row] is not None for col in columns):
                scale = 1.0 if kind == "U" else 1.0 / (8 * math.pi ** 2)
                aniso_by_label.setdefault(label, tuple(col[row] * scale for col in columns))
    unknown_adp_labels = []
    for i, site in enumerate(small.sites):
        label = site.label.strip()
        if not label or label.upper() in labels:
            raise ValueError(f"CIF atom labels must be unique (case insensitive): {label!r}")
        labels.add(label.upper())
        element = site.element.name
        if site.element.atomic_number == 0:
            raise ValueError(f"Unsupported/unknown element for {label}: {site.type_symbol!r}")
        xyz = (site.fract.x, site.fract.y, site.fract.z)
        if not all(math.isfinite(v) for v in xyz):
            raise ValueError(f"Missing/non-finite fractional coordinates for {label}")
        if occ_values and occ_values[i] in ("?", "."):
            raise ValueError(f"Unknown occupancy for {label}; supply an explicit occupancy")
        occ = float(site.occ)
        if not math.isfinite(occ) or occ < 0:
            raise ValueError(f"Invalid occupancy for {label}")
        u_iso = iso_u[i] if i < len(iso_u) else None
        if u_iso is None and i < len(iso_b) and iso_b[i] is not None:
            u_iso = iso_b[i] / (8 * math.pi ** 2)
        u_cif = aniso_by_label.get(label)
        if u_iso is None and u_cif is None:
            unknown_adp_labels.append(label)
            notes.append(f"{label}: ADP not reported; zero is a geometry-only storage placeholder")
        sc = xray.scatterer(label=label, scattering_type=element,
                            site=xyz, occupancy=occ, u=u_iso if u_iso is not None else 0.0)
        if u_cif is not None:
            sc.u_star = adptbx.u_cif_as_u_star(xs.unit_cell(), u_cif)
            sc.flags.set_use_u_aniso(True)
            sc.flags.set_use_u_iso(False)
        xs.add_scatterer(sc)
    if not labels:
        raise ValueError("CIF contains no atom sites")
    xs.scattering_type_registry(table="it1992")
    reported = {name: value(tag) for name, tag in _REPORTED_TAGS.items()
                if value(tag) is not None}
    reported = {"source": source.name, "block_name": block.name,
                "status": "reported_reference", "values": reported,
                "note": "Published CIF values, not calculated for the current project"}
    groups = list(block.find_values("_atom_site_disorder_group"))
    parts = {site.label: int(gemmi.cif.as_string(raw))
             for site, raw in zip(small.sites, groups)
             if raw not in ("?", ".") and gemmi.cif.as_string(raw).lstrip("-").isdigit()}
    z_value = number("_cell_formula_units_Z")
    return StructureDocument(
        structure=xs, source=source, block_name=block.name,
        reported_reference=reported, wavelength=number("_diffrn_radiation_wavelength"),
        z=int(z_value) if z_value and z_value.is_integer() and z_value > 0 else None,
        parts=parts, notes=notes, cif_block_text=block.as_string(),
        unknown_adp_labels=unknown_adp_labels)
