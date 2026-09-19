"""Workbench harness smoke test against the merged package (Phase 1).

Validates: isolated CODEX_HOME at <repo>/codex-home, provider auth.command
(key never enters env/config/logs), thread start + turn + resume, normalized
event stream. Never prints the API key.

Run:  H:/CrystalPilot/.venv/Scripts/python.exe -X utf8 scripts/workbench_smoke.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crystalpilot.workbench.core import CODEX_HOME, ENGINE_ROOT, Workbench


def run_turn(task, prompt: str) -> tuple[str | None, dict | None]:
    text, usage = None, None
    for ev in task.send(prompt, turn_kwargs={"model": "gpt-5.6-luna", "effort": "low"}):
        if ev["kind"] == "agent_message":
            text = ev["text"]
        elif ev["kind"] == "turn_completed":
            usage = ev.get("usage")
        elif ev["kind"] == "turn_failed":
            print("TURN FAILED:", str(ev.get("error"))[:400])
    return text, usage


def main() -> int:
    print("CODEX_HOME:", CODEX_HOME)
    assert CODEX_HOME.exists(), "isolated codex-home missing"
    project = ENGINE_ROOT.parent / "projects" / "workbench-smoke"
    project.mkdir(parents=True, exist_ok=True)

    with Workbench(project) as wb:
        task = wb.new_task(title="smoke")
        print("thread:", task.thread_id, "| task:", task.task_id)
        text, usage = run_turn(task, "Reply with exactly: CRYSTAL-OK")
        print("turn1 text:", repr(text))
        print("turn1 usage:", usage)
        ok1 = text is not None and "CRYSTAL-OK" in text
        thread_id = task.thread_id

    # fresh client: proves resume across process boundaries
    with Workbench(project) as wb2:
        task2 = wb2.resume_task(thread_id)
        text2, _ = run_turn(task2, "Reply with exactly: RESUME-OK")
        print("turn2 text:", repr(text2))
        ok2 = text2 is not None and "RESUME-OK" in text2

    print("SMOKE:", "PASS" if (ok1 and ok2) else "FAIL")
    return 0 if (ok1 and ok2) else 1


if __name__ == "__main__":
    sys.exit(main())
