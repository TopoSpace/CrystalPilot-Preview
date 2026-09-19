---
name: counterion-solvent-signatures
description: 抗衡离子与常见小分子的几何签名速查（硝酸根/高氯酸根/BF4/羧酸根鉴别、NMP/DMF/DMSO/MeCN 骨架）+ "合成盐的阴离子必须在模型中找到或显式排除"的早期检查纪律。建模早期遇到无法归属的 3-5 原子片段、或合成配方含 M(NO3)x/MClO4 类盐时读此卡。
alerts: []
tools: [get_geometry, audit_element_assignment, validate_structure, integrate_difference_density, audit_guest_evidence, solvent_mask]
tags: [抗衡离子, 客体, 元素指认, 电荷平衡, 建模早期]
source: r14a 实弹（硝酸根被误诊"残缺 NMP"~25 min，09:38:50 由 checkCIF 几何模式触发顿悟，证据其实早在 get_geometry 输出里）；r22 知情臂硝酸根/客体化学推理；r19 羧酸根判读
confidence: high
created_by: mentor
---

## 纪律：阴离子记账先行

合成配方含金属盐（Cu(NO₃)₂、Zn(NO₃)₂、MClO₄…）时，**"阴离子去哪了"
是建模早期检查项，不是收尾疑问**：骨架电荷（金属价态 × 数目 − 去质子化
配体电荷）必须由抗衡离子、配位阴离子或质子化位点平衡。模型里找不到
阴离子的去向，就必须显式给出去向假设（掩膜孔道内？合成中被置换？）并
在 VALIDATION 披露，r14a 的教训是反着走的：先花 25 分钟把硝酸根碎片
硬拼成"残缺溶剂"，checkCIF 才兜底纠正。

## 几何签名速查（差图/粗模里 3-5 原子小片段先对这张表）

| 物种 | 签名 | 易混淆点 |
|---|---|---|
| 硝酸根 NO₃⁻ | 平面三角，中心原子 3×1.20-1.25 Å，O-N-O≈120° | 被误读成"残缺溶剂骨架"；中心是 N 不是 C（Ueq 邻居比＋键长联判） |
| 羧酸根 -CO₂⁻ | C 上两条 1.25-1.27 Å C–O + 一条 ~1.50 Å C–C | 与硝酸根的区别=有第三条 C–C 键；配位模式可单齿/螯合/桥连 |
| 高氯酸根 ClO₄⁻ | 四面体 4×1.42-1.45 Å，中心 Ueq 常显著小于 O | 常整体无序（绕三重轴旋转）；差图呈环带时先想它 |
| BF₄⁻ | 四面体 4×1.37-1.40 Å | 与 ClO₄ 靠中心电子密度区分（Cl≫B） |
| NMP/DMF | 酰胺 C=O 1.23 Å + C–N 1.34 Å 平面 + 烷基尾 | 残缺时只剩 3-4 原子，先排除阴离子再当溶剂拼 |
| DMSO | S 中心锥形，S=O 1.50 Å + 2×S–C 1.78 Å | S 的电子密度像 Cl；看配位（O 端配金属）与角度 |
| MeCN | 线性 C≡N 1.14 Å + C–C 1.45 Å | 线性三原子；勿在 N 上加 H |
| H₂O/OH⁻ | 孤立 O，看氢键网与 M–O 距离定质子化态 | 电荷平衡是 OH⁻ vs H₂O 的主判据之一 |

判读工具链：`get_geometry`（键长/角实测）→ `audit_element_assignment`
（Ueq-邻居比 + 受体环境）→ 占有率自由精修/删除对照。X 射线常分不出
C/N/O 单凭密度，**几何模式 + 电荷平衡 + 合成先验三线合裁**，证据不足
时如实披露而非硬判。

## 掩膜路线的记账义务

阴离子若归入掩膜（未建模），BYPASS 电子数必须与"阴离子 + 溶剂"的
化学假设对得上（NO₃⁻ 31 e、ClO₄⁻ 49 e、NMP 62 e…），并写进
_platon_squeeze_details / VALIDATION，电子数对不上的掩膜记账会被
审稿人一眼抓住（见 mof-solvent-mask-discipline 卡三分法）。
