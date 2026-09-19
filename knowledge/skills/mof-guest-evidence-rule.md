---
name: mof-guest-evidence-rule
description: 孔内客体真实性三检验：①残余密度积分电子数 vs 该占有率假设下的期望电子数（数量级不符即证伪该假设）；②Uiso 固定后占有率自由精修的崩塌测试（逐原子读：跌到远低于工作假设=该假设不成立）；③撤限制稳定性测试（几何仅靠限制撑住=数据不支持）。三检验已程序化为 audit_guest_evidence（模型副本上只读跑全部三项，一次调用出证据面板）。附残差图 pareidolia 戒律与互证要求。往孔里建任何客体/溶剂前、或审稿质疑客体归属时读此卡。
alerts: []
tools: [audit_guest_evidence, integrate_difference_density, add_atoms_from_difference_map, interpret_peaks, model_disorder, run_shelxl, validate_structure, edit_atoms]
tags: [客体, 残余密度, 过拟合, 占有率, 证据纪律, 无序]
source: Poręba, Macchi & Ernst, Nat Commun 13 (2022) 5288 (https://www.nature.com/articles/s41467-022-32890-0)；Wang et al. 答复 (https://www.nature.com/articles/s41467-022-32891-z)；Ramadhar, Zheng, Chen & Clardy, Acta Cryst. A71 (2015) 46-58 (https://journals.iucr.org/a/issues/2015/01/00/pc5042/)；晶体海绵法更新 IUCrJ 3 (2016) 139 (https://journals.iucr.org/m/issues/2016/02/00/de5035/)；Canossa, CrystEngComm 2025, 27, 6556
confidence: high
created_by: researcher
---

# 客体证据三检验

## 背景判例（BUT-17@二噁英，Nat Commun Matters Arising）

发表结构声称 6 个满占客体（应 ~768 e⁻），实测通道残余密度全胞积分仅
~3 e⁻；Uiso 固定到配体水平后客体占有率自由精修跌到 ≤1%；客体几何仅靠
restraints 撑住，撤掉即散架。原作者答复承认原数据不足，靠新数据+¹H NMR
重立结论。，"模型能收敛"与"数据支持它"是两回事。

## 三检验（建客体前后各跑一遍；audit_guest_evidence 一次调用跑全三项）

工具 audit_guest_evidence 在模型副本上只读执行下述三项并给证据面板
（atoms=客体原子标签、expected_formula=声称的身份）；mask 激活时它会
拒跑检验 2/3 - mask 与建模客体互斥，先二选一。手工逐项时按下述规程。

1. **电子数积分检验**：候选客体区域残余密度积分电子数 vs 化学式期望
   电子数，数量级必须相符。差 1-2 个数量级 = 直接证伪，不必进入精修。
   平台工具：`integrate_difference_density`（建前用 site_frac 测空位残差；
   建后用 labels 做 omit 积分对照 modeled_electrons_omitted 与
   expected_electrons，正负两半分开报告）。
2. **占有率崩塌检验**：把客体原子 Uiso 固定到框架配体同水平，放开占有率
   自由精修。判词按**工作占有率假设**和数据分辨率读，不用固定百分比：
   声称满占的客体精修到百分位，说明"满占"这个假设不成立；声称 0.1 占有
   的客体精修到 0.08，说明数据在这个量级上是支持它的。逐原子看
   audit_guest_evidence 的 per_atom 表（每个原子的 occ_start → occ_refined、
   是否钉在 0 或 1 的边界），任一原子钉边界或整组跨两栏就是 inconclusive，
   不看均值。低分辨率（d_min 明显粗于 1 Å）下占有率与 Uiso 强相关，单靠
   这一项不下结论。
3. **限制依赖检验**：撤掉客体几何限制再精修数轮。几何立刻崩坏/原子飞散 =
   客体形状是限制画出来的，不是数据给的。

## 低占有率客体：先问"在任何占有率下有没有"（pa3 教训，2026-09-03）

- **满占有电子数不是尺子。** 数据钉住的是 occupancy × Z：0.125 占有的
  Br 只有 4.4 e，0.25 占有的 Cl 只有 4.3 e，用 35 e 去量 3.5 e 的峰然后
  写"不存在"，是把问题问错了。pa3 的 agent 自己都写了"占有率 0.1 仍有
  可能"，却没有任何动作把这句话变成检验。
- 正确问法是 `probe_site(element|elements, site|peak|near_atom)`：在诊断
  分支上把该原子放到位点，占有率与 Uiso 自由精修（先只放开占有率、再放
  开位点/Uiso、最后全自由，与参考同口径），读 occupancy×Z、Uiso 是否
  物理、ΔR1/ΔwR2、位点残差前后与位点漂移，给 supported / not_supported /
  borderline；expected_electrons_at_occupancy 表按该元素任意 Z 给出。
  差值峰表的 `chem_hint`（端基 O 旁 1.15–1.65 Å 的羧酸/甲酸 C 候选、金属旁
  1.9–2.6 Å 的配体给体）先照它去建，再用 probe_site 验证。
- **掩膜之后找不到客体不是"不存在"**：掩膜一旦存入，差值图按 Fc + F_mask
  计算，空腔内的密度按构造被吸收。找客体必须用掩膜前的差值图：
  probe_site 与 `integrate_difference_density(mask='auto')` 在位点落入
  掩膜空腔时自动关掩膜并在 mask_handling 里说明；在有掩膜的节点上用
  inspect_map 找客体、没找到就写"无客体"，是方法错误。
- 找到了要给身份：probe_site 说 supported 的原子走本卡三检验与
  [[mof-solvent-mask-discipline]] 的建模/掩膜二选一；被 ghost_test 判 real
  的原子同理（见 difference-peak-reading 卡的三档判词）。

## 残差判读戒律

- 残差图**必须同看正负两半**；只展示正密度须声明。正负密度分布与幅度
  相当 = 结构无关噪音，不得脑补成原子（pareidolia/确认偏误）。
- 高残余密度的备择解释先排除：吸收校正差、Fourier 截断误差、辐照损伤
  （常堆积在特殊位置与重原子旁）。
- 为压 R 把孔内孤立密度安成水氧 = 过拟合。任何"水"要有氢键网络/化学
  证据（必要时 TGA/EA），R 下降不构成证据。

## 环形客体特别警告（晶体海绵指南）

目标客体含环己基/芳环时，低占有/差数据下与残余溶剂难以区分，滥用硬
限制会"用溶剂密度画出想要的客体"。处置：提高占有率（浸泡条件逐样优化，
>50% 为宜，顺带避开赝对称）；**并行建模晶格溶剂**改善相位、降低客体所
需限制。

## 高对称群提醒

弱主客作用 + 高对称空间群强加的对称无序，本就使客体常呈部分/随机分布
，建不出有序客体是物理，不是失败；如实报告优于硬画。
