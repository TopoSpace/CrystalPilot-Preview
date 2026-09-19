"""Build the pa1 prompt-ladder manifests.

The experiment varies ONE thing: how much the opening message tells the
agent. For that to mean anything the four levels have to be a strict
monotone ladder - L0 ⊂ L1 ⊂ L2 ⊂ L3, each a literal superset of the one
below - and identical in wording across the three crystals apart from the
data path. Hand-writing twelve briefs guarantees drift, so they are
composed here from shared fragments and the result is asserted to nest.

The one rule that keeps L3 honest: it adds SYNTHESIS-SIDE priors only -
what metal went into the flask, which ligand, what solvent, which
instrument. Never a structural conclusion: no space group, no cell, no
atom count, no formula, no R factor, no topology. The moment L3 carries a
structural answer it stops measuring prompt informativeness and starts
measuring answer leakage, and the whole ladder becomes meaningless.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DATA_ROOT = Path("H:/CrystalPilotData")
PROJECTS_ROOT = "H:/CrystalPilot/workbench/pa1"
SERVER = "http://127.0.0.1:8010/api"

# --------------------------------------------------------------- ladder text
L0 = """数据目录（只读）：{data_dir}

请解这个结构。"""

L1_ADD = """

交付要求：解出结构并精修到可交付，写出 CIF 与报告。
诚实优先：解不出、判不定的一律写 unresolved，不编造。这套数据的质量本身
可能限制能走多远，如果是那样，把证据摆出来说清楚，比硬凑一个好看的 R 值
有价值。"""

L2_ADD = """

**关于 start.ins**：它是求解程序的占位文件，不是模型；其中 LATT/SYMM 声明的
空间群只是还原程序的猜测，不可直接采信。

工作要求：
1) 冷启动摄入数据。定群前先 read_skill data-ingest-space-group-protocol，
   用系统消光与 E 统计自行判群（screen_space_groups 可在无原子会话上跑），
   把心/非心的判断依据写出来；不要因为 ins 里写着某个群就沿用。
2) 先跑 estimate_resolution 看逐壳层曲线，自己判断该在哪里截断，并说明判断
   依据（不要只看某一个指标过没过某条线）。截断与否都要记录理由。
3) 求解前后跑体检（audit_reflection_data / check_symmetry / situation_report），
   异常追到底并如实披露。
4) 若是非心群，Flack 判读读 read_skill flack-absolute-structure，必要时
   invert_structure。
5) 元素指认自己判断：不要预设有没有金属。重原子的存在与身份从数据出发
   （差值峰高度、配位几何、audit_element_assignment）；有孔道/溶剂时处置前读
   read_skill mof-solvent-mask-discipline 与 mof-guest-evidence-rule，每个
   溶剂/客体的归宿都要有差值密度证据链。
6) 收敛后 write_outputs + run_checkcif；VALIDATION.md 逐条解释 A/B/C，
   SUMMARY.md 写清每个关键决定链（截断/定群/求解/元素指认/建模/客体处置/
   未解决问题）。"""

L3_ADD = """

已知的合成与实验背景见项目根目录的 context.json（投料与仪器信息）。
注意：那里只有合成侧先验，结构本身（空间群、胞、组成、拓扑）仍然未知，
需要你完全从数据判断。"""

#: pa3 guest re-run (2026-09-02): the group's manual structure of the hex
#: crystal carries a post-synthetic guest the blind agents masked as
#: solvent. This paragraph tells the agent WHAT WENT INTO THE FLASK - the
#: modification reagent - and nothing about where it sits, its occupancy
#: or its binding mode; those are the things the run is meant to find.
GUEST_ADD = """

已知的样品背景：这批晶体是 Zr 基 MOF（Zr 源 + 四羧酸芘类配体 TBAPy 一类的
溶剂热产物）经**后合成修饰**得到的，修饰试剂是**对溴苯乙酸
（4-bromophenylacetic acid）**。数据所有者据此认为孔道内很可能存在对溴苯乙酸
（可能以羧酸/羧酸盐形式与 Zr 节点结合，也可能只是孔内客体），但这只是投料侧
信息：它是否真的在孔道里、占有率多少、朝向如何、与骨架怎样连接，需要你从
差值密度出发核实（read_skill mof-guest-evidence-rule），并在 SUMMARY 里给出
证据链，"找不到"同样是一个需要证据的结论。Br 是重原子，元素指认时把它的
异常散射一并考虑。"""

ARMS = ["L0", "L1", "L2", "L3"]


def brief_for(level: str) -> str:
    """The ladder, composed so the nesting is structural, not editorial."""
    text = L0
    if level in ("L1", "L2", "L3"):
        text += L1_ADD
    if level in ("L2", "L3"):
        text += L2_ADD
    if level == "L3":
        text += L3_ADD
    return text


# ------------------------------------------------------------------ crystals
#: `context` is written to context.json and is L3-ONLY. Every entry is a
#: charge-side fact a chemist would have from their own notebook before any
#: diffraction happened. Positive facts ONLY - the "and the structure
#: itself is still unknown" framing lives in the brief (L3_ADD), because a
#: disclaimer that enumerates which structural facts are unknown is itself
#: a hint about what to go looking for, and it makes the no-structural-
#: content rule impossible to check mechanically.
CRYSTALS: dict[str, dict[str, Any]] = {
    "hex": {
        "data_dir": "H:/CrystalPilotData/staging/r25a",
        # the group's manual final structure (2026-09-02): NU-1000 with a
        # post-synthetic guest in the pores. Before that the reference was
        # CrystalPilot's own r25 solution (refs/nu1000_r25_agent.res).
        "reference": "H:/CrystalPilotData/refs/nu1000_034a1_manual.cif",
        "reference_kind": "literature",
        "case_timeout_s": 14400,
        "context": {
            "experiment": {"instrument": {
                "source": "同步辐射 lambda = 0.68883 A"}},
            "chemistry": {"note":
                "课题组样品。数据所有者确认投料体系为 Zr 源 + 四羧酸芘类"
                "有机配体（TBAPy 一类）的溶剂热反应；反应体系中的金属只有"
                "Zr。溶剂/客体种类没有记录。"},
        },
    },
    "cu": {
        "data_dir": "H:/CrystalPilotData/staging/r22a",
        "reference": "H:/CrystalPilotData/refs/nu1200cu_expert.cif",
        "reference_kind": "literature",
        "case_timeout_s": 14400,
        "context": {
            "experiment": {
                "instrument": {"diffractometer":
                               "single-crystal diffractometer, Cu K-alpha",
                               "source": "Cu, 1.54178 A"},
                "temperature_K": 173.0,
                "crystal": {"colour": "green"}},
            "chemistry": {"note":
                "真实科研样品（非教学案例）。合成：Cu(NO3)2 与三齿羧酸配体 "
                "4,4',4''-(2,4,6-三甲基苯-1,3,5-三基)三苯甲酸（中心苯环 "
                "1,3,5 位三个甲基、2,4,6 位三个 4-羧基苯基臂）溶剂热反应所得"
                "绿色晶体。反应体系中的金属只有 Cu；N 可能来自硝酸根或溶剂"
                "分子；溶剂/客体种类没有记录。"},
        },
    },
    "cage": {
        # junction-masked: the real directory name is a searchable sample id
        "data_alias": {"link": "H:/CrystalPilotData/staging/pa1c-link",
                       "target": "H:/CrystalPilotData/staging/pa1c"},
        "reference": "H:/CrystalPilotData/refs/t2_2_cage_zjj1174a1.cif",
        "reference_kind": "literature",
        "case_timeout_s": 18000,   # 45835 uniq, 73.6% complete, hard
        "context": {
            "experiment": {"instrument": {
                "source": "同步辐射 lambda = 0.68883 A"}},
            "chemistry": {"note":
                "课题组样品。投料体系为 Zr 源 + 羧酸配体，反应与后处理使用"
                "含氯溶剂（二氯甲烷/氯仿一类）。反应体系中的金属只有 Zr。"
                "客体种类没有记录。"},
        },
    },
}

#: one lane per manifest: three runner processes, three independent
#: state.json files, and resume/`--only` for free
LANES: list[tuple[str, list[tuple[str, str, int]]]] = [
    # (campaign name, [(crystal, arm, replicate)])
    ("pa1-hex", [("hex", a, r) for r in (1, 2) for a in ARMS]),
    ("pa1-cu", [("cu", a, 1) for a in ARMS]),
    ("pa1-cage", [("cage", a, 1) for a in ARMS]),
]


def build_case(crystal: str, arm: str, rep: int) -> dict[str, Any]:
    spec = CRYSTALS[crystal]
    case: dict[str, Any] = {
        "name": f"{crystal}-{arm.lower()}-r{rep}",
        "crystal": crystal,
        "arm": arm,
        "replicate": rep,
        "reference": spec["reference"],
        "reference_kind": spec["reference_kind"],
        "case_timeout_s": spec["case_timeout_s"],
        "brief": brief_for(arm),
        "followups": [],
    }
    if "data_alias" in spec:
        case["data_alias"] = spec["data_alias"]
    else:
        case["data_dir"] = spec["data_dir"]
    # context.json is the L3 variable: L0-L2 get no file at all
    if arm == "L3":
        case["context"] = spec["context"]
    return case


#: pa2 = the same crystals on the FIXED tool surface (PA1-FINAL-ANALYSIS
#: §10 landed, tag pa1-fixes-v1). Prompt level is not a lever (pa1), so
#: only the bare (L0) and scaffolded (L2) arms run, two replicates each,
#: against the pa1 baselines of the same arms. cage is split into two
#: lanes so its 5 h cells overlap instead of queueing.
REGRESSION_LANES: list[tuple[str, list[tuple[str, str, int]]]] = [
    ("pa2-hex", [("hex", a, r) for r in (1, 2) for a in ("L2", "L0")]),
    ("pa2-cage1", [("cage", "L2", 1), ("cage", "L0", 1)]),
    ("pa2-cage2", [("cage", "L2", 2), ("cage", "L0", 2)]),
]


def _manifest(name: str, cells: list[tuple[str, str, int]],
              projects_root: str, design: str,
              anonymize: bool = True) -> dict[str, Any]:
    return {
        "campaign": name,
        "server": SERVER,
        "projects_root": projects_root,
        "defaults": {"permission_mode": "auto", "case_timeout_s": 14400,
                     # the project folder is the agent's cwd: pa1's
                     # `cu-l0-r2` names were cited as the Cu prior by
                     # four "blind" runs. pa1 itself ran with plain names
                     # (workbench/pa1/<case>) - its manifests must keep
                     # them or a --regrade looks in the wrong folder
                     "anonymize_projects": anonymize},
        "_experiment": {
            "design": design,
            "l3_rule": "context.json carries synthesis-side priors only "
                       "(metal charged, ligand, solvent, instrument); "
                       "never a structural conclusion",
            "lane": name,
        },
        "cases": [build_case(c, a, r) for c, a, r in cells],
    }


def build_all() -> dict[str, dict[str, Any]]:
    return {name: _manifest(name, cells, PROJECTS_ROOT,
                            "prompt-informativeness ladder, L0 subset of "
                            "L1 subset of L2 subset of L3",
                            anonymize=False)
            for name, cells in LANES}


def build_regression(projects_root: str = PROJECTS_ROOT.replace("pa1", "pa2")
                     ) -> dict[str, dict[str, Any]]:
    return {name: _manifest(name, cells, projects_root,
                            "pa2 regression on the fixed tool surface "
                            "(pa1-fixes-v1): same data and briefs as pa1, "
                            "arms L0 and L2 x 2 replicates, compared with "
                            "the pa1 cells of the same arm")
            for name, cells in REGRESSION_LANES}


def build_guest_rerun(projects_root: str = PROJECTS_ROOT.replace("pa1", "pa3")
                      ) -> dict[str, dict[str, Any]]:
    """pa3: the hex crystal once more, L2 scaffold + the guest paragraph,
    with the synthesis-side context.json (the modification reagent is a
    charge-side fact and goes there too)."""
    case = build_case("hex", "L2", 1)
    case["name"] = "hex-l2g-r1"
    case["arm"] = "L2G"
    case["brief"] = brief_for("L2") + GUEST_ADD
    ctx = json.loads(json.dumps(CRYSTALS["hex"]["context"]))
    ctx["chemistry"]["note"] += (
        "晶体经后合成修饰：修饰试剂为对溴苯乙酸（4-bromophenylacetic acid）；"
        "修饰产物在孔道内的存在与否、位置和占有率均未知。")
    case["context"] = ctx
    man = _manifest("pa3-hex-guest", [], projects_root,
                    "pa3 guest re-run: hex data with the L2 scaffold plus "
                    "the post-synthetic-modification reagent stated in the "
                    "brief and context.json; compared atom by atom with the "
                    "group's manual structure (mentor side only)")
    man["cases"] = [case]
    return {"pa3-hex-guest": man}


def write_all(dest: Path = DATA_ROOT / "campaigns",
              regression: bool = False, guest: bool = False) -> list[Path]:
    paths = []
    mans = (build_guest_rerun() if guest else
            build_regression() if regression else build_all())
    for name, man in mans.items():
        p = dest / f"{name}.json"
        p.write_text(json.dumps(man, ensure_ascii=False, indent=2),
                     encoding="utf-8")
        paths.append(p)
    return paths


if __name__ == "__main__":  # pragma: no cover
    import sys
    for p in write_all(regression="--regression" in sys.argv,
                       guest="--guest" in sys.argv):
        print(p)
