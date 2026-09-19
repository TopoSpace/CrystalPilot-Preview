# Cancelling a long MCP tool call: what the plumbing can and cannot do

Written 2026-09-03 for WP1 (docs/ka1-2026-09-03/KA1-ANALYSIS.md §5.1 / §7.1-1).
Evidence: ka1 org-tools-r1 (`solve_charge_flipping` 65 min + two 30 min queue
give-ups) and ka1 cage-full-r1 (`optimize_weights` 65 min).

The question this file answers: **when codex gives up on a tool call, can
anything stop the computation on the server side?**

Short answer: **no external signal can be relied on.** Every long tool must
carry its own wall-clock budget and stop itself. The cancellation plumbing
below is a best-effort accelerator on top of that, not a substitute for it.

---

## (a) How `mcp/server.py` runs `call_tool`

`build_server()` registers an async `call_tool(name, arguments)` on the
lowlevel `Server`. The body:

1. reads `server.request_context` for the `progressToken` and the session and
   builds `progress_cb` (thread-agnostic: `asyncio.run_coroutine_threadsafe`);
2. on the first call, imports cctbx **in the event-loop (= main) thread**
   (`handle._ensure()` - Boost extension modules deadlock when first imported
   from a worker thread on Windows);
3. runs the real work in a worker thread:
   `await anyio.to_thread.run_sync(handle.call, name, arguments, progress_cb)`.

`ProjectHandle.call` takes a `threading.Lock` (one project = one lock, calls
serialise), records `self._running = (name, t0)`, and calls
`RefineProject.invoke_tool`, which puts `progress` (and now `cancel_event`)
on the `ToolContext` for the duration of the call.

**The load-bearing detail:** `anyio.to_thread.run_sync` defaults to
`abandon_on_cancel=False`. Cancelling the task that awaits it does **not**
interrupt the worker thread and does not even deliver the cancellation to the
awaiting task until the thread returns. There is no way to interrupt a running
Python thread from outside - so a tool that never looks at a stop flag cannot
be stopped, full stop. This is why the lock stayed held for 7 545 s in
org-tools-r1 while the client had long given up.

## (b) Does the installed SDK deliver `notifications/cancelled`?

Installed: **mcp 1.29.1** (`.venv/Lib/site-packages/mcp-1.29.1.dist-info`).
Yes, it delivers it, and here is the exact path:

- `shared/session.py:403` - the receive loop matches `CancelledNotification`
  and calls `self._in_flight[requestId].cancel()`.
- `RequestResponder.cancel()` (`shared/session.py:139-149`) cancels the
  responder's `anyio.CancelScope` and immediately sends
  `ErrorData(code=0, message="Request cancelled")` for that request id.
- `server/lowlevel/server.py:_handle_message` runs every request inside
  `with responder:` (which enters that cancel scope), so cancelling the scope
  cancels **our** `call_tool` coroutine at its next checkpoint.
- `server/lowlevel/server.py:781` swallows the resulting `CancelledError`
  without sending a duplicate response.
- The same scope is also cancelled when the transport closes
  (`server/lowlevel/server.py:696`, `tg.cancel_scope.cancel()` in the `finally`
  of `run()`), i.e. when codex kills the MCP child.

So the SDK gives us a cancellation *signal*, but - see (a) - the signal cannot
reach a thread that is not looking for it, and while the thread runs, the
cancellation is not even delivered to the awaiting coroutine.

**The bridge we install** (`server.call_with_cancel_bridge`, WP1): the tool
call runs inside a small task group with a `sleep_forever()` watcher task. When
the responder's scope is cancelled the watcher is cancelled *promptly* (it is
at a checkpoint), and before re-raising it sets a `threading.Event` that is
handed to the tool through `ToolContext.cancel_event`. Cooperative loops
(`crystalpilot/tools/budget.py`) poll that event between iterations and raise
`Cancelled`, so the thread returns, the project lock frees, and the next queued
call starts. Measured on this machine with a 5 s fake computation and a cancel
at 0.5 s: the thread stopped at 0.50 s and the handler unwound at 0.51 s.
Regression test:
`tests/test_budget.py::test_cancel_bridge_stops_the_worker_and_frees_the_lock`
cancels exactly that scope and asserts the worker stopped, its `finally` ran
(= the lock was released) and the cancelled payload came back.

The watcher fires for **both** reasons the scope can be cancelled (client
`notifications/cancelled`, transport close), which is exactly what we want:
either way nobody will ever read the result.

## (c) Does codex 0.147 send `notifications/cancelled` when its tool timeout fires?

**No - and there is no evidence in the ka1 logs either way, so we designed for
both cases.**

- ka1 logs: `workdir/campaigns/ka1-org/org-tools-r1/logs/` and
  `ka1-cage/cage-full-r1/logs/` contain the rollout, SSE and engine events -
  i.e. the *agent's* view. There is no JSON-RPC wire trace on either side
  (`mcp_server.jsonl` holds one startup evidence line per process, nothing
  per-call). The only `cancel` hit in either log is the cage agent musing
  about whether it may terminate the cell. So the logs cannot decide it.
- The 0.147.0 binary contains the literal `notifications/cancelled` 16 times,
  but every occurrence sits next to serde derive metadata
  (`expect const string value "notifications/cancelled"`, next to
  `sampling/createMessage`, `notifications/progress`, ...). That proves the
  *type* is compiled in, not that the client *emits* it on timeout. The
  timeout message itself is the format string `timed out awaiting {} after {}`.
- Upstream: **openai/codex issue #26956** ("Codex never tells MCP servers to
  stop after tool call interrupt/timeout", opened 2026-06-08 against
  codex-cli 0.137.0, labels CLI/bug/mcp/tool-calls) reports precisely this: on
  interrupt or timeout codex "will drop the request future locally but sends
  nothing back", verified with a stdio server that logs whether the
  notification arrives. Still open, no maintainer reply, no linked PR - only
  the reporter's own fork branch `a9lim/codex:fix/mcp-client-cancellation`.
  Nothing indicates the fix landed in 0.147.0.
- Indirect ka1 evidence consistent with the report: after the 3 900 s timeout
  the server kept computing (`running 5729s`, then `running 7545s`) and
  cage-full's `optimize_weights` node n0087 landed 4 051 s after its
  predecessor. But that is equally consistent with "codex sent it and the
  thread ignored it", so it is not decisive on its own.

**Consequence for the design:** the wall-clock budget in each tool is the
primary mechanism and must be sized to fire *well before* codex's 3 900 s
(`workbench/core.py`, `tool_timeout_sec=3900`); the cancel-event bridge is a
bonus that also covers transport close and any future codex that starts
sending the notification.

---

## Do we need an `abort` tool?

**Proposal: no, and here is why it would not work anyway.**

An `abort` MCP tool would itself be a tool call on the same project, so it
would queue behind the lock it is trying to free - useless. Making it bypass
the lock is possible (it only needs to set a flag), but:

- it can only ever set the same cooperative flag the budget already polls, so
  it stops exactly the loops a budget would have stopped anyway, just sooner;
- it adds a tool to a 65-69 tool surface for a situation that, once budgets
  exist, resolves itself within a known, *stated* number of seconds;
- ka1 evidence says the agent's problem was not "I want to abort and cannot",
  it was "I have no idea whether this will ever end and no rule says I may
  stop waiting" (org-tools 50 waiting messages, cage-full 30). A budget plus a
  queue message that names the budget answers that; an abort button does not.

If a future case shows a tool stuck in a **non-cooperative** segment (a cctbx
C++ call with no Python checkpoint, e.g. a single huge `fft_map`), an abort
tool would still not help - only running that segment in a killable
subprocess would. That is the real escalation, and `run_shelxt`'s detached-job
pattern (`timeout_s` / `phasing_grace_s` / `detach` + `job_status` polling) is
the template for it: it is a separate process, so a watchdog can kill it.

**Recommended escalation order** if budgets prove insufficient:

1. widen `Budget` coverage to more loops (cheap, no new tools);
2. move the heaviest single-shot kernels behind the detached-job pattern
   already used by `run_shelxt` (`detach=true` + `job_status`), which gives
   real killability *and* keeps the project lock free;
3. only then consider an `abort` tool - and if so, as a **parameter** on an
   existing status tool (e.g. `get_project_brief(abort_running=true)`), not as
   a new tool, and it must be documented as cooperative-only.

## Invariants worth keeping

- `to_thread.run_sync` must keep `abandon_on_cancel=False`. Abandoning the
  thread would return control to the event loop while the thread still holds
  the project lock and still writes to the node store - the exact corruption
  risk the lock exists to prevent.
- A tool may only stop at a point where the session/node store is consistent.
  `Budget.check()` is therefore called *between* iterations (seeds, attempts,
  grid points, LS cycles), never inside one.
- Budgets are wall-clock defaults and every one of them is overridable via a
  `timeout_s` parameter. They are sized from measured campaign timings, never
  from a property of a particular crystal.

## (d) The client is gone and nobody looks: the orphaned server (2026-09-04)

Observed, not hypothesised. The MCP process of ka1 case org-tools_only
(`-m crystalpilot.mcp --project H:\CrystalPilot-campaigns\ka1-org\pe4fa7e09`,
started 2026-09-03 15:55) was found the next morning still alive: 518
CPU-minutes, one core busy (4.2 CPU-s per 4 s wall when sampled), 28
threads, while its codex parent had exited hours earlier and the campaign
itself had ended by the 7200 s timeout around 18:00. It was the unbounded
Pmmm charge flipping of KA1-ANALYSIS §3.2, on a pre-WP1 build: no budget, no
cancel bridge - and nothing that noticed the stdio pipe was broken.

Why anyio did not save us: on stdin EOF the SDK's reader task ends and
`Server.run` wants to return, but its task group waits for the in-flight
`call_tool` handler, which waits on `to_thread.run_sync` (uninterruptible,
and `abandon_on_cancel=False` must stay - see (a)). So `anyio.run` only
returns when the worker thread does. Post-WP1 the transport close sets the
cancel bridge's event, so a budgeted loop stops at its next check - but a
stage that cannot check the clock (a vendor subprocess, one big cctbx call)
still holds the process, and the interpreter then joins threads at exit.

Fix (server.py `_transport_watchdog`, started from `main()`): a daemon
thread polls a NON-destructive probe every `ORPHAN_POLL_S` (5 s) - on
Windows `PeekNamedPipe` on the stdin handle, which fails with
ERROR_BROKEN_PIPE / ERROR_NO_DATA / ERROR_INVALID_HANDLE once the writer is
gone and never consumes bytes (the SDK reader keeps sole ownership); on
POSIX a changed `os.getppid()`. A stdin that is not a pipe reports
"unknown", never "closed". Once the client is gone: a running tool gets
`ORPHAN_GRACE_S` (60 s, env `CRYSTALPILOT_MCP_ORPHAN_GRACE_S`) to finish
under the cancel bridge; then one evidence line goes to
`<project>/.crystalpilot/mcp_server.jsonl` (`event=transport_closed`,
`running_tool`, `elapsed_s`, `budget_s`, `action`) and the process
`os._exit(3)`s. An idle server exits after one poll (anyio normally beats
it). Vendor subprocesses the tool had started are not chased: SHELXL/SHELXT
runs are bounded by cycles/tries and end on their own; DIALS work is
detached by design.

Not done on purpose: killing the process from the workbench side. The
workbench does not own campaign MCP processes (codex spawns them), and a
process that watches its own transport needs no owner. `tests/
test_mcp_orphan_watchdog.py` drives the real path (pipe + thread +
`_exit`) in a subprocess without cctbx.
