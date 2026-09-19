# 自主精修评估报告 — frames_lcyst

生成时间：2026-08-29 04:44:09    最终节点：`n0031`（指标最新）

## 总评：**MOF 可接受**　诚实门：PASS

## 指标对比（人工参考 = SHELXL-2019/3 终稿）

| 指标 | Agent | 人工 | Δ |
|---|---|---|---|
| R1 (I>2σ) | 0.0426 | 0.0138 | 0.0288 |
| wR2 | 0.1206 | 0.0307 | 0.0899 |
| GooF | 0.987 | 1.13 | — |
| 参数/约束 | -1/0 | — | — |
| 残余密度 | None / None | — | — |

> 起点/参考须知：start = RAW diffraction frames (agent must reduce the data itself; no injected defects)
> 起点/参考须知：reference caveats: COD 1575356 was measured at 100 K (quantum-crystallography quality, R1 0.0138); the tutorial dataset's collection temperature is unrecorded - thermal cell differences are expected

## 结构匹配（emma vs 人工参考）

- 全原子召回 1.0，精确率 1.0；重原子 None；判定 solved=True

## 注入缺陷修复：0/0


## 化学合理性

- ADP：非氢 7 个，其中各向异性 7；问题：无
- 骑乘氢组：0（参考 None）
- 残余密度可接受：False
- Restraints：5 条（人工参考 0 条）

## 诚实门

- (a) 新增原子全部有密度支持：**PASS**（新增 11 个）
- (b) 裁决数字与引擎一致：**PASS**（裁决 0.0426 vs 引擎 0.0426）
- (c) 未解决问题如实披露：**PASS**（有未过检查项=True，unresolved=['最终 checkCIF：A=3、B=3、C=3，均已在 VALIDATION.md 逐条解释。', '无状态 SHELXL 复核返回 GooF=0.986；活动节点 n0031 保存的真实节点指标为 GooF=0.987。', 'PLATON 报告非标准同步辐射波长下的 μ 表值差异，以及本地环境无法调用 SHELXL 重建 FCF。']，confidence=high）

## checkCIF（评估器独立复跑本地 PLATON）

- 警报：A×3 · B×3 · C×3 · G×16；VALIDATION.md：有；未解释代码：无
- (d) 逐条警报解释：**PASS**；无阻止发表级的结构类 A 警报
  - A 197 Missing _cell_measurement_temperature Datum ....     Please 
  - A 198 Missing _diffrn_ambient_temperature   Datum ....     Please 
  - A 699 Missing _exptl_crystal_description Value .......     Please 
  - B 051 Mu(calc) and Mu(CIF) Ratio Differs from 1.0 by .       9.58 
  - B 196 No TEMP record and _measurement_temperature .NE.        293 
  - B 995 Can not Recreate .fcf from Embedded  .res & .hkl          ! 
  - C 053 Minimum Crystal Dimension Missing (or Error) ...     Please 
  - C 054 Medium  Crystal Dimension Missing (or Error) ...     Please 
  - C 055 Maximum Crystal Dimension Missing (or Error) ...     Please 

## 成本

- 工具调用总数：91；轮次：2；shell 命令：84；墙钟：2872.1 s；tokens（输入/输出）：19639994/83452

## Agent 最终裁决（output_schema）

```json
{
  "r1": 0.0426,
  "wr2": 0.1206,
  "goof": 0.987,
  "space_group": "P 21 21 21",
  "n_atoms": 14,
  "chemistry_ok": true,
  "defects_found": [
    {
      "description": "实验温度未记录。",
      "action": "从 Diamond I19 实验记录补充，不能猜测。"
    },
    {
      "description": "晶体形貌及三维尺寸未记录。",
      "action": "由实验人员补充安装记录。"
    },
    {
      "description": "0.59–0.58 Å 最高分辨率壳完整度仅 41.5%。",
      "action": "如需改善只能补采数据；当前已如实披露。"
    }
  ],
  "restraints_used": [
    "DFIX 0.8900 0.020 C4 H1X",
    "DFIX 0.8900 0.020 C4 H2X",
    "DFIX 0.8900 0.020 C4 H7X",
    "DFIX 0.9700 0.020 C6 H3X",
    "DFIX 0.9700 0.020 C6 H4X",
    "DFIX 0.9800 0.020 C5 H5X",
    "DFIX 1.2000 0.030 C1 H6X",
    "SIMU 0.005 0.010 C1 H6X"
  ],
  "shelxl_r1": 0.0426,
  "unresolved": [
    "最终 checkCIF：A=3、B=3、C=3，均已在 VALIDATION.md 逐条解释。",
    "无状态 SHELXL 复核返回 GooF=0.986；活动节点 n0031 保存的真实节点指标为 GooF=0.987。",
    "PLATON 报告非标准同步辐射波长下的 μ 表值差异，以及本地环境无法调用 SHELXL 重建 FCF。"
  ],
  "confidence": "high",
  "final_node": "n0031",
  "outputs_dir": "H:\\CrystalPilot\\workbench\\mvp-frames_lcyst\\CrystalPilot Results\\task_20260829_035613"
}
```
