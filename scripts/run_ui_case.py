"""Run an existing isolated UI test project through the real HTTP/Codex flow.

Requires a prepared project outside the source repository and a brief file.
All testing defaults to gpt-5.6-luna; no global provider configuration changes.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import quote

import httpx
from run_live import Logger, follow


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project", required=True, type=Path)
    ap.add_argument("--brief", required=True, type=Path)
    ap.add_argument("--title", required=True)
    ap.add_argument("--model", default="gpt-5.6-luna")
    ap.add_argument("--effort", default="high")
    ap.add_argument("--minutes", type=float, default=25)
    args = ap.parse_args()
    root = Path(__file__).resolve().parents[1]
    project = args.project.resolve()
    if project.is_relative_to(root) or not project.is_dir():
        raise SystemExit("Use a prepared test project outside the source repository")
    if args.model != "gpt-5.6-luna":
        raise SystemExit("User testing policy requires gpt-5.6-luna")
    log_dir = root / "workdir" / "research-ui-20260908" / project.name
    log_dir.mkdir(parents=True, exist_ok=True)
    base = "http://127.0.0.1:8010/api"
    log = Logger(log_dir, {"project": str(project), "model": args.model, "phase": "preparing"})
    try:
        with httpx.Client(timeout=120) as client:
            def post(endpoint, payload):
                return client.post(base + endpoint, json=payload).raise_for_status().json()
            post("/projects/open", {"path": str(project)})
            post("/projects/settings", {"path": str(project), "permission_mode": "auto", "settings": {
                "model_override": args.model, "effort_override": args.effort,
                "subagents": "off", "enable_specialists": False, "allow_iucr_upload": False,
            }})
            first = post("/threads/send", {"project": str(project), "title": args.title,
                "message": "初始化测试会话，只回复「就绪」。不要调用工具或开始分析。"})
            thread = first["thread_id"]
            url = f"http://127.0.0.1:8010/thread/{thread}?project={quote(str(project), safe='')}"
            log.save(thread_id=thread, task_id=first["task_id"], url=url, phase="warmup")
            print(json.dumps({"url": url, "model": args.model}), flush=True)
            cursor = follow(client, base, thread, 0, log, warmup=True)
            brief = args.brief.read_text(encoding="utf-8")
            (log_dir / "brief.md").write_text(brief, encoding="utf-8")
            post("/threads/send", {"project": str(project), "thread_id": thread, "message": brief})
            follow(client, base, thread, cursor, log, hours=args.minutes / 60, idle_s=3)
    except Exception as exc:
        log.save(phase="launcher_error", error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        log.close()


if __name__ == "__main__":
    main()
