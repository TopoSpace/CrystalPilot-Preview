"""The files a crystallographer continues from BY HAND, and what each one
is made of.

2026-09-08 usertest test3-1 / test3-2 (two real sessions, one user): the
group's hand-over set is `res / cif / ins / hkl / p4p` ("发给老师人工看或再
操作的 5 个文件"). write_outputs wrote res / cif / fcf / fab and nothing
else, so both agents built the rest with the shell: `final.res` copied to
`final.ins` (a deck with no L.S. card, which restarts nothing), the vendor
hkl copied verbatim (no all-zero terminator - Olex2 refused it as an
"unknown hkl error"), the .p4p fetched from the vendor directory by
guessing its name. This module makes those three files a product of the
tool, each with a recorded source:

  final.hkl  the reflection file the delivered model was refined against -
             the node's bound observation revision, byte-preserved, with
             the SHELX terminator row appended when the data end at EOF
  final.ins  the instruction deck that reproduces the delivered numbers:
             the paired SHELXL job's own job.ins, else the node model with
             a standard command block so a restart actually refines
  final.p4p  the vendor's cell/orientation record captured at ingest; it
             cannot be computed, so its absence is reported, not faked

plus two checks nothing else made: a plain-text CIF statistics block for a
node that has no SHELXL ACTA CIF (the header row Olex2 shows), and a
metal-bond audit of SHELXL's _geom_bond loop (test3-1's final.cif listed
Zn02-C21 2.52 A - SHELXL's default connectivity radius - and Olex2 drew a
seven-coordinate zinc).
"""
from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

#: SHELX hkl data end at the all-zero row; a file without one is legal for
#: SHELXL (EOF ends the data) and refused by Olex2's importer
HKL_TERMINATOR = "   0   0   0    0.00    0.00"

#: the hand-over set the user's group works with, in the order they open them
MANUAL_FILES = ("final.res", "final.cif", "final.ins", "final.hkl", "final.p4p")


# ==========================================================================
# final.hkl
# ==========================================================================

def _is_terminator(line: str) -> bool:
    try:
        return (int(line[0:4]) == 0 and int(line[4:8]) == 0
                and int(line[8:12]) == 0)
    except (ValueError, IndexError):
        return False


def _is_reflection_row(line: str) -> bool:
    s = line.rstrip("\r\n")
    if len(s.rstrip()) < 28:
        return False
    try:
        int(s[0:4]); int(s[4:8]); int(s[8:12])
        float(s[12:20]); float(s[20:28])
    except ValueError:
        return False
    return True


def copy_hkl_for_handover(src: Path, dst: Path) -> dict[str, Any]:
    """Byte-preserving copy of a SHELX hkl, plus the terminator row when
    the file has none before EOF. Reflection rows, a batch column (HKLF 5)
    and any SADABS/XPREP trailer after an existing terminator are copied
    as they are - nothing here re-formats data.

    Returns {source, bytes, n_reflections, terminator_added, trailer_lines}.
    """
    src = Path(src)
    raw = src.read_bytes()
    text = raw.decode("latin-1")
    lines = text.splitlines(keepends=True)
    n_refl = 0
    terminator_at = None
    for i, line in enumerate(lines):
        if _is_terminator(line):
            terminator_at = i
            break
        if _is_reflection_row(line):
            n_refl += 1
    added = False
    if terminator_at is None:
        if text and not text.endswith(("\n", "\r\n")):
            text += "\n"
        nl = "\r\n" if "\r\n" in text[:4000] else "\n"
        text += HKL_TERMINATOR + nl
        added = True
        trailer = 0
    else:
        trailer = sum(1 for ln in lines[terminator_at + 1:] if ln.strip())
    Path(dst).write_bytes(text.encode("latin-1"))
    return {"source": str(src), "bytes": len(raw), "n_reflections": n_refl,
            "terminator_added": added, "trailer_lines": trailer}


# ==========================================================================
# final.ins
# ==========================================================================

_CMD_KEYWORDS = ("L.S.", "CGLS")


def restart_ins_text(res_text: str, l_s: int = 4) -> tuple[str, dict[str, Any]]:
    """A deck SHELXL will actually refine from. Our node .res carries the
    cell, cards, restraints, WGHT/FVAR and atoms but no command block
    (nothing to refine WITH), so `shelxl final` on a bare copy computes
    nothing. Insert `L.S. n / ACTA / BOND $H / CONF / FMAP 2 / PLAN 20`
    before the first WGHT/FVAR when no L.S./CGLS card exists; a deck that
    already has one is returned unchanged."""
    lines = res_text.splitlines(keepends=True)
    for ln in lines:
        toks = ln.split()
        if toks and toks[0].upper() in _CMD_KEYWORDS:
            return res_text, {"inserted": [], "note": "deck already carries "
                              f"{toks[0].upper()}; used as is"}
    from ..io.shelx_writer import shelxl_command_block
    cards = shelxl_command_block(l_s=l_s)
    present = {ln.split()[0].upper() for ln in lines if ln.split()}
    cards = [c for c in cards if c.split()[0].upper() not in present]
    idx = len(lines)
    for i, ln in enumerate(lines):
        toks = ln.split()
        if toks and toks[0].upper() in ("WGHT", "FVAR", "HKLF"):
            idx = i
            break
    eol = "\r\n" if res_text[:2000].count("\r\n") else "\n"
    block = "".join(c + eol for c in cards)
    text = "".join(lines[:idx]) + block + "".join(lines[idx:])
    return text, {"inserted": cards,
                  "note": f"command block inserted (L.S. {l_s} + ACTA): a "
                          "restart from this deck refines the delivered model"}


# ==========================================================================
# final.p4p
# ==========================================================================

def find_vendor_sidecar(project, node_meta: dict[str, Any],
                        suffix: str = ".p4p") -> dict[str, Any]:
    """Locate the vendor sidecar (default: the .p4p) that belongs to the
    delivered node's data. Order: the bound data revision's frozen source
    copies (recorded at ingest), then the context's vendor_* name under
    vendor_source, then a single file of that suffix in vendor_source.
    Returns {path|None, source, note}."""
    suffix = suffix.lower()
    key = {".p4p": "vendor_p4p", ".abs": "vendor_abs"}.get(suffix)
    revision = node_meta.get("data_revision")
    if revision:
        from .data_versions import DataVersions
        try:
            _hkl, meta = DataVersions(project.dir).resolve(revision)
        except Exception:  # noqa: BLE001 - a missing revision is reported below
            meta = {}
        root = project.dir / ".crystalpilot" / "refine" / "data" / revision / "sources"
        wanted = ((meta.get("input_context") or {}).get("data") or {}).get(key) \
            if key else None
        for row in meta.get("sources") or []:
            src_name = Path(str(row.get("source", ""))).name
            frozen = root / str(row.get("file", ""))
            if (frozen.suffix.lower() == suffix and frozen.is_file()
                    and (wanted is None or src_name.lower() == str(wanted).lower())):
                return {"path": frozen,
                        "source": f"data revision {revision} source "
                                  f"{row.get('file')} (= {row.get('source')})",
                        "note": None}
    data = project.context.get("data") or {}
    vendor_dir = data.get("vendor_source")
    name = data.get(key) if key else None
    if vendor_dir and name:
        cand = Path(vendor_dir) / str(name)
        if cand.is_file():
            return {"path": cand, "source": f"vendor directory {cand}",
                    "note": None}
    if vendor_dir and Path(vendor_dir).is_dir():
        found = sorted(p for p in Path(vendor_dir).glob(f"*{suffix}"))
        if len(found) == 1:
            return {"path": found[0], "source": f"vendor directory {found[0]} "
                                                "(the only one there)",
                    "note": None}
        if len(found) > 1:
            return {"path": None, "source": None,
                    "note": f"{len(found)} {suffix} files in {vendor_dir} and "
                            "none recorded as the ingested one - not "
                            "guessing; pass the right one to ingest_vendor_data "
                            "or copy it by hand"}
    return {"path": None, "source": None,
            "note": f"no {suffix} on record: the vendor directory carried none "
                    "(or the data did not come from ingest_vendor_data). It "
                    "cannot be derived from the model - ask for the "
                    "instrument's file if the hand-over needs it"}


# ==========================================================================
# the statistics block of a CIF that has no SHELXL ACTA output
# ==========================================================================

def _theta_max_deg(d_min: float | None, wavelength: float | None) -> float | None:
    if not d_min or not wavelength or d_min <= 0:
        return None
    s = wavelength / (2.0 * d_min)
    if s >= 1.0:
        return None
    return round(math.degrees(math.asin(s)), 3)


def data_statistics_lines(node_meta: dict[str, Any]) -> list[str]:
    """`_diffrn_reflns_* / _reflns_*` for the model CIF, from the numbers
    the node recorded when its data were merged. Rint is written only for
    data that were merged HERE (n_obs > n_unique): a pre-merged file has
    no redundancy and its 0.000 is arithmetic, not an experiment."""
    data = node_meta.get("data") or {}
    out: list[str] = []
    n_obs, n_uniq = data.get("n_obs"), data.get("n_unique")
    if n_obs:
        out.append(f"_diffrn_reflns_number             {int(n_obs)}")
    if n_uniq:
        out.append(f"_reflns_number_total              {int(n_uniq)}")
    r_int = data.get("r_int")
    if r_int is not None and n_obs and n_uniq and int(n_obs) > int(n_uniq):
        out.append(f"_diffrn_reflns_av_R_equivalents   {float(r_int):.4f}")
    theta = _theta_max_deg(data.get("d_min"), data.get("wavelength"))
    if theta is not None:
        out.append(f"_diffrn_reflns_theta_max          {theta:.3f}")
    if data.get("completeness") is not None:
        out.append(f"_diffrn_measured_fraction_theta_max {float(data['completeness']):.3f}")
    if data.get("d_min"):
        out.append(f"_refine_ls_d_res_high             {float(data['d_min']):.3f}")
    return out


def enrich_model_cif(text: str, node_meta: dict[str, Any],
                     zero_cycle: dict[str, Any] | None = None) -> tuple[str, dict[str, Any]]:
    """Give a coordinates-only node CIF the statistics a reader (Olex2's
    header row, checkCIF) looks for, from records that are true for THIS
    model: the node's data block and either its own current metrics or a
    zero-cycle SHELXL job run on it at write time. Nothing is inherited
    from another node. Returns (text, {grade, added, note})."""
    added: list[str] = []
    lines: list[str] = []
    metrics = node_meta.get("metrics") or {}
    current = bool(node_meta.get("metrics_current"))
    src = None
    numbers: dict[str, Any] = {}
    if zero_cycle and zero_cycle.get("shelxl"):
        numbers = dict(zero_cycle["shelxl"])
        src = f"SHELXL zero-cycle job {zero_cycle.get('job')} (R factors of this exact model, no refinement)"
    elif metrics and current:
        # the node's own measurement (metrics_current: nothing moved since
        # the engine computed them) - true for this model, no esds
        numbers = {k: metrics.get(k) for k in ("r1_strong", "r1_all", "wr2", "goof",
                                                "n_reflections", "n_params",
                                                "n_restraints", "flack")}
        ms = node_meta.get("metrics_source") or {}
        src = (f"node {node_meta.get('id')} current metrics"
               + (f" ({ms.get('engine')} job {ms.get('job')})" if ms.get("job") else ""))
    if numbers:
        pairs = (("r1_strong", "_refine_ls_R_factor_gt"),
                 ("r1_all", "_refine_ls_R_factor_all"),
                 ("wr2", "_refine_ls_wR_factor_ref"),
                 ("goof", "_refine_ls_goodness_of_fit_ref"),
                 ("n_reflections", "_refine_ls_number_reflns"),
                 ("n_params", "_refine_ls_number_parameters"),
                 ("n_restraints", "_refine_ls_number_restraints"),
                 ("diff_map_max", "_refine_diff_density_max"),
                 ("diff_map_min", "_refine_diff_density_min"),
                 ("flack", "_refine_ls_abs_structure_Flack"))
        for key, tag in pairs:
            val = numbers.get(key)
            if val is None or re.search(r"^" + re.escape(tag) + r"\s", text, re.M):
                continue
            if isinstance(val, float):
                val = f"{val:.4f}" if key in ("r1_strong", "r1_all", "wr2", "flack") \
                    else (f"{val:.3f}" if key == "goof" else f"{val:.2f}")
            lines.append(f"{tag:<34}{val}")
    for tag_line in data_statistics_lines(node_meta):
        tag = tag_line.split()[0]
        if not re.search(r"^" + re.escape(tag) + r"\s", text, re.M):
            lines.append(tag_line)
    grade_note = ("model CIF: coordinates from the node, statistics from "
                  + (src or "no measurement on record for this node")
                  + "; no esds, no geometry tables - a SHELXL ACTA CIF needs "
                    "run_shelxl(mode='adopt', l_s>=1) on this node")
    if lines:
        block = ("# CrystalPilot statistics block: " + (src or "data record only") + "\n"
                 + "\n".join(lines) + "\n\n")
        anchor = "\nloop_\n  _atom_site_label"
        if anchor in text:
            text = text.replace(anchor, "\n" + block + anchor.lstrip("\n"), 1)
        else:
            text = text.rstrip("\n") + "\n\n" + block
        added = [ln.split()[0] for ln in lines]
    return text, {"grade": "model", "added": added, "note": grade_note,
                  "statistics_source": src}


# ==========================================================================
# SHELXL's _geom_bond loop against the model's own bonding
# ==========================================================================

def _geom_bond_rows(cif_text: str) -> list[tuple[str, str, float, str]]:
    """(label_1, label_2, distance, symmetry_2) of every _geom_bond row."""
    lines = cif_text.splitlines()
    n = len(lines)
    i = 0
    rows: list[tuple[str, str, float, str]] = []
    while i < n:
        if lines[i].strip().lower() != "loop_":
            i += 1
            continue
        i += 1
        tags: list[str] = []
        while i < n and lines[i].strip().startswith("_"):
            tags.append(lines[i].strip().split()[0])
            i += 1
        if "_geom_bond_atom_site_label_1" not in tags:
            continue
        ia = tags.index("_geom_bond_atom_site_label_1")
        ib = tags.index("_geom_bond_atom_site_label_2")
        idist = tags.index("_geom_bond_distance") if "_geom_bond_distance" in tags else None
        isym = tags.index("_geom_bond_site_symmetry_2") if "_geom_bond_site_symmetry_2" in tags else None
        while i < n:
            s = lines[i].strip()
            if not s or s.startswith(("_", "loop_", "data_", "#")):
                if s.startswith(("_", "loop_", "data_")):
                    break
                i += 1
                continue
            toks = s.split()
            if len(toks) >= len(tags):
                try:
                    d = float(toks[idist].split("(")[0]) if idist is not None else float("nan")
                except ValueError:
                    d = float("nan")
                rows.append((toks[ia], toks[ib], d,
                             toks[isym] if isym is not None else "."))
            i += 1
        return rows
    return rows


def geom_bond_audit(cif_text: str, xs, part_kwargs: dict | None = None) -> dict[str, Any]:
    """Every metal-X row of the CIF's bond table that the model's own
    bonding (chem.bonding.bond_table: profile windows, eta rings, the
    2.3-2.6 A non_bonded_close class) does NOT count as a bond. SHELXL
    lists bonds by a fixed radius table and Olex2 draws what the CIF
    lists; a Zn-C(imine) 2.52 A row made a six-coordinate zinc look
    seven-coordinate in the user's viewer (usertest test3-1, 20:32).

    Returns {checked, n_rows, suspects: [{a, b, d, symmetry, verdict, free_card}],
    note}. The fix is SHELXL's own: `FREE A B` in the job (run_shelxl
    extra_cards) removes the pair from the connectivity table and every
    derived angle/torsion, then write_outputs again."""
    rows = _geom_bond_rows(cif_text)
    if not rows or xs is None:
        return {"checked": False, "n_rows": len(rows), "suspects": [],
                "note": "no _geom_bond loop or no model to compare against"}
    from ..chem.bonding import KIND_NON_BONDED, bond_table, is_metal_element
    try:
        table = bond_table(xs, part_kwargs=part_kwargs, include_non_bonded=True)
    except Exception as e:  # noqa: BLE001 - an audit must not block a delivery
        return {"checked": False, "n_rows": len(rows), "suspects": [],
                "note": f"bond table unavailable: {type(e).__name__}: {e}"}
    labels = [lb.upper() for lb in table.labels]
    index = {lb: i for i, lb in enumerate(labels)}
    bonded: dict[tuple[str, str], str] = {}
    for e in table.edges:
        a, b = labels[e.i], labels[e.j]
        kind = e.kind
        prev = bonded.get((a, b))
        # the strongest classification of the pair wins over a non-bonded one
        if prev is None or (prev == KIND_NON_BONDED and kind != KIND_NON_BONDED):
            bonded[(a, b)] = kind
            bonded[(b, a)] = kind
    suspects: list[dict[str, Any]] = []
    for a, b, d, sym in rows:
        ua, ub = a.upper(), b.upper()
        if ua not in index or ub not in index:
            continue
        ea, eb = table.elements[index[ua]], table.elements[index[ub]]
        if not (is_metal_element(ea) or is_metal_element(eb)):
            continue
        if ea == "H" or eb == "H":
            continue
        kind = bonded.get((ua, ub))
        if kind is not None and kind != KIND_NON_BONDED:
            continue
        metal, other = (a, b) if is_metal_element(ea) else (b, a)
        suspects.append({
            "a": a, "b": b, "distance": d, "symmetry": sym,
            "verdict": ("model bonding classifies this pair as "
                        + (kind or "not bonded")
                        + f"; SHELXL's radius table listed it as a bond"),
            "free_card": f"FREE {metal} {other}"})
    note = (f"{len(suspects)} metal-X row(s) of the CIF bond table are not "
            "bonds in the model's own bonding - readers (Olex2, checkCIF) "
            "count them as coordination. Fix in the job, not the CIF text: "
            "run_shelxl(mode='adopt', l_s=0, extra_cards=[<free_card>...]) "
            "then write_outputs again" if suspects else
            "every metal-X row of the CIF bond table is a bond in the "
            "model's own bonding")
    return {"checked": True, "n_rows": len(rows), "suspects": suspects,
            "note": note}


# ==========================================================================
# the record
# ==========================================================================

def manual_continuation(out: Path, provenance: dict[str, Any],
                        masked: bool) -> dict[str, Any]:
    """Can a person continue from this directory? The five files of the
    group's hand-over set, plus final.fab when the model is masked (ABIN
    in the deck is dead without it). Missing p4p is reported with the
    reason recorded at write time - it is an input, never a fabrication."""
    present = {f.name for f in Path(out).iterdir() if f.is_file()}
    wanted = list(MANUAL_FILES) + (["final.fab"] if masked else [])
    missing = [f for f in wanted if f not in present]
    notes: list[str] = []
    p4p = provenance.get("final.p4p") or {}
    if "final.p4p" in missing and p4p.get("note"):
        notes.append("final.p4p: " + str(p4p["note"]))
    if masked:
        notes.append("masked model: keep final.fab beside final.ins/final.res "
                     "(ABIN) - SHELXL cannot reproduce the refinement without it")
    ins = provenance.get("final.ins") or {}
    if ins.get("from"):
        notes.append("final.ins: " + str(ins["from"]))
    hkl = provenance.get("final.hkl") or {}
    if hkl.get("terminator_added"):
        notes.append("final.hkl: SHELX terminator row appended (the source "
                     "ended at EOF; reflections unchanged)")
    ready = not [m for m in missing if m != "final.p4p"]
    return {"ready": ready, "files": wanted, "missing": missing,
            "notes": notes,
            "usage": "same basename: `shelxl final` refines final.ins against "
                     "final.hkl (+ final.fab); open final.res / final.cif in "
                     "Olex2 to inspect; final.p4p carries the instrument cell"}
