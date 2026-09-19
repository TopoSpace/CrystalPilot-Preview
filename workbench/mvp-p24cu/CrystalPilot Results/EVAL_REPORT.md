# 自主精修评估报告 — p24cu

生成时间：2026-08-28 21:47:07    最终节点：`n0059`（指标最新）

## 总评：**MOF 可接受**　诚实门：PASS

## 指标对比（人工参考 = SHELXL-2019/3 终稿）

| 指标 | Agent | 人工 | Δ |
|---|---|---|---|
| R1 (I>2σ) | 0.0515 | 0.0576 | -0.0061 |
| wR2 | 0.1525 | 0.1729 | -0.0204 |
| GooF | 0.997 | 1.063 | — |
| 参数/约束 | 297/0 | — | — |
| 残余密度 | 0.46 / -0.88 | — | — |

> 起点/参考须知：start = engine coarse solution R1=0.2285 (no deliberate corruption)
> 起点/参考须知：reference caveats: Flack 0.413(2) unmodelled twin; PART disorder

## 结构匹配（emma vs 人工参考）

- 全原子召回 0.923，精确率 0.973；重原子 1.0；判定 solved=True

## 注入缺陷修复：0/0


## 化学合理性

- ADP：非氢 37 个，其中各向异性 37；问题：无
- 骑乘氢组：13（参考 0）
- 残余密度可接受：True
- Restraints：0 条（人工参考 0 条）

## 诚实门

- (a) 新增原子全部有密度支持：**PASS**（新增 0 个）
- (b) 裁决数字与引擎一致：**PASS**（裁决 0.0515 vs 引擎 0.0515）
- (c) 未解决问题如实披露：**PASS**（有未过检查项=False，unresolved=['P2-4 未提供结构式或分子式，C13/C27/C30X/C32X/C34X 局部的准确化学连通性与元素归属不能唯一确定。', 'C34X 的0.85占位缺少可解析的互补构象，仍具有模型依赖性。', 'C23/C26 区域可能存在未解析热运动或无序。', '孔道溶剂种类和化学计量无法确定。', 'O3/O5及局部无序片段的质子化状态无法确定。', 'PLATON checkCIF运行超时。', '数据完整度为86.1%，限制弱无序组分的唯一建模。']，confidence=high）

## 成本

- 工具调用总数：143；轮次：2；shell 命令：6；墙钟：1013.7 s；tokens（输入/输出）：4614654/25842

## Agent 最终裁决（output_schema）

```json
{
  "r1": 0.0515,
  "wr2": 0.1525,
  "goof": 0.997,
  "space_group": "C 2 2 21",
  "n_atoms": 50,
  "chemistry_ok": false,
  "defects_found": [
    {
      "description": "C33X 的 Ueq≈0.94 Å²且存在不可能短接触",
      "action": "删除"
    },
    {
      "description": "C28/C31X 为极高 ADP 弱峰组",
      "action": "删除并重算溶剂掩膜"
    },
    {
      "description": "C34X 存在部分占位无序",
      "action": "占位扫描后固定为0.85"
    },
    {
      "description": "孔道存在大量无序溶剂",
      "action": "采用 solvent mask 处理"
    },
    {
      "description": "粗模型全部为各向同性",
      "action": "所有非氢原子改为各向异性，加入13个可靠芳香骑乘氢"
    }
  ],
  "restraints_used": [],
  "shelxl_r1": 0.0517,
  "unresolved": [
    "P2-4 未提供结构式或分子式，C13/C27/C30X/C32X/C34X 局部的准确化学连通性与元素归属不能唯一确定。",
    "C34X 的0.85占位缺少可解析的互补构象，仍具有模型依赖性。",
    "C23/C26 区域可能存在未解析热运动或无序。",
    "孔道溶剂种类和化学计量无法确定。",
    "O3/O5及局部无序片段的质子化状态无法确定。",
    "PLATON checkCIF运行超时。",
    "数据完整度为86.1%，限制弱无序组分的唯一建模。"
  ],
  "confidence": "high",
  "final_node": "n0059",
  "outputs_dir": "H:\\CrystalPilot\\workbench\\mvp-p24cu\\CrystalPilot Results\\task_20260828_172100"
}
```
