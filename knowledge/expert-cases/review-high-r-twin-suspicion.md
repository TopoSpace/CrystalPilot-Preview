---
symptom: Rint 不高但 R1/wR2 偏高，审稿人依统计特征怀疑孪晶+无序
alerts: []
tools: [SHELXT, SHELXL, PART]
tags: [审稿意见, 孪晶判据, 无序, R因子, 重测决策]
source: https://www.matstr.com/forum.php?mod=viewthread&tid=2335
case: CCDC 2416519, Acta Cryst. 2025, C81, 82-92 (DOI 10.1107/S2053229625000282)
practice_data:
  - 论文PDF+CIF: https://pan.baidu.com/s/1NS4ReD4-J7H8jDWrROMTGA?pwd=yeye
  - 晶体数据: https://pan.baidu.com/s/1qSBeIJmxcJjttkIFORl6pg?pwd=g6p6
---

## 症状

投稿态 Rint = 5.25%，R1 = 7.28%，wR2 = 15.41% - Rint 尚可但 R 因子
明显偏高；C6-C10（环戊二烯基）位移椭球大且拉长。

## 审稿人的孪晶怀疑判据（原文，可实现为检测器）

1. 中、弱强度反射系统性 Fo² > Fc²；
2. 弱反射的 K 值（scale 组）偏大；
3. Rint 比"好晶体+简单结构"的预期略高；
4. **给定 Rint 的情况下 R 因子高于预期**（Rint 与 R1 失配）。
   → 通常指向孪晶；但审稿人试遍 SHELXT 提示的三种 Pca2₁ 变体也
   找不到孪晶律。

## 处理与结局

- Cp 环按 SHELXL 提示裂分（遮蔽/交错双取向无序）：R 稍降但仍高
  ，无序建模不是根因。
- **重新培养晶体重测**：Rint 3.26%，R1 3.34%，wR2 9.01%，返稿即收。
- 原始衍射照片未保留 → 无法回溯验证孪晶假设（教训：保留 frames）。

## 提炼规则

- "Rint 与 R1 失配"是独立于 CheckCIF 的一级诊断信号：Rint 好而 R 高
  ≠ 模型差，优先怀疑数据病理（孪晶/调制/错误对称性）。
- 无序建模只治椭球症状；若 R 不随之正常化，说明另有全局问题，
  不要靠堆 PART/约束硬压。
- 当孪晶律搜索失败且 frames 不可得时，"重新长晶重测"是正当解，
  agent 应把它作为正式建议输出（而不是硬精修到底）。
- 期刊档位影响判定：同样数据一般期刊能过，Acta 级别会被四条统计
  判据卡住，报告里按最严标准自检。
- CrystalPilot 落地：refine 完成后自动计算 (a) 弱/中反射 Fo²-Fc²
  符号偏差统计 (b) Rint/R1 比值，异常时提示孪晶检查
  （twin law 搜索 / PLATON TwinRotMat）。

## 原始审稿意见（英文关键句，供回复审稿人时引用风格）

> "The refinements show some features that give rise to suspicion:
> Fo2 > Fc2 for most of the reflections of medium or weak intensity;
> large K values for weak reflections; Rint a little larger than one
> would expect...; R factors higher than expected given Rint. These
> issues usually point towards a twinned crystal..."
