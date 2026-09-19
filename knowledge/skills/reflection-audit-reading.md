---
name: reflection-audit-reading
description: audit_reflection_data 体检报告判读指南：重复观测 χ² 安静≠无孪晶；fcf 同 hkl 多 Fc² 值=TWIN/HKLF5 观测模型证据；Fo²≫Fc² 失配聚集在奇偶类/晶带=第二孪晶畴（该类消光违例不可作空间群证据）；弱中档 Fo²>Fc² 系统偏多=未建模贡献；R1>1.3×Rint 且>5%=数据病理可正当建议重测。R1/wR2 高居不下、或 audit 返回 twin_alarm 时读此卡。
alerts: []
tools: [audit_reflection_data, set_twin, check_symmetry, run_shelxl, scale_and_export]
tags: [反射数据, 体检, 孪晶, Rint, fcf 审计, 消光]
source: AGENTS v21 audit 判读段下沉；真实 Acta 审稿案例 CCDC 2416519（弱中档符号偏差判据）；p770 非切变孪晶边界实证；r12 CD-MOF |E²-1| 安静案例
confidence: high
created_by: mentor
---

# 反射数据体检判读

## 各项指标怎么读

- **重复观测一致性 χ²**：单晶格积分的孪晶数据 χ² 往往**安静**（重叠污染
  是一致的），安静≠无孪晶。孪晶怀疑要看别的征象。
- **当前 Laue 群 vs 三斜 R_int 对比**：当前群显著更差 → 对称性可能给高了。
- **twin_alarm (e)/(f)**：|E²−1| < 0.68（XPREP 警戒）与"度规对称阶数 >
  Laue 阶数"只针对（赝）缺面孪晶；非切变双晶格孪晶在此保持安静，靠帧阶段
  双晶格索引（max_lattices=2）/ TwinRotMat→HKLF5 处理。详见
  [[framework-twin-pseudosymmetry-alarm]]。
- **fcf 审计**：同一 hkl 的 Fc² 不单值 = 该模型用了 TWIN/HKLF5 观测模型
  （核对他人结构如何处理孪晶时的直接证据）。
- **Fo²≫Fc² 失配的聚集分析**：失配离群点集中在某个奇偶类/晶带 → 第二
  孪晶畴把强度折到该类上，**该类里的"消光违例"不可作为空间群证据**，
  先排查孪晶再降对称。

## 审稿人级两条统计（真实审稿案例提炼）

1. **弱/中强度档 Fo²>Fc² 系统性占多数**（健康≈50%）= 有未建模贡献抬高
   观测，典型是未建模孪晶畴或漏建溶剂。
2. **R1(obs) 明显高于 R_int**（>1.3× 且 R1>5%）= "R 高于数据质量预期"，
   指向数据病理而非噪声。孪晶律找不到且无帧可回溯时，"重新长晶重测"是
   正当建议，写进报告，不要硬精修到底。

## 使用时机

R1/wR2 高居不下先跑 audit_reflection_data：先排除数据侧原因（孪晶/错群/
截断）再改模型。高 R 且 Rint 不高另读 review-high-r-twin-suspicion。
