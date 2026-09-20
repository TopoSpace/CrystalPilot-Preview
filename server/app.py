"""CrystalPilot local server: the UI's backend.

Local-first: data never leaves this machine except the structured summaries the
engine itself sends to the configured LLM. Runs execute in worker threads; the UI
follows progress by polling the run's event log (robust across threads/restarts).
"""
from __future__ import annotations

import json
import shutil
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import mimetypes

from fastapi import FastAPI, File, HTTPException, UploadFile

# Windows registry can map .js to text/plain, which breaks ES module loading.
# init() must run FIRST: it re-reads the registry and would clobber add_type.
mimetypes.init()
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("image/svg+xml", ".svg")
mimetypes.add_type("font/woff2", ".woff2")
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = ROOT / "runs"
UPLOADS_DIR = ROOT / "workdir" / "uploads"
UI_DIST = ROOT / "ui" / "dist"

app = FastAPI(title="CrystalPilot", version="0.1.0")

# ---------------------------------------------------------------------------
# Local security boundary. This is a personal, local-first tool bound to
# loopback, but a browser is a confused deputy: any web page the user visits
# can fire requests at http://localhost:<port>. Two checks close that:
#   1. Host must be loopback (kills DNS-rebinding, where Host: evil.com
#      resolves to 127.0.0.1);
#   2. if the browser attached an Origin, it must be one of ours (kills
#      cross-site calls from arbitrary pages, including "simple" POSTs that
#      CORS alone would still deliver).
# CORS itself is an allowlist instead of "*" so foreign pages cannot read
# responses either.
# ---------------------------------------------------------------------------
_ALLOWED_ORIGINS = tuple(
    f"{scheme}://{host}"
    for scheme in ("http",)
    for host in ("localhost", "127.0.0.1", "[::1]")
) + ("http://localhost:5173", "http://127.0.0.1:5173")   # vite dev


def _origin_ok(origin: str) -> bool:
    o = origin.rstrip("/")
    return any(o == a or o.startswith(a + ":") for a in _ALLOWED_ORIGINS)


@app.middleware("http")
async def _interface_language(request, call_next):
    """Bind the browser's interface language for the duration of the request."""
    from crystalpilot.workbench import i18n as wb_i18n

    token = wb_i18n.bind(request.headers.get(wb_i18n.HEADER) or request.query_params.get("lang"))
    try:
        return await call_next(request)
    finally:
        wb_i18n.reset(token)


@app.middleware("http")
async def _local_guard(request, call_next):
    host = (request.headers.get("host") or "").split(":", 1)[0].lower()
    if host not in ("localhost", "127.0.0.1", "[::1]", "::1"):
        return PlainTextResponse("forbidden host", status_code=403)
    origin = request.headers.get("origin")
    if origin and not _origin_ok(origin):
        return PlainTextResponse("forbidden origin", status_code=403)
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=list(_ALLOWED_ORIGINS)
    + [f"http://localhost:{p}" for p in (8000, 8010, 5173)]
    + [f"http://127.0.0.1:{p}" for p in (8000, 8010, 5173)],
    allow_methods=["*"],
    allow_headers=["*"],
)


# transfer compression for the heavy display payloads (multi-MB CCP4 maps,
# supercell scene JSON, transcripts): SSE streams are exempted: gzip
# buffering can delay event delivery, and their frames are tiny anyway
_NO_GZIP_PREFIXES = ("/api/threads/events", "/api/projects/feed")


class SelectiveGZipMiddleware(GZipMiddleware):
    async def __call__(self, scope, receive, send):  # type: ignore[override]
        if scope["type"] == "http" and str(scope.get("path", "")).startswith(
                _NO_GZIP_PREFIXES):
            await self.app(scope, receive, send)
            return
        await super().__call__(scope, receive, send)


app.add_middleware(SelectiveGZipMiddleware, minimum_size=1024)

_executor = ThreadPoolExecutor(max_workers=2)
_runs_lock = threading.Lock()
_active_runs: dict[str, dict] = {}   # run_id -> {status, future, params}


class SolveRequest(BaseModel):
    hkl_path: str
    ins_path: str | None = None
    p4p_path: str | None = None
    mode: str = "auto"            # auto (agent) | standard (deterministic)
    symmetry: str = "auto"        # auto | hint


class DetectRequest(BaseModel):
    paths: list[str]


def _do_solve(run_id: str, req: SolveRequest) -> None:
    try:
        from crystalpilot.io.autodetect import classify, load_bundle
        kind = classify(Path(req.hkl_path))
        bundle: dict = {}
        if kind == "sf_cif":
            bundle["sf_cif"] = req.hkl_path
        else:
            bundle["hkl"] = req.hkl_path
        if req.ins_path:
            bundle["ins"] = req.ins_path
        if req.p4p_path:
            bundle["p4p"] = req.p4p_path
        ds = load_bundle(bundle)
        if req.mode in ("auto", "copilot"):
            from crystalpilot.agent.crystal_agent import run_auto
            result = run_auto(ds, RUNS_DIR, run_id=run_id, symmetry_mode=req.symmetry,
                              copilot=(req.mode == "copilot"))
        else:
            from crystalpilot.pipeline.standard import run_standard
            result = run_standard(ds, RUNS_DIR, run_id=run_id,
                                  symmetry_mode=req.symmetry)
        status = "done" if result.get("ok") else "failed"
    except Exception as e:  # noqa: BLE001
        status = "failed"
        err_file = RUNS_DIR / run_id / "server_error.txt"
        err_file.parent.mkdir(parents=True, exist_ok=True)
        import traceback
        err_file.write_text(f"{e}\n{traceback.format_exc()}", encoding="utf-8")
    with _runs_lock:
        if run_id in _active_runs:
            _active_runs[run_id]["status"] = status


@app.post("/api/upload")
async def upload(files: list[UploadFile] = File(...)) -> dict:
    """Receive dropped data files; returns stored paths."""
    batch = UPLOADS_DIR / time.strftime("%Y%m%d_%H%M%S")
    batch.mkdir(parents=True, exist_ok=True)
    stored = []
    for f in files:
        name = Path(f.filename or "file").name
        dest = batch / name
        with dest.open("wb") as out:
            shutil.copyfileobj(f.file, out)
        stored.append(str(dest))
    return {"paths": stored}


@app.post("/api/detect")
def detect(req: DetectRequest) -> dict:
    """Classify uploaded files and propose the hkl/ins pairing."""
    from crystalpilot.io.autodetect import detect_bundle
    return detect_bundle(req.paths)


@app.post("/api/solve")
def start_solve(req: SolveRequest) -> dict:
    if not Path(req.hkl_path).exists():
        raise HTTPException(400, f"data file not found: {req.hkl_path}")
    run_id = "run_" + uuid.uuid4().hex[:10]
    # create the run dir up-front so the UI can attach before the worker starts
    (RUNS_DIR / run_id / "artifacts").mkdir(parents=True, exist_ok=True)
    with _runs_lock:
        _active_runs[run_id] = {"status": "running", "params": req.model_dump(),
                                "started": time.time()}
    _executor.submit(_do_solve, run_id, req)
    return {"run_id": run_id}


@app.get("/api/runs")
def list_runs() -> list[dict]:
    out = []
    if RUNS_DIR.exists():
        for d in sorted(RUNS_DIR.iterdir(), key=lambda p: -p.stat().st_mtime):
            if not d.is_dir():
                continue
            entry: dict = {"run_id": d.name, "mtime": d.stat().st_mtime}
            with _runs_lock:
                active = _active_runs.get(d.name)
            entry["status"] = active["status"] if active else "done"
            report = d / "artifacts" / "report.json"
            if report.exists():
                try:
                    rep = json.loads(report.read_text(encoding="utf-8"))
                    entry["summary"] = {
                        "ok": rep.get("ok"),
                        "space_group": (rep.get("symmetry") or {}).get("space_group"),
                        "r1": (rep.get("refinement") or {}).get("r1_strong"),
                        "confidence": ((rep.get("validation") or {}).get("confidence")
                                       or {}).get("score"),
                        "elapsed_s": rep.get("elapsed_s"),
                    }
                except json.JSONDecodeError:
                    pass
            elif entry["status"] == "done":
                entry["status"] = "failed"
            out.append(entry)
    return out


@app.get("/api/runs/{run_id}")
def run_detail(run_id: str) -> dict:
    d = RUNS_DIR / run_id
    if not d.exists():
        raise HTTPException(404, "unknown run")
    report = d / "artifacts" / "report.json"
    rep = (json.loads(report.read_text(encoding="utf-8"))
           if report.exists() else None)
    with _runs_lock:
        active = _active_runs.get(run_id)
    err = d / "server_error.txt"
    return {
        "run_id": run_id,
        "status": active["status"] if active else ("done" if rep else "failed"),
        "report": rep,
        "error": err.read_text(encoding="utf-8")[:2000] if err.exists() else None,
        "has_cif": (d / "artifacts" / "final.cif").exists(),
    }


@app.get("/api/runs/{run_id}/events")
def run_events(run_id: str, after: int = 0, limit: int = 500) -> dict:
    """Event log slice for live timeline; poll with ?after=<n_received>."""
    path = RUNS_DIR / run_id / "events.jsonl"
    if not path.exists():
        return {"events": [], "next": after}
    events = []
    with path.open(encoding="utf-8") as fh:
        for i, line in enumerate(fh):
            if i < after or len(events) >= limit:
                continue
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return {"events": events, "next": after + len(events)}


class ApprovalRequest(BaseModel):
    event_id: str
    approve: bool
    comment: str = ""


@app.post("/api/runs/{run_id}/approve")
def approve_action(run_id: str, req: ApprovalRequest) -> dict:
    """Copilot mode: record the user's decision for a pending_approval event."""
    d = RUNS_DIR / run_id
    if not d.exists():
        raise HTTPException(404, "unknown run")
    with (d / "approvals.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"event_id": req.event_id, "approve": req.approve,
                             "comment": req.comment, "ts": time.time()}) + "\n")
    return {"ok": True}


@app.get("/api/runs/{run_id}/cif", response_class=PlainTextResponse)
def run_cif(run_id: str) -> str:
    path = RUNS_DIR / run_id / "artifacts" / "final.cif"
    if not path.exists():
        raise HTTPException(404, "no CIF for this run")
    return path.read_text(encoding="utf-8")


# UI inputs whose mtime must be older than dist/index.html for the served
# bundle to count as fresh (round-2 plan R0, defect D1: a two-day-old dist
# was served while newer tool cards sat unbuilt in ui/src).
_UI_BUILD_INPUTS = ("src", "index.html", "vite.config.ts", "package.json", "package-lock.json")


def ui_build_info() -> dict:
    index = UI_DIST / "index.html"
    if not index.exists():
        return {"present": False}
    built = index.stat().st_mtime
    ui_root = ROOT / "ui"
    newest = 0.0
    newest_file: Path | None = None
    for name in _UI_BUILD_INPUTS:
        p = ui_root / name
        files = (f for f in p.rglob("*") if f.is_file()) if p.is_dir() else ([p] if p.is_file() else [])
        for f in files:
            m = f.stat().st_mtime
            if m > newest:
                newest, newest_file = m, f
    stamp: dict = {}
    try:
        stamp = json.loads((UI_DIST / "build.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    iso = lambda t: datetime.fromtimestamp(t).isoformat(timespec="seconds")  # noqa: E731
    return {
        "present": True,
        "built_at": stamp.get("built_at") or iso(built),
        "version": stamp.get("version"),
        "src_newest_at": iso(newest) if newest else None,
        "src_newest_file": str(newest_file.relative_to(ROOT)) if newest_file else None,
        # 1 s slack: build.json is written right after index.html
        "stale": bool(newest > built + 1.0),
    }


@app.get("/api/health")
def health() -> dict:
    llm_ok = False
    try:
        from crystalpilot.llm.config import resolve_llm_config
        resolve_llm_config(ROOT)
        llm_ok = True
    except RuntimeError:
        pass
    return {"ok": True, "llm_configured": llm_ok, "ui_build": ui_build_info()}


# Workbench (Codex-harness) routes: optional: engine-only installs lack the
# openai-codex SDK; everything else keeps working without it.
try:
    from crystalpilot.workbench.routes import router as _wb_router
    from crystalpilot.workbench.routes import ui_router as _wb_ui_router
    from crystalpilot.workbench.routes_config import router as _wb_config_router
    app.include_router(_wb_router)
    app.include_router(_wb_ui_router)
    app.include_router(_wb_config_router)
    _workbench_available = True
except ImportError as _wb_err:
    _workbench_available = False
    _workbench_error = str(_wb_err)


@app.get("/api/workbench/health")
def workbench_health() -> dict:
    return {"available": _workbench_available,
            "error": None if _workbench_available else _workbench_error}


@app.on_event("startup")
def _warmup_cctbx() -> None:
    """Import boost extension modules on the MAIN thread before any request.

    On Windows, cctbx/smtbx boost extensions can deadlock when first imported
    from a worker thread; the scene/map endpoints run in FastAPI's threadpool,
    so pre-import here (startup handlers run on the event-loop thread).
    """
    try:
        # one list for the MCP process and this server: scipy (BLAS),
        # cctbx / smtbx boost extensions, gemmi - all first-imported on the
        # main thread (mcp/prewarm.py has the deadlock evidence)
        from crystalpilot.mcp.prewarm import prewarm_heavy_imports
        rep = prewarm_heavy_imports()
        if rep["failed"]:
            print(f"[crystalpilot] prewarm: {len(rep['imported'])} modules, "
                  f"missing {sorted(rep['failed'])}")
        import crystalpilot.chem.bonding  # noqa: F401
        from crystalpilot.workbench import analysis_jobs as jobs
        if jobs.analysis_jobs.closed:
            jobs.analysis_jobs = jobs.AnalysisJobManager()
    except ImportError:
        pass  # engine-less installs: scene endpoints will 500 with a clear error
    # seed the CPU cap on the tree root: every descendant (codex engines,
    # MCP pythons, SHELXL/PLATON bursts) inherits the affinity mask, so
    # crystallography can never saturate the user's workstation (r12
    # user report; CRYSTALPILOT_CPU_CORES=0 disables)
    try:
        from crystalpilot.procutil import limit_cpu
        note = limit_cpu()
        if note:
            print(f"[crystalpilot] {note}")
    except Exception:  # noqa: BLE001 - the cap is best-effort
        pass


@app.on_event("shutdown")
def _stop_analysis_jobs() -> None:
    from crystalpilot.workbench.analysis_jobs import analysis_jobs
    analysis_jobs.shutdown(wait=False)


if UI_DIST.exists():
    app.mount("/assets", StaticFiles(directory=str(UI_DIST / "assets")), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):  # SPA fallback: serve real files, else index.html
        candidate = UI_DIST / path
        if path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(UI_DIST / "index.html")
