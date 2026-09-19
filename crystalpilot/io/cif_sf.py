"""Structure-factor CIF adapter: .fcf / IUCr "hkl" supplements / COD hkl-mirror files.

These files are CIF documents carrying a ``_refln`` loop with *measured* structure
factors (``_refln_F_squared_meas`` + sigma, occasionally ``_refln_F_meas``). They are
what IUCr journals publish as the "hkl" supplementary block and what the COD mirrors
under https://www.crystallography.net/cod/hkl/. SHELX .fcf files are the same format.

Olex2's IUCr-style export is also handled: it carries no ``_shelx_hkl_file`` and no
``_refln`` loop of its own, but embeds the whole .fcf - a complete CIF document, its
own ``data_`` header and all - as the text value of ``_iucr_refine_fcf_details``. See
``_find_refln_block``.

Produces the engine's uniform ReflectionDataset, mirroring shelx.load_shelx_dataset:
intensities are returned on a P1 basis and any symmetry claimed by the file goes into
``symmetry_hint``. Data from refinement fcf files is usually MERGED (SHELX LIST 4);
``instrument_meta["merged"]`` records this (detected via duplicate-index heuristic,
overridable). Cell/symmetry/wavelength come from the sf file itself with the embedded
fcf's host block and then the reference structure CIF as fallbacks; the composition
hint is read from ``_chemical_formula_sum`` / ``_cell_formula_units_Z`` of whichever
of those two carries the structure.
"""
from __future__ import annotations

import re
from pathlib import Path

import iotbx.cif
from cctbx import crystal, miller, uctbx
from cctbx.array_family import flex

from ..core.dataset import CompositionHint, ReflectionDataset

_FORMULA_TOKEN_RE = re.compile(r"([A-Z][a-z]?)\s*([0-9]*\.?[0-9]*)")


def _to_float(value) -> float | None:
    """CIF numeric value -> float, stripping a trailing esd like '7.2649(3)'."""
    if value is None:
        return None
    s = str(value).strip()
    if s in ("", "?", "."):
        return None
    s = re.sub(r"\(.*?\)", "", s)
    try:
        return float(s)
    except ValueError:
        return None


def parse_formula_sum(formula: str) -> dict[str, float]:
    """'C12 H12 N2 O4' -> {'C': 12.0, 'H': 12.0, 'N': 2.0, 'O': 4.0} (per formula unit)."""
    out: dict[str, float] = {}
    for el, cnt in _FORMULA_TOKEN_RE.findall(formula.replace("'", " ")):
        out[el] = out.get(el, 0.0) + (float(cnt) if cnt else 1.0)
    return out


def _scalar(block, *tags):
    """First present scalar value among tags ('?'/'.' treated as absent)."""
    for tag in tags:
        v = block.get(tag)
        if v is None:
            continue
        s = str(v).strip()
        if s not in ("", "?", "."):
            return s
    return None


def _cell_from_block(block) -> tuple | None:
    vals = [_to_float(block.get(t)) for t in (
        "_cell_length_a", "_cell_length_b", "_cell_length_c",
        "_cell_angle_alpha", "_cell_angle_beta", "_cell_angle_gamma")]
    if any(v is None for v in vals):
        return None
    return tuple(vals)


def _space_group_from_block(block):
    """sgtbx.space_group from symop loop, Hall symbol, or H-M symbol (in that order)."""
    from cctbx import sgtbx

    for tag in ("_space_group_symop_operation_xyz", "_symmetry_equiv_pos_as_xyz"):
        ops = block.get(tag)
        if ops is not None and len(ops) > 0:
            sg = sgtbx.space_group()
            try:
                for op in ops:
                    sg.expand_smx(sgtbx.rt_mx(str(op)))
                return sg
            except (RuntimeError, ValueError):
                pass
    hall = _scalar(block, "_symmetry_space_group_name_Hall", "_space_group_name_Hall")
    if hall:
        try:
            return sgtbx.space_group(hall)
        except RuntimeError:
            pass
    hm = _scalar(block, "_symmetry_space_group_name_H-M", "_space_group_name_H-M_alt")
    if hm:
        try:
            return sgtbx.space_group_info(symbol=hm).group()
        except RuntimeError:
            pass
    return None


def _wavelength_from_block(block) -> float | None:
    return _to_float(block.get("_diffrn_radiation_wavelength"))


def _first_block_with(model, tag: str):
    for name, block in model.items():
        if block.get(tag) is not None:
            return name, block
    name = next(iter(model.keys()))
    return name, model[name]


#: IUCr tag under which Olex2 deposits the whole .fcf as a semicolon text
#: field. The value is itself a complete CIF document - `data_<name>` header,
#: symops, the _refln loop - so the reflections are invisible to any
#: block-level scan: a `data_` line inside a text field is content, not a
#: header, and the outer block honestly has no _refln loop, only a megabyte-
#: long string. 2026-09 survey: 4 of 13 shortlist files, and these carry no
#: _shelx_hkl_file at all, so this is their ONLY reflection source.
_EMBEDDED_FCF_TAG = "_iucr_refine_fcf_details"


def _find_refln_block(model):
    """(name, block, host_block) for the first block carrying a _refln loop.

    Falls back to the fcf document embedded in ``_iucr_refine_fcf_details``;
    ``host_block`` is then the outer structure block that carried it, whose
    cell/symmetry/wavelength/formula stand in for metadata the bare fcf omits.
    Returns (None, None, None) when the file holds no reflections anywhere.
    """
    for name, block in model.items():
        if block.get("_refln_index_h") is not None:
            return name, block, None
    for name, block in model.items():
        raw = block.get(_EMBEDDED_FCF_TAG)
        if not isinstance(raw, str) or "_refln_index_h" not in raw:
            continue
        inner = iotbx.cif.reader(input_string=raw).model()
        for inner_name, inner_block in inner.items():
            if inner_block.get("_refln_index_h") is not None:
                return (f"{name}:{_EMBEDDED_FCF_TAG}/{inner_name}",
                        inner_block, block)
    return None, None, None


def composition_from_ref_cif(block, source: str = "") -> CompositionHint | None:
    formula = _scalar(block, "_chemical_formula_sum")
    if not formula:
        return None
    elements = parse_formula_sum(formula)
    if not elements:
        return None
    z = _to_float(block.get("_cell_formula_units_Z"))
    return CompositionHint(elements=elements, z=z, source=source)


def load_cif_sf_dataset(sf_path: Path, ref_cif_path: Path | None = None,
                        cell: tuple | None = None, wavelength: float | None = None,
                        space_group=None, merged: bool | None = None) -> ReflectionDataset:
    """Load measured reflections from a structure-factor CIF (.fcf / COD .hkl).

    Metadata resolution order: explicit args > sf file header > reference CIF.
    `merged=None` auto-detects: a list without duplicate hkl entries (the normal
    fcf/LIST-4 case) is flagged merged; raw dumps with equivalents are not.
    """
    sf_path = Path(sf_path)
    model = iotbx.cif.reader(file_path=str(sf_path)).model()
    block_name, sf_block, host_block = _find_refln_block(model)
    if sf_block is None:
        raise ValueError(f"no _refln_index_h/k/l loop in {sf_path}")

    ref_block = None
    if ref_cif_path is not None:
        ref_model = iotbx.cif.reader(file_path=str(Path(ref_cif_path))).model()
        _, ref_block = _first_block_with(ref_model, "_atom_site_fract_x")

    # metadata fallback chain: the reflection block itself, then the structure
    # block that hosted it when it came out of an embedded fcf (a bare fcf
    # carries symops but often no cell/wavelength), then the reference CIF
    meta_blocks = [b for b in (sf_block, host_block, ref_block) if b is not None]
    if cell is None:
        cell = next((c for c in map(_cell_from_block, meta_blocks) if c), None)
    if cell is None:
        raise ValueError(f"unit cell not found in {sf_path} (pass cell= or ref_cif_path=)")
    if space_group is None:
        space_group = next(
            (g for g in map(_space_group_from_block, meta_blocks) if g), None)
    if wavelength is None:
        wavelength = next(
            (w for w in map(_wavelength_from_block, meta_blocks) if w), None)

    # --- refln loop -> flex arrays -------------------------------------------------
    h = sf_block.get("_refln_index_h")
    k = sf_block.get("_refln_index_k")
    l = sf_block.get("_refln_index_l")
    if h is None or k is None or l is None:
        raise ValueError(f"no _refln_index_h/k/l loop in {sf_path}")
    indices = flex.miller_index(
        [(int(float(a)), int(float(b)), int(float(c))) for a, b, c in zip(h, k, l)])

    i_meas = sf_block.get("_refln_F_squared_meas")
    sig = sf_block.get("_refln_F_squared_sigma")
    if i_meas is None:
        i_meas = sf_block.get("_refln_intensity_meas")
        sig = sf_block.get("_refln_intensity_sigma")
    if i_meas is not None:
        data = flex.double([float(x) for x in i_meas])
        sigmas = (flex.double([float(x) for x in sig]) if sig is not None
                  else flex.double(data.size(), 0.0))
    else:
        f_meas = sf_block.get("_refln_F_meas")
        f_sig = sf_block.get("_refln_F_sigma")
        if f_meas is None:
            raise ValueError(f"no measured reflection data (F^2, I or F) in {sf_path}")
        f = flex.double([float(x) for x in f_meas])
        fs = (flex.double([float(x) for x in f_sig]) if f_sig is not None
              else flex.double(f.size(), 0.0))
        data = f * f
        sigmas = 2.0 * flex.abs(f) * fs
    if data.size() != indices.size():
        raise ValueError(f"refln loop size mismatch in {sf_path}")

    if merged is None:
        merged = len(set(indices)) == len(indices)

    symmetry_hint = None
    if space_group is not None:
        symmetry_hint = crystal.symmetry(unit_cell=uctbx.unit_cell(cell),
                                         space_group=space_group)
    # Reflections carried cell-only (P1), matching shelx.load_shelx_dataset: symmetry
    # is determined/confirmed downstream.
    base_symm = crystal.symmetry(unit_cell=uctbx.unit_cell(cell), space_group_symbol="P1")
    mset = miller.set(crystal_symmetry=base_symm, indices=indices, anomalous_flag=True)
    intensities = miller.array(mset, data=data, sigmas=sigmas)
    intensities.set_observation_type_xray_intensity()

    # the formula lives on whichever block holds the structure: the reference
    # CIF when one was given, else the host of an embedded fcf
    comp_block, comp_source = ((ref_block, ref_cif_path) if ref_block is not None
                               else (host_block, sf_path))
    return ReflectionDataset(
        intensities=intensities,
        wavelength=wavelength,
        symmetry_hint=symmetry_hint,
        composition=(composition_from_ref_cif(comp_block, source=str(comp_source))
                     if comp_block is not None else None),
        source_files=[str(sf_path)] + ([str(ref_cif_path)] if ref_cif_path else []),
        instrument_meta={
            "merged": bool(merged),
            "format": "cif_sf",
            "data_block": str(block_name),
            "embedded_fcf": host_block is not None,
            "shelx_refln_list_code": _scalar(sf_block, "_shelx_refln_list_code"),
        },
    )


def write_hklf4(intensities, path: Path) -> dict:
    """Serialize a miller.array of intensities as SHELX HKLF4 (3I4,2F8.2).

    Values wider than the F8.2 field are uniformly scaled down (allowed:
    HKLF data are on an arbitrary scale); the applied factor is returned so
    callers can disclose it.
    """
    data = intensities.data()
    sigmas = intensities.sigmas()
    import math as _math
    peak = 0.0
    for v in data:
        peak = max(peak, abs(float(v)))
    if sigmas is not None:
        for v in sigmas:
            peak = max(peak, abs(float(v)))
    scale = 1.0
    if peak > 9999.99:
        scale = 9999.0 / peak
        scale = 10.0 ** _math.floor(_math.log10(scale))  # tidy power of 10
    lines = []
    for i, hkl in enumerate(intensities.indices()):
        v = float(data[i]) * scale
        s = float(sigmas[i]) * scale if sigmas is not None else 0.0
        lines.append("%4d%4d%4d%8.2f%8.2f" % (hkl[0], hkl[1], hkl[2], v, s))
    lines.append("%4d%4d%4d%8.2f%8.2f" % (0, 0, 0, 0.0, 0.0))
    Path(path).write_text("\n".join(lines) + "\n", encoding="ascii")
    return {"n_reflections": len(data), "scale_applied": scale}
