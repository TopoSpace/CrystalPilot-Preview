"""Agent campaign runner: drive full blind refinement campaigns through the
workbench HTTP API, then grade each delivery with the mentor-side grader.

Design:
  * engine-side script, NOT a workbench extension - it talks to the same
    HTTP surface the UI uses (every campaign doubles as an API regression
    test), and survives server restarts because all state lives in
    workdir/campaigns/<campaign>/state.json.
  * strictly serial across cases; never passes allow_concurrent (the
    project lock is part of what we are testing). 409 -> backoff+retry.
  * blind hygiene: reference paths live only in the manifest (mentor
    side); the runner writes context.json but never anything
    reference-derived into the project. Optional directory junctions mask
    identifying dataset names (CCDC numbers) from the agent.
  * grading is an in-process import of benchmark.grade.grade_delivery;
    grade output goes to the campaign workdir, never the project.

Manifest (benchmark/campaigns/<name>.json):
  {"campaign": "r11-rodin", "server": "http://127.0.0.1:8010/api",
   "projects_root": "H:/CrystalPilot-campaigns/r11",   # OUTSIDE the repo
   # defaults.anonymize_lane: true -> the lane folder becomes l<sha1[:8]>
   # beside projects_root, so the campaign name never reaches the agent
   "defaults": {"permission_mode": "auto", "case_timeout_s": 10800,
                "model_override": "...", "effort_override": "xhigh",
                "knowledge_mode": "full"},   # or "tools_only" (ka1 arm A)
   "cases": [{"name": "case-a",
              "context": {...},              # written to context.json
              "brief": "...{data_dir}...",   # the campaign task message
              "data_alias": {"link": "...", "target": "..."},  # optional
              "reference": "H:/CrystalPilotData/rodin/refs/x.cif",
              "reference_kind": "exact",
              "followups": ["..."]}]}

CLI: python -m crystalpilot.benchmark.agent_campaign <manifest.json>
         [--only case-a] [--regrade]

projects_root must not sit inside the engine repo: codex concatenates every
AGENTS.md from the git toplevel down to the project cwd, so pa1-pa4 (under
workbench/pa*/) ran with the stale repo-root AGENTS.md prepended to the
template. Each opened case records the template it actually ran under
(knowledge_mode, agents_version, agents_sha256, root_agents_sha256,
agents_chain) in state.json - see workbench.agents_md.agents_md_record.
"""
from __future__ import annotations

import json
import re
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]

#: structured end-of-task verdict; feeds the grader's honesty gates.
#: strict response_format rule: EVERY property must be in required -
#: optionality is expressed as ["...", "null"] unions instead
VERDICT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "solved": {"type": "boolean"},
        "space_group": {"type": ["string", "null"]},
        "r1": {"type": ["number", "null"]},
        "wr2": {"type": ["number", "null"]},
        "n_atoms": {"type": ["integer", "null"]},
        "delivered": {"type": "boolean",
                      "description": "write_outputs publication CIF done"},
        "unresolved": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "string",
                       "enum": ["high", "medium", "low"]},
        "summary": {"type": "string"},
    },
    "required": ["solved", "space_group", "r1", "wr2", "n_atoms",
                 "delivered", "unresolved", "confidence", "summary"],
    "additionalProperties": False,
}

#: turn outcomes where the RUNNER ended the turn rather than the agent
#: finishing it. Both mean the same thing for the verdict: the agent was
#: never asked, or never able to answer, so whatever it had at that moment
#: is on disk and nowhere else.
INTERRUPTED_TURN_STATUSES = ("timeout", "no_tools")

#: leash on every turn issued AFTER an interrupt. A case that has already
#: spent its whole case_timeout_s must not be able to spend another one on
#: the verdict turn: ka1's org lane took 7224 s of a 7200 s budget and
#: then went back to the same thread for more. The verdict turn does no
#: refinement, so ten minutes is generous for the work it is allowed to do.
INTERRUPT_TAIL_S = 600.0

#: A turn that ends with a TRANSIENT transport error leaves the codex
#: thread and the node tree intact - only the model stream broke. reg11-cage
#: (2026-09-05 07:30): "stream disconnected before completion: stream
#: closed before response.completed" twice in a row, minutes before the
#: host crashed (Kernel-Power 41); the same error four times on
#: 2026-08-28 inside 25 minutes and never in the ~40 cells in between. The
#: old runner took the first failure as final and graded 32 minutes of
#: work no_delivery. Now: wait, resend a "continue from where you were" on
#: the same thread, at most STREAM_RETRIES times per turn.
STREAM_RETRIES = 2
STREAM_RETRY_WAIT_S = 45.0
TRANSIENT_TURN_ERROR = re.compile(
    r"stream disconnected|stream closed|response\.completed|connection "
    r"(reset|aborted|refused)|broken pipe|temporarily unavailable|"
    r"\b(502|503|504)\b|gateway time|timed out while|overloaded",
    re.IGNORECASE)
CONTINUE_AFTER_STREAM_ERROR = (
    "运行提示：上一轮因模型流中断（stream disconnected）而失败，工作台线程与节点树"
    "完好，这不是你的错也不是工具缺陷。请从中断处继续：先用 situation_report 或 "
    "list_nodes 确认当前节点与分支，不要重复已完成的步骤，也不要为此重启任何进程。")


def is_transient_turn_error(err: Any) -> bool:
    return bool(err) and bool(TRANSIENT_TURN_ERROR.search(str(err)))


def _load_json(path: Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def harvest_after_interrupt(project_dir: Path,
                            task_id: str | None = None) -> dict[str, Any]:
    """Whatever the agent had already written when its turn was cut off.

    ka1's org-tools_only lane is the case this exists for: it hit the
    7200 s campaign timeout mid-turn, so the runner recorded no verdict at
    all - which made it indistinguishable from a case where the agent
    produced nothing. Those are different findings, and the difference is
    on disk: a verdict.json the agent wrote itself, a task directory, a
    write_outputs product set. So they get read.

    Reports what exists and nothing else. No field here is derived,
    guessed or defaulted: if the agent delivered nothing, every value is
    None or empty and the caller says so.
    """
    project_dir = Path(project_dir)
    out: dict[str, Any] = {"verdict": None, "verdict_path": None,
                           "task_dir": None, "products": [],
                           "final_cif": None}
    results = project_dir / "CrystalPilot Results"
    tasks: list[Path] = []
    if task_id:
        preferred = results / str(task_id)
        if preferred.is_dir():
            tasks.append(preferred)          # the task THIS run started
    try:
        tasks += sorted((p for p in results.iterdir() if p.is_dir()),
                        key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        pass                                  # no delivery directory at all
    seen: set[Path] = set()
    tasks = [t for t in tasks if not (t in seen or seen.add(t))]

    if tasks:
        out["task_dir"] = str(tasks[0])
        try:
            out["products"] = sorted(
                p.relative_to(tasks[0]).as_posix()
                for p in tasks[0].rglob("*") if p.is_file())[:200]
        except OSError:
            pass
    for cand in [t / "verdict.json" for t in tasks] + [
            project_dir / "verdict.json"]:
        data = _load_json(cand)
        if isinstance(data, dict):
            out["verdict"] = data
            out["verdict_path"] = str(cand)
            break
    try:
        from .grade import find_delivery
        cif = find_delivery(project_dir)
    except Exception:  # noqa: BLE001 - harvesting must never raise
        cif = None
    out["final_cif"] = str(cif) if cif else None
    return out


class Api:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")

    def _req(self, method: str, path: str, body: dict | None = None,
             timeout: float = 60.0):
        url = self.base + path
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            url, data=data, method=method,
            headers={"Content-Type": "application/json"} if data else {})
        return urllib.request.urlopen(req, timeout=timeout)

    def post(self, path: str, body: dict, timeout: float = 60.0) -> dict:
        with self._req("POST", path, body, timeout) as r:
            return json.loads(r.read().decode())

    def get(self, path: str, timeout: float = 60.0) -> dict:
        with self._req("GET", path, None, timeout) as r:
            return json.loads(r.read().decode())

    def sse_events(self, thread_id: str, after: int = 0):
        """Yield (seq, event) from the thread SSE channel; returns on
        disconnect (caller decides whether to re-attach or poll)."""
        req = urllib.request.Request(
            f"{self.base}/threads/events?thread_id={thread_id}&after={after}")
        # 90 s socket timeout: on a dead thread (host reboot killed the
        # turn) the replayed history ends and the live stream goes silent
        # forever - the read timeout is what breaks wait_turn out to its
        # busy-poll fallback. Live turns are unaffected: a silent long
        # tool call just re-attaches from the cursor.
        with urllib.request.urlopen(req, timeout=90.0) as resp:
            seq, buf = after, []
            for raw in resp:
                line = raw.decode("utf-8", "replace").rstrip("\n\r")
                if line.startswith("id:"):
                    try:
                        seq = int(line[3:].strip())
                    except ValueError:
                        pass
                elif line.startswith("data:"):
                    buf.append(line[5:].lstrip())
                elif not line and buf:
                    try:
                        yield seq, json.loads("\n".join(buf))
                    except json.JSONDecodeError:
                        pass
                    buf = []


def anonymous_project_name(campaign_name: str, case_name: str) -> str:
    """Opaque project-folder name for a case.

    The project folder is the agent's cwd, so its name is in every shell
    prompt and tool result. pa1's `cu-l0-r2` style names leaked the metal:
    four "blind" cu runs cited "项目标识中的 Cu 线索" as evidence for Cu,
    while r22b (`case-b-blind`) had no such hint and chose Ni. Stable per
    (campaign, case) so resumes land in the same folder."""
    import hashlib
    h = hashlib.sha1(f"{campaign_name}/{case_name}".encode("utf-8"))
    return "p" + h.hexdigest()[:8]


def anonymous_lane_dir(projects_root: str | Path, campaign_name: str) -> Path:
    """Opaque lane folder beside the named one.

    The lane folder is the parent of the agent's cwd, so it is in every
    prompt and path the agent sees: reg2-mof (2026-09-04) read the word
    "mof" out of `H:/CrystalPilot-campaigns/reg2-mof/...` while the
    project itself was anonymised. Stable per campaign name so a resume
    or --regrade lands in the same folder."""
    import hashlib
    h = hashlib.sha1(campaign_name.encode("utf-8")).hexdigest()[:8]
    return Path(projects_root).parent / f"l{h}"


class CaseRun:
    def __init__(self, campaign: "Campaign", case: dict[str, Any]) -> None:
        self.c = campaign
        self.case = case
        self.name = case["name"]
        folder = self.name
        if (case.get("anonymize_project", campaign.defaults.get(
                "anonymize_projects", False))):
            folder = anonymous_project_name(campaign.name, self.name)
        self.project_dir = Path(case.get("project_dir")
                                or Path(campaign.projects_root) / folder)
        # a --regrade of a finished lane must find the folder the run
        # actually used: a manifest regenerated with the other naming
        # convention (pa1-hex rewritten with anonymize_projects on) sent
        # eight graded cells to 'no_delivery'
        if not self.project_dir.exists() and not case.get("project_dir"):
            other = Path(campaign.projects_root) / (
                self.name if folder != self.name
                else anonymous_project_name(campaign.name, self.name))
            if other.exists():
                self.project_dir = other
        self.out_dir = campaign.work / self.name
        # full log bundle: the run's own numbers answer "how did it score",
        # the bundle answers "why did it go that way" (campaign_logs)
        from .campaign_logs import CaseLogger
        self.logger = CaseLogger(self.out_dir, self.project_dir, self.name)

    # -- state -------------------------------------------------------------
    @property
    def st(self) -> dict[str, Any]:
        return self.c.state.setdefault(self.name, {"status": "pending"})

    def _save(self, **kw: Any) -> None:
        self.st.update(kw)
        self.c.save_state()

    # -- stages ------------------------------------------------------------
    def ensure_alias(self) -> None:
        al = self.case.get("data_alias")
        if not al:
            return
        link, target = Path(al["link"]), Path(al["target"])
        if link.exists():
            return
        if not target.exists():
            raise RuntimeError(f"data_alias target missing: {target}")
        link.parent.mkdir(parents=True, exist_ok=True)
        # directory junction: masks identifying dataset names (CCDC numbers)
        # from the agent without copying gigabytes; no elevation needed
        from ..procutil import NO_WINDOW
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                       check=True, capture_output=True,
                       creationflags=NO_WINDOW)

    def check_staging_hygiene(self) -> list[str]:
        """Answer-shaped files in the agent-visible data dir.

        The staging tree is built by hand, and answer material lives one
        directory away from blind data more often than is comfortable: the
        2026-09 E-drive survey found solved CIFs for three blind crystals
        in a sibling folder, and benchmark/data ships a SHELXT solution
        (194 atoms, the space group in the header) as `ins.ins`. A leak
        here does not fail the campaign, it silently invalidates the
        score, so the check runs before the brief is sent and refuses."""
        data_dir = ((self.case.get("data_alias") or {}).get("target")
                    or self.case.get("data_dir"))
        if not data_dir or self.case.get("allow_answers_in_data"):
            return []
        found: list[str] = []
        for p in sorted(Path(data_dir).rglob("*")):
            if not p.is_file() or p.suffix.lower() not in (
                    ".res", ".cif", ".ins", ".fcf"):
                continue
            try:
                head = p.read_text(encoding="utf-8",
                                   errors="replace")[:200_000]
            except OSError:
                continue
            if p.suffix.lower() == ".cif":
                if "_atom_site_fract_x" in head:
                    found.append(f"{p.name}: CIF with refined coordinates")
                continue
            # .ins/.res: atoms are lines of "<label> <sfac#> x y z sof U"
            atoms = len(re.findall(
                r"^[A-Za-z]{1,2}[A-Za-z0-9_]*\s+\d+\s+-?\d*\.\d+\s+"
                r"-?\d*\.\d+\s+-?\d*\.\d+", head, re.M))
            if atoms >= 5:
                found.append(f"{p.name}: {atoms} atom records")
        return found

    def open_project(self) -> None:
        leaks = self.check_staging_hygiene()
        if leaks:
            raise RuntimeError(
                f"case '{self.name}': answer material in the agent-visible "
                f"data dir - {'; '.join(leaks[:6])}. Move it to a mentor-"
                "side reference/ directory outside data_dir, or set "
                "allow_answers_in_data=true if the case deliberately "
                "starts from a known model.")
        self.ensure_alias()
        self.project_dir.mkdir(parents=True, exist_ok=True)
        ctx = self.case.get("context")
        if ctx is not None:
            (self.project_dir / "context.json").write_text(
                json.dumps(ctx, indent=2, ensure_ascii=False),
                encoding="utf-8")
        self.c.api.post("/projects/open", {"path": str(self.project_dir)})
        mode = self.c.defaults.get("permission_mode", "auto")
        body: dict[str, Any] = {"path": str(self.project_dir),
                                "permission_mode": mode}
        # model / reasoning-effort for the lane (pa4: gpt-5.6-sol-fast
        # trial); the case may override the lane. Applied per turn by the
        # workbench, recorded here so the analysis knows what ran.
        overrides = {k: v for k, v in (
            ("model_override", self.case.get(
                "model_override", self.c.defaults.get("model_override"))),
            ("effort_override", self.case.get(
                "effort_override", self.c.defaults.get("effort_override"))),
            # ka1 ablation arm: "tools_only" | "full" (default full)
            ("knowledge_mode", self.case.get(
                "knowledge_mode", self.c.defaults.get("knowledge_mode"))),
            # round-2 R7: "off" | "top_tier" (default top_tier - the
            # delegation hint + read-only roles exist only at xhigh)
            ("subagents", self.case.get(
                "subagents", self.c.defaults.get("subagents"))),
        ) if v}
        if overrides:
            body["settings"] = overrides
        eff = self.c.api.post("/projects/settings", body)
        # the template the agent will actually see, by content hash, plus
        # every other AGENTS.md codex injects above the project (must be
        # none for a clean arm) - read back from disk, not from the request
        from ..workbench.agents_md import agents_md_record
        delegation = eff.get("delegation") or {}
        rec = agents_md_record(self.project_dir,
                               eff.get("knowledge_mode")
                               or overrides.get("knowledge_mode"),
                               delegate=bool(delegation.get("active")))
        self._save(status="opened",
                   model=eff.get("model"), effort=eff.get("effort"),
                   subagents=eff.get("subagents"), **rec)

    def _brief(self) -> str:
        data_dir = (self.case.get("data_alias") or {}).get(
            "link") or self.case.get("data_dir") or ""
        return str(self.case["brief"]).replace("{data_dir}", str(data_dir))

    def send(self, message: str, first: bool,
             with_schema: bool = False) -> str:
        body = {"project": str(self.project_dir), "message": message,
                "title": f"campaign:{self.c.name}:{self.name}"}
        if not first and self.st.get("thread_id"):
            body["thread_id"] = self.st["thread_id"]
        if with_schema:
            # ONLY on the dedicated verdict followup: output_schema
            # constrains every assistant message of that turn, so putting
            # it on the working turn renders raw JSON blobs in the chat UI
            # (seen live on r11 case-b)
            body["output_schema"] = (self.case.get("output_schema")
                                     or VERDICT_SCHEMA)
        for attempt in range(120):
            try:
                r = self.c.api.post("/threads/send", body)
                self._save(status="sent", thread_id=r["thread_id"],
                           task_id=r.get("task_id"))
                return r["thread_id"]
            except urllib.error.HTTPError as e:
                if e.code == 409:
                    # project lock: respect it, never allow_concurrent
                    time.sleep(min(30, 5 + attempt))
                    continue
                raise
        raise RuntimeError("409 project-busy did not clear in 10 min")

    def _mcp_ready(self, within_s: float = 180.0) -> dict[str, Any]:
        """Poll the toolset probe until the crystalpilot MCP reports a sane
        tool count. Codex spawns the MCP lazily at first turn and a healthy
        cctbx import takes 10-20 s, so poll rather than one-shot."""
        deadline = time.time() + within_s
        last: dict[str, Any] = {}
        while time.time() < deadline:
            try:
                last = self.c.api.post("/projects/mcp_status",
                                       {"path": str(self.project_dir)})
            except Exception as e:  # noqa: BLE001
                last = {"error": str(e)}
            if (last.get("n_tools") or 0) >= 30:
                return last
            time.sleep(5)
        return last

    #: turn 1 of every case: absorbs codex's tool-surface race (below)
    WARMUP = ("会话初始化：本回合只回复「就绪」两个字，不要调用任何工具，"
              "不要开始任务。")
    #: injected when the working turn has gone LIVENESS_S without a single
    #: crystalpilot tool call - the signature of an agent that concluded
    #: "no MCP" from an empty first probe and went its own way
    LIVENESS_STEER = ("运行提示：crystalpilot 的 MCP 工具现在已在 ALL_TOOLS 里"
                      "（mcp__crystalpilot__*，get_project_brief / "
                      "ingest_vendor_data / run_shelxt …）。请重新过滤 "
                      "ALL_TOOLS 并改用这些工具完成任务；不要用 CLI 或自写"
                      "脚本驱动引擎，那样的结果不会被采信。")
    LIVENESS_S = 300.0

    def _interrupt_and_restart(self, tid: str | None) -> None:
        if tid:
            try:
                self.c.api.post("/threads/interrupt", {"thread_id": tid})
            except Exception:  # noqa: BLE001
                pass
        for _ in range(24):  # restart_engine 409s until the turn ends
            time.sleep(5)
            try:
                self.c.api.post("/projects/restart_engine",
                                {"path": str(self.project_dir)})
                break
            except urllib.error.HTTPError as e:
                if e.code != 409:
                    raise
        else:
            raise RuntimeError("interrupt did not release the turn")
        self.st.pop("thread_id", None)
        self._save(status="opened", saw_crystalpilot=False,
                   liveness_steered=False)

    def _first_send_gated(self) -> str:
        """First send behind two gates.

        1. A WARM-UP turn. Codex builds each model request's tool set when
           the request goes out and spawns the crystalpilot MCP lazily at
           the first turn, so the first request of a fresh thread almost
           never carries the crystalpilot tools (pa1: 22/31 empty first
           ALL_TOOLS probes; the 4 agents that did not look again took
           the old CLI clause as their licence and delivered nothing
           auditable). A no-tool warm-up turn absorbs the race: the brief
           goes out as turn 2, when the thread's MCP has long answered
           tools/list. (mcpServerStatus/list cannot gate this - it
           reports the app-server's own connection, 63 tools before any
           thread exists.)
        2. The MCP liveness probe (r11 case-c: the MCP child froze during
           startup; codex ran the whole session with an empty toolset).
        One engine-restart retry, then the case fails as an environment
        failure instead of burning hours of toolless agent time."""
        for attempt in (1, 2):
            tid = self.send(self.WARMUP, first=True)
            warm = self.wait_turn(tid, deadline_s=240.0, liveness_s=None)
            probe = self._mcp_ready()
            if (str(warm.get("status", "")).startswith("completed")
                    and (probe.get("n_tools") or 0) >= 30):
                self._save(mcp_tools=probe["n_tools"],
                           warmup_ms=warm.get("duration_ms"))
                return self.send(self._brief(), first=False)
            self._save(mcp_env_note=(f"attempt {attempt}: warm-up turn "
                                     f"{warm.get('status')}, MCP probe "
                                     f"{probe}"))
            self._interrupt_and_restart(tid)
        raise RuntimeError("MCP toolset unavailable after engine restart")

    def _steer(self, thread_id: str, message: str) -> bool:
        try:
            self.c.api.post("/threads/steer",
                            {"thread_id": thread_id, "message": message})
            return True
        except Exception:  # noqa: BLE001 - 409 when idle; best-effort
            return False

    def wait_turn(self, thread_id: str, deadline_s: float | None = None,
                  liveness_s: float | None = LIVENESS_S) -> dict[str, Any]:
        """Follow SSE until turn_completed/turn_failed; fall back to busy
        polling on disconnect. Returns {status, error?, usage, agent_text}.

        liveness_s: agent-side check the tool-surface race needs (nothing
        in the workbench watches "MCP up, agent never used it"). A working
        turn with no crystalpilot tool call after liveness_s gets one
        steer; after 2*liveness_s it returns status 'no_tools' so run()
        can restart the engine and resend."""
        deadline = time.time() + float(
            deadline_s or self.case.get("case_timeout_s")
            or self.c.defaults.get("case_timeout_s", 10800))
        if liveness_s is not None:
            liveness_s = float(self.c.defaults.get("liveness_s", liveness_s))
        t_start = time.time()
        saw_cp = bool(self.st.get("saw_crystalpilot"))
        steered = bool(self.st.get("liveness_steered"))
        cursor = int(self.st.get("sse_cursor") or 0)
        usage: dict[str, Any] = dict(self.st.get("usage") or {})
        n_tools = int(self.st.get("n_tool_events") or 0)
        agent_text = self.st.get("agent_text") or ""
        while True:
            if time.time() > deadline:
                try:
                    self.c.api.post("/threads/interrupt",
                                    {"thread_id": thread_id})
                except Exception:  # noqa: BLE001
                    pass
                # the last thing the agent said before the plug was pulled
                # is evidence too, and the other two exits already keep it
                self._save(sse_cursor=cursor, usage=usage,
                           n_tool_events=n_tools,
                           agent_text=agent_text[-8000:])
                return {"status": "timeout", "usage": usage,
                        "agent_text": agent_text}
            try:
                for seq, ev in self.c.api.sse_events(thread_id, cursor):
                    cursor = seq
                    # every event to disk before it is reduced to a counter
                    self.logger.sse(seq, ev)
                    kind = ev.get("kind")
                    if kind == "token_usage" and ev.get("total"):
                        usage = ev["total"]
                    elif kind and kind.startswith(("tool_", "command")):
                        n_tools += 1
                        if not saw_cp and ev.get("server") == "crystalpilot":
                            saw_cp = True
                            self._save(saw_crystalpilot=True)
                    elif kind == "agent_message":
                        agent_text = ev.get("text") or agent_text
                    if liveness_s and not saw_cp:
                        idle = time.time() - t_start
                        if idle > 2 * liveness_s:
                            self.logger.sse(cursor, {
                                "kind": "runner_liveness", "action": "give_up",
                                "idle_s": round(idle), "ts": time.time()})
                            self._save(sse_cursor=cursor, usage=usage,
                                       n_tool_events=n_tools,
                                       agent_text=agent_text[-8000:])
                            return {"status": "no_tools", "usage": usage,
                                    "agent_text": agent_text}
                        if idle > liveness_s and not steered:
                            steered = True
                            self._save(liveness_steered=True)
                            ok = self._steer(thread_id, self.LIVENESS_STEER)
                            self.logger.sse(cursor, {
                                "kind": "runner_liveness", "action": "steer",
                                "delivered": ok, "idle_s": round(idle),
                                "ts": time.time()})
                    if kind in ("turn_completed", "turn_failed"):
                        self._save(sse_cursor=cursor, usage=usage,
                                   n_tool_events=n_tools,
                                   agent_text=agent_text[-8000:])
                        return {"status": ("completed"
                                           if kind == "turn_completed"
                                           and not ev.get("error")
                                           else "failed"),
                                "error": ev.get("error"),
                                "duration_ms": ev.get("duration_ms"),
                                "usage": usage, "agent_text": agent_text}
                    if time.time() > deadline:
                        break
            except (urllib.error.URLError, TimeoutError, OSError):
                pass  # SSE dropped - fall through to the busy poll
            self._save(sse_cursor=cursor, usage=usage,
                       n_tool_events=n_tools)
            try:
                meta = self.c.api.get(
                    f"/threads/list?project={self.project_dir}")
                mine = next((t for t in meta.get("threads", [])
                             if t.get("thread_id") == thread_id), None)
                if mine is not None and not mine.get("busy"):
                    return {"status": "completed(poll)", "usage": usage,
                            "agent_text": agent_text}
            except Exception:  # noqa: BLE001
                pass
            time.sleep(10)

    def interrupted(self) -> bool:
        """Did the runner end the last turn, rather than the agent?"""
        return (str(self.st.get("turn_status") or "")
                in INTERRUPTED_TURN_STATUSES)

    def grade(self) -> dict[str, Any]:
        from .grade import grade_delivery
        r = grade_delivery(
            self.project_dir,
            reference=self.case.get("reference") or None,
            reference_kind=self.case.get("reference_kind", "exact"),
            out_dir=self.out_dir)
        verdict, source = None, None
        txt = (self.st.get("agent_text") or "").strip()
        if txt:
            try:
                verdict, source = json.loads(txt), "final_turn"
            except json.JSONDecodeError:
                verdict = {"unparsed": txt[:2000]}
                source = "final_turn_unparsed"
        if self.interrupted():
            harvest = harvest_after_interrupt(self.project_dir,
                                              self.st.get("task_id"))
            harvest["last_agent_text"] = txt[:2000] or None
            r["interrupted"] = True
            r["interrupt_turn_status"] = self.st.get("turn_status")
            r["interrupt_harvest"] = harvest
            # a verdict the agent WROTE beats the last thing it happened
            # to be saying when the runner pulled the plug ("状态无变化：
            # 原求解仍在运行" is not a verdict, and ka1 stored it as one)
            if isinstance(harvest.get("verdict"), dict) and (
                    source in (None, "final_turn_unparsed")):
                verdict, source = (harvest["verdict"],
                                   "harvested_after_interrupt")
        if verdict is not None:
            (self.out_dir / "verdict.json").write_text(
                json.dumps(verdict, indent=2, ensure_ascii=False),
                encoding="utf-8")
            r["verdict"] = verdict
            # offline honesty gate b: verdict R1 vs delivered CIF R1
            cif_r1 = ((r.get("self_consistency") or {}).get("cif")
                      or {}).get("r1_gt")
            v_r1 = verdict.get("r1") if isinstance(verdict, dict) else None
            if cif_r1 is not None and v_r1 is not None:
                r["verdict_matches_cif"] = bool(
                    abs(float(v_r1) - cif_r1) <= 0.002)
        r["verdict_source"] = source
        if r.get("grade") == "no_delivery" and self.interrupted():
            # grading from the delivered CIF is what grade_delivery already
            # does whenever one exists - interrupted or not. Reaching here
            # means there was none, and the honest report of that is which
            # of the two ways it happened, not a guess at what might have
            # been coming.
            r["no_delivery_reason"] = "interrupted_before_verdict"
            r.setdefault("grade_reasons", []).append(
                "interrupted_before_verdict：主轮被 runner 中断"
                f"（{self.st.get('turn_status')}），项目里没有 "
                "CrystalPilot Results/*/final.cif + final.fcf 交付"
                + (f"；中断时任务目录里有 "
                   f"{len(r['interrupt_harvest']['products'])} 个文件"
                   if (r.get("interrupt_harvest") or {}).get("products")
                   else "；中断时任务目录是空的"))
        # grade.json is re-written because everything above was added to
        # the result AFTER grade_delivery wrote its own copy
        (self.out_dir / "grade.json").write_text(
            json.dumps(r, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8")
        self._save(status="graded", grade=r.get("grade"),
                   verdict_matches_cif=r.get("verdict_matches_cif"),
                   verdict_source=source)
        return r

    # -- one case, resumable ----------------------------------------------
    def run(self) -> None:
        st = self.st.get("status", "pending")
        if st == "graded":
            return
        if st in ("pending",):
            self.open_project()
            st = "opened"
        if st == "opened":
            t0 = time.time()
            self._save(started_at=time.strftime("%Y-%m-%d %H:%M:%S"))
            tid = self._first_send_gated()
            st = "sent"
        else:
            tid = self.st.get("thread_id")
            # resuming after a runner/host restart: the fresh server has
            # no open project session and /threads/send would 400 (live
            # failure, r15 reboot). Re-open idempotently.
            try:
                self.open_project()
            except Exception:  # noqa: BLE001 - wait_turn surfaces real trouble
                pass
            t0 = None
        if st == "sent" and tid:
            r = self.wait_turn(tid)
            if r["status"] == "no_tools" and not self.st.get("no_tools_restart"):
                # the agent never touched the tool face despite the steer:
                # environment, not crystallography - restart once, resend
                self._save(no_tools_restart=True,
                           mcp_env_note="working turn had no crystalpilot "
                                        "call after steer; engine restarted "
                                        "and brief resent")
                self._interrupt_and_restart(tid)
                self.open_project()
                tid = self._first_send_gated()
                r = self.wait_turn(tid)
            r = self._retry_transient(tid, r)
            cut_off = r["status"] in INTERRUPTED_TURN_STATUSES
            self._save(turn_status=r["status"], turn_error=r.get("error"),
                       interrupted=cut_off,
                       wall_s=(round(time.time() - t0, 1) if t0 else
                               self.st.get("wall_s")))
            fus = self.case.get("followups") or []
            done = int(self.st.get("n_followups_done") or 0)
            # after an interrupt every remaining turn is short-leashed, and
            # none of them may cost the case its log bundle or its harvest:
            # the thread was just interrupted, so a steer can legitimately
            # be refused, and grade() below is what still has something to
            # report when it is.
            tail = INTERRUPT_TAIL_S if cut_off else None
            try:
                for i, fu in enumerate(fus):
                    if i < done:
                        continue  # already delivered before a crash/resume
                    self.send(fu, first=False)
                    self.wait_turn(tid, deadline_s=tail)
                    self._save(n_followups_done=i + 1)
                # dedicated verdict turn: short, schema-constrained; a
                # transient stream failure here is retried too (reg11's
                # verdict turn died 19 s after the working turn did)
                self.send("战役收尾：请按输出 schema 给出最终裁决"
                          "（不做新的精修动作，如实汇报当前状态）。",
                          first=False, with_schema=True)
                self._retry_transient(tid, self.wait_turn(tid, deadline_s=tail),
                                      deadline_s=tail, with_schema=True)
            except Exception as exc:  # noqa: BLE001
                if not cut_off:
                    raise
                self._save(post_interrupt_error=f"{type(exc).__name__}: {exc}")
            self._save(status="interrupted" if cut_off else "done")
        self.collect_logs(tid)
        self.grade()

    def _retry_transient(self, tid: str, r: dict[str, Any],
                         deadline_s: float | None = None,
                         with_schema: bool = False) -> dict[str, Any]:
        """Resend a continue-on-the-same-thread after a turn that failed
        with a transient transport error (see STREAM_RETRIES). Returns the
        last turn result; every attempt is logged to the SSE bundle."""
        attempts = 0                                   # per turn
        total = int(self.st.get("stream_retries") or 0)  # per case, reported
        while (r.get("status") == "failed"
               and is_transient_turn_error(r.get("error"))
               and attempts < STREAM_RETRIES):
            attempts += 1
            total += 1
            self._save(stream_retries=total,
                       last_stream_error=str(r.get("error"))[:300])
            self.logger.sse(int(self.st.get("sse_cursor") or 0), {
                "kind": "runner_retry", "attempt": attempts,
                "error": str(r.get("error"))[:300],
                "wait_s": STREAM_RETRY_WAIT_S, "ts": time.time()})
            time.sleep(STREAM_RETRY_WAIT_S)
            self.send(CONTINUE_AFTER_STREAM_ERROR, first=False,
                      with_schema=with_schema)
            r = self.wait_turn(tid, deadline_s=deadline_s)
        return r

    def collect_logs(self, thread_id: str | None) -> None:
        """Freeze the log bundle. Deliberately AFTER the last turn and
        BEFORE grading: grading writes into the campaign workdir, and a
        bundle that contains the grade cannot be used to argue the grade
        was reached without seeing it."""
        from .campaign_logs import free_memory_mb
        try:
            man = self.logger.collect(
                thread_id,
                lanes_busy=self.c.lanes_busy(),
                free_mem_mb=free_memory_mb(),
                extra={"campaign": self.c.name,
                       "arm": self.case.get("arm"),
                       "crystal": self.case.get("crystal"),
                       "wall_s": self.st.get("wall_s"),
                       "usage": self.st.get("usage")})
            self._save(log_bytes=man.get("total_bytes"),
                       log_errors=man.get("errors") or None,
                       lanes_busy=man.get("lanes_busy"))
        except Exception as exc:  # noqa: BLE001 - never lose a finished case
            self._save(log_errors=[f"collect: {type(exc).__name__}: {exc}"])


class Campaign:
    def __init__(self, manifest_path: Path) -> None:
        m = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.name = m["campaign"]
        self.api = Api(m.get("server") or "http://127.0.0.1:8010/api")
        self.projects_root = m.get("projects_root") or str(
            REPO / "workbench" / self.name)
        self.defaults = m.get("defaults") or {}
        if self.defaults.get("anonymize_lane"):
            anon = anonymous_lane_dir(self.projects_root, self.name)
            # a lane that already ran under its plain name (before this
            # option existed) must still be found by --regrade
            if anon.exists() or not Path(self.projects_root).exists():
                self.projects_root = str(anon)
        self.cases = m["cases"]
        self.work = REPO / "workdir" / "campaigns" / self.name
        self.work.mkdir(parents=True, exist_ok=True)
        self.state_path = self.work / "state.json"
        self.state: dict[str, Any] = (
            json.loads(self.state_path.read_text(encoding="utf-8"))
            if self.state_path.exists() else {})

    def lanes_busy(self) -> int | None:
        """How many projects are mid-turn right now, this one included.

        Recorded per case because a batch run puts several campaign lanes
        on one machine and one CPU budget: a 40-minute case measured
        alongside two others is not the same measurement as a 40-minute
        case measured alone, and a report that puts both in one column is
        lying about its own axis."""
        try:
            rows = self.api.get("/projects/status", timeout=15.0)
        except Exception:  # noqa: BLE001 - telemetry, never fatal
            return None
        if not isinstance(rows, list):
            return None
        return sum(1 for r in rows if isinstance(r, dict) and r.get("busy"))

    def save_state(self) -> None:
        tmp = self.state_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.state, indent=2, ensure_ascii=False),
                       encoding="utf-8")
        tmp.replace(self.state_path)

    def run(self, only: str | None = None, regrade: bool = False) -> None:
        for case in self.cases:
            if only and case["name"] != only:
                continue
            cr = CaseRun(self, case)
            if regrade and cr.st.get("status") == "graded":
                cr.st["status"] = "done"
            try:
                cr.run()
            except Exception as exc:  # noqa: BLE001 - a case must not kill the campaign
                cr._save(status="failed", error=f"{type(exc).__name__}: {exc}")
            self.report()

    def report(self) -> None:
        lines = [f"# 战役报告：{self.name}",
                 "",
                 f"更新：{time.strftime('%Y-%m-%d %H:%M:%S')}",
                 "",
                 "| case | 状态 | 评级 | R1 agent | ΔR1 vs ref | solved | "
                 "SG同型 | 自洽 | checkCIF A/B/C | 裁决=CIF | tokens in/out "
                 "| 墙钟 s |",
                 "|---|---|---|---|---|---|---|---|---|---|---|---|"]
        grades: list[str | None] = []
        state_healed = False
        for case in self.cases:
            name = case["name"]
            st = self.state.get(name) or {}
            g = {}
            gp = self.work / name / "grade.json"
            if gp.exists():
                g = json.loads(gp.read_text(encoding="utf-8"))
                # grade.json is authoritative (a case may be re-graded out
                # of band, e.g. after a grader fix); heal a stale state label
                if g.get("grade") and st.get("grade") != g["grade"]:
                    st["grade"] = g["grade"]
                    self.state[name] = st
                    state_healed = True
            grades.append(g.get("grade"))
            rl = g.get("reference_layer") or {}
            sc = g.get("self_consistency") or {}
            cc = (sc.get("checkcif") or {}).get("counts") or {}
            u = st.get("usage") or {}
            lines.append(
                f"| {name} | {st.get('status', 'pending')} "
                f"| {g.get('grade', '—')} "
                f"| {(sc.get('cif') or {}).get('r1_gt', '—')} "
                f"| {rl.get('r1_delta', '—')} "
                f"| {(rl.get('emma') or {}).get('solved', '—')} "
                f"| {rl.get('sg_type_equal', '—')} "
                f"| {sc.get('self_consistent', '—')} "
                f"| {cc.get('A', '—')}/{cc.get('B', '—')}/{cc.get('C', '—')} "
                f"| {g.get('verdict_matches_cif', st.get('verdict_matches_cif', '—'))} "
                f"| {u.get('input_tokens', '—')}/{u.get('output_tokens', '—')} "
                f"| {st.get('wall_s', '—')} |")
        lines += ["",
                  f"完成 {sum(1 for s in self.state.values() if s.get('status') == 'graded')}"
                  f"/{len(self.cases)}；评级分布："
                  f"{ {g: grades.count(g) for g in set(grades) if g} }", ""]
        (self.work / "CAMPAIGN_REPORT.md").write_text(
            "\n".join(lines), encoding="utf-8")
        if state_healed:
            self.save_state()


def main(argv: list[str]) -> int:
    import argparse
    try:  # host frugality: the runner and anything it spawns stay capped
        from ..procutil import limit_cpu
        limit_cpu()
    except Exception:  # noqa: BLE001
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("manifest")
    ap.add_argument("--only", default=None)
    ap.add_argument("--regrade", action="store_true",
                    help="re-run grading for already-graded cases")
    a = ap.parse_args(argv)
    c = Campaign(Path(a.manifest))
    c.run(only=a.only, regrade=a.regrade)
    c.report()
    print(f"state: {c.state_path}")
    print(f"report: {c.work / 'CAMPAIGN_REPORT.md'}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv[1:]))
