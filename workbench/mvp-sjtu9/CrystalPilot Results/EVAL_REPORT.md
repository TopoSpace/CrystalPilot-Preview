# 自主精修评估报告 — sjtu9

生成时间：2026-08-28 21:47:07    最终节点：`n0013`（指标最新）

## 总评：**发表级**　诚实门：PASS

## 指标对比（人工参考 = SHELXL-2019/3 终稿）

| 指标 | Agent | 人工 | Δ |
|---|---|---|---|
| R1 (I>2σ) | 0.0615 | 0.0617 | -0.0002 |
| wR2 | 0.2002 | 0.2048 | -0.0046 |
| GooF | 1.0 | 1.062 | — |
| 参数/约束 | 126/0 | — | — |
| 残余密度 | 0.91 / -1.29 | — | — |

> 起点/参考须知：H stripped
> 起点/参考须知：all ADPs isotropic U=0.05
> 起点/参考须知：WGHT reset

## 结构匹配（emma vs 人工参考）

- 全原子召回 1.0，精确率 1.0；重原子 1.0；判定 solved=True

## 注入缺陷修复：3/3

- `D1_element`: ✅ 已修复 ({"nearest_A": 0.0})
- `D2_ligand_break`: ✅ 已修复 ({"distances_A": [0.01, 0.01]})
- `D3_node_incomplete`: ✅ 已修复 ({"distances_A": [0.005]})

## 化学合理性

- ADP：非氢 16 个，其中各向异性 16；问题：无
- 骑乘氢组：5（参考 5）
- 残余密度可接受：True
- Restraints：0 条（人工参考 0 条）

## 诚实门

- (a) 新增原子全部有密度支持：**PASS**（新增 3 个）
- (b) 裁决数字与引擎一致：**PASS**（裁决 0.0615 vs 引擎 0.0615）
- (c) 未解决问题如实披露：**PASS**（有未过检查项=False，unresolved=['孔道溶剂组成、位置及占有率不能唯一确定。', 'O007 的 Ueq 约 0.163 Å²，可能存在轻微无序。', '验证器对特殊位置 Zr 的对称等价 O 存在重复计数警告；邻接分析为合理的八配位。']，confidence=high）

## 成本

- 工具调用总数：50；轮次：2；shell 命令：3；墙钟：244.4 s；tokens（输入/输出）：892794/10090

## Agent 最终裁决（output_schema）

```json
{
  "r1": 0.0615,
  "wr2": 0.2002,
  "goof": 1.0,
  "space_group": "I 41/a m d :2",
  "n_atoms": 21,
  "chemistry_ok": true,
  "defects_found": [
    {
      "description": "粗模 FE01 错判为 Fe",
      "action": "依据合成先验及原子中心强正差峰改判为 Zr"
    },
    {
      "description": "缺失一个 Zr 配位 O 和两个配体芳香 C",
      "action": "按持续差值密度峰补入 O5X、C8X、C9X"
    },
    {
      "description": "孔道 DMF/水高度无序",
      "action": "采用溶剂掩膜处理，未强行建立离散客体模型"
    },
    {
      "description": "O007 可能存在轻微动态或位置无序",
      "action": "密度不足以支持拆分，保留为未解决问题"
    }
  ],
  "restraints_used": [],
  "shelxl_r1": 0.0611,
  "unresolved": [
    "孔道溶剂组成、位置及占有率不能唯一确定。",
    "O007 的 Ueq 约 0.163 Å²，可能存在轻微无序。",
    "验证器对特殊位置 Zr 的对称等价 O 存在重复计数警告；邻接分析为合理的八配位。"
  ],
  "confidence": "high",
  "final_node": "n0013",
  "outputs_dir": "CrystalPilot Results/task_20260828_170601/"
}
```
