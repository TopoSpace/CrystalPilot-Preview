"""The one contract both sub-agent paths share (round-3 R7).

Two ways a read-only specialist can be consulted:

* the native Codex roles (``workbench/agent_roles/*.toml``, spawned by the
  main agent with ``spawn_agent`` at the delegation tier), and
* the nested ``consult_specialist`` MCP tool (``refine/tools_specialist.py``,
  a fresh Codex thread driven by the engine).

Both return the same verdict object and both are described by the same
specialty table, so a campaign can compare them and the UI can render either
verdict the same way. This module is a leaf: it imports nothing from the
workbench or the refine package, so either side can import it.
"""
from __future__ import annotations

from typing import Any

#: specialty -> role title + brief. The keys ARE the role file names under
#: workbench/agent_roles/ (tests pin that both directions agree).
SPECIALTIES: dict[str, dict[str, str]] = {
    "space_group": {
        "role": "空间群/对称性审计专家",
        "brief": ("审查当前空间群指认是否正确：用 check_symmetry 找模型服从但当前群缺失的"
                  "对称操作（过低对称），用 inspect_model/get_geometry 检查特殊位置与"
                  "近重复原子（过高对称的症状），必要时查看 list_nodes 历史。"),
    },
    "chemistry": {
        "role": "化学建模专家",
        "brief": ("以合成先验为假设、以密度为裁判，审查模型化学合理性：check_ligand 对照"
                  "配体 SMILES，get_geometry 核对键长键角是否化学可信（金属-配体距离、"
                  "芳环内距、质子化位点），inspect_model 看配位数/τ 指数/悬挂原子。"),
    },
    "density": {
        "role": "残余密度解读专家",
        "brief": ("解读差值密度：inspect_map 逐峰分析（峰高、环境、身份提示），判断哪些峰是"
                  "缺失原子/氢/无序拆分/溶剂/噪声，deep hole 是否指示元素过重或占位过高；"
                  "结合 get_geometry 验证假设的成键距离是否成立。"),
    },
    "validation": {
        "role": "结构验证/checkCIF 专家",
        "brief": ("发表前审计：run_checkcif 跑当前模型（只读允许），逐条判断 A/B/C 警报是"
                  "真结构问题还是元数据缺失，validate_structure/get_geometry 交叉验证；"
                  "给出哪些警报必须修、哪些解释即可、解释的证据是什么。"),
    },
    "refinement_strategy": {
        "role": "精修策略专家",
        "brief": ("从节点历史规划下一步：list_nodes/compare_nodes 看指标轨迹与分支，判断"
                  "当前瓶颈（权重、氢、溶剂、无序、数据质量），给出下一步最有价值的 2-3 个"
                  "行动及预期收益，并指出哪些操作是浪费。"),
    },
}

#: the verdict every specialist returns (JSON Schema; the nested tool
#: passes it as the turn's output_schema, the role files spell the same
#: five fields out in prose because a spawned role has no schema hook)
VERDICT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "assessment": {"type": "string",
                       "description": "对问题的直接回答（中文，含关键数字）"},
        "recommendation": {"type": "string",
                           "description": "建议主 agent 采取的具体行动"},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "evidence": {"type": "array", "items": {"type": "string"},
                     "description": "支撑证据，每条含工具来源与数字"},
        "risks": {"type": "array", "items": {"type": "string"},
                  "description": "该建议可能出错的方式"},
    },
    "required": ["assessment", "recommendation", "confidence", "evidence",
                 "risks"],
    "additionalProperties": False,
}

VERDICT_FIELDS: tuple[str, ...] = tuple(VERDICT_SCHEMA["required"])


def parse_verdict(text: str) -> dict[str, Any]:
    """A verdict from a specialist's final message: the JSON object when it
    is one, otherwise the text folded into `assessment` with low confidence
    and a recommendation that says so - never an exception, never a
    fabricated field."""
    import json

    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        data = None
    if isinstance(data, dict) and all(k in data for k in VERDICT_FIELDS):
        return {k: data[k] for k in VERDICT_FIELDS}
    return {"assessment": (text or "")[:2000],
            "recommendation": "(specialist did not return valid JSON - "
                              "treat as free-text advice)",
            "confidence": "low", "evidence": [], "risks": []}
