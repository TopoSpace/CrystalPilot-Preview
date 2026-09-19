"""Raw-diffraction-frames toolchain: staged, resumable DIALS processing that
turns detector frames into crystal.hkl + start.res for the refinement
workbench.

Six typed tools (whitelisted in registry.SESSIONLESS_TOOLS) drive the chain

    import_frames -> find_spots -> index_frames -> integrate_frames
        -> scale_and_export -> create_start_model

Every stage runs DIALS headlessly through crystalpilot.io.frames_dials
(separate conda env; never imported into this venv), writes its log to
<project>/.crystalpilot/frames/logs/<stage>.log and records its summary in
<project>/.crystalpilot/frames/state.json (atomic tmp+replace writes), so a
half-finished pipeline resumes where it stopped and any stage may be re-run
(overwrites its artifacts).

create_start_model produces the refinement starting point exactly like
benchmark/corrupt.py build_p24cu: deterministic coarse solve (charge flipping
-> peak interpretation -> isotropic LS -> Fourier completion) through the
default engine registry on the exported hkl/ins pair, serialized via
io.shelx_writer.write_res, then activates the refinement session via
project.reload_inputs() (imports the start model as node n0000).
"""
from __future__ import annotations

from .data_versions import input_directory, capture_source

import json
import math
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any

from ..io import frames_dials as fd
from ..tools.base import Tool, ToolContext, ToolResult, invoke

__all__ = ["register_frames_tools"]

#: generous per-DIALS-call timeouts (seconds). import must survive a cold
#: first read of ~2000 CBF headers from a loaded spinning disk (observed
#: >300s under concurrent runs).
# frame-reading stages (import/find_spots/integrate) scale with format cost:
# miniCBF parses in ms/frame but full imgCIF-CBF needs a pycbf parse per frame
# (~0.5 s x 1800 frames observed on sample_02) - give them the long budget
_TIMEOUTS = {
    "import": 2400.0, "find_spots": 3600.0, "index": 900.0, "refine": 900.0,
    "integrate": 3600.0, "symmetry": 900.0, "scale": 900.0, "export": 900.0,
    "export_mtz": 900.0,
}

#: Windows multiprocessing is PATHOLOGICAL for DIALS stages: measured on
#: the RODIN W(CO)6 set (376 rodhypix frames, idle machine)
#:   find_spots  nproc=1 11.6 s   nproc=2 44.1 s   nproc=4  86.5 s
#:   integrate   nproc=1 16.9 s                    nproc=4 221.2 s (13x!)
#: per-worker imageset re-open dominates. The W(CO)6 agent independently
#: found the same (its fast manual run used nproc=1). Overridable via
#: the tools' nproc param.
_NPROC = 1 if os.name == "nt" else 4


def register_frames_tools(reg, project) -> None:
    for cls in (ImportFrames, FindSpots, IndexFrames, IntegrateFrames,
                ScaleAndExport, ExportTwinHklf5,
                CreateStartModel, EstimateResolution,
                IngestVendorData):
        reg.register(cls(project))


# --------------------------------------------------------------------------- #
# state file (pure helpers, unit-testable without DIALS)
# --------------------------------------------------------------------------- #

def load_frames_state(workdir: str | Path) -> dict[str, Any]:
    """Read <workdir>/state.json ({} when absent or unreadable)."""
    p = Path(workdir) / "state.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_frames_state(workdir: str | Path, state: dict[str, Any]) -> None:
    """Atomic write (tmp file + os.replace) of <workdir>/state.json."""
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    tmp = workdir / "state.json.tmp"
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False,
                              default=str), encoding="utf-8")
    os.replace(tmp, workdir / "state.json")


# --------------------------------------------------------------------------- #
# small pure helpers
# --------------------------------------------------------------------------- #

_FORMULA_TOKEN = re.compile(r"([A-Z][a-z]?)([0-9]*\.?[0-9]*)")


def parse_composition(comp: str) -> dict[str, float]:
    """'C3 H7 N O2 S' / 'C3H7NO2S' -> {'C': 3.0, 'H': 7.0, 'N': 1.0, ...}."""
    counts: dict[str, float] = {}
    for el, num in _FORMULA_TOKEN.findall(comp or ""):
        counts[el] = counts.get(el, 0.0) + (float(num) if num else 1.0)
    return counts


def theta_deg(wavelength: float | None, d: float | None) -> float | None:
    """Bragg theta (degrees) for resolution d at the given wavelength."""
    if not wavelength or not d or d <= 0:
        return None
    x = wavelength / (2.0 * d)
    if x >= 1.0:
        return None
    return round(math.degrees(math.asin(x)), 3)


def build_solve_ins(dials_ins_text: str, composition: dict[str, float],
                    z: int, include_symmetry: bool = True) -> str:
    """A proper solve .ins from the DIALS shelx export: keep TITL/CELL (and
    LATT/SYMM when include_symmetry), add ZERR Z and a real SFAC/UNIT from the
    composition (the DIALS export writes 'UNIT 0 0 ...', which the engine
    rightly rejects as a composition hint)."""
    titl = "CrystalPilot frames toolchain"
    cell_line = None
    latt = None
    symm: list[str] = []
    for raw in dials_ins_text.splitlines():
        s = raw.strip()
        u = s.upper()
        if u.startswith("TITL"):
            titl = s[4:].strip() or titl
        elif u.startswith("CELL"):
            cell_line = s
        elif u.startswith("LATT"):
            latt = s
        elif u.startswith("SYMM"):
            symm.append(s)
    if cell_line is None:
        raise ValueError("dials.ins carries no CELL card")
    elements = sorted(composition, key=lambda e: (e != "C", e != "H", e))
    lines = [f"TITL {titl} (CrystalPilot start model)", cell_line,
             f"ZERR {z:g} 0 0 0 0 0 0"]
    if include_symmetry:
        if latt:
            lines.append(latt)
        lines.extend(symm)
    lines.append("SFAC " + " ".join(elements))
    lines.append("UNIT " + " ".join(f"{composition[e] * z:g}"
                                    for e in elements))
    lines += ["HKLF 4", "END"]
    return "\n".join(lines) + "\n"


def _deep_merge(dst: dict, patch: dict) -> dict:
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _deep_merge(dst[k], v)
        else:
            dst[k] = v
    return dst


def _dials_absorption_record(log_text: str) -> dict | None:
    """Absorption record from a dials.scale log: the corrections table row
    `| absorption | N |` proves a spherical-harmonic absorption surface was
    refined (empirical correction, no transmission factors to report)."""
    m = re.search(r"^\|\s*absorption\s*\|\s*(\d+)\s*\|", log_text,
                  re.MULTILINE)
    if not m:
        return None
    return {"type": "empirical",
            "details": (f"dials.scale spherical-harmonic absorption surface "
                        f"({m.group(1)} parameters), scale+decay+absorption "
                        f"model")}


def _update_context(project, patch: dict) -> dict:
    """Read-modify-write context.json (existing keys preserved; nested dicts
    merged), atomic replace, and refresh the in-memory project.context."""
    from .data_versions import input_directory
    path = input_directory(project) / "context.json"
    data: dict = {}
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
    _deep_merge(data, patch)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    os.replace(tmp, path)
    project.context = data
    return data


def _vendor_software(det: dict) -> str | None:
    """Data-collection software when the frame format implies it; else None."""
    exts = {Path(f).suffix.lower() for f in det.get("scan") or []}
    if ".sfrm" in exts:
        created = (det.get("sfrm_meta", {}).get("scan") or {}).get("CREATED")
        return f"Bruker ({created})" if created else "Bruker frame software"
    if exts & {".odeiger", ".rodhypix", ".rod_img", ".esperanto"}:
        return "CrysAlisPro (Rigaku Oxford Diffraction)"
    if ".kcd" in exts:
        return "Collect (Nonius KappaCCD)"
    return None


_STEM_NUM = re.compile(r"^(?P<prefix>.*?)(?P<num>\d+)$")


def _import_arguments(frames: list[str], workdir: Path) -> tuple[list[str], dict]:
    """dials.import argv for a frame list, working around the Windows 32 KiB
    command-line limit exactly like frames_dials.process_frames: collapse runs
    into template= patterns; unpadded frame numbering (1,10,100...) cannot be
    expressed as a template and is normalised into a hardlink directory with
    zero-padded names first."""
    info: dict[str, Any] = {"notes": []}
    if sum(len(f) + 3 for f in frames) <= 25000:
        return list(frames), info
    templates = fd._frame_templates(frames)
    widths: dict[tuple, set[int]] = {}
    for f in frames:
        mm = _STEM_NUM.match(Path(f).stem)
        if mm:
            key = (str(Path(f).parent), mm.group("prefix"), Path(f).suffix)
            widths.setdefault(key, set()).add(len(mm.group("num")))
    unpadded = any(len(w) > 1 for w in widths.values())
    if templates is None or unpadded:
        link_dir = workdir / "frames_normalized"
        link_dir.mkdir(parents=True, exist_ok=True)
        expected: dict[str, Path] = {}
        for f in frames:
            p = Path(f)
            mm = _STEM_NUM.match(p.stem)
            if not mm:
                raise fd.DialsProcessingError(
                    "import", f"frame {p.name} has no trailing frame number; "
                              "cannot normalise for template import.",
                    hint=fd._STAGE_HINTS["import"])
            expected[(f"{mm.group('prefix')}"
                      f"{int(mm.group('num')):05d}{p.suffix}")] = p
        # sync, don't just add: a re-import with a narrower scan selection
        # must drop the previous import's links, or the iterdir()-based
        # template build silently resurrects every excluded frame while the
        # summary honestly reports the exclusion (r11 case-c: agent had to
        # delete the cache dir by hand to make its scan filter take effect)
        n_stale = 0
        for q in link_dir.iterdir():
            if q.name not in expected:
                q.unlink()
                n_stale += 1
        if n_stale:
            info["notes"].append(
                f"dropped {n_stale} stale normalised link(s) from a "
                "previous import with a different frame selection")
        for name, src in expected.items():
            dest = link_dir / name
            if not dest.exists():
                try:
                    os.link(src, dest)
                except OSError:
                    shutil.copy2(src, dest)
        frames = sorted(str(link_dir / name) for name in expected)
        templates = fd._frame_templates(frames)
        info["notes"].append("unpadded frame numbering normalised via "
                             f"hardlinks in {link_dir}")
        info["frames_normalized_dir"] = str(link_dir)
    info["templates"] = templates
    return [f"template={t}" for t in templates], info


#: RMSD rows demand decimal points so integer count tables (e.g. dials.index's
#: '% indexed' table) never match
_RMSD_ROW = re.compile(r"^\|\s*\d+\s*\|\s*\d+\s*\|\s*(\d+\.\d+)\s*\|"
                       r"\s*(\d+\.\d+)\s*\|\s*(\d+\.\d+)\s*\|", re.M)


def _last_rmsd_row(text: str) -> dict[str, float] | None:
    rows = _RMSD_ROW.findall(text)
    if not rows:
        return None
    return {"x_px": float(rows[-1][0]), "y_px": float(rows[-1][1]),
            "phi_deg": float(rows[-1][2])}


def _space_group_hint(context: dict) -> str | None:
    for scope in ("data", "experiment", "chemistry"):
        v = (context.get(scope) or {}).get("space_group_hint")
        if v:
            return str(v)
    v = context.get("space_group_hint")
    return str(v) if v else None


# --------------------------------------------------------------------------- #
# tool base
# --------------------------------------------------------------------------- #

class _FramesTool(Tool):
    def __init__(self, project) -> None:
        self.project = project

    @property
    def workdir(self) -> Path:
        d = self.project.dir / ".crystalpilot" / "frames"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def state(self) -> dict[str, Any]:
        return load_frames_state(self.workdir)

    def record_stage(self, name: str, summary: dict[str, Any],
                     **top_level: Any) -> None:
        st = self.state()
        st.update(top_level)
        st.setdefault("stages", {})[name] = {
            "completed_at": time.strftime("%Y-%m-%d %H:%M:%S"), **summary}
        save_frames_state(self.workdir, st)

    def _dials_env(self, explicit: str | None = None) -> fd.DialsEnv:
        return fd.find_dials(explicit or self.state().get("dials_env"))

    def _runner(self, env: fd.DialsEnv, stage: str) -> fd._Runner:
        return fd._Runner(env, self.workdir, _TIMEOUTS.get(stage, 900.0))

    def _fail(self, e: fd.DialsProcessingError) -> ToolResult:
        msg = str(e)                     # already carries [stage], hint, log
        if e.log_path and Path(e.log_path).exists():
            tail = Path(e.log_path).read_text(encoding="utf-8",
                                              errors="replace")[-500:]
            msg += "\n--- log tail (last 500 chars) ---\n" + tail
        # DIALS 3.30 broken error path: when every candidate lattice is
        # rejected during refinement, dials.index dies with an
        # AttributeError instead of 'no solution' - translate the scary
        # traceback into the actionable truth (seen live on r11 case-b)
        if "'BasisVectorSearch' object has no attribute" in msg:
            msg += ("\n  -> this DIALS traceback is its broken error path "
                    "for 'all candidate solutions rejected' - treat it as "
                    "NO SOLUTION FOUND: retry with unit_cell=/space_group= "
                    "priors (see vendor_cell in the import summary / "
                    "context) or a different indexing method")
        vc = ((self.project.context or {}).get("data") or {}).get(
            "vendor_cell")
        if vc and "[index]" in msg:
            cell = vc.get("cell")
            if cell:
                msg += ("\n  -> vendor pre-experiment cell on file: "
                        + " ".join(f"{x:.4g}" for x in cell)
                        + (f" (centring {vc['centring']})"
                           if vc.get("centring") else "")
                        + " - pass unit_cell=[...] to index_frames")
        return ToolResult.failure(msg)

    def _missing(self, filename: str, produced_by: str) -> ToolResult:
        done = sorted((self.state().get("stages") or {}))
        return ToolResult.failure(
            f"{filename} not found under {self.workdir} - run {produced_by} "
            f"first (completed stages: {', '.join(done) if done else 'none'})")

    def _log(self, stage: str) -> str:
        return str(self.workdir / "logs" / f"{stage}.log")


# --------------------------------------------------------------------------- #
# 1. import_frames
# --------------------------------------------------------------------------- #

def parse_crysalis_crystal_ini(path: Path) -> dict[str, Any] | None:
    """CrysAlisPro pre-experiment cell from expinfo/<name>_crystal.ini.

    [Constrained lattice] carries the symmetry-constrained cell (preferred,
    all-zero when absent), [Lattice] the unconstrained fit; 'lattice
    type="C-lattice"' gives the centring. This is the vendor's own indexing
    answer - the single best prior when DIALS ab-initio indexing fails
    (auto max_cell underestimation on sparse small-molecule data).
    """
    try:
        text = path.read_text(encoding="latin-1", errors="replace")
    except OSError:
        return None

    def _cells(section: str) -> tuple[list[float], list[float]] | None:
        m = re.search(re.escape(f"[{section}]") + r"(.*?)(?:\n\[|\Z)", text,
                      re.S)
        if not m:
            return None
        blk = m.group(1)
        vals = re.search(r"^constants plus vol=\s*([\d.eE+\s-]+)$", blk,
                         re.M)
        errs = re.search(r"^error on constants plus vol=\s*([\d.eE+\s-]+)$",
                         blk, re.M)
        if not vals:
            return None
        try:
            v = [float(x) for x in vals.group(1).split()][:6]
            e = ([float(x) for x in errs.group(1).split()][:6]
                 if errs else [0.0] * 6)
        except ValueError:
            return None
        if len(v) < 6 or not any(v):
            return None
        return v, e

    got = _cells("Constrained lattice") or _cells("Lattice")
    if not got:
        return None
    cell, esd = got
    if not (all(1.5 < x < 300 for x in cell[:3])
            and all(10 < x < 170 for x in cell[3:6])):
        return None
    out: dict[str, Any] = {"cell": cell, "cell_esd": esd,
                           "source": path.name}
    mlat = re.search(r'lattice type="([A-Za-z])-lattice"', text)
    if mlat:
        out["centring"] = mlat.group(1).upper()
    return out


def find_vendor_cell(frames_dir: Path) -> dict[str, Any] | None:
    """Look for a CrysAlisPro crystal.ini near the frames (the experiment
    root is usually the frames dir itself or its parent)."""
    for root in (frames_dir, frames_dir.parent):
        for pat in ("expinfo/*_crystal.ini", "*_crystal.ini"):
            for p in sorted(root.glob(pat)):
                v = parse_crysalis_crystal_ini(p)
                if v:
                    return v
    return None


def _filter_screening_runs(det: dict, min_run: int,
                           notes: list[str]) -> None:
    """Drop screening/pre-experiment runs from a detect_frames() result.

    A handful-of-frames run (e.g. CrysAlisPro 'pre_' cell-check
    collections) poisons downstream profile modelling ('Too few
    reflections ... got 47 in total' at dials.integrate). Mutates det
    in place; never drops everything (if ALL runs are short, keep them)."""
    if min_run <= 1 or not det.get("runs"):
        return
    short = {k: v for k, v in det["runs"].items() if len(v) < min_run}
    if not short or len(short) == len(det["runs"]):
        return
    drop = {str(f) for v in short.values() for f in v}
    det["scan"] = [f for f in det["scan"] if str(f) not in drop]
    for k in short:
        det["runs"].pop(k)
    notes.append(
        f"excluded {len(short)} short run(s) {sorted(short)} "
        f"(<{min_run} frames each - screening collections; "
        f"pass min_run_frames=1 to keep them)")


class ImportFrames(_FramesTool):
    name = "import_frames"
    description = (
        "Start the raw-frames pipeline: classify the files in frames_dir "
        "(scan / background / mask runs, vendor notes) and run dials.import "
        "on the scan frames. Reports n_images, sweeps and formats; artifacts "
        "and per-stage logs live under .crystalpilot/frames/. Stages are "
        "resumable and re-runnable (state.json). BUDGET: the dials.import "
        f"stage is killed by a fixed watchdog at {_TIMEOUTS['import']:.0f} s "
        "(no parameter) and the tool then returns ok=false with the log "
        "tail; nothing is lost, the stage is simply re-runnable.")
    params_schema = {
        "type": "object",
        "properties": {
            "frames_dir": {"type": "string",
                           "description": "directory of raw detector frames "
                                          "(absolute or project-relative)"},
            "dials_env": {"type": "string",
                          "description": "DIALS conda env prefix (default: "
                                         "auto-discover)"},
            "min_run_frames": {"type": "integer", "default": 12,
                               "description": "runs with fewer frames are "
                                              "treated as screening "
                                              "collections and excluded "
                                              "(1 = keep everything)"},
        },
        "required": ["frames_dir"],
    }

    def run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        frames_dir = params.get("frames_dir")
        if not frames_dir:
            return ToolResult.failure("frames_dir is required")
        src = Path(str(frames_dir))
        if not src.is_absolute():
            src = self.project.dir / src
        src = src.resolve()
        if not src.is_dir():
            return ToolResult.failure(
                f"frames_dir does not exist or is not a directory: {src}")
        det = fd.detect_frames(src.iterdir())
        notes = list(det["notes"])
        if not det["scan"]:
            return ToolResult.failure(
                f"no scan frames recognised in {src}"
                + ((" - " + " ".join(notes)) if notes else ""))
        _filter_screening_runs(det, int(params.get("min_run_frames", 12)
                                        or 0), notes)
        formats: dict[str, int] = {}
        for f in det["scan"]:
            ext = Path(f).suffix.lower().lstrip(".") or "?"
            formats[ext] = formats.get(ext, 0) + 1
        vendor = _vendor_software(det)
        try:
            env = self._dials_env(params.get("dials_env"))
        except fd.DialsProcessingError as e:
            return self._fail(e)
        workdir = self.workdir
        try:
            import_args, extra = _import_arguments(det["scan"], workdir)
            notes += extra.get("notes", [])
            out = self._runner(env, "import").run(
                "import", "dials.import", import_args,
                progress=getattr(ctx, "progress", None))
        except fd.DialsProcessingError as e:
            return self._fail(e)
        m = re.search(r"num images:\s*(\d+)", out)
        n_images = int(m.group(1)) if m else None
        m = re.search(r"sweep:\s*(\d+)", out)
        n_sweeps = int(m.group(1)) if m else None
        expt = workdir / "imported.expt"
        if not expt.exists():
            return ToolResult.failure(
                "[import] dials.import produced no imported.expt\n  -> "
                + fd._STAGE_HINTS["import"] + f"\n  log: {self._log('import')}")
        summary: dict[str, Any] = {
            "n_images": n_images, "n_sweeps": n_sweeps, "formats": formats,
            "runs": {k: len(v) for k, v in det["runs"].items()},
            "n_background": len(det["background"]), "n_mask": len(det["mask"]),
            "notes": notes, "imported_expt": str(expt),
        }
        if vendor:
            summary["vendor_software"] = vendor
        if extra.get("templates"):
            summary["import_templates"] = extra["templates"]
        vc = find_vendor_cell(src)
        if vc:
            summary["vendor_cell"] = {
                **vc,
                "note": ("CrysAlisPro pre-experiment cell - the vendor's "
                         "own indexing answer. If ab-initio indexing "
                         "fails, pass unit_cell=[...] (and optionally the "
                         "centred space group) to index_frames instead of "
                         "digging through vendor files by shell")}
            _update_context(self.project, {"data": {"vendor_cell": vc}})
        top = {"frames_dir": str(src), "dials_env": str(env.prefix)}
        if vendor:
            top["vendor_software"] = vendor
        self.record_stage("import_frames", summary, **top)
        summary["no_state_change"] = True
        return ToolResult(ok=True, summary=summary,
                          artifacts={"imported_expt": str(expt),
                                     "log": self._log("import")})


# --------------------------------------------------------------------------- #
# 2. find_spots
# --------------------------------------------------------------------------- #

class FindSpots(_FramesTool):
    name = "find_spots"
    description = (
        "dials.find_spots on the imported frames -> strong.refl. Optional "
        "d_min resolution cutoff and min_spot_size (pixels) for weak/noisy "
        "data. Reports the number of strong spots (thousands expected for a "
        f"full scan of a decent crystal). BUDGET: a fixed watchdog kills the "
        f"stage at {_TIMEOUTS['find_spots']:.0f} s (no parameter) and the "
        "tool returns ok=false with the log tail; on a big sweep keep "
        "nproc=1 on Windows (measured 7x slower at nproc=4) and use d_min to "
        "cut the work rather than hoping for more time.")
    params_schema = {
        "type": "object",
        "properties": {
            "d_min": {"type": "number",
                      "description": "high-resolution cutoff for spot search"},
            "min_spot_size": {"type": "integer",
                              "description": "minimum pixels per spot"},
            "nproc": {"type": "integer",
                      "description": "worker processes (default 1 on "
                                     "Windows - multiprocessing overhead "
                                     "dominates there, measured 7x slower "
                                     "at nproc=4)"},
        },
    }

    def run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        if not (self.workdir / "imported.expt").exists():
            return self._missing("imported.expt", "import_frames")
        try:
            env = self._dials_env()
        except fd.DialsProcessingError as e:
            return self._fail(e)
        nproc = int(params.get("nproc") or _NPROC)
        args = ["imported.expt", f"nproc={nproc}"]
        if params.get("d_min") is not None:
            args.append(f"spotfinder.filter.d_min={float(params['d_min']):g}")
        if params.get("min_spot_size") is not None:
            args.append("spotfinder.filter.min_spot_size="
                        f"{int(params['min_spot_size'])}")
        r = self._runner(env, "find_spots")
        try:
            out = r.run("find_spots", "dials.find_spots", args,
                        progress=getattr(ctx, "progress", None))
        except fd.DialsProcessingError as e:
            return self._fail(e)
        n_strong = r.refl_count(self.workdir / "strong.refl")
        if n_strong is None:
            m = re.search(r"Saved (\d+) reflections", out)
            n_strong = int(m.group(1)) if m else None
        if not n_strong:
            return ToolResult.failure(
                "[find_spots] no strong spots found\n  -> "
                + fd._STAGE_HINTS["find_spots"]
                + f"\n  log: {self._log('find_spots')}")
        summary: dict[str, Any] = {"n_strong_spots": n_strong}
        extracted = sum(int(x) for x in
                        re.findall(r"Extracted (\d+) spots", out))
        if extracted and n_strong < 0.5 * extracted:
            summary["filter_warning"] = (
                f"only {n_strong} of {extracted} extracted spots survived "
                f"filtering ({100 * n_strong // extracted}%) - the auto "
                f"min_spot_size may be too strict for this detector "
                f"(CCDs with big pixels often need min_spot_size=3); "
                f"weak indexing later usually traces back here")
        for k in ("d_min", "min_spot_size"):
            if params.get(k) is not None:
                summary[k] = params[k]
        self.record_stage("find_spots", summary)
        summary["no_state_change"] = True
        return ToolResult(ok=True, summary=summary,
                          artifacts={"strong_refl":
                                     str(self.workdir / "strong.refl"),
                                     "log": self._log("find_spots")})


# --------------------------------------------------------------------------- #
# 3. index_frames
# --------------------------------------------------------------------------- #

def _count_crystals(expt_path: Path) -> int:
    """Number of crystal models in a DIALS .expt (multi-lattice indexing)."""
    try:
        data = json.loads(Path(expt_path).read_text())
        return len(data.get("crystal") or []) or 1
    except (OSError, json.JSONDecodeError, TypeError):
        return 1


def _dials_split_pair(workdir: Path, prefix: str,
                      index: int) -> tuple[Path, Path]:
    """Resolve the (expt, refl) pair dials.split_experiments wrote for
    experiment `index`.

    DIALS zero-pads the file index to the width of the LARGEST index
    (``len(str(n_experiments - 1))``): 6 experiments -> split_0.expt,
    22 -> split_00.expt .. split_21.expt, 150 -> split_000.expt. The
    r21 live failure: 11 sweeps x 2 lattices = 22 experiments, so
    split wrote ``twin_split_00`` while the old lookup tried
    ``twin_split_0`` then ``%03d`` - both missed, and a completed
    48-minute two-domain integration was thrown away at the packaging
    step. Try every plausible width, then the legacy default prefixes.
    """
    for fmt in (f"{prefix}_{index}", f"{prefix}_{index:02d}",
                f"{prefix}_{index:03d}", f"{prefix}_{index:04d}"):
        a = workdir / f"{fmt}.expt"
        if a.exists():
            return a, workdir / f"{fmt}.refl"
    return (workdir / ("experiments_%03d.expt" % index),
            workdir / ("reflections_%03d.refl" % index))


def _split_outputs_present(workdir: Path, prefix: str) -> str:
    """Short listing of what split_experiments actually produced, for
    error messages (so a name-scheme drift is self-diagnosing)."""
    names = sorted(p.name for p in workdir.glob(f"{prefix}_*.expt"))
    if not names:
        names = sorted(p.name for p in workdir.glob("experiments_*.expt"))
    head = ", ".join(names[:4])
    return f"{len(names)} file(s) on disk" + (f": {head}, ..." if head else "")


def _supercell_sentinel(cell, references) -> str | None:
    """Integer-multiple cell-volume check against reference cells.

    The twin-composite supercell trap (r17 live: 79 min sunk in a 2.003x
    cell; r18 hit the same trap and was only pulled back 45 min later by
    the reflection-data audit): a non-merohedral twin's two domains can
    index as ONE enlarged lattice when more spots are offered. The tell
    is exactly this volume ratio - fire it AT THE INDEXING STAGE.
    references: [(label, cell6), ...]."""
    from cctbx import uctbx
    if not cell:
        return None
    try:
        vol = uctbx.unit_cell(cell).volume()
    except Exception:  # noqa: BLE001 - advisory only
        return None
    hits: list[str] = []
    for label, ref in references:
        try:
            rv = uctbx.unit_cell(ref).volume()
        except Exception:  # noqa: BLE001
            continue
        if rv <= 0 or vol <= 0:
            continue
        big, small = max(vol, rv), min(vol, rv)
        ratio = big / small
        n = round(ratio)
        if 2 <= n <= 4 and abs(ratio - n) < 0.03 * n:
            rel = ("LARGER than" if vol > rv else "SMALLER than")
            hits.append(f"{ratio:.3f}x {rel} {label} ({rv:.0f} A^3)")
    if not hits:
        return None
    return (
        f"cell volume {vol:.0f} A^3 is an integer multiple of a "
        f"previously seen cell: {'; '.join(hits)}. This is the "
        f"twin-composite SUPERCELL precondition - a non-merohedral twin "
        f"can absorb both domains into one enlarged lattice that still "
        f"'solves' and refines to R~0.15-0.2. Evidence, not a verdict: "
        f"before adopting the larger cell, re-index with the SMALLER "
        f"cell as unit_cell= prior and max_lattices=2 (a genuine "
        f"composite splits into two clean sub-lattices; r18 resolution "
        f"path), and expect grossly inconsistent duplicate groups in "
        f"audit_reflection_data if the large cell is a composite.")


class IndexFrames(_FramesTool):
    name = "index_frames"
    description = (
        "dials.index: find the unit cell + orientation from the strong spots "
        "(joint indexing across sweeps of one crystal). Pass space_group / "
        "unit_cell as priors when known (e.g. from a .p4p) or after a failed "
        "ab-initio attempt. Reports cell, hall symbol, indexed fraction and "
        "positional RMSDs. If indexing fails outright on a spot list several "
        "times larger than physically plausible (CCD noise flooding), retry "
        "with strongest_n; for twins add max_lattices=2, and if the second "
        "lattice is not found lower fft3d_rmsd_cutoff. BUDGET: fixed "
        "watchdogs (no parameter) cap the optional filter and the indexing "
        f"at {_TIMEOUTS['index']:.0f} s each, so at most "
        f"{2 * _TIMEOUTS['index']:.0f} s; at the cap the tool returns "
        "ok=false with the log tail and nothing is committed.")
    params_schema = {
        "type": "object",
        "properties": {
            "space_group": {"type": "string",
                            "description": "known space group, e.g. P212121"},
            "unit_cell": {"type": "array", "items": {"type": "number"},
                          "minItems": 6, "maxItems": 6,
                          "description": "known cell a,b,c,alpha,beta,gamma"},
            "max_lattices": {"type": "integer", "default": 1,
                             "description": "search for up to N lattices - "
                                            "use 2 when a non-merohedral "
                                            "twin / split crystal defeats "
                                            "single-lattice indexing"},
            "method": {"type": "string",
                       "enum": ["fft3d", "fft1d",
                                "real_space_grid_search",
                                "low_res_spot_match"],
                       "description": "indexing algorithm (default fft3d; "
                                      "real_space_grid_search needs "
                                      "unit_cell+space_group)"},
            "keep_lattice": {"type": "integer",
                             "description": "when several lattices index: "
                                            "continue the chain with this "
                                            "one (0-based). The others "
                                            "remain in indexed_all.expt - "
                                            "declare the choice honestly "
                                            "(a twin's minor domain is "
                                            "real data you are setting "
                                            "aside)"},
            "strongest_n": {"type": "integer",
                            "description": "index using only the N most "
                                           "intense strong spots. The rescue "
                                           "for noise-flooded CCD spot lists "
                                           "(more 'spots' than physically "
                                           "possible reflections starve the "
                                           "FFT peak search); 8000 is a good "
                                           "first try"},
            "fft3d_rmsd_cutoff": {"type": "number",
                                  "description": "lower the FFT peak "
                                                 "acceptance threshold "
                                                 "(default 15); 3 rescues "
                                                 "sparse clouds, e.g. the "
                                                 "minor twin domain in a "
                                                 "max_lattices=2 search"},
        },
    }

    def run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        for req, by in (("imported.expt", "import_frames"),
                        ("strong.refl", "find_spots")):
            if not (self.workdir / req).exists():
                return self._missing(req, by)
        try:
            env = self._dials_env()
        except fd.DialsProcessingError as e:
            return self._fail(e)
        st = self.state()
        n_sweeps = ((st.get("stages") or {}).get("import_frames")
                    or {}).get("n_sweeps")
        spot_file = "strong.refl"
        n_keep = int(params.get("strongest_n") or 0)
        if n_keep > 0:
            code = ("import numpy as np; "
                    "from dials.array_family import flex; "
                    "t = flex.reflection_table.from_file(r'"
                    f"{self.workdir / 'strong.refl'}'); "
                    "I = np.array(t['intensity.sum.value']); "
                    "s = flex.bool(len(t), False); "
                    f"[s.__setitem__(int(i), True) for i in np.argsort(-I)[:{n_keep}]]; "
                    "t.select(s).as_file(r'"
                    f"{self.workdir / 'strong_filtered.refl'}'); "
                    "print(min(len(I), " + str(n_keep) + "))")
            r0 = self._runner(env, "index_filter")
            out0 = r0.run_pycode("index_filter", code)
            if out0 is None or not (self.workdir / "strong_filtered.refl").exists():
                return ToolResult.failure(
                    "strongest_n filtering failed (see logs/index_filter.log)")
            spot_file = "strong_filtered.refl"
        args = ["imported.expt", spot_file]
        if (n_sweeps or 0) > 1:
            # multiple sweeps of ONE crystal (normal home-lab multi-run setup)
            args.append("joint_indexing=True")
        uc = params.get("unit_cell")
        if uc:
            if len(uc) != 6:
                return ToolResult.failure("unit_cell needs exactly 6 numbers")
            args.append("unit_cell=" + ",".join(f"{float(v):g}" for v in uc))
        if params.get("space_group"):
            args.append("space_group="
                        + str(params["space_group"]).replace(" ", ""))
        n_latt = int(params.get("max_lattices") or 1)
        if n_latt > 1:
            args.append(f"max_lattices={n_latt}")
        if params.get("method"):
            args.append(f"indexing.method={params['method']}")
        if params.get("fft3d_rmsd_cutoff") is not None:
            args.append("indexing.fft3d.rmsd_cutoff="
                        f"{float(params['fft3d_rmsd_cutoff']):g}")
        r = self._runner(env, "index")
        try:
            out = r.run("index", "dials.index", args,
                        progress=getattr(ctx, "progress", None))
        except fd.DialsProcessingError as e:
            return self._fail(e)

        n_lattices = _count_crystals(self.workdir / "indexed.expt")
        lattice_note = None
        if n_lattices > 1:
            keep = params.get("keep_lattice")
            if keep is None:
                lattice_note = (
                    f"{n_lattices} lattices indexed (split crystal or "
                    f"non-merohedral twin). Downstream stages need ONE "
                    f"lattice: re-run index_frames with keep_lattice=<i> "
                    f"to choose (0 = usually the major domain), or handle "
                    f"the twin at the data level later.")
            else:
                keep = int(keep)
                if not 0 <= keep < n_lattices:
                    return ToolResult.failure(
                        f"keep_lattice={keep} out of range "
                        f"(0..{n_lattices - 1})")
                shutil.copy(self.workdir / "indexed.expt",
                            self.workdir / "indexed_all.expt")
                shutil.copy(self.workdir / "indexed.refl",
                            self.workdir / "indexed_all.refl")
                # joint indexing of S sweeps with L lattices yields S*L
                # experiment rows sharing L crystal models. Keeping one
                # lattice must keep ALL its sweeps - the r15 live failure
                # kept split_0 only and silently threw away 2 of 3 runs
                # (48% completeness traced back to exactly this).
                try:
                    exp_json = json.loads(
                        (self.workdir / "indexed_all.expt").read_text())
                    xtal_of = [e.get("crystal")
                               for e in exp_json.get("experiment", [])]
                except (OSError, json.JSONDecodeError) as e:
                    return ToolResult.failure(
                        f"cannot read indexed_all.expt: {e}")
                rows = [i for i, c in enumerate(xtal_of) if c == keep]
                if not rows:
                    return ToolResult.failure(
                        f"no experiments use crystal {keep} "
                        f"(crystal indices per row: {xtal_of})")
                try:
                    r.run("index_split", "dials.split_experiments",
                          ["indexed_all.expt", "indexed_all.refl"])
                except fd.DialsProcessingError as e:
                    return self._fail(e)

                pairs = [_dials_split_pair(self.workdir, "split", i)
                         for i in rows]
                if not all(a.exists() for a, _ in pairs):
                    return ToolResult.failure(
                        "dials.split_experiments per-lattice files not "
                        "found for rows "
                        f"{[i for (a, _), i in zip(pairs, rows) if not a.exists()]} "
                        f"({_split_outputs_present(self.workdir, 'split')}; "
                        "check logs/index_split.log)")
                if len(pairs) == 1:
                    shutil.copy(pairs[0][0], self.workdir / "indexed.expt")
                    shutil.copy(pairs[0][1], self.workdir / "indexed.refl")
                else:
                    args2: list[str] = []
                    for a, b in pairs:
                        args2 += [a.name, b.name]
                    args2 += ["output.experiments=indexed.expt",
                              "output.reflections=indexed.refl"]
                    try:
                        r.run("index_combine", "dials.combine_experiments",
                              args2)
                    except fd.DialsProcessingError as e:
                        return self._fail(e)
                lattice_note = (
                    f"kept lattice {keep} of {n_lattices} with all "
                    f"{len(pairs)} of its sweep(s); the other lattice(s) "
                    f"are REAL diffraction (twin/split domains) set aside "
                    f"in indexed_all.expt - disclose this in the final "
                    f"report, and expect overlap-affected intensities "
                    f"where the lattices collide.")

        cell, hall = fd._cell_from_expt(self.workdir / "indexed.expt")
        n_indexed = r.refl_count(self.workdir / "indexed.refl", flag="indexed")
        n_strong = ((st.get("stages") or {}).get("find_spots")
                    or {}).get("n_strong_spots") \
            or r.refl_count(self.workdir / "strong.refl")
        summary: dict[str, Any] = {
            "cell": [round(v, 5) for v in cell] if cell else None,
            "hall_symbol": hall,
            "n_lattices": n_lattices,
            "n_indexed": n_indexed,
            "rmsd": _last_rmsd_row(out),
        }
        if lattice_note:
            summary["lattice_note"] = lattice_note
        if n_keep > 0:
            summary["strongest_n"] = n_keep
            summary["spot_filter_note"] = (
                f"indexed against the {n_keep} most intense of "
                f"{n_strong or '?'} strong spots (noise-flood guard); "
                f"pct_indexed is relative to the full strong list")
        if params.get("fft3d_rmsd_cutoff") is not None:
            summary["fft3d_rmsd_cutoff"] = float(params["fft3d_rmsd_cutoff"])
        if n_strong and n_indexed:
            summary["pct_indexed"] = round(100.0 * n_indexed / n_strong, 1)
        # supercell sentinel: compare against every cell this project has
        # indexed before (kept in state) and the vendor pre-experiment cell
        refs: list[tuple[str, list[float]]] = []
        for h in st.get("indexed_cells_history") or []:
            if h.get("cell"):
                refs.append((f"earlier index run "
                             f"(strongest_n={h.get('strongest_n')})",
                             h["cell"]))
        vc = ((getattr(self.project, "context", None) or {})
              .get("data") or {}).get("vendor_cell") or {}
        if vc.get("cell"):
            refs.append(("vendor pre-experiment cell", vc["cell"]))
        sentinel = _supercell_sentinel(cell, refs)
        if sentinel:
            summary["twin_composite_warning"] = sentinel
        hist = list(st.get("indexed_cells_history") or [])
        if cell:
            hist.append({"cell": [round(v, 5) for v in cell],
                         "strongest_n": n_keep or None,
                         "n_lattices": n_lattices,
                         "at": time.strftime("%Y-%m-%d %H:%M:%S")})
            hist = hist[-10:]
        self.record_stage("index_frames", summary,
                          indexed_cells_history=hist)
        summary["no_state_change"] = True
        return ToolResult(ok=True, summary=summary,
                          artifacts={"indexed_expt":
                                     str(self.workdir / "indexed.expt"),
                                     "log": self._log("index")})


# --------------------------------------------------------------------------- #
# 4. integrate_frames
# --------------------------------------------------------------------------- #

class IntegrateFrames(_FramesTool):
    name = "integrate_frames"
    description = (
        "dials.refine (scan-varying geometry, also the cell refinement whose "
        "reflection count feeds the publication CIF) then dials.integrate. "
        "The long stage: minutes of CPU on thousands of frames. Reports "
        "n_integrated and the post-refinement RMSDs. BUDGET: fixed watchdogs "
        f"(no parameter) cap dials.refine at {_TIMEOUTS['refine']:.0f} s and "
        f"dials.integrate at {_TIMEOUTS['integrate']:.0f} s, so the ceiling "
        f"is {_TIMEOUTS['refine'] + _TIMEOUTS['integrate']:.0f} s - LONGER "
        "than the 3900 s a single tool call is allowed to take, so on a very "
        "large sweep expect the client to time out first; the stage keeps "
        "running and is resumable, and the progress notifications every "
        "~20 s are the liveness signal meanwhile.")
    params_schema = {
        "type": "object",
        "properties": {
            "nproc": {"type": "integer",
                      "description": "worker processes (default 1 on "
                                     "Windows - measured 13x slower at "
                                     "nproc=4 there)"},
        },
    }

    def run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        for req, by in (("indexed.expt", "index_frames"),
                        ("indexed.refl", "index_frames")):
            if not (self.workdir / req).exists():
                return self._missing(req, by)
        try:
            env = self._dials_env()
        except fd.DialsProcessingError as e:
            return self._fail(e)
        try:
            out_ref = self._runner(env, "refine").run(
                "refine", "dials.refine", ["indexed.expt", "indexed.refl"],
                progress=getattr(ctx, "progress", None))
        except fd.DialsProcessingError as e:
            return self._fail(e)
        rmsd = _last_rmsd_row(out_ref)
        n_used = re.findall(r"to refine against (\d+) reflections", out_ref)
        n_refl_cell = int(n_used[-1]) if n_used else None
        cell, hall = fd._cell_from_expt(self.workdir / "refined.expt")
        r = self._runner(env, "integrate")
        try:
            r.run("integrate", "dials.integrate",
                  ["refined.expt", "refined.refl",
                   f"nproc={int(params.get('nproc') or _NPROC)}"],
                  progress=getattr(ctx, "progress", None))
        except fd.DialsProcessingError as e:
            return self._fail(e)
        n_integrated = r.refl_count(self.workdir / "integrated.refl",
                                    flag="integrated")
        summary: dict[str, Any] = {
            "n_integrated": n_integrated,
            "rmsd": rmsd,
            "cell_refined": [round(v, 5) for v in cell] if cell else None,
            "hall_symbol": hall,
        }
        if n_refl_cell is not None:
            summary["n_refl_cell_refinement"] = n_refl_cell
        self.record_stage("integrate_frames", summary)
        summary["no_state_change"] = True
        return ToolResult(ok=True, summary=summary,
                          artifacts={"integrated_refl":
                                     str(self.workdir / "integrated.refl"),
                                     "refine_log": self._log("refine"),
                                     "log": self._log("integrate")})


# --------------------------------------------------------------------------- #
# 5. scale_and_export
# --------------------------------------------------------------------------- #

class ScaleAndExport(_FramesTool):
    name = "scale_and_export"
    description = (
        "dials.symmetry (space-group suggestion; failure downgraded to a "
        "warning) -> dials.scale -> dials.export (SHELX dials.hkl/dials.ins, "
        "best-effort .mtz). Needs the expected composition (e.g. 'C3 H7 N O2 "
        "S') for the SHELX export. Reports merging statistics (judge CC1/2, "
        "R_meas, completeness, I/sigma before continuing) and records the "
        "cell-measurement + computing provenance into context.json for the "
        "final publication CIF. Pass space_group= to RE-SCALE under a decided "
        "group (dials.reindex applies it, dials.symmetry is skipped): scaling "
        "under the true group lets outlier rejection see full equivalence "
        "classes - do this after deciding the group from the "
        "space_group_screen TABLE (a field in this tool's own summary: "
        "systematic-absence + E-stats scoring; not a separate tool) "
        "instead of hand-editing files. BUDGET: fixed watchdogs (no "
        f"parameter) cap each of reindex / symmetry / scale / export at "
        f"{_TIMEOUTS['scale']:.0f} s, so the ceiling is about "
        f"{5 * _TIMEOUTS['scale']:.0f} s; at a cap the tool returns ok=false "
        "naming the stage and the log tail, and the earlier stages stay on "
        "disk so a re-run resumes.")
    params_schema = {
        "type": "object",
        "properties": {
            "composition": {"type": "string",
                            "description": "chemical composition per formula "
                                           "unit, e.g. 'C3 H7 N O2 S'"},
            "resolution": {"type": "number",
                           "description": "optional d_min cutoff for scaling"},
            "space_group": {"type": "string",
                            "description": "decided space group (short "
                                           "Hermann-Mauguin, e.g. 'P21/c', "
                                           "'Pnma'); applied via dials.reindex "
                                           "before scaling so merging/outlier "
                                           "rejection run under this group"},
            "intensity": {
                "type": "string", "enum": ["combine", "profile", "sum"],
                "default": "combine",
                "description":
                    "dials.scale intensity_choice. On detectors with "
                    "structured noise, summation backgrounds can bias "
                    "strongly negative and the min_isigi guard then "
                    "silently excludes many rows under 'combine' "
                    "(signature: large removed_sum_isigi with near-zero "
                    "removed_prf_isigi in this tool's "
                    "scaling_exclusions); 'profile' rescues those rows "
                    "at slight cost on strong reflections."},
        },
        "required": ["composition"],
    }

    def run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        for req, by in (("integrated.expt", "integrate_frames"),
                        ("integrated.refl", "integrate_frames")):
            if not (self.workdir / req).exists():
                return self._missing(req, by)
        comp_raw = str(params.get("composition") or "").strip()
        if not comp_raw or not parse_composition(comp_raw):
            return ToolResult.failure(
                "composition is required (per formula unit, e.g. "
                "'C3 H7 N O2 S') - dials.export needs it for the SHELX SFAC")
        try:
            env = self._dials_env()
        except fd.DialsProcessingError as e:
            return self._fail(e)

        # -- decided group: reindex, skip the symmetry search -------------- #
        explicit_sg = str(params.get("space_group") or "").strip()
        sg_applied = None
        scale_in = ("integrated.refl", "integrated.expt")
        sg_suggestion = None
        sym_warning = None
        if explicit_sg:
            from cctbx import sgtbx as _sgtbx
            try:
                sg_info = _sgtbx.space_group_info(explicit_sg)
            except RuntimeError as e:
                return ToolResult.failure(
                    f"bad space_group {explicit_sg!r}: {e}")
            try:
                self._runner(env, "reindex").run(
                    "reindex", "dials.reindex",
                    ["integrated.refl", "integrated.expt",
                     "space_group=" + explicit_sg.replace(" ", "")],
                    progress=getattr(ctx, "progress", None))
            except fd.DialsProcessingError as e:
                return ToolResult.failure(
                    f"dials.reindex could not apply {explicit_sg!r} "
                    f"(incompatible with the integrated lattice?): "
                    f"{str(e).splitlines()[0]}\n  log: {self._log('reindex')}")
            if not (self.workdir / "reindexed.refl").exists():
                return ToolResult.failure(
                    "[reindex] produced no reindexed.refl - see log: "
                    + self._log("reindex"))
            scale_in = ("reindexed.refl", "reindexed.expt")
            sg_applied = str(sg_info.symbol_and_number())
        else:
            # -- symmetry (tolerate failure) ------------------------------ #
            try:
                out = self._runner(env, "symmetry").run(
                    "symmetry", "dials.symmetry",
                    ["integrated.refl", "integrated.expt"],
                    progress=getattr(ctx, "progress", None))
                m = re.search(r"Recommended space group:\s*(.+)", out)
                if m:
                    sg_suggestion = m.group(1).strip()
                if (self.workdir / "symmetrized.refl").exists():
                    scale_in = ("symmetrized.refl", "symmetrized.expt")
            except fd.DialsProcessingError as e:
                sym_warning = str(e).splitlines()[0]

        # -- scale --------------------------------------------------------- #
        args = list(scale_in)
        if params.get("resolution") is not None:
            args.append(f"d_min={float(params['resolution']):g}")
        intensity = str(params.get("intensity") or "combine")
        if intensity != "combine":
            args.append(f"intensity_choice={intensity}")
        try:
            out = self._runner(env, "scale").run(
                "scale", "dials.scale", args,
                progress=getattr(ctx, "progress", None))
        except fd.DialsProcessingError as e:
            return self._fail(e)
        scaling = fd._parse_scale_stats(out)
        try:  # filter census lives in the log; console may truncate it
            log_t = (self.workdir
                     / "dials.scale.log").read_text(errors="replace")
        except OSError:
            log_t = out
        scaling["exclusions"] = fd._parse_scale_exclusions(log_t)
        if intensity != "combine":
            scaling["intensity_choice"] = intensity
        if "i_over_sigma" not in scaling:
            # newer DIALS merging tables label the row 'I/sigma'
            m = re.search(r"^I/sigma\s+(-?[\d.]+)", out, re.M)
            if m:
                scaling["i_over_sigma"] = float(m.group(1))
        m = re.search(r"Low resolution limit\s+([\d.]+)", out)
        d_max = float(m.group(1)) if m else None
        if d_max is not None:
            scaling["d_max"] = d_max
        cell, hall = fd._cell_from_expt(self.workdir / "scaled.expt")

        # -- export -------------------------------------------------------- #
        composition_arg = re.sub(r"\s+", "", comp_raw)
        try:
            self._runner(env, "export").run(
                "export", "dials.export",
                ["scaled.refl", "scaled.expt", "format=shelx",
                 "shelx.hklout=dials.hkl", "shelx.ins=dials.ins",
                 f"composition={composition_arg}"])
        except fd.DialsProcessingError as e:
            return self._fail(e)
        exports: dict[str, str] = {}
        mtz_warning = None
        try:
            self._runner(env, "export_mtz").run(
                "export_mtz", "dials.export",
                ["scaled.refl", "scaled.expt", "format=mtz",
                 "mtz.hklout=scaled.mtz"])
        except fd.DialsProcessingError as e:       # mtz is a bonus
            mtz_warning = str(e).splitlines()[0]
        for key, name in (("shelx_hkl", "dials.hkl"),
                          ("shelx_ins", "dials.ins"), ("mtz", "scaled.mtz")):
            p = self.workdir / name
            if p.exists():
                exports[key] = str(p)
        if "shelx_hkl" not in exports:
            return ToolResult.failure(
                "[export] SHELX hkl was not written\n  -> "
                + fd._STAGE_HINTS["export"] + f"\n  log: {self._log('export')}")

        # -- provenance into context.json ---------------------------------- #
        from ..io.shelx import parse_ins_metadata
        wavelength = None
        if "shelx_ins" in exports:
            wavelength = parse_ins_metadata(
                Path(exports["shelx_ins"])).get("wavelength")
        st = self.state()
        n_cell = ((st.get("stages") or {}).get("integrate_frames")
                  or {}).get("n_refl_cell_refinement")
        reflns_used = n_cell or scaling.get("n_observations")
        cell_measurement = {
            k: v for k, v in (
                ("reflns_used", int(reflns_used) if reflns_used else None),
                ("theta_min", theta_deg(wavelength, d_max)),
                ("theta_max", theta_deg(wavelength, scaling.get("d_min"))),
            ) if v is not None}
        computing = {"data_reduction": "DIALS", "cell_refinement": "DIALS"}
        if st.get("vendor_software"):
            computing["data_collection"] = st["vendor_software"]
        exp_patch: dict[str, Any] = {
            "cell_measurement": cell_measurement, "computing": computing}
        # absorption record (P2 backlog): dials.scale refines a spherical-
        # harmonic absorption surface - an EMPIRICAL correction with no
        # transmission factors. Record it honestly so the frames route
        # stops shipping '?' absorption slots; a vendor .abs record
        # (multi-scan with a T range) always wins.
        try:
            absn = _dials_absorption_record(
                (self.workdir / "dials.scale.log").read_text(
                    encoding="utf-8", errors="replace"))
        except OSError:
            absn = None
        if absn and not (
                (self.project.context.get("experiment") or {})
                .get("absorption")):
            exp_patch["absorption"] = absn
        _update_context(self.project, {"experiment": exp_patch})

        # small-molecule space-group screen: dials.symmetry only ranks
        # SOHNCKE groups (MX heritage) - glides/inversion NEVER appear in
        # its recommendation (P21/c comes back "P 21", Pnma comes back
        # "P 21 21 21" - both observed live). Score the full Laue class by
        # systematic-absence statistics + E-statistics on the exported
        # unmerged intensities so the agent can pick the real group.
        sg_screen = None
        sg_screen_warning = None
        try:
            from cctbx import sgtbx as _sgtbx

            from .sg_screen import (read_shelx_hkl_intensities,
                                    screen_space_groups)
            ma = read_shelx_hkl_intensities(
                self.workdir / "dials.hkl", tuple(cell))
            laue = _sgtbx.space_group(str(hall).strip()) \
                .build_derived_laue_group()
            sg_screen = screen_space_groups(ma, laue)
        except Exception as e:  # noqa: BLE001 - the screen is advisory
            sg_screen_warning = f"{type(e).__name__}: {e}"

        summary: dict[str, Any] = {
            **({"space_group_applied": sg_applied,
                "space_group_applied_note":
                "data reindexed+scaled under this group (dials.symmetry "
                "skipped); merging stats above are the verdict on it"}
               if sg_applied else {}),
            "space_group_suggestion": sg_suggestion,
            **({"space_group_suggestion_note":
                "from dials.symmetry, which ranks SOHNCKE (chiral) groups "
                "only - check space_group_screen for glide/inversion "
                "candidates before solving"} if sg_screen else {}),
            **({"space_group_screen": sg_screen} if sg_screen else {}),
            **({"space_group_screen_warning": sg_screen_warning}
               if sg_screen_warning else {}),
            "symmetry_warning": sym_warning,
            "scaling": scaling,
            "cell_scaled": [round(v, 5) for v in cell] if cell else None,
            "hall_symbol": hall,
            "wavelength": wavelength,
            "exports": exports,
            "composition": comp_raw,
            "cell_measurement": cell_measurement,
            "computing": computing,
            "context_updated": True,
        }
        if mtz_warning:
            summary["mtz_warning"] = mtz_warning
        if params.get("resolution") is not None:
            summary["resolution_cutoff"] = float(params["resolution"])
        self.record_stage("scale_and_export", summary)
        summary["no_state_change"] = True
        return ToolResult(ok=True, summary=summary,
                          artifacts={**exports, "log": self._log("scale")})


# --------------------------------------------------------------------------- #
# 6. create_start_model
# --------------------------------------------------------------------------- #

class CreateStartModel(_FramesTool):
    name = "create_start_model"
    description = (
        "Turn the scaled data into the refinement starting point: copies the "
        "exported dials.hkl to <project>/crystal.hkl, runs the deterministic "
        "coarse solve (charge flipping -> peak interpretation -> isotropic LS "
        "-> Fourier completion) and writes start.res, then activates the "
        "refinement session (imports node n0000 via reload). symmetry='auto' "
        "accepts the DIALS space-group suggestion; 'hint' uses "
        "data.space_group_hint from context.json instead. Every result "
        "carries a solution_capability block (d_min, heaviest declared Z, "
        "completeness, tier routine/harder/no_record) stating what the "
        "physics expects of the scaled data before the coarse solve runs, "
        "so a failure in the tier this platform has no record for is not "
        "read as evidence that the structure is unsolvable.")
    params_schema = {
        "type": "object",
        "properties": {
            "composition": {"type": "string",
                            "description": "composition per formula unit "
                                           "(default: the one given to "
                                           "scale_and_export)"},
            "symmetry": {"type": "string", "enum": ["auto", "hint"],
                         "default": "auto"},
            "space_group": {"type": "string",
                            "description": "explicit space group (H-M, in "
                                           "the CURRENT cell setting, e.g. "
                                           "'P c m n' from the "
                                           "space_group_screen table) - "
                                           "overrides symmetry=auto/hint"},
            "hkl_source": {"type": "string",
                           "description": "alternative hkl in the frames "
                                          "workdir to solve from (default "
                                          "dials.hkl). For non-merohedral "
                                          "twins use 'twin_major_clean.hkl' "
                                          "from export_twin_hklf5 - the "
                                          "overlap-cleansed major domain "
                                          "solves far better than the "
                                          "contaminated full export"},
        },
    }

    def run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        # the disclosure travels with every outcome. The data this tool
        # solves are built inside _run, so _run publishes the block on the
        # context as soon as it has them; before that (a prerequisite
        # failure) the composition string is all there is to disclose.
        from ..chem import solvability
        try:
            # a project reuses its ToolContext across calls - never let a
            # previous run's block ride on this one's outcome
            ctx._solution_capability = None
        except Exception:  # noqa: BLE001 - some contexts are frozen stubs
            pass
        result = self._run(ctx, **params)
        block = getattr(ctx, "_solution_capability", None)
        if block is None:
            comp_raw = str(params.get("composition") or "").strip()
            try:
                block = solvability.session_capability(
                    getattr(ctx, "session", None), d_min=None,
                    d_min_source="the call did not reach the scaled data",
                    elements=list(parse_composition(comp_raw) or {})
                    if comp_raw else None,
                    elements_source=(f"composition given to this call "
                                     f"({comp_raw!r})" if comp_raw else ""))
            except Exception:  # noqa: BLE001 - never fail a call on a note
                block = None
        return solvability.attach(result, block)

    def _run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        hkl_name = str(params.get("hkl_source") or "dials.hkl").strip()
        if "/" in hkl_name or "\\" in hkl_name or ".." in hkl_name:
            return ToolResult.failure(
                "hkl_source must be a bare filename in the frames workdir")
        hkl_src = self.workdir / hkl_name
        ins_src = self.workdir / "dials.ins"
        if not hkl_src.exists():
            avail = sorted(p.name for p in self.workdir.glob("*.hkl"))
            return ToolResult.failure(
                f"{hkl_name} not found in the frames workdir "
                f"(available: {avail or 'none'}) - run scale_and_export "
                "(dials.hkl) or export_twin_hklf5 (twin_major_clean.hkl) "
                "first")
        if not ins_src.exists():
            return self._missing(ins_src.name, "scale_and_export")
        st = self.state()
        scale_sum = (st.get("stages") or {}).get("scale_and_export") or {}
        comp_raw = str(params.get("composition")
                       or scale_sum.get("composition") or "").strip()
        comp = parse_composition(comp_raw)
        if not comp:
            return ToolResult.failure(
                "no usable composition: pass composition='C3 H7 N O2 S' or "
                "run scale_and_export (whose composition is remembered)")
        n_non_h = sum(v for el, v in comp.items() if el != "H")
        if n_non_h <= 0:
            return ToolResult.failure(
                f"composition {comp_raw!r} has no non-H atoms")

        # heavy imports deferred (cctbx)
        from cctbx import sgtbx, uctbx
        from ..core.events import RunStore
        from ..io.shelx import load_shelx_dataset, parse_ins_metadata
        from ..io.shelx_writer import ShelxModel, write_res
        from ..pipeline.session import SolveSession
        from ..pipeline.standard import CF_LADDER, default_registry

        meta = parse_ins_metadata(ins_src)
        cell = meta.get("cell")
        if not cell:
            return ToolResult.failure("dials.ins carries no CELL card")
        volume = uctbx.unit_cell(cell).volume()
        z = max(1, round(volume / (18.0 * n_non_h)))   # ~18 A^3 per non-H atom

        sg_override = None
        explicit_sg = str(params.get("space_group") or "").strip()
        if explicit_sg:
            try:
                sg_override = sgtbx.space_group_info(explicit_sg).group()
            except RuntimeError as e:
                return ToolResult.failure(
                    f"bad space_group {explicit_sg!r}: {e}")
            if not sg_override.is_compatible_unit_cell(
                    uctbx.unit_cell(cell)):
                return ToolResult.failure(
                    f"space_group {explicit_sg!r} is not compatible with "
                    f"the scaled cell {cell} - give the symbol in the "
                    f"CURRENT setting (see space_group_screen symbols)")
        elif str(params.get("symmetry") or "auto") == "hint":
            hint = _space_group_hint(self.project.context or {})
            if not hint:
                return ToolResult.failure(
                    "symmetry='hint' but no space-group hint found - put it "
                    "in context.json under data.space_group_hint, or use "
                    "symmetry='auto' to accept the DIALS suggestion")
            try:
                sg_override = sgtbx.space_group_info(str(hint)).group()
            except RuntimeError as e:
                return ToolResult.failure(f"bad space-group hint {hint!r}: {e}")

        solve_ins = self.workdir / "solve.ins"
        try:
            solve_ins.write_text(
                build_solve_ins(ins_src.read_text(encoding="utf-8",
                                                  errors="replace"),
                                comp, z, include_symmetry=sg_override is None),
                encoding="utf-8")
        except ValueError as e:
            return ToolResult.failure(str(e))

        crystal_hkl = input_directory(self.project) / "crystal.hkl"
        hkl_src = capture_source(self.project, hkl_src)
        ins_src = capture_source(self.project, ins_src)
        from ..io.shelx import clean_hklf4
        hkl_clean = clean_hklf4(hkl_src, crystal_hkl)
        if getattr(self.project, "_input_stage", None) is not None:
            self.project._input_stage.processing = [
                f"clean_hklf4: dropped {hkl_clean['n_dropped_sigma']} sigma<=0 and {hkl_clean['n_dropped_nonfinite']} non-finite rows"]
        dataset = load_shelx_dataset(crystal_hkl, ins_path=solve_ins,
                                     space_group=sg_override)
        if dataset.symmetry_hint is None:
            return ToolResult.failure(
                "no symmetry available: dials.ins carries no LATT/SYMM and no "
                "hint was given")
        ses = SolveSession(dataset=dataset)
        merge = ses.set_symmetry(dataset.symmetry_hint)
        # publish the capability disclosure now: the coarse solve below may
        # fail, and the caller must be able to read that failure correctly
        try:
            from ..chem import solvability
            ctx._solution_capability = solvability.session_capability(
                ses, d_min=merge.get("d_min"),
                d_min_source="scaled data as exported (all of it)",
                elements=list(comp), elements_source=(
                    f"composition given to create_start_model / "
                    f"scale_and_export ({comp_raw!r})"),
                completeness=merge.get("completeness"),
                completeness_source="working-group merge of the scaled data")
        except Exception:  # noqa: BLE001 - a disclosure never fails a solve
            pass

        # deterministic coarse solve, exactly the build_p24cu recipe
        reg = default_registry()
        solve_ctx = ToolContext(store=RunStore(self.workdir / "solve_runs"),
                                session=ses)
        r = invoke(reg, solve_ctx, "solve_charge_flipping", {})
        if not r.ok:
            for attempt in CF_LADDER:
                r = invoke(reg, solve_ctx, "solve_charge_flipping", attempt)
                if r.ok:
                    break
        if not r.ok:
            return ToolResult.failure(
                f"charge flipping failed on the scaled data: {r.error}")
        r = invoke(reg, solve_ctx, "interpret_peaks", {})
        if not r.ok:
            return ToolResult.failure(f"peak interpretation failed: {r.error}")
        invoke(reg, solve_ctx, "refine", {"mode": "isotropic", "n_cycles": 6})
        invoke(reg, solve_ctx, "fourier_complete", {"max_rounds": 3})
        r = invoke(reg, solve_ctx, "refine", {"mode": "isotropic",
                                              "n_cycles": 6})
        if not r.ok:
            return ToolResult.failure(
                f"isotropic refinement of the coarse model failed: {r.error}")
        coarse_r1 = r.summary.get("r1_strong")
        if ses.model is None or ses.model.scatterers().size() == 0:
            return ToolResult.failure("coarse solve produced no atoms")
        space_group = str(ses.model.space_group_info())

        write_res(ShelxModel(
            xray_structure=ses.model,
            wavelength=dataset.wavelength or 0.71073, z=z,
            title="coarse solution from raw frames (DIALS + CrystalPilot)",
            rem_lines=[f"coarse solve R1 = {coarse_r1}",
                       "raw frames -> DIALS (import/index/integrate/scale) -> "
                       "charge flipping + isotropic LS"],
            weights=(0.1, 0.0)), input_directory(self.project) / "start.res")

        _update_context(self.project, {"data": {"hkl": "crystal.hkl",
                                                "start_model": "start.res"}})
        reload_info = self.project.reload_inputs()

        summary: dict[str, Any] = {
            "solved_r1": coarse_r1,
            "n_atoms": ses.model.scatterers().size(),
            "space_group": space_group,
            "z_estimated": z,
            "composition": comp_raw,
            "merge": merge,
            **({"hkl_source": hkl_name} if hkl_name != "dials.hkl" else {}),
            **({"hkl_rows_dropped": {
                    "sigma_le_0": hkl_clean["n_dropped_sigma"],
                    "non_finite": hkl_clean["n_dropped_nonfinite"]}}
               if (hkl_clean["n_dropped_sigma"]
                   or hkl_clean["n_dropped_nonfinite"]) else {}),
            "node": reload_info.get("node"),
            "reload": {"node": reload_info.get("node"),
                       "n_atoms": reload_info.get("n_atoms")},
            "files": {"hkl": "crystal.hkl", "start_model": "start.res"},
            # reload_inputs committed node n0000 itself - no second commit
            "no_state_change": True,
        }
        self.record_stage("create_start_model", {
            k: summary[k] for k in ("solved_r1", "n_atoms", "space_group",
                                    "z_estimated", "composition", "node")})
        return ToolResult(ok=True, summary=summary,
                          artifacts={"crystal_hkl": str(crystal_hkl),
                                     "start_res":
                                     str(self.project.dir / "start.res")})


# --------------------------------------------------------------------------- #
# 7. estimate_resolution
# --------------------------------------------------------------------------- #

class EstimateResolution(_FramesTool):
    name = "estimate_resolution"
    description = (
        "Resolution-cutoff evidence. Frames route: dials.estimate_resolution "
        "on the integrated (or scaled) data - objective d_min suggestion "
        "from CC1/2 (and I/sigma) shell curves. Vendor-hkl route (no DIALS "
        "products): falls back to a 12-shell merging-statistics table "
        "(CC1/2, I/sigma, completeness, multiplicity, Rmerge/Rmeas) "
        "computed from the session's unmerged intensities, with the same "
        "d_min heuristics. Expert rule: many lab datasets do not diffract "
        "to the detector edge - integrating noise shells inflates R factors "
        "and Ueq. If the suggested d_min is meaningfully coarser than the "
        "current limit, re-export truncated (frames: scale_and_export "
        "resolution=...; hkl: SHEL) and compare. Advisory only: never "
        "truncate to chase R - record the decision either way.")
    params_schema = {"type": "object", "properties": {
        "dials_env": {"type": "string",
                      "description": "optional DIALS env prefix override"}}}

    def run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        refl, expt = None, None
        for stem in ("scaled", "symmetrized", "integrated"):
            r = self.workdir / f"{stem}.refl"
            e = self.workdir / f"{stem}.expt"
            if r.exists() and e.exists():
                refl, expt = r, e
                break
        if refl is None:
            ses = ctx.session or getattr(self.project, "session", None)
            raw = (ses.dataset.intensities
                   if ses is not None and ses.dataset is not None else None)
            if raw is not None:
                return self._hkl_shell_estimate(raw, ses)
            return self._missing("integrated.refl", "integrate_frames")
        env = self._dials_env(params.get("dials_env"))
        runner = self._runner(env, "estimate_resolution")
        try:
            # misigma=2.0: referees' lenient cut (I/sigma>=2); their
            # conservative cut is I/sigma>=3 ("truncate where I/sigma
            # drops below 3 and add a note to the experimental")
            out = runner.run("estimate_resolution",
                             "dials.estimate_resolution",
                             [refl.name, expt.name, "misigma=2.0"])
        except fd.DialsProcessingError as e:
            return self._fail(e)

        import re as _re
        suggestions: dict[str, float] = {}
        for metric, pat in (
                ("cc_half", r"Resolution cc_half:\s*([\d.]+)"),
                ("i_over_sigma", r"Resolution I/sig:\s*([\d.]+)")):
            m = _re.search(pat, out)
            if m:
                suggestions[metric] = float(m.group(1))
        current = None
        m = _re.search(r"d_min\s*[:=]\s*([\d.]+)", out)
        if m:
            current = float(m.group(1))
        if not suggestions:
            return ToolResult.failure(
                "dials.estimate_resolution produced no suggestion "
                f"(see {self._log('estimate_resolution')})")
        d_suggest = suggestions.get("cc_half") or min(suggestions.values())
        summary = {
            "suggested_d_min": d_suggest,
            "by_metric": suggestions,
            "source": refl.name,
            "note": ("apply via scale_and_export(resolution=...) if coarser "
                     "than the current limit; keep the full-resolution "
                     "export for comparison and record the decision. "
                     "by_metric.i_over_sigma is the I/sig>=2 (lenient "
                     "referee) cut; strict referees use I/sig>=3 - if the "
                     "two metrics disagree strongly, state the choice and "
                     "its rationale in the report"),
        }
        if current:
            summary["current_d_min"] = current
        self.record_stage("estimate_resolution", summary)
        return ToolResult(ok=True, summary=summary)

    def _hkl_shell_estimate(self, raw, ses) -> ToolResult:
        """Vendor-hkl fallback: shell table + d_min suggestion from the
        session's unmerged intensities. Both r22 arms were pointed at this
        tool by the brief, got refused ('integrated.refl not found'), and
        each hand-wrote the same 12-shell table via SHELL - this is that
        table, computed by iotbx.merging_statistics."""
        from cctbx import crystal

        raw = raw.set_observation_type_xray_intensity()
        # merge in the working Laue class. Vendor-hkl sessions usually sit
        # in P1 before the group is decided - merging a metrically higher
        # lattice in -1 halves the apparent completeness (r22 live: mmm
        # data read 48% in -1 vs ~97% in mmm), so upgrade a trivial Laue
        # class to the LATTICE-METRIC one and disclose. CC1/2 / I-over-sig
        # barely move; completeness becomes meaningful.
        sg = (ses.symmetry.space_group() if ses.symmetry is not None
              else raw.space_group())
        laue = sg.build_derived_laue_group()
        laue_source = "working symmetry"
        if laue.order_z() <= 2:                       # -1: pre-decision
            from cctbx.sgtbx import lattice_symmetry
            metric = lattice_symmetry.group(
                raw.unit_cell(), max_delta=3.0).build_derived_laue_group()
            if metric.order_z() > laue.order_z():
                laue = metric
                laue_source = ("lattice metric (working symmetry is "
                               "triclinic/undecided)")
        # Centring: vendor exports omit lattice-absent rows entirely, so a
        # primitive-lattice expectation halves apparent completeness (r22
        # live: C-centred data read 48% against P). Infer the centring
        # from the index parity of the DATA and fold its translations into
        # the merging group; disclosed below. A file that does ship the
        # extinct rows fails every parity test -> P, still honest.
        centring, trs = self._infer_centring(raw.indices())
        if trs:
            from cctbx import sgtbx
            g = sgtbx.space_group(laue)
            for t in trs:
                g.expand_ltr(sgtbx.tr_vec(t))
            laue = g
        cs = crystal.symmetry(unit_cell=raw.unit_cell(), space_group=laue,
                              assert_is_compatible_unit_cell=False)
        # Friedel-merged stats: an anomalous-flagged array (hklf reader
        # default) counts +hkl/-hkl separately, halving completeness again
        data = raw.customized_copy(crystal_symmetry=cs,
                                   anomalous_flag=False)

        rows: list[dict[str, Any]] = []
        overall: dict[str, Any] = {}
        try:
            from iotbx import merging_statistics
            try:
                st = merging_statistics.dataset_statistics(
                    i_obs=data, n_bins=12, sigma_filtering=None)
            except TypeError:       # older signature without the kwarg
                st = merging_statistics.dataset_statistics(
                    i_obs=data, n_bins=12)

            def _row(b) -> dict[str, Any]:
                return {
                    "d_max": round(b.d_max, 3), "d_min": round(b.d_min, 3),
                    "n_obs": int(b.n_obs), "n_unique": int(b.n_uniq),
                    "multiplicity": round(b.mean_redundancy, 2),
                    "completeness": round(b.completeness, 3),
                    "i_over_sigma": round(b.i_over_sigma_mean, 2),
                    "r_merge": round(b.r_merge, 4),
                    "r_meas": round(b.r_meas, 4),
                    "cc_one_half": round(b.cc_one_half, 3),
                }
            rows = [_row(b) for b in st.bins]
            overall = _row(st.overall)
        except Exception as e:  # noqa: BLE001 - degrade, don't refuse:
            # merging_statistics raises on effectively-merged input
            # (multiplicity ~1); a completeness + I/sigma table is still
            # honest evidence there, just without CC1/2 / R_merge.
            merged = data.merge_equivalents().array()
            merged.setup_binner(n_bins=12)
            comp = merged.completeness(use_binning=True)
            binner = merged.binner()
            for i_bin in binner.range_used():
                frac = comp.data[i_bin]
                sel = binner.selection(i_bin)
                mi = merged.select(sel)
                ios = None
                if mi.size() and mi.sigmas() is not None:
                    from cctbx.array_family import flex
                    s = mi.sigmas().set_selected(mi.sigmas() <= 0, 1e-9)
                    ios = round(float(flex.mean(mi.data() / s)), 2)
                d_max, d_min = binner.bin_d_range(i_bin)
                rows.append({
                    "d_max": round(d_max, 3), "d_min": round(d_min, 3),
                    "n_unique": mi.size(),
                    "completeness": round(float(frac or 0.0), 3),
                    "i_over_sigma": ios,
                })
            overall = {"note": f"merging_statistics unavailable ({e}); "
                               f"reduced table (no CC1/2 / R_merge)"}

        suggestions: dict[str, float] = {}
        last_cc = last_ios = None
        for r in rows:                       # rows run coarse -> fine
            if r.get("cc_one_half") is not None and r["cc_one_half"] >= 0.3:
                last_cc = r["d_min"]
            if r.get("i_over_sigma") is not None and r["i_over_sigma"] >= 2.0:
                last_ios = r["d_min"]
        if last_cc is not None:
            suggestions["cc_half"] = last_cc
        if last_ios is not None:
            suggestions["i_over_sigma"] = last_ios

        summary: dict[str, Any] = {
            "mode": "hkl_shells",
            "source": "session unmerged intensities (no DIALS products)",
            "merge_laue_class": str(cs.space_group_info()),
            "merge_laue_source": laue_source,
            "centring_inferred": centring,
            "shells": rows,
            "overall": overall,
            "note": ("threshold heuristics: coarsest contiguous shells with "
                     "CC1/2>=0.3 and mean I/sig>=2 (lenient referee cut; "
                     "strict referees use I/sig>=3). Advisory only - to "
                     "ACT on it, set_resolution_limit(d_min=..., reason=...) "
                     "makes the cutoff session state (run_shelxl and the "
                     "delivery CIF apply it), then compare refinement + "
                     "merging stats and record the decision either way. "
                     "CC1/2 and R_merge need duplicate observations: with "
                     "multiplicity near 1 the file is already merged and "
                     "only completeness + I/sigma carry information."),
        }
        if suggestions:
            summary["suggested_d_min"] = (suggestions.get("cc_half")
                                          or min(suggestions.values()))
            summary["by_metric"] = suggestions
        else:
            summary["suggested_d_min"] = None
            summary["note"] = ("no shell meets CC1/2>=0.3 or I/sig>=2 - "
                               "inspect the table directly. " +
                               summary["note"])
        mult = overall.get("multiplicity")
        if isinstance(mult, (int, float)) and mult < 1.2:
            summary["warning"] = (
                f"overall multiplicity {mult} - data look already merged; "
                f"CC1/2/R_merge shells are not meaningful here")
        self.record_stage("estimate_resolution", summary)
        return ToolResult(ok=True, summary=summary)

    @staticmethod
    def _infer_centring(idx) -> tuple[str, list[tuple[int, int, int]]]:
        """Lattice centring implied by the measured indices, as (symbol,
        centring translations in 12ths). all() short-circuits on the first
        counter-example, so primitive data cost almost nothing."""
        def _all(f) -> bool:
            return all(f(h, k, l) for h, k, l in idx)

        a = _all(lambda h, k, l: (k + l) % 2 == 0)
        b = _all(lambda h, k, l: (h + l) % 2 == 0)
        c = _all(lambda h, k, l: (h + k) % 2 == 0)
        if a and b and c:
            return "F", [(0, 6, 6), (6, 0, 6), (6, 6, 0)]
        if _all(lambda h, k, l: (h + k + l) % 2 == 0):
            return "I", [(6, 6, 6)]
        if c:
            return "C", [(6, 6, 0)]
        if b:
            return "B", [(6, 0, 6)]
        if a:
            return "A", [(0, 6, 6)]
        if _all(lambda h, k, l: (-h + k + l) % 3 == 0):
            return "R", [(8, 4, 4), (4, 8, 8)]
        return "P", []


# --------------------------------------------------------------------------- #
# 8. ingest_vendor_data - cold start from vendor-software products
# --------------------------------------------------------------------------- #

_P4P_WAVE = {"MO": 0.71073, "CU": 1.54184, "AG": 0.56087, "GA": 1.34139}


def parse_p4p(path: Path) -> dict[str, Any]:
    """Cell / esd / wavelength / chem from a Bruker SAINT/XPREP .p4p."""
    out: dict[str, Any] = {}
    for line in path.read_text(encoding="latin-1",
                               errors="replace").splitlines():
        f = line.split()
        if not f:
            continue
        key = f[0].upper()
        if key == "CELL" and len(f) >= 7:
            out["cell"] = [float(x) for x in f[1:7]]
        elif key == "CELLSD" and len(f) >= 7:
            out["cell_esd"] = [float(x) for x in f[1:7]]
        elif key == "SOURCE" and len(f) >= 3:
            out["target"] = f[1].upper()
            try:
                out["wavelength"] = float(f[2])
            except ValueError:
                out["wavelength"] = _P4P_WAVE.get(f[1].upper()[:2])
        elif key == "CHEM" and len(f) >= 2 and f[1] != "?":
            out["chem"] = " ".join(f[1:])
        elif key in ("SPGR", "SGROUP") and len(f) >= 2 and f[1] != "?":
            out["space_group"] = f[1]
    return out


def parse_saint_ls(path: Path) -> dict[str, Any]:
    """Cell-measurement provenance from a Bruker SAINT ._ls listing.

    Exactly the numbers checkCIF PLAT183/184/185 ask for (and the expert
    KB names name._ls as their source): used-reflection count + 2theta
    range from the final Reflection Summary, plus the first component's
    cell with goodness-of-fit-corrected ESDs from the last global unit-cell
    least squares. Returns {} when the file has none of it.
    """
    import re
    try:
        text = path.read_text(encoding="latin-1", errors="replace")
    except OSError:
        return {}
    out: dict[str, Any] = {}
    m = re.match(r"\s*(SAINT\s+V[\w.]+)", text)
    if m:
        out["software"] = m.group(1)

    blocks = text.split("Reflection Summary:")
    if len(blocks) > 1:
        rows = re.findall(
            r"^\s+(All|\d+\.\d+\(\d+\))\s+(\d+)\s+(\d+)\s+(\d+)"
            r"\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*$",
            blocks[-1][:3000], re.M)
        pick = next((r for r in rows if r[0] == "All"), None)
        if pick is None and rows:
            pick = max(rows, key=lambda r: int(r[3]))
        if pick:
            out["reflns_used"] = int(pick[3])
            out["theta_min"] = round(float(pick[6]) / 2.0, 3)
            out["theta_max"] = round(float(pick[7]) / 2.0, 3)

    # cell + ESDs: first component block of the last global refinement
    # (anchor must not hit the 'End global unit cell refinement' trailer)
    anchor = text.rfind("Unconstrained global unit cell refinement")
    if anchor < 0:
        anchor = text.rfind("Constrained global unit cell refinement")
    region = text[anchor:] if anchor >= 0 else text
    cms = list(re.finditer(
        r"cell and ESDs:\s*\n[^\n]*Alpha[^\n]*\n"
        r"\s*([\d.eE+\s-]+)\n\s*([\d.eE+\s-]+)\n"
        r"(?:Corrected for goodness of fit:\s*\n\s*([\d.eE+\s-]+)\n)?",
        region))
    cm = (cms[0] if anchor >= 0 and cms
          else (cms[-1] if cms else None))
    if cm:
        try:
            vals = [float(x) for x in cm.group(1).split()]
            esd_plain = [float(x) for x in cm.group(2).split()]
            esd_corr = ([float(x) for x in cm.group(3).split()]
                        if cm.group(3) else None)
            if len(vals) >= 6:
                out["cell"] = vals[:6]
            esd = esd_corr if esd_corr and len(esd_corr) >= 6 else esd_plain
            if len(esd) >= 6 and any(esd[:6]):
                out["cell_esd"] = esd[:6]
        except ValueError:
            pass
    return out


def looks_like_shelx_hkl(path: Path, n_check: int = 30) -> dict[str, Any]:
    """Cheap validation + HKLF5-batch sniff of a SHELX-format hkl."""
    n_ok = 0
    has_batch = False
    try:
        with path.open(encoding="latin-1", errors="replace") as fh:
            for i, line in enumerate(fh):
                if i >= n_check or _is_hkl_terminator(line):
                    break
                if len(line.rstrip("\r\n")) < 28:
                    continue
                try:
                    int(line[0:4]); int(line[4:8]); int(line[8:12])
                    float(line[12:20]); float(line[20:28])
                    n_ok += 1
                    # negative component = the defining HKLF5 marker; a
                    # positive-only column is a scan/scale batch (HKLF4)
                    tail = line[28:].split()
                    if tail and tail[-1].lstrip("-").isdigit() \
                            and int(tail[-1]) < 0:
                        has_batch = True
                except ValueError:
                    return {"ok": False}
    except OSError:
        return {"ok": False}
    return {"ok": n_ok >= 5, "hklf5_batches": has_batch}


def parse_sadabs_abs(path: Path) -> dict[str, Any] | None:
    """Absorption-correction provenance from a SADABS/TWINABS .abs listing.

    First non-empty line carries the program+version (-> details); the last
    'Minimum and maximum apparent transmission' line carries the T range
    that belongs in _exptl_absorpt_correction_T_min/max (the file prints
    one per exported dataset - differences are in the 4th decimal).
    """
    try:
        text = path.read_text(encoding="latin-1", errors="replace")
    except OSError:
        return None
    head = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    if not re.search(r"SADABS|TWINABS", head, re.I):
        return None
    trans = re.findall(r"Minimum and maximum apparent transmission:\s*"
                       r"([\d.]+)\s+([\d.]+)", text)
    if not trans:
        return None
    out: dict[str, Any] = {"type": "multi-scan",
                           "t_min": float(trans[-1][0]),
                           "t_max": float(trans[-1][1]),
                           "details": head}
    msph = re.findall(r"spherical absorption correction applied with\s+"
                      r"mu\*r =\s*([\d.]+)", text)
    if msph:
        out["details"] += ("; additional spherical correction "
                           f"mu*r={msph[-1]}")
    return out


def parse_crysalis_cif_od(path: Path) -> dict[str, Any] | None:
    """Experimental metadata from a CrysAlisPro `.cif_od` reduction record.

    CrysAlisPro writes this next to <name>_autored.hkl and it carries
    exactly the fields checkCIF asks for and a bare hkl cannot supply:
    absorption type + T range, collection temperature, source/radiation,
    diffractometer and detector, and the cell-measurement reflection
    count and theta range. Without it a vendor-reduced dataset arrives
    with '?' in those slots (PLAT183/184/185 family).

    Returns the canonical context.json `experiment` sub-dict; None when
    the file is not a CrysAlisPro record."""
    try:
        text = path.read_text(encoding="latin-1", errors="replace")
    except OSError:
        return None

    def val(tag: str) -> str | None:
        m = re.search(re.escape(tag) + r"[ \t]+(?:'([^']*)'|\"([^\"]*)\"|"
                      r"(\S+))", text)
        if not m:
            return None
        raw = (m.group(1) or m.group(2) or m.group(3) or "").strip()
        return None if raw in ("?", ".", "") else raw

    def num(tag: str) -> float | None:
        raw = val(tag)
        if raw is None:
            return None
        # CIF numbers carry an esd in parentheses: 100.0(2)
        m = re.match(r"(-?\d*\.?\d+)", raw)
        try:
            return float(m.group(1)) if m else None
        except ValueError:
            return None

    creator = val("_audit_creation_method") or ""
    if "crysalis" not in creator.lower():
        return None

    out: dict[str, Any] = {}
    if (t := num("_diffrn_ambient_temperature")) is not None:
        out["temperature_K"] = t
    instrument = {k: v for k, v in (
        ("source", val("_diffrn_source_type") or val("_diffrn_source")),
        ("diffractometer", val("_diffrn_measurement_device_type")),
        ("detector", val("_diffrn_detector_type")),
        ("radiation_type", val("_diffrn_radiation_type")),
        ("monochromator", val("_diffrn_radiation_monochromator")),
    ) if v}
    if (wl := num("_diffrn_radiation_wavelength")) is not None:
        instrument["wavelength_A"] = wl
    if instrument:
        out["instrument"] = instrument
    t_min, t_max = (num("_exptl_absorpt_correction_T_min"),
                    num("_exptl_absorpt_correction_T_max"))
    if t_min is not None and t_max is not None:
        out["absorption"] = {
            "type": val("_exptl_absorpt_correction_type") or "multi-scan",
            "t_min": t_min, "t_max": t_max,
            "details": val("_exptl_absorpt_process_details") or creator}
    cm = {k: v for k, v in (
        ("reflns_used", num("_cell_measurement_reflns_used")),
        ("theta_min", num("_cell_measurement_theta_min")),
        ("theta_max", num("_cell_measurement_theta_max")),
        ("temperature_K", num("_cell_measurement_temperature")),
    ) if v is not None}
    if cm:
        if "reflns_used" in cm:
            cm["reflns_used"] = int(cm["reflns_used"])
        out["cell_measurement"] = cm
    computing = {k: v for k, v in (
        ("data_collection", val("_computing_data_collection")),
        ("cell_refinement", val("_computing_cell_refinement")),
        ("data_reduction", val("_computing_data_reduction")),
    ) if v}
    if computing:
        out["computing"] = computing
    return out or None


def hklf5_batch_count(path: Path) -> int:
    """Largest twin-domain index in an HKLF5-batched hkl (0 = no batches).

    Scans the whole file: the first reflections often belong to domain 1
    only, so the 30-line sniff in looks_like_shelx_hkl cannot count domains.
    A uniform batch column of 1s (some HKLF4 exports) also returns 0.

    HKLF5 marks composite (overlapped) reflections with NEGATIVE
    component numbers - a column that never goes negative is either a
    SAINT/scaling batch label on HKLF4 data (plain SHELXL ignores it
    without BASF) or a separated-domain twin export; sign alone cannot
    distinguish those two, so positive-only files return 0 here and the
    ingest listing surfaces the ambiguity for the agent to resolve from
    provenance. r14a live-fire: an 8-batch scale column was misread as a
    7-domain twin. r14b live-fire: scanning past the SHELX all-zero
    terminator row turned a '3-10' page range in the trailer citation
    into a bogus negative domain -10.
    """
    n = 0
    has_neg = False
    try:
        with path.open(encoding="latin-1", errors="replace") as fh:
            for line in fh:
                if _is_hkl_terminator(line):
                    break
                if len(line.rstrip("\r\n")) < 28:
                    continue
                tail = line[28:].split()
                if tail and tail[-1].lstrip("-").isdigit():
                    try:
                        b = int(tail[-1])
                    except ValueError:
                        continue
                    n = max(n, abs(b))
                    if b < 0:
                        has_neg = True
    except OSError:
        return 0
    return n if has_neg and n > 1 else 0


def parse_hkl_trailer_cif(path: Path) -> dict[str, Any] | None:
    """Absorption CIF items SADABS/XPREP append AFTER the hkl terminator.

    SHELXL-2018 silently copies these into its ACTA output - r14b's
    delivered CIF carried the author's SADABS T values while the agent's
    prose said 'not supplied', because nothing had surfaced the channel.
    Parsing the trailer at ingest makes it visible: the values land in
    experiment.absorption with provenance instead of sneaking through.
    Text fields use ')' as delimiter in this convention (not ';')."""
    try:
        lines = path.read_text(encoding="latin-1",
                               errors="replace").splitlines()
    except OSError:
        return None
    it = iter(lines)
    for line in it:
        if _is_hkl_terminator(line):
            break
    else:
        return None
    out: dict[str, Any] = {}
    details: list[str] = []
    in_details = False
    for line in it:
        s = line.strip()
        if in_details:
            if s == ")":
                in_details = False
            else:
                details.append(s)
            continue
        m = re.match(r"(_exptl_absorpt_correction_(?:type|T_min|T_max))"
                     r"\s+(\S+)", s)
        if m:
            tag, val = m.group(1), m.group(2)
            if tag.endswith("type"):
                out["type"] = val
            else:
                try:
                    out["t_min" if tag.endswith("T_min") else "t_max"] = \
                        float(val)
                except ValueError:
                    pass
        elif s == "_exptl_absorpt_process_details":
            nxt = next(it, "").strip()
            if nxt == ")":
                in_details = True
    if details:
        out["details"] = " ".join(details)
    return out if ("type" in out or "t_min" in out) else None


def _is_hkl_terminator(line: str) -> bool:
    """SHELX hkl data ends at the all-zero h k l row; anything after is
    free trailer text (often the SHELX citation) and must never be parsed
    as reflections."""
    try:
        return (int(line[0:4]) == 0 and int(line[4:8]) == 0
                and int(line[8:12]) == 0)
    except (ValueError, IndexError):
        return False


def scale_batch_max(path: Path) -> int:
    """Largest positive batch label when the column is positive-only
    (0 when absent, uniform, or a negative-marker HKLF5 file). Stops at
    the all-zero terminator row. Informational: lets ingest surface the
    positive-only ambiguity (scan-scale batches vs separated-domain twin
    export) for the agent."""
    n = 0
    try:
        with path.open(encoding="latin-1", errors="replace") as fh:
            for line in fh:
                if _is_hkl_terminator(line):
                    break
                if len(line.rstrip("\r\n")) < 28:
                    continue
                tail = line[28:].split()
                if tail and tail[-1].lstrip("-").isdigit():
                    try:
                        b = int(tail[-1])
                    except ValueError:
                        continue
                    if b < 0:
                        return 0
                    n = max(n, b)
    except OSError:
        return 0
    return n if n > 1 else 0


def hkl_file_hashes(path: Path) -> dict[str, Any]:
    """Whole-file sha256 plus a sha256 of the REFLECTION ROWS only (up to
    and including the all-zero terminator, CR stripped), and the row count.

    pa1 cu: crystal_b.hkl and crystal_c.hkl differ by 71 bytes of trailer
    text after the terminator and are the same dataset; every cu agent
    compared them by hand (Get-FileHash, line counts, head/tail,
    Compare-Object - cu-l3-r1 hung 15 min in it). Two hashes turn 'same
    data, different trailer' into a one-line fact, and the whole-file hash
    is what the same-file ingest guard compares."""
    import hashlib
    raw = path.read_bytes()
    rows: list[bytes] = []
    n_rows = 0
    for ln in raw.splitlines():
        ln = ln.rstrip(b"\r")
        rows.append(ln)
        if _is_hkl_terminator(ln.decode("latin-1", errors="replace")):
            break
        if len(ln.rstrip()) >= 28:
            n_rows += 1
    return {"sha256": hashlib.sha256(raw).hexdigest(),
            "data_sha256": hashlib.sha256(b"\n".join(rows)).hexdigest(),
            "n_rows": n_rows, "size_bytes": len(raw)}


def hkl_candidate_stats(path: Path, cell, space_group=None,
                        n_bins: int = 10) -> dict[str, Any]:
    """The numbers a crystallographer picks a reflection file on: n
    reflections, n unique after merging in the Laue class, multiplicity,
    completeness, R_int / R_sigma, mean I/sigma overall and in the outer
    shell, resolution limits, and whether the file looks merged already.

    pa1 cu (6 runs): ingest_vendor_data listed three candidates as
    'HKLF4-like' and nothing else, so the agents either re-ingested each
    file in turn (three nodes) or hand-wrote shell statistics; this table
    is what they were reconstructing. Merging class: the declared
    LATT/SYMM group's Laue class when one is given, upgraded to the
    lattice-metric class when that is triclinic (a P1 placeholder start
    would otherwise halve the apparent completeness - r22 live), with
    the lattice centring inferred from index parity (vendor exports omit
    the absent rows). Both are disclosed per row. Never raises: a file
    the reader cannot digest reports {'error': ...} instead."""
    from cctbx import crystal, sgtbx
    from cctbx.array_family import flex
    from cctbx.sgtbx import lattice_symmetry
    from iotbx.shelx import hklf

    out: dict[str, Any] = {}
    try:
        cs1 = crystal.symmetry(unit_cell=cell, space_group_symbol="P 1")
        rd = hklf.reader(file_name=str(path))
        arrays = rd.as_miller_arrays(crystal_symmetry=cs1,
                                     merge_equivalents=False,
                                     anomalous=True)
    except Exception as e:  # noqa: BLE001 - one bad file must not kill the table
        return {"error": f"{type(e).__name__}: {e}"}
    raw = arrays[0]
    out["n_reflections"] = int(raw.size())
    batch = rd.batch_numbers()
    if batch is None and len(arrays) > 1:
        batch = arrays[1].data()
    if batch is not None:
        try:
            pos = batch > 0
        except TypeError:               # flex.int has no comparison ops
            pos = batch.as_double() > 0
        n_neg = pos.count(False)
        if n_neg:
            # HKLF5: one row per composite observation (batch>0), same
            # convention as load_shelx_dataset
            raw = raw.select(pos)
            out["hklf5_note"] = (f"{n_neg} negative-batch component rows "
                                 "excluded; intensities are twin-composite "
                                 "(statistics approximate)")
    if raw.sigmas() is not None:
        good = raw.sigmas() > 0
        n_bad = good.count(False)
        if n_bad:
            raw = raw.select(good)
            out["n_sigma_dropped"] = int(n_bad)
    if raw.size() == 0 or raw.sigmas() is None:
        out["error"] = "no usable reflections (empty file or no sigmas)"
        return out
    raw = raw.set_observation_type_xray_intensity()
    d_max, d_min = raw.d_max_min()
    out["d_max"] = round(float(d_max), 2)
    out["d_min"] = round(float(d_min), 3)

    laue = None
    laue_source = ""
    if space_group is not None:
        laue = space_group.build_derived_laue_group()
        laue_source = "declared LATT/SYMM"
    if laue is None or laue.order_z() <= 2:
        metric = lattice_symmetry.group(
            raw.unit_cell(), max_delta=3.0).build_derived_laue_group()
        if laue is None or metric.order_z() > laue.order_z():
            laue = metric
            laue_source = ("lattice metric (max_delta=3 deg; the declared "
                           "class is triclinic/undecided)"
                           if space_group is not None
                           else "lattice metric (max_delta=3 deg)")
    centring, trs = EstimateResolution._infer_centring(raw.indices())
    g = sgtbx.space_group(laue)
    for t in trs:
        g.expand_ltr(sgtbx.tr_vec(t))
    cs = crystal.symmetry(unit_cell=raw.unit_cell(), space_group=g,
                          assert_is_compatible_unit_cell=False)
    data = raw.customized_copy(crystal_symmetry=cs, anomalous_flag=False)
    data = data.set_observation_type_xray_intensity().eliminate_sys_absent()
    merged = data.merge_equivalents()
    arr = merged.array()
    n_unique = int(arr.size())
    out.update({
        "merge_group": str(cs.space_group_info()),
        "merge_group_source": laue_source,
        "centring_inferred": centring,
        "n_unique": n_unique,
        "multiplicity": round(data.size() / n_unique, 2) if n_unique else None,
        "completeness": round(float(arr.completeness(d_max=float("inf"))), 3),
        "r_int": round(float(merged.r_int()), 4),
    })
    sum_i = float(flex.sum(arr.data()))
    out["r_sigma"] = (round(float(flex.sum(arr.sigmas())) / sum_i, 4)
                      if sum_i > 0 else None)
    out["i_over_sigma"] = round(float(flex.mean(arr.data() / arr.sigmas())), 2)
    # 'merged' has two readings a crystallographer keeps apart: no index
    # is repeated at all (vendor merged in P1 / Friedel pairs folded -
    # R_int in the Laue class then measures symmetry consistency only),
    # or already unique in the Laue class (R_int carries nothing)
    n_distinct = int(raw.merge_equivalents().array().size())
    out["p1_multiplicity"] = round(raw.size() / n_distinct, 2) if n_distinct else None
    if out["multiplicity"] is not None and out["multiplicity"] < 1.2:
        out["looks_merged"] = True
        out["merged_note"] = (f"multiplicity {out['multiplicity']} in "
                              f"{out['merge_group']}: already merged in "
                              "the Laue class - R_int carries no "
                              "information here")
    elif out["p1_multiplicity"] is not None and out["p1_multiplicity"] < 1.05:
        out["looks_merged"] = True
        out["merged_note"] = ("no repeated indices (merged in P1 / Friedel "
                              "pairs folded): R_int here measures Laue-"
                              "class consistency only, not counting "
                              "reproducibility")
    else:
        out["looks_merged"] = False
    try:
        arr.setup_binner(n_bins=max(1, min(n_bins, n_unique // 20 or 1)))
        binner = arr.binner()
        used = list(binner.range_used())
        if used:
            last = used[-1]
            s_dmax, s_dmin = binner.bin_d_range(last)
            comp_bins = arr.completeness(use_binning=True)
            shell = data.resolution_filter(d_max=s_dmax)
            sm = shell.merge_equivalents()
            sa = sm.array()
            out["outer_shell"] = {
                "d_max": round(float(s_dmax), 3),
                "d_min": round(float(s_dmin), 3),
                "n_unique": int(sa.size()),
                "completeness": round(float(comp_bins.data[last] or 0.0), 3),
                "r_int": round(float(sm.r_int()), 4),
                "i_over_sigma": (round(float(flex.mean(sa.data()
                                                        / sa.sigmas())), 2)
                                 if sa.size() else None),
            }
    except Exception as e:  # noqa: BLE001 - shell is a bonus, not the table
        out["outer_shell"] = {"error": f"{type(e).__name__}: {e}"}
    return out


def ins_cell_metadata(path: Path) -> dict[str, Any] | None:
    """Cell / wavelength / ZERR esds / LATT-SYMM space group from any SHELX
    ins/res, or None when it carries no CELL card.

    pa1 hex-l2-r1/r2, cage-l2-r1/r2 (4 failures): the agents asked for an
    atomless start (ins='-') because they distrusted the vendor start.ins's
    space group, and ingest answered 'no .p4p with a cell' - the cell was
    sitting in that very ins. The group is returned SEPARATELY as an
    unverified guess so the caller can disclose it without adopting it."""
    from ..io.shelx import parse_ins_metadata, space_group_from_latt_symm
    try:
        meta = parse_ins_metadata(path)
    except (OSError, ValueError, IndexError):
        return None
    if not meta.get("cell") or len(meta["cell"]) != 6:
        return None
    out: dict[str, Any] = {"cell": [float(x) for x in meta["cell"]],
                           "wavelength": meta.get("wavelength")}
    m = re.search(r"^[ \t]*ZERR[ \t]+\S+((?:[ \t]+[-\d.eE+]+){6})",
                  path.read_text(encoding="latin-1", errors="replace"),
                  re.M | re.I)
    if m:
        try:
            out["cell_esd"] = [float(x) for x in m.group(1).split()]
        except ValueError:
            pass
    if meta.get("latt") is not None:
        try:
            from cctbx import sgtbx
            g = space_group_from_latt_symm(meta["latt"], meta.get("symm") or [])
            out["space_group"] = g
            out["space_group_symbol"] = str(sgtbx.space_group_info(group=g))
        except Exception as e:  # noqa: BLE001 - malformed SYMM: no guess
            out["space_group_error"] = f"{type(e).__name__}: {e}"
    return out


def ins_elements_declared(path: Path) -> dict[str, Any] | None:
    """SFAC element list + UNIT counts an ins/res declares, disclosed as a
    GUESS - never fed back into the engine's own composition trust decision
    (that is composition_from_meta in io/shelx.py, which independently
    decides whether UNIT is credible via a cell-volume density check and
    silently drops it when not). ka1-org: run_shelxt failed 'no element
    list available' and Wilson stats said 'no model/composition' on a
    session whose start.ins plainly declared SFAC C H N O - correct engine
    behaviour (a UNIT 1 1 1 1 placeholder on an ~880 A^3 cell is not
    credible evidence) but nothing SAID a declaration existed to disclose
    and pass explicitly. This is that disclosure, element-agnostic and
    independent of composition_from_meta's verdict.

    Placeholder rule (syntactic, cell-independent - state it, do not hide
    it): every declared UNIT count is identical AND no greater than 20 -
    the shape of vendor cold-start templates (XPREP/SHELXT commonly write
    'UNIT 1 1 1 1' or '2 2 2 2') and of this tool's own generated atomless
    start (UNIT 20 20 20 20, see the gen_start branch above). A real
    formula can coincidentally look the same at low, equal per-element
    counts (e.g. a genuine 1:1 compound at Z=1) - this flag is a disclosed
    guess for the agent to judge in context, not a verdict, and 'note'
    below says so regardless of which way the guess falls."""
    from ..io.shelx import parse_ins_metadata
    try:
        meta = parse_ins_metadata(path)
    except (OSError, ValueError, IndexError):
        return None
    elements = meta.get("sfac") or []
    if not elements:
        return None
    unit = meta.get("unit") or []
    placeholder = (bool(unit) and len(unit) == len(elements)
                   and len({round(float(u), 6) for u in unit}) == 1
                   and float(unit[0]) <= 20.0)
    return {
        "elements": list(elements),
        "unit": [float(u) for u in unit],
        "unit_is_placeholder": placeholder,
        "source": f"{path.name} SFAC/UNIT",
        "note": "vendor/cold-start declaration, not evidence",
    }


def cif_od_cell(path: Path) -> list[float] | None:
    """Unit cell from a CrysAlisPro .cif_od (cell source of last resort for
    a candidate hkl that pairs with no ins/p4p)."""
    try:
        text = path.read_text(encoding="latin-1", errors="replace")
    except OSError:
        return None
    vals = []
    for tag in ("_cell_length_a", "_cell_length_b", "_cell_length_c",
                "_cell_angle_alpha", "_cell_angle_beta", "_cell_angle_gamma"):
        m = re.search(re.escape(tag) + r"\s+(-?\d*\.?\d+)", text)
        if not m:
            return None
        vals.append(float(m.group(1)))
    return vals


def _pair_by_stem(stem: str, names) -> str | None:
    """The candidate whose stem is a prefix of / prefixed by `stem`
    (CrysAlisPro writes name_autored.hkl next to name.cif_od)."""
    names = list(names)
    for n in names:
        if Path(n).stem == stem:
            return n
    for n in names:
        s = Path(n).stem
        if stem.startswith(s) or s.startswith(stem):
            return n
    return None


def _pick_vendor_file(hkl_name: str, pool: list[str],
                      cell_src: dict[str, Any] | None = None) -> str | None:
    """Which vendor sidecar (p4p / ._ls / .abs) belongs to the chosen hkl:
    the one pairing by stem, else the file the cell was taken from, else
    the directory's only one. Several unrelated ones = None (never guess
    a file that may describe another crystal)."""
    if not pool:
        return None
    hit = _pair_by_stem(Path(hkl_name).stem, pool)
    if hit:
        return hit
    if cell_src and cell_src.get("file") in pool:
        return str(cell_src["file"])
    if len(pool) == 1:
        return pool[0]
    return None


def candidate_cell_source(hkl_name: str, src: Path, inss: list[str],
                          p4ps: dict[str, dict], cif_ods: dict[str, Any],
                          explicit_cell=None,
                          prefer_p4p: bool = False) -> dict[str, Any] | None:
    """Where a candidate hkl's cell comes from: the ins/res, .p4p or
    .cif_od pairing with it by stem, else the directory's single one, else
    any with a CELL, else an explicit cell. prefer_p4p puts the .p4p ahead
    of a stem-paired ins (the generated-start path: SAINT's cell ESDs are
    the honest ZERR). Returns {'cell', 'file', 'kind', 'wavelength'?,
    'space_group'?, 'space_group_symbol'?, 'cell_esd'?} or None."""
    stem = Path(hkl_name).stem

    def _ins(name: str) -> dict[str, Any] | None:
        meta = ins_cell_metadata(src / name)
        if not meta:
            return None
        return {**meta, "file": name, "kind": "ins"}

    def _p4p(name: str) -> dict[str, Any] | None:
        v = p4ps.get(name) or {}
        if not v.get("cell"):
            return None
        return {"cell": v["cell"], "cell_esd": v.get("cell_esd"),
                "wavelength": v.get("wavelength"), "file": name,
                "kind": "p4p"}

    def _od(name: str) -> dict[str, Any] | None:
        c = cif_od_cell(src / name)
        return {"cell": c, "file": name, "kind": "cif_od"} if c else None

    paired = [(_ins, inss), (_p4p, list(p4ps)), (_od, list(cif_ods))]
    if prefer_p4p:
        paired = [paired[1], paired[0], paired[2]]
    for finder, pool in paired:
        hit = _pair_by_stem(stem, pool)
        if hit and (found := finder(hit)):
            return found
    for finder, pool in ((_p4p, list(p4ps)), (_ins, inss),
                         (_od, list(cif_ods))):
        if len(pool) == 1 and (found := finder(pool[0])):
            return {**found, "shared": True}
    for finder, pool in ((_ins, inss), (_p4p, list(p4ps))):
        for name in pool:
            if found := finder(name):
                return {**found, "shared": True}
    if explicit_cell:
        return {"cell": [float(x) for x in explicit_cell], "file": None,
                "kind": "explicit"}
    return None


def build_candidate_table(src: Path, hkls: dict[str, dict],
                          inss: list[str], p4ps: dict[str, dict],
                          cif_ods: dict[str, Any],
                          explicit_cell=None) -> dict[str, dict[str, Any]]:
    """One row per hkl candidate: format class, size/hashes, identical
    twins, cell + its source, and hkl_candidate_stats when a cell is
    known. What the pa1 cu agents reconstructed by shell for every run."""
    table: dict[str, dict[str, Any]] = {}
    for name, v in hkls.items():
        row: dict[str, Any] = {"format": v.get("format")}
        try:
            row.update(hkl_file_hashes(src / name))
        except OSError as e:
            row["hash_error"] = str(e)
        cs = candidate_cell_source(name, src, inss, p4ps, cif_ods,
                                   explicit_cell)
        if cs is None:
            row["cell"] = None
            row["cell_source"] = None
            row["stats"] = {"skipped": "no cell: no ins/res/p4p/cif_od "
                                       "pairs with this file and none is "
                                       "shared; pass cell=[...]"}
        else:
            row["cell"] = [round(float(x), 4) for x in cs["cell"]]
            row["cell_source"] = (
                f"{cs['kind']} {cs['file']}" + (" (shared, not stem-paired)"
                                                if cs.get("shared") else "")
                if cs.get("file") else "explicit cell= parameter")
            if cs.get("wavelength"):
                row["wavelength"] = cs["wavelength"]
            if cs.get("space_group_symbol"):
                row["space_group_guess"] = (
                    f"{cs['space_group_symbol']} (LATT/SYMM of {cs['file']}; "
                    "an unverified guess, not a decision)")
            row["stats"] = hkl_candidate_stats(src / name, cs["cell"],
                                               cs.get("space_group"))
        table[name] = row
    # identical twins: whole file, or reflection rows only (trailer differs)
    for name, row in table.items():
        same_file = [o for o, r in table.items()
                     if o != name and r.get("sha256")
                     and r.get("sha256") == row.get("sha256")]
        same_data = [o for o, r in table.items()
                     if o != name and o not in same_file
                     and r.get("data_sha256")
                     and r.get("data_sha256") == row.get("data_sha256")]
        if same_file:
            row["identical_file_to"] = same_file
        if same_data:
            row["same_reflections_as"] = same_data
            row["same_reflections_note"] = (
                "byte-identical reflection rows; the files differ only "
                "after the terminator (trailer text) - one dataset")
    return table


def candidate_table_lines(table: dict[str, dict[str, Any]]) -> list[str]:
    """One compact line per candidate for error messages."""
    lines = []
    for name, row in table.items():
        st = row.get("stats") or {}
        if st.get("n_unique"):
            outer = st.get("outer_shell") or {}
            parts = [f"{st['n_reflections']} refl",
                     f"{st['n_unique']} unique in {st['merge_group']}",
                     f"mult {st['multiplicity']}",
                     f"compl {st['completeness']}",
                     f"Rint {st['r_int']}", f"Rsigma {st['r_sigma']}",
                     f"<I/sig> {st['i_over_sigma']}"
                     + (f" (outer {outer['i_over_sigma']} at "
                        f"{outer['d_min']} A)"
                        if outer.get("i_over_sigma") is not None else ""),
                     f"d {st['d_max']}-{st['d_min']} A"]
            if st.get("looks_merged"):
                parts.append("looks MERGED")
            if st.get("hklf5_note"):
                parts.append("HKLF5")
        else:
            parts = [f"{row.get('n_rows', '?')} rows",
                     str((st or {}).get("skipped") or (st or {}).get("error")
                         or row.get("format"))]
        if row.get("identical_file_to"):
            parts.append("IDENTICAL FILE to "
                         + ", ".join(row["identical_file_to"]))
        if row.get("same_reflections_as"):
            parts.append("same reflections as "
                         + ", ".join(row["same_reflections_as"]))
        lines.append(f"{name}: " + "; ".join(parts))
    return lines


def symmetry_provenance(space_group_symbol: str | None, source: str,
                        confirmed: bool = False, **extra: Any) -> dict[str, Any]:
    """context.json `symmetry` block: what group the project currently
    declares, where it came from and whether anything has confirmed it.
    get_project_brief reads it; ingest writes it; a declaration tool that
    changes the group should overwrite it (change_space_group hook).
    Every key is always present so the deep-merging context writer
    replaces the block instead of keeping a stale ins_guess around.

    pa1 hex-l2-r2: the brief reported 'P 6/m m m' (the atomless model's
    stale symmetry) after the agent had declared R-3m, then 'R -3 m' after
    it had declared P-3m1 - the working group and its provenance were
    nowhere to be read."""
    block: dict[str, Any] = {
        "space_group": space_group_symbol, "source": source,
        "confirmed": bool(confirmed), "ins_guess": None, "cell_source": None,
        "recorded_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    block.update(extra)
    return block


class IngestVendorData(_FramesTool):
    name = "ingest_vendor_data"
    description = (
        "Cold-start the refinement project from vendor-software products "
        "(Bruker SAINT/TWINABS/XPREP, CrysAlisPro...) instead of raw "
        "frames: scans a directory for .p4p (cell/wavelength), SHELX .hkl "
        "and .ins/.res, copies the chosen pair into the project as "
        "crystal.hkl (+ start model; an atomless ins is generated from the "
        "p4p when none exists) and activates the session. SAINT ._ls "
        "listings are mined for cell-measurement provenance (used "
        "reflections, 2theta range, GooF-corrected cell ESDs) into "
        "context.json - this is what fills _cell_measurement_* in the final "
        "CIF (checkCIF PLAT183/184/185). Reports every candidate found - "
        "including HKLF5 twin files - so the choice is explicit and "
        "auditable: with several hkl files (or list_candidates=true) a "
        "candidate_table gives per file n reflections / unique / "
        "completeness / R_int / R_sigma / I-over-sigma (overall + outer "
        "shell) / resolution / merged-or-not / cell source / hashes, and "
        "flags files that carry the same reflection rows. ins='-' takes "
        "the cell from the .p4p or ANY .ins/.res in the directory (the "
        "ins's LATT/SYMM group is reported as an unverified guess, not "
        "adopted). Re-ingesting a file identical to the current "
        "crystal.hkl is refused unless force=true. Use when the "
        "practice/user data ships as reduced hkl rather than frames.")
    params_schema = {
        "type": "object",
        "properties": {
            "source_dir": {"type": "string",
                           "description": "directory to scan (absolute or "
                                          "project-relative)"},
            "hkl": {"type": "string",
                    "description": "explicit hkl file inside source_dir "
                                   "(default: the single validated "
                                   "candidate, or the one pairing with the "
                                   "chosen ins by stem)"},
            "ins": {"type": "string",
                    "description": "explicit ins/res start model (default: "
                                   "stem-pair of the hkl; '-' forces the "
                                   "generated atomless start)"},
            "list_candidates": {
                "type": "boolean", "default": False,
                "description": "only return the candidate_table (nothing "
                               "is copied or activated) - compare the hkl "
                               "files first, then call again with hkl="},
            "cell": {"type": "array", "items": {"type": "number"},
                     "minItems": 6, "maxItems": 6,
                     "description": "explicit [a, b, c, alpha, beta, gamma] "
                                    "for the generated start / candidate "
                                    "statistics when no .p4p/.ins carries "
                                    "one"},
            "wavelength": {"type": "number",
                           "description": "explicit wavelength (A) for the "
                                          "generated start when no vendor "
                                          "file carries one"},
            "force": {"type": "boolean", "default": False,
                      "description": "re-ingest even when the file is "
                                     "identical to the current crystal.hkl"},
        },
        "required": ["source_dir"],
    }

    def run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        import shutil
        src = Path(str(params["source_dir"]))
        if not src.is_absolute():
            src = self.project.dir / src
        if not src.is_dir():
            return ToolResult.failure(f"source_dir not found: {src}")

        hkls = {}
        for p in sorted(src.glob("*.hkl")):
            v = looks_like_shelx_hkl(p)
            if v.get("ok"):
                # the 30-line sniff misses files whose leading reflections
                # are all domain 1 (real TWINABS exports sort that way) -
                # a full-file count is authoritative and still cheap
                v["n_domains"] = hklf5_batch_count(p)
                v["hklf5_batches"] = v["n_domains"] >= 2
                v["scale_batches"] = (scale_batch_max(p)
                                      if not v["hklf5_batches"] else 0)
                hkls[p.name] = v
        p4ps = {p.name: parse_p4p(p) for p in sorted(src.glob("*.p4p"))}
        inss = [p.name for p in sorted(src.glob("*.ins"))
                + sorted(src.glob("*.res"))]
        # Bruker names these 'name._ls' - a bare '*.ls' glob never matches
        # that (the last three chars are '_ls'), which silently killed the
        # cell-measurement mining on real vendor dirs
        lss = {p.name: v
               for p in sorted(set(src.glob("*.ls")) | set(src.glob("*._ls")))
               if (v := parse_saint_ls(p))}
        abss = {p.name: v for p in sorted(src.glob("*.abs"))
                if (v := parse_sadabs_abs(p))}
        # CrysAlisPro writes its reduction record next to the hkl
        cif_ods = {p.name: v for p in sorted(src.glob("*.cif_od"))
                   if (v := parse_crysalis_cif_od(p))}
        for v in hkls.values():
            v["format"] = ("HKLF5-batched" if v["hklf5_batches"]
                           else (f"HKLF4-like + positive-only batch column "
                                 f"(1..{v['scale_batches']}; no negative "
                                 f"composite markers). Ambiguous by format: "
                                 f"scan/scale batches (plain SHELXL HKLF 4 "
                                 f"ignores them) OR a separated-domain twin "
                                 f"export - decide from vendor provenance "
                                 f"(TWINABS/.abs, integration logs), not "
                                 f"from the column alone"
                                 if v.get("scale_batches") else "HKLF4-like"))
        found = {"hkl_candidates": {k: v["format"] for k, v in hkls.items()},
                 "p4p": {k: {kk: vv for kk, vv in v.items()
                             if kk in ("cell", "wavelength", "space_group",
                                       "chem")}
                         for k, v in p4ps.items()},
                 "ins_res": inss,
                 "saint_ls": {k: {kk: vv for kk, vv in v.items()
                                  if kk != "cell"}
                              for k, v in lss.items()},
                 **({"absorption_abs": abss} if abss else {}),
                 **({"crysalis_cif_od": sorted(cif_ods)} if cif_ods else {})}
        if not hkls:
            return ToolResult(ok=False, summary=found,
                              error=f"no valid SHELX hkl found in {src}")

        explicit_cell = params.get("cell")
        if explicit_cell is not None:
            try:
                explicit_cell = [float(x) for x in explicit_cell]
                if len(explicit_cell) != 6:
                    raise ValueError("need 6 values")
            except (TypeError, ValueError) as e:
                return ToolResult(ok=False, summary=found,
                                  error=f"cell must be [a, b, c, alpha, "
                                        f"beta, gamma]: {e}")
        # Several reflection files = the numbers a crystallographer picks
        # on, per file, in ONE answer. pa1 cu: 'HKLF4-like' x3 sent seven
        # runs to the shell (hashes, line counts, head/tail, Compare-Object
        # hung 15 min) or into three successive ingests to compare a/b/c.
        list_only = bool(params.get("list_candidates"))
        if len(hkls) > 1 or list_only:
            found["candidate_table"] = build_candidate_table(
                src, hkls, inss, p4ps, cif_ods, explicit_cell)
            found["candidate_table_note"] = (
                "statistics merged in the Laue class of each file's cell "
                "source (LATT/SYMM guess, or the lattice metric when that "
                "is triclinic) with centring inferred from index parity; "
                "R_int/R_sigma/I-over-sigma compare the reductions, "
                "same_reflections_as marks one dataset under two names. "
                "Judge, then pass hkl=<name>.")
        if list_only:
            return ToolResult(ok=True, summary={
                **found, "no_state_change": True,
                "note": "listing only - nothing was copied or activated; "
                        "call again with hkl=<name> (and ins=) to ingest"})

        hkl_name = params.get("hkl")
        if hkl_name and hkl_name not in hkls:
            return ToolResult(ok=False, summary=found,
                              error=f"hkl {hkl_name!r} not among validated "
                                    f"candidates {sorted(hkls)}")
        if not hkl_name:
            plain = [k for k, v in hkls.items() if not v["hklf5_batches"]]
            if len(plain) == 1:
                hkl_name = plain[0]
            elif len(hkls) == 1:
                hkl_name = next(iter(hkls))
            else:
                lines = candidate_table_lines(found["candidate_table"])
                return ToolResult(ok=False, summary=found,
                                  error="several hkl candidates - pass "
                                        "hkl=<name> explicitly. Per file "
                                        "(full numbers in candidate_table): "
                                        + " | ".join(lines))

        ins_name = params.get("ins")
        stem = Path(hkl_name).stem
        if ins_name is None:
            for cand in (stem + ".res", stem + ".ins"):
                if cand in inss:
                    ins_name = cand
                    break
        gen_start = ins_name in (None, "-")

        # SAINT ._ls cell-measurement provenance (checkCIF PLAT183/184/185):
        # the ls pairing with the chosen hkl by stem wins, else the one with
        # the most reflections in its final cell least squares
        ls_pick = None
        if lss:
            ls_pick = ({Path(k).stem: v for k, v in lss.items()}.get(stem)
                       or max(lss.values(),
                              key=lambda v: v.get("reflns_used") or 0))

        # the HKLF code must follow the *chosen data*: an HKLF 4 start over
        # HKLF5-batched data makes SHELXL misread the batch column
        # (R1~0.65 artefacts, seen live on p770)
        n_domains = int(hkls[hkl_name].get("n_domains") or 0)
        chosen_is_hklf5 = n_domains >= 2

        # '-' / no ins: the cell must come from SOMEWHERE, decided before
        # any file is touched (a failure here used to leave a half-copied
        # crystal.hkl behind). pa1 hex-l2-r1/r2, cage-l2-r1/r2: 'no ins
        # given and no .p4p with a cell' x4 while start.ins carried it.
        cell_src: dict[str, Any] | None = None
        if gen_start:
            if explicit_cell is not None:
                cell_src = {"cell": explicit_cell, "file": None,
                            "kind": "explicit"}
            else:
                cell_src = candidate_cell_source(
                    hkl_name, src, inss, p4ps, cif_ods, None,
                    prefer_p4p=True)
            if cell_src is None:
                tried = [
                    f".p4p: {len(p4ps)} found"
                    + (", none with a CELL line" if p4ps else ""),
                    f".ins/.res: {len(inss)} found"
                    + (", none with a parsable CELL card" if inss else ""),
                    f".cif_od: {len(cif_ods)} CrysAlisPro record(s), no "
                    f"cell" if cif_ods else ".cif_od: none",
                    "cell= parameter: not given"]
                return ToolResult(ok=False, summary=found, error=(
                    f"no ins given and no cell source for a generated "
                    f"atomless start in {src} - tried " + "; ".join(tried)
                    + ". Pass cell=[a, b, c, alpha, beta, gamma] "
                      "(+ wavelength=), or put the vendor .p4p/.ins next "
                      "to the hkl."))

        # Same-file guard. hex-l2-r2 re-ingested the PROJECT directory to
        # drop placeholder atoms and hit WinError 32 (crystal.hkl copied
        # onto its open self); re-importing identical bytes under another
        # name (pa1 cu: crystal_b == crystal_c up to the trailer) only
        # rebuilds the import node and confuses the audit trail.
        dst = input_directory(self.project) / "crystal.hkl"
        current = self.project.dir / "crystal.hkl"
        src_file = src / hkl_name
        try:
            same_path = current.exists() and src_file.resolve() == current.resolve()
        except OSError:
            same_path = False
        if same_path:
            return ToolResult(ok=False, summary=found, error=(
                f"{hkl_name} IS this project's own crystal.hkl (source_dir "
                "is the project directory): re-ingesting the current file "
                "changes nothing and only risks a lock on the open file "
                "(WinError 32). To reset the session instead: checkout "
                "n0000 (the import node), or change_space_group("
                "space_group=...) on the atomless model; to ingest OTHER "
                "data pass the vendor directory as source_dir."))
        if dst.exists() and not params.get("force"):
            raw, previous = src_file.read_bytes(), dst.read_bytes()
            same_file = raw == previous
            def reflection_rows(data):
                rows = []
                for line in data.splitlines():
                    rows.append(line)
                    if _is_hkl_terminator(line.decode("latin-1")):
                        break
                return rows
            same_rows = reflection_rows(raw) == reflection_rows(previous)
            if same_file or same_rows:
                prior = (self.project.context.get("data") or {}).get(
                    "vendor_hkl")
                how = ("byte-identical to" if same_file else
                       "the same reflection rows as (only trailer text "
                       "differs from)")
                return ToolResult(ok=False, summary=found, error=(
                    f"{hkl_name} is {how} the already-ingested crystal.hkl"
                    + (f" (ingested from {prior})" if prior else "")
                    + ". Nothing "
                      "changes by re-ingesting it: pass hkl=<another "
                      "candidate>, or force=true to rebuild the start node "
                      "from the same data anyway (to drop placeholder "
                      "atoms, checkout n0000 does that without "
                      "re-ingesting)."))

        frozen_hkl = capture_source(self.project, src_file)
        shutil.copy2(frozen_hkl, dst)
        # The vendor's cell/orientation record (.p4p) rides with the data
        # from here on: it is one of the five files a crystallographer hands
        # over for manual continuation (res/cif/ins/hkl/p4p) and nothing
        # downstream can compute it. 2026-09-08 usertest: two sessions
        # hand-copied it from the vendor directory with the shell because
        # ingest read its cell and then forgot which file that was.
        vendor_p4p = _pick_vendor_file(hkl_name, list(p4ps), cell_src)
        vendor_ls = _pick_vendor_file(hkl_name, list(lss))
        vendor_abs = _pick_vendor_file(hkl_name, list(abss))
        for name in (vendor_p4p, vendor_ls, vendor_abs):
            if name:
                capture_source(self.project, src / name)
        start_name = "start.ins"
        hklf_mismatch = None
        if gen_start:
            cell = cell_src["cell"]
            esd = cell_src.get("cell_esd") or [0.001] * 6
            if ls_pick and ls_pick.get("cell") and ls_pick.get("cell_esd"):
                # GooF-corrected ESDs from the final cell LS are the honest
                # ZERR - but only when the ls cell matches the p4p cell
                drift = max(abs(a - b) / max(abs(b), 1e-6) for a, b in
                            zip(ls_pick["cell"][:3], cell[:3]))
                if drift < 0.005:
                    esd = ls_pick["cell_esd"]
            wl_explicit = params.get("wavelength")
            wl = float(wl_explicit or cell_src.get("wavelength") or 0.71073)
            cell_src["wavelength_used"] = wl
            cell_src["wavelength_source"] = (
                "wavelength= parameter" if wl_explicit
                else (f"{cell_src['kind']} {cell_src['file']}"
                      if cell_src.get("wavelength")
                      else "ASSUMED Mo Kalpha 0.71073 (no vendor file "
                           "carries a wavelength - set it if wrong)"))
            tail = "HKLF 4\nEND\n"
            if n_domains >= 2:
                # equal-fraction start; no TWIN card - HKLF 5 carries the
                # domain assignment itself
                tail = ("BASF "
                        + " ".join(f"{1.0 / n_domains:.4f}"
                                   for _ in range(n_domains - 1))
                        + "\nHKLF 5\nEND\n")
            (input_directory(self.project) / start_name).write_text(
                "TITL ingest_vendor_data atomless start\n"
                f"CELL {wl:.5f} "
                + " ".join(f"{x:.5f}" for x in cell) + "\n"
                "ZERR 1.00 " + " ".join(f"{x:.5f}" for x in esd) + "\n"
                "LATT 1\nSFAC C H N O\nUNIT 20 20 20 20\n" + tail,
                encoding="ascii")
        else:
            if ins_name not in inss:
                return ToolResult(ok=False, summary=found,
                                  error=f"ins {ins_name!r} not found in "
                                        f"{src}")
            frozen_model = capture_source(self.project, src / ins_name)
            shutil.copy2(frozen_model, input_directory(self.project) / start_name)
            m = re.search(r"^[ \t]*HKLF[ \t]+(\d)",
                          (src / ins_name).read_text(encoding="latin-1",
                                                     errors="replace"),
                          re.M | re.I)
            ins_code = int(m.group(1)) if m else None
            if chosen_is_hklf5 and ins_code == 4:
                hklf_mismatch = (
                    f"{ins_name} says HKLF 4 but {hkl_name} is "
                    "HKLF5-batched - SHELXL would misread the batch column; "
                    "fix the HKLF code (and add BASF) before refining")
            elif not chosen_is_hklf5 and ins_code == 5:
                hklf_mismatch = (
                    f"{ins_name} says HKLF 5 but {hkl_name} has no batch "
                    "column - change to HKLF 4 or ingest the twin file")

        # SFAC/UNIT the start.ins declares - disclosed as a guess for
        # run_shelxt / get_project_brief regardless of whether
        # composition_from_meta (io/shelx.py) trusted it as real evidence;
        # covers both branches above (generated placeholder and copied
        # vendor ins) since both have finished writing start_name by here
        ins_elements = ins_elements_declared(input_directory(self.project) / start_name)

        ctx_update: dict[str, Any] = {"data": {
            "hkl": "crystal.hkl", "start_model": start_name,
            "vendor_source": str(src),
            "vendor_hkl": hkl_name,
            "vendor_hkl_bytes": src_file.stat().st_size,
            "vendor_ins": None if gen_start else ins_name,
            "vendor_p4p": vendor_p4p,
            "vendor_ls": vendor_ls,
            "vendor_abs": vendor_abs,
            "ins_elements": ins_elements}}
        # symmetry provenance: what the project declares from here on and
        # where it came from - get_project_brief shows it (pa1 briefs
        # showed the vendor ins's P21/c / the placeholder P1 as plain
        # 'space_group' with no hint that nobody had verified them)
        cell_source_note = None
        if gen_start:
            cell_source_note = (
                f"{cell_src['kind']} {cell_src['file']}" if cell_src.get("file")
                else "explicit cell= parameter")
            guess = cell_src.get("space_group_symbol")
            sym_block = symmetry_provenance(
                "P -1", "generated atomless start (LATT 1 placeholder - a "
                        "merging convenience, not a decision; decide via "
                        "screen_space_groups + solution trials, then "
                        "change_space_group(space_group=...) declares it)",
                confirmed=False,
                ins_guess=({"file": cell_src["file"], "space_group": guess,
                            "note": "LATT/SYMM of that ins - the vendor's "
                                    "or a previous solver's guess, NOT "
                                    "adopted"} if guess else None),
                cell_source=cell_source_note)
        else:
            ins_meta = ins_cell_metadata(src / ins_name) or {}
            sym_block = symmetry_provenance(
                ins_meta.get("space_group_symbol"),
                f"vendor start model {ins_name} LATT/SYMM - the vendor's or "
                f"a previous solver's guess, unverified here",
                confirmed=False, cell_source=f"ins {ins_name}")
        ctx_update["symmetry"] = sym_block
        exp: dict[str, Any] = {}
        if ls_pick:
            cm = {k: ls_pick[k] for k in
                  ("reflns_used", "theta_min", "theta_max") if k in ls_pick}
            if cm:
                exp["cell_measurement"] = cm
            sw = ls_pick.get("software")
            if sw:
                # SAINT does cell refinement + reduction; data COLLECTION
                # software (APEX etc.) is not evidenced by the ls - leave it
                exp["computing"] = {"cell_refinement": sw,
                                    "data_reduction": sw}
        if cif_ods:
            # CrysAlisPro reduction record: the fullest vendor provenance
            # we get (temperature, source, diffractometer, absorption T
            # range, cell measurement). Pair by stem with the chosen hkl -
            # one experiment directory holds several reductions.
            od_pick = next(
                (v for k, v in cif_ods.items()
                 if Path(hkl_name).stem.startswith(Path(k).stem)
                 or Path(k).stem.startswith(Path(hkl_name).stem)), None) \
                or next(iter(cif_ods.values()))
            for key, val_ in od_pick.items():
                if isinstance(val_, dict) and isinstance(exp.get(key), dict):
                    exp[key] = {**val_, **exp[key]}   # keep SAINT specifics
                else:
                    exp.setdefault(key, val_)
        if abss:
            # SADABS/TWINABS listing = the honest absorption provenance
            # (fills _exptl_absorpt_* - checkCIF PLAT089 family); the abs
            # pairing with the chosen hkl by stem prefix wins
            abs_pick = next(
                (v for k, v in abss.items()
                 if Path(hkl_name).stem.startswith(Path(k).stem)), None) \
                or next(iter(abss.values()))
            exp["absorption"] = abs_pick
        trailer_abs = parse_hkl_trailer_cif(src / hkl_name)
        if trailer_abs and not exp.get("absorption"):
            # SADABS/XPREP trailer metadata: weaker provenance than a full
            # .abs listing but honest vendor record - and SHELXL will copy
            # it into ACTA output regardless, so record it visibly
            exp["absorption"] = {**trailer_abs,
                                 "provenance": "hkl trailer (SADABS/XPREP "
                                               "post-terminator CIF items)"}
        if exp:
            ctx_update["experiment"] = exp
        _update_context(self.project, ctx_update)
        reload_info = self.project.reload_inputs()
        summary = {**found,
                   "chosen": {"hkl": hkl_name,
                              "ins": ("(generated atomless)" if gen_start
                                      else ins_name),
                              "hkl_bytes": src_file.stat().st_size},
                   "node": reload_info.get("node"),
                   "merge": reload_info.get("merge"),
                   "n_atoms": reload_info.get("n_atoms"),
                   "symmetry": {k: sym_block[k] for k in
                                ("space_group", "source", "confirmed",
                                 "ins_guess") if sym_block.get(k) is not None},
                   "note": ("session active; space group and composition "
                            "in a generated start are placeholders - run "
                            "the space-group screen / audits before "
                            "solving"),
                   "no_state_change": True}
        if gen_start:
            summary["cell_source"] = {
                "cell": [round(float(x), 4) for x in cell_src["cell"]],
                "from": cell_source_note,
                "wavelength": cell_src["wavelength_used"],
                "wavelength_from": cell_src["wavelength_source"],
                **({"space_group_guess": cell_src["space_group_symbol"]}
                   if cell_src.get("space_group_symbol") else {})}
            if inss:
                # cage full arm: ingest_vendor_data(source_dir) with no
                # ins= generated a placeholder (SFAC C H N O UNIT 20 20 20
                # 20) while a real start.ins sat right there undeclared -
                # the agent never learned it existed until it shelled in to
                # read the directory by hand. Say so, by name, here.
                unused_preview = (ins_elements_declared(src / inss[0])
                                  if len(inss) == 1 else None)
                summary["ins_not_used"] = {
                    "files": inss,
                    "note": (
                        (f"{inss[0]} is present in {src} but was not used "
                         f"(no ins= was given, and its name does not pair "
                         f"with the chosen hkl {hkl_name!r} by filename "
                         f"stem). Pass ins={inss[0]!r} to start from it "
                         "instead of the generated placeholder"
                         + (f" - it declares SFAC "
                            f"{' '.join(unused_preview['elements'])}"
                            + (" (UNIT looks like a placeholder, not a "
                               "formula)" if unused_preview[
                                   "unit_is_placeholder"] else "")
                            if unused_preview else "") + ".")
                        if len(inss) == 1 else
                        (f"{len(inss)} ins/res files are present in {src} "
                         "but none was used (no ins= was given, and none "
                         f"pairs with the chosen hkl {hkl_name!r} by "
                         f"filename stem): {', '.join(inss)}. Pass "
                         "ins=<name> to start from one of them instead of "
                         "the generated placeholder."))}
        if trailer_abs:
            summary["hkl_trailer_metadata"] = {
                **trailer_abs,
                "note": ("absorption items found after the hkl terminator "
                         "(SADABS/XPREP convention). SHELXL copies these "
                         "into its CIF output - they are now recorded in "
                         "experiment context so your reports stay "
                         "consistent with the delivered CIF")}
        if n_domains >= 2:
            summary["hklf5"] = {
                "n_domains": n_domains,
                "note": (f"HKLF 5 twin data ({n_domains} domains): least "
                         "squares goes through run_shelxl (start.ins "
                         f"carries HKLF 5 + {n_domains - 1} equal BASF "
                         "fractions); the in-process view keeps batch>0 "
                         "rows only, so audits/charge flipping stay "
                         "approximate but safe. SHELXT cannot read HKLF5 "
                         "(verified: hard reject, and mislabelling it "
                         "HKLF 4 yields garbage solutions) - solve from "
                         "the vendor HKLF4 export instead, then re-ingest "
                         "this file for final refinement")}
        skipped5 = sorted(k for k, v in hkls.items()
                          if v.get("hklf5_batches") and k != hkl_name)
        if not chosen_is_hklf5 and skipped5:
            summary["twin_data_note"] = (
                f"HKLF5-batched candidate(s) present: {', '.join(skipped5)}"
                " - if refinement shows twin symptoms, re-ingest with "
                "hkl=<that file>")
        if hklf_mismatch:
            summary["hklf_mismatch"] = hklf_mismatch
        self.record_stage("ingest_vendor_data", {
            "hkl": hkl_name, "node": reload_info.get("node")})
        # reg8: the duplicate structure of the file is known the moment it
        # is imported - same maths as audit_reflection_data, reported here
        # so an HKLF5-export (composite rows, no batch column) is named on
        # ingest instead of three tools later
        try:
            ses_now = self.project.session
            raw_now = (ses_now.dataset.intensities
                       if ses_now is not None and ses_now.dataset is not None
                       else None)
            if raw_now is not None:
                from .tools_analysis import duplicate_consistency
                dup = duplicate_consistency(raw_now)
                summary["duplicates"] = {k: v for k, v in dup.items()
                                         if k != "hint"}
                if dup.get("reading"):
                    summary.setdefault("notes", [])
                    if isinstance(summary["notes"], list):
                        summary["notes"].append("HKLF5-export signature: "
                                                + dup["reading"])
        except Exception as e:  # noqa: BLE001 - a report, never a blocker
            summary["duplicates_note"] = f"not computed: {type(e).__name__}: {e}"
        return ToolResult(ok=True, summary=summary)


# --------------------------------------------------------------------------- #
# 7. export_twin_hklf5
# --------------------------------------------------------------------------- #

class ExportTwinHklf5(_FramesTool):
    name = "export_twin_hklf5"
    description = (
        "Non-merohedral twin exporter (the p770-validated pipeline): from a "
        "TWO-lattice indexing (indexed_all.expt, made by index_frames "
        "max_lattices=2 + keep_lattice), integrate BOTH domains, scale each "
        "domain separately, classify predicted-spot overlaps per sweep "
        "(coincident -> HKLF5 composite record / partial -> dropped or "
        "modelled per partial_policy / clean -> single-domain line), and "
        "write twin5.hkl (HKLF5) + twin_major_clean.hkl (overlap-cleansed "
        "HKLF4 of the major domain, for SOLVING - SHELXT/charge flipping "
        "reject HKLF5). minor_policy trades completeness vs R1 optics: "
        "'none' (best R1), 'coverage' (add minor-domain singles only for "
        "unique reflections nothing else measured - selection by hkl "
        "identity, statistically neutral), 'all' (max completeness, "
        "weakest optics). Measured accounting fact: SHELXL computes "
        "_diffrn_measured_fraction from batch-1 lines ONLY, so minor "
        "singles never move reported completeness; partial_policy="
        "'composite' is the lever that does (p770 E1: 0.58 -> 0.80, and "
        "0.99 after intensity='profile' rescaling, at ~0.005 R1 cost). "
        "Workflow: create_start_model(hkl_source='twin_major_clean.hkl') "
        "to solve, then swap_reflection_data to twin5.hkl and refine via "
        "run_shelxl (BASF refines the twin fraction; batch 3, if "
        "present, absorbs the minor domain's arbitrary scale; with "
        "partial_policy='composite' the refined BASF underestimates the "
        "twin fraction - the blob convention undercounts the minor tail "
        "- disclose that).")
    params_schema = {
        "type": "object",
        "properties": {
            "minor_policy": {
                "type": "string", "enum": ["none", "coverage", "all"],
                "default": "coverage",
                "description": "minor-domain singles policy (see tool "
                               "description for the tradeoff)"},
            "tight_xy": {"type": "number", "default": 2.0,
                         "description": "coincidence radius in px - "
                                        "predictions closer than this "
                                        "share one blob (composite)"},
            "tight_z": {"type": "number", "default": 1.0,
                        "description": "coincidence tolerance in frames"},
            "wide_xy": {"type": "number", "default": 6.0,
                        "description": "contamination radius in px - "
                                       "pairs between tight and wide are "
                                       "dropped as mutually contaminated"},
            "wide_z": {"type": "number", "default": 3.0,
                       "description": "contamination tolerance in frames"},
            "partial_policy": {
                "type": "string", "enum": ["drop", "composite"],
                "default": "drop",
                "description":
                    "partial-overlap handling. 'drop' discards the "
                    "tight..wide pairs as mutually contaminated (cleanest "
                    "R1 optics, but the loss is SYSTEMATIC in reciprocal "
                    "space - affected uniques never recover via "
                    "redundancy, so reported completeness can fall far "
                    "below what the frames actually measured). "
                    "'composite' pairs each partial with its nearest "
                    "counterpart and writes TWINABS-style composite "
                    "records carrying the major measurement as the blob "
                    "estimate - completeness recovers, R1 rises "
                    "slightly, refined BASF reads low (disclose)."},
            "intensity": {
                "type": "string", "enum": ["combine", "profile", "sum"],
                "default": "combine",
                "description":
                    "dials.scale intensity_choice for both domains. On "
                    "detectors with structured noise (or crowded twin "
                    "patterns) summation backgrounds can bias strongly "
                    "negative and the min_isigi guard then silently "
                    "excludes a large fraction of rows under 'combine' - "
                    "the signature is a big removed_sum_isigi with "
                    "near-zero removed_prf_isigi in this tool's "
                    "scaling_exclusions output; 'profile' rescues those "
                    "rows (p770: 4456 -> 485 excluded)."},
        },
    }

    def run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        all_e = self.workdir / "indexed_all.expt"
        all_r = self.workdir / "indexed_all.refl"
        if not all_e.exists() or not all_r.exists():
            return ToolResult.failure(
                "no indexed_all.expt/refl - this tool needs a multi-lattice "
                "indexing kept via index_frames(max_lattices=2, "
                "keep_lattice=<major>), which sets the twin domains aside "
                "in indexed_all.*")
        try:
            exp_json = json.loads(all_e.read_text())
        except (OSError, json.JSONDecodeError) as e:
            return ToolResult.failure(f"cannot read indexed_all.expt: {e}")
        xtal_of = [e.get("crystal") for e in exp_json.get("experiment", [])]
        n_xtal = len(exp_json.get("crystal") or [])
        if n_xtal != 2:
            return ToolResult.failure(
                f"indexed_all has {n_xtal} crystal model(s); this exporter "
                "handles exactly 2 twin domains (for 3+ component twins "
                "process the dominant pair or fall back to vendor "
                "TWINABS-style products)")
        try:
            env = self._dials_env()
        except fd.DialsProcessingError as e:
            return self._fail(e)

        # domain 0 of indexed_all = index_frames' lattice 0 = what
        # keep_lattice usually kept as the major domain; report both sizes
        rows_a = [i for i, c in enumerate(xtal_of) if c == 0]
        rows_b = [i for i, c in enumerate(xtal_of) if c == 1]

        # stage-boundary pings: the long stages have DIALS heartbeats, but
        # phase TRANSITIONS were invisible - r16-r18 agents blind-narrated
        # ~24 'still running' messages across 20+ min exports
        def _ping(msg: str) -> None:
            prog = getattr(ctx, "progress", None)
            if prog is not None:
                try:
                    prog(f"export_twin_hklf5 [stage] {msg}")
                except Exception:  # noqa: BLE001 - liveness best-effort
                    pass

        # 1. integrate both domains in one pass. The joint integration is
        # by far the most expensive step (r21: 48 min for 11 sweeps x 2
        # domains) and its inputs are exactly indexed_all.* - reuse a
        # previous run's products when they are newer than the indexing,
        # so a retry after a downstream packaging/scaling failure costs
        # minutes, not another integration.
        int_e = self.workdir / "twin_int.expt"
        int_r = self.workdir / "twin_int.refl"
        reused_integration = (
            int_e.exists() and int_r.exists()
            and int_e.stat().st_mtime > all_e.stat().st_mtime
            and int_r.stat().st_mtime > all_r.stat().st_mtime)
        if reused_integration:
            _ping("1/4 reusing cached joint integration (twin_int.* newer "
                  "than indexing)")
        else:
            _ping(f"1/4 joint integration of both domains "
                  f"({len(rows_a)}+{len(rows_b)} sweeps) - the expensive "
                  f"step (r21 scale: tens of minutes)")
            r_int = self._runner(env, "integrate")
            try:
                r_int.run("integrate", "dials.integrate",
                          ["indexed_all.expt", "indexed_all.refl",
                           f"nproc={_NPROC}",
                           "output.experiments=twin_int.expt",
                           "output.reflections=twin_int.refl",
                           "output.log=twin_integrate.log"],
                          progress=getattr(ctx, "progress", None))
            except fd.DialsProcessingError as e:
                return self._fail(e)

        # 2. split integrated rows, regroup per crystal
        _ping("2/4 splitting integrated rows per domain")
        r_exp = self._runner(env, "export")
        try:
            r_exp.run("export", "dials.split_experiments",
                      ["twin_int.expt", "twin_int.refl",
                       "output.experiments_prefix=twin_split",
                       "output.reflections_prefix=twin_split"])
        except fd.DialsProcessingError as e:
            return self._fail(e)

        # integration can drop whole experiments (rare); regroup by the
        # SURVIVING experiment->crystal map of twin_int.expt
        try:
            int_json = json.loads((self.workdir / "twin_int.expt").read_text())
            int_xtal = [e.get("crystal")
                        for e in int_json.get("experiment", [])]
        except (OSError, json.JSONDecodeError) as e:
            return ToolResult.failure(f"cannot read twin_int.expt: {e}")
        groups = {0: [i for i, c in enumerate(int_xtal) if c == 0],
                  1: [i for i, c in enumerate(int_xtal) if c == 1]}
        if not groups[0] or not groups[1]:
            return ToolResult.failure(
                "one twin domain vanished during integration "
                f"(experiment crystals: {int_xtal}) - check "
                "twin_integrate.log")
        for dom, tag in ((0, "A"), (1, "B")):
            pairs = [_dials_split_pair(self.workdir, "twin_split", i)
                     for i in groups[dom]]
            if not all(a.exists() for a, _ in pairs):
                return ToolResult.failure(
                    "dials.split_experiments output missing for domain "
                    f"{tag} "
                    f"({_split_outputs_present(self.workdir, 'twin_split')}; "
                    "check logs/export.log)")
            if len(pairs) == 1:
                shutil.copy(pairs[0][0], self.workdir / f"twin_dom{tag}.expt")
                shutil.copy(pairs[0][1], self.workdir / f"twin_dom{tag}.refl")
            else:
                args2: list[str] = []
                for a, b in pairs:
                    args2 += [a.name, b.name]
                args2 += [f"output.experiments=twin_dom{tag}.expt",
                          f"output.reflections=twin_dom{tag}.refl"]
                try:
                    r_exp.run("export", "dials.combine_experiments", args2)
                except fd.DialsProcessingError as e:
                    return self._fail(e)

        # 3. scale each domain separately (the multi-crystal scaler is
        # unnecessary; per-domain arbitrary scales are absorbed by the
        # HKLF5 batch scale factors downstream)
        intensity = str(params.get("intensity") or "combine")
        scale_stats: dict[str, Any] = {}
        scale_excl: dict[str, Any] = {}
        for tag in ("A", "B"):
            _ping(f"3/4 scaling domain {tag}")
            r_sc = self._runner(env, "scale")
            args_sc = [f"twin_dom{tag}.expt", f"twin_dom{tag}.refl",
                       f"nproc={_NPROC}",
                       f"output.experiments=twin_scaled{tag}.expt",
                       f"output.reflections=twin_scaled{tag}.refl",
                       f"output.log=twin_scale{tag}.log"]
            if intensity != "combine":
                args_sc.append(f"intensity_choice={intensity}")
            try:
                out = r_sc.run("scale", "dials.scale", args_sc,
                               progress=getattr(ctx, "progress", None))
            except fd.DialsProcessingError as e:
                return self._fail(e)
            scale_stats[f"domain_{tag}"] = fd._parse_scale_stats(out)
            try:
                log_t = (self.workdir
                         / f"twin_scale{tag}.log").read_text(errors="replace")
                scale_excl[f"domain_{tag}"] = fd._parse_scale_exclusions(
                    log_t)
            except OSError:
                pass

        # 4. classification + HKLF5 composition via the writer script in
        # the DIALS env (reflection tables live there)
        _ping("4/4 overlap classification + HKLF5 composition")
        cell, hall = fd._cell_from_expt(self.workdir / "twin_domA.expt")
        if not cell:
            return ToolResult.failure("cannot read domain-A cell")
        writer = Path(fd.__file__).resolve().parent / "hklf5_writer.py"
        argv = [str(self.workdir),
                f"{float(params.get('tight_xy') or 2.0):g}",
                f"{float(params.get('tight_z') or 1.0):g}",
                f"{float(params.get('wide_xy') or 6.0):g}",
                f"{float(params.get('wide_z') or 3.0):g}",
                str(params.get("minor_policy") or "coverage"),
                ",".join(f"{v:.5f}" for v in cell),
                f"hall: {hall}" if hall else "P 1",
                str(params.get("partial_policy") or "drop")]
        code = ("import runpy, sys; "
                f"sys.argv = [r'{writer}'] + {argv!r}; "
                f"runpy.run_path(r'{writer}', run_name='__main__')")
        r_wr = self._runner(env, "export")
        out_wr = r_wr.run_pycode("twin_write", code, timeout=900.0)
        report_p = self.workdir / "twin5_report.json"
        if out_wr is None or not report_p.exists():
            return ToolResult.failure(
                "HKLF5 writer failed (see logs/twin_write.log)")
        try:
            census = json.loads(report_p.read_text())
        except (OSError, json.JSONDecodeError) as e:
            return ToolResult.failure(f"unreadable twin5_report.json: {e}")

        summary: dict[str, Any] = {
            "files": {"twin5_hkl": str(self.workdir / "twin5.hkl"),
                      "major_clean_hkl":
                          str(self.workdir / "twin_major_clean.hkl"),
                      "report": str(report_p)},
            "n_experiments": {"domain_A": len(rows_a),
                              "domain_B": len(rows_b)},
            "reused_integration": reused_integration,
            "overlap_census": census,
            "scaling": scale_stats,
            "scaling_exclusions": scale_excl,
            "basf_start_hint": 0.25,
            "workflow_note": (
                "solve from the CLEAN major-domain data: "
                "create_start_model(hkl_source='twin_major_clean.hkl'); "
                "after the model stands, swap_reflection_data(hkl="
                "'twin5.hkl', ...) and refine with run_shelxl - BASF 1 "
                "then IS the measured twin fraction"
                + (", BASF 2 absorbs the minor domain's arbitrary scale "
                   "(not a physical fraction - say so in the report)"
                   if census.get("n_batches") == 3 else "")),
            "disclosure_note": (
                f"{census.get('major_partial_dropped', 0)} major-domain + "
                f"{census.get('minor_partial_dropped', 0)} minor-domain "
                "observations were dropped as mutually contaminated "
                "partial overlaps"
                + (f"; {census.get('pc_composites', 0)} partial pairs "
                   "were written as composite records (blob=major "
                   "measurement - refined BASF will underestimate the "
                   "twin fraction, disclose)"
                   if census.get("pc_composites") else "")
                + " - disclose this data-reduction decision and the "
                  "minor_policy/partial_policy choices in the final "
                  "report"),
            "completeness_note": (
                "SHELXL's _diffrn_measured_fraction counts batch-1 lines "
                "only: minor-domain singles do not move it, partial "
                "composites do. If scaling_exclusions shows a large "
                "removed_sum_isigi with near-zero removed_prf_isigi, "
                "the summation backgrounds are biased (structured noise/"
                "crowded patterns) and rerunning this tool with "
                "intensity='profile' typically rescues those rows."),
        }
        self.record_stage("export_twin_hklf5", summary)
        summary["no_state_change"] = True
        return ToolResult(ok=True, summary=summary,
                          artifacts={"twin5_hkl":
                                     str(self.workdir / "twin5.hkl"),
                                     "log": self._log("twin_write")})
