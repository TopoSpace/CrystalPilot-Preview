"""R5 acceptance: agent-driven discovery on the hidden-twin trap case.

COD 2229074 deposits NO twin metadata (no embedded res, no _twin fields)
but the published R1 (0.0526) is only reachable with twin refinement.
The agent must import the deposit, diagnose the R gap honestly, and find
the treatment itself. Specialists enabled (organic-usage observation)."""
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
project.mkdir(exist_ok=True)
(project / "context.json").write_text(json.dumps({
    "chemistry": {"note": ("文献结构复现/验证任务：COD 2229074，有机小分子 "
                           "C16H14N2O5（洛美沙星相关？以 CIF 为准）。无合成先验"
                           "——这是已发表结构的独立验证。")}},
    ensure_ascii=False, indent=2), encoding="utf-8")

DATA = REPO / "benchmark" / "data_ext2" / "twintrap_nm_cod2229074"

PROMPT = f"""这是一个已发表结构的独立验证/复现任务。COD 条目 2229074 的终稿 CIF 与结构因子在：
- CIF: {DATA / 'ref.cif'}
- HKL: {DATA / 'ref.hkl'}（由沉积 fcf 派生的 HKLF4）

论文报告 R1[I>2σ] = 0.0526。请你作为精修晶体学家：
1. 用 import_cif_model 导入该结构（这会成为节点 n0000）；
2. 用 run_shelxl(mode='check') 复现 R 因子。注意：直接复现大概率与发表值有明显差距——
   你的核心任务是**诊断这个差距的来源**（模型？数据处理？CIF 未披露的处理步骤？）并
   尽你所能把精修带到该数据支持的最佳水平；
3. 诊断时充分利用工具（inspect_map / get_geometry / check_symmetry / set_twin(law='suggest')
   / consult_specialist …），分支比较任何假设；
4. 收尾按 AGENTS.md：run_shelxl 复核 → write_outputs → run_checkcif(cif=…/final.cif) →
   VALIDATION.md 逐条解释 A/B/C 警报。解释不了的差距如实写进 unresolved——诚实优先，
   不许为凑发表值做没有证据的操作。完成后用中文总结诊断过程与最终指标。"""

NUDGE = ("请继续。如果 R 差距还没有诊断清楚或精修未到位（含交付流程 write_outputs / "
         "run_checkcif / VALIDATION.md），请接着做；确实完成了就明确说明最终指标、"
         "诊断结论与未解决问题。")

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
    task = wb.new_task(title="R5验收：隐匿孪晶陷阱侦破")
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
