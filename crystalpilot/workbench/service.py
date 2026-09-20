"""Server-side workbench session management.

One ProjectSession (= one Codex app-server process) per open project folder;
per-thread event channels with replay buffers for SSE reconnects; approval
gates that block the app-server callback until the UI decides; an idle reaper
that shuts down app-servers for projects nobody has touched in a while.

Framework-agnostic: routes.py adapts this to FastAPI.
"""
from __future__ import annotations

import os
import re
import threading
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Any

from . import i18n, preferences, registry
from .attachments import compose_message, resolve_attachments
from .agent_roles import (SUBAGENT_POLICIES, delegation_tier,
                          effective_model, ensure_agent_roles, normalize_subagent_policy,
                          role_names)
from .agents_md import (KNOWLEDGE_MODES, ensure_agents_md,
                        normalize_knowledge_mode)
from .core import RESULTS_DIRNAME, TaskSession, Workbench
from .background_jobs import BackgroundJobWatcher

APPROVAL_TIMEOUT_S = 900
IDLE_SHUTDOWN_S = 30 * 60

# permission modes: what each maps to (see workbench/ROUND4_NOTES.md).
# sandbox/turn knobs apply from the NEXT turn; changing the MCP column
# rebuilds the app-server (refused while a turn is running).
PERMISSION_MODES: dict[str, dict[str, Any]] = {
    "readonly": {"mcp_approval": "prompt", "mcp_readonly": True,
                 "sandbox": "read_only", "turn_approval": None,
                 "auto_approve": False},
    "copilot": {"mcp_approval": "writes", "mcp_readonly": False,
                "sandbox": "workspace_write", "turn_approval": None,
                "auto_approve": False},
    "auto": {"mcp_approval": "auto", "mcp_readonly": False,
             "sandbox": "workspace_write", "turn_approval": None,
             "auto_approve": False},
    "full": {"mcp_approval": "auto", "mcp_readonly": False,
             "sandbox": "full_access", "turn_approval": "deny_all",
             "auto_approve": True},
}
DEFAULT_PERMISSION_MODE = "auto"

#: unattended-shell approval blocklist (auto mode). On Windows codex raises a
#: commandExecution/fileChange approval for nearly every shell call, so an
#: unattended run would hang at the first one (r7/r8 lesson - previously
#: worked around with an external approval daemon). Requests matching NOTHING
#: here are auto-accepted in auto mode; matches stay queued for a human.
#: NB: match "format <drive>:", not a bare word-boundary format - PowerShell's Format-Table
#: false-positived 3/141 decisions in the r8 run.
#: this checkout's root, as a case-insensitive regex with either separator
#: (H:\CrystalPilot -> h:[\\/]crystalpilot followed by a separator, blank,
#: quote or the end); it does NOT match sibling
#: directories such as H:\CrystalPilot-campaigns, where the projects live.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_REPO_ROOT_RE = "".join(
    "[\\\\/]" if ch in "\\/" else re.escape(ch.lower()) for ch in str(_REPO_ROOT)
) + "(?=[\\\\/\\s\"'`]|$)"
_MUTATING_SHELL = (r"(remove-item|del\b|\brd\b|\brm\b|move-item|\bmv\b|set-content|"
                   r"out-file|add-content|copy-item|\bcp\b|\bmove\b|\bren\b|rename-item|"
                   r"\bgit\b[^\n]{0,80}?\b(checkout|reset|clean|commit|add|stash|rebase|merge)\b|>>?\s*)")

SHELL_APPROVAL_BLOCKLIST = (
    r"testapi\.txt",                      # credential file - never touched
    r"secrets[\\/]",                       # the whole secrets/ directory (2026-09-16 review)
    r"\be:[\\/]",                         # raw experimental data drive
    r"codex-home|\.codex\b",              # codex state (repo or user global)
    r"taskkill|stop-process|\bpskill\b|\bkill\b",
    r"shutdown|diskpart|format\s+[a-z]:|reg\s+(add|delete)",
    r"git\s+(push|remote)",
    r"(remove-item|del\b|\brd\b|\brm\b|move-item|\bmv\b|set-content|"
    r"out-file|add-content)[^\n]*crystalpilotdata",
    # the source checkout itself: reading is fine, mutating it unattended is
    # not (2026-09-16 review: nothing protected H:\CrystalPilot before)
    _MUTATING_SHELL + r"[^\n]*" + _REPO_ROOT_RE,
    # git -C <checkout> checkout|reset|... (the path comes before the verb)
    r"\bgit\b[^\n]{0,120}?" + _REPO_ROOT_RE
    + r"[^\n]{0,80}?\b(checkout|reset|clean|commit|add|stash|rebase|merge)\b",
)


def is_shell_approval(req: dict) -> bool:
    method = str(req.get("method") or "")
    return "commandExecution" in method or "fileChange" in method


def shell_approval_blocked_by(req: dict) -> str | None:
    """The blocklist pattern a shell/file approval hits, None when it
    clears the list (or is not a shell approval)."""
    import json as _json
    import re as _re
    if not is_shell_approval(req):
        return None
    detail = req.get("detail") or {}
    blob = (str(detail.get("command") or "") + " "
            + _json.dumps(detail, ensure_ascii=False, default=str)).lower()
    for pat in SHELL_APPROVAL_BLOCKLIST:
        if _re.search(pat, blob):
            return pat
    return None


def shell_approval_verdict(req: dict) -> str:
    """'accept' when an auto-mode shell/file approval clears the blocklist,
    'ask' when it must wait for a human (or is not a shell approval)."""
    if not is_shell_approval(req):
        return "ask"
    return "ask" if shell_approval_blocked_by(req) else "accept"

#: the gateway's reasoning ladder (ascending) - the fallback for a model
#: unknown to the codex catalog and to the provider's metadata. Probed live
#: 2026-09-05 (docs/reg1-2026-09-04/EFFORT-PROBE.md): gpt-6-astra runs a
#: turn at 'max' and 'ultra' (reasoning tokens present); 'minimal' is
#: rejected (2026-09-03 probe on gpt-5.6-sol).
EFFORT_CHOICES = ("low", "medium", "high", "xhigh", "max", "ultra")
#: the gateway's tier names, kept for tiers_for (campaign arm labels); the
#: sub-agent switch itself reads the top rung of the MODEL's ladder
TOP_EFFORT = "xhigh"
TOP_TIER_EFFORTS = EFFORT_CHOICES[EFFORT_CHOICES.index(TOP_EFFORT):]
AGGRESSIVE_EFFORTS = tuple(e for e in TOP_TIER_EFFORTS if e != TOP_EFFORT)


#: provider-level fallback ladders (a model the provider's metadata does not
#: describe). OpenRouter maps `reasoning.effort` onto each model's own
#: thinking controls with three unified levels.
EFFORT_LADDERS: dict[str, tuple[str, ...]] = {
    "openrouter": ("low", "medium", "high"),
}

#: the `subagents` project setting (2026-09-07 redesign, owner's ask): ONE
#: switch. "auto" (default) = on exactly when the effective effort is the
#: top rung of the model's ladder; "on" / "off" = the user's choice at any
#: effort. Legacy values map: top_tier -> auto, aggressive -> on.
SUBAGENT_MODES = ("auto", "on", "off")
_LEGACY_SUBAGENT_MODES = {"top_tier": "auto", "aggressive": "on"}


def normalize_subagent_mode(v) -> str:
    s = str(v if v is not None else "auto").strip().lower()
    s = _LEGACY_SUBAGENT_MODES.get(s, s)
    if s not in SUBAGENT_MODES:
        raise ValueError(f"subagents must be one of {SUBAGENT_MODES}, got {v!r}")
    return s


def provider_for(settings: dict) -> str | None:
    """The provider the project's NEW threads run on (override or config)."""
    return (settings.get("model_provider_override")
            or _model_info().get("provider") or None)


def model_for(settings: dict) -> str | None:
    """The model the next turn runs on (override or config default)."""
    return settings.get("model_override") or _model_info().get("model") or None


def effort_ladder(provider: str | None, model: str | None = None) -> tuple[str, ...]:
    """The reasoning levels `model` takes, ascending, from the first source
    that knows it: the codex catalog (bundled models + the custom entries
    CrystalPilot declared), then the provider's metadata (OpenRouter names
    `reasoning` among a model's supported parameters), then the provider's
    fallback ladder, then the gateway's. An empty tuple = the model has no
    reasoning control (the effort menu says so and no effort is sent)."""
    if model:
        try:
            from .model_catalog import effort_ladder_of
            lad = effort_ladder_of(model)
        except Exception:  # noqa: BLE001 - no kernel / unreadable catalog
            lad = None
        if lad:
            return tuple(lad)
        # an empty catalog ladder is "unknown" (a placeholder entry), not
        # "no reasoning": the provider's metadata decides next
        try:
            from .models import ladder_from_metadata
            lad = ladder_from_metadata(provider, model)
        except Exception:  # noqa: BLE001
            lad = None
        if lad is not None:
            return tuple(lad)
    return EFFORT_LADDERS.get(provider or "", EFFORT_CHOICES)


def tiers_for(ladder: tuple[str, ...]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(top-tier efforts, aggressive efforts) of a ladder: at or above the
    xhigh floor / above it when the ladder has that rung; otherwise the
    ladder's top rung serves as both. Kept for the campaign runner's arm
    labels; the switch itself is subagents_on."""
    if not ladder:
        return (), ()
    if TOP_EFFORT in ladder:
        i = ladder.index(TOP_EFFORT)
        return tuple(ladder[i:]), tuple(ladder[i + 1:])
    return (ladder[-1],), (ladder[-1],)


def effective_effort(settings: dict) -> str | None:
    """The effort the next turn runs at: the override, else the config
    default, snapped onto the model's ladder (an effort the model does not
    take falls to the ladder's top rung). None when the model has no
    reasoning control."""
    ladder = effort_ladder(provider_for(settings), model_for(settings))
    if not ladder:
        return None
    want = str(settings.get("effort_override") or _model_info().get("effort") or "")
    return want if want in ladder else ladder[-1]


def subagents_auto_default(settings: dict) -> bool:
    """What "auto" resolves to: the effective effort is the model's top rung."""
    ladder = effort_ladder(provider_for(settings), model_for(settings))
    return bool(ladder) and effective_effort(settings) == ladder[-1]


def subagents_mode(settings: dict) -> str:
    try:
        return normalize_subagent_mode(settings.get("subagents"))
    except ValueError:
        return "auto"


def subagents_on(settings: dict) -> bool:
    """The one rule behind the 开启子代理 switch: the user's choice, or at
    "auto" the top-rung default. On = the read-only role files exist, the
    AGENTS.md carries the proactive delegation section, and the engine
    keeps codex's multi-agent tools; off = none of those (the tools are
    removed at the process level, so the model cannot spawn anything)."""
    mode = subagents_mode(settings)
    if mode == "on":
        return True
    if mode == "off":
        return False
    return subagents_auto_default(settings)


def vision_for(settings: dict) -> bool | None:
    """Whether the project's effective model takes image input (True /
    False / None = unknown): the codex catalog's input modalities first
    (bundled and custom entries), then workbench/model_caps.py."""
    model = model_for(settings)
    try:
        from .model_catalog import catalog_entry
        e = catalog_entry(model)
    except Exception:  # noqa: BLE001
        e = None
    if e is not None:
        return "image" in (e.get("input_modalities") or [])
    from .model_caps import image_input_supported
    return image_input_supported(provider_for(settings), model)


def delegation_tier_for(settings: dict) -> str:
    """"aggressive" (the proactive delegation template + the role files)
    when the sub-agent switch is on, else "off". The former "hint" tier is
    retired: a switch that is on means the sub-agents are used, not
    mentioned."""
    return "aggressive" if subagents_on(settings) else "off"


def delegation_for(settings: dict) -> bool:
    """Whether delegation is active (roles exist, the template carries the
    delegation paragraph)."""
    return subagents_on(settings)


def _catalog_stamp() -> float | None:
    """mtime of the generated model catalog - the engine reads it at start,
    so a newer file means a restart is pending."""
    try:
        from .model_catalog import CATALOG_PATH
        return CATALOG_PATH.stat().st_mtime
    except Exception:  # noqa: BLE001
        return None


def _model_info() -> dict:
    """Model + effort as configured in the isolated CODEX_HOME config.toml
    (display-only in the composer badge)."""
    import os
    import tomllib
    from .core import ENGINE_ROOT
    home = Path(os.environ.get("CRYSTALPILOT_CODEX_HOME",
                               ENGINE_ROOT / "codex-home"))
    try:
        cfg = tomllib.loads((home / "config.toml").read_text(encoding="utf-8"))
        return {"model": cfg.get("model"),
                "effort": cfg.get("model_reasoning_effort"),
                # the provider the config runs by default and every
                # [model_providers.<id>] a project may switch a NEW thread to
                "provider": cfg.get("model_provider"),
                "providers": sorted((cfg.get("model_providers") or {}).keys())}
    except Exception:  # noqa: BLE001
        return {"model": None, "effort": None, "provider": None,
                "providers": []}


#: what the crystal IS, declared by the owner (the analysis tab suggests
#: one from the product and the owner confirms). Kept as plain strings so a
#: future class costs one entry here and one label in the UI.
STRUCTURE_CLASSES = ("small_molecule", "macrocycle", "cage", "framework",
                     "salt_cocrystal")


def normalize_structure_class(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip().lower()
    return s if s in STRUCTURE_CLASSES else None


def _policy_or_default(v) -> str:
    try:
        return normalize_subagent_policy(v)
    except ValueError:
        return normalize_subagent_policy(None)


def project_settings_dict(path, settings: dict,
                          permission_mode: str,
                          engine: dict | None = None) -> dict:
    """One assembly point for GET/POST settings responses (the routes'
    project-not-open fallback uses it too - keep the shapes identical).
    "model"/"effort" are the EFFECTIVE next-turn values (override wins
    over config.toml; the effort is snapped onto the model's ladder).
    `engine` = ProjectSession.engine_info() when the project is open."""
    info = _model_info()
    model_ov = settings.get("model_override") or None
    effort_ov = settings.get("effort_override") or None
    provider_ov = settings.get("model_provider_override") or None
    provider = provider_ov or info.get("provider")
    model = model_ov or info.get("model")
    ladder = effort_ladder(provider, model)
    effort = effective_effort(settings)
    _, aggressive = tiers_for(ladder)
    mode = subagents_mode(settings)
    on = subagents_on(settings)
    try:
        from .model_catalog import catalog_entry
        entry = catalog_entry(model)
    except Exception:  # noqa: BLE001 - no kernel on this machine
        entry = None
    return {"path": str(path),
            "permission_mode": permission_mode,
            "display_name": settings.get("display_name") or None,
            "allow_iucr_upload": bool(
                settings.get("allow_iucr_upload", False)),
            "auto_shell_approvals": bool(
                settings.get("auto_shell_approvals", True)),
            "enable_specialists": bool(
                settings.get("enable_specialists", False)),
            # owner-declared structure class (round-2 R6 / owner's ask):
            # the analysis tab opens the blocks that fit it and the agent
            # reads it from get_project_brief; None = not declared
            "structure_class": normalize_structure_class(
                settings.get("structure_class")),
            "structure_classes": list(STRUCTURE_CLASSES),
            # the sub-agent switch (2026-09-07): auto | on | off, plus what
            # it resolves to right now (roles + proactive template + the
            # kernel's multi-agent tools all follow `active`)
            "subagents": mode,
            "subagent_choices": list(SUBAGENT_MODES),
            "delegation": {
                "active": on,
                "tier": "aggressive" if on else "off",
                "mode": mode,
                "auto_default": subagents_auto_default(settings),
                "top_effort": ladder[-1] if ladder else None,
                "aggressive_efforts": list(aggressive),
                "effective_effort": effort,
                "roles": role_names(),
            },
            "model": model,
            "effort": effort,
            "model_default": info["model"],
            "effort_default": info["effort"],
            "model_override": model_ov,
            "effort_override": effort_ov,
            # the MODEL's own reasoning levels, as they are (catalog /
            # provider metadata); empty = no reasoning control
            "effort_choices": list(ladder),
            "effort_default_for_model": (entry or {}).get("default_effort"),
            "model_info": {
                "display_name": (entry or {}).get("display_name") or model,
                "input_modalities": (entry or {}).get("input_modalities"),
                "context_window": (entry or {}).get("context_window"),
                "in_catalog": entry is not None,
            },
            # provider (2026-09-06, second provider for tests): fixed at
            # thread start, so an override reaches NEW threads (or a fork)
            "model_provider": provider,
            "model_provider_override": provider_ov,
            "model_provider_default": info.get("provider"),
            "model_providers": list(info.get("providers") or []),
            # image input of the effective model (True / False / null =
            # unknown); False makes the MCP server keep pictures on disk
            "vision": vision_for(settings),
            # ka1 ablation switch: which AGENTS.md template the project
            # runs under and whether the skill tools are registered
            "knowledge_mode": normalize_knowledge_mode(
                settings.get("knowledge_mode")),
            "knowledge_modes": list(KNOWLEDGE_MODES),
            # per-project context controls (process-level in codex: applied
            # when the engine (re)starts)
            "context_window_override": settings.get("context_window_override") or None,
            "auto_compact_token_limit": settings.get("auto_compact_token_limit") or None,
            "engine": dict(engine or {})}


class Channel:
    """Ordered event buffer with blocking reads (SSE-friendly).

    Readers are either threads (``read_since``) or asyncio tasks
    (``wait_async``): the SSE route awaits instead of parking a worker
    thread per browser connection (the threadpool has 40 tokens shared with
    every synchronous route). ``close()`` wakes every reader and makes the
    route send ``channel_closed`` so a browser holding a channel whose
    project session was released (idle reaper, shutdown) re-syncs instead of
    receiving keepalives from an orphan forever (2026-09-16 root cause of
    "the page stops updating until a reload")."""

    def __init__(self, maxlen: int = 2000) -> None:
        self.seq = 0
        # a fresh channel (project reopened, server restarted) restarts seq
        # at 0; the client compares this token to know that its Last-Event-ID
        # belongs to a dead numbering and must re-bootstrap instead
        self.generation = uuid.uuid4().hex[:12]
        self._buf: deque[tuple[int, dict]] = deque(maxlen=maxlen)
        self._cond = threading.Condition()
        self.closed = False
        self._async_waiters: set[tuple[Any, Any]] = set()

    @property
    def oldest(self) -> int:
        """Smallest seq still buffered (seq + 1 when nothing is buffered).
        A resume cursor below oldest - 1 means events were lost."""
        with self._cond:
            return self._buf[0][0] if self._buf else self.seq + 1

    def push(self, ev: dict) -> None:
        with self._cond:
            self.seq += 1
            self._buf.append((self.seq, ev))
            self._cond.notify_all()
            waiters = list(self._async_waiters)
        self._wake(waiters)

    def close(self) -> None:
        with self._cond:
            self.closed = True
            self._cond.notify_all()
            waiters = list(self._async_waiters)
        self._wake(waiters)

    @staticmethod
    def _wake(waiters: list[tuple[Any, Any]]) -> None:
        for loop, evt in waiters:
            try:
                loop.call_soon_threadsafe(evt.set)
            except RuntimeError:      # the reader's loop is gone
                pass

    def peek_since(self, after: int) -> list[tuple[int, dict]]:
        with self._cond:
            return [(s, e) for s, e in self._buf if s > after]

    def read_since(self, after: int, timeout: float = 15.0) -> list[tuple[int, dict]]:
        """Events with seq > after; blocks up to timeout if none pending."""
        with self._cond:
            out = [(s, e) for s, e in self._buf if s > after]
            if out or self.closed:
                return out
            self._cond.wait(timeout)
            return [(s, e) for s, e in self._buf if s > after]

    async def wait_async(self, after: int, timeout: float = 15.0) -> list[tuple[int, dict]]:
        """asyncio counterpart of read_since: no thread is held while waiting."""
        import asyncio
        out = self.peek_since(after)
        if out or self.closed:
            return out
        loop = asyncio.get_running_loop()
        evt = asyncio.Event()
        key = (loop, evt)
        with self._cond:
            self._async_waiters.add(key)
            # re-check under the lock: a push between peek and register
            out = [(s, e) for s, e in self._buf if s > after]
            if out or self.closed:
                self._async_waiters.discard(key)
                return out
        try:
            await asyncio.wait_for(evt.wait(), timeout)
        except asyncio.TimeoutError:
            pass
        finally:
            with self._cond:
                self._async_waiters.discard(key)
        return self.peek_since(after)


class ProjectSession:
    """A live workbench on one project folder."""

    def __init__(self, path: str | Path, auto_approve: bool = False) -> None:
        registry.ensure_trusted(path)
        self.auto_approve = auto_approve
        self.feed = Channel()                       # project-level aggregate
        self._channels: dict[str, Channel] = {}     # thread_id -> channel
        self._sessions: dict[str, TaskSession] = {}
        self._busy: set[str] = set()
        self._pending: dict[str, dict] = {}         # approval_id -> slot
        self._session_allow: set[tuple] = set()     # accept_for_session keys
        self._lock = threading.Lock()
        self.last_active = time.time()
        self._title_lock = threading.Lock()
        self._closed = False
        #: a settings change that needs a process-level codex flag arrived
        #: while a turn was running: rebuild when it ends
        self._restart_pending = False
        self._agents_md_dirty = False  # AGENTS.md changed while a turn ran
        self._running_catalog_stamp: float | None = None
        self.wb = self._build_workbench(path)
        self.wb.start()
        registry.record_recent(self.wb.project.path)
        # detached solver jobs (run_shelxt detach=true) are owned by the
        # MCP tool process; this thread mirrors their files as
        # background_job events so a SHELXT that outlives the turn stays
        # visible in the conversation and the status rail (2026-09-18:
        # two NU-1000 turns were stopped by the user while an invisible
        # 13-minute space-group search was about to finish)
        self._jobs_watch = BackgroundJobWatcher(
            Path(self.wb.project.path), emit=self._emit_background_job,
            owner_hint=self._busy_owner)
        self._jobs_watch.start()

    def _build_workbench(self, path: str | Path) -> Workbench:
        from .core import ProjectState
        # one ProjectState (= one ensure_agents_md) per build: opening
        # twice made /projects/open report "current" for a file it had
        # just written
        st = ProjectState.open(path, delegate_for=delegation_tier_for)
        mode = (st.settings.get("permission_mode")
                or DEFAULT_PERMISSION_MODE)
        if mode not in PERMISSION_MODES:
            mode = DEFAULT_PERMISSION_MODE
        self.permission_mode = mode
        spec = PERMISSION_MODES[mode]
        # the catalog codex reads at start: bundled models of the active
        # kernel + CrystalPilot's custom entries (regenerated when stale)
        try:
            from .model_catalog import ensure_catalog
            ensure_catalog()
        except Exception:  # noqa: BLE001 - no kernel to read: codex uses its own
            pass
        self._running_catalog_stamp = _catalog_stamp()
        return Workbench(st, event_cb=self._on_core_event,
                         approval_cb=self._on_approval,
                         mcp_approval=spec["mcp_approval"],
                         mcp_readonly=spec["mcp_readonly"],
                         # only a KNOWN text-only model loses the pictures
                         mcp_images=(vision_for(st.settings) is not False),
                         # the kernel side of the sub-agent switch
                         multi_agent=subagents_on(st.settings),
                         context_window=st.settings.get("context_window_override") or None,
                         auto_compact_limit=st.settings.get("auto_compact_token_limit") or None)

    def _rebuild_workbench(self, event: dict) -> None:
        """Close and rebuild the app-server + MCP pair (their env is baked
        at spawn); refused while a turn runs. `event` is pushed after."""
        with self._lock:
            if self._busy:
                raise RuntimeError(
                    f"cannot change {event.get('kind')} while a turn is running")
        path = self.wb.project.path
        try:
            self.wb.close()
        except Exception:  # noqa: BLE001
            pass
        with self._lock:
            self._sessions.clear()
        self.wb = self._build_workbench(path)
        self.wb.start()
        self._push(None, event)

    # -- permission modes ---------------------------------------------------
    def set_permission_mode(self, mode: str) -> dict:
        if mode not in PERMISSION_MODES:
            raise ValueError(f"unknown permission mode {mode!r}")
        with self._lock:
            if self._busy:
                raise RuntimeError("cannot change permission mode while a "
                                   "turn is running")
        old_spec = PERMISSION_MODES[self.permission_mode]
        new_spec = PERMISSION_MODES[mode]
        self.wb.project.settings["permission_mode"] = mode
        self.wb.project.save()
        self.permission_mode = mode
        mcp_changed = (old_spec["mcp_approval"] != new_spec["mcp_approval"]
                       or old_spec["mcp_readonly"] != new_spec["mcp_readonly"])
        if mcp_changed:
            # MCP config is baked into the app-server spawn: transparent
            # rebuild (threads resume lazily by id on the new process)
            path = self.wb.project.path
            try:
                self.wb.close()
            except Exception:  # noqa: BLE001
                pass
            with self._lock:
                self._sessions.clear()
            self.wb = self._build_workbench(path)
            self.wb.start()
        self._push(None, {"kind": "permission_mode", "mode": mode,
                          "rebuilt": mcp_changed})
        self._push_settings()
        return self.settings()

    def settings(self) -> dict:
        return project_settings_dict(self.wb.project.path,
                                     self.wb.project.settings,
                                     self.permission_mode,
                                     engine=self.engine_info())

    def update_project_settings(self, patch: dict) -> dict:
        """Persist plain per-project flags.

        allow_iucr_upload: read live by submit_iucr_checkcif - no rebuild.
        enable_specialists: the MCP server builds its tool list at spawn, so
        flipping it triggers the same transparent rebuild as an MCP
        permission change (409 while a turn is running).
        """
        if "allow_iucr_upload" in patch:
            self.wb.project.settings["allow_iucr_upload"] = bool(
                patch["allow_iucr_upload"])
            self.wb.project.save()
        if "display_name" in patch:
            # the sidebar's rename: one line, whitespace-collapsed, capped;
            # empty clears back to the directory name
            v = patch["display_name"]
            if v is not None:
                v = " ".join(str(v).split())[:80] or None
            self.wb.project.settings["display_name"] = v
            self.wb.project.save()
        if "structure_class" in patch:
            v = patch["structure_class"]
            if v is not None and normalize_structure_class(v) is None:
                raise ValueError(
                    f"structure_class must be one of {STRUCTURE_CLASSES} "
                    f"or null")
            self.wb.project.settings["structure_class"] = (
                normalize_structure_class(v))
            self.wb.project.save()
        # model / provider / effort / sub-agents / context. Model and effort
        # travel with every turn and the provider with new threads (or a
        # fork); what codex takes only at the process level - the
        # multi-agent tools, the image tool, the context window, the
        # compaction threshold, a catalog entry for a model it did not know
        # - rebuilds the engine when no turn is running, or right after the
        # current one (_sync_engine / _restart_pending).
        st = self.wb.project.settings
        learned: dict | None = None
        if "model_provider_override" in patch:
            # applied FIRST so an effort in the same patch is validated
            # against the new provider/model ladder; a [model_providers.
            # <id>] key of the isolated config.toml
            v = patch["model_provider_override"]
            if v is not None:
                v = str(v).strip() or None
                known = _model_info().get("providers") or []
                if v is not None and known and v not in known:
                    raise ValueError(
                        f"model_provider_override must be one of {known} "
                        f"or null")
            st["model_provider_override"] = v
            self.wb.project.save()
        if "model_override" in patch:
            v = patch["model_override"]
            if v is not None:
                v = str(v).strip()[:128] or None
            st["model_override"] = v
            self.wb.project.save()
            if v:
                # declare the model to codex (context window, ladder,
                # modalities) when it is not in the catalog yet
                try:
                    from .models import learn_model
                    learned = learn_model(provider_for(st), v)
                except Exception as e:  # noqa: BLE001 - offline / unknown provider
                    learned = {"error": f"{type(e).__name__}: {e}"[:200]}
        if "effort_override" in patch:
            v = patch["effort_override"]
            ladder = effort_ladder(provider_for(st), model_for(st))
            if v is not None:
                v = str(v)
                if v not in ladder:
                    raise ValueError(
                        f"effort_override must be one of {ladder}")
            st["effort_override"] = v
            self.wb.project.save()
        elif "model_provider_override" in patch or "model_override" in patch:
            # the stored effort must exist on the new model's ladder: fall
            # to the top rung explicitly rather than leaving a value the
            # provider would silently remap
            ladder = effort_ladder(provider_for(st), model_for(st))
            cur = st.get("effort_override")
            if cur is not None and cur not in ladder:
                st["effort_override"] = ladder[-1] if ladder else None
                self.wb.project.save()
        if "subagents" in patch:
            st["subagents"] = normalize_subagent_mode(patch["subagents"])   # ValueError
            self.wb.project.save()
        for key in ("context_window_override", "auto_compact_token_limit"):
            if key in patch:
                v = patch[key]
                if v in (None, "", 0, "0"):
                    v = None
                else:
                    v = int(v)
                    if not 1000 <= v <= 50_000_000:
                        raise ValueError(
                            f"{key} must be between 1000 and 50000000 tokens")
                st[key] = v
                self.wb.project.save()
        if any(k in patch for k in ("model_provider_override", "model_override",
                                    "effort_override", "subagents")):
            # the role files pin the sub-agents to the model and the
            # template variant follows the switch - re-render AFTER every
            # value of this patch is stored, whatever the key order
            self._refresh_delegation()
        if "knowledge_mode" in patch:
            # ablation switch (ka1): rewrites AGENTS.md for the new mode
            # and rebuilds the workbench, because the MCP env (which
            # decides whether the skill tools exist) is baked at spawn
            new_mode = normalize_knowledge_mode(patch["knowledge_mode"])
            old_mode = normalize_knowledge_mode(
                self.wb.project.settings.get("knowledge_mode"))
            if new_mode != old_mode:
                with self._lock:
                    if self._busy:
                        raise RuntimeError(
                            "cannot change knowledge_mode while a turn is "
                            "running")
                self.wb.project.settings["knowledge_mode"] = new_mode
                self.wb.project.save()
                path = self.wb.project.path
                tier = delegation_tier_for(self.wb.project.settings)
                info = ensure_agents_md(
                    path, new_mode, tier != "off",
                    aggressive=(tier == "aggressive"),
                    language=preferences.language())
                try:
                    self.wb.close()
                except Exception:  # noqa: BLE001
                    pass
                with self._lock:
                    self._sessions.clear()
                self.wb = self._build_workbench(path)
                self.wb.start()
                self._push(None, {"kind": "knowledge_mode", "mode": new_mode,
                                  "agents_md": info})
        if "enable_specialists" in patch:
            new = bool(patch["enable_specialists"])
            old = bool(self.wb.project.settings.get("enable_specialists",
                                                    False))
            if new != old:
                with self._lock:
                    if self._busy:
                        raise RuntimeError(
                            "cannot toggle specialists while a turn is "
                            "running")
                self.wb.project.settings["enable_specialists"] = new
                self.wb.project.save()
                path = self.wb.project.path
                try:
                    self.wb.close()
                except Exception:  # noqa: BLE001
                    pass
                with self._lock:
                    self._sessions.clear()
                self.wb = self._build_workbench(path)
                self.wb.start()
                self._push(None, {"kind": "specialists_toggled",
                                  "enabled": new})
        self._sync_engine(learned)
        self._push_settings()
        return self.settings()

    def _refresh_delegation(self) -> dict:
        """Re-render AGENTS.md (the proactive delegation variant or the plain
        template) and write/remove the per-project role files after a model,
        effort or switch change. Codex reads AGENTS.md and the roles when a
        thread starts or resumes, so the change reaches new threads at once
        and running ones when the engine restarts (each sub-agent spawns its
        own MCP process from the role file)."""
        st = self.wb.project
        on = subagents_on(st.settings)
        tier = "aggressive" if on else "off"
        mode = st.settings.get("knowledge_mode")
        info = ensure_agents_md(st.path, mode, on, aggressive=on,
                                language=preferences.language())
        roles = ensure_agent_roles(st.path, on, mode,
                                   effective_model(st.settings))
        st.agents_md = info
        st.agent_roles = roles
        self._push(None, {"kind": "delegation", "active": on, "tier": tier,
                          "agents_md": info.get("action"),
                          "roles_written": roles.get("written"),
                          "roles_removed": roles.get("removed")})
        return {"active": on, "tier": tier, "agents_md": info,
                "roles": roles}

    def apply_language(self, language: str) -> dict:
        """The interface language changed (Settings > Appearance): rewrite
        AGENTS.md so the agent narrates and delivers in that language, then
        restart the engine so resumed threads read the new file (codex only
        reads AGENTS.md when a thread starts or resumes). While a turn runs
        the restart is deferred to the end of the turn."""
        st = self.wb.project
        on = subagents_on(st.settings)
        info = ensure_agents_md(st.path, st.settings.get("knowledge_mode"), on,
                                aggressive=on, language=language)
        st.agents_md = info
        changed = info.get("action") == "written"
        restarted = False
        if changed:
            restarted = self._rebuild_or_defer(
                {"kind": "engine_restarted", "reason": "language",
                 "language": language})
            if not restarted:
                self._agents_md_dirty = True
        self._push(None, {"kind": "language", "language": language,
                          "agents_md": info.get("action"),
                          "restart_pending": self.restart_pending})
        return {"language": language, "agents_md": info,
                "restarted": restarted, "restart_pending": self.restart_pending}

    def _turn_kwargs(self) -> dict:
        from openai_codex import Sandbox
        spec = PERMISSION_MODES[self.permission_mode]
        kwargs: dict[str, Any] = {"sandbox": getattr(Sandbox, spec["sandbox"])}
        if spec["turn_approval"] == "deny_all":
            from openai_codex import ApprovalMode
            kwargs["approval_mode"] = ApprovalMode.deny_all
        # ALWAYS pass model/effort explicitly: a codex Thread remembers the
        # last values it ran with, so omitting the kwarg means "keep the
        # thread's previous effort", NOT "use the config default" - clearing
        # an override must actively restore the default (observed live:
        # cleared override kept sending the old effort and 400'd).
        ps = self.wb.project.settings
        model = model_for(ps)
        if model:
            kwargs["model"] = str(model)
        effort = effective_effort(ps)      # None = the model has no ladder
        if effort:
            from openai_codex.types import ReasoningEffort
            try:
                kwargs["effort"] = ReasoningEffort(str(effort))
            except ValueError:      # unknown config value - let codex decide
                pass
        return kwargs

    # -- engine sync (codex flags that live at the process level) -----------
    def _engine_flags(self) -> dict:
        """What the settings ask the engine to run with."""
        st = self.wb.project.settings
        return {"multi_agent": subagents_on(st),
                "images": vision_for(st) is not False,
                "context_window": st.get("context_window_override") or None,
                "auto_compact_limit": st.get("auto_compact_token_limit") or None,
                "catalog": _catalog_stamp()}

    def _running_flags(self) -> dict:
        """What the running engine was started with."""
        wb = self.wb
        return {"multi_agent": bool(getattr(wb, "multi_agent", True)),
                "images": bool(getattr(wb, "mcp_images", True)),
                "context_window": getattr(wb, "context_window", None) or None,
                "auto_compact_limit": getattr(wb, "auto_compact_limit", None) or None,
                "catalog": self._running_catalog_stamp}

    @property
    def restart_pending(self) -> bool:
        return bool(self._restart_pending) or self._engine_flags() != self._running_flags()

    def engine_info(self) -> dict:
        """The running engine as the settings report it."""
        wb = self.wb
        kinfo = getattr(wb, "kernel_info", None) or {}
        return {"kernel_version": kinfo.get("version"),
                "kernel_path": kinfo.get("path"),
                "multi_agent": bool(getattr(wb, "multi_agent", True)),
                "images": bool(getattr(wb, "mcp_images", True)),
                "context_window": getattr(wb, "context_window", None) or None,
                "auto_compact_limit": getattr(wb, "auto_compact_limit", None) or None,
                "restart_pending": self.restart_pending}

    def _rebuild_or_defer(self, event: dict) -> bool:
        """Rebuild now when idle; otherwise mark the restart pending (the
        turn worker applies it when the turn ends). Returns True when the
        rebuild happened."""
        with self._lock:
            busy = bool(self._busy)
        if busy:
            self._restart_pending = True
            return False
        try:
            self._rebuild_workbench(event)
        except RuntimeError:
            self._restart_pending = True
            return False
        self._restart_pending = False
        return True

    def _sync_engine(self, learned: dict | None = None) -> None:
        if self._engine_flags() == self._running_flags():
            self._restart_pending = False
            return
        self._rebuild_or_defer({"kind": "engine_restarted", "reason": "settings",
                                **({"learned_model": learned} if learned else {})})

    def _apply_pending_restart(self) -> None:
        if not self._restart_pending:
            return
        if self._engine_flags() == self._running_flags() and not self._agents_md_dirty:
            self._restart_pending = False
            return
        try:
            self._rebuild_workbench({"kind": "engine_restarted",
                                     "reason": "deferred_settings"})
        except Exception:  # noqa: BLE001 - a turn slipped in; try after it
            return
        self._restart_pending = False
        self._agents_md_dirty = False
        self._push_settings()

    def _push_settings(self) -> None:
        """Every open view gets the whole settings record after a change,
        whoever made it (the browser, a CLI script, a config.toml edit)."""
        try:
            self._push(None, {"kind": "settings", "settings": self.settings()})
        except Exception:  # noqa: BLE001 - the push is a courtesy
            pass

    # -- codex-backed thread operations ------------------------------------
    def compact(self, thread_id: str) -> dict:
        """Compact the thread's context now (codex thread/compact/start).
        Refused while a turn runs on it; the compaction runs as a turn of
        its own and reports through compaction_* events."""
        task = self.get_thread(thread_id)
        with self._lock:
            if thread_id in self._busy:
                raise RuntimeError("a turn is running on this thread; "
                                   "compaction can start when it ends")
        self.wb.compact_thread(thread_id)
        self._note(thread_id, {"kind": "compaction_requested",
                               "task_id": task.task_id})
        self.last_active = time.time()
        return {"ok": True, "thread_id": thread_id}

    def rename(self, thread_id: str, title: str) -> dict:
        with self._title_lock:
            rec = self.wb.rename_thread(thread_id, title)
        self._push(thread_id, {"kind": "thread_renamed", "title": rec["title"]})
        return rec

    def _start_auto_title(self, thread_id: str, message: str, attachments: list[str]) -> None:
        from .thread_titles import naming_context, fallback_title, generate_title
        with self._title_lock:
            rec = next((r for r in self.wb.project.threads if r["thread_id"] == thread_id), {})
            if self._closed or rec.get("title_source") != "unnamed":
                return
        settings = dict(self.wb.project.settings)
        model, provider = model_for(settings), provider_for(settings)
        lang = i18n.current()  # the naming thread below runs outside the request
        context = naming_context(self.wb.project.path, settings, message, attachments)
        with self._title_lock:
            claimed = self.wb.claim_auto_title(thread_id, fallback_title(context, lang), model)
        if claimed is None:
            return
        self._push(thread_id, {"kind": "thread_renamed", "title": claimed["title"]})

        def name() -> None:
            with self._title_lock:
                rec = next((r for r in self.wb.project.threads if r["thread_id"] == thread_id), {})
                if self._closed or rec.get("title_source") != "auto_pending":
                    return
            try:
                title = generate_title(context, model=model, provider=provider, lang=lang)
            except Exception:  # naming must never interrupt a scientific turn or expose credentials
                title = None
            with self._title_lock:
                if self._closed:
                    return
                rec = self.wb.finish_auto_title(thread_id, title)
                if rec is None:
                    return
                try:
                    self.wb._client.thread_set_name(thread_id, rec["title"])
                except Exception:
                    pass
                self._push(thread_id, {"kind": "thread_renamed", "title": rec["title"]})
        threading.Thread(target=name, daemon=True, name=f"title-{thread_id[:8]}").start()

    def fork(self, thread_id: str, title: str | None = None) -> TaskSession:
        """A new thread continuing `thread_id`'s conversation on the
        project's CURRENT provider/model (the way a provider switch reaches
        a running conversation)."""
        with self._lock:
            if thread_id in self._busy:
                raise RuntimeError("a turn is running on this thread; fork "
                                   "when it ends")
        self.get_thread(thread_id)       # resumed on this engine first
        st = self.wb.project.settings
        task = self.wb.fork_task(
            thread_id, title=title,
            model_provider=st.get("model_provider_override") or None,
            images=(vision_for(st) is not False))
        with self._lock:
            self._sessions[task.thread_id] = task
        self.last_active = time.time()
        return task

    # -- events ------------------------------------------------------------
    def channel(self, thread_id: str) -> Channel:
        with self._lock:
            if thread_id not in self._channels:
                self._channels[thread_id] = Channel()
            return self._channels[thread_id]

    def _push(self, thread_id: str | None, ev: dict) -> None:
        ev.setdefault("ts", time.time())
        if thread_id:
            ev.setdefault("thread_id", thread_id)
            self.channel(thread_id).push(ev)
        else:
            # project-scoped system events (permission_mode,
            # specialists_toggled): fan out to every open thread channel so
            # the conversation view can render a system row
            with self._lock:
                chans = list(self._channels.values())
            for ch in chans:
                ch.push(dict(ev))
        self.feed.push(ev)

    def _on_core_event(self, ev: dict) -> None:
        # approval_request / approval_decision arrive here from core
        self._push(ev.get("thread_id"), dict(ev))

    # -- approvals ---------------------------------------------------------
    def _on_approval(self, req: dict) -> dict:
        spec = PERMISSION_MODES.get(self.permission_mode,
                                    PERMISSION_MODES[DEFAULT_PERMISSION_MODE])
        if self.auto_approve or spec["auto_approve"]:
            return {"decision": "accept"}
        # auto mode: trust our own MCP server's first-write elicitation, so a
        # fully-autonomous run is not blocked by the one-time trust prompt
        if (self.permission_mode == "auto"
                and "elicitation" in (req.get("method") or "")
                and req.get("mcp_server") == "crystalpilot"):
            return {"decision": "accept"}
        # auto mode: unattended shell/file approvals pass a protected-area
        # blocklist instead of waiting for a human; matches stay queued
        if (self.permission_mode == "auto"
                and self.wb.project.settings.get("auto_shell_approvals", True)
                and shell_approval_verdict(req) == "accept"):
            self._push(req.get("thread_id"),
                       {"kind": "approval_decision",
                        "approval_id": req["approval_id"],
                        "method": req.get("method"),
                        "decision": "accept", "auto": True,
                        "policy": "shell_blocklist"})
            return {"decision": "accept"}
        # auto mode is UNATTENDED: a protected-area hit is answered now
        # with a rejection - the model reroutes - instead of sitting in the
        # queue for a human who is not there (R7 A2 continuation,
        # 2026-09-06 16:33: `New-Item .codex\\tmp` waited 10 minutes)
        if (self.permission_mode == "auto"
                and self.wb.project.settings.get("auto_shell_approvals", True)
                and is_shell_approval(req)):
            pat = shell_approval_blocked_by(req)
            self._push(req.get("thread_id"),
                       {"kind": "approval_decision",
                        "approval_id": req["approval_id"],
                        "method": req.get("method"),
                        "decision": "reject", "auto": True,
                        "policy": "shell_blocklist_reject",
                        "blocked_by": pat})
            return {"decision": "reject"}
        if self._allow_key(req) in self._session_allow:
            self._push(req.get("thread_id"),
                       {"kind": "approval_decision",
                        "approval_id": req["approval_id"],
                        "method": req.get("method"),
                        "decision": "accept", "auto": True})
            return {"decision": "accept"}
        gate = threading.Event()
        slot = {"gate": gate, "decision": None, "req": req}
        with self._lock:
            self._pending[req["approval_id"]] = slot
        try:
            if not gate.wait(timeout=APPROVAL_TIMEOUT_S):
                self._push(req.get("thread_id"),
                           {"kind": "approval_timeout",
                            "approval_id": req["approval_id"]})
                return {"decision": "reject"}
            return slot["decision"] or {"decision": "reject"}
        finally:
            with self._lock:
                self._pending.pop(req["approval_id"], None)

    @staticmethod
    def _allow_key(req: dict) -> tuple:
        """Session-allowlist key for '本次会话总是允许': same MCP tool, or the
        same approval method for non-MCP requests."""
        import re as _re
        tool = None
        m = _re.search(r'tool "([\w-]+)"', str(req.get("mcp_message") or ""))
        if m:
            tool = m.group(1)
        return (req.get("mcp_server"), tool or req.get("method"))

    def decide(self, approval_id: str, decision: str) -> bool:
        with self._lock:
            slot = self._pending.get(approval_id)
        if slot is None:
            return False
        if decision == "accept_for_session":
            self._session_allow.add(self._allow_key(slot["req"]))
            decision = "accept"
        slot["decision"] = {"decision": decision}
        slot["gate"].set()
        return True

    def pending_approvals(self) -> list[dict]:
        with self._lock:
            return [dict(s["req"]) for s in self._pending.values()]

    # -- threads -----------------------------------------------------------
    def new_thread(self, title: str | None = None) -> TaskSession:
        task = self.wb.new_task(
            title=title,
            model_provider=self.wb.project.settings.get(
                "model_provider_override") or None,
            images=(vision_for(self.wb.project.settings) is not False))
        with self._lock:
            self._sessions[task.thread_id] = task
        return task

    def get_thread(self, thread_id: str) -> TaskSession:
        with self._lock:
            task = self._sessions.get(thread_id)
        if task is None:
            task = self.wb.resume_task(thread_id)
            with self._lock:
                self._sessions[thread_id] = task
        return task

    def is_busy(self, thread_id: str) -> bool:
        with self._lock:
            return thread_id in self._busy

    def busy_threads(self) -> set[str]:
        with self._lock:
            return set(self._busy)

    def send(self, thread_id: str, message: str,
             attachments: list[dict] | None = None,
             allow_concurrent: bool = False,
             output_schema: dict | None = None) -> None:
        """Run one turn in a worker thread, streaming into the channels."""
        task = self.get_thread(thread_id)
        with self._lock:
            if thread_id in self._busy:
                raise RuntimeError("a turn is already running on this thread")
            if self._busy and not allow_concurrent:
                # PROJECT-level exclusivity: two agents mutating the same
                # .crystalpilot concurrently swapped crystal.hkl mid-turn in
                # practice-770 (HKLF5 under a running HKLF4 SHELXL job ->
                # fake R1=0.687, cross-injected nodes, duplicate deliveries)
                raise RuntimeError(
                    "another thread is mid-turn on this project "
                    f"({', '.join(sorted(self._busy))}); concurrent agents "
                    "on one project corrupt the shared session/crystal.hkl. "
                    "Wait for it, or pass allow_concurrent=true only for "
                    "read-only work.")
            self._busy.add(thread_id)
        self.last_active = time.time()
        images, ctx_lines, att_names = resolve_attachments(
            self.wb.project.path, attachments)
        full_message = compose_message(message, ctx_lines)
        # one event object: logged (gets its eid) and pushed live
        user_ev = {
            "kind": "user_message", "text": message, "task_id": task.task_id,
            "ts": time.time(),
            **({"attachments": att_names} if att_names else {}),
        }
        self.wb._log_event(thread_id, user_ev)
        self._push(thread_id, user_ev)

        try:
            self._start_auto_title(thread_id, message, att_names)
        except Exception:  # optional naming never blocks sending the user's message
            pass

        turn_kwargs = self._turn_kwargs()

        def run() -> None:
            try:
                self._await_mcp_ready(thread_id, task)
                for ev in task.send(full_message, turn_kwargs=turn_kwargs,
                                    images=images or None,
                                    display_text=message,
                                    attachment_names=att_names or None,
                                    output_schema=output_schema,
                                    log_user=False):
                    ev.setdefault("task_id", task.task_id)
                    self._watch_mcp_health(ev)
                    self._push(thread_id, ev)
            except Exception as e:  # noqa: BLE001
                self._push(thread_id, {"kind": "client_error",
                                       "error": str(e)[:400]})
            finally:
                with self._lock:
                    self._busy.discard(thread_id)
                    quiet = not self._busy
                self.last_active = time.time()
                self._push(thread_id, {"kind": "idle", "task_id": task.task_id,
                                       "artifacts": self.artifacts(task.task_id)})
                if quiet and self._restart_pending:
                    # a settings change that needs a process-level codex
                    # flag waited for this turn to end
                    self._apply_pending_restart()
                if quiet:
                    # turn-idle display prewarm: the user's first click after
                    # a turn (scene/Q-peaks/voids) hits warm caches instead
                    # of paying the build (incl. solvent-mask recompute)
                    try:
                        from crystalpilot.refine.scene import \
                            prewarm_display_cache
                        threading.Thread(
                            target=prewarm_display_cache,
                            args=(self.wb.project.path,), daemon=True,
                            name="display-prewarm").start()
                    except Exception:  # noqa: BLE001 - warming is optional
                        pass

        threading.Thread(target=run, daemon=True,
                         name=f"turn-{thread_id[:8]}").start()

    def interrupt(self, thread_id: str) -> bool:
        with self._lock:
            task = self._sessions.get(thread_id)
            busy = thread_id in self._busy
        if task is None or not busy:
            return False
        task.interrupt()
        return True

    def steer(self, thread_id: str, message: str,
              attachments: list[dict] | None = None) -> dict | None:
        """Inject guidance into the running turn. Returns the steer receipt
        ({"status": "submitted" | "failed", "error"?, "steer_eid"}) once the
        words are in the transcript, None when the thread is idle (caller
        should send a normal message instead)."""
        with self._lock:
            task = self._sessions.get(thread_id)
            busy = thread_id in self._busy
        if task is None or not busy:
            return None
        images, ctx_lines, att_names = resolve_attachments(
            self.wb.project.path, attachments)
        eid, receipt = task.steer(compose_message(message, ctx_lines),
                                  images=images or None,
                                  display_text=message,
                                  attachment_names=att_names or None)
        if eid is None or receipt is None:
            return None
        self.last_active = time.time()
        self._push(thread_id, {
            "kind": "user_message", "text": message, "steer": True,
            "task_id": task.task_id,
            **({"eid": eid} if eid > 0 else {}),
            **({"attachments": att_names} if att_names else {}),
        })
        # round-3 R6: the receipt rides the live channel right behind the
        # bubble, so the client can show 已送达模型 / 送达失败 (and retry)
        self._push(thread_id, {**receipt, "task_id": task.task_id})
        return receipt

    # -- MCP health --------------------------------------------------------
    #: transport-death signatures (verbatim from the r6 campaign, where a
    #: killed MCP process degraded a whole campaign to 166 shell commands:
    #: "tool call failed for `crystalpilot/...` Caused by: Transport closed")
    _MCP_DEATH = re.compile(
        r"transport closed|connection closed|transport error|"
        r"server (?:not found|disconnected)|broken pipe", re.I)

    def _watch_mcp_health(self, ev: dict) -> None:
        """Two consecutive transport-death tool errors -> mcp_down system
        event. codex has no reconnect API; the remedy is restart_engine
        (threads resume lazily on the rebuilt process, which respawns MCP)."""
        if ev.get("kind") != "tool_completed":
            return
        err = str(ev.get("error") or "")
        if err and self._MCP_DEATH.search(err):
            self._mcp_fail_streak = getattr(self, "_mcp_fail_streak", 0) + 1
            if self._mcp_fail_streak >= 2 and not getattr(self, "_mcp_down",
                                                          False):
                self._mcp_down = True
                self._push(None, {
                    "kind": "mcp_down", "detail": err[:200],
                    "action": ("crystallography MCP transport is dead for "
                               "this engine process - restart the engine "
                               "(POST /projects/restart_engine) and resend; "
                               "the thread resumes with tools restored")})
        else:
            # any tool round-trip WITHOUT a transport error proves the MCP
            # channel is alive (tool-level failures included)
            self._mcp_fail_streak = 0

    def restart_engine(self) -> dict:
        """Transparent engine rebuild (same path as a permission-mode MCP
        change): close -> rebuild -> start; threads resume lazily by id on
        the new process, which respawns the MCP server."""
        with self._lock:
            if self._busy:
                raise RuntimeError(
                    "cannot restart the engine while a turn is running "
                    f"({', '.join(sorted(self._busy))}) - interrupt first")
        path = self.wb.project.path
        try:
            self.wb.close()
        except Exception:  # noqa: BLE001
            pass
        with self._lock:
            self._sessions.clear()
        self.wb = self._build_workbench(path)
        self.wb.start()
        self._mcp_down = False
        self._mcp_fail_streak = 0
        self._push(None, {"kind": "engine_restarted"})
        return self.settings()

    #: how long the first turn of a fresh/resumed thread waits for the
    #: crystalpilot MCP to register its tools; a server that is not even
    #: listed after MCP_ABSENT_GIVEUP_S is not going to be (codex spawns it
    #: on thread start/resume, so absence means "this codex does not do that")
    MCP_READY_WAIT_S = 75.0
    MCP_ABSENT_GIVEUP_S = 20.0
    MCP_POLL_S = 2.0

    def _await_mcp_ready(self, thread_id: str, task) -> None:
        """Block the turn worker until the crystallography tools exist.

        codex 0.147 starts a thread's MCP servers in the background after
        thread/start and thread/resume and begins the turn at once; a turn
        whose first model call precedes the crystalpilot registration runs
        with shell only (resumed org_hsl thread, 2026-09-05: the agent
        reported "situation_report 工具未提供" and gave up). The wait is
        bounded and narrated as system rows so the user sees why the
        first reply is late."""
        if not getattr(task, "awaiting_mcp", False):
            return
        task.awaiting_mcp = False
        t0 = time.time()
        st = self.mcp_status(timeout_s=5.0)
        if st.get("present") and (st.get("n_tools") or 0) > 0:
            return
        # logged as well as pushed: a slow first reply must still explain
        # itself after a reload
        self._note(thread_id, {"kind": "mcp_startup", "server": "crystalpilot",
                               "status": "waiting", "task_id": task.task_id})
        while True:
            elapsed = time.time() - t0
            if elapsed >= self.MCP_READY_WAIT_S:
                break
            if not st.get("present") and elapsed >= self.MCP_ABSENT_GIVEUP_S:
                break
            time.sleep(self.MCP_POLL_S)
            st = self.mcp_status(timeout_s=5.0)
            if st.get("present") and (st.get("n_tools") or 0) > 0:
                self._note(thread_id, {
                    "kind": "mcp_startup", "server": "crystalpilot",
                    "status": "ready", "n_tools": int(st["n_tools"]),
                    "seconds": round(time.time() - t0, 1),
                    "task_id": task.task_id})
                return
        self._note(thread_id, {
            "kind": "mcp_startup", "server": "crystalpilot",
            "status": "timeout", "seconds": round(time.time() - t0, 1),
            "present": bool(st.get("present")), "error": st.get("error"),
            "task_id": task.task_id})

    # -- background solver jobs -------------------------------------------
    def _busy_owner(self) -> str | None:
        """The one thread mid-turn right now (the turn that just started a
        detached job), None when none or several are busy."""
        with self._lock:
            return next(iter(self._busy)) if len(self._busy) == 1 else None

    def _emit_background_job(self, ev: dict, owner: str | None,
                             persist: bool) -> None:
        if self._closed:
            return
        if owner and persist:
            self._note(owner, ev)          # transcript line + live push
        else:
            self._push(owner, ev)          # live only (fan-out when no owner)

    def background_jobs(self) -> list[dict]:
        """Tracked solver jobs as live-only background_job events (no eid):
        appended to a transcript bootstrap so a reload shows a job the
        transcript never recorded (server restart, no owning turn)."""
        w = getattr(self, "_jobs_watch", None)
        return w.snapshot_events() if w is not None else []

    def _note(self, thread_id: str, ev: dict) -> None:
        """A service-side system row that belongs to the thread's history:
        transcript first (eid), then the live channel - one event object."""
        ev.setdefault("ts", time.time())
        try:
            self.wb._log_event(thread_id, ev)
        except Exception:  # noqa: BLE001 - a failed log must not stop the turn
            pass
        self._push(thread_id, ev)

    def mcp_status(self, timeout_s: float = 20.0) -> dict:
        """Probe the app-server for the crystalpilot MCP server's toolset.

        Covers the failure mode the tool_completed death watch cannot see:
        the MCP child freezing DURING startup (Windows DLL-loader freeze,
        r11 case-c - process alive at ~2s CPU, zero transport errors, codex
        proceeds with an empty toolset and the agent improvises shell
        fallbacks). Codex spawns the MCP lazily at first turn, so an absent
        server before any send is normal - callers poll after sending."""
        out: dict = {"present": False, "n_tools": 0, "error": None}

        def probe() -> None:
            try:
                from openai_codex.generated.v2_all import (
                    ListMcpServerStatusResponse)
                resp = self.wb._client.request(
                    "mcpServerStatus/list", {"detail": "toolsAndAuthOnly"},
                    response_model=ListMcpServerStatusResponse)
                for s in resp.data:
                    if s.name == "crystalpilot":
                        out["present"] = True
                        out["n_tools"] = len(s.tools or {})
            except Exception as e:  # noqa: BLE001
                out["error"] = f"{type(e).__name__}: {e}"

        t = threading.Thread(target=probe, daemon=True,
                             name="mcp-status-probe")
        t.start()
        t.join(timeout_s)
        if t.is_alive():
            out["error"] = f"probe timed out after {timeout_s}s"
        return out

    def threads_meta(self) -> list[dict]:
        with self._lock:
            busy = set(self._busy)
        return [dict(t, busy=t["thread_id"] in busy) for t in self.wb.tasks()]

    # -- artifacts ---------------------------------------------------------
    def artifacts(self, task_id: str) -> list[dict]:
        root = self.wb.project.results_root / task_id
        out: list[dict] = []
        if root.exists():
            for p in sorted(root.rglob("*")):
                if p.is_file() and p.stat().st_size > 0:
                    out.append({"rel": str(p.relative_to(root)),
                                "path": str(p), "size": p.stat().st_size})
        return out[:100]

    def close(self) -> None:
        self._closed = True
        w = getattr(self, "_jobs_watch", None)
        if w is not None:
            w.stop()
        # every browser holding one of our channels learns the session is
        # gone (channel_closed) and re-opens the project; before this the SSE
        # generators kept sending keepalives from orphaned channels while all
        # new events went to the next session's channels
        with self._lock:
            chans = list(self._channels.values())
        for ch in chans:
            ch.close()
        self.feed.close()
        self.wb.close()


class WorkbenchPool:
    """All open projects; owns the idle reaper."""

    def __init__(self) -> None:
        self._sessions: dict[str, ProjectSession] = {}   # key: lower resolved path
        self._thread_index: dict[str, str] = {}          # thread_id -> project key
        self._opening: dict[str, threading.Lock] = {}   # key -> in-flight construction
        self._lock = threading.Lock()
        self._reaper = threading.Thread(target=self._reap, daemon=True,
                                        name="workbench-reaper")
        self._reaper.start()
        #: config.toml watched for edits made outside the UI (an editor, a
        #: CLI script): every open view is told and re-reads its settings
        self.config_mtime: float = 0.0
        self.config_changed_at: float | None = None
        try:
            from .codex_config import config_mtime
            self.config_mtime = config_mtime()
        except Exception:  # noqa: BLE001
            pass
        self._config_watch = threading.Thread(target=self._watch_config, daemon=True,
                                              name="config-watch")
        self._config_watch.start()

    def _watch_config(self) -> None:
        from .codex_config import config_mtime
        catalog_seen = _catalog_stamp()
        while True:
            time.sleep(2.0)
            try:
                mt = config_mtime()
            except Exception:  # noqa: BLE001
                continue
            if mt and mt != self.config_mtime:
                self.config_mtime = mt
                self.config_changed_at = time.time()
                for ps in self.sessions():
                    try:
                        ps._push(None, {"kind": "config_changed", "mtime": mt})
                        ps._push_settings()
                    except Exception:  # noqa: BLE001
                        pass
            # the generated catalog changed (a model learned in another
            # project, a kernel upgrade): engines started on the old file
            # rebuild now when idle, at turn end when busy
            cs = _catalog_stamp()
            if cs != catalog_seen:
                catalog_seen = cs
                for ps in self.sessions():
                    try:
                        ps._sync_engine()
                        ps._push_settings()
                    except Exception:  # noqa: BLE001
                        pass

    def register_thread_of(self, thread_id: str, project: str | Path) -> ProjectSession | None:
        """Self-heal the thread index: a thread the state file lists under
        `project` (created by another process, or before a reopen) is
        indexed on demand so its channel can be served."""
        ps = self.get(project)
        if ps is None:
            return None
        if any(t["thread_id"] == thread_id for t in ps.wb.tasks()):
            self.register_thread(thread_id, ps)
            return ps
        return None

    @staticmethod
    def _key(path: str | Path) -> str:
        return os.path.normcase(str(Path(path).resolve()))

    def open(self, path: str | Path, auto_approve: bool = False) -> ProjectSession:
        key = self._key(path)
        with self._lock:
            ps = self._sessions.get(key)
            if ps is None:
                # one construction per path: a second /projects/open that
                # arrives while the first is still spawning its engine used
                # to build a second ProjectSession (and a second codex
                # app-server, which failed with "failed to initialize sqlite
                # state runtime" against the first one's databases - seen
                # live 2026-09-16 12:11 and 12:14). The late caller now waits
                # for the first construction and gets the same session.
                opening = self._opening.get(key)
                if opening is None:
                    opening = self._opening[key] = threading.Lock()
                    owner = True
                else:
                    owner = False
        if ps is not None:
            ps.auto_approve = auto_approve
            ps.last_active = time.time()
            return ps
        if not owner:
            with opening:            # wait for the constructing caller
                pass
            with self._lock:
                ps = self._sessions.get(key)
            if ps is not None:
                ps.auto_approve = auto_approve
                ps.last_active = time.time()
                return ps
            return self.open(path, auto_approve=auto_approve)
        with opening:
            try:
                ps = ProjectSession(path, auto_approve=auto_approve)
                with self._lock:
                    self._sessions[key] = ps
                    for t in ps.wb.tasks():
                        self._thread_index[t["thread_id"]] = key
            finally:
                with self._lock:
                    self._opening.pop(key, None)
        return ps

    def get(self, path: str | Path) -> ProjectSession | None:
        with self._lock:
            return self._sessions.get(self._key(path))

    def register_thread(self, thread_id: str, ps: ProjectSession) -> None:
        with self._lock:
            self._thread_index[thread_id] = self._key(ps.wb.project.path)

    def by_thread(self, thread_id: str) -> ProjectSession | None:
        with self._lock:
            key = self._thread_index.get(thread_id)
            return self._sessions.get(key) if key else None

    def sessions(self) -> list[ProjectSession]:
        with self._lock:
            return list(self._sessions.values())

    def close_all(self) -> None:
        for ps in self.sessions():
            try:
                ps.close()
            except Exception:  # noqa: BLE001
                pass
        with self._lock:
            self._sessions.clear()
            self._thread_index.clear()

    def _reap(self) -> None:
        while True:
            time.sleep(60)
            now = time.time()
            for key, ps in list(self._sessions.items()):
                with ps._lock:
                    busy = bool(ps._busy) or bool(ps._pending)
                if not busy and now - ps.last_active > IDLE_SHUTDOWN_S:
                    try:
                        ps.close()
                    except Exception:  # noqa: BLE001
                        pass
                    with self._lock:
                        self._sessions.pop(key, None)


RESULTS = RESULTS_DIRNAME  # re-export for routes
