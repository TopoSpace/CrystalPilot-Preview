"""SHELX-format adapters: .hkl (HKLF4) reflection data and .ins/.res metadata.

Produces the engine's uniform ReflectionDataset. The .ins is used only as a metadata
source (cell, wavelength, composition); symmetry from it is treated as a *hint* that the
pipeline may confirm or override via its own space-group determination.
"""
from __future__ import annotations

import re
from pathlib import Path

from cctbx import crystal, miller, uctbx
from iotbx.shelx import hklf

from ..core.dataset import CompositionHint, ReflectionDataset

_ELEMENT_RE = re.compile(r"^[A-Z][a-z]?$")


def clean_hklf4(src: Path, dest: Path) -> dict:
    """Copy an HKLF4 file dropping physically-unusable rows: sigma <= 0 or
    non-finite F^2/sigma. Such rows crash smtbx weighting (SMTBX_ASSERT
    sigma > 0) and silently distort SHELXL weights - round-6 agents ended up
    hand-writing this exact filter, so the platform now does it at the
    dials.hkl -> crystal.hkl handoff. Kept rows are copied byte-identical.

    Returns counts: n_kept, n_dropped_sigma, n_dropped_nonfinite.
    """
    n_kept = n_sig = n_nan = 0
    out_lines: list[str] = []
    for raw in Path(src).read_text(encoding="utf-8",
                                   errors="replace").splitlines():
        line = raw.rstrip("\n")
        if len(line.rstrip()) < 12:
            out_lines.append(line)
            continue
        try:
            h, k, l = int(line[0:4]), int(line[4:8]), int(line[8:12])
            f2 = float(line[12:20])
            sig = float(line[20:28])
        except ValueError:
            out_lines.append(line)    # header/trailer junk: pass through
            continue
        if h == 0 and k == 0 and l == 0:
            out_lines.append(line)    # terminator (and anything after)
            continue
        if not (f2 == f2 and sig == sig and
                abs(f2) != float("inf") and abs(sig) != float("inf")):
            n_nan += 1
            continue
        if sig <= 0:
            n_sig += 1
            continue
        n_kept += 1
        out_lines.append(line)
    Path(dest).write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    return {"n_kept": n_kept, "n_dropped_sigma": n_sig,
            "n_dropped_nonfinite": n_nan}


def parse_ins_metadata(ins_path: Path) -> dict:
    """Extract cell, wavelength, Z, SFAC/UNIT composition, latt/symm cards from an ins/res."""
    meta: dict = {"symm": [], "sfac": [], "unit": [], "latt": None, "titl": ""}
    for raw_line in Path(ins_path).read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        u = line.upper()
        if u.startswith("TITL"):
            meta["titl"] = line[4:].strip()
        elif u.startswith("CELL"):
            parts = line.split()
            meta["wavelength"] = float(parts[1])
            meta["cell"] = tuple(float(x) for x in parts[2:8])
        elif u.startswith("ZERR"):
            meta["z"] = float(line.split()[1])
        elif u.startswith("LATT"):
            meta["latt"] = int(line.split()[1])
        elif u.startswith("SYMM"):
            meta["symm"].append(line[4:].strip())
        elif u.startswith("SFAC"):
            toks = line.split()[1:]
            meta["sfac"].extend(t.capitalize() for t in toks
                                if _ELEMENT_RE.match(t.capitalize()))
        elif u.startswith("UNIT"):
            meta["unit"] = [float(x) for x in line.split()[1:]]
        elif u.startswith("HKLF"):
            try:
                meta["hklf"] = int(float(line.split()[1]))
            except (IndexError, ValueError):
                meta["hklf"] = 4
            break
    return meta


def space_group_from_latt_symm(latt: int | None, symm_cards: list[str]):
    """Reconstruct the space group from SHELX LATT/SYMM cards (returns sgtbx.space_group)."""
    from cctbx import sgtbx

    sg = sgtbx.space_group()
    # LATT: 1=P 2=I 3=R(obverse) 4=F 5=A 6=B 7=C ; negative = non-centrosymmetric
    latt = latt if latt is not None else 1
    centric = latt > 0
    lat_symbol = {1: "P", 2: "I", 3: "R", 4: "F", 5: "A", 6: "B", 7: "C"}[abs(latt)]
    sg.expand_conventional_centring_type(lat_symbol)
    if centric:
        sg.expand_inv(sgtbx.tr_vec((0, 0, 0)))
    for card in symm_cards:
        sg.expand_smx(sgtbx.rt_mx(card.replace(" ", "")))
    return sg


def composition_from_meta(meta: dict) -> CompositionHint | None:
    if meta.get("sfac") and meta.get("unit") and len(meta["sfac"]) == len(meta["unit"]):
        z = meta.get("z") or 1.0
        # Placeholder detection: xia2/SHELXT template ins files carry fake UNIT
        # cards (e.g. "UNIT 2 2 2 2"). Rule of thumb: a real crystal packs ~1 non-H
        # atom per 18 A^3; if UNIT accounts for <20% of that, it is not credible.
        cell = meta.get("cell")
        if cell:
            from cctbx import uctbx
            volume = uctbx.unit_cell(cell).volume()
            n_non_h = sum(cnt for el, cnt in zip(meta["sfac"], meta["unit"])
                          if el != "H")
            if n_non_h < 0.2 * volume / 18.0:
                return None
        per_fu = {el: cnt / z for el, cnt in zip(meta["sfac"], meta["unit"])}
        return CompositionHint(elements=per_fu, z=z, source=str(meta.get("_src", "ins")))
    return None


def _hklf_file_key(hkl_path: Path, base_symm) -> tuple | None:
    """Identity of a reflection file for the read cache: path + mtime +
    size + the cell the arrays were built with. None when unstat-able."""
    try:
        st = hkl_path.stat()
    except OSError:
        return None
    return (str(hkl_path.resolve()), int(st.st_mtime_ns), int(st.st_size),
            tuple(round(float(x), 6)
                  for x in base_symm.unit_cell().parameters()))


def read_hklf_arrays(hkl_path: Path, base_symm, cache: dict | None = None):
    """hklf.reader(...).as_miller_arrays(...) with an optional caller-owned
    cache. The text parse + Bijvoet pairing is ~0.6 s for a 337k-row MOF
    hkl and was repeated on EVERY checkout/branch (pa1: 730 switches),
    although the file never changes between them. A hit hands back deep
    copies so no session ever aliases the cached arrays; the entry is
    invalidated by mtime/size (swap_reflection_data copies a new file
    into place) and by the cell the arrays were built with."""
    key = _hklf_file_key(hkl_path, base_symm) if cache is not None else None
    if key is not None:
        hit = cache.get("hklf")
        if hit is not None and hit[0] == key:
            return [a.deep_copy() for a in hit[1]]
    arrays = hklf.reader(file_name=str(hkl_path)).as_miller_arrays(
        crystal_symmetry=base_symm, merge_equivalents=False)
    if key is not None:
        cache["hklf"] = (key, [a.deep_copy() for a in arrays])
    return arrays


def rekey_hklf_cache(cache: dict | None, old_path: Path,
                     new_path: Path) -> tuple[tuple, tuple] | None:
    """The arrays parsed from `old_path` now describe `new_path`: a
    byte-identical copy published under another name (a controlled import
    parses the staged input, then publishes it as the node's immutable
    observation revision - same bytes, new path, new mtime). Without this
    the first checkout after every import re-parsed the whole file (2026-09-08).
    Returns (old_key, new_key) so callers keyed on the file key can follow."""
    hit = cache.get("hklf") if cache else None
    if hit is None:
        return None
    old_key = hit[0]
    try:
        st = Path(new_path).stat()
    except OSError:
        return None
    if old_key[0] != str(Path(old_path).resolve()) or old_key[2] != int(st.st_size):
        return None
    new_key = (str(Path(new_path).resolve()), int(st.st_mtime_ns),
               int(st.st_size), old_key[3])
    cache["hklf"] = (new_key, hit[1])
    return old_key, new_key


def load_shelx_dataset(hkl_path: Path, ins_path: Path | None = None,
                       cell: tuple | None = None, wavelength: float | None = None,
                       space_group=None, hklf_override: int | None = None,
                       cache: dict | None = None) -> ReflectionDataset:
    """Load HKLF4 data; metadata from ins if given, else from explicit args.

    hklf_override overrides the ins HKLF code - needed when swapping in a batch
    file (HKLF5) without any ins carrying the code.

    cache: optional dict owned by the caller (RefineProject) that memoizes
    the parsed reflection file across sessions of the same project - see
    read_hklf_arrays. Everything metadata-dependent (composition, symmetry
    hint, sigma hygiene) is recomputed on every call, so nodes with
    different SFAC/UNIT or LATT/SYMM cards still get their own dataset."""
    hkl_path = Path(hkl_path)
    meta: dict = {}
    if ins_path is not None:
        meta = parse_ins_metadata(Path(ins_path))
        meta["_src"] = str(ins_path)
        cell = cell or meta.get("cell")
        wavelength = wavelength or meta.get("wavelength")
        if space_group is None and meta.get("symm") is not None and meta.get("latt"):
            space_group = space_group_from_latt_symm(meta.get("latt"), meta.get("symm", []))
    if cell is None:
        raise ValueError("unit cell required (from ins/p4p or explicit)")

    symmetry_hint = None
    if space_group is not None:
        symmetry_hint = crystal.symmetry(unit_cell=uctbx.unit_cell(cell),
                                         space_group=space_group)
    # Read reflections cell-only (P1): symmetry is determined downstream.
    base_symm = crystal.symmetry(unit_cell=uctbx.unit_cell(cell), space_group_symbol="P1")
    arrays = read_hklf_arrays(hkl_path, base_symm, cache)
    intensities = arrays[0]
    instrument_meta: dict = {"titl": meta.get("titl", "")} if meta else {}
    hklf_code = int(hklf_override or meta.get("hklf") or 4)
    if hklf_code == 5 and len(arrays) > 1:
        # HKLF5 twin data: rows with batch<0 are extra-component
        # contributions of a composite observation; keep one row per
        # observation (batch>0) so merging does not double-count. The
        # resulting Fo are still twin-composite - only SHELXL (which
        # consumes the batch column natively) refines correctly.
        batch = arrays[1].data()
        pos = batch > 0
        n_neg = pos.count(False)
        intensities = intensities.select(pos)
        instrument_meta["hklf"] = 5
        instrument_meta["hklf5_note"] = (
            f"twin-batch data: {n_neg} negative-batch component rows "
            f"excluded from the in-process view; intensities remain "
            f"twin-composite (approximate for maps/merge stats) - "
            f"refinement must go through SHELXL")
    elif hklf_code != 4:
        instrument_meta["hklf"] = hklf_code
    # sigma<=0 rows (some integration exports carry them) crash least-squares
    # weighting (SMTBX_ASSERT sigma > 0); discard them up front and surface
    # the count so downstream summaries can report the data hygiene applied
    if intensities.sigmas() is not None:
        good = intensities.sigmas() > 0
        n_bad = good.count(False)
        if n_bad:
            intensities = intensities.select(good)
            instrument_meta["n_sigma_dropped"] = n_bad
    intensities.set_observation_type_xray_intensity()

    return ReflectionDataset(
        intensities=intensities,
        wavelength=wavelength,
        symmetry_hint=symmetry_hint,
        composition=composition_from_meta(meta) if meta else None,
        source_files=[str(hkl_path)] + ([str(ins_path)] if ins_path else []),
        instrument_meta=instrument_meta,
    )
