---
name: difference-peak-reading
description: 差值密度峰的化学判读速查：峰压原子上=元素太轻；U 异常小/大的含义；金属 1.8-2.4 Å 强峰=缺配位原子；芳环断口补环锚点；带 * 的对称邻居陷阱。inspect_map/inspect_model 观察后决定改模动作前读此卡。
alerts: []
tools: [inspect_map, inspect_model, check_ligand, edit_atoms, add_atoms_from_difference_map, fit_fragment]
tags: [差值密度, 峰判读, 元素改判, 鬼原子, 缺配体]
source: AGENTS v21 判读经验段下沉（r5-r12 战役实证：p770 元素改判、SJTU-9 配位 O、demo-live O6X 幽灵裁决）
confidence: high
created_by: mentor
---

# 差值峰化学判读

- **峰压在某原子上（<0.5 Å）且很强** → 该原子元素太轻：对照合成先验金属
  改判（edit_atoms reassign）。反向（深负峰压原子）= 元素太重或占有率过高。
- **原子 U 异常小** → 元素指认太轻；**U 异常大** → 鬼原子 / 元素太重 /
  未建模无序。删除裁决交给 `ghost_test(atoms)`（删→精修→看 ΔR1 与回峰，
  基线自动恢复），判词只有三档：**ghost = 唯一的删除许可**；**real** =
  密度真实，命名（客体/溶剂/抗衡离子/无序组分/缺失骨架原子）、放开占有率
  精修（element_scan free_occupancy / probe_site）、或交给掩膜时带
  `acknowledge_real={labels, reason}` 删除，绝不静默删；**inconclusive** =
  暂留，模型更完整（掩膜/元素/ADP）后复测，不是删除许可。每行的
  `expected_delta_r1_if_real` / `r1_fence_informative` 说明 ΔR1 栅栏在当前
  模型上有无判别力：高 R1、无掩膜大空洞、轻/部分占有的原子本来就动不了
  R1 0.002，那时判词只看回峰，"ΔR1 小"不是鬼的证据。带 `+` 成组判 real 的
  成员不能凭单点复测逐个删。real 判词记入项目台账（ghost_ledger.json），
  之后 edit_atoms 删它会被拒绝并列出证据与三条出路。
- **金属 1.8–2.4 Å 处的强峰** → 缺失的配位 O/N（对照 inspect_model 的
  配位数与 τ 指数）。
- **芳环断口（悬挂 C）且峰在环位** → 配体断裂：用 check_ligand 的
  mapped_pairs 做 fit_fragment 锚点补环。fit_fragment 拒绝=密度不支持，
  不许调低 min_density 硬塞。
- **带 `*` 的邻居是对称生成的**: "缺失"原子可能由对称性提供，先看差值
  图再补，别重复建对称像。
- 孔道里的弥散峰群：先试离散溶剂建模，确实弥散才掩膜，读
  [[mof-solvent-mask-discipline]] 与 [[mof-guest-evidence-rule]]（建前
  建后用 integrate_difference_density 电子数检验）。
