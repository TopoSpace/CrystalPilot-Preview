"""Extended-benchmark fetcher: builds benchmark/data_ext from COD deposits.

Assembles ~100 test cases, each = SHELX-format .hkl (measured F^2 + sigma) plus the
human-refined reference CIF, pulled exclusively from the Crystallography Open
Database (COD, https://www.crystallography.net/ -- contents placed in the public
domain by contributors).  Candidate discovery uses COD's result.php CSV interface
filtered on ``has_fobs``; per-case reflection data comes from the COD hkl mirror
(https://www.crystallography.net/cod/<id>.hkl, a CIF-formatted _refln loop or a
raw SHELX file) and is normalised to fixed-format HKLF (3I4, 2F8.2) so that
``iotbx.shelx.hklf`` / SHELXL can read it directly.

Layout produced (all under benchmark/):
    data_ext/<case_id>/<case_id>.hkl        fixed-format h k l F2 sigma(F2)
    data_ext/<case_id>/<case_id>_ref.cif    reference (refined) structure CIF
    data_ext/_cache/                        candidate CSVs + resumable state
    manifest_ext.json                       one record per accepted case

Resumable: accepted and rejected COD ids are remembered in _cache/state.json and
skipped on re-runs (use --retry-rejected to reconsider rejects).  Network access
is throttled to <= 3 requests/s with retry + exponential backoff.

Run:  PYTHONUTF8=1 .venv/Scripts/python.exe benchmark/tools/fetch_ext.py
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import re
import sys
import time
from pathlib import Path

import requests

BENCH = Path(__file__).resolve().parents[1]
DATA = BENCH / "data_ext"
CACHE = DATA / "_cache"
MANIFEST = BENCH / "manifest_ext.json"
COD = "https://www.crystallography.net/cod"
LICENSE = "Public domain (COD; data placed in the public domain by the contributors)"
SEED = 20260828

# COD ids already used by benchmark/public (the original 12 public cases) -- never reuse.
EXCLUDE_COD_IDS = {
    "4120127", "2206821", "2100591", "2210768", "2204276", "2236885",
    "2104364", "2300557", "2202666", "2016645", "2201595", "2019790",
}

QUOTAS = {           # category -> target number of accepted cases
    "mof": 38,
    "organic": 28,
    "inorganic": 13,
    "hard-P1": 5,
    "hard-pseudo": 4,
    "hard-large": 4,
    "hard-twin": 5,
    "hard-disorder": 4,
}

LANTHANIDES = {"La", "Ce", "Pr", "Nd", "Sm", "Eu", "Gd", "Tb", "Dy", "Ho",
               "Er", "Tm", "Yb", "Lu"}
MOF_METALS = {"Zn", "Cu", "Zr", "Co", "Cd", "Fe", "Mn", "Ni", "Ag", "Ca",
              "Mg", "Al", "In", "Pb"} | LANTHANIDES
HEAVY = {"Mo", "W", "Bi", "U", "Nb", "Ta", "Te", "Sb", "Sn", "Re", "Os",
         "Ir", "Pt", "Au", "Hg", "V", "Th"} | LANTHANIDES
ORGANIC_ELEMENTS = {"C", "H", "D", "N", "O", "S", "P", "F", "Cl", "Br", "I", "B"}
# strong indicators of an extended coordination network (IUPAC catena-/poly[
# nomenclature, or explicit framework/coordination-polymer wording); a bare
# "polymeric" is NOT enough -- it also matches hydrogen-bonded molecular adducts
POLYMERIC_RE = re.compile(
    r"catena|framework|coordination polymer|metal.organic|porous|zeolitic|"
    r"\bMOF\b|\bpoly\[", re.I)

VENDOR_PATTERNS = [        # first match wins; checked against device+source text
    ("synchrotron", re.compile(r"synchrotron|beamline|\bAPS\b|\bESRF\b|\bALS\b|"
                               r"Diamond Light|SPring-?8|PETRA|photon factory|"
                               r"\bSLS\b|BESSY|SOLEIL|ANKA|MAX-?lab", re.I)),
    ("Bruker", re.compile(r"bruker|siemens|\bsmart\b|apex|\bd8\b|proteum|"
                          r"platform diffractometer|\bP4\b|venture", re.I)),
    ("Rigaku", re.compile(r"rigaku|xtalab|saturn|r-axis|rapid|mercury|"
                          r"\bafc[- ]?\d|sculptor|synergy", re.I)),
    ("Oxford-Agilent", re.compile(r"oxford diffraction|agilent|xcalibur|supernova|"
                                  r"gemini|\bkuma\b|km-?4|excalibur", re.I)),
    ("Stoe", re.compile(r"stoe|ipds|stadi", re.I)),
    ("Nonius", re.compile(r"nonius|kappa\s?ccd|cad-?4|enraf|fast\s?tv|mach3", re.I)),
]

# vendor families we try to represent with at least MIN_PER_FAMILY cases each
TARGET_FAMILIES = ["Bruker", "Rigaku", "Oxford-Agilent", "Stoe", "Nonius"]
MIN_PER_FAMILY = 2
MAX_VENDOR_PROBES = 150   # CIF-only probes allowed during vendor top-up

_last_request = {}


def throttled_get(url: str, tries: int = 4, timeout: int = 60) -> requests.Response | None:
    """GET with per-host >=0.34 s spacing and exponential-backoff retries."""
    host = url.split("/")[2]
    for attempt in range(tries):
        wait = 0.34 - (time.time() - _last_request.get(host, 0))
        if wait > 0:
            time.sleep(wait)
        _last_request[host] = time.time()
        try:
            r = requests.get(url, timeout=timeout,
                             headers={"User-Agent": "CrystalPilot-benchmark-fetch/1.0"})
            if r.status_code == 404:
                return None
            if r.ok:
                return r
        except requests.RequestException:
            pass
        time.sleep(2 ** attempt)
    return None


# --------------------------------------------------------------------------- CIF-lite
_CIF_TOKEN = re.compile(
    r"""(?xm)
    ^;((?:.*\n)*?)^;[^\n]*\n          # semicolon text field (multi-line)
    | '([^']*)'                       # single-quoted
    | "([^\"]*)"                      # double-quoted
    | ([^\s]+)                        # bare token
    """)


def cif_tokenize(text: str) -> list[str]:
    tokens = []
    for m in _CIF_TOKEN.finditer(text):
        if m.group(1) is not None:
            tokens.append(m.group(1))
        elif m.group(2) is not None:
            tokens.append(m.group(2))
        elif m.group(3) is not None:
            tokens.append(m.group(3))
        else:
            tok = m.group(4)
            if tok.startswith("#"):
                continue
            tokens.append(tok)
    return tokens


def strip_comments(text: str) -> str:
    out = []
    for line in text.splitlines():
        if line.startswith(";"):
            out.append(line)          # never touch semicolon-field lines
            continue
        # cheap comment strip: '#' outside quotes
        pos, inq = 0, None
        for i, ch in enumerate(line):
            if inq:
                if ch == inq:
                    inq = None
            elif ch in "'\"":
                inq = ch
            elif ch == "#":
                pos = i
                break
        else:
            pos = len(line)
        out.append(line[:pos])
    return "\n".join(out) + "\n"


def parse_cif_blocks(text: str) -> dict[str, dict]:
    """Very small CIF parser: {block_name: {'items': {tag: value}, 'loops': [(tags, rows)]}}.

    Handles COD's machine-written CIF 1.1 files (quoted strings, semicolon fields,
    loops).  Not a general CIF parser.
    """
    tokens = cif_tokenize(strip_comments(text))
    blocks: dict[str, dict] = {}
    cur = None
    i = 0
    n = len(tokens)
    while i < n:
        tok = tokens[i]
        low = tok.lower()
        if low.startswith("data_"):
            cur = {"items": {}, "loops": []}
            blocks[tok[5:]] = cur
            i += 1
        elif low == "loop_":
            i += 1
            tags = []
            while i < n and tokens[i].startswith("_"):
                tags.append(tokens[i].lower())
                i += 1
            values = []
            while i < n and not tokens[i].startswith("_") \
                    and tokens[i].lower() not in ("loop_",) \
                    and not tokens[i].lower().startswith("data_"):
                values.append(tokens[i])
                i += 1
            if cur is not None and tags:
                nrow = len(values) // len(tags)
                rows = [values[r * len(tags):(r + 1) * len(tags)] for r in range(nrow)]
                cur["loops"].append((tags, rows))
        elif tok.startswith("_"):
            if i + 1 < n and not tokens[i + 1].startswith("_") \
                    and tokens[i + 1].lower() not in ("loop_",) \
                    and not tokens[i + 1].lower().startswith("data_"):
                if cur is not None:
                    cur["items"][tok.lower()] = tokens[i + 1]
                i += 2
            else:
                if cur is not None:
                    cur["items"][tok.lower()] = ""
                i += 1
        else:
            i += 1
    return blocks


def cif_get(block: dict, *tags) -> str | None:
    for tag in tags:
        v = block["items"].get(tag.lower())
        if v is not None and str(v).strip() not in ("", "?", "."):
            return str(v).strip()
    return None


def cif_float(block: dict, *tags) -> float | None:
    v = cif_get(block, *tags)
    if v is None:
        return None
    v = re.sub(r"\(.*?\)", "", v)
    try:
        return float(v)
    except ValueError:
        return None


def find_loop(block: dict, *needed_tags):
    """First loop containing every tag in needed_tags (case-insensitive)."""
    needed = [t.lower() for t in needed_tags]
    for tags, rows in block["loops"]:
        if all(t in tags for t in needed):
            return tags, rows
    return None


# ------------------------------------------------------------------- reflection data
RAW_HKL_RE = re.compile(r"^[\s\-\d]{12}[\s\-\d.]{8}[\s\-\d.]{8}")


def parse_raw_hklf(text: str):
    """Parse raw SHELX fixed-format lines -> list of (h,k,l,F2,sig). None on failure."""
    refl = []
    for line in text.splitlines():
        if not line.strip():
            continue
        if len(line) < 28 or not RAW_HKL_RE.match(line):
            return None
        try:
            h, k, l = int(line[0:4]), int(line[4:8]), int(line[8:12])
            f2, sig = float(line[12:20]), float(line[20:28])
        except ValueError:
            return None
        if h == 0 and k == 0 and l == 0:
            break
        extra = line[28:32].strip()
        if extra and extra not in ("1",):
            return "multibatch"       # HKLF5-style / multi-batch: refuse
        refl.append((h, k, l, f2, sig))
    return refl or None


def extract_reflections(hkl_text: str):
    """COD hkl deposit -> (reflections, data_kind, notes) or (None, None, reason).

    Accepts: CIF _refln loops with F^2 (or intensity) + sigma; embedded
    _shelx_hkl_file semicolon fields; raw fixed-format SHELX files.
    Refuses F-only (LIST 3) deposits -- no silent F->F^2 conversion.
    """
    notes = []
    stripped = "\n".join(l for l in hkl_text.splitlines() if not l.startswith("#"))
    if "data_" not in stripped[:4000]:
        refl = parse_raw_hklf(stripped)
        if refl == "multibatch":
            return None, None, "raw multi-batch/HKLF5 file"
        if refl:
            return refl, "F2_raw", ["raw fixed-format deposit"]
        return None, None, "unrecognised non-CIF hkl format"

    blocks = parse_cif_blocks(hkl_text)
    cand = [(name, b) for name, b in blocks.items()
            if find_loop(b, "_refln_index_h") or b["items"].get("_shelx_hkl_file")]
    if not cand:
        return None, None, "no _refln loop in hkl deposit"
    if len(cand) > 1:
        notes.append(f"multi-block hkl deposit ({len(cand)} blocks); used first")
    name, b = cand[0]

    embedded = b["items"].get("_shelx_hkl_file")
    if embedded and not find_loop(b, "_refln_index_h"):
        refl = parse_raw_hklf(embedded)
        if refl == "multibatch":
            return None, None, "embedded multi-batch/HKLF5 data"
        if refl:
            return refl, "F2_embedded", notes + ["embedded _shelx_hkl_file"]
        return None, None, "unparsable embedded _shelx_hkl_file"

    for meas, sig, kind in (
            ("_refln_f_squared_meas", "_refln_f_squared_sigma", "F2"),
            ("_refln_intensity_meas", "_refln_intensity_sigma", "intensity")):
        got = find_loop(b, "_refln_index_h", "_refln_index_k", "_refln_index_l",
                        meas, sig)
        if got:
            tags, rows = got
            ih, ik, il = (tags.index("_refln_index_h"), tags.index("_refln_index_k"),
                          tags.index("_refln_index_l"))
            im, is_ = tags.index(meas), tags.index(sig)
            refl = []
            for r in rows:
                try:
                    h, k, l = int(r[ih]), int(r[ik]), int(r[il])
                    f2 = float(re.sub(r"\(.*?\)", "", r[im]))
                    s = float(re.sub(r"\(.*?\)", "", r[is_]))
                except (ValueError, IndexError):
                    return None, None, "non-numeric refln row"
                if h == 0 and k == 0 and l == 0:
                    continue
                refl.append((h, k, l, f2, s))
            if kind == "intensity":
                notes.append("deposited as _refln_intensity (treated as F^2-scale I)")
            return refl, kind, notes
    if find_loop(b, "_refln_index_h", "_refln_f_meas"):
        return None, None, "F-only (LIST 3) deposit; skipped to avoid F->F2 conversion"
    return None, None, "refln loop lacks F2/intensity + sigma"


def write_hklf(refl, path: Path) -> float:
    """Write fixed-format HKLF4 (3I4,2F8.2).  Returns applied linear scale (1.0 if none)."""
    max_pos = max((max(f2, s) for _, _, _, f2, s in refl), default=0.0)
    min_neg = min((f2 for _, _, _, f2, _ in refl), default=0.0)
    scale = 1.0
    if max_pos > 99999.99:
        scale = 99999.0 / max_pos
    if min_neg < 0 and abs(min_neg) * scale > 9999.99:
        scale = min(scale, 9999.0 / abs(min_neg))
    lines = []
    for h, k, l, f2, s in refl:
        if not (-999 <= h <= 9999 and -999 <= k <= 9999 and -999 <= l <= 9999):
            raise ValueError("index out of 4-column range")
        lines.append(f"{h:4d}{k:4d}{l:4d}{f2 * scale:8.2f}{s * scale:8.2f}")
    lines.append(f"{0:4d}{0:4d}{0:4d}{0.0:8.2f}{0.0:8.2f}")
    path.write_text("\n".join(lines) + "\n", encoding="ascii")
    # strict self-check: file must re-parse by column slicing
    for line in path.read_text(encoding="ascii").splitlines():
        int(line[0:4]); int(line[4:8]); int(line[8:12])
        float(line[12:20]); float(line[20:28])
    return scale


# --------------------------------------------------------------------- reference CIF
def pick_structure_block(blocks: dict, cod_id: str):
    if cod_id in blocks and find_loop(blocks[cod_id], "_atom_site_fract_x"):
        return cod_id, blocks[cod_id]
    for name, b in blocks.items():
        if find_loop(b, "_atom_site_fract_x"):
            return name, b
    return None, None


def vendor_family(device: str | None, source: str | None, radiation_source: str | None):
    text = " ".join(x for x in (device, source, radiation_source) if x)
    if not text:
        return None
    for fam, pat in VENDOR_PATTERNS:
        if pat.search(text):
            return fam
    return "other"


def validate_ref_cif(cif_text: str, cod_id: str):
    """Reference-CIF checks -> (record_fields, reject_reason)."""
    blocks = parse_cif_blocks(cif_text)
    name, b = pick_structure_block(blocks, cod_id)
    if b is None:
        return None, "no atom_site loop in reference CIF"
    cell = [cif_float(b, t) for t in (
        "_cell_length_a", "_cell_length_b", "_cell_length_c",
        "_cell_angle_alpha", "_cell_angle_beta", "_cell_angle_gamma")]
    if any(v is None for v in cell):
        return None, "incomplete _cell parameters"
    sg = cif_get(b, "_space_group_name_h-m_alt", "_symmetry_space_group_name_h-m")
    sg_number = cif_float(b, "_space_group_it_number", "_symmetry_int_tables_number")
    if sg is None and sg_number is None:
        return None, "no space-group information"
    loop = find_loop(b, "_atom_site_label", "_atom_site_fract_x",
                     "_atom_site_fract_y", "_atom_site_fract_z")
    if loop is None:
        return None, "atom_site loop lacks coordinates"
    tags, rows = loop
    if len(rows) < 3:
        return None, f"only {len(rows)} atoms in atom_site loop"
    r1 = cif_float(b, "_refine_ls_r_factor_gt", "_refine_ls_r_factor_obs")
    r1_all = cif_float(b, "_refine_ls_r_factor_all")
    if r1 is None and r1_all is None:
        return None, "no _refine_ls_R_factor_gt/_all"
    device = cif_get(b, "_diffrn_measurement_device_type", "_diffrn_measurement_device")
    diffrn_source = cif_get(b, "_diffrn_source", "_diffrn_radiation_source")
    fields = {
        "cell": [round(v, 4) for v in cell],
        "volume_A3": cif_float(b, "_cell_volume"),
        "sg_ref": sg,
        "sg_number": int(sg_number) if sg_number else None,
        "formula": cif_get(b, "_chemical_formula_sum"),
        "z": cif_float(b, "_cell_formula_units_z"),
        "human_R1": r1 if r1 is not None else r1_all,
        "r1_is_all": r1 is None,
        "radiation": cif_get(b, "_diffrn_radiation_type", "_diffrn_radiation_probe"),
        "wavelength": cif_float(b, "_diffrn_radiation_wavelength"),
        "temperature_K": cif_float(b, "_cell_measurement_temperature",
                                   "_diffrn_ambient_temperature"),
        "device": device,
        "vendor_family": vendor_family(device, diffrn_source,
                                       cif_get(b, "_diffrn_radiation_source")),
        "n_atoms": len(rows),
        "doi": cif_get(b, "_journal_paper_doi"),
    }
    # feature detection for tags
    raw = cif_text
    fields["is_twin"] = bool(
        re.search(r"^_twin", raw, re.M)
        or re.search(r"^\s*(TWIN|BASF)\b", raw, re.M | re.I))
    occ = None
    ol = find_loop(b, "_atom_site_occupancy")
    has_partial_occ = False
    if ol:
        otags, orows = ol
        if "_atom_site_occupancy" in otags:
            oi = otags.index("_atom_site_occupancy")
            for r in orows:
                try:
                    v = float(re.sub(r"\(.*?\)", "", r[oi]))
                    if v < 0.99:
                        has_partial_occ = True
                        break
                except (ValueError, IndexError):
                    pass
    fields["has_disorder"] = has_partial_occ or bool(
        re.search(r"_atom_site_disorder_group", raw))
    fields["has_squeeze"] = "_platon_squeeze" in raw or bool(
        re.search(r"\bSQUEEZE\b", raw))
    return fields, None


# ------------------------------------------------------------------- candidate lists
def load_cod_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", errors="replace") as f:
        lines = [l for l in f if not l.startswith("#")]
    return list(csv.DictReader(lines))


def fetch_candidate_lists(refresh: bool = False) -> dict[str, list[dict]]:
    CACHE.mkdir(parents=True, exist_ok=True)
    lists = {}
    queries = {"all": f"{COD}/result.php?has_fobs=1&format=csv",
               "twin": f"{COD}/result.php?text1=twin&has_fobs=1&format=csv"}
    for key, url in queries.items():
        path = CACHE / f"cod_{key}.csv"
        if refresh or not path.exists():
            print(f"[lists] downloading {key} candidate list ...")
            r = throttled_get(url, timeout=300)
            if r is None:
                raise RuntimeError(f"cannot download candidate list {url}")
            path.write_bytes(r.content)
        lists[key] = load_cod_csv(path)
    return lists


def formula_elements(formula: str) -> set[str]:
    return set(re.findall(r"([A-Z][a-z]?)[0-9. ]",
                          " " + (formula or "").replace("-", " ") + " "))


def row_float(row: dict, key: str) -> float | None:
    try:
        return float(row.get(key) or "")
    except ValueError:
        return None


def names_text(row: dict) -> str:
    return " ".join(filter(None, [row.get("commonname"), row.get("chemname"),
                                  row.get("title"), row.get("mineral")]))


def build_queues(lists: dict[str, list[dict]]) -> dict[str, list[dict]]:
    """Category -> ordered candidate rows (deterministic, seeded)."""
    rng = random.Random(SEED)
    rows = [r for r in lists["all"]
            if r.get("file") and r["file"] not in EXCLUDE_COD_IDS
            and row_float(r, "Robs") is not None]
    by_id = {r["file"]: r for r in rows}

    def base(r):
        e = formula_elements(r.get("formula") or "")
        v = row_float(r, "vol") or 0
        return e, v

    queues: dict[str, list[dict]] = {k: [] for k in QUOTAS}

    # hard-twin from the dedicated full-text list (verified against CIF later)
    twin_ids = [r["file"] for r in lists["twin"]
                if r.get("file") in by_id]
    rng.shuffle(twin_ids)
    queues["hard-twin"] = [by_id[i] for i in twin_ids]

    mof_by_metal: dict[str, list[dict]] = {}
    org_buckets: dict[str, list[dict]] = {"hydrate": [], "salt": [], "small": [],
                                          "other": []}
    for r in rows:
        e, v = base(r)
        sgn = r.get("sgNumber") or ""
        name = names_text(r)
        zp = row_float(r, "Zprime") or 0
        if sgn == "1":
            queues["hard-P1"].append(r)
        if v > 10000:
            queues["hard-large"].append(r)
        if zp >= 2:
            queues["hard-pseudo"].append(r)
        if "has disorder" in (r.get("flags") or ""):
            queues["hard-disorder"].append(r)
        if (e & MOF_METALS) and "C" in e and ("O" in e or "N" in e) and "H" in e \
                and POLYMERIC_RE.search(name):
            for metal in ("Zn", "Cu", "Zr", "Co", "Cd", "Fe", "Mn"):
                if metal in e:
                    mof_by_metal.setdefault(metal, []).append(r)
                    break
            else:
                key = "Ln" if e & LANTHANIDES else "otherM"
                mof_by_metal.setdefault(key, []).append(r)
        if e and e <= ORGANIC_ELEMENTS and "C" in e and "H" in e:
            low = name.lower()
            if "hydrate" in low:
                org_buckets["hydrate"].append(r)
            elif "ium" in low and ("ate" in low or "ide" in low or "chloride" in low):
                org_buckets["salt"].append(r)
            elif v and v < 900:
                org_buckets["small"].append(r)
            else:
                org_buckets["other"].append(r)
        if e and "C" not in e and (e & HEAVY or len(e) >= 2):
            queues["inorganic"].append(r)

    for q in ("hard-P1", "hard-large", "hard-pseudo", "hard-disorder", "inorganic"):
        rng.shuffle(queues[q])
    # prefer heavy-element inorganics first
    queues["inorganic"].sort(key=lambda r: 0 if formula_elements(r.get("formula") or "") & HEAVY else 1)

    def round_robin(buckets: dict[str, list[dict]], prefer=None) -> list[dict]:
        for v in buckets.values():
            rng.shuffle(v)
            if prefer is not None:
                v.sort(key=prefer)      # stable: preferred entries sort last -> popped first
        out, idx = [], 0
        keys = sorted(buckets)
        while any(buckets.values()):
            k = keys[idx % len(keys)]
            if buckets[k]:
                out.append(buckets[k].pop())
            idx += 1
        return out

    # porous frameworks preferred: bias MOF picks toward cells >= 1200 A^3
    queues["mof"] = round_robin(
        mof_by_metal, prefer=lambda r: 1 if (row_float(r, "vol") or 0) >= 1200 else 0)
    queues["organic"] = round_robin(org_buckets)
    return queues


# ------------------------------------------------------------------------ processing
def load_state() -> dict:
    p = CACHE / "state.json"
    if p.exists():
        state = json.loads(p.read_text(encoding="utf-8"))
        state.setdefault("probed", {})
        return state
    return {"accepted": {}, "rejected": {}, "probed": {}}


def save_state(state: dict) -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    (CACHE / "state.json").write_text(json.dumps(state, indent=1),
                                      encoding="utf-8")


def process_case(row: dict, category: str, state: dict,
                 require_family=None) -> tuple[bool, str]:
    """Download+validate one candidate.  Returns (accepted, reason_or_id).

    With ``require_family`` (a set of vendor families), the reference CIF is
    fetched and validated first and the case is skipped -- recorded under
    state['probed'], not permanently rejected -- when the measurement device
    belongs to a different family.  Used by the vendor top-up stage.
    """
    cod_id = row["file"]
    case_id = f"cod_{cod_id}"
    if cod_id in state["accepted"]:
        return False, "already accepted"
    if cod_id in state["rejected"]:
        return False, "already rejected"

    url_cif = f"{COD}/{cod_id}.cif"
    url_hkl = f"{COD}/{cod_id}.hkl"
    r_cif = throttled_get(url_cif)
    if r_cif is None:
        state["rejected"][cod_id] = "CIF download failed/404"
        return False, state["rejected"][cod_id]
    cif_text = r_cif.content.decode("utf-8", errors="replace")

    fields, err = validate_ref_cif(cif_text, cod_id)
    if err:
        state["rejected"][cod_id] = err
        return False, err
    if require_family is not None and fields["vendor_family"] not in require_family:
        state.setdefault("probed", {})[cod_id] = fields["vendor_family"]
        return False, f"probe: family={fields['vendor_family']}"

    r_hkl = throttled_get(url_hkl)
    if r_hkl is None:
        state["rejected"][cod_id] = "hkl download failed/404"
        return False, state["rejected"][cod_id]
    hkl_text = r_hkl.content.decode("utf-8", errors="replace")
    refl, kind, notes = extract_reflections(hkl_text)
    if refl is None:
        state["rejected"][cod_id] = notes if isinstance(notes, str) else "hkl parse failure"
        return False, state["rejected"][cod_id]
    if len(refl) < 500:
        state["rejected"][cod_id] = f"only {len(refl)} reflections"
        return False, state["rejected"][cod_id]
    sigmas = [s for _, _, _, _, s in refl]
    if all(s == 0 for s in sigmas):
        state["rejected"][cod_id] = "all sigmas zero"
        return False, state["rejected"][cod_id]

    # category-specific verification
    tags = []
    if category == "hard-twin" and not fields["is_twin"]:
        state["rejected"][cod_id] = "twin not confirmed in CIF (no TWIN/BASF/_twin)"
        return False, state["rejected"][cod_id]
    if category == "hard-disorder" and not (fields["has_disorder"] or fields["has_squeeze"]):
        state["rejected"][cod_id] = "disorder flag not confirmed in CIF"
        return False, state["rejected"][cod_id]

    vol = fields.get("volume_A3") or 0
    ratio = (len(refl) / vol) if vol else None
    notes = list(notes)
    if ratio is not None and not (0.02 <= ratio <= 60):
        notes.append(f"UNUSUAL reflection-count/volume ratio {ratio:.3f}")

    case_dir = DATA / case_id
    case_dir.mkdir(parents=True, exist_ok=True)
    scale = write_hklf(refl, case_dir / f"{case_id}.hkl")
    if scale != 1.0:
        notes.append(f"F2+sigma uniformly scaled by {scale:.6g} to fit F8.2 columns")
    if kind == "intensity":
        pass  # note already added by extract_reflections
    (case_dir / f"{case_id}_ref.cif").write_text(cif_text, encoding="utf-8")

    if fields["is_twin"]:
        tags.append("twin")
    if fields["has_squeeze"]:
        tags.append("squeeze")
    if fields["has_disorder"]:
        tags.append("disorder")
    if fields["sg_number"] in (1, 2):
        tags.append("triclinic")
    zp = row_float(row, "Zprime") or 0
    if zp >= 2:
        tags.append("zprime>1")
    if vol > 10000:
        tags.append("large-cell")
    if fields["r1_is_all"]:
        notes.append("human_R1 is _refine_ls_R_factor_all (R_gt absent)")

    record = {
        "id": case_id,
        "source": "COD",
        "cod_id": cod_id,
        "doi": fields["doi"] or (row.get("doi") or None),
        "url_hkl": url_hkl,
        "url_cif": url_cif,
        "license": LICENSE,
        "device": fields["device"],
        "vendor_family": fields["vendor_family"],
        "radiation": fields["radiation"],
        "wavelength": fields["wavelength"],
        "temperature_K": fields["temperature_K"],
        "formula": fields["formula"],
        "sg_ref": fields["sg_ref"],
        "sg_number": fields["sg_number"],
        "z": fields["z"],
        "cell": fields["cell"],
        "volume_A3": fields["volume_A3"],
        "n_reflections_hkl": len(refl),
        "human_R1": fields["human_R1"],
        "category": category,
        "tags": sorted(set(tags)),
        "notes": "; ".join(notes) if notes else None,
    }
    state["accepted"][cod_id] = record
    return True, case_id


def write_outputs(state: dict) -> None:
    order = list(QUOTAS)
    records = sorted(state["accepted"].values(),
                     key=lambda r: (order.index(r["category"])
                                    if r["category"] in order else 99, r["id"]))
    MANIFEST.write_text(json.dumps(records, indent=1), encoding="utf-8")
    gi = DATA / ".gitignore"
    if not gi.exists():
        gi.write_text("*\n!.gitignore\n!README.md\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--refresh-lists", action="store_true")
    ap.add_argument("--retry-rejected", action="store_true")
    ap.add_argument("--max-new", type=int, default=10**9,
                    help="stop after this many newly accepted cases (debug)")
    args = ap.parse_args()

    DATA.mkdir(parents=True, exist_ok=True)
    lists = fetch_candidate_lists(refresh=args.refresh_lists)
    queues = build_queues(lists)
    state = load_state()
    if args.retry_rejected:
        state["rejected"] = {}

    # never let one COD id satisfy two categories
    claimed = set(state["accepted"])
    new_accepted = 0
    for category, quota in QUOTAS.items():
        have = sum(1 for rec in state["accepted"].values()
                   if rec["category"] == category)
        qi = 0
        queue = queues.get(category, [])
        while have < quota and qi < len(queue) and new_accepted < args.max_new:
            row = queue[qi]
            qi += 1
            if row["file"] in claimed or row["file"] in state["rejected"]:
                continue
            ok, info = process_case(row, category, state)
            if ok:
                claimed.add(row["file"])
                have += 1
                new_accepted += 1
                rec = state["accepted"][row["file"]]
                print(f"[{category:13s}] + {info}  {rec['sg_ref']}  "
                      f"V={rec['volume_A3']}  n={rec['n_reflections_hkl']}  "
                      f"R1={rec['human_R1']}  {rec['vendor_family']}")
            else:
                print(f"[{category:13s}] - cod_{row['file']}: {info}")
            save_state(state)
        if have < quota:
            print(f"[{category}] WARNING: quota {quota} not met (have {have})")

    # ---- vendor top-up: probe candidate CIFs (device metadata lives only in the
    # CIF, not in COD's search index) until each target family has enough cases.
    def family_counts():
        fams: dict = {}
        for rec in state["accepted"].values():
            fams[rec["vendor_family"]] = fams.get(rec["vendor_family"], 0) + 1
        return fams

    fams = family_counts()
    print("vendor families before top-up:", fams)
    missing = {f for f in TARGET_FAMILIES if fams.get(f, 0) < MIN_PER_FAMILY}
    if missing and args.max_new >= 10**9:   # skip top-up in --max-new debug runs
        by_id = {r["file"]: r for r in lists["all"] if r.get("file")}
        # candidates already probed in earlier runs whose family is now wanted
        pool: list[dict] = [by_id[cid] for cid, fam in state.get("probed", {}).items()
                            if fam in missing and cid in by_id and cid not in claimed]
        # then untouched candidates from the organic/mof/inorganic queues
        for cat_name in ("organic", "mof", "inorganic"):
            pool.extend(r for r in queues.get(cat_name, [])
                        if r["file"] not in claimed
                        and r["file"] not in state["rejected"]
                        and r["file"] not in state.get("probed", {}))
        probes = 0
        for row in pool:
            if not missing or probes >= MAX_VENDOR_PROBES:
                break
            e = formula_elements(row.get("formula") or "")
            cat = ("organic" if e <= ORGANIC_ELEMENTS and "C" in e and "H" in e
                   else "mof" if (e & MOF_METALS) and "C" in e
                   and POLYMERIC_RE.search(names_text(row))
                   else "inorganic" if "C" not in e else "organic")
            probes += 1
            ok, info = process_case(row, cat, state, require_family=missing)
            if ok:
                claimed.add(row["file"])
                rec = state["accepted"][row["file"]]
                fams = family_counts()
                missing = {f for f in TARGET_FAMILIES
                           if fams.get(f, 0) < MIN_PER_FAMILY}
                print(f"[topup] + {info} ({cat}) {rec['vendor_family']}: {rec['device']}")
            save_state(state)
        if missing:
            print(f"[topup] families still under-represented: {sorted(missing)}")

    write_outputs(state)
    n = len(state["accepted"])
    cats = {}
    for rec in state["accepted"].values():
        cats[rec["category"]] = cats.get(rec["category"], 0) + 1
    print(f"\nTOTAL accepted: {n}")
    print("by category:", json.dumps(cats, indent=1))
    fams = {}
    for rec in state["accepted"].values():
        fams[rec["vendor_family"]] = fams.get(rec["vendor_family"], 0) + 1
    print("by vendor:", json.dumps(fams, indent=1))
    print(f"rejected: {len(state['rejected'])}")
    print(f"manifest: {MANIFEST}")


if __name__ == "__main__":
    sys.exit(main())
