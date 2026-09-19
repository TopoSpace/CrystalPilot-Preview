"""DIALS-backed raw diffraction frame processing (spot finding -> indexing ->
integration -> scaling -> export).

CrystalPilot's own engine works on reduced reflection data; this adapter turns raw
detector frames (CBF, Bruker .sfrm, ...) into scaled reflections by driving a separate
DIALS installation headlessly via subprocess. DIALS is NOT imported into CrystalPilot's
venv: it lives in its own conda env (or official installer tree) whose location is
auto-discovered or passed explicitly.

Public API
----------
- find_dials(dials_env=None) -> DialsEnv        locate a DIALS installation
- detect_frames(paths) -> dict                  classify frame files into scan/bg/mask runs
- read_sfrm_header(path) -> dict                parse a Bruker .sfrm header (80-char records)
- process_frames(frame_source, workdir, ...)    run the full DIALS chain, return summary
- DialsProcessingError                          stage-tagged failure with actionable message

Standalone demo:  python -m crystalpilot.io.frames_dials <frames...> [--workdir D]
                  [--p4p file.p4p] [--dials-env PREFIX]
(no pipeline/server integration here by design).
"""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..procutil import NO_WINDOW

__all__ = [
    "DialsEnv", "DialsProcessingError", "find_dials", "detect_frames",
    "ensure_format_plugins", "read_sfrm_header", "parse_p4p_cell",
    "process_frames",
]

# --------------------------------------------------------------------------- #
# DIALS environment discovery
# --------------------------------------------------------------------------- #

_ENV_VAR = "CRYSTALPILOT_DIALS_ENV"


@dataclass
class DialsEnv:
    """A usable DIALS installation: conda env prefix or DIALS installer tree."""
    prefix: Path
    python: Path
    dispatcher_dirs: list[Path] = field(default_factory=list)
    version: str | None = None

    def dispatcher(self, name: str) -> Path | None:
        """Find e.g. 'dials.import' as .exe/.bat/.cmd/bare in this env."""
        exts = (".exe", ".bat", ".cmd", "") if os.name == "nt" else ("",)
        for d in self.dispatcher_dirs:
            for ext in exts:
                cand = d / f"{name}{ext}"
                if cand.is_file():
                    return cand
        return None

    def subprocess_env(self) -> dict:
        """Environment mimicking 'conda activate <prefix>' (DLL paths on Windows).

        Built from a MINIMAL base instead of os.environ.copy(): when the
        parent is a long-lived service process, inherited entries (stale
        PATH members, host-app injections) have frozen the child's DLL
        loader for tens of minutes (python.exe stuck at 16 modules, 0 CPU,
        Wait/Executive - observed r9 on dials.find_spots). Everything a
        conda python + DIALS dispatcher needs is whitelisted here.
        """
        keep = ("SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP",
                "USERPROFILE", "APPDATA", "LOCALAPPDATA", "PROGRAMDATA",
                "HOMEDRIVE", "HOMEPATH", "USERNAME", "COMPUTERNAME",
                "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE",
                "SYSTEMDRIVE", "ALLUSERSPROFILE", "PUBLIC", "OS",
                "PYTHONUTF8", "HOME", "LANG", "LC_ALL", "SSL_CERT_FILE",
                "REQUESTS_CA_BUNDLE")
        env = {k: v for k, v in os.environ.items() if k.upper() in keep}
        env.setdefault("PYTHONUTF8", "1")
        extra = [self.prefix, self.prefix / "Library" / "mingw-w64" / "bin",
                 self.prefix / "Library" / "usr" / "bin",
                 self.prefix / "Library" / "bin", self.prefix / "Scripts",
                 self.prefix / "bin"]
        if os.name == "nt":
            root = os.environ.get("SystemRoot") or os.environ.get("SYSTEMROOT") \
                or r"C:\Windows"
            system = [root + r"\System32", root,
                      root + r"\System32\Wbem",
                      root + r"\System32\WindowsPowerShell\v1.0"]
        else:
            system = os.defpath.split(os.pathsep)
        env["PATH"] = os.pathsep.join(
            [str(p) for p in extra if p.is_dir()] + system)
        # a real 'conda activate' also exports these; some conda packages
        # locate resources (plugins, share/ data) via CONDA_PREFIX - the
        # W(CO)6 agent diagnosed a large find_spots slowdown without it
        env["CONDA_PREFIX"] = str(self.prefix)
        env.setdefault("CONDA_DEFAULT_ENV", self.prefix.name)
        return env


def _candidate_prefixes() -> list[Path]:
    home = Path.home()
    roots = [home / n for n in ("miniforge3", "mambaforge", "miniconda3", "anaconda3")]
    roots += [Path(r"C:\miniforge3"), Path(r"C:\miniconda3")]
    cands: list[Path] = [Path(__file__).resolve().parents[2] / "vendor" / "dials"]
    for root in roots:
        for env_name in ("dials", "dials-env"):
            cands.append(root / "envs" / env_name)
        cands.append(root)                       # dials installed into base
    # official DIALS installers unpack a conda env under the install dir
    for pf in (Path(r"C:\Program Files"), home / "AppData" / "Local", home, Path("/opt"),
               Path("/usr/local")):
        if pf.is_dir():
            cands.extend(p / "conda_base" for p in pf.glob("dials-*"))
            cands.extend(p for p in pf.glob("dials-*") if (p / "python.exe").exists())
    return cands


# CrystalPilot-maintained dxtbx format plugins (crystalpilot/io/dxtbx_plugin):
# stock dxtbx has no Format class for Rigaku HyPix miniCBF as written by
# CrysAlisPro (header_convention "RIGAKU_1.x"), so dials.import rejects such
# frames outright. Bump the version here AND in the plugin pyproject/__init__
# to trigger a reinstall in already-provisioned DIALS envs.
_PLUGIN_VERSION = "0.2.0"
_plugin_ok_prefixes: set[str] = set()


def ensure_format_plugins(env: DialsEnv, timeout: float = 600.0) -> dict:
    """Install/refresh CrystalPilot's dxtbx format plugins inside a DIALS env.

    Idempotent, cached per env prefix for the process lifetime. Returns
    {'ok': bool, ...}; failures are reported rather than raised - only Rigaku
    HPAD frames need the plugin, everything else reads fine without it.
    """
    key = str(env.prefix)
    if key in _plugin_ok_prefixes:
        return {"ok": True, "cached": True}
    plugin_dir = Path(__file__).resolve().parent / "dxtbx_plugin"
    if not (plugin_dir / "pyproject.toml").is_file():
        return {"ok": False, "error": f"plugin source missing: {plugin_dir}"}

    probe_code = "import crystalpilot_dxtbx_rigaku as m; print(m.__version__)"

    def _probe() -> str | None:
        try:
            p = subprocess.run([str(env.python), "-c", probe_code],
                               stdin=subprocess.DEVNULL,
                               capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=120,
                               env=env.subprocess_env(),
                               creationflags=NO_WINDOW)
            if p.returncode == 0 and p.stdout.strip():
                return p.stdout.strip().splitlines()[-1]
        except Exception:  # noqa: BLE001 - probe is best-effort
            pass
        return None

    result: dict = {"ok": True, "version": _PLUGIN_VERSION}
    if _probe() != _PLUGIN_VERSION:
        try:
            p = subprocess.run(
                [str(env.python), "-m", "pip", "install", "--no-deps",
                 "--force-reinstall", "--quiet", str(plugin_dir)],
                stdin=subprocess.DEVNULL,
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=timeout, env=env.subprocess_env(),
                creationflags=NO_WINDOW)
        except Exception as exc:  # noqa: BLE001 - subprocess/timeout errors
            return {"ok": False, "error": f"pip install failed: {exc}"}
        if p.returncode != 0:
            tail = "\n".join((p.stderr or p.stdout or "").splitlines()[-5:])
            return {"ok": False, "error": f"pip install failed: {tail}"}
        if _probe() != _PLUGIN_VERSION:
            return {"ok": False, "error": "plugin installed but import probe failed"}
        result["installed"] = True
    _plugin_ok_prefixes.add(key)
    return result


def find_dials(dials_env: str | Path | None = None) -> DialsEnv:
    """Locate DIALS. Order: explicit arg > $CRYSTALPILOT_DIALS_ENV > common prefixes.

    Raises DialsProcessingError('discover', ...) when nothing usable is found.
    """
    tried: list[str] = []
    cands: list[Path] = []
    if dials_env:
        cands.append(Path(dials_env))
    elif os.environ.get(_ENV_VAR):
        cands.append(Path(os.environ[_ENV_VAR]))
    else:
        cands = _candidate_prefixes()

    for prefix in cands:
        if not prefix.is_dir():
            tried.append(str(prefix))
            continue
        python = None
        for rel in ("python.exe", "bin/python", "python"):
            if (prefix / rel).is_file():
                python = prefix / rel
                break
        ddirs = [d for d in (prefix / "Scripts", prefix / "Library" / "bin",
                             prefix / "bin", prefix) if d.is_dir()]
        env = DialsEnv(prefix=prefix, python=python or prefix, dispatcher_dirs=ddirs)
        if python is not None and env.dispatcher("dials.import") is not None:
            return env
        tried.append(str(prefix))

    raise DialsProcessingError(
        stage="discover",
        message="No DIALS installation found.",
        hint=("Install DIALS into its own conda env, e.g.\n"
              "  conda create -n dials -c conda-forge dials\n"
              f"then pass dials_env=<prefix> or set {_ENV_VAR}=<prefix>.\n"
              f"Locations tried: {tried[:8]}{' ...' if len(tried) > 8 else ''}"))


# --------------------------------------------------------------------------- #
# Bruker .sfrm header parsing + frame classification
# --------------------------------------------------------------------------- #

def read_sfrm_header(path: str | Path) -> dict:
    """Parse a Bruker frame header: HDRBLKS x 512 bytes of 80-char 'KEY :value' records.

    Repeated keys (TITLE, ...) are joined with newlines. Returns {} on non-sfrm files.
    """
    path = Path(path)
    with open(path, "rb") as fh:
        block = fh.read(512)
        if not block.startswith(b"FORMAT"):
            return {}
        m = re.search(rb"HDRBLKS:\s*(\d+)", block)
        nblocks = int(m.group(1)) if m else 15
        header = block + fh.read(nblocks * 512 - len(block))
    fields: dict[str, str] = {}
    for i in range(0, len(header) - 79, 80):
        rec = header[i:i + 80].decode("latin-1")
        key, sep, value = rec[:7], rec[7:8], rec[8:]
        if sep != ":":
            continue
        key, value = key.strip(), value.strip()
        if not key:
            continue
        fields[key] = f"{fields[key]}\n{value}" if key in fields else value
    return fields


_SCAN_EXTS = {".cbf", ".img", ".h5", ".nxs", ".osc", ".mccd", ".mar2300", ".cbf.gz",
              # Rigaku Oxford Diffraction family (CrysAlisPro exports)
              ".odeiger", ".rodhypix", ".rod_img", ".esperanto",
              # Bruker Nonius KappaCCD
              ".kcd"}
_RUN_RE = re.compile(r"^(?P<base>.+?)[._](?P<run>\d+)[._](?P<frame>\d+)$")


def _classify_sfrm(path: Path) -> tuple[str, dict]:
    hdr = read_sfrm_header(path)
    if not hdr:
        return "other", hdr
    ftype = hdr.get("TYPE", "").upper()
    if "MASK" in ftype:
        return "mask", hdr
    if "BACKGROUND" in ftype or "DARK" in ftype:
        return "background", hdr
    return "scan", hdr


def detect_frames(paths) -> dict:
    """Classify an arbitrary set of files into diffraction frame categories.

    Returns dict with:
      scan / background / mask / other : sorted lists of paths (str)
      runs        : {run_label: [scan frame paths]} grouped by filename pattern
      notes       : human-readable warnings (e.g. 'no scan frames found')
      sfrm_meta   : header snippets for the first frame of each category
    """
    out = {"scan": [], "background": [], "mask": [], "other": [],
           "runs": {}, "notes": [], "sfrm_meta": {}}
    for p in sorted(Path(p) for p in paths):
        if p.is_dir():
            continue
        suffix = p.suffix.lower()
        if suffix == ".sfrm":
            kind, hdr = _classify_sfrm(p)
            out[kind].append(str(p))
            if kind not in out["sfrm_meta"] and hdr:
                out["sfrm_meta"][kind] = {
                    k: hdr.get(k) for k in
                    ("TYPE", "DETTYPE", "MODEL", "NFRAMES", "ANGLES", "AXIS",
                     "WAVELEN", "DISTANC", "NROWS", "NCOLS", "CREATED")
                    if hdr.get(k)}
        elif suffix in _SCAN_EXTS or p.name.lower().endswith(".cbf.gz"):
            out["scan"].append(str(p))
        else:
            out["other"].append(str(p))

    for f in out["scan"]:
        m = _RUN_RE.match(Path(f).stem)
        label = f"{m.group('base')}_{m.group('run')}" if m else Path(f).stem
        out["runs"].setdefault(label, []).append(f)

    if not out["scan"]:
        if out["mask"] or out["background"]:
            out["notes"].append(
                "Only detector masks / background measurements found (Bruker TYPE "
                "'ACTIVE MASK' / '... BACKGROUND'): these are calibration frames, not "
                "diffraction data. The actual scan frames (TYPE 'SCAN ...', usually "
                "hundreds per run) were not among the given paths - they often stay "
                "on the instrument PC (check the FILENAM header field).")
        else:
            out["notes"].append("No recognisable diffraction frames found.")
    return out


def parse_p4p_cell(path: str | Path) -> tuple | None:
    """CELL a b c alpha beta gamma [volume] from a Bruker/SAINT .p4p file."""
    for line in Path(path).read_text(encoding="latin-1", errors="replace").splitlines():
        if line.upper().startswith("CELL"):
            vals = [float(x) for x in line.split()[1:7]]
            if len(vals) == 6:
                return tuple(vals)
    return None


# --------------------------------------------------------------------------- #
# Pipeline driver
# --------------------------------------------------------------------------- #

def _frame_templates(frames) -> list[str] | None:
    """Collapse frame paths into dials 'template=' patterns (trailing frame number
    -> #### marks), one per (directory, prefix, digit-count, extension) group.
    Returns None when any file has no trailing number in its stem."""
    groups: dict[tuple, int] = {}
    for f in frames:
        p = Path(f)
        m = re.match(r"^(?P<prefix>.*?)(?P<num>\d+)$", p.stem)
        if not m:
            return None
        key = (str(p.parent), m.group("prefix"), len(m.group("num")), p.suffix)
        groups[key] = groups.get(key, 0) + 1
    return [str(Path(d) / f"{prefix}{'#' * nd}{ext}")
            for (d, prefix, nd, ext) in sorted(groups)]


class DialsProcessingError(RuntimeError):
    """Failure in one stage of the DIALS chain, with an actionable message."""

    def __init__(self, stage: str, message: str, hint: str = "",
                 log_path: str | None = None, partial: dict | None = None):
        self.stage, self.hint, self.log_path = stage, hint, log_path
        self.partial = partial or {}
        text = f"[{stage}] {message}"
        if hint:
            text += f"\n  -> {hint}"
        if log_path:
            text += f"\n  log: {log_path}"
        super().__init__(text)


_STAGE_HINTS = {
    "import": ("dxtbx does not understand these images. For Bruker .sfrm check that the "
               "frames are data scans (TYPE 'SCAN'), not masks/backgrounds, and that the "
               "DIALS env is recent enough to ship FormatBrukerModern (dxtbx >= 3.17). "
               "Rigaku HyPix miniCBF needs CrystalPilot's bundled plugin (installed "
               "automatically; see format_plugin_warning in the summary if that failed). "
               "Other custom Format classes can be registered via the dxtbx entry point "
               "'dxtbx.format' or by placing them in ~/.dxtbx."),
    "find_spots": ("No/too few strong spots. Weak data or wrong detector gain: try "
                   "sigma_strong=2, gain=1, or a d_max/d_min window."),
    "index": ("Indexing failed. Ladder (validated on a noise-flooded Bruker CCD twin): "
              "1) strongest_n=8000 - CCD spot lists often carry several times more "
              "noise blobs than physically possible reflections, which starves the FFT "
              "peak search (compare n_strong_spots against a rough physical estimate: "
              "a few hundred spots per frame is already suspicious for a small cell); "
              "2) known unit_cell=/space_group= from a .p4p; 3) max_lattices=2 for "
              "twins/split crystals; 4) fft3d_rmsd_cutoff=3 when the second lattice or "
              "a sparse cloud still fails; 5) method=real_space_grid_search (needs the "
              "known cell) or fft1d."),
    "refine": "Geometry refinement failed; inspect the rmsd table in the log.",
    "integrate": "Integration failed; check profile model warnings in the log.",
    "symmetry": "Symmetry determination failed (often too few reflections).",
    "scale": "Scaling failed; try scaling the integrated (unsymmetrized) data.",
    "export": "Export failed; for SHELX export a composition string may be required.",
}


def _cell_from_expt(expt_path: Path) -> tuple[tuple, str] | tuple[None, None]:
    """(cell, hall_symbol) of the first crystal in a DIALS .expt JSON, no cctbx needed."""
    try:
        data = json.loads(expt_path.read_text())
        cryst = data["crystal"][0]
        va, vb, vc = (cryst[f"real_space_{k}"] for k in "abc")
    except (OSError, KeyError, IndexError, json.JSONDecodeError):
        return None, None
    norm = lambda v: math.sqrt(sum(x * x for x in v))
    ang = lambda u, v: math.degrees(math.acos(
        sum(a * b for a, b in zip(u, v)) / (norm(u) * norm(v))))
    cell = (norm(va), norm(vb), norm(vc), ang(vb, vc), ang(va, vc), ang(va, vb))
    return cell, cryst.get("space_group_hall_symbol")


def _kill_tree(popen: "subprocess.Popen") -> None:
    """Terminate a process and all its descendants (Windows: taskkill /T)."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(popen.pid)],
                           capture_output=True, timeout=30,
                           creationflags=NO_WINDOW)
        else:
            popen.kill()
    except Exception:  # noqa: BLE001 - last-resort cleanup
        try:
            popen.kill()
        except Exception:  # noqa: BLE001
            pass


def _use_wmi_relay() -> bool:
    """The WMI relay was built for a freeze that turned out to be stdin.

    The r9 "conda python froze in the DLL loader for tens of minutes"
    symptom is the MCP stdio transport's pending synchronous read on the
    stdin pipe the child inherits: python.exe probes stdin at start-up and
    blocks until the next JSON-RPC message arrives (the superflip root
    cause, 2026-09-02). Measured under an MCP-shaped parent: the DIALS
    conda python with inherited stdin hung 180 s (timeout); with
    stdin=DEVNULL it imported dials/dxtbx in 3.2 s and dials.version ran
    in 0.7 s. Every spawn here passes DEVNULL, so the direct path is the
    default; CRYSTALPILOT_DIALS_WMI=1 re-enables the relay if a machine
    ever shows a different freeze (CRYSTALPILOT_DIALS_DIRECT is accepted
    as a no-op for old launch configs)."""
    return os.name == "nt" and bool(os.environ.get("CRYSTALPILOT_DIALS_WMI"))


class _Runner:
    def __init__(self, env: DialsEnv, workdir: Path, timeout: float):
        self.env, self.workdir, self.timeout = env, workdir, timeout
        self.log_dir = workdir / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def _communicate_with_heartbeat(self, popen, stage, program, progress,
                                    t0, log_path, partial,
                                    interval: float = 10.0):
        """communicate() with reader threads + periodic progress calls."""
        import threading

        chunks: dict[str, list[str]] = {"out": [], "err": []}
        last_line = [""]

        def _reader(pipe, key):
            for line in iter(pipe.readline, ""):
                chunks[key].append(line)
                s = line.strip()
                if s:
                    last_line[0] = s
            pipe.close()

        threads = [
            threading.Thread(target=_reader, args=(popen.stdout, "out"),
                             daemon=True),
            threading.Thread(target=_reader, args=(popen.stderr, "err"),
                             daemon=True),
        ]
        for th in threads:
            th.start()
        while True:
            try:
                popen.wait(timeout=interval)
                break
            except subprocess.TimeoutExpired:
                elapsed = time.time() - t0
                if elapsed >= self.timeout:
                    _kill_tree(popen)
                    popen.wait()
                    for th in threads:
                        th.join(timeout=5)
                    log_path.write_text("".join(chunks["out"]) + "\n"
                                        + "".join(chunks["err"]),
                                        encoding="utf-8")
                    raise DialsProcessingError(
                        stage, f"{program} timed out after "
                               f"{self.timeout:.0f}s",
                        hint=_STAGE_HINTS.get(stage, ""),
                        log_path=str(log_path), partial=partial)
                try:
                    progress(f"[{stage}] {elapsed:.0f}s elapsed - "
                             f"{last_line[0] or 'working'}")
                except Exception:  # noqa: BLE001 - heartbeat is best-effort
                    pass
        for th in threads:
            th.join(timeout=10)
        return "".join(chunks["out"]), "".join(chunks["err"])

    def _run_wmi(self, stage: str, program: str, exe: Path, args: list[str],
                 partial: dict | None, progress, log_path: Path) -> str:
        """Windows: launch via WMI Win32_Process.Create so the child's
        ancestry is WmiPrvSE, not this service.

        conda-python children spawned anywhere under the host-app-embedded
        service froze in the DLL loader for tens of minutes (0 CPU, ~17
        modules, initial thread Wait/Executive) regardless of environment
        sanitisation, job breakaway or a cmd relay - while the identical
        command from any independently-parented shell ran in seconds. WMI
        creation runs with the caller's token but a clean system lineage,
        which is the one topology verified to work. Output round-trips via
        files; exit code needs cmd /v delayed expansion (a plain
        %errorlevel% in a one-liner expands before execution, always 0).
        """
        import base64
        import uuid
        wd = self.workdir.resolve()   # WMI needs an ABSOLUTE CurrentDirectory
        # unique suffix per invocation: with a FIXED name, a stale driver
        # (or a concurrent one) polling the same stage consumes/deletes the
        # rc file and the other poller waits for the full stage timeout
        tag = uuid.uuid4().hex[:8]
        out_f = wd / f".{stage}.{tag}.wmi.out"
        err_f = wd / f".{stage}.{tag}.wmi.err"
        rc_f = wd / f".{stage}.{tag}.wmi.rc"
        for f in (out_f, err_f, rc_f):
            try:
                f.unlink()
            except OSError:
                pass
        env = self.env.subprocess_env()
        sets = " && ".join(
            f'set "{k}={env[k]}"'
            for k in ("PATH", "CONDA_PREFIX", "CONDA_DEFAULT_ENV",
                      "PYTHONUTF8", "TEMP", "TMP")
            if env.get(k))
        inner = subprocess.list2cmdline([str(exe)] + args)
        # relative redirection targets: quoted absolute paths inside the
        # /s /c quoted block break cmd's quote stripping (verified - the
        # redirected file is never created); cwd is the workdir anyway
        cmdline = (f'cmd /d /s /v:on /c "{sets} && {inner} > {out_f.name} '
                   f'2> {err_f.name} & echo !errorlevel! > {rc_f.name}"')
        # ShowWindow=0 (SW_HIDE): WMI-created console processes otherwise
        # open a visible console window on the interactive desktop - one
        # flashing black box per DIALS stage (user report, r11)
        ps = ("$si = New-CimInstance -ClassName Win32_ProcessStartup "
              "-ClientOnly -Property @{ ShowWindow = [UInt16]0 }; "
              "$r = Invoke-CimMethod -ClassName Win32_Process -MethodName "
              "Create -Arguments @{ CommandLine = @'\n" + cmdline
              + "\n'@; CurrentDirectory = '" + str(wd) + "'; "
              "ProcessStartupInformation = $si }; "
              "Write-Output $r.ReturnValue; Write-Output $r.ProcessId")
        encoded = base64.b64encode(ps.encode("utf-16-le")).decode()
        t0 = time.time()
        try:
            create = subprocess.run(
                ["powershell", "-NoProfile", "-EncodedCommand", encoded],
                capture_output=True, text=True, timeout=120,
                encoding="utf-8", errors="replace",
                creationflags=NO_WINDOW)
        except subprocess.TimeoutExpired:
            raise DialsProcessingError(
                stage, f"WMI launcher for {program} timed out",
                hint=_STAGE_HINTS.get(stage, ""), partial=partial)
        vals = [v.strip() for v in (create.stdout or "").split() if v.strip()]
        if len(vals) < 2 or vals[0] != "0":
            raise DialsProcessingError(
                stage, f"WMI create failed for {program}: "
                       f"rv={vals[:1] or '?'} {create.stderr[:200]}",
                hint=_STAGE_HINTS.get(stage, ""), partial=partial)
        pid = int(vals[1])
        # WMI children break away from our process tree (parent WmiPrvSE)
        # and do NOT inherit the seeded affinity cap - re-apply per PID
        try:
            from ..procutil import limit_cpu
            limit_cpu(pid)
        except Exception:  # noqa: BLE001 - cap is best-effort
            pass

        def _tail() -> str:
            try:
                text = out_f.read_text(encoding="utf-8", errors="replace")
                lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
                return lines[-1] if lines else ""
            except OSError:
                return ""

        interval = 10.0
        while not rc_f.exists():
            elapsed = time.time() - t0
            if elapsed >= self.timeout:
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)],
                               capture_output=True, timeout=30,
                               creationflags=NO_WINDOW)
                out = (out_f.read_text(encoding="utf-8", errors="replace")
                       if out_f.exists() else "")
                log_path.write_text(out, encoding="utf-8")
                raise DialsProcessingError(
                    stage, f"{program} timed out after {self.timeout:.0f}s",
                    hint=_STAGE_HINTS.get(stage, ""),
                    log_path=str(log_path), partial=partial)
            if progress is not None:
                try:
                    progress(f"[{stage}] {elapsed:.0f}s elapsed - "
                             f"{_tail() or 'working'}")
                except Exception:  # noqa: BLE001 - heartbeat is best-effort
                    pass
            time.sleep(interval if elapsed > 30 else 2.0)
        time.sleep(0.5)   # let the redirections flush
        stdout = out_f.read_text(encoding="utf-8", errors="replace") \
            if out_f.exists() else ""
        stderr = err_f.read_text(encoding="utf-8", errors="replace") \
            if err_f.exists() else ""
        try:
            rc = int(rc_f.read_text().strip() or "1")
        except (OSError, ValueError):
            rc = 1
        for f in (out_f, err_f, rc_f):
            try:
                f.unlink()
            except OSError:
                pass
        out = stdout + "\n--- stderr ---\n" + stderr
        log_path.write_text(out, encoding="utf-8")
        if rc != 0:
            tail = "\n".join(out.strip().splitlines()[-12:])
            raise DialsProcessingError(
                stage, f"{program} exited with code {rc} "
                       f"({time.time() - t0:.0f}s).\n--- log tail ---\n{tail}",
                hint=_STAGE_HINTS.get(stage, ""), log_path=str(log_path),
                partial=partial)
        return out

    def run(self, stage: str, program: str, args: list[str],
            partial: dict | None = None, progress=None) -> str:
        """progress: optional callable(str) heartbeat - called every ~10 s
        with elapsed time + the subprocess's last output line, so the
        agent can SEE that a slow stage is alive (find_spots on a loaded
        machine was mistaken for a hang and its subprocess force-killed
        from a shell - the observed failure mode this prevents)."""
        exe = self.env.dispatcher(program)
        if exe is None:
            raise DialsProcessingError(stage, f"{program} not found in {self.env.prefix}",
                                       hint=_STAGE_HINTS.get(stage, ""), partial=partial)
        log_path = self.log_dir / f"{stage}.log"
        if _use_wmi_relay():
            return self._run_wmi(stage, program, exe, args, partial, progress,
                                 log_path)
        t0 = time.time()
        # Popen + tree-kill: dials.*.exe is a wrapper around a child python;
        # subprocess.run's timeout kills only the wrapper and leaves the
        # child working/holding file locks (observed on Windows).
        popen = subprocess.Popen(
            [str(exe)] + args, cwd=str(self.workdir),
            env=self.env.subprocess_env(), stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
        if progress is None:
            try:
                stdout, stderr = popen.communicate(timeout=self.timeout)
            except subprocess.TimeoutExpired:
                _kill_tree(popen)
                stdout, stderr = popen.communicate()
                log_path.write_text(str(stdout or "") + "\n" + str(stderr or ""),
                                    encoding="utf-8")
                raise DialsProcessingError(
                    stage, f"{program} timed out after {self.timeout:.0f}s",
                    hint=_STAGE_HINTS.get(stage, ""), log_path=str(log_path), partial=partial)
        else:
            stdout, stderr = self._communicate_with_heartbeat(
                popen, stage, program, progress, t0, log_path, partial)
        proc = subprocess.CompletedProcess(popen.args, popen.returncode,
                                           stdout, stderr)
        out = (proc.stdout or "") + "\n--- stderr ---\n" + (proc.stderr or "")
        log_path.write_text(out, encoding="utf-8")
        if proc.returncode != 0:
            tail = "\n".join(out.strip().splitlines()[-12:])
            raise DialsProcessingError(
                stage, f"{program} exited with code {proc.returncode} "
                       f"({time.time() - t0:.0f}s).\n--- log tail ---\n{tail}",
                hint=_STAGE_HINTS.get(stage, ""), log_path=str(log_path), partial=partial)
        return out

    def run_pycode(self, stage: str, code: str, timeout: float = 300.0) -> str | None:
        """Run a SINGLE-LINE python snippet in the DIALS env, return stdout.

        Direct spawn with stdin=DEVNULL (see _use_wmi_relay for why that is
        enough); the legacy WMI relay stays available behind
        CRYSTALPILOT_DIALS_WMI=1. The snippet must be one line so it also
        survives the cmd relay. Returns None on any failure (callers treat
        it as best-effort).
        """
        try:
            if _use_wmi_relay():
                saved = self.timeout
                try:
                    self.timeout = timeout
                    out = self._run_wmi(
                        stage, "python", self.env.python,
                        ["-c", code], partial=None, progress=None,
                        log_path=self.log_dir / f"{stage}.log")
                finally:
                    self.timeout = saved
                return out.split("--- stderr ---")[0]
            proc = subprocess.run([str(self.env.python), "-c", code],
                                  stdin=subprocess.DEVNULL,
                                  capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", timeout=timeout,
                                  env=self.env.subprocess_env(),
                                  creationflags=NO_WINDOW)
            return proc.stdout
        except Exception:
            return None

    def refl_count(self, refl: Path, flag: str | None = None) -> int | None:
        """Count reflections (optionally with a named flag) using the DIALS env python."""
        code = ("from dials.array_family import flex; "
                f"t = flex.reflection_table.from_file(r'{refl}'); "
                + (f"t = t.select(t.get_flags(t.flags.{flag})); " if flag else "")
                + "print(len(t))")
        out = self.run_pycode("refl_count", code)
        try:
            return int(out.strip().splitlines()[-1])
        except (AttributeError, ValueError, IndexError):
            return None


def _parse_scale_stats(log: str) -> dict:
    stats = {}
    pats = {"r_merge": r"Rmerge\(I\)\s+([\d.]+)",
            "r_meas": r"Rmeas\(I\)\s+([\d.]+)",
            "r_pim": r"Rpim\(I\)\s+([\d.]+)",
            "cc_half": r"CC half\s+([\d.]+)",
            "i_over_sigma": r"Mean\(I\)/sd\(I\)\s+([\d.]+)",
            "completeness": r"Completeness\s+([\d.]+)",
            "n_unique": r"Total unique\s+(\d+)",
            "n_observations": r"Total observations\s+(\d+)",
            "d_min": r"High resolution limit\s+([\d.]+)"}
    for key, pat in pats.items():
        m = re.search(pat, log)
        if m:
            stats[key] = float(m.group(1)) if "." in m.group(1) else int(m.group(1))
    return stats


def _parse_scale_exclusions(log: str) -> dict:
    """Census of dials.scale's silent pre-scaling filters.

    Sums the per-dataset "Removed N intensity.sum.value ..." /
    "Removed N intensity.prf.value ..." / partiality lines and the
    "Excluding N/M reflections" totals. A large sum-value removal count
    with near-zero prf removals is the signature of summation
    backgrounds biased negative (structured CCD noise, or crowded twin
    patterns) - the data usually survives rescaling with
    intensity_choice=profile (p770 E1 experiment, 2026-08-31: 4456/18037
    rows excluded under combine vs 485 under profile; delivered
    completeness 0.579 -> 0.99 with the partial-composite writer).
    """
    out = {"excluded_rows": 0, "total_rows": 0,
           "removed_sum_isigi": 0, "removed_prf_isigi": 0,
           "removed_partiality": 0}
    for n, d in re.findall(r"Excluding (\d+)/(\d+) reflections", log):
        out["excluded_rows"] += int(n)
        out["total_rows"] += int(d)
    for n in re.findall(
            r"Removed (\d+) intensity\.sum\.value reflections", log):
        out["removed_sum_isigi"] += int(n)
    for n in re.findall(
            r"Removed (\d+) intensity\.prf\.value reflections", log):
        out["removed_prf_isigi"] += int(n)
    for n in re.findall(
            r"Removed (\d+) reflections below partiality", log):
        out["removed_partiality"] += int(n)
    return out


def process_frames(frame_source, workdir: str | Path,
                   dials_env: str | Path | DialsEnv | None = None, *,
                   known_cell: tuple | None = None, known_space_group: str | None = None,
                   d_min: float | None = None, run_symmetry: bool = True,
                   composition: str = "CH", nproc: int = 4,
                   stage_timeout: float = 3600.0) -> dict:
    """Run dials.import -> find_spots -> index -> refine -> integrate -> [symmetry]
    -> scale -> export (SHELX .hkl/.ins and .mtz) on raw frames.

    frame_source : directory, glob-able template, or explicit list of frame files.
    workdir      : where DIALS output + logs/<stage>.log land (created).
    dials_env    : DialsEnv, a conda-env prefix path, or None to auto-discover.
    known_cell / known_space_group : optional priors (e.g. from a .p4p) passed to
        dials.index; leave None for ab initio.
    Returns a summary dict (see keys below); raises DialsProcessingError with the
    failed stage, a log path and a hint otherwise. Partial results survive in
    exc.partial.
    """
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    env = dials_env if isinstance(dials_env, DialsEnv) else find_dials(dials_env)
    plug = ensure_format_plugins(env)
    if not plug.get("ok"):
        summary_plugin_warning = plug.get("error")
    else:
        summary_plugin_warning = None

    # resolve frame list
    if isinstance(frame_source, (str, Path)):
        src = Path(frame_source)
        frames = sorted(str(p) for p in src.iterdir()
                        if p.suffix.lower() in _SCAN_EXTS | {".sfrm"}) \
            if src.is_dir() else [str(src)]
    else:
        frames = [str(f) for f in frame_source]
    if not frames:
        raise DialsProcessingError("import", "No frame files supplied.",
                                   hint="Pass a directory or list of image files.")

    summary: dict = {"workdir": str(workdir), "dials_env": str(env.prefix),
                     "n_input_files": len(frames)}
    if summary_plugin_warning:
        summary["format_plugin_warning"] = summary_plugin_warning
    r = _Runner(env, workdir, stage_timeout)

    # -- import ------------------------------------------------------------ #
    import_args = list(frames)
    if sum(len(f) + 3 for f in import_args) > 25000:
        # Windows 32 KiB command-line limit: collapse each run into a
        # 'template=prefix_####.ext' argument (one sweep per template).
        # Unpadded frame numbers (1,10,100 …) fragment into several digit
        # widths that dials templates cannot express; import the whole
        # directory instead when the frame list is exactly its scan content.
        templates = _frame_templates(frames)
        widths: dict[tuple, set[int]] = {}
        for f in frames:
            mm = re.match(r"^(?P<prefix>.*?)(?P<num>\d+)$", Path(f).stem)
            if mm:
                key = (str(Path(f).parent), mm.group("prefix"), Path(f).suffix)
                widths.setdefault(key, set()).add(len(mm.group("num")))
        unpadded = any(len(w) > 1 for w in widths.values())
        if templates is None or unpadded:
            # Unpadded frame numbers (1,10,100 …) cannot be expressed as
            # dials templates, and this dials build neither globs nor accepts
            # directory= reliably on Windows. Normalise via a hardlink dir
            # with zero-padded names (same volume: free; else copies).
            link_dir = workdir / "frames_normalized"
            link_dir.mkdir(parents=True, exist_ok=True)
            import shutil
            for f in frames:
                p = Path(f)
                mm = re.match(r"^(?P<prefix>.*?)(?P<num>\d+)$", p.stem)
                if not mm:
                    raise DialsProcessingError(
                        "import", f"frame {p.name} has no trailing frame "
                        "number; cannot normalise for template import.",
                        partial=summary)
                dest = link_dir / f"{mm.group('prefix')}{int(mm.group('num')):05d}{p.suffix}"
                if not dest.exists():
                    try:
                        os.link(p, dest)
                    except OSError:
                        shutil.copy2(p, dest)
            frames = sorted(str(q) for q in link_dir.iterdir())
            templates = _frame_templates(frames)
            summary["frames_normalized_dir"] = str(link_dir)
        summary["import_templates"] = templates
        import_args = [f"template={t}" for t in templates]
    out = r.run("import", "dials.import", import_args, partial=summary)
    m = re.search(r"num images:\s*(\d+)", out)
    summary["n_images"] = int(m.group(1)) if m else None
    m = re.search(r"sweep:\s*(\d+)", out)
    summary["n_sweeps"] = int(m.group(1)) if m else None
    if not (workdir / "imported.expt").exists():
        raise DialsProcessingError("import", "dials.import produced no imported.expt",
                                   hint=_STAGE_HINTS["import"],
                                   log_path=str(r.log_dir / "import.log"), partial=summary)

    # -- find spots --------------------------------------------------------- #
    args = ["imported.expt", f"nproc={nproc}"]
    if d_min:
        args.append(f"spotfinder.filter.d_min={d_min}")
    out = r.run("find_spots", "dials.find_spots", args, partial=summary)
    n_strong = r.refl_count(workdir / "strong.refl")
    if n_strong is None:
        m = re.search(r"Saved (\d+) reflections", out)
        n_strong = int(m.group(1)) if m else None
    summary["n_strong_spots"] = n_strong
    if not n_strong:
        raise DialsProcessingError("find_spots", "No strong spots found.",
                                   hint=_STAGE_HINTS["find_spots"],
                                   log_path=str(r.log_dir / "find_spots.log"),
                                   partial=summary)

    # -- index --------------------------------------------------------------- #
    args = ["imported.expt", "strong.refl"]
    if (summary.get("n_sweeps") or 0) > 1:
        # multiple sweeps of ONE crystal (the normal home-lab multi-run strategy)
        args.append("joint_indexing=True")
    if known_cell:
        args.append("unit_cell=" + ",".join(f"{v:g}" for v in known_cell))
    if known_space_group:
        args.append(f"space_group={known_space_group}")
    r.run("index", "dials.index", args, partial=summary)
    cell, hall = _cell_from_expt(workdir / "indexed.expt")
    n_indexed = r.refl_count(workdir / "indexed.refl", flag="indexed")
    summary.update(cell=cell, hall_symbol=hall, n_indexed=n_indexed)
    if n_strong and n_indexed:
        summary["pct_indexed"] = round(100.0 * n_indexed / n_strong, 1)

    # -- refine -------------------------------------------------------------- #
    out = r.run("refine", "dials.refine", ["indexed.expt", "indexed.refl"],
                partial=summary)
    rows = re.findall(r"^\|\s*\d+\s*\|\s*\d+\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|"
                      r"\s*([\d.]+)\s*\|", out, re.M)
    if rows:
        summary["rmsd"] = {"x_px": float(rows[-1][0]), "y_px": float(rows[-1][1]),
                           "phi_deg": float(rows[-1][2])}
    cell, hall = _cell_from_expt(workdir / "refined.expt")
    summary.update(cell=cell or summary.get("cell"),
                   hall_symbol=hall or summary.get("hall_symbol"))

    # -- integrate ----------------------------------------------------------- #
    r.run("integrate", "dials.integrate",
          ["refined.expt", "refined.refl", f"nproc={nproc}"], partial=summary)
    summary["n_integrated"] = r.refl_count(workdir / "integrated.refl", flag="integrated")

    # -- symmetry (optional, tolerate failure) ------------------------------- #
    scale_in = ("integrated.refl", "integrated.expt")
    if run_symmetry:
        try:
            out = r.run("symmetry", "dials.symmetry",
                        ["integrated.refl", "integrated.expt"], partial=summary)
            m = re.search(r"Recommended space group:\s*(.+)", out)
            if m:
                summary["space_group_suggestion"] = m.group(1).strip()
            if (workdir / "symmetrized.refl").exists():
                scale_in = ("symmetrized.refl", "symmetrized.expt")
        except DialsProcessingError as e:
            summary["symmetry_warning"] = str(e).splitlines()[0]

    # -- scale --------------------------------------------------------------- #
    out = r.run("scale", "dials.scale", list(scale_in), partial=summary)
    summary["scaling"] = _parse_scale_stats(out)
    cell, hall = _cell_from_expt(workdir / "scaled.expt")
    summary.update(cell=cell or summary.get("cell"),
                   hall_symbol=hall or summary.get("hall_symbol"))

    # -- export -------------------------------------------------------------- #
    r.run("export", "dials.export",
          ["scaled.refl", "scaled.expt", "format=shelx", "shelx.hklout=dials.hkl",
           "shelx.ins=dials.ins", f"composition={composition}"], partial=summary)
    exports = {"shelx_hkl": workdir / "dials.hkl", "shelx_ins": workdir / "dials.ins"}
    try:
        r.run("export", "dials.export",
              ["scaled.refl", "scaled.expt", "format=mtz", "mtz.hklout=scaled.mtz"],
              partial=summary)
        exports["mtz"] = workdir / "scaled.mtz"
    except DialsProcessingError as e:      # mtz is a bonus, don't fail the run
        summary["mtz_warning"] = str(e).splitlines()[0]
    missing = [k for k, p in exports.items() if not p.exists()]
    if "shelx_hkl" in missing:
        raise DialsProcessingError("export", "SHELX hkl was not written.",
                                   hint=_STAGE_HINTS["export"],
                                   log_path=str(r.log_dir / "export.log"), partial=summary)
    summary["exports"] = {k: str(p) for k, p in exports.items() if p.exists()}
    return summary


# --------------------------------------------------------------------------- #
# demo / smoke test
# --------------------------------------------------------------------------- #

def _main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(
        description="CrystalPilot DIALS frame-processing demo (standalone)")
    ap.add_argument("frames", nargs="+",
                    help="frame files, or a directory containing them")
    ap.add_argument("--workdir", default="workdir/dials/processed")
    ap.add_argument("--dials-env", default=None, help="DIALS conda env prefix")
    ap.add_argument("--p4p", default=None,
                    help=".p4p whose CELL is compared with the indexed cell")
    ap.add_argument("--cell", default=None, help="known cell a,b,c,al,be,ga for indexing")
    ap.add_argument("--space-group", default=None)
    ap.add_argument("--composition", default="CH")
    ap.add_argument("--classify-only", action="store_true")
    args = ap.parse_args(argv)

    paths: list[Path] = []
    for f in args.frames:
        p = Path(f)
        paths.extend(sorted(p.iterdir())) if p.is_dir() else paths.append(p)
    det = detect_frames(paths)
    print(f"detect_frames: {len(det['scan'])} scan / {len(det['background'])} background"
          f" / {len(det['mask'])} mask / {len(det['other'])} other; "
          f"runs: {list(det['runs'])}")
    for note in det["notes"]:
        print("NOTE:", note)
    if args.classify_only or not det["scan"]:
        return 0 if det["scan"] or args.classify_only else 1

    known_cell = tuple(float(x) for x in args.cell.split(",")) if args.cell else None
    try:
        summary = process_frames(det["scan"], args.workdir, args.dials_env,
                                 known_cell=known_cell,
                                 known_space_group=args.space_group,
                                 composition=args.composition)
    except DialsProcessingError as e:
        print("FAILED:", e)
        if e.partial:
            print("partial summary:", json.dumps(e.partial, indent=2, default=str))
        return 1

    print(json.dumps(summary, indent=2, default=str))
    if args.p4p:
        ref = parse_p4p_cell(args.p4p)
        got = summary.get("cell")
        if ref and got:
            print("\ncell vs p4p reference:")
            for name, a, b in zip("a b c alpha beta gamma".split(), got, ref):
                print(f"  {name:>5}: dials={a:9.4f}  p4p={b:9.4f}  d={a - b:+.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
