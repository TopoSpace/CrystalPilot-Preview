"""Run dials.import (ONLY import, no processing) on a frames directory and report
the detected dxtbx format class + number of images. Uses the same DIALS env
discovery as crystalpilot.io.frames_dials.

Usage: python _verify_import.py <frames_dir> <workdir> [glob_ext ...]
Writes <workdir>/import.log; prints JSON summary on last line.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, r"H:\CrystalPilot")
from crystalpilot.io.frames_dials import find_dials  # noqa: E402

FRAME_EXTS = {".cbf", ".img", ".h5", ".nxs", ".osc", ".mccd", ".sfrm",
              ".rodhypix", ".odeiger", ".kcd", ".mar2300", ".x", ".esperanto"}


def main():
    frames_dir = Path(sys.argv[1])
    workdir = Path(sys.argv[2])
    workdir.mkdir(parents=True, exist_ok=True)
    env = find_dials()

    files = sorted(p for p in frames_dir.rglob("*")
                   if p.is_file() and (p.suffix.lower() in FRAME_EXTS
                                       or p.name.lower().endswith(".cbf.gz")))
    if not files:
        print(json.dumps({"ok": False, "error": "no frame-like files found"}))
        return 1

    # Windows 32KiB command-line limit: pass explicit files when they fit,
    # otherwise pass the parent directories (dials.import scans directories;
    # robust against unpadded frame numbers where template= fails).
    args = [str(f) for f in files]
    if sum(len(a) + 3 for a in args) > 25000:
        # dials.import expands wildcards itself (works on Windows): one glob
        # per (directory, prefix-before-trailing-number, extension) group.
        pats = set()
        for f in files:
            m = re.match(r"^(?P<prefix>.*?)(?P<num>\d+)$", f.stem)
            prefix = m.group("prefix") if m else f.stem
            pats.add(str(f.parent / f"{prefix}*{f.suffix}"))
        args = sorted(pats)

    exe = env.dispatcher("dials.import")
    proc = subprocess.run([str(exe)] + args, cwd=str(workdir),
                          env=env.subprocess_env(), capture_output=True,
                          text=True, encoding="utf-8", errors="replace",
                          timeout=1800)
    out = (proc.stdout or "") + "\n--- stderr ---\n" + (proc.stderr or "")
    (workdir / "import.log").write_text(out, encoding="utf-8")

    fmt = re.findall(r"format:\s*<class '([^']+)'>", out)
    n_img = re.findall(r"num images:\s*(\d+)", out)
    summary = {
        "ok": proc.returncode == 0 and bool(fmt) and (workdir / "imported.expt").exists(),
        "returncode": proc.returncode,
        "n_files_given": len(files),
        "format": sorted(set(fmt)),
        "num_images": [int(x) for x in n_img],
        "log": str(workdir / "import.log"),
    }
    if not summary["ok"]:
        tail = [ln for ln in out.strip().splitlines() if ln.strip()][-6:]
        summary["log_tail"] = tail
    print(json.dumps(summary))
    return 0 if summary["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
