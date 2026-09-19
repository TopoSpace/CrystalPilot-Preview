"""Refine the agent's o-nitroaniline model against the two-lattice HKLF5
data: HKLF 4 -> HKLF 5 + BASF, run vendored SHELXL, report R1/wR2/BASF.
Compare against the RDL ladder (naive 0.0678 -> PLATON HKLF5 0.0465)."""
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
SHELXL = REPO / "vendor" / "shelx" / "shelxl.exe"
RES = (REPO / "workbench" / "r5-onitwin" / "CrystalPilot Results"
       / "task_20260829_102829" / "final.res")

job = HERE / "hklf5_job"
job.mkdir(exist_ok=True)
txt = RES.read_text(encoding="utf-8", errors="replace")

lines = []
n_ls = 0
for ln in txt.splitlines():
    u = ln.strip().upper()
    if u.startswith("HKLF"):
        lines.append("BASF 0.3")
        lines.append("HKLF 5")
        continue
    if u.startswith("L.S."):
        ln = "L.S. 8"
    if u.startswith("WGHT"):
        # start from default weights; let SHELXL update
        ln = "WGHT 0.1"
    lines.append(ln)
(job / "job.ins").write_text("\n".join(lines) + "\n", encoding="ascii",
                             errors="replace")
shutil.copy(HERE / "onitwin_hklf5.hkl", job / "job.hkl")

r = subprocess.run([str(SHELXL), "job"], cwd=job, capture_output=True,
                   text=True, timeout=600)
out = (job / "job.lst").read_text(encoding="latin-1", errors="replace")
m = re.findall(r"R1 =\s+([\d.]+) for\s+(\d+) Fo > 4sig\(Fo\)\s+and\s+"
               r"([\d.]+) for all\s+(\d+) data", out)
w = re.findall(r"wR2 =\s+([\d.]+)", out)
b = re.findall(r"BASF\s+([\d.]+)", (job / "job.res").read_text(
    encoding="latin-1", errors="replace"))
gof = re.findall(r"GooF = S =\s+([\d.]+)", out)
print("last R1 blocks:", m[-2:] if m else None)
print("wR2:", w[-1] if w else None, " GooF:", gof[-1] if gof else None)
print("refined BASF:", b)
for ln in out.splitlines():
    if "**" in ln:
        print("WARN:", ln.strip()[:120])
