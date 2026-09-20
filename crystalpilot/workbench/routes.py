"""FastAPI routes for the workbench: projects, threads, SSE, approvals.

Mounted by server/app.py under the main CrystalPilot server (port 8000).
Windows paths travel in JSON bodies / query params, never in URL path segments.
The debug UI is served at /wb until the React workbench (Phase 2) replaces it.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

from fastapi import (APIRouter, Body, File, Form, Header, HTTPException,
                     UploadFile)
from fastapi.responses import (FileResponse, HTMLResponse, PlainTextResponse,
                               StreamingResponse)
from pydantic import BaseModel

from . import registry
from .core import ENGINE_ROOT, RESULTS_DIRNAME
from .i18n import msg
from .service import ProjectSession, WorkbenchPool

router = APIRouter(prefix="/api")
pool = WorkbenchPool()
log = logging.getLogger("crystalpilot.workbench")
REPO_ROOT = Path(__file__).resolve().parents[2]
UI_DIAGNOSTICS_LOG = REPO_ROOT / "workdir" / "ui-diagnostics.jsonl"
UI_DIAGNOSTICS_ROTATE_BYTES = 5 * 1024 * 1024
TRANSCRIPT_PAGE_MAX = 5000

# shut down all app-server subprocesses when the server process exits
import atexit  # noqa: E402

atexit.register(pool.close_all)


def _session_or_404(project: str) -> ProjectSession:
    ps = pool.get(project)
    if ps is None:
        raise HTTPException(400, "project not open; call /api/projects/open first")
    return ps


def _by_thread_or_404(thread_id: str) -> ProjectSession:
    ps = pool.by_thread(thread_id)
    if ps is None:
        raise HTTPException(404, f"no open project owns thread {thread_id}")
    return ps


# -- projects ---------------------------------------------------------------
@router.get("/folders")
def list_project_folders(path: str | None = None) -> dict:
    """Read-only directory picker for both local desktops and headless hosts.

    Uses the same OS-user access as the existing native picker. Returns only
    directory names/paths, never file contents or hidden configuration entries.
    """
    default = ENGINE_ROOT.parent / "projects"
    folder = Path(path).expanduser() if path else (default if default.is_dir() else ENGINE_ROOT.parent)
    try:
        folder = folder.resolve(strict=True)
        if not folder.is_dir():
            raise HTTPException(400, msg("请选择一个文件夹", "Choose a folder"))
        children = []
        for child in folder.iterdir():
            try:
                if not child.name.startswith(".") and child.is_dir():
                    children.append({"name": child.name, "path": str(child)})
            except OSError:
                continue
        children.sort(key=lambda row: row["name"].casefold())
        return {"path": str(folder), "parent": str(folder.parent) if folder.parent != folder else None,
                "directories": children[:1000], "truncated": len(children) > 1000}
    except PermissionError as exc:
        raise HTTPException(403, msg("无法访问这个文件夹，请选择其他位置", "This folder cannot be accessed; choose another location")) from exc
    except (FileNotFoundError, NotADirectoryError) as exc:
        raise HTTPException(404, msg("文件夹不存在，请检查路径", "The folder does not exist; check the path")) from exc


class OpenProject(BaseModel):
    path: str
    auto_approve: bool = False


@router.post("/projects/open")
def open_project(req: OpenProject) -> dict:
    if not Path(req.path).expanduser().exists():
        Path(req.path).expanduser().mkdir(parents=True, exist_ok=True)
    try:
        ps = pool.open(req.path, auto_approve=req.auto_approve)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"failed to open project: {e}") from e
    return {"project": str(ps.wb.project.path),
            "threads": ps.wb.tasks(),
            "results_dirname": RESULTS_DIRNAME,
            "auto_approve": ps.auto_approve,
            # what ensure_agents_md did (action/warning): a project whose
            # AGENTS.md is the user's own file is reported, not overwritten
            "agents_md": ps.wb.project.agents_md}


@router.post("/projects/import-structure")
async def import_structure_document(project: str = Form(...),
                                    file: UploadFile = File(...),
                                    block: str | None = Form(None)) -> dict:
    """Create a geometry-only project; no model turn or reflection data required."""
    import tempfile
    from starlette.concurrency import run_in_threadpool
    from crystalpilot.refine.project import RefineProject
    from .core import ProjectState

    target = Path(project).expanduser()
    if not target.is_absolute():
        raise HTTPException(400, msg("请使用仓库外新项目的完整路径", "Give the full path of a new project outside the repository"))
    target = target.resolve()
    if target == ENGINE_ROOT or ENGINE_ROOT in target.parents:
        raise HTTPException(400, msg("结构项目请放在程序仓库之外", "Structure projects must live outside the program repository"))
    if Path(file.filename or "").suffix.lower() != ".cif":
        raise HTTPException(400, msg("请选择 CIF 文件", "Choose a CIF file"))
    content = await file.read(50 * 1024 * 1024 + 1)
    if len(content) > 50 * 1024 * 1024:
        raise HTTPException(413, msg("CIF 超过 50 MB，请使用本地路径导入工具", "The CIF exceeds 50 MB; use the local-path import tool"))
    temporary_root = ENGINE_ROOT / "workdir" / "uploads"
    temporary_root.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix="cif-document-", dir=temporary_root) as temporary:
            source = Path(temporary) / Path(file.filename or "source.cif").name
            source.write_bytes(content)
            document = await run_in_threadpool(
                RefineProject.create_structure_only, target, source,
                block_name=(block.strip() or None) if block else None)
        state = ProjectState.open(target)
        state.settings["permission_mode"] = "readonly"
        state.settings["subagents"] = "off"
        state.save()
        return {"project": str(target), "node": document.nodes.state()["active_node"],
                "mode": "structure_only"}
    except (ValueError, RuntimeError, OSError) as error:
        raise HTTPException(400, str(error)) from error


@router.get("/projects/recent")
def recent() -> list[dict]:
    return registry.recent_projects()


@router.get("/projects/usage")
def project_usage_route(path: str) -> dict:
    """Bytes by category (user data / deliverables / system) and what a
    cleanup would reclaim (dry run). Reads the directory only."""
    p = Path(path).expanduser()
    if not p.is_dir():
        raise HTTPException(404, "no such project directory")
    from crystalpilot.refine.storage import project_usage
    return project_usage(p)


class CleanupRequest(BaseModel):
    path: str
    apply: bool = False
    include_cache: bool = False


@router.post("/projects/cleanup")
def project_cleanup(req: CleanupRequest) -> dict:
    """Storage cleanup of unreferenced intermediates (see
    crystalpilot/refine/storage.py). `apply=false` (default) returns the
    plan only; `apply=true` executes it after re-checking every action.
    409 while a turn runs on the project (tools write job directories)."""
    p = Path(req.path).expanduser()
    if not p.is_dir():
        raise HTTPException(404, "no such project directory")
    ps = pool.get(p)
    if ps is not None and ps.busy_threads():
        raise HTTPException(409, "a turn is running on this project; clean up when it ends")
    from crystalpilot.refine.storage import (apply_cleanup, measure_project,
                                             plan_cleanup)
    plan = plan_cleanup(p, include_cache=req.include_cache)
    out: dict[str, Any] = plan.to_dict()
    out["applied"] = False
    if req.apply:
        result = apply_cleanup(plan)
        out["applied"] = True
        out["result"] = result
        usage = measure_project(p)
        after = plan_cleanup(p, include_cache=req.include_cache)
        usage["reclaimable_bytes"] = after.reclaimable_bytes
        usage["reclaimable_by_kind"] = after.summary()["by_kind"]
        usage["n_actions"] = len(after.actions)
        out["usage"] = usage
        log.info("storage cleanup %s: freed %d bytes, %d done, %d skipped",
                 p, result["freed_bytes"], result["n_done"], result["n_skipped"])
    return out


@router.get("/projects/status")
def projects_status() -> list[dict]:
    """Where every known project stands, at a glance.

    Deliberately engine-free: it reads the workbench state file, the node
    store and the last checkCIF report off disk, so asking for the whole
    picture never boots a Codex process or a cctbx import. Only the
    `busy` flag consults the live pool."""
    open_keys = {pool._key(ps.wb.project.path): ps
                 for ps in pool.sessions()}
    out: list[dict] = []
    for entry in registry.recent_projects():
        p = Path(entry["path"])
        ps = open_keys.get(pool._key(p))
        row: dict[str, Any] = {
            "path": str(p), "name": p.name,
            "display_name": entry.get("display_name"),
            "opened": entry.get("opened"),
            "is_open": ps is not None,
            "busy": bool(ps and ps.busy_threads()),
        }
        row.update(_project_status_from_disk(p))
        out.append(row)
    out.sort(key=lambda r: (not r["busy"],
                           -(r.get("last_active") or r.get("opened") or 0)))
    return out


#: /projects/status is polled by the sidebar and the status board. Reading
#: every recent project's node store (78 node.json files for one real
#: project) cost 2.1 s warm and 36.8 s cold for 30 projects (measured
#: 2026-09-16); the answer only changes when one of a handful of files
#: does, so it is cached per project behind their mtimes.
_STATUS_CACHE: dict[str, tuple[tuple, dict]] = {}
_STATUS_CACHE_LOCK = threading.Lock()


def _status_stamp(p: Path) -> tuple:
    """Everything _project_status_from_disk reads, as (path, mtime_ns) pairs
    of the files/directories whose change invalidates the answer."""
    refine = p / ".crystalpilot" / "refine"
    probes = (p / ".crystalpilot-workbench.json", refine / "state.json",
              refine / "nodes", refine / "checkcif", p / RESULTS_DIRNAME)
    stamp = []
    for q in probes:
        try:
            stamp.append(q.stat().st_mtime_ns)
        except OSError:
            stamp.append(None)
    return tuple(stamp)


def _project_status_from_disk(p: Path) -> dict:
    """Node-store head + last checkCIF counts + thread activity (cached
    behind the mtimes of what it reads; see _status_stamp)."""
    key = str(p)
    stamp = _status_stamp(p)
    with _STATUS_CACHE_LOCK:
        hit = _STATUS_CACHE.get(key)
    if hit is not None and hit[0] == stamp:
        return dict(hit[1])
    out = _project_status_from_disk_uncached(p)
    with _STATUS_CACHE_LOCK:
        _STATUS_CACHE[key] = (stamp, dict(out))
        if len(_STATUS_CACHE) > 200:
            _STATUS_CACHE.pop(next(iter(_STATUS_CACHE)))
    return out


def _project_status_from_disk_uncached(p: Path) -> dict:
    out: dict[str, Any] = {}
    state = p / ".crystalpilot-workbench.json"
    if state.exists():
        try:
            st = json.loads(state.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            st = {}
        threads = st.get("threads") or []
        out["n_threads"] = len(threads)
        if threads:
            last = max(threads, key=lambda t: t.get("last_active") or 0)
            out["last_active"] = last.get("last_active")
            out["last_title"] = last.get("title")
        out["permission_mode"] = (st.get("settings") or {}).get(
            "permission_mode")
    if (p / ".crystalpilot" / "refine").exists():
        try:
            from crystalpilot.refine.nodes import NodeStore
            nodes = NodeStore(p).list_nodes(limit=400)
            rows = nodes.get("nodes") or []
            out["n_nodes"] = len(rows)
            out["active_node"] = nodes.get("active_node")
            head = next((r for r in reversed(rows)
                         if r.get("id") == nodes.get("active_node")), None)
            # the active node may predate the best refinement; report both
            r1s = [r["r1"] for r in rows if r.get("r1") is not None]
            if head:
                out["r1"] = head.get("r1")
                out["n_atoms"] = head.get("n_atoms")
                out["last_tool"] = head.get("tool")
            if r1s:
                out["r1_best"] = min(r1s)
        except Exception:  # noqa: BLE001 - a status view never raises
            pass
    reports = sorted(
        (p / ".crystalpilot" / "refine" / "checkcif").glob("*/checkcif.json"),
        key=lambda f: f.stat().st_mtime) if (
            p / ".crystalpilot" / "refine" / "checkcif").exists() else []
    if reports:
        try:
            out["checkcif"] = json.loads(
                reports[-1].read_text(encoding="utf-8")).get("counts")
        except (OSError, json.JSONDecodeError):
            pass
    results = p / RESULTS_DIRNAME
    if results.exists():
        out["n_deliveries"] = sum(1 for d in results.iterdir() if d.is_dir())
    return out


class SettingsUpdate(BaseModel):
    path: str
    permission_mode: str | None = None
    # plain per-project flags, e.g. {"allow_iucr_upload": true}
    settings: dict | None = None


@router.get("/projects/settings")
def get_settings(path: str) -> dict:
    ps = pool.get(path)
    if ps is not None:
        return ps.settings()
    from .service import DEFAULT_PERMISSION_MODE, project_settings_dict
    from .core import ProjectState
    st = ProjectState.open(path)
    return project_settings_dict(
        st.path, st.settings,
        st.settings.get("permission_mode") or DEFAULT_PERMISSION_MODE)


@router.post("/projects/settings")
def set_settings(req: SettingsUpdate) -> dict:
    ps = _session_or_404(req.path)
    try:
        if req.permission_mode is not None:
            ps.set_permission_mode(req.permission_mode)
        if req.settings is not None:
            ps.update_project_settings(req.settings)
        return ps.settings()
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except RuntimeError as e:
        raise HTTPException(409, str(e)) from e


@router.post("/projects/upload")
async def upload(path: str = Form(...),
                 files: list[UploadFile] = File(...)) -> dict:
    """Copy attachments into <project>/uploads/; returns rel paths the client
    references in the message text."""
    ps = _session_or_404(path)
    root = ps.wb.project.path / "uploads"
    root.mkdir(exist_ok=True)
    out = []
    for f in files:
        name = Path(f.filename or "file").name  # strip any client path parts
        dest = root / name
        stem, suffix = dest.stem, dest.suffix
        k = 1
        while dest.exists():
            dest = root / f"{stem}_{k}{suffix}"
            k += 1
        data = await f.read()
        if len(data) > 50 * 1024 * 1024:
            raise HTTPException(413, f"{name} exceeds 50 MB")
        dest.write_bytes(data)
        kind = ("image" if suffix.lower() in
                (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")
                else "data" if suffix.lower() in
                (".hkl", ".res", ".ins", ".cif", ".fcf", ".p4p", ".fab")
                else "other")
        if kind == "image" and not _sniff_image(data):
            kind = "other"  # extension lies about the bytes - don't feed
            # it to the model as an image input
        rel = str(dest.relative_to(ps.wb.project.path)).replace("\\", "/")
        out.append({"rel": rel, "size": len(data), "kind": kind,
                    "name": name})
    return {"files": out}


def _sniff_image(data: bytes) -> bool:
    """First-bytes check for the image formats we accept as model input."""
    return (data.startswith(b"\x89PNG\r\n\x1a\n")
            or data.startswith(b"\xff\xd8\xff")             # JPEG
            or data.startswith((b"GIF87a", b"GIF89a"))
            or (data[:4] == b"RIFF" and data[8:12] == b"WEBP")
            or data.startswith(b"BM"))                       # BMP


_FRAME_EXTS = (".cbf", ".sfrm", ".img", ".osc", ".mccd", ".mar2300", ".h5",
               ".nxs", ".odeiger", ".rodhypix", ".rod_img", ".kcd", ".esperanto")


@router.get("/projects/frames_probe")
def frames_probe(path: str) -> dict:
    """Read-only stat of a local raw-frames directory, so the UI can hand the
    agent a VALIDATED path instead of uploading thousands of frames (frames
    stay in place; the staged import_frames tool reads them directly)."""
    d = Path(path).expanduser()
    if not d.is_dir():
        raise HTTPException(404, msg(f"目录不存在：{d}", f"Directory not found: {d}"))
    by_ext: dict[str, int] = {}
    total = 0
    n_other = 0
    sample: list[str] = []
    try:
        for f in d.iterdir():
            if not f.is_file():
                continue
            ext = f.suffix.lower()
            if ext in _FRAME_EXTS:
                by_ext[ext] = by_ext.get(ext, 0) + 1
                total += f.stat().st_size
                if len(sample) < 3:
                    sample.append(f.name)
            else:
                n_other += 1
    except OSError as e:
        raise HTTPException(400, msg(f"无法读取目录：{e}", f"The directory cannot be read: {e}")) from e
    n_frames = sum(by_ext.values())
    return {
        "path": str(d),
        "n_frames": n_frames,
        "by_ext": by_ext,
        "n_other_files": n_other,
        "total_MB": round(total / 1e6, 1),
        "sample": sample,
        "ok": n_frames > 0,
        "note": None if n_frames > 0 else
        msg(f"目录里没有已知格式的衍射帧（识别扩展名：{', '.join(_FRAME_EXTS)}）",
            f"No diffraction frames of a known format in this directory (recognised extensions: {', '.join(_FRAME_EXTS)})"),
    }


# -- threads ----------------------------------------------------------------
class AttachmentRef(BaseModel):
    rel: str
    kind: str = "other"
    name: str | None = None


class SendMessage(BaseModel):
    project: str
    message: str
    thread_id: str | None = None
    title: str | None = None
    attachments: list[AttachmentRef] | None = None
    allow_concurrent: bool = False
    # campaign runner: force the final assistant message into a JSON verdict
    # (r1/space_group/unresolved/confidence) the grader's honesty gates eat
    output_schema: dict | None = None


@router.post("/threads/send")
def send(req: SendMessage) -> dict:
    ps = _session_or_404(req.project)
    if req.thread_id:
        task = ps.get_thread(req.thread_id)
    else:
        task = ps.new_thread(title=req.title)
        pool.register_thread(task.thread_id, ps)
    if ps.is_busy(task.thread_id):
        raise HTTPException(409, "a turn is already running on this thread")
    others = ps.busy_threads() - {task.thread_id}
    if others and not req.allow_concurrent:
        raise HTTPException(
            409, "another thread is mid-turn on this project "
                 f"({', '.join(sorted(others))}); concurrent agents on one "
                 "project corrupt the shared session (practice-770 incident)."
                 " Wait, or resend with allow_concurrent=true for read-only "
                 "work only.")
    atts = [a.model_dump() for a in req.attachments] if req.attachments else None
    ps.send(task.thread_id, req.message, attachments=atts,
            allow_concurrent=req.allow_concurrent,
            output_schema=req.output_schema)
    return {"thread_id": task.thread_id, "task_id": task.task_id}


class ThreadRef(BaseModel):
    thread_id: str


@router.post("/threads/interrupt")
def interrupt(req: ThreadRef) -> dict:
    ps = _by_thread_or_404(req.thread_id)
    return {"interrupted": ps.interrupt(req.thread_id)}


class ProjectRef(BaseModel):
    path: str


@router.post("/projects/restart_engine")
def restart_engine(req: ProjectRef) -> dict:
    """Rebuild the engine process for a project whose MCP transport died
    (mcp_down event). 409 while a turn is running."""
    ps = _session_or_404(req.path)
    try:
        return ps.restart_engine()
    except RuntimeError as e:
        raise HTTPException(409, str(e))


@router.post("/projects/mcp_status")
def mcp_status(req: ProjectRef) -> dict:
    """Toolset liveness probe: {present, n_tools, error}. Detects an MCP
    child that froze during startup (empty toolset, no transport errors)."""
    return _session_or_404(req.path).mcp_status()


class SteerMessage(BaseModel):
    thread_id: str
    message: str
    attachments: list[AttachmentRef] | None = None


@router.post("/threads/steer")
def steer(req: SteerMessage) -> dict:
    """Inject guidance into the RUNNING turn (Codex turn_steer).
    409 when the thread is idle - the client should send() instead."""
    ps = _by_thread_or_404(req.thread_id)
    atts = [a.model_dump() for a in req.attachments] if req.attachments else None
    receipt = ps.steer(req.thread_id, req.message, attachments=atts)
    if receipt is None:
        raise HTTPException(409, "thread idle")
    task = ps.get_thread(req.thread_id)
    # round-3 R6: ok = the words are in the transcript; `receipt` says
    # whether they reached the model ("submitted" | "failed" + error)
    return {"ok": True, "task_id": task.task_id,
            "receipt": receipt.get("status"),
            "steer_eid": receipt.get("steer_eid"),
            "error": receipt.get("error")}


@router.get("/threads/list")
def threads_list(project: str) -> dict:
    ps = pool.get(project)
    if ps is not None:
        return {"threads": ps.threads_meta()}
    # project not open: read thread metadata straight from disk
    from .core import ProjectState
    p = Path(project)
    if not p.exists():
        raise HTTPException(404, "no such project directory")
    return {"threads": [dict(t, busy=False)
                        for t in ProjectState.open(p).threads]}


def _thread_results(thread_id: str, project: str | None):
    """(task record, results root, live session | None) for a thread that is
    open in the pool or, failing that, recorded on disk under project=."""
    ps = pool.by_thread(thread_id)
    rec = None
    if ps is not None:
        rec = next((t for t in ps.wb.tasks()
                    if t["thread_id"] == thread_id), None)
        root = ps.wb.project.results_root
    elif project:
        from .core import RESULTS_DIRNAME as RD
        from .core import ProjectState
        st = ProjectState.open(project)
        rec = next((t for t in st.threads if t["thread_id"] == thread_id), None)
        root = st.path / RD
    else:
        raise HTTPException(404, "thread not in an open project; pass project=")
    if rec is None:
        raise HTTPException(404, "unknown thread")
    return rec, root, ps


@router.get("/threads/transcript")
def thread_transcript(thread_id: str, project: str | None = None,
                      limit: int = 2000, before: int | None = None) -> dict:
    """Historical events for reopening a thread, newest page first.

    Every event carries ``eid`` = its 1-based line index in transcript.jsonl
    (assigned here for lines written before eids existed, identical to what
    the live channel stamps for new ones). ``before`` pages backwards: only
    lines with eid < before are returned, at most ``limit`` of them.
    live_cursor / generation are snapshotted from the live channel BEFORE
    reading the file so the client can resume SSE exactly there; both are
    0 / None when the project session is not open."""
    limit = max(1, min(int(limit), TRANSCRIPT_PAGE_MAX))
    rec, root, ps = _thread_results(thread_id, project)
    live_cursor = 0
    generation = None
    busy = False
    if ps is not None:
        ch = ps.channel(thread_id)
        live_cursor = ch.seq
        generation = ch.generation
        busy = ps.is_busy(thread_id)
    path = root / rec["task_id"] / "transcript.jsonl"
    lines: list[str] = []
    if path.exists():
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    total = len(lines)
    end = total if before is None else max(0, min(int(before) - 1, total))
    start = max(0, end - limit)
    events: list[dict] = []
    for idx in range(start, end):
        try:
            ev = json.loads(lines[idx])
        except json.JSONDecodeError:
            continue
        if not isinstance(ev, dict):
            continue
        ev["eid"] = idx + 1
        events.append(ev)
    if ps is not None and before is None:
        # the newest page also carries the live state of detached solver
        # jobs (no eid): a SHELXT still running or finished-but-unadopted
        # is shown after a reload even when no transcript line recorded it
        try:
            events.extend(ps.background_jobs())
        except Exception:  # noqa: BLE001 - never fail a bootstrap for this
            pass
    return {"thread_id": thread_id, "task_id": rec["task_id"],
            "live_cursor": live_cursor, "generation": generation,
            # server truth for the client: a transcript that ends mid-turn
            # while busy is False was cut (restart/crash) - its running rows
            # are closed as "no result" instead of spinning forever
            "busy": busy,
            "events": events, "total": total,
            "oldest_eid": (start + 1) if end > start else None,
            "has_more": start > 0}


@router.get("/threads/command_output")
def thread_command_output(thread_id: str, item_id: str,
                          project: str | None = None) -> PlainTextResponse:
    """Full output of one shell command (the transcript keeps a 1500-char
    tail; TaskSession.send stored the rest under command_output/)."""
    rec, root, _ = _thread_results(thread_id, project)
    from .core import _safe_item_name
    d = (root / rec["task_id"] / "command_output").resolve()
    name = _safe_item_name(item_id)
    candidates = sorted(d.glob(f"{name}*.txt")) if d.exists() else []
    for cand in candidates:
        if cand.resolve().parent != d:
            continue
        return PlainTextResponse(cand.read_text(encoding="utf-8", errors="replace"))
    raise HTTPException(404, "no stored output for this command")


@router.post("/ui/diagnostics")
def ui_diagnostics(report: dict = Body(...)) -> dict:
    """Browser-side error reports (ErrorBoundary, window.onerror,
    unhandledrejection) -> workdir/ui-diagnostics.jsonl, one line each, so a
    blank region has a stack, a component stack and a transcript cursor next
    time instead of nothing (forensics 2026-09-05)."""
    if not isinstance(report, dict):
        raise HTTPException(400, "report must be an object")
    clipped: dict[str, Any] = {}
    for k, v in report.items():
        if isinstance(v, str) and len(v) > 20000:
            v = v[:20000] + "..."
        clipped[str(k)[:64]] = v
    clipped["received"] = time.time()
    try:
        UI_DIAGNOSTICS_LOG.parent.mkdir(parents=True, exist_ok=True)
        if (UI_DIAGNOSTICS_LOG.exists()
                and UI_DIAGNOSTICS_LOG.stat().st_size > UI_DIAGNOSTICS_ROTATE_BYTES):
            UI_DIAGNOSTICS_LOG.replace(UI_DIAGNOSTICS_LOG.with_suffix(".1.jsonl"))
        with UI_DIAGNOSTICS_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(clipped, ensure_ascii=False, default=str) + "\n")
    except OSError as e:
        log.warning("ui diagnostic not stored: %s", e)
        return {"ok": False}
    log.warning("ui diagnostic [%s] %s", clipped.get("area"),
                str(clipped.get("message", ""))[:300])
    return {"ok": True}


#: heartbeat period of the SSE routes; the browser treats 3x this of
#: silence as a dead socket (ui/src/state/useThreadChannel.ts STALE_AFTER_MS)
SSE_PING_S = 15.0


def _sse(channel, after: int) -> StreamingResponse:
    """One SSE connection on a Channel. Async: waiting for the next event
    holds no worker thread (a browser tab keeps 2 of these open for hours;
    the sync generator pinned one of the 40 threadpool tokens each, shared
    with every synchronous route). The heartbeat is a real `ping` data
    event because SSE comment lines never reach JavaScript, so the client
    can tell a silent socket from a quiet one. `channel_closed` ends the
    stream when the project session is released."""
    async def gen():
        yield "retry: 2000\n\n"
        # no id: on the hello so the browser keeps its Last-Event-ID
        hello = {"kind": "channel_hello", "generation": channel.generation,
                 "seq": channel.seq, "after": after, "oldest": channel.oldest,
                 "ts": time.time()}
        yield f"data: {json.dumps(hello)}\n\n"
        cursor = after
        while True:
            batch = await channel.wait_async(cursor, timeout=SSE_PING_S)
            if not batch:
                if channel.closed:
                    closed = {"kind": "channel_closed", "ts": time.time()}
                    yield f"data: {json.dumps(closed)}\n\n"
                    return
                yield f"data: {json.dumps({'kind': 'ping', 'ts': time.time()})}\n\n"
                continue
            for seq, ev in batch:
                cursor = seq
                data = json.dumps(ev, ensure_ascii=False, default=str)
                yield f"id: {seq}\ndata: {data}\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream")


def _after(after: int, last_event_id: str | None) -> int:
    """SSE reconnects resume from the browser-supplied Last-Event-ID header."""
    try:
        return max(after, int(last_event_id or 0))
    except ValueError:
        return after


@router.get("/threads/events")
def thread_events(thread_id: str, after: int = 0, project: str | None = None,
                  last_event_id: str | None = Header(None)) -> StreamingResponse:
    ps = pool.by_thread(thread_id)
    if ps is None and project:
        # a thread the pool has not indexed yet (recorded on disk under
        # this project, e.g. created by another process): index it instead
        # of answering 404 and leaving the client's channel dead
        ps = pool.register_thread_of(thread_id, project)
    if ps is None:
        ps = _by_thread_or_404(thread_id)
    return _sse(ps.channel(thread_id), _after(after, last_event_id))


@router.get("/projects/feed")
def project_feed(path: str, after: int = 0,
                 last_event_id: str | None = Header(None)) -> StreamingResponse:
    ps = _session_or_404(path)
    return _sse(ps.feed, _after(after, last_event_id))


# -- approvals --------------------------------------------------------------
@router.get("/approvals")
def approvals(path: str) -> list[dict]:
    return _session_or_404(path).pending_approvals()


class Decision(BaseModel):
    approval_id: str
    decision: str = "accept"      # accept | reject


@router.post("/approvals/decide")
def decide(req: Decision) -> dict:
    if req.decision not in ("accept", "reject", "accept_for_session"):
        raise HTTPException(400,
                            "decision must be accept, reject, or "
                            "accept_for_session")
    for ps in pool.sessions():
        if ps.decide(req.approval_id, req.decision):
            return {"ok": True}
    raise HTTPException(404, "no such pending approval")


# -- artifacts --------------------------------------------------------------
@router.get("/threads/artifacts")
def thread_artifacts(thread_id: str) -> list[dict]:
    ps = _by_thread_or_404(thread_id)
    rec = next((t for t in ps.wb.tasks() if t["thread_id"] == thread_id), None)
    if rec is None:
        raise HTTPException(404, "unknown thread")
    return ps.artifacts(rec["task_id"])


def artifact_allowed(root: Path, results_root: Path, p: Path) -> bool:
    """Is `p` a file the UI may fetch for the project rooted at `root`?

    Deliverables, plus the read-only engine outputs the UI renders:
    checkCIF structured reports, SHELXL job files, and views/ - the
    rendered structure images view_structure/situation_report put in
    front of the model, so the user sees the same pictures it did."""
    cp = root / ".crystalpilot"
    return (results_root in p.parents
            or cp / "refine" / "checkcif" in p.parents
            or cp / "refine" / "shelxl" in p.parents
            or cp / "views" in p.parents)


@router.get("/wb/artifact")
def artifact(path: str) -> FileResponse:
    p = Path(path)
    for ps in pool.sessions():
        root = ps.wb.project.path
        if not p.exists() or root not in p.parents:
            continue
        if artifact_allowed(root, ps.wb.project.results_root, p):
            return FileResponse(p)
    raise HTTPException(404, "not an artifact of an open project")


# -- refinement session state (node store; plain JSON, no cctbx) ------------
def _deliveries_from_disk(p: Path) -> list[dict]:
    """Delivered nodes, read off the MANIFEST.json files under the results
    folder (one per write_outputs; a sub-delivery nests one level down).
    The node tree marks these rows 已交付. Manifests that predate the
    source-node field are skipped rather than guessed."""
    root = p / RESULTS_DIRNAME
    if not root.is_dir():
        return []
    out: list[dict] = []
    try:
        manifests = sorted(root.glob("*/MANIFEST.json")) + sorted(
            root.glob("*/*/MANIFEST.json"))
    except OSError:
        return []
    for m in manifests:
        try:
            d = json.loads(m.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(d, dict):
            continue
        src = d.get("source_state")
        node = src.get("node") if isinstance(src, dict) else None
        node = node or d.get("final_node")
        if not isinstance(node, str) or not node:
            continue
        out.append({"node": node, "status": d.get("status"),
                    "rel": m.parent.relative_to(root).as_posix(),
                    "generated": d.get("generated"),
                    "revision": d.get("delivery_revision")})
    return out


@router.get("/wb/refine/nodes")
def refine_nodes(project: str) -> dict:
    from crystalpilot.refine.nodes import NodeStore
    p = Path(project)
    if not (p / ".crystalpilot" / "refine").exists():
        return {"nodes": [], "active_node": None, "branches": {},
                "deliveries": []}
    try:
        out = NodeStore(p).list_nodes(limit=400)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"node store unreadable: {e}") from e
    out["deliveries"] = _deliveries_from_disk(p)
    return out


@router.get("/wb/refine/comparison")
def refine_comparison(project: str, node: str, baseline: str) -> dict:
    from crystalpilot.refine.nodes import NodeStore
    p = _refine_project_or_404(project)
    if any(not (value.startswith("n") and value[1:].isdigit()) for value in (node, baseline)):
        raise HTTPException(400, "comparison requires explicit node ids")
    try:
        return NodeStore(p).comparison(node, baseline)
    except (KeyError, FileNotFoundError) as exc:
        raise HTTPException(404, "comparison node not found") from exc


@router.get("/wb/refine/file")
def refine_file(project: str, node: str, name: str) -> FileResponse:
    if name not in ("model.cif", "model.res"):
        raise HTTPException(400, "name must be model.cif or model.res")
    if not node.replace("n", "").isdigit():
        raise HTTPException(400, "bad node id")
    p = Path(project) / ".crystalpilot" / "refine" / "nodes" / node / name
    if not p.exists():
        raise HTTPException(404, "no such node file")
    return FileResponse(p, media_type="chemical/x-cif"
                        if name.endswith(".cif") else "text/plain")


def _refine_project_or_404(project: str) -> Path:
    p = Path(project)
    if not (p / ".crystalpilot" / "refine").exists():
        raise HTTPException(404, "not a refinement project")
    return p


def _valid_node(node: str) -> str:
    if not (node.startswith("n") and node[1:].isdigit()) and node != "active":
        raise HTTPException(400, "bad node id")
    return node


@router.get("/wb/refine/scene")
def refine_scene(project: str, node: str, mode: str = "asu", n: int = 2,
                 hops: int = 0, polyhedra: int = 1, diff: int = 0,
                 extra: str | None = None, vs: str | None = None,
                 contacts: int = 0, complete: int = 0, interactions: int = 0,
                 radius: float = 8.0, center: str | None = None,
                 lo: str | None = None, hi: str | None = None,
                 grow_all: int = 0) -> dict:
    """Viewer scene JSON (atoms/bonds/polyhedra/cell) for one node.

    mode radius: whole molecules within `radius` A (1-30) of `center` (an
    ASU atom label, else the ASU centroid) - Olex2 `pack r`.
    mode range: groups whose centroid lies in the fractional box lo..hi
    ("a,b,c" each; default -0.5..1.5) - Olex2 `pack a1 a2 b1 b2 c1 c2`.
    complete: 1 = Olex2 `grow -w`, apply every operator already used to the
    whole ASU after growing.
    grow_all: 1 = Olex2 `grow` (no arguments): grow until a symmetry
    element repeats within the fragment - finite molecules complete,
    periodic nets stop after one period and the scene says so (`grow_all`).

    hops: grow the materialized set outward by this many bonded shells
    (0-4). Composes with any mode - growing is an action applied to the
    slice, not a slice of its own (Olex2: `pack` then `grow`).

    vs: diff against this node instead of the parent (any-vs-any compare).

    contacts: 1 = include short vdW contact edges + contact grow stubs
    (Olex2 grow -s analog).

    interactions: 1 = attach the interaction layer (hydrogen bonds, pi-pi,
    C-H...pi, C-H...X, halogen, anion-pi) computed on the drawn range with
    the boundary rule (R2.3; see refine.scene._interactions_block).

    extra: JSON list of user-grown instances [{"i": i_seq, "op": "x,y,z"}]
    from clicked grow stubs (Olex2 mode-grow analog); capped at 64.

    Heavy cctbx work runs in FastAPI's threadpool; cctbx itself is warmed up
    on the main thread at server startup (Windows boost import constraint).
    """
    p = _refine_project_or_404(project)
    if mode not in ("asu", "grow", "cell", "supercell", "radius", "range"):
        raise HTTPException(
            400, "mode must be asu|grow|cell|supercell|radius|range")
    frac_range = None
    if mode == "range":
        def _triple(s: str | None, default: float) -> tuple[float, float, float]:
            if not s:
                return (default, default, default)
            parts = [float(x) for x in s.split(",")]
            if len(parts) != 3:
                raise ValueError("expected a,b,c")
            return (parts[0], parts[1], parts[2])
        try:
            frac_range = (_triple(lo, -0.5), _triple(hi, 1.5))
        except ValueError as e:
            raise HTTPException(400, f"bad lo/hi: {e}") from e
    grown: list[dict] | None = None
    if extra:
        try:
            raw = json.loads(extra)
            assert isinstance(raw, list)
            grown = [{"i": int(e["i"]), "op": str(e["op"])[:80]}
                     for e in raw[:64]]
        except Exception as e:  # noqa: BLE001
            raise HTTPException(400, f"bad extra parameter: {e}") from e
    from crystalpilot.refine.scene import cached_scene
    try:
        return cached_scene(p, _valid_node(node), mode=mode,
                            n=max(1, min(n, 4)), hops=max(0, min(hops, 4)),
                            polyhedra=bool(polyhedra), diff=bool(diff),
                            extra=grown,
                            diff_vs=_valid_node(vs) if vs else None,
                            contacts=bool(contacts), complete=bool(complete),
                            interactions=bool(interactions),
                            grow_all=bool(grow_all),
                            radius=max(1.0, min(float(radius), 30.0)),
                            center=(center or "")[:40] or None,
                            frac_range=frac_range)
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"scene build failed: {e}") from e


@router.get("/wb/refine/map")
def refine_map(project: str, node: str, kind: str = "fofc") -> FileResponse:
    """Fo-Fc (or 2Fo-Fc, kind=2fofc) map (CCP4); computed lazily, cached."""
    if kind not in ("fofc", "2fofc"):
        raise HTTPException(400, "kind must be fofc|2fofc")
    p = _refine_project_or_404(project)
    from crystalpilot.refine.scene import cached_fofc
    try:
        path = cached_fofc(p, _valid_node(node), kind=kind)
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"map build failed: {e}") from e
    return FileResponse(path, media_type="application/octet-stream")


@router.get("/wb/refine/voids")
def refine_voids(project: str, node: str) -> dict:
    """Solvent-accessible void metadata for a node (count, volumes,
    electron counts, centres); computed lazily, disk-cached.

    `params_source` says whether `mask_params` came from the node's own
    solvent_mask call ("node" - this is the mask the refinement applied) or
    from the tool's schema defaults ("defaults" - a preview of what
    masking WOULD find). Those are different claims about the picture."""
    p = _refine_project_or_404(project)
    from crystalpilot.refine.scene import cached_voids
    try:
        _ccp4, meta = cached_voids(p, _valid_node(node))
        return json.loads(meta.read_text(encoding="utf-8"))
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"voids build failed: {e}") from e


class AnalysisStart(BaseModel):
    project: str
    node: str = "active"
    observer_id: str | None = None


class AnalysisCancel(BaseModel):
    project: str
    observer_id: str


def _analysis_jobs():
    from .analysis_jobs import analysis_jobs
    return analysis_jobs


@router.post("/wb/refine/analysis/jobs")
def start_refine_analysis(req: AnalysisStart) -> dict:
    from .analysis_jobs import AnalysisQueueFull
    p = _refine_project_or_404(req.project)
    try:
        return _analysis_jobs().start(p, _valid_node(req.node), observer_id=req.observer_id)
    except AnalysisQueueFull as error:
        raise HTTPException(429, str(error)) from error
    except KeyError as error:
        raise HTTPException(404, str(error)) from error
    except (ValueError, RuntimeError) as error:
        raise HTTPException(409, str(error)) from error


@router.get("/wb/refine/analysis/jobs/{job_id}")
def poll_refine_analysis(job_id: str, project: str,
                         since_result_revision: int | None = None) -> dict:
    p = _refine_project_or_404(project)
    try:
        return _analysis_jobs().poll(p, job_id, since_result_revision=since_result_revision)
    except KeyError as error:
        raise HTTPException(404, str(error)) from error


@router.post("/wb/refine/analysis/jobs/{job_id}/cancel")
def cancel_refine_analysis(job_id: str, req: AnalysisCancel) -> dict:
    p = _refine_project_or_404(req.project)
    try:
        return _analysis_jobs().cancel(p, job_id, req.observer_id)
    except KeyError as error:
        raise HTTPException(404, str(error)) from error


@router.post("/wb/refine/analysis/jobs/{job_id}/release")
def release_refine_analysis(job_id: str, req: AnalysisCancel) -> dict:
    p = _refine_project_or_404(req.project)
    try:
        return _analysis_jobs().release(p, job_id, req.observer_id)
    except KeyError:
        return {"released": False, "status": "expired"}


@router.get("/wb/refine/analysis")
def refine_analysis(project: str, node: str) -> dict:
    """Per-node analysis product (round-2 R3.5): the symmetry-unique
    interaction tables with their criteria and hydrogen provenance, the
    node's pore geometry, and the pending blocks (packing numbers, guest
    sites) each with a note. Computed lazily, disk-cached next to
    voids.json; the same product `analyze_packing` reads."""
    p = _refine_project_or_404(project)
    from crystalpilot.refine.analysis import cached_analysis
    try:
        path = cached_analysis(p, _valid_node(node))
        return json.loads(path.read_text(encoding="utf-8"))
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"analysis build failed: {e}") from e


@router.get("/wb/refine/validation-source")
def refine_validation_source(project: str, cif: str) -> dict:
    """Read the target's recorded node/export version, without a payload audit."""
    p = _refine_project_or_404(project)
    target = (p / cif).resolve()
    if p.resolve() not in target.parents:
        raise HTTPException(403, "validation target must stay inside the project")
    if not target.is_file():
        return {"source": None, "status": "missing"}
    from crystalpilot.refine.nodes import NodeStore
    from crystalpilot.refine.provenance import validation_source
    store = NodeStore(p)
    node = revision = None
    if target.name == "model.cif" and target.parent.parent == store.nodes_dir:
        node = _valid_node(target.parent.name)
        revision = store.node_meta(node).get("revision")
    return {"source": validation_source(target, node=node, revision=revision), "status": "recorded"}


@router.get("/wb/refine/voidmap")
def refine_voidmap(project: str, node: str) -> FileResponse:
    """Binarized whole-cell void mask (CCP4) for isosurface display."""
    p = _refine_project_or_404(project)
    from crystalpilot.refine.scene import cached_voids
    try:
        ccp4, _meta = cached_voids(p, _valid_node(node))
        if not ccp4.exists():
            # also the "every void fell below min_void_volume" case: then
            # nothing was masked, so there is no surface to draw
            raise HTTPException(404, "structure has no masked voids")
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"void map build failed: {e}") from e
    return FileResponse(ccp4, media_type="application/octet-stream")


@router.get("/wb/refine/data")
def refine_data(project: str, node: str) -> dict:
    """Reflection-data block for one node (Rint / n_unique / d_min /
    completeness / space group / wavelength / HKLF / SHEL).

    `source` is load-bearing: "node" means these are the node's own
    commit-time numbers, "computed" means the node predates the field and
    they were merged just now from the project's CURRENT reflection file -
    which is a different claim, because the data can have been swapped
    since. Recomputed blocks are disk-cached against the hkl's mtime+size;
    committed node.json files are never rewritten.
    """
    p = _refine_project_or_404(project)
    from crystalpilot.refine.scene import cached_data_block
    try:
        return cached_data_block(p, _valid_node(node))
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"data block failed: {e}") from e


@router.get("/wb/refine/peaks")
def refine_peaks(project: str, node: str) -> dict:
    """Difference-map Q-peak table for one node (peak positions in
    fractional coords + heights + nearest-atom context); computed by the
    same one-shot session as the map, disk-cached beside it."""
    p = _refine_project_or_404(project)
    from crystalpilot.refine.scene import cached_peaks
    try:
        path = cached_peaks(p, _valid_node(node))
        return json.loads(path.read_text(encoding="utf-8"))
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"peaks build failed: {e}") from e


# -- debug UI ---------------------------------------------------------------
ui_router = APIRouter()


@ui_router.get("/wb", response_class=HTMLResponse)
def debug_ui() -> str:
    return (Path(__file__).parent / "static" / "index.html").read_text(
        encoding="utf-8")
