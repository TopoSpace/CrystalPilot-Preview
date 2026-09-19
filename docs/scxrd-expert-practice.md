# 单晶结构解析专家知识库（SCXRD Expert Practice）

> 本文是 2026-09-03 调研的**知识侧完整记录**，与 `docs/scxrd-expert-knowledge-review.md`（那份是"知识 × CrystalPilot 现状"的对照分析与路线图）配套但独立。
> 这一份不谈我们的代码，只整理**领域本身**：厂家/设备/软件的操作规程、人类专家的流程与判断依据、失败模式与识别方法。
> 目标读者是要仔细研读的人，因此**所有关键论断都附一手来源的英文原文引语**（verbatim，不翻译、不改写），中文是解释。

---

## 阅读约定

**1. 数字一律是证据，不是阈值。** 本文出现的每一个数字（CC1/2 0.2、R1 0.10、|E²−1| 0.736、μ·t 3.0、δsym 0.25 …）在其原始来源里几乎都伴随着"适用条件"或"这不是硬规则"的说明。我尽量把那些限定条件一并抄下来。看到数字时请连着限定条件一起读，**脱离条件的阈值就是本文最想反对的东西**。

**2. 证据强度标注。**
- 【一手·逐字】= 已取得来源原文引语。
- 【一手·单次】= 抓取时取得逐字原文，但复核时页面不可达（多为 IUCr 403）。
- 【转述】= 只有检索层面的转述，未取得逐字原文。
- 未标注者为常识性背景或多来源交叉共识。

**3. 文档分两部分。**
- **第一部分（第 0–10 章）** 按解析流程走：采集与还原 → 孪晶 → 空间群 → 求解 → 精修 → 模型诊断 → 验证与发表 → 自动化的历史教训 → 3D-ED。
- **第二部分（第 11–16 章）** 是第二轮针对缺口的补编：指标化与积分 → 化学层验证与特殊位置 → Linden 的 best practice → 反常散射与波长 → 精修的判断力 → 病态结构分类学。
- **文末两个附录**（数值锚点速查表、来源清单与证据强度）**同时覆盖两部分**。

**4. 一条要先说的元结论。** 第二部分反复撞到同一个逻辑结构：**这些统计量与判据几乎都是单向证据**：异常指示有问题，正常**不**构成没问题的证明。Watkin 说"结构看起来不对，多半就是不对；反之不成立"（§15.4）；Linden 说"一份干净的验证报告不必然意味着一切正常"（§13.6）；Xtriage 说"大的 Z 分数可以指示孪晶，但小的值并不排除它"（§16.11）。**任何把这类指标实现成双向通过/不通过判据的做法，都误用了它们。**

---

## 第 0 章 总纲：专家共识的四条底层原则

这四条几乎在每一份权威来源里都被独立重述过，是整份知识库的骨架。

### 0.1 R 因子不能证明结构正确

Raymond & Girolami, *Acta Cryst.* C79 (2023) 445–455【一手·逐字】：

> "Note that incorrect crystal structures often have good R values (least-squares residuals) and that these values are of little or no use in deciding whether a structure is correct, although they may help to decide which of two possible structural models is `more correct.'"

Müller 2009 的经典演示：同一个中心对称结构，错误地在 P1 中精修得到 R1 = 0.0636 / wR2 = 0.1862，正确的 P-1 无约束精修得到 R1 = 0.0635 / wR2 = 0.1870 - **两者几乎相同**，但 P1 里 24 个芳香 C–C 键散布在 1.324(14)–1.465(12) Å，P-1 里 12 个独立键只在 1.382(4)–1.398(4) Å【一手·逐字】：

> "the 24 distances between aromatic carbon atoms vary from 1.324(14) Å to 1.465(12) Å with an average bond distance of 1.39 Å. [...] This is typical for an overlooked inversion centre, as bond lengths and other parameters that should be identical if the structure was refined in the centrosymmetric space group will be highly correlated. [...] the residual values of the refinement in P-1 are comparable to the unrestrained P1 refinement [R1 = 0.0635 for F > 4σ(F), wR2 = 0.1870 for all data]. Clearly, P-1 is the correct space group [...] the structure in P1 is simply wrong"

Clegg 2019 补充了一条更细的推论：**低对称模型参数更多，本来就该给出更低的 R**，所以 R 甚至不能用来在高低对称之间做选择【一手·逐字】：

> "While the triclinic setting is clearly preferred on the basis of Laue symmetry (Rint), the refinement R factors are more ambiguous, as lower values are expected when more parameters are refined in a lower-symmetry model, and the monoclinic setting gives a cleaner difference map. So, with conflicting evidence, which is the correct solution?"

### 0.2 每个统计判据都有文档化的失效条件

最典型的是 |E²−1|。Bruker XPREP 手册自己写明【一手·逐字】：

> "Mean |E*E-1| = 1.047 [expected .968 centrosym and .736 non-centrosym] ... such statistics may be unreliable if heavy atoms are present (especially when they lie on special positions) or if there are very few reflections in one of these three projections. Twinned structures may give an acentric distribution even when the true space group is centrosymmetric."

SADABS 手册对同一统计量给出**另一组**失效条件与诊断价值【一手·逐字】：

> "In the plot of |E2-1| as a function of resolution, the curve should stay close to the 0.968 line for a centrosymmetric structure or the 0.736 line for a non-centrosymmetric structure, especially for large organic or macromolecular structures. Values that are uniformly lower than expected may indicate twinning, and values that are uniformly higher than expected may be caused by pseudo-translational symmetry. A systematic drop or rise at high resolution may indicate problems with the SAINT integration (e.g., integrating data that were not present). [...] For inorganic structures with heavy atoms on special positions, this plot is less reliable."

Clegg 2019 则记录了一个实测反例：金属配合物的 |E²−1| 常落在心与非心之间，**根本给不出判断**【一手·逐字】：

> "Intensity statistics were unhelpful, the mean |E² − 1| lying between typical centric and acentric values, but this is not unknown for such metal complexes."

**读法**：|E²−1| 是证据，其可信度随"是否有重原子/重原子是否在特殊位置/投影反射数/是否孪晶/是否赝平移/结构是有机还是无机"而变。一个只报数字不报条件的工具，等于在制造错误结论。

### 0.3 化学优先于统计

Clegg 2019 的三个案例全都靠**非晶体学证据**才裁决对：例 2 的关键是"化合物是对映体纯的，所以必须是 Sohncke 群"；例 3 的关键是化学家坚持环己烷环必须是椅式而不是平面【一手·逐字】：

> "Chemists insisted that the rings are cyclohexane rather than benzene and should, therefore, be chair-shaped instead of planar."

Clegg 的结论是三句话【一手·逐字】：

> "In conclusion, the advice is: do not trust entirely in automation; do not rely unthinkingly on validation procedures; take note of all relevant available information."

### 0.4 自动化只对常规结构有效：而这正是它的危险

Müller 2009【一手·逐字】：

> "It is evident that (semi)automated structure determination works only for routine structures. In more complex cases, such as structures with disorders, pseudo-symmetry or twinning, crystallographic knowledge, refinement skills and experience are still vital for obtaining high-quality, publication-grade crystal structures."

Clegg 2019 把"不需要晶体学专业知识"这句卖点直接指认为失效模式【一手·逐字】：

> "On the negative side, we can use the same words: it removes the need for crystallographic expertise, which means that potential problems may lie undiscovered, the new structure being in some way defective or misleading, or the automatic procedures used being inappropriate for the underlying structural questions being asked. Non-routine issues such as twinning, structural disorder, and modulated structures (both commensurate and incommensurate) are often poorly treated, or completely overlooked, by automatic software, and require individual personal attention by an expert."

Müller 还明确点名了**哪些决策靠经验而非规则**【一手·逐字】：

> "The decision of which crystal to pick from a batch is mostly experience driven, and so to can be the choice between two space groups in the presence of pseudo-symmetry. The answer to the question of whether a specific disorder is worth refining is as much based on experience as the assessment of data quality and difference density maps."

**这四项就是"应当留白给判断"的清单**：挑哪颗晶体、赝对称下两个群怎么选、某个无序值不值得建、以及数据质量与差值图的整体评估。它们不是还没写好的规则，而是**作者本人认为不该写成规则的东西**。

他自己对这门手艺的概括【一手·逐字】：

> "there are only three things a crystallographer needs: basic understanding of diffraction theory and general chemistry, patience, and practice in the use of constraints and restraints."

（**注意这三样里没有一样是阈值表**：理论理解、耐心、以及**约束与限制的使用熟练度**。第三样是唯一的"技能"，而它恰好是第 5 章与第 15 章反复出现的那件事。）

---

## 第 1 章 数据采集与还原

### 1.1 "好数据"的数值锚点

Müller 2009 给了一套最常被引用的数字，但同时声明**没有任何一项有公认的硬界限**【一手·逐字】：

> "A good dataset must be complete (in most cases 99% or even 100% completeness can and should be obtained), and for small molecule structures, the International Union of Crystallography (IUCr) requires a good dataset to extend to at least 0.84 Å resolution. A reasonable value for MoO should be above five to seven for area detector data, but double digit MoO-values are preferable. The value for I/σ should be as high as possible (at least 8–10 for the whole dataset), while the lower the merging R-factors are the better (most small molecule datasets should show Rint values of below 10% for the whole resolution range). As pointed out before, weak data contain important information and must not be excluded from the dataset [...] There is no generally accepted limit for any of the above mentioned qualifiers, but many crystallographers agree that data with values of ⟨I/σ⟩ ≤ 2.0 and/or Rint ≥ 0.45 throughout the entire resolution shell are to be considered as noise. In practice, there may be more factors to be taken into account and, as always, experience helps. [...] the IUCr community agreed practice currently recommends a minimum data-to-parameter ratio of eight for non-centrosymmetric structures and 10 for centrosymmetric structures. This corresponds to a resolution of about 0.84 Å or a 2θmax of 50° for Mo-Kα radiation and 134° for Cu-Kα, respectively."

Spek 2020 的版本（措辞为 good practice 而非 rule）【一手·逐字】：

> "collect diffraction data up to at least copper sphere resolution, i.e. sin (θ)/λ = 1/1.5418 = 0.65 Å−1" … "data sets are expected to be at least complete up to that value (i.e. ∼25° in θ for Mo Kα)" … "A sensible cut-off value might be a value beyond which there is only noise"

CrysAlisPro 手册把这些做成了可覆盖的按钮【一手·逐字】：

> "Clicking on the IUCr limit button reduces the coverage to 98.5%, which is the minimum required for publication in an IUCr journal. [...] D. Time prediction: shows the predicted exposure times, based on the pre-experiment data and desired I/sigma value (usually set to 15 for good quality data). These values can be overridden by the user. [...] When collecting with copper radiation, it is usually necessary to collect for a longer time at higher angles (a ratio of 1:4 is recommended)."

同一手册对"过滤数据"给出警告【一手·逐字】：

> "NOTE: Filtering data will inevitably lead to a loss of completeness. For this reason, filters should only be used when absolutely necessary"

### 1.2 积分与"定稿"是两件事

这是厂家管线里最容易被外行忽略的结构性事实：**积分产生未合并未缩放的强度，定稿（finalization）才施加劳厄对称、空间群、吸收校正与逐帧缩放**；定稿可以反复做而不必重新积分。CrysAlisPro 手册【一手·逐字】：

> "The last step of the data reduction process is finalization, in which a *.hkl and *.mtz file is generated from the *.rrpprof file by applying the Laue symmetry, space group, multiscan absorption correction and frame scaling (both using the ABSPACK module). Data can be refinalized repeatedly using differing parameters, generating several *.hkl and *.mtz files. [...] 3. Absorption Correction: A face-indexed absorption correction can be applied (provided the crystal shape has already been determined by ticking the Apply absorption correction box in the top right corner of the window. A spherical absorption correction can also be applied by ticking Apply next to the Spherical abs button and then entering a suitable value for *r, where r is the average radius of the crystal. 4. Sigma calculation control: Possible to change the sigma error model and rejection criteria for overlapped reflections 5. Limits, filters & lattice extinction filters: set a negative intensity sigma limit, change the resolution limits, and apply filters used for discarding outlier peaks and images."

对"有问题的数据集"，手册明确要求人接管【一手·逐字】：

> "For problematic data sets it is often useful to process data with some manual influence over the settings used."

具体人要选的东西包括：孪晶组分晶胞或非公度 q 矢量、编辑 run 列表、样品移动模型（moderate wobble / significant wobble / discontinuous jumps）、背景模型从 Average 换成 Smart、按劳厄群做离群剔除。

### 1.3 吸收校正：方法选择有一条 IUCr 成文规则

checkCIF 过程 ABSTM_02 把"该用哪种吸收校正"写成了可计算的判据【一手·单次】：

> "IF mu * tmid > 3.0 exit and issue ALERT A 'Alert A Crystal and compound unsuitable for non-numerical corrections. Product of mu and tmid > 3.0' When the product of the linear absorption coefficient (mu) and the median crystal dimension (_exptl_crystal_size_mid) is greater than 3.0, the application of a numerical or analytical absorption correction based on the indexing of the crystal faces is considered to be compulsory. [...] If, despite all efforts, a regularly shaped crystal cannot be obtained, or the crystal is immersed in oil, and the faces cannot be indexed adequately, empirical or multi-scan absorption corrections may be acceptable, PROVIDED the experimental and predicted values of Tmin and Tmax do not differ significantly."

注意最后那句**判断式逃逸条款**——μ·t>3.0 是"触发审视"，不是"禁止"。

ABSTM_02 还给出完整的期望透过率计算法与两套分级（**两套阈值属于不同分支，不要混**）【一手·单次】：

> "Tmax(shape) = EXP(-tmin * mu) Tmin(shape) = EXP(-temx * mu) Tmin(shape)'= EXP(-tmax * mu) where temx = MAX{tmid, MIN[(1.2*tmid), tmax]} [...] RR = RT(exp) / RT(rep) [...] IF _exptl_absorpt_correction_type ~ 'refdelf' OR 'empirical' OR 'psi-scan' OR 'multi-scan' THEN IF RR' OR RR > 2.00 issue ALERT A [...] IF RR' OR RR > 1.50 issue ALERT B [...] IF RR' OR RR > 1.10 issue ALERT C [...] ELSE IF _exptl_absorpt_correction_type ~ 'numerical' OR 'analytical' OR 'gaussian' THEN IF RR' OR RR > 2.00 issue General ALERT"

> "ELSE IF _exptl_absorpt_correction_type ~ 'none' THEN IF RT(exp) > 1.30 issue ALERT A (2) 'Alert A The ratio of Tmax/Tmin expected RT(exp) is > 1.30 An absorption correction should be applied.' IF RT(exp) > 1.20 issue ALERT B (2) [...] IF RT(exp) > 1.10 issue ALERT C (2)"

即：**multi-scan 类用 RR（期望比/报告比）分级 2.00/1.50/1.10；声明"未校正"用 RT(exp) 分级 1.30/1.20/1.10；同样的数值不符，非数值校正被罚得远重于数值校正。**

IUCr 规定的**响应顺序**是诊断而非改数【一手·单次】：

> "Alerts of this nature need to be addressed carefully. First check that the crystal dimensions given in the CIF do represent the actual crystal dimensions as closely as possible. [...] It should normally be possible to estimate the crystal dimensions to 2 decimal places. Rough estimates to only 1 decimal place may be too inaccurate to provide reliable estimates of Tmin & Tmax. [...] Even if the crystal is only weakly absorbing, numerical and analytical corrections are still the most reliable and realistic method. If the multi-scan method (e.g. SADABS) has been employed and there are discrepancies in the spread of the Tmin & Tmax values, one needs to be sceptical of the correction, particularly if the experimental Tmin is much smaller than predicted as this implies that an overly extreme correction is being applied to some reflections. [...] Corrections of the DIFABS type should normally be avoided if at all possible."

还有一条常被误解的：multi-scan 报的透过率是**相对标度**，IUCr 只比较比值，必要时重新标定发表值而**不改变实际施加的校正**【一手·单次】：

> "Confusion often arises here because the experimental and predicted values of Tmax are given on a different scale. This of itself is unimportant. [...] Since the ratio of scaled T's is identical to the ratio of reported T values, the scaling does not imply a change to the absorption corrections used in the study. It simply places the published T values on an absolute scale with respect to the crystal dimensions and the crystal mu value."

### 1.4 multi-scan 吸收模型的内部参数与盲点（SADABS）

球谐阶数按吸收强度选【一手·逐字】：

> "If absorption is small, we recommend the default values of 4 and 1; for moderate absorption, 6 and 3 are suitable; and for strong absorption, 8 and 5. Theoretically, the odd order can be lower if the crystal shape is centrosymmetric. [...] In many cases the general spherical harmonic treatment (with orders 8 and 5) is just as good and converges significantly faster."

**关键盲点**：多扫描方法在原理上无法建模各向同性的 θ 依赖吸收，因为等效反射共享同一个 2θ【一手·逐字】：

> "This correction is included because the theta-dependent part of the absorption cannot be modeled well by comparing equivalent reflections, because these invariably have the same 2-theta values. However, the correction should not be applied if absorption is absent. The main affect of applying it will be to increase the equivalent isotropic displacement parameters in the resulting refinement."

（即：可选的球形 μ·r 校正是补这个洞的，但没有吸收时施加它只会把 Ueq 抬高。）

### 1.5 误差模型：形状判据而非单一数字

SADABS 的误差模型与其验收标准【一手·逐字】：

> "su2(Ic) = k [σ2(Ic) + (g<Ic>)2 ] where k is a scaling factor and su(I) is the corrected standard uncertainty of the corrected intensity Ic [...] The best test of success in establishing a good error model is that the Postscript plots of χ2 against intensity and against resolution should be horizontal lines with χ2 equal to one."

并且要求把 SAINT 的 instrument error factor 设为 0【一手·逐字】：

> "we strongly recommend that you set the 'instrument error factor' to 0 when processing the data with SAINT. A non-zero value can make it impossible for SADABS to find a good error model."

DIALS 的两参数版本，其**refined 值本身就是数据质量诊断**【一手·逐字】：

> "the a value is expected to be close to 1, with a b value around the range of 0.02–0.04"

AIMLESS 的三参数版本与其诊断图【一手·逐字】：

> "If it slopes upwards, then σ(I) is too small for large I, so SdAdd should be increased [...] > 6 σ (I) from the mean of other observations of equivalent Ihkl [...] is likely to be unreliable in the presence of serious pathologies."

（最后半句指 Emax 归一化强度检验在各向异性、孪晶、tNCS 存在时不可靠。）

### 1.6 缩放模型的过拟合与 free-set 检验

DIALS 论文的核心告诫【一手·逐字】：

> "an increase in precision does not necessarily lead to a more accurate data set"

做法是留出约 10% 的对称等效组做 free set，看 Rmeas 的 work/free 差；选 Rmeas 而不是 Rpim/CC1/2 是因为它与多重度无关且 CC1/2 都贴近 1。默认 physical model（scale + decay + 球谐吸收 lmax=4，每 360° 扫描约 70 个参数）在观测/参数比约 100–500 时过拟合风险低。

**顺序是硬约束**：缩放前必须已定点群【一手·逐字】：

> "the point-group symmetry of the data set must be known, as the intensities are grouped by symmetry-unique index"

### 1.7 Rint 的陷阱

这是全部来源里最反直觉、也最重要的一条。Bruker SADABS 手册【一手·逐字】：

> "We must emphasize that the Rint value, although traditional, is a very poor guide to the quality of the data. It is very easy to reduce it artificially by overfitting the data (e.g., by making the scale factor restraint esd larger, or by using high order spherical harmonics when there is no absorption) or by rejecting too many reflections [Diederichs & Karplus, Nature Struct. Biol. 4 (1997) 269-275]. The final R1 value, bond length and angle standard uncertainties, and largest peak and hole in the difference electron density map after refinement are a much better guide (provided the same number of reflections are compared)."

**推论**：任何"改了还原参数后 Rint 下降了"都不构成"数据变好了"的证据。厂家自己给的替代判据是：最终 R1、键长键角 s.u.、差图最大峰/洞（在相同反射数下比较）、以及全分辨率全强度范围内 χ²≈1。

同一手册同时说明离群剔除的正确时机与目的【一手·逐字】：

> "The idea is to eliminate reflection measurements suffering from serious systematic errors (e.g., a reflection cut off by the beam stop or close to a strong reflection from an ice crystal or other impurity), not to throw out a large number of reflections in order to reduce the merging R-values. If the data conform to a normal distribution and the weights are correct, 0.27% will deviate by more than 3σ and 0.05% by more than 3.5σ. Fewer than 0.01% should deviate more than 4.0σ. [...] In practice, a cutoff of about 4.0σ catches the real errors without upsetting the statistics too much. [...] Note the logic of applying this rejection threshold after modeling absorption and other errors, rather than before (as would be the case using the Filter option in SAINT). [...] You are far better off not to eliminate any reflections in SAINT (i.e., do NOT use Filter)."

**"人为压低 Rint"具体指哪个旋钮**（同手册，帧间比例因子的限制 esd）【一手·逐字】：

> "This should almost always be in the range 0.001 to 0.005, and the default of 0.002 is a good first try."

> "In general, the R1 value at the end of the structure refinement will show a shallow minimum as a function of the value of this restraint. In critical cases, you can use this test to obtain the optimum value."

**读法**：把这个限制放松（esd 调大）正是上面那段点名的第一种"人为压低 Rint"的手段。手册给出的正确调法**不是看 Rint，而是看最终 R1 的浅极小**：用**下游**指标反过来定**上游**参数。这与 §1.5 误差模型的验收方式（看 χ² 对强度/对分辨率两张图是否平于 1）、§17.4 SHELXL 权重的验收方式（看方差对 Fc²/分辨率的趋势而非 GooF 单值）是同一种思路：**一个参数调得好不好，不由它自己会改善的那个数说了算。**

### 1.8 分辨率截断

CCP4/AIMLESS 给出默认值与**明确的反对意见**【一手·逐字】：

> "The current default cut-offs are: on CC(½), 0.2; on <<I>/ σ <I>)>, 1.0; and on information content, 0.1. [...] Resolution cut-offs ought to take into account anisotropy [...] The optional automatic cutoff in the pipeline is based on the information content measure."

> "Rmerge and its relatives are not good indicators of resolution, as they increase to arbitrary large values as the intensities get weaker. [...] Rmeas: multiplicity-weighted, a better overall indicator than the classic version as it does not increase with multiplicity [...] Rpim: Precision-indicating R-factor, more closely related to precision of the merged intensity [...] CC(½) etc.: well-defined statistical properties (0 no correlation, +1 perfect correlation), unlike R-factors"

> "It is a mistake to cut back the resolution too severely at the data reduction stage. [...] in refinement and model building even weak high resolution data can be helpful. [...] Cutting back the resolution makes your R-factors look better, but is unlikely to improve your model. [...] It is often best to integrate the data to a higher resolution and then cut it back after examining the Report."

DIALS 论文给了一个"不接受单一判据"的实例【一手·逐字】：

> "this suggests a resolution limit of 2.1 Å based on a CC1/2 threshold of 0.3; however, the completeness is insufficient"

IUCr checkCIF 侧的规定【一手·单次】：

> "In principle, all observed data should be included in the refinement. Alternatively, a sin(theta)/Lambda cutoff value can be used at a value where average(I/Sigma(I)) < 2 in order not to refine on noise. ... There should be a good reason for a cutoff below sin(theta)/lambda = 0.6 Ang**-1. Reflection data beyond that value should not be removed when significantly above the noise level. E.g. they may be very relevant in case of pseudo-symmetry and (non)centrosymmetry refinement."

**综合**：截断是多证据判断（CC1/2、⟨I/σ⟩、壳层完整度、各向异性、以及"这些数据对赝对称/心性判定有没有用"），且**宁晚勿早**。

### 1.9 坏数据诊断

**辐射损伤**（AIMLESS 的 batch 分析图）：相对 B 因子随剂量变负、平均 scale 升过无穷分辨率 scale、Rmerge 上升、估计最大分辨率（I/σ 掉到 1.0 的位置）变差。累积完整度图可能显示后半程可以整段丢弃【一手·逐字】：

> "the second half of the data could be omitted without compomising completeness [...] Sometimes there is just a single bad image which should be excluded."

**多晶体/多扫描的系统性差异**：DIALS 实现了 ΔCC1/2 逐轮剔除，但作者明说这**只能半自动**【一手·逐字】：

> "It is not clear that there is a suitable metric for an appropriate automatic cutoff"

**还原阶段就该看的结构级诊断**：|E²−1| 对分辨率的曲线（见 §0.2 的 SADABS 引文），以及 Rint/Rsigma 对分辨率的曲线，后者被 SADABS 明确称为读取截断位置的依据【一手·逐字】：

> "The next plot page shows the variation of Rint and Rsigma [...] as a function of resolution. It provides an indication of the resolution cutoff to be applied to the data, and often shows very clearly the improvement of the data as a result of high redundancy."

---

## 第 2 章 孪晶

孪晶在本知识库里单列一章，因为它是**自动化失败的头号原因**，而且专家的处理顺序与直觉相反：**先试孪晶，再试无序**。

### 2.1 "先试孪晶"的理由

Bruker SHELXTL 手册第 11 章（Herbst-Irmer 撰写）【一手·逐字】：

> "Since refinement as a twin usually requires only two extra instructions and one extra parameter, in such cases it should be attempted first, before investing many hours in a detailed interpretation of the `disorder'!"

Müller 2009 同意【一手·逐字】：

> "When a structure appears to be difficult and shows some twin-warning signs [see (3) or Chapter 7 in (1)], it is comparatively easy to try twinning first, before spending hours or days on refining disorders or pseudo-symmetry."

### 2.2 并孪晶（merohedral）警示清单

Herbst-Irmer 的清单（1997 手册版与 2019 讲义版一致）【一手·逐字】：

> "Metric symmetry higher than Laue symmetry / Rint for the higher symmetry Laue group only slightly higher than for the lower symmetry one / Different Rint values for the higher symmetry Laue group for different crystals of the same compound / Mean value for |E2 -1| << 0.736 / Apparent trigonal or hexagonal space group / Systematic absences not consistent with any known space group / No structure solution / Patterson function physically impossible (for heavy atom structures) / High R-Values"

XPREP 的 [M] 检验给出定量证据带【一手·逐字】：

> "Comparing true/apparent Laue groups. 0.05 < BASF < 0.45 indicates partial merohedral twinning. BASF ca. 0.5 and a low <|E^2-1|> (0.968[C] or 0.736[NC]) are normal) suggests perfect merohedral twinning. For a twin, R(int) should be low for the true Laue group and low/medium for the apparent Laue group."

1997 手册还记录了 Jameson 的常规检验建议：对所有"可赝亚晶孪生而不改变消光"的空间群（如 P3₁），常规用 `TWIN 0 1 0 1 0 0 0 0 -1` / `BASF 0.1` 试一次。

### 2.3 非贯穿孪晶（non-merohedral）：指标化期的识别

Purdue X 射线中心 SOP【一手·逐字】：

> "Warning signs for non-merohedral twinning at this stage are: The unit cell determination fails. The unit cell found is unusually large, but many predicted spot positions show no intensity. The unit cell size is normal, but many intense spots are not assigned to the predicted cell. Some reflections are unusually close or appear 'split'. In the hkl histogram the percentage of the fitting reflections is low (under 90% for a well diffracting crystal with no other obvious problems). Not all warning signs have to be present at the same time."

以及更常见的情况，**孪晶只在下游才暴露**【一手·逐字】：

> "Often problems arise only at a later stage: structure solution might fail; structure quality is lower than expected from the experimental R values; large residuals are present; thermal parameters are ill-defined; apparent disorder that cannot be refined well; and other complications. While neither of these complications has to be associated by twinning, it is usually worth checking for presence of twinning by both merohedry (use programs such as Platon or Rotax), or by non-merohedry."

### 2.4 CELL_NOW 的操作规程与"真孪晶律"判据

**不得自动接受最高 FOM 的解**【一手·逐字】：

> "Move the <Min. I/sigma(I)> sliding bar to the left so that more and weaker spots from minor twin moieties are read in. A value of 5 is usually sufficient (this also helps to account for supercell reflections). [...] In simple cases, often the first solution displayed (that with the highest figure of merit, FOM) is the 'correct' solution, but this needs to be verified. [...] Read the displayed value (in Å) and compare it with the axis values obtained by Cell Now. If all three values agree, the unit cell from Cell Now is a valid solution. If not (as in the current example, below), the unit cell has to be corrected, e.g. by running Cell Now again with the new information taken into account."

（实例中第一个答案 β=90°、轴长 ~17 Å 是错的，把允许的晶胞边范围从 "4 40" 收紧到 "5 17" 后才对。）

**真孪晶律必须是简单操作**：这是一条极有用的通用判据【一手·逐字】：

> "If the second domain is created indeed by a twin operation, the domains are usually related by a simple mathematical operation, e.g. a 180 degree rotation around a low index axis (e.g. one of the real space or reciprocal axis, or simple combinations of them such as a face or space diagonal). Also possible are 90 or 120 degree rotations. Solutions rotated by different values, or around non-integer fractions of an axis are usually not created by twinning, but the crystal might be split or cracked (small angle rotations around an odd axis), or simply more than one crystal is present (random rotation around an odd axis). [...] The third moiety is related to the first by a close to 180 degree rotation around the b-axis. With a monoclinic crystal this cannot be a twin operation (a two fold axis around b is a symmetry element already present in the monoclinic system). This indicates that the crystal might be split in two nearly aligned parts rather than being twinned a second time."

### 2.5 TWINABS → SHELXL 的交接

【一手·逐字】：

> "go to the refinement step, and accept the results of wR2(int) = 0.0846. Do not accept anything over 0.2. [...] We have two hkl files. We use detwinned HKLF4 format file for structure solution and refiment HKLF5 for final refinement. [...] In this case insert the line BASF 0.4 0.2 before the FVAR line and change the HKLF 4 line to HKLF 5 and then refine the file with the [...] data. R1 should all decrease. [...] Run refinement cycle until no changes are observed for R1 and Goof, and until Max. dU and Maximum are basically zero. [...] The Rint value given is for all reflections and is based on agreement between observed single and composite intensities and those calculated from refined unique intensities and twin fractions (TWINABS (Sheldrick, 2009))."

**注意最后一句**：孪晶数据的 Rint 与常规合并 R 不是同一个量，CIF 里必须说明。

CrysAlisPro 侧的对应功能【一手·逐字】：

> "One feature here which is unique to twin data finalization is the full overlap threshold setting. The Full Overlap Threshold defines the overlap level below which partially-overlapped reflections of twins are partitioned into their component contributions. The parameter can be set to anything between 0 and 1 (with 0.8 as the default value). The Separate scales for all twin components option allows for the application of different scaling models for each set of twin reflections. The Output multi HKLF4 file option will attempt to produce a complete data set by combining reflections from the twin components."

### 2.6 孪晶的采集策略

【一手·逐字】：

> "For twinned structures, a higher redundancy (multiplicity of observation, MoO) is usually required for meaningful multi-scan absorption correction than for untwinned similar systems. Set up a hemisphere or sphere data collection for any but the highest symmetry systems. It is advisable to check completeness of the dataset via a trial solution and refinement before terminating a data collection or dismounting the crystal. [...] If reflections from different twin moieties that successively overlap exceed the 'maximum queue size' set in SAINT [...] the reflections are rejected by SAINT as the intensities cannot be accurately measured any more. The settings [...] can be edited in SAINT so that fewer reflections are rejected, but usually at the expense of data quality. In such cases, the best approach usually involves to collect more data [...] For low symmetry cases sometimes no complete data set can be obtained."

### 2.7 精修期才暴露的孪晶：K 与 most disagreeable

这是把"孪晶"与"无序"区分开的关键诊断【一手·逐字】：

> "K = mean(Fo2)/mean(Fc2) is systematically high for reflections with low intensity / For all of the most disagreeable reflections Fo >> Fc. / Strange residual density, which could not be resolved as solvent or disorder. [...] R1 (F > 4σ(F)) = 11.05 %, wR2 = 34.56 % / Residual density: -1.18 – 3.20 e/Å3 / K = < (Fo2) > / < (Fc2) > = 10.283 for the reflections with the lowest intensity. / most disagreeable reflections Fo is always larger than Fc. / For all these reflections: h + l = 5n"

（该例双域积分 + HKLF 5 后 R1 降到 0.036、残余密度降到 0.35 e/Å³。注意最后一行：**把 most disagreeable 反射的指标写出来往往直接给出孪晶律**。）

Clegg 2019 的赝并孪晶例给出 K 的另一种用法【一手·逐字】：

> "The clue to the answer is given by the large mean observed/calculated intensity ratios K in the analysis of variance following refinement. These, together with the metric pseudo-symmetry of a triclinic lattice closely approximating a monoclinic one, are an indication of possible twinning of a type commonly known as pseudo-merohedral [...] A twin law with matrix (1 0 0, 0 −1 0, 0 0 −1) represents a twofold rotation about the triclinic a axis. [...] Incorporation into the refinement of the twin law and a twin fraction [...] significantly improves the result for the triclinic model, so that it is now clearly the preferred solution. The second twin component has a fraction of almost 17%"

（数值链：未孪晶 P-1 R1 0.058 / max K 4.01；P2₁/n R1 0.065 / max K 7.47；孪晶 P-1 R1 0.043 / max K 1.09 / 组分比 0.832:0.168。）

### 2.8 孪晶数据的求解

【一手·逐字】：

> "For small molecules, normal direct methods are often able to solve twinned structures even for perfect twins, provided that the correct space group is used. / SHELXT often fails! / SHELXD can use the twin law and the fractional contribution [...] SHELXD with TWIN 1 0 0 0 -1 0 -1 0 -1 and BASF 0.45: C32 O4 Fe3 Ni Br5 best final CC 87.4 / SHELXT : space group Cc R1 = 0.232, Alpha = 0.028, Flack x= 0.38"

**这一条很反直觉**：SHELXT 是现代默认求解器，但在孪晶数据上常常失败，此时应回退到 SHELXS（用正确空间群）或给 SHELXD 显式孪晶律。

### 2.9 SHELXL 的孪晶指令语义（可机检）

【一手·逐字】：

> "This method of defining twinning allows the standard HKLF 4 format to be used for the .hkl file, but can only be used when the reciprocal lattices of the original and twin-related components are superimposable. In other cases HKLF 5 format must be used. [...] If BASF is omitted the TWIN factors are all assumed to be equal (i.e. 'perfect' twinning). [...] HKLF 5 sets MERG 0, and may not be used with TWIN. [...] The program now allows BASF parameters to become negative, though of course they should always be positive. [...] If the racemic twinning is present at the same time as normal twinning, N should be doubled (because there are twice as many components as before) and given a negative sign"

---

## 第 3 章 空间群判定

专家在这一步用的是**三条互相独立的证据链**，任何一条单独都会错。

### 3.1 证据链一：系统消光与劳厄群 Rint（XPREP/GRAL 路线）

XPREP 手册的数值指引，全都带"随数据量加权"的限定【一手·逐字】：

> "The R(int) value may be used as a test of the Laue group provided that appropriate equivalent reflections have been measured. Generally R(int) should be below 0.1 for the correct assignment. ... a value above 0.1 indicates the data are very weak or that they have been incorrectly processed. ... The mean Intensity divided by [sigma](I) (<I/s>) should be about unity (or less) for a systematically absent set of reflections. ... systematic absence indications are relatively unreliable if there are only a very small number of reflections in the group, and that the diagnostic value of R(int) in determining the correct Laue group depends on the number of equivalents which were merged to obtain it."

CFOM 的用法与自陈局限【一手·逐字】：

> "Usually a CFOM of less than 1 is a decisive indication that the proposed space group is correct, and a value greater than 10 is rather unlikely to be correct. A good approach in such a case is to prepare a set of files - with different names - for each plausible space group, and to run all through XS to solve the structure before making a choice. ... The program attempts to combine all available information in reaching a probability decision in much the same way as an experienced crystallographer would do. The procedure is not infallible, but the chances of success may be improved by collecting equivalent reflections and by performing absorption corrections and then repeating the space group determination."

CrysAlisPro 的 GRAL 模块把这条链做成了交互流程，并说明**弱数据时应当人工介入**【一手·逐字】：

> "The space group determination module, GRAL, can be run in interactive mode. This is very helpful in cases where the X-ray data are weak and the automated procedure fails. [...] 4. Lattice: a selection of Bravais lattices are shown, with corresponding Rint values 5. Centring: the centring statistics are re-examined after the Niggli reduction 6. <E2-1>: E-statistics are shown to help determine whether the structure is centrosymmetric (centric) or non-centrosymmetric (acentric). [...] 7. Space group: systematic absence exception statistics are shown"

**这条链的失效点**（Palatinus & van der Lee 2008）【一手·逐字】：

> "From our experience it was observed that problems of this nature start to arise when the mean value of the ratio of the intensity and its estimated standard deviation for a given resolution, ⟨I/σ(I)⟩, drops below 10."

实例 flo19（⟨I/σ⟩=6.81）给出了**不存在的衍射符号 P-2121/n**，三个直接法程序在所有候选群里全部失败；在 P1 里用 SUPERFLIP 解出后再导对称，才得到真群 P21221，那个假 n 滑移的 δsym = 0.72，来源是投影上的 (½,½) 赝心化。

另一类失效是**消光位置上有杂散强度**（Renninger 效应、次要孪晶重叠、层错）：实例 flo2 真群 P4₁ 被 XPREP 与 GRAL 都漏掉，PLATON 只标"可疑"；作者指出 t/f 强度比（8.20 vs 4.90）没有原则性截断值，并且**看一张模拟进动图就一目了然**【一手·逐字】：

> "it is not possible to argue whether the threshold should be placed at t/f = 5.0 or another value. […] It is interesting to note that the presence of the 41c screw axis would have been immediately obvious by looking at a simulated precession image of the a*c* plane."

### 3.2 证据链二：强度统计（|E²−1|）与数据库频率先验

见 §0.2 的失效条件。Palatinus & van der Lee 给了两个把这条链单独用就会错的实例【一手·逐字】：

> "a metallo-organic complex with ⟨|E2 − 1|⟩ = 0.904, ⟨|E2 − 1|2⟩ = 2.15 and ⟨|E2 − 1|3⟩ = 14.75 all clearly in favor of a centrosymmetric space group, whereas the correct space group is noncentrosymmetric. […] The space-group determination modules of GRAL and XPREP propose Pnam as the correct space group, probably because the E statistics are in favor of a centrosymmetric space group, whereas PLATON suggests Pnaa, with Pna21 as a second choice. […] The structure turns out to be an inversion twin with Flack parameter 0.405 (11)."

> "All three space-group determination modules used in this study select P-4 as the most probable space group, based mainly on the much higher occurrence of P-4 than that of P4 and P4/m in the databases."

（后一例真群是 P4：δsym 0.069 [4 轴] vs 0.848 [-4] vs 0.523 [反演心]。**数据库频率先验会压倒实测证据**。）

**两条证据链互相矛盾时是一个信号，不是一个噪声**: SHELXTL 手册的 roe119 实例（数据按正交收集，真群其实是 P2₁/c）【一手·逐字】：

> "(b) The statistics are clearly centrosymmetric, but only a non-centrosymmetric space group is consistent with the systematic absences."

> "Since only reflections of type h,k,l and a few -h,-k,-l were collected, the merging R-index is not able to help. If a few equivalents (e.g., with one index negative) had been collected here, the result might well have been the message that no space group is consistent with the given information!"

> "The conclusion is that the true space group is P2(1)/c and that ONLY HALF the necessary data have been collected."

**这个实例值得整体记住，因为它把三件事串了起来**：
1. **"统计说中心对称、消光只容非中心对称"这个矛盾本身就是晶系定错了的诊断**：不该靠挑一边来"解决"。
2. 该例的其余线索是：一个晶胞角偏离 90° 仅 **0.04°**；hk0 层出现不属于任何空间群的额外消光；Patterson 无法用预期的重原子解释；直接法与 Patterson 法**双双失败**。（"消光对不上任何空间群"这条与 §16.3 非贯穿孪晶的签名同形，**同一个观察有两种解释，必须靠别的证据分开**。）
3. **采集策略被晶系判断污染**：按正交收，就只收了单斜所需数据的一半，Rint 因此也帮不上忙。这与 §13.1 Linden 的 β ≈ 90.2° 陷阱是同一件事的另一个版本，**结论都是必须重新采集**。

### 3.3 证据链三：相位/密度对称（SHELXT、SUPERFLIP）

SHELXT 明确**不用系统消光**【一手·逐字】：

> "The data are first merged according to the specified Laue group and then expanded to P1. [...] All space groups in the specified Laue group are tested to find which are consistent with the P1 phases. [...] The systematic absences are not then used for the space-group determination [...] in practice it is best to determine the Laue group first anyway. [...] it is still necessary to identify the correct unit cell and metric symmetry."

心性指标与默认停机规则【一手·逐字】：

> "If α0 is less than about 0.3, the space group is probably centrosymmetric. [...] only unlikely solutions with α greater than a specified value (default 0.3) are eliminated [...] If α0 is below 0.3 and no atom heavier than scandium is expected, the program stops"

SUPERFLIP 的对称一致因子（两个可调参数，且给了经验分布）【一手·逐字】：

> "The vector m is accepted as a centering vector of the space group if R(m) > 0.98, which means that the sum of intensities of the reflections extinct because of the centering must be less than 2% of the total sum of intensities. Setting a more relaxed limit would increase the tolerance to the noise in the data, but at the cost of accepting a false centering vector in cases of superstructures [...] according to our experience δsym for the correct symmetry operations is most frequently below 0.1, and almost always below 0.2, while δsym for the wrong symmetry operations is usually above 0.5. In SUPERFLIP the default acceptance threshold is 0.25, and this limit works very well in a vast majority of cases, although it can fail occasionally in cases of very noisy data, especially data extracted from powder patterns or data from a twinned crystal."

**这条链的失效点是赝对称**【一手·逐字】：

> "If the pseudosymmetry is strong, δsym of the pseudosymmetry elements can be quite low. In such a case the automatic space-group determination will result in a choice of a higher symmetry, often accompanied by an apparent disorder of one or more functional groups. It is up to the crystallographer to decide whether the disordered model in the higher-symmetrical group is to be preferred or if an ordered model in a lower-symmetrical space group should be accepted [...] With high-quality data intermediate δsym values between 0.10 and 0.25 indicate potentially pseudosymmetric elements [...] The least SUPERFLIP does is to quantify the presence of these elements; it is up to the crystallographer to decide about the best space group."

作者还给出一条**可直接用的交叉核对规则**【一手·逐字】：

> "Therefore it is advisable to pay increased attention if the refined structure exhibits disorder and if the space group derived using the symmetry agreement factors corresponds to a different extinction symbol from that derived directly from the integrated intensities."

### 3.4 倒易空间 vs 直接空间：为什么 SHELXT 常比 ADDSYM 准

Clegg 2019 的假说与实测【一手·逐字】：

> "With hindsight, in 2019, the P1 structure is the preferred solution from SHELXT, the P1̄ structure having a somewhat poorer Combined Figure of Merit. PLATON, however, still suggests P1̄ with a 100% fit within default tolerances. It may be that SHELXT is so successful in choosing the correct space group in such cases partly because it bases its decisions on examination of phase relationships between potentially symmetry-equivalent reflections in reciprocal space (primary data) rather than looking for evidence of symmetry operations between atoms in direct space (derived secondary data); perhaps the reciprocal space approach provides better discrimination."

在 Clegg 的三个例子里 ADDSYM 全部推荐了错误的更高对称（100% n 滑移 → P2₁/n；90% 反演 / 95% 滑移 → P2₁/n；100% → P-1）。

### 3.5 错群的类型学与规模（Marsh 系列）

**规模**【一手·逐字】：

> "A recent survey of the Cambridge Structural Database, CSD [...] shows that the percentage of incorrect assignments of the space group Cc has remained at about 10% since the last survey in 1997."

**两类后果必须分开对待**【一手·逐字】：

> "The space groups of 98 structures originally reported in Cc are revised. In 75 cases the revised space group is C2/c and the revision entails adding a center of symmetry, usually leading to large changes in bond lengths and angles. In the remaining 23 cases, where the revised space group is Fdd2, R3c or (in one case) I-4c2, the lattice type is changed but no center is added; in these cases the molecular dimensions are effectively unchanged."

即：**漏反演中心 = 高风险（几何全变）；漏格子心化 = 低风险（分子尺寸基本不变）**。

**P1 的错误谱系**【一手·逐字】：

> "The October 1998 release of the Cambridge Structural Database contains structural details [...] for nearly 1300 distinct entries under space group P1 (No. 1); for 279 of these entries, the space-group designation is incorrect. The most common type of error, occurring for 157 entries with Z > 1, seems to have resulted from a simple misprint – the omission of the `overline' in the symbol P-1 [...] In the remaining 123 cases the space group is incorrect for more fundamental reasons"

Müller 的相关操作建议【一手·逐字】：

> "If a triclinic structure cannot be solved in space group P-1, it is usually solved easily in P1. This is not supposed to mean that P1 is the correct space group, in by far most cases P-1 is correct, it only means that direct methods work better in non-centrosymmetric space groups."

**错群的方向性，一条可直接缩小搜索空间的规则**（Raymond & Girolami 2023, Acta Cryst. C79, 445–455）【一手·逐字】：

> "In most published crystallographic studies in which an incorrect space group has inadvertently been chosen, the correct space group is usually a supergroup of the chosen one, which means that the true space group has additional symmetry elements. Automated tools such as PLATON and checkCIF can easily detect such problems"

**读法**：错群**几乎总是错在对称性定低了**，正确群是所选群的**超群**。上面 Marsh 的三组统计（Cc→C2/c、P1→P-1、C2→C2/c）全部符合这个方向。**对自动化的含义**：怀疑错群时，优先搜索的方向是"有没有漏掉的对称元素"，而不是"要不要降对称"。这与 §3.7 赝对称的两难并不矛盾，那一节讲的是当漏对称与无序两种解释都说得通时如何取舍。

### 3.6 ADDSYM：容差、假阳性率、适用条件

**默认容差**【一手·逐字】：

> "WARNING - The ADDSYM analysis is purely based on an analysis of the supplied derived geometry within (default) tolerances. All higher symmetry indications should be investigated against the reflection data. [...] ang - Angle criterium in search for metrical symmetry of the lattice (default 1.0 degree). d1 - Distance criterium for coinciding atoms for non-inversion (pseudo)symmetry elements (default 0.25 Angstrom). d2 - Distance criterium for coinciding atoms for (pseudo) inversion symmetry (default 0.45, 0.25 Angstrom). [...] Note : By default up to 20 % of the atoms are allowed as mis-fits"

**假阳性率约 2/3**【一手·逐字】：

> "From a search of the October 2000 release of the Cambridge Structural Database we find coordinate data for approximately 1500 entries under space group No. 5: C2 [...] Software designed to detect cases of missed higher symmetry identified 144 entries for detailed inspection. Of these, 50 should, we believe, be revised to space groups of higher symmetry."

**适用条件与一个具体的假阳性案例**（Spek 2009）【一手·逐字】：

> "Validation suggests space group C2/m within default error tolerances as a higher symmetry alternative, which makes sense since the basic molecule has an approximate mirror plane. In fact, this structure easily solves and refines in C2/m when instructed to do so, although with a higher R factor. The evidence against C2/m is that the atomic displacement parameters in the t-butyl moiety are high. [...] the PLATON/ADDSYM algorithm that is used to detect missing symmetry requires atomic resolution data."

以及那条对精修实践极重要的观察【一手·逐字】：

> "Some missed symmetry cases are relatively harmless in that this error does not seriously affect the structure and its interpretation (e.g. wrong Laue group) [...] On the other hand, overlooking an inversion centre is generally serious. This last problem can be hidden when structure refinement is performed by using constraints and restraints to secure the stability of the least-squares refinement."

**"加了限制之后精修就稳定了"本身可能是漏反演中心的掩饰信号。**

**规模与最终裁决依据**（同文）【一手·逐字】：

> "384 space-group changes were indicated. Other frequently reported problems are unaccounted-for solvent-accessible voids and numerous problems with H atoms."

> "There are many borderline cases for which the reflection data are needed for a definitive space-group assignment."

（第一句的分母是 2006–2007 年初新增 CSD 的 35 760 个条目，即约 **1%** 被指出需改空间群；同批次另外两类高频问题是**未说明的溶剂可及空腔**与**大量氢原子问题**：正好对应本文第 5 章与第 7 章。第二句是本节的落点：**ADDSYM 是纯几何的，边界情形必须回到衍射数据才能定案**，这与本节开头 PLATON 自己的 WARNING 一致。）

### 3.7 赝对称的两难：中心+无序 vs 非中心+有序

这是 Spek 点名"只有有经验的晶体学家能裁决"的一类问题【一手·逐字】：

> "Some ALERTS reveal issues that can only be addressed by experienced crystallographers. An example is whether a given structure is best described as disordered in a centrosymmetric space group or as ordered in a noncentrosymmetric space group (Flack et al., 2006)."

Clegg 给出裁决所需的证据清单【一手·逐字】：

> "Several factors need to be considered when a structure can be refined alternatively as disordered in a centrosymmetric space group or, at least apparently, ordered in a non-centrosymmetric space group. Important evidence comes not only from refinement indicators such as R-factors, satisfactory convergence, and difference map features, but also from the resultant molecular geometry, including abnormal distortions and the need to impose refinement constraints and/or unusually strong restraints. There may also be relevant non-crystallographic data, for example information from the chemical synthesis method, spectroscopy, or physical properties."

他的实例（对映体纯环氧化合物）里，XPREP 因 |E²−1| 接近心值、消光"提示"n 滑移（那些"消光"反射平均强度约为其余的 10%）、且 P2₁/n 在 CSD 里远比 P2₁ 常见，把 P2₁/n 排在了前面；P2₁/n 解需要无序的环氧环（R≈0.07），手工搭的 P2₁ Z'=2 有序模型 R=0.046 且所有 H 可见。**决定性证据是化学的**：化合物对映体纯，必须是 Sohncke 群；两个分子由非晶体学反演中心相关（"pseudo-racemate"），Clegg 说这对只有一个手性中心、Z'=2 的对映体纯药物分子很常见。

---

## 第 4 章 结构求解

### 4.1 方法选择的成文启发（PLATON System S）

【一手·逐字】：

> "DIRDIF The method of choise for heavy atom structures. DIRDIF may have problems with structure determinations run with an incorrect CONTENTS formula, in particular when the number of heavy atoms is different from the number suggested. [...] SIR SIR97 provides an excellent alternative for SHELXS. It is slower but often gives results with large poorly reflecting (low resolution) data sets. SPGR By default, a list of spacegroups consistent with the current lattice, Laue symmetry and systematic extinctions is presented with an indication of a plausible first choice. [...] Z is not necessarily equal to the number of symmetry operations. It can be more or less. The Default (Return) will suggest a suitable value (to be confirmed or overruled) giving reasonable density and volume-per-atom values."

Müller 给出分辨率与方法的关系【一手·逐字】：

> "Classical direct methods stop working around 1.0–1.1 Å, while sometimes dual-space methods can solve structures based on data extending to only 1.5 Å."

孪晶下的方法选择见 §2.8（SHELXT 常败、SHELXS 常成、SHELXD 可给孪晶律）。

### 4.2 元素指认：为什么峰高不可靠

SHELXT 的做法与理由【一手·逐字】：

> "It is better to use integrated densities rather than peak heights [...] (default radius 0.7 Å) [...] between 1.25 and 1.65 Å [...] the scale is set so that they will have average atomic numbers of 6 [...] it is assumed that the heaviest atom expected corresponds to the peak with the highest integrated density [...] chlorine, bromine or iodine atoms are added [...] It is always essential to check the element assignments, especially if the program has added extra elements"

PLATON System S 对峰高法的直白批评【一手·逐字】：

> "Atom types are assigned to the resulting peaklist on the basis of the contents formula. The correct identification of a peak as C,O or N may be hampered by difference in thermal parameters (i.e. periferal O atoms may fit the peak height of a carbon atom and a central C may fit the peak height of an O atom."

Raymond & Girolami 的**可分辨性判据**（元素通用）【一手·逐字】：

> "A very rough rule of thumb is that atoms whose atomic numbers differ by less than 10% cannot easily be distinguished. Thus, the atomic numbers of nitrogen (Z = 7) and oxygen (Z = 8) differ by 15% and may be distinguishable, whereas the 7% difference between tungsten (Z = 74) and gold (Z = 79) will make it difficult to tell them apart. [...] One common symptom of an incorrect atom type is that the bond distances to that atom are incorrect; another is that the displacement parameters for that atom are inexplicably different from those of nearby atoms [...]. But other factors can also affect displacement parameters, such as thermal motion, disorder, and an incorrect site-occupancy factor, so that the displacement parameters cannot always indicate the presence of mis-assigned atoms."

Müller 的椭球形态学速查（**极其实用**）【一手·逐字】：

> "A very small ellipsoid indicates that the corresponding atom may in fact be heavier than the one currently contained in the model (e.g. oxygen refined as carbon), a very large ellipsoid could mean the opposite or indicate disorder. Elongated, cigar shaped ellipsoids are another sign indicating disorder. Flat, pancake shaped ellipsoids usually point out problems with pseudo-symmetry or incorrect space groups."

### 4.3 SHELXT 的实测成功率与失效模式

【一手·逐字】：

> "the correct space group was identified in about 97% of cases [...] for about half of the structures every atom was located and assigned to the correct element [...] the most common errors being carbon assigned as nitrogen or vice versa. [...] inversion of the structure if the value of the Flack parameter is greater than 0.5 [...] so far no examples to the contrary have been reported"

> "unsuitable for severely disordered and twinned structures [...] not suitable for neutron diffraction data. [...] Often a value close to 0.5 indicates a centrosymmetric structure. [...] In such cases the highest-symmetry (centrosymmetric) space group is almost always correct. [...] Poor solutions were sometimes obtained when the heavy atoms corresponded to a centrosymmetric substructure [...] The biggest danger is that inexperienced users may assume that the program is always right!"

### 4.4 怎么认出"解对了"

综合各来源，专家看的是（按重要性排序）：

1. **化学合理的碎片**：能不能认出预期的配体、环、羧酸、反离子。
2. **峰的积分密度与元素身份是否自洽**（不是峰高）。
3. **ADP 形态**（见 §4.2 速查）。
4. **Flack**：极性群里 ≈0.5 往往意味着其实是中心对称（§4.3 引文）。
5. **R1 只用于在候选之间排序**（§0.1）。
6. **非晶体学证据**：合成路线、对映体纯度、光谱、电荷平衡。

---

## 第 5 章 精修

### 5.1 权重方案：一条有明确时序的规则

SHELXL 手册【一手·逐字】：

> "The parameters should be set by trial and error so that the variance shows no marked systematic trends with the magnitude of Fc² or of resolution; the program suggests a suitable WGHT instruction after the analysis of variance. This scheme is chosen to give a flat analysis of variance in terms of Fc², but does not take the resolution dependence into account. It is usually advisable to retain default weights (WGHT 0.1) until all atoms have been found and the refinement is essentially complete, when the scheme suggested by the program can be used for the next refinement job by replacing the existing WGHT instruction by the one output by the program towards the end of the .res file. This procedure is adequate for most routine refinements."

要点：① **模型没建完就不要采纳建议权重**；② 权重方案的目标是让方差分析对 Fc² 平坦；③ 该方案**故意不管分辨率依赖**：所以"方差分析对分辨率有趋势"不是靠 WGHT 解决的。

Spek 2020 关于收敛假象的告诫【一手·逐字】：

> "A sufficient reflection data (N) to refined parameter (p) ratio is expected." … "Failure to come close to that value might be indicative of unresolved issues (in the data or the model)." … "A strong damping factor may erroneously give the illusion of a converged structure with unreasonably low s.u.'s"

SHELXL 对 damping 的对应说明【一手·逐字】：

> "A side-effect of damping is that the standard deviations of poorly determined parameters will be artificially reduced; it is recommended that a final least-squares cycle be performed with little or no damping in order to improve these estimated standard deviations."

### 5.2 约束与限制（constraints vs restraints）

**总原则**（Müller 2009）【一手·逐字】：

> "Owing to the mathematical rigidity of constraints, more damage can be done with incorrectly used constraints than with inappropriate restraints and whenever a refinement problem can be solved by means of restraints, this approach should be preferred over the use of constraints."

> "Restraints must be applied with great care and only if justified. When appropriate however, they should be used without hesitation, and having more restraints than parameters in a refinement is nothing to be ashamed of. [...] whenever possible similarity restraints should be given preference over direct restraints."

**默认弹性（s.u.），Müller 版**【一手·逐字】：

> "Typical elasticities for geometry restraints are 0.02 Å for bonds, 0.04 Å for 1,3-distances (i.e. bond angles) and 0.1 Å³ for planarity restraints. [...] The rigid bond restraint [...] (suggested elasticity 0.01 Å²). The similar ADP restraint [...] (suggested elasticity 0.04 Å²; 0.08 Å² for terminal atoms). The isotropy restraint [...] (suggested elasticity 0.1 Å²; 0.2 Å² for terminal atoms). [...] This assumption should only be applied as an option of last resort"

**ADP 限制的层级与适用边界，SHELXL 手册版**【一手·逐字】：

> "This may be considered a hard restraint and so these low esds are appropriate and will rarely need changing. [...] Note that SIMU should in general be given a much larger esd (and hence lower weight) than RIGU and DELU; whereas there is good evidence that RIGU and DELU restraints should hold accurately for most covalently bonded systems, SIMU (and ISOR) are only rough approximations to reality. [...] SIMU restraints are NOT recommended for SMALL molecules and ions, especially if free rotation or torsion is possible (e.g. C5H5-groups, BF4 ions). [...] However it should not be used indiscriminately for this purpose without investigating whether there are reasons (e.g. disorder, wrong scattering factor type etc.) for the atom going NPD."

**这一段是最容易被误用成"通用配方"的地方**：RIGU/DELU 有物理依据（共价体系刚性键假设成立），SIMU/ISOR 只是粗近似；SIMU 明确**不推荐**用于小分子与自由旋转基团；ISOR 不得用来"治"非正定原子而不查原因（无序？元素错了？）。

**滥用的红线**（Müller）【一手·逐字】：

> "This restraint is easily abused and must not be mistaken for a convenient way to make anisotropic displacement ellipsoids look better. Pathological ellipsoids should always be investigated and not massaged away with restraints."

**限制被数据推翻时的检查**（Müller）【一手·逐字】：

> "A large difference between target and observed value indicates that a restraint has been overruled by the diffraction data, which means that the validity of this restraint needs to be verified carefully."

（对应 SHELXL .lst 里的 "Disagreeable restraints" 列表。）

### 5.3 无序建模：完整流程

**第一步是诊断，且诊断对象是模型不是衍射图**（Müller 无序教程）【一手·逐字】：

> "the ellipsoids derived from the anisotropic displacement parameters (ADPs) may be of pathological shape because the program tries to describe two or more atom sites with only one ellipsoid, and the presence of relatively high residual electron density peaks or holes close to the disordered atoms is not unusual. … Therefore, the ADPs should be drastically larger to justify a reduction of the occupancy factors. The residual electron density map, which shows negative electron density at or around the nuclear positions if the true occupancy is lower than one is a better criterion. … However, not all 'may be split' atoms should be split; sometimes the anisotropic motion of an atom on a single position is a better description."

要点：**大 ADP 本身不足以证明部分占据**（可移动溶剂满占据时 ADP 也大），核位置上的**负残余密度**才是更好的判据。

**第二步：拆位前先各向同性**【一手·逐字】：

> "it is always a good idea to refine disorders at first isotropically, as anisotropic displacement parameters tend to compensate for the disorder, which makes it difficult to find additional positions."

**第三步：PART / 自由变量 / 特殊位置**【一手·逐字】：

> "When in doubt, 0.6 is almost always a reasonable starting value. … either one changes the space group to one of lower symmetry without this particular special position, or – in most cases far better – one assumes a disorder of the molecule about this particular special position. … It is important to note that the positions of the hydrogen atoms bonded to C(12) and C(14) are disordered in the same way as the corresponding Me-groups, although C(12) and C(14) are not directly involved in the disorders themselves. … These distances are sensible at this temperature (-140 °C). A list of X-H distances at the temperature defined by the TEMP instruction in the .ins file, can be found in the .lst file."

要点：① 比例未知时起点 0.6；② 分子坐在比自身对称性更高的特殊位置上时，**优先按无序处理而不是降空间群**；③ 与无序基团相邻的**有序**原子上的 H 也必须跟着拆；④ X–H 目标距离**随温度变**。

**第四步：接受检验（无序建模里唯一确定性的验收）**【一手·逐字】：

> "The value of this standard uncertainty is supposed to be much smaller than the value for the free variable, or the disorder represented by the free variable would not be very meaningful. … If the free variable coupled to a disorder should refine to 0.95 [±] 0.1 – this corresponds to an occupancy of the minor compound of 5(10) % – it is very reasonable to assume that there is no disorder represented by the coordinates coupled to the free variable in question. In such a case, the atoms from the second component should be deleted, the sof instruction of the atoms of the first component should be changed back to 11.0000 and the PART instructions should be removed."

**第五步：限制必须从一开始就加**【一手·逐字】：

> "And, as there is no disorder refinement without restraints, you should use SAME (or the respective SADI instructions) to make the 1,2- and 1,3-distances equivalent."

同一教程另有一句更强的、**把范围说死**的表述【一手·逐字】：

> "Introducing similarity restraints on both geometry and anisotropic displacement parameters for all disordered atoms should be standard and there should be no disorder refinement without similarity restraints."

**注意它比上一句多说了两件事**：限制要同时覆盖**几何与 ADP 两侧**，且适用于**全部**无序原子（不只是被拆开的那几个）。这与 §13.4 Linden 的"SIMU/DELU/RIGU 优于 EADP"、§15.9 Watkin 的"无序情形下限制 s.u. 需人工调"是同一条工艺链上的三段：**加什么（Müller）→ 加哪一类（Linden）→ 加多紧（Watkin）**。

SAME 的两条**独立**忠告（不要合并成因果句）【一手·逐字】：

> "start two atoms earlier. That means the SAME instructions should not be given immediately before the disordered atoms... but rather two atoms before them"

> "If the atoms in the two components... are not precisely in the same order, the restraints generated by the SAME command may do more harm than good."

s.u. 默认与 ISOR 的定位【一手·逐字】：

> "default values are 0.02 for 1,2- and 0.04 for 1,3-distances … The default values for the standard deviations are 0.04 for SIMU (0.08 for terminal atoms, which tend to move more strongly) and 0.01 for DELU. … ISOR is helpful for certain special cases (e.g. a disordered atom close to a special position, or anisotropic refinement of a protein against 1.5 Å data) and should almost always be applied to the water molecules of a protein model, but is otherwise less appropriate than SIMU or DELU. … This should be done with care and preferably only in early stages of a disorder refinement. Whenever a similarly satisfying effect can be reached by the use of restraints, the restraints should be given the preference."

（最后两句是关于 AFIX 66/56 一类刚体约束的：可以用，但只在早期且要小心。）

**第六步：分批推进**（Müller 2009）【一手·逐字】：

> "When refining disorder, first model the non-hydrogen atoms while keeping them isotropic. Once the refinement is stable, allow for anisotropic refinement and then, finally, add the hydrogen atoms. If there are several disorders in a structure, refine them one at a time and if a disorder involves many atoms (say more than 20% of all independent atoms), refine it in portions."

### 5.4 残余密度的读法：来源清单

**不是每个显著残峰都是无序**（Müller 无序教程）【一手·逐字】：

> "In any case, a disorder must be chemically reasonable. Not every significant residual electron density peak is caused by disorder. High residual electron density can also be caused by inadequately corrected absorption, Fourier series truncation errors (e.g. when strong reflections are missing) or radiation damage. Such artifacts often lead to the accumulation of spurious electron density at special positions. … This is a normal effect for isotropically refined heavy metals. … A peak height of about 13 electrons corresponds very well with aluminum, which is expected to bond to the fluorine atoms. However, the aluminum positions do not seem to be chemically reasonable. … And not two, as many – even experienced – crystallographers might answer. Disordered molecules on special positions are a famous and infamous trap"

**残余密度来源清单（诊断时应逐项排除）**：无序 / 吸收校正不足 / 傅立叶截断（强反射缺失）/ 辐射损伤（常堆在特殊位置）/ 各向同性精修的重原子邻近（正常伪影）/ 漏掉的 H / 元素指认错 / 未建模溶剂或客体 / 孪晶。

Spek 2020 给出收敛模型的期望【一手·逐字】：

> "Such a map should be close to featureless with similar positive and negative density excursions of less than ∼±0.5 e Å−3." … "Significant approximately spherical density in a difference-density map cannot be ignored."

Spek 2009 的 H 差图判据【一手·逐字】：

> "Hydroxyl moieties generally have their H atom on a cone and pointing to a hydrogen-bond acceptor in the structure. Exceptions are rare and are generally the consequence of misplaced H-atom positioning, incomplete structures or wrong atom-type assignment. [...] A misplaced H atom will show up as a negative density peak in its false location and the correct location will appear as a positive peak."

### 5.5 消光（EXTI）与漫散射溶剂（SWAT）

SHELXL 手册把两者的**不可分辨性**写得很清楚【一手·逐字】：

> "The program will print a warning if extinction (or SWAT) may be worth refining, but it is not normally advisable to introduce it until all the non-hydrogen atoms have been found. [...] for small molecules without significant diffuse solvent regions g should refine to zero. [...] Since both extinction and diffraction from diffuse solvent tend to affect primarily the strong reflections at low diffraction angle, they tend to show the same symptoms in the analysis of variance, and so a combined warning message is printed. It will however be obvious from the type of structural problem which of the two should be applied. The program does not permit the simultaneous refinement of SWAT and EXTI."

**这是"工具故意给出模糊裁定、把消歧交给人"的教科书案例**：程序知道有问题但不知道是哪一个，判据是"这是什么类型的结构"。

### 5.6 绝对构型

**判定力先于判定**（Parsons, Flack & Wagner 2013）【一手·逐字】：

> "should be less than 0.1, even if a material is known to be enantiopure"

> "If Friedifstat has a value of ∼ 80 or more, absolute structure determination presents little problem."

> "Acceptable precision has been obtained for data-sets with Friedifstat as low as 12."

**常规 TWIN/BASF 精修的 s.u. 系统性悲观**【一手·逐字】：

> "but with standard uncertainties ranging from 0.15 to 0.77"

> "suggesting that the uncertainties are overestimated by a factor of 5.5"

（23 个轻原子结构、Cu Kα；商法/Bayesian-Hooft/差值限制法给出同样答案但精度高得多。）

**后精修法的前提**【一手·逐字】：

> "the diffraction data should be recollected with a revised collection strategy"

**中间值的歧义必须用显式 TWIN 精修裁决**（Herbst-Irmer 实例）【一手·逐字】：

> "0 < x < 1 ** Possible racemic twinning or wrong absolute structure - try TWIN refinement ** [...] Flack x = 0.932(14) by hole-in-one fit to all intensities 0.715(12) from 3181 selected quotients (Parsons' method) ** Absolute structure probably wrong - invert and repeat refinement ** [...] No Twinning by Inversion! MOVE 1 1 1 -1 TWIN -1 0 0 0 -1 0 1 0 1 R1 = 0.0271 k2= 0.461(1) Flack x = 0.009(4)"

**checkCIF 侧的成文判据**【一手·单次】：

> "A value close to 0.5 may be indicative of an inversion twin or a missed centre of inversion. For valid absolute structure assignments, abs(x) should be less than 2 * s.u., with s.u. < 0.04. For enantiopure compounds, s.u. should be less than 0.1."

**独立复核**（Spek 2009）【一手·逐字】：

> "This value can be erroneous (Flack et al., 2006) and lead to false conclusions about enantiopurity. The availability of the reflection file allows software to check the reported value independently. This is performed by a comparison of the value of the reported Flack parameter with the value of the Hooft parameter (Hooft et al., 2008), which is calculated from the Bijvoet differences."

**极性方向选错的后果**（Harlow 1996）【一手·逐字】：

> "Choosing the wrong polarity can lead to incorrect bond lengths whenever atoms with significant anomalous scattering are present."

### 5.7 无序溶剂：显式建模 vs SQUEEZE / 掩膜

**优先级是明确的**（Spek 2015）【一手·逐字】：

> "Traditionally, an atomistic solvent disorder model is attempted. Such an approach is generally to be preferred, but it does not always lead to a satisfactory result and may even be impossible in cases where channels in the structure are filled with continuous electron density. [...] Sometimes the nature of the solvent mixture present in the voids of the structure is unclear. The structures of metal–organic frameworks (MOFs) are notorious examples. [...] Its main purpose can be to bring down the R value as proof that an unaccounted-for solvent is the main reason for a high R factor. The main concern is not to overstretch its application to conditions with poor or limited data sets. The SQUEEZE procedure needs a sufficient ratio of reflection data to least-squares parameters to avoid over-fitting."

**前提条件清单（用之前必须满足）**【一手·逐字】：

> "SQUEEZE is designed for `small-molecule structures' and is most effective when based on a complete and reliable data set with sufficient resolution. Low-temperature data are strongly advised for better resolution and to avoid loss of solvent during data collection. [...] The host structure should be completely modelled, including H atoms and any disorder without unresolved residual electron density, because of its impact on the difference map in the solvent region. SQUEEZE cannot properly handle cases of coupled disorder affecting both the host and the solvent region [...] Also, there should be no unresolved charge-balance issues that might affect the conclusions about the chemistry involved, such as the valency of the metal in the host part of the structure, if SQUEEZE removes undetected counter-ions. Using SQUEEZE as part of the MOF soaking method (Inokuma et al., 2013), where the interest lies in the guest region as opposed to the host region, can be very challenging, is not recommended and should be done with extreme care when attempted."

**算法参数与"电子数当化学核对"**【一手·逐字】：

> "Solvent-accessible regions (SARs) in a structure are defined on a grid of approximately 0.2 Å. [...] The solvent region can then be defined as the volume enclosed when a sphere of radius 1.2 Å is rolled over the surface of the host. Thus, a void in a structure should at least have a volume of 4π(1.2)3/3 = 7.2 Å3 to be relevant. [...] By default, PLATON SQUEEZE will estimate this number with the expression NEXTRA = (En)/(Zm), where E is the number of recovered electrons in the unit cell, Z is the number of asymmetric units, n is the number of parameters usually refined for a CH2 fragment (i.e. 9) and m is the number of electrons in a CH2 fragment (i.e. 8). [...] SQUEEZE calculates an electron count of 37 electrons at the CH2Cl2 site, where 42 are expected for full occupancy. From this ratio, a tentative CH2Cl2 occupancy of 0.88 can be calculated and compared with the value of 0.69 obtained in the least-squares refinement."

**一个重要陷阱：峰搜索会漏掉弥散的通道密度**【一手·逐字】：

> "Smeared residual electron density in voids in a structure is not always detected by peak search routines that assume three-dimensional Gaussian-shaped densities for peak fitting. An example is the structure determination of (−)-crebanine (Duangthongyou et al., 2011), where the authors indeed reported `empty' large voids (maximum residual electron density = 0.55 e Å−3) that, on close inspection, are found to be solvent-filled infinite channels."

**报告义务**【一手·逐字】：

> "The procedure followed should be well documented in the final structure report and associated CIF archive. This would involve the reporting of the number of voids per unit cell, their volume, their shape, the number of electrons per void and some estimate of the likely solvent content this might correspond to. [...] checkCIF will report calculated values for the moiety formula, sum formula, Mr, Dx, μ and F000 that are based only on the model parameters. The reported and calculated values should currently be compared manually for consistency."

**与孪晶、绝对构型的相互作用**【一手·逐字】：

> "The current SHELXL release (SHELXL2014/7) allows for the output of a detwinned Fo2/Fc2/σ(Fo2) reflection file (i.e. a LIST 8 type .fcf file). This makes it possible, in cases for which detwinning succeeds, to SQUEEZE twinned structures. Again, the detwinned data are used only for the generation of the .fab file. [...] Both BASF/TWIN and BASF/HKLF 5 twin refinements are accommodated in this way. [...] It might be necessary to repeat the SQUEEZE procedure, for example, when the refined value of the twin domain ratio has changed significantly [...] The presence of significant anomalous scatterers in the solvent region cannot be used for the determination of the absolute structure of a light-atom host if SQUEEZE has been used [...] The same Friedel-averaged solvent contribution is added to both Bijvoet-pair related reflections. The effect will be a higher s.u. on the Flack parameter value than when an atomistic solvent model is refined."

**孪晶时必须走哪条路，一条容易漏掉的限定**【一手·逐字】：

> "This method should not be used in cases of twinning (see §3.1)."

**这里的 "This method" 指的是简化的 .ins/.hkl 捷径，不是 SQUEEZE 本身**（SQUEEZE 本身可以用于孪晶，见上一条引文）。**正确路线是：孪晶必须经 SHELXL LIST 8 输出的解卷积 .fcf 来生成 .fab，不能用捷径。** 且孪晶分数明显变化后要重跑 SQUEEZE，这意味着 **SQUEEZE 与孪晶精修之间存在循环依赖**，不是一次性步骤。

**为什么"看上去有很大空隙"不等于"有溶剂可及体积"**【一手·逐字】：

> "Such spaces can constitute of the order of 30% of the unit-cell volume when the solvent-accessible volume is zero."

**读法**：球堆积之间的尖隙（cusp）空间可以占到晶胞体积的约 30%，而**溶剂可及体积仍为零**：因为 1.2 Å 探针滚不进去。所以"晶胞里有 30% 不是原子"绝不能推出"应该有溶剂"。这与 §12.4 堆积系数约 65% 是同一件事的两种说法。

**低角数据的重要性**（Spek 2020）【一手·逐字】：

> "The exact content of the disordered solvent volume is not determined explicitly with this method" … "Disordered solvents contribute in particular to low-angle data." … "Improper handling of low-angle data or omitting those data may seriously hamper the usefulness of the electron count." … "'[+solvent]' when the nature of the solvent (mixture) is unclear or '[+toluene]'" … "The contribution within the square brackets is not included in the calculated molecular weight and density"

### 5.8 过拟合与"可疑的降 R 手法"

SHELXL 手册自己点名了一条【一手·逐字】：

> "It is possible to change this parameter (to say 1.1 to allow for hydrogen atoms) when refining both occupation factors and U's for solvent water in proteins (a popular but suspect way of improving the R factor)."

以及对自动加氢的告诫【一手·逐字】：

> "This output should be checked carefully, since the algorithms used by HFIX/AFIX to place hydrogens are by no means infallible!"

---

## 第 6 章 模型诊断：从模型反推错误

### 6.1 Müller 的键长诊断树（元素无关，适用任意体系）

【一手·逐字】：

> "Check bond lengths and angles for sensibility. If all bonds are systematically too long or too short, it is likely that there is a problem with the data or the unit cell. If many bonds deviate significantly from expected values, some too long, others too short, check whether the space group is correct (an overlooked inversion centre can sometimes lead to dramatic distortions, as demonstrated in Section 4.4). If only a few bonds are longer or shorter than expected, check for errors in the assignment of atom types or look into disorders"

| 症状 | 首要怀疑 |
|---|---|
| 所有键系统性偏长或偏短 | 数据或晶胞（标度、波长、晶胞常数） |
| 大量键双向散乱 | 空间群错（尤其漏反演中心） |
| 只有少数键异常 | 元素指认错，或无序 |

### 6.2 ADP 形态学速查

| 椭球形态 | 含义 |
|---|---|
| 异常小 | 该位点比模型里的元素**重** |
| 异常大 | 比模型**轻**，或无序 |
| 雪茄形（拉长） | 无序 |
| 煎饼形（扁平） | 赝对称或空间群错 |

**这张表的前提是一条祈使句**（Müller 2009）【一手·逐字】：

> "Always look at a plot of the anisotropic displacement ellipsoids"

> "A very small ellipsoid indicates that the corresponding atom may in fact be heavier than the one currently contained in the model (e.g. oxygen refined as carbon), a very large ellipsoid could mean the opposite or indicate disorder. Elongated, cigar shaped ellipsoids are another sign indicating disorder. Flat, pancake shaped ellipsoids usually point out problems with pseudo-symmetry or incorrect space groups."

**"要去看"本身是这条判据的一部分**: ADP 的数值在 CIF 里，但形态学要在图上才读得出来。这与 §13.6 Linden 的 *"Seeing is believing."* 和 *"if it looks weird, it probably is!"* 是同一条纪律的两次独立表述。**对自动化的含义**：把 Uij 六个数交给判据函数，与"看一眼椭球图"不是等价操作；若系统没有视觉通道，必须用别的方式补上形态学（如主轴比值、各向异性度）。

**注意**：Raymond & Girolami 提醒 ADP 会被热运动、无序、错误占有率混淆，所以它是**线索不是判据**。

**同一段里还有一条优先级规则**（与 §2.1 Herbst-Irmer 的"先试孪晶"独立同源）【一手·逐字】：

> "When a structure appears to be difficult and shows some twin-warning signs [...] it is comparatively easy to try twinning first, before spending hours or days on refining disorders or pseudo-symmetry."

### 6.3 Hirshfeld 刚性键检验

Spek 2009【一手·逐字】：

> "It is assumed in this test that two bonded atoms vibrate along the bond with approximately equal amplitude. Significant differences, i.e. those which deviate by more than a few standard uncertainties from zero, need close examination. Notorious exceptions are metal-to-carbonyl bonds, which generally show much larger differences (Braga & Koetzle, 1988)."

Spek 2020 指出它的历史作用【一手·逐字】：

> "the components of the displacement parameters of the two atoms in a covalent bond have approximately equal opposite values" … "Large deviations may point to erroneously mis-assigned atom types." … "This test turned out to be instrumental in discovering published structures with deliberately changed atom types."

**一个对框架材料极重要的细节**（checkCIF 文档）【一手·单次】：

> "NOTE: The 'Hirshfeld-test' ALERTS are suppressed for polymeric or disordered structures."

即：**MOF/COF（聚合物）或含无序的 CIF 在 checkCIF 里根本没有做 Hirshfeld 检验**: "通过了 checkCIF"在这类结构上不包含这项证据。

### 6.4 超胞 / 漏平移对称的签名

Raymond & Girolami【一手·逐字】：

> "Especially for crystals that contain a small number of heavy atoms, whenever a large fraction of the light atoms in a crystal structure are disordered with site-occupancy factors that are exactly 0.5, the presence of a supercell should be considered. In such cases, the original diffraction images should be re-examined to look for additional weak reflections that would indicate the presence of a larger unit cell."

（实例 QALQID：P2₁/m 里 30 个非氢原子有 26 个无序、wR2 0.17 → c 轴加倍后 P2₁/c 全有序、wR2 0.12。）

**一个完整的现代实例**（自动化失败的教科书案例）【一手·逐字】：

> "the very weak X‐ray reflections with odd k Miller indices had been discarded, resulting in too small unit cells"

> "half of the X‐ray reflections were missed, resulting in incorrect unit cells, incorrect space groups"

> "This causes all reflections with odd l indices to be very weak and only discernible at lower diffraction angles."

> "If these weak reflections are missed or sorted out by the computer, an incorrect unit cell and an incorrect space group result"

> "the correct unit cells can be automatically found using a lower I/sigma threshold value for peak search"

> "The true space groups are Pnam, which are subgroups of Pbam with doubled c."

**这个案例把整条因果链摆出来了**：自动寻峰的 I/σ 阈值 → 弱的超结构反射被剔除 → 晶胞减半 → 空间群错 → 结构错。**补救办法也很具体：降低寻峰的 I/σ 阈值重做。** 这与 §2.4 里 CELL_NOW 要求把 Min I/σ 降到约 5 是同一个道理。

checkCIF 侧的反射端签名【一手·单次】：

> "A low maximum percentage of reflections with I > 2*s(I) may indicate: 1 - Missed translation symmetry. E.g. all reflections hkl weak for l = 2n +1 2 - Pseudo-merohedral twinning, index > 1. (e.g. non-space-group extinctions. 3 - Very weak observed data."

### 6.5 高对称多孔框架里的客体：两个可复现的证伪实验

Raymond & Girolami 引 Poręba et al. 2022 对 BCDD@BUT-17 的反驳【一手·逐字】：

> "A fundamental property of crystallography is that the electron-density distribution around a so-called special position must have the symmetry imposed on that position by the space group. Thus, the electron-density distribution within the pores of a high-symmetry superstructure will have the symmetry of that position. Almost always, this means that the contents of the pores are disordered, so that the interpretation of the apparent electron density will lie in the eye of the beholder. [...] Based on the reported XRD data, we refined the structural model fixing the U_iso to those refined for the MOF organic linkers… The resulting occupancies drop to 1% or smaller except for C17 and C18, which have site occupation factors of ca 8 and 3%, respectively. This clearly shows that the electron-density peaks do not form a connected set of the modeled molecule… We then removed the BCDD from the reported BCDD@BUT-17 and refined a guest-free model. The agreement indices are nearly identical to those for the model including the guest molecule."

**两个实验都可机械执行**：① 把客体 Uiso 固定为骨架值再放开占有率，看是否塌陷；② 精修一个无客体对照模型，比较一致性指标。

### 6.6 Harlow 的"模糊结构"（fuzzy structures）

这是一个独立且重要的错误类别，**它的第一特征恰恰是 R 值好看**【一手·逐字】：

> "The second category, which includes most of the structures being reported today, contains the fuzzy structures."

> "These are firstly and primarily characterized by good R values."

> "Hydrogen atoms, if included at all, refine to poor positions with widely variable, generally high, thermal parameters"

> "may contain atoms with strange-looking anisotropic thermal parameters, atoms which have been constrained or restrained in some fashion"

> "it is difficult to decide whether they are interesting structures or wrong structures."

Harlow 对错误分布的判断【一手·逐字】：

> "Probably the most common error in crystal structures relates to incorrect symmetry, particularly cases where the assigned symmetry is too low."

> "Refinements are often done in the wrong space group and sometimes in the wrong Laue group."

> "Cases where the assigned symmetry is too high appear to be rather rare."

> "the model is forced to fit the "average" of the two asymmetric units"

---

## 第 7 章 氢原子处理

氢是 NeuDiff Agent 论文里点名的"非专家用户的实际瓶颈"，也是 Spek 四级分类里 Class IV（错误结构）的两大成因之一（"too few or too many H atoms"）。这一章单列。

### 7.1 总原则：多数情况下算，而不是自由精修

WinGX/CCP14 镜像的经典教学文档 "Treatment of Hydrogen Atoms"【一手·逐字】：

> "it is preferable to calculate the hydrogen positions according to well-established geometrical criteria."

骑乘模型的机制【一手·逐字】：

> "The hydrogen coordinates are re-idealized before each cycle, and 'ride' on the atoms to which they are attached."

SHELXL 手册对骑乘（AFIX n=3）的定义【一手·逐字】：

> "The coordinates, but not the sof or U (or Uij), ride on the previous non-riding atom."

### 7.2 AFIX 的 m 值编码表（几何类型）

以下全部来自 SHELXL 官方手册【一手·逐字】：

| m | 含义 | 原文 |
|---|---|---|
| 1 | 叔碳 CH | "Idealized tertiary C-H with all X-C-H angles equal" |
| 2 | 仲碳 CH₂ | "with all X-C-H and Y-C-H angles equal" |
| 3 | 甲基 CH₃ | "Idealized CH3 group with tetrahedral angles" |
| 4 | 芳香 CH 或酰胺 NH | "Aromatic C-H or amide N-H with the hydrogen on the external bisector." |
| 5 | 正五边形刚体 | "Next five non-hydrogen atoms are fitted to a regular pentagon, default d=1.42 Å." |
| 6 | 正六边形刚体 | "Next six non-hydrogen atoms are fitted to a regular hexagon, default d=1.39 Å." |
| 7 | 目前同 m=6，保留 | "Currently identical to m=6, reserved for other use in the future (e.g. OH2)." |
| 8 | 羟基 OH | "Idealized OH group, with X-O-H angle tetrahedral," |
| 9 | 端基 X=CH₂ / X=NH₂⁺ | "Idealized terminal X=CH2 or X=NH2+" |
| 11 | 萘环刚体 | "Idealized naphthalene group with equal bonds (default d=1.39 A)." |
| 12 | 无序甲基（两取向差 60°） | "Idealized disordered methyl group; as m=3 but with two positions rotated from each other by 60 degrees." |
| 16 | 炔基 C–H（直线） | "Acetylenic C-H, with X-C-H linear," |

n 值（精修方式）里两个刚体相关的【一手·逐字】：

> "'pivot atom' of a new rigid group"（n=6）

> "The first (pivot) atom of a new _variable metric rigid group_"（n=9）

**U(H) 的处理**【一手·逐字】：

> "it is fixed at T times the Ueq of the previous atom not constrained in this way."

> "-1.2 (1.2 times Ueq of the preceding normal atom)"

教学文档给出的常规选择【一手·逐字】：

> "the standard option is to set the isotropic U's to -1.2 (-1.5 for methyl and hydroxyl)"

### 7.3 HFIX 的用法与陷阱

【一手·逐字】：

> "generates AFIX instructions and dummy hydrogen atoms bonded to the named atoms"

> "must come before the atoms to which it is to be applied"

> "only the first is applied"

（**两条极易踩的坑**：HFIX 必须写在目标原子之前；多条匹配同一原子时只有第一条生效。）

### 7.4 按基团选 HFIX 码（教学文档的成文规程）

【一手·逐字】：

> "the riding model is a good choice for tertiary CH (HFIX 13), secondary CH2 (HFIX 23), ethylenic =CH2 (HFIX 93)."

> "acetylenic CH (HFIX 163), BH in polyhedral boranes (HFIX 153), and aromatic CH or amide NH (HFIX 43)."

**甲基与羟基要看数据质量分两档**【一手·逐字】：

> "the method of choice is HFIX 137 for -CH3 and HFIX 147 for -OH groups."（高质量/低温数据）

> "the hydrogens can be positioned geometrically and refined using a riding model by HFIX 33 for methyl and HFIX 83 for hydroxyl groups."（数据较差时）

> "For disordered methyl groups (with two sites rotated by 60 degrees from one another) HFIX 123 is recommended."

### 7.5 137/147 的旋转搜索机制（值得完整理解）

【一手·逐字】：

> "a difference electron density synthesis is calculated around the circle which represents the loci of possible hydrogen positions."

> "The maximum electron density (in the case of a methyl group after local threefold averaging) is then taken as the starting position."

> "the choice of hydrogen position is then determined by best hydrogen bond (to an N, O, Cl or F atom) which can be created."

即：**沿可能 H 位置的圆周算差值密度 → 取极大值（甲基先做三重平均）作起点 → 羟基另按能形成的最佳氢键定向。** 随后精修时【一手·逐字】：

> "the torsion angles are allowed to refine whilst keeping the X-H distance and Y-X-H angle fixed"

> "the refinement of torsion angles may not converge very well."（数据差时）

### 7.6 检验 H 位置：omit map

【一手·逐字】：

> "enables an 'omit map' to be calculated, which is a convenient way of checking whether there are actually electron density peaks close to the calculated hydrogen positions."

（做法：`OMIT $H` + `FMAP 2` + `PLAN -100`。）

其他可用手段【一手·逐字】：

> "AFIX (or HFIX) 14 etc. performs a similar riding refinement but allows the C-H distance to vary as well."

> "It is possible to use SADI or DFIX to restrain chemically equivalent C-H distances involving different carbons to be equal."

### 7.7 O–H / N–H：必须看差值图

checkCIF 综述【一手·逐字】：

> "Common restrictions include the fixing of carbon-bonded hydrogen atoms on calculated positions and riding them"

> "Their positions should be confirmed in a difference-density map (_vide infra_) and refined whenever possible"

> "their location depends on the presence of available acceptors in their environment"

**即：C–H 可以算；O–H / N–H 应当在差值图里确认并尽可能自由精修，因为它们的取向由环境里有没有受体决定。**

Spek 2009 的对应几何规则见 §5.4（羟基 H 在一个圆锥上并指向氢键受体）。

### 7.8 H 相关的常见错误与警报

【一手·逐字】：

> "generally an indication for a missed hydrogen-atom site."（轻原子旁约 1 Å 处的正密度）

> "Negative densities on a calculated hydrogen-atom site may indicate misplaced hydrogen atoms"

> "Short O⋯O or O⋯N contacts generally point to a missing hydrogen atom in this contact."

> "Short H⋯H contacts may be related to hydrogen atoms placed in incorrect calculated positions."

> "A common problem are the hydrogen-atom positions on a C - CH3 fragment that often need to be rotated by 60°"

> "A wrong hybridization instruction for the calculation of the hydrogen-atom positions may show up"

> "hydrogen atoms on N atoms that are calculated on planar _sp_ 2 locations rather than with tetra­hedral _sp_ 3 geometry"

> "not carrying out a rigid-rotating group refinement for the methyl group"

> "ALERT #977 indicates that atom H9 is located in a location not supported by the data."

> "The #007 ALERT implies that the H-atom positions are not necessarily to be trusted for detailed hydrogen-bond analysis."

### 7.9 金属氢化物 M–H：X 射线的固有困难

IUCr 量子晶体学论文【一手·逐字】：

> "the weak X-ray diffraction signal from the hydrogen atom is screened by the strong signal from the electron-rich metal atom"

> "difficult due to high absorption and radiation damage"

> "Neutron structures, crucial for validating hydrogen positions and thermal motions, are even scarcer."

**独立原子模型（IAM）系统性低估 X–H 键长**【一手·逐字】：

> "The limitations arise from the simplified spherical electron density model"

> "IAM underestimates the lengths of X–H bonds typical for crystals of organic compounds on average by 0.12 Å"

> "mean X–H bond lengths obtained with HAR are underestimated by on average only 0.014 Å"

> "Regarding TM - H bond lengths, traditional HAR exhibits a slight advantage over the other methods."

**这解释了为什么 X–H 距离要用"目标值"而不是自由精修**：常规球形原子模型下 X 射线测到的是电子密度重心而非核位置，系统性短约 0.12 Å；Hirshfeld 原子精修（HAR）能把这个偏差降到 0.014 Å。ACS 的披露清单也专门要求说明"氢化物配体是怎么定位的"（§8.9）。

### 7.10 CF₃ 一类基团

SHELXL 手册【一手·逐字】：

> "an AFIX 6 or AFIX 9 rigid group could be used"

（原因是 F 主导结构因子时骑乘模型不稳定。注意这与 §5.2 里"SIMU 不推荐用于自由旋转基团如 BF₄"是同一类问题的两个侧面。）

### 7.11 FRAG / FEND / RESI

【一手·逐字】：

> "Enables a fragment to be input using a cell and coordinates taken from the literature"

> "often a preliminary to a rigid group refinement"

> "This must immediately follow the last atom of a FRAG fragment."

> "The same atom names may be employed in different residues, enabling them to be referenced globally or selectively."

> "so that cyclic chains of residues may be created"

---

## 第 8 章 验证与发表

### 8.1 checkCIF 的官方语义

Spek 2009【一手·逐字】：

> "The validation software assigns one of four severity levels (A, B, C and G) to reported issues. Level A ALERTS usually indicate that corrective action is imperative or there has to be a scientifically acceptable explanation for the case at hand. Level G ALERTS concern issues that may be correct but should be checked. They can still point to serious problems that could not be analyzed in detail on the basis of the available data. Currently, about 400 validation tests have been implemented."

Spek 2020【一手·逐字】：

> "It should be clear that ALERTS are not necessarily errors." … "They might also point to interesting features in a crystal structure." … "a set of lower-level ALERTS may in combination point to a serious issue that needs to be addressed" … "Validation ALERTS should not be ignored or worked around." … "Level A ALERTS that cannot be resolved should be accompanied by a VRF record" … "It does not give a 'good structure' or 'bad structure' (or 'publish' or 'reject') verdict." "That is left to human beings, either referees or users of the reported results."

**作者本人承认判据是经验性的**（Spek 2009）【一手·逐字】：

> "The validation criteria currently in use are in many cases empirical and based on experience and tradition rather than based on science. Some criteria have changed over time. There is an obvious trade-off between being too critical, leading to too many false ALERTS, and being less sensitive and thus missing multiple weak indications of a serious problem. [...] It sets a quality standard that is not just based on low final R factors"

### 8.2 数值分级（只存在于 IUCr 原生过程，不在 PLATnnn 描述里）

【一手·单次】：

> "IF _refine_ls_R_factor_gt > 0.20 issue ALERT A ... > 0.15 issue ALERT B ... > 0.10 issue ALERT C ... values less than 0.07 are normally expected. Higher values should be accompanied by a suitable explanation in the _publ_section_exptl_refinement section. However, authors should first ensure that there are not overlooked problems associated with the data or the model. ... (c) There is untreated twinning ... (d) The model is incorrect or incomplete in terms of incorrect element assignment, missing atoms or unmodelled or inadequately modelled disorder or solvent atoms. ... The value of Rint (i.e. '_diffrn_reflns_av_R_equivalents') should normally be considerably less than 0.12 and in the order of magnitude of the reported R-values. ... The data/parameter ratio of a quality structure determination in a centrosymmetric space-group is expected to be higher than 10. ... Alert C The least squares goodness of fit parameter lies outside the range 0.80 <> 2.00"

**注意最后一段的结构**：每一个数值门后面都跟着"作者应先排除吸收/晶体质量/未处理的孪晶/错劳厄群/模型错或不完整"——**阈值是诊断的触发器，不是判决**。

### 8.3 完整度与截断（PLAT023/027/029/909）

【一手·单次】：

> "Ideally (and a requirement for publication in Acta Crystallographica), this fraction should be close to 1.0 for theta-full greater or equal to sin(theta/lambda) = 0.6 (i.e. 25.24 degrees for MoKa and 67.7 degrees for CuKa radiation). ... 3 - Incomplete scans, possibly based on erroneously assumed higher than actual symmetry."

**最后半句很重要**：不完整度的一个成因是**按错误的（过高的）对称性制定了采集策略**。

### 8.4 ADP 类警报被明确定位为元素指认诊断

【一手·单次】：

> "Too high or too low Ueq's may be an indication for incorrectly identified atomic species (i.e. O versus N). ... Atomic sites assigned the wrong scattering type (e.g. Ag versus Br) should generate 'problem signals' with this test. Data sets corrected for absorption effects with DELREF techniques (e.g. DIFABS, SHELXA, XABS2) often show large DELU values for bonds involving the heaviest atom. ... The value of SQRT(U3/U1) main axis ADP ratio (Angstrom Units) is tested for the main residue(s). Large values may indicate unresolved disorder. Oblate criterium: U3 - U2 < U2 - U1. Prolate otherwise."

### 8.5 空腔与掩膜类警报

【一手·单次】：

> "Voids of 40 Ang**3 may accommodate H2O. Small molecules such as Tetrahydrofuran have typical volumes in the 100 to 200 Ang**3 range. ... A paper reporting a crystal structure with a significant solvent accessible void should at the least discuss the issue. ... Such a warning might also indicate that the symmetry is incomplete e.g. should have been specified as P-1 and not P1, leaving out half of the unit-cell content. ... The presence of an ABIN instruction in the SHELXL .ins file implies the use of the PLATON/SQUEEZE or OLEX2/MASK tool [...] Generally, the contribution to the structure factors is expected to be on an absolute scale in electrons per unit-cell. ... Good quality low order reflections might be relevant for SQUEEZE and similar solvent modelling refinement techniques."

**"空腔太大可能是漏了对称"** 是一条容易被忽略的交叉证据。

### 8.6 漏对称与孪晶的检验（PLAT110–116 / 908 / 930 / 931）

【一手·单次】：

> "Tests for missed symmetry are done with ADDSYM, an extended MISSYM (C) clone. These tests warn for missed or possible higher (pseudo) symmetry in the structural model (i.e. based on the coordinate data). Close examination of the situation at hand is indicated in order to prove/disprove the issue (usually in combination with the reflection data). ... NOTE: Atom types are treated in this test as EQUAL for structures with less than 250 atoms in the asymmetric unit in order to detect cases of possibly misassigned atom types."

**"故意把所有原子类型当成相同"** 是为了抓元素指认错，这是个巧妙的设计。

### 8.7 反射数据能做而模型做不到的验证

Spek 2009【一手·逐字】：

> "Some problems, such as missed or ignored twinning as an explanation for an unsatisfactory refinement result, may only show up in an analysis of the reflection data. The submission of reflection data as a structure-factor file (Fo/Fc data in CIF format) is required for a structural publication in Acta Crystallographica. This allows automatic checking for missed twinning."

### 8.8 Spek 的四级结构质量分类

【一手·逐字】：

> "Class IV structures are incorrect. Important examples are those in which some of the element-type assignments are wrong or models with too few or too many H atoms. [...] Validation should avoid having Class IV structures ever appear in print. [...] The displacement ellipsoids of the N and C atoms clearly suggested that they should be interpreted as the atom types O and B, respectively. Hirshfeld (1976) rigid-bond test ALERTS sent out similar signals."

分类概要：Class I 近完美低温高分辨；Class II 常规好结构；Class III 化学正确但精度有限、一般不宜发表除非附深入分析；**Class IV 错误结构：元素指认错、H 太多或太少**。

### 8.9 期刊与数据库要求（ACS 系）

【一手·逐字】：

> "In addition, authors are required to upload the checkCIF output files (combined into one PDF file) as Supporting Information for Review Only. Any A and/or B level alerts must also be addressed prior to submission or otherwise explained in the checkCIF PDF."

> "In addition, authors are required to deposit structure factor tables with the CCDC alongside their CIFs. Structure factor tables should include h, k, 1, Fo, Fc, and |Fo| values. The embedded original, unmerged, uncut, unmasked hkl file must be embedded in the CIF file."

（**注意** "original, unmerged, uncut, unmasked"：即使精修时做了 SHEL 截断、SQUEEZE/掩膜或 OMIT，嵌入 CIF 的必须是原始未动的 hkl。这条直接对抗"丢数据降 R"。）

> "It is the responsibility of the author(s) to check all CIFs for the following prior to submission: • Syntax errors • Numerical self-consistency of the data • Possible higher symmetry in the space group assignment."

> "If restraints or constraints on non-hydrogen atoms or adjustments to the structure factors are used in the refinement of a crystal structure, these should be described in detail in the experimental section and their application justified. Data from complementary experiments should be made available to resolve any ambiguities arising from problems with a refinement."

**最小披露清单（体系无关，可直接当模板）**【一手·逐字】：

> "Clearly state whether more than one independent molecule or any solvent molecules were found in the lattice. Include a paragraph or single table summarizing the crystal parameters, unit cell constants, and refinement metrics along with the thermal ellipsoid plot in the supporting information. Special molecular symmetry, such as an inversion center should be noted. Disorder or partial (solvent) occupancy, together with how this was modeled or refined should be noted. Describe how any similarly sized ligands were distinguished (CO, NO, CN, etc.) and how any hydride ligands were located. With non-racemic compounds, the method by which the absolute configuration was assigned should be detailed."

### 8.10 "checkCIF 干净"与"结构正确"是两回事

Raymond & Girolami【一手·逐字】：

> "A principal take-home lesson from this article is that checkCIF is a great program, but it is entirely possible for a completely incorrect model to have a flawless report, and for a completely correct structure to give a report that contains lots of alerts (for example, because it does not diffract strongly, or it is not possible to apply a good absorption correction). This situation reflects a fundamental limitation of current automated structure-checking packages: they are numerically competent but chemically unsophisticated. Their use must be augmented by an analysis of the model by a knowledgeable and skilled chemist."

Clegg 的实例（Co-salen）是这句话的具体化【一手·逐字】：

> "There were no significant checkCIF alerts except for indications of unresolved disorder in the substituent chains as already noted. The structural model could be improved somewhat with some chain disorder modelling. This structure is, however, wrong."

**但这不构成"不必跑验证"的理由**（Müller 2009）【一手·逐字】：

> "Use automated validation software such as PLATON (22) before publishing a structure. Everybody makes mistakes and automated validation programs point out potential problems that should be looked into."

**两句话必须一起读**：自动验证**必须跑**（它抓的是人会犯的错），但**跑干净不等于结构对**（它抓不到化学层面的错）。这正是 §17.6 checkCIF 分型的意义所在，1 型（语法/缺数据）是自动验证的强项，2 型（模型可能错）才是它力有未逮的地方。

### 8.11 错误的概率取决于数据质量 × 操作者水平

【一手·逐字】：

> "Wrong structures are more likely if there are problems with the crystal, such as poor resolution, weak intensities, disorder, twinning, pseudosymmetry, etc. With good data and a skilled crystallographer/chemist, the chance of a major error is almost zero. With bad data and a skilled crystallographer/chemist, or good data and an unskilled crystallographer/chemist, there is a small chance of a major error. With bad data and an unskilled crystallographer/chemist, a major error becomes rather likely."

---

## 第 9 章 自动化与专家系统：前人的设计与教训

### 9.1 PLATON System S：一个"有晶体学学位的主管"

【一手·逐字】：

> "SYSTEM-S is for the professional chemical crystallographer who is bored by the routine input/output preparation/analysis cycle, but knowledgeable about the procedural details and aware of all signals of possible trouble. [...] SYSTEM-S operates as a supervisor (with a crystallographic degree and with an organized memory) over the process of a single crystal structure determination [...] Guided Mode: The program suggests the course of the structure determination on the basis of the current context. [...] Sub-directories of a level-0 directory include level-1 trees (one for each lattice type that is attempted). Sub-directories of a level-1 directory include level-2 trees (one for each space group attempted to solve the structure in)."

**全自动模式的边界与失败回退策略**【一手·逐字】：

> "The NQA-mode (and Silent mode) obviously works only in the case of (relatively) trouble free structures (i.e. no disorder, twinning and similar specialist issues). [...] NQA This is the No-Questions-Asked mode to operate S. This option may be used to see whether a default structure determination leads to interpretable results. If not, various other options should be tried including solution in alternative spacegroups with alternative structure solution techniques."

**把漏对称检查放进流程的固定位置**【一手·逐字】：

> "Addsym is invoked automatically (unless switched off) at the start of the anisotropic refinement. [...] Example: Solve the 'sdemo' structure not in P21/c but in Pc (# 7). At the anisotropic refinement stage, a message 'M/P P21/c' in RED will appear to attract attention to the possibly missed or pseudo-symmetry."

**方法选择启发**【一手·逐字】：

> "DIRDIF The method of choise for heavy atom structures. DIRDIF may have problems with structure determinations run with an incorrect CONTENTS formula, in particular when the number of heavy atoms is different from the number suggested. [...] SIR SIR97 provides an excellent alternative for SHELXS. It is slower but often gives results with large poorly reflecting (low resolution) data sets."

### 9.2 xia2：把每个决策当成"待检验的假设"

Winter, Lobley & Prince 2013 的设计哲学，对 harness 设计极有参考价值【一手·逐字】：

> "Any results from this are necessarily empirical, as it is impossible to derive the correct choices from first principles."

> "Any justification for the protocols can only be empirical in nature"

**反馈架构**（这是最值得学的一条）【一手·逐字】：

> "considering all 'decisions' made about the data set as hypotheses to be subsequently tested"

> "If subsequent analysis indicates that a result is incorrect this will be flagged and a new result calculated"

> "The loop structure of each module ensures that invalid results can be recalculated"

**一条具体且可移植的判据**（晶格约束是否合适）【一手·逐字】：

> "If the r.m.s. deviations are made substantially worse by applying the Bravais lattice constraints it is unlikely that the lattice constraints are appropriate."

> "The ratio of the r.m.s. deviations with and without the lattice constraints was lower than 1.5 in all cases"

> "1.5 is taken as the limit on acceptable values, and no counterexamples have been found to date."

**分辨率判据与用户控制权**【一手·逐字】：

> "By default the merged and unmerged I/σ(I) are used, with thresholds of 2 and 1, respectively."

> "Too low a limit will result in throwing away useful data"

> "the user has complete control over the resolution-limit criteria"

**一条原理性限制**【一手·逐字】：

> "It is, however, impossible to determine the hand of a screw axis (e.g. 41 versus 43) from intensity data alone."

### 9.3 CRYSTALS：把专家知识放进可修改的脚本层

【一手·逐字】：

> "CRYSTALS aims to provide novice users with the expert decision-making tools required for undertaking unsupervised structure determination."

> "built-in guidance and validation using 'The GUIDE'."

> "The decision-making system and validation tools are written in CRYSTALS' own macro language, SCRIPTS"

> "so that they can be modified to accommodate expert knowledge without users needing to become expert programmers"

（**设计取向值得注意**：决策系统写在脚本层而不是编译代码里，目的正是让专家知识可以被后续修改进去。）

### 9.4 CrysAlisPro + AutoChem：实时自动化的形态与自认边界

【一手·逐字】：

> "During the automatic data collection and reduction process this window will only display feedback after the first 25 frames have been collected, since data reduction will not start until this point. This is so that a good estimate of the average background can be established, requiring 25 consecutive frames. The automatic data reduction will process newly collected data in batches of 25 frames [...] If AutoChem is installed, structure solution will also be attempted every 25 frames."

AutoChem 2.0 手册对自身能力边界的自陈【转述】：Auto 模式会把所有可用求解与精修方法都试一遍取最优；但明确写着无法处理显著无序或孪晶分解，这些情况需要人介入。

### 9.5 NeuDiff Agent（2026）：目前最接近的"受治理的 LLM 代理"

这是与自主 harness 最可比的已发表系统，设计取舍值得完整记录【一手·逐字】：

> "we define a verification gate as a deterministic check that must be passed before a workflow state transition is accepted. If a check fails, the workflow halts and requires a user-authorized corrective action. ... The user authorizes each tool execution and approves any corrective action required to clear a failed verification gate. ... NeuDiff Agent is designed to preserve scientific judgment by concentrating expert intervention at explicit checkpoints, rather than embedding judgment in opaque automated steps or dispersing it across repeated bookkeeping."

**四类检查的划分**【一手·逐字】：

> "Tool-verified execution checks Mantid reduction log signatures and output completeness; SHELXL convergence and residual patterns; displacement parameter plausibility Flags the failure mode and suggests a targeted corrective step (parameter change, restraint or data selection) with justification ... (iv) parsing of Mantid and SHELXL logs for known failure signatures, including non-convergence and physically unreasonable displacement parameters"

**知识分两层、用户数据不进检索库**【一手·逐字】：

> "(ii) the neutron knowledge schema containing long-lived facility facts such as instrument geometry, valid angle ranges, canonical file locations and typical parameter bounds ... User experimental data are never added to the retrieval knowledge base."

**成果与作者自陈的局限**【一手·逐字】：

> "Across five independent runs per backend, NeuDiff Agent reduces the baseline time of 435 min to 86.5 ± 4.7 min (Gemini 3.0 Pro) and 94.4 ± 3.5 min (GPT-OSS 120B). ... R1 0.1846 0.0554 wR2 0.4594 0.1297 GoF 2.195 1.062 ... the practical scientific bottleneck for non-expert users is completing the hydrogen substructure that is absent or unreliable in the starting X-ray model"

> "A single representative TOPAZ dataset is used as a prototype reference case ... used the original X-ray CIF as the starting model ... the checkCIF verification gate triggered at the start of publication validation with 6 level A, 0 level B, 5 level C and 15 level G alerts ... This required seven intervention events: six metadata completions and one chemical-formula consistency correction. ... Extending controlled replay to additional TOPAZ datasets spanning varied crystal systems, experimental conditions and data quality will quantify how general the current verification gates are"

**读法**：它没有做从头定群与求解（起点是已知 X 射线 CIF），A 级警报清的全是元数据；它的价值在**架构**（确定性验证门 + 知识外置 + 检查点集中人类判断），不在能力覆盖。

### 9.6 Olex2 的引擎与掩膜实现细节

Olex2 官方帮助【一手·逐字】：

> "The refinement engine built into Olex2."

> "supports all ShelXL instructions, plus a number of new restraints and constraints that are not available from ShelXL."

> "will not 'forget' the special instructions"（切换引擎时）

**一个非常重要的实现差异**【一手·逐字】：

> "is added internally to that calculated from the ordered part"（olex2.refine 路线：溶剂贡献**加到**有序部分的计算值上）

> "is subtracted from the observed data"（ShelXL 路线：溶剂贡献从**观测数据**里减去）

**这解释了为什么"带掩膜"的差值图与 R 因子在两条路线下不能直接互比。**

掩膜算法与参数【一手·逐字】：

> "as the discrete Fourier transform of the electron density in the solvent area"

> "a region occupied by disordered solvent"

> "based on the BYPASS paper by P. van der Sluis and A. L. Spek."

> "prevents displaying voids in which no atom could fit."（Solvent r 默认 1.2 Å）

> "usually very close, if not equal, to the solvent radius."（Truncation）

> "'1/2 toluene' or 'CH2Cl2'"（建议在掩膜信息表里填入空腔的估计内容，写进 CIF）

循环数语义的差别【一手·逐字】：

> "if the refinement converges earlier, the refinement process will stop automatically"（olex2.refine：上限）

> "the actual number of refinement cycles"（ShelXL：实跑次数）

算法选择【一手·逐字】：

> "most suited for small molecule structures"（LS）

> "faster than LS when the number of parameters is large"（CGLS）

> "when the refinement converges poorly"（切到 Levenberg–Marquardt）

Olex2 专有的限制（ShelXL 没有的）【一手·逐字】：

> "Restrains all provided rings (e.g., C6, C5N, SC4) to be regular, i.e., flat with all interatomic distances similar."（RRINGS）

> "Adds a distance restraint for the atom pairs and an "angle" restraint for the atom triplet."（TRIA）

> "Restrains the ADPs of the selected atoms to the Ueq value provided."（ADPUEQ）

> "The volumes of the ADP ellipsoids of the selected atoms will be restrained to be the same."（ADPVOL）

---

## 第 10 章 3D 电子衍射与调制结构（覆盖较薄，标注清楚）

### 10.1 运动学 vs 动力学

Klar et al. 2023（Nature Chemistry）【一手·逐字，仅摘要级】：

> "Dynamical diffraction effects cause non-linear deviations from kinematical intensities"

> "up to fourfold reduction of the noise level in difference Fourier maps"

> "the routine determination of absolute structures"

**关键概念**：3D-ED 的运动学精修 R 因子普遍远高于 X 射线（因为多次散射未被建模），**R 高不等于模型差**；动力学精修显著改善模型精度与差图噪声，并使**绝对构型的常规测定**成为可能。

【证据强度说明】nature.com 正文需机构鉴权、PMC 镜像被机器人验证拦截、ChemRxiv/ResearchGate 403，因此"12 个化合物"、"58 颗晶体 / 9 种手性化合物"等细节以及作者关于"两类 R 不可比"的原话**未取得逐字正文**；上面三条短语来自该刊 CC BY 摘要的元数据镜像。Palatinus et al. 2015 的两篇理论/实测论文（Acta Cryst. A71, 235–244；B71, 740–751）均为 IUCr 403，**未取得原文**。

### 10.2 Jana2020 的定位

【一手·逐字】：

> "the successor to the well-known Jana2006, designed for solving regular, modulated, and magnetic structures"

> "the leading software for structure analysis of aperiodic samples"（指 Jana2006）

> "visualizes standard, modulated, and magnetic structures"

> "can read electron diffraction data processed by the PETS program and directly communicates with Dyngo"

> "corrects derivatives of structure factors for dynamical effects"

> "that of X-ray-based structure analysis"（称藉由动力学精修，3D-ED 模型精度可接近 X 射线水平）

### 10.3 尚未补齐的部分（诚实标注）

以下主题在本轮调研中**没有取得一手逐字材料**，列出以备后续补齐：

- MicroED 小分子实践的数据筛选标准（Org. Lett. 2024 的完整度 >65% / Robs <30% / 分辨率 <1.1 Å / CC1/2 >97%），ACS 403、NSF PAR 镜像返回未解码 PDF 流。**这些数字目前只有检索转述级证据，不可直接引用。**
- 卫星反射 / 非公度调制在指标化阶段的识别征兆，未取得一手成文描述。目前只知道 Clegg 把"commensurate and incommensurate modulation"列为自动化常常完全忽略的问题类别（§0.4），以及 CrysAlisPro 的"Data reduction with options"里人可以指定非公度 q 矢量（§1.2）。
- 超空间群（3+1）D 的精修实务。
- Petříček et al. 2023 的 Jana2020 论文原文（De Gruyter 返回 405）。

---
---

# 第二部分：第二轮调研补编（2026-09-03）

> 第一轮（第 0–10 章）覆盖了从数据还原到发表的主干。第二轮针对 `workdir/knowledge-gap-register.md` 里逐条盘点出的缺口补齐：**指标化与积分本身**（第 11 章）、**化学层验证与特殊位置**（第 12 章）、**Linden 的完整 best-practice**（第 13 章）、**反常散射与波长选择**（第 14 章）、**精修的判断力**（第 15 章）、**病态结构分类学**（第 16 章）、**精修力学与交付合规**（第 17 章）、**采集侧决策与旁证表征**（第 18 章）。
> 相关章节之间已加交叉引用。**两部分共用文末的附录 A（数值锚点）与附录 B（来源清单）**，第二轮新增的锚点见附录 A 下半部分。

## 第 11 章 指标化与积分：决策点与失败模式

第 1 章讲的是"积分之后"的事（缩放、吸收、截断）。这一章补上"积分之前和之中"——这正是自主 harness 在驱动、却最没有知识支撑的一段。

### 11.1 指标化算法的选择

DIALS 提供四条不同的路线，各有适用场景【一手·逐字】：

> "dials.index provides both one-dimensional and three-dimensional fast Fourier transform (FFT) based methods." "These can be chosen by setting the parameters indexing.method=fft1d or indexing.method=fft3d."

**1D FFT**【一手·逐字】：

> "Search for the basis vectors of the direct lattice by performing a series of 1D FFTs along various directions in reciprocal space." "This has a lower memory requirement than a single 3D FFT (the fft3d method)." "This method may also be more appropriate than a 3D FFT if the reflections are from narrow wedges of rotation data or from stills data."

**3D FFT**【一手·逐字】：

> "Search for the basis vectors of the direct lattice by performing a 3D FFT in reciprocal space of the density of found spots." "Since this can be quite memory-intensive, the data used for indexing may automatically be constrained to just the lower resolution spots."

**已知晶胞的实空间网格搜索**（困难情形的主力）【一手·逐字】：

> "Index the found spots by testing a known unit cell in various orientations until the best match is found." "This strategy is often useful for difficult cases of narrow-wedge rotation data or stills data, especially where there is diffraction from multiple crystals."

**低分辨率斑点匹配（专为电子衍射静止图像）**【一手·逐字】：

> "A lattice search strategy that matches low resolution spots to candidate indices based on a known unit cell and space group." "Designed primarily for electron diffraction still images."

XDS 走的是另一条技术路线，**差向量法**，其参数含义【一手·逐字】：

> "Maximum allowed deviation from 'integerness' of computed indices of a reflection" "Maximum magnitude of index differences between reflections" "Minimum quality of indices required for a reflection to be included in the shortest tree."

> "Minimum distance between diffraction spots required when depositing their vector difference in the histogram" "Maximum radius of a difference vector cluster (pixel units)."

### 11.2 指标化失败的成因与征兆

**头号单一成因是几何输入错误，不是晶体不好**【一手·逐字】：

> "Errors in the values of ORGX, ORGY (as supplied in XDS.INP) are the most common single source of indexing failure."

**基本自检：差向量应接近整数**【一手·逐字】：

> "ideally these should be close to integral numbers (1, 2 3, ...)" "If the difference vectors are not (close to) integers, something is wrong"

**"标定率不足 50%"是有意设计的提醒**【一手·逐字】：

> "!!! ERROR !!! INSUFFICIENT PERCENTAGE (< 50%) OF INDEXED REFLECTIONS" "This is a feature (not a bug) to make the user aware of a possible problem."

**其他成因**【一手·逐字】：

> "This is due to either wrong inputs in XDS.INP, or due to bad data, e.g. spots from many crystals whose diffraction patterns overlap."

> "the crystal changed its orientation within the SPOT_RANGE by more than ~ 0.1°" "This can happen if SPACE_GROUP_NUMBER is wrong" "!!! WARNING !!! REFINEMENT DID NOT CONVERGE"

### 11.3 多晶格：怎么发现、怎么分离、以及一条重要告诫

**发现**【一手·逐字】：

> "The "subtrees" each refer to their own lattice." "IDXREF will choose the lattice with most reflections, but the user should be aware that other lattices exist!"

> "it may result from one or more additional crystals contributing to the diffraction patterns" "the histogram of indexed spots often has two equally-large subtrees" "your crystal may really be triclinic"

（**最后半句值得记住**：两个规模相当的子树，也可能只是说明晶体真的是三斜的。）

**分离流程**【一手·逐字】：

> "Now you have (basically) indexed lattice 1." "This will remove the non-indexed spots and run IDXREF again." "Maybe you have a third (fourth etc) lattice? Then repeat step 3 for this one ... etc"

**告诫（这一条对自动化尤其重要）**【一手·逐字】：

> "just because XDS decides not to use some spots for indexing doesn't mean these initially non-indexed spots really belong to a separate lattice"

DIALS 侧的多晶格参数【一手·逐字】：

> "max_lattices = 1" "minimum_angular_separation = 5" "The minimum angular separation (in degrees) between two lattices." "recycle_unindexed_reflections_cutoff = 0.1" "Attempt another cycle of indexing on the unindexed reflections if more than the fraction of input reflections are unindexed."

（与第 2 章 CELL_NOW 的"真孪晶律必须是简单操作"判据配合使用：**能指标化出第二个晶格 ≠ 是孪晶**。）

### 11.4 Bravais 晶格判定：怎么读输出

【一手·逐字】：

> "Refinement of Bravais settings consistent with the primitive unit cell." "in all Bravais settings that are consistent with the input primitive unit cell"

> "A table is printed containing various information for each potential Bravais setting, including the metric fit" "(a measure of the deviation from the triclinic cell)" "the root-mean-square-deviations (rmsd), in mm, between the observed and predicted spot centroids" "the refined unit cell parameters in each Bravais setting" "the change of basis operator to transform from the triclinic cell to each Bravais setting"

**判据的具体形态**（这是 §9.2 里 xia2 那条"rms 比 < 1.5"规则在教程输出里的实际读法）【一手·逐字】：

> "the options 3, 4, 5 have higher symmetries, but at the cost of a steep jump in RMSd's and worsening of fit."

XDS 侧的对应量【一手·逐字】：

> "The above list is sorted by the "Quality of fit" - good values are below 10."

**一个与"非标准设置"直接相关的细节**【一手·逐字】：

> "if the change of basis operator (cb_op) for the chosen Bravais setting is not the identity operator (a,b,c)." "If True, then for monoclinic centered cells, I2 will be preferred over C2 if it gives a less oblique cell (i.e. smaller beta angle)."

（即：单斜 C 心晶胞在 β 角过于倾斜时，程序会主动选 I2 设置，这正是第 3 章 Marsh 型"非标准设置"问题的上游来源之一。）

### 11.5 积分：轮廓拟合 vs 求和

**两种方法的定义与分工**【一手·逐字】：

> "the integrated intensity is obtained as the sum of all background-subtracted pixel values in the peak region." "For weak data, fitting the pixel intensities against an empirical reflection profile has been shown to give better estimates"

**化学晶体学实践中的实际分工**（关键句）【一手·逐字】：

> "the stronger reflections are dominated by summation-integrated values and the weaker reflections by the results of profile fitting."

**部分反射的两种输出形态**【一手·逐字】：

> "as either individual partial reflection intensities or as a single value summed across all of the frames on which the reflection is recorded." "This ensures that the majority of reflections are fully recorded within a single block"

**背景估计**【一手·逐字】：

> "This is accomplished by using information from nonpeak pixels in the local area of each spot." "an important step in the background modelling is to ensure that the estimated background is not contaminated by outlier pixels" "the default background-modelling algorithm in DIALS uses a robust generalized linear model approach" "has been shown to be effective even when the average background is below one count per pixel"

**轮廓拟合的开关与前提**【一手·逐字】：

> "Use profile fitting if available" "The minimum fraction of foreground pixels that must be valid in order for a reflection to be integrated by profile fitting."

> "if (total_reflections > overall or reflections_per_degree > per_degree) then do the profile modelling." "The minimum number of spots needed to do the profile modelling"

（**推论**：斑点太少时轮廓建模根本不会发生，弱数据/小楔形数据上"用了轮廓拟合"这个假设需要核实。）

### 11.6 积分阶段的坏数据征兆

| 病征 | 一手表述 | 处置 |
|---|---|---|
| 冰环 | "This nicely shows ice rings, and may also help to find shaded regions on the detector." "it may just be the case that there are ice rings with very many isolated ice reflections" "in that case you may want to use EXCLUDE_RESOLUTION_RANGE for the IDXREF task" | 按分辨率区间排除 |
| 溢出/饱和 | "a reflection is overloaded if it includes one or more overloaded pixels." | 一个饱和像素即判整条反射溢出 |
| 挡块阴影 / 坏区 | "This allows you to remove a rectangle from the trusted detector plane." "Pixels covered by the largest ellipse that fits into this rectangle are considered as 'untrusted'." | 屏蔽矩形/椭圆区域 |
| 劈裂斑点 | "If the spots are split or unclean, you may get a seemingly terrible match between observed and calculated spot positions" "26303 REJECTED REFLECTIONS (REASON: TOO FAR FROM IDEAL POSITION)" | 大量"离理想位置过远"的剔除即信号 |
| **卫星反射** | "I've seen datasets where each reflection had a satellite associated with the main reflection, but separate from it." | 每个主反射旁伴随分离的伴生反射，**这是调制/非公度结构在积分期的样子**（呼应 §12.2 的倒易层图像检查） |
| 积分期参数不稳 | "the refinement of parameters (during the INTEGRATE step) can be very unstable" | 留意距离/原点/镶嵌度的异常跳变 |

找斑点阶段的常见问题【一手·逐字】：

> "Removed 17040 spots with size < 3 pixels" "Removed 1 spots with size > 1000 pixels" "Issues with incorrectly set gain might, for example, lead to background noise being extracted as spots."

### 11.7 精修诊断：rmsd、离群点、scan-varying

**rmsd 的读法**（一条很实用的通则）【一手·逐字】：

> "As long as each macrocyle shows a reduction in RMSDs then refinement is doing its job" "The RMSDs at the start of each cycle start off worse than at the end of the previous cycle" "because the best fit model for lower resolution data is being applied to higher resolution reflections."

**离群点剔除的算法与阈值**【一手·逐字】：

> "If auto is selected, the algorithm is chosen automatically." "The IQR multiplier used to detect outliers. A value of 1.5 gives Tukey's rule for outlier detection" "uses an algorithm based on FAST-MCD by Rousseeuw and van Driessen." "Observations whose robust Mahalanobis distances are larger than the obtained quantile will be flagged as outliers."

> "Detecting centroid outliers using the Tukey algorithm" "Detecting centroid outliers using the MCD algorithm" "Large outliers can dominate refinement using a least squares target, so it is important to be able to remove these."

**scan-varying 精修：两阶段与平滑区间**【一手·逐字】：

> "For rotation scans, the model may be either static (the same for all reflections) or scan-varying" "Allow models that are not forced to be static to vary during the scan, Auto will run one macrocycle with static then scan varying refinement for the crystal"

> "Two passes of refinement are actually done here" "an initial pass where unit cell and crystal rotation is consistent over the length of the experiment" "a second pass where these are allowed to vary." "allows compensation for small missets in the rotation of the goniometer, and compensation for changes to the unit cell" "typically due to radiation damage." "the refinement looks for smooth changes over intervals of 30°, to avoid fitting unphysical models to noise"

**rmsd 目标截断的单位**【一手·逐字】：

> "Method to choose rmsd cutoffs." "the natural discrete units of positional data, viz., (pixel width, pixel height, image thickness in phi)." "Absolute Values for the RMSD target achieved cutoffs in X, Y and Phi. The units are (mm, mm, rad)."

### 11.8 本章未取得的一手材料

- Le Page 度量对称搜索算法与 Niggli 约简的专门论述（J. Appl. Cryst. 2022 "Niggli reduction and Bravais lattice determination"），IUCr 与 ResearchGate 均 403。
- Leslie (1999) "Integration of macromolecular diffraction data"——IUCr 403。
- MOSFLM 用户指南，站点不可达。
- **Bruker SAINT 官方手册，公网无可抓取的一手文档**（专有资料，随许可提供）。这意味着 Bruker 侧的积分决策我们只能从 SADABS 手册与第三方 SOP 反推。

---

## 第 12 章 化学层验证与特殊位置记账

第 6 章讲的是从模型反推错误（键长、ADP、Hirshfeld）。这一章补上**化学自洽**（氧化态、电荷、几何期望值）与**特殊位置的占有率记账**：后者是 CIF 写作里一个真实且常见的陷阱。

### 12.1 键价和（BVS）：能用在哪、不能用在哪

**参数的含义**（Brown 2009 综述）【一手·逐字】：

> "R0, the notional length of a bond of unit valence, and b, the softness parameter."

**b = 0.37 Å 是惯例而非常数**【一手·逐字】：

> "is found to lie between 0.3 and 0.6 Å"

> "For this reason a value of 0.37 Å is frequently assumed although recent work discussed in section 7.3 shows that significantly different values should be used for some bond types."

综述里有一整节的标题就是在质疑它【一手·逐字】：

> "Is the Value of b Constant?"

> "there is no unique value for b for a given bond type since its value depends on the arbitrarily chosen maximum bond length"

**最重要的一条：BVS 在原理上不适用于有机化合物**【一手·逐字】：

> "unfortunately excludes C−C and C−H bonds and therefore large parts of organic chemistry."

> "the principal limitation of the model"

（**这条限定必须随判据一起给出**：把 BVS 当成通用化学检查会在纯有机结构上给出无意义的结论。它的适用域是离子性/配位化合物。）

**偏离程度的量化指标**【一手·逐字】：

> "The root-mean-square deviation of the experimental bond valence sums from the atomic valence"

> "measures the degree of failure of the valence sum rule."

（即全局不稳定性指数 G。）

**未取得**：Brown & Altermatt (1985) Acta Cryst. B41, 244 的原文（IUCr 付费墙）；键价公式本身在综述页面里是图片，文本层无该字符串，故不作逐字引用。

### 12.2 特殊位置：占有率必须按位置重数折算

SHELXL 手册【一手·逐字】：

> "should be multiplied by the multiplicity of that position (as given in International Tables, Volume A)"

> "an atom on a fourfold axis will usually have 10.25 in the sof position."

**程序会自动施加约束，但你手工写了它就不再管**【一手·逐字】：

> "the program will automatically work out and apply the appropriate positional, sof and Uij constraints for any special position."

> "reports but does not apply the correct constraints."

> "can lead to the refinement 'blowing up'!"

（最后一句指：把自由变量误用在特殊位置原子的 Uij 上会让精修发散。）

**相关约束指令**【一手·逐字】：

> "The same x, y and z parameters are used for all the named atoms."（EXYZ，常用于同一位点被不同元素共占）

> "The same isotropic or anisotropic displacement parameters are used for all the named atoms." "EADP applies an (exact) constraint,"

> "The following atoms belong to PART n of a disordered group." "the generation of special position constraints is suppressed"（PART 取负值时；用于溶剂无序占据了高于分子自身对称性的特殊位置，例如对称心上的甲苯）

> "The combination of atom name, PART and RESI numbers must be unique,"

### 12.3 occupancy ≠ SOF：一个真实的 CIF 陷阱

checkCIF 说明文【一手·逐字】：

> "is sometimes confused with the site-occupancy factor (SOF)"

> "should be reported with an occupancy of 1.0 in the CIF"

> "sso = nsym/ssm"

> "SOF = occupancy/sso"

**读法**：位于对称心（位置对称性乘子 0.5）且**完全占据**的原子，在 SHELXL 里 SOF 记 0.5，但写进 CIF 的 `occupancy` 必须是 **1.0**。把 SOF 直接抄进 CIF 会让化学式与占有率整体错一个因子，这是自动化写 CIF 时极易踩的坑。

### 12.4 体积与堆积的自洽检查

**每非氢原子约 18 Å³ 的规则**: Linden 2020 是我们取得的一手出处【一手·逐字】：

> "the 18 Å3 per atom rule"

（他把它用在从晶胞体积反推 Z、进而判断晶系是否被自动软件定错的场景，见 §13.1。）

**堆积系数**（PLATON 文档）【一手·逐字】：

> "have a typical packing index of in the order of 65 %" "Kitaigorodskii type of packing index" "a 'free' extra with the VOID calculation"

> "in small pockets, too small to include isolated atoms"

**空腔体积的化学折算基准**（比 §8.5 的 checkCIF 版本更细）【一手·逐字】：

> "A hydrogen bonded H2O-molecule 40 Ang^3" "Small molecules (e.g. Toluene) 100-300 Ang^3"

**"正常结构不该有大空腔"的经验基准**【一手·逐字】：

> "do not contain solvent accessible voids larger than in the order of 25 Ang**3" "Use the CALC SQUEEZE instruction to calculate and optionally correct for"

### 12.5 配位几何描述符 τ₄ / τ₄′ / τ₅

**证据强度说明**：本节内容取自 Wikipedia "Geometry index" 条目（**二手**），原始文献（Addison 1984 / Yang 2007 / Okuniewski 2015）本轮未取得全文。公式与极限值属于可独立验算的数学定义，风险较低；但**不应把本节当作一手出处引用**。

**五配位 τ₅**（Addison, Rao, Reedijk, van Rijn & Verschoor, 1984, *J. Chem. Soc., Dalton Trans.* 7, 1349–1356）：

- τ₅ = (β − α) / 60°，其中【二手·逐字】"β > α are the two greatest valence angles of the coordination center."
- 【二手·逐字】"When *τ*5 is close to 0 the geometry is similar to square pyramidal, while if *τ*5 is close to 1 the geometry is similar to trigonal bipyramidal"
- 极限：四方锥 β = α = 180°；三角双锥 β = 180°, α = 120°。

**四配位 τ₄**（Yang, Powell & Houser, 2007, *Dalton Trans.* 9, 955–964）：

- τ₄ = [360° − (α + β)] / (360° − 2θ)，其中【二手·逐字】"θ = cos−1(− 1/3) ≈ 109.5° is a tetrahedral angle."
- 分母 360° − 2θ ≈ **141°**：文献中常见的 "τ₄ = [360 − (α+β)]/141" 写法就是把这个常数先算了出来，两者等价。
- 【二手·逐字】"When *τ*4 is close to 0 the geometry is similar to square planar, while if *τ*4 is close to 1 then the geometry is similar to tetrahedral."

**四配位 τ₄′**（Okuniewski, Rosiak, Chojnacki & Becker, 2015, *Polyhedron* 90, 47–57）：

- τ₄′ = (β − α)/(360° − θ) + (180° − β)/(180° − θ)
- 提出动机【二手·逐字】：τ₄ "does not distinguish *α* and *β* angles"，故 τ₄′ "adopts values similar to *τ*4 but better differentiates the examined structures"。
- 【二手·逐字】"Extreme values of *τ*4 and *τ*4′ denote exactly the same geometries"，且 τ₄′ ≤ τ₄ 恒成立。
- 区分能力的实例：跷跷板型（β = 180°, α = 120°）给出 τ₄ ≈ 0.43 而 τ₄′ ≈ 0.24。

**对 harness 的含义**：这些是**描述符**，不是**判据**：它们把一个配位多面体压缩成一个 0–1 的数，用于**报告几何类型**，而不是用于判定结构对错。把 τ 值卡阈值当成"配位环境合理性检查"是误用：一个 τ₅ = 0.5 的中间态既可能是真实的畸变，也可能是建模错误，单凭该数无法区分。

### 12.6 本章未取得的一手材料

- **Mogul / CSD 几何统计**如何生成键长键角期望分布，CCDC 页面为 JS 渲染、ACS 与镜像均 403。**另外一个值得记录的负面结果**：在已抓到全文的 checkCIF 说明文里**没有出现 "Mogul" 字样**，checkCIF 的几何类检验走的是 Hirshfeld 刚性键等另一套机制，不能想当然认为两者相连。
- Spek 2009 里 NO₃⁻ 实为 CO₃²⁻ 的电荷平衡改判实例原文（IUCr 403、PLATON 镜像 PDF 无文本层），该实例的转述见 §8.8，但逐字原文未取得。
- Acta Cryst C/E 作者须知中关于电荷平衡的成文要求。
- checkCIF PLAT076（特殊位置占有率警报）原文，403。
- Steed 2003 关于 Z′>1 的定义与统计（RSC 403）。

---

## 第 13 章 Linden (2020)：一份完整的"best practice"清单

Linden, A. (2020). *Obtaining the best results: aspects of data collection, model finalization and interpretation of results in small-molecule crystal-structure determination.* Acta Cryst. E76, 765–775. （PMC7273997，开放获取）

这篇是本知识库里最接近"专家把整条流程的经验一次讲完"的一份，且**多处与本项目的设计原则直接呼应**，故单列一章。

### 13.1 采集阶段的一个具体陷阱

场景：β ≈ 90.2° 的单斜晶体被仪器软件当成正交【一手·逐字】：

> "the diffractometer software might decide that this unit cell is orthorhombic and automatically collect sufficient data for orthorhombic"

症状与后果【一手·逐字】：

> "the user discovers that it is impossible to find a suitable orthorhombic space group or solve the structure."

> "the data are incomplete, because a needed part of the monoclinic data was not collected"

他给的对策：用 **"the 18 Å3 per atom rule"** 反推 Z；拿不准时按**低对称**收；或直接收满半球。以及两句通则【一手·逐字】：

> "having more than enough data is always better than insufficient data"

> "High redundancy in the data, such as at least fivefold, is normally recommended"

（**这与 §8.3 checkCIF 列出的不完整度成因"按错误的过高对称制定采集策略"是同一件事的两侧。**）

### 13.2 倒易点阵层图像：数字看不出来的东西

【一手·逐字】：

> "at least the hk0, h0l, and 0kl layers"

> "the presence of twinning, streaks, diffuse scattering, satellite reflections, a split crystal or just a plain poor crystal."

> "some unexpected features might only appear in one of them."

**这条补上了本知识库此前最大的一个方法空白**：调制结构（卫星反射）、层错（条纹、漫散射）、劈裂晶体这些在数值统计里很难现形的问题，有一个统一且廉价的入口，**看三层倒易图**。呼应 §3.1 Palatinus 关于 P4₁ 螺旋轴"看一张模拟进动图就一目了然"的说法，以及 §11.6 卫星反射在积分期的表现。

### 13.3 孪晶数据的处理

【一手·逐字】：

> "If twinning is evident, the integration should be repeated with two or more orientation matrices."

得到的文件包含两个域的非重叠反射加上重叠反射，"thereby giving the most complete data set."

**对 PLATON 捷径的警告**【一手·逐字】：

> 生成的 HKLF5 "will contain only the overlapping reflections and the non-overlaps from one twin domain"，因为第二个域的非重叠反射 "were never included in the original HKLF4 file."

> "to see if this is the better data set or not."（应回到原始帧重做并比较）

### 13.4 无序与限制：一条正向原则加一条反向警报

**正向原则**【一手·逐字】：

> "Do not restrain or constrain a model to be that which it is not"

**反向警报（很实用）**【一手·逐字】：

> "If significant difference-map peaks appear on the original atom positions after you apply restraints"

（即：加了限制之后，**原子原来的位置上冒出显著差值峰**，说明限制正把模型拉离真实。）

**s.u. 起点比 SHELXL 默认更紧**【一手·逐字】：

> "one can use initial s values of 0.005 or 0.01, which are smaller than the SHELXL default values."

**验收判据**【一手·逐字】：

> "the final s.u.s on restrained parameters, such as bond lengths, should be similar to those on equivalent unrestrained parameters"

**限制优于约束**【一手·逐字】：

> "SIMU, DELU and/or RIGU restraints are preferred over EADP constraints"

（理由是例如 CF₃ 的氟原子并不共享椭球取向。与 §5.2 SHELXL 手册"SIMU 不推荐用于自由旋转基团"要放在一起读，两者约束的是不同层面。）

### 13.5 氢原子

【一手·逐字】：

> "It is recommended, if the data quality allows it, to try refining freely at least the H atoms bonded to heteroatoms (O, N, …)"

> "A high value suggests an incorrect position or insufficient information in the data to decide."（Uiso 作为诊断）

> "it is quite in order to omit such H atoms from the model, provided that the fact is documented clearly"

> "one must always check the calculated positions for –OH, –NH, –NH2 and H2O."

> 把它们指向最近的受体 "is not always the correct choice."

> 对角锥化的 1,2-苯二胺，用 "the SHELXL HFIX 93 instruction would be incorrect."

（最后一条是 §7.8 "N 上的 H 被按平面 sp² 而非四面体 sp³ 计算"这一常见错误的具体实例。）

### 13.6 checkCIF 之外的验证

【一手·逐字】：

> "Validation with checkCIF often does not detect such issues."（指 N 原子杂化）

> "A clean validation report does not necessarily mean that all is in order."

> "checkCIF does not detect this for an isolated species in the rigid-bond test, the atom-type test"（错元素的情形）

> "when taken together with other alerts in the list, they could indicate a real issue with the results."

**两句箴言**【一手·逐字】：

> "if it looks weird, it probably is!"

> "Seeing is believing."

以及【一手·逐字】：

> "It is ill-advised to attempt to hand-edit data in a CIF"

### 13.7 结果的推导与报告：s.u. 的现实

**差值显著性怎么算**【一手·逐字】：差值的 s.u. 是两个 s.u. 平方和的平方根。工作实例：1.523(3) 与 1.545(4) Å 相差 0.022(5) Å，即 4.4σ——

> "may be considered to be just significantly different"

而若两者 s.u. 都是 (7)，差值变成 "0.022 (11) Å or 2.1σ"，则

> "no justification for claiming that the bond lengths are significantly different"

**一条必须知道的系统偏差**【一手·逐字】：

> "s.u.s from crystal-structure refinements tend to be underestimated"

（他给的量级是约 1.5 到 2 倍。）

**其他**【一手·逐字】：

> "it is essential to document fully all non-routine procedures used during data collection and structure refinement."

> "It is ambiguous to state, for example, that a chain propagates in the (100) plane."（方向用方括号表示矢量、圆括号表示晶面）

> PLATON 的 s.u. 只在 "if the CIF is used as the input file." 时可用

### 13.8 非常规特征有多常见

【一手·逐字】：

> "In my experience, no two structure determinations are entirely alike"

> "many 'special features' can appear maybe once in 50 or more structures"

> "One might successfully complete many structure determinations before encountering a seldom-occurring 'feature' for the first time."

> "an extensive toolbox of tricks, knowledge and experience to fall back on."

> "New structural features, such as an unusual bond length, are quite rare these days"

**他的总结性告诫**【一手·逐字】：

> "resist the temptation to click, click, click without the accompanying check, check, check as you go."

**这一节量化了自动化的难处**：特殊情形"大约每 50 个结构出现一次"意味着，在几个测试晶体上表现良好，与"能处理任意未知晶体"之间隔着一条统计上的鸿沟。

### 13.9 绝对构型：Flack 值该怎么读

**读的是值与 s.u. 的组合，不是值本身**【一手·逐字片段】：

> "A value of 0.01 (2) is a confident indicator"

> "However, 0.0 (2) is inconclusive"

理由：s.u. 为 0.2 时，3σ 区间上界可达 +0.6，等于什么都没判定。

**Flack & Bernardinelli 的 s.u. 上限**（本条同时补上缺口 H6 的一手转述）【一手·逐字片段】：

> 已知对映体纯的化合物："the s.u. on the Flack parameter should be less than 0.1"

> 若晶体可能是外消旋的："the s.u. should be less than 0.04"

**Flack 值既不接近 0 也不接近 1 = 反演孪晶**，此时 SHELXL 必须上 TWIN + BASF，否则【一手·逐字片段】：

> "One consequence can be a bias in the geometrical parameters."

（注意后果不只是 Flack 本身不可信，而是**几何参数被系统性带偏**：这比"报个错值"严重得多。）

**空间群本身就能否决手性**【一手·逐字片段】：

> 手性中心出现在中心对称群（或含镜面/滑移/反轴的群）中，意味着 "the compound is necessarily racemic."

**一条常被忽略的边界**【一手·逐字片段】：

> "the chosen crystal is not necessarily representative of the composition of the bulk material"

> 95% 对映体过量的溶液，仍可能长出一颗外消旋晶体而恰好被挑走。

**操作细节**：OLEX2 用 `inv -f` 反演，会同时切换对映异构群对（如 P6₁ → P6₅）。

### 13.10 一个直接打在"元素指认"上的实例

Linden 给的例子里，同一个位点按**氯离子**建模与按**水分子**建模，R 因子差出三倍【一手·逐字片段】：

> "The _R_-factor is somewhat elevated at 0.061."（按氯离子）

> "the _R_-factor is 0.021 when the chloride ion is replaced by a water mol­ecule."（按水）

**这是本知识库里最直接的一条"元素指认错误可以用 R 因子发现"的一手证据**。它同时说明：R 因子偏高不必然是数据差，也可能是**某一个原子的元素判错了**：而这正是 §6.4 ADP 反常与 §12.1 化学自洽应当联合起来查的场景。

### 13.11 差值图的正确用法

【一手·逐字片段】：

> 差值图 "produced with the _PLATON ContourDif_ option" 可以确认氢的位置

> "The _ContourDif_ function has options to display the H-atom positions"（把该氢对图的贡献扣除后再看该位置是否真有电子密度）

**读法**：判断一个氢该不该存在，正确做法不是看它精修后跑不跑，而是**把它从图里扣掉、看那里本来有没有密度**。这条对自动化尤其重要，它给了"该不该加这个 H"一个可计算的判据，而不是靠几何模板硬加。

**注意本文未涉及的话题**（避免把它当成万能清单）：Linden 2020 **没有**讨论 OMIT/剔反射的纪律、收敛判据/shift-esd、权重方案、残余峰的数值阈值、以及 SQUEEZE 的方法学（只在"必须披露的非常规操作"清单里点了一次名）。这些仍是本知识库的空缺，见缺口清册 E3/E5。

---

## 第 14 章 反常散射、吸收边与波长选择

本章补的是知识库里最要命的一个物理空白：我们**真出过 Zr K 边事故**（用了 0.68883 Å 波长），却在第一轮里一条一手原文都没有。

### 14.1 物理起源

低能光子与高能光子的区别（Merritt 教学页）【一手·逐字】：

> 低能时："The photon is either scattered or not, but is not absorbed as it has insufficient energy to excite any of the available electronic transitions." "The photon scatters with no phase delay (imaginary, or f", component is 0)."

> 高能时："Some photons are absorbed and re-emitted at lower energy (fluorescence)." "Some photons are absorbed and immediately re-emitted at the same energy (strong coupling to absoption edge energy)."

> "The scattered photon gains an imaginary component to its phase (f" scattering coefficient becomes non-zero); i.e. it is retarded compared to a normally scattered photon."

**f′ 与 f″ 的关系**【一手·逐字】：

> "The imaginary scattering component f" is proportional to these directly measurable quantities. The real scattering component f' is related to f" via the Kramers-Kronig relationship."

（**诚实说明**：我们想找的"f′ 在边前显著变负"这句成文表述**未取得**。Merritt 页只到 Kramers-Kronig 为止；f′ 的负值要从元素数值表读，本轮未抓到数值页。）

### 14.2 Friedel 定律与 Bijvoet 差

**定义与定律**（Merritt, *Breaking Friedel's Law*）【一手·逐字】：

> "Friedel pairs are Bragg reflections related by inversion through the origin."

> "Friedel's Law states that members of a Friedel pair have equal amplitude and opposite phase."

> "Friedel's Law is broken whenever there is anomalous scattering."

> "If all atoms scatter equally, then the amplitudes remain equal but the phase relationship no longer holds."

> "If some atoms scatter anomalously and some don't, then both the amplitude and phase relationships are broken."

**同一命题的现代期刊表述**（El Omari et al. 2024, Acta Cryst. D80, 713–721）【一手·逐字】：

> "Consequently, the atomic scattering factor (f) for each atom would be directly proportional to the atomic number (Z), implying that all atoms scatter X-rays similarly, thereby adhering to Friedel's law (|Fhkl| = |F−h−k−l|)."

> "When this adjustment occurs, Friedel's law is broken, resulting in asymmetry between symmetry-related reflections within the same data set, as the f′′ phase shift introduces intensity differences called anomalous differences."

**一条必须区分开的表述**（Fanwick, CCDC 教学材料）【一手·逐字】：

> "AS arises from absorbed then emitted photons."

> "AS is important in both centric and accentric space groups."

> "Discovered by the Dutch crystallographer Johannes Bijvoet."

**第二句很重要，且容易被误读成相反的意思**：反常散射在**中心对称与非中心对称空间群里都存在、都重要**：它会改变 |F| 本身（影响标度、消光、精修）。**"中心对称群里没有反常散射"是错的**；正确的说法是"中心对称群里反常散射**不产生 Bijvoet 差**"（因为 Friedel 对被对称性联系起来，两者振幅恒等）。我们系统里若有"中心对称 ⇒ 反常散射不可用"这类措辞，应当收窄为"⇒ **不能用 Bijvoet 差定绝对构型**"，而不是"反常散射不起作用"。

**必须记录的一条空缺**：我们已经把"中心对称空间群里 Bijvoet 差恒为零"写进了系统规则，但**两轮调研都没能取得同时含 "centrosymmetric" 与 "Bijvoet difference is zero" 的一手逐字表述**。上面 Merritt 的 "If all atoms scatter equally, then the amplitudes remain equal" 与 El Omari 的 Friedel 定律式在逻辑上覆盖了它，但不是该命题本身的成文出处。IUCr Acta Cryst. A 相关论文被 Cloudflare 拦截，archive.org 在本网络环境**完全不可达**（首页即 HTTP 000，非页面级问题）。**该规则目前属于"我们相信它对、但引不出原文"的状态，应如实标注。**

### 14.3 吸收边附近的信号强度

【一手·逐字】：

> "Above the edge, both the measured anomalous signal and f′′ are typically high (f′′ = 4 e− at the absorption K edges), whereas below the edge the anomalous signal and f′′ are either negligible or significantly reduced."

**这条给出了 Zr 事故的物理解释**：波长跨到吸收边的哪一侧，f″ 差出的不是几个百分点，而是"高"与"可忽略"之别。

**理论值本身在边附近不可靠**（Cromer–Liberman 近似的边界）【一手·逐字】：

> "This theory gives accurate values far from an absorption edge but does not account for the effects of neighboring atoms, which can be very substantial near an absorption edge."

**对 harness 的直接含义**：靠近吸收边时，"查表得到 f′/f″"这一步本身就不可靠，这是一个**必须触发警告而不是静默继续**的情形。

**理论值到底错在哪**（Merritt, *Theory vs reality*，以蓝铜蛋白中 Cu 位点的实测谱与理论值对照）【一手·逐字】：

> "The Cromer/Liberman theoretical values for scattering factors are not accurate for energies very near an absorption edge. Here the interaction of the scattering atom with its chemical neighbors complicates the scattering behaviour considerably."

他逐条列出的四个偏差【一手·逐字】：

> "The actual absorption edge is shifted relative to the idealized edge for an isolated Cu atom. The largest part of this shift is due to the oxidation state of the Cu atom in the protein."

> "The local chemical environment introduces "ripples" (EXAFS) into the scattering spectrum."

> "The maximum achievable f" is actually larger than the edge jump from theory. (The effect isn't very large in this particular example, but sometimes it is substantial)."

> "The maximum achievable |f'|, however, is smaller than the theoretical value. This is largely limited by the energy bandwidth of the x-ray source."

**第一条是本节最有价值的一句**：查表得到的吸收边位置，是**孤立原子**的理想边；真实化合物里的边会移位，**主因是氧化态**。这意味着"我的波长离 Zr 的 K 边还差一点，应该安全"这种基于表值的推断本身带有系统误差，所以边附近的正确姿态是**留出余量并报警**，而不是精确贴边。

（顺带：`|f'|` 这个写法本身印证了 f′ 在边附近取负值，但我们仍未取得"f′ 变负"的成文陈述句，见 §14.1 的说明。）

**一条来自 MAD 实践的旁证，边附近对波长精度的要求有多苛刻**（Merritt, *Choosing wavelengths*；MAD 是蛋白定相技术，但这条讲的是波长控制精度，与体系无关）【一手·逐字】：

> "The largest signal will come from choosing the wavelength with maximal f''"

> "The second wavelength is usually chosen to have maximal |f'|"

> "very close together, requiring great precision in setting up the apparatus which controls wavelength during data collection."

**两点**：① 取 f″ 极大与取 |f′| 极大的两个波长**挨得极近**，近到"需要极高的波长控制精度"——这与 §14.5 我们自算出的"1.7 × 10⁻⁴ Å 内 f″ 落差 7 倍"是同一现象的两种表述，一个来自蛋白 MAD 实践，一个来自我们自己的数值表。② `|f'|` 这个绝对值写法再次印证 f′ 在边附近取负值。

**长波长的实用边界**（Merritt, *Chart of absorption edges*）【一手·逐字】：

> "Absorption edges below 6 keV correspond to x-ray wavelengths > 2A, which present practical difficulties for use in crystallography."

（6 keV ≈ 2.07 Å。与 §14.4 中 Cr Kα 2.2909 Å 的分辨率/吸收代价互相印证。）

### 14.4 波长选择的权衡

**轻原子定绝对构型为什么难**（Parsons et al. 2017）【一手·逐字】：

> "it is always very weak for crystals of compounds containing no element heavier than oxygen"

> "Resonant scattering effects are smallest for the `light atoms' of the first two periods of the periodic table..."

> "In general it is advisable to collect diffraction data on such materials with Cu K radiation, but an illustration of the power of the new methods has been given by Escudero-Adán, Benet-Buchholz and Ballester, who successfully determined a series of light-atom absolute structures using Mo K radiation."

（**注意最后半句**：Mo 波长下做轻原子绝对构型**不是不可能**：所以"轻原子 + Mo ⇒ 直接判定不可定"是过强的规则。）

**更长波长的代价**【一手·逐字】：

> "One option might appear to be to carry out data collections with still longer X-ray wavelengths, such as Cr K radiation ( = 2.2909 Å). The values of f for C, N and O at this wavelength are about double those for Cu K. However, this approach compromises the maximum practically attainable resolution, which is about 1.2 Å for Cr K, compared to about 0.8 Å for Cu K, while systematic errors due to absorption also become substantial."

**这是本知识库里唯一一条把"波长 ↔ 反常信号 ↔ 可达分辨率 ↔ 吸收误差"四者串起来的定量原文**，值得作为波长决策的骨架。

**Ag 辐射（0.56 Å）**：来源为 Ruf et al. 2025 会议摘要，措辞明显带厂商推介色彩（"a noble choice"、"the preferred option"），**证据强度低**，仅可用于确认 Ag Kα ≈ 0.56 Å 这一事实与"高角数据/强吸收样品"的适用方向，不宜作为判据来源。

**能量，波长换算**（Merritt）【一手·逐字】：

> "X-ray energy in keV = 12.398/λ in Å"

### 14.5 我们自己算出来的 Zr K 边（本项目实测，非文献）

**证据类型标注：以下不是文献引语，是我们用本项目 venv 内的 cctbx（`cctbx.eltbx.sasaki` 表）现算的结果**，脚本见 `workdir/fdp_scan.py`，输出存档 `workdir/fdp_scan_output.txt`。之所以自己算，是因为 §14.6 记录的原因，网上的数值表取不到。

Zr 跨 K 边的扫描（E = 12.3984 / λ）：

| λ / Å | E / keV | f′ | f″ |
|---|---|---|---|
| 0.67000 | 18.5051 | −2.826 | 3.537 |
| 0.68000 | 18.2330 | −3.664 | 3.640 |
| 0.68600 | 18.0735 | −4.877 | 3.703 |
| 0.68800 | 18.0210 | −6.138 | 3.724 |
| **0.68883** | **17.9992** | **−9.041** | **2.772** |
| 0.68900 | 17.9948 | −7.910 | **0.529** |
| 0.69000 | 17.9687 | −5.855 | 0.530 |
| 0.69500 | 17.8395 | −4.204 | 0.537 |
| 0.70000 | 17.7120 | −3.642 | 0.544 |
| 0.71073 (Mo Kα) | 17.4446 | −3.039 | 0.560 |

**三条结论**：

1. **我们出事的那个波长 0.68883 Å 几乎正好压在 Zr 的 K 边上。** 边的位置落在 0.68883 与 0.68900 之间，两者相差 **1.7 × 10⁻⁴ Å**，而 f″ 跨过这道坎从 ~3.7 掉到 **0.529**，相差约 **7 倍**。这个间距远小于常规仪器的波长标定精度，也小于"我离边还有一点点"这种直觉判断能分辨的尺度。**这就是 §14.3 那句"实际边相对理想边有位移、主因是氧化态"在数值上的后果**：贴着边工作时，表值给的边位置本身就有不确定度，而结果对边位置极其敏感。

2. **f′ 在边附近确实取显著负值，且是一个尖峰。** 从 −3.0（Mo Kα）一路加深到边上的 −9.0 - **相当于 Zr（Z = 40）少了 9 个电子，约占其散射能力的 22%**。这不是小修正，会直接影响结构解析与元素指认。§14.1 里我们没能取到"f′ 变负"的成文陈述句，这张表是我们自己的替代证据。

3. **正好落在边上的那一行（f″ = 2.772）本身就不可信。** 它比边上方（3.7）和边下方（0.53）都不是，这是表格在不连续点两侧插值产生的假值。**换句话说，在边附近，"查表"这个动作本身就没有正确答案可给。** 这反过来印证了 §14.3 的结论：正确姿态是**留余量 + 报警**，而不是相信表值精确贴边。

**实验室波长下的 f′/f″（同一计算）**，可作为元素指认与绝对构型判断的快查表：

| 元素 | Ag Kα (0.56087 Å) f′ / f″ | Mo Kα (0.71073 Å) f′ / f″ | Cu Kα (1.54184 Å) f′ / f″ |
|---|---|---|---|
| Zr | −0.656 / 2.639 | −3.039 / 0.560 | −0.313 / 2.247 |
| Cu | 0.266 / 0.830 | 0.261 / 1.270 | −2.017 / 0.590 |
| Zn | 0.261 / 0.942 | 0.219 / 1.435 | −1.609 / 0.679 |
| Fe | 0.244 / 0.548 | 0.301 / 0.848 | −1.188 / **3.202** |
| Br | 0.086 / 1.653 | −0.390 / 2.468 | −0.767 / 1.283 |
| Cl | 0.084 / 0.099 | 0.132 / 0.159 | 0.348 / 0.703 |
| S | 0.069 / 0.077 | 0.111 / 0.124 | 0.319 / 0.558 |
| O | 0.003 / 0.004 | 0.008 / 0.006 | 0.046 / 0.032 |
| N | 0.001 / 0.002 | 0.004 / 0.003 | 0.029 / 0.018 |
| C | 0.000 / 0.001 | 0.002 / 0.002 | 0.017 / 0.009 |

**读法**：

- **C/N/O 的 f″ 在任何实验室波长下都在 0.001–0.05 量级**：这是 §14.4 中 Parsons "轻原子共振散射效应最小"那句话的定量版本，也解释了纯有机化合物定绝对构型为什么难。即便如此，Cu Kα 下 O 的 f″（0.032）是 Mo Kα 下（0.006）的 **5 倍**，这就是"轻原子建议用 Cu"的全部依据。
- **Fe 在 Cu Kα 下 f″ = 3.202**：这是含铁样品用 Cu 辐射会强烈荧光、抬高背景的定量原因。属于"波长选择必须看样品元素组成"的典型案例。
- **S 与 Cl 在 Cu Kα 下 f″ 分别为 0.558 / 0.703**：这就是"用 Cu 辐射靠 S 定绝对构型"这一常规做法的物理基础。

**给系统的直接含义**：这张表说明，**"用什么波长"不是一个可以随数据带过来就照单全收的元数据**，它与元素组成、绝对构型可判定性、荧光背景、以及吸收边风险都强耦合。一个通用 harness 至少应当在读入波长后，**对样品中每个元素检查其吸收边与该波长的距离**，并在距离过近时报警，而不是只把波长当成计算 d 值的一个常数。

### 14.6 本章未取得

- checkCIF **PLAT984** 原文（403；archive.org 不可达）。
- **Merritt 站点的元素 f′/f″ 数值表，已查明取不到，不必再试**：`scatter/data/<Elem>.html` 返回 404；数值是由 `AS_periodic.html` / `AS_form.html` 两个 **CGI 表单**动态生成的，没有可直接抓取的静态页。若确实需要数值，应改用本地 cctbx（`cctbx.eltbx.sasaki` / `henke` 表）自行计算，而不是继续爬这个站。
- IUCr Acta Cryst. A (1995) *Friedel's law and non-centrosymmetric space groups*: Cloudflare 拦截。

---

## 第 15 章 精修的判断力从哪里来（Watkin 2008 / Sheldrick 2008 / Harlow）

Watkin, D. (2008). *Structure refinement: some background theory and practical strategies.* J. Appl. Cryst. 41, 491–522.

**这一章是本轮调研中与本项目设计原则最直接对应的一份材料**：它几乎是逐字论证了"综合判断力优先于参数阈值"。

### 15.1 约束 vs 限制：适用边界

【一手·逐字】：

> "When an analyst has no doubt about a functional relationship between parameters in the physical model, constraints are the correct tool to use to feed this information into the refinement. A more flexible tool for influencing the outcome of a refinement under less clear-cut conditions is the use of the 'observations of restraint', usually just called restraints (Waser, 1963)."

**限制的两种正当用途**【一手·逐字】：

> 情形一："The starting model is very poor, and the user suspects that the minimization space is full of false minima. Suitable soft restraints may help the minimization move towards an acceptable (and hopefully correct) minimum – they provide a guide through the minimization space. Once the solution is 'correct', the restraints can be slackened or removed so that the structure becomes the one 'seen' by the X-ray data only."

> 情形二："Normal refinement has produced an unacceptable structure, i.e. one that does not conform in detail to the accepted rules of chemical bonding... Alternatively, the result could imply that the data are inadequate in some way or that the model is under-parameterized. If the data cannot be improved and the user cannot think of additional valid parameters to add to the model, restraints should be investigated as a way to achieve a preconceived end result."

（**注意最后半句的措辞**：Watkin 直白地把情形二的限制称为"达成一个**预先设定的**结果"的手段，他没有粉饰。这正是为什么情形二必须配 §15.2 的残差判据：一旦你在朝预设结果推，唯一能拦住你的就是"数据是否在抗议"。）

**读法**：情形一里"解对了就该松开甚至去掉限制，让结构变成 X 射线数据自己'看见'的那个"——这是一条**限制的退出条件**，比"加了限制就一直留着"要严格得多。

### 15.2 限制是否合理：一条可计算的判据

【一手·逐字】：

> "This conflict will be evident as a large value for the restraint residual (Tobs − Tcalc). Residuals larger than about three times the requested standard uncertainty should always be investigated."

**工作实例（四苯并环丁烷）**【一手·逐字】：

> "Requesting an s.u. of 0.001 [Å] makes the two bonds very similar but is slightly in conflict with the X-ray data – the R factor rises. Restraining them to the unrealistic bond length of 1.29 [Å] with a reasonable s.u. has little effect on the model, and the residual (1.29 − Dcalc) = 0.10 greatly exceeds the requested s.u. of 0.01 [Å], showing that the restraint is inappropriate."

**这是一条可以直接落成工具的判据**：把每条限制的残差与其所设 s.u. 相比，比值 > 3 的必须被报出来。它比"看 R 有没有变好"敏感得多，且与 §13.4 Linden 的"限制之后原来位置冒出差值峰"是两个独立的、可互相印证的信号。

### 15.3 参数数量：大象与指导原则

【一手·逐字】：

> "If more parameters are refined than the data will support, their values risk becoming meaningless – hence Stewart Pawley's comment 'It is often said that with enough parameters you could fit an elephant.' Let us coin the phrase 'elephant parameter' for any model parameter that has no relevance to reality."

**关键的一句**【一手·逐字】：

> "The IUCr guidelines for the observation:parameter ratio are only guidelines, and the model refined in every structure analysis must be judged on its own merits."

**这句话应当被当成本项目的一条外部背书**：连观测数/参数比这种最"客观"的指标，原作者都明说它只是指导原则，每个结构必须按自身情况判断。把它硬编成通过/不通过的阈值，是对文献本意的曲解。

### 15.4 结构质量的分级与"看起来不对"

Harlow (1996) 的四分类【一手·逐字】：

> "Harlow (1996) divides refined structures into four classes – 'quality structures', which are the gold standard analyses obtained by careful work on very good crystals; 'fuzzy structures', which are the normal run-of-the-mill products from routine analytical work; 'incorrect structures', which are ones where a fundamental error has been made; and finally 'junk' structures."

**判断的性质**【一手·逐字】：

> "Even if we have good statistical information, final distinctions have to be made on the basis of experience and the general consensus of the crystallographic community. This may sound dangerously close to 'chi-by-eye' (Press et al., 2005), but it is perhaps better than putting blind faith in insecure statistical inference. If a structure 'looks wrong', it probably is wrong. The converse is not necessarily true."

（**注意最后一句的不对称性**：看起来不对 ⇒ 多半真不对；但**看起来对 ⇏ 就是对的**。这正是"checkCIF 全绿不等于结构正确"在精修侧的同构表述，见 §13.6。）

### 15.5 失败本身是信号：不必然是操作失误

【一手·逐字】：

> "A structure could satisfy Harlow's 'junk' criteria simply as a result of careless work, in which case the result is worthless. However, if the sample preparation and data collection have been carefully performed, failure to refine to a conventionally fuzzy structure (or better) is an indication that something unusual is happening in the diffraction process, which may be worth reporting and reinvestigating. Nature is not always so obliging that she invariably follows the laws that we make."

**这段对自主 harness 极其重要**。它说的是：在采集环节确实做扎实的前提下，**精修精不下去本身是一条关于样品的信息**（可能是调制、层错、孪晶、相变），而不是默认判定为"agent 没做好"。这条应当反向约束我们的评分逻辑，把所有失败一律归因于执行方，会教会系统去**掩盖**异常而不是**报告**异常。

（同时要与 §13.10 的实例并置：也确实存在"R 高只是因为某个原子元素判错了"的情形。所以正确的姿态是**两条都查**，而不是二选一地信任其中一条。）

### 15.6 期刊侧的根本困境

【一手·逐字】：

> "The problem for the journals is to try to distinguish between good work on bad crystals and bad work on good crystals. If all you have is a CIF, the two cases must look very similar."

**这句话直指本项目评分体系的软肋**：只看最终 CIF 的数值指标，无法区分"在烂晶体上做了好工作"与"在好晶体上做了烂工作"。任何只用 R1/wR2/GOF 打分的评分器，都继承了这个不可分辨性。要区分，必须看**过程证据**（做了哪些诊断、如何取舍、异常如何披露），而不只是终值。

### 15.7 氢原子作为可靠性的敏感探针

Harlow (1998)，经 Watkin 转引【一手·逐字】：

> "I have a lot of confidence in structures where the hydrogen atoms were found and refined to reasonable positions (e.g. 0.85 < C--H < 1.05 [Å]) and with reasonable thermal parameters (e.g. 2.0 < Biso < 6.0 [Å]2). The hydrogen atoms appear to be very sensitive indicators of a reliable structure and simply don't refine well if there are even modest errors in the data or the model, or if the data is insufficient for the structural analysis."

**读法**：H 精修得好不好，是**整体可靠性**的探针，而不只是 H 自己的问题。这与 §7 章"骑式 H 是妥协而非真相"并不矛盾，它说的是：当数据允许自由精修 H 时，H 的表现能反向诊断数据与模型。

### 15.8 天平动：s.u. 之外的系统性偏差

【一手·逐字】：

> "This large libration results in a significant apparent shortening of the bond lengths."

> "The bond-length adjustments are almost ten times as large as the s.u. computed from the normal matrix."

**含义**：键长的**系统性**偏差可以是最小二乘 s.u. 的十倍。所以"键长在 3σ 内 ⇒ 正常"这类判断，在有明显天平动的基团上是失效的。与 §13.7 "s.u. 本身被低估 1.5–2 倍"叠加，说明**任何以 s.u. 为分母的自动判据都必须留出余量**。

### 15.9 无序情形下的限制 s.u. 需要人工调

【一手·逐字】：

> "Restraints are commonly used in cases of disorder to ensure normal bond lengths and ADPs. The standard uncertainties of the restraints are adjusted manually to achieve a desired conformity with the target values."

（呼应 §13.4 Linden 建议从 0.005–0.01 起步、再放松。）

### 15.10 Sheldrick 2008：SHELX 的适用边界

Sheldrick, G. M. (2008). *A short history of SHELX.* Acta Cryst. A64, 112–122.

**直接法的硬门槛**【一手·逐字】：

> "The strongest restraint is still the requirement of atomic resolution (ca 1.2 [Å]). All three programs are able to solve much larger structures if heavier atoms (even S or Cl) are present (especially when SHELXD or SIR make use of the Patterson), and for such structures the resolution requirement is much less rigid."

**"更好的程序存在，但 SHELX 仍被广泛使用"**【一手·逐字】：

> "...refinement and SHELXS and SHELXD are often employed for structure solution despite the availability of objectively superior programs."

> "Although several other powerful and user-friendly direct-methods programs are now available, for example SnB (Miller et al., 1993, 1994), SIR (Burla et al., 2005) and SHELXD [...], that can solve much larger structures and also obtain more complete solutions, SHELXS is still widely used."

**历史细节**（SHELX-76 的两条直接法指令）【一手·逐字】：

> "The first of these, the EEES instruction for centrosymmetric structures, represented phases as 0 or 1 to save computer time and memory. It was very efficient for straightforward small structures. The second, the TANG instruction for non-centrosymmetric structures, required an experienced user to select the origin and enantiomorph-fixing reflections by hand; it was inspired by MULTAN"

**对本项目的含义**：1.2 Å 原子分辨率是**从头直接法**的门槛，且**有重原子时这个门槛显著放松**：这解释了为什么我们在含金属的 MOF 上从头建模顺利，而在纯有机体系上退化（见分析文档中已证实的第三条缺口）。这不是我们工具的偶发 bug，而是**方法本身的已知边界**，必须被显式建模。

### 15.11 本章未取得

- **Guzei 的经验型 SOP**：xray.chem.wisc.edu 的两个页面实为软件安装清单与课程目录，**不含**经验法则型论述；真正对口的是 Guzei 2026 Acta Cryst E 教学论文，但 journals.iucr.org 被 Cloudflare 拦截。
- **Flack & Bernardinelli 原文**（J. Appl. Cryst. 33, 1143; Chirality 20, 681），多路径尝试均被拦截。**目前我们对该文的唯一一手转述来自 Linden 2020**（见 §13.9 的 0.1 / 0.04 两个 s.u. 上限）。需注意搜索引擎返回的若干"Flack 引语"经核查实为 checkCIF PLAT032/033 说明文的二次转述，**已剔除，未采用**。
- **Thompson (2019) *Chemical Crystallography: when are 'bad data' 'good data'?*** Crystallography Reviews 25(1), 3–53 - Taylor & Francis 付费墙，无开放版本。**订正一处署名**：该文为 Amber L. Thompson **独著**，此前我按"Thompson & Watkin"合著记录，属误记。
- **Acta Cryst C best-practice 系列**：未及尝试，且同域名三次均被 Cloudflare 拦截。
- **Beavers 2025 "Don't Panic"**：确认其 PMC 条目**只是一段 ACA 年会会议摘要**，没有可供摘录审稿准则的正文。此前把它当作一篇"审稿经验论文"来期待是错的，特此记录以免后续重复投入。

---

## 第 16 章 病态结构的分类学：孪晶、调制、层错

第一轮把这一块整体标为空白。本章补齐。**总纲**：孪晶、调制、OD/层错这三类不是三个互斥的诊断标签，Fröschl et al. (2025) 明说它们**常常出现在同一颗晶体上且未必可分**，见 §16.6。

### 16.1 孪晶的定义与两大类

Parsons, S. (2003). *Introduction to twinning.* Acta Cryst. D59, 1995–2003.【一手·逐字】：

> "A twinned crystal is an aggregate in which different domains are joined together according to a specific symmetry operation: the twin law. The diffraction patterns derived from different domains are rotated, reflected or inverted with respect to each other... Reflections from different domains may overlap and twinned crystals fall broadly into two categories in which either all reflections or only certain zones of reflections are affected by overlap. The former occurs when a crystal lattice belongs to a higher point group than the crystal structure itself; the latter frequently occurs when the twin law is a symmetry operation belonging to a higher symmetry supercell."

**这两类的操作后果完全不同**：全部反射受影响 ⇒ HKLF 4 + TWIN/BASF 即可；仅特定区带受影响 ⇒ 必须回到帧数据、用多取向矩阵重新积分、走 HKLF 5（呼应 §13.3 Linden 关于 PLATON 捷径的警告）。

### 16.2 赝并孪晶（pseudo-merohedry）

【一手·逐字】：

> "A monoclinic crystal structure which happens to have β ≈ 90° has a lattice with, at least approximately, the mmm symmetry characteristic of the orthorhombic crystal family. If twinning occurs by a twofold axis about a or c, the crystal is not merohedrally twinned, since monoclinic and orthorhombic are two different crystal families. This type of effect is instead referred to as twinning by pseudo-merohedry."

**注意这与 §13.1 Linden 的 β ≈ 90.2° 陷阱是同一个度规巧合的两个不同后果**：Linden 讲的是采集策略被定错，Parsons 讲的是同一个巧合还会让晶体真的孪晶化。**一个 β 接近 90° 的单斜晶体，同时面临这两个风险**：这是通用 harness 应当把"β ≈ 90°"当成一个显式警戒条件的理由。

### 16.3 非贯穿孪晶（non-merohedral）的识别

【一手·逐字】：

> "In merohedral and pseudo-merohedral twinning, the nature of the twin-law matrix means that all integral Miller indices are converted into other integer triples, so that all reciprocal-lattice points overlap... Twins in which only certain zones of reciprocal-lattice points overlap are classified as being non-merohedral. In these cases, only reflections which meet some special conditions on h, k and/or l are affected by twinning."

**衍射图上的直接表现**【一手·逐字】：

> "Diffraction patterns from non-merohedrally twinned crystals contain many more spots than would be observed for an untwinned sample... Zones of unusual systematic absences are frequently a sign that a crystal is non-merohedrally twinned."

**"异常的系统消光"是一条可自动检测的信号**：它与 §16.5 网状孪晶的"非空间群消光"是同一类现象，且都指向：**当消光模式对不上任何空间群时，第一反应应该是孪晶，而不是硬挑一个最接近的空间群。**

### 16.4 |E²−1| 的孪晶诊断值

【一手·逐字】：

> "The values of |E2 − 1| for each figure are (a) and (b) 1.015, (c) 0.674, (d) 0.743. The ideal (untwinned) value of |E2 − 1| for this centric crystal structure is 0.97, meaning that its diffraction pattern characterized by the presence of both strong and weak reflections; intensities are more evenly distributed in acentric distributions, where |E2 − 1| has an ideal value of 0.74."

**读法与陷阱**：孪晶会把中心对称结构的 |E²−1|（理想 0.97）压低到接近非中心对称的理想值（0.74）。所以**一个 |E²−1| ≈ 0.74 的读数有两种截然不同的解释**：真的非中心对称，或者是被孪晶压低了的中心对称结构。**单凭这个数无法区分**：这是 §3 章空间群判定里必须显式建模的歧义。

### 16.5 完整的六分类体系（Friedel / Nespolo–Ferraris）

Grimmer, H. & Nespolo, M. (2006). *Geminography: the crystallography of twins.* Z. Kristallogr. 221, 28–50.

**两个定量参数**【一手·逐字】：

> 孪晶指数 n："We defined the twin index (or multiplicity) n as the volume ratio of primitive cells in the twin lattice and crystal lattice, n = VT/V."

> 孪晶偏角 ω："The obliquity w is thus the angle between the vectors [uvw] and [hkl]*"

**并孪晶的形式定义**【一手·逐字】：

> "A crystal is called merohedral if its point group H has less elements than the holohedry, i.e. the point group of the crystal lattice d."

**按 (n, ω) 划分的完整分类**【一手·逐字，节选】：

> "1 Twinning by merohedry: n = 1, w = 0."
> "1.1 Twinning by syngonic merohedry: H ⊂ d and the twin operation belongs to d..."
> "1.2 Twinning by metric merohedry, or class IIB twins. Here, H ⊂ d ⊂ d(L), but now the twin operation belongs to d(L) and no longer to d. Twinning by metric merohedry cannot occur for crystals belonging to the cubic or hexagonal crystal system and for trigonal crystals with an hP lattice"
> "2 Twinning by pseudo-merohedry: n = 1. ... Twinning by pseudo-merohedry cannot occur for crystals belonging to the cubic or hexagonal lattice systems."
> "3.1 Twinning by reticular merohedry: n > 1, w = 0, d(LT) ≠ d(LI)."
> "3.2 Twinning by reticular polyholohedry: n > 1, w = 0, d(LT) = d(LI)."
> "4.1 Twinning by reticular pseudo-merohedry: n > 1, d(LT) ≠ d(LI)."
> "4.2 Twinning by reticular pseudo-pol yholohedry: n > 1, d(LT) = d(LI)."

**(n, ω) 不是纸上概念，它就是程序输出的量**（Phenix *Xtriage* 文档）【一手·逐字】：

> "Twin laws are found using a modified le-Page algorithm and classified as"

> "The delta le-Page is the familiar obliquity. The delta Lebedev is a twin law quality measure developed by A. Lebedev (Lebedev, Vagin & Murshudov; Acta Cryst. (2006). D62, 83-95.)."

> "The R-metric is equal to : Sum (M_i-N_i)^2 / Sum M_i^2"

> "M_i are elements of the original metric tensor and N_i are elements of the metric tensor after 'idealizing' the unit cell, in compliance with the restrictions the twin law poses on the lattice if it would be a 'true' symmetry operator."

> "Note that for merohedral twin laws, all quality indicators are 0. For non-merohedral twin laws, this value is larger or equal to zero. If a twin law is classified as non-merohedral, but has a delta le-page equal to zero, the twin law is sometimes referred to as a metric merohedral twin law."

**两条可直接用的结论**：
1. **delta le-Page 就是 Grimmer & Nespolo 的偏角 ω**：上面那套六分类里的一个关键参数，我们的工具链**已经能算**，只是没有按分类学去读它。"非贯穿但 delta le-Page = 0"正好对应分类里的 **1.2 度规并孪晶（metric merohedry）**。
2. **一条能力边界**【一手·逐字】：

> "Non-merohedral (reticular) twinning is not considered."

即 Xtriage 的孪晶律搜索**不覆盖网状（reticular）孪晶**：也就是分类里的 3.x 与 4.x 全类。obverse–reverse 这类常见情形不会被它找出来，必须另想办法（§16.5 末尾的"非空间群消光"是其入口）。

**这套分类给了 harness 一个可判定的骨架**：先算 (n, ω)，就能定位到具体类别，而不是笼统地说"可能有孪晶"。注意其中两条**否定性规则**可直接用于排除：立方与六方晶系不可能有 pseudo-merohedry；立方/六方/hP 三方不可能有 metric merohedry。

**网状并孪晶的实例**（Parsons 2003）【一手·逐字】：

> "Instead, it is referred to as obverse–reverse twinning or twinning by reticular merohedry; this is an important distinction because overlap between reflections from different domain variants in obverse–reverse twins only affects a third of the intensity data."

**网状孪晶的衍射信号**（Grimmer & Nespolo）【一手·逐字】：

> "The third set of nodes gives rise to non-space group absences in the diffraction pattern. Such absences are a strong indication for the presence of twinning."

### 16.6 一类根本看不出来的孪晶

【一手·逐字】：

> "the measured intensities in case of class I twins are in principle the same as those resulting from an untwinned individual because the diffraction pattern of each individual becomes centrosymmetric according to Friedel's law. It follows that twinning is not at all evident from the diffraction pattern and it may even pass unnoticed in the structural investigation"

**这是本章最重要的一条警告**：反演孪晶（class I）**在衍射图上原则上不可见**。它只能通过精修（Flack 参数、BASF）发现，这与 §13.9 Linden "Flack 值既不接近 0 也不接近 1 = 反演孪晶，不处理会带偏几何参数"是同一件事的两端。**任何"先从衍射图判断有没有孪晶、没有就往下走"的流程，都会漏掉这一整类。**

### 16.7 自动化的具体翻车方式

Clegg, W. et al. (2019). *Some reflections on symmetry: pitfalls of automation and some illustrative examples.* Acta Cryst. E75.

**这篇的标题就是冲着自动化去的。**【一手·逐字】：

> "The clue to the answer is given by the large mean observed/calculated intensity ratios K in the analysis of variance following refinement. These, together with the metric pseudo-symmetry of a triclinic lattice closely approximating a monoclinic one, are an indication of possible twinning of a type commonly known as pseudo-merohedral (Parsons, 2003) or twinning by pseudomerohedry (Nespolo & Ferraris, 2004). A twin law with matrix (1 0 0, 0 −1 0, 0 0 −1) represents a twofold rotation about the triclinic a axis. Because of the closeness of two unit cell angles to 90°, the two twin components related by this rotation give almost exact overlap, with near-coincidence of their reciprocal lattice points."

**可操作的判据**：精修后方差分析里的 **K = ⟨Fo²⟩/⟨Fc²⟩ 分组均值异常偏大** + **度规赝对称** = 赝并孪晶的联合指征。这两条都是我们**已经能算**的量，问题只在于有没有把它们联起来读。

### 16.8 调制结构与超空间

Pinheiro, C. B. & Abakumov, A. M. (2015). *Superspace crystallography: a key to the chemistry and properties.* IUCrJ 2, 137–154.

**识别信号（在指标化阶段）**【一手·逐字】：

> "exhibits in its diffraction pattern some extra peaks (called satellite reflections) that cannot be indexed using only three integer numbers, indicating the presence of a superstructure"

**核心思想**【一手·逐字】：

> "the wavelength of the distortion and the vectors describing the translations of the network are not commensurate. In this approach, the real crystal is regarded as a three-dimensional section through the (3 +d)-dimensional periodic `supercrystal' and the diffraction pattern of the modulated crystal is regarded as the projection of its (3 + d)-dimensional reciprocal lattice"

> "the concept of periodicity (translational symmetry) can be preserved (de Wolff, 1974)."

**调制函数与 q 矢量**【一手·逐字】：

> "where r0j is the average position of the atom j, uj is the periodic vector such that uj(x) = uj(x + 1), q is the modulation vector and the vector gj defines the phase reference point of the displaced entity."

**工具链**【一手·逐字】：

> "JANA2006 allows (i) data reduction and automatic identification of reflection conditions and superspace groups, (ii) structure solution directly in superspace using SUPERFLIP and (iii) refinement of nonmodulated, modulated and composite structures."

**历史注脚**（说明这不是新问题）【一手·逐字】：

> "As far back as 1902, attempts to index the crystal faces of the naturally occurring crystals of the mineral calaverite (AuTe2), following the law of the simple rational indexes, had failed... Indeed calaverite has incommensurate facets"

**一条对交付极重要的边界**（Spek 2020, checkCIF ALERTS）【一手·逐字】：

> "The current checkCIF tool cannot handle symmetries of non-three-dimensional structures such as those for incommensurate structures."

> "The same applies to incommensurate structures (JANA; Petricek & Dusek, 2000) and structure determinations based on electron diffraction. Those will need the development of specialized validation procedures of the associated experimental, refinement and interpretation of the reported results."

**含义**：对调制结构与电子衍射结构，**我们赖以判定"可发表"的 checkCIF 本身是失效的**。系统必须知道这个边界，否则会在这两类样品上给出虚假的通过信号。

### 16.9 OD 结构、层错与漫散射

Fröschl, D. et al. (2025). *OD (order–disorder) interpretation and diffuse scattering analysis of an organic polytype with allotwin character: a detailed how-to.* Acta Cryst. B81, 550–564.

**OD 理论的定义**【一手·逐字】：

> "The order–disorder (OD) theory (Dornberger-Schiff & Grell-Niemann, 1961) was created in the 1950s and further developed in the second half of the 20th century to explain the common occurrence of polytypism in all known classes of crystalline matter. It is based on the limited range of interatomic interactions. OD polytypes are an often observed class of polytypes, where layers can connect in different ways, nevertheless forming geometrically equivalent layer pairs."

**衍射表现**【一手·逐字】：

> "crystallizes in an order–disorder (OD) structure with a high stacking fault probability. The diffraction pattern features diffuse scattering and broad peaks, which can be attributed to fragments of two polytypes of a maximum degree of order (MDO). Additional weak peaks indicate existence of a non-MDO polytype."

**四条可操作的诊断标准**【一手·逐字】：

> "An OD model should always be based on experimental evidence (for example twinning or diffuse scattering). For 1 there were four characteristic signs of stacking disorder.
> (i) Pronounced one-dimensional diffuse scattering in c* direction.
> (ii) `Phantom molecules' of alternative stacking arrangements.
> (iii) Crystallographically independent molecules (Z0 = 2) with systematic orientation relations.
> (iv) Additional diffraction peaks of alternative polytypes."

**第 (ii) 条对本项目特别值得注意**：所谓"幽灵分子"——差值图上出现另一种堆垛方式的分子轮廓，正是我们内部一直用"幽灵原子"称呼的现象的**成文对应物**。它在这里不是建模错误，而是**层错的诊断证据**。

**三类病态不可分离**【一手·逐字】：

> "Polytypism is a multifarious phenomenon leading to interesting crystallographic challenges such as twinning (Nespolo & Ferraris, 2004), antiphase domains (Wondratschek & Jeitschko, 1976), allotwins (Nespolo et al., 1999) and diffuse scattering (Welberry, 2010). Often, these appear in the same crystal and may not be separable."

> "we observed distinct diffuse scattering and broad peaks at positions that indicated fragments of distinct polytypes, i.e. an intermediate between a disordered structure and an allotwin."

**这条否定了"给样品贴一个病态标签然后走对应分支"的设计**。真实样品可以同时是无序的、孪晶的、有层错的，且**未必可分离**。正确的姿态是记录观察到的证据组合，而不是强行归类。

### 16.10 赝平移对称（tNCS / TPS）的检测

PLATON/checkCIF 验证测试【一手·逐字】：

> "PLAT115 Type_5 Test for non-crystallographic centre of symmetry [0, 100] Tests for missed symmetry are done with ADDSYM, an expanded MISSYM (C) clone. This ALERT reports on local inversion symmetry, not compatible with the reported space-group symmetry."

> "PLAT116 Type_2 Report implemented (pseudo) lattice translation A (Pseudo) Lattice translation was detected and implemented before the current ADDSYM analysis."

（本条来源为代理本机缓存页面，**精确 URL 未复核**，引用前应核实。）

**可操作的 Patterson 判据**（Phenix *Xtriage* 文档，https://phenix-online.org/documentation/reference/xtriage.html）【一手·逐字】：

> "TPS is located by inspecting a low resolution Patterson function. Peaks and their significance levels are reported:"

> "Largest Patterson peak with length larger then 15 Angstrom"

> "The probability that a peak of the specified height or larger is found in a Patterson function of a macro molecule that does not have any translational pseudo symmetry is equal to 9.982e-01"

> "p_values smaller then 0.05 might indicate weak translation pseudo symmetry, or the self vector of a large anomalous scatterer such as Hg, whereas values smaller then 1e-3 are a very strong indication for the presence of translational pseudo symmetry."

**读法**：查**低分辨率 Patterson 图中距原点 > 15 Å 的最大峰**，用 p 值判定；p < 0.05 为弱迹象、p < 10⁻³ 为强迹象。**注意其中写明的混淆源**：一个大反常散射体（如 Hg）的自向量也会产生同样的峰，所以这个信号本身并不唯一指向 tNCS。

**一个重要的连带效应**【一手·逐字】：

> "Outliers are removed from the data set in the further analysis. Note that if pseudo translational symmetry is present, a large number of 'outliers' will be present."

（即：tNCS 存在时会出现大量被判为"离群"的反射。**如果流程会自动剔除离群点，就会在 tNCS 样品上大量误删真实数据**：这是一条自动化的隐蔽陷阱。）

**适用性说明**：Xtriage 面向蛋白晶体学，其中 Matthews 分析等属蛋白专用；但上述 Patterson 峰判据与下节的强度矩统计基于 Wilson 统计，**对小分子同样成立**（阈值中的"15 Å"是针对大分子晶胞设定的经验值，小分子晶胞需相应调整）。

### 16.11 强度统计检验组合：各自测什么、互相怎么区分

**理想值对照表**（Xtriage 文档）【一手·逐字】：

> 非中心（Acentric）：
> "<I^2>/<I>^2 :1.955 (untwinned: 2.000; perfect twin 1.500)"
> "<F>^2/<F^2> :0.796 (untwinned: 0.785; perfect twin 0.885)"
> "<|E^2 - 1|> :0.725 (untwinned: 0.736; perfect twin 0.541)"

> 中心（Centric）：
> "<I^2>/<I>^2 :2.554 (untwinned: 3.000; perfect twin 2.000)"
> "<F>^2/<F^2> :0.700 (untwinned: 0.637; perfect twin 0.785)"
> "<|E^2 - 1|> :0.896 (untwinned: 0.968; perfect twin 0.736)"

**这张表解决了 §16.4 留下的歧义**：因为它给出了**方向相反的两个偏离**【一手·逐字】：

> "Significant departure from the ideal values could indicate the presence of twinning or pseudo translations. For instance, an <I^2>/<I>^2 value significantly lower than 2.0, might point to twinning, whereas a value significantly larger than 2.0, might point towards pseudo translational symmetry."

**这是本章最实用的一条**：孪晶把 ⟨I²⟩/⟨I⟩² **压低**（趋向 1.5），赝平移把它**推高**（超过 2.0）。所以偏离的**符号**本身就携带诊断信息，只报"偏离理想值"而不报方向，等于丢掉一半信息。

**L 检验**（Padilla & Yeates 2003, Acta Cryst. D59, 1124–1130）【一手·逐字】：

> "The L-test is an intensity statistic developed by Padilla and Yeates (Acta Cryst. (2003), D59: 1124-1130) and is reasonably robust in the presence of anisotropy and pseudo centering, especially if the miller indices are partitioned properly. Partitioning is carried out on the basis of a Patterson analysis. A significant deviation of both <|L|> and <L^2> from the expected values indicate twinning or other problems:"

**为什么需要 L 检验**：它对**各向异性与赝心（pseudo centering）稳健**，而 |E²−1| 不是。换句话说，当样品同时有 tNCS 时，|E²−1| 会被污染而 L 检验仍可用，这两个统计量不是冗余的。

**L 检验估计孪晶分数的可靠性有限**【一手·逐字】：

> "The distribution of |L| values indicates a twin fraction of 0.00. Note that this estimate is not as reliable as obtained via a Britton plot or H-test if twin laws are available."

**依赖孪晶律的检验**（需要先有候选孪晶律）【一手·逐字】：

> "Twin law specific tests (Britton, H and RvsR) are performed:"
> "mean |H| : 0.183 (0.50: untwinned; 0.0: 50% twinned)"
> "mean H^2 : 0.055 (0.33: untwinned; 0.0: 50% twinned)"
> "R_abs_twin = <|I1-I2|>/<|I1+I2|>" （Lebedev, Vagin, Murshudov. Acta Cryst. (2006). D62, 83–95）

**综合 Z 分数及其不对称性**【一手·逐字】：

> "The multivariate Z score is a quality measure of the given spread in intensities. Good to reasonable data is expected to have a Z score lower than 3.5. Large values can indicate twinning, but small values do not necessarily exclude it."

**最后一句的逻辑结构与 §15.4 Watkin 的"看起来不对多半就是不对，反之不成立"完全同构**：**这些统计量是单向证据**：异常值指示问题，正常值不构成"无问题"的证明。任何把这类指标写成"通过/不通过"双向判据的实现，都误用了它们。

**两级检验的层次关系**：不依赖孪晶律的统计量（矩、L 检验）用于**发现可疑**；依赖孪晶律的检验（Britton、H、R vs R）用于**确认并定量**。前者可无脑跑，后者需要先从度规对称枚举候选孪晶律，这决定了流程顺序。

### 16.12 本章未取得

- ~~Zwart & Read / Phenix Xtriage 关于 tNCS 的判据~~ —— **已补齐，见 §16.10–16.11**（走 Phenix 官方文档，非期刊原文）。仍未取得的是 Read, Adams & McCoy (2013) Acta Cryst. D69, 176–183 的正文（PMC3565438 可访问，本轮未及提取）与 Caballero et al. (2021) 关于 Patterson 检测 tNCS 的后续论文；以及 Padilla & Yeates (2003) L 检验的原始推导。**这三篇是 F4 的下一步。**
- **International Tables Vol. D Ch. 3.3 "Twinning of crystals"**（Hahn & Klapper），Wiley 站点 403。
- **IUCr Online Dictionary 词条**（Twinning / Twin_index / Twin_obliquity / Modulated_crystal_structure / Superspace_group），dictionary.iucr.org 被 Cloudflare 拦截。

**本章带回的一条关键操作发现（已用于后续调研）**：`journals.iucr.org` 的 **HTML 页**被 Cloudflare 拦截，但**同域名下的 PDF 直链不受限制**，curl 可直接成功。Parsons (2003) 与 Fröschl et al. (2025) 两篇一手原文都是靠这条路取得的。此前多轮把"IUCr 一律打不开"当成结论，是一个代价不小的误判。（**但这条规则不能外推到所有 iucr.org 子域**：`www.iucr.org` 上的 PDF 实测仍返回 403 `Cf-Mitigated: challenge`，见 §17.7。）

---

## 第 17 章 精修的力学、纪律与交付合规

本章补齐缺口清册的 E（精修力学）与 G（交付合规）。**最有价值的一份来源是 IUCr 验证共同编辑（Validation Co-editor）的内部指引**：它不是教科书，而是编辑真正据以处置稿件的规则，里面有具体的拒稿案例。

### 17.1 OMIT 的三种形式与它们的纪律

SHELXL 手册【一手·逐字】：

**形式一：按原子名剔除（做 OMIT 图，不是删数据）**

> "The named atoms are retained in the atom list but ignored in the structure factor calculation and least-squares refinement. This instruction may be used, together with L.S. 0 and FMAP 2, to create an 'OMIT map' to get a clearer picture of disordered regions of the structure; this concept will be familiar to macromolecular crystallographers. In particular, 'OMIT $H' can be used to check the hydrogen atom assignment of -OH groups etc."

（**`OMIT $H` 正是 §13.11 Linden 说的"把 H 从图里扣掉、看那里本来有没有密度"的 SHELXL 实现**。两条独立来源指向同一个操作。）

**形式二：按 σ 阈值标记为"未观测"**

> "If s is positive it is interpretated as a threshold for flagging reflections as 'unobserved'. Unobserved data are not used for least-squares refinement or Fourier calculations, but are retained for the calculation of R-indices based on all data, and may also appear (flagged with an asterisk) in the list of reflections for which Fo2 and Fc2 disagree"

（**关键**：被标为"未观测"的数据**仍计入 all-data R 值**。这就是 R1(all) 与 R1(I>2σ) 的差别所在，想靠提高 σ 门槛来美化 R1(all) 是无效的。）

**形式三：按 h k l 剔除单条反射**

> "The reflection h,k,l (the indices refer to the standard setting after data reduction, and correspond to those in the list of `disagreeable reflections' after refinement) is ignored completely. Since there may be perfectly justified reasons for ignoring individual reflections (e.g. when a reflection is truncated by the beam stop) this form of OMIT is allowed with ACTA; however it should not be used indiscriminately."

**这句 "allowed with ACTA; however it should not be used indiscriminately" 就是纪律本身**：不是禁止，而是"必须有正当理由"。手册举的正当理由是**物理性的**（被光阑挡住），不是统计性的（这条反射不合群）。

### 17.2 IUCr 的成文要求：剔反射必须披露

Acta Cryst C/E 投稿数据要求（`journals.iucr.org/c/services/cif/reqdata.html`）【一手·逐字】：

> "The number of reflections used in the refinement should be as large as possible, and should, if possible, be greater than the number of refined parameters _refine_ls_number_parameters by at least a factor of 10 if the structure is centrosymmetric, or by a factor of 8 if it is not. Omission of outlier reflections should be avoided unless there is good reason and, in such cases, details of the omitted reflections and the reasons for doing so should be included in the _publ_section_exptl_refinement section."

**两条可直接落地的规则**：
1. 观测/参数比目标：**中心对称 ≥ 10，非中心对称 ≥ 8**（注意 §15.3 Watkin 的限定：这是指导原则，不是判定阈值；同一组数字在 §1.1 的 Müller 引文里已出现过，并附有到 0.84 Å / 2θmax 50°(Mo) / 134°(Cu) 的换算）。
2. **剔除离群反射默认应避免；若剔除，必须在 `_publ_section_exptl_refinement` 中写明剔了哪些、为什么。**

### 17.3 编辑实务：真实的拒稿案例

IUCr Validation Co-editor 指引（`journals.iucr.org/services/coeditors/cifs/Valid.html`）【一手·逐字】：

> DC3："PROBLEM: Dataset is only 0.69 complete to 2theta 50 degrees on Mo radiation ACTION: Author contacted immediately and replied that a filter was applied in SAINT; author was immediately asked to reprocess data without this filter, re-refine the structure and resubmit the paper."

> DC4："PROBLEM: Synchrotron dataset with high redundancy but only 0.72 complete (after beam dump). ACTION: Completeness is not satisfactory: rejected."

> DC5："PROBLEM: About half the data were skipped or suppressed. ACTION: Author could not provide a valid explanation: paper rejected."

**这三条是本知识库里"删数据降 R 是学术不端"最硬的成文依据**，且给出了处置的层次：
- **主动过滤数据**（即便作者给了解释）⇒ 要求**去掉过滤重做**，不接受解释本身；
- **完整度不足**（哪怕是设备原因如 beam dump 造成的）⇒ 直接拒；
- **约一半数据被跳过且无正当理由** ⇒ 直接拒。

**注意 DC4 的含义**：完整度不达标**不因"不是作者的错"而豁免**。这否定了"客观原因造成的数据缺陷可以在评审中被谅解"这一假设，对我们的评分体系是一条重要校准。

### 17.4 权重方案

**WGHT 完整定义**（SHELXL 手册）【一手·逐字，但见下方注意事项】：

> "WGHT a[0.1] b[0] c[0] d[0] e[0] f[.33333]
> The weighting scheme is defined as follows:
> w = q / [ σ2(Fo2) + (a*P)2 + b*P + d + e*sin(θ)/λ ]
> where P = [ f * Maximum of (0 or Fo2) + (1-f) * Fc2 ]. It is possible for the experimental Fo2 value to be negative because the background is higher than the peak; such negative values are replaced by 0 to avoid possibly dividing by a very small or even negative number in the expression for w. For twinned and powder data, the Fc2 value used in the expression for P is the total calculated intensity obtained as a sum over all components. q is 1 when c is zero, exp[c*(sinθ/λ)2] when c is positive, and 1 - exp[c*(sinθ/λ)2] when c is negative."

> **证据强度注意**：该 PDF 经 `pdftotext` 提取时丢失了希腊字母与上下标，代理按 SHELXL 公认公式补回了 σ/θ/λ。**这一条不是逐字节意义上的原文**，公式结构可信但字符层面需对照原 PDF 图像核对。已如实标注，不按【一手·逐字】对待。

**P 的默认 f = 1/3 的含义**：P 是 Fo² 与 Fc² 的加权组合（默认 1/3 : 2/3），而不是单用其中之一，这是 F² 精修权重设计的核心，也是为什么把 F 精修的直觉搬过来会出错。

**何时优化权重**【一手·逐字】：

> "The parameters should be set by trial and error so that the variance shows no marked systematic trends with the magnitude of Fc2 or of resolution; the program suggests a suitable WGHT instruction after the analysis of variance... It is usually advisable to retain default weights (WGHT 0.1) until all atoms have been found and the refinement is essentially complete, when the scheme suggested by the program can be used for the next refinement job by replacing the existing WGHT instruction by the one output by the program towards the end of the .res file. This procedure is adequate for most routine refinements."

**两条可落地的规则**：
1. **权重的验收判据不是 GooF 接近 1，而是"方差对 Fc² 大小和分辨率都没有明显系统趋势"**：这与 §1 章 SADABS 误差模型 g 的验收方式（χ² vs 强度、vs 分辨率两张图都平于 1）是同构的。
2. **建完所有原子、精修基本完成之前，保持默认 WGHT 0.1**。中途反复更新权重是常见的坏习惯。

**等权重的禁令**【一手·逐字】：

> "Refinement against F2 requires different weights to refinement against F; in particular, making all the weights equal ('unit weights'), although useful in the initial stages of refinement against F, is never a sensible option for F2. If the program suspects that an unsuitable WGHT instruction has been used it will output a warning message."

**SQUEEZE 后必须申报额外参数**【一手·逐字】：

> "nextra is the number of additional parameters that were derived from the data when 'squeezing' the structure etc. It ensures that the standard deviations and GooF are estimated correctly; they would be underestimated if the number of extra parameters is not specified. nextra should be left at the default of zero except when 'squeeze' has been used."

**这条很容易被漏**：用了 SQUEEZE 却不申报 nextra，会让 **s.u. 与 GooF 被低估**：叠加 §13.7 "s.u. 本身已被低估 1.5–2 倍"，误差会被系统性地报小两次。

### 17.5 收敛与停止

**SHELXL 的位移限幅机制**【一手·逐字】：

> "If the maximum shift/esd for a L.S. refinement (excluding the overall scale factor) is greater than limse, all the shifts are scaled down by the same numerical factor so that the maximum is equal to limse. If the maximum shift/esd is smaller than limse no action is taken. This helps to prevent excessive shifts in the early stages of refinement. limse is ignored in CGLS refinements."

**IUCr 编辑的具体判据**【一手·逐字】：

> "PROBLEM: Poor convergence - maximum shift/s.u. > 1.5. ACTION: Author immediately asked to identify the problem (Flack parameter? extinction parameter? H atoms? disorder?), re-refine and resubmit."

**这是我们拿到的唯一一条 shift/s.u. 的成文数值判据**：**max shift/s.u. > 1.5 = 收敛不良**。注意编辑同时给出了**四个排查方向**: Flack 参数、消光参数、H 原子、无序，这本身就是一份诊断清单。

（**仍未取得**："shift/esd < 0.1 表示收敛完成"这类**完成侧**的成文出处，见 §17.7。）

**分块最小二乘（BLOC）**【一手·逐字】：

> "BLOC n1 n2 atomnames
> If n1 or n2 are positive, the x, y and z parameters of the named atoms are refined in cycle |n1| or |n2| respectively. If n1 or n2 are negative, the occupation and displacement parameters are refined in the cycle... If a cycle number less than the maximum |n1| or |n2| is not mentioned in any BLOC instruction, it is treated as full-matrix."

> "It is important that there is sufficient overlap between the blocks to enable every esd to be estimated with all contributing atoms refining in at least one of the refinement cycles."

**含义**：分块可以省内存，但**块之间必须有足够重叠，否则某些 esd 无法被正确估计**。这条与 §15.3 "elephant parameter" 一起说明：报出来的 s.u. 是否可信，取决于精修是怎么组织的，而不只是取决于数据。

### 17.6 交付：CIF 字段、checkCIF 警报体系与 VRF

**CIF 核心字典的官方定义**（COMCIFS `cif_core.dic`）【一手·逐字】：

> `_refine_special_details`："Details of the refinement not specified by other data items."

> `_exptl_special_details`："Details of the experiment prior to intensity measurement. See also _exptl_crystal.preparation"

（**分工很清楚**：测强度**之前**的实验细节进 `_exptl_special_details`，精修细节进 `_refine_special_details`。§13.7 Linden 说"必须完整披露所有非常规操作"，落地就是这两个字段。）

**checkCIF/PLATON 的警报类型（1–5 型）**（Spek, CIF-VALIDATION.pdf）【一手·逐字】：

> "ALERT_1_ = CIF Construction/Syntax Error, Inconsistent or Missing Data.
> ALERT_2_ = Indicator that the Structure Model may be Wrong or Deficient.
> ALERT_3_ = Indicator that the Structure Quality may be Low.
> ALERT_4_ = Cosmetic improvement, Methodology, Query or Suggestion.
> ALERT_5_ = Informative Message, Check."

**这套分型比 A/B/C 分级更有用**：**2 型说的是"模型可能错"，3 型说的是"结构质量可能低"——这正是 §15.6 Watkin 所说"好晶体上的烂工作 vs 烂晶体上的好工作"的区分维度。** 一个只按 A/B/C 数量打分的实现，会把这两类完全不同的问题混为一谈。

**警报级别**【一手·逐字】：

> "ALERT_Level_A = In General: Serious Problem.
> ALERT_Level_C = Check & Explain.
> ALERT_Level_G = General Issues to Check, Not Necessarily Errors."

（**B 级的官方定义未取得**：该文档的示例报告里恰好没有 B 级警报，故没有印出那一行。见 §17.7。）

**警报类别编号**【一手·逐字】：

> "ALERT CATEGORIES
> n_0xx - general
> n_1xx - cell/symmetry
> n_2xx - adp-related
> n_3xx - intra geometry
> n_4xx - inter geometry
> n_5xx - coordination geometry
> n_6xx - void tests
> n_7xx - varia
> n_8xx - (Fatal) Software Errors/Problems
> n_9xx - Reflection data issues"

**反射计数异常的正当解释**（同文档，片段）【一手·逐字片段】：

> "Reasons to exceed those numbers can be: •Systematic extinctions were not omitted from the reported _reflns_number_total data count •The refinement is deliberately done with a redundant/not merged data set. This might be the case with HKLF 5 data."

（即：观测/参数比异常**并不总是**问题，HKLF 5 孪晶数据天然是未合并的冗余数据集。这是一个必须与 §17.2 的 10:1 / 8:1 一起读的例外。）

### 17.7 什么样的 VRF 才算合格

IUCr Validation Co-editor 指引【一手·逐字】：

> "In general, author responses in the VRF should be reasonable scientific justifications, and not emotional, illogi cal or pleading-for-forgiveness type responses. If the argument is irrational, ask for a better one. A common argument is that the parameter is "near the acceptable limit", but they forget this is the limit for achieving only a B alert, not the limit for a completely acceptable value. If they are already in the A alert region, then things are far from normally acceptable values, never simply borderline."

（`illogi cal` 中间的空格是代理经 reader 代理转换后的原样输出，为转写瑕疵，如实保留未擅自"修正"。）

**"接近可接受限值"是一个被点名的谬误**：那个限值只是 B 级的边界，不是"完全可接受"的边界；已经落在 A 级区就说明离正常值很远，**根本谈不上"只是擦边"**。

**"数据old、当年达标"也是被点名的谬误**【一手·逐字】：

> "Arguments that the data are old and met the acceptable standards at the time of collection are also poor ones. This argument usually appears when a theta(max) of 23 degrees or lower was used. The data would have to be at least prior to 1996 to be in this class, but even back then it was an undesirable trend. Old data may actually become less publishable with time as modern expectations move ahead, so the argument that publishing old data is OK is not really acceptable - otherwise it allows the scenario that one could publish any mediocre result if one waited long enough."

**经验法则**【一手·逐字】：

> "A good rule of thumb: if it does not feel adequate, then it isn't."

**这一节对本项目的直接含义**：我们的系统在遇到无法消除的警报时会生成解释性文字。上面这段给出了**判断这类解释是否合格的成文标准**：必须是**理性的科学论证**，而"接近限值""数据较老""不是我们的错"这三类都被明确列为不合格。这可以直接作为自检规则。

### 17.8 本章未取得

- **GooF 应接近 1 的核心论证原文**: SHELXL 手册只有 SQUEEZE/nextra 的旁证段落；未找到可核验的一手论证。
- **相关系数矩阵 > 0.8 的处置指引**：最可能的出处是 Watkin, D. J. (1994) *The control of difficult refinements*, Acta Cryst. A50, 411–437，付费且未找到开放副本。**这是 E2 的核心缺口。**
- **"只有全矩阵才给出正确 s.u."的完整单句**：只拿到句首被截断的片段，未采用。
- **checkCIF ALERT Level_B 的官方一句话定义**：示例报告里恰好没有 B 级警报。
- **VRF 的官方 CIF 标签模板语法**（`_vrf_PLATxxx_datablock` 的官方示范）。
- **"shift/esd < 0.1 表示收敛完成"的一手出处**：只拿到编辑侧的"> 1.5 为收敛不良"。

**两条操作性发现（补充 §16.12）**：
1. **`www.iucr.org` 上的 PDF 仍被拦截**（403，`Cf-Mitigated: challenge`）。"IUCr 的 PDF 直链不受限"这条**只对 `journals.iucr.org` 成立，不能外推到其他子域**。
2. **reader 代理（`r.jina.ai`）可以穿透 Cloudflare 拿到 IUCr 的 HTML 页**：本章两份 IUCr 编辑文档都是这样取得的。这是继"PDF 直链"之后的第二条通路。

**一条方法学教训**：本轮代理抓取 University of Oregon 的 SHELX-97 页面时，WebSearch 的摘要声称该页讨论了 OMIT/SHEL 指令的行为变更，但代理实际抓下页面（HTTP 200, 57 KB）后 grep **完全找不到 "OMIT" 或 "SHEL" 字样**，遂判定该摘要不可靠并弃用。**这是本轮唯一一次明确捕获到检索层转述与页面实际内容不符的案例，值得记入：搜索摘要不能替代抓取核实。**

---

## 第 18 章 采集侧决策、温度与旁证表征

本章补齐缺口清册的 A（实验与采集侧）与 I4（旁证手段）。

**一条适用性说明**：本章大量引用 Garman (1999) *Cool data: quantity AND quality*（Acta Cryst. D55, 1641–1653）。这是**大分子晶体学**文献，但其关于完整度/冗余度数学关系、低温分辨率增益机制的论述属通用衍射物理，对小分子同样成立；文中蛋白专属操作（冷冻保护剂浸泡、PDB 存档等）已剔除未收录。

### 18.1 完整度与冗余度：两个不可互相替代的量

**完整度的定义与目标**【一手·逐字】：

> "Whatever the purpose of the data collection, the data are likely to be much more useful if they are complete; i.e. the number of unique reflections collected in each resolution shell is at least 95% of the theoretical maximum number."

（注意是**按分辨率壳层**统计，不是总体一个数，这与 §1 章"不要在还原阶段激进截断"和 §8.3 checkCIF 的完整度警报是同一件事。）

**两者是反相关的**【一手·逐字】：

> "It can be seen that the overall completeness is in anti-phase with the redundancy (number of times the intensity of each unique reflection is measured)."

**冗余度解决的是另一个问题**【一手·逐字】：

> "A higher redundancy or `multiplicity', where each unique reflection is measured multiple times, will result in more accurate data even though R(I)sym might become larger"

**本章最重要的一句**【一手·逐字】：

> "In the extreme case, where most unique reflections are measured only once, R(I)sym for the data set will be lower than if each were measured four or five times, but the latter data would be more accurate and thus more reliable."

**这句话直接否证了"Rint 越低数据越好"**：只测一次的数据集 Rint 反而更低，但重复测四五次的数据**更准确、更可靠**。Rint 是**一致性**的度量，不是**准确度**的度量，把它当质量分来优化，会奖励恰恰错误的行为。（这与 §1 章 SADABS "剔离群点的目的不是降 Rint"、以及 §17.1 "提高 σ 门槛不能美化 R1(all)"构成同一族纪律。）

**分辨率与帧宽的连带关系**【一手·逐字】：

> "if the higher resolution data are collected, a smaller oscillation angle per image will be required to avoid overlapping reflections at higher resolutions. This implies more images and thus more time will be needed for the data collection."

**尽量收到最高分辨率**（Sanjuan-Szklarz et al. 2016）【一手·逐字】：

> "Single-crystal X-ray diffraction data should be collected to the highest resolution as this allows for refinement of more reliable structural, thermal and dependent parameters."

**反射/参数比与 2θmax 的定量关系**【一手·逐字】：

> "In general, the reflection-to-parameters ratio increases as the 2θmax angle increases and, for data with 100% completeness, it is ca 10 reflections per parameter for 2θmax equal to ca 50° for small organic molecules with no heavy atoms."

（**这条与 §17.2 IUCr 的 10:1 / 8:1 要求、以及 §1.1 Müller 的说法三方吻合**：Müller 早已写明该比值 "corresponds to a resolution of about 0.84 Å or a 2θmax of 50° for Mo-Kα radiation and 134° for Cu-Kα"。**读法**：对无重原子的有机小分子，"达到 IUCr 的观测/参数比"与"收到 2θmax ≈ 50°（Mo）且完整"在实践中大致同义。但**不是严格等价**：比值还取决于参数数目，即分子大小、是否各向异性、H 是否自由精修、有无无序，所以重原子体系或参数很多的模型不能照搬这个换算。）

### 18.2 探测器距离：一个会污染下游一切的决策

Ramadhar et al. (2015), *Practical guidelines for the crystalline sponge method*, Acta Cryst. A71【一手·逐字】：

> "Long unit-cell axes correlate to small reflection distances in reciprocal space. If the detector distance is small (e.g., the typical 5 cm distance used on in-house diffractometers), then the reflections will overlap. These overlapped reflections could cause indexing programs to select the incorrect Bravais lattice and unit-cell dimensions or fail, and space-group determination can be hampered through incorrect presence/lack of systematically absent reflections. Even if the data are solved in the correct space group and unit cell, the data quality will be poor."

**这条把因果链完整写了出来**：长晶胞轴 → 倒易空间反射间距小 → 探测器太近导致峰重叠 → **指标化选错 Bravais 晶格**或失败 → **系统消光的有无被误判** → 空间群定错。**对大晶胞体系（MOF、COF 正是如此），探测器距离是一个会污染下游全部判断的上游决策。**

**但拉远探测器不是免费的**【一手·逐字】：

> "While the typical solution to this problem is to increase the detector distance from the crystal, this is not suitable for analysis of crystal sponge systems on in-house diffractometers with a sealed-tube anode Mo Kα source, since the reflection intensities would be extremely weak or absent, especially in the mid- to high-resolution shells. Measuring reflections in-house using 2 min per frame exposures with a 5 cm detector distance is at the limit of what can be done on these diffractometers; increasing the detector distance will not provide usable results."

**实操下限**（Northwestern IMSERC, Kappa APEX3 手册）【一手·逐字】：

> "Change the distance to "40". Never put the distance closer than 40 due to collisions and overlap of spots, no matter what the default value is!"

> "Try to get a complete data set with plenty of redundant data."

### 18.3 什么时候该中止并换一颗晶体

Ramadhar et al. (2015)【一手·逐字】：

> "Data collection should be aborted if the crystal exhibits significant cracking, non-merohedral twinning, or is suspected of pseudo-merohedral twinning."

**判断质量的正确手段**【一手·逐字】：

> "The use of a polarizing light filter can aid in visualizing cracking; however, the best gauge for quality is performing initial diffraction studies."

（**与 §13.2 Linden 的"看 hk0/h0l/0kl 三层倒易图"一致**：判断晶体好坏的最终依据是衍射本身，不是显微镜下的外观。）

**装样的一条具体警告**【一手·逐字】：

> "It is important to note that the crystals should not be shipped to synchrotron sources in the immersion oil. We have observed problems with performing diffraction studies on these crystals, which may possibly arise from diffusion of the guest within the sponge into the immersion oil."

**波长与吸收的权衡（实例）**【一手·逐字】：

> "Data were collected using a wavelength of ~0.41 Å on account of much lower absorption by the heavy atoms in the host. This wavelength allows for better absorption correction and mitigates the use of extinction or diffuse solvent corrections."

（与 §14.4 的波长决策骨架互为补充：短波长的好处是**降低吸收**，代价见 §14.4。）

### 18.4 低温：好处与代价

**为什么低温衍射更好**（Garman 1999）【一手·逐字】：

> "Cryo-cooled crystals in general diffract to higher resolution than the same crystals at room temperature for two main reasons. Radiation damage tends first to be evident in the higher range order (which gives the higher resolution diffraction) and thermal vibrations are in general lower for structures determined at 100 K, giving enhanced diffraction intensity at higher resolution"

**代价（一句很到位的"paradoxically"）**【一手·逐字】：

> "Cryo-cooling also provides the opportunity to optimize the quality of the data which are collected, since the prolonged crystal lifetime allows more time for the experiment. Paradoxically, the flash-cooling technique can also introduce features which compromise the data quality, such as increased mosaicity and ice diffraction."

**信噪比**（Nichol & Clegg 2005）【一手·逐字】：

> "It is true that the lower the crystal temperature, the higher the diffracted X-ray intensities are, and so the more distinguishable from the background are the reflections."

### 18.5 "低温测到的不是室温相"——一个具体案例

Nichol, G. S. & Clegg, W. (2005). Acta Cryst. B61（巴比妥酸二水合物）。

**同一化合物在两个温度下是两个不同的相**【一手·逐字】：

> "It was found that, at 150 K, the crystal system was not orthorhombic but non-merohedrally twinned monoclinic and the space group was P21/n."

即：**室温为正交 Pnma，150 K 变成非贯穿孪晶的单斜 P2₁/n**。

**重测的动机**【一手·逐字】：

> "Curious to know whether this result pointed to inaccuracies in the literature reports (which were at least 27 years old), we re-collected data, from the same crystal, at room temperature."

**这个案例同时说明三件事**：
1. 低温下出现的孪晶**可能是降温诱发的**，不是晶体本身的性质；
2. **"文献值不一致"未必是文献错**，可能是两者测的温度不同；
3. §16.2 说的"β ≈ 90° 的度规巧合"在这里以**相变**的形式出现，正交与单斜之间只差一点点。

**变温策略的成文理由**【一手·逐字】：

> "The reasons for selecting two extreme temperatures to finish the strategy were to check that the crystal did not undergo a second phase transition at even lower temperatures; so we could verify that the phase transition is reversible; so that we could see that the crystal did not suffer physical stress at extreme cold; and so we could collect data as close to room temperature as possible without the crystal decomposing."

**降温本身有风险**【一手·逐字】：

> "As reported by Jeffrey et al. (1961), the crystal decomposed on the diffractometer during data collection from a transparent colourless crystal to a white opaque solid, which did not diffract at all."

**但也不必然有害（反例）**【一手·逐字】：

> "the crystal was not removed from the goniometer head between data collections, and a visual examination of the crystal at the end of the experiments showed that it suffered no physical effects (e.g. cracking) as a result of the cooling and heating. Ultimately the same crystal stayed attached to the goniometer head for over 2 weeks."

（**两条并列收录是有意的**：降温既可能毁掉晶体，也可能反复循环两周毫发无损。**这正是"不能用一条规则代替判断"的教科书式例子。**）

### 18.6 SQUEEZE 与 MOF：一条被明确写下的"不推荐"

Spek, A. L. (2015). *PLATON SQUEEZE: a tool for the calculation of the disordered solvent contribution to the calculated structure factors.* Acta Cryst. C71, 9–18.

**MOF 被点名为典型难题**【一手·逐字】：

> "Sometimes the nature of the solvent mixture present in the voids of the structure is unclear. The structures of metal–organic frameworks (MOFs) are notorious examples."

**SQUEEZE 的动机**【一手·逐字】：

> "The time invested in devising an unsatisfactorily parametrized disordered solvent model is not always considered to be worth the effort. This applies in particular in the context of a routine (service) structure determination"

**明确的不推荐**【一手·逐字】：

> "Using SQUEEZE as part of the MOF soaking method (Inokuma et al., 2013), where the interest lies in the guest region as opposed to the host region, can be very challenging, is not recommended and should be done with extreme care when attempted."

**读法**：当**客体本身就是研究对象**时（晶体海绵法、MOF 浸泡法），SQUEEZE 把客体电子密度抹掉恰恰抹掉了要看的东西。**这是一条按目的而非按数值来决定的纪律**：同样的空腔、同样的残余密度，在"客体是杂质"和"客体是目标"两种情形下应当有相反的处理。

**为什么 SQUEEZE 之后化学式需要独立证据**【一手·逐字】：

> "checkCIF will suppress certain validation messages when it detects details about the use of SQUEEZE in the CIF. Unfortunately, the current CIF data definitions for _chemical_formula_sum and _chemical_formula_moiety, and related quantities such as the linear absorption coefficient (µ value) and the molecular weight, are not fully adequate when reporting details of SQUEEZEd solvents."

**这条极其重要**：SQUEEZE 之后，**checkCIF 会主动抑制一部分校验消息**，而 CIF 的化学式相关定义本身又"不完全适用"。也就是说，**用了 SQUEEZE 的结构，其化学式、μ 值、分子量都处在验证盲区**。这正是需要 TGA / 元素分析等独立证据的技术根源。

**SQUEEZE 的前提条件**（Ramadhar et al. 2015）【一手·逐字】：

> "The general conditions needed for the use of PLATON/SQUEEZE are (i) acceptable data resolution (0.84 Å), (ii) the remainder of the structure is completed with H atoms in order to generate the vdW surface"

**未知结构应有独立的分子式依据**【一手·逐字】：

> "it is strongly recommended that a molecular formula obtained from elemental analysis (EA) or high-resolution mass spectrometry (HRMS) be used as guidance for an unknown structure."

**这是本知识库里第一条明确的"旁证表征"要求**：当无序或数据质量使元素指认困难时，**应当用 EA 或 HRMS 得到的分子式作为指引**：而不是仅靠电子密度硬猜。（呼应 §13.10 氯离子/水的实例与 §6 章的元素指认问题。）

### 18.7 本章未取得

- **ω 扫描 vs φ 扫描的适用场景差异**: CrysAlisPro 页面只返回导航菜单；Bruker APEX3/SAINT 手册无可抓取的公开版本（与 §11.8 的结论一致）。**这仍是采集策略里的一个真空白。**
- **晶体尺寸与束斑匹配的成文要求**：只找到波长/吸收的旁证。
- **粉末 XRD 验证体相纯度（phase purity）的成文要求**：最对口的 RSC *CrystEngComm* "Useful practices in single crystal diffraction analysis of reticular structures" 返回 **403（RSC 自身反爬，非 Cloudflare，无法用 Referer 绕过）**。已定位但未抓取的候选：PMC4224474、PMC11957409、PMC7492392。**这是 I4 剩下的核心缺口。**
- **TGA / 元素分析与 SQUEEZE 结果冲突时如何处置**：已有 Spek 与 Ramadhar 的强相关引文（§18.6），但没有专门论述"单晶结构与体相不一致时怎么办"的段落。
- **降温速率 / 退火的数值化协议**: Cryostream 手册已定位 URL 未抓取；检索摘要提到 annealing 功能但无数值。
- **checkCIF 具体判据页**（PLAT029、THETM_01、REFLT_03），这些在 `journals.iucr.org/services/cif/checking/` 下，是 **HTML 业务页而非 issues 目录下的 PDF**，curl + Referer 仍返回 403。**再次确认"PDF 直链不受限"只对 `/x/issues/.../xxx.pdf` 形式成立。**

---
---

## 附录 A 数值锚点速查表

**使用须知：这张表只是索引，每个数字都必须回到正文读它的限定条件。** 单看这张表就是本知识库最反对的用法。

### A.1 第一轮（第 0–10 章）锚点

| 数值 | 出处 | 用途 | 关键限定条件 |
|---|---|---|---|
| \|E²−1\| 0.968 / 0.736 | XPREP、SADABS | 心 / 非心 | 重原子（尤其特殊位置）、投影反射太少、孪晶时不可靠；金属配合物常落两者之间 |
| \|E²−1\| ≪ 0.736 | Herbst-Irmer | 孪晶警示 | 需与其他警示征同向 |
| Rint < 0.1 | XPREP | 劳厄群指认 | 诊断价值取决于合并的等效反射数 |
| Rsigma > 0.1 | XPREP | 数据极弱或处理错 | — |
| 消光集 ⟨I/σ⟩ ≈ 1 或更小 | XPREP | 系统消光判定 | 反射数少时"relatively unreliable" |
| CFOM < 1 / > 10 | XPREP | 空间群正确 / 很可能错 | 手册自称"not infallible"，不清晰时应逐群求解再选 |
| ⟨I/σ⟩ < 10 | Palatinus & van der Lee | 消光法开始失灵 | 经验起点 |
| α0 < 0.3 | SHELXT | 可能中心对称 | 同时是剔除不可能群的默认门 |
| δsym < 0.1 / < 0.2 / > 0.5 | SUPERFLIP | 正确 / 几乎总正确 / 错误算符 | 默认接受门 0.25；噪声大（粉末、孪晶）时会失效；0.10–0.25 为赝对称警戒带 |
| R(m) > 0.98 | SUPERFLIP | 接受心化矢量 | 故意从严以防超结构误判 |
| ADDSYM 1.0° / 0.25 Å / 0.45 Å / 20% misfit | PLATON | 漏对称搜索容差 | 纯几何、必须回衍射数据核实；需原子分辨率数据；命中约 1/3 为真 |
| CC1/2 0.2、⟨I/σ⟩ 1.0、info 0.1 | AIMLESS | 分辨率截断默认 | 应考虑各向异性；不要在还原阶段激进截断 |
| CC1/2 0.3 | xia2.multiplex | 截断默认 | DIALS 论文实例中因壳层完整度不足而**未被采纳** |
| 合并/未合并 I/σ 2 和 1 | xia2 | 截断默认 | 用户可完全覆盖 |
| rms 比 < 1.5 | xia2 | Bravais 晶格约束是否合适 | 全部已知案例均低于此值 |
| μ·t_mid > 3.0 | checkCIF ABSTM_02 | 要求面指标数值校正 | 油封/不规则晶体可豁免，但 Tmin/Tmax 须相符 |
| RR > 2.00 / 1.50 / 1.10 | ABSTM_02 | 非数值校正的 A/B/C | 数值/解析校正同样数值只给 G 级 |
| RT(exp) > 1.30 / 1.20 / 1.10 | ABSTM_02 | 声明"未校正"的 A/B/C | — |
| 球谐阶数 4/1、6/3、8/5 | SADABS | 弱/中/强吸收 | 中心对称晶形可降低奇次阶 |
| 4.0σ | SADABS | 离群剔除默认 | 必须在吸收模型精修**之后**；目的不是降 Rint |
| g（误差模型） | SADABS | 逐数据集精修 | 验收标准是 χ² vs 强度、vs 分辨率两张图都平于 1 |
| a≈1、b≈0.02–0.04 | DIALS | 误差模型健康值 | — |
| 完整度 99–100%、0.84 Å、多重度 >5–7、I/σ ≥8–10、Rint <10% | Müller 2009 | 好数据 | 作者明说"没有任何一项有公认硬界限" |
| 壳层 ⟨I/σ⟩ ≤ 2.0 且/或 Rint ≥ 0.45 | Müller 2009 | 视为噪音 | 需整个壳层都如此 |
| 数据/参数 ≥ 8（非心）/ 10（中心） | Müller、checkCIF | 参数比 | checkCIF 另有 >7（非心 Zmax<19）分档 |
| sin θ/λ 0.6 Å⁻¹ | checkCIF PLAT027/029 | Acta 发表完整度要求 | — |
| R1 > 0.20 / 0.15 / 0.10；<0.07 expected | checkCIF RFACG01 | A/B/C | 须先排除吸收、晶体质量、未处理孪晶、错劳厄群、模型不完整 |
| Rint > 0.20 / 0.15 / 0.10 | RINTA01 | A/B/C | PLAT020 文本用 0.12 |
| GooF 0.40–6.00 / 0.60–4.00 / 0.80–2.00 | GOODF01 | A/B/C 区间外 | — |
| 差图 ±0.5 e/Å³ | Spek 2020 | 收敛小分子的期望 | 重原子附近 ~1 Å 内常是吸收伪影 |
| 空腔 7.2 Å³ | SQUEEZE | 最小相关空腔 | = 半径 1.2 Å 探针球体积 |
| 空腔 ~40 Å³ / 100–200 Å³ | checkCIF PLAT601/605 | 一个水 / THF 级分子 | 【转述级证据】 |
| Flack su < 0.1 | Parsons 2013 | 可下结论的前提 | 即使已知对映体纯 |
| Flack \|x\| < 2 s.u.、s.u. < 0.04（对映体纯 < 0.1） | checkCIF | 有效绝对构型指认 | — |
| Friedif ≳ 80 / 低至 12 | Parsons 2013 | 基本无问题 / 后精修法仍可用 | 常规精修在 9–36 时 s.u. 约 0.8–0.2 |
| 常规 Flack s.u. 高估 ×5.5 | Parsons 2013 | 轻原子 Cu Kα 23 例 | reduced χ² 0.031 |
| BASF 0.05–0.45 / ≈0.5 | XPREP [M] | 部分 / 完全并孪晶 | 后者需配合低 \|E²−1\| |
| wR2(int) ≈ 0.08，>0.2 绝不接受 | TWINABS | 孪晶缩放验收 | — |
| hkl 拟合率 < 90% | Purdue SOP | 非贯穿孪晶警示 | 限"衍射良好且无其他明显问题"的晶体 |
| Full Overlap Threshold 0.8 | CrysAlisPro | 孪晶部分重叠拆分 | 可设 0–1 |
| 自由变量 s.u. ≪ 其值；0.95(10) 即撤销 | Müller 无序教程 | 无序模型验收 | — |
| 无序起始占有率 0.6 | Müller 无序教程 | 比例未知时 | — |
| DFIX/SADI 0.02、DANG 0.04、FLAT 0.1 | Müller / SHELXL | 几何限制默认 s.u. | — |
| RIGU/DELU 0.004 / 0.01；SIMU 0.04（端基 0.08）；ISOR 0.1（端基 0.2） | SHELXL / Müller | ADP 限制默认 s.u. | RIGU/DELU 是"硬"限制；SIMU/ISOR 只是粗近似，SIMU 不推荐小分子与自由旋转离子 |
| 无序原子 > 20% 独立原子 | Müller 2009 | 分批精修 | — |
| U(H) = 1.2 × Ueq（甲基/羟基 1.5） | SHELXL | 骑乘 H 的 U | — |
| AFIX 5/6 默认 d = 1.42 / 1.39 Å | SHELXL | 五/六元环刚体 | — |
| IAM 低估 X–H 0.12 Å；HAR 0.014 Å | IUCr 量子晶体学 | 为什么 X–H 用目标值 | — |
| 原子序数差 < ~10% | Raymond & Girolami | X 射线难以区分 | N/O 差 15% 可分；W/Au 差 7% 不可分 |
| 25 帧 | CrysAlisPro | 自动还原批大小 | 首批 25 帧用于估背景 |
| 98.5% 覆盖度、目标 I/σ 15、Cu 高角 1:4 | CrysAlisPro | 采集策略默认 | 均可被用户覆盖 |

### A.2 第二轮（第 11–16 章）新增锚点

| 数值 | 出处 | 用途 | 关键限定条件 |
|---|---|---|---|
| 限制残差 > 3 × 所设 s.u. | Watkin 2008 §15.2 | **限制不合理，必须调查** | 比"看 R 有没有变好"敏感得多；与"加限制后原位置冒差值峰"（§13.4）互为独立信号 |
| 限制起始 s.u. 0.005–0.01 | Linden 2020 §13.4 | 比 SHELXL 默认更紧的起点 | 解对之后应放松 |
| 受限参数 s.u. ≈ 同类未受限参数 s.u. | Linden 2020 §13.4 | **限制的验收判据** | — |
| s.u. 被低估约 1.5–2 倍 | Linden 2020 §13.7 | 所有以 s.u. 为分母的判据都要留余量 | — |
| 天平动引起的键长偏差 ≈ 10 × s.u. | Watkin 2008 §15.8 | "3σ 内即正常"在强天平动基团上失效 | — |
| 差值显著性：σ_diff = √(σ₁²+σ₂²)；4.4σ 勉强显著、2.1σ 不显著 | Linden 2020 §13.7 | 键长差异是否可声称 | — |
| Flack s.u. < 0.1（已知对映体纯）/ < 0.04（可能外消旋） | Flack & Bernardinelli，经 Linden 转引 §13.9 | 绝对构型验收 | 0.01(2) 可信；0.0(2) 不可结论 |
| 原子分辨率 ≈ 1.2 Å | Sheldrick 2008 §15.10 | **从头直接法的门槛** | **有重原子（甚至 S、Cl）时门槛显著放松**：这解释了纯有机体系为何更难 |
| C–H 0.85–1.05 Å；Biso 2.0–6.0 Å² | Harlow 1998，经 Watkin 转引 §15.7 | 自由精修 H 的合理区间 | H 是**整体**可靠性的敏感探针，不只是 H 自己的问题 |
| ⟨I²⟩/⟨I⟩² 显著 **< 2.0** | Xtriage §16.11 | **孪晶**方向 | 完美孪晶理想值 1.5（非心） |
| ⟨I²⟩/⟨I⟩² 显著 **> 2.0** | Xtriage §16.11 | **赝平移**方向 | **偏离的符号本身即诊断信息，只报"偏离"等于丢一半信息** |
| 非心理想值 ⟨I²⟩/⟨I⟩² 2.000、⟨F⟩²/⟨F²⟩ 0.785、⟨\|E²−1\|⟩ 0.736 | Xtriage §16.11 | 未孪晶基线 | 完美孪晶对应 1.500 / 0.885 / 0.541 |
| 中心理想值 3.000 / 0.637 / 0.968 | Xtriage §16.11 | 未孪晶基线 | 完美孪晶对应 2.000 / 0.785 / 0.736 |
| 多元 Z 分数 < 3.5 | Xtriage §16.11 | 数据"好到合理" | **大值指示孪晶，小值并不排除孪晶**（单向证据） |
| Patterson 距原点 > 15 Å 的最大峰，p < 0.05 / p < 10⁻³ | Xtriage §16.10 | 弱 / 强赝平移迹象 | 大反常散射体（如 Hg）的自向量会产生同样的峰；15 Å 是大分子经验值，小分子需调整 |
| tNCS 存在 ⇒ 大量"离群点" | Xtriage §16.10 | **自动剔除离群点会在 tNCS 样品上误删真实数据** | — |
| 孪晶指数 n = V_T/V；偏角 ω | Grimmer & Nespolo §16.5 | 孪晶六分类的两个定量参数 | 立方/六方不可能 pseudo-merohedry |
| obverse–reverse 孪晶只影响 1/3 强度数据 | Parsons 2003 §16.5 | 网状并孪晶 | — |
| 每非氢原子约 18 Å³ | Linden 2020 §12.4 | 从晶胞体积反推 Z | 用于识别"自动软件把晶系定错" |
| 堆积系数约 65% | PLATON §12.4 | Kitaigorodskii 型 | — |
| 正常结构无 > ~25 Å³ 的溶剂可及空腔 | PLATON §12.4 | 空腔判据 | H₂O ≈ 40 Å³；甲苯类 100–300 Å³ |
| BVS 的 b 在 0.3–0.6 Å，惯用 0.37 | Brown 2009 §12.1 | 键价参数 | **无唯一值**；且 **BVS 原理上不适用于有机化合物**（不含 C–C、C–H） |
| 特殊位置 sof 需乘位置重数（四重轴上常写 10.25） | SHELXL §12.2 | 特殊位置记账 | 手工写会让程序**报告但不施加**正确约束；自由变量误用在特殊位置 Uij 上会让精修发散 |
| sso = nsym/ssm；SOF = occupancy/sso | checkCIF §12.3 | **CIF 里写 occupancy 不是 SOF** | 对称心上满占据原子：SHELXL sof = 0.5，CIF occupancy 必须 = 1.0 |
| τ₅ = (β−α)/60°；τ₄ = [360−(α+β)]/141° | §12.5（二手） | 五 / 四配位几何描述符 | **是描述符不是判据**；0 与 1 的含义见正文 |
| Zr K 边：λ 差 1.7×10⁻⁴ Å，f″ 从 ~3.7 跌至 0.53 | 本项目 cctbx 实算 §14.5 | **边附近对波长极度敏感** | 正好落在边上的表值本身是插值假值 |
| Zr 在 K 边上 f′ = −9.0 e（Z=40 的 22%） | 本项目 cctbx 实算 §14.5 | 反常修正可以很大 | Mo Kα 下仅 −3.0 |
| C/N/O 的 f″ 在任何实验室波长下 0.001–0.05 | 本项目 cctbx 实算 §14.5 | 轻原子绝对构型为何难 | Cu Kα 下 O 的 f″ 是 Mo Kα 的 5 倍 |
| Fe 在 Cu Kα 下 f″ = 3.20 | 本项目 cctbx 实算 §14.5 | 含铁样品用 Cu 会强荧光 | — |
| Cr Kα 2.2909 Å：f″ 约 Cu 的 2 倍，但分辨率 1.2 Å vs Cu 0.8 Å | Parsons 2017 §14.4 | 波长权衡的四要素 | 吸收系统误差同时显著增大 |
| 吸收边 < 6 keV ⇔ λ > 2 Å | Merritt §14.3 | 晶体学中使用的实际困难 | — |
| ORGX/ORGY 错误 | XDS wiki §11.2 | **指标化失败的最常见单一原因** | — |
| 观测/参数比 ≥ 10（心）/ ≥ 8（非心） | IUCr Acta C/E §17.2 | 投稿要求 | HKLF 5 孪晶数据天然冗余未合并，是成文的例外 |
| 每分辨率壳层完整度 ≥ 95% | Garman 1999 §18.1 | 完整度目标 | **按壳层，不是总体一个数** |
| 2θmax ≈ 50° + 完整度 100% ⇒ 约 10 反射/参数 | Sanjuan-Szklarz 2016 §18.1 | 与 IUCr 的 10:1 对上了 | 限无重原子的有机小分子 |
| max shift/s.u. > 1.5 | IUCr 编辑指引 §17.5 | **收敛不良** | 排查方向：Flack / 消光 / H / 无序 |
| WGHT 默认 a=0.1，P 的 f=1/3 | SHELXL §17.4 | F² 精修权重 | 验收判据是"方差对 Fc² 与分辨率无系统趋势"，**不是 GooF ≈ 1** |
| 建模完成前保持 WGHT 0.1 | SHELXL §17.4 | 何时才优化权重 | 等权重对 F² 精修 "never a sensible option" |
| SQUEEZE 后须申报 nextra | SHELXL §17.4 | 否则 s.u. 与 GooF 被**低估** | 与"s.u. 本身已低估 1.5–2×"叠加 |
| 探测器距离 ≥ 40 mm | APEX3 实操手册 §18.2 | 碰撞与斑点重叠下限 | "no matter what the default value is" |
| SQUEEZE 前提：分辨率 0.84 Å + 先补 H 生成 vdW 面 | Ramadhar 2015 §18.6 | 使用条件 | — |
| checkCIF 1–5 型 / A-C-G 级 / n_0xx–n_9xx | Spek CIF-VALIDATION §17.6 | 警报体系 | **2 型="模型可能错"，3 型="质量可能低"——两者不可混为一谈** |

---

## 附录 B 来源清单与证据强度

### B.1 已取得逐字原文的一手来源（25 份主调研 + 补齐轮）

**厂家 / 软件文档**
- Bruker AXS, *SADABS User Manual* v2.03 (2002), doc M86-E00046-0102 - https://xray.uky.edu/Resources/manuals/SADABS-manual.pdf
- Bruker AXS, *SHELXTL Software Reference Manual* (1997), 含 XPREP 章与 Herbst-Irmer 撰写的第 11 章孪晶，https://xray.uky.edu/Resources/manuals/Shelxtl-manual.pdf
- Agilent/Rigaku OD, *CrysAlisPro User Manual* rev. 5.2 (2013, 软件 171.36.24) - https://www.agilent.com/cs/library/usermanuals/Public/CrysAlis_Pro_User_Manual.pdf
- *SHELXL Command List*（Universität Göttingen 官方），https://shelx.uni-goettingen.de/shelxl_html.php
- Olex2 官方帮助 refine.md 与 Olex2_restraints_and_constraints.md - https://github.com/Olex2/help
- PLATON SYSTEM-S 文档，http://www.platonsoft.nl/platon/pl070000.html
- PLATON ADDSYM 文档，https://www.platonsoft.nl/platon/pl000401.html
- CCP4i2 AIMLESS scaling & merging - https://ccp4i2.gitlab.io/rstdocs/tasks/aimless_pipe/scaling_and_merging.html
- CRYSTALS 官方文档，https://www.xtl.ox.ac.uk/crystals.1.html
- Jana2020 官方说明，https://jana.fzu.cz/about-jana
- "Treatment of Hydrogen Atoms"（WinGX/CCP14 镜像的经典教学文档），https://www.chem.gla.ac.uk/~louis/software/wingx/hlp/sxl103.htm
- Purdue X-ray Facility, *Analysis of crystals twinned by non-merohedry*（Nimthong-Roldan & Zeller, 2016），https://www.chem.purdue.edu/xray/docs/TwinningUserGuide_09Dec2016.pdf
- ACS, *Requirements for Depositing X-Ray Crystallographic Data* (2025) - https://pubsapp.acs.org/paragonplus/submission/acs_cif_authguide.pdf

**IUCr 验证过程页**（抓取时逐字取得，复核时多次 403）
- checkCIF ABSTM_02 - https://journals.iucr.org/services/cif/checking/ABSTM_02.html
- PLATON data validation tests 总表，https://journals.iucr.org/services/cif/checking/platon_tests.html

**期刊论文**
- Sheldrick, G. M. (2015). SHELXT – Integrated space-group and crystal-structure determination. *Acta Cryst.* A71, 3–8. - PMC4283466
- Palatinus, L. & van der Lee, A. (2008). Symmetry determination following structure solution in P1. *J. Appl. Cryst.* 41, 975–984.
- Parsons, S., Flack, H. D. & Wagner, T. (2013). *Acta Cryst.* B69, 249–259. - PMC3661305
- Spek, A. L. (2009). Structure validation in chemical crystallography. *Acta Cryst.* D65, 148–155. - PMC2631630
- Spek, A. L. (2015). PLATON SQUEEZE. *Acta Cryst.* C71, 9–18.
- Spek, A. L. (2020). checkCIF validation ALERTS: what they mean and how to respond. *Acta Cryst.* E76, 1–11. - PMC6944088
- Müller, P. (2009). Practical suggestions for better crystal structures. *Crystallogr. Rev.* 15, 57–83. - https://web.mit.edu/pmueller/www/own_papers/suggestions.pdf
- Müller, P. *Refinement of Disorder with SHELXL*（MIT 教程），https://web.mit.edu/x-ray/Summer_School_Material/Disorder_Workshop/Disorder_Workshop.pdf
- Herbst-Irmer, R. *Twinning in Chemical Crystallography*（RECIPROCS Paris 2019），https://cdifx.univ-rennes.fr/RECIPROCS/Paris2019/pdf/ChemicalCrystallography_RHI.pdf
- Clegg, W. (2019). Some reflections on symmetry: pitfalls of automation. *Acta Cryst.* E75, 1812–1819. - PMC6895943
- Raymond, K. N. & Girolami, G. S. (2023). Pathological crystal structures. *Acta Cryst.* C79, 445–455.
- Harlow, R. L. (1996). Troublesome Crystal Structures. *J. Res. NIST* 101, 327. - PMC4894611
- Marsh, R. E. (2004). Space group Cc: an update. *Acta Cryst.* B60, 252–253.
- Marsh, R. E. (1997). The perils of Cc revisited. *Acta Cryst.* B53, 317–322.
- Marsh, R. E. (1999). P1 or P-1? Or something else? *Acta Cryst.* B55, 931–936.
- Marsh & Spek (2001). Use of software to search for higher symmetry: space group C2. *Acta Cryst.* B57, 800–805.
- Beilsten-Edmands et al. (2020). Scaling diffraction data in DIALS. *Acta Cryst.* D76, 385–399. - PMC7137103
- Winter, Lobley & Prince (2013). Decision making in xia2. *Acta Cryst.* D69, 1260–1273. - PMC3689529
- "Automated Crystal Structure Determination Has its Pitfalls: Correction to the Crystal Structures of ..." — PMC8361933
- NeuDiff Agent, *J. Appl. Cryst.* 59 (2026) 1102–1111 - https://journals.iucr.org/j/issues/2026/04/00/oz5013/
- Klar et al. (2023). *Nature Chemistry*: https://www.nature.com/articles/s41557-023-01186-1（仅摘要级）
- IUCr 量子晶体学论文（过渡金属氢化物 HAR vs IAM），PMC10833390

### B.2 证据强度总账

- **抓取层**：25 份主来源全部成功，每条声明附源文件 verbatim 引语；补齐轮又新增约 60 条逐字引语（xia2、Harlow、自动化失败案例、CRYSTALS、Jana2020、SHELXL 的 AFIX/HFIX/FRAG/RESI、氢原子教学文档、Olex2 帮助、金属氢化物）。
- **对抗验证层**：deep-research 工作流两次运行都被 API 限流打断（108 个子任务 31 个 429、确认 15 条；重跑 105 个 75 个 429、确认 0 条）。
- **定向抽验**：对九条最吃重的数字做了独立重新取源。SHELXT、Parsons/Flack、SHELXL 手册、Marsh、AIMLESS 五条 **CONFIRMED**（逐字吻合）；Müller 无序教程 **PARTIALLY**（我曾把 SAME 的两条独立忠告接成因果句，已在 §5.3 改正并分列）；RFACG01 **PARTIALLY**（>0.10→C、>0.15→B 逐字确认，A 级 0.20 与 "<0.07 expected" 未确证）；PLAT601/605 空腔体积 **PARTIALLY**（仅转述级）；ABSTM_02 **首次抓取逐字成功、复核 403**（抽验另在真实 checkCIF 报告里查到 RR>1.10 的实际措辞，机制方向成立）。
- **已知缺口**（见 §10.3）：3D-ED 的正文细节、MicroED 数据筛选标准的逐字来源、调制结构的识别与精修实务、Palatinus 2015 两篇原文、PLAT420/430 官方页。

### B.3 第二轮（第 11–18 章）新增的一手来源

**期刊论文（均已取得逐字原文）**
- Linden, A. (2020). *Obtaining the best results…* Acta Cryst. **E76**, 765–775 - PMC7273997，第 13 章
- Watkin, D. (2008). *Structure refinement: some background theory and practical strategies.* J. Appl. Cryst. **41**, 491–522 - web.mit.edu/pmueller/www/Watkin_2008.pdf，第 15 章
- Sheldrick, G. M. (2008). *A short history of SHELX.* Acta Cryst. **A64**, 112–122 - web.mit.edu/x-ray/Summer_School_Material/Sheldrick_2008.pdf —— §15.10
- Parsons, S. (2003). *Introduction to twinning.* Acta Cryst. **D59**, 1995–2003 - journals.iucr.org PDF 直链 —— §16.1–16.4
- Grimmer, H. & Nespolo, M. (2006). *Geminography: the crystallography of twins.* Z. Kristallogr. **221**, 28–50 - crm2.univ-lorraine.fr —— §16.5
- Clegg, W. et al. (2019). *Some reflections on symmetry: pitfalls of automation…* Acta Cryst. **E75** —— §16.7
- Pinheiro, C. B. & Abakumov, A. M. (2015). *Superspace crystallography…* IUCrJ **2**, 137–154 —— §16.8
- Fröschl, D. et al. (2025). *OD interpretation and diffuse scattering analysis…* Acta Cryst. **B81**, 550–564 —— §16.9
- Spek, A. L. (2020). *checkCIF validation ALERTS…* Acta Cryst. **E76** —— §16.8
- Spek, A. L. (2015). *PLATON SQUEEZE…* Acta Cryst. **C71**, 9–18 —— §18.6
- Garman, E. (1999). *Cool data: quantity AND quality.* Acta Cryst. **D55**, 1641–1653 —— §18.1、§18.4
- Nichol, G. S. & Clegg, W. (2005). Acta Cryst. **B61**（巴比妥酸二水合物变温研究）—— §18.5
- Ramadhar, T. R. et al. (2015). *Practical guidelines for the crystalline sponge method.* Acta Cryst. **A71** —— §18.2–18.3、§18.6
- Parsons, S. et al. (2017). *Determination of absolute configuration using X-ray diffraction.*: pure.ed.ac.uk —— §14.4
- El Omari, K. et al. (2024). Acta Cryst. **D80**, 713–721 - PMC11448921 —— §14.2–14.3
- Brown, I. D. (2009). Chem. Rev.（键价模型综述）—— §12.1
- Sanjuan-Szklarz, W. F. et al. (2016) - PMC4704080 —— §18.1

**官方文档 / 手册**
- SHELXL Command List（Göttingen 官方）与 SHELXL 手册 PDF（web.sas.upenn.edu 转载）—— §12.2、§17.1、§17.4–17.5
- COMCIFS `cif_core.dic`（GitHub raw）—— §17.6
- Spek, A. L., *CIF-VALIDATION.pdf*（platonsoft.nl）—— §17.6
- IUCr Acta C/E 投稿数据要求（`/c/services/cif/reqdata.html`，经 r.jina.ai）—— §17.2
- **IUCr Validation Co-editor 内部指引**（`/services/coeditors/cifs/Valid.html`，经 r.jina.ai）—— §17.3、§17.5、§17.7 ← **本轮最有价值的单一来源**
- Phenix *Xtriage* 文档（phenix-online.org）—— §16.10–16.11
- Merritt, E. A., *X-ray Anomalous Scattering* 教学站（skuld.bmsc.washington.edu，curl 直连）—— §14.1–14.3
- Northwestern IMSERC, Kappa APEX3 手册 —— §18.2
- XDS wiki，第 11 章

**本项目自算（非文献）**
- `workdir/fdp_scan.py` + `fdp_scan_output.txt`：用项目 venv 的 `cctbx.eltbx.sasaki` 计算 Zr 跨 K 边的 f′/f″ 扫描与十种元素在三个实验室波长下的值 —— §14.5

**二手来源（已标注，不作一手引用）**
- Wikipedia "Geometry index"（τ₄/τ₄′/τ₅ 公式）—— §12.5

### B.4 第二轮的证据强度与已知瑕疵

- 全文带原文引号的引用行 **571 行**（第一部分 289 / 第二部分 282）。计数口径：以 `>` 开头且含英文引号的行；跨行的长引语按行计，故"条数"略少于此数。
- **一条不达逐字标准并已标注的**：SHELXL WGHT 公式（§17.4），`pdftotext` 丢失希腊字母与上下标，由代理按公认公式补回，**非逐字节原文**。
- **两条来源未复核**：§16.10 的 PLAT115/116 引语来自代理本机缓存页，精确 URL 未确认；§17.6 的 r/p 比值段落为句首被截断的片段。
- **一条如实保留的转写瑕疵**：§17.7 的 `illogi cal`（r.jina.ai 代理转换所致），未擅自"修正"。
- **一次明确捕获的检索层不可靠**：WebSearch 摘要声称 Oregon SHELX-97 页讨论 OMIT/SHEL 指令变更，实际抓取后 grep 无该字符串，已弃用（见 §17.8）。
- **两轮均未取得的一条关键出处**：中心对称空间群 Bijvoet 差恒为零的成文表述（§14.2）。该规则已被写进本项目的系统规则，目前属"相信其对但引不出原文"。

### B.5 补漏核对（2026-09-03，两轮之后的一次全面回查）

把 `workdir/partB.txt`（第一轮 25 个来源、125 条 QUOTE）与第二轮各批返回的原始材料，逐条对照本文实际写入的内容，做了一次机械 + 人工的双重核查（工装 `workdir/audit_quotes.py`、`audit_probe.py`、`audit_docs.py`）。

**机械核查结果**：交叉引用（全文 §X.Y 形式）**全部命中**，小节编号无缺号无重号。

**查出并已补入的遗漏（14 处）**：

| 补入位置 | 内容 | 为什么重要 |
|---|---|---|
| §0.4 | Müller："crystallographer 只需要三样东西：理论理解、耐心、约束与限制的使用熟练度"，并把"哪些决策该留白"点成四项清单 | 三样里没有一样是阈值表；四项清单是作者本人认为**不该**写成规则的东西 |
| §1.7 | SADABS 帧间比例因子限制 esd 0.001–0.005 / 默认 0.002 / 用 R1 浅极小定其最优值 | 点明了"人为压低 Rint"具体是哪个旋钮，并给出用下游指标定上游参数的方法 |
| §3.6 | "384 space-group changes were indicated"（分母 35 760 条，约 1%）+ 同批高频问题是未说明空腔与氢原子 | 给出漏对称的规模 |
| §3.6 | "There are many borderline cases for which the reflection data are needed for a definitive space-group assignment." | ADDSYM 是纯几何的，边界情形必须回衍射数据定案 |
| §3.2 | SHELXTL roe119 实例：统计说心化、消光只容非心；晶胞角偏 0.04°；只收了一半数据 | 两条证据链矛盾**本身**是晶系定错的诊断 |
| §3.5 | Raymond & Girolami："正确群通常是所选群的**超群**" | 直接缩小错群搜索方向 |
| §5.3 | Müller："相似性限制须覆盖几何与 ADP 两侧、适用于全部无序原子" | 比文中原有那句范围更宽 |
| §5.7 | "This method should not be used in cases of twinning" 指的是 **.ins/.hkl 捷径**，孪晶必须走 LIST 8 解卷积 .fcf | 极易误读成"SQUEEZE 不能用于孪晶" |
| §5.7 | 尖隙空间可占胞体积约 30% 而溶剂可及体积为零 | 防止"有 30% 空隙 ⇒ 应该有溶剂"的错误推断 |
| §6.2 | Müller："Always look at a plot of the anisotropic displacement ellipsoids" + 形态学逐条原文 | "要去看"本身是判据的一部分 |
| §8.10 | Müller："发表前必须跑自动验证；每个人都会犯错" | 与"跑干净≠结构对"必须成对读 |
| §14.2 | Fanwick："AS is important in both centric and accentric space groups." | **纠正一个易错表述**：中心对称群里反常散射照样存在，只是不产生 Bijvoet 差 |
| §14.3 | Merritt：取 f″ 极大与取 \|f′\| 极大的两个波长"挨得极近，需要极高的波长控制精度" | 与 §14.5 我们自算的边附近敏感性互证 |
| §15.1 | Watkin 情形二引语的后半句："restraints should be investigated as a way to achieve a preconceived end result" | 原作者没有粉饰情形二的性质 |
| §16.5 | Xtriage："delta le-Page 就是 obliquity"；且"Non-merohedral (reticular) twinning is not considered" | 把 (n, ω) 分类学接到可计算量上；同时暴露一条工具能力边界 |
| §16.10 | 补全为 "Outliers are removed from the data set in the further analysis. Note that if..." | 前半句才说明危险在哪 |

**同时订正的两处表述**：
- §17.2 / §18.1 原先把 IUCr 的 10:1 / 8:1 观测参数比当作新内容，实际 §1.1 的 Müller 引文里早已出现并附有到 0.84 Å / 2θmax 50°(Mo) / 134°(Cu) 的换算；已加交叉引用。
- §18.1 原写"那条要求实际上**等价于**至少收到 2θ ≈ 50° 且收满"，过强；比值还取决于参数数目（分子大小、各向异性、H 是否自由精修、有无无序），已改为"实践中大致同义，但不是严格等价"并说明边界。

**核查中确认为假警报的（无需改动）**：孪晶警示清单 (c)/(k)/(l) 与 K、most disagreeable 反射均已在 §2.2/§2.7（机械比对没命中只是因为文中用的是同源但措辞略异的另一段原文）；SADABS 关于 Rint 的核心引语在 §1.7；Palatinus 的 P4₁/进动图实例在 §3.1（§13.2 对它的交叉引用成立，机械比对失手是因为文中写作下标 "P4₁"）；SQUEEZE 的前提条件、低角数据、Flack s.u. 影响均在 §5.7；SHELXT 的 α₀ < 0.3 与"无重于 Sc 的原子即停止"在 §4；Müller 的"哪些决策靠经验"清单在 §0.4。

**唯一未采纳的候选**：SHELXT 论文中 "the other 11 space groups tested were rejected because one or more figures of merit were too high" —— 属实例的装饰性细节，其判据本身（α₀、R1、R_weak、Flack 的联合排序）已在 §4。

**这次核对本身的一个结论**：机械比对（字符串包含）在本任务上的**假阳性率约三分之二**: 56 条候选里只有 14 条是真遗漏。原因是同一份来源的同一件事常有多处措辞、以及中文正文里改用了下标/全角字符。**机械核查只能用来生成候选清单，判定必须回到人工阅读。**

### B.6 与本知识库配套的另一份文档

`docs/scxrd-expert-knowledge-review.md`，把本知识库的内容对照 CrystalPilot 现状（AGENTS 模板、技能卡、70 个 MCP 工具、历次战役），给出过拟合诊断、知识编码原则与 P0–P2 路线图。**本文是"领域知识"，那一份是"我们该怎么办"。**
