"""Turn the ka1 knowledge-layer ablation into a process-analysis draft.

ka1 varies ONE thing: how much crystallography is pre-loaded into the
project's own AGENTS.md. Arm `tools` gets the operational contract and the
honesty rules and nothing else; arm `full` gets AGENTS v32 plus the whole
skill-card library. Same L0 brief, same model, same data, same MCP tool
surface. Three lanes (ka1-hex / ka1-cage / ka1-org), one crystal each, two
arms, one replicate per cell.

Which means the outcome table is the *least* interesting thing this report
can produce. n=1 per cell: a one-band grade gap or a 0.01 R1 gap between
two single runs is not a measurement of the knowledge layer, and this
module never presents it as one. What is worth reading at n=1 is the
EXECUTION TRACE - which tools the agent could not call, where it span,
where a tool error pushed it off course, whether it read a path it should
not have. Those are per-run facts, not population estimates, and they stay
true whatever the grade turned out to be.

So the report is deliberately lopsided: one table of outcomes, then four
sections of process mined out of the rollouts by `campaign_analysis`, then
a list of mechanical signals a human still has to read the transcript to
interpret. Everything printed here comes from state.json, grade.json or
`analyse_case`; a field that is in none of those three renders as an em
dash rather than a guess.

The accounting appendix exists because the ablation is only as good as the
AGENTS.md the agent actually saw. codex concatenates every AGENTS.md from
the git toplevel down, so an injected ancestor file silently re-adds
crystallographic knowledge to the `tools` arm and voids the comparison.
`root_agents_sha256` and `agents_matches_template` are how that gets
caught, and they get their own loud warning rather than a footnote.

CLI: python -m crystalpilot.benchmark.ka1_report
         [--lanes ka1-hex,ka1-cage,ka1-org]
         [--out workdir/campaigns/KA1-ANALYSIS-draft.md]
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Sequence

from .campaign_analysis import analyse_case

REPO = Path(__file__).resolve().parents[2]
CAMPAIGNS = REPO / "workdir" / "campaigns"

LANES: tuple[str, ...] = ("ka1-hex", "ka1-cage", "ka1-org")
#: arm A then arm B, in the order the lanes run them
ARMS: tuple[str, ...] = ("tools", "full")
ARM_LETTER = {"tools": "A", "full": "B"}
ARM_LABEL = {"tools": "tools（仅工具契约）", "full": "full（v32+技能卡）"}
#: the knowledge_mode each arm is supposed to have run under
ARM_KNOWLEDGE_MODE = {"tools": "tools_only", "full": "full"}

#: worst to best, mirroring grade.grade_delivery's ladder: publication >
#: acceptable > below_bar with a reference, self_consistent_pass >
#: self_consistent_fail without one, and no_delivery underneath both.
#: Ordinal only - used to say "which arm ranked higher", never printed as
#: a score, because the spacing between bands is not meaningful.
GRADE_RANK = {
    "no_delivery": 0,
    "below_bar": 1, "self_consistent_fail": 1,
    "self_consistent": 2, "self_consistent_pass": 2,
    "acceptable": 3,
    "publication": 4,
}

#: R1 gap below which the two arms are called 接近 rather than ranked. A
#: DECLARED REPORTING CONVENTION, not a measurement: ka1 has one run per
#: cell, so no noise floor can be computed from this experiment at all.
R1_TIE_BAND = 0.01

#: a tool repeated this many times with identical arguments inside one
#: short window is listed as a spin signal in section 4
SPIN_ALERT = 3

#: honesty / self-audit gates as grade.json exposes them, in reading
#: order: (short name, dotted path into grade.json)
GATES: tuple[tuple[str, str], ...] = (
    ("s2 CIF↔fcf", "self_consistency.s2_cif_matches_fcf"),
    ("s3 REPORT↔CIF", "self_consistency.s3_report_matches_cif"),
    ("s4 checkCIF解释门", "self_consistency.checkcif.gate_d_pass"),
    ("e 窥视干净", "self_consistency.peek_report.clean"),
    ("自洽", "self_consistency.self_consistent"),
    ("结论↔CIF", "verdict_matches_cif"),
)

DASH = "—"


# --------------------------------------------------------------- small io
def _load_json(p: Path) -> Any:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _dig(d: Any, path: str) -> Any:
    """Dotted lookup that returns None instead of raising on any miss."""
    cur = d
    for key in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def expected_cells(lane: str) -> list[tuple[str, str, int]]:
    """(crystal, arm, replicate) the ka1 manifest says a lane should hold.

    Read from the manifest rather than from state.json so a lane that has
    never been started still produces rows - "未跑" is a result too, and a
    report that silently omits it looks like a completed experiment."""
    try:
        from .ka1_manifests import LANES as MANIFEST_LANES
    except Exception:  # noqa: BLE001 - a report must never die on an import
        return []
    for name, cells in MANIFEST_LANES:
        if name == lane:
            return [(c, a, r) for c, a, r in cells]
    return []


#: where campaign manifests live (the runner takes the path on its command
#: line; the report has to find the lane's manifest by name)
MANIFESTS_DIR = Path("H:/CrystalPilotData/campaigns")


def staging_allow(crystal: str, lane: str | None = None,
                  manifests_dir: Path | None = None) -> list[str]:
    """The case's own data directory: what the leakage audit subtracts.

    Two sources, unioned: the ka1 crystal table (hex / cage / org) and the
    lane's own manifest `<manifests_dir>/<lane>.json` (data_dir and
    data_alias of every case of that crystal). reg1-ext2 (2026-09-04) had
    five crystals the table never heard of, so every case's OWN staging
    directory was reported as a mentor-side leak and all five cells were
    marked void - a false positive of the audit, not of the agent."""
    out: list[str] = []
    try:
        from .ka1_manifests import CRYSTALS
        spec = CRYSTALS.get(crystal) or {}
        alias = spec.get("data_alias") or {}
        out += [str(x) for x in (alias.get("target"), alias.get("link"),
                                 spec.get("data_dir")) if x]
    except Exception:  # noqa: BLE001
        pass
    if lane:
        m = _load_json((manifests_dir or MANIFESTS_DIR) / f"{lane}.json")
        for case in (m or {}).get("cases", []) if isinstance(m, dict) else []:
            if not isinstance(case, dict):
                continue
            if crystal and case.get("crystal") not in (None, crystal):
                continue
            alias = case.get("data_alias") or {}
            out += [str(x) for x in (alias.get("target"), alias.get("link"),
                                     case.get("data_dir")) if x]
    seen: set[str] = set()
    return [x for x in out if not (x in seen or seen.add(x))]


# ------------------------------------------------------------------ loader
def analyse_logs(logs_dir: Path,
                 allow: Iterable[str] = ()) -> dict[str, Any] | None:
    """`analyse_case` on a case that may not have any logs yet.

    None means "nothing to mine" (case not run, or its bundle was never
    collected); a dict with an `error` key means the bundle is there but
    unreadable. Both are printable states; neither is an exception."""
    logs_dir = Path(logs_dir)
    if not (logs_dir / "rollout.jsonl").exists():
        return None
    try:
        return analyse_case(logs_dir, list(allow))
    except Exception as e:  # noqa: BLE001 - one bad bundle never kills the run
        return {"error": f"{type(e).__name__}: {e}",
                "tools": {}, "spin": [], "arg_churn": [], "pivots": [],
                "shell_hazards": [], "leakage": [], "leak_clean": True,
                "path_tokens": [], "failures": [], "schema_errors": [],
                "polling": [], "server_abandoned_tools": [],
                "n_tool_calls": None, "n_tool_errors": None,
                "n_schema_errors": None, "n_polls": None}


def _split_case_name(name: str) -> tuple[str, str, int]:
    """`hex-tools-r1` -> ("hex", "tools", 1); tolerant of odd names."""
    parts = name.split("-")
    crystal = parts[0] if parts else name
    arm = parts[1] if len(parts) > 1 else "?"
    rep = 1
    if len(parts) > 2 and parts[-1].startswith("r"):
        try:
            rep = int(parts[-1][1:])
        except ValueError:
            rep = 1
    return crystal, arm, rep


def _grade_facts(g: dict[str, Any]) -> dict[str, Any]:
    """Flatten the slice of grade.json this report prints."""
    rl = g.get("reference_layer") or {}
    emma = rl.get("emma") or {}
    guest = emma.get("guest") or {}
    nt = g.get("node_tree") or {}
    por = g.get("porosity") or {}
    unresolved = _dig(g, "self_consistency.unresolved_disclosed")
    return {
        "grade": g.get("grade"),
        "grade_reasons": g.get("grade_reasons") or [],
        # not written by grade.py today (docs/PLAN-2026-09-03-upgrade.md
        # T1.9 plans it); read defensively so it shows up the day it lands
        "evidence_gaps": g.get("evidence_gaps") or [],
        "r1_agent": rl.get("r1_agent"),
        "r1_reference": rl.get("r1_reference"),
        "r1_delta": rl.get("r1_delta"),
        "r1_incomparable": rl.get("r1_delta_incomparable") is True,
        "r1_scored": rl.get("r1_scored"),
        "sg_agent": rl.get("sg_agent"),
        "sg_reference": rl.get("sg_reference"),
        "sg_type_equal": rl.get("sg_type_equal"),
        "cell_compatible": rl.get("cell_compatible"),
        "elements_ok": emma.get("metal_identity_ok"),
        "n_element_mismatch": emma.get("n_element_mismatch"),
        "solved": emma.get("solved"),
        "gates": {name: _dig(g, path) for name, path in GATES},
        "n_unresolved": (len(unresolved)
                         if isinstance(unresolved, list) else None),
        "best_node_id": nt.get("best_node_id"),
        "best_node_r1": nt.get("best_node_r1"),
        "delivered_node_r1": nt.get("delivered_node_r1"),
        "delivery_vs_best_delta": nt.get("delivery_vs_best_delta"),
        "better_node_existed": nt.get("better_node_existed"),
        "mask_in_cif": por.get("mask_block_in_cif"),
        "void_fraction": por.get("void_fraction"),
        "n_guest_fragments": por.get("n_guest_fragments"),
        "porous_unmasked_unmodelled": por.get("porous_unmasked_unmodelled"),
        "guest_ref": guest.get("n_ref"),
        "guest_matched": guest.get("n_matched"),
        "guest_recall": guest.get("recall"),
        "r1_self": _dig(g, "self_consistency.cif.r1_gt"),
        "space_group_self": _dig(g, "self_consistency.cif.space_group"),
    }


def load_cases(lanes: Sequence[str] = LANES,
               root: Path | str | None = None,
               mine_logs: bool = True) -> list[dict[str, Any]]:
    """One record per expected cell, run or not.

    `root` defaults to the repo's campaign workdir; tests pass their own so
    they never read (or depend on the state of) the real one."""
    work = Path(root) if root is not None else CAMPAIGNS
    out: list[dict[str, Any]] = []
    for lane in lanes:
        state = _load_json(work / lane / "state.json")
        if not isinstance(state, dict):
            state = {}
        names = [f"{c}-{a}-r{r}" for c, a, r in expected_cells(lane)]
        # anything the runner actually produced but the manifest does not
        # list (a renamed or hand-added case) still gets a row
        names += [n for n in state if n not in names]
        for name in names:
            st = state.get(name)
            st = st if isinstance(st, dict) else None
            crystal, arm, rep = _split_case_name(name)
            cdir = work / lane / name
            usage = (st or {}).get("usage")
            rec: dict[str, Any] = {
                "lane": lane, "case": name, "crystal": crystal,
                "arm": arm, "replicate": rep,
                "started": st is not None,
                "status": (st or {}).get("status"),
                "grade": (st or {}).get("grade"),
                "wall_s": (st or {}).get("wall_s"),
                "lanes_busy": (st or {}).get("lanes_busy"),
                "tokens": (usage or {}).get("total_tokens"),
                "n_tool_events": (st or {}).get("n_tool_events"),
                "log_bytes": (st or {}).get("log_bytes"),
                "log_errors": (st or {}).get("log_errors"),
                "turn_status": (st or {}).get("turn_status"),
                "model": (st or {}).get("model"),
                "effort": (st or {}).get("effort"),
                "knowledge_mode": (st or {}).get("knowledge_mode"),
                "agents_version": (st or {}).get("agents_version"),
                "agents_sha256": (st or {}).get("agents_sha256"),
                "agents_matches_template":
                    (st or {}).get("agents_matches_template"),
                "root_agents_sha256": (st or {}).get("root_agents_sha256"),
                "agents_chain_len": len((st or {}).get("agents_chain") or []),
                "verdict_matches_cif": (st or {}).get("verdict_matches_cif"),
                "gates": {name_: None for name_, _ in GATES},
                "logs_dir": cdir / "logs",
            }
            g = _load_json(cdir / "grade.json")
            rec["graded"] = isinstance(g, dict) and bool(g.get("grade"))
            if isinstance(g, dict):
                # grade.json is authoritative: a case can be re-graded out
                # of band, leaving state.json's label stale
                rec.update(_grade_facts(g))
                if rec["gates"].get("结论↔CIF") is None:
                    rec["gates"]["结论↔CIF"] = rec["verdict_matches_cif"]
            rec["mined"] = (analyse_logs(cdir / "logs",
                                         staging_allow(crystal, lane))
                            if mine_logs else None)
            out.append(rec)
    return out


# ----------------------------------------------------------- cell renderers
def _tri(v: Any) -> str:
    if v is True:
        return "是"
    if v is False:
        return "否"
    return DASH


def _num(v: Any, fmt: str = "{:.4f}") -> str:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return DASH
    return fmt.format(v)


def _state_cell(r: dict[str, Any]) -> str:
    if not r["started"]:
        return "未跑"
    if not r.get("graded"):
        return f"{r.get('status') or '进行中'}（未评分）"
    return str(r.get("status") or "graded")


def _grade_cell(r: dict[str, Any]) -> str:
    if not r["started"]:
        return "未跑"
    return str(r.get("grade") or "未评分")


def _delta_cell(r: dict[str, Any]) -> str:
    """ΔR1, or why it is not a number you may compare."""
    if not r.get("graded"):
        return "未评分" if r["started"] else "未跑"
    d = r.get("r1_delta")
    shown = _num(d, "{:+.4f}")
    if r.get("r1_incomparable"):
        return f"不可比（分辨率截断不同；Δ={shown}）"
    if r.get("r1_scored") is False:
        return f"不可比（literature 参考不计分；Δ={shown}）"
    return shown


def _gate_cell(r: dict[str, Any]) -> str:
    gates = r.get("gates") or {}
    if not any(v is not None for v in gates.values()):
        return DASH
    bits = [f"{name}:{_tri(gates.get(name))}" for name, _ in GATES]
    n_unres = r.get("n_unresolved")
    if n_unres is not None:
        bits.append(f"未决披露:{n_unres} 条")
    return "<br>".join(bits)


def _best_node_cell(r: dict[str, Any]) -> str:
    if r.get("better_node_existed") is None:
        return DASH
    if not r["better_node_existed"]:
        return "是（交付即最佳，或差距在 0.01 以内）"
    return (f"否：树里最佳 {r.get('best_node_id')} R1 "
            f"{_num(r.get('best_node_r1'))}，交付 "
            f"{_num(r.get('delivered_node_r1'))}"
            f"（Δ={_num(r.get('delivery_vs_best_delta'), '{:+.4f}')}）")


def _tool_counts(r: dict[str, Any]) -> tuple[str, str]:
    m = r.get("mined") or {}
    n_calls = m.get("n_tool_calls")
    if n_calls is None:
        n_calls = r.get("n_tool_events")
    n_err = m.get("n_tool_errors")
    return (str(n_calls) if n_calls is not None else DASH,
            str(n_err) if n_err is not None else DASH)


def _template_cell(r: dict[str, Any]) -> str:
    sha = r.get("agents_sha256")
    match = r.get("agents_matches_template")
    if not isinstance(sha, str) or not sha:
        return DASH if match is None else f"{DASH} {_tri(match)}"
    if match is False:
        return f"`{sha[:8]}` **不匹配模板**"
    return f"`{sha[:8]}` {_tri(match)}"


# --------------------------------------------------------------- section 1
def render_summary_table(recs: list[dict[str, Any]]) -> list[str]:
    L = ["## 1. 结果总表", "",
         "每格一次运行（n=1）。缺失字段一律打 ` - `，不做任何补值。",
         "「诚实门」列出 grade.json 实际写下的自审门：s2（CIF 声称的 R1 能否由",
         "它自己的 fcf 复算出来）、s3（REPORT.json 与 CIF 是否一致）、",
         "s4（checkCIF 警报是否逐条解释，gate_d_pass）、e（窥视报告是否干净）、",
         "自洽（self_consistent 汇总）、结论↔CIF（收尾结论里的 R1 与交付 CIF",
         "是否相符，verdict_matches_cif）。",
         "",
         "| 晶体 | 臂 | 等级 | R1(agent) | R1(ref) | ΔR1 | 空间群一致 "
         "| 元素一致 | 诚实门 | 最佳节点是否交付 | 墙钟 | tokens "
         "| 工具调用 | 工具错误 | 并发泳道 | 模板哈希 | 状态 |",
         "|" + "---|" * 17]
    for r in recs:
        calls, errs = _tool_counts(r)
        wall = (f"{r['wall_s'] / 60:.0f} min"
                if isinstance(r.get("wall_s"), (int, float)) else DASH)
        tok = (f"{r['tokens']:,}"
               if isinstance(r.get("tokens"), int) else DASH)
        L.append(
            f"| {r['crystal']} | {ARM_LETTER.get(r['arm'], '?')}/{r['arm']} "
            f"| {_grade_cell(r)} | {_num(r.get('r1_agent'))} "
            f"| {_num(r.get('r1_reference'))} | {_delta_cell(r)} "
            f"| {_tri(r.get('sg_type_equal'))} "
            f"| {_tri(r.get('elements_ok'))} | {_gate_cell(r)} "
            f"| {_best_node_cell(r)} | {wall} | {tok} "
            f"| {calls} | {errs} | {r.get('lanes_busy') or DASH} "
            f"| {_template_cell(r)} | {_state_cell(r)} |")
    if not any(r.get("graded") for r in recs):
        L += ["", "> **本实验尚无任何已评分的格子**：后面各节的表格因此都是空的。",
              "> 这不是失败，是还没跑。"]
    return L


# --------------------------------------------------------------- section 2
def arm_verdict(a: dict[str, Any] | None,
                b: dict[str, Any] | None) -> tuple[str, str]:
    """(判语, 依据) for one crystal's A(tools) vs B(full) pair.

    Grade band first, R1 only to break a tie inside one band. Purely
    mechanical: it reports which cell ranked higher, and section 2's prose
    says why that is not the same thing as a finding."""
    missing = [letter for letter, rec in (("A", a), ("B", b))
               if rec is None or not rec.get("graded")]
    if missing:
        return "不可判", f"{'/'.join(missing)} 臂未评分"
    ra = GRADE_RANK.get(a.get("grade") or "")
    rb = GRADE_RANK.get(b.get("grade") or "")
    if ra is None or rb is None:
        return "不可判", (f"等级 {a.get('grade')} / {b.get('grade')} "
                          "不在评级梯上")
    if rb > ra:
        return "B>A", f"等级 {b['grade']} 高于 {a['grade']}"
    if ra > rb:
        return "A≥B", f"等级 {a['grade']} 高于 {b['grade']}"
    r1a, r1b = a.get("r1_agent"), b.get("r1_agent")
    if not isinstance(r1a, (int, float)) or not isinstance(r1b, (int, float)):
        return "接近", f"等级同为 {a['grade']}，R1 缺失，无法再分"
    gap = round(r1a - r1b, 4)
    if abs(gap) < R1_TIE_BAND:
        return "接近", (f"等级同为 {a['grade']}，R1 相差 {gap:+.4f}，"
                        f"小于本报告声明的并列带 {R1_TIE_BAND}")
    if gap > 0:
        return "B>A", f"等级同为 {a['grade']}，B 的 R1 低 {abs(gap):.4f}"
    return "A≥B", f"等级同为 {a['grade']}，A 的 R1 低 {abs(gap):.4f}"


#: rows compared side by side in section 2
_COMPARE_ROWS: tuple[tuple[str, str], ...] = (
    ("等级", "grade"),
    ("R1(agent)", "r1_agent"),
    ("R1(ref)", "r1_reference"),
    ("ΔR1", "_delta"),
    ("空间群 agent / ref", "_sg"),
    ("空间群同型", "sg_type_equal"),
    ("骨架复现 emma solved", "solved"),
    ("元素一致", "elements_ok"),
    ("自洽", "_self_consistent"),
    ("最佳节点是否交付", "_best"),
    ("掩膜 / 客体", "_mask"),
    ("未达 publication 的原因", "_reasons"),
    ("墙钟", "_wall"),
    ("并发泳道", "lanes_busy"),
    ("tokens", "_tokens"),
    ("工具调用 / 出错", "_tools"),
    ("knowledge_mode", "knowledge_mode"),
)


def _compare_value(r: dict[str, Any] | None, key: str) -> str:
    if r is None:
        return DASH
    if key == "grade":
        return _grade_cell(r)
    if not r["started"]:
        return "未跑"
    if key == "_delta":
        return _delta_cell(r)
    if key == "_sg":
        return f"{r.get('sg_agent') or DASH} / {r.get('sg_reference') or DASH}"
    if key == "_self_consistent":
        return _tri((r.get("gates") or {}).get("自洽"))
    if key == "_best":
        return _best_node_cell(r)
    if key == "_mask":
        guest_m = r.get("guest_matched")
        guest_n = r.get("guest_ref")
        return (f"掩膜={_tri(r.get('mask_in_cif'))}；"
                f"客体片段="
                f"{r.get('n_guest_fragments') if r.get('n_guest_fragments') is not None else DASH}；"
                f"空腔占比={_num(r.get('void_fraction'), '{:.1%}')}；"
                f"参考客体复现="
                f"{guest_m if guest_m is not None else DASH}/"
                f"{guest_n if guest_n is not None else DASH}")
    if key == "_reasons":
        rs = r.get("grade_reasons") or []
        gaps = r.get("evidence_gaps") or []
        if not rs and not gaps:
            return DASH
        out = "<br>".join(f"- {str(x)[:160]}" for x in rs[:6])
        if gaps:
            out += "<br>证据缺口：" + "；".join(str(x)[:80] for x in gaps[:4])
        return out
    if key == "_wall":
        return (f"{r['wall_s'] / 60:.0f} min（{r['wall_s']:.0f} s）"
                if isinstance(r.get("wall_s"), (int, float)) else DASH)
    if key == "_tokens":
        return f"{r['tokens']:,}" if isinstance(r.get("tokens"), int) else DASH
    if key == "_tools":
        calls, errs = _tool_counts(r)
        return f"{calls} / {errs}"
    v = r.get(key)
    if v is None:
        return DASH
    if isinstance(v, bool):
        return _tri(v)
    if isinstance(v, float):
        return _num(v)
    return str(v)


def render_arm_comparison(recs: list[dict[str, Any]]) -> list[str]:
    by: dict[tuple[str, str], dict[str, Any]] = {
        (r["crystal"], r["arm"]): r for r in recs}
    crystals: list[str] = []
    for r in recs:
        if r["crystal"] not in crystals:
            crystals.append(r["crystal"])

    L = ["## 2. 两臂对比（按晶体）", "",
         f"A = {ARM_LABEL['tools']}；B = {ARM_LABEL['full']}。", "",
         "**判读纪律：每格只有一次运行（n=1）。** 判语只是机械地报出「哪一格排",
         "在前面」，它不是「知识层有没有用」的答案。pa1 的做法是让同一格重复跑",
         "两次、把两次之间的散布当噪声地板，任何小于地板的差都记为不可区分（见",
         "`pa1_report` 模块文档：r22 那一次 informed/blind 只差 R1 0.0006，在没",
         "有地板的情况下根本无法判断那是真的零效应还是样本量不足）。ka1 没有重复",
         "格，因此本实验**测不出自己的噪声地板**：下面任何一档的差距、任何一个",
         "R1 的差距，都可能只是同一条件下重跑一次的正常抖动。要下结论，得补重复",
         "格，或者把结论限制在过程层（第 3–5 节）。", "",
         f"「接近」使用的并列带 ΔR1 < {R1_TIE_BAND} 是本报告声明的呈现约定，",
         "不是任何测量得到的阈值。", ""]

    for i, c in enumerate(crystals, 1):
        a, b = by.get((c, "tools")), by.get((c, "full"))
        verdict, why = arm_verdict(a, b)
        L += [f"### 2.{i} {c}", "",
              "| 项目 | A/tools | B/full |", "|---|---|---|"]
        for label, key in _COMPARE_ROWS:
            L.append(f"| {label} | {_compare_value(a, key)} "
                     f"| {_compare_value(b, key)} |")
        L += ["", f"**机械判语：{verdict}**：{why}。n=1，不构成结论。", ""]
    return L


# --------------------------------------------------------------- section 3
def _tool_error_table(m: dict[str, Any]) -> list[str]:
    tools = m.get("tools") or {}
    if not tools:
        return ["_无工具调用记录_"]
    msg_by_tool: dict[str, Counter] = defaultdict(Counter)
    for f in m.get("failures") or []:
        msg_by_tool[f.get("tool") or "?"][(f.get("error") or "")[:110]] += 1
    L = ["| 工具 | 调用 | 出错 | 错误率 | 累计耗时 | 最常见错误 |",
         "|---|---|---|---|---|---|"]
    rows = sorted(tools.items(),
                  key=lambda kv: (-(kv[1].get("errors") or 0),
                                  -(kv[1].get("calls") or 0)))
    for tool, row in rows:
        top = msg_by_tool.get(tool)
        msg = f"`{top.most_common(1)[0][0]}`" if top else DASH
        secs = row.get("secs")
        L.append(f"| `{tool}` | {row.get('calls', 0)} | {row.get('errors', 0)} "
                 f"| {row.get('error_rate', 0)} "
                 f"| {_num(secs, '{:.1f}s') if secs else DASH} | {msg} |")
    return L


def _schema_error_lines(m: dict[str, Any]) -> list[str]:
    """One line per distinct (tool, parameter, message) rejection."""
    errs = m.get("schema_errors") or []
    if not errs:
        return ["_无_"]
    grouped: Counter[tuple[str, str, str, str]] = Counter()
    for e in errs:
        grouped[(e.get("tool") or "?", e.get("param") or "",
                 e.get("kind") or "", (e.get("message") or "")[:110])] += 1
    out = []
    for (tool, param, kind, msg), n in grouped.most_common(12):
        out.append(f"- `{tool}` ×{n}　参数 "
                   + (f"`{param}`" if param else "未在消息中点名")
                   + (f"（{kind}）" if kind else "")
                   + (f"：`{msg}`" if msg else ""))
    return out


def _polling_lines(m: dict[str, Any]) -> list[str]:
    polls = m.get("polling") or []
    if not polls:
        return ["_无_"]
    out = []
    for p in polls[:12]:
        span = p.get("span_s")
        gap = p.get("mean_interval_s")
        out.append(
            f"- `{p.get('tool')}` 轮询 `{p.get('job')}` {p.get('polls')} 次"
            + (f"，覆盖 {span}s 墙钟" if span else "")
            + (f"（平均间隔 {gap}s）" if gap else ""))
    total = m.get("polled_wall_s")
    if total:
        out.append(f"- 合计：{m.get('n_polls')} 次轮询，覆盖 {total}s 墙钟；"
                   "这是**等待**，不是打转")
    return out


def _abandoned_lines(m: dict[str, Any]) -> list[str]:
    ab = m.get("server_abandoned_tools") or []
    if not ab:
        return ["_无_"]
    out = []
    for a in ab[:12]:
        out.append(f"- `{a.get('tool') or '?'}` 在传输断开时仍在运行，已算 "
                   f"{_num(a.get('elapsed_s'), '{:.0f}')}s"
                   + (f"（预算 {_num(a.get('budget_s'), '{:.0f}')}s）"
                      if a.get("budget_s") is not None else "")
                   + "：这一格结束时它还没算完，模型没能给它设界")
    return out


def _case_process(r: dict[str, Any], n: int) -> list[str]:
    m = r.get("mined")
    title = (f"### 3.{n} {r['case']}（{ARM_LETTER.get(r['arm'], '?')}/"
             f"{r['arm']}）")
    if m is None:
        return [title, "", "_无日志包（未跑，或 rollout.jsonl 未收集）_", ""]
    L = [title, ""]
    if m.get("error"):
        L += [f"**日志挖掘失败**：`{m['error']}`", ""]

    leaks = m.get("leakage") or []
    if leaks:
        L += ["> **数据泄漏命中 → 本格结果作废。** 该格在自己的 staging 目录之外",
              "> 读到了导师侧路径。盲测的前提是 agent 拿不到答案；一旦读到，这一格",
              "> 的等级和 R1 就不再能证明任何事，只能重跑。", ""]

    L += [f"- rollout 记录 {m.get('rollout_records', DASH)} 条；"
          f"工具调用 {m.get('n_tool_calls', DASH)} 次，"
          f"其中出错 {m.get('n_tool_errors', DASH)} 次；"
          f"推理段 {m.get('n_reasoning', DASH)} 段", "",
          "**工具错误率**", ""]
    L += _tool_error_table(m)
    n_exp = m.get("n_expected_refusals") or 0
    if n_exp:
        by = Counter(e["tool"] for e in (m.get("expected_refusals") or []))
        L += ["", f"协议性拒绝 {n_exp} 次（不计入出错：工具按协议先拒、agent 补理由再收）："
              + "、".join(f"`{k}` ×{v}" for k, v in by.most_common())]

    L += ["", "**schema 拒绝（MCP 层在工具执行前挡下的调用）**", "",
          "这类调用工具根本没跑过，因此和工具好不好用无关，只和**参数面好不好",
          "调**有关。", ""]
    L += _schema_error_lines(m)

    L += ["", "**原地打转（短窗口内重复同一调用、同一参数）**", "",
          "轮询已剔除（见下一小节）：detach 任务的状态查询本来就该重复。", ""]
    spin = m.get("spin") or []
    L += ([f"- `{s['tool']}` 重复 {s['repeats']} 次　参数 "
           f"`{str(s.get('args') or '')[:110]}`" for s in spin[:12]]
          or ["_无_"])

    L += ["", "**轮询（detach 任务的状态查询，按工具契约每 60-120 s 一次）**", ""]
    L += _polling_lines(m)

    L += ["", "**服务端丢下的工具（MCP 传输断开时仍在算）**", ""]
    L += _abandoned_lines(m)

    L += ["", "**参数试错（同一工具连续调用、参数每次都变，且其中有出错）**", ""]
    churn = m.get("arg_churn") or []
    bad = [c for c in churn if c.get("n_errors")]
    browse = [c for c in churn if not c.get("n_errors")]
    L += ([f"- `{c['tool']}` 连续 {c['calls']} 次，{c['distinct_args']} 种参数，"
           f"其中出错 {c['n_errors']} 次"
           for c in bad[:12]] or ["_无_"])
    if browse:
        L += ["", "连续换参但全部成功（读卡、逐段查看、逐片段验证一类的正常浏览，"
                  "不计入易用性信号）：",
              "; ".join(f"`{c['tool']}` {c['calls']} 次 {c['distinct_args']} 种"
                        for c in browse[:12])]

    L += ["", "**转向（换打法，并附紧邻其前的工具错误）**", ""]
    pivots = m.get("pivots") or []
    if pivots:
        for p in pivots[:12]:
            after = p.get("after_tool_error")
            L.append(f"- 触发词 `{p.get('marker')}`"
                     + (f"，紧接在 `{after}` 报错之后："
                        f"`{(p.get('tool_error') or '')[:110]}`"
                        if after else "，其前无工具报错"))
            L.append(f"  > {(p.get('excerpt') or '')[:300]}")
    else:
        L.append("_无_")

    L += ["", "**shell 危险用法**", ""]
    haz = m.get("shell_hazards") or []
    if haz:
        for h in haz:
            L += [f"- **{h['hazard']}** ×{h['count']}",
                  f"  - 后果：{h['why']}",
                  f"  - 例：`{(h.get('example') or '')[:140]}`"]
    else:
        L.append("_无_")

    L += ["", "**数据泄漏审计**", ""]
    if leaks:
        for h in leaks[:8]:
            L.append(f"- {h.get('where')}：`{(h.get('context') or '')[:140]}`")
    else:
        L.append("_干净：未读取自己 staging 目录以外的导师侧路径_")

    L += ["", "**路径线索（agent 从目录名里读出的提示）**", ""]
    toks = m.get("path_tokens") or []
    L += ([f"- `{t.get('token')}`：{(t.get('context') or '')[:140]}"
           for t in toks[:8]] or ["_无_"])
    L.append("")
    return L


def aggregate_tools(recs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Per-tool totals over every mined case in the experiment.

    `schema_errors` is a subset of `errors` (a rejected call is a failed
    call) and `polls` a subset of `calls`; both are carried separately
    because they answer different questions - the first "can the model
    call this tool at all", the second "how much of this tool's traffic
    was just waiting"."""
    agg: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"calls": 0, "errors": 0, "schema_errors": 0, "polls": 0,
                 "abandoned": 0, "secs": 0.0, "cases": 0,
                 "cases_with_error": 0, "spin": 0, "churn": 0})
    for r in recs:
        m = r.get("mined") or {}
        for tool, row in (m.get("tools") or {}).items():
            t = agg[tool]
            t["calls"] += row.get("calls") or 0
            t["errors"] += row.get("errors") or 0
            t["schema_errors"] += row.get("schema_errors") or 0
            t["polls"] += row.get("polls") or 0
            t["secs"] += row.get("secs") or 0.0
            t["cases"] += 1
            if row.get("errors"):
                t["cases_with_error"] += 1
        for s in m.get("spin") or []:
            agg[s["tool"]]["spin"] += s.get("repeats") or 0
        for c in m.get("arg_churn") or []:
            if c.get("n_errors"):          # error-free churn is browsing
                agg[c["tool"]]["churn"] += c.get("distinct_args") or 0
        for a in m.get("server_abandoned_tools") or []:
            if a.get("tool"):
                agg[a["tool"]]["abandoned"] += 1
    for t in agg.values():
        t["secs"] = round(t["secs"], 1)
        t["error_rate"] = (round(t["errors"] / t["calls"], 3)
                           if t["calls"] else 0.0)
    return dict(agg)


def render_process(recs: list[dict[str, Any]]) -> list[str]:
    L = ["## 3. 过程分析（执行层）", "",
         "本节每个数字都来自 `campaign_analysis.analyse_case` 对该格 rollout 的",
         "挖掘：工具调用与结果、推理摘要、shell 命令。等级好坏与本节无关，一个",
         "拿到 publication 的 run 照样可能在某个工具上空转二十分钟。", ""]
    # lane order, arm A before arm B - the order load_cases emits, which is
    # the order the runner actually ran them in
    for i, r in enumerate(recs, 1):
        L += _case_process(r, i)

    agg = aggregate_tools(recs)
    L += [f"### 3.{len(recs) + 1} 全实验汇总", ""]
    if not agg:
        L += ["_尚无任何日志包可挖掘_", ""]
        return L
    L += ["**错误率最高的工具**（只列有过失败的）", "",
          "| 工具 | 调用 | 出错 | 错误率 | 出错的格数 |",
          "|---|---|---|---|---|"]
    erred = [(t, v) for t, v in agg.items() if v["errors"]]
    if erred:
        for tool, v in sorted(erred, key=lambda kv: (-kv[1]["error_rate"],
                                                     -kv[1]["errors"]))[:15]:
            L.append(f"| `{tool}` | {v['calls']} | {v['errors']} "
                     f"| {v['error_rate']} | {v['cases_with_error']}"
                     f"/{v['cases']} |")
    else:
        L.append("| _无工具报错_ | | | | |")

    L += ["", "**打转 / 试错最多的工具**", "",
          "| 工具 | 打转重复次数 | 参数试错种数 |", "|---|---|---|"]
    noisy = [(t, v) for t, v in agg.items() if v["spin"] or v["churn"]]
    if noisy:
        for tool, v in sorted(noisy,
                              key=lambda kv: -(kv[1]["spin"] +
                                               kv[1]["churn"]))[:15]:
            L.append(f"| `{tool}` | {v['spin']} | {v['churn']} |")
    else:
        L.append("| _无_ | | |")

    L += ["", "**每个工具的累计耗时**", ""]
    if any(v["secs"] for v in agg.values()):
        L += ["| 工具 | 调用 | 累计耗时 |", "|---|---|---|"]
        for tool, v in sorted(agg.items(), key=lambda kv: -kv[1]["secs"])[:15]:
            if not v["secs"]:
                continue
            L.append(f"| `{tool}` | {v['calls']} | {v['secs']}s |")
    else:
        L.append("_rollout 未携带每次调用的时长（只有 MCP 传输记录 duration）；"
                 "此项留空，不补零_")
    L.append("")
    return L


# --------------------------------------------------------------- section 4
def collect_signals(recs: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Mechanically computable flags. Each one says WHAT to go and read."""
    sig: list[dict[str, str]] = []
    for r in recs:
        case = r["case"]
        if r.get("agents_matches_template") is False:
            sig.append({"case": case, "kind": "模板不匹配",
                        "detail": "该格磁盘上的 AGENTS.md 不是本臂应有的渲染结果"
                                  "（外来文件 / 旧副本 / 开跑后又改过模板）。"
                                  "**这一格的臂标签不可信**，它究竟属于哪一臂，"
                                  "必须人工确认后才能进入任何对比。"})
        if r.get("root_agents_sha256"):
            sig.append({"case": case, "kind": "祖先 AGENTS.md 注入",
                        "detail": "root_agents_sha256=`"
                                  f"{str(r['root_agents_sha256'])[:8]}`；"
                                  "codex 会把 git 顶层到项目目录之间的每个 "
                                  "AGENTS.md 串起来，被注入的那份很可能把晶体学"
                                  "知识又塞回了 tools 臂，消融因此失效。"})
        m = r.get("mined") or {}
        if m.get("leakage"):
            sig.append({"case": case, "kind": "数据泄漏",
                        "detail": f"{len(m['leakage'])} 处命中导师侧路径 → "
                                  "本格结果作废，需重跑"})
        for s in m.get("spin") or []:
            if (s.get("repeats") or 0) >= SPIN_ALERT:
                sig.append({"case": case, "kind": "原地打转",
                            "detail": f"`{s['tool']}` 同参数重复 "
                                      f"{s['repeats']} 次（阈值 {SPIN_ALERT}）"})
        # one finding per (tool, parameter): the same rejection twice is
        # one call-surface defect, not two signals to go and read
        rejects: Counter[tuple[str, str, str]] = Counter()
        for e in m.get("schema_errors") or []:
            rejects[(e.get("tool") or "?", e.get("param") or "",
                     e.get("kind") or "")] += 1
        for (tool, param, kind), n in rejects.most_common():
            sig.append({"case": case, "kind": "schema 拒绝",
                        "detail": f"`{tool}` 的调用被 MCP 层挡下 {n} 次，"
                                  + (f"参数 `{param}`" if param
                                     else "参数未点名")
                                  + f"（{kind}）：工具没跑过，是参数面的问题"})
        for a in m.get("server_abandoned_tools") or []:
            sig.append({"case": case, "kind": "工具被丢下",
                        "detail": f"`{a.get('tool') or '?'}` 在 MCP 传输断开时"
                                  f"仍在运行（已算 "
                                  f"{_num(a.get('elapsed_s'), '{:.0f}')}s）"})
        if r.get("better_node_existed"):
            sig.append({"case": case, "kind": "交付的不是最佳节点",
                        "detail": f"树里 {r.get('best_node_id')} 的 R1 是 "
                                  f"{_num(r.get('best_node_r1'))}，交付的是 "
                                  f"{_num(r.get('delivered_node_r1'))}"
                                  f"（Δ="
                                  f"{_num(r.get('delivery_vs_best_delta'), '{:+.4f}')}）"})
        for name, v in (r.get("gates") or {}).items():
            if v is False:
                sig.append({"case": case, "kind": "诚实门未过",
                            "detail": f"{name} = 否"})
        if r.get("porous_unmasked_unmodelled"):
            sig.append({"case": case, "kind": "多孔但既无掩膜也无客体",
                        "detail": "空腔占比 "
                                  f"{_num(r.get('void_fraction'), '{:.1%}')}"})
    return sig


def render_signals(recs: list[dict[str, Any]]) -> list[str]:
    L = ["## 4. 跑偏倾向与打转点（机械信号，待人工核读）", "",
         "下面每一条都是程序能算出来的**信号**，不是结论。信号只回答「该去",
         "transcript 的哪一段看」；看到的究竟是不是跑偏，必须人读。", ""]
    sig = collect_signals(recs)
    if not sig:
        L += ["_当前没有触发任何机械信号（也可能只是还没跑）_", ""]
    else:
        by_case: dict[str, list[dict[str, str]]] = defaultdict(list)
        for s in sig:
            by_case[s["case"]].append(s)
        for case, items in by_case.items():
            L.append(f"- **{case}**")
            for s in items:
                L.append(f"  - [{s['kind']}] {s['detail']}")
        L.append("")
        loud = [s["case"] for s in sig
                if s["kind"] in ("模板不匹配", "祖先 AGENTS.md 注入", "数据泄漏")]
        if loud:
            L += ["> **实验有效性告警**：带「模板不匹配 / 祖先 AGENTS.md 注入 /",
                  "> 数据泄漏」标记的格子（"
                  + "、".join(f"`{c}`" for c in sorted(set(loud)))
                  + "）不能进入两臂对比，臂标签或盲测",
                  "> 前提已经被破坏。", ""]
    L += ["<!-- 人工核读：",
          "  1. 逐格读 transcript，判断上面每条信号是真跑偏，还是正常的探索；",
          "  2. 记下 tools 臂在没有技能卡的情况下自己重建了哪些判据、漏了哪些；",
          "  3. 记下 full 臂是否出现「照卡执行但并不理解」的迹象；",
          "  4. 写下每格最关键的一次转向，以及它是被哪一条工具消息推动的。",
          "-->", ""]
    return L


# --------------------------------------------------------------- section 5
def render_tool_usability(recs: list[dict[str, Any]]) -> list[str]:
    agg = aggregate_tools(recs)
    L = ["## 5. 工具易用性信号", "",
         "按「出错 + schema 拒绝 + 参数试错 + 打转」之和排序。这是**模型难以",
         "正确调用的工具清单**，逐格证据见第 3 节。本节不解释原因。", "",
         "schema 拒绝额外加权一次：它已经计入「出错」，但它比一次运行失败更",
         "重，工具连跑都没跑，是参数面本身让模型调不对。轮询不计入任何一项",
         "（那是工具契约要求的等待）。", ""]
    scored = [(t, v, v["errors"] + v["schema_errors"] + v["churn"] + v["spin"])
              for t, v in agg.items()]
    scored = [x for x in scored if x[2] > 0]
    if not scored:
        L += ["_无数据（没有工具报错、schema 拒绝、参数试错或打转的记录）_", ""]
    else:
        L += ["| 工具 | 合计信号 | 出错 | 其中 schema 拒绝 | 参数试错 | 打转 "
              "| 调用 | 其中轮询 | 错误率 |",
              "|---|---|---|---|---|---|---|---|---|"]
        for tool, v, score in sorted(scored, key=lambda x: -x[2]):
            L.append(f"| `{tool}` | {score} | {v['errors']} "
                     f"| {v['schema_errors']} | {v['churn']} "
                     f"| {v['spin']} | {v['calls']} | {v['polls']} "
                     f"| {v['error_rate']} |")
        L.append("")
    abandoned = [(t, v) for t, v in agg.items() if v["abandoned"]]
    if abandoned:
        L += ["**传输断开时仍在计算的工具**（来自 `mcp_server.jsonl` 的看门狗行，",
              "不是 rollout）：这一格结束时工具还没算完，rollout 里只有调用、",
              "没有结果。", "",
              "| 工具 | 被丢下的次数 |", "|---|---|"]
        for tool, v in sorted(abandoned, key=lambda kv: -kv[1]["abandoned"]):
            L.append(f"| `{tool}` | {v['abandoned']} |")
        L.append("")
    return L


# ------------------------------------------------------------- appendix
def render_accounting(recs: list[dict[str, Any]]) -> list[str]:
    L = ["## 附：运行记账", "",
         "`root_agents_sha256` 对一条干净的臂必须是 null，`agents_chain` 长度必须",
         "是 1（只有项目自己那份 AGENTS.md）。", "",
         "| 格 | model | effort | knowledge_mode | agents_version "
         "| agents_sha256 | 匹配模板 | root_agents_sha256 | 链长 |",
         "|" + "---|" * 9]
    for r in recs:
        sha = r.get("agents_sha256")
        root = r.get("root_agents_sha256")
        # a case that never opened has no chain to report: "null" would
        # claim a clean arm that was never checked
        root_cell = (f"`{str(root)[:8]}`" if root
                     else ("null（干净）" if r["started"] else DASH))
        L.append(
            f"| {r['case']} | {r.get('model') or DASH} "
            f"| {r.get('effort') or DASH} "
            f"| {r.get('knowledge_mode') or DASH} "
            f"| {r.get('agents_version') or DASH} "
            f"| {('`' + sha[:8] + '`') if isinstance(sha, str) and sha else DASH} "
            f"| {_tri(r.get('agents_matches_template'))} "
            f"| {root_cell} "
            f"| {r.get('agents_chain_len') or DASH} |")

    L.append("")
    warned = False
    for r in recs:
        chain = r.get("agents_chain_len") or 0
        if r.get("root_agents_sha256") or chain > 1:
            L += [f"- **污染告警：`{r['case']}` 之上还有被注入的祖先 AGENTS.md**"
                  f"（root_agents_sha256="
                  f"`{str(r.get('root_agents_sha256'))[:8]}`，链长 {chain}）。",
                  "  codex 会把 git 顶层到项目目录之间的每个 AGENTS.md 串起来喂"
                  "给 agent，所以这一格实际读到的指令并不是本臂的模板；消融被",
                  "  破坏，该格不得进入两臂对比。"]
            warned = True
        if r.get("agents_matches_template") is False:
            L.append(f"- **模板告警：`{r['case']}` 的 AGENTS.md 与本臂模板哈希不符"
                     "，臂标签不可信。**")
            warned = True
        km = r.get("knowledge_mode")
        expect = ARM_KNOWLEDGE_MODE.get(r["arm"])
        if km and expect and km != expect:
            L.append(f"- **臂标签告警：`{r['case']}` 的 knowledge_mode=`{km}`，"
                     f"而案例名声称的臂是 `{r['arm']}`（应为 `{expect}`）。**")
            warned = True
    if not warned:
        L.append("- 未发现祖先 AGENTS.md 注入、模板哈希不符或臂标签矛盾"
                 "（未跑的格子无从检查）。")
    L.append("")
    return L


# --------------------------------------------------------------- assembly
def render_report(recs: list[dict[str, Any]]) -> str:
    n_started = sum(1 for r in recs if r["started"])
    n_graded = sum(1 for r in recs if r.get("graded"))
    L = ["# ka1：知识层消融实验分析（草稿）", "",
         "**实验设计**：只变一件事，项目自己的 AGENTS.md 里预装了多少晶体学知识。",
         f"A 臂 = {ARM_LABEL['tools']}：只有操作契约与诚实规则（怎么调工具、交付",
         "格式、「没定就说没定，不许编」），没有任何技能卡、没有任何晶体学判据。",
         f"B 臂 = {ARM_LABEL['full']}：现行 AGENTS v32 加完整技能卡库。两臂同一",
         "条 L0 简报、同一模型、同一份数据、同一套 MCP 工具面。", "",
         f"**当前进度**：共 {len(recs)} 格，已开跑 {n_started} 格，"
         f"已评分 {n_graded} 格。", "",
         "**本报告的取舍**：n=1 的等级差不是结论，所以第 1、2 节只做机械呈现；",
         "真正能读的是第 3–5 节的执行层，哪些工具调不动、在哪里打转、哪条错误",
         "消息把 agent 推去了别处。这些是单次运行就成立的事实。所有数字只来自",
         "`state.json`、`grade.json` 与 `campaign_analysis.analyse_case`；缺的",
         "字段一律打 ` - `。", ""]
    if n_started == 0:
        L += ["> **实验尚未开始**：这些泳道下还没有 state.json（或其中没有任何",
              "> 案例）。下面的表格按清单列出应有的格子，全部标记为「未跑」。", ""]
    L += render_summary_table(recs)
    L += [""] + render_arm_comparison(recs)
    L += render_process(recs)
    L += render_signals(recs)
    L += render_tool_usability(recs)
    L += render_accounting(recs)
    return "\n".join(L).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="ka1 knowledge-ablation report (Chinese markdown draft)")
    ap.add_argument("--lanes", default=",".join(LANES),
                    help="comma-separated lane names under <root>")
    ap.add_argument("--root", type=Path, default=CAMPAIGNS,
                    help="campaign workdir root (default workdir/campaigns)")
    ap.add_argument("--out", type=Path,
                    default=CAMPAIGNS / "KA1-ANALYSIS-draft.md")
    a = ap.parse_args(argv)
    lanes = tuple(s.strip() for s in a.lanes.split(",") if s.strip())
    recs = load_cases(lanes, root=a.root)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(render_report(recs), encoding="utf-8")
    n_started = sum(1 for r in recs if r["started"])
    n_graded = sum(1 for r in recs if r.get("graded"))
    n_mined = sum(1 for r in recs if r.get("mined"))
    print(f"{len(recs)} cell(s), {n_started} started, {n_graded} graded, "
          f"{n_mined} with logs -> {a.out}")
    if not n_started:
        print("nothing has run yet: every cell is rendered 未跑")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
