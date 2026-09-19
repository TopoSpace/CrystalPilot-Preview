"""Workbench CLI: interactive Codex-style chat over a CrystalPilot project.

Usage:
  python -m crystalpilot.workbench.cli chat <project-dir> [--resume THREAD_ID] [--yes]
  python -m crystalpilot.workbench.cli tasks <project-dir>
  python -m crystalpilot.workbench.cli once <project-dir> "<message>" [--yes]
"""
from __future__ import annotations

import argparse
import sys

# Windows consoles default to GBK; agent output is UTF-8 scientific text
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

from .core import Workbench


_last_usage: dict = {}


def _print_event(ev: dict) -> None:
    k = ev["kind"]
    if k == "token_usage":
        _last_usage.update(ev.get("total") or {})
        return
    if k == "agent_delta":
        print(ev["delta"], end="", flush=True)
    elif k == "agent_message":
        print()  # newline after deltas
    elif k == "reasoning_summary":
        print(f"\n\x1b[2m[thinking] {ev['text'][:300]}\x1b[0m")
    elif k == "command_started":
        print(f"\n\x1b[36m$ {ev['command'][:200]}\x1b[0m", flush=True)
    elif k == "command_completed":
        status = ev.get("status") or ""
        tail = (ev.get("output_tail") or "").strip()
        if tail:
            print("\x1b[2m" + tail[-600:] + "\x1b[0m")
        print(f"\x1b[36m[command {status}]\x1b[0m")
    elif k == "turn_completed":
        i, o = _last_usage.get("input_tokens"), _last_usage.get("output_tokens")
        c = _last_usage.get("cached_input_tokens")
        detail = (f"in {i} (cached {c}) / out {o} tokens"
                  if i is not None else "usage n/a")
        secs = (ev.get("duration_ms") or 0) / 1000
        print(f"\n\x1b[2m-- turn done in {secs:.0f}s ({detail}) --\x1b[0m")
    elif k == "turn_failed":
        print(f"\n!! turn failed: {ev.get('error')}")
    elif k == "approval_decision":
        print(f"\x1b[33m[approval: {ev.get('decision')}]\x1b[0m")


def _make_approval_cb(auto_yes: bool):
    def cb(req: dict) -> dict:
        detail = req.get("detail") or {}
        cmd = (detail.get("command") or detail.get("changes") or "")
        print(f"\n\x1b[33m[APPROVAL NEEDED] {req['method']}\n  {str(cmd)[:300]}\x1b[0m")
        if auto_yes:
            print("\x1b[33m  --yes: auto-approved\x1b[0m")
            return {"decision": "accept"}
        ans = input("  approve? [y/N] ").strip().lower()
        return {"decision": "accept" if ans in ("y", "yes") else "reject"}
    return cb


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="crystalpilot-workbench")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("chat", "once", "tasks"):
        sp = sub.add_parser(name)
        sp.add_argument("project")
        if name == "once":
            sp.add_argument("message")
        if name == "chat":
            sp.add_argument("--resume", default=None)
        if name in ("chat", "once"):
            sp.add_argument("--yes", action="store_true",
                            help="auto-approve escalated actions")
    args = ap.parse_args(argv)

    if args.cmd == "tasks":
        wb = Workbench(args.project)
        for t in wb.tasks():
            print(f"{t['thread_id']}  {t['task_id']}  {t.get('title','')}")
        return 0

    approval_cb = _make_approval_cb(getattr(args, "yes", False))
    with Workbench(args.project, approval_cb=approval_cb) as wb:
        if args.cmd == "once":
            task = wb.new_task(title=args.message[:40])
            print(f"[task {task.task_id} | thread {task.thread_id}]")
            for ev in task.send(args.message):
                _print_event(ev)
            return 0
        # chat
        if getattr(args, "resume", None):
            task = wb.resume_task(args.resume)
            print(f"[resumed thread {task.thread_id} -> {task.task_id}]")
        else:
            task = wb.new_task()
            print(f"[new task {task.task_id} | thread {task.thread_id}]")
        print("Type your message (empty line to exit).")
        while True:
            try:
                msg = input("\n\x1b[1myou>\x1b[0m ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not msg:
                break
            for ev in task.send(msg):
                _print_event(ev)
    return 0


if __name__ == "__main__":
    sys.exit(main())
