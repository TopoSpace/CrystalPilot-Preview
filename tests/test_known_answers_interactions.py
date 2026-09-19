"""Known-answer validation of `chem/interactions.py` (no snapshots).

Two independent answers are used, neither of them produced by this code
base:

  1. the DEPOSITED `_geom_hbond_*` loop of a published CIF - the author's
     own hydrogen-bond table with its symmetry codes, distances and angles
     (14 structures: benchmark/data_ext2, benchmark/public, and one COD
     download for the halogen bond).  The model is read from the CIF's
     embedded `_shelx_res_file` when it has one, else from the CIF atom
     loop, so engine and table describe the same atoms;
  2. PLATON run headlessly on the SAME model (`platon_calc_all`) - its
     "Analysis of Potential Hydrogen Bonds", "Analysis of Short
     Ring-Interactions with Cg-Cg Distances", "Analysis of X-H...Cg(Pi-Ring)
     Interactions" and "Analysis of Short Intra- and Inter-molecular
     Contacts" tables (the last one is the only known answer available for
     halogen bonds - a CIF has no `_geom_*` loop for those).

HOW PLATON IS DRIVEN WITHOUT A TERMINAL (Windows).  `platon -u` runs
unattended but writes no .lis; every other switch, and stdin redirection,
leaves the program idling at its `>>` prompt because the ClearWin runtime
does not read a redirected stdin.  What works is PLATON's own rule that it
takes instructions FROM THE INPUT FILE: `platon_spf` writes the model as a
.spf with `NOMOVE / CALC INTRA / CALC INTER / END` appended after the atoms,
so the prompt is never reached.  `NOMOVE` matters - without it PLATON moves
the molecule and its ARU codes stop being comparable with our operators.

WHERE THE KINDS DIFFER.  A deposited `_geom_hbond` loop routinely carries
C-H...O and C-H...Cg rows; this engine files those under `chx` and `chpi`
by construction ("a polar carrier makes it a hydrogen bond and it is
reported as one" - interactions.py).  A deposited row is therefore looked
up in hbond -> chx -> chpi, and the test records WHICH table answered.
That is a taxonomy difference, not a disagreement, and the geometry must
still match to 0.01 A / 0.02 A / 1 deg.

The benchmark CIFs are gitignored working data; every test skips when its
input is absent.  PLATON tests additionally skip without
`vendor/shelx/platon.exe`.

Run the whole comparison as a report:
    .venv/Scripts/python.exe -X utf8 tests/test_known_answers_interactions.py
"""
from __future__ import annotations

import math
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
EXT2 = REPO / "benchmark" / "data_ext2"
PUB = REPO / "benchmark" / "public"
KNOWN = REPO / "benchmark" / "known_answers"
PLATON_EXE = Path(os.environ.get(
    "CRYSTALPILOT_PLATON", str(REPO / "vendor" / "shelx" / "platon.exe")))

#: (slug, cif) - every deposit here carries a `_geom_hbond_atom_site_label_D`
CASES: list[tuple[str, Path]] = [
    (s, EXT2 / s / "ref.cif") for s in (
        "coord_cuox_cod2241944", "coorddis_cuspar_cod2241447",
        "org_hsl_cod2241460", "orgdis_dbu_cod2241572",
        "twin_iodouracil_cod2020129", "twin_rz5267_iucr",
        "twindis_hb8035_iucr", "twintrap_nm_cod2229074")
] + [
    (s, PUB / s / "ref_cif.cif") for s in (
        "Ca_imidazolate", "Cd_complex_P1", "Cu3_terephthalate_CP",
        "MeIm_H_terephthalate", "Zn2_dhtp_complex")
] + [
    # downloaded for this validation: the only halogen-bonded case
    # (benchmark/known_answers/SOURCES.md has the COD id and citation)
    ("xb_tfib_bipy_cod2201150", KNOWN / "xb_tfib_bipy_cod2201150" / "ref.cif"),
    # round-3 R5-F: the anion-pi case (BF4- over a triazinium ring) with the
    # authors' own Cg...F distances and pi-pi geometry in the abstract
    ("anionpi_triazinium_bf4_cod2232050",
     KNOWN / "anionpi_triazinium_bf4_cod2232050" / "ref.cif"),
]

#: structures with aromatic rings used for the PLATON pi-geometry check
RING_CASES = ["MeIm_H_terephthalate", "Ca_imidazolate", "twin_rz5267_iucr",
              "twin_iodouracil_cod2020129", "Cd_complex_P1",
              "twindis_hb8035_iucr", "Zn2_dhtp_complex",
              "xb_tfib_bipy_cod2201150", "anionpi_triazinium_bf4_cod2232050"]

#: round-3 R5-F: the PLATON pi-pi comparison must COMPARE at least this
#: many rows here, not excuse them. Zn2_dhtp has 20 PLATON stacking rows
#: inside our window; 12 involve 5/6-rings that close through an inversion
#: centre and are now compared row by row (before round-3 R5-A the engine
#: had no such ring and the whole table was "excused" as missing); the other
#: 8 involve the fused 8-membered ring find_rings does not search and stay
#: excused as size_outside_find_rings
MIN_PIPI_COMPARED = {"Zn2_dhtp_complex": 12,
                     "anionpi_triazinium_bf4_cod2232050": 1}

#: tolerances of the comparison (the deposits print 2-4 decimals and PLATON
#: rounds its angles to whole degrees, so 1 deg is its own rounding width)
TOL_DA = 0.01
TOL_HA = 0.02
TOL_ANG = 1.0

#: Deposited rows this engine does NOT reproduce, with the exact reason.
#: `test_documented_gaps_...` re-measures each one, so a gap can never be a
#: silent pass: it asserts the row is a BOUNDARY case of the stated
#: criterion and that the geometry itself still agrees with the deposit.
KNOWN_GAPS: dict[tuple[str, str], dict] = {
    ("xb_tfib_bipy_cod2201150", "C5C-H5C...F3A"): {
        "kind": "chx", "margin_A": 0.02,
        "why": ("H...F = 2.676 A is 0.006 A OUTSIDE the C-H...X window "
                "r_vdW(H) + r_vdW(F) = 1.20 + 1.47 = 2.67 A (cctbx vdw "
                "table); the deposit's own value is 2.68(3) A, so the "
                "geometry agrees and only the cut-off differs")},
    ("xb_tfib_bipy_cod2201150", "C2D-H2D...F1A"): {
        "kind": "chx", "margin_A": 0.02,
        "why": ("H...F = 2.685 A is 0.015 A outside the same 2.67 A "
                "window; deposit 2.69(4) A")},
}


def _gap_key(slug: str, row: dict) -> tuple[str, str]:
    return (slug, f"{row['D']}-{row['H']}...{row['A']}")


# --------------------------------------------------------------------------
# the deposited model + the deposited table
# --------------------------------------------------------------------------

def _gemmi_block(cif: Path):
    import gemmi
    doc = gemmi.cif.read(str(cif))
    for b in doc:
        if b.find_loop("_geom_hbond_atom_site_label_D"):
            return doc, b
    return doc, doc.sole_block()


def _symops(block) -> list[str]:
    import gemmi
    for tag in ("_space_group_symop_operation_xyz",
                "_symmetry_equiv_pos_as_xyz"):
        col = block.find_loop(tag)
        if col:
            return [gemmi.cif.as_string(v) for v in col]
    return ["x,y,z"]


def _rt(op_str: str):
    from cctbx import sgtbx
    return sgtbx.rt_mx(str(op_str).replace(" ", ""))


def _translation(tx: int, ty: int, tz: int):
    from cctbx import sgtbx
    return sgtbx.rt_mx(sgtbx.rot_mx(),
                       sgtbx.tr_vec([12 * tx, 12 * ty, 12 * tz], 12))


def _decode_symcode(code: str, ops: list[str]):
    """CIF `n_pqr` -> rt_mx (`.` is the identity)."""
    code = (code or "").strip()
    if code in (".", "?", ""):
        return _rt("x,y,z")
    if "_" in code:
        n, t = code.split("_")
        tx, ty, tz = int(t[0]) - 5, int(t[1]) - 5, int(t[2]) - 5
    else:
        n, (tx, ty, tz) = code, (0, 0, 0)
    return _translation(tx, ty, tz).multiply(_rt(ops[int(n) - 1]))


def _float(raw: str):
    raw = re.sub(r"\(.*?\)", "", str(raw)).strip()
    try:
        return float(raw)
    except ValueError:
        return None


def deposited_hbonds(cif: Path) -> list[dict]:
    """The published `_geom_hbond_*` loop, symmetry codes decoded."""
    import gemmi
    _doc, block = _gemmi_block(cif)
    ops = _symops(block)
    tags = ["_geom_hbond_atom_site_label_D", "_geom_hbond_atom_site_label_H",
            "_geom_hbond_atom_site_label_A", "_geom_hbond_site_symmetry_A",
            "_geom_hbond_distance_DH", "_geom_hbond_distance_HA",
            "_geom_hbond_distance_DA", "_geom_hbond_angle_DHA"]
    out = []
    for r in block.find(tags):
        s = [gemmi.cif.as_string(r[k]) for k in range(len(tags))]
        out.append({"D": s[0], "H": s[1], "A": s[2], "code": s[3],
                    "d_DH": _float(s[4]), "d_HA": _float(s[5]),
                    "d_DA": _float(s[6]), "angle": _float(s[7]),
                    "op": _decode_symcode(s[3], ops)})
    return out


def known_model(cif: Path, tmpdir: Path):
    """(xs, parts, provenance) of the DEPOSITED model.

    The embedded `_shelx_res_file` is preferred because it carries the SHELX
    PART numbers the engine needs; the CIF atom loop (gemmi ->
    `_small_structure_to_xray`, the product's own import path) is the
    fallback and `_atom_site_disorder_group` then supplies the parts."""
    import gemmi

    from crystalpilot.refine.tools_ingest import (_semicolon_field,
                                                  _small_structure_to_xray)
    text = cif.read_text(encoding="utf-8", errors="replace")
    res = _semicolon_field(text, "_shelx_res_file")
    if res and "HKLF" in res.upper():
        p = Path(tmpdir) / "deposited.res"
        p.write_text(res, encoding="ascii", errors="replace")
        try:
            from crystalpilot.io.shelx_model import load_res_model
            parsed = load_res_model(p)
            if parsed.structure.scatterers().size():
                return parsed.structure, parsed.parts, "embedded_shelx_res"
        except Exception:                      # noqa: BLE001 - fall back
            pass
    small = gemmi.read_small_structure(str(cif))
    xs, _notes = _small_structure_to_xray(small)
    parts = {}
    for site in small.sites:
        g = int(getattr(site, "disorder_group", 0) or 0)
        if g:
            parts[site.label[:4]] = g
    return xs, (parts or None), "cif_atom_loop"


def engine_tables(xs, parts, criteria="platon") -> dict:
    from crystalpilot.chem.interactions import find_interactions
    return find_interactions(xs, parts=parts, criteria=criteria)


def _elem_map(xs) -> dict[str, str]:
    """{LABEL: element} straight off the scatterers, same rule as the
    engine's `_elem`."""
    return {sc.label.upper(): "".join(
        ch for ch in sc.scattering_type if ch.isalpha())[:2].capitalize()
        for sc in xs.scatterers()}


# --------------------------------------------------------------------------
# matching a deposited row against the engine's canonical tables
# --------------------------------------------------------------------------

def _same_op(a, b) -> bool:
    return _rt(str(a)) == _rt(str(b))


def _op_mod_lattice(a, b) -> bool:
    """Same rotation and a translation difference that is a whole lattice
    vector - the case where two ASU choices describe the same relation."""
    ra, rb = _rt(str(a)), _rt(str(b))
    if ra.r() != rb.r():
        return False
    d = ra.t().minus(rb.t())
    den = d.den()
    return all(int(v) % den == 0 for v in d.num())


def find_engine_row(dep: dict, unique: dict):
    """The engine row that answers a deposited row, and which table it is in.

    Returns (kind, row, note).  `note` is empty for a clean match."""
    dl, hl, al = (dep["D"] or "").upper(), (dep["H"] or "").upper(), \
        (dep["A"] or "").upper()
    ring_target = al.startswith("CG") and al[2:].isdigit()
    cands: list[tuple[str, dict]] = []
    for kind in ("hbond", "chx"):
        for row in unique.get(kind) or ():
            if ((row.get("d") or "").upper() == dl
                    and (row.get("h") or "").upper() == hl
                    and (row.get("a") or "").upper() == al):
                cands.append((kind, row))
    if ring_target:
        for row in unique.get("chpi") or ():
            if ((row.get("c") or "").upper() == dl
                    and (row.get("h") or "").upper() == hl):
                cands.append(("chpi", row))
    if not cands:
        return None, None, "no row with these labels in hbond/chx/chpi"
    best, best_score = None, None
    for kind, row in cands:
        d_ha = row.get("d_HA") if kind != "chpi" else row.get("d_HCg")
        score = (0 if _same_op(row["op"], dep["op"]) else 1,
                 abs((d_ha or 99.0) - (dep["d_HA"] or 0.0)))
        if best_score is None or score < best_score:
            best, best_score = (kind, row), score
    kind, row = best
    return kind, row, ""


def compare_row(dep: dict, kind: str, row: dict) -> list[str]:
    """Every way `row` fails to reproduce `dep`, as plain text."""
    bad: list[str] = []
    if not _same_op(row["op"], dep["op"]):
        bad.append(f"operator {row['op']} != deposited {dep['op']} "
                   f"({dep['code']})"
                   + ("; same modulo a lattice translation"
                      if _op_mod_lattice(row["op"], dep["op"]) else ""))
    if kind == "chpi":
        d_ha, d_da, ang = row.get("d_HCg"), None, row.get("angle")
    else:
        d_ha, d_da, ang = row.get("d_HA"), row.get("d_DA"), row.get("angle")
    if d_da is not None and dep["d_DA"] is not None \
            and abs(d_da - dep["d_DA"]) > TOL_DA:
        bad.append(f"D...A {d_da} vs {dep['d_DA']}")
    if d_ha is not None and dep["d_HA"] is not None \
            and abs(d_ha - dep["d_HA"]) > TOL_HA:
        bad.append(f"H...A {d_ha} vs {dep['d_HA']}")
    if ang is not None and dep["angle"] is not None \
            and abs(ang - dep["angle"]) > TOL_ANG:
        bad.append(f"angle {ang} vs {dep['angle']}")
    return bad


# --------------------------------------------------------------------------
# PLATON, headless
# --------------------------------------------------------------------------

#: NOMOVE keeps PLATON's frame equal to the coordinates we hand it (its
#: `Move` column then reads 1.555), so its ARU codes are comparable with our
#: operators; CALC INTRA produces the ring/plane analysis the two pi tables
#: hang off, CALC INTER the contact and hydrogen-bond tables.
PLATON_INSTRUCTIONS = ("NOMOVE", "CALC INTRA", "CALC INTER")


def platon_spf(xs, title: str, instructions=PLATON_INSTRUCTIONS) -> str:
    """A PLATON .spf holding EXACTLY the model the engine was given.

    PLATON reads instructions from the input file itself and stops at END,
    which is what makes a headless run possible on Windows: the interactive
    `>>` prompt is never reached (`platon -u` is the only other unattended
    mode this build has, and it writes no .lis)."""
    a, b, c, al, be, ga = xs.unit_cell().parameters()
    lines = [f"TITL {title[:60]}",
             "CELL 0.71073 %.5f %.5f %.5f %.4f %.4f %.4f" % (a, b, c, al, be,
                                                             ga),
             "SPGR %s" % str(xs.space_group_info()).replace(" ", "")]
    for sc in xs.scatterers():
        x, y, z = sc.site
        lines.append("ATOM %-8s %10.5f %10.5f %10.5f %7.4f"
                     % (sc.label, x, y, z, sc.occupancy))
    lines.extend(instructions)
    lines.append("END")
    return "\n".join(lines) + "\n"


def platon_calc_all(xs, title: str, job: Path, timeout_s: int = 600,
                    instructions=PLATON_INSTRUCTIONS) -> str:
    """Run PLATON in `job` and return the .lis text ("" on failure).

    PLATON is known to idle instead of exiting, so the listing is polled for
    completeness and the process is killed - same pattern as
    `refine/tools_deliver.py`."""
    job.mkdir(parents=True, exist_ok=True)
    (job / "m.spf").write_text(platon_spf(xs, title, instructions),
                               encoding="ascii")
    lis = job / "m.lis"
    with open(job / "stdout.txt", "wb") as so:
        proc = subprocess.Popen(
            [str(PLATON_EXE), "m.spf"], cwd=str(job),
            stdin=subprocess.DEVNULL, stdout=so, stderr=subprocess.STDOUT,
            env=dict(os.environ), creationflags=getattr(
                subprocess, "CREATE_NO_WINDOW", 0))
        t0, last, stable = time.time(), -1, 0
        try:
            while time.time() - t0 < timeout_s:
                if proc.poll() is not None:
                    break
                if lis.exists():
                    size = lis.stat().st_size
                    stable = stable + 1 if size and size == last else 0
                    last = size
                    if stable >= 4:
                        break
                time.sleep(1.0)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=15)
    if not lis.exists():
        return ""
    text = lis.read_text(encoding="utf-8", errors="replace")
    return text if "NORMAL END of PLATON" in text or "Analysis of" in text \
        else ""


_NUM_RE = re.compile(r"-?\d*\.?\d+")
#: "ARU = Asymmetric Residue Unit encoded as sklm.nn, with s = symmetry op,
#: klm = translation, nn = residue #" (PLATON's own legend)
_ARU_RE = re.compile(r"\[\s*(\d{4,6})\.(\d+)\s*\]")


def platon_symops(text: str) -> dict[int, str]:
    """PLATON's numbered operator list, as printed under Space Group
    Symmetry - the key to its `sklm` ARU codes."""
    ops: dict[int, str] = {}
    for m in re.finditer(r"^\s*(\d+)\s+(-?\s*[XYZxyz0-9/+\- ]*?,"
                         r"\s*-?\s*[XYZxyz0-9/+\- ]*?,"
                         r"\s*-?\s*[XYZxyz0-9/+\- ]+?)\s*$", text, re.M):
        body = m.group(2).replace(" ", "")
        if body.count(",") == 2 and any(c in body for c in "XYZxyz"):
            ops.setdefault(int(m.group(1)), body)
    return ops


def decode_aru(code: str, symops: dict[int, str]):
    """`sklm` -> rt_mx, using PLATON's own operator numbering."""
    s, klm = int(code[:-3]), code[-3:]
    base = symops.get(s)
    if base is None:
        return None
    t = [int(klm[i]) - 5 for i in range(3)]
    return _translation(*t).multiply(_rt(base))


_SECTIONS = {
    "hbond": "Analysis of Potential Hydrogen Bonds",
    "pipi": "Analysis of Short Ring-Interactions",
    "chpi": "Analysis of X-H...Cg(Pi-Ring) Interactions",
    "contacts": "Analysis of Short Intra- and Inter-molecular Contacts",
}


def _section(text: str, head: str) -> str:
    """The listing between an `Analysis of ...` header and the next one."""
    heads = [m.start() for m in re.finditer(r"^Analysis of ", text, re.M)]
    for i, pos in enumerate(heads):
        if text[pos:pos + len(head)] == head:
            end = heads[i + 1] if i + 1 < len(heads) else len(text)
            return text[pos:end]
    return ""


def parse_platon(text: str) -> dict:
    """PLATON's three interaction tables + its ring definitions.

    Rows are read only from inside their own section, so the `Y-X...Cg`
    (non-hydrogen) table can never be mistaken for the `X-H...Cg` one."""
    symops = platon_symops(text)
    out: dict = {"hbond": [], "pipi": [], "chpi": [], "contacts": [],
                 "rings": {}, "symops": symops}

    for m in re.finditer(r"^\s*(\d+)-Membered Ring \(\s*(\d+)\)\s*(.*)$",
                         text, re.M):
        labels = [t.strip() for t in re.split(r"\s*-->\s*", m.group(3))
                  if t.strip()]
        out["rings"][int(m.group(2))] = labels

    def _op(code):
        rt = decode_aru(code, symops)
        return str(rt) if rt is not None else None

    # "1   1 N1    --H1     ..O2     [  1655.01]  0.83  2.05  2.7973  149"
    hb = re.compile(r"^\s*\d+\s+\S*\s*\d+\s+(\S+)\s*--\s*(\S+)\s*\.\.\s*"
                    r"(\S+)\s*\[\s*(\d{4,6})\.(\d+)\]\s+(.*)$")
    for line in _section(text, _SECTIONS["hbond"]).splitlines():
        m = hb.match(line)
        if not m:
            continue
        nums = [float(v) for v in _NUM_RE.findall(m.group(6))]
        if len(nums) < 4:
            continue
        out["hbond"].append({
            "D": m.group(1), "H": m.group(2), "A": m.group(3),
            "aru": m.group(4), "op": _op(m.group(4)),
            "d_DH": nums[0], "d_HA": nums[1], "d_DA": nums[2],
            "angle": nums[3]})

    # "Cg1 [ 1] -> Cg2 [  2666.02]   4.5106 <P Q R S> alpha beta gamma ..."
    pp = re.compile(r"^Cg(\d+)\s+\[\s*\d+\]\s*->\s*Cg(\d+)\s+\[\s*(\d{4,6})"
                    r"\.(\d+)\]\s+(.*)$")
    for line in _section(text, _SECTIONS["pipi"]).splitlines():
        m = pp.match(line)
        if not m:
            continue
        nums = [float(v) for v in _NUM_RE.findall(m.group(5))]
        if len(nums) < 9:
            continue
        out["pipi"].append({
            "I": int(m.group(1)), "J": int(m.group(2)), "aru": m.group(3),
            "op": _op(m.group(3)), "d_cc": nums[0], "alpha": nums[5],
            "beta": nums[6], "gamma": nums[7], "cgI_perp": nums[8],
            "cgJ_perp": nums[9] if len(nums) > 9 else None,
            "slip": nums[10] if len(nums) > 10 else None})

    # "C2     -H2     [ 1] -> Cg2    [  2566.02]   2.96 <P Q R S> ..."
    xh = re.compile(r"^(\S+)\s+-(\S+)\s+\[\s*\d+\]\s*->\s*Cg(\d+)\s+"
                    r"\[\s*(\d{4,6})\.(\d+)\]\s+(.*)$")
    for line in _section(text, _SECTIONS["chpi"]).splitlines():
        m = xh.match(line)
        if not m:
            continue
        nums = [float(v) for v in _NUM_RE.findall(m.group(6))]
        if len(nums) < 9:
            continue
        out["chpi"].append({
            "X": m.group(1), "H": m.group(2), "ring": int(m.group(3)),
            "aru": m.group(4), "op": _op(m.group(4)),
            "d_HCg": nums[0], "h_perp": nums[5], "gamma": nums[6],
            "angle": nums[7], "d_XCg": nums[8]})

    # " I1A     ....  N4C    [  8544.03]  2.9581<< 3.53 -0.57  <6 coords>
    #   C2A          175.36"  - PLATON's vdW-contact table.  It is the only
    # oracle here for X...Y halogen bonds: the last two fields are the
    # carrier on I and the C-X...Y angle.
    ct = re.compile(r"^\s*(\S+)\s+\.\.\.\.\s+(\S+)\s+"
                    r"\[\s*(?:(\d{4,6})\.(\d+))?\s*\]\s+(.*?)\s*$")
    for line in _section(text, _SECTIONS["contacts"]).splitlines():
        m = ct.match(line)
        if not m:
            continue
        tail = m.group(5)
        d = _NUM_RE.match(tail.strip())
        if not d:
            continue
        ang = re.search(r"(?:^|\s)([A-Za-z]\S*)\s+(\d+(?:\.\d+)?)\s*$", tail)
        code = m.group(3)
        out["contacts"].append({
            "I": m.group(1), "J": m.group(2), "aru": code,
            "op": _op(code) if code else "x,y,z",
            "d": float(d.group(0)), "intra": " Intra" in tail,
            "via": ang.group(1) if ang else None,
            "angle": float(ang.group(2)) if ang else None})
    return out


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def workdirs(tmp_path_factory):
    return tmp_path_factory.mktemp("known-answers")


def _case(slug: str) -> Path:
    for s, p in CASES:
        if s == slug:
            return p
    raise KeyError(slug)


@pytest.fixture(scope="module")
def models(workdirs):
    """{slug: (xs, parts, provenance)} for every benchmark present."""
    out = {}
    for slug, cif in CASES:
        if not cif.exists():
            continue
        d = workdirs / slug
        d.mkdir(parents=True, exist_ok=True)
        out[slug] = known_model(cif, d)
    return out


# --------------------------------------------------------------------------
# 1. every deposited hydrogen-bond row is reproduced
# --------------------------------------------------------------------------

@pytest.mark.parametrize("slug,cif", CASES, ids=[s for s, _ in CASES])
def test_deposited_hbond_table_is_reproduced(slug, cif, models):
    """Author's own table vs `unique`: same partners, same operator, same
    geometry.  A C-H...O / C-H...Cg row of the deposit is answered by `chx`
    / `chpi` - that is this engine's taxonomy, and the geometry still has to
    match."""
    if slug not in models:
        pytest.skip(f"{cif} not present (gitignored benchmark data)")
    xs, parts, _via = models[slug]
    dep = deposited_hbonds(cif)
    assert dep, "the deposit has an empty _geom_hbond loop"
    unique = engine_tables(xs, parts, criteria="platon")["unique"]

    problems = []
    for row in dep:
        if _gap_key(slug, row) in KNOWN_GAPS:
            continue                    # measured by test_documented_gaps_*
        kind, got, note = find_engine_row(row, unique)
        if got is None:
            problems.append(f"{row['D']}-{row['H']}...{row['A']} "
                            f"[{row['code']}]: MISSING ({note})")
            continue
        for bad in compare_row(row, kind, got):
            problems.append(f"{row['D']}-{row['H']}...{row['A']} "
                            f"[{row['code']}] in {kind}: {bad}")
    assert not problems, "\n".join(problems)


@pytest.mark.parametrize("slug,cif", CASES, ids=[s for s, _ in CASES])
def test_documented_gaps_are_boundary_cases_of_the_stated_criterion(
        slug, cif, models):
    """A deposited row we do NOT report must still be measurable and must
    still be explained by the criterion we publish, not by a wrong number.

    For each entry of KNOWN_GAPS: the row really is absent, the geometry
    computed from the deposited model agrees with the deposited table, and
    the quantity that excludes it (H...A vs r_vdW(H)+r_vdW(A)) misses the
    limit by less than the recorded margin.  If the engine ever starts
    finding the row, or drifts further from the limit, this fails."""
    if slug not in models:
        pytest.skip("benchmark data not present")
    gaps = {k: v for k, v in KNOWN_GAPS.items() if k[0] == slug}
    if not gaps:
        pytest.skip("no documented gap for this structure")
    xs, parts, _via = models[slug]
    from crystalpilot.chem.interactions import _Vdw
    vdw = _Vdw()
    uc = xs.unit_cell()
    site = {sc.label.upper(): sc.site for sc in xs.scatterers()}
    elem = _elem_map(xs)
    unique = engine_tables(xs, parts, criteria="platon")["unique"]
    seen = set()
    for row in deposited_hbonds(cif):
        key = _gap_key(slug, row)
        rec = gaps.get(key)
        if rec is None:
            continue
        seen.add(key)
        _kind, got, _n = find_engine_row(row, unique)
        assert got is None, (f"{key} is documented as absent but the engine "
                             f"now reports it: {got} - update KNOWN_GAPS")
        acc = row["op"] * site[row["A"].upper()]
        d_ha = float(uc.distance(site[row["H"].upper()], acc))
        d_da = float(uc.distance(site[row["D"].upper()], acc))
        ang = float(uc.angle(site[row["D"].upper()],
                             site[row["H"].upper()], acc))
        assert abs(d_ha - row["d_HA"]) <= TOL_HA, (key, d_ha, row["d_HA"])
        assert abs(d_da - row["d_DA"]) <= TOL_DA, (key, d_da, row["d_DA"])
        assert abs(ang - row["angle"]) <= TOL_ANG, (key, ang, row["angle"])
        limit = vdw("H") + vdw(elem[row["A"].upper()])
        assert d_ha > limit, (f"{key}: {d_ha} is INSIDE the {limit} A "
                              f"window, so its absence is a bug, not a "
                              f"boundary case")
        assert d_ha - limit <= rec["margin_A"], (
            f"{key}: {d_ha - limit:.4f} A outside the {limit} A window, "
            f"more than the documented {rec['margin_A']} A - the reason on "
            f"record ({rec['why']}) no longer describes what happens")
    assert seen == set(gaps), f"KNOWN_GAPS rows not in the deposit: "\
                              f"{set(gaps) - seen}"


@pytest.mark.parametrize("slug,cif", CASES, ids=[s for s, _ in CASES])
def test_deposited_rows_land_in_the_expected_table(slug, cif, models):
    """The kind a deposited row lands in is decided by the DONOR ELEMENT,
    never by the structure: a polar donor -> hbond, a carbon carrier ->
    chx (atom acceptor) or chpi (ring acceptor)."""
    if slug not in models:
        pytest.skip("benchmark data not present")
    xs, parts, _via = models[slug]
    from crystalpilot.chem.interactions import HBOND_ELEMS
    unique = engine_tables(xs, parts, criteria="platon")["unique"]
    elem_of = _elem_map(xs)
    for row in deposited_hbonds(cif):
        kind, got, _n = find_engine_row(row, unique)
        if got is None:
            continue
        donor_el = elem_of.get(row["D"].upper())
        acceptor_is_ring = row["A"].upper().startswith("CG")
        if donor_el in HBOND_ELEMS:
            want = "hbond"
        else:
            want = "chpi" if acceptor_is_ring else "chx"
        assert kind == want, (f"{slug} {row['D']}-{row['H']}...{row['A']}: "
                              f"donor element {donor_el} -> expected {want}, "
                              f"engine put it in {kind}")


@pytest.mark.parametrize("slug,cif", CASES, ids=[s for s, _ in CASES])
def test_olex2_preset_keeps_every_deposited_row_inside_its_own_limits(
        slug, cif, models):
    """The narrow preset must not lose a row it claims: every deposited
    hbond row with a polar donor and D...A <= 2.9 A has to be in the olex2
    table too (the preset's only distance rule)."""
    if slug not in models:
        pytest.skip("benchmark data not present")
    xs, parts, _via = models[slug]
    from crystalpilot.chem.interactions import HBOND_ELEMS
    unique = engine_tables(xs, parts, criteria="olex2")["unique"]
    elem_of = _elem_map(xs)
    missing = []
    for row in deposited_hbonds(cif):
        if elem_of.get(row["D"].upper()) not in HBOND_ELEMS:
            continue
        if row["d_DA"] is None or row["d_DA"] > 2.9:
            continue
        kind, got, _n = find_engine_row(row, unique)
        if got is None or kind != "hbond":
            missing.append(f"{row['D']}-{row['H']}...{row['A']} "
                           f"[{row['code']}] d_DA={row['d_DA']}")
    assert not missing, "\n".join(missing)


@pytest.mark.parametrize("slug,cif", CASES, ids=[s for s, _ in CASES])
def test_extra_rows_obey_the_criteria_they_are_reported_under(
        slug, cif, models):
    """Rows we report beyond the author's selection are not free: each one
    must satisfy the emitted-when rule of its own kind, and `passes` must be
    exactly the criterion re-evaluated from the row's own numbers."""
    if slug not in models:
        pytest.skip("benchmark data not present")
    xs, parts, _via = models[slug]
    res = engine_tables(xs, parts, criteria="platon")
    crit, unique = res["criteria"], res["unique"]
    for row in unique["hbond"]:
        if row.get("angle") is None:
            continue
        assert row["passes"] is (row["angle"] >= crit["hbond"][
            "angle_DHA_min_deg"]), row
    for row in unique["chx"]:
        assert row["passes"] is (row["angle"] >= crit["chx"][
            "angle_CHA_min_deg"]), row
    for row in unique["pipi"]:
        want = (row["alpha"] <= crit["pipi"]["alpha_max_deg"]
                and min(row["slip_ab"], row["slip_ba"])
                <= crit["pipi"]["slip_max_A"])
        assert row["passes"] is want, row
        assert row["d_cc"] <= crit["pipi"]["d_cc_max_A"] + 1e-9, row


# --------------------------------------------------------------------------
# 2. PLATON as an independent oracle
# --------------------------------------------------------------------------

def _platon_or_skip(slug, models, workdirs) -> dict:
    if not PLATON_EXE.exists():
        pytest.skip(f"platon.exe not found at {PLATON_EXE}")
    if slug not in models:
        pytest.skip("benchmark data not present")
    xs, parts, _via = models[slug]
    text = platon_calc_all(xs, slug, workdirs / ("platon_" + slug))
    if not text:
        pytest.skip("PLATON produced no listing")
    return parse_platon(text)


@pytest.mark.slow
@pytest.mark.parametrize("slug", [s for s, _ in CASES])
def test_platon_hydrogen_bonds_are_all_found(slug, models, workdirs):
    """Every D-H...A PLATON reports (its own criteria: d(H...A) <
    r+r-0.12 A, angle > 100 deg) must be in our hbond or chx table with the
    same H...A and angle.  PLATON's window is INSIDE ours (we use r+r and
    110 deg for hbond / 120 deg for chx), so a miss is our bug."""
    pl = _platon_or_skip(slug, models, workdirs)
    xs, parts, _via = models[slug]
    from crystalpilot.chem.interactions import (CHX_ACCEPTOR_ELEMS,
                                                HBOND_ELEMS)
    unique = engine_tables(xs, parts, criteria="platon")["unique"]
    elem_of = _elem_map(xs)
    problems = []
    for row in pl["hbond"]:
        a_el = elem_of.get(row["A"].upper())
        d_el = elem_of.get(row["D"].upper())
        if a_el not in (HBOND_ELEMS | CHX_ACCEPTOR_ELEMS):
            continue                       # outside the kinds we define
        if d_el not in (HBOND_ELEMS | {"C"}):
            continue
        dep = {"D": row["D"], "H": row["H"], "A": row["A"],
               "code": row["aru"], "op": _rt(row["op"] or "x,y,z"),
               "d_HA": row["d_HA"], "d_DA": row["d_DA"],
               "angle": row["angle"]}
        kind, got, note = find_engine_row(dep, unique)
        if got is None:
            problems.append(f"{row['D']}-{row['H']}...{row['A']} "
                            f"[{row['aru']}] d_HA={row['d_HA']}: {note}")
            continue
        # PLATON prints 2 decimals for H...A and whole degrees
        if abs((got.get("d_HA") or 0) - row["d_HA"]) > 0.02:
            problems.append(f"{row['D']}...{row['A']}: H...A "
                            f"{got.get('d_HA')} vs PLATON {row['d_HA']}")
        if abs((got.get("angle") or 0) - row["angle"]) > 1.0:
            problems.append(f"{row['D']}...{row['A']}: angle "
                            f"{got.get('angle')} vs PLATON {row['angle']}")
    assert not problems, "\n".join(problems)


def _ring_key(labels) -> frozenset:
    """Ring identity = its set of ASU atom LABELS.

    PLATON writes the symmetry image of an atom as `C14_a`, so the suffix is
    stripped: a ring that closes through a symmetry element is then the same
    key as the three-atom census entry this engine reports for it."""
    return frozenset(str(x).split("_")[0].upper() for x in labels)


def engine_ring_defs(xs, parts):
    """(ring definitions, symmetry-closed census) as the engine sees them."""
    from crystalpilot.chem.interactions import _Model
    mdl = _Model(xs, parts=parts)
    defs = [{"key": _ring_key(r["key"].split(",")),
             "aromatic": bool(r["aromatic"])} for r in mdl.rings]
    census = [{"key": _ring_key(r["key"].split(",")), "op": r["op"]}
              for r in mdl.rings_through_symmetry]
    return defs, census


#: PLATON's ring/plane search runs 3..24-membered; find_rings runs 5 and 6
_OUR_RING_SIZES = (5, 6)


def classify_platon_ring(labels, defs, census) -> str:
    """Why a PLATON ring is or is not one of ours - a fixed vocabulary, all
    of it read off the engine's OWN published criteria, never off a label."""
    key = _ring_key(labels)
    for d in defs:
        if d["key"] == key:
            return "ours_aromatic" if d["aromatic"] else "ours_not_aromatic"
    for c in census:
        if c["key"] == key:
            return "closes_through_symmetry"
    if len(key) not in _OUR_RING_SIZES:
        return "size_outside_find_rings"
    return "unexplained"


def part_of_map(xs, parts) -> dict[str, int]:
    """{LABEL: |PART|}; 0 for the ordered part of the model."""
    labels = [sc.label.upper() for sc in xs.scatterers()]
    if not parts:
        return dict.fromkeys(labels, 0)
    if isinstance(parts, dict):
        up = {str(k).upper(): abs(int(v or 0)) for k, v in parts.items()}
        return {lb: up.get(lb, 0) for lb in labels}
    return {lb: abs(int(p or 0)) for lb, p in zip(labels, parts)}


def cross_part(part_of: dict[str, int], *labels) -> bool:
    """The engine's D19 rule: two DIFFERENT non-zero PARTs never interact."""
    seen = {part_of.get(str(x).split("_")[0].upper(), 0) for x in labels}
    return len({p for p in seen if p}) > 1


@pytest.mark.slow
@pytest.mark.parametrize("slug", RING_CASES)
def test_platon_ring_geometry_matches(slug, models, workdirs):
    """pi-pi: for every PLATON Cg...Cg row that is inside OUR window
    (Cg-Cg <= 4.0 A, alpha <= 30 deg) the engine must have the row, with
    Cg-Cg and both perpendicular distances to 0.01 A, alpha to 0.5 deg and
    the slippage to 0.01 A.  PLATON's own window is wider (6.0 A / 20 deg /
    beta < 60 deg), so its extra rows are not a disagreement.

    A PLATON ring that is not one of ours is only allowed through when the
    engine ITSELF says why: a ring it judged non-aromatic (`rings`:
    "aromatic only"), a ring size find_rings does not search, or a ring the
    symmetry-closed census named.  Anything else is `unexplained` and
    fails - which is what stops this test from degenerating into "our table
    is right because it is ours"."""
    pl = _platon_or_skip(slug, models, workdirs)
    xs, parts, _via = models[slug]
    from crystalpilot.chem.interactions import find_interactions
    res = find_interactions(xs, parts=parts, criteria="platon")
    ours = res["unique"]["pipi"]
    defs, census = engine_ring_defs(xs, parts)
    part_of = part_of_map(xs, parts)
    ring_atoms = {n: v for n, v in pl["rings"].items()}
    problems, compared, excused = [], 0, {}
    for row in pl["pipi"]:
        if row["d_cc"] > 4.0 or row["alpha"] > 30.0:
            continue
        la, lb = ring_atoms.get(row["I"]), ring_atoms.get(row["J"])
        if not la or not lb:
            continue
        why = [classify_platon_ring(la, defs, census),
               classify_platon_ring(lb, defs, census)]
        if cross_part(part_of, *(list(la) + list(lb))):
            excused["cross_PART"] = excused.get("cross_PART", 0) + 1
            continue
        skip = [w for w in why if w != "ours_aromatic"]
        if skip:
            if "unexplained" in skip:
                problems.append(f"Cg{row['I']}...Cg{row['J']} "
                                f"[{row['aru']}] d_cc={row['d_cc']}: a ring "
                                f"the engine neither has nor explains "
                                f"({la} / {lb})")
            else:
                excused[skip[0]] = excused.get(skip[0], 0) + 1
            continue
        ka, kb = _ring_key(la), _ring_key(lb)
        hits = [r for r in ours
                if {_ring_key(r["ring_a"].split(",")),
                    _ring_key(r["ring_b"].split(","))} == {ka, kb}
                and abs(r["d_cc"] - row["d_cc"]) <= 0.01]
        if not hits:
            problems.append(f"Cg{row['I']}...Cg{row['J']} [{row['aru']}] "
                            f"d_cc={row['d_cc']} alpha={row['alpha']}: "
                            f"absent from unique.pipi")
            continue
        got = hits[0]
        compared += 1
        if abs(got["alpha"] - row["alpha"]) > 0.5:
            problems.append(f"alpha {got['alpha']} vs {row['alpha']}")
        perps = sorted([got["d_perp_ab"], got["d_perp_ba"]])
        pl_perps = sorted([row["cgI_perp"], row["cgJ_perp"]])
        if max(abs(x - y) for x, y in zip(perps, pl_perps)) > 0.01:
            problems.append(f"perp {perps} vs {pl_perps}")
        if row["slip"] is not None:
            slips = (got["slip_ab"], got["slip_ba"])
            if min(abs(s - row["slip"]) for s in slips) > 0.01:
                problems.append(f"slippage {slips} vs {row['slip']}")
    assert not problems, "\n".join(problems)
    need = MIN_PIPI_COMPARED.get(slug, 0)
    assert compared >= need, (f"{slug}: only {compared} PLATON pi-pi rows "
                              f"compared (need {need}); excused {excused}")
    if compared == 0:
        pytest.skip(f"no PLATON ring pair inside our pi-pi window here "
                    f"(excused: {excused or 'none'})")


@pytest.mark.slow
@pytest.mark.parametrize("slug", RING_CASES)
def test_platon_ch_pi_geometry_matches(slug, models, workdirs):
    """C-H...pi: every PLATON X-H...Cg row with a carbon carrier and
    H...Cg <= 3.2 A (our own limit) must be in `unique.chpi` with H...Cg to
    0.01 A and the C-H...Cg angle to 1 deg; PLATON's gamma (Cg-H vector vs
    ring normal) must equal acos(d_perp / d_HCg) from our row to 0.5 deg.

    Two exemptions, both taken from the engine's published rules rather than
    from the fixture: a carrier and a ring in DIFFERENT SHELX PARTs never
    interact here (D19) while PLATON, handed a .spf that carries only
    occupancies, has no way to know the components apart; and a ring the
    engine cannot represent is excused only when its own census names it."""
    pl = _platon_or_skip(slug, models, workdirs)
    xs, parts, _via = models[slug]
    from crystalpilot.chem.interactions import find_interactions
    res = find_interactions(xs, parts=parts, criteria="platon")
    ours = res["unique"]["chpi"]
    elem_of = _elem_map(xs)
    defs, census = engine_ring_defs(xs, parts)
    part_of = part_of_map(xs, parts)
    ring_atoms = {n: v for n, v in pl["rings"].items()}
    problems, compared, excused = [], 0, {}
    for row in pl["chpi"]:
        if elem_of.get(row["X"].upper()) != "C" or row["d_HCg"] > 3.2:
            continue
        labels = ring_atoms.get(row["ring"]) or []
        if cross_part(part_of, row["X"], *labels):
            excused["cross_PART"] = excused.get("cross_PART", 0) + 1
            continue
        why = classify_platon_ring(labels, defs, census) if labels else None
        if why not in (None, "ours_aromatic"):
            if why == "unexplained":
                problems.append(f"{row['X']}-{row['H']}...Cg{row['ring']}: "
                                f"a ring the engine neither has nor "
                                f"explains ({labels})")
            else:
                excused[why] = excused.get(why, 0) + 1
            continue
        key = _ring_key(labels) if labels else None
        hits = [r for r in ours
                if (r["c"] or "").upper() == row["X"].upper()
                and (r["h"] or "").upper() == row["H"].upper()
                and (key is None or _ring_key(r["ring"].split(",")) == key)
                and abs(r["d_HCg"] - row["d_HCg"]) <= 0.01]
        if not hits:
            problems.append(f"{row['X']}-{row['H']}...Cg{row['ring']} "
                            f"[{row['aru']}] H..Cg={row['d_HCg']}: absent "
                            f"from unique.chpi")
            continue
        got = hits[0]
        compared += 1
        if abs(got["angle"] - row["angle"]) > 1.0:
            problems.append(f"{row['X']}-{row['H']}: angle {got['angle']} "
                            f"vs PLATON {row['angle']}")
        gamma = math.degrees(math.acos(
            max(-1.0, min(1.0, got["d_perp"] / got["d_HCg"]))))
        if abs(gamma - row["gamma"]) > 0.5:
            problems.append(f"{row['X']}-{row['H']}: gamma {gamma:.2f} vs "
                            f"PLATON {row['gamma']}")
    assert not problems, "\n".join(problems)
    if compared == 0:
        pytest.skip(f"no PLATON X-H...Cg row inside our window here "
                    f"(excused: {excused or 'none'})")


@pytest.mark.slow
@pytest.mark.parametrize("slug", ["xb_tfib_bipy_cod2201150",
                                  "twin_iodouracil_cod2020129"])
def test_platon_confirms_the_halogen_bond_table(slug, models, workdirs):
    """Halogen bonds have no `_geom_*` loop of their own in a CIF, so
    PLATON's vdW-contact table is the known answer: for every X...Y contact
    it lists with a halogen donor and a Lewis-base acceptor and a distance
    inside OUR window (r_vdW(X)+r_vdW(Y), cctbx radii), the engine must have
    the row with the same X...Y distance (0.01 A), the same operator, and -
    when PLATON printed a carrier and its angle - the same C-X...Y angle
    (0.5 deg), with `passes` being exactly the IUPAC directionality test
    (>= 155 deg) applied to it."""
    pl = _platon_or_skip(slug, models, workdirs)
    if not pl.get("contacts"):
        pytest.skip("PLATON listed no contact table")
    xs, parts, _via = models[slug]
    from crystalpilot.chem.interactions import (HALOGEN_ACCEPTOR_ELEMS,
                                                HALOGEN_DONOR_ELEMS, _Vdw)
    res = engine_tables(xs, parts, criteria="platon")
    ours = res["unique"]["halogen"]
    limit = res["criteria"]["halogen"]["angle_CXY_min_deg"]
    elem, vdw = _elem_map(xs), _Vdw()
    problems, compared, with_angle = [], 0, 0
    for row in pl["contacts"]:
        ex, ey = elem.get(row["I"].upper()), elem.get(row["J"].upper())
        if ex not in HALOGEN_DONOR_ELEMS or ey not in HALOGEN_ACCEPTOR_ELEMS:
            continue
        if row["d"] > vdw(ex) + vdw(ey):
            continue                     # PLATON's radii are wider than ours
        hits = [r for r in ours
                if (r["x"] or "").upper() == row["I"].upper()
                and (r["a"] or "").upper() == row["J"].upper()
                and abs(r["d_XA"] - row["d"]) <= 0.01]
        if not hits:
            problems.append(f"{row['I']}...{row['J']} [{row['aru']}] "
                            f"d={row['d']}: absent from unique.halogen")
            continue
        compared += 1
        if row["aru"] and not any(_same_op(h["op"], row["op"]) for h in hits):
            problems.append(f"{row['I']}...{row['J']}: ops "
                            f"{[h['op'] for h in hits]} vs PLATON "
                            f"{row['op']}")
        for got in hits:
            if got["passes"] is not (got["angle"] >= limit):
                problems.append(f"{row['I']}...{row['J']}: "
                                f"passes={got['passes']} but angle "
                                f"{got['angle']} vs limit {limit}")
        if row["via"] is None or elem.get(row["via"].upper()) in (None, "H"):
            continue                     # PLATON printed no carrier angle
        via = [h for h in hits
               if (h["c"] or "").upper() == row["via"].upper()]
        if not via:
            problems.append(f"{row['I']}...{row['J']}: no row through the "
                            f"carrier {row['via']} PLATON used")
            continue
        with_angle += 1
        if abs(via[0]["angle"] - row["angle"]) > 0.5:
            problems.append(f"{row['via']}-{row['I']}...{row['J']}: angle "
                            f"{via[0]['angle']} vs PLATON {row['angle']}")
    assert not problems, "\n".join(problems)
    assert compared, "no halogen contact was compared - check the fixture"


# --------------------------------------------------------------------------
# report mode
# --------------------------------------------------------------------------

def _report():                                   # pragma: no cover - manual
    import json
    import sys
    import tempfile

    from crystalpilot.chem.interactions import (CHX_ACCEPTOR_ELEMS,
                                                HBOND_ELEMS)
    only = sys.argv[1:]
    tmp = Path(os.environ.get("KNOWN_ANSWERS_WORKDIR")
               or tempfile.mkdtemp(prefix="known-"))
    summary = []
    for slug, cif in CASES:
        if only and slug not in only:
            continue
        if not cif.exists():
            print(f"== {slug}: MISSING {cif}")
            continue
        d = tmp / slug
        d.mkdir(parents=True, exist_ok=True)
        xs, parts, via = known_model(cif, d)
        elem = _elem_map(xs)
        dep = deposited_hbonds(cif)
        res = engine_tables(xs, parts, criteria="platon")
        res2 = engine_tables(xs, parts, criteria="olex2")
        unique = res["unique"]
        rows = []
        for row in dep:
            kind, got, note = find_engine_row(row, unique)
            bad = compare_row(row, kind, got) if got is not None else [note]
            rows.append({"row": f"{row['D']}-{row['H']}...{row['A']} "
                                f"[{row['code']}]", "kind": kind,
                         "problems": bad})
        pl, pl_bad = {}, []
        if PLATON_EXE.exists():
            text = platon_calc_all(xs, slug, tmp / ("pl_" + slug))
            (d / "platon.lis").write_text(text, encoding="utf-8")
            if text:
                pl = parse_platon(text)
        n_hb = 0
        for row in pl.get("hbond") or ():
            if elem.get(row["A"].upper()) not in (HBOND_ELEMS
                                                  | CHX_ACCEPTOR_ELEMS):
                continue
            if elem.get(row["D"].upper()) not in (HBOND_ELEMS | {"C"}):
                continue
            probe = {"D": row["D"], "H": row["H"], "A": row["A"],
                     "code": row["aru"], "op": _rt(row["op"] or "x,y,z"),
                     "d_HA": row["d_HA"], "d_DA": row["d_DA"],
                     "angle": row["angle"]}
            kind, got, note = find_engine_row(probe, unique)
            n_hb += 1
            if got is None:
                pl_bad.append(f"HB MISS {row['D']}-{row['H']}...{row['A']}"
                              f" [{row['aru']}] d_HA={row['d_HA']} "
                              f"ang={row['angle']}: {note}")
                continue
            if not _same_op(got["op"], probe["op"]):
                pl_bad.append(f"HB OP {row['D']}...{row['A']}: {got['op']} "
                              f"vs {row['op']}")
            if abs((got.get("d_HA") or 0) - row["d_HA"]) > 0.02:
                pl_bad.append(f"HB d_HA {row['D']}...{row['A']}: "
                              f"{got.get('d_HA')} vs {row['d_HA']}")
            if abs((got.get("angle") or 0) - row["angle"]) > 1.0:
                pl_bad.append(f"HB ang {row['D']}...{row['A']}: "
                              f"{got.get('angle')} vs {row['angle']}")
        defs, census = engine_ring_defs(xs, parts)
        part_of = part_of_map(xs, parts)
        rings = pl.get("rings") or {}
        tally = {"pp_compared": 0, "cp_compared": 0, "xb_compared": 0,
                 "hb_compared": n_hb, "pp_excused": {}, "cp_excused": {}}
        for row in pl.get("pipi") or ():
            if row["d_cc"] > 4.0 or row["alpha"] > 30.0:
                continue
            la, lb = rings.get(row["I"]), rings.get(row["J"])
            if not la or not lb:
                continue
            if cross_part(part_of, *(list(la) + list(lb))):
                tally["pp_excused"]["cross_PART"] = tally[
                    "pp_excused"].get("cross_PART", 0) + 1
                continue
            why = [classify_platon_ring(la, defs, census),
                   classify_platon_ring(lb, defs, census)]
            skip = [w for w in why if w != "ours_aromatic"]
            if skip:
                tally["pp_excused"][skip[0]] = tally[
                    "pp_excused"].get(skip[0], 0) + 1
                if "unexplained" in skip:
                    pl_bad.append(f"PP UNEXPLAINED Cg{row['I']}..Cg"
                                  f"{row['J']} {la} {lb}")
                continue
            ka, kb = _ring_key(la), _ring_key(lb)
            hits = [r for r in unique["pipi"]
                    if {_ring_key(r["ring_a"].split(",")),
                        _ring_key(r["ring_b"].split(","))} == {ka, kb}
                    and abs(r["d_cc"] - row["d_cc"]) <= 0.01]
            if not hits:
                pl_bad.append(f"PP MISS Cg{row['I']}..Cg{row['J']} "
                              f"[{row['aru']}] d={row['d_cc']} "
                              f"alpha={row['alpha']}")
                continue
            g = hits[0]
            tally["pp_compared"] += 1
            if abs(g["alpha"] - row["alpha"]) > 0.5:
                pl_bad.append(f"PP alpha {g['alpha']} vs {row['alpha']}")
            if row["slip"] is not None and min(
                    abs(g["slip_ab"] - row["slip"]),
                    abs(g["slip_ba"] - row["slip"])) > 0.01:
                pl_bad.append(f"PP slip {g['slip_ab']}/{g['slip_ba']} vs "
                              f"{row['slip']}")
            pl_op = row["op"] or "x,y,z"
            if not _same_op(g["op"], pl_op) \
                    and not _op_mod_lattice(g["op"], pl_op):
                pl_bad.append(f"PP op {g['op']} vs {row['op']}")
        for row in pl.get("chpi") or ():
            if elem.get(row["X"].upper()) != "C" or row["d_HCg"] > 3.2:
                continue
            labels = rings.get(row["ring"]) or []
            if cross_part(part_of, row["X"], *labels):
                tally["cp_excused"]["cross_PART"] = tally[
                    "cp_excused"].get("cross_PART", 0) + 1
                continue
            why = classify_platon_ring(labels, defs, census) if labels else None
            if why not in (None, "ours_aromatic"):
                tally["cp_excused"][why] = tally[
                    "cp_excused"].get(why, 0) + 1
                continue
            key = _ring_key(labels) if labels else None
            hits = [r for r in unique["chpi"]
                    if (r["c"] or "").upper() == row["X"].upper()
                    and (r["h"] or "").upper() == row["H"].upper()
                    and (key is None
                         or _ring_key(r["ring"].split(",")) == key)
                    and abs(r["d_HCg"] - row["d_HCg"]) <= 0.01]
            if not hits:
                pl_bad.append(f"CP MISS {row['X']}-{row['H']}..Cg"
                              f"{row['ring']} [{row['aru']}] "
                              f"d={row['d_HCg']}")
                continue
            g = hits[0]
            tally["cp_compared"] += 1
            if abs(g["angle"] - row["angle"]) > 1.0:
                pl_bad.append(f"CP ang {g['angle']} vs {row['angle']}")
            gamma = math.degrees(math.acos(
                max(-1.0, min(1.0, g["d_perp"] / g["d_HCg"]))))
            if abs(gamma - row["gamma"]) > 0.5:
                pl_bad.append(f"CP gamma {gamma:.2f} vs {row['gamma']}")
        from crystalpilot.chem.interactions import (HALOGEN_ACCEPTOR_ELEMS,
                                                    HALOGEN_DONOR_ELEMS, _Vdw)
        vdw = _Vdw()
        for row in pl.get("contacts") or ():
            ex, ey = elem.get(row["I"].upper()), elem.get(row["J"].upper())
            if (ex not in HALOGEN_DONOR_ELEMS
                    or ey not in HALOGEN_ACCEPTOR_ELEMS):
                continue
            if row["d"] > vdw(ex) + vdw(ey):
                continue
            hits = [r for r in unique["halogen"]
                    if (r["x"] or "").upper() == row["I"].upper()
                    and (r["a"] or "").upper() == row["J"].upper()
                    and abs(r["d_XA"] - row["d"]) <= 0.01]
            if not hits:
                pl_bad.append(f"XB MISS {row['I']}..{row['J']} "
                              f"[{row['aru']}] d={row['d']}")
                continue
            tally["xb_compared"] += 1
            if row["via"] and elem.get(row["via"].upper()) not in (None, "H"):
                carrier = [h for h in hits
                           if (h["c"] or "").upper() == row["via"].upper()]
                if not carrier:
                    pl_bad.append(f"XB carrier {row['via']} missing for "
                                  f"{row['I']}..{row['J']}")
                elif abs(carrier[0]["angle"] - row["angle"]) > 0.5:
                    pl_bad.append(f"XB ang {carrier[0]['angle']} vs "
                                  f"{row['angle']}")
        rec = {
            "slug": slug, "via": via, "n_atoms": xs.scatterers().size(),
            "sg": str(xs.space_group_info()), "deposited": len(dep),
            "matched": sum(1 for r in rows if not r["problems"]),
            "kinds": {str(k): sum(1 for r in rows if r["kind"] == k)
                      for k in ("hbond", "chx", "chpi", None)},
            "problems": [r for r in rows if r["problems"]],
            "unique_platon": res["counts"]["unique"],
            "passing_platon": res["counts"]["passing"],
            "unique_olex2": res2["counts"]["unique"],
            "rings": len(res["rings"]),
            "aromatic": sum(1 for r in res["rings"] if r["aromatic"]),
            "platon_hbond": len(pl.get("hbond") or []),
            "platon_pipi": len(pl.get("pipi") or []),
            "platon_chpi": len(pl.get("chpi") or []),
            "platon_rings": len(pl.get("rings") or {}),
            "platon_problems": pl_bad,
            "platon_compared": tally,
        }
        summary.append(rec)
        print(json.dumps(rec, ensure_ascii=False))
        if pl:
            (d / "platon.json").write_text(
                json.dumps(pl, default=str, ensure_ascii=False, indent=1),
                encoding="utf-8")
        (d / "engine.json").write_text(
            json.dumps({"unique": unique, "criteria": res["criteria"],
                        "rings": res["rings"]}, default=str,
                       ensure_ascii=False, indent=1), encoding="utf-8")
    print("\nWORKDIR:", tmp)
    tot = sum(r["deposited"] for r in summary)
    ok = sum(r["matched"] for r in summary)
    print(f"TOTAL deposited rows {tot}, matched {ok}, "
          f"mismatched {tot - ok}; PLATON problems "
          f"{sum(len(r['platon_problems']) for r in summary)}")


if __name__ == "__main__":                       # pragma: no cover
    _report()


# --------------------------------------------------------------------------
# round-3 R5-F: anion-pi and pi-pi against the authors' own numbers
# --------------------------------------------------------------------------

def test_anion_pi_known_answer_cod2232050(models):
    """Gomathi & Muthiah, Acta Cryst. E67 (2011) o2762 (COD 2232050): the
    abstract gives Cg1...F4(i) = 3.178 (3) A and Cg1...F2(i) = 3.654 (3) A
    for the tetrafluoroborate over the triazinium ring, (i) = 1-x, 2-y,
    1-z, and a face-to-face stack of the ring with its inversion image at
    Cg...Cg 3.3361 (12) A, interplanar 3.333 A, slip angle 2.46 deg.

    The engine measures anion-pi from the ANION CENTROID (B) to the ring
    centroid, so the deposit's atom-to-centroid numbers are re-measured
    here on the same model under the operator the engine's row names: the
    row must be the same contact, and the geometry must agree."""
    slug = "anionpi_triazinium_bf4_cod2232050"
    if slug not in models:
        pytest.skip("COD 2232050 not present")
    import numpy as np
    from cctbx import sgtbx

    from crystalpilot.chem.interactions import find_interactions
    xs, parts, _via = models[slug]
    res = find_interactions(xs, parts=parts, criteria="platon")
    ring_labels = {"N1", "C2", "N3", "C4", "N5", "C6"}
    rows = [r for r in res["unique"]["anion_pi"]
            if _ring_key(r["ring"].split(",")) == frozenset(ring_labels)]
    assert rows, res["unique"]["anion_pi"]
    row = rows[0]
    assert row["anion_name"] == "BF4-" and row["passes"] is True
    assert _same_op(row["op"], "-x+1,-y+2,-z+1"), row["op"]
    assert row["offset"] <= 1.0                  # over the ring, not beside it
    # the deposit's own two distances, re-measured on this model under (i)
    uc = xs.unit_cell()
    site = {sc.label.upper(): np.array(sc.site, dtype=float)
            for sc in xs.scatterers()}
    cg = np.mean([np.array(uc.orthogonalize(tuple(site[a])))
                  for a in ring_labels], axis=0)
    op = sgtbx.rt_mx("-x+1,-y+2,-z+1")

    def d_to_cg(label):
        img = np.array(uc.orthogonalize(tuple(op * tuple(site[label]))))
        return float(np.linalg.norm(img - cg))
    # the anion in the engine's row sits at (i): its F4 is the 3.178 A one
    assert abs(d_to_cg("F4") - 3.178) <= 0.01, d_to_cg("F4")
    assert abs(d_to_cg("F2") - 3.654) <= 0.01, d_to_cg("F2")
    # the centroid-to-centroid number the engine reports is the B...Cg one
    assert 3.178 < row["d_cc"] < 4.5 and row["d_perp"] < row["d_cc"]
    # pi-pi: the ring with its inversion image
    pp = [r for r in res["unique"]["pipi"]
          if _ring_key(r["ring_a"].split(",")) == frozenset(ring_labels)
          and _ring_key(r["ring_b"].split(",")) == frozenset(ring_labels)]
    assert pp, res["unique"]["pipi"]
    st = min(pp, key=lambda r: r["d_cc"])
    assert abs(st["d_cc"] - 3.3361) <= 0.002
    assert abs(st["d_perp_ab"] - 3.333) <= 0.005
    assert st["alpha"] <= 0.01                   # inversion image: parallel
    slip_angle = math.degrees(math.asin(st["slip_ab"] / st["d_cc"]))
    assert abs(slip_angle - 2.46) <= 0.05, slip_angle
