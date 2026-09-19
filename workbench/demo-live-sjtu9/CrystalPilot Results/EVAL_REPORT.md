# 自主精修评估报告 — sjtu9

生成时间：2026-08-29 04:18:11    最终节点：`n0014`（指标最新）

## 总评：**发表级**　诚实门：PASS

## 指标对比（人工参考 = SHELXL-2019/3 终稿）

| 指标 | Agent | 人工 | Δ |
|---|---|---|---|
| R1 (I>2σ) | 0.0614 | 0.0617 | -0.0003 |
| wR2 | 0.1993 | 0.2048 | -0.0055 |
| GooF | 1.002 | 1.062 | — |
| 参数/约束 | 126/0 | — | — |
| 残余密度 | 0.9 / -1.27 | — | — |

> 起点/参考须知：H stripped
> 起点/参考须知：all ADPs isotropic U=0.05
> 起点/参考须知：WGHT reset

## 结构匹配（emma vs 人工参考）

- 全原子召回 1.0，精确率 1.0；重原子 1.0；判定 solved=True

## 注入缺陷修复：3/3

- `D1_element`: ✅ 已修复 ({"nearest_A": 0.0})
- `D2_ligand_break`: ✅ 已修复 ({"distances_A": [0.006, 0.007]})
- `D3_node_incomplete`: ✅ 已修复 ({"distances_A": [0.002]})

## 化学合理性

- ADP：非氢 16 个，其中各向异性 16；问题：无
- 骑乘氢组：5（参考 5）
- 残余密度可接受：True
- Restraints：0 条（人工参考 0 条）

## 诚实门

- (a) 新增原子全部有密度支持：**PASS**（新增 4 个）

## checkCIF（评估器独立复跑本地 PLATON）

- 警报：A×6 · B×4 · C×8 · G×16；VALIDATION.md：有；未解释代码：无
- (d) 逐条警报解释：**PASS**；无阻止发表级的结构类 A 警报
  - A 183 Missing _cell_measurement_reflns_used Value ....     Please 
  - A 184 Missing _cell_measurement_theta_min Value ......     Please 
  - A 185 Missing _cell_measurement_theta_max Value ......     Please 
  - A 197 Missing _cell_measurement_temperature Datum ....     Please 
  - A 198 Missing _diffrn_ambient_temperature   Datum ....     Please 
  - A 699 Missing _exptl_crystal_description Value .......     Please 
  - B 196 No TEMP record and _measurement_temperature .NE.        293 
  - B 242 Low    'MainMol' Ueq as Compared to Neighbors of       Zr02 
  - B 780 Coordinates do not Form a Properly Connected Set     Please 
  - B 995 Can not Recreate .fcf from Embedded  .res & .hkl          ! 
  - C 052 Info on Absorption Correction Method   Not Given     Please 
  - C 053 Minimum Crystal Dimension Missing (or Error) ...     Please 
  - C 054 Medium  Crystal Dimension Missing (or Error) ...     Please 
  - C 055 Maximum Crystal Dimension Missing (or Error) ...     Please 
  - C 213 Atom O007            has ADP max/min Ratio .....        3.2 
  - C 220 NonSolvent   Resd 1  O   Ueq(max)/Ueq(min) Range        3.7 
  - C 241 High   'MainMol' Ueq as Compared to Neighbors of       O006 
  - C 250 Large U3/U1 Ratio for <U(i,j)> Tensor(Resd    1)        2.2 

## 成本

- 工具调用总数：56；轮次：?；shell 命令：?；墙钟：? s；tokens（输入/输出）：?/?
