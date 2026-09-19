# checkCIF 逐条验证说明

验证对象：`final.cif`；本地 PLATON/checkCIF 最终结果为 A 级 6 条、B 级 2 条、C 级 15 条。最终结构性 A 级警报为零；余下 A 级均来自数据完整度或缺失实验记录。最终 SHELXL-2019/3 指标为 R1(obs) = 0.0666、R1(all) = 0.0733、wR2 = 0.2100、GooF = 1.028，最大 shift/s.u. = 0.000，差值密度 +1.571/−1.578 e Å⁻³。

## PLAT975 专项说明

最终 checkCIF **未报 PLAT975**。最高正残峰仍位于 N3 附近（距 N3 约 1.25–1.28 Å），但无法组成有化学意义且连续的次组分；强行放置 C/N/O 会破坏 N3 已有的 La–N3–C4/C11 配位与价态。HKLF5 对照和反射失配统计也不支持用第二孪晶畴解释该峰，因此按诚实原则不加无身份原子。若期刊服务器因程序版本差异重新报 PLAT975，可直接引用这一证据链。

### A PLAT029 `_diffrn_measured_fraction_theta_full value Low .      0.907 Why?`

- 含义：常用完整分辨率范围内的数据完整度偏低。
- 本结构中的原因：theta-full 完整度为 0.907；全部数据到 d_min = 0.682 Å 时总体完整度为 0.741，属于高角覆盖缺失，而非精修删点造成。
- 已做的检查/尝试：保留全部 12112 个输入 HKLF4 反射，没有为降低 R 值截断分辨率；HKLF5 对照也未改善数据覆盖。
- 影响评估：降低几何精度并使末端/客体 ADP 较不稳定，但主骨架和金属配位仍有充分密度支持。投稿时须解释；彻底消除需重新测量缺失晶带。

### A PLAT183 `Missing _cell_measurement_reflns_used Value ....     Please Do !`

- 含义：缺少晶胞测定所用反射数。
- 本结构中的原因：交付数据只有 TWINABS/XPREP 后的 HKL 与 INS，未附 SAINT 的晶胞测定统计。
- 已做的检查/尝试：检查了 context.json、INS/HKL 及现有还原记录；该数值无法由合并后的独立反射可靠反推。
- 影响评估：不改变结构模型，但属于实验可重复性元数据缺口。需从原始 SAINT/P4P 日志补录。

### A PLAT184 `Missing _cell_measurement_theta_min Value ......     Please Do !`

- 含义：缺少晶胞测定反射的最小 θ。
- 本结构中的原因：原始晶胞测定日志未随数据提供。
- 已做的检查/尝试：没有用最终 HKL 的 θ 范围冒充晶胞测定专用反射范围。
- 影响评估：仅影响实验记录完整性；需原始 SAINT/P4P 输出才能消除。

### A PLAT185 `Missing _cell_measurement_theta_max Value ......     Please Do !`

- 含义：缺少晶胞测定反射的最大 θ。
- 本结构中的原因：同 PLAT184，输入包不含相应原始记录。
- 已做的检查/尝试：保持为未知值，未从数据分辨率臆造。
- 影响评估：不影响当前坐标与配位结论；投稿前应由原始还原日志补齐。

### A PLAT699 `Missing _exptl_crystal_description Value .......     Please Do !`

- 含义：缺少晶体形貌描述。
- 本结构中的原因：context.json 明确把晶体 habit/colour 标为 unknown。
- 已做的检查/尝试：未根据衍射数据猜测晶体颜色或形状。
- 影响评估：不影响结构解与精修，但期刊 CIF 元数据不完整；需实验者提供显微镜记录。

### A PLAT881 `No Datum for _diffrn_reflns_av_R_equivalents ...     Please Do !`

- 含义：缺少等价反射合并 R 值 R_int。
- 本结构中的原因：主文件是 TWINABS 已合并的独立 HKLF4，12112 行中没有等价重复观测；当前工具显示的 0.000 只是“无重复可统计”，不能当作实验 R_int。
- 已做的检查/尝试：反射审计确认无重复组；没有伪报 R_int = 0。HKLF5 文件用于孪晶对照，不能重建原始 SAINT 合并统计。
- 影响评估：无法从现有文件独立评价原始重复观测一致性。需 TWINABS/SAINT 最终报告或未合并反射文件补录。

### B PLAT242 `Low 'MainMol' Ueq as Compared to Neighbors of C11 Check`

- 含义：C11 的 Ueq 相对邻原子偏低，需排查元素判错或局部无序。
- 本结构中的原因：C11 是叔丁基中心的季碳，Ueq = 0.0639 Å²；相邻三个甲基具有更大的旋转运动，因此比较值自然偏高。
- 已做的检查/尝试：确认 N3–C11 = 1.482(8) Å，C11–C36/C31/C38 = 1.479(14)/1.482(13)/1.549(16) Å；全占位、各向异性正定，差图没有要求更重元素。
- 影响评估：符合季碳连接和末端甲基运动，不影响元素指认或主骨架可信度。

### B PLAT995 `Can not Recreate .fcf from Embedded .res & .hkl          ! Check`

- 含义：PLATON 未能在其运行环境中调用 SHELXL，从 CIF 内嵌 RES/HKL 重新生成 FCF。
- 本结构中的原因：checkCIF 的详细说明明确提示检查 `SHLEXE/PATH`；本模型没有溶剂掩膜或 `.fab` 依赖。
- 已做的检查/尝试：CrystalPilot 已直接调用 SHELXL-2019/3 成功精修，内嵌模型含全部 H66；独立 FCF 审计得到 R1(obs) = 0.06657、R1(all) = 0.07327，与最终 CIF 一致，且 `final.fcf` 已交付。
- 影响评估：这是本地 PLATON 子进程路径问题，不是结构因子或模型不一致。投稿时同时提交 final.fcf 即可；若需本机消警，配置 PLATON 的 SHLEXE。

### C PLAT052 `Info on Absorption Correction Method Not Given Please Do !`

- 含义：吸收校正方法字段未给出受控关键词。
- 本结构中的原因：用户说明数据经过 TWINABS，但输入包没有版本、Tmin/Tmax 或完整吸收校正报告；将 type 写成 multi-scan 会立刻产生 PLAT058/059-A。
- 已做的检查/尝试：CIF details 中如实记录“TWINABS 已用于数据还原、透过率未提供”，type 与 Tmin/Tmax 保持未知，避免伪造。
- 影响评估：La/Ni 使吸收校正文档较重要。需原始 TWINABS 报告补齐方法、版本和 Tmin/Tmax 后再投稿。

### C PLAT053 `Minimum Crystal Dimension Missing (or Error) ... Please Check`

- 含义：缺少晶体最小尺寸。
- 本结构中的原因：实验记录未提供晶体尺寸。
- 已做的检查/尝试：未凭经验填写 SIZE。
- 影响评估：影响吸收校正与实验复现说明；需实验者提供实测三维尺寸。

### C PLAT054 `Medium Crystal Dimension Missing (or Error) ... Please Check`

- 含义：缺少晶体中间尺寸。
- 本结构中的原因：同 PLAT053。
- 已做的检查/尝试：保持未知，未编造。
- 影响评估：需与最小/最大尺寸一起从原始测量记录补齐。

### C PLAT055 `Maximum Crystal Dimension Missing (or Error) ... Please Check`

- 含义：缺少晶体最大尺寸。
- 本结构中的原因：同 PLAT053。
- 已做的检查/尝试：保持未知，未编造。
- 影响评估：不改变坐标，但限制吸收校正审计；需原始晶体记录。

### C PLAT220 `NonSolvent Resd 1 C Ueq(max)/Ueq(min) Range 4.0 Ratio`

- 含义：主分子不同碳原子的 Ueq 范围较大。
- 本结构中的原因：刚性的配位/芳香碳与多个室温可旋转异丙基、叔丁基甲基共存；后者运动显著更强。
- 已做的检查/尝试：全体非氢原子均各向异性精修且正定；validate_structure 无 ghost_atom_suspect，差图未支持删除或拆分主配合物原子。
- 影响评估：主要反映柔性取代基和数据完整度，不改变 La/Ni 核心连接；低温、更完整数据可改善。

### C PLAT222 `NonSolvent Resd 1 H Uiso(max)/Uiso(min) Range 4.1 Ratio`

- 含义：主分子 H 的 Uiso 范围较大。
- 本结构中的原因：所有 H 为标准骑乘模型；芳香 CH/CH2/CH 使用 1.2Ueq，旋转甲基使用 1.5Ueq。载体碳 Ueq 本身跨度大，故 H 的绝对 Uiso 比值也大。
- 已做的检查/尝试：核对 AFIX，最终式含完整 H66；不存在自由精修 H 或异常占有率。
- 影响评估：不是错误骑乘系数，对重原子结构无实质影响。

### C PLAT241 `High 'MainMol' Ueq as Compared to Neighbors of N8 Check`

- 含义：N8 的 Ueq 相对邻原子偏高。
- 本结构中的原因：N8 为端位腈/异腈型 N，Ueq = 0.0667 Å²，处于轻原子末端并与 Ni 配位，运动大于重金属邻原子。
- 已做的检查/尝试：Ni–N8 = 1.872(7) Å、N8–C3 = 1.162(8) Å，键长与线性多键片段相符；密度与元素 N 一致，全占位。
- 影响评估：局部 ADP 差异可解释，不支持降占有率或改元素；不影响 Ni 配位指认。

### C PLAT242 `Low 'MainMol' Ueq as Compared to Neighbors of P1 Check`

- 含义：P1 的 Ueq 相对邻原子偏低。
- 本结构中的原因：P 是较重且被 Ni–P 与三个 P–C 键固定的原子，Ueq = 0.0469 Å²，自然低于柔性碳端基。
- 已做的检查/尝试：Ni–P1 = 2.1989(17) Å；P1–C7/C22/C16 = 1.860(7)/1.874(7)/1.877(8) Å，元素与几何均合理。
- 影响评估：不提示元素判错，对结构可靠性无负面影响。

### C PLAT242 `Low 'MainMol' Ueq as Compared to Neighbors of C27 Check`

- 含义：C27 的 Ueq 相对邻原子偏低。
- 本结构中的原因：C27 是连接 C3 与三个甲基的季碳，Ueq = 0.074 Å²；其甲基端运动更大。
- 已做的检查/尝试：C3–C27 = 1.457(8) Å，C27–C37/C44/C41 = 1.461(15)/1.472(16)/1.571(17) Å；密度支持全占位 C。
- 影响评估：与季碳—运动甲基的物理图像一致；较长的 C27–C41 反映末端运动/数据精度，不支持幽灵原子假设。

### C PLAT243 `High 'Solvent' Ueq as Compared to Neighbors of C42 Check`

- 含义：晶格苯 C42 的 Ueq 相对环邻原子偏高。
- 本结构中的原因：独立 C6H6 客体在室温晶格中存在较强运动；C42 Ueq = 0.168 Å²。
- 已做的检查/尝试：以两个局部差峰锚定的整环刚体双取向试验得到 0.627/0.373，但 R1/wR2 反而变差，故否决离散 PART 模型；保留单取向并只约束不变的环几何。
- 影响评估：客体精确位置/ADP 可信度有限，不影响 La/Ni 主配合物连接。

### C PLAT243 `High 'Solvent' Ueq as Compared to Neighbors of C43 Check`

- 含义：晶格苯 C43 的 Ueq 相对邻原子偏高。
- 本结构中的原因：与 C42 相同，为未能离散解析的整体运动；C43 Ueq = 0.165 Å²。
- 已做的检查/尝试：同一整环无序分支已经显式比较并被 R 因子和差图否决，未为压 R 强留小占有率组分。
- 影响评估：局限于晶格苯客体；建议低温数据以分辨静态/动态无序。

### C PLAT244 `Low 'Solvent' Ueq as Compared to Neighbors of C28 Check`

- 含义：晶格苯 C28 的 Ueq 相对同环原子偏低。
- 本结构中的原因：C28 Ueq = 0.113 Å²，虽低于 C42/C43，但仍明显高于常规刚性芳环；这是同一非均匀运动模型的一部分。
- 已做的检查/尝试：确认无元素判错、无负占有率、无孤立密度；整环双取向试验未获统计支持。
- 影响评估：说明单一椭球不能完全描述客体运动，但不影响主配合物。

### C PLAT260 `Large Average Ueq of Residue Including C28 0.150 Check`

- 含义：整个 C6H6 客体的平均 Ueq 很大。
- 本结构中的原因：平均约 0.150 Å²，符合晶格苯的室温平移/转动运动。
- 已做的检查/尝试：优先尝试实体双取向而非掩膜；试验变差后回滚。未使用 solvent mask，故不存在实体苯与掩膜双计数。
- 影响评估：苯客体的精细几何/ADP 不宜过度解释；化学计量 C6H6 和主结构连接仍明确。

### C PLAT331 `Small Aver Phenyl C-C Dist C28--C43 1.37 Ang.`

- 含义：晶格苯平均 C–C 略短。
- 本结构中的原因：高 Ueq 与不完整数据使自由精修曾给出 1.21–1.43 Å 并触发 A 级警报。
- 已做的检查/尝试：对六条苯 C–C 使用 DFIX 1.390(10) Å、整环 FLAT 0.01 Å；最终六键为 1.357(9)–1.381(9) Å，A 级已降为 C 级。没有继续收紧以免把客体过度理想化。
- 影响评估：留下的 1.37 Å 均值反映密度分辨力而非异常键型；约束理由已完整披露。

### C PLAT342 `Low Bond Precision on C-C Bonds 0.01466 Ang.`

- 含义：平均 C–C 键长标准不确定度约 0.0147 Å，精度一般。
- 本结构中的原因：总体完整度 0.741、高角覆盖不足，并含多个高运动末端和晶格苯。
- 已做的检查/尝试：保持全部数据、完成各向异性与权重精修；没有以主观分辨率截断换取更小 esd。
- 影响评估：连接关系和金属配位可信，但不宜讨论很小的 C–C 键长差异。改善需要更完整、最好低温的重测数据。

## 结论

没有未处理的结构性 A 级问题，也没有 ghost atom、未说明的 restraint 或溶剂掩膜。剩余 A 级警报均需原始实验记录/补测解决；B/C 级均有数据或化学证据支持的解释。最终提交前最重要的补充材料是 SAINT/TWINABS 报告、晶体尺寸/形貌、实测温度与吸收校正透过率。
