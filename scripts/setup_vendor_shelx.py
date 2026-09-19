"""Deploy a project-local copy of SHELX (and PLATON) into vendor/shelx/.

Read-only copy from an existing local installation (default: D:\\OLEX2\\Olex2-1.5).
Never modifies the source installation, PATH, or the registry. vendor/ is
gitignored: licensed binaries must not enter the repository.

Usage:
    python -X utf8 scripts/setup_vendor_shelx.py [--source DIR] [--force]
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
VENDOR = REPO / "vendor" / "shelx"

DEFAULT_SOURCES = [
    Path(r"D:\OLEX2\Olex2-1.5"),
    Path(r"D:\shelx等等"),
]
if os.name != "nt":
    DEFAULT_SOURCES = [Path("/usr/local/bin"), Path("/opt/shelx"), Path("/usr/bin")]

# shelxl is required (refinement engine); the rest are optional extras.
# platon.exe needs the three DLLs next to it or it fails with
# "error while loading shared libraries".
BINARIES = {
    "shelxl.exe": True,
    "shelxt.exe": False,
    "platon.exe": False,
    "ciftab.exe": False,
    "salflibc.dll": False,
    "wgxlib01.dll": False,
    "wgxlib04.dll": False,
}
if os.name != "nt":
    BINARIES = {name: required for name, required in BINARIES.items() if name.endswith(".exe")}


def source_binary(directory: Path, name: str) -> Path:
    # Keep the application's historical *.exe destination names, but accept
    # native Linux filenames from the licensed installation source.
    native = directory / Path(name).stem
    return native if os.name != "nt" and native.is_file() else directory / name


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", type=Path, default=None)
    ap.add_argument("--force", action="store_true", help="re-copy even if present")
    args = ap.parse_args()

    sources = [args.source] if args.source else DEFAULT_SOURCES
    source = next((s for s in sources if s and source_binary(s, "shelxl.exe").is_file()), None)
    if source is None:
        print("ERROR: no source with shelxl.exe found. Tried:", ", ".join(map(str, sources)))
        return 1

    VENDOR.mkdir(parents=True, exist_ok=True)
    copied, missing = [], []
    for name, required in BINARIES.items():
        src, dst = source_binary(source, name), VENDOR / name
        if not src.exists():
            (missing if not required else copied).append(f"MISSING {name}")
            if required:
                print(f"ERROR: required binary {name} not found in {source}")
                return 1
            continue
        if os.name != "nt" and src.open("rb").read(2) == b"MZ":
            print(f"ERROR: {src} is a Windows executable; provide a native Linux build")
            return 1
        if src.resolve() == dst.resolve():
            copied.append(f"kept   {name} (already in vendor)")
            continue
        if dst.exists() and not args.force and sha256(dst) == sha256(src):
            copied.append(f"kept   {name} ({dst.stat().st_size} B)")
            continue
        shutil.copy2(src, dst)
        if os.name != "nt":
            dst.chmod(dst.stat().st_mode | 0o100)
        if sha256(src) != sha256(dst):
            print(f"ERROR: checksum mismatch after copying {name}")
            return 1
        copied.append(f"copied {name} ({dst.stat().st_size} B)")

    # Smoke: shelxl with no args prints a banner and exits (needs no license file).
    try:
        proc = subprocess.run([str(VENDOR / "shelxl.exe")], capture_output=True,
                              stdin=subprocess.DEVNULL,
                              timeout=30, cwd=str(VENDOR), text=True, errors="replace")
        banner = (proc.stdout or proc.stderr or "").strip().splitlines()
        banner_line = next((ln.strip() for ln in banner if "SHELX" in ln.upper()), "(no banner)")
    except Exception as e:  # noqa: BLE001
        print(f"ERROR: SHELXL cannot run on this host: {e}")
        return 1

    (VENDOR / "PROVENANCE.txt").write_text(
        f"source: {source}\n" + "\n".join(copied + missing) +
        f"\nbanner: {banner_line}\n"
        "note: read-only copies for CrystalPilot's internal use on this machine; "
        "do not redistribute; vendor/ is gitignored.\n",
        encoding="utf-8")

    print(f"source: {source}")
    for line in copied + missing:
        print(" ", line)
    print("banner:", banner_line)
    print("OK ->", VENDOR)
    return 0


if __name__ == "__main__":
    sys.exit(main())
