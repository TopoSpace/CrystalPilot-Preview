---
name: review-response-ruleset
description: 晶体学审稿意见应对规则集（75 条）：每条 = 审稿触发模式 → 必做动作/回复策略 → 数值阈值 → 论坛出处 tid。覆盖 R 因子质疑、分辨率截断、无序/孪晶点名、溶剂遮掩披露、CheckCIF 警报回应（VRF）、CIF/论文一致性、氢原子与标签规范、空间群争议等。写 VALIDATION.md 与审稿回复前先查此集。
alerts: [PLAT080, PLAT084, PLAT090, PLAT196, PLAT213, PLAT220, PLAT230, PLAT232, PLAT241, PLAT242, PLAT244, PLAT250, PLAT302, PLAT304, PLAT340, PLAT342, PLAT415, PLAT430, PLAT910, PLAT911, PLAT971, PLAT972, PLAT987, THETM01]
tools: [run_checkcif, write_outputs, audit_reflection_data, estimate_resolution, model_disorder, set_twin, set_restraints, solvent_mask, run_shelxl, set_experiment, rename_atoms, add_hydrogens]
tags: [审稿, 回复策略, checkCIF, VRF, 分辨率截断, 无序, 孪晶, 溶剂遮掩, 数据诚实]
source: matstr.com DJ_Tokyo「审稿意见」系列 160 帖全量精读（2026-08-30，两路子代理草稿 A1-A34/B1-B41 + 导师精编）；实读提炼 72 帖，跳过 84 帖（网盘存根/图片意见，名单见附录），逐条 tid 可溯
confidence: high
created_by: mentor+subagents
---

# 晶体学审稿意见应对规则集

**用法**：收到审稿意见/写 VALIDATION.md 时，先在"主题索引"定位，再读对应规则；
每条规则的出处 tid 对应 `matstr/threads/<日期>_<tid>_*/post.md` 原帖。
铁律：只收语料真实说过的内容；帖间分歧在"导师裁决"统一定调；
规则编号 A*（前 80 帖草稿）/B*（后 80 帖草稿）保持稳定可引用。

## 主题索引（跨 A/B 合并）

| 主题 | 规则 |
|---|---|
| 结构参数报告（s.u./IUCr 建议 12/θ-2θ） | A1 A2 A3 A4；温度 s.u. B35 |
| R 因子偏高应对链 | A5 A6 A7 A8 A9；消光 B40；孪晶排查 A22 B25 |
| 分辨率截断/真实分辨率/删点纪律 | A19 A20 A21 B26 B37；OMIT 红线 B8 B30(二审) A8-3 |
| 无序建模被点名 | A12 A14 A24 B9 B11 B13 B21 B23 B28 B41；机制分组 B41 |
| 溶剂：遮掩披露/建模/占有率 | A10 B3 B5 B6 B15；来路不明水 A15 B9 |
| 重原子旁高残余峰归因 | B7 B19 B30 B41 + 裁决⑦排除顺序 |
| CheckCIF 警报回应（VRF） | A23 A25 B20 B22 B34；单码成例 PLAT220=B22 241/250=B23 415/414=B24 430=B20 987=B25 |
| CIF/论文/CCDC 一致性 | A11 A16 A17 A18 A30 B18 B31 B32 B33 B36 B38 B39 |
| 氢原子处理与描述 | A27 B1 B14 B24 B27 |
| 原子标签/排序 | B16（A12 的游离原子同根） |
| 限制/约束纪律 | A13 A14 B11 B14 B28 B29 |
| 空间群争议 | A32 A33 A22 |
| 测试条件（温度等） | A34 B35 B38 |
| SI/正文描述义务 | A26 A27 A28 A29 B2 B29 |
| 孪晶 | A5 A22 B12 B25 B41 |

## 导师裁决（语料分歧的统一定调）

1. **I/σ 截断阈值 2 vs 3**：审稿人惯用"低于 3σ 即噪音"的话语（987/1004/1166/1878），
   实操按 I/σ(I)≥2 截断被多个期刊接受（1004/1878/2344 明言"高于 2.0 为有效数据"）。
   定调：**2.0/3.0 都是语料证据锚点，不是动作触发线**：截断决定看壳层多证据
   （I/σ、Rint/Rmeas、CC1/2、完整度）是否同向并做截前后对照，披露所用标准与
   理由；回复话语可引审稿人的 3σ 判据。禁止一刀切（"钼靶必截 0.77 Å"类），
   极限分辨率因晶体而异（B26）。
2. **截断手段**：有原始帧时**优先重新积分**（1202/1878 审稿人明确偏好，还能改善
   Rint）；只有成品 hkl 时 SHEL/OMIT 可用但必须在实验部分披露（1099 案 SHEL 过审）。
   CrystalPilot 对应：帧路线走 estimate_resolution（advisory only）+ scale_and_export
   重导出；SHEL/OMIT 为 SHELXL 指令、当前 run_shelxl 不暴露对应参数，vendor hkl
   路线的精修端截断属外部能力（需人工执行），做与否连同壳层证据写进 VALIDATION。
3. **删点 vs 完整度**：双向纪律（B37+B8 合并），**不弃有效数据（被弃区间 I/σ≥2
   占比高即不可弃），不留纯噪音；单点删除须有束挡遮挡类可查证的测量事故理由并
   逐点披露**（"限 1-2 个"是 B8 审稿话语中的案例锚点 tid 1586，非通用许可额度；
   需删更多时先怀疑数据本身有病，按 B8 对症处理）。宁可 R 略高也还回完整度（A8-3）。
4. **Z/分子式基准**：与论文对结构的讨论方式一致，优先级高于 checkCIF 计算/报告
   一致（A16）；但遇审稿人明确改判则从审稿意见。**适用边界**：此容忍仅限"式单位
   取几倍"的记账口径差（晶胞真实内容不变）；密度/F000/分子量/吸收系数等物理
   导出量仍必须与晶胞实际内容自洽（含被遮掩溶剂，A10 与 mof-solvent-mask-
   discipline 卡同口径），不得借此放过真实的内容缺漏。
5. **空间群改判（审稿人主张升/降/换群）**：不盲从也不空口反驳，在两种设定下
   **实算**（收敛性、Flack、无序是否消失），必要时重测新数据，以实算结果+新证据
   回复（A32/A33 两案均以此推翻审稿人主张）。
6. **遮掩 vs 建模**："能认出形状的建模、认不出的才遮、配位的绝不遮"（B6/B9/1536
   合并）；程序无定规（SQUEEZE/Solvent Mask 均可）但**披露是硬规**：种类+数量+
   计入分子式+引 Spek 2015 正式文献（B5/B15/A10）；审稿人点名用哪个就用哪个。
7. **重原子旁大峰的归因排除顺序**（导师归纳的元规则，语料只有分立案例
   B7/B19/B30/B41/裁决记录，无统一判定树，此条为综合）：
   ①先查**孪晶**（TwinRotMat 找法则；fcf 的 Fc² 单值性/audit_reflection_data 的
   Fo²>Fc² 带偏）→ ②查**吸收**（校正质量、T 范围、μ·r；B30 审稿人的案例锚点：
   吸收/截断解释通常只覆盖 ≤重元素电子密度 ~5% 且贴近重原子的峰，tid 1742，
   引用需注明出处，非普适红线）→ ③查**非谐振动**（高分辨数据 + Kuhs 判据，B19：
   假二组分无序 vs 非谐波精修指标全面对比；非谐精修当前平台不可执行，属外部/
   人工路线）→ ④**真无序**（差图形状可辨认+化学合理）→ ⑤全排除后书面归因披露
   （B7：重测不改善即以吸收伪影解释过关）。每步以实算指标（R1/wR2/残余峰/椭球）
   验证。
8. **审稿人建议加无序组分**：以差图证据与 R 改善为准，先查是否强限制（ISOR
   esd 0.001 级）撑出假组分需求（B28 放宽到 0.01/0.02 后二组分即够）；证据支持
   就加（B21 主动二→三组分）。既不盲从也不抵触。
9. **"不得有 AB 级警报"是伪律**：警报≠错误；能解决尽量解决，解决不了的用 CIF 内
   VRF（validation reply form）给"相关且有意义"的解释即可发表（A23/B20/B34；
   引句要完整，通用意见原文确实写 no A/B alerts remaining，但后半句允许 VRF）。
   注意 B32 反向：**无 AB 级警报 ≠ 结构正确**（溶剂元素指认错可能只报 C 级）。
10. **复现容差**：同数据同程序不同时期 BASF 漂移 ±0.01 属正常（B25/1872，单案
    观察值、量级参考而非通用容差表），CrystalPilot 基准评卷时孪晶比例等次要
    参数的漂移按此量级理解并结合收敛质量综合判定，不算复现失败。
11. **对审稿人的元认知**（多帖一致）：审稿人会拿你的 hkl 自己精修并预告结果数值
    （B17/B19/A9/A14/A33）、会去 CCDC 查时间戳（A11）、熟悉硬件搭配（B31）、
    会统计被弃数据（B37），一切声称必须实际做到，编造必被戳穿。

---

# 规则正文（A 部：前半 80 帖）

## 一、结构参数报告规范（s.u./有效数字/表格）

### A1. 键长键角必须带标准不确定度（s.u.）
- **触发模式**：审稿人问"are all the digits displayed for angle values meaningful ... what are the associated standard / thermal uncertainties?"——正文/表格中键角写成 110.322° 这类无偏差裸值。
- **必做动作**：论文中引用晶体结构参数（键长、键角等）时，不论行文还是表格、正文还是 SI，一律带 s.u.，格式如 115.88(16)°，含义为 115.88±0.16°（参数是范围不是准确值；原子热振动 + 衍射测的是平均结构）。数值直接取自 CIF 的几何表，不要手工去尾。
- **数值阈值**：无硬阈值；格式规范 = "值(不确定度末位)"。
- **出处**：tid 2005。

### A2. s.u. 位数遵守 IUCr 建议 12：末位不确定度只允许 1–19
- **触发模式**：审稿人原文："Crystallographic convention is that uncertainties may have values ranging from 1-19. If the uncertainty is higher, it and the bond/angle associated with it should be rounded off. For example, the A-C dihedral angle ... currently shown as 20.042(62) should be given as 20.04(6)."
- **必做动作**：按 IUCr recommendation 12 修约：u(y) 落在 10–19 时取两位有效数字，落在 2–9 时取一位；y 的末位与 u(y) 对齐；不确定度**向上取整**而非四舍五入（"uncertainties should be rounded up rather than to the nearest digit"）。相关系数通常给两位有效数字，绝对值接近 1.0 时给三位。信源链接：iucr.org/resources/commissions/crystallographic-nomenclature/statdes/recomm.html。
- **数值阈值**：括号内 s.u. 合法区间 1–19；示例 1.54249 Å (s.u. 0.01532) → 1.542(16) Å；2.16352 Å (s.u. 0.00481) → 2.164(5) Å；20.042(62) → 20.04(6)。
- **出处**：tid 943。

### A3. 键长键角不得砍到两位小数了事：图内可省，正文/表格必须报完整位数+esd
- **触发模式**：审稿人原文："All values currently appear to have been rounded to two decimal places, and no esd values are given in the figures or tables. It might be okay to due that in the figure because of limited space, but not elsewhere. Report the full values to however many decimal places were measured with the esd values."
- **必做动作**：正文、SI 表格按测得位数+esd 报全（该案修正后 Figure 2 键长报 3 位小数）；只有图片内因空间受限可适当四舍五入。位数规则回到 IUCr 建议 12（A2）。
- **数值阈值**：两位小数+无 esd = 被批格式；修正版 3 位小数。
- **出处**：tid 1270（Inorg. Chem. 2024, 63, 21397–21409）。

### A4. 表格里 θ 与 2θ 别写混：与 CIF `_diffrn_reflns_theta_min/max` 对齐
- **触发模式**：审稿人（中文转述）："表1中给出了2θ角度，但这个角度太小了！应该是θ值，不是2θ。"
- **必做动作**：晶体数据表中角度行写 θ 或 2θ 皆可，但必须正确且一致：与 CIF 条目 `_diffrn_reflns_theta_min`/`_diffrn_reflns_theta_max`（记录的是 θ 值）核对；写 2θ 则乘 2。由光源与数值大小可自查（θ 值本质反映分辨率）。
- **数值阈值**：示例换算 θ 2.689–29.207° ↔ 2θ 5.378–58.414°（钼靶）。
- **出处**：tid 1042。

---

## 二、R 因子与数据质量

### A5. R 因子偏高 + 精修统计异常 → 按孪晶怀疑链排查，必要时重新长晶重测
- **触发模式**：审稿人列出组合证据："The R factors ... are much higher than is normally expected ... Fo2 > Fc2 for most of the reflections of medium or weak intensity; large K values for weak reflections; Rint a little larger than one would expect ...; R factors higher than expected given Rint. These issues usually point towards a twinned crystal."
- **必做动作**：①先按孪晶方向排查（找孪晶法则；该例审稿人自己在 Pca21 三种可能性里都没找到法则）；②审稿人点名的高位移参数原子（该例 C6–C10 环戊二烯基）按 SHELXL 劈裂建议做无序建模，但帖中明确记录"无序处理后 R1 和 wR2 稍有降低，但仍然很高"，无序不背 R 高的锅；③终局方案：重新培养晶体重新测试。楼主注：作者未提供原始衍射照片，无法确认是否孪晶；投《晶体学报》类高要求期刊更易触发此意见。
- **数值阈值**：投稿时 Rint=5.25%、R1=7.28%、wR2=15.41%（被质疑）；重测后 Rint=3.26%、R1=3.34%、wR2=9.01%（顺利接收）。
- **出处**：tid 2335（CCDC 2416519，Acta Cryst. 2025, C81, 82–92）。

### A6. "R1/wR2 太大请重修"的三段式回复：无序建模降 R + 噪音坦白 + 论文补描述
- **触发模式**：审稿人一次给三条："The wR1 and wR2 values for compounds 3-8 is too large ... please re-refine related crystal data"；"Some B alerts for these compounds should be refined"；"The refinement of disordered atoms, such as Cl in compound 2, I in compound 4, should be described in the section of 'X-Ray crystal structure determination'."
- **必做动作**：①把椭球形变严重的片段做无序处理，R 因子会降；②降不动时如实解释数据噪音：看 I/σ(I) vs Resolution 图，大量衍射点低于 3 sigma line 即数据含噪多，R 难再降，这是可写进回复的客观理由；③B 级警报逐条解决，帖中点名 PLAT910 这类"也许需要重测晶体才能解决"，其余 B 级警报"差不多能够解决"；④无序、孪晶等特殊处理必须写进论文的 X-Ray 结构测定小节。
- **数值阈值**：噪音判据 = I/σ(I) vs Resolution 图中低于 3 sigma line 的衍射点占比高。
- **出处**：tid 954。

### A7. wR2 超 30% 会被点名：如实解释弱衍射；截断只能基于壳层噪音证据，不得以压线为目标
- **触发模式**：审稿人原文："However, part of the weakness in the SI is the poor X-ray diffraction data with high weighed R2 values of two crystals 2a and 5a, both exceeding 30%."
- **必做动作**：该案衍射很弱、且重新还原时人为把 Rint 调到 18% 以下，R 因子因此偏高（投稿态 R1=11.99%、wR2=30.48%）。两条出路（帖中并列）：①楼主建议，如实解释"晶体衍射较弱"；②作者实际做法，加 `SHEL 999 0.84` 截断分辨率把 wR2 压到 30% 以下，随后发表。**本卡定调**：②为案例实录而非许可，按导师裁决 1/3 与 B37，截断须先有壳层噪音证据、不得截掉 I/σ≥2 的有效数据；若 0.84 Å 外确属噪音壳层则截断正当（wR2 下降是结果不是目标），证据不支持时走①如实解释。（另注意与 A19-3 的张力：审稿人普遍更认可重新积分截断而非精修指令截断；本案用 SHEL 也过了。SHEL 属 SHELXL 指令、当前平台不可直接执行，见导师裁决 2。）
- **数值阈值**：wR2>30% 触发审稿批评（另见 1263 案 CheckCIF 084_B 的机器线 wR2>0.25）；该案 Rint 人为调至 <18%；截断用 SHEL 999 0.84。
- **出处**：tid 1099（CCDC 2406432，Org. Lett. 2025）。

### A8. "检查结构能否改善"的实操工具箱：吸收校正 / 精修消光 / 撤销滥删点 / 重新还原 / 建模无序
- **触发模式**：审稿人原文："I encourage the authors to also check whether or not the structures can be improved by modeling disorder in the phenyl ring bound to boron. In some of the structures, the elongated ellipsoids suggest that disorder might be present."（细长椭球=可能无序的提示。）
- **必做动作**（同一论文 7 个结构的实际改进清单，逐项带效果）：
  1. **补做吸收校正**：无原始衍射图像但有 raw 文件 → APEX4 中用 SADABS 校正。效果（CCDC 2384354）：信噪比 32.5→71.6，Rint 8.11%→2.45%，R1 5.89%→4.41%，wR2 14.08%→10.80%。
  2. **精修消光参数**（2384356/2384358）：R1、wR2 略降。
  3. **撤销用 OMIT 删除的大量衍射点**（2384357）：R1/wR2 略升但完整度 96.9%→98.4%，宁可 R 略高也要还回完整度（与"删点降 R"的作弊路径相反）。
  4. **重新还原+分辨率截断+系统建模无序**（2384360）：截 0.84 Å、苯环/二甲胺基批量无序建模。效果：信噪比 5.9→12.8，Rint 16.50%→4.73%，R1 12.30%→8.93%，wR2 35.15%→33.91%；B 级警报 5 个（PLAT026+2×PLAT241+2×PLAT242）→ 0 个。
  5. **对点名基团做二组分无序**（2384359）：R 略降、椭球恢复正常。
- **数值阈值**：见各项前后对照数字。
- **出处**：tid 1051（CCDC 2384354–2384360，Inorg. Chem. 2024）。

### A9. 审稿人替你算好的消光参数：EXTI 该加就加
- **触发模式**：审稿人原文："There is extinction present here; EXTI refines to 0.0038(5), and R1 will drop to 3.78% and a much cleaner residual density plot will result."（审稿人常直接给出精修后的预期值。）
- **必做动作**：按建议加 EXTI 精修消光参数；实测 R1 4.14%→3.75%、wR2 12.00%→11.46%，与审稿人预告吻合。987 帖审稿人同样点名消光的影响（"a powerful example of how much difference extinction ... can make"）；1051 帖两个结构也以精修消光作为改进项。（EXTI 为 SHELXL 指令，当前平台 run_shelxl 未暴露对应参数，属外部能力，需人工改 ins 执行，做与否写进 VALIDATION。）
- **数值阈值**：该案 EXTI=0.0038(5)；R1 预告 3.78% vs 实测 3.75%。
- **出处**：tid 1381（CCDC 2370581，Chem 2024）；tid 1051；tid 987，3 例一致。

---

## 三、CIF 完整性与数据托管

### A10. Solvent Mask/SQUEEZE 扣除的溶剂必须估算并加回总分子式
- **触发模式**：审稿人原文（1166）："I note that the content of the squeezed solvent has still not been added to the formula quoted. This must be estimated and added as it affects follow on quantities e.g. density, molecular mass, F000, absorption coefficient etc."；1419 帖同一质疑（意见本体为图片，规则由楼主正文陈述）。
- **必做动作**：把被遮掩/挤压的溶剂估算后并入 `_chemical_formula_sum`，理由是它牵连密度、分子量、F000、吸收系数等一串导出量。案例：完整式 C47H66Cl2N3O4Yb = 主体 C43H58Cl2N3O3Yb + 溶剂 C4H8O（THF）（1419，Olex2 有具体操作）；1166 案回复模板："We have now included the content of the squeezed solvent, and the related crystallographic data and refinement parameters have been updated in the revised Table S1."
- **零披露=最重措辞**（851/884 补采全文）：CCDC 审稿人对"用了 mask 但 CIF 只字未提"的裁决原文："In some structures, a solvent mask has been used, but nothing regarding this process has been reported in the CIF. **This is not acceptable.** You must provide information regarding the estimated number and nature of the masked moieties." 并点明估算的三类证据来源，TGA/DSC、结晶条件、遮掩电子数+孔隙尺寸+施掩前密度峰位；且引 IUCr 官方要求（journals.iucr.org/c/services/cif/reqdata.html）："If atoms are missing from the atomic model (e.g. ... solvent molecules suppressed by the 'SQUEEZE' or similar approach), the moiety and sum formulae should state the assumed overall formula." 该案终态：作者干脆取消遮掩、把 THF 建了出来，审稿人致谢收尾，**能建则建仍是评审最欢迎的终态**。
- **数值阈值**：无。
- **出处**：tid 1419（CCDC 2067415）；tid 1166（CCDC 2377155）；tid 851/884（CCDC 2057102/2057105，New J. Chem. 2024, 48, 18695），4 例一致。

### A11. 回复信声称"已重新精修"前，必须先把新 CIF 更新到 CCDC
- **触发模式**：审稿人原文："This review is identical to the previous one. In your reply you state that 'we have re-refined all structures', but this is not true. This is not a surprise since these structures haven't been updated with the CCDC since February 2024."
- **必做动作**：返修中做过的任何精修改动，先向 CCDC 更新 deposit，再写回复；审稿人会去 CCDC 核对时间戳，口头声称而数据未动会被当场戳穿并收到一字不改的重复审稿意见。正面模板：1004 案每条回复末尾固定加 "The new cif file have been updated in CCDC."；977 案审稿人也明确要求 "update and redeposit the CIF files to CCDC"。
- **数值阈值**：无。
- **出处**：tid 1246；tid 1004；tid 977，3 例一致。

---

## 四、ASU 组织与无序建模（审稿驳回类）

### A12. PART 分组必须让"PART 0 + 任一 PART"呈现清晰化学片段；ASU 不得有游离原子、分子式不得出现小数
- **触发模式**：CCDC 审稿人原文："In the core of this structure, everything is bound to everything else. This is impossible. It is impossible to discern the actual chemical unit here and the currently reported bond distances don't make sense ... Please re-organise the asymmetric unit so that it is possible to view the chemical moieties clearly when looking at PART 0 and any one other PART. Note: I have tried to do this and failed. Currently, your model assigns the measured electron density very well, but I can not make chemical sense out of it."（附荒谬键长清单：Br4-Cu3 1.768、Cu3-Cu1 1.202、Cu3-Cu2 0.894 Å 等。）同一意见还点名 CIF 缺条目 `_computing_data_collection`。
- **必做动作**：①无序 PART 重新分组，使 ASU 中无游离原子（该例投稿版 Br3/Br4 游离）、PART 0+任一 PART 可读出化学合理片段；②"分组没做好→存在游离 Br→CIF 分子式出现小数点"是同一根因的连锁病症，重分组后一并消失；③补齐被点名的 CIF 缺失条目。要点：模型拟合电子密度好（"assigns the measured electron density very well"）不豁免化学可读性要求。
- **数值阈值**：无（键长荒谬值见触发段）。
- **出处**：tid 932（CCDC 2294423–2294424，New J. Chem. 2024, 48, 3192–3198）。

### A13. 限制指令过量会被点名"over restrained"——去重、降强、每条留理由
- **触发模式**：审稿人原文："I appreciate this type of structure often requires restraints. However, the structure is still very heavily over restrained, with 1483 restraints, many of which are very strong restraints and some are essentially doing similar things so both probably aren't needed. Please look at these to give more reasonable restraints."
- **必做动作**：审查全部 restraint：删除功能重复的（"essentially doing similar things so both probably aren't needed"）、放宽过强的，只留有理由的合理限制。回复模板："Following your comments, we have reviewed and adjusted the restraints, removing some unnecessary refinements."
- **数值阈值**：该案 1483 条 restraint 被判过量（针对 Ti12 簇类大结构，审稿人已先承认"this type of structure often requires restraints"）。
- **出处**：tid 1166。

### A14. 大面积 EADP 让结构"看起来还行"= 掩盖无序；撤掉不当约束反而降 R，再把无序真建出来
- **触发模式**：审稿人原文："The R factors are too large to contemplate publication of this structure. The fit between your model and the measured data is very bad, and this can be seen also from the residual density plot and the Fractal Dimension Plot. ... The structure 'looks' ok by virtue of these inappropriate constraints: EADP O1 O2 O3 ...（两条各数十原子的整列 EADP）... Removing these, will lower R1 to ~7.8% with almost acceptable ADPs. There is clearly disorder here that can and must be modelled. An R1 of ~6.5% will probably result."
- **必做动作**：①删除大面积覆盖式 EADP（该案撤掉后 R1 反而降到 ~7.8%、ADP 接近可接受，不当约束不仅掩盖问题还抬高 R）；②把明显无序真正建模（审稿人预估建完 ~6.5%；楼主实操：乙酸片段二组分无序+建模配位甲醇与水分子）；③数据先天不好时必须在 CIF/正文写"详细问题描述+无法避免的正当理由"（"I would expect a detailed description of the problems and a valid justification"），一字不写会被视为零交代；④剩余 AB 级警报逐条解释。⑤同案暗坑：Solvent Mask 用了"long deprecated version of PLATON"生成、CIF 里还嵌了全零的空 fab 文件，软件版本要新、废文件别打包进 CIF。与 tid 1137（"ins 中添加了很多不合适的指令如 EADP"）、tid 1426 同向，3 帖一致。
- **EADP 的正当边界**（1426 补采全文+SHELXL 手册原文）：审稿人原文："the EADP should rarely be used **except where the atom positions are also fixed with EXYZ**. ... it would be better to use SIMU if needed in these cases as with EADP both ellipsoids are exactly the same and 'point' in the same direction which doesn't necessarily make chemical sense." 两个正当场景：①EXYZ 共占位无序（如 Sb/Sn 同一位点，CCDC 1850710）；②无序 CF3/PF6 中"方向相反的对位氟"两两 EADP（SHELXL 手册钦点例：EADP F11 F14 / F12 F15 / F13 F16）。其余场景一律优先 SIMU（restraint 带 esd）而非 EADP（exact constraint 令两椭球完全同向）。
- **数值阈值**：该案警报实录 wR2=0.45（>0.25 触发 084_B）、C–C 键长精度 0.012 Å（340_B）、残余密度 −2.59 eÅ⁻³（972_B）；撤 EADP 后 R1≈7.8%，建模无序后预期 R1≈6.5%。
- **出处**：tid 1263（CCDC 2311191，Dalton Trans. 2024）；tid 1137；tid 1426（全文已补采，含 SHELXL 手册 EADP 节原文）。

### A15. 来路不明的"水分子"要有化学证据：氢键网络、结晶体系、必要时 TGA 佐证，否则考虑改判元素
- **触发模式**：审稿人原文（节选）："Structure 6 has an additional highly suspect feature – a water molecule (of unknown origin) positioned 1.9191 Å (extremely close contact!) from a phenyl carbon (C1BA), with the 'water molecule' hydrogen atoms do not participate in any sensible HB interactions. This is highly unusual, and implies erroneous assignment of atom type (possibly the O7 is in fact a chlorine atom with ca 0.25 occupancy from a differently oriented (1-chloroethyl)benzene molecule). ... the claim of the presence of water in this structure should be corroborated by some additional evidence, such as a TGA curve showing the loss of a stoichiometric amount of water."
- **必做动作**：给结构里塞"水"前过四道检查：①接触距离是否物理合理（该案 O…C 仅 1.9191 Å 被斥为 extremely close）；②氢是否参与合理氢键；③结晶体系有没有水的来源（无水体系+疏水介质+疏水腔=从大气吸水"extremely unlikely"）；④拿不出以上答案时要么补 TGA 等独立证据证明化学计量水损失，要么考虑该峰实为其他元素/其他取向组分（审稿人给的替代假设：O7 实为 ~0.25 占有率的 Cl）。
- **数值阈值**：O…C 1.9191 Å 被判过近；替代指认占有率 ~0.25。
- **出处**：tid 1397（CCDC 2350452）。

## 五、Z 值/分子式设置

### A16. Z/Z' 基准跟论文对分子式的定义走，一致性优先级高于 checkCIF 的计算/报告值一致
- **触发模式**：两种形态——①"The calculated and reported Z values for the XRD data set ... do not match."（checkCIF 口径）；②"The definition of the structural formulas should be consistent. To me, the structure formula of compound 1 should contain a complete cluster, and thus the Z value in CIF/RES/INS file should be 1 rather than 2. Accordingly, the formula weight etc. should also be changed. ... Please fix these problems and update and redeposit the CIF files to CCDC."（论文一致性口径）。
- **必做动作**：分子式基准（Z'）的设定服从论文中如何讨论结构：论文按 1 个 [RuSb13] 簇讨论 → CIF 分子式就设成含 1 个簇（该例 Z'=1、Z=2），哪怕这样 checkCIF 里 Z 值/分子式/分子量的计算值与报告值变成 2 倍关系不一致。楼主总结原文："晶体数据 CIF 中分子式的定义应和论文中分子式的定义保持一致，这个一致性的优先级应当高于 checkCIF 报告中计算值和报告值的一致性。（关于这一点，可能不同的审稿人有不同的观点，具体遇到时，可能还是要以审稿意见为准。）"改完要 update & redeposit 到 CCDC。（适用边界见导师裁决 4：仅限式单位记账口径之差，密度/F000 等物理导出量仍须与晶胞实际内容自洽。）
- **第三例**（1218 补采全文，CCDC 2349582，Org. Chem. Front. 2024）：审稿人："There are two independent molecules, so why is the formula based on Au2?"——ASU 有两个独立分子（Z′=2）时分子式仍应以**一个**分子为基准（改 Z′ 使式基于单 Au），而非把整个 ASU 当式单位。且建模 0.25 个游离正己烷后 Z 的报告值与计算值不再一致，楼主裁决：**这不算问题**，"数据是为论文讨论观点服务的，不能本末倒置"。回复模板："The free solvent n-hexane has been modelled appropriately and the formula is based on Au(C52H55AuIN5O4·0.25C6H14) in the revised data set, and the new CIF has been updated in CCDC."
- **数值阈值**：无（Z'=0.5/1、Z=1/2 为该例取值）。
- **出处**：tid 977（CCDC 2334104，JACS 2024）；tid 968（触发形态①，正文截断仅存触发句）；tid 1218（全文已补采），3 例一致。

### A17. 分子式里出现古怪的非整数溶剂计量会被追问"这真是它吗"
- **触发模式**：审稿人原文："if this is really n-hexane, then this would be ~0.666 molecules per formula unit. Could this be something else? Also, the effective resolution is not quite as high as is currently claimed."
- **必做动作**：溶剂指认要经得起化学计量推敲，每分子式单元 0.666 个正己烷这类别扭数字会让审稿人怀疑溶剂种类指认错误，应复核溶剂归属（结晶溶剂清单、电子数）后再定分子式。
- **数值阈值**：无硬阈值；帖中被质疑值为 0.666 个/分子式单元。
- **出处**：tid 1186（CCDC 2265180）。（同主题另一机理见 A18。）

### A18. checkCIF 算出 "3.8(H0.40 O0.2)" 这类碎片分子式 = 无序水的分组/编号乱了
- **触发模式**：审稿人原文："I am a little concerned by the calculated moiety formula listed in the CheckCIF for Mn-1. According to the calculated formula there are 3.8 (H0.40 O0.2) molecules. I do not understand where these partial atoms come from and why there is a discrepancy with the reported values."
- **必做动作**：病因：游离水做了五组分无序，SHELXL 报告的分子式正常，但 checkCIF 的 Calculated moiety 列解析成碎片。处置：对水分子重新分组、重新编号，该案改为 1 个二组分无序 + 3 个三组分无序，并按差值电子密度图把占有率总和定为约 1.25，之后 checkCIF 的 Calculated 与 Reported 分子式一致。要点：无序溶剂的 PART 分组和编号方式影响 checkCIF 的 moiety 解析，Reported/Calculated 不一致要主动消除或解释。
- **数值阈值**：该案水占有率总和 ≈1.25（由差图定）。
- **出处**：tid 1420（CCDC 2327336，Inorg. Chem. 2024）。
- **附**：同帖第二条意见为晶胞参数 s.u. 全为 "(10)"、末位全为 0 的质疑（"Are the standard uncertainties for the unit cell dimensions and angles for Mn-1 correct? I note they are all the same (10) and the values are all '0' in the final decimal place."），楼主注"已在推文《晶体数据审稿意见-晶胞参数标准不确定度问题》讲过"（对应 tid 1342，属后半部范围，本稿仅存触发句）。

## 六、分辨率截断与原始衍射数据

### A19. "真实分辨率"质疑：高角噪音数据应截断、只报有效分辨率；截断引出的新警报加 vrf 答复（高频主题，5 帖合并）
- **触发模式**（各帖审稿原文）：
  - "I would recommend omitting any data above 48° in 2Θ from the refinement -- Rint at that point is already close to 100%!"（987）
  - "The I/sigma drops below 3 at ~2theta = 45. The data should be truncated here and a note added to the experimental."（1004）
  - "The I/sigma drops below 3 at around 2 theta = 42 degrees. This is not surprising given the type of structure, however, the data should ideally be cut around this point. A vrf response will need to be added for the resultant CheckCif alert."（1166）
  - "The resolution has been reported as 0.80 Å -- but the effective resolution is closer to 0.92 Å -- where Rint reaches ~40%. The minimum required resolution has not been reached. I will still recommend publication (if you cannot collect better data), but I also suggest that you only use reflections that are not noise and report the 'true' resolution."（1186）
  - "I suggest rather than including the OMIT -2 50 command in the refinement that the authors re-integrate the data with a lower resolution cutoff. This usually provides better stats in the final model."（1202）
- **必做动作**：
  1. 判定真实分辨率：Olex2 点信噪比出 I/σ(I) vs Resolution 图；XPREP 看分辨率壳层统计（%Complete、Mean I/s、Rmerge）。
  2. 截断位置两判据（1202）：①信噪比，有效数据 I/σ(I)>2（"也有认为应当舍去小于3的"，两标准并存，帖中如实并列）；②完整度骤降壳层舍去（案例：0.74–0.73 壳层完整度 91.8% 对比 0.76–0.74 的 98.1% 属台阶式骤降 → 截 0.74 Å）。
  3. 截断手段三选（1202）：数据还原时设 Resolution Limit（APEX Integrate Images 界面）＞ XPREP 的 [H] Apply HIGH/low resolution cutoffs ＞ 精修中 OMIT/SHEL。**审稿人明确偏好重新积分而非精修里挂 OMIT**（"usually provides better stats"）；楼主各案也均采用重新还原。低分辨率端通常不截。
  4. 指令语法（1202）：`OMIT s[-2] 2θ(lim)[180]`，如钼靶截 0.84 Å → `OMIT -2 50`（λ=0.71073 Å 由布拉格定律换算 2θ=50°）；`SHEL lowres[infinite] highres[0]`，如 `SHEL 999 0.84`（等效截断，R 因子与 OMIT 结果有微小差异）。（OMIT/SHEL 为 SHELXL 指令：当前平台 run_shelxl 不暴露对应参数，属外部能力；平台内等价路径是 scale_and_export(resolution=...) 重导出，见导师裁决 2。）
  5. 截断触发 A 级警报 THETM01（sin(θmax)/λ<0.550）及可能的 PLAT342（键长精度），在 CIF 中加 vrf/author response 解释（1166、1004 均如此处理并被接受，1166 案审稿人复审原话 "The recollected data look much better."）。
  6. 实验部分加说明句，模板（1004）："The data were truncated by 0.84 angstrom due to the I/sigma drops below 2 at about 2theta = 50."
- **数值阈值**：审稿人噪音判据 I/σ(I)<3（多帖一致）；楼主实操截断标准 I/σ(I)≥2；完整度台阶式骤降（91.8% vs 98.1%）为另一截断判据；Rint/Rmerge ≈40% 的壳层被审稿人视为"未达最低分辨率要求"（1186：报 0.80 Å 实际 0.92 Å；XPREP 0.98 Å 处 Rmerge 43%）；案例截断点：2θ=42°(0.99 Å)、45°(0.91/0.93 Å)、48°、50°(0.84 Å)；截断后 sin(θmax)/λ=0.5477<0.550 触发 THETM01。
- **出处**：tid 987、1004、1166（CCDC 2377155）、1186（CCDC 2265177/2265180）、1202（CCDC 2152655/2383197），5 例一致；截断标准 2σ vs 3σ 为帖内并列分歧（见尾部存疑记录）。

### A20. HKLF 变换矩阵不得留到最终结构：回到正确晶胞/设置重新积分
- **触发模式**：审稿人原文："the structure contains an hklf matrix: HKLF 4 1 0 1 0 0 0 1 1 0 0. This should never make it through to the final structure -- it is much better to repeat the data reduction step in the correct setting."；另案："Looking at the HKLF instruction it seems that the cell has been changed after the initial integration, the data should really be reintegrated in the correct cell. This may also help to improve the Rint."
- **必做动作**：解析中若经 PLATON 升空间群/变胞留下了 HKLF 矩阵，投稿前应回原始衍射照片、在正确晶胞设置下重新积分（可顺带改善 Rint），而不是带矩阵交差。1004 案：最初按三斜还原后转 P21/c 留矩阵 → 重新按单斜还原。
- **数值阈值**：无。
- **出处**：tid 987（CCDC 2254645）；tid 1004（CCDC 2262744/2262745），2 例一致。

### A21. 保留原始衍射照片，否则审稿要求重新积分/查明数据病因时无解
- **触发模式**：审稿人要求"reintegrate in the correct cell"/质疑数据质量根源（消光+被 beam stop 挡住的不一致衍射点、晶体滑动、空间群错误）。
- **必做动作**：始终保留原始衍射照片文件。两案全靠重来：987 案重新积分发现第 3 轮约第 100 张照片起晶体滑动，按帧分组重新积分；1004 案重新积分证实空间群定错。楼主在 2335 案也注明"未提供原始衍射照片文件，因此无法确定是否确系孪晶"。
- **数值阈值**：无。
- **出处**：tid 987；tid 1004；tid 2335（反面），3 例一致。

### A22. BASF≈0.5 + 整配体无序/大量 OMIT → 先查空间群与晶胞轴翻倍，别急着上孪晶法则
- **触发模式**：审稿人原文："Given that the BASF is 0.5 it would be worth checking the space group when reintegrating and checking that one of the cell axes is not currently doubled."；"Removing the restraints suggests that perhaps there is some unmodelled disorder present in the ethyl chains that should be modelled, if still the case once the data have been reintegrated."
- **必做动作**：重新积分并重定空间群。1004 案结局：Pmc21（#26）错 → 正确为更高对称 Pnma（#62），正确空间群下 Rint 更低、不再需要孪晶法则、ASU 只剩 1 个分子且无序消失。教训：BASF 恰为 0.5、"整个配体无序"、需大量 OMIT，都是空间群/晶胞可疑的旁证。
- **数值阈值**：BASF=0.5 为触发点。
- **出处**：tid 1004（CCDC 2262745）。

## 七、CheckCIF 警报与元数据完整性

### A23. A/B 级警报的总方针：能解决的尽量解决，解决不了的给出合理解释
- **触发模式**：通用型审稿意见，原文："The characterization relies heavily on single-crystal X-ray crystallography, and for this reason it would be important that the striking structure is assessed by an expert crystallographer, as Platon flags A and B-level alerts."
- **必做动作**：楼主定调原文："不是说必须要消除存在的AB级警报，只是说能解决的尽量解决，无法解决的，给出合理解释即可，大部分问题只需要基本的化学知识即可解释，而有些则可能需要结合晶体学方面的知识。"实操闭环见 1137/1263：处理到只剩少数 B 级警报后逐条在 CIF/回复中书面解释。
- **数值阈值**：无。
- **出处**：tid 1297；tid 1137；tid 1263，3 例一致。

### A24. Ueq > 0.15 的原子 = 占有率设高了或存在未建模无序
- **触发模式**：审稿人固定句式（两案完全一致）："The Ueq values of the following atoms are extremely large (Ueq = > 0.15). Either the occupancy is set too high for these atom, or you might need to explore the possibility that these atoms are involved in some form of disorder: ..."
- **必做动作**：对点名原子查 Ueq（Olex2 悬停原子看 Ueq，或 lst 文件搜 "Ueq"），按无序建模处理。1004 案：二氯甲烷 Cl3/Cl4/C30 做二组分无序（占有率 0.646:0.354）后警报解决。
- **数值阈值**：Ueq > 0.15 为审稿人红线。
- **出处**：tid 1004；tid 1137，2 例一致（同句式）。

### A25. 大量 A/B 级警报 + 元数据空缺 = "preliminary working version"，会被整体驳回
- **触发模式**：审稿人原文："the structure looks like a preliminary working version. Please have a look if there has been an error here, this structure is definitely not for publication in this form. Please check all the cif alerts."随附警报清单（该案实际出现）：080 Max Shift/Error 4.15（未收敛）、031 消光参数、183/184/185 缺 _cell_measurement_reflns_used/theta_min/theta_max、214/216 ADP max/min 比 6.7–9.9、368/369 异常 C–C 键长 1.12–1.68 Å、342 键长精度 0.035 Å、699/缺 _exptl_crystal_description、987_B Flack x >> 0 应做 BASF/TWIN 精修、吸收系数 11.786 但 Tmax/Tmin/校正类型全为 "?"、晶体尺寸/形状/颜色缺失、_computing_* 系列缺失。
- **必做动作**：①精修必须收敛（Shift/Error 达 4.15 属硬伤）；②该建的无序都建；③删除 ins 中不合适的指令，楼主点名"添加了很多不合适的指令如 EADP 指令"（与 tid 1426 标题"切勿随意使用EADP限制"互证）；④补齐全部元数据：晶胞测定三项、吸收校正 Tmax/Tmin 与类型、晶体尺寸/形状/颜色、_computing_* 软件条目；⑤处理到只剩少数 B 级警报后逐条书面解释（该案最终剩 2 个 B 级并附解释）。
- **数值阈值**：该案 Max Shift/Error 4.15（正常应≈0）；Ueq>0.15 名单同 A24；μ=11.786 mm⁻¹ 必须报吸收校正。
- **出处**：tid 1137（CCDC 2309587，J. Mater. Chem. A 2024）。

## 八、论文与 SI 的描述义务

### A26. 无序精修细节+占有率必须写进 SI（给模板句）
- **触发模式**：审稿人原文："Please provide detailed information on how to refine disordered molecules (including site occupancy factors of the disordered atoms/molecules."（1156）；"The refinement of disordered atoms, such as Cl in compound 2, I in compound 4, should be described in the section of 'X-Ray crystal structure determination'."（954）
- **必做动作**：SI 逐结构写无序描述，模板（帖中原句）：三组分 "I1, I1A and I1B were disordered over three sites with occupancies 0.871:0.042:0.087."；二组分 "C1~C6, F1~F4, I1~I2 and C1A~C6A, F1A~F4A, I1A~I2A are disordered over two sites with occupancies 0.418:0.582"。restraint 说明模板（1004 回复原文）："Necessary restraints/constraints (SADI, DFIX, FLAT, RIGU and SIMU) were applied to prevent deformation of the disordered fragments and maintain its anisotropic displacement parameters within a reasonable range. The residual electron densities were of no chemical significance."
- **期刊硬规定**（1386 引作者指南原文）："If restraints or constraints on non-hydrogen atoms or adjustments to the structure factors are used in the refinement of a crystal structure, these should be described in detail in the experimental section and their application justified."——不仅要列出用了哪些 constraint/restraint，还要**说明其应用理由**及**占有率如何确定**（"as well as how the relative occupancies of the disordered positions were determined"）。1386 案回复模板：逐基团列 SAME/SIMU 与占有率（"Atoms C18 to C22 and C18A to C22A were disordered over two sites with occupancies of 0.514 and 0.486, respectively."），并写明相应讨论已加到修改稿第几页。
- **数值阈值**：占有率写到三位小数、和为 1。
- **出处**：tid 1156（CCDC 2281927–2281938）；tid 954；tid 1004；tid 1386（Inorg. Chem. 2024），4 例一致。

### A27. 实验部分必须交代氢原子处理、restraint/constraint 与孪晶（给 H 模板）
- **触发模式**：审稿人原文："The experimental should include information on the hydrogen atom treatment, any restraints or constraints used and any twinning present."
- **必做动作**：SI 写明每类 H 的处理方式，模板（1004 回复原文）：胺基 N–H 由差值傅里叶定位自由精修（"was located by difference Fourier syntheses and was refined freely"）；因无序定位不到时改算位+骑乘（"cannot be located by difference Fourier syntheses due to disorder, and thus were placed at the calculated positions and were refined as riding model"）；Uiso 约定 "Uiso(N−H)=1.2 Ueq(N), Uiso(Csp2−H)=1.2 Ueq(Csp2), Uiso(Csp3−H)=1.2 Ueq(C), Uiso(CH3)=1.2 Ueq(C)"。
- **数值阈值**：Uiso=1.2 Ueq（该帖各类 H 均写 1.2）。
- **出处**：tid 1004。

### A28. 解析/精修方法的措辞必须技术正确：解析算法不能拿来"精修"
- **触发模式**：审稿人（中文转述）：实验部分写"通过直接法求解，并基于 F2 使用 SHELXL 通过正负交替反转法进行精修"——"最后一句话没有意义，正负交替反转法是一种结构解析算法，不能精修结构。"
- **必做动作**：解析方法与精修方法分开写并与所用程序对应：charge flipping（正负交替反转法）是 Superflip/olex2.solve 的**解析**算法；SHELXL 的**精修**方法是最小二乘法（least squares）。写作前核对程序-方法对应表。
- **数值阈值**：无。
- **出处**：tid 1284。

### A29. 每个结构至少一张 ADP 椭球图，无序可见、图注注明椭球概率水平
- **触发模式**：审稿人原文："In the MS (or at least the SI), please provide at least one structural drawing showing ADPs of each structure. From these images, any disorder should be visible -- and the nature of the actual molecule must be easily discernible."
- **必做动作**：正文全用球棍/棍状图时，至少在 SI 补一张 Olex2 椭球模型图（Ellipses and stick）；无序组分要在图上可见；标题必须注明椭球率/椭球概率水平（ellipsoid probability level）。
- **数值阈值**：无（椭球概率水平数值需注明但帖中未规定具体值）。
- **出处**：tid 1237（CCDC 2373596，Chem. Commun. 2024）。

### A30. 实验部分对测试条件的描述必须逐项与 CIF 一致（光源/单色器等）
- **触发模式**：审稿人原文："The experimental section of the paper says that the data was collected using graphite-monochromated Cu radiation, However, the CIF indicates that three structures (1a, 1e, and 3) were collected using Mo radiation. The CIF also says that 2a, 2b, 2c, 2d, and 3 were run on a diffractometer using a mirror monochromator, not a graphite monochromator (the monochromator information was not reported in the CIF for 1a or 1e)."
- **必做动作**：写实验部分前逐项对照 CIF：光源 `_diffrn_radiation_type`、单色器 `_diffrn_radiation_monochromator`（以及温度等测试条件）；CIF 缺该条目的要补上。审稿人会逐结构核对。
- **数值阈值**：无。
- **出处**：tid 1059。

### A31. 审稿回复三件套：致谢 + 具体动作 + "CIF 已更新"
- **触发模式**：任何晶体学审稿意见的逐条回复场景。
- **必做动作**：帖中实战回复的固定结构，开头统一致谢（"Thank you very much for your kind and insightful suggestions..."），每条意见下写明实际做了什么（截断到哪、限制怎么调、溶剂怎么加），结尾落到数据托管状态（"the revised CIF file has been updated accordingly" / "The new cif file have been updated in CCDC."）。承诺的动作必须真做（呼应 A11 的反面案例）。
- **数值阈值**：无。
- **出处**：tid 1166；tid 1004，2 例一致。

---

## 九、空间群争议

### A32. 被指"赝对称/错定中心对称"：诚实试解非中心群，收敛失败可作保留原空间群的证据
- **触发模式**：审稿人原文（节选）："there are some indications that these are in fact cases of pseudosymmetry, and that the structures are in fact non-centric, erroneously refined as centrosymmetric ... Classic 'symptom' of such misassignment of the space group [is] apparent disorder of the part of the structure which 'brakes' the symmetry. The disorder in 6 is apparent, but is also present in 5, as evidenced by large and highly elongated (even with ISOR!) displacement ellipsoids of C1 and Cl1. Therefore both 5 and 6 should be solved and refined in non-centric groups (viz P1 and P21) ... It might be necessary to perform additional measurements (in particularly for 5, as the whole reflection sphere is needed for proper structure refinement in P1)."（背景：主体大环近中心对称、只有客体破坏对称；作者用"加热外消旋"解释两对映体共存被质疑。）
- **必做动作**：①按审稿人要求真的在非中心群（P1/P21）重解重修；②该案结局：非中心群下精修**无法收敛**: P1 下 PLAT080 Max Shift/Error 1.41、P21 下 0.42，均伴 PLAT340，把不收敛的 CIF 作为附件证据随回复提交（"See attached CIF files."）；③最终以中心对称空间群发表。方法论：对空间群质疑不空口反驳，用两种设定的实算结果说话。
- **数值阈值**：不收敛证据 Max Shift/Error 1.41 / 0.42（正常应≈0）；P1 精修需完整衍射球。
- **出处**：tid 1397（CCDC 2350450/2350452，Molecules 2024）。

### A33. Flack 参数被当作空间群判据：审稿人算得更低不必照单全收，重测数据改善 Flack 后可保原空间群
- **触发模式**：审稿人原文（节选）："the correct space group may be P1 instead of P21. In P21 the authors report an R of 5.24% with a Flack parameter of 0.214. In P1 with no hydrogens, no attempt to account for disorder in the CF3 groups, and some atoms isotropic, I get R = 2.69% and Flack = -0.004. ... In my view, the very good Flack parameter in P1 is strong evidence that P1 is correct."（审稿人还自己找到一个占有率仅 5% 的甲苯分子作 P1 的旁证。）
- **必做动作**：①先在 P1 下复算，该案"尝试在P1下解析没有得到审稿人所说的结果"；②重测新数据：新数据在 P21 下 Flack 从 0.214(12) 改善到 0.062(3)，以 P21 发表。要点：Flack 差可能是数据质量问题而非空间群错误；复现不了审稿人的方案时，用更好的数据支撑自己的空间群。
- **数值阈值**：被质疑 Flack=0.214(12)；重测后 0.062(3)；审稿人宣称 P1 下 R=2.69%、Flack=−0.004（未建氢/未建无序/部分各向同性的简化模型）。
- **出处**：tid 1405（CCDC 2239204，ACS Catal. 2024）。

## 十、测试条件（温度等）

### A34. "为什么在 293 K 测？低温才是 state of the art"——按实际条件与化合物特性作答
- **触发模式**：审稿人原文："X-ray quality: The quality of the X-ray structures are at least in my opinion moderate. Large R1/wR2 values. Most of the structures were measured at 293K. Why? This is – at least in my opinion - no longer state of the art."
- **必做动作**：承认低温通常数据质量更好、R 更低，但可用三类正当理由回复：①单位条件，"很多时候低温测试并不是能够常态获取的测试手段（有些单位可能根本无法提供低温测试），常温测试才是常态"；②化合物特性，低温可能引起相变或晶体被冻坏（楼主引"一颗怕冷的晶体"等实例）；③性质对应，化合物性质与温度相关，换温测试将与性质无法对应。楼主结论原文："只有合适的测试温度，没有最好的测试温度。"
- **数值阈值**：293 K 室温测试为触发点。
- **出处**：tid 1088。（tid 1067/1076 同主题但正文截断。）

## 高频重题统计（A 部）（同主题出现 ≥3 帖；候选独立技能卡素材）

按"该主题为帖子标题主旨或规则主体"计数，存根/截断帖凭标题计入主题热度但不供内容：

> **补采修订（2026-08-31）**：所谓"存根/截断"大部分是早期抓取器丢失
> Discuz 表格所致，**并非**"意见本体是图片"。16 帖全文已补采入语料
> `threads/<目录>/supplement.md`（832, 851, 884, 911, 1026, 1067, 1076,
> 1177, 1211, 1218, 1309, 1368, 1411, 1426, 1434, 1441 - A10/A14/A16
> 已据此增补，1368 另立 refine-special-details-templates 卡）；
> 3 帖仅知乎搜索摘要（505/542/559，非保真勿直接引用）；10 帖正文本体
> 即网盘 PDF 无法补采（338, 373, 417, 466, 524, 601, 655, 722, 737,
> 750 - "CIF 必填项/不应出现的审稿意见"系列，凭标题计热度）。

1. **无序建模被审稿人点名/描述**（≈12 帖）：2335, 954, 1051, 1137, 1156, 1263, 1386,
   1420 实文 + 722, 832, 884, 1411 存根/截断。→ 候选技能卡：无序建模审稿应对链
   （椭球拉长/Ueq>0.15 → 建模 → SI 描述模板）。
2. **CIF 必填项与元数据完整性**（≈12 帖）：1137, 1059 实文 + 338, 373, 417, 466, 524,
   542, 559, 601, 911, 1026 存根（晶癖/尺寸/颜色/温度/嵌入 hkl-res/吸收校正行宽等，
   "不应出现的审稿意见"系列）。→ 候选技能卡：CIF 交付前自检清单。注意该系列存根
   居多，正文需向楼主公众号/网盘补采。
3. **真实分辨率与截断**（8 帖）：987, 1004, 1166, 1186, 1202, 1099, 1051 实文 + 1177
   存根。→ 候选技能卡：真实分辨率判定与截断三工位（A19 已合并 5 帖主干）。
4. **A/B 级警报解决与解释**（≈9 帖）：954, 1137, 1263, 1297 实文 + 737, 750, 832,
   1026, 1309 存根/截断。→ 候选技能卡：警报分级处置（解决→解释→vrf）。
5. **SI/正文精修描述义务**（9 帖）：954, 1004, 1059, 1156, 1284, 1386 实文 + 1368,
   1434, 1441 存根。→ 候选技能卡：精修描述模板库（无序/氢原子/限制指令/方法措辞）。
6. **Z 值与分子式基准**（8 帖）：968, 977, 1186, 1419, 1166, 1420 实文/部分 + 1211,
   1218 存根。
7. **s.u./有效数字/报道格式**（6 帖）：2005, 943, 1042, 1270 实文 + 505, 655 存根。
   → 候选技能卡：结构参数报道格式（IUCr 建议 12 全文已录）。
8. **R 因子偏高回复链**（5 帖）：2335, 954, 1099, 1263, 1088。→ 候选技能卡：R 高
   四步应对（孪晶排查→无序建模→噪音/弱衍射解释→重测）。
9. **测试温度**（4 帖）：1088 实文 + 601, 1067, 1076 存根/截断。
10. **原始衍射数据保留/重新还原**（4 帖）：987, 1004, 1202, 2335（反面）。
11. **CCDC 数据更新纪律**（4 帖）：1246, 977, 1004, 1166。
12. **EADP 滥用**（3 帖）：1263, 1137 实文 + 1426 截断。
13. **孪晶精修被点名**（3 帖）：2335, 1004, 851 全实文。851 补采亮点：
    CCDC 审稿人**亲自给出孪晶律** `1 0 0.191 / 0 -1 0 / 0 0 -1` 并预报
    改善数字（R1 9.8→7.7、wR2 31.2→26.9、残峰 2.5→1.4，BASF 0.09）；
    实操=PLATON TwinRotMat 检出→HKLF5-Gener 生成 hklf5 ins/hkl 精修
    （与 hklf5-twin-workflow 卡同流程的期刊实证）。

## 存疑/冲突记录（A 部：定调见头部导师裁决）

1. **截断标准 2σ vs 3σ**：多位审稿人以 I/σ(I)<3 划噪音线（987/1004/1166），但楼主实操
   将截断标准定为 I/σ(I)≥2（1004 回复原文 "Effective data standards (I/sigma above 2)
   were applied"），1202 明言两派并存（"通常认为信噪比大于2的为有效数据……也有认为
   应当舍去小于3的"）。两标准都被期刊接受过，未见统一。
2. **截断手段：重新积分 vs 精修指令**：1202 审稿人明确建议重新积分而非 OMIT
   （"usually provides better stats"），987/1004/1166 也都走了重新还原；但 1099 案作者
   只加 `SHEL 999 0.84` 压 wR2 也顺利发表。手段与结论未统一，倾向重新积分更稳妥。
3. **Z 值基准：论文一致性 vs checkCIF 一致性**：977 楼主总结"CIF 分子式应和论文
   定义一致，优先级高于 checkCIF 计算/报告值一致"，但同帖自注"可能不同的审稿人有
   不同的观点，具体遇到时，可能还是要以审稿意见为准"——非硬规则。
4. **删点与 R 因子的取舍**：1051 案撤销 OMIT 删点使 R1/wR2 略升、完整度 96.9%→98.4%
   ，与"R 越低越好"的直觉相反，语料立场是完整度/诚实优先；但 1099 案又靠截断
   （变相删高角点）把 wR2 压线发表。两案的边界（截噪音 vs 删好点）本稿按 A19/A8-3
   的判据区分，导师精编时可再明确。
5. **空间群争议两案均未采纳审稿人方案**：1397 审稿人要求改非中心群 → 作者以
   "不收敛（Shift/Error 1.41/0.42）"为证保住中心对称群发表；1405 审稿人以 Flack 论证
   P1 → 作者复算不出该结果、重测新数据后仍以 P21 发表。共同方法是"实算+新证据"，
   但两案都推翻了审稿人的具体空间群主张，提示审稿人的空间群改判需实证检验，
   不可盲从，也不可空口反驳。
6. **1099 案 Rint 人为调整**：楼主自述重新还原时"人为调整了Rint值"到 <18%，并因此
   推高了 R 因子；该操作与数据诚实的边界帖中未展开，存疑待导师定调。
7. **截断帖的标题证据力**：（2026-08-31 已大幅缓解，16 帖全文补采见
   统计节修订框；其中 1411/1426 等已从"仅标题"升级为全文证据。）仍剩
   10 个网盘 PDF 帖只有标题可用，继续按"实文互证时弱佐证"原则处理。
8. **连通性表的键该不该删（851 案第二轮）**：审稿人点名 Co–P 距离
   ~2.73 Å 为 "spurious bonds"，要求 `CONN $P 4` 从键表删除；作者以
   "Co 与 P 之间可能存在弱配位作用"为由**有理有据地不采纳**（论文图中
   也不画该键），审稿通过。边界：键表只报真实键是原则，但弱相互作用
   可用化学论证保留，关键是回应而非沉默。同轮小坑：论文正文键长小数
   位数与 CIF 不一致（软件导表四舍五入所致）也会被点名，以 CIF 为准。

## 附录：跳过名单（A 部）

### 网盘存根（正文=标题+网盘链接，无审稿意见文字）
- tid 338 CIF必填项-晶癖；tid 373 CIF必填项-晶体尺寸；tid 417 CIF必填项-晶体颜色；
- tid 466 CIF中未嵌入hkl和res文件；tid 486 绘制椭球图；tid 505 几何参数需有偏差；
- tid 524 晶体尺寸；tid 542 晶体形状；tid 559 晶体颜色；tid 579 数据不收敛(PLAT080)；
- tid 601 温度记录；tid 618 原子冗余标签；tid 633 结构精修需要删除的键案例13；
- tid 639 重复的数据名称；tid 655 晶体结构几何参数表；tid 722 2,6-萘二甲酸无序处理；
- tid 737 AB级警报和信息缺失；tid 750 AB级警报解释说明；tid 762 ASU中6个分子-晶胞错误；
- tid 774 ASU中多个分子时结构参数报道；tid 788 A类警报PLAT881；tid 801 B级警报PLAT220；
- tid 823 B级警报PLAT430；tid 832 B级警报处理(大量无序)；
- tid 911 CIF中吸收校正详情文本行超过80字符；tid 1014 报道真实键；
- tid 1026 标签+AB级警报+嵌入HKL；tid 1113 撤销删除衍射点；tid 1145 对残余峰进行解释；
- tid 1177 分辨率截断；tid 1211 分子量计算值和报告值存在差异；
- tid 1218 分子式单元基准设置(Z'值或Z值设置)；tid 1226 化合物全名和俗名；
- tid 1368 精修细节描述文献案例(Nat._Chem.)；tid 1374 表格中的数据格式；
- tid 1411 明显存在无序则需要进行无序处理；
- tid 1434 氢原子处理方式描述；tid 1441 氢原子处理描述；tid 1067 测试温度及回复
- （注：这些帖标题即审稿主题，晶癖/尺寸/颜色/嵌入 hkl-res/椭球图/几何偏差等 CIF 必填与
  警报处理，但正文无内容，按数据诚实原则不由标题脑补规则。）

### 正文截断（有开场白，审稿意见本体是未抓取的图片）
- tid 851 CCDC2057102(孪晶精修) / tid 875 CCDC2057104 / tid 884 CCDC2057105(无序处理) /
  tid 897 CCDC2063197：同一论文（New J. Chem. 2024, 48, 18695–18699）四连帖，均只剩
  案例号+主题词，审稿意见为图片；
- tid 1062 PLAT987：审稿意见与"群主张老师解答"均为图片；
- tid 1076 测试温度问题：审稿意见为图片，余为背景闲聊；
- tid 1126 错用限制指令(PLAT430)：只剩案例号（CCDC 2396827），意见为图片；
- tid 1309 解决和解释AB级警报：只剩案例来源（Inorg. Chem. 2024），意见为图片；
- tid 1426 切勿随意使用EADP限制：仅存"EADP 指令切勿随意使用，否则可能会出现如下
  审稿意见"一句话规则，意见本体为图片，该句已作为弱佐证并入 A14，计入"部分可用
  4 帖"而非纯跳过。

### 无技术内容
- tid 332 Chem._Sci.查看审稿意见及其回复：正文=网盘 PDF 分享+网友寒暄，无正文内容。

---

# 规则正文（B 部：后半 80 帖）

## 规则条目（B 部：后半 80 帖）

**B1. 氢原子确定/精修方式未描述**
- 触发模式：审稿人要求说明氢原子是找出后各向同性精修还是固定在理想位置（原文 "whether the H atoms were located and refined isotropically or, fixed in idealized positions. Very important to know this information."，JACS 2024）。
- 必做动作：在 SI 中补一段氢原子处理描述，尤其活泼氢（O、N、S 上的氢）要单独交代确定方式与精修方式。
- 数值阈值：无。
- 出处：tid 1448。

**B2. 要求提供热椭球图（ORTEP 风格）及图注注明椭球概率**
- 触发模式一："Please provide an ORTEP-style illustration of each structure, with probability ellipsoids in the main Supplementary Information PDF file, along with the CCDC reference number."
- 触发模式二："Please indicate the ellipsoid contour % probability levels in the caption for the image of the structure."
- 必做动作：SI 中每个结构给一张椭球模型图（非球棍/线框/条状图），并附 CCDC 号；图注写明椭球概率水平（范例句 "...with thermal ellipsoids set at 30% probability level..."，Sci. China Chem. 2023）；工具可用 Olex2/ORTEP-3/Diamond（帖中列了成套教程）。
- 数值阈值：范例椭球率 30%（并非规定值，是范例）。
- 出处：tid 1463；tid 1836。

**B3. 溶剂占有率过度分配（over-assigned）**
- 触发模式：审稿人由差值图指出溶剂被过度分配（原文 "The difference map shows quite clearly that the DCM solvent has been over-assigned. When refined freely, the occupancy will be around 93% -- and R1 will be significantly lower"，Chem. Commun.，CCDC 2265176）。判据：原子处出现暗红色负差值电子密度（Olex2 Ctrl+M 查看）＝该处电子密度不足以支撑全占据。
- 必做动作：整个溶剂分子引入自由变量放开占有率精修（Olex2 选中整分子输入 `part 0 21`）；接受非整数分子式；知悉由此可能触发 PLAT041/042/068/077/302/304（小数分子式类警报），属可解释项。帖中解释：晶体挑选过程中部分 DCM 逃逸很常见。
- 数值阈值：该例占有率精修至 0.926（审稿人预估约 93%），R1 5.19%→4.87%。
- 出处：tid 1481。

**B4. 原子被过度/不足分配→元素指认错误（卤素交换混占）**
- 触发模式：审稿人指某原子 over-assigned 并直接给出混占比例与预期 R1（原文 "Atom Br1 has been over-assigned... best explained by a Br/Cl disorder in the ratio of 86/14. The final R1 of this structure will be around 3.62% (currently 4.41%)."）。
- 必做动作：查原料清单找卤素来源（金属氯化物+有机溴化铵盐→卤素交换）；按共占据无序建模精修占比；若作者坚称不存在另一卤素，先查污染，否则重新长晶重测。占有率对了 R1 应同步下降（审稿人以预期 R1 为验证标尺）。
- 数值阈值：案例一 Br/Cl 精修为 21%/79%；案例二审稿人给 86/14、R1 应 4.41%→约 3.62%。
- 出处：tid 1512。

**B5. 用了 SQUEEZE/溶剂遮掩但论文未说明**
- 触发模式：审稿人从 CIF 发现 SQUEEZE 却在正文/ESI 找不到说明（原文 "We see from the CIF that the SQUEEZE program was used... but we are nowhere told about this in text or ESI material"；另例 "Squeeze routine in PLATON has been applied to three single-crystal structures..., which should be described in detail in ESI"）。
- 必做动作：正文与修订 CIF 中明确写出被去除溶剂的种类与数量（该例 227 e⁻）；溶剂种类和数量应由其他表征（元素分析等）确认，并计入 CIF/RES/INS 与正文分子式；相应修正分子量、密度等衍生量；修改后 CIF 重新沉积 CCDC；参考文献必须引 SQUEEZE 正式文献 Spek, A. L. (2015). Acta Cryst. C71, 9–18（引 PLATON 通用文献不算数，原文 "Reference 48 is not an adequate PLATON reference"）。
- 数值阈值：该例被除电子数 227 e⁻/晶胞。
- 出处：tid 1498；tid 1489；tid 1608（同型触发：用了 PLATON SQUEEZE 或 Olex2 Solvent Mask 但信息未进 CIF/论文，帖中审稿原文为图片未抓取）。

**B6. 溶剂遮掩"切到大动脉"——把配位配体当溶剂挤掉**
- 触发模式：做了 SQUEEZE 后金属配位球仍不完整、金属旁 Max Peak 仍高（该例 K 两侧空缺、Max Peak 2.4 且 Q1 在 K 旁），审稿人要求确认被挤压内容。
- 必做动作：遮掩前检查配位球完整性；金属旁被遮掩的密度优先按配位配体（该例为与 K 配位的乙二胺）显式建模而非当游离溶剂挤掉；补回配体后得到完整配位环境再发表。
- 数值阈值：遮掩后 Max Peak 2.4（位于金属 K 旁）即为异常信号。
- 出处：tid 1489。

**B7. 金属/重原子旁高残余峰（PLAT971 类）要求解释**
- 触发模式：审稿人指出最高残余电子密度过高且贴近重原子，怀疑吸收伪影或晶体质量（原文 "the highest residual electron density is firstly quite high and nearby Sb9. This might be an artifact of the absorption."；并问为何该化合物在室温而非 100 K 测试；"Maybe a high R(int) value hints to problems of the crystal quality?"）。
- 必做动作：能重测先低温重测（该例 130 K 重测未改善）；重测无效时在 checkCIF 回应表中对 AB 级警报给出书面解释（归因吸收伪影），并正面回答测试温度选择。同系列化合物可对照（Fe 类似物无此峰，说明非纯吸收）。
- 数值阈值：该例 Max Peak 3.9 / Min Peak -3.5；R1 8.5% 被审稿人称 "not satisfying"，R1 5.7% 被称 "better"。
- 出处：tid 1334。

**B8. OMIT 删除大量衍射点（审稿红线）**
- 触发模式：审稿人清点 CIF 中被 OMIT 的反射数并驳回（原文分级："It is sometimes necessary to omit one or two reflections that have been incorrectly measured, typically because they have been blocked by the diffractometer beamstop. Although not generally recommended, it can also be acceptable to use an OMIT instruction to limit the resolution of the data (i.e. OMIT 0 50) if the data quality drops at higher resolutions. It is NEVER acceptable, however, to omit several dozen to several hundred reflections"）。该例 2d 手动删 400+ 点触发 A/B 级警报，作者以"同步辐射机时有限/探测器跳过区域"辩解被当场戳穿（数据实为实验室衍射仪所测）。
- 必做动作：把被删反射全部放回精修；数据真实问题（该例为孪晶）用孪晶法则解决（TwinRotMat 或衍射仪自带工具找法则）；审稿人要求 "MUST re-refine all the structures without omitting dozens of reflections"。作者最终以重新长晶重测了结。楼主总结：若需要删大量点才能压 R，或删了也压不下来，多半是数据本身有病（无序/孪晶/晶体质量差），应对症处理而非删点。对警报的解释必须真实，编造理由会被审稿人核实揭穿。
- 数值阈值：允许删 1-2 个（束挡遮挡类）；删几十到几百个绝对不可接受；该例加孪晶法则后 R1 降到 6% 以下。
- 出处：tid 1586（tid 1580 同题存根无正文）。

**B9. 溶剂水氧椭球异常大 + 未建模残余密度**
- 触发模式：审稿人指某原子椭球"不切实际"、远大于周围原子并直接暗示非全占据（原文 "The ellipsoid of O7 in complex 4 appears to be unrealistic. Please check this... Is it possible it is not a full occupancy water molecule of solvation?"；"There is significant residual unmodeled electron density in complex 5 (~1.7 e–/Å3). Is this due to the spherical treatment of Cd or is there unmodeled solvent?"，J. Coord. Chem.，CCDC 2218166/2259290）。
- 必做动作：椭球异常大的溶剂水按无序处理（楼主方案：三组分无序，差图变干净、残余峰与 R 均降）；或者用 Olex2 Solvent Mask 直接遮掩（作者实际路线），两条路都被接收，帖中并列保留。残余峰能认出形状的（该例硝基第二取向）必须显式建二组分无序，认不出的（O13）才遮掩。
- 数值阈值：触发残余密度 ~1.7 e⁻/Å³；硝基建无序后残余峰 1.8→1.4。
- 出处：tid 1634。

**B10. 图表中对称等效原子未标对称操作码**
- 触发模式：审稿意见（中文）："表2、图1中原子有对称操作码，应该标明。"
- 必做动作：Z'<1 的结构中凡 grow 出的片段/原子进图或进几何参数表，须在图注/表格注脚标注对称操作码（如 i: 2-X,1-Y,2-Z），堆积图同理；键长键角表述用上标区分（Mn1–N2 vs Mn1–N2^i）。Olex2 的 Draw→Symmetry label 提供 $ /#/罗马数字/full 四种标识形式（full 太占空间不建议），也可双击原子标签自定义后缀；任何绘图软件同此要求。
- 数值阈值：无。
- 出处：tid 1669。

**B11. 用全结构 SIMU/ISOR 糊弄代替无序建模（"不要偷懒"）**
- 触发模式：审稿原文 "The authors have not modelled the disorder of the 1,4-benzenedicarboxylate but instead applied a SIMU restraint to the entire structure. This is a rather lazy way of addressing this issue (and masks the presence of disorder), when modelling the disorder would give a more accurate representation of the structure."（Chem. Sci.，CCDC 2347593–2347594）。
- 必做动作：对明显无序显式建模；精简限制指令（撤掉全结构 SIMU/ISOR，只留有理由的局部限制）；顺带做规范的原子编号。
- 数值阈值：无。
- 出处：tid 1685。

**B12. 作者自己提出的倒反孪晶未纳入精修**
- 触发模式：审稿原文 "The crystal structure of NPU-6 should be refined taking into account the inversion twin the authors postulate is present."
- 必做动作：既然文中主张存在倒反孪晶，精修就必须加入相应孪晶处理（TWIN/BASF），文字主张与模型必须一致。
- 数值阈值：无。
- 出处：tid 1685。

**B13. 无序占有率被锁死未解释**
- 触发模式：审稿原文 "Why was the ratio of the disorder fixed? Please refine or explain."（J. Mater. Chem. A 2024）。
- 必做动作：二选一，放开占有率精修，或给出锁定的物理理由；不能默不作声地锁死。
- 数值阈值：无。
- 出处：tid 1707。

**B14. 氢原子处理方式混乱、约束堆砌**
- 触发模式：审稿原文 "The mixed treatment of hydrogen atoms is confusing. 'EADP H14 H15' is the only necessary constraint or restraint for this structure."
- 必做动作：统一氢原子处理方案；把约束/限制砍到最少（该例审稿人认定全结构只需一条 EADP H14 H15），每条约束要有存在理由。
- 数值阈值：无。
- 出处：tid 1707。

**B15. 溶剂遮掩程序选择被审稿人指定**
- 触发模式：审稿原文 "Rigaku equipment is used; guest molecules in void should be approximated using Olex2 solvent masks similar to SQUEEZE."（审稿人要求把 PLATON SQUEEZE 换成 Olex2 Solvent Mask）。
- 必做动作：楼主观点：用 Solvent Mask、SQUEEZE 或其他等效程序均可、无硬性规定，但被去除的部分需计入总分子式；具体到审稿意见，"既然审稿人提了要求，那么按照审稿人的要求修改即可"（顺从成本最低）。
- 数值阈值：无。
- 出处：tid 1561。

**B16. 原子标签不标准 / 原子未排序 / 未从初始解更新编号**
- 触发模式一：审稿原文 "Atomic names should be standardized (e.g., change K00J to K1) and atoms should be sorted properly."（JACS 2024）。
- 触发模式二（大意）：原子名称尚未从 SHELXL/SHELXT 的初始解中更新，应按合理顺序给原子起化学上有意义的名称。
- 触发模式三：标签与论文图表不一致（原文 "these labels don't match what's given elsewhere in the manuscript. For example, the current labels for the heteroatoms in the CIF of molecule 1a are B00P, O001, N002, N003 and N004 but in Figure 2, they are B, O1, N1 and N3. Please assign sensible labels... then update the figures and tables in the manuscript and SI to match the correct labels."）。
- 触发模式四：坐标表顺序随机（原文 "The atoms in the coordinate list and in all subsequent lists for these structures are in a random order in the CIFs. This is not best practice but fortunately is easily corrected. The atoms in the SHELXL .ins file... should be reordered to be in a logical sequence, the refinement redone and the CIF etc., remade. This will help the reader who wishes to use the CIF."）。
- 必做动作：SHELXT 解出的模型自带"四字符满编的混乱无序没有逻辑的原子编号"，必须重新设计有序、有逻辑、有化学意义的编号；特定骨架可用约定俗成编号（如吲哚），也可整体结构采用顺序逻辑编号（范例 CCDC 2152655）；在 ins 中按逻辑顺序重排原子后重新精修、重新生成 CIF；改完标签要同步更新论文与 SI 的全部图表。操作纪律（tid 1808）：PART、AFIX（56/66/116）、SAME、RESI 这类自带分组属性的指令**应在排序之后再加**，否则排序效果出不来。楼主强调："这些审稿意见无不表明审稿人对于原子标签以及原子排序相当重视……编号和排序等步骤尽量不要省略"。
- 数值阈值：无。
- 出处：tid 1814；tid 1777；tid 1804；tid 1808（同主题 tid 1816、1794 存根无正文）。

**B17. 重原子占有率不足（over-assigned 金属），指认错误或数据有病**
- 触发模式：审稿人自由精修作者的金属占有率并给出三种可能（原文 "The Cd atom refines freely to an occupancy of only 85% - this is either not a Cd atom, there is something else on this site, or it is due to issues in your data processing pipeline. Either way, you must identify the cause of this and eliminate it... The best way forward is to collect new data on this material."，RSC Adv.，CCDC 2371872）。审稿人还用残余密度图与分形维数图（Meindl & Henn 2008, Acta Cryst. A64, 404-418）可视化问题，并检验了"改精修为全占据 Ru"的备选（因键长不匹配而排除）。
- 必做动作：金属原子处出现负差值密度→自由精修其占有率验证；用键长排除换元素指认的可能；找不到化学原因时按审稿人要求重新采数（该例作者重测后发表）。注意审稿人的手段：他们会拿你的 hkl 自己精修并预告结果数值。
- 数值阈值：投稿数据 Cd 占有率自由精修 ~85%、R1 3.53%→2.82%；重测后发表数据自由精修 ~91.37%。
- 出处：tid 1821（tid 1481/1512 为同族 over-assigned 判据，见 B3/B4）。

**B18. 要求晶体数据在论文发表前公开（CCDC）**
- 触发模式：审稿原文 "Please confirm that the CCDC accession numbers will be made publicly available prior to your manuscript's publication."
- 必做动作：在 CCDC 后台把 Unpublished 数据以 CSD Communication 形式公开：Details → Publish in a Database → Authors 填申请人（或全部作者）→ Save，状态立即变 Published；论文发表后再回 Add Publication 补期刊信息。帖中另给出连带用法：CIF（含 hkl/res）太大超投稿系统限制时，可先公开到 CCDC 让审稿人凭号自取，或压缩 rar/zip 上传；已公开数据仍可按审稿意见修改更新。背景：数据自申请起有禁运期（例：2321180 禁运 10 个月），期间他人查不到。
- 数值阈值：无。
- 出处：tid 1827。

**B19. 重原子旁残余峰被误建成无序，实为非简谐振动（anharmonicity）**
- 触发模式：审稿原文 "The 'disorder' refinement involving the Re atom is incorrect. This is not disorder, but anharmonicity. When refining this, the residual peak will be of magnitude 0.6 and R1 will be 1.87%"（Dalton Trans. 2025，CCDC 2441907）。
- 必做动作：撤销重原子的假"二组分无序"，改做非谐波精修：olex2.refine 中选原子 `anis -a`（取消用 `anis`；实验性功能，官网警告 "open to abuse"）；可用 `MSDSView -a=anh -s=1.5` 查看非谐项形状（`kill MSDS` 关闭）；是否值得做可按 Kuhs 规则估计（0.074758·sqrt(n/U²) 给出区分谐/非谐所需的 sinθ/λ 分辨率，Kuhs, Aust. J. Phys. 1988, 41, 369-82）。（非谐精修属外部能力：olex2.refine 实验性功能，当前平台 MCP 工具不可执行，需人工操作并在 VALIDATION 披露。）
- 数值阈值：投稿版（假无序 0.857:0.143）R1 2.10%、Max Peak 0.5；不做处理 R1 4.41%、Q1 4.0/-2.4（触发 A 级 PLAT971）；非谐波精修后 R1 1.73%、wR2 4.32%、Max Peak 0.3/-0.7。
- 出处：tid 1832。

**B20. 未回应 B 级警报 / 回应渠道不对（PLAT430 假阳性范式）**
- 触发模式一：审稿原文 "Question 17: no response to B-level alerts."
- 触发模式二（二审）："I note that the proper way of responding to a B-level alert in a .cif file is to add a 'response form' in the .cif."（J. Mater. Chem. A 2025，CCDC 2369163）。
- 必做动作：所有 B 级警报必须逐条回应；正规渠道是在 CIF 内加验证回复表（Validation Reply Form）并更新 checkCIF 报告、同步更新 CCDC 上的 CIF，只写在 ESI 里不算"proper way"。PLAT430 的化学性解释模板（帖中回稿原文）：两个可成氢键原子距离 <2.9 Å 即触发，但本结构中两个 O 均来自硝基、彼此成氢键不合理；可引用有相同警报的先例文献（该例引 Dalton Trans. 2017, 46, 3240-3251, CCDC 1521260）佐证。楼主铁律：对硝基 O 做二组分无序确实能消掉 PLAT430 但不推荐，"晶体结构要的是合理的化学结构，而不是什么'没有AB级警报'这种罔顾科学事实的无理一刀切要求，而且不论是期刊还是审稿人，从未有过这种要求"。
- 数值阈值：PLAT430 触发距离 <2.9 Å（该例 O6–O1 3.141 Å 未触发可作对照）。
- 出处：tid 1838；通用触发句另见 "There are B level alerts in the author-generated checkCIF report that need to be addressed. The CIF should be examined and corrected, and an appropriate comment is required to explain the problem if it cannot be sorted out."（tid 1861、tid 1872 同一论文两数据均收到此句；具体解法见 B23、B25）。

**B21. 审稿人点名个别基团建无序 + 追问"模型是否缺溶剂"**
- 触发模式：审稿原文 "Compound 4: C38/42 should be modelled as disordered. As this is the weakest of the data sets and there is a single q peak (the largest one) left, is there a possibility that a solvent or anything else is missing in the model?"（Nat. Chem. 2024，CCDC 2354667）。
- 必做动作：不止处理点名的基团，差值图上形态相似的其余片段一并建无序（该例点名 1 处、实做 3 处相似片段）；标准限制对 SAME（组间几何）+SIMU（ADP）；残余峰在 -PMe3 反向位置且 P 疑非全占据→取向无序二组分，最大峰移位后再加第三组分；最后跑 PLATON-TwinRotMat，检出孪晶法则就加入精修。逐级验证 R 因子改善。
- 数值阈值：改善链 R1 7.83%→7.42%（点名片段+同类片段二组分）→7.14%（-PMe3 二组分，Max Peak 0.9→0.7，wR2 20.60%→18.45%）→6.95%（三组分）；孪晶法则入修 R1 7.14%→6.69%、wR2→17.90%。
- 出处：tid 1719。

**B22. PLAT220 被追问（"小问题，稍加用心即可解决"），先读懂警报文本再动手**
- 触发模式：审稿原文 "There is still a B alert in the Check_Cif which has been commented by 'Author Response: Due to disordered hexanes molecules.' ... But to me this seems to be a minor problem that can be solved with a little bit of care. Furthermore, how does squeeze - although I am not a fan of it - help here?"（Angew 2023，CCDC 2290011），泛泛归因"无序溶剂"的敷衍解释逃不过审稿人。
- 必做动作：逐字读警报描述定位对象，PLAT220 写明 "NonSolvent Resd 1 C Ueq(max)/Ueq(min) Range 10.0 Ratio"，是**非溶剂**残基的碳 Ueq 极值比过大，在溶剂上折腾注定无效（帖中两条弯路实录：①正己烷占有率减半→警报数值原封不动 10.0 且 R1/wR2 反升，且差图证明确应为 1 个正己烷；②Solvent Mask 遮掩→警报仍在还新冒 PLAT232）。真正病灶是无序异丙基第二组分甲基碳 C41A 的 Ueq 异常小（0.009），一条 `EADP C41 C41A` 即解决。判歧方向的信号：警报数值不变 + R 因子变差 = 方向错了。另注：同报告中 PLAT910（衍射点覆盖类）属数据收集问题、精修解决不了，审稿人也不会揪着它。
- 数值阈值：PLAT220 Ratio 10.0；病灶碳 Ueq 0.009。
- 出处：tid 1855。

**B23. PLAT241/PLAT250（椭球变形严重）→ 对症局部无序建模**
- 触发模式：通用句（见 B20 附注）+ 警报指向具体原子椭球变形（该例 PLAT241 指羧酸 O2/O11 椭球变形严重，PLAT250 亦由椭球变形引起）。
- 必做动作：顺着警报点名的原子找化学单元：羧酸 O 椭球变形→整个羧基二组分无序（或只拆两个 O）；若羧基所在苯环碳椭球同样变形→羧基连同苯环整体二组分无序。处理后复查警报与差图/椭球是否实质改善（该案结果恰为 AB 级警报清零，属案例记录；验收口径统一从 A23/B34：能解决的解决、解决不了的 VRF 解释，不以清零为目标）。顺手项：数据文件名（res/hkl/cif_od 一起）改成论文中化合物代号（Gd-L/Tb-L），呼应"数据名称"类意见。
- 数值阈值：无（该案结果为 AB 级警报清零；验收标准见 A23/B34）。
- 出处：tid 1861。

**B24. CIF 报告虚假键 / O–H 键长异常（PLAT415/414）**
- 触发模式：审稿原文 "This structure reports spurious bonds: Distance (K1-C2): 3.465(7). It also reports strangely long O-H bond distances: Distance (O1W-H1WB): 1.0846, (O1W-H1WA): 1.0824. If these are adjusted for neutron distances, then *all* X-H distances should be adjusted, but they are not."（New J. Chem. 2021，CCDC 1949331）。
- 必做动作：①虚假键：从连通性表删除，ins 加 `FREE K1 C2`（Olex2 选键输入 `delbond` 自动写入；对称等效键一并删，该例共删 3 根 K–C），或用 `CONN 6 K1` 按配位数限定最大成键数；②过长 O–H：删掉旧氢重新理论加氢（该例水在 3 次轴上，按特殊位置加氢流程）；过长 O–H 还连带氢间距 <2.1 Å 触发 B 级 PLAT415/C 级 PLAT414。一致性原则（审稿人原话）：若采用中子距离标准，则所有 X–H 都要统一调整，不能只调一部分。
- 数值阈值：假键 K1–C2 3.465(7) Å；异常 O–H 1.0846/1.0824 Å（中子距离量级）；PLAT415/414 触发条件 H…H <2.1 Å。
- 出处：tid 1866。

**B25. PLAT987（漏掉倒反孪晶）→ 倒反孪晶纳入精修（该案为 TWIN+BASF 两行）**
- 触发模式：通用句（见 B20 附注）+ B 级 PLAT987。
- 必做动作：ins 中加 `TWIN` 与 `BASF 0.5`（初值可取 0-1 间任意值），精修由程序补孪晶矩阵并修出批比例因子；平台对应 set_twin(law='inversion') → run_shelxl(mode='adopt')。纳入后按 flack-absolute-structure 卡核对 BASF/Flack 与收敛证据，"加了两行"不是终点，BASF 与 R/差图变化要能支撑第二域假设。帖中可重复性提示：同一数据同一电脑不同时期精修 BASF 0.07 vs 0.08，"这种现象其实挺常见也挺正常的"（单案观察，见导师裁决 10）。与 B12（审稿人点名倒反孪晶）同族。
- 数值阈值：该例 BASF 精修为 0.08（早前 0.07）。
- 出处：tid 1872。

**B26. 数据"真实分辨率"——按 I/σ 截断并重新积分**
- 触发模式：审稿原文 "The I/sigma drops below 3 at ~2theta = 45. The data should be truncated here and a note added to the experimental."；同批另一数据附加 "Looking at the HKLF instruction it seems that the cell has been changed after the initial integration, the data should really be reintegrated in the correct cell. This may also help to improve the Rint."（Dalton Trans. 2023，CCDC 2262742/2262744）。
- 必做动作：①用 Olex2 的 I/sigma vs resolution 图（3 sigma line：线上为 data、线下为 noise）或 xprep 分辨率壳层统计定位真实分辨率（I/σ 是证据之一，与 Rint/完整度壳层及 estimate_resolution 的 advisory 建议合读，见导师裁决 1）；②审稿人要求的是**回数据还原阶段截断**: APEX4 Reduce Data→Integrate Images→Resolution Limit 处设值重新积分（精修阶段 OMIT/SHEL 只是从精修排除数据、hkl 未变，"不知是否可以满足审稿人的要求"）；晶胞曾在初积分后改过的要在正确晶胞下重新积分（还能改善 Rint）；③实验部分加注说明；④回复模板（原文）："Effective data standards (I/sigma above 2) were applied to the new data integration process, thus the data were truncated by 0.84 Å (2θ = 50°). The new cif file have been updated in CCDC."；⑤截断致 theta_max 偏低会触发 A 级警报（sin(θmax)/λ <0.550），解释为晶体极限分辨率即可，"有AB类警报并不意味着数据无法发表，只要能对相应警报给出合理解释即可"。
- 数值阈值：审稿人阈值 I/σ=3（2θ≈45° 处跌破）；实操采用 I/σ>2 标准，两数据分别截至 0.84 Å（2θ=50°）与 0.91 Å（2θ=45.8°）；壳层示例 0.91−0.89 Å mean I/s 3.25、0.89−0.87 Å 降至 2.80；A 警报判据 sin(θmax)/λ=0.5477 <0.550。楼主反对一刀切："钼靶截 0.77 Å/铜靶截 0.83 Å"不可套用，极限分辨率因晶体而异，硬截到 0.77 Å 会掺入大量噪音，反之能衍射更高的截到 0.77 Å 也不合适。
- 出处：tid 1878。

**B27. 配位水氢原子朝向错误（审稿人附差值图指认）**
- 触发模式：审稿人附图指出氢的真实位置（原文 "It is easy to see where the hydrogen atom really must be (the green area) and where it shouldn't be (the red area)."，Dalton Trans. 2023，CCDC 2280242）。
- 必做动作：Ctrl+M 查差值图验证：正确位置呈绿色正密度（该例 Q1 位于 O5…O3 之间、O5–Q1–O3 近直线、O5–O3 2.764 Å——典型氢键几何），错误位置呈红色负密度；修正手段：直接调整氢位置，或删氢后按 Q 峰重新定氢。楼主结语：水分子氢位置的确定"应当考虑形成合理的氢键，通过残余电子密度峰（Q峰）、差值电子密度图或相关原子周围环境等手段综合考虑"，位置对了指标自然变好。
- 数值阈值：修正后 Max Peak 0.7→0.5、R1 3.54%→3.31%、wR2 9.75%→8.93%。
- 出处：tid 1889。

**B28. 审稿人建议加无序组分（CF3 二→三组分），组分数以能解释密度为准**
- 触发模式：审稿人认为结构 2、3 中 CF3 的二组分无序"改为三组分无序更佳"（Nat. Commun. 2023，CCDC 2208059–2208060）。
- 必做动作：先查限制的 esd 是否过强，该例 CF3 上挂了 ISOR 0.001/0.002 的强限制，把差图撑出假的"第三组分"需求；放宽到 0.01/0.02 后"电子云图和R因子立即得到改善"；最终全部 CF3 做二组分+SIMU，未按审稿人建议加第三组分，论文照样接收。同时把之前漏掉的明显无序 CF3 补建。楼主结语（原文）："应采用合理的标准偏差，不应采用过小的标准偏差致使限制作用太强而使模型偏离数据，当然，过大的标准偏差则使得限制命令无法达到预期效果。"
- 数值阈值：ISOR esd 反面教材 0.001/0.002，正解 0.01/0.02。
- 出处：tid 1891。

**B29. 特殊精修处理（孪晶/约束/限制）未在 SI 或 CIF 中说明理由**
- 触发模式：审稿原文 "it would be helpful if additional information on the crystal structure processing was provided in the supplementary information. For example, that two of the structures were pseudomerohedral twins, plus any constraints and restraints reported."；类似句 "The reasons for using the restraints and constraints should be given."（Nat. Commun. 2023）。
- 必做动作：把解析精修中的特殊情况（孪晶类型、每条约束/限制及其理由、无序处理）以文字写进 CIF 适当位置或论文 SI。警报解释范例（该论文 SI 对 PLAT090_ALERT_3_B "Poor Data / Parameter Ratio 5.54" 的回应原文）："A large number of parameters are increased due to large number of disordered groups in the structure, resulting in a decrease in the data/parameter ratio."
- 数值阈值：PLAT090 例值 5.54（Zmax>18 档）。
- 出处：tid 1734；tid 1891（其第一条审稿意见同型）。

**B30. 严重残余峰不能拿"吸收/截断"当万能借口（5% 红线）**
- 触发模式：审稿原文 "There is a very high residual electron density peak, which cannot be accounted for by absorption or truncation (as suggested by the authors) - this can only reliably explain electron density peaks of up to 5% of the electron density of the heavy element. In the current case, the electron density peak is even closer to a carbon atom than to the heavy atom! In the current state, the XRD data can only serve as a proof of connectivity in the best case... no bonding parameters could be discussed reliably."（Chem 2025，CCDC 2360390）。
- 必做动作：①吸收/截断解释只适用于 ≤重元素电子密度 ~5% 的残余峰，且峰必须贴近重原子，峰靠近碳原子时该借口不成立（5% 为该案审稿人的经验锚点 tid 1742，引用需注明出处、非普适红线）；②按差图真因处理：该例中央烯基片段二组分改三组分无序+把甲苯溶剂建模，残余峰 4.9→1.9；③若结构仍大量无序，可接受的降级表述是"数据仅作连通性证明、不讨论键长键角"（二审审稿人认可原文 "the authors note this and do not discuss geometric parameters so this is alright"）。二审补丁清单：同位置 Te 补 `EXYZ`+`EADP`；精修没收敛前就 OMIT 掉的、看起来不需要删的衍射点全部恢复（从 ins 删 OMIT 行，呼应 B8）；无序建模详情写入 CIF `_refine_special_details`（每行 ≤80 字符）。（EXYZ/EADP 为 SHELXL 指令，当前 set_restraints/edit_atoms 均不支持，属外部能力需人工执行。）
- 数值阈值：残余峰"吸收解释"上限 = 重元素电子密度的 5%；该例 Max Peak 4.9→1.9。
- 出处：tid 1742。

**B31. 论文实验部分与 CIF 的设备/光源信息互相矛盾**
- 触发模式：审稿人逐条对質（一审）"the experimental section of the paper says that the data was collected using graphite-monochromated Cu radiation, However, the CIF indicates that three structures were collected using Mo radiation... using a mirror monochromator, not a graphite monochromator"；（二审）"all seven CIFs have conflicting information about the diffractometer... they also say an APEXII detector was used even though D8 Ventures don't typically come equipped with this detector. Instead, they typically have Photon detectors... Please verify exactly what equipment was used and make sure it is accurately reported in the CIFs and in the manuscript's experimental section."（Inorg. Chem. 2024，CCDC 2384354–2384360）。
- 必做动作：写论文实验部分前用记事本打开 CIF 核对 `_diffrn_radiation_type`（光源）与 `_diffrn_radiation_monochromator`（单色器），确保论文与全部 CIF 一致；核实真实硬件后统一更正（该例把误填的 "mirror" 改回 "graphite"）。楼主总结："其实就一个原则，实事求是"。警示：审稿人熟悉硬件搭配（D8 Venture 不配 APEXII 探测器而配 Photon 系列），编造会露馅。
- 数值阈值：无。
- 出处：tid 1757。

**B32. 无 AB 级警报 ≠ 结构正确（溶剂原子指认错、图文分子式矛盾）**
- 触发模式：审稿意见（中文原文）："作者在正文图1给出的配合物2的结构中溶剂为DMF，但CIF中溶剂是C4H7O，请更正；正文表1中的配合物2分子量使用的也是CIF中错误结构的分子量。"（Chin. J. Inorg. Chem. 2024，CCDC 2354708）。
- 必做动作：差值图复核溶剂原子指认，该例 C23 定小了、实为 N（应为 DMF）；指认正确后差图无异常；正文分子量等衍生数值同步更正。此类错误可能只触发 C 级警报（该例 PLAT244 提示 C23）而无 AB 级警报。楼主原则句："CheckCIF/PLATON 系统能够检查一致性、规范性等基础问题，对于结构是否正确，还是需要人来评判……没有AB级警报不代表结构一定正确……反之，即便有警报也不代表结构错误"。
- 数值阈值：无。
- 出处：tid 1920。

**B33. 元素分析分子式与晶体结构分子式不一致被追问**
- 触发模式：审稿意见（中文原文）："第4页给出的配合物2的元素分析……也即没有溶剂。在做元素分析时，样品是如何处理的？"（CIF 总分子式含 2 个 DMF：C48H48NiN6O4；元素分析按无溶剂主体 C42H34NiN4O2 计算）。
- 必做动作：回复说明样品处理方式（该例回复：元素分析样品经加热油泵抽干处理，故无溶剂）。原则：同一批未处理样品做 EA 与单晶时两个分子式应一致；样品经历不同（纯化引入溶剂、结晶溶剂进格子）时不一致属正常，但必须能说清楚，"分析结果要和具体样品对应，最重要是要（及时）做好实验记录"。
- 数值阈值：无。
- 出处：tid 1938。

**B34. "不能有 AB 级警报"是伪律，审稿人接受带警报发表，条件是 VRF**
- 触发模式：通用审稿意见（常置于晶体意见首尾）原文 "Please use CheckCif as a guide in the final preparation of these structures. There should be no CheckCif A or B alerts remaining, and if any of them do, you must provide relevant and meaningful vrf entries."
- 必做动作：能解决的 A/B 级警报尽量解决；确实无法解决的以验证答复表（vrf, validation response form）给出相关且有意义的解释，满足此条件审稿人可以接受带 AB 级警报的数据发表。楼主正名：验证报告条目全部是 alert（警报/提示）而非 error（错误）；"必须消除AB级警报/有AB级警报不能发表"是流传甚广的无理要求（学生和不少导师都固执持有），与期刊/审稿人实际要求不符（与 B20 楼主铁律同源）。
- 数值阈值：无。
- 出处：tid 1895。

**B35. 温度缺标准不确定度**
- 触发模式：审稿原文 "Check the uncertainties quoted for the temperatures used, as some are missing."
- 必做动作：CIF 的 `_cell_measurement_temperature` 与 `_diffrn_ambient_temperature` 应带标准偏差（193.00(10) 表示 193.00±0.10 K，温度是范围而非确定值才合理）；精修生成的 CIF 一般自带，缺失时手动补：Olex2 在 Report→Diffraction 填写，且 ins 中要写 TEMP 指令，否则可能触发 B 级 PLAT196。
- 数值阈值：温度偏差一般取 ±1~2 K。
- 出处：tid 1901。

**B36. CIF 解析方法字段空缺（_atom_sites_solution_*）**
- 触发模式：审稿原文 "A couple of fields seem blank after re-refinements: '_atom_sites_solution_hydrogens', '_atom_sites_solution_primary ?', '_atom_sites_solution_secondary ?', please add for completeness."
- 必做动作：把 CIF 中 `_atom_sites_solution_primary`（初级结构解法）、`_atom_sites_solution_secondary`、`_atom_sites_solution_hydrogens`（氢定位方法）三个条目按 CIF 核心词典定义填全（帖中给出 IUCr 词典网址与定义出处；重精修后这些字段容易被清空，交稿前检查）。
- 数值阈值：无。
- 出处：tid 1907。

**B37. 无理由的分辨率截断被审稿人反查（B26 的反向情形）**
- 触发模式：审稿原文 "Data on these compounds were collected to two-theta = 55°, whereas the structures presented use only data to two-theta = 50°, without any comment on their reasons. I calculate that about 50% of reflections between 50° and 55° have I > 2σ for 1 and 2. Normally, one would not abandon such data... The authors should explain their reasons for these two decisions, or else correct them."（Acta Cryst. C 2025，CCDC 2416520），审稿人自己统计了被截区间的有效衍射占比。
- 必做动作：核查截断是否站得住：删除 ins 中的 `OMIT -3 50`，用 I/σ(I) vs Resolution 图（3 sigma line）和 XPREP 壳层统计判断；该例 0.76–0.77 Å 壳层 I/σ 仍有 2.09（>2.0 属有效数据），"完全没有理由用OMIT指令截去……区间的数据（能说得过去的理由大概就是这部分数据的完整度偏低）"→处理就是删掉 OMIT 指令重新精修。要么给理由要么改正；与 B26 合成完整判据：截到噪音起点为止，既不带噪音也不弃有效数据。
- 数值阈值：有效数据判据 I/σ≥2.0（该帖明言"高于2.0为有效数据"）；审稿人统计被弃区间 ~50% 反射 I>2σ 即不可弃。
- 出处：tid 2344。

**B38. 多个结构测试温度不一致被要求复核**
- 触发模式：审稿原文 "The crystallographic data tables indicate that data for one compound was collected at 293(2) K, while the other was collected at 273(2) K, which should be double-checked."
- 必做动作：核对真实测试温度，"只要数据实事求是，不弄虚作假即可"；确需修改则改后重新精修生成新 CIF 并更新 CCDC 数据库，再正常答复；无需修改则直接答复确认。楼主定性：这类属审稿人"带着疑问顺带一提"的小问题。
- 数值阈值：无。
- 出处：tid 2539。

**B39. fcf 数据格式（LIST 6→LIST 4）、SI 差值图极值、对映纯声明**
- 触发模式：审稿原文 "The final difference map max. and min. need to be added to the tables in the SI. Intensity data in LIST 6 rather than LIST 4 format predominate (see Checkcif alerts). It would be useful to state explicitly which crystal structures are enantiopure."
- 必做动作：①ins 中 `LIST 6` 改 `LIST 4` 重新精修再生 CIF（LIST 参数决定 fcf 中衍射点列表格式）；②SI 晶体表格补最终差值电子密度 max/min；③正文明确声明哪些结构是对映纯。（LIST 为 SHELXL 指令：当前平台 run_shelxl 不暴露该参数，属外部能力，需人工改 ins 执行。）
- 数值阈值：无。
- 出处：tid 2562。

**B40. 建议在精修中加入消光校正**
- 触发模式：审稿原文 "The refinement would benefit from the inclusion of an extinction correction."
- 必做动作：ins 命令区加 `EXTI` 指令精修消光参数；用 Olex2 则在 Work→Refine 勾选 EXTI 复选框（程序自动写入 ins）。（EXTI 为 SHELXL 指令：当前平台 run_shelxl 不暴露消光精修参数，属外部能力，需人工或未来工具支持。）
- 数值阈值：无。
- 出处：tid 2566。

**B41. 无序模型被质疑"也许是孪晶重影/吸收问题"、且不同机制被绑进同一组分（Nature 案例）**
- 触发模式：审稿原文（节选）"is it obvious to me that this is indeed disorder, but rather a modelling of (potentially) something else: maybe the crystal data presented some degree of twinning and what they are modelling is simply ghosting from a secondary component? Or perhaps there is an issue with the absorption correction method?... the ring has rotational disorder, whilst the other fragments are displaced by roughly 0.3 Å, so these two are not the same disorder component... I wouldn't recommend solely focusing on obtaining the lowest R1, but rather present a more realistic model."（Nature 2025，CCDC 2374582）。
- 必做动作：①重新长晶重新采数，正面排除孪晶与吸收校正两种替代解释后再谈无序（回稿原文 "we grew new single crystals and collected the data again. We analyzed the new data and excluded the reasons of twinning and absorption correction"）；②不同机制拆分建组：环旋转无序（part 1/part 2）与整体平移无序（part 1/part 3）分开设组分；③小占有率组分只建电子密度足以支撑的原子，part 3 仅建 Os、P，不硬修 C（回稿原文：全修 C 需堆大量限制、结果"messy"且"对确认分子结构没有帮助"）；④牢记审稿人价值观："不建议只关注最低 R1，而是提出更真实的模型"。
- 数值阈值：平移量 ~0.3 Å（审稿人识别两机制的依据）；旋转无序占有率 0.51369/0.48631（发表值 0.514(4)/0.486(4)）；平移无序 0.90753/0.09247（第三组分 0.0925(9)）。
- 出处：tid 2569。


## 高频重题统计（B 部）（出现 ≥3 帖的主题，候选独立技能卡素材）

计数含标题可辨的存根/图片帖（标注"含存根"），按本区间 80 帖统计：

1. **溶剂遮掩（SQUEEZE/Solvent Mask）的使用、说明与后果**: 9 帖：1489、1498、1608、1561、1844、1536（存根）、1547（存根）、1552（存根）、1568（存根）。核心可立卡：遮掩披露四件套（种类+数量+分子式+引文）、遮掩前配位球检查、遮掩 vs 建模的选择。
2. **无序处理类审稿意见（点名建模/组分数/机制质疑）**: 8 帖：1634、1685、1695（存根）、1707、1719、1742、1891、2569。核心可立卡：审稿人点名之外同类片段全建、组分数以差图证据为准不盲从、机制分组。
3. **氢原子处理**: 8 帖：1448、1458（存根）、1472（图片）、1630（存根）、1707、1866、1889、1568（存根，游离水加氢）。核心可立卡：氢原子确定方式描述模板、活泼氢/水氢的定位与朝向、X–H 距离标准一致性。
4. **checkCIF AB 级警报的回应义务与具体解法**: 7 帖：1322（存根）、1838、1855、1861、1866、1872、1895。核心可立卡：VRF（验证回复表）流程 + "警报≠错误、解释即可发表" + 按警报文本对症（PLAT220/241/250/415/430/987 各有成例）。
5. **原子编号/标签/排序**: 6 帖：1814、1816（存根）、1777、1794（存根）、1804、1808。核心可立卡：SHELXT 乱码标签必改、ins 内逻辑排序重精修、CIF 与论文图表标签一致、分组指令在排序后加。
6. **残余峰解释（金属/重原子旁）**: 6 帖：1334、1634、1695（存根）、1719、1742、1832。核心可立卡：吸收借口 5% 红线、无序/孪晶重影/非谐振动三种解释的排除顺序。
7. **删点与分辨率截断（OMIT 纪律）**: 6 帖：1580（存根）、1586、1621（存根，完整度）、1878、2344、1742（二审）。核心可立卡：真实分辨率判定（I/σ 壳层）、双向红线（不弃有效数据、不留噪音、删点须有理由）。
8. **孪晶相关（法则加入/倒反孪晶/排除孪晶）**: 6 帖：1586、1672（存根）、1685、1719、1872、2569。
9. **测试/设备/软件条目信息一致性**: 5 帖：1757、1359（存根）、1576（存根）、1662（存根）、1666（存根）。核心可立卡：论文实验段与 CIF 逐项核对清单（光源/单色器/衍射仪/探测器/软件/吸收校正）。
10. **溶剂建模与混占无序（含 over-assigned）**: 6 帖：1481、1511（存根）、1512、1520（存根）、1634、1644（存根）。
11. **晶胞参数/温度等数值条目规范**: 5 帖：1342（存根）、1350（存根）、1625（存根）、1901、2539。
12. **数据还原晶胞正确性**: 3 帖：1909（存根）、1912（存根）、1878（其第二条意见）。

## 存疑/冲突记录（B 部：定调见头部导师裁决）（帖间说法矛盾或张力处，导师精编时裁决）

1. **遮掩 vs 显式建模的优先序**：tid 1634 中楼主方案（水三组分建模）与作者方案（Solvent Mask 遮掩）都被期刊接收，帖内并列保留；但存根标题 tid 1536"溶剂能建模的应当建模而不是遮掩了事"、tid 1552"溶剂遮掩不如建模省事"显示楼主立场倾向建模（正文缺失，无法引证细节）。tid 1489 则给出遮掩的硬下限（配位配体不可遮）。三者不矛盾但强度不同，建议合并表述为"能认出形状的建模、认不出的才遮、配位的绝不遮"。
2. **遮掩程序选择**：tid 1561 审稿人因 Rigaku 设备要求换用 Olex2 Solvent Mask，楼主认为"用哪个程序都没有硬性规定"但建议顺从审稿人；tid 1855 审稿人自称 "although I am not a fan of it（squeeze）" 却仍建议试用。审稿人个人偏好差异大，规则应写成"程序无定规，披露是硬规，审稿人点名就照办"。
3. **I/σ 截断阈值 2 还是 3**：tid 1878 审稿人以 I/σ<3（2θ≈45°）为截断依据，作者却按 I/σ>2 标准截断（0.84 Å/0.91 Å）回复并被接受；tid 2344 楼主明言"高于2.0为有效数据"。阈值 2 与 3 并存于语料，实操上"审稿人说 3、作者用 2 也过关"，建议规则写区间并注明出处。
4. **OMIT 截断分辨率的合法性**：tid 1586 审稿人称 OMIT 0 50 限分辨率"not generally recommended"但可接受；tid 2344 审稿人则对 OMIT -3 50 截掉 I/σ≥2 数据直接要求删指令；tid 1878 审稿人反过来要求截断且要在还原阶段截。三帖合读结论：截不截以数据真实质量为准、必须给理由，精修阶段截断（OMIT/SHEL）与还原阶段截断（重积分）审稿人认可度不同（1878 明确要求后者）。
5. **审稿人建议加无序组分是否照办**：tid 1891（CF3 二组分顶住"加三组分"建议，靠放宽 ISOR 获接收）vs tid 1719（-PMe3 主动从二组分加到三组分、R 持续下降）。两帖合读：以差图证据与 R 改善为准，既不盲从也不抵触。
6. **重原子旁大峰的三种解释竞争**：tid 1832（审稿人判"非无序而是非谐振动"，非谐波精修后指标全面优于假无序模型）、tid 2569（审稿人疑"孪晶重影或吸收"，作者重测排除后仍按无序处理）、tid 1334（低温重测不改善，最终以吸收伪影书面解释过关）。同一表象三种归因，语料未给统一判定树，建议精编时补一条"排除顺序"元规则（这是笔者归纳的空缺，语料只有分立案例）。
7. **精修结果的可重复性容差**：tid 1872 同一数据、同一电脑、同一程序、不同时期 BASF 0.07 vs 0.08，楼主称"挺常见也挺正常"。对 CrystalPilot 基准复现的启示：孪晶比例等次要参数存在 ±0.01 级别漂移属正常，不应视为复现失败。
8. **1838 与 1895 的表述张力**：1838 楼主痛斥"消除AB级警报"的一刀切要求"从未有过"，但 1895 引用的通用审稿意见原文确实写着 "There should be no CheckCif A or B alerts remaining"——只是后半句允许 VRF 解释。两帖立场一致（解释即可），但引用时须完整引句，避免断章。
