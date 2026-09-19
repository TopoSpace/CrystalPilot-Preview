"""Scan a local data tree (READ-ONLY) and build a benchmark dataset manifest.

A usable case = reflection data (.hkl, HKLF-like) + metadata (.ins/.res with CELL)
+ a reference refined structure (.res with atoms, or a final .cif). Files are copied
into the benchmark data dir; originals are never touched.
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

_HKL_LINE = re.compile(r"^\s*-?\d+\s+-?\d+\s+-?\d+\s+-?[\d.]+\s+[\d.]+")


def _looks_like_hklf(path: Path, min_lines: int = 200) -> bool:
    try:
        with path.open(encoding="ascii", errors="strict") as fh:
            n = 0
            for i, line in enumerate(fh):
                if i > 400:
                    break
                if _HKL_LINE.match(line):
                    n += 1
            return n >= min(min_lines, 150)
    except (UnicodeDecodeError, OSError):
        return False


def _res_has_atoms(path: Path) -> bool:
    """A refined .res contains atom lines: NAME sfac# x y z occ [U…]."""
    atom_re = re.compile(r"^[A-Za-z]{1,2}\d+[A-Za-z']*\s+\d+\s+[-\d.]+\s+[-\d.]+\s+[-\d.]+")
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return sum(1 for ln in text.splitlines() if atom_re.match(ln)) >= 5


def _cell_of(ins_path: Path) -> tuple | None:
    try:
        for line in ins_path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.upper().startswith("CELL"):
                p = line.split()
                return tuple(round(float(x), 3) for x in p[2:8])
    except (OSError, ValueError, IndexError):
        pass
    return None


def scan_tree(root: Path) -> list[dict]:
    """Find candidate cases: hkl + same-stem ins (+ optional same-stem res / dir cif)."""
    cases = []
    seen_keys: set[tuple] = set()
    for hkl in sorted(root.rglob("*.hkl")):
        stem, d = hkl.stem, hkl.parent
        ins = d / f"{stem}.ins"
        if not ins.exists() or not _looks_like_hklf(hkl):
            continue
        cell = _cell_of(ins)
        if cell is None:
            continue
        key = (cell, hkl.stat().st_size)
        if key in seen_keys:            # skip duplicated copies/backups of same data
            continue
        seen_keys.add(key)
        res = d / f"{stem}.res"
        ref_res = res if (res.exists() and _res_has_atoms(res)) else None

        def _cif_has_atoms(c: Path) -> bool:
            try:
                return "_atom_site_fract" in c.read_text(encoding="utf-8",
                                                         errors="replace")
            except OSError:
                return False

        ref_cifs = [c for c in d.glob("*.cif")
                    if "check" not in c.name.lower() and c.stat().st_size > 2000
                    and _cif_has_atoms(c)]
        cases.append({
            "hkl": str(hkl), "ins": str(ins),
            "ref_res": str(ref_res) if ref_res else None,
            "ref_cif": str(ref_cifs[0]) if ref_cifs else None,
            "cell": cell,
            "size_mb": round(hkl.stat().st_size / 1e6, 2),
        })
    return cases


def build_benchmark_set(source_root: Path, dest: Path,
                        require_reference: bool = True) -> list[dict]:
    dest.mkdir(parents=True, exist_ok=True)
    manifest = []
    for case in scan_tree(source_root):
        if require_reference and not (case["ref_res"] or case["ref_cif"]):
            continue
        rel = Path(case["hkl"]).parent.relative_to(source_root)
        name = re.sub(r"[^\w\-]+", "_", str(rel) + "_" + Path(case["hkl"]).stem)[:80]
        case_dir = dest / name
        case_dir.mkdir(exist_ok=True)
        entry = {"name": name, "origin": str(Path(case["hkl"]).parent), "cell": case["cell"]}
        for kind in ("hkl", "ins", "ref_res", "ref_cif"):
            src = case.get(kind)
            if src:
                target = case_dir / (kind + Path(src).suffix)
                if not target.exists():
                    shutil.copy2(src, target)
                entry[kind] = str(target)
        manifest.append(entry)
    (dest / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


if __name__ == "__main__":
    import os
    import sys
    # The source tree is a local folder: pass it as the first argument or set
    # CRYSTALPILOT_LOCAL_DATA. There is no built-in default.
    root = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("CRYSTALPILOT_LOCAL_DATA", "")
    if not root:
        sys.exit("usage: local_data.py SOURCE_ROOT [DEST]   (or set CRYSTALPILOT_LOCAL_DATA)")
    src = Path(root)
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("benchmark/data")
    m = build_benchmark_set(src, out)
    print(f"{len(m)} benchmark cases -> {out}")
    for e in m:
        print(" -", e["name"], e["cell"], "ref:",
              "res" if e.get("ref_res") else "", "cif" if e.get("ref_cif") else "")
