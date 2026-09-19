"""M5 probe: one inspection turn through the full workbench + MCP stack.

Opens the corrupted MVP project, asks the agent (中文) to examine the model
with the typed tools, and reports: which MCP tools ran, whether any shell
crystallography happened, and the agent's diagnosis.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from crystalpilot.workbench.core import Workbench  # noqa: E402

PROJECT = REPO / "workbench" / "mvp-sjtu9"

PROMPT = (
    "请先用 crystalpilot MCP 工具了解这个项目（get_project_brief），然后检查当前粗解"
    "模型的状态：先精修一轮拿到基线指标，再用 inspect_model、inspect_map、check_ligand "
    "找出模型的问题。只做检查和诊断，不要修改模型。最后用中文总结你发现的所有可疑之处"
    "及其证据。不要用 shell 做任何晶体学计算。")


def main() -> int:
    events = []

    def on_event(ev):
        events.append(ev)
        k = ev.get("kind")
        if k == "tool_completed":
            print(f"  [tool] {ev.get('tool')} ok={ev.get('ok')} "
                  f"{(ev.get('result_tail') or '')[:120]}", flush=True)
        elif k == "tool_started":
            print(f"  [tool>] {ev.get('tool')}", flush=True)
        elif k == "command_started":
            print(f"  [SHELL] {str(ev.get('command'))[:160]}", flush=True)
        elif k == "turn_failed":
            print(f"  [FAIL] {ev.get('error')}", flush=True)

    with Workbench(PROJECT, event_cb=on_event) as wb:
        task = wb.new_task(title="M5 inspection probe")
        final = ""
        for ev in task.send(PROMPT):
            on_event(ev)          # turn events come from the send iterator
            if ev["kind"] == "agent_message":
                final = ev["text"]
    tools_used = [e.get("tool") for e in events if e.get("kind") == "tool_completed"]
    shells = [e for e in events if e.get("kind") == "command_started"]
    print("\n=== tools used:", tools_used)
    print("=== shell commands:", len(shells))
    print("=== final message ===")
    print(final)
    report = {"tools_used": tools_used, "n_shell": len(shells),
              "final": final}
    (REPO / "workdir" / "m5_probe_result.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    ok = bool(tools_used) and len(shells) == 0 and final
    print("M5 PROBE", "OK" if ok else "CHECK-NEEDED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
