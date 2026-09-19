"""Minimal, dependable CIF writer for solved/refined structures.

Written by hand (not via cctbx cif export) so the emitted tags are fully controlled
and stable for downstream validation/viewers.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from cctbx import adptbx


def _formula_sum(xs, z: int | None = None) -> str:
    """Occupancy-weighted formula per formula unit (cell content / Z)."""
    counts: dict[str, float] = {}
    div = float(z) if z and z > 0 else 1.0
    for sc in xs.scatterers():
        el = sc.scattering_type.strip().capitalize()
        counts[el] = counts.get(el, 0.0) + sc.occupancy * sc.multiplicity() / div
    parts = []
    for el in sorted(counts, key=lambda e: (e != "C", e != "H", e)):
        n = counts[el]
        parts.append(f"{el}{n:.2f}".rstrip("0").rstrip(".")
                     if abs(n - round(n)) > 0.05 else f"{el}{int(round(n))}")
    return " ".join(parts)


def structure_to_cif(xs, path: Path, *, wavelength: float | None = None,
                     stats: dict[str, Any] | None = None,
                     mask_info: dict[str, Any] | None = None,
                     data_name: str = "crystalpilot",
                     z: int | None = None) -> Path:
    uc = xs.unit_cell()
    sg = xs.space_group()
    a, b, c, al, be, ga = uc.parameters()

    lines: list[str] = [f"data_{data_name}", ""]
    push = lines.append
    push("_audit_creation_method        'CrystalPilot'")
    push(f"_chemical_formula_sum         '{_formula_sum(xs, z)}'")
    zz = int(z) if z and z > 0 else 1
    push(f"_cell_formula_units_Z         {zz}")
    # Z from the node's ZERR when known: the delivery coherence check
    # compares final.res ZERR against this tag and a hard-coded 1 sent
    # pa2 cage-l0-r2 through four write_outputs retries
    push("# formula counts are per formula unit (cell content / Z); "
         "occupancy-weighted"
         if zz != 1 else
         "# formula counts are per unit cell (Z=1 basis); occupancy-weighted")
    if wavelength:
        push(f"_diffrn_radiation_wavelength  {wavelength:.5f}")
    push(f"_cell_length_a                {a:.4f}")
    push(f"_cell_length_b                {b:.4f}")
    push(f"_cell_length_c                {c:.4f}")
    push(f"_cell_angle_alpha             {al:.3f}")
    push(f"_cell_angle_beta              {be:.3f}")
    push(f"_cell_angle_gamma             {ga:.3f}")
    push(f"_cell_volume                  {uc.volume():.2f}")
    # Symmetry NAMES must be true for the operator loop below, in every
    # setting: `symbol_and_number().split("(")[0]` used to drop cctbx's
    # change-of-basis suffix, so an origin-shifted SHELXT solution
    # (reg1-ext2 hsl: P 21 21 21 (a+1/4,b,c-1/4)) was published as plain
    # 'P 21 21 21' beside SHIFTED operators - unparseable for cctbx and
    # PLATON alert 120. See crystalpilot/io/cif_symmetry for the decision.
    from ..io.cif_symmetry import cif_symmetry_block
    sym_lines, _setting = cif_symmetry_block(sg)
    for ln in sym_lines:
        push(ln)
    push("")
    push("loop_")
    push("  _space_group_symop_operation_xyz")
    for op in sg.all_ops():
        push(f"  '{op.as_xyz()}'")
    push("")
    if stats:
        mapping = {
            "r1_strong": "_refine_ls_R_factor_gt",
            "r1_all": "_refine_ls_R_factor_all",
            "wr2": "_refine_ls_wR_factor_ref",
            "goof": "_refine_ls_goodness_of_fit_ref",
            "n_reflections": "_refine_ls_number_reflns",
            "n_params": "_refine_ls_number_parameters",
            "diff_map_max": "_refine_diff_density_max",
            "diff_map_min": "_refine_diff_density_min",
        }
        for key, tag in mapping.items():
            if stats.get(key) is not None:
                push(f"{tag:<34}{stats[key]}")
        push("")
    if mask_info:
        push("# Disordered solvent handled by BYPASS-style masking (cf. SQUEEZE):")
        push(f"_platon_squeeze_void_nr           {mask_info.get('n_voids_masked', '?')}")
        push(f"# total solvent electrons/cell:   "
             f"{mask_info.get('total_solvent_electrons_per_cell', '?')}")
        push(f"# solvent-accessible volume:      "
             f"{mask_info.get('solvent_volume_pct_of_cell', '?')} % of cell")
        push("")
    push("loop_")
    for tag in ("label", "type_symbol", "fract_x", "fract_y", "fract_z",
                "U_iso_or_equiv", "adp_type", "occupancy"):
        push(f"  _atom_site_{tag}")
    # duplicate-label safety net: a CIF with two identical _atom_site_label
    # rows is invalid for every downstream consumer, and the SHELX
    # round-trip silently collapses the pair (r22 live: two C29X). Rename
    # later occurrences deterministically and say so.
    seen_labels: dict[str, int] = {}
    display: list[str] = []
    renamed: list[str] = []
    for sc in xs.scatterers():
        lbl = sc.label
        if lbl in seen_labels:
            n = seen_labels[lbl] = seen_labels[lbl] + 1
            cand = f"{lbl}{chr(ord('a') + n - 1)}"
            while cand in seen_labels:
                n += 1
                cand = f"{lbl}{chr(ord('a') + n - 1)}"
            renamed.append(f"{lbl}->{cand}")
            lbl = cand
        seen_labels[lbl] = 0
        display.append(lbl)
    if renamed:
        push(f"# WARNING duplicate atom labels renamed for CIF validity: "
             f"{', '.join(renamed)}")
    aniso_rows = []
    for sc, lbl in zip(xs.scatterers(), display):
        el = sc.scattering_type.strip().capitalize()
        x, y, z = sc.site
        if sc.flags.use_u_aniso():
            u_eq = adptbx.u_star_as_u_iso(uc, sc.u_star)
            adp = "Uani"
            u_cif = adptbx.u_star_as_u_cif(uc, sc.u_star)
            aniso_rows.append((lbl, u_cif))
        else:
            u_eq, adp = sc.u_iso, "Uiso"
        push(f"  {lbl:<8}{el:<4}{x:9.5f} {y:9.5f} {z:9.5f} "
             f"{u_eq:8.4f} {adp} {sc.occupancy:6.3f}")
    if aniso_rows:
        push("")
        push("loop_")
        for tag in ("label", "U_11", "U_22", "U_33", "U_23", "U_13", "U_12"):
            push(f"  _atom_site_aniso_{tag}")
        for label, u in aniso_rows:
            u11, u22, u33, u12, u13, u23 = u
            push(f"  {label:<8}{u11:8.4f} {u22:8.4f} {u33:8.4f} "
                 f"{u23:8.4f} {u13:8.4f} {u12:8.4f}")
    path = Path(path)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
