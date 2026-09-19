"""R5 frames-twin E2E: agent-driven refinement of the o-nitroaniline set
reduced from raw CBF frames (single-lattice, naive route).

The dataset is a known non-merohedral twin (IUCrData RDL benchmark ladder:
naive R1 0.0678 -> HKLF5 0.0465), and the coarse solve landed in P21
instead of the published P21/a (twin overlap corrupts absences). The
prompt is deliberately NEUTRAL - the agent must find the symmetry problem
and the data-side twin symptoms itself. Specialists enabled."""
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

project = REPO / "workbench" / "r5-onitwin"

PROMPT = """本项目的数据来自原始衍射帧：staged 工具链已完成还原
（import_frames → find_spots → index_frames → integrate_frames →
scale_and_export → create_start_model），粗解起始模型在节点 n0000
（R1≈0.16，40 个原子，P2₁）。化学先验：o-nitroaniline（邻硝基苯胺）
C6H6N2O2，SMILES 在 context.json。

请你作为精修晶体学家把它带到可交付水平：
1. get_project_brief 了解数据与模型现状；
2. 用观察工具全面体检（inspect_model / inspect_map / check_ligand /
   check_symmetry / audit_reflection_data …）；发现的任何异常——对称性、
   数据一致性、密度特征——都要用工具核实、分支验证，并在报告中如实披露；
3. 正常精修至交付：run_shelxl 复核 → write_outputs →
   run_checkcif(cif=…/final.cif) → VALIDATION.md 逐条解释警报；
4. 数据支持不了的目标不要硬凑：解释不了的残差/警报写进 unresolved。
   完成后用中文总结：做了什么、为什么、最终指标、未解决问题。"""

NUDGE = ("请继续。若诊断或精修未完成（含交付流程 write_outputs / run_checkcif / "
         "VALIDATION.md），接着做；确实完成了就明确给出最终指标、关键诊断结论与"
         "未解决问题。")

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


with Workbench(project, event_cb=on_event) as wb:
    task = wb.new_task(title="R5验收：孪晶原始帧全链路精修")
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

    print(f"== task {task.task_id} thread {task.thread_id}", flush=True)
    final, failed = run_turn(PROMPT)
    n = 0
    while not failed and n < 3 and not any(
            (task.results_dir / f).exists()
            for f in ("REPORT.json", "final.cif")):
        n += 1
        print(f"== nudge {n}", flush=True)
        final, failed = run_turn(NUDGE)

    print("\n==== FINAL MESSAGE ====\n", finals[-1][:4000], flush=True)

stats["wall_s"] = round(time.time() - t0, 1)
print("== stats", json.dumps(stats, ensure_ascii=False), flush=True)
