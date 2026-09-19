"""MVP acceptance run: the agent autonomously repairs + refines the corrupted
model, knowing ONLY the synthesis priors. Fully automatic (audit via node
store + transcripts), then honest evaluation vs the human reference.

Usage:
  .venv\\Scripts\\python.exe -X utf8 scripts\\run_refine_mvp.py --case sjtu9
  ... --project <dir>   reuse an existing corrupted project (skip corruption)
  ... --max-nudges 4
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

CASE_PROMPTS = {
    "sjtu9": """\
这个项目是一颗我们课题组合成的 MOF 晶体：项目里有反射数据 crystal.hkl 和一个由软件
自动粗解得到的初始模型 start.res。合成背景（也写在 context.json / get_project_brief
里）：金属源是 ZrCl4，有机配体是 1,2,4,5-四(4-羧基苯基)苯 (H4TCPB)，溶剂热合成
（DMF/水），孔道里可能有无序溶剂。

粗解模型只是软件的初步结果，可能存在元素判错、配体不完整、金属节点缺原子等各种问题
，像平时人工精修一样，请你不要信任它。

请你作为精修晶体学家，用 crystalpilot MCP 工具自主完成这颗晶体的精修，目标是化学
合理、可辩护的发表级结构：检查模型与差值密度、诊断问题、修复、多轮精修（各向异性、
氢、权重、溶剂处理都要做到位），过程中该分支比较就分支比较。收尾按 AGENTS.md 的
交付流程：run_shelxl 独立复核 → write_outputs 输出发表级 final.cif/final.fcf 到
"CrystalPilot Results/{task_id}/" → run_checkcif(cif=…/final.cif) 完整验证 →
写 VALIDATION.md 对每条 A/B/C 警报逐条解释。实验元数据（温度/晶体尺寸/吸收校正）
如果项目里没有提供，就如实留空并在总结里提醒需要补充，不要编造数值。
记住诚实守则：数据不支持的东西不要硬塞，未解决的问题要如实列出。完成后用中文总结。
""",
    "p24cu": """\
这个项目是我们课题组合成的一颗 Cu-MOF 晶体：反射数据 crystal.hkl（同步辐射，
λ≈0.689 Å）+ 软件粗解模型 start.res。合成背景（也在 get_project_brief 里）：金属源
Cu(NO3)2；配体是课题组编号 P2-4 的芳香多羧酸连接体（具体结构式没有提供，只知道通过
COO⁻ 桥连 Cu）；溶剂热合成，孔道可能有无序溶剂。

start.res 只是电荷翻转+各向同性精修的早期粗解，元素归属和模型完整性都不可信。请你
作为精修晶体学家，用 crystalpilot MCP 工具把它精修到该数据能支持的最佳水平（各向
异性、氢、权重、溶剂处理、必要的 restraints；结构有歧义就分支比较）。收尾按
AGENTS.md 交付流程：run_shelxl 复核 → write_outputs（发表级 final.cif/final.fcf）
→ run_checkcif(cif=…/final.cif) → VALIDATION.md 逐条解释 A/B/C 警报；输出目录
"CrystalPilot Results/{task_id}/"。
诚实守则：配体结构未知，就让密度说话，不要臆造；数据支持不了的（无序拆分、可能的
孪晶等）如实列入 unresolved；缺失的实验元数据如实留空并提醒。完成后用中文总结。
""",
}

CASE_PROMPTS["frames_lcyst"] = """\
这个项目现在只有一套**原始衍射帧**，还没有任何归约数据或初始模型。样品是
L-半胱氨酸（L-cysteine）单晶（教程级测试晶体，非 MOF），在 Diamond I19 同步辐射
线站采集，λ≈0.6889 Å，1700 张 Pilatus CBF 图像，帧目录：
{frames_dir}

请你从零开始走完整条链：用 crystalpilot MCP 的帧处理工具
（import_frames → find_spots → index_frames → integrate_frames →
scale_and_export → create_start_model）把原始帧归约成数据并得到初始模型，每一步
把关键统计（斑点数、指标化晶胞与空间群、RMSD、CC½/Rmerge/完整度）看一眼并判断
质量；然后按精修晶体学家的标准把结构精修到发表级（元素归属检查、各向异性、氢、
权重），收尾按 AGENTS.md 交付流程：run_shelxl 复核 → write_outputs（发表级
final.cif/final.fcf）→ run_checkcif(cif=…/final.cif) → VALIDATION.md 逐条解释
A/B/C 警报；输出目录 "CrystalPilot Results/{task_id}/"。
诚实守则照旧：每步统计如实报告，数据质量问题（完整度、温度未记录等）如实披露。
完成后用中文总结整条链的关键数字。
"""

NUDGE = ("请继续。如果精修还没有达到你能做到的最好水平（各向异性 ADP、骑乘氢、"
         "权重优化、溶剂处理、SHELXL 交叉验证、write_outputs 发表级产物、"
         "run_checkcif 验证 final.cif、VALIDATION.md 逐条解释警报都完成），"
         "请接着做；确实完成了就明确说明并给出最终指标与未解决问题。")

VERDICT_PROMPT = ("请以 JSON 形式汇报最终结果。数字必须来自最后一个节点的真实指标"
                  "（refine/run_shelxl 的返回值），不要凭记忆填写。")

VERDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "r1": {"type": "number", "description": "final R1 (I>2sigma), from the last refine"},
        "wr2": {"type": "number"},
        "goof": {"type": "number"},
        "space_group": {"type": "string"},
        "n_atoms": {"type": "integer"},
        "chemistry_ok": {"type": "boolean"},
        "defects_found": {"type": "array", "items": {
            "type": "object",
            "properties": {"description": {"type": "string"},
                           "action": {"type": "string"}},
            "required": ["description", "action"],
            "additionalProperties": False}},
        "restraints_used": {"type": "array", "items": {"type": "string"}},
        "shelxl_r1": {"type": ["number", "null"]},
        "unresolved": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "final_node": {"type": "string"},
        "outputs_dir": {"type": "string"},
    },
    "required": ["r1", "wr2", "goof", "space_group", "n_atoms", "chemistry_ok",
                 "defects_found", "restraints_used", "shelxl_r1", "unresolved",
                 "confidence", "final_node", "outputs_dir"],
    "additionalProperties": False,
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", default="sjtu9")
    ap.add_argument("--project", default=None)
    ap.add_argument("--truth", default=None)
    ap.add_argument("--max-nudges", type=int, default=4)
    ap.add_argument("--fresh", action="store_true",
                    help="rebuild the corrupted project even if it exists")
    args = ap.parse_args()

    stamp = time.strftime("%Y%m%d_%H%M%S")
    project = Path(args.project) if args.project else \
        REPO / "workbench" / f"mvp-{args.case}"
    truth = Path(args.truth) if args.truth else \
        REPO / "workdir" / f"mvp_truth-{args.case}"

    if args.fresh or not (project / "start.res").exists():
        from crystalpilot.benchmark.corrupt import PRESETS
        shutil.rmtree(project, ignore_errors=True)
        shutil.rmtree(truth, ignore_errors=True)
        PRESETS[args.case](project, truth)
        print(f"corrupted project rebuilt at {project}")

    from crystalpilot.workbench.core import Workbench

    stats = {"n_turns": 0, "n_shell": 0, "n_tool_calls_wb": 0,
             "input_tokens": None, "output_tokens": None, "wall_s": None}
    t0 = time.time()

    def on_event(ev):
        k = ev.get("kind")
        if k == "tool_completed":
            print(f"  [tool] {ev.get('tool')} ok={ev.get('ok')} "
                  f"{(ev.get('result_tail') or '')[:150]}", flush=True)
            stats["n_tool_calls_wb"] += 1
        elif k == "command_started":
            print(f"  [SHELL] {str(ev.get('command'))[:160]}", flush=True)
            stats["n_shell"] += 1
        elif k == "token_usage":
            tot = ev.get("total") or {}
            stats["input_tokens"] = tot.get("input_tokens")
            stats["output_tokens"] = tot.get("output_tokens")
        elif k == "turn_failed":
            print(f"  [TURN-FAILED] {json.dumps(ev.get('error'), default=str)[:400]}",
                  flush=True)
        elif k == "reasoning_summary":
            print(f"  [think] {ev.get('text', '')[:160]}", flush=True)

    verdict = None
    with Workbench(project, event_cb=on_event) as wb:
        task = wb.new_task(title=f"MVP自主精修 {stamp}")
        fmt = {"task_id": task.task_id}
        tj = truth / "defects.json"
        if tj.exists():
            fmt["frames_dir"] = json.loads(
                tj.read_text(encoding="utf-8")).get("frames_dir", "")
        prompt = CASE_PROMPTS[args.case].format(**fmt)
        finals = []

        def run_turn(text, output_schema=None):
            stats["n_turns"] += 1
            final = ""
            failed = False
            for ev in task.send(text, output_schema=output_schema):
                on_event(ev)      # turn events come from the send iterator
                if ev["kind"] == "agent_message":
                    final = ev["text"]
                if ev["kind"] == "turn_failed":
                    failed = True
            finals.append(final)
            return final, failed

        print(f"== task {task.task_id} thread {task.thread_id}")
        final, failed = run_turn(prompt)
        print(f"== turn 1 done ({len(final)} chars)")

        def outputs_written() -> bool:
            return any((task.results_dir / f).exists()
                       for f in ("REPORT.json", "final.cif"))

        nudges = 0
        while not failed and nudges < args.max_nudges and not outputs_written():
            nudges += 1
            print(f"== nudge {nudges}")
            final, failed = run_turn(NUDGE)

        print("== verdict turn")
        verdict_text, _ = run_turn(VERDICT_PROMPT, output_schema=VERDICT_SCHEMA)
        try:
            verdict = json.loads(verdict_text)
        except json.JSONDecodeError:
            print("verdict was not valid JSON:", verdict_text[:400])
            verdict = None

    stats["wall_s"] = round(time.time() - t0, 1)
    print("== stats", json.dumps(stats, ensure_ascii=False))

    run_dir = REPO / "workdir" / f"mvp_run_{stamp}"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "verdict.json").write_text(
        json.dumps(verdict or {}, indent=2, ensure_ascii=False), encoding="utf-8")
    (run_dir / "cost.json").write_text(
        json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8")

    from crystalpilot.benchmark.evaluate_refinement import evaluate, to_markdown
    r = evaluate(project, truth, verdict, stats)
    out_dir = project / "CrystalPilot Results"
    (out_dir / "eval.json").write_text(
        json.dumps(r, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    (out_dir / "EVAL_REPORT.md").write_text(to_markdown(r), encoding="utf-8")
    shutil.copy(out_dir / "EVAL_REPORT.md", run_dir / "EVAL_REPORT.md")
    print(json.dumps({k: r[k] for k in ("grade", "honesty_pass", "n_defects_fixed")},
                     ensure_ascii=False))
    print(f"eval -> {out_dir / 'EVAL_REPORT.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
