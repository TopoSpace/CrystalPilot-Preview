"""Resume the interrupted twin-trap discovery thread after the reboot."""
import json
import os
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
os.environ["PYTHONUTF8"] = "1"
os.environ["CRYSTALPILOT_SPECIALISTS"] = "1"

from crystalpilot.workbench.core import Workbench

project = REPO / "workbench" / "r5-twintrap"
state = json.loads((project / ".crystalpilot-workbench.json")
                   .read_text(encoding="utf-8"))
rec = state["threads"][-1]
print(f"resuming thread {rec['thread_id']} task {rec['task_id']}",
      flush=True)

RESUME = ("（系统提示：机器意外重启中断了你上一回合，会话已恢复；节点树与所有工具"
          "状态都在。）请从中断处继续。你中断前的最后判断是：自由精修 R1=0.0942 且"
          "差值图干净，坐标模型已排除；数据合并 R_int=0.0822 偏高，你正要展开"
          "关于数据本身（孪晶复合观测）的假设。请继续诊断并完成任务：按 AGENTS.md "
          "交付流程收尾（run_shelxl 复核 → write_outputs → run_checkcif(cif=…"
          "/final.cif) → VALIDATION.md 逐条解释），解释不了的差距如实列入 "
          "unresolved，最后中文总结诊断结论与最终指标。")

NUDGE = ("请继续。若诊断与交付（write_outputs / run_checkcif / VALIDATION.md）"
         "尚未完成请接着做；完成了就明确给出最终指标、诊断结论与未解决问题。")

stats = {"n_turns": 0, "n_tools": 0, "in_tok": None, "out_tok": None}
t0 = time.time()


def on_event(ev):
    k = ev.get("kind")
    if k == "tool_completed":
        print(f"  [tool] {ev.get('tool')} ok={ev.get('ok')} "
              f"{(ev.get('result_tail') or '')[:130]}", flush=True)
        stats["n_tools"] += 1
    elif k == "command_started":
        print(f"  [SHELL] {str(ev.get('command'))[:120]}", flush=True)
    elif k == "token_usage":
        tot = ev.get("total") or {}
        stats["in_tok"] = tot.get("input_tokens")
        stats["out_tok"] = tot.get("output_tokens")
    elif k == "turn_failed":
        print(f"  [TURN-FAILED] {str(ev.get('error'))[:300]}", flush=True)
    elif k == "reasoning_summary":
        print(f"  [think] {(ev.get('text') or '')[:120]}", flush=True)


with Workbench(project, event_cb=on_event) as wb:
    task = wb.resume_task(rec["thread_id"])
    finals = []

    def run_turn(text):
        stats["n_turns"] += 1
        final, failed = "", False
        for ev in task.send(text):
            on_event(ev)
            if ev["kind"] == "agent_message":
                final = ev["text"]
            if ev["kind"] == "turn_failed":
                failed = True
        finals.append(final)
        return final, failed

    final, failed = run_turn(RESUME)
    n = 0
    while not failed and n < 3 and not any(
            (task.results_dir / f).exists()
            for f in ("REPORT.json", "final.cif")):
        n += 1
        print(f"== nudge {n}", flush=True)
        final, failed = run_turn(NUDGE)

    print("\n==== FINAL MESSAGE ====\n", (finals[-1] or "")[:5000],
          flush=True)

stats["wall_s"] = round(time.time() - t0, 1)
print("== stats", json.dumps(stats, ensure_ascii=False), flush=True)
