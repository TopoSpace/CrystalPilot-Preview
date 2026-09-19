---
symptom: Rint 高（>18% 触发 CheckCIF AB 警报），需在还原阶段而非精修阶段解决
alerts: [PLAT020]
tools: [APEX4, XPREP, SHELXT, PLATON-ADDSYM]
tags: [Rint, 数据还原, 对称性选择, 多run数据]
source:
  - https://www.matstr.com/forum.php?mod=viewthread&tid=2081  # 舍弃部分衍射图
  - https://www.matstr.com/forum.php?mod=viewthread&tid=2149  # 正确对称性还原
refs:
  - CheckCIF-Rint值触发警报的界限: https://mp.weixin.qq.com/s/AVTX98zdPSpyAwbtvZXlMA
---

## 案例 A（tid=2081）：多轮数据质量不均 → 舍弃坏轮

- 症状：Rint 19.51%（>18% AB 警报）；ins 里 HKLF 后带晶胞变换矩阵
  （曾按三斜还原再 PLATON 升群到 I4₁/acd，升群没有回到还原端重做）。
- 按轮分组统计（APEX4，rejection ratio 3.0）：Run1（360帧）17.88%、
  Run2（22帧）36.84%、fastscan（180帧）31.31%；混合还原 22.71%。
- 调低 |I-⟨I⟩|/su rejection ratio（3→2→1）：坏轮 Rint 反而升高，
  **rejection 阈值救不了系统性差的轮次**。
- 解法：仅用 Run1 还原（整轮舍弃 Run2+fastscan）。

### 规则

- Rint 高先按 run/sweep 分组诊断，坏轮整体舍弃优于全局混合或调
  rejection；fastscan（定胞用）默认不进最终还原。
- 见到 HKLF 后带变换矩阵 = "低对称还原+事后升群"的标志，正确做法
  是回到还原端按正确 Bravais 格重新积分/缩放。

## 案例 B（tid=2149）：FOM 并列时的对称性选择

- Bravais FOM：Tetragonal I 0.86 / Ortho F 0.88 / Ortho I 0.83 /
  Mono C 0.94，都高，不可靠。
- 稳妥流程：先 Triclinic P 还原 → SHELXT 解出 P-1，Rint 13.96% →
  PLATON ADDSYM 提示可升 I4/mmm → 升群后重新按四方还原 Rint 20.41%
  （爆表）→ 证明赝对称：真对称性低于 metric 对称性。
- 判据：**升群后 Rint 显著恶化 = 该对称性是赝的**，退回低对称群。

### 规则

- 首测晶体对称性未知时按最低对称（Triclinic P）还原起步，用
  merge-Rint 对比裁决 Laue 群，FOM/metric 对称仅供参考。
- ADDSYM 的建议必须经"按新群重新还原/合并 → Rint 对比"验证，
  不是无条件采纳（CrystalPilot 已实现为 audit_reflection_data 的
  Laue-vs-triclinic 检查 + change_space_group 显式链路）。

## CrystalPilot 落地状态

- Laue 群 Rint 对比：已有（audit_reflection_data (b)）。
- 待做：DIALS 管线按 sweep 分组 Rint 统计与坏轮识别
  （scale 输出有 per-sweep 统计，可在 frames 工具汇总暴露）。
