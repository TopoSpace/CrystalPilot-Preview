# 单晶结构解析专家知识调研 × CrystalPilot 雏形对照

日期：2026-09-03　　范围：外部知识（厂家管线 / 晶体学软件 / 专家流程与经验 / 验证与发表 / 自动化与 AI）
对照对象：CrystalPilot 现状（AGENTS v32 模板 + 20 张技能卡 + 5 张案例卡 + 70 个 MCP 工具 + 历次战役）
写作口径：面向项目负责人的中文分析稿；引用的代码位置以 `file:line` 给出，外部来源保留英文原文引用。

---

## 0. 一页结论

用户的担心成立，但位置和想象的不一样：**过拟合不在 agent 的推理里，而在工具默认值、阈值句和评分口径里。**
证据链（详见 §2）：

1. **知识底座是一张 MOF 表。** `crystalpilot/chem/knowledge.py:1-6` 自述 "MOF chemistry knowledge tables"；37 个金属档案覆盖 MOF 常见金属，漏掉全部碱金属（Mg/Ca 除外）、全部铂族、Au/Hg/Re/Nb/Ta/Sn/Sb/Bi/U/Th；缺表金属的配位数校验**静默通过**（`chem/connectivity.py:583`）。M–C 键上限写死 2.15 Å（`chem/connectivity.py:156`，注释即 "M-C bonds are rare in MOFs"）。
2. **从头建模在无金属时退化。** `tools/model_tools.py:154-171` 无金属则峰全判 C；N 预算算出后从未使用（`:162`），任何情况下不指认 N。纯有机物、共晶、含氮杂环的起模会系统性错元素。
3. **外部引擎自由度极低。** `run_shelxl` 只暴露 4 个参数（`refine/tools_shelxl.py:447-465`），指令块硬编码；EADP/EXYZ/SUMP/FVAR/EXTI/SWAT/AFIX 刚体/RESI/SAME 全部不可达且 shell 绕行被禁。任何需要这些指令的结构在工具层就是不可达。
4. **知识层顶层是证据语言，末梢在向查表退化。** `workbench/agents_md.py:49-58` 明确"数字是证据锚点不是触发器"，但同文件 `:305-309` 的"质量标尺"是零免责查表段；pa1–pa3 之后补写的段落体裁是"某格犯错 → 禁令 + 那格的数字"。三张卡记录"低 R 也可能是错群"，第四张卡用 R1<0.25 禁止回头查群。
5. **system_type 三分类只有代码没有知识。** 引擎已分 framework/molecular/salt（`tools/validation_tools.py:37`），但 `knowledge/skills/` 里没有一张 molecular/salt/organometallic 类目的卡。
6. **经验来源集中在三颗晶体。** 13 颗独立晶体、约 65 格战役，PA 系列 45 格全压在 NU-1000 / NU-1200+Cu / Zr₆ 笼上；孪晶经验全部来自一颗 La/Ni 配合物同题五投；绝对构型、Z′>1、并孪晶、纯有机共晶、无机氧化物、3D-ED 从未进过战役。**而这些类型的数据已经躺在 `benchmark/data_ext2` 和 `benchmark/data_frames` 里没跑过。**
7. **根目录 `AGENTS.md` 是过期旧版**（无版本标记，还教 v28 已删除的 CLI solve 后路）；`ensure_agents_md` 永远不会刷新它。

外部调研给出的启发（详见 §3–§5）归结为一句话：**专家的知识不是一张阈值表，而是"每个决策点上有哪些证据、每条证据在什么条件下失效、失效时换哪条"。** 系统要泛化，应把知识按 (a) 确定性检查、(b) 工具 verdict 的证据文本、(c) 按体系类型分层的技能卡、(d) 留白给判断 四层重新分配，并把所有案例数字改成从当前模型/数据实测推算的量。

> **第二轮补充（同日，见本稿 §8）**：按缺口清册又补了 8 章知识，并在两轮之后做了一次全面回查补漏（知识库附录 B.5 记录了查出的 11 处遗漏与 2 处表述订正；全文现有 571 行带原文引号的引用）。第二轮最重要的收获是一条**贯穿性的逻辑形状**：三份独立来源（Watkin 2008、Linden 2020、Phenix Xtriage）都指出这些判据是**单向证据**：异常指示问题，正常不构成没问题的证明。由此新增编码原则 12–14。另外三条对本项目有直接后果：Watkin 明说观测/参数比"只是指导原则、每个结构须按自身情况判断"（**对"判断力优先于阈值"的外部背书**）；他同时指出只看 CIF **无法区分**"烂晶体上的好工作"与"好晶体上的烂工作"（**对我们评分体系的结构性意见**）；Sheldrick 的 1.2 Å 原子分辨率门槛（有重原子时放松）**解释了本稿 §0 第 2 条诊断**：纯有机体系建模退化不是偶发缺陷，而是方法的已知边界。

---

## 1. 方法

- **外部调研**：deep-research 工作流，五个搜索角度并行（厂家管线与数据还原 / 空间群与求解 / 精修决策 / 验证与发表 / 自动化-专家系统-AI），抓取 25 份一手来源、逐条摘取带原文引语的声明。**证据强度须如实说明**：抓取层全部成功（每条声明都附源文件的 verbatim 引语），但随后的三票对抗验证层两次运行都被 API 限流打断（第一次 108 个子任务里 31 个 429、只完成 15 条确认；重跑 105 个里 75 个 429、确认 0 条）。因此本稿的外部声明是**一手来源直引**而非**交叉验证**级别；对其中最吃重的九条数字另做了定向抽验，结果见 §7。
- **内部审计**：三个只读子代理并行审计（知识层 AGENTS+技能卡；工具层 70 个 MCP 工具与写死常数；测试谱系与失败史）。关键论断（根 AGENTS.md 无版本标记、2.15 Å、N 预算死代码、run_shelxl 4 参数、质量标尺无免责语）已由主线程逐条对源码核过。
- 本稿不改任何代码。§6 给出优先级路线图。

---

## 2. 现状诊断：雏形到底"固定"和"片面"在哪里

### 2.1 知识层：AGENTS 模板与技能卡

**生效的文件不是根目录那份。** 真正注入每个项目的是 `crystalpilot/workbench/agents_md.py:39-368` 的 v32 模板（330 行）；根目录 `AGENTS.md`（59 行）没有版本标记，`AGENTS.md:15` 仍教 `crystalpilot.cli solve` 路线，而 `agents_md.py:15-22` 记载 v28 正是因为"四个 agent 把后备 CLI 条款读成许可、交付了不可审计的结果"才删掉它。`codex-home/skills/` 只有 Codex 自带系统技能，晶体学知识只在 `knowledge/skills/`（20 张）与 `knowledge/expert-cases/`（5 张）。

**证据语言与查表语言并存，且查表段每回合必读。**
- 顶层：`agents_md.py:49-58` "工具输出与技能卡里的一切数字都是证据锚点，不是行为触发器，'略低于/高于某值'本身从不构成结论"。带文献来源的六张卡（restraint / twin / Flack / data-collection / review-ruleset / plat097）每张自带免责表头。
- 同文件 `:305-309`："R1<0.05 优秀；0.05–0.10 对多孔 MOF 可接受；残余密度 |峰|≲1.5 e/Å³"——整个体系里唯一没有免责语的纯查表段，且与 `:263-265` 的正确版本（"数据质量决定 R 的下限"）相隔 40 行并存。
- 末梢：pa1–pa3 之后补写的段落体裁明显不同，`framework-solve-ladder.md:67-73`（"R1 明显低于 0.25 后不再回求解阶梯"，0.25 无物理来源）、`framework-restraint-idioms.md:66-71`（NPD 处置顺序固定化）、`mof-solvent-mask-discipline.md:83-89`（"唯一判据是精修 / 降 0.1 就留 / 不要交付无掩膜模型"）、`element-assignment-audit.md:111-119`（把 0.68883 Å = Zr K 边写进硬性段）、`mof-guest-evidence-rule.md:39-40`（0.125×Br 写进 AGENTS 工具说明）。

**跨卡矛盾。** `data-ingest-space-group-protocol.md:46-47`、`framework-twin-pseudosymmetry-alarm.md:49-54`、`hklf5-twin-workflow.md:57-58` 各自记录"错群/漏心/假胞里 R1 也能到 0.14–0.2"，而 `framework-solve-ladder.md:67-73` 用 R1<0.25 禁止回头查群。

**只为一个类目建过知识。** 20 张卡里 4 张以 `mof-`/`framework-` 起名，其余隐含框架语境；没有 molecular / salt / organometallic / inorganic 类目的卡。隐含的 MOF 默认至少十条：掩膜默认要有；负积分＝模型偏轻而非"空洞是空的"；重位点默认属多核簇；金属旁无碳骨架的 C/N 先怀疑为 O 给体（对有机金属系统性错向）；高对称大胞＝孪晶默认嫌疑；残余密度默认是"孔内客体"；高孔隙变温建议；抗衡离子必存在；大结构默认 P1/掩膜活跃。

**检索盲区放大空白。** `refine/tools_skills.py:165-168` 的检索只拼 name/description/tags/aliases，不含正文；EXTI、AFIX 66、Z′、Marsh 只写在正文里，`list_skills` 查不到。`read_skill(section=)` 鼓励按节读，而免责声明写在表头，按节读会读到数字、读不到免责。

**知识空白（有/薄/无）。** 吸收校正类型选择：薄（只有"有没有做过"）。孪晶律搜索：能力与知识错位（TwinRotMat/ROTAX/CELL_NOW 全标为"外部能力"）。Z′>1：薄（`ncs_audit` 有工具无卡）。非标准设置与 Marsh 错群类型学：薄。Hooft/Bijvoet 对：无。氢：O–H/N–H 正向定向薄，水 vs 氢氧根只有一行，金属氢化物零命中。权重方案：有但无独立卡。EXTI：知识在但检索不到且不可执行。刚体 AFIX：无。调制结构：一个词。3D-ED：完全无。checkCIF：约 30 个码有卡。期刊/CSD 提交：薄。小分子有机物特有问题（多晶型、共晶/盐判定、柔性侧链无序、H 键网络、低温相变）：基本无。

### 2.2 工具层：70 个 MCP 工具

**覆盖矩阵。** 厚：建模 8、精修 7、可视化与态势 7、元素归属 6、数据质量 5、空间群 5、求解 5、验证 5。薄：孪晶 3、溶剂掩膜 2、吸收校正与缩放 1.5、无序 1、氢 1。零覆盖：吸收校正方法选择（数值/解析/多扫描/面指标）、`dials.scale` 缩放模型与误差模型、残差驱动的孪晶律搜索、Flack/Hooft 专用分析、无序约束自动生成、刚体/RESI/FRAG、EXTI/SWAT/OMIT/MERG、调制结构、3D-ED 电子散射因子与动力学精修、CSD/期刊格式、EXYZ/EADP/SUMP/FVAR 线性约束。

**知识底座。** `chem/knowledge.py:22-51` 37 个 MetalProfile（注释即 "Zr6O4(OH)4 node (UiO/NU/PCN)"、"HKUST-1 paddlewheel"）；`refine/tools_heavysites.py:110-152` 22 个元素的判别窗口，来源全是 UiO-66/NU-1000/MOF-5/HKUST-1/ZIF-8/MIL；`chem/connectivity.py:156` M–C 上限 2.15 Å；`:583` 无档案金属 CN 永不报警；η 环识别只认 5/6 元全碳环（`:31-36`）；39 条碎片签名精确等值匹配（`:47-85`），部分占据的 PF₆⁻ 立刻变 `small_unrecognised`；只有标签形如 `O\d*W\d*` 的 O 才算水（`:24`）。

**从头建模。** `tools/model_tools.py:143-171`：最强峰→组成里最重金属；其余按到金属距离落 M–O 窗口判 O，否则 C；无金属则全判 C；N 预算 `:162` 死代码。`tools/refinement_tools.py:73-82` 峰化学提示只有"端基节点 O 旁 1.15–1.65 Å 的 C"与"金属旁 1.9–2.6 Å 的给体"两条，docstring 明写来源 pa3。

**外部引擎自由度。** `run_shelxl`：mode / l_s / timeout_s / wght_rounds；指令块硬编码 `L.S. n / BOND $H / CONF / ACTA / FMAP 2 / PLAN 20`（`io/shelx_writer.py:475-480`）。`set_restraints` 8 种 kind，`refine/restraints.py:38-41` 明写 "EADP/SAME/PART etc. are not available"。`model_disorder` 只拆二位点，`refine/tools_disorder.py:565` "EADP is not available"。`add_hydrogens` 11 种几何，无 AFIX 147/148 旋转搜索、无受体定向、U 倍数写死。`scale_and_export` 4 参数，`dials.scale` 模型/误差模型/离群剔除全封闭。`reduce_with_crysalis` 5 步硬编码（`io/crysalis_cap.py:118-123`），无 ABSPACK 类型选择。

**MOF 语汇进了守卫与就绪判定。** `tools/mask_tools.py:42-43` 配位球侵入 2.2/2.7 Å 按 Zr₆ 端基定，`:678-683` 自认多核节点上"每次都标每个金属"；无金属晶体掩膜零化学守卫。`refine/tools_heavysites.py:995-1069` 就绪判定四组阻断里三组是"体积期望扣空腔 / linker 悬空 C / 溶剂既未掩膜也未建模"。`tools/validation_tools.py:99-107` 置信分 R1 分段权重 300/200/150 拍定；`:457` framework 维数门。

**已经做对的通用设计（应当成为范式）。** `refine/tools_batch.py:292-343` 灵敏度地板：判据自带"本模型上能否分辨"的元判断；`refine/absence_test.py:41-80` 消光三态含 undecidable；`chem/connectivity.py:362` + `tools/validation_tools.py:37` 按体系类型切判据并回显所用判据；`io/shelx_writer.py:206-256` 非 Cu/Mo/Ag 波长自动写 DISP 卡；`tools_batch.py:75-80` ELEMENT_RULE 先声明扫描的分辨极限。

### 2.3 经验来源与测试谱系

**13 颗独立晶体，约 65 格战役。** PA 系列 45 格全在三颗上：NU-1000（19 格）、NU-1200+Cu（12 格）、Zr₆ 笼（14 格）。孪晶、超胞陷阱、完整度、HKLF5 的全部经验出自 p770 一颗 La/Ni 膦配合物的同题五投。r11 的四例分子/有机小样本（W(CO)₆、TCNQ、NaOAc·3H₂O、dppf-PdCl₂）首轮全部 publication/acceptable，之后再没回归过。

**类型缺口。** 9 种空间群，无四方/三方/立方战役；非心 4 颗但零个真正的绝对构型考题（三次 Flack 实弹全是"无判定力"或"反演孪晶"，系统默认先验已被校准到"Flack 通常没用"）；Z′>1 零；真正的位点无序建模几乎没有（战役侧"无序处置"≈溶剂掩膜；`model_disorder` 在 cu 泳道 9/10 被同一镜面位点拒绝）；纯有机 1 例；非 Mo/Cu 波长有（同步辐射 0.68883 Å、Cu Kα）；3D-ED 无。

**已有但从未跑过的数据。** `benchmark/data_ext2`：手性纯有机 P2₁2₁2₁（R1 0.0264）、DBU 有机盐显式两组分无序、Cu 草酸配位聚合物 R1 0.018、四个孪晶案例（含"CIF 对孪晶沉默的陷阱案例"）。`benchmark/data_frames`：硫脲 Pnma、L-天冬氨酸孪晶、AsBr₃（Ag Kα 0.56 Å）、八氟萘:酞嗪共晶（同步辐射）、4-氨基吡啶盐酸盐、LEF-PG 共晶（调制结构）、L-半胱氨酸（Diamond I19）。`data_ext2/README.md` 自述的 tune-on-one / verify-on-the-other 孪晶实验尚未做。

**确定性引擎的分布外事实。** `benchmark/CAPABILITY_REPORT.md`：101 例中无机/重元素 solved 8%（1/13，MnSbSe₂I 被指认成 {I:2, C:1} - "默认碳、按金属配位距离指认 O"）、hard-pseudo 0/4、三方/四方 0/4 与 1/2（R32:H 基变换 bug 未修）、≥15k 反射 0/4；调优集 76% → 全新数据 41.6%。

**失败归因。** 按仓库自己的编目，工具/平台/评分器侧约 85–90%，agent 判断约 10–15%；22 份记录无一例伪造。评分器四次错案（赝简并度规盲区、参考本身错、数据还原侧 0.1625、元素盲），`benchmark/grade.py:1174-1183` 自陈 21 个参考里 12 个 R1>0.12。**推论：在新晶体类型上，"评级"既不足以判定 agent 对错，也不足以驱动回灌，而回灌飞轮是本系统改进的唯一机制。**

**从案例推出的规则分三类。**
- 普适（可直接保留）：中心对称群反常散射不可用；掩膜后不可再找客体；occupancy×Z 才是尺子；两引擎 R 永不互比；抗衡离子不得遮掩；SHELXT 组成串标签不是元素证据；"失败信息的信息量决定下游推理质量"；"纪律条款越具体越容易被机械执行"。
- 普适但阈值案例化（保留原理、参数化数字）：ghost_test 三档（栅栏已按模型参数化，是范例）；相邻 Z 的 ΔR1<0.005 无判别力（0.005 来自 79% 空洞 MOF）；λ 近吸收边元素看轻一档（原理普适，0.68883/Zr 被硬编码）；负积分＝模型偏轻（机制普适，动作序列案例化）。
- 案例经验过硬（须降级为"某类体系的经验"）："R1 0.05–0.10 可接受"；"掩膜去留只看 ΔR1 不看电子数"（与同卡报告义务冲突）；"客体只能作为片段在掩膜前检验"（工具门限的产物）；"吸收校正与截断纪律 > 联合积分"（对并孪晶方向相反）；"交付前每个片段必须与主片段成键"（共晶/盐天然不成立）。

---

## 3. 专家知识五大领域 × CrystalPilot 对照 × 启发

每节三段：**专家怎么做**（外部一手来源，数字一律是证据锚点）→ **CrystalPilot 现状** → **启发**（按四层分配：确定性检查 / 工具 verdict 证据文本 / 技能卡 / 留白给判断）。

### 3.1 数据还原与厂家管线

**专家怎么做。**
- **Rint 不是质量指标。** Bruker SADABS 手册（v2.03）原话：Rint "is a very poor guide to data quality"，可被过拟合的缩放/吸收模型（放松逐帧标度约束、无吸收时用高阶球谐）或过度剔除反射人为压低；更好的指标是最终 R1、键长/键角 s.u.、同反射数下的差图峰/洞、全分辨率与全强度范围内 χ²≈1。误差模型 su²(Ic)=k[σ²(Ic)+(g⟨Ic⟩)²] 的 g 应逐数据集精修（依赖晶体质量与探测器）；SAINT 的 instrument error factor 应设 0；球谐阶数按吸收强度 4/1（弱）、6/3（中）、8/5（强）；离群剔除必须在吸收模型精修之后（"do NOT use Filter"）；|E²−1| 对分辨率的曲线是**还原阶段就该看的结构级诊断**：整体偏低→孪晶，整体偏高→赝平移，高角骤变→积分问题。
- **吸收校正方法由 μ·t 决定，且 IUCr 已把它写成确定性规则。** checkCIF 过程 ABSTM_02［§7 记：首次抓取成功、复核时 IUCr 返回 403，未获独立二次确认，实现前请再核一遍原页］：声明非数值校正（multi-scan/psi-scan/empirical）而 μ·t_mid>3.0 时报 A 级，面指标数值/解析校正"considered to be compulsory"但允许解释；由晶体尺寸与 μ 算出期望透过率范围与报告值比对；声明 'none' 而期望 Tmax/Tmin 比超过 1.30/1.20/1.10 时报 A/B/C；响应程序是"先核实晶体尺寸（应可量到 0.01 mm）再质疑校正本身"，multi-scan 的实验 Tmin 远小于预测即过校正信号。**这条即使细节有出入，方向是稳的**：抽验在真实 checkCIF 报告里查到实际运行的措辞 "The ratio of expected to reported Tmax/Tmin (RR) is > 1.10 ... Please check that your absorption correction is appropriate."，说明"按尺寸与 μ 推算期望透过率再与报告值比"这套机制确实在跑。
- **积分与"定稿"分离，人决定的是定稿参数。** CrysAlisPro 手册：积分结果存 *.rrpprof，hkl 由 refinalize 生成，可反复重做而不重积分，此时选 multi-scan（默认）/面指标/球形/无；"IUCr limit" 策略把覆盖度设 98.5%；曝光按目标 I/σ 15 预测（可改）；孪晶定稿的 Full Overlap Threshold 默认 0.8；GRAL 定群在弱数据时手册建议改交互模式；25 帧一批 + AutoChem 实时解；"problematic data sets" 走 "Data reduction with options" 由人决定孪晶成分、背景、离群。
- **分辨率截断是多证据、且宁可晚截。** CCP4 AIMLESS 文档默认 CC1/2 0.2、⟨I/σ⟩ 1.0、information content 0.1，并明说要考虑各向异性；Rmerge 明确不作截断判据（随强度变弱无界增长），Rmeas 优于 Rmerge、Rpim 表精度、CC1/2 有统计界；**警告不要在还原阶段激进截断**：弱高分辨数据对精修有帮助，截数据只让 R 好看不让模型变好，正确流程是积分到更高分辨率、看缩放报告再回截。DIALS 缩放论文（Beilsten-Edmands et al. 2020）：thaumatin 例 CC1/2 0.3 会给 2.1 Å，作者不采纳，因壳层完整度不够，改用"所有壳层 98% 完整"目标。
- **缩放的前提与诊断。** DIALS：缩放前必须已定劳厄群（按对称唯一指标分组），管线顺序固定；误差模型 (a, b) 从 1.0/0.02 起迭代，低系统误差时 a≈1、b≈0.02–0.04，是数据质量诊断；参数越多合并统计越好但会过拟合噪声，故有 free-set（留出 10% 等效组，看 Rmeas work/free 差）；ΔCC1/2 剔除系统性不同的扫描只用于多晶体。AIMLESS 三参数误差模型 σ'²=SdFac²{σ²+SdB⟨I⟩+(SdAdd⟨I⟩)²}，诊断图是归一化误差 vs ⟨I⟩ 应平坦≈1；辐射损伤从 batch 图判（相对 B 因子越来越负、scale 上升、Rmerge 上升、估计分辨率变差）。
- **非贯穿孪晶的还原 SOP（Purdue/Zeller）。** 指标化阶段警示：指标化失败；大晶胞很多预测点无强度；正常晶胞很多强点未指标化；劈裂点；hkl 直方图拟合 <~90%。CELL_NOW 最高 FOM 的胞**不得自动接受**：≥200 帧、I/σ 门降到 ~5、初始整数偏差 0.25，按拟合比例、度规对称、最小胞权衡。**真孪晶律必须是简单操作**（180°、偶尔 90°/120°，绕低指数实/倒易轴或对角线，矩阵单个非对角非零元），其他角度/非整数轴是裂晶或多晶。TWINABS 在 wR2(int)~0.08 接受、>0.2 绝不接受；输出两套文件（HKLF4 主域求解、HKLF5 全域精修）；孪晶采集要更高冗余、半球/全球，且下机前先试解查完整度。
- **数值指引汇总（证据，非门槛）。** Müller 2009：完整度 99–100%、IUCr 最低分辨率 0.84 Å、多重度 >5–7、总 I/σ ≥8–10、Rint <10%、高分辨壳 ⟨I/σ⟩≤2 或 Rint≥0.45 视为噪音、数据/参数比 8（非心）/10（中心）。Spek 2020：采到 Cu 球 0.65 Å⁻¹、完整到 0.6 Å⁻¹；截断在"只剩噪音"处；PLAT023 仅 ⟨I/σ⟩<2 处截断才合理。XPREP 手册：R(sigma)>0.1 表示极弱或处理错。
- **3D-ED。** 运动学精修 R 普遍 15–30%（多次散射），R 高不等于模型差；Jana2020+Dyngo 的动力学精修（Palatinus 2015；Klar et al. 2023 对 12 种化合物运动学/动力学对照，差图噪声最多降四倍，58 颗晶体绝对构型全对）；运动学与动力学、合并与不合并数据的 R 互不可比；Amgen（Org. Lett. 2024）筛选做动力学精修的数据集用完整度>65%、Robs<30%、分辨率<1.1 Å、CC1/2>97%，个别研究的经验，没有社区标准。

**CrystalPilot 现状。** 吸收校正零工具（只能事后读 SADABS .abs / dials.scale 日志）；`scale_and_export` 四参数，误差模型、free-set、离群剔除封闭；CAP 五步硬编码无 refinalize；`estimate_resolution` 用 CC1/2 0.3 / I/σ 2（`tools_frames.py:1693-1711`）；Rint 不入节点；`ingest_vendor_data` 不摄入吸收类型/Tmin/Tmax；|E²−1| 只算一个数（`tools_analysis.py:746-751`），没有对分辨率的曲线；无误差模型诊断；无辐射损伤 batch 图；`set_twin(law='suggest')` 只做度规陪集、无"简单操作"判据；3D-ED 只有一句"引擎用 X 射线表不可比"。r24 的判决（"吸收校正与截断纪律 > 联合积分"）与 ABSTM_02、SADABS 的方向一致，但被写成了一颗晶体的结论。

**启发。**
- 确定性检查：① ABSTM_02 的 μ·t 门与期望透过率比对（IUCr 自己的规则，可逐字实现，`ingest_vendor_data`/`set_experiment` 摄入尺寸与校正类型后自动算）；② 误差模型参数与归一化误差-强度曲线平坦度（DIALS a/b、SADABS g、AIMLESS SdFac/SdB/SdAdd）作为数据质量记录；③ |E²−1| 按分辨率壳层输出并自动标注三种形态；④ 孪晶律"简单操作"判据（矩阵形态 + 角度 + 轴指数）；⑤ 缩放顺序守卫（劳厄群未定不缩放）；⑥ Rint、Rmeas、Rpim、多重度、完整度进节点元数据。
- verdict 文本：Rint 的免责（引 SADABS 原话）；截断的多证据（CC1/2、I/σ、壳层完整度、各向异性）+"先积分到高分辨率、看报告再截"；辐射损伤征兆清单。
- 技能卡：吸收校正选择卡（μ·t、晶体形状、面指标可行性、multi-scan 需要冗余、Tmin/Tmax 核实程序）；孪晶采集与还原卡（Purdue SOP 的通用部分，去掉 Bruker 专名）；3D-ED 卡（运动学 vs 动力学、R 不可比、动力学可定绝对构型）。现有 `model-error-vs-data-error.md` 可升级为"还原对照判决法"的通用卡，把 r24 数字降为例子。
- 工具面：`reduce_with_crysalis` 拆成 integrate / refinalize 两步并暴露 ABSPACK 类型与 Full Overlap Threshold；`scale_and_export` 暴露 model / error_model / outlier_rejection / free-set；`export_twin_hklf5` 前置简单操作判据；`estimate_resolution` 输出各向异性与壳层完整度。
- 留白：是否重采、是否接受次优晶胞、孪晶数据用主域还是全域，判断。

### 3.2 空间群判定与结构求解

**专家怎么做。**
- **判据自带失效条件（XPREP 手册）。** ⟨|E²−1|⟩ 0.968/0.736，且手册明确它在三种情形不可靠：重原子（尤其特殊位置）、某投影反射太少、孪晶（真实中心对称也给非心分布）。CFOM<1 通常决定性、>10 很可能错，但手册说这不是硬规则："不清晰时为每个候选群准备文件、全部跑求解再选"，非心群解出后**必须**查是否符合中心对称超群（独立原子坐标间的意外关系、最小二乘大相关）。R(int) 判劳厄群的价值取决于等效反射数；消光反射集 ⟨I/σ⟩ 应≈1 或更小，反射少时消光判定"relatively unreliable"。roe119 实例的错晶系识别靠五条独立线索（角偏 0.04°、E 心而消光只允许非心、额外消光、Patterson 无法解释、两种方法都失败）。
- **两条独立路线。** SHELXT（Sheldrick 2015）只读劳厄群不读空间群，**不用系统消光**，在 P1 解相后按相位一致性搜索空间群与原点；α0<0.3 判中心对称；默认找到合理中心对称解且无重于 Sc 的元素就停；元素按 0.7 Å 球积分电子密度分配（不是峰高，因为 ADP 不同），以 1.25–1.65 Å 峰平均 Z=6 定标；几千结构测试：空间群正确约 97%，全原子正确约一半，最常见错是 C/N；失效：严重无序、孪晶、中子；赝对称/重原子子结构可在多个群得同一结构，此时最高对称中心对称群几乎总对，Flack≈0.5 常是漏反演心。Palatinus & van der Lee 2008（SUPERFLIP）：P1 解后从相位/密度导对称，与强度统计/消光完全独立；对称一致因子正确操作多 <0.1、几乎总 <0.2，错误 >0.5；心化 R(m)>0.98；赝对称是自动阈值选群的失效模式（重原子高对称、配体低 → 选高群 → 精修表现为"无序"）；**消光法在 ⟨I/σ⟩ 低于约 10 时开始失灵**（flo19 例给出不存在的衍射符号）；E 统计 + CSD 频率先验会错判心/非心（Pna2₁ 反演孪晶 Flack 0.405 例）。结论："两条独立路线不一致时才需要人"。
- **孪晶警示清单（Herbst-Irmer，与 SHELXL 手册一致）。** 度规对称 > 劳厄对称；高劳厄群 Rint 仅略高于低者；同化合物不同晶体在高劳厄群 Rint 差异大；⟨|E²−1|⟩ ≪ 0.736；表观三方/六方；不可能或异常消光；数据正常却解不出；Patterson 物理不可能。非贯穿：异常长轴伴大量消光、胞精修困难、劈裂点、K=⟨Fo²⟩/⟨Fc²⟩ 对弱反射系统性偏高、"most disagreeable" 全部 Fo≫Fc、无法解释的残余密度。XPREP [M]：BASF 0.05–0.45 部分并孪、≈0.5 + 低 E 完全并孪。**"孪晶精修只需两条指令一个参数，应先于耗时的无序解释尝试。"** 求解：SHELXS 在正确群里对完全孪晶也常成功，SHELXT 对孪晶数据常失败，SHELXD 可显式给 TWIN/BASF。
- **R 因子不能决定对称性（Clegg 2019；Müller 2009）。** 低对称模型参数多必然 R 低；Clegg 三例：伪单斜三斜（P-1 Z'=2 R1 0.058 vs P2₁/n 孪晶 0.065，"错"的模型差图更干净）靠劳厄 Rint、方差分析 K 值、孪晶建模一起权衡；有序 P2₁ Z'=2 vs 无序 P2₁/n 靠几何畸变、约束强度、非晶体学证据（合成、光谱）；Co 复合物 checkCIF 无显著警报却错两次，线索是环碳椭球垂直环面拉长但低于 "may be split" 阈值。ADDSYM 三例都推荐错的高对称，SHELXT 2019 版两例选对（倒易空间相位检验 vs 直接空间几何搜索）。Müller 的 P1 vs P-1 例：R1 0.0636 vs 0.0635 几乎相同，但 P1 的 24 个芳香 C–C 散在 1.324–1.465 Å，P-1 的 12 个只在 1.382–1.398 Å。
- **错群的类型学与规模（Marsh；Spek）。** CSD 中 Cc 约 10% 错且 1997→2004 不降；修正约 80% 是补反演中心（键长键角"通常发生大变化"），其余是漏心化（几何基本无害）；P1 近 1300 条中 279 错。Marsh & Spek 2001：自动标记 144 条只有 50 条真（约 1/3），**ADDSYM 输出是候选列表不是裁决**。Spek 2009：初解常只在真群的子群成功；漏劳厄群相对无害，漏反演心严重且会被约束掩盖；ADDSYM 假阳性例（P-1 正确而建议 C2/m：t-Bu ADP 偏高、变换后角偏 90° 达 0.3°、且高温可能真是 C2/m）；默认容差 1.0°/0.25 Å/0.45 Å/20% 不符；需要原子分辨率数据。
- **元素/模型诊断树（Müller，元素无关）。** 所有键都长或都短 → 数据/晶胞；许多键双向散 → 错群（漏反演心）；少数键偏 → 元素或无序；椭球太小 = 比模型重，太大 = 比模型轻或无序。Raymond & Girolami 2023：原子序数差 <~10% 难分（N/O 15% 可分、W/Au 7% 不可）；ADP 被热运动、无序、占有率混淆 → 最终靠化学；大量轻原子精修成恰好 50:50 无序 → 怀疑漏超胞、回看原始图像弱反射。System S 文档：EXOR 按峰高分 C/N/O 不可靠（外围 O 像 C、中心 C 像 O）。

**CrystalPilot 现状。** `screen_space_groups` 消光三态 + E 统计已做得好（`refine/absence_test.py`），且 `laue_group='all'` + merge_stats；但只有一条路线，`run_shelxt` 的 α0/空间群搜索结果没有与消光/E 统计做结构化交叉核对，`solve_superflip` 的对称派生未暴露。`check_symmetry` 是 ADDSYM 式（0.35 Å、0.975），描述已写"建议须验证"，但结果未分"漏反演心/漏心化"两级风险。孪晶警示清单在 `framework-twin-pseudosymmetry-alarm.md` 里有，但 K-vs-Fc² 方差分析与 "most disagreeable reflections" 没有从 SHELXL .lst 结构化回读（`tools_shelxl.py` 只读 disagreeable **restraints**）；|E²−1| 无失效条件标注。`framework-solve-ladder.md:67-73` 的"R1<0.25 不回阶梯"与专家"先试孪晶两条指令"、"R 不能决定对称"直接冲突。Marsh 类型学、非标准设置转换、Z'>1 判定都薄。

**启发。**
- 确定性检查：① 劳厄群 Rint 表附等效反射数与置信；② |E²−1| 输出时自动检测三条失效条件（重原子/特殊位置、投影反射数、孪晶信号）并写进 verdict；③ **两条独立路线交叉核对**：消光+E 统计 vs SHELXT α0/空间群搜索（或 superflip 对称一致因子），一致→自动，不一致→列出分歧交 agent；④ 弱数据（⟨I/σ⟩ 低）时消光判据自动降权（已有 undecidable，加"⟨I/σ⟩<~10 时消光法失灵"的注记）；⑤ ADDSYM 结果分两级风险并附"需反射数据核实"；⑥ 从 .lst 回读 K 对弱反射、most disagreeable 全 Fo≫Fc 的孪晶签名；⑦ 等价键长离散度检验（同类键 range/mean）作为漏反演心签名；⑧ 50:50 无序比例异常高 → 超胞旗标。
- verdict 文本："R 不能决定高低对称，低对称参数多必然 R 低"；"错的模型可能差图更干净"；"Z 差 <10% 的元素 X 射线单独不可分"。
- 技能卡：错群类型学卡（Cc/C2/c、P1/P-1、Pna2₁/Pnam、伪单斜三斜，各自签名与后果）；求解方法选择卡按体系与数据（轻原子 / 重原子 / 大弱 / 孪晶：SHELXS、SHELXT、SHELXD+TWIN、Patterson、电荷翻转），把 `framework-solve-ladder.md` 的框架专有部分降为例子；"中心+无序 vs 非心+有序"裁决卡（几何畸变、约束强度、非晶体学证据）。
- 修正矛盾：把"R1<0.25 不回阶梯"改成"回头查群的触发签名清单"（等价键长离散、Flack≈0.5、ADDSYM 命中、无序恰好 50:50、K 异常）。
- 留白：赝对称下两群取舍、Z'>1 是否真实、是否回帧重看弱反射，判断。

### 3.3 精修决策：约束、无序、氢、权重、消光、绝对构型、溶剂、孪晶

**专家怎么做。**
- **SHELXL 手册的可机检规则。** WGHT 保持默认 0.1 直到所有原子找到、精修基本完成再采纳建议值；RIGU（0.004）是"硬"约束默认少改，SIMU（0.04/0.08）、ISOR（0.1/0.2）是"粗近似"须大 esd，**SIMU 明确不推荐小分子与自由旋转离子（C₅H₅、BF₄）**，ISOR 是最后手段；EXTI 在所有非氢找到后才引入，EXTI 与 SWAT 在方差分析里症状相同、不能同时精修、由用户按结构类型选；TWIN+HKLF4 仅倒易格子可重合时用，否则 HKLF5；HKLF5 强制 MERG 0 且不能与 TWIN 合用；BASF 可能漂负；DEFS maxsof 1.1 同时精修溶剂水占有率与 U 是"popular but suspect"；damping 人为压小 esd → 末轮去 damping；自动加 H 需人工核实。
- **无序建模流程（Müller）。** 无序从模型诊断（病态椭球、相邻残峰/洞），大 ADP 不足以证明部分占有；拆位前先各向同性（各向异性会吸收无序藏住第二位）；PART 1/2/0 原子同序；占有率经自由变量 21/-21 合一，起点 ~0.6 或按 Q 峰高估；**接受检验是确定性的**：自由变量 s.u. 必须远小于其值，精修到 0.95(10) 即撤销；"as there is no disorder refinement without restraints, you should use SAME (or the respective SADI instructions) to make the 1,2- and 1,3-distances equivalent"；SAME 有两条独立忠告，**位置上**要从无序原子往前数两个原子开始写（"start two atoms earlier"，否则抓不全 1,3-距离），**顺序上**两组分原子次序必须严格一致（"If the atoms in the two components ... are not precisely in the same order, the restraints generated by the SAME command may do more harm than good"）；残余密度是化学判断不是峰高阈值：可来自吸收、傅立叶截断、辐射损伤（堆在特殊位置）、重原子邻近正常伪影。
- **绝对构型（Parsons, Flack & Wagner 2013；Sheldrick 2015）。** x 的 s.u. 应 <0.1 才可下结论，0.2(8) 什么都说明不了；全矩阵 TWIN/BASF 的 s.u. 在弱反常散射下悲观约 5.5 倍，商法/差法/Hooft 给现实的 s.u.；Friedif ≥80 无问题，<~12 困难；后精修法只在有完整 Friedel 对时合法；中间 Flack 在"反演孪晶 vs 错手"之间有歧义，须显式 TWIN 精修裁决（Herbst-Irmer 四域精修例）。
- **溶剂（Spek 2015；Olex2 帮助；Spek 2020）。** 原子模型"generally to be preferred"，SQUEEZE 用于连续通道、高对称位上的不对称分子、未知混合物；**前提**：主体模型完整（含 H 与主体无序、无未解释残余密度）、数据完整可靠、最好低温；低角缺失/消光离群破坏电子数但不破坏溶剂 Fcalc；报告义务：每胞空腔数、体积、电子数、推定溶剂进 formula；孪晶 SQUEEZE 只经 LIST 8 的 fcf；抗衡离子不得 squeeze；探针 1.2 Å、最小空腔 7.2 Å³；Olex2：掩膜只在"用原子位点建模既不可能也不合理"时。Spek 2020：收敛的小分子差图应近乎无特征（±0.5 e/Å³ 内），C/N/O 旁 ~1 Å 正峰 = 漏 H，算得 H 位负密度 = H 放错；Hirshfeld 刚性键检验能抓元素错配（曾揭穿故意改元素的发表结构）。
- **客体过度解读的可复现检验（Raymond & Girolami 2023）。** 高对称多孔框架里特殊位置的密度必须带该位对称，孔内客体几乎总是无序、持续被过度解读；BCDD@BUT-17 反驳给出两个检验：把客体 Uiso 固定为骨架值精修占有率；等。
- **3D-ED 精修。** 运动学 R 高属正常；动力学精修可定绝对构型（Klar 2023）；两类 R 不可比。

**CrystalPilot 现状。** `run_shelxl(mode='adopt_wght')` 与 `set_weights` 已闭环；Parsons 商已从 .lst 回读（`tools_shelxl.py:112-147`），Hooft 与 Friedif 没有；`set_restraints` 拒 SAME/EADP/EXYZ/SUMP；`model_disorder` 只拆二位点、无自由变量 s.u. 接受检验、无"拆前先各向同性"守卫、撤销后 FVAR 残留（pa2 待修）；`add_hydrogens` 无 AFIX 147/148、无受体定向、无 HTAB；EXTI/SWAT/DEFS/DAMP 不可达；掩膜工具（收敛/发散仪表、电子数置信、mask_diagnosis）比 Olex2 更细，但守卫按 Zr₆ 定、义务文案 MOF 口径；`audit_guest_evidence` 三检验与 Raymond & Girolami 同向；`refine` 有 rigid-bond **约束**但没有 Hirshfeld **检验**；无"漏 H 正峰"检测；DISP 自动写（非 Cu/Mo/Ag 波长）是超过多数实验室的做法。

**启发。**
- 确定性检查：① 无序模型接受检验（自由变量 s.u. vs 值，Müller 的 0.95(10) 判例）；② 拆位前各向同性守卫；③ WGHT 采纳时机守卫（未找全原子/存在未解释残峰时拒绝 adopt_wght，给出理由）；④ EXTI/SWAT 互斥与"非氢找全后"守卫；⑤ Flack 判定力：Friedif 由组成与波长算、Friedel 对覆盖率、s.u.<0.1 三件套；⑥ Hirshfeld 刚性键检验进 `validate_structure`；⑦ C/N/O 旁 ~1 Å 正峰的"漏 H"检测与算得 H 位负密度检测；⑧ SQUEEZE 前提检查（主体完整、低角数据存在、抗衡离子不在空腔内）；⑨ damping 末轮清零、DEFS maxsof>1 报警。
- verdict 文本：残余密度的来源清单（吸收、截断、辐射损伤、重原子伪影、无序、漏 H、错元素、客体）而不是默认"孔内客体"；"SIMU 对小分子不推荐"；"运动学 R 高是 3D-ED 常态"。
- 工具面：`run_shelxl` 开受审计的 `extra_cards` 通道（白名单 EXTI/SWAT/EADP/EXYZ/SUMP/SAME/RESI/AFIX 6x/DAMP/STIR/OMIT/MERG/DEFS/HTAB/MORE/LIST 8，必填 reason，与 `set_resolution_limit` 同模式）；`set_restraints` 加 SAME/EADP/EXYZ/SUMP；`model_disorder` 支持多组分、自动生成 SAME/SIMU/RIGU 建议、报告自由变量值与 s.u.、撤销时清 FVAR；`add_hydrogens` 加 AFIX 147/148 旋转搜索、受体定向、HTAB 输出；新工具 `absolute_structure`（Friedif、Parsons/Hooft、四域 TWIN 检验）；长期：接 Jana2020 做动力学精修与调制结构（vendor 目录已有安装包）。
- 技能卡：无序建模卡（Müller 流程，体系无关，把 `framework-restraint-idioms.md` 的 NPD 顺序改为证据式）；氢原子卡（O–H/N–H 定向、水 vs 氢氧根、金属氢化物、差图检验）；绝对构型卡升级（Friedif、后精修法、中间值裁决）；溶剂卡按体系分流（分子晶体先建模、通道型才掩膜、抗衡离子红线）；权重/消光卡。
- 留白：是否 SQUEEZE、何时停止精修、中心+无序 vs 非心+有序，判断。

### 3.4 验证与发表

**专家怎么做。**
- **checkCIF 的语义（Spek 2009/2020）。** ALERT 不必然是错误，checkCIF 刻意不给 publish/reject 判决；A 级须解决或科学解释（VRF），低级别组合也可能指向严重问题，G 级不可自动忽略；判据"很多是经验性、基于传统"，存在过严/过松权衡；"无序-中心对称 vs 有序-非中心"只有专家能裁决；四级质量分类 Class I–IV，验证首要目标是 **Class IV（元素错、H 太多或太少）永不见刊**；识别 Class IV 靠椭球异常与 Hirshfeld 检验；基于反射数据的验证能做 CIF 做不到的事：漏判孪晶、Flack vs Hooft 比对、H 差图正负峰。
- **数值只在 IUCr 原生过程里分级。** RFACG01 R1 >0.20/0.15/0.10 为 A/B/C（抽验从真实 checkCIF 报告逐字确认了 >0.10→C、>0.15→B："RFACG01_ALERT_3_C The value of the R factor is > 0.10"；A 级 0.20 与 "<0.07 normally expected" 未取得逐字确证）；RINTA01 Rint >0.20/0.15/0.10、GOODF01 GooF 超出 0.40–6.00/0.60–4.00/0.80–2.00［单次抓取，未复核］；PLAT027/029 完整到 0.6 Å⁻¹ 是 Acta 发表要求；PLAT023 截断只在 ⟨I/σ⟩<2 处；PLAT601/602：~40 Å³ 容一个水、THF 100–200 Å³［检索转述级证据］，未报告的显著空腔至少要讨论，太大的空腔可能是漏对称（P1 vs P-1）［未复核］；PLAT220/241/242 把异常 Ueq 当元素错配信号，PLAT230–234 Hirshfeld 抓错散射类型（Ag vs Br）；PLAT110–116 ADDSYM 故意不分元素以抓元素错配。
  **工程含义不受这些出入影响**：这些数字进系统的方式应当是 `run_checkcif` 直接读 PLATON/IUCr 的实际输出，而不是我们在代码里复写一份阈值表，复写就等于把别人的版本化规则冻结成我们的常数。
- **期刊要求（ACS 2025）。** checkCIF PDF 随投稿，A/B 必须解决或解释；结构因子沉积 CCDC，且 **原始、未合并、未截断、未掩膜的 hkl 嵌入 CIF**；作者自己负责查语法、数值自洽、**可能的更高对称**；非氢约束与"对结构因子的调整"（含 SQUEEZE/掩膜）必须详述并说明理由；披露清单：Z'>1、溶剂、特殊对称、无序建模、相似配体（CO/NO/CN）如何区分、H 处理。
- **正确性与 R（Raymond & Girolami；Harlow）。** R 至多用于两个候选模型排序，不能作为独立正确性判据；错模型可无警报、对结构可多警报。

**CrystalPilot 现状。** `run_checkcif` + 95 码知识库 + 逐条脚手架、`finalize_delivery` 的 A 级 waive 都在正轨；写出的 CIF 嵌入反射数据；但评分器把 R1≤0.10 做成绝对悬崖（pa1 正确的 0.1057 判 below_bar）、置信分 R1 分段权重拍定；Hirshfeld、Flack-vs-Hooft、H 差图检验缺；ACS 披露清单只有部分进 `write_outputs` 义务；`benchmark/grade.py` 自陈 12/21 参考 R1>0.12，评分口径本身在新类型上不可信。

**启发。**
- 交付门与评分器：R1 不做绝对门，改为 Class I–IV + 体系类型的期望（RFACG01 的 A/B/C 与 "<0.07 expected" 作为通用锚点，MOF 的 0.10 只是该类的经验）；**Class IV 三项（元素、H 计数、电荷平衡）做硬门**；ACS 披露清单做交付模板并要求逐项作答；VRF 自动生成脚手架、理由必须由 agent 写。
- 确定性检查：Hirshfeld；H 差图正负峰；Flack vs Hooft；空腔过大 → 漏对称提示；"未报告空腔"检测。
- verdict 文本："无 A/B ≠ 结构正确"；"R 只用于排序两个模型"。
- 评分器：参考质量自检已做（`_self_declared_caveat`），下一步是评分维度按体系类型切换，与 `CRITERIA_BY_SYSTEM_TYPE` 同构。

### 3.5 自动化、专家系统与 AI 代理：前人怎么失败、怎么设计

**前人的经验。**
- **PLATON System S（Spek）**："supervisor with a crystallographic degree and an organized memory"——每个尝试过的晶格类型一级分支、每个空间群二级分支，可比较可回退；全自动 NQA/Silent 模式**只对无麻烦结构**，明确排除无序与孪晶；NQA 失败的回退是"换空间群 + 换求解方法"；各向异性精修开始时自动跑 ADDSYM；方法选择启发：SHELXS 轻原子、DIRDIF 重原子（CONTENTS 错则败）、SIR97 大而弱数据。
- **xia2（Winter 2010；Winter, Lobley & Prince 2013 "Decision making in xia2"）**：决策点清单（选帧、试指标化解、参数、分辨率、点群、缩放模型）；**经验只能实证不能从第一原理推导**（用 JCSG 大样本校准）；**反馈架构**：积分/缩放阶段的信息可以推翻早期决策，框架支持假设检验与回溯；约束晶格判据：加 Bravais 约束后 rms 偏差不应明显变差。
- **AutoChem（Rigaku/OlexSys）**：多程序并试（SHELXT、SIR、Patterson、电荷翻转）取最优；25 帧实时解；手册坦承**无法处理显著无序与孪晶分解**；Olex2 可回看每一步并从任一步接管。
- **SHELXT**：几千结构上空间群 97%、全原子约 50%，最常见错 C/N。
- **Clegg 2019**："无需晶体学专业知识"这个卖点本身就是失效模式，没人看所以问题不被发现；自动化常错过孪晶、无序、调制。**Müller 2009**：半自动只对常规结构有效，经验驱动的决策清单（选哪颗晶体、赝对称下两群取舍、无序是否值得建模、约束松紧）不是规则能替代的。
- **NeuDiff Agent（ORNL, J. Appl. Cryst. 2026）**：最接近 CrystalPilot 的已发表系统：LLM 被限制在 LangGraph 状态机与白名单工具里，每个状态转移有**确定性的验证门**；检查分四类（硬边界/schema、跨输入一致性、工具执行验证、发表验证）；工具执行验证解析 Mantid/SHELXL 日志找不收敛与不物理 ADP，然后**建议**（不是执行）修正；知识两层：系统上下文里的"仪器知识 schema"（几何、角度范围、参数边界）+ 版本化不可变的 RAG 知识库（含 checkCIF 指南），用户数据永不进知识库；每步人授权。局限：一个数据集、从已知 X 射线 CIF 起步、无从头定群/求解、A 级警报全是元数据。
- **其他**：Rongzai（LLM + 知识库 + GSAS-II，Rietveld，已在 CSNS 部署）；guillemot（Pydantic AI + TOPAS）；agentic X-ray scientist（Nature MI 2026，MCP 驱动束线对准）；CrystalX/RefrActor（端到端深度学习，与 Olex2/AutoChem ac7 比较）。**未见任何已发表的 LLM 代理自主驱动 Olex2/SHELXL 完成小分子 X 射线从头解析**: CrystalPilot 的自主程度超过现有文献，代价是没有可抄的验证门设计。

**CrystalPilot 对照。** 节点树 ≈ System S 的 organized memory（做对了）；`branch/checkout/compare_nodes` 支持回溯，但没有 xia2 式的**决策记录 + 可推翻条件 + 反馈触发**；验证门主要在评分器侧（导师面）而非 agent 面；知识层没有 NeuDiff 的两层分离（仪器/数据 schema 与技能卡混在 AGENTS 模板里）、没有版本化，`save_skill` 会把单次战役经验直接写进知识层；评测集单一类目；失败回退策略（换群/换法/换还原）散在卡里，没有显式的"回退表"。

**启发。**
- 借 xia2：每个决策点写**决策记录**（候选、证据、选择、可推翻条件），后期签名命中时自动回到该决策点；经验校准必须用大样本，把 `benchmark/data_ext`（101 例）、`data_ext2`、`data_frames` 建成"决策校准集"。
- 借 System S：显式回退表（求解失败 → 换群/换法/换分辨率/换还原）；各向异性开始时自动跑 `check_symmetry` 并记录。
- 借 NeuDiff：验证门分四类并写成表（哪些是硬边界、哪些是一致性、哪些解析日志、哪些是发表门）；知识分两层，项目上下文 schema（波长、仪器、组成、参数边界，由 `set_experiment` 类型化）与版本化技能库；`save_skill` 写入的经验必须带来源、体系类型、"泛化审查"标记。
- 借 Clegg/Müller：留白清单写进 AGENTS，哪些决策系统明知不该规则化。
- 评测：tune-on-one / verify-on-other 成为纪律；每次改规则跑"另一类型"回归。

---

## 4. 知识编码原则：怎么写才不过拟合

1. **四层分配。** 确定性检查 = 物理/对称/程序语义决定的东西（μ·t 门、缩放顺序、HKLF5 与 TWIN 互斥、自由变量 s.u. 检验、Hirshfeld、Friedel 对覆盖、中心对称群无反常散射）；verdict 证据文本 = 判据 + 失效条件 + 分辨极限（`GHOST_CRITERION`、`ELEMENT_RULE` 已是范例）；技能卡 = 决策程序与类型学（错群类型、无序流程、方法选择），按体系类型分层；留白 = 专家也只能靠经验的决策（赝对称两群取舍、是否值得建模无序、是否 SQUEEZE、何时停）。
2. **每条判据必须携带失效条件。** XPREP 对 |E²−1| 列了三条失效条件，ghost_test 有灵敏度地板，把这做成模板：任何数值判据的输出都带 "informative: true/false + why"。
3. **数字从当前数据/模型推算，不写案例常数。** μ·t 由尺寸与组成算；Friedif 由组成与波长算；期望电子数由 occ×Z 算；ΔR1 判别力由灵敏度地板算；0.68883/Zr、0.125/Br、0.25、"降 0.1" 这类数字只能进 expert-cases 的例子。
4. **按体系类型分层。** 引擎已有 framework/molecular/salt；知识层与守卫（掩膜配位球、就绪判定、置信分权重、质量期望）都要随类型切换，并补 organometallic 与 inorganic；每类至少一张"该类特有问题"卡（分子晶体：多晶型、共晶/盐判定、柔性侧链、H 键网络；有机金属：M–C、η 环、桥氢、羰基；无机：混占位、超结构、调制）。
5. **证据式语言模板。** "X 通常意味着 A；但在 B 情形下会 C；用 D 分辨"；禁止"低于 X 就做 Y"；免责语随节走，`read_skill(section=)` 返回时自动附卡首的免责表头；`list_skills` 检索含正文。
6. **举例与规则分离。** 战役复盘的数字进 `knowledge/expert-cases`，规则进 `knowledge/skills`；战役后补写的每一段都过一次"泛化审查"：换成小分子/有机金属/无机盐是否仍成立？不成立就限定 scope。
7. **两条独立路线交叉核对**（空间群：消光+E 统计 vs 相位对称；绝对构型：Flack vs Hooft；精修：两引擎），一致自动通过，不一致才升级为判断，并把分歧写进决策记录。
8. **R 只用于排序两个候选模型**，不做正确性门；评分器与 AGENTS 同步改。
9. **决策记录 + 可推翻条件**（xia2）：把"后期证据推翻早期决策"做成机制而不是靠 agent 记得。
10. **知识版本化与来源**：技能卡 frontmatter 加 scope（体系类型）、source、generalization_reviewed；`save_skill` 强制填写。
11. **不复写别人的规则表。** checkCIF 的分级、PLATON 的空腔校准、SHELXL 的默认 s.u.、DIALS 的默认判据，这些是**别人版本化维护**的规则，应当由 `run_checkcif` / 引擎输出直接读回，而不是在我们代码里复写一份常数表。复写就等于把外部规则冻结在我们某一天的理解上；本次调研自己就撞到这一点：几条 IUCr 数值在复核时因页面 403 无法二次确认（§7），如果这些数字被硬写进判据，出错时既不会有人发现、也没有单一位置可修。同理，`_MX_TYPICAL`、`METAL_PROFILES` 这类**我们自己维护**的表必须标注来源与适用范围，并在缺表时显式说"未检查"而不是默认通过。
12. **判据是单向的：异常指示问题，正常不构成许可。**（第二轮新增，依据见 §8.1）Watkin *"If a structure 'looks wrong', it probably is wrong. The converse is not necessarily true."*；Linden *"A clean validation report does not necessarily mean that all is in order."*；Xtriage *"Large values can indicate twinning, but small values do not necessarily exclude it."*：三份独立来源给出同一个逻辑形状。**实现上的后果**：这类指标只能用来**触发怀疑与升级**，不能用来**发放通过许可**；当一个判据没有报异常时，正确的输出是"该检查未发现异常"，而不是"该项通过"。当前 `workbench/agents_md.py:305-309` 的零免责质量标尺、以及"R1 < 0.25 即禁止回头查群"这类规则，正是把单向证据当成了双向许可。
13. **偏离要报方向，不只报幅度。**（第二轮新增，依据见 §8.4(c)）⟨I²⟩/⟨I⟩² 显著低于 2.0 指向孪晶、显著高于 2.0 指向赝平移，**符号本身是诊断信息**。任何只输出"偏离理想值 X"而不给方向的判据，都丢掉了一半信息。
14. **能力边界要显式建模，不能只在失败后归因。**（第二轮新增，依据见 §8.3）直接法的 1.2 Å 原子分辨率门槛（有重原子时放松）、BVS 不适用于有机化合物、checkCIF 对非公度与电子衍射结构失效、反演孪晶在衍射图上不可见，这些都是**方法本身的已知边界**。系统应当在进入某条路径**之前**知道它在当前样品上是否适用，而不是失败之后才解释。

---

## 5. 优先级路线图

**P0（文本与小改，一周内）**
- 根目录 `AGENTS.md` 同步到 v32 或改成指针（现在教的是被删除的 CLI 后路）。
- `agents_md.py:305-309` 质量标尺改为按体系的证据式表述（RFACG01 锚点 + "数据质量决定 R 下限"），删除"0.05–0.10 对多孔 MOF 可接受"作为通用标尺。
- 删 `framework-solve-ladder.md:67-73` 的 R1<0.25 禁令，改为"回头查群的触发签名清单"。
- 现有 `mof-*` / `framework-*` 卡加 scope 字段；新建 molecular / salt / organometallic 三张卡骨架（先把 §3 里体系无关的专家规程放进去）。
- `list_skills` 检索含正文；`read_skill(section=)` 附免责表头；expert-cases 与 skills 分离并加 generalization_reviewed 标记。

**P1（工具面，2–4 周）**
- `chem/knowledge.py` 补全 MetalProfile（碱/碱土、铂族、Au/Hg、Sn/Sb/Bi、Nb/Ta/Re、U/Th），`connectivity.py:583` 的 "prof is None → plausible" 改成显式 "not checked" 警报；`connectivity.py:156` M–C 上限改元素相关窗口；η 环识别扩到含杂原子环与 η²/η⁴。
- `model_tools.py` interpret_peaks 补无金属分支与 N 指认；chem_hint 补有机/氢键/卤素提示。
- `run_shelxl` 受审计的 `extra_cards` 白名单通道；`set_restraints` 加 SAME/EADP/EXYZ/SUMP；`model_disorder` 多组分 + 自由变量 s.u. 检验 + 拆前各向同性守卫 + 撤销清 FVAR；`add_hydrogens` AFIX 147/148 + 受体定向 + HTAB。
- 新工具/检查：ABSTM_02 式吸收门；|E²−1| 按壳层；两路线空间群交叉核对；ADDSYM 两级风险；孪晶签名（K、most disagreeable、简单操作律）；Hirshfeld；漏 H 差图检测；`absolute_structure`（Friedif + Parsons/Hooft + 四域 TWIN 检验）；无序接受检验。
- 掩膜守卫、就绪判定、置信分、交付义务全部随 `system_type` 切换。
- 决策记录与可推翻条件（先做空间群、掩膜、元素三个决策点）。
- 评分器：R1 悬崖改 Class + 体系期望；Class IV 三项硬门；ACS 披露清单进交付模板。

**P2（数据还原与新模态，1–2 月）**
- `scale_and_export` 暴露缩放模型/误差模型/离群/free-set；`reduce_with_crysalis` 拆 integrate/refinalize 并暴露 ABSPACK 类型；辐射损伤 batch 诊断；Rint/Rmeas/Rpim 进节点。
- 3D-ED：电子散射因子 + Jana2020 动力学精修通道；调制结构（Jana2020）。

**泛化验证计划（与 P1 并行，不等工具做完）**

已有数据足够建一张"类型矩阵"，每类至少一格，参考不进 agent 面。`benchmark/data_ext2/README.md` 自述这批的用途正是"stress the three CrystalPilot entry stages beyond data_ext"，其中孪晶四例"spanning the whole twin phenomenology"，o-nitroaniline 帧集明写 "enables tune-on-one / verify-on-the-other twin-rescue experiments"——**这些实验一次都没做过**。

| 考什么 | 数据 | 预期暴露的问题 |
|---|---|---|
| 手性绝对构型（真判题） | `data_ext2/org_hsl_cod2241460`（手性纯有机 Sohncke 群） | Flack 判定力默认先验被校准到"通常没用"；Friedif/商法缺工具 |
| 两组分无序（真拆位） | `data_ext2/orgdis_dbu_cod2241572`（DBU 有机盐） | `model_disorder` 二位点上限、无自由变量 s.u. 检验、撤销残留 FVAR |
| 无金属起模 | `data_frames` 八氟萘:酞嗪共晶（同步辐射） | `interpret_peaks` 全判 C、N 永不指认、`chem_hint` 静默 |
| 盐/反离子记账 | `data_frames` 4-氨基吡啶盐酸盐 | `classify_system` 的 salt 分支、碎片签名精确匹配 |
| 无机重元素 + 非常规波长 | `data_frames` AsBr₃（Ag Kα 0.56 Å） | 无 MetalProfile 时 CN 静默通过；DISP 路径；`aniso_heavy` 不选 Br |
| 孪晶陷阱（CIF 沉默） | `data_ext2/twintrap_nm_cod2229074` | 孪晶警示清单是否真被触发（K、most disagreeable 尚未回读） |
| 显式 TWIN/BASF 弱数据 | `data_ext2/twin_rz5267_iucr`（赝并孪晶 R1~0.10） | 与 p770 非贯穿路线的经验冲突（"别做联合积分/要截断"在这里方向相反） |
| HKLF5 重原子孪晶 | `data_ext2/twin_iodouracil_cod2020129`（BASF 0.389） | HKLF5 下 `optimize_weights` 瘫痪等历史缺口 |
| 孪晶 + 大量无序 | `data_ext2/twindis_hb8035_iucr`（82 个部分占位） | 约束体系上限（SAME/SUMP/EADP 不可达） |
| "数据好时 R 该多低" | `data_ext2/coord_cuox_cod2241944`（Cu 配位聚合物 clean baseline） | 质量标尺的 MOF 宽容度在这里应当收紧 |
| 调制结构（预期失败） | `data_frames` LEF-PG 共晶 | 是否诚实披露"平台不支持超空间"而非硬解 |
| 孪晶帧 tune/verify 对照 | `data_ext2/frames_onitroaniline_twin`（3324 帧，非贯穿 180° 绕 c） | 与 `frames_zn_dpnpp` 构成同一能力的两颗晶体交叉验证 |

纪律：tune-on-one / verify-on-the-other；每次改规则至少跑一格"另一类型"回归；"评分与 agent 冲突先查参考"这条只在参考质量未核实时成立，`data_ext2` 的 9 个参考已用 fcf 重算 R1 复现到 ≤0.002，在这批上不得再用它为 agent 开脱。

---

## 6. 来源清单（外部，英文原文保留）

厂家/软件文档：Bruker AXS SADABS User Manual v2.03 (2002) - https://xray.uky.edu/Resources/manuals/SADABS-manual.pdf ；Bruker SHELXTL Software Reference Manual, XPREP chapter (1997) - https://xray.uky.edu/Resources/manuals/Shelxtl-manual.pdf ；CrysAlisPro User Manual (Agilent/Rigaku OD, rev. 5.2, 2013) - https://www.agilent.com/cs/library/usermanuals/Public/CrysAlis_Pro_User_Manual.pdf ；AutoChem 2.0 User Manual - https://www.agilent.com/cs/library/usermanuals/Public/Autochem_User_Manual.pdf ；Rigaku AutoChem/CrysAlisPro product notes - https://rigaku.com/products/crystallography/x-ray-diffraction/crysalispro ；SHELXL Command List (Univ. Göttingen) - https://shelx.uni-goettingen.de/shelxl_html.php ；Olex2 help refine.md - https://github.com/Olex2/help/blob/master/gui/EN/work/refine.md ；PLATON SYSTEM-S documentation - http://www.platonsoft.nl/platon/pl070000.html ；PLATON ADDSYM - https://www.platonsoft.nl/platon/pl000401.html ；CCP4i2 AIMLESS scaling & merging statistics - https://ccp4i2.gitlab.io/rstdocs/tasks/aimless_pipe/scaling_and_merging.html ；Purdue X-ray facility, "Analysis of crystals twinned by non-merohedry" (Nimthong-Roldan & Zeller, 2016) - https://www.chem.purdue.edu/xray/docs/TwinningUserGuide_09Dec2016.pdf ；IUCr checkCIF ABSTM_02 - https://journals.iucr.org/services/cif/checking/ABSTM_02.html ；IUCr PLATON data validation tests - https://journals.iucr.org/services/cif/checking/platon_tests.html ；ACS "Requirements for Depositing X-Ray Crystallographic Data" (2025) - https://pubsapp.acs.org/paragonplus/submission/acs_cif_authguide.pdf 。

方法学论文：Sheldrick, G. M. (2015). SHELXT – Integrated space-group and crystal-structure determination. Acta Cryst. A71, 3–8 ；Sheldrick, G. M. (2015). Crystal structure refinement with SHELXL. Acta Cryst. C71, 3–8 ；Palatinus, L. & van der Lee, A. (2008). Symmetry determination following structure solution in P1. J. Appl. Cryst. 41, 975–984 ；Parsons, S., Flack, H. D. & Wagner, T. (2013). Use of intensity quotients and differences in absolute structure refinement. Acta Cryst. B69, 249–259 ；Spek, A. L. (2009). Structure validation in chemical crystallography. Acta Cryst. D65, 148–155 ；Spek, A. L. (2015). PLATON SQUEEZE. Acta Cryst. C71, 9–18 ；Spek, A. L. (2020). checkCIF validation ALERTS: what they mean and how to respond. Acta Cryst. E76, 1–11 ；Müller, P. (2009). Practical suggestions for better crystal structures. Crystallogr. Rev. 15, 57–83 - https://web.mit.edu/pmueller/www/own_papers/suggestions.pdf ；Müller, P. Refinement of Disorder with SHELXL (MIT tutorial) - https://web.mit.edu/x-ray/Summer_School_Material/Disorder_Workshop/Disorder_Workshop.pdf ；Herbst-Irmer, R. Twinning in Chemical Crystallography (RECIPROCS 2019) - https://cdifx.univ-rennes.fr/RECIPROCS/Paris2019/pdf/ChemicalCrystallography_RHI.pdf ；Clegg, W. (2019). Some reflections on symmetry: pitfalls of automation. Acta Cryst. E75, 1812–1819 ；Raymond, K. N. & Girolami, G. S. (2023). Pathological crystal structures. Acta Cryst. C79, 445–455 ；Marsh, R. E. (1997/2004/2005) The perils of Cc revisited; Space group Cc: an update; Space group P1: an update. Acta Cryst. B53/B60/B61 ；Marsh & Spek (2001). Acta Cryst. B57, 800–805 ；Harlow, R. L. (1996). Troublesome crystal structures. J. Res. NIST 101, 327 ；Beilsten-Edmands et al. (2020). Scaling diffraction data in the DIALS software package. Acta Cryst. D76, 385–399 ；Winter, G. (2010). xia2: an expert system for macromolecular crystallography data reduction. J. Appl. Cryst. 43, 186–190 ；Winter, Lobley & Prince (2013). Decision making in xia2. Acta Cryst. D69, 1260–1273 - https://www.ncbi.nlm.nih.gov/pmc/articles/PMC3689529/ ；Gildea et al. (2022). xia2.multiplex. Acta Cryst. D78, 752–769 。

3D-ED：Palatinus et al. (2015). Acta Cryst. A71, 235–244 & B71, 740–751 ；Klar et al. (2023). Accurate structure models and absolute configuration determination using dynamical effects in continuous-rotation 3D ED data. Nature Chem. - https://www.nature.com/articles/s41557-023-01186-1 ；Petříček et al. (2023). Jana2020. Z. Kristallogr. 238, 271–282 ；Org. Lett. 2024, 26, 6944 (MicroED absolute stereochemistry, Amgen) - https://pubs.acs.org/doi/10.1021/acs.orglett.4c01865 。

AI/自动化：NeuDiff Agent (ORNL), J. Appl. Cryst. 59 (2026) - https://journals.iucr.org/j/issues/2026/04/00/oz5013/ ；An agentic AI X-ray scientist, Nature Machine Intelligence (2026) - https://www.nature.com/articles/s42256-026-01261-5 ；Rongzai agent (arXiv 2605.13911)；LLM Hackathon 2025 outcomes / guillemot (arXiv 2605.03205)；CrystalX (arXiv 2410.13713)。

---

## 7. 验证状态（如实记录，不要当成已核实的事实来用）

deep-research 的抓取层全部成功（25 份一手来源，每条声明附源文件 verbatim 引语），但三票对抗验证层两次运行都被 API 限流打断（108 个子任务 31 个 429、确认 15 条；重跑 105 个 75 个 429、确认 0 条）。因此我另用两个子代理对**九条最吃重的数字**做了定向抽验（独立重新取源、要求 verbatim 引语）。结果：

| # | 声明 | 结论 | 说明 |
|---|---|---|---|
| 1 | SHELXT 不用系统消光定群；α0<0.3 判中心对称；元素按 0.7 Å 球内积分密度（非峰高）、以 1.25–1.65 Å 峰平均 Z=6 定标；群正确率约 97% | **CONFIRMED** | 五个子点全部逐字吻合（PMC4283466） |
| 2 | Flack 的 su 应 <0.1；常规 TWIN/BASF 的 su 高估约 5.5 倍（reduced χ² 0.031）；Friedif ≳80 基本无问题 | **CONFIRMED** | 0.1 / 0.031 / 5.5 / 80 四个数字精确吻合（PMC3661305） |
| 3 | SHELXL 手册：WGHT 0.1 保持到精修基本完成；SIMU 不推荐小分子与自由旋转离子；EXTI 待非氢找全；EXTI 与 SWAT 不可同时精修；TWIN+HKLF4 仅限倒易格子可重合；HKLF5 强制 MERG 0 且不可配 TWIN | **CONFIRMED** | 六个子点全部逐字吻合 |
| 4 | Marsh：Cc 约 10% 错且 1997→2004 未降；Marsh & Spek 2001 的 C2 普查 1500→144→50 | **CONFIRMED** | Cc 一手页面逐字确认；C2 的 1500/144/50 数字吻合但来自转述（原页 403） |
| 5 | AIMLESS 默认截断 CC1/2 0.2、⟨I/σ⟩ 1.0、information content 0.1；Rmerge 不作截断判据；警告不要在还原阶段过度截断 | **CONFIRMED** | 直接抓取逐字确认，含 "Cutting back the resolution makes your R-factors look better, but is unlikely to improve your model." |
| 6 | Müller 无序教程：无约束不做无序精修；自由变量 0.95(10) 即撤销；拆位前先各向同性；SAME 相关规则 | **PARTIALLY_CONFIRMED** | 前三条逐字确认；**我原先把 SAME 的两条独立忠告接成了因果句，已在 §3.3 改正** |
| 7 | RFACG01 R1 >0.20/0.15/0.10 = A/B/C，"<0.07 normally expected"；RINTA01、GOODF01 分级 | **PARTIALLY_CONFIRMED** | >0.10→C、>0.15→B 从真实 checkCIF 报告逐字确认；A 级 0.20 与 "<0.07" 未确证；RINTA01/GOODF01 未复核 |
| 8 | PLAT601/605 空腔校准 ~40 Å³ 容一个水、THF 100–200 Å³；PLAT602/606 过大空腔提示漏对称 | **PARTIALLY_CONFIRMED** | 体积数字只有检索转述级证据（原页 403）；漏对称那半句完全未复核 |
| 9 | checkCIF ABSTM_02：μ·t_mid>3.0 + 非数值校正 → A 级；面指标"considered to be compulsory"；'none' + 期望 Tmax/Tmin >1.30/1.20/1.10 → A/B/C | **UNVERIFIABLE（首次抓取成功，复核 403）** | 抽验在真实报告里查到 RR>1.10 的实际措辞，机制方向成立；但分级数字与"compulsory"措辞未获二次确认。另注：相邻的 PLAT057 用的是 "would appear to be required"。**实现前必须重核原页** |

**怎么用这张表**：1–5 可以直接作为设计依据；6 的正文已改正；7–9 的**方向**可用（μ·t 决定吸收校正方式、R1/Rint/GooF 有官方分级、空腔体积可折算溶剂），但**具体数字不得硬写进代码**：按本稿 §4 原则 11，这些应由 `run_checkcif` 读 PLATON/IUCr 的实际输出。

（本稿所有内部代码论断，根 AGENTS.md 无版本标记、`connectivity.py:156` 的 2.15 Å、`model_tools.py:162` 的 N 预算死代码、`run_shelxl` 四参数、`tools_skills.py:165-168` 的检索盲区、`mask_tools.py:42-43` 的 2.2/2.7 Å、`validation_tools.py:37` 的体系分流、以及 `benchmark/data_ext2` 的构成，均由主线程逐条对源码与文件核过。）

---

## 8. 第二轮调研（第 11–18 章）带来的系统含义

第二轮按 `workdir/knowledge-gap-register.md` 逐条补缺。本节只写**对系统设计有直接后果**的部分；知识本身见 `docs/KNOWLEDGE-SCXRD-expert-practice.md` 第二部分。

> **引用约定**：本节里形如 §11.x–§18.x 的编号指**知识库文档**的小节；指本稿自己的章节时一律写成"本稿 §…"。

### 8.1 一条贯穿性原则：这些判据几乎都是单向证据

第二部分反复撞到同一个逻辑形状，**异常指示有问题，正常不构成没问题的证明**：

- Watkin (2008)：*"If a structure 'looks wrong', it probably is wrong. The converse is not necessarily true."*（§15.4）
- Linden (2020)：*"A clean validation report does not necessarily mean that all is in order."*（§13.6）
- Xtriage：*"Large values can indicate twinning, but small values do not necessarily exclude it."*（§16.11）

**后果**：任何把这类指标实现成双向"通过/不通过"的地方都是误用。这不只是措辞问题，它决定了**判据缺席时系统应当采取什么姿态**。当前 `workbench/agents_md.py:305-309` 的零免责质量标尺、以及"R1<0.25 即禁止回头查群"这类规则，正是把单向证据当成了双向许可。**这条应当写进 §4 的编码原则，成为第 12 条。**

### 8.2 对评分体系的三条校准

**(a) 只看 CIF 无法区分"烂晶体上的好工作"与"好晶体上的烂工作"。** Watkin：*"The problem for the journals is to try to distinguish between good work on bad crystals and bad work on good crystals. If all you have is a CIF, the two cases must look very similar."*（§15.6）

任何只用 R1/wR2/GooF 打分的评分器都继承了这个**不可分辨性**。要区分必须看**过程证据**：做了哪些诊断、如何取舍、异常如何披露，而不只是终值。这对我们的 grader 是一条结构性意见，不是参数调整。

**(b) 精修失败本身是关于样品的信息，不必然是执行失误。** Watkin：采集确实做扎实的前提下，*"failure to refine to a conventionally fuzzy structure (or better) is an indication that something unusual is happening in the diffraction process, which may be worth reporting and reinvestigating. Nature is not always so obliging that she invariably follows the laws that we make."*（§15.5）

**把所有失败一律归因于 agent，会训练系统去掩盖异常而不是报告异常。** 但要注意与 §13.10 Linden 的实例并置，同一个位点按氯离子建模 R = 0.061、按水建模 R = 0.021 - **"R 高"也确实可能只是某个原子元素判错了**。正确姿态是两条都查，而不是二选一。

**(c) 观测/参数比只是指导原则。** Watkin：*"The IUCr guidelines for the observation:parameter ratio are only guidelines, and the model refined in every structure analysis must be judged on its own merits."*（§15.3）连最"客观"的指标，原作者都明说要按结构自身情况判断。**这是"综合判断力优先于阈值"这条设计原则的外部背书**，可直接引用。

补充一条对上的数字：IUCr 要求心 ≥ 10、非心 ≥ 8（§17.2），而无重原子有机小分子在 2θmax ≈ 50°、完整度 100% 时恰好是 10:1（§18.1）。**即该要求实质等价于"至少收到 2θ ≈ 50° 且收满"**，而 HKLF 5 孪晶数据天然冗余未合并，是成文的例外。

### 8.3 已证实的能力边界：应当显式建模，而不是当成 bug

**本稿 §0 第 2 条诊断（无金属时从头建模退化）现在有了方法学解释。** Sheldrick (2008)：直接法的门槛是约 **1.2 Å 原子分辨率**，且 *"the resolution requirement is much less rigid"* 当存在重原子（**甚至 S 或 Cl**）时（§15.10）。

**含义变了**：我们在含金属 MOF 上顺利、纯有机上退化，**不是偶发实现缺陷，而是方法本身的已知边界**。`tools/model_tools.py:154-171` 的元素指认缺陷仍要修，但同时应当让系统**知道**这条边界，在无重原子且分辨率接近 1.2 Å 时，从头直接法本就该被判为高风险路径，而不是失败后才归因。

**其他必须显式建模的边界**：
- **checkCIF 对非公度结构与电子衍射结构失效**（Spek 2020，§16.8）：*"The current checkCIF tool cannot handle symmetries of non-three-dimensional structures such as those for incommensurate structures."* 在这两类样品上，我们赖以判定"可发表"的工具**给不出有效信号**。
- **BVS 在原理上不适用于有机化合物**（Brown 2009，§12.1）：*"unfortunately excludes C−C and C−H bonds and therefore large parts of organic chemistry"*，且被称为 *"the principal limitation of the model"*。任何化学自洽检查都必须带这个适用域门。
- **反演孪晶（class I）在衍射图上原则上不可见**（§16.6）：*"twinning is not at all evident from the diffraction pattern and it may even pass unnoticed"*。**任何"先看衍射图判断有无孪晶、没有就往下走"的流程都会整类漏掉。** 它只能靠 Flack/BASF 在精修阶段发现。

### 8.4 已对代码验证的缺失检查

**(a) 吸收边邻近性检查完全不存在。** 全库 `edge` 匹配都是图论的边。`io/shelx_writer.py:142-160` 已经会用真波长的 Sasaki 项写 DISP 卡（那次 Zr K 边事故的**后果**已修，注释里的 "f'(Zr) = -9.0 e" 与我用项目 venv 的 cctbx 独立算出的 −9.041 吻合），但**没有任何东西预警"当前波长正压在某元素的吸收边上"**。

自算证据（`workdir/fdp_scan.py`，§14.5）：0.68883 Å 距 Zr K 边仅 **1.7 × 10⁻⁴ Å**，跨过这道坎 f″ 从 ~3.7 跌到 0.53（约 7 倍），f′ 深至 −9.0 e（Zr 散射能力的 22%）；且**正好落在边上的表值本身是插值假值**。叠加 Merritt 的 *"The actual absorption edge is shifted relative to the idealized edge... The largest part of this shift is due to the oxidation state"*（§14.3），**查表得到的边位置对成键原子本就不准**。

**建议**：读入波长后对样品中每个元素检查其吸收边距离，过近时**报警而非静默继续**。这是元素通用规则，不针对任何测试晶体。

**(b) tNCS 与自动剔离群点的冲突。** Xtriage：*"Note that if pseudo translational symmetry is present, a large number of 'outliers' will be present."*（§16.10）**在 tNCS 样品上自动剔除离群点会大量误删真实数据。** 我们的还原/精修链路里凡有离群剔除的地方，都应先问一句有没有 tNCS 迹象。

**(c) 判据的方向性被丢掉了。** Xtriage 给出：⟨I²⟩/⟨I⟩² 显著 **< 2.0 指向孪晶**，显著 **> 2.0 指向赝平移**（§16.11）。**偏离的符号本身携带诊断信息**：只报"偏离理想值"等于丢掉一半信息。这解决了 §16.4 留下的歧义（|E²−1| ≈ 0.74 既可能是真非心、也可能是被孪晶压低的中心对称结构）。

**(d) 限制是否合理有了可计算判据。** Watkin：*"Residuals larger than about three times the requested standard uncertainty should always be investigated."*（§15.2）把每条限制的残差与其所设 s.u. 相比、报出比值 > 3 的，比"看 R 有没有变好"敏感得多，且与 Linden 的"加限制后原位置冒出差值峰"（§13.4）是两个独立可互证的信号。

**(e) 一个轻微的基准打标风险（非解析正确性问题）。** `benchmark/tools/fetch_ext.py:442` 用 `occupancy < 0.99` 判无序。CIF 的 `occupancy` 与 SHELXL 的 SOF 是两个量（`SOF = occupancy/sso`，§12.3），对称心上满占据的原子 SOF = 0.5 但 CIF 应写 1.0。**遇到把 SOF 误写进 occupancy 的野生 CIF（checkCIF 专门警告过这种混淆），会把它误标为无序。** 主包不自己写 `_atom_site_occupancy`（CIF 由 SHELXL 产出），所以这个陷阱目前咬不到解析链路。

### 8.5 "不许删数据降 R"现在有了成文依据

第一轮只能说这是常识。第二轮拿到了三层证据（§17.1–17.3）：

1. **SHELXL 手册**对按 hkl 剔反射的定性：*"this form of OMIT is allowed with ACTA; however it should not be used indiscriminately."* 手册举的正当理由是**物理性的**（被光阑截断），不是统计性的（这条不合群）。
2. **IUCr 投稿要求**：*"Omission of outlier reflections should be avoided unless there is good reason and, in such cases, details of the omitted reflections and the reasons for doing so should be included in the _publ_section_exptl_refinement section."*
3. **IUCr 验证共同编辑内部指引里的真实处置**：主动过滤数据 ⇒ **要求去掉过滤重做**（不接受解释本身）；完整度 0.72（beam dump 造成）⇒ **直接拒**；约一半数据被跳过且无正当理由 ⇒ **直接拒**。

**注意第二例的含义**：完整度不达标**不因"不是作者的错"而豁免**。这否定了"客观原因造成的数据缺陷可以被谅解"的假设，对我们的评分口径是一条重要校准。

**同族的两条纪律**（都指向"别优化错的东西"）：
- Garman (1999)：*"In the extreme case, where most unique reflections are measured only once, R(I)sym for the data set will be lower than if each were measured four or five times, but the latter data would be more accurate and thus more reliable."*（§18.1），**Rint 是一致性的度量，不是准确度的度量。把它当质量分优化会奖励恰恰错误的行为。**
- SHELXL：被 σ 门槛标为"未观测"的数据**仍计入 all-data R 值**（§17.1），想靠提高门槛美化 R1(all) 是无效的。

### 8.6 交付层：可直接落成自检规则的条文

**(a) checkCIF 应当按"型"读而不是按"级"读。** 官方分型（§17.6）：1 型 = CIF 语法/数据缺失，**2 型 = 模型可能错**，**3 型 = 结构质量可能低**，4 型 = 方法学建议，5 型 = 信息。**2 型与 3 型正是本稿 §8.2(a) 那个"不可分辨性"的区分维度**：一个只统计 A/B/C 数量的实现会把两类完全不同的问题混为一谈。

**(b) 我们生成的解释性文字有了合格标准。** IUCr 编辑指引点名了三类不合格论证（§17.7）：
- *"near the acceptable limit"*：那只是 B 级的边界，不是"完全可接受"的边界；已在 A 级区就说明离正常值很远，**根本谈不上擦边**。
- *"数据较老、当年达标"*: *"Old data may actually become less publishable with time as modern expectations move ahead."*
- 情绪化 / 不合逻辑 / 求情式。
经验法则：*"A good rule of thumb: if it does not feel adequate, then it isn't."* **这三条可以直接作为我们输出前的自检规则。**

**(c) 披露写在哪里有了官方定义**（§17.6）：测强度**之前**的实验细节 → `_exptl_special_details`；精修细节 → `_refine_special_details`。

**(d) SQUEEZE 的两条硬约束**（§18.6）：
- **用了 SQUEEZE 就必须申报 nextra**，否则 s.u. 与 GooF 被**低估**：叠加 §13.7 的"s.u. 本身已被低估 1.5–2 倍"，误差会被系统性报小两次。
- **SQUEEZE 之后化学式处于验证盲区**：*"checkCIF will suppress certain validation messages when it detects details about the use of SQUEEZE"*，而 CIF 的化学式/μ/分子量定义又"不完全适用"。**这是需要 TGA / 元素分析等独立证据的技术根源。**
- 并且 Spek 明确写下：把 SQUEEZE 用在 **MOF 浸泡法**（客体本身就是研究对象）*"is not recommended"*。**这是一条按目的而非按数值决定的纪律**：同样的空腔、同样的残余密度，在"客体是杂质"与"客体是目标"两种情形下应有相反处理。**对我们 MOF 优先的数据谱系，这条直接相关。**

### 8.7 对既有诊断的加强与修正

**加强本稿 §2.3（经验来源集中）**：Linden 说 *"many 'special features' can appear maybe once in 50 or more structures"*，且 *"One might successfully complete many structure determinations before encountering a seldom-occurring 'feature' for the first time."*（§13.8）**这给"三颗晶体上表现良好"与"能处理任意未知晶体"之间的鸿沟提供了量级估计**：大约每 50 个结构一次的稀有情形，在 13 颗晶体的谱系里基本不会出现。

**加强上游决策的权重**：探测器距离过近 → 峰重叠 → **指标化选错 Bravais 晶格** → **系统消光有无被误判** → 空间群定错（Ramadhar 2015，§18.2）。**对大晶胞体系（MOF、COF 正是如此），这是一个会污染下游全部判断的上游决策**，而我们目前的知识层几乎不涉及采集期。

**一条新的解释力**：巴比妥酸二水合物在 150 K 是非贯穿孪晶的单斜 P2₁/n，室温却是正交 Pnma（§18.5）。**低温下出现的孪晶可能是降温诱发的**；**"与文献不一致"未必是文献错，可能是温度不同**。这与我们内部"先怀疑参考值"的纪律需要协调，`data_ext2` 的 9 个参考能复现已发表 R1 到 ≤0.002，那里不该用这条借口；但对温度不同的外部文献值，这条是成立的。

**一条内部术语的外部对应**：我们一直叫"幽灵原子"的现象，在 OD/层错文献里叫 *"'Phantom molecules' of alternative stacking arrangements"*，并且被列为**层错的四条诊断证据之一**（§16.9）。**即：它未必是建模错误，也可能是真实的层错信号。** 我们的幽灵原子检查应当能区分这两种情形，而不是一律判为缺陷。

**一条否定"贴标签走分支"的设计**：Fröschl (2025) 明说孪晶、反相畴、allotwin、漫散射 *"often, these appear in the same crystal and may not be separable."*（§16.9）**真实样品可以同时是无序的、孪晶的、有层错的，且未必可分离。** 正确姿态是记录观察到的证据组合，而不是强行归入某一类再走对应分支。

### 8.8 本轮未能取得、但值得后续补的

按剩余价值排序（详见 `workdir/knowledge-gap-register.md`）：

1. **相关系数矩阵 > 0.8 的处置指引**：最可能出处 Watkin (1994) Acta Cryst. A50, 411，付费无开放副本。我们能算相关矩阵却不知怎么读，这是剩余最大缺口。
2. **PXRD 验证体相纯度的成文要求**: MOF 论文标配，我们完全没有；RSC 403，候选 PMC 镜像未抓。
3. **ω vs φ 扫描的适用场景**：采集策略里唯一的真空白（厂家手册无公开版本，与 Bruker SAINT 情况相同）。
4. **中心对称群 Bijvoet 差恒零的成文出处**: **我们已把这条写进系统规则却两轮都引不出原文**，目前属"相信其对但无出处"，应如实标注。
5. **"收敛完成"侧的 shift/esd 判据**：只拿到编辑侧的"> 1.5 为收敛不良"。

---

## 9. 补漏核对（2026-09-03）查出的追加事项

把两轮收集到的全部原始材料与两份文档逐条回查（工装 `workdir/audit_quotes.py` / `audit_probe.py` / `audit_docs.py`；结果记录在知识库附录 B.5）。交叉引用与小节编号机械核查全部通过；查出并补入 11 处知识遗漏、订正 2 处表述。其中**对系统有直接后果的**如下。

### 9.1 一处措辞精度问题（已查代码，我们没有踩）

Fanwick 的 CCDC 教学材料明确写道 *"AS is important in both centric and accentric space groups."*（知识库 §14.2）。**"中心对称群里没有反常散射"是错的**：反常散射照样改变 |F|，影响标度、消光与精修；正确的说法是它在中心对称群里**不产生 Bijvoet 差**，因而不能用来定绝对构型。

**已核查**：`knowledge/skills/flack-absolute-structure.md`、`AGENTS.md`、`crystalpilot/workbench/` 与 `crystalpilot/` 全库中与反常散射相关的表述都限定在非心群语境（`tools/validation_tools.py:515` 的措辞是 "non-centrosymmetric structure with anomalous …"），**没有发现错误的全称表述**。此条记录下来是为了防止将来写成过宽的规则。

### 9.2 空间群搜索的方向性（可直接缩小搜索空间）

Raymond & Girolami：*"the correct space group is usually a supergroup of the chosen one, which means that the true space group has additional symmetry elements."*（知识库 §3.5）Marsh 的三组统计（Cc→C2/c、P1→P-1、C2→C2/c）全部符合这个方向。

**含义**：怀疑错群时，优先搜索方向应是"**有没有漏掉的对称元素**"，而不是"要不要降对称"。我们的 `check_symmetry` / ADDSYM 路线本来就是这个方向，但 `screen_space_groups` 的候选排序里没有体现这条先验。

### 9.3 一条会误读的 SQUEEZE 限定

Spek 2015 的 *"This method should not be used in cases of twinning"* 指的是 **.ins/.hkl 捷径**，**不是 SQUEEZE 本身**（SQUEEZE 可用于孪晶，但必须经 SHELXL LIST 8 输出的解卷积 .fcf 生成 .fab）。且孪晶分数明显变化后需重跑 SQUEEZE - **SQUEEZE 与孪晶精修之间存在循环依赖，不是一次性步骤**（知识库 §5.7）。

**含义**：我们若要支持"孪晶 + 溶剂掩膜"同时存在的体系，必须按这条路线实现，且需要一个"孪晶分数变了要重跑掩膜"的触发条件。

### 9.4 一条工具能力边界

Phenix *Xtriage* 的孪晶律搜索明说 *"Non-merohedral (reticular) twinning is not considered."*（知识库 §16.5），即**不覆盖网状孪晶全类**（obverse–reverse 这类常见情形不会被找出来）。同时它给出一条有用的桥接：*"The delta le-Page is the familiar obliquity."*，**即 Grimmer & Nespolo 六分类里的 ω 就是我们已经能算的量**。

**含义**：任何"跑一遍孪晶律搜索、没找到就判定无孪晶"的流程，会整类漏掉网状孪晶。入口应改用"非空间群消光"（知识库 §16.5）。

### 9.5 一条重复出现三次的方法论

**一个参数调得好不好，不由它自己会改善的那个数说了算。** 三处独立出现：
- SADABS：帧间比例因子的限制 esd 用**最终 R1 的浅极小**定，不看 Rint（知识库 §1.7）；
- SADABS：误差模型 g 的验收是 **χ² 对强度、对分辨率两张图都平于 1**，不是单个数（§1.5，该节标题即"误差模型：形状判据而非单一数字"）；
- SHELXL：权重的验收是**方差对 Fc² 与分辨率无系统趋势**，不是 GooF ≈ 1（§17.4）。

**含义**：凡我们有"自动调某参数"的地方，验收指标必须与被优化的指标**分离**。这是编码原则 12（单向证据）在参数整定上的对应物。

### 9.6 矛盾是信号

SHELXTL 的 roe119 实例（知识库 §3.2）：统计明确指向中心对称，而系统消光只容非中心对称群，**这个矛盾本身就是晶系定错了的诊断**，不该靠挑一边来"解决"。该例最终结论是真群 P2₁/c，且按正交采集导致**只收了所需数据的一半**。

**含义**：我们的 `screen_space_groups` 在证据链冲突时应当**报冲突**，而不是按打分挑一个最高的。这与本稿 §4 原则 7（两条独立路线交叉核对，不一致才升级为判断）是同一条，roe119 给了它一个具体的、可复现的形态。

