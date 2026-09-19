---
name: mof-data-collection-bottomline
description: 框架晶体数据端底线与温度反常判据：sinθ/λ≥0.6（0.84 Å）+ 完整度≈100% 的 IUCr 硬线；MoO≥5-7、I/σ≥8-10、Rint<10% 的健康值；外壳判噪靠壳层多证据（CC1/2、I/σ、Rint/Rmeas、完整度）同向+截前后对照，I/σ≈2.0、Rint≈0.45 仅为证据锚点；对称性存疑按三斜算策略；高孔隙 MOF 低温可能反而更差（Yaghi 反常），衍射差先变温筛查再放弃。评估新数据集、规划采集建议、或答辩分辨率/温度质疑时读此卡。
alerts: [THETM01, PLAT023, PLAT029]
tools: [ingest_vendor_data, audit_reflection_data, estimate_resolution, import_frames, integrate_frames, scale_and_export, set_experiment]
tags: [数据质量, 完整度, 冗余, 分辨率, 采集温度, 弱衍射]
source: IUCr 投稿数据要求 (https://journals.iucr.org/services/cif/reqdata.html)；checkCIF THETM01/PLAT029 文档 (https://journals.iucr.org/services/cif/checking/THETM01.html, .../PLAT029.html)；Müller, Crystallogr. Rev. 15 (2009) §2 (https://web.mit.edu/pmueller/www/own_papers/suggestions.pdf)；Lee, Bürgi, Alshmimri & Yaghi, JACS 2018, 140, 8958 (doi:10.1021/jacs.8b05271，全文核对)；iScience 2021 (doi:10.1016/j.isci.2021.103425)；Canossa, CrystEngComm 2025, 27, 6556
confidence: high
created_by: researcher
---

# 框架数据端底线

## 硬底线（IUCr/checkCIF 口径）

- 分辨率：sin θmax/λ ≥ 0.6 Å⁻¹（≈0.84 Å；Mo θmax>25°，Cu >67°），该范围
  内**所有可测独立反射都要测**；theta_full 完整度≈1.0。触线警报：
  THETM01（S<0.55 A 级）、PLAT023、PLAT029。
- 数据/参数比 ≥8（非心）/10（中心对称）；不足时用限制补（见 restraint 卡），
  不是删参数硬凑。

## 健康值（专家经验域）

- 完整度 99-100% 可做到就做到；MoO（多取向真冗余）≥5-7、两位数更好；
  全集 I/σ ≥8-10；全程 Rint <10%。
- **弱反射不许在还原阶段按强度阈值丢弃**（对 F² 精修、SHELXT 判解、
  超胞识别都靠它们）。
- 外壳是否已成噪音是**多证据壳层判断，不是单阈值动作**：看壳层统计
  多项证据是否同向，CC1/2 崩塌、I/σ 低迷（审稿语料锚点 ≤2.0，另有
  3σ 口径）、Rint/Rmeas 发散（≥0.45 已属深度噪音区）、完整度骤降；
  `estimate_resolution` 建议值为 advisory only。证据同向才截，截前后
  用 scale_and_export 重导出对照合并统计，如实报告截断位置与理由
  （截断后触发的新警报加 VRF 解释）；证据不同向或仅单项孤立时保留
  数据并记录判断。
- 曝光取舍：完整集优先；宁短曝多帧攒冗余（数据质量+辐照损伤保险）。

## 策略假设

- 对称性存疑（框架常见赝对称/孪晶/多晶粒干扰自动定群）：**按三斜非心
  假设算采集策略**：对任何真实对称性都完整；自动策略在孪晶存在时常
  给出不完整方案。事后再合并到真 Laue 群，损失的只是时间。

## 温度判据（框架特有，反直觉）

- 默认仍是 100 K；但高孔隙+满客体 MOF 存在**实证反常**：MOF-1004/1005
  在 100 K 无法求解、290 K 反得原子分辨率；MOF-177、UiO-67 同趋势。
  机理：无序客体低温"顶住"柔性骨架诱发骨架无序（案例 100 K 晶胞缩 5.7%，
  收缩源于客体）；**抽空后的晶体无此反常**：效应属于客体-框架相互作用。
- 操作判据：高孔隙 MOF 低温探查帧高角弱/斑点弥散 → 变温筛查（200 K、
  250 K、290 K）再下结论；衍射差 ≠ 晶体差。评审质疑"为何室温测"时以此
  文献+实测对比作答。
- 失溶剂纪律：晶体在上机前**永不离开母液**（孔道溶剂挥发=晶格坍塌）；
  油封/毛细管快速转移。

## 存档纪律

- 原始帧必须保留（重积分/查数据病因的唯一凭据）；未合并反射数据随 CIF
  存档不删。
