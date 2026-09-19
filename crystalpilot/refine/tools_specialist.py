"""consult_specialist: a READ-ONLY advisor examines an isolated fixed snapshot
in its own Codex thread; the main agent adjudicates the second opinion.

Containment model:
- The specialist MCP reads a fixed, whitelisted scientific snapshot with its
  OWN project lock. Reopening the parent's project would deadlock against the
  full-invocation OS lock retained by the caller.
- CRYSTALPILOT_MCP_READONLY=1 refuses model edits; native multi_agent is also
  disabled. Advisors cannot recursively consult or write the parent's model.
- An ephemeral ProjectState carries only saved non-secret project overrides;
  no parent state/credentials are copied. Transcripts and bounded cancellation
  diagnostics live under <project>/.crystalpilot/specialists/<uuid>/.
- Availability is opt-in: project setting `enable_specialists` (Workbench
  settings UI) or env CRYSTALPILOT_SPECIALISTS=1 (headless runs). Default
  off - the workbench works exactly as before without sub-agents. Not
  registered inside readonly specialist servers (no recursion).
"""
from __future__ import annotations

import json
import os
import queue
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from ..tools.base import Tool, ToolContext, ToolResult
from ..tools.budget import default_timeout_s
from .nodes import atomic_write_json
from .specialist_snapshot import create_snapshot
from .transactions import TransactionCancelled, check_cancelled

CLEANUP_GRACE_S = 2.0
WAIT_POLL_S = 0.05


class SpecialistInterrupted(RuntimeError):
    def __init__(self, state: str, stats: dict, cleanup_pending: bool):
        super().__init__(f"Specialist {state}; interrupt/close requested for its isolated worker")
        self.state = state
        self.stats = stats
        self.cleanup_pending = cleanup_pending

# round-3 R7: the specialty table and the verdict schema are the ONE
# contract both consultation paths share (native roles + this nested tool)
from ..workbench.subagent_contract import (SPECIALTIES, VERDICT_SCHEMA,  # noqa: E402,F401
                                           parse_verdict)


def specialists_enabled(project_dir: Path) -> bool:
    if os.environ.get("CRYSTALPILOT_MCP_READONLY") == "1":
        return False          # no recursion inside a specialist
    if os.environ.get("CRYSTALPILOT_SPECIALISTS") == "1":
        return True
    state = Path(project_dir) / ".crystalpilot-workbench.json"
    if state.exists():
        try:
            data = json.loads(state.read_text(encoding="utf-8"))
            return bool((data.get("settings") or {})
                        .get("enable_specialists", False))
        except (OSError, json.JSONDecodeError):
            return False
    return False


def register_specialist_tools(reg, project) -> None:
    if specialists_enabled(project.dir):
        reg.register(ConsultSpecialist(project))


class ConsultSpecialist(Tool):
    name = "consult_specialist"
    description = (
        "Dispatch a READ-ONLY specialist sub-agent for a focused second "
        "opinion on THIS project, then adjudicate yourself. The specialist "
        "gets its own reasoning budget and only inspection tools (it cannot "
        "edit the model); you remain the only writer and the final judge. "
        "Use at genuinely hard forks - space-group doubt, ambiguous density, "
        "chemistry that contradicts priors, pre-delivery validation - not "
        "for routine steps you can decide directly. Costs a full model "
        "conversation; expect ~1-3 minutes. specialties: space_group | "
        "chemistry | density | validation | refinement_strategy.")
    params_schema = {
        "type": "object",
        "properties": {
            "specialty": {"type": "string",
                          "enum": sorted(SPECIALTIES.keys())},
            "question": {"type": "string",
                         "description": "the specific question, with the "
                                        "context the specialist needs "
                                        "(current hypothesis, competing "
                                        "options, relevant numbers)"},
            "node": {"type": "string",
                     "description": "node/branch to snapshot (default: active). Historical "
                                    "reflection nodes without matched data are refused."},
            "timeout_s": {"type": "number", "minimum": 1, "maximum": 900,
                          "default": default_timeout_s("consult_specialist"),
                          "description": "Execution budget after project queueing, including snapshot "
                                         "and advisor; plus at most 2s cleanup grace. Cancellation "
                                         "may report cleanup_pending, never a late successful verdict."},
        },
        "required": ["specialty", "question"],
    }

    def __init__(self, project) -> None:
        self.project = project

    def run(self, ctx: ToolContext, **params: Any) -> ToolResult:
        specialty = str(params["specialty"])
        if specialty not in SPECIALTIES:
            return ToolResult.failure(
                f"unknown specialty {specialty!r}; "
                f"choose from {sorted(SPECIALTIES)}")
        question = str(params["question"]).strip()
        if not question:
            return ToolResult.failure("question must not be empty")
        if not specialists_enabled(self.project.dir):
            return ToolResult.failure(
                "specialist sub-agents are disabled for this project. The "
                "user can enable them in the Workbench project settings "
                "(enable_specialists) or via CRYSTALPILOT_SPECIALISTS=1.")

        try:
            timeout_s = float(params.get("timeout_s", default_timeout_s(self.name)))
        except (TypeError, ValueError):
            return ToolResult.failure("timeout_s must be a number from 1 to 900")
        if not 1 <= timeout_s <= 900:
            return ToolResult.failure("timeout_s must be from 1 to 900")
        started = time.monotonic()
        deadline = started + timeout_s
        cancel = getattr(ctx, "cancel_event", None)
        progress = getattr(ctx, "progress", None)
        out_dir = self.project.dir / ".crystalpilot" / "specialists" / uuid.uuid4().hex
        out_dir.mkdir(parents=True)
        source = None
        try:
            snapshot = create_snapshot(self.project, out_dir, params.get("node"),
                                       cancel_event=cancel, deadline=deadline)
            source = snapshot.source
            atomic_write_json(out_dir / "consultation.json", {"status": "running", "source": source})
            prompt = self._specialist_prompt(SPECIALTIES[specialty], question, source["node"])
            prompt += ("\n\n你正在独立只读快照中，不是主项目。只检查此快照的活动节点；"
                       "不访问原项目路径，也不尝试读取未复制的历史节点。原始来源与限制：\n"
                       + json.dumps(source, ensure_ascii=False))
            verdict, stats = _run_specialist_turn(
                snapshot.directory, out_dir, prompt, settings=snapshot.settings,
                cancel_event=cancel, deadline=deadline, progress=progress)
            check_cancelled(cancel)
            if time.monotonic() >= deadline:
                raise TimeoutError("specialist execution budget expired before verdict publication")
            stats["total_execution_s"] = round(time.monotonic() - started, 3)
            atomic_write_json(out_dir / "verdict.json", {
                "specialty": specialty, "question": question, "source": source,
                "verdict": verdict, "stats": stats}, indent=2)
            atomic_write_json(out_dir / "consultation.json", {"status": "completed", "source": source})
        except Exception as exc:
            state = "failed"
            stats = {}
            pending = False
            if isinstance(exc, SpecialistInterrupted):
                state, stats, pending = exc.state, exc.stats, exc.cleanup_pending
            elif isinstance(exc, TransactionCancelled):
                state = "cancelled"
            elif isinstance(exc, TimeoutError):
                state = "timeout"
            record = {"status": state, "source": source, "error": str(exc),
                      "cleanup_pending": pending, "stats": stats}
            atomic_write_json(out_dir / "consultation.json", record, indent=2)
            summary = {"specialty": specialty, "source_state": source,
                       "specialist_cost": stats, "transcript_dir": str(out_dir),
                       "cleanup_pending": pending}
            if state == "cancelled":
                summary["cancelled"] = True
            elif state == "timeout":
                summary["timeout"] = str(exc)
            return ToolResult(ok=False, summary=summary,
                              artifacts={"diagnostic": str(out_dir / "consultation.json")},
                              error=f"specialist {state}: {type(exc).__name__}: {exc}")
        return ToolResult(ok=True, summary={
            "specialty": specialty, "verdict": verdict, "source_state": source,
            "specialist_cost": stats, "transcript_dir": str(out_dir),
            "adjudication_note": "Advice from a fixed read-only snapshot; verify load-bearing claims "
                                 "against your own tools and record disagreements.",
        })

    def _specialist_prompt(self, spec: dict, question: str,
                           node: str | None) -> str:
        node_line = (f"请针对固定快照的活动节点 `{node}`；checkout 被禁用，"
                     "未复制的历史节点不能比较。记录指标不是本次重新验证的结果。"
                     if node else "针对快照的当前活动节点。")
        return f"""你是本晶体学项目的{spec['role']}（只读子代理）。主精修 agent 请你出一份聚焦的第二意见。

你的职责：{spec['brief']}

{node_line}

主 agent 的问题：
{question}

规则：
- 你只有只读工具（inspect_model / inspect_map / check_ligand / get_geometry / check_symmetry / validate_structure / run_checkcif / list_nodes / compare_nodes / get_project_brief）。任何修改类工具都会被服务端拒绝，不要尝试，也不要试图用 shell 改文件。
- 每条结论必须给出工具来源和数字；诚实守则与 AGENTS.md 相同：数据不支持的不要说，拿不准就降低 confidence 并说明还缺什么证据。
- 一轮内完成：先调用需要的工具，然后按要求的 JSON schema 给出裁决。不要输出 JSON 以外的最终答复。"""


def _run_specialist_turn(project_dir: Path, out_dir: Path, prompt: str, *,
                         settings: dict[str, str], cancel_event=None,
                         deadline: float, progress=None) -> tuple[dict, dict]:
    """Supervise a snapshot-only worker; blocked SDK streams cannot retain the parent lock forever."""
    from openai_codex import Sandbox
    from openai_codex.types import ReasoningEffort
    from ..workbench.core import ProjectState, Workbench

    class _EphemeralState(ProjectState):
        def save(self) -> None:
            pass

        @property
        def results_root(self) -> Path:
            return out_dir

    state = _EphemeralState(path=Path(project_dir), settings=dict(settings))
    turn_kwargs = {"sandbox": Sandbox.read_only}
    if settings.get("model_override"):
        turn_kwargs["model"] = settings["model_override"]
    if settings.get("effort_override"):
        turn_kwargs["effort"] = ReasoningEffort(settings["effort_override"])
    stats = {"n_tool_calls": 0, "input_tokens": None, "output_tokens": None,
             "wall_s": None,
             "configuration": {
                 "model": settings.get("model_override"),
                 "provider": settings.get("model_provider_override"),
                 "effort": settings.get("effort_override"),
                 "source": "saved_project_overrides; absent values use isolated engine defaults",
                 "parent_turn_overrides_known": False,
             }}
    guard = threading.Lock()
    replies = queue.Queue(maxsize=1)
    interrupted = threading.Event()
    runtime = {"workbench": None, "task": None}
    started = time.monotonic()

    def on_event(ev: dict) -> None:
        # Callback and iterator may overlap. Only the iterator counts tool
        # completions; cumulative token totals can safely reach either channel.
        if ev.get("kind") == "token_usage":
            totals = ev.get("total") or {}
            with guard:
                for key in ("input_tokens", "output_tokens"):
                    value = totals.get(key)
                    if isinstance(value, int):
                        stats[key] = max(stats[key] or 0, value)

    def worker() -> None:
        try:
            wb = Workbench(state, event_cb=on_event, mcp_readonly=True,
                           mcp_approval="auto", multi_agent=False)
            with guard:
                runtime["workbench"] = wb
            if interrupted.is_set():
                wb.close()
                return
            with wb:
                if interrupted.is_set():
                    return
                task = wb.new_task(title="specialist",
                                   model_provider=settings.get("model_provider_override"))
                with guard:
                    runtime["task"] = task
                if interrupted.is_set():
                    task.interrupt()
                    return
                final = ""
                for ev in task.send(prompt, output_schema=VERDICT_SCHEMA,
                                    turn_kwargs=turn_kwargs):
                    if interrupted.is_set():
                        return
                    on_event(ev)
                    if ev.get("kind") == "tool_completed":
                        with guard:
                            stats["n_tool_calls"] += 1
                    if ev.get("kind") == "agent_message":
                        final = ev.get("text") or ""
                    if ev.get("kind") == "turn_failed":
                        raise RuntimeError(f"specialist turn failed: {ev.get('error')}")
            if not interrupted.is_set():
                replies.put((True, parse_verdict(final)))
        except Exception as exc:
            if not interrupted.is_set():
                replies.put((False, exc))

    thread = threading.Thread(target=worker, daemon=True, name="specialist-snapshot-turn")
    thread.start()
    next_ping = started + 10
    while True:
        now = time.monotonic()
        cancelled = cancel_event is not None and cancel_event.is_set()
        if cancelled or now >= deadline:
            interrupted.set()
            with guard:
                task, wb = runtime["task"], runtime["workbench"]

            def best_effort(action):
                try:
                    action()
                except Exception:
                    pass

            # Either SDK method may itself block; neither is allowed to keep
            # the caller's project lock. They affect only this owned worker.
            cleanup = []
            for action in ((task.interrupt if task is not None else None),
                           (wb.close if wb is not None else None)):
                if action is not None:
                    closer = threading.Thread(target=best_effort, args=(action,), daemon=True)
                    closer.start()
                    cleanup.append(closer)
            stop_by = time.monotonic() + CLEANUP_GRACE_S
            thread.join(max(0, stop_by - time.monotonic()))
            for closer in cleanup:
                closer.join(max(0, stop_by - time.monotonic()))
            with guard:
                stats["wall_s"] = round(time.monotonic() - started, 3)
                measured = dict(stats)
            raise SpecialistInterrupted("cancelled" if cancelled else "timeout", measured,
                                        thread.is_alive() or any(t.is_alive() for t in cleanup))
        if progress is not None and now >= next_ping:
            next_ping = now + 10
            try:
                progress("specialist: reading an isolated fixed snapshot; awaiting advisor response")
            except Exception:
                pass
        try:
            ok, reply = replies.get(timeout=min(WAIT_POLL_S, max(0, deadline - now)))
        except queue.Empty:
            continue
        check_cancelled(cancel_event)
        if time.monotonic() >= deadline:
            raise TimeoutError("specialist execution budget expired")
        if not ok:
            raise reply
        with guard:
            stats["wall_s"] = round(time.monotonic() - started, 3)
            return reply, dict(stats)
