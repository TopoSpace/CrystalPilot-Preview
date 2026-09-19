"""Launch ONE real end-to-end cell in the live workbench and log it.

Parametrised successor of workdir/live-demos/demo-20260905-1503/run_demo.py.
Crystallography stays inside the workbench; this script only prepares a
project directory OUTSIDE the repo, opens it through the HTTP API, sends the
brief, and mirrors the SSE stream into a log folder so the run can be
audited later. It prints the browser URL as soon as the thread exists so a
human can watch and interject.

Usage (from H:\\CrystalPilot, venv python):

  python scripts/run_live.py --source H:/CrystalPilotData/staging/r25a \
      --name r3-r4-mof --brief workdir/live-demos/briefs/mof-guest.md \
      --context workdir/live-demos/contexts/mof-guest.json \
      --title "R4 整客体工具复跑 · Zr-MOF" --structure-class framework \
      --strip-placeholders

Only crystal.hkl and start.ins (or --hkl/--ins) are copied; source files are
never modified. Refuses to reuse an existing project directory.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path
from urllib.parse import quote

import httpx

DEFAULT_BRIEF = """这是 CrystalPilot 的真实单晶结构解析运行，用户正在浏览器观察，可随时插话。
请从当前项目的真实 HKL 与 start.ins 开始，完成数据判断、空间群假设、结构求解、化学建模、精修、验证与诚实交付。
合成先验见 context.json；它们不是原子坐标、占有率或结构答案，必须通过数据验证。
请使用晶体学 MCP 工具，而不是自己写晶体学管线。先 get_project_brief、数据质量/分辨率与定群检查，提出可检验假设，必要时显式分支比较。不要因为某条路线暂时不理想便无限重复同条件求解，也不要靠删数据或无依据删原子追低 R。
在关键阶段用简洁中文说明正在判断什么、证据与当前瓶颈；让结构、节点、精修指标和检查结果在工作台中自然更新。
用户可以随时补充信息；若确实缺少能改变判断的事实，请清楚提问。不要编造温度、晶体尺寸、合成细节或元数据。
不浏览以往相同样品的交付结果或参考结构找答案。不要进行文件哈希/摘要审计，也不要访问凭据、环境变量或 API 配置。原始源数据和 inputs 中的文件只读；所有科学修改只在本项目的工具与节点中进行。IUCr 在线上传未获授权。
最终按现有工具流程写 CIF/FCF/RES、SUMMARY.md 与逐条 VALIDATION.md，并适当 finalize_delivery。若客体、元素、无序或数据质量仍限制结果，明确列出未解决问题，允许诊断性交付，不能把未完成结构包装成发表级。"""


def _placeholder(line: str) -> bool:
    fields = line.split()
    if len(fields) != 7 or fields[0] not in ("C", "H", "N", "O"):
        return False
    try:
        return all(float(x) == 0 for x in fields[2:5]) and float(fields[6]) == 0
    except ValueError:
        return False


class Logger:
    def __init__(self, log_dir: Path, state: dict) -> None:
        self.dir = log_dir
        self.state = state
        self.events = (log_dir / "events.jsonl").open("a", encoding="utf-8", buffering=1)

    def save(self, **changes) -> None:
        self.state.update(changes)
        tmp = self.dir / "state.tmp"
        tmp.write_text(json.dumps(self.state, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.dir / "state.json")

    def event(self, seq: int, value: dict) -> None:
        self.events.write(json.dumps({"seq": seq, "received_at": time.time(), "event": value},
                                     ensure_ascii=False) + "\n")

    def close(self) -> None:
        self.events.close()


def follow(client: httpx.Client, base: str, thread: str, cursor: int, log: Logger, *,
           warmup: bool = False, hours: float = 4.0, idle_s: float = 900.0) -> int:
    started = time.monotonic()
    limit = 240 if warmup else hours * 3600
    idle_since = None
    completed_tools = 0
    while time.monotonic() - started < limit:
        try:
            with client.stream("GET", base + "/threads/events",
                               params={"thread_id": thread, "after": cursor},
                               timeout=httpx.Timeout(40, connect=15)) as response:
                response.raise_for_status()
                seq, data = cursor, []
                for line in response.iter_lines():
                    if line.startswith("id:"):
                        seq = int(line[3:].strip())
                    elif line.startswith("data:"):
                        data.append(line[5:].lstrip())
                    elif not line and data:
                        value = json.loads("\n".join(data))
                        data = []
                        if seq <= cursor:
                            continue
                        cursor = seq
                        log.event(seq, value)
                        kind = value.get("kind")
                        updates = {"last_event": kind, "cursor": cursor,
                                   "last_event_at": time.strftime("%Y-%m-%d %H:%M:%S")}
                        if kind == "tool_started":
                            updates["current_tool"] = value.get("tool")
                        if kind == "tool_completed":
                            completed_tools += 1
                            updates["completed_tool_calls"] = completed_tools
                        if kind == "turn_started":
                            idle_since = None
                            updates["phase"] = "warmup" if warmup else "running"
                        if kind in ("turn_completed", "turn_failed"):
                            updates["last_turn_status"] = value.get("status")
                            updates["last_turn_error"] = value.get("error")
                            updates["phase"] = "warmup_done" if warmup else "awaiting_user_or_finished"
                            idle_since = time.monotonic()
                        if kind not in ("agent_delta", "command_output"):
                            log.save(**updates)
                        if warmup and kind in ("turn_completed", "turn_failed"):
                            if value.get("error") or kind == "turn_failed":
                                raise RuntimeError("Warm-up turn failed; see events.jsonl")
                            return cursor
                    if time.monotonic() - started > limit:
                        break
                    if not warmup and idle_since is not None and time.monotonic() - idle_since > idle_s:
                        log.save(phase="logger_finished",
                                 note="Native workbench transcripts continue recording later turns")
                        return cursor
        except (httpx.HTTPError, ValueError) as error:
            log.event(cursor, {"kind": "logger_reconnect", "error": type(error).__name__, "at": time.time()})
            time.sleep(3)
    if warmup:
        raise TimeoutError("Warm-up did not finish; see events.jsonl")
    log.save(phase="logger_finished", note="Event capture window ended; native project logs remain active")
    return cursor


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", help="directory holding crystal.hkl and start.ins")
    ap.add_argument("--hkl", help="explicit HKL path (overrides --source)")
    ap.add_argument("--ins", help="explicit INS/RES path (overrides --source)")
    ap.add_argument("--name", required=True, help="project folder name under --root")
    ap.add_argument("--root", default=str(Path(__file__).resolve().parents[2] / "projects"), help="projects root OUTSIDE the repo")
    ap.add_argument("--title", default=None, help="thread title shown in the workbench")
    ap.add_argument("--brief", help="file with the task brief (default: built-in generic brief)")
    ap.add_argument("--context", help="context.json to copy (chemistry/experiment priors)")
    ap.add_argument("--model", default="gpt-5.6-luna")
    ap.add_argument("--effort", default="xhigh")
    ap.add_argument("--provider", default=None,
                    help="[model_providers.<id>] key of codex-home/config.toml for this project's "
                         "threads (default: the config's model_provider); e.g. openrouter with "
                         "--model z-ai/glm-5.3 --effort high")
    ap.add_argument("--subagents", default="off", choices=("off", "top_tier", "aggressive"))
    ap.add_argument("--permission", default="auto", choices=("readonly", "copilot", "auto", "full"))
    ap.add_argument("--structure-class", default=None,
                    choices=(None, "small_molecule", "macrocycle", "cage", "framework", "salt_cocrystal"))
    ap.add_argument("--strip-placeholders", action="store_true",
                    help="drop zero-coordinate zero-U C/H/N/O placeholder atoms from start.ins (original kept in inputs/)")
    ap.add_argument("--hours", type=float, default=4.0, help="event capture window")
    ap.add_argument("--base", default="http://127.0.0.1:8010/api")
    ap.add_argument("--log-dir", default=None, help="default workdir/live-demos/<name>-<stamp>")
    ap.add_argument("--min-tools", type=int, default=30, help="MCP readiness threshold (registered tools)")
    args = ap.parse_args(argv)

    root_repo = Path(__file__).resolve().parents[1]
    project = Path(args.root) / args.name
    if project.exists():
        raise SystemExit(f"refusing to reuse existing project dir: {project}")
    if root_repo in project.resolve().parents:
        raise SystemExit("project must live outside the repository")
    hkl = Path(args.hkl) if args.hkl else Path(args.source) / "crystal.hkl"
    ins = Path(args.ins) if args.ins else Path(args.source) / "start.ins"
    for p in (hkl, ins):
        if not p.is_file():
            raise SystemExit(f"missing input: {p}")
    stamp = time.strftime("%Y%m%d-%H%M")
    log_dir = Path(args.log_dir) if args.log_dir else root_repo / "workdir" / "live-demos" / f"{args.name}-{stamp}"
    log_dir.mkdir(parents=True, exist_ok=True)
    state = {"project": str(project), "phase": "preparing", "model": args.model, "effort": args.effort,
             "provider": args.provider, "subagents": args.subagents, "source_hkl": str(hkl),
             "source_ins": str(ins)}
    log = Logger(log_dir, state)
    try:
        project.mkdir(parents=True)
        (project / "inputs").mkdir()
        shutil.copy2(hkl, project / "crystal.hkl")
        shutil.copy2(ins, project / "inputs" / "original-start.ins")
        text = ins.read_text(encoding="utf-8", errors="replace").splitlines()
        removed: list[str] = []
        if args.strip_placeholders:
            kept = []
            for line in text:
                if _placeholder(line):
                    removed.append(line.split()[0])
                else:
                    kept.append(line)
            text = kept
        (project / "start.ins").write_text("\n".join(text) + "\n", encoding="utf-8")
        if args.context:
            ctx = json.loads(Path(args.context).read_text(encoding="utf-8"))
        else:
            ctx = {}
        ctx.setdefault("data", {"hkl": "crystal.hkl", "start_model": "start.ins"})
        (project / "context.json").write_text(json.dumps(ctx, ensure_ascii=False, indent=2), encoding="utf-8")
        brief = Path(args.brief).read_text(encoding="utf-8") if args.brief else DEFAULT_BRIEF
        (log_dir / "brief.md").write_text(brief, encoding="utf-8")
        log.save(removed_placeholder_atoms=removed, event_log=str(log_dir / "events.jsonl"),
                 brief=str(log_dir / "brief.md"))
        with httpx.Client(timeout=120) as client:
            for _ in range(30):
                try:
                    if client.get(args.base + "/health", timeout=5).json().get("ok"):
                        break
                except (httpx.HTTPError, ValueError):
                    pass
                time.sleep(2)
            else:
                raise RuntimeError("workbench server not reachable")
            post = lambda ep, payload: client.post(args.base + ep, json=payload).raise_for_status().json()
            post("/projects/open", {"path": str(project)})
            settings = {"model_override": args.model, "effort_override": args.effort,
                        "subagents": args.subagents, "enable_specialists": False,
                        "allow_iucr_upload": False}
            if args.provider:
                settings["model_provider_override"] = args.provider
            if args.structure_class:
                settings["structure_class"] = args.structure_class
            applied = post("/projects/settings", {"path": str(project), "permission_mode": args.permission,
                                                  "settings": settings})
            log.save(vision=applied.get("vision"), model_provider=applied.get("model_provider"))
            title = args.title or f"实机运行 · {args.name}"
            first = post("/threads/send", {"project": str(project), "title": title,
                                           "message": "会话初始化：本回合只回复「就绪」，不要调用工具或开始解析。"})
            thread, task = first["thread_id"], first["task_id"]
            url = f"http://127.0.0.1:8010/thread/{thread}?project={quote(str(project), safe='')}"
            log.save(thread_id=thread, task_id=task, url=url, phase="warmup",
                     native_transcript=str(project / "CrystalPilot Results" / task / "transcript.jsonl"),
                     engine_logs=str(project / ".crystalpilot" / "refine"))
            print(json.dumps({"url": url, "project": str(project), "phase": "warmup"}, ensure_ascii=False), flush=True)
            cursor = follow(client, args.base, thread, 0, log, warmup=True)
            ready = False
            for _ in range(24):
                probe = post("/projects/mcp_status", {"path": str(project)})
                if (probe.get("n_tools") or 0) >= args.min_tools:
                    ready = True
                    break
                time.sleep(5)
            if not ready:
                raise RuntimeError("crystallographic MCP did not become available; see server log")
            post("/threads/send", {"project": str(project), "thread_id": thread, "message": brief})
            log.save(phase="running", started_at=time.strftime("%Y-%m-%d %H:%M:%S"), mcp_tools=probe.get("n_tools"))
            print(json.dumps({"url": url, "phase": "running", "event_log": str(log_dir / "events.jsonl")},
                             ensure_ascii=False), flush=True)
            follow(client, args.base, thread, cursor, log, hours=args.hours)
    except Exception as error:  # noqa: BLE001 - recorded, then re-raised
        log.save(phase="launcher_error", error=f"{type(error).__name__}: {error}")
        raise
    finally:
        log.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
