"""Workbench core: project registry + Codex app-server session + normalized events.

Design: CrystalPilot supplies the crystallography domain (AGENTS.md, engine CLI,
results conventions) while the unmodified Codex runtime supplies threads, turns,
streaming, shell, sandboxing and approvals. Everything runs against an ISOLATED
CODEX_HOME so the user's personal Codex installation is never touched.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator

from openai_codex import CodexConfig, LocalImageInput, TextInput
from openai_codex.api import Thread
from openai_codex.client import CodexClient
from openai_codex.generated.v2_all import (AskForApproval, AskForApprovalValue,
                                           SandboxMode, ThreadStartParams)

from . import kernel
from .agent_roles import effective_model, ensure_agent_roles
from .agents_md import ensure_agents_md, normalize_knowledge_mode
from ..runtime_paths import engine_python

ENGINE_ROOT = Path(__file__).resolve().parents[2]       # H:\CrystalPilot
CODEX_HOME = Path(os.environ.get("CRYSTALPILOT_CODEX_HOME",
                                 str(ENGINE_ROOT / "codex-home")))
RESULTS_DIRNAME = "CrystalPilot Results"
STATE_FILENAME = ".crystalpilot-workbench.json"

EventCallback = Callable[[dict[str, Any]], None]
ApprovalCallback = Callable[[dict[str, Any]], dict[str, Any]]   # -> {"decision": ...}


def _gateway_env() -> dict[str, str]:
    """Runtime env for the Codex subprocess.

    The API key is NOT placed in the environment: the model provider's
    auth.command (print_token.py) supplies it on demand, so neither the
    app-server env nor any agent shell command inherits it. RUST_LOG=warn
    suppresses TRACE spawn logs that would record child environments.
    """
    env = {"CODEX_HOME": str(CODEX_HOME), "RUST_LOG": "warn"}
    try:
        # the kernel's own tool directory (rg.exe) in front of PATH: the SDK
        # does that only for its pinned pip build, not for a vendored one
        env.update(kernel.kernel_env())
    except FileNotFoundError:
        pass
    return env


def _engine_overrides(multi_agent: bool = True, images: bool = True,
                      context_window: int | None = None,
                      auto_compact_limit: int | None = None) -> tuple[str, ...]:
    """Process-level codex config for one project's engine, beyond the MCP
    table. These are `--config` overrides because codex 0.153 applies
    them per app-server process only: a thread/start `config` carrying
    features.multi_agent / tools.view_image changed nothing (probed
    2026-09-07, the request tool list kept multi_agent_v1 and view_image),
    while the same keys on the command line did. Changing any of them
    therefore means rebuilding the project's engine (service._rebuild_
    workbench), which the service does when no turn is running.

    multi_agent=False removes codex's spawn_agent/wait_agent/... tools -
    the kernel side of the "开启子代理" switch; images=False removes
    view_image for a text-only model; context_window / auto_compact_limit
    override the catalog's context size and the auto-compaction threshold
    (tokens) for this project."""
    out: list[str] = []
    if not multi_agent:
        out.append("features.multi_agent=false")
    if not images:
        out.append("tools.view_image=false")
    if context_window:
        out.append(f"model_context_window={int(context_window)}")
    if auto_compact_limit:
        out.append(f"model_auto_compact_token_limit={int(auto_compact_limit)}")
    return tuple(out)


def _toml_lit(s: str) -> str:
    """TOML literal string: single quotes, backslash-safe (Windows paths)."""
    if "'" in s:
        raise ValueError(f"path contains a single quote, cannot TOML-quote: {s!r}")
    return f"'{s}'"


#: [mcp_servers.<name>] key of the codex config override below; the model
#: sees the tools under the namespace `mcp__<name>`.
MCP_SERVER_NAME = "crystalpilot"


def _mcp_overrides(project_path: Path, approval: str | None = None,
                   readonly: bool = False,
                   knowledge_mode: str | None = None,
                   images: bool = True) -> tuple[str, ...]:
    """Register the per-project CrystalPilot MCP server via --config argv
    (codex-home/config.toml stays untouched). Disable with
    CRYSTALPILOT_DISABLE_MCP=1. Approval mode: explicit arg, else
    CRYSTALPILOT_MCP_APPROVAL (auto|writes|prompt; default auto - see
    workbench/MCP_NOTES.md). readonly=True makes the MCP server itself refuse
    every mutating tool (the MCP process is NOT under the codex sandbox, so
    the read-only permission mode needs this server-side gate).
    knowledge_mode='tools_only' (ka1 ablation) reaches the MCP process as
    CRYSTALPILOT_KNOWLEDGE_MODE so refine.registry skips the skill tools."""
    if os.environ.get("CRYSTALPILOT_DISABLE_MCP") == "1":
        return ()
    py = engine_python(ENGINE_ROOT)
    if approval is None:
        approval = os.environ.get("CRYSTALPILOT_MCP_APPROVAL", "auto")
    if approval not in ("auto", "writes", "prompt"):
        approval = "auto"
    env_items = ["PYTHONUTF8='1'"]
    if readonly:
        env_items.append("CRYSTALPILOT_MCP_READONLY='1'")
    if normalize_knowledge_mode(knowledge_mode) == "tools_only":
        env_items.append("CRYSTALPILOT_KNOWLEDGE_MODE='tools_only'")
    if not images:
        # a text-only model (workbench/model_caps.py): the MCP server keeps
        # the pictures on disk for the user and sends none to the model
        env_items.append("CRYSTALPILOT_NO_IMAGES='1'")
    env = "{" + ",".join(env_items) + "}"
    return (
        f"mcp_servers.{MCP_SERVER_NAME}.command={_toml_lit(str(py))}",
        "mcp_servers.crystalpilot.args=['-X','utf8','-m','crystalpilot.mcp',"
        f"'--project',{_toml_lit(str(project_path))}]",
        f"mcp_servers.crystalpilot.cwd={_toml_lit(str(ENGINE_ROOT))}",
        f"mcp_servers.crystalpilot.env={env}",
        "mcp_servers.crystalpilot.startup_timeout_sec=180",
        "mcp_servers.crystalpilot.tool_timeout_sec=3900",  # full-CBF frame stages (per-frame pycbf parse) legitimately run tens of minutes
        f"mcp_servers.crystalpilot.approval_mode={_toml_lit(approval)}",
    )


def _redact(obj: Any) -> Any:
    """Best-effort scrub of the api key pattern from anything user-visible."""
    s = json.dumps(obj, ensure_ascii=False, default=str)
    s = re.sub(r"cpl-[0-9a-f]{16,}", "***", s)
    return json.loads(s)


# ----------------------------------------------------------------------------
@dataclass
class ProjectState:
    path: Path
    threads: list[dict[str, Any]] = field(default_factory=list)
    settings: dict[str, Any] = field(default_factory=dict)
    #: what ensure_agents_md did on open (action / warning) - surfaced by
    #: /projects/open so a kept-foreign AGENTS.md is never silent
    agents_md: dict[str, Any] = field(default_factory=dict)
    #: what ensure_agent_roles did on open (round-2 R7): the per-project
    #: read-only sub-agent roles exist only while delegation is active
    agent_roles: dict[str, Any] = field(default_factory=dict)

    @property
    def state_file(self) -> Path:
        return self.path / STATE_FILENAME

    @property
    def results_root(self) -> Path:
        return self.path / RESULTS_DIRNAME

    def save(self) -> None:
        temporary = self.state_file.with_name(f"{STATE_FILENAME}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_text(json.dumps({"threads": self.threads, "settings": self.settings},
                                           indent=2, ensure_ascii=False), encoding="utf-8")
            os.replace(temporary, self.state_file)
        finally:
            temporary.unlink(missing_ok=True)

    @classmethod
    def open(cls, path: str | Path,
             delegate_for: "Callable[[dict], bool | str] | None" = None
             ) -> "ProjectState":
        """`delegate_for(settings)` decides (from the saved settings) the
        delegation tier: a bool (active or not) or, round-3 R7, the tier
        name "off" | "hint" | "aggressive". It selects the AGENTS.md
        variant and whether the sub-agent role files exist. None = never
        (tests, the bare core); the service passes
        service.delegation_tier_for."""
        p = Path(path).resolve()
        p.mkdir(parents=True, exist_ok=True)
        st = cls(path=p)
        if st.state_file.exists():
            try:
                data = json.loads(st.state_file.read_text(encoding="utf-8"))
                st.threads = data.get("threads", [])
                st.settings = data.get("settings", {})
            except json.JSONDecodeError:
                st.threads = []
        st.results_root.mkdir(exist_ok=True)
        res = delegate_for(st.settings) if delegate_for else False
        tier = res if isinstance(res, str) else ("hint" if res else "off")
        delegate = tier != "off"
        mode = st.settings.get("knowledge_mode")
        st.agents_md = ensure_agents_md(p, mode, delegate,
                                        aggressive=(tier == "aggressive"))
        st.agent_roles = ensure_agent_roles(p, delegate, mode,
                                            effective_model(st.settings))
        return st


# ----------------------------------------------------------------------------
class Workbench:
    """One app-server process serving one project; multiple tasks/threads."""

    def __init__(self, project: str | Path,
                 event_cb: EventCallback | None = None,
                 approval_cb: ApprovalCallback | None = None,
                 mcp_approval: str | None = None,
                 mcp_readonly: bool = False,
                 mcp_images: bool = True,
                 multi_agent: bool = True,
                 context_window: int | None = None,
                 auto_compact_limit: int | None = None) -> None:
        self.project = (project if isinstance(project, ProjectState)
                        else ProjectState.open(project))
        self.event_cb = event_cb or (lambda ev: None)
        self.approval_cb = approval_cb
        self.mcp_approval = mcp_approval
        self.mcp_readonly = mcp_readonly
        self.mcp_images = mcp_images
        self.multi_agent = multi_agent
        self.context_window = context_window
        self.auto_compact_limit = auto_compact_limit
        try:
            self.codex_bin: str | None = str(kernel.codex_binary())
        except FileNotFoundError:
            self.codex_bin = None      # the SDK resolves its pinned build
        overrides = (_mcp_overrides(self.project.path, approval=mcp_approval,
                                    readonly=mcp_readonly,
                                    knowledge_mode=self.project.settings.get(
                                        "knowledge_mode"),
                                    images=mcp_images)
                     + _engine_overrides(multi_agent=multi_agent, images=mcp_images,
                                         context_window=context_window,
                                         auto_compact_limit=auto_compact_limit))
        self._client = CodexClient(
            config=CodexConfig(codex_bin=self.codex_bin, env=_gateway_env(),
                               cwd=str(self.project.path),
                               config_overrides=overrides),
            approval_handler=self._on_approval_request)
        self._task_by_thread: dict[str, str] = {}
        self._lock = threading.Lock()
        self._log_lock = threading.Lock()
        # task_id -> last event id handed out (1-based transcript line index)
        self._eids: dict[str, int] = {}
        # thread_id -> the turn id a TaskSession is streaming right now; the
        # notification tap leaves those to the stream and forwards the rest
        self._active_turns: dict[str, str] = {}
        self._install_tap()

    # -- notification tap --------------------------------------------------
    def _install_tap(self) -> None:
        """See every app-server notification, not only the ones the SDK routes
        to a turn stream we are consuming. What the tap forwards (as thread
        events) is what a turn stream cannot see: a manual compaction runs
        as a turn of its own (thread/compact/start answers before its
        turn/started), thread status changes, kernel warnings, and the MCP
        startup status. Runs on the SDK reader thread - must never raise."""
        router = getattr(self._client, "_router", None)
        if router is None:
            return
        orig = router.route_notification

        def tapped(note):  # type: ignore[no-untyped-def]
            try:
                self._on_tapped(note)
            except Exception:  # noqa: BLE001 - never break the reader thread
                pass
            return orig(note)

        router.route_notification = tapped

    def _on_tapped(self, note) -> None:  # type: ignore[no-untyped-def]
        method = str(getattr(note, "method", "") or "")
        payload = getattr(note, "payload", None)
        thread_id, turn_id = _ids_of(payload)
        if not thread_id or thread_id not in self._task_by_thread:
            return
        if turn_id and self._active_turns.get(thread_id) == turn_id:
            return      # the TaskSession stream normalizes this one
        ev = tap_notification(method, payload)
        if ev is None:
            return
        ev["ts"] = time.time()
        ev["thread_id"] = thread_id
        if ev["kind"] not in ("token_usage", "agent_delta", "command_output"):
            self._log_event(thread_id, ev)
        self.event_cb(ev)

    @property
    def kernel_info(self) -> dict[str, Any]:
        return {"path": self.codex_bin,
                "version": kernel.codex_version(self.codex_bin) if self.codex_bin else None}

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        self._client.start()
        self._client.initialize()

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "Workbench":
        self.start()
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    # -- approvals ---------------------------------------------------------
    def _on_approval_request(self, method: str, params: dict | None) -> dict:
        params = params or {}
        req = {
            "kind": "approval_request",
            "approval_id": str(uuid.uuid4())[:8],
            "method": method,
            "thread_id": params.get("threadId"),
            "item_id": params.get("itemId"),
            "detail": _redact({k: v for k, v in params.items()
                               if k not in ("threadId", "turnId")}),
            "ts": time.time(),
        }
        # MCP tool approvals arrive as elicitation requests; surface the tool
        # name/args so approval UIs can render a meaningful card
        meta = params.get("_meta") or {}
        if meta.get("codex_approval_kind") == "mcp_tool_call":
            req["mcp_server"] = params.get("serverName")
            req["mcp_message"] = params.get("message")
            req["mcp_tool_params"] = _redact(meta.get("tool_params"))
        self._log_event(req["thread_id"], req)
        self.event_cb(req)
        if self.approval_cb is None:
            decision = {"decision": "accept"}
        else:
            decision = self.approval_cb(req)
        done = {"kind": "approval_decision", "approval_id": req["approval_id"],
                "method": method, "decision": decision.get("decision"),
                "thread_id": req["thread_id"], "ts": time.time()}
        self._log_event(req["thread_id"], done)
        self.event_cb(done)
        if "elicitation" in method:
            # MCP elicitation result shape (probed 2026-08-28, MCP_NOTES.md):
            # plain {"decision": ...} counts as a rejection
            if decision.get("decision") == "accept":
                return {"action": "accept", "content": {}}
            return {"action": "decline"}
        return decision

    # -- tasks -------------------------------------------------------------
    def new_task(self, title: str | None = None,
                 model_provider: str | None = None,
                 images: bool = True) -> "TaskSession":
        """`model_provider` = a [model_providers.<id>] key of the isolated
        config.toml; None keeps the config's default. A provider is fixed
        at thread start (codex thread/start), unlike model / effort which
        travel with every turn - so a project's provider override only
        reaches NEW threads. `images=False` (a text-only model,
        workbench/model_caps.py) switches codex's own view_image tool off
        for the thread and says so in the developer instructions: the MCP
        server already keeps its pictures on disk, but the second GLM-5.3
        cell (2026-09-06 10:20) then opened the saved PNG with view_image
        and the provider rejected the request all the same."""
        task_id = time.strftime("task_%Y%m%d_%H%M%S")
        results_dir = self.project.results_root / task_id
        results_dir.mkdir(parents=True, exist_ok=True)
        dev_instructions = (
            f"Current CrystalPilot task id: {task_id}. Place all final "
            f"deliverables for this task under "
            f"'{RESULTS_DIRNAME}/{task_id}/' inside the project, as described "
            f"in AGENTS.md.")
        if not images:
            # the tool itself is removed at the process level
            # (_engine_overrides: tools.view_image=false); the instruction
            # covers reading picture files through the shell
            dev_instructions += (
                " This model has NO image input: never call view_image and "
                "never open, read or attach picture files (PNG/JPG) - a "
                "request carrying an image is rejected by the provider and "
                "ends the turn. Tools that render pictures keep them on "
                "disk for the user (`images_saved`); work from the numeric "
                "reports they return.")
        if model_provider:
            # A non-default (third-party) provider. codex advertises the MCP
            # tools as ONE Responses-API namespace tool (`mcp__crystalpilot`,
            # 74 functions inside) and the model has to echo that namespace
            # on every call; GLM-5.3 dropped it on the first call of the
            # 2026-09-06 10:24 thread (four 'unsupported call: get_project_
            # brief' replies, then it gave up) and later ended a turn by
            # only announcing the call it meant to make.
            dev_instructions += (
                f" Tool calling: every CrystalPilot crystallography tool lives "
                f"in the tool namespace `mcp__{MCP_SERVER_NAME}` - always send "
                f"that namespace together with the bare tool name. A reply "
                f"'unsupported call: <tool>' means the namespace was missing: "
                f"re-issue the same call with the namespace. Never end a turn "
                f"by announcing a tool call you have not made - make the call.")
        params = ThreadStartParams(
            approval_policy=AskForApproval(root=AskForApprovalValue.on_request),
            approvals_reviewer=None,
            cwd=str(self.project.path),
            sandbox=SandboxMode.workspace_write,
            developer_instructions=dev_instructions,
            model_provider=model_provider or None,
        )
        started = self._client.thread_start(params)
        thread_id = started.thread.id
        with self._lock:
            self._task_by_thread[thread_id] = task_id
            self.project.threads.append({
                "thread_id": thread_id, "task_id": task_id,
                "title": title or task_id, "created": time.time(),
                "title_source": "manual" if title else "unnamed",
                "last_active": time.time(),
                **({"model_provider": model_provider} if model_provider else {})})
            self.project.save()
        return TaskSession(self, thread_id, task_id, results_dir)

    def fork_task(self, thread_id: str, title: str | None = None,
                  model_provider: str | None = None,
                  images: bool = True) -> "TaskSession":
        """A NEW thread that continues `thread_id`'s conversation (codex
        thread/fork) - the way a provider switch reaches a conversation
        that is already running, since the provider is fixed per thread.
        The fork gets its own task id and results directory (a transcript
        is per task; two threads writing one would interleave)."""
        from openai_codex.generated.v2_all import ThreadForkParams
        rec = next((t for t in self.project.threads
                    if t["thread_id"] == thread_id), None)
        if rec is None:
            raise KeyError(f"unknown thread {thread_id} in this project")
        task_id = time.strftime("task_%Y%m%d_%H%M%S")
        results_dir = self.project.results_root / task_id
        results_dir.mkdir(parents=True, exist_ok=True)
        dev_instructions = (
            f"Current CrystalPilot task id: {task_id} (this conversation "
            f"continues task {rec['task_id']} on a new thread). Place all "
            f"final deliverables for this task under "
            f"'{RESULTS_DIRNAME}/{task_id}/' inside the project, as described "
            f"in AGENTS.md.")
        if not images:
            dev_instructions += (
                " This model has NO image input: never call view_image and "
                "never open, read or attach picture files (PNG/JPG).")
        if model_provider:
            dev_instructions += (
                f" Tool calling: every CrystalPilot crystallography tool lives "
                f"in the tool namespace `mcp__{MCP_SERVER_NAME}` - always send "
                f"that namespace together with the bare tool name.")
        params = ThreadForkParams(
            approval_policy=AskForApproval(root=AskForApprovalValue.on_request),
            cwd=str(self.project.path),
            sandbox=SandboxMode.workspace_write,
            developer_instructions=dev_instructions,
            model_provider=model_provider or None,
        )
        forked = self._client.thread_fork(thread_id, params)
        new_id = forked.thread.id
        with self._lock:
            self._task_by_thread[new_id] = task_id
            self.project.threads.append({
                "thread_id": new_id, "task_id": task_id,
                "title": title or f"{rec.get('title') or rec['task_id']} (续)",
                "created": time.time(), "last_active": time.time(),
                "forked_from": thread_id,
                **({"model_provider": model_provider} if model_provider else {})})
            self.project.save()
        return TaskSession(self, new_id, task_id, results_dir)

    def compact_thread(self, thread_id: str) -> None:
        """Ask codex to compact the thread's context now (thread/compact/
        start). The compaction runs as its own turn; its progress reaches
        the UI through the notification tap (compaction_* events)."""
        self._client.thread_compact(thread_id)

    def rename_thread(self, thread_id: str, title: str) -> dict[str, Any]:
        rec = next((t for t in self.project.threads
                    if t["thread_id"] == thread_id), None)
        if rec is None:
            raise KeyError(f"unknown thread {thread_id} in this project")
        clean = " ".join(str(title).split())[:120] or rec.get("task_id", "")
        with self._lock:
            rec["title"] = clean
            rec["title_source"] = "manual"
            self.project.save()
        try:
            self._client.thread_set_name(thread_id, clean)
        except Exception:  # noqa: BLE001 - codex's own name is cosmetic here
            pass
        return dict(rec)

    def claim_auto_title(self, thread_id: str, fallback: str, model: str | None) -> dict | None:
        """Only explicitly new, unnamed records qualify. Missing metadata is
        historical, not an invitation to rename. Claim persists before I/O."""
        with self._lock:
            rec = next((t for t in self.project.threads if t["thread_id"] == thread_id), None)
            if rec is None or rec.get("title_source") != "unnamed":
                return None
            rec.update(title=fallback, title_source="auto_pending", title_model=model)
            self.project.save()
            return dict(rec)

    def finish_auto_title(self, thread_id: str, title: str | None) -> dict | None:
        with self._lock:
            rec = next((t for t in self.project.threads if t["thread_id"] == thread_id), None)
            if rec is None or rec.get("title_source") != "auto_pending":
                return None  # manual naming always wins
            if title:
                rec["title"] = title
            rec["title_source"] = "auto" if title else "fallback"
            self.project.save()
            return dict(rec)

    def resume_task(self, thread_id: str) -> "TaskSession":
        rec = next((t for t in self.project.threads
                    if t["thread_id"] == thread_id), None)
        if rec is None:
            raise KeyError(f"unknown thread {thread_id} in this project")
        resumed = self._client.thread_resume(thread_id)
        _ = resumed
        task_id = rec["task_id"]
        results_dir = self.project.results_root / task_id
        results_dir.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self._task_by_thread[thread_id] = task_id
        return TaskSession(self, thread_id, task_id, results_dir)

    def tasks(self) -> list[dict[str, Any]]:
        return list(self.project.threads)

    # -- event logging -----------------------------------------------------
    def _log_event(self, thread_id: str | None, ev: dict[str, Any]) -> int | None:
        """Append one event to the thread transcript and stamp it with its
        identity: ``eid`` = 1-based line index in transcript.jsonl. The same
        dict object is what the live channel pushes, so a client that saw
        the event over SSE and again after a reload can tell they are one
        event (forensics 2026-09-05: the (kind, ts) dedup window let 77
        duplicate/orphan cards through). Returns the eid, None when the
        thread has no task."""
        task_id = self._task_by_thread.get(thread_id or "")
        if not task_id:
            return None
        path = self.project.results_root / task_id / "transcript.jsonl"
        # Single locked binary append: turn iterator + notification callbacks
        # log concurrently, and TextIOWrapper chunking can interleave a long
        # line mid-character (observed as a mojibake'd transcript.jsonl).
        # errors="replace" survives surrogate bytes from GBK console output.
        with self._log_lock:
            eid = self._eids.get(task_id)
            if eid is None:
                eid = _count_lines(path)
            eid += 1
            self._eids[task_id] = eid
            ev["eid"] = eid
            line = json.dumps(_redact(ev), ensure_ascii=False, default=str)
            data = (line + "\n").encode("utf-8", errors="replace")
            with path.open("ab") as fh:
                fh.write(data)
        return eid


def _count_lines(path: Path) -> int:
    """Number of newline-terminated lines (= events) already in a transcript."""
    if not path.exists():
        return 0
    n = 0
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            n += chunk.count(b"\n")
    return n


def _safe_item_name(item_id: Any) -> str:
    text = str(item_id or "")
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", text).strip("._")
    return text[:80] or "item"


# ----------------------------------------------------------------------------
#: codex multi-agent verbs (both the v1 collab tool names and the v2
#: cell-style ones) - a custom tool call by one of these names is delegation
COLLAB_TOOL_NAMES = frozenset({
    "spawn_agent", "spawnAgent", "wait_agent", "waitAgent", "wait",
    "send_input", "sendInput", "resume_agent", "resumeAgent",
    "close_agent", "closeAgent", "list_agents", "listAgents"})


def _item_dict(payload: Any) -> dict[str, Any]:
    item = getattr(payload, "item", None)
    if item is None:
        return {}
    if hasattr(item, "root"):
        item = item.root
    if hasattr(item, "model_dump"):
        return item.model_dump(by_alias=False)
    return dict(item) if isinstance(item, dict) else {}


def _ids_of(payload: Any) -> tuple[str | None, str | None]:
    """(thread_id, turn_id) of a typed or unknown notification payload."""
    if payload is None:
        return None, None
    params = getattr(payload, "params", None)
    if isinstance(params, dict):
        return (params.get("threadId") or params.get("thread_id"),
                params.get("turnId") or params.get("turn_id"))
    return (getattr(payload, "thread_id", None), getattr(payload, "turn_id", None))


def _status_name(status: Any) -> str:
    """ThreadStatus root model / dict -> "idle" | "active" | ..."""
    root = getattr(status, "root", status)
    if hasattr(root, "model_dump"):
        root = root.model_dump()
    if isinstance(root, dict):
        return str(root.get("type") or root.get("status") or "")
    return str(root or "")


def tap_notification(method: str, payload: Any) -> dict[str, Any] | None:
    """Notifications the turn stream never carries (or carries only for our
    own turns) -> UI events. Used by Workbench._on_tapped for anything
    outside an actively streamed turn: a manual compaction's turn, thread
    status changes, kernel warnings, MCP startup."""
    if method == "thread/status/changed":
        return {"kind": "thread_status",
                "status": _status_name(getattr(payload, "status", None))}
    if method in ("item/started", "item/completed", "item/updated"):
        item = _item_dict(payload)
        if item.get("type") == "contextCompaction":
            phase = method.rsplit("/", 1)[1]
            return {"kind": "compaction_started" if phase == "started"
                    else "compaction_completed", "manual": True}
        return None
    if method == "thread/compacted":
        return {"kind": "compaction_completed", "manual": True, "legacy": True}
    if method == "thread/tokenUsage/updated":
        return normalize_notification(method, payload)
    if method == "turn/completed":
        turn = getattr(payload, "turn", None)
        return {"kind": "background_turn_completed",
                "status": str(getattr(turn, "status", "") or "")}
    if method in ("warning", "configWarning", "error"):
        params = getattr(payload, "params", None)
        msg = (params.get("message") or params.get("summary") if isinstance(params, dict)
               else getattr(payload, "message", None))
        return {"kind": "engine_warning", "level": method, "message": str(msg)[:600]}
    if method == "mcpServer/startupStatus/updated":
        return normalize_notification(method, payload)
    if method == "model/rerouted":
        return normalize_notification(method, payload)
    return None


#: (item type, phase) pairs that are complete lifecycles in themselves and
#: carry nothing the transcript/UI needs (see normalize_notification)
_BENIGN_ITEM_PHASES = frozenset({
    ("userMessage", "started"), ("userMessage", "updated"),
    ("userMessage", "completed"),
    ("agentMessage", "started"), ("agentMessage", "updated"),
    ("reasoning", "started"), ("reasoning", "updated"),
})


def _item_id_of(item: dict[str, Any]) -> str | None:
    iid = item.get("id")
    return str(iid) if iid not in (None, "") else None


def normalize_notification(method: str, payload: Any) -> dict[str, Any] | None:
    """Codex app-server notification -> compact UI event. Returns None to drop.

    Every lifecycle event of an item (tool call, shell command, file change,
    web search, image view) carries the codex ``item_id`` so the UI pairs a
    completion with the card it started, not with whichever card started
    last: codex executes tool calls concurrently and real transcripts show
    completions arriving out of start order (test4-0909 eids 2141-2155)."""
    if method == "model/rerouted":
        return {"kind": "model_rerouted",
                "from_model": getattr(payload, "from_model", None),
                "to_model": getattr(payload, "to_model", None),
                "reason": str(getattr(payload, "reason", "") or "")}
    if method == "thread/compacted":
        # legacy notification (deprecated in favour of the contextCompaction
        # item, still sent by some builds)
        return {"kind": "compaction_completed", "legacy": True}
    if method == "item/agentMessage/delta":
        return {"kind": "agent_delta", "delta": getattr(payload, "delta", "")}
    if method == "item/commandExecution/outputDelta":
        chunk = getattr(payload, "chunk", None) or getattr(payload, "delta", "")
        ev_out: dict[str, Any] = {"kind": "command_output", "delta": str(chunk)[:2000]}
        # codex runs shell commands concurrently (real sessions: up to four
        # in flight); the delta must name the command it belongs to or the
        # UI appends it to whichever card started last
        iid = getattr(payload, "item_id", None)
        if iid is not None:
            ev_out["item_id"] = str(iid)
        return ev_out
    if method == "mcpServer/startupStatus/updated":
        # when the thread's MCP became usable - the one timestamp the pa1
        # log bundles lacked (the tool-surface race had to be reconstructed
        # from spec-cache mtimes and ALL_TOOLS probes)
        status = getattr(payload, "status", None)
        return {"kind": "mcp_startup",
                "server": getattr(payload, "name", None),
                "status": getattr(status, "value", None) or str(status),
                "thread_id": getattr(payload, "thread_id", None),
                "error": getattr(payload, "error", None)}
    if method in ("item/started", "item/completed", "item/updated"):
        item = _item_dict(payload)
        itype = item.get("type")
        phase = method.rsplit("/", 1)[1]
        if itype == "agentMessage" and phase == "completed":
            return {"kind": "agent_message", "text": item.get("text", "")}
        if (itype, phase) in _BENIGN_ITEM_PHASES:
            # known lifecycle phases with no UI meaning (the user message we
            # logged ourselves, the start of a message/reasoning block whose
            # completion is handled above). Recording them as item_unhandled
            # made up 23 % of a real 4548-line transcript (test-5-zcb16,
            # 2026-09-09) and told nobody anything.
            return None
        if itype == "contextCompaction":
            # codex compacting the conversation (auto-compaction inside a
            # turn, or the compaction turn of thread/compact/start): the UI
            # shows "正在压缩上下文" and a system row when it lands
            if phase == "started":
                return {"kind": "compaction_started"}
            if phase == "completed":
                return {"kind": "compaction_completed"}
            return None
        if itype == "commandExecution":
            out = (item.get("aggregated_output") or "")
            ev: dict[str, Any] = {
                "kind": f"command_{phase}",
                "command": item.get("command", ""),
                "status": item.get("status"),
                "exit_code": item.get("exit_code"),
                "output_tail": out[-1500:] if phase == "completed" else None}
            if item.get("id") is not None:
                ev["item_id"] = str(item.get("id"))
            if phase == "completed":
                ev["output_len"] = len(out)
                if len(out) > 1500:
                    # the full text goes to disk in TaskSession.send (the
                    # transcript keeps only the tail); underscore key = not
                    # part of the wire event
                    ev["_output_full"] = out
            return ev
        if itype == "reasoning" and phase == "completed":
            summaries = []
            for s in item.get("summary") or []:
                if isinstance(s, dict) and s.get("text"):
                    summaries.append(s["text"])
            if summaries:
                return {"kind": "reasoning_summary", "text": "\n".join(summaries)}
            return None
        if itype == "fileChange":
            return {"kind": f"file_change_{phase}",
                    "changes": item.get("changes"), "status": item.get("status"),
                    "item_id": _item_id_of(item)}
        if itype == "mcpToolCall":
            res = item.get("result") or {}
            content = res.get("content") or []
            text = ""
            if content and isinstance(content[0], dict):
                text = content[0].get("text") or ""
            # `ok` is CrystalPilot's own envelope convention, not MCP's.
            # Codex built-ins answer in their own shape - list_mcp_resources
            # returns {"resources": []}, which is a correct answer to a
            # server that exposes no resources - and `.get("ok")` on that is
            # None, which bool() turned into False. Result: the first two
            # calls of EVERY session were painted as failures in the UI and
            # in the SSE stream. A verdict is only reported when the payload
            # actually carries one.
            ok = None
            if text:
                try:
                    body = json.loads(text)
                except json.JSONDecodeError:
                    body = None
                if isinstance(body, dict) and "ok" in body:
                    ok = bool(body["ok"])
            err = item.get("error") or {}
            status = str(item.get("status") or "").rsplit(".", 1)[-1]
            # tools whose summaries the FE renders STRUCTURALLY (checkCIF
            # alert lists + kb notes, validation tables) keep the full
            # result - a 2000-char tail decapitates the JSON and the FE
            # falls back to salvage parsing with lower-bound counts
            tool_name = item.get("tool")
            # R6: the stage track reads situation_report.stage, the
            # delivery card reads finalize_delivery / write_outputs - a
            # 2000-char tail decapitates those JSONs too
            tail_n = (200_000 if item.get("server") == "crystalpilot" or tool_name in (
                "run_checkcif", "submit_iucr_checkcif", "validate_structure",
                "situation_report", "write_outputs", "finalize_delivery")
                else 2000)
            # Scientific results drive the UI, not just a terminal preview.
            # Keep their JSON intact when it fits the existing bounded limit.
            # Python engines can emit Infinity for an unbounded resolution bin;
            # encode that unknown bound as null so browsers can parse the rest.
            if text and item.get("server") == "crystalpilot":
                try:
                    text = json.dumps(json.loads(text, parse_constant=lambda _: None),
                                      ensure_ascii=False, allow_nan=False)
                except (ValueError, TypeError):
                    pass
            return {"kind": f"tool_{phase}",
                    "server": item.get("server"),
                    "tool": tool_name,
                    "args": _redact(item.get("arguments")),
                    "status": status,
                    "duration_ms": item.get("duration_ms"),
                    "ok": ok,
                    "result_tail": text[-tail_n:] if text else None,
                    "error": (err.get("message") if isinstance(err, dict)
                              else str(err) or None),
                    "item_id": _item_id_of(item)}
        if itype == "collabAgentToolCall":
            # multi-agent (subagent) activity: spawn/wait/send/resume/
            # close. Codex has multi_agent v2 ON in every session (4
            # concurrency slots, developer preamble advertises
            # spawn_agent et al.) but nothing had ever surfaced it -
            # this branch makes delegation visible in transcripts/SSE
            # instead of being silently dropped (recon 2026-09-01).
            states = item.get("agents_states") or {}
            return {"kind": f"collab_{phase}",
                    "tool": item.get("tool"),
                    "sender": item.get("sender_thread_id"),
                    "receivers": item.get("receiver_thread_ids"),
                    "prompt": (str(item.get("prompt") or "")[:2000] or None),
                    "model": item.get("model"),
                    "reasoning_effort": item.get("reasoning_effort"),
                    "status": item.get("status"),
                    "agents_states": _redact(states)}
        if itype in ("todoList", "webSearch", "error", "imageView"):
            # imageView (codex 0.154: the model looking at an image) was an
            # item_unhandled marker before; it is a real activity row now
            return {"kind": f"{itype}_{phase}", "detail": _redact(item),
                    "item_id": _item_id_of(item)}
        # reg11-cage (2026-09-05): the agent spawned two roles and polled
        # `wait` 28 times - the rollout shows them as custom_tool_call
        # items, and NOTHING reached the transcript or SSE, so the UI's
        # sub-agent directory stayed empty during a real delegation. Any
        # custom tool call whose name is a multi-agent verb is a collab
        # event; every other unknown item type is recorded by name instead
        # of being dropped, so the next gap can be diagnosed from the
        # transcript rather than from codex's rollout files.
        name = item.get("name") or item.get("tool") or item.get("tool_name")
        if str(name or "") in COLLAB_TOOL_NAMES:
            args = item.get("input") or item.get("arguments") or item.get("args")
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {"raw": args[:2000]}
            args = args if isinstance(args, dict) else {}
            out = item.get("output") or item.get("result")
            return {"kind": f"collab_{phase}",
                    "tool": str(name),
                    "sender": None,
                    "receivers": None,
                    "prompt": (str(args.get("message") or args.get("prompt")
                                   or args.get("input") or "")[:2000] or None),
                    "agent_type": args.get("agent_type"),
                    "model": args.get("model"),
                    "reasoning_effort": args.get("reasoning_effort"),
                    "status": str(item.get("status") or ""),
                    "output_tail": (str(out)[-1500:] if out else None),
                    "item_type": itype}
        return {"kind": "item_unhandled", "phase": phase,
                "item_type": str(itype), "name": str(name) if name else None,
                "keys": sorted(str(k) for k in item)[:24]}
    if method == "item/mcpToolCall/progress":
        msg = getattr(payload, "message", None) or getattr(payload, "progress", None)
        ev_prog: dict[str, Any] = {"kind": "tool_progress",
                                   "message": str(msg)[:500] if msg else None}
        iid = getattr(payload, "item_id", None)
        if iid is not None:
            ev_prog["item_id"] = str(iid)
        return ev_prog
    if method == "turn/started":
        return {"kind": "turn_started"}
    if method == "turn/completed":
        turn = getattr(payload, "turn", None)
        terr = getattr(turn, "error", None)
        if hasattr(terr, "model_dump"):
            terr = terr.model_dump()
        if isinstance(terr, dict):
            terr = terr.get("message") or terr
        return {"kind": "turn_completed",
                "duration_ms": getattr(turn, "duration_ms", None),
                "status": str(getattr(turn, "status", "") or ""),
                # failed turns carry the provider error here - without it
                # diagnosis requires digging through codex rollout files
                **({"error": _redact(str(terr)[:600])} if terr else {})}
    if method == "turn/failed":
        err = getattr(payload, "error", None)
        if hasattr(err, "model_dump"):
            err = err.model_dump()
        return {"kind": "turn_failed", "error": _redact(err)}
    if method == "thread/tokenUsage/updated":
        tu = getattr(payload, "token_usage", None)
        if tu is None:
            return None
        return {"kind": "token_usage",
                "last": tu.last.model_dump() if tu.last else None,
                "total": tu.total.model_dump() if tu.total else None,
                "context_window": tu.model_context_window}
    return None


class TaskSession:
    def __init__(self, wb: Workbench, thread_id: str, task_id: str,
                 results_dir: Path) -> None:
        self.wb = wb
        self.thread_id = thread_id
        self.task_id = task_id
        self.results_dir = results_dir
        self._thread = Thread(wb._client, thread_id)
        self._active_turn = None
        #: codex spawns the MCP servers asynchronously on thread/start and
        #: thread/resume; the service waits for crystalpilot's tools to be
        #: registered before this session's FIRST turn (see
        #: ProjectSession._await_mcp_ready), then clears the flag
        self.awaiting_mcp = True

    def send(self, text: str,
             output_schema: dict[str, Any] | None = None,
             turn_kwargs: dict[str, Any] | None = None,
             images: list[str] | None = None,
             display_text: str | None = None,
             attachment_names: list[str] | None = None,
             log_user: bool = True,
             ) -> Iterator[dict[str, Any]]:
        """Run one turn; yield normalized events (already transcript-logged).

        output_schema (JSON Schema) constrains the final assistant message to a
        machine-readable verdict - used for the structured end-of-task report.
        turn_kwargs passes per-turn SDK knobs (sandbox=, approval_mode=,
        model=, effort=) - used by the permission modes.
        images: absolute local paths sent as multimodal input alongside text.
        display_text: what the transcript shows for this message (the user's
        typed text); must MATCH the live-channel push or the client renders
        duplicate bubbles. The fully-composed prompt is audited in the codex
        rollout, not here.
        log_user=False when the caller already logged the user_message (the
        workbench service does, so the live push and the transcript line are
        the same event with the same eid)."""
        if log_user:
            self.wb._log_event(self.thread_id, {
                "kind": "user_message",
                "text": display_text if display_text is not None else text,
                "ts": time.time(),
                **({"attachments": attachment_names} if attachment_names else {}),
            })
        kwargs: dict[str, Any] = dict(turn_kwargs or {})
        if output_schema is not None:
            kwargs["output_schema"] = output_schema
        run_input: Any = text
        if images:
            run_input = [TextInput(text),
                         *(LocalImageInput(p) for p in images)]
        handle = self._thread.turn(run_input, **kwargs)
        self._active_turn = handle
        self.wb._active_turns[self.thread_id] = handle.id
        stream = handle.stream()
        try:
            for note in stream:
                ev = normalize_notification(note.method, note.payload)
                if ev is None:
                    continue
                ev["ts"] = time.time()
                full = ev.pop("_output_full", None)
                if full is not None:
                    ev["output_file"] = self._store_command_output(
                        ev.get("item_id"), full)
                if ev["kind"] not in ("agent_delta", "command_output",
                                      "token_usage"):
                    self.wb._log_event(self.thread_id, ev)
                yield ev
                if ev["kind"] in ("turn_completed", "turn_failed"):
                    break
        finally:
            stream.close()
            self._active_turn = None
            self.wb._active_turns.pop(self.thread_id, None)
            for t in self.wb.project.threads:
                if t["thread_id"] == self.thread_id:
                    t["last_active"] = time.time()
            self.wb.project.save()

    def _store_command_output(self, item_id: Any, text: str) -> str | None:
        """Full command output -> <results>/command_output/<item>.txt. The
        transcript event keeps a 1500-char tail; the UI fetches the file on
        demand (forensics F-6: the tail used to replace 16k streamed chars)."""
        try:
            d = self.results_dir / "command_output"
            d.mkdir(parents=True, exist_ok=True)
            name = _safe_item_name(item_id)
            path = d / f"{name}.txt"
            if path.exists():
                name = f"{name}-{uuid.uuid4().hex[:6]}"
                path = d / f"{name}.txt"
            path.write_text(text, encoding="utf-8", errors="replace")
            return f"command_output/{path.name}"
        except OSError:
            return None

    def interrupt(self) -> None:
        if self._active_turn is not None:
            self._active_turn.interrupt()

    def steer(self, text: str, images: list[str] | None = None,
              display_text: str | None = None,
              attachment_names: list[str] | None = None
              ) -> tuple[int | None, dict[str, Any] | None]:
        """Inject guidance into the RUNNING turn (Codex turn_steer). Returns
        (eid, receipt): the transcript eid of the logged user_steer (truthy)
        and the steer_receipt event that says whether the words REACHED
        the model (round-3 R6: status "submitted" | "failed" + error). The
        receipt is logged right after the steer so a reload shows the same
        three states the live client saw. (None, None) when no turn is
        active (caller should send() instead)."""
        handle = self._active_turn
        if handle is None:
            return None, None
        eid = self.wb._log_event(self.thread_id, {
            "kind": "user_steer",
            "text": display_text if display_text is not None else text,
            "ts": time.time(),
            **({"attachments": attachment_names} if attachment_names else {}),
        })
        run_input: Any = text
        if images:
            run_input = [TextInput(text),
                         *(LocalImageInput(p) for p in images)]
        receipt: dict[str, Any] = {"kind": "steer_receipt",
                                   "steer_eid": eid, "ts": time.time()}
        try:
            handle.steer(run_input)
        except Exception as e:  # noqa: BLE001 - the words are kept; say they did not arrive
            receipt["status"] = "failed"
            receipt["error"] = f"{type(e).__name__}: {e}"[:400]
        else:
            receipt["status"] = "submitted"
        self.wb._log_event(self.thread_id, receipt)
        return (eid if eid is not None else -1), receipt
