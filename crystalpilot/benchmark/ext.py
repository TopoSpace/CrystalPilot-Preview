"""Extended-benchmark adapter: manifest_ext.json (COD/IUCr hkl+CIF pairs) ->
runner-compatible cases.

Each fetched case is a measured SHELX .hkl plus the human-refined reference
CIF. The solver additionally needs what any experimentalist knows before
solving: unit cell, wavelength, Z and elemental composition. We generate a
minimal gen.ins carrying exactly that - never coordinates, never symmetry
operators from the reference (space-group determination is scored separately).

Usage:
  python -m crystalpilot.benchmark.ext build            # generate gen.ins + runner manifest
  python -m crystalpilot.benchmark.ext run [only=...] [mode=standard|auto]
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST_EXT = ROOT / "benchmark" / "manifest_ext.json"
RUNNER_MANIFEST = ROOT / "benchmark" / "data_ext" / "runner_manifest.json"

ELEMENTS = set(
    "H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni "
    "Cu Zn Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I "
    "Xe Cs Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt "
    "Au Hg Tl Pb Bi Po At Rn Fr Ra Ac Th Pa U Np Pu D".split())

RADIATION_WL = {"mo": 0.71073, "cu": 1.54184, "ag": 0.56087, "ga": 1.34139,
                "in": 0.51364, "fe": 1.93736, "cr": 2.28970}

_FORMULA_TOKEN = re.compile(r"([A-Z][a-z]?)\s*(\d+(?:\.\d+)?)?")


def parse_formula(s: str | None) -> dict[str, float] | None:
    """'C12 H8 Cu N2 O6' -> {'C':12,...}; None if it doesn't look like one."""
    if not s:
        return None
    s = s.strip().strip("'\"").replace(",", " ")
    counts: dict[str, float] = {}
    pos = 0
    for m in _FORMULA_TOKEN.finditer(s):
        if s[pos:m.start()].strip(" ()0123456789."):
            return None                      # garbage between tokens
        el, n = m.group(1), m.group(2)
        if el == "D":
            el = "H"
        if el not in ELEMENTS:
            return None
        counts[el] = counts.get(el, 0.0) + float(n or 1)
        pos = m.end()
    return counts or None


def _cif_first(block, *tags) -> str | None:
    for t in tags:
        v = block.find_value(t)
        if v and v not in ("?", "."):
            return v.strip().strip("'\"")
    return None


def cif_meta(cif_path: Path) -> dict:
    """Cell / wavelength / Z / formula from the reference CIF (gemmi parser)."""
    import gemmi
    doc = gemmi.cif.read(str(cif_path))
    block = None
    for b in doc:
        if b.find_value("_cell_length_a"):
            block = b
            break
    if block is None:
        raise ValueError("no cell in reference CIF")

    def num(tag):
        v = block.find_value(tag)
        if not v or v in ("?", "."):
            return None
        return float(re.sub(r"\(.*\)", "", v))

    cell = [num(t) for t in ("_cell_length_a", "_cell_length_b", "_cell_length_c",
                             "_cell_angle_alpha", "_cell_angle_beta",
                             "_cell_angle_gamma")]
    if any(v is None for v in cell):
        raise ValueError("incomplete cell in reference CIF")
    wl = num("_diffrn_radiation_wavelength")
    wl_assumed = False
    if wl is None:
        rad = (_cif_first(block, "_diffrn_radiation_type",
                          "_diffrn_radiation_probe") or "").lower()
        for key, val in RADIATION_WL.items():
            if key in rad:
                wl = val
                break
        if wl is None:
            wl, wl_assumed = 0.71073, True   # Mo Ka default; recorded honestly
    z = num("_cell_formula_units_Z")
    formula = parse_formula(_cif_first(block, "_chemical_formula_sum"))
    return {"cell": cell, "wavelength": wl, "wavelength_assumed": wl_assumed,
            "z": z, "formula": formula}


def sniff_hkl(hkl_path: Path) -> str:
    """'shelx' fixed-format vs 'sf_cif' structure-factor CIF."""
    head = hkl_path.read_text(encoding="utf-8", errors="replace")[:4000]
    if "_refln" in head or head.lstrip().startswith("data_"):
        return "sf_cif"
    return "shelx"


def gen_ins(name: str, meta: dict, dest: Path) -> Path:
    z = meta["z"] or 1
    formula = meta["formula"]
    elements = sorted(formula, key=lambda e: (e != "C", e != "H", e))
    sfac = " ".join(elements)
    unit = " ".join(f"{formula[el] * z:g}" for el in elements)
    a, b, c, al, be, ga = meta["cell"]
    text = (f"TITL {name} (generated: cell+wavelength+composition only)\n"
            f"CELL {meta['wavelength']:.5f} {a:.4f} {b:.4f} {c:.4f} "
            f"{al:.3f} {be:.3f} {ga:.3f}\n"
            f"ZERR {z:g} 0 0 0 0 0 0\n"
            f"SFAC {sfac}\n"
            f"UNIT {unit}\n"
            f"HKLF 4\n"
            f"END\n")
    dest.write_text(text, encoding="utf-8")
    return dest


def build(manifest_path: Path = MANIFEST_EXT) -> dict:
    entries = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    out, skipped = [], []
    for e in entries:
        name = e["id"]
        try:
            files = e.get("files") or {}
            hkl = ROOT / files.get("hkl", f"benchmark/data_ext/{name}/{name}.hkl")
            ref = ROOT / files.get("cif_ref",
                                   f"benchmark/data_ext/{name}/{name}_ref.cif")
            if not hkl.exists() or not ref.exists():
                skipped.append({"id": name, "reason": "files missing"})
                continue
            kind = sniff_hkl(hkl)
            row = {"name": name, "ref_cif": str(ref.relative_to(ROOT)),
                   "category": e.get("category"), "tags": e.get("tags"),
                   "human_r1_manifest": e.get("human_R1"),
                   "sg_ref_manifest": e.get("sg_ref"),
                   "vendor_family": e.get("vendor_family")}
            if kind == "sf_cif":
                row["sf_cif"] = str(hkl.relative_to(ROOT))
            else:
                meta = cif_meta(ref)
                if meta["formula"] is None:
                    skipped.append({"id": name, "reason": "no parseable formula"})
                    continue
                if meta["z"] is None:
                    skipped.append({"id": name, "reason": "no Z in reference"})
                    continue
                ins = gen_ins(name, meta, hkl.parent / "gen.ins")
                row["hkl"] = str(hkl.relative_to(ROOT))
                row["ins"] = str(ins.relative_to(ROOT))
                if meta["wavelength_assumed"]:
                    row["wavelength_assumed"] = True
            out.append(row)
        except Exception as exc:  # noqa: BLE001 - collect, don't die
            skipped.append({"id": name, "reason": f"{type(exc).__name__}: {exc}"})
    RUNNER_MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    RUNNER_MANIFEST.write_text(json.dumps(out, indent=1), encoding="utf-8")
    report = {"built": len(out), "skipped": skipped,
              "runner_manifest": str(RUNNER_MANIFEST)}
    print(json.dumps(report, indent=1, ensure_ascii=False))
    return report


def main(argv: list[str]) -> None:
    cmd = argv[0] if argv else "build"
    kwargs = dict(a.split("=", 1) for a in argv[1:] if "=" in a)
    if cmd == "build":
        build()
    elif cmd == "run":
        build()
        from .runner import main as runner_main
        runner_main(manifest_path=str(RUNNER_MANIFEST),
                    out_dir=kwargs.get("out_dir", "benchmark/results_ext"),
                    symmetry_mode=kwargs.get("symmetry_mode", "auto"),
                    mode=kwargs.get("mode", "standard"),
                    only=kwargs.get("only"))
    else:
        raise SystemExit(f"unknown command {cmd!r} (use build|run)")


if __name__ == "__main__":
    import sys
    main(sys.argv[1:])
