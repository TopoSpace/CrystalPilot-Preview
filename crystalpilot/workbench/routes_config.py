"""Routes behind the settings dialog and the composer's model menu: the
kernel, providers and their keys, model lists, global config defaults, the
codex-backed thread operations (compact / rename / fork), skills, and the
native folder picker for "open project".

Keys never leave the server: the provider records carry `has_key` and a
modification time, the connection test reports HTTP outcomes only.
"""
from __future__ import annotations

import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel

from . import codex_config, i18n, kernel, model_catalog, models, preferences, providers
from .i18n import msg
from .routes import _by_thread_or_404, _session_or_404, pool

router = APIRouter(prefix="/api")
log = logging.getLogger("crystalpilot.workbench.config")

#: the top-level config.toml keys the settings dialog may edit
GLOBAL_KEYS = ("model", "model_provider", "model_reasoning_effort",
               "model_reasoning_summary", "model_context_window",
               "model_auto_compact_token_limit")


def _broadcast_settings() -> None:
    for ps in pool.sessions():
        try:
            ps._push_settings()
        except Exception:  # noqa: BLE001
            pass


# -- kernel --------------------------------------------------------------
@router.get("/kernel")
def kernel_info() -> dict:
    info = kernel.kernel_info()
    try:
        cat = model_catalog.build()
        meta = cat.get("_crystalpilot") or {}
        info["catalog"] = {"n_bundled": meta.get("n_bundled"),
                           "n_custom": meta.get("n_custom"),
                           "path": str(model_catalog.CATALOG_PATH)}
    except Exception as e:  # noqa: BLE001
        info["catalog"] = {"error": f"{type(e).__name__}: {e}"[:200]}
    info["config_path"] = str(codex_config.config_path())
    info["config_mtime"] = codex_config.config_mtime()
    info["open_projects"] = [
        {"path": str(ps.wb.project.path),
         "kernel_version": (getattr(ps.wb, "kernel_info", None) or {}).get("version"),
         "restart_pending": ps.restart_pending,
         "busy": bool(ps.busy_threads())}
        for ps in pool.sessions()]
    return info


# -- providers -------------------------------------------------------------
@router.get("/providers")
def list_providers() -> dict:
    cfg = codex_config.load()
    return {"providers": providers.list_providers(),
            "default": cfg.get("model_provider"),
            "config_path": str(codex_config.config_path())}


class ProviderUpsert(BaseModel):
    id: str
    name: str | None = None
    base_url: str
    wire_api: str | None = None
    auth_mode: Literal["managed_api_key", "environment", "none"] | None = None
    env_key: str | None = None
    #: Blank/None keeps the stored key; removal is a separate explicit action.
    api_key: str | None = None
    remove_api_key: bool = False
    http_headers: dict[str, str] | None = None
    query_params: dict[str, str] | None = None
    env_http_headers: dict[str, str] | None = None
    request_max_retries: int | None = None
    stream_max_retries: int | None = None
    stream_idle_timeout_ms: int | None = None


@router.post("/providers")
def upsert_provider(req: ProviderUpsert) -> dict:
    try:
        payload = (req.model_dump(exclude_unset=True) if hasattr(req, "model_dump")
                   else req.dict(exclude_unset=True))
        payload.setdefault("name", None)
        payload["pid"] = payload.pop("id")
        out = providers.upsert_provider(**payload)
    except (codex_config.ConfigError, ValueError) as e:
        raise HTTPException(400, str(e)) from e
    _broadcast_settings()
    return out


@router.delete("/providers/{pid}")
def delete_provider(pid: str) -> dict:
    try:
        out = providers.remove_provider(pid)
    except (codex_config.ConfigError, ValueError) as e:
        raise HTTPException(400, str(e)) from e
    except KeyError:
        raise HTTPException(404, f"no provider {pid!r}") from None
    _broadcast_settings()
    return out


class ProviderTest(BaseModel):
    id: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    http_headers: dict[str, str] | None = None
    query_params: dict[str, str] | None = None


@router.post("/providers/test")
def test_provider(req: ProviderTest) -> dict:
    try:
        res = providers.test_connection(req.id, req.base_url, req.api_key,
                                        req.http_headers, req.query_params)
        res.pop("ids", None)       # the full id list stays server-side
        return res
    except (codex_config.ConfigError, ValueError) as e:
        raise HTTPException(400, str(e)) from e


class ProviderRef(BaseModel):
    id: str


@router.post("/providers/default")
def set_default_provider(req: ProviderRef) -> dict:
    try:
        out = providers.set_default_provider(req.id)
    except (codex_config.ConfigError, ValueError) as e:
        raise HTTPException(400, str(e)) from e
    except KeyError:
        raise HTTPException(404, f"no provider {req.id!r}") from None
    _broadcast_settings()
    return out


# -- models ----------------------------------------------------------------
@router.get("/models")
def list_models(provider: str | None = None, refresh: bool = False,
                include_hidden: bool = False) -> dict:
    pid = provider or codex_config.load().get("model_provider")
    if not pid:
        raise HTTPException(400, "no provider configured")
    try:
        return models.list_models(pid, refresh=refresh, include_hidden=include_hidden)
    except KeyError:
        raise HTTPException(404, f"no provider {pid!r}") from None


# -- global config defaults -------------------------------------------------
@router.get("/config")
def get_config() -> dict:
    cfg = codex_config.load()
    return {k: cfg.get(k) for k in GLOBAL_KEYS} | {
        "agents": dict(cfg.get("agents") or {}),
        "config_path": str(codex_config.config_path()),
        "config_mtime": codex_config.config_mtime(),
        "model_catalog_json": cfg.get("model_catalog_json"),
    }


@router.post("/config")
def set_config(patch: dict = Body(...)) -> dict:
    """Write global defaults. A key set to null / "" / 0 is removed from
    the file (codex falls back to its own default)."""
    unknown = sorted(set(patch) - set(GLOBAL_KEYS))
    if unknown:
        raise HTTPException(400, f"not editable here: {unknown}")
    try:
        for key, value in patch.items():
            if value in (None, "", 0, "0"):
                codex_config.set_top_level(key, None)
                continue
            if key in ("model_context_window", "model_auto_compact_token_limit"):
                value = int(value)
                if not 1000 <= value <= 50_000_000:
                    raise codex_config.ConfigError(
                        f"{key} must be between 1000 and 50000000 tokens")
            elif key == "model_provider":
                if str(value) not in (codex_config.load().get("model_providers") or {}):
                    raise codex_config.ConfigError(f"unknown provider {value!r}")
                value = str(value)
            else:
                value = str(value).strip()
            codex_config.set_top_level(key, value)
    except (codex_config.ConfigError, ValueError) as e:
        raise HTTPException(400, str(e)) from e
    _broadcast_settings()
    return get_config()


# -- interface language ------------------------------------------------------
class LanguageReq(BaseModel):
    language: str


@router.get("/language")
def get_language() -> dict:
    """The interface language the workbench remembers for the agent side."""
    return {"language": preferences.language()}


@router.post("/language")
def set_language(req: LanguageReq) -> dict:
    """Remember the interface language and make the agent follow it: every
    open project gets its AGENTS.md rewritten and its engine restarted (or
    the restart deferred to the end of the running turn)."""
    if i18n.normalize(req.language) != req.language.strip().lower():
        raise HTTPException(400, f"unsupported language {req.language!r}")
    lang = preferences.set_language(req.language)
    projects = []
    for ps in pool.sessions():
        try:
            res = ps.apply_language(lang)
        except Exception as e:  # noqa: BLE001 - one project must not block the others
            res = {"error": f"{type(e).__name__}: {e}"[:200]}
        projects.append({"path": str(ps.wb.project.path), **res})
    return {"language": lang, "projects": projects}


# -- codex-backed thread operations -----------------------------------------
class ThreadOp(BaseModel):
    thread_id: str
    project: str | None = None
    title: str | None = None


def _ps_for(req: ThreadOp):
    ps = pool.by_thread(req.thread_id)
    if ps is None and req.project:
        ps = pool.register_thread_of(req.thread_id, req.project)
    if ps is None:
        return _by_thread_or_404(req.thread_id)
    return ps


@router.post("/threads/compact")
def compact_thread(req: ThreadOp) -> dict:
    ps = _ps_for(req)
    try:
        return ps.compact(req.thread_id)
    except RuntimeError as e:
        raise HTTPException(409, str(e)) from e
    except KeyError as e:
        raise HTTPException(404, str(e)) from e


@router.post("/threads/rename")
def rename_thread(req: ThreadOp) -> dict:
    if not (req.title or "").strip():
        raise HTTPException(400, "title required")
    ps = _ps_for(req)
    try:
        rec = ps.rename(req.thread_id, req.title or "")
    except KeyError as e:
        raise HTTPException(404, str(e)) from e
    return {"thread": rec, "threads": ps.threads_meta()}


@router.post("/threads/fork")
def fork_thread(req: ThreadOp) -> dict:
    ps = _ps_for(req)
    try:
        task = ps.fork(req.thread_id, title=req.title)
    except RuntimeError as e:
        raise HTTPException(409, str(e)) from e
    except KeyError as e:
        raise HTTPException(404, str(e)) from e
    pool.register_thread(task.thread_id, ps)
    return {"thread_id": task.thread_id, "task_id": task.task_id,
            "threads": ps.threads_meta()}


@router.get("/skills")
def list_skills(project: str) -> dict:
    ps = _session_or_404(project)
    try:
        res = ps.wb._client._request_raw("skills/list", {"cwds": [str(ps.wb.project.path)]})
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"skills/list failed: {e}") from e
    out: list[dict[str, Any]] = []
    for entry in (res.get("data") or []) if isinstance(res, dict) else []:
        if not isinstance(entry, dict):
            continue
        for sk in entry.get("skills") or []:
            if isinstance(sk, dict):
                out.append({"name": sk.get("name"), "description": sk.get("description"),
                            "path": sk.get("path"), "scope": sk.get("scope"),
                            "enabled": sk.get("enabled", True)})
        for err in entry.get("errors") or []:
            if isinstance(err, dict):
                out.append({"name": None, "error": err.get("message"), "path": err.get("path")})
    return {"skills": out}


# -- native folder picker -----------------------------------------------------
class PickFolder(BaseModel):
    title: str | None = None
    initial: str | None = None


_PICK_PS = r'''
Add-Type -AssemblyName System.Windows.Forms
$d = New-Object System.Windows.Forms.FolderBrowserDialog
$d.Description = $env:CP_PICK_TITLE
$d.ShowNewFolderButton = $true
if ($env:CP_PICK_INITIAL -and (Test-Path $env:CP_PICK_INITIAL)) { $d.SelectedPath = $env:CP_PICK_INITIAL }
$owner = New-Object System.Windows.Forms.Form
$owner.TopMost = $true
$owner.ShowInTaskbar = $false
$owner.Opacity = 0
$owner.StartPosition = 'CenterScreen'
$owner.Show()
$owner.Activate()
$r = $d.ShowDialog($owner)
$owner.Close()
if ($r -eq [System.Windows.Forms.DialogResult]::OK) { Write-Output $d.SelectedPath }
'''


@router.post("/system/pick_folder")
def pick_folder(req: PickFolder) -> dict:
    """Open the operating system's folder dialog ON THE SERVER MACHINE (the
    workbench is a local app: the browser and the server share a desktop)
    and return the chosen path, or null when cancelled."""
    if os.name != "nt":
        raise HTTPException(501, "the native folder picker is Windows-only here")
    env = dict(os.environ)
    env["CP_PICK_TITLE"] = (req.title or msg("选择项目文件夹", "Choose a project folder"))[:200]
    env["CP_PICK_INITIAL"] = req.initial or ""
    t0 = time.time()
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass",
             "-Command", _PICK_PS],
            capture_output=True, text=True, env=env, timeout=600,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        return {"path": None, "cancelled": True, "reason": "timeout"}
    except OSError as e:
        raise HTTPException(500, f"cannot open the folder dialog: {e}") from e
    chosen = (out.stdout or "").strip().splitlines()
    path = chosen[-1].strip() if chosen else ""
    if not path:
        return {"path": None, "cancelled": True,
                "elapsed_s": round(time.time() - t0, 1),
                **({"error": (out.stderr or "")[:300]} if out.returncode else {})}
    return {"path": str(Path(path)), "cancelled": False,
            "elapsed_s": round(time.time() - t0, 1)}
