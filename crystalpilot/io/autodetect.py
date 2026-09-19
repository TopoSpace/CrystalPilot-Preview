"""File-set auto-detection: pair dropped files into a loadable dataset.

Given an arbitrary set of user files (drag & drop), classify and pair them:
reflection data (.hkl) + metadata (.ins/.res, .p4p) -> ReflectionDataset.
"""
from __future__ import annotations

import re
from pathlib import Path

from ..core.dataset import ReflectionDataset
from .shelx import load_shelx_dataset

_HKL_LINE = re.compile(r"^\s*-?\d+\s+-?\d+\s+-?\d+\s+-?[\d.eE+]+\s+[\d.eE+]+")


def classify(path: Path) -> str:
    ext = path.suffix.lower()
    if ext == ".hkl":
        return "hkl"
    if ext in (".ins", ".res"):
        return "ins"
    if ext == ".p4p":
        return "p4p"
    if ext in (".cif", ".fcf"):
        try:
            head = path.read_text(encoding="utf-8", errors="replace")[:60000]
        except OSError:
            return "cif"
        if "_refln" in head and ("_refln_F_squared_meas" in head
                                 or "_refln_F_meas" in head
                                 or "_refln.F_meas" in head):
            return "sf_cif"
        return "cif"
    if ext in (".raw", ".sfrm", ".img", ".cbf", ".h5", ".osc"):
        return "frames"
    # sniff extension-less files
    try:
        head = path.read_text(encoding="ascii", errors="strict")[:4000]
    except (UnicodeDecodeError, OSError):
        return "unknown"
    lines = head.splitlines()
    n_hkl = sum(1 for ln in lines[:40] if _HKL_LINE.match(ln))
    if n_hkl > 20:
        return "hkl"
    if any(ln.upper().startswith("CELL") for ln in lines[:30]):
        return "ins"
    return "unknown"


def parse_p4p(path: Path) -> dict:
    """Bruker P4P: CELL / CELLSD / SOURCE lines."""
    meta: dict = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        toks = line.split()
        if not toks:
            continue
        kw = toks[0].upper()
        if kw == "CELL" and len(toks) >= 7:
            meta["cell"] = tuple(float(x) for x in toks[1:7])
        elif kw in ("SOURCE", "SOURCE01") and len(toks) >= 3:
            try:
                meta["wavelength"] = float(toks[2])
            except ValueError:
                pass
    return meta


def detect_bundle(paths: list[str | Path]) -> dict:
    """Classify a set of files and propose the best pairing."""
    by_kind: dict[str, list[Path]] = {}
    for p in map(Path, paths):
        if p.exists():
            by_kind.setdefault(classify(p), []).append(p)
    bundle: dict = {"kinds": {k: [str(p) for p in v] for k, v in by_kind.items()}}
    hkls = by_kind.get("hkl", [])
    inss = by_kind.get("ins", [])
    if hkls:
        hkl = max(hkls, key=lambda p: p.stat().st_size)
        bundle["hkl"] = str(hkl)
        same_stem = [i for i in inss if i.stem.lower() == hkl.stem.lower()]
        if same_stem:
            bundle["ins"] = str(same_stem[0])
        elif inss:
            bundle["ins"] = str(inss[0])
        elif by_kind.get("p4p"):
            bundle["p4p"] = str(by_kind["p4p"][0])
    elif by_kind.get("sf_cif"):
        bundle["sf_cif"] = str(by_kind["sf_cif"][0])
        if by_kind.get("cif"):
            bundle["ref_cif"] = str(by_kind["cif"][0])
    return bundle


def load_bundle(bundle: dict) -> ReflectionDataset:
    if bundle.get("hkl"):
        hkl = Path(bundle["hkl"])
        if bundle.get("ins"):
            return load_shelx_dataset(hkl, Path(bundle["ins"]))
        if bundle.get("p4p"):
            meta = parse_p4p(Path(bundle["p4p"]))
            if "cell" not in meta:
                raise ValueError("p4p file has no CELL record")
            return load_shelx_dataset(hkl, None, cell=meta["cell"],
                                      wavelength=meta.get("wavelength"))
        raise ValueError("reflection data needs cell metadata (.ins/.res or .p4p)")
    sf = bundle.get("sf_cif")
    if not sf and bundle.get("hkl") is None:
        # a lone .cif dropped as "hkl_path" may actually be structure-factor data
        for key in ("cif",):
            if bundle.get(key):
                sf = bundle[key]
    if sf:
        from .cif_sf import load_cif_sf_dataset
        return load_cif_sf_dataset(Path(sf),
                                   ref_cif_path=bundle.get("ref_cif"))
    raise ValueError("no reflection data (.hkl or structure-factor CIF) found")
