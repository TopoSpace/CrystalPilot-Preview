"""CrystalPilot MCP stdio server: ToolRegistry -> MCP tools, per project.

One server process serves one project (--project, injected per-Workbench via
CodexConfig.config_overrides). All durable state lives in the NodeStore on
disk, so any spawn cadence codex chooses is correct: a fresh process resumes
from state.json's active node.

Requires mcp>=1.2,<2 (the 2.x SDK cannot register tools with explicit JSON
schemas - see workbench/MCP_NOTES.md).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from pathlib import Path
from typing import Any

import anyio
import mcp.types as types
from mcp.server.lowlevel import Server

# tool annotations: read-only hints drive codex approval_mode='writes'
READ_ONLY_TOOLS = {
    "get_project_brief", "inspect_model", "inspect_map", "check_ligand",
    "validate_structure", "list_nodes", "compare_nodes", "run_checkcif",
    "get_geometry", "check_symmetry", "audit_reflection_data",
    "integrate_difference_density", "audit_element_assignment",
    "audit_guest_evidence", "audit_heavy_sites", "view_structure", "run_olex2",
    "preflight_restraints",
    # round-3 WP5: the pose search only reads the map and caches candidates
    "search_fragment_pose",
    "list_skills", "read_skill",
    # analysis tools that only READ session state (they may drop derived
    # files - rendered views, a dials log - but never touch model or data).
    # Left out until 2026-09 by oversight, which hard-blocked the very
    # tools a read-only specialist sub-agent exists to run.
    "situation_report", "ncs_audit", "screen_space_groups",
    "reflection_statistics",
    "estimate_resolution",
    # R5: reads the cached per-node analysis product; never touches state
    "analyze_packing",
}

#: a queued call reports its wait through the progress channel this often
QUEUE_PING_S = 10.0
#: ...and gives up (fail with an explanation) after this long in the queue;
#: codex's own tool timeout is 3900 s, so a queued call outlives any single
#: SHELXT/refine stage without either side timing out
QUEUE_MAX_S = 1800.0
#: when the running tool DOES declare a wall-clock budget, a queued caller
#: gives up this long after that budget expires instead of burning the full
#: QUEUE_MAX_S. ka1 org-tools spent its last 60 min on two 30 min waits that
#: could have ended in minutes with a message naming the running tool's
#: budget.
QUEUE_GRACE_S = 60.0


class ProjectHandle:
    """Lazily-opened RefineProject, one lock around every tool call.

    The first _ensure() pulls the whole cctbx/smtbx stack. Boost extension
    modules can deadlock when FIRST imported from a worker thread on
    Windows, so callers must route the first _ensure() through the event
    loop (= main) thread - see build_server()."""

    def __init__(self, project_dir: Path) -> None:
        self.project_dir = project_dir
        self._project = None
        self._opened: dict[str, Any] | None = None
        self._lock = threading.Lock()
        self._running: tuple[str, float] | None = None   # (tool, t0)
        #: wall-clock ceiling the running tool stops itself at (None = the
        #: tool declares none), so a queued caller can say when the lock frees
        self._running_budget_s: float | None = None

    @property
    def ready(self) -> bool:
        return self._project is not None

    def _ensure(self):
        if self._project is None:
            from crystalpilot.refine.project import RefineProject
            # every heavy extension module the tools import lazily is
            # loaded HERE, on the loop (= main) thread: a worker thread's
            # first `import scipy.spatial` deadlocked the reg9-dbu cell for
            # 65 minutes (see mcp/prewarm.py for the py-spy evidence)
            from .prewarm import prewarm_heavy_imports
            rep = prewarm_heavy_imports()
            _log_event(self.project_dir, "prewarm",
                       n_imported=len(rep["imported"]),
                       failed=sorted(rep["failed"]),
                       seconds=rep["seconds"], thread=rep["thread"])
            # only a project whose open() succeeded counts as opened: a
            # failed open used to leave _project set, so a retry skipped
            # open() and every later tool ran on an unopened project
            proj = RefineProject(self.project_dir)
            self._opened = proj.open()
            self._project = proj
        return self._project

    def specs(self) -> list[dict[str, Any]]:
        p = self._ensure()
        return p.registry.specs()

    def _queue_detail(self) -> tuple[str, float | None]:
        """(what is running, seconds until its budget expires or None).

        The budget comes from tools.budget.BUDGET_PARAMS, the same table the
        tools take their defaults from, applied to the ARGUMENTS the running
        call was made with - so a caller who passed timeout_s=120 is quoted
        120 s, not the default."""
        import time as _time
        running = self._running
        if not running:
            return "a previous tool call", None
        started = running[1]
        if self._project is None:
            return f"'{running[0]}' (project startup; execution budget has not started)", None
        if hasattr(self._project, "_operation_started_at"):
            started = self._project._operation_started_at
            if started is None:
                return (f"'{running[0]}' (waiting for project ownership/startup; "
                        "execution budget has not started)"), None
        elapsed = _time.time() - started
        budget = self._running_budget_s
        detail = f"'{running[0]}' (running {elapsed:.0f}s so far"
        if budget is None:
            return detail + "; it declares no wall-clock budget)", None
        left = budget - elapsed
        if left > 0:
            return (f"{detail}; it stops itself at its own {budget:.0f}s "
                    f"budget, i.e. in about {left:.0f}s)", left)
        return (f"{detail}; already past its {budget:.0f}s budget - it is in "
                f"a stage that cannot check the clock, but it still ends by "
                f"itself)", 0.0)

    def call(self, name: str, arguments: dict[str, Any],
             progress=None, cancel_event=None) -> dict[str, Any]:
        # read-only permission mode: hard server-side gate (the MCP process is
        # not inside the codex sandbox, so the sandbox alone cannot stop it)
        import os
        if (os.environ.get("CRYSTALPILOT_MCP_READONLY") == "1"
                and name not in READ_ONLY_TOOLS):
            return {"ok": False, "summary": {},
                    "artifacts": {},
                    "error": f"tool '{name}' is blocked: this workbench is "
                             "in READ-ONLY mode (inspection tools only). "
                             "Ask the user to switch the permission mode "
                             "to make model changes."}
        # One project = one lock: tool calls execute one at a time. The
        # exec harness encourages `Promise.all([...])` batches, and every
        # member of a batch used to be REJECTED as "server busy" the
        # moment the members ahead of it held the lock for >10 s (pa1: 11
        # rejections in 5 batches, all behind a 10-13 s read-only call;
        # the message blamed a client interrupt that never happened). Now
        # a call waits its turn, and says so through the progress channel
        # every QUEUE_PING_S so the agent sees a queue, not a hang. The
        # fail-fast only remains for a lock held longer than QUEUE_MAX_S.
        import time as _time

        def cancelled():
            return cancel_event is not None and cancel_event.is_set()

        def cancelled_result():
            return {"ok": False, "summary": {"tool_status": {"execution": "cancelled"}},
                    "artifacts": {}, "error": "Cancelled while waiting; tool was not run."}

        if cancelled():
            return cancelled_result()
        t_wait = _time.time()
        pinged = False
        give_up_at = t_wait + QUEUE_MAX_S
        next_ping = t_wait + QUEUE_PING_S
        while not self._lock.acquire(timeout=min(QUEUE_PING_S, 0.1)):
            if cancelled():
                return cancelled_result()
            now = _time.time()
            waited = now - t_wait
            detail, left = self._queue_detail()
            if left is not None:
                # the running tool WILL end at a known time: no reason to burn
                # the full QUEUE_MAX_S. Monotonically non-increasing so the
                # deadline cannot run away as `waited` grows.
                give_up_at = min(give_up_at, now + left + QUEUE_GRACE_S)
            if now >= give_up_at:
                after = (f"in about {left + QUEUE_GRACE_S:.0f}s"
                         if left is not None else
                         "once it returns (this tool declares no budget, so "
                         "the wait is open-ended)")
                return {"ok": False, "summary": {}, "artifacts": {},
                        "error": f"gave up waiting after {waited:.0f}s: "
                                 f"{detail} is still executing. Calls on one "
                                 f"project run one at a time. Nothing is "
                                 f"stuck and nothing needs killing - the "
                                 f"running call ends by itself at its budget "
                                 f"and its result is kept. What you can do "
                                 f"now: re-issue THIS call {after}; if you "
                                 f"are the one who started '{name}'-blocking "
                                 f"work, give the long tool a smaller "
                                 f"timeout_s next time so it reports a "
                                 f"partial result instead of holding the "
                                 f"lock."}
            if progress is not None and now >= next_ping:
                next_ping = now + QUEUE_PING_S
                pinged = True
                try:
                    progress(f"{name}: queued behind {detail} - calls on "
                             f"this project run one at a time, it starts "
                             f"the moment the lock frees (waited "
                             f"{waited:.0f}s; nothing was interrupted)")
                except Exception:  # noqa: BLE001 - liveness is best-effort
                    pass
        try:
            if cancelled():
                return cancelled_result()
            from ..tools.budget import declared_budget_s
            self._running = (name, _time.time())
            self._running_budget_s = declared_budget_s(name, arguments)
            p = self._ensure()
            result = p.invoke_tool(name, arguments, progress=progress,
                                   cancel_event=cancel_event)
            out = {"ok": result.ok, "summary": result.summary,
                   "artifacts": result.artifacts, "error": result.error}
            if pinged and isinstance(out.get("summary"), dict):
                out["summary"]["queued_s"] = round(
                    self._running[1] - t_wait, 1)
            return out
        finally:
            self._running = None
            self._running_budget_s = None
            self._lock.release()


def _log_event(project_dir: Path, event: str, **facts: Any) -> None:
    """Append one JSON line to <project>/.crystalpilot/mcp_server.jsonl.

    Evidence, not telemetry: the ka1 ablation's construct validity rests on
    the tools_only arm's MCP process really having run without the skill
    tools, and stderr of an MCP child is not kept by codex. The campaign
    log bundle copies this file. Best-effort - never delays startup or
    shutdown. Events: "startup", "transport_closed" (see
    _transport_watchdog)."""
    import os
    import time
    try:
        d = Path(project_dir) / ".crystalpilot"
        d.mkdir(parents=True, exist_ok=True)
        rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "pid": os.getpid(),
               "event": event,
               "readonly": os.environ.get("CRYSTALPILOT_MCP_READONLY") == "1",
               **facts}
        with (d / "mcp_server.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001 - evidence file must not block startup
        pass


def _log_startup(project_dir: Path, **facts: Any) -> None:
    _log_event(project_dir, "startup", **facts)


# --- transport watchdog -----------------------------------------------------
# ka1 org-tools (2026-09-04): the MCP process of a case that had ended by the
# 7200 s campaign timeout was found 9.6 h later still burning one core (518
# CPU-min) - codex had exited, the stdio pipe was broken, but the pre-WP1
# tool had no budget and nothing made the process notice its client was
# gone. After WP1 the transport close does reach the cancel bridge, but a
# stage that cannot check the clock (vendor subprocess, one big cctbx call)
# still keeps the interpreter alive until it finishes, and an idle server
# only exits once anyio unwinds. So: poll the pipe ourselves; once the
# client end is gone, give the running tool a short grace (it may be
# finishing under the cancel bridge), write an evidence line naming the
# tool and its elapsed time, and _exit. The stdin probe is NON-destructive
# (PeekNamedPipe / ppid) - the SDK's reader thread keeps sole ownership of
# the bytes.

ORPHAN_POLL_S = 5.0
#: seconds a running tool gets after the client vanished before we _exit
ORPHAN_GRACE_S = float(os.environ.get("CRYSTALPILOT_MCP_ORPHAN_GRACE_S", "60"))
_PPID_AT_START = os.getppid()


def transport_closed() -> bool:
    """True once the client end of our stdio transport is gone.

    Windows: PeekNamedPipe on the stdin handle fails with ERROR_BROKEN_PIPE
    (or ERROR_INVALID_HANDLE / ERROR_NO_DATA) when the writer has exited; a
    stdin that is not a pipe (console, file) reports False - unknown is not
    closed. POSIX: codex execs the server directly, so a changed parent pid
    means the client died."""
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.GetStdHandle.restype = wintypes.HANDLE
        k32.GetStdHandle.argtypes = [wintypes.DWORD]
        k32.GetFileType.restype = wintypes.DWORD
        k32.GetFileType.argtypes = [wintypes.HANDLE]
        k32.PeekNamedPipe.restype = wintypes.BOOL
        k32.PeekNamedPipe.argtypes = [wintypes.HANDLE, wintypes.LPVOID,
                                      wintypes.DWORD, wintypes.LPDWORD,
                                      wintypes.LPDWORD, wintypes.LPDWORD]
        h = k32.GetStdHandle(wintypes.DWORD(0xFFFFFFF6))         # STD_INPUT_HANDLE (-10)
        if not h or h == wintypes.HANDLE(-1).value:
            return False
        if k32.GetFileType(h) != 3:                              # FILE_TYPE_PIPE
            return False
        avail = wintypes.DWORD(0)
        if k32.PeekNamedPipe(h, None, 0, None, ctypes.byref(avail), None):
            return False
        # ERROR_INVALID_HANDLE 6, ERROR_BROKEN_PIPE 109, ERROR_NO_DATA 232
        return ctypes.get_last_error() in (6, 109, 232)
    if os.getppid() != _PPID_AT_START:
        return True
    # A live parent may close its pipe without exiting (disconnect/cancel).
    # poll observes hangup without consuming any MCP protocol bytes.
    import select
    import stat
    try:
        fd = sys.stdin.fileno()
        if not stat.S_ISFIFO(os.fstat(fd).st_mode):
            return False
        poller = select.poll()
        poller.register(fd, select.POLLHUP | select.POLLERR)
        return any(events & (select.POLLHUP | select.POLLERR)
                   for _, events in poller.poll(0))
    except (OSError, ValueError):
        return False


def _orphan_step(handle, closed: bool, closed_since: float | None,
                 now: float) -> tuple[float | None, dict[str, Any] | None]:
    """One watchdog tick, pure. Returns (closed_since, exit_record).

    exit_record is None while we keep waiting; otherwise it is the evidence
    line to write before _exit. Rule: a tool still running gets
    ORPHAN_GRACE_S from the moment the client vanished; an idle server gets
    ORPHAN_POLL_S (anyio normally unwinds it sooner)."""
    if not closed:
        return None, None
    if closed_since is None:
        closed_since = now
    running = handle._running
    waited = now - closed_since
    if running is None:
        if waited < ORPHAN_POLL_S:
            return closed_since, None
        return closed_since, {"running_tool": None, "waited_s": round(waited, 1),
                              "action": "exit_idle"}
    if waited < ORPHAN_GRACE_S:
        return closed_since, None
    return closed_since, {"running_tool": running[0],
                          "elapsed_s": round(now - running[1], 1),
                          "budget_s": handle._running_budget_s,
                          "waited_s": round(waited, 1),
                          "action": "exit_abandoning_tool"}


def _transport_watchdog(handle: "ProjectHandle") -> None:
    import time
    closed_since: float | None = None
    while True:
        time.sleep(ORPHAN_POLL_S)
        try:
            closed = transport_closed()
        except Exception:  # noqa: BLE001 - a broken probe must not kill a live server
            closed = False
        closed_since, rec = _orphan_step(handle, closed, closed_since, time.time())
        if rec is None:
            continue
        _log_event(handle.project_dir, "transport_closed", **rec)
        print(f"crystalpilot mcp: client transport closed - {rec}",
              file=sys.stderr, flush=True)
        os._exit(3)


def start_transport_watchdog(handle: "ProjectHandle") -> threading.Thread:
    t = threading.Thread(target=_transport_watchdog, args=(handle,),
                         name="cp-transport-watchdog", daemon=True)
    t.start()
    return t


async def call_with_cancel_bridge(handle, name: str,
                                  arguments: dict[str, Any],
                                  progress_cb=None) -> dict[str, Any]:
    """Run `handle.call` in a worker thread with a cooperative cancel bridge.

    mcp 1.29.1 turns a client `notifications/cancelled` - and a transport
    close - into a cancellation of the RequestResponder's CancelScope, which
    wraps the call_tool handler. But the work runs in a worker thread that
    `to_thread.run_sync` cannot interrupt, and with abandon_on_cancel=False
    (which must stay: abandoning the thread would hand the loop back while
    the thread still holds the project lock) the cancellation is not even
    delivered here until that thread returns.

    So: a watcher task parked on a checkpoint IS cancelled promptly, and on
    its way out it sets a threading.Event that the budgeted loops poll
    (tools/budget.py). The tool stops at its next safe point, the lock frees
    in seconds instead of hours, and the deferred cancellation then unwinds
    this coroutine normally.

    codex 0.147 is NOT known to send the notification (openai/codex#26956 is
    open), so this covers the transport-close case and any client that does -
    the self-enforced budgets remain the primary mechanism. See
    CANCELLATION_NOTES.md."""
    cancel_event = threading.Event()
    finished = {"v": False}
    out: dict[str, Any] = {}

    async def cancel_watch() -> None:
        try:
            await anyio.sleep_forever()
        except BaseException:
            if not finished["v"]:
                cancel_event.set()
            raise

    async with anyio.create_task_group() as tg:
        tg.start_soon(cancel_watch)
        try:
            out["payload"] = await anyio.to_thread.run_sync(
                handle.call, name, arguments, progress_cb, cancel_event)
        except Exception as e:  # noqa: BLE001 - the agent must see failures
            out["payload"] = {"ok": False,
                              "error": _sane_error(f"{type(e).__name__}: {e}")}
        finally:
            finished["v"] = True
            tg.cancel_scope.cancel()
    return out["payload"]


#: a fresh project's first open can lose a race with a sibling MCP process
#: (see RefineProject._bootstrap_once); give it a few seconds, not one shot
OPEN_ATTEMPTS = 3
OPEN_RETRY_S = 2.0


def build_server(handle: ProjectHandle) -> Server:
    from . import spec_cache

    server = Server("crystalpilot")
    fp = spec_cache.cache_key()      # code + knowledge mode

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        # cache first: answers instantly with zero heavy imports, so a
        # loaded machine cannot push the codex handshake past its startup
        # timeout (round-5 shell-fallback root cause)
        specs = spec_cache.load_specs(fp)
        if specs is None:
            last: Exception | None = None
            for attempt in range(1, OPEN_ATTEMPTS + 1):
                try:
                    # synchronously IN the loop (= main) thread: the first
                    # cctbx import must not happen in a worker (deadlock)
                    specs = handle.specs()
                    spec_cache.store_specs(fp, specs)
                    last = None
                    break
                except Exception as e:  # noqa: BLE001 - surface as error tool
                    # codex keeps no stderr of an MCP child, so the reason a
                    # project failed to open used to be lost (live cell
                    # 2026-09-05); keep it beside the startup record
                    import traceback
                    last = e
                    _log_event(handle.project_dir, "open_failed",
                               attempt=attempt, error=f"{type(e).__name__}: {e}",
                               traceback=traceback.format_exc()[-2500:])
                    print(f"[crystalpilot mcp] open attempt {attempt} failed: "
                          f"{type(e).__name__}: {e}", file=sys.stderr, flush=True)
                    if attempt < OPEN_ATTEMPTS:
                        await anyio.sleep(OPEN_RETRY_S)
            if last is not None:
                return [types.Tool(
                    name="crystalpilot_error",
                    description=f"CrystalPilot project failed to open: "
                                f"{type(last).__name__}: {last}",
                    inputSchema={"type": "object", "properties": {}})]
        out = []
        for s in specs:
            out.append(types.Tool(
                name=s["name"], description=s["description"],
                inputSchema=s["parameters"],
                annotations=types.ToolAnnotations(
                    readOnlyHint=s["name"] in READ_ONLY_TOOLS)))
        return out

    @server.list_resources()
    async def list_resources() -> list[types.Resource]:
        # codex probes resources/list at the start of every session; an
        # unimplemented method answered -32601, which three pa1 agents read
        # as "the crystalpilot server is not there" (the tools live under
        # tools/list, not resources). An empty list is the truthful answer.
        return []

    @server.list_resource_templates()
    async def list_resource_templates() -> list[types.ResourceTemplate]:
        # same story one probe later (2026-09-05, resumed thread after a
        # server restart): codex's list_mcp_resource_templates hit -32601
        # and the agent concluded the crystallography tools were gone
        return []

    @server.list_prompts()
    async def list_prompts() -> list[types.Prompt]:
        return []

    # validate_input=False: the SDK would reject a JSON *string* where the
    # schema wants an object (GLM-5.3 double-encoded `tiers` four times,
    # 2026-09-06); decode such strings first, then validate the same way
    @server.call_tool(validate_input=False)
    async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
        images_ok = os.environ.get("CRYSTALPILOT_NO_IMAGES") != "1"
        coerced: list[str] = []
        if name == "crystalpilot_error":
            payload: dict[str, Any] = {"ok": False,
                                       "error": "project failed to open"}
        else:
            schema = next((s.get("parameters") for s in
                           (spec_cache.load_specs(fp) or [])
                           if s.get("name") == name), None)
            if schema:
                arguments, coerced = coerce_json_strings(arguments or {}, schema)
                try:
                    import jsonschema
                    jsonschema.validate(instance=arguments, schema=schema)
                except jsonschema.ValidationError as e:
                    return [types.TextContent(type="text", text=json.dumps(
                        {"ok": False,
                         "error": f"Input validation error: {e.message}"},
                        ensure_ascii=False, default=str))]
                except Exception:  # noqa: BLE001 - validation is advisory
                    pass
            # heartbeat channel: long DIALS stages call progress(msg) from
            # the worker thread; forward as MCP progress notifications so
            # the agent SEES liveness (a silent slow find_spots was
            # mistaken for a hang and its subprocess force-killed)
            rc = server.request_context
            token = getattr(rc.meta, "progressToken", None) if rc.meta \
                else None
            session = rc.session
            counter = {"n": 0}
            # thread-agnostic dispatch: anyio.from_thread only works from
            # to_thread workers, so a progress call from any OTHER thread
            # (the tools' wall-clock heartbeat threads, T2) would raise
            # and be silently swallowed - run_coroutine_threadsafe works
            # from every thread on the asyncio backend
            import asyncio
            loop = asyncio.get_running_loop()

            def progress_cb(message: str) -> None:
                if token is None:
                    return
                counter["n"] += 1
                try:
                    fut = asyncio.run_coroutine_threadsafe(
                        session.send_progress_notification(
                            token, float(counter["n"]), None,
                            str(message)[:300]),
                        loop)
                    fut.add_done_callback(
                        lambda f: f.cancelled() or f.exception())
                except Exception:  # noqa: BLE001 - heartbeat best-effort
                    pass

            try:
                if not handle.ready:
                    # first heavy import in the loop (= main) thread; the
                    # blocked event loop is fine post-handshake and the
                    # call itself is covered by codex's tool timeout
                    handle._ensure()
                payload = await call_with_cancel_bridge(
                    handle, name, arguments or {}, progress_cb)
            except Exception as e:  # noqa: BLE001 - agent must see the failure
                payload = {"ok": False,
                           "error": _sane_error(f"{type(e).__name__}: {e}")}
        if coerced and isinstance(payload, dict):
            payload.setdefault("argument_notes", []).append(
                "decoded JSON-string arguments into the objects the schema "
                "asks for: " + ", ".join(coerced) + " - send objects directly")
        return content_blocks(payload, images_ok)

    return server


def coerce_json_strings(arguments: dict, schema: dict) -> tuple[dict, list[str]]:
    """Decode arguments given as JSON strings where the schema wants an
    object or an array (models double-encode nested arguments; the value
    was right, the wrapping was not). Anything that does not parse to the
    wanted type is left for validation to report. Returns (args, names)."""
    props = (schema or {}).get("properties") or {}
    out = dict(arguments or {})
    names: list[str] = []
    for key, val in list(out.items()):
        if not isinstance(val, str):
            continue
        wanted = _container_types(props.get(key) or {})
        if not wanted:
            continue
        try:
            parsed = json.loads(val)
        except ValueError:
            continue
        if (isinstance(parsed, dict) and "object" in wanted) or \
                (isinstance(parsed, list) and "array" in wanted):
            out[key] = parsed
            names.append(key)
    return out, names


def _container_types(prop: dict) -> set[str]:
    types_: set[str] = set()
    t = prop.get("type")
    for x in (t if isinstance(t, list) else [t]):
        if x in ("object", "array"):
            types_.add(x)
    for alt in list(prop.get("anyOf") or []) + list(prop.get("oneOf") or []):
        if isinstance(alt, dict):
            types_ |= _container_types(alt)
    return types_


def content_blocks(payload: Any, images_ok: bool = True) -> list:
    """The MCP content for a tool payload: the JSON text plus, when the
    model takes images, the pictures a tool attached via `_image_files`
    (view_structure). For a text-only model the pictures stay on disk and
    the payload says where they are (`images_saved`) - the turn used to
    die at the provider instead (OpenRouter 404, 2026-09-06)."""
    image_blocks: list[types.ImageContent] = []
    if isinstance(payload, dict):
        summary = payload.get("summary")
        holder = summary if isinstance(summary, dict) else payload
        img_files = [str(x) for x in (holder.pop("_image_files", None) or [])]
        if img_files and not images_ok:
            holder["images_saved"] = img_files[:8]
            holder["image_note"] = (
                "images not sent: this model has no image input; the "
                "pictures are saved for the user to open in the workbench "
                "(the numeric report above is complete)")
        elif img_files:
            for fp in img_files[:4]:
                try:
                    image_blocks.append(types.ImageContent(
                        type="image", data=_encode_image(fp),
                        mimeType="image/png"))
                except Exception as e:  # noqa: BLE001 - vision best-effort
                    holder.setdefault("image_errors", []).append(
                        f"{fp}: {type(e).__name__}: {e}")
    return [types.TextContent(
        type="text",
        text=json.dumps(payload, ensure_ascii=False, default=str)),
        *image_blocks]


def _sane_error(msg: str, limit: int = 800) -> str:
    """Keep tool errors human-readable: elide base64-like payloads and cap
    length. Live failure (r20 23:19 / r22 informed arm): a view_structure
    error surfaced ~1.8k chars of encoded image content as the error body
    - noise at best, a prompt-injection surface at worst."""
    import re as _re
    msg = _re.sub(r"[A-Za-z0-9+/=]{120,}",
                  lambda m: f"<{len(m.group(0))}-char encoded payload "
                            f"elided>", msg)
    if len(msg) > limit:
        msg = msg[:limit] + f" ...(+{len(msg) - limit} chars elided)"
    return msg


def _encode_image(path: str, max_px: int = 1024) -> str:
    """Downscale + base64 a PNG for the MCP image block (context weight)."""
    import base64
    import io

    from PIL import Image

    im = Image.open(path)
    if max(im.size) > max_px:
        ratio = max_px / max(im.size)
        im = im.resize((int(im.width * ratio), int(im.height * ratio)),
                       Image.LANCZOS)
    buf = io.BytesIO()
    im.convert("RGB").save(buf, format="PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode("ascii")


async def _run(server: Server) -> None:
    from mcp.server.stdio import stdio_server
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="crystalpilot.mcp")
    ap.add_argument("--project", required=True,
                    help="absolute path of the refinement project directory")
    args = ap.parse_args(argv)
    project_dir = Path(args.project)
    print(f"crystalpilot mcp server starting for {project_dir}",
          file=sys.stderr, flush=True)
    handle = ProjectHandle(project_dir)
    # the CPU cap is seeded on the uvicorn tree root and inherited, but an
    # MCP process launched by codex outside that tree (campaign runners,
    # a hand-started codex) has no root to inherit from - and until
    # 2026-09-06 the root's own cap silently failed (procutil._kernel32),
    # so every server states its cap itself
    try:
        from ..procutil import limit_cpu
        _cap = limit_cpu()
        if _cap:
            print(f"crystalpilot mcp: {_cap}", file=sys.stderr, flush=True)
    except Exception as exc:  # noqa: BLE001 - best effort
        print(f"crystalpilot mcp: cpu cap skipped ({exc})", file=sys.stderr, flush=True)
    # numpy MUST load before the anyio loop spawns its stdio worker
    # threads: importing numpy._core._multiarray_umath while those threads
    # exist deadlocks in the Windows loader lock (OpenBLAS DllMain
    # thread-pool init; faulthandler evidence in ROUND6_NOTES). numpy
    # alone is ~0.2s, so startup stays instant; the rest of the cctbx
    # chain imports fine in-loop AFTER numpy is resident.
    import numpy  # noqa: F401
    # scipy carries its OWN OpenBLAS: the reg9-dbu cell (2026-09-05) hung
    # 65 min in a worker thread's first `import scipy.spatial`, and the
    # cold-cache handshake test hangs when it is imported in-loop on the
    # main thread - so it goes here, with numpy, before the loop exists
    # (~1 s; mcp/prewarm.py has the py-spy evidence)
    from .prewarm import prewarm_preloop
    _preloop_failed = prewarm_preloop()
    if _preloop_failed:
        print(f"crystalpilot mcp: pre-loop imports missing "
              f"{sorted(_preloop_failed)}", file=sys.stderr, flush=True)
    # NO eager project open: tools/list is served from the spec cache so
    # the codex handshake completes in milliseconds even on a loaded
    # machine (round-5 shell-fallback root cause was cctbx imports
    # blowing the 90s startup timeout under load); the heavy import
    # happens on the first cache-miss tools/list or the first tool call,
    # synchronously in the loop (= main) thread - never first in a
    # worker thread.
    from . import spec_cache
    cached = spec_cache.load_specs(spec_cache.cache_key())
    from .. import knowledge_mode as _km
    print(f"crystalpilot mcp ready (spec cache: "
          f"{'hit' if cached else 'miss - first call imports cctbx'}; "
          f"knowledge_mode={_km.current()})",
          file=sys.stderr, flush=True)
    _log_startup(project_dir, mode=_km.current(), cache_hit=bool(cached),
                 n_tools_cached=len(cached) if cached else None,
                 fingerprint=spec_cache.cache_key())
    server = build_server(handle)
    start_transport_watchdog(handle)
    anyio.run(_run, server)
    return 0


if __name__ == "__main__":
    sys.exit(main())
