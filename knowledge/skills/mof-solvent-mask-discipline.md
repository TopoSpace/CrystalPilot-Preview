---
name: mof-solvent-mask-discipline
description: 溶剂遮掩（SQUEEZE/solvent mask）三分法决策与报告义务：配位溶剂必须建模、可识别物种应建模、只有不可辨认的弥散密度才遮掩；抗衡离子原则上不遮；mask 后电子数核对+分子式加回+CIF 披露缺一不可。准备调用 solvent_mask、遇 PLAT602、或审稿质疑溶剂处理时读此卡。
alerts: [PLAT602]
tools: [solvent_mask, run_shelxl, model_disorder, set_restraints, run_checkcif, validate_structure, write_outputs]
tags: [溶剂, SQUEEZE, solvent mask, 报告规范, 电荷平衡]
source: Spek, Acta Cryst. C71 (2015) 9-18 (https://journals.iucr.org/paper?S2053229614024929=)；Olex2 官方文档 (https://www.olexsys.org/olex2/docs/tasks/tasks/using-maps-and-masks/)；CCDC/UdeM 教学 (https://www.ccdc.cam.ac.uk/media/resources/schaper-squeeze-fs06b.pdf)；Canossa, CrystEngComm 2025, 27, 6556 (doi:10.1039/D5CE00824G)；Woods, ACA 2025 摘要 (https://pmc.ncbi.nlm.nih.gov/articles/PMC12585478/)；Øien-Ødegaard et al., Chem Soc Rev 2017, 46, 4867 (doi:10.1039/C6CS00533K)
confidence: high
created_by: researcher
---

# 溶剂遮掩纪律（MOF/框架）

## 决策三分法（只许单向降级：建模→强限制建模→遮掩）

1. **配位到金属中心的溶剂：必须建模**，哪怕无序（拆位+限制）。出现在 mask
   区内的配位溶剂 = 模型错误，不是遮掩对象。
2. **可明确识别的孔内物种**（差图可辨形状/氢键网络/化学计量支持）：建入模型，
   占有率可 <1（弱结合溶剂会流失）；先并行建模晶格溶剂常能改善相位、反而
   降低主体所需限制。
3. **无法辨认的连续弥散密度**：才是 SQUEEZE/solvent_mask 的正当对象，
   与其对弱噪音密度过拟合（乱安水氧压 R），宁可遮掩。

## 电荷纪律

- **抗衡离子原则上不得遮掩**（"never SQUEEZE your counter-ions"）：先用
  刚体/强限制建模。唯一例外：完全不可建模且有充分外部表征（EA/NMR/谱学）
  支撑电荷态与组成，"外部证据换遮掩权"，并在 CIF/SI 明说。
- 有序部分电荷有歧义时禁用遮掩（遮掉的电子数无法归属）。

## 前置与操作检查

- 数据前提：反射数/参数比不足（弱数据、低完整度）时 SQUEEZE 即过拟合
  装置，不要用它拯救烂数据。
- 不叠加：撤掉旧 mask 并跑一轮精修后才能换用另一实现（"don't squeeze a
  squeezed structure"）；终版若改为建模溶剂，必须先撤 mask。
- 现代管线走 .fab/ABIN（溶剂贡献作外部文件进 SHELXL），不改 Fo；孪晶
  （BASF/TWIN 与 HKLF5）现已兼容。

## 报告义务（缺一即挨审稿刀）

1. 每晶胞 void 数、体积、位置、**回收电子数**；
2. 电子数 → 候选溶剂种类与数量折算（按合成液成分），**加回分子式/密度/F000**；
3. CIF 精修细节段写明：用了何工具、理由、电子数与归属；SQUEEZE 细节与
   未合并数据留在 CIF 内不得删；
4. PLAT602 标准 VRF：多孔框架 + 无序溶剂无法建模 + 已遮掩并计入分子式。
- 生态位注意：checkCIF 识别 PLATON .sqf/.fab 嵌入会自动降级 void 警报，
  对 Olex2/smtbx 的 _smtbx_masks 识别不完全，投稿场景优先 PLATON 兼容
  的披露格式。

## 判读一致性

- mask 电子数应与折算溶剂期望值大致相符（数量级不符 = 归属错误或模型
  缺块）；每次 mask 后核对并记入会话结论。

## solvent_mask 的三种"非成功"都不是"没有溶剂"（pa1 实例）

- **失败："BYPASS dropped … NEGATIVE"**：差图均值为零，某个空洞积分为
  负，意味着**模型在骨架区偏轻**（原子/氢缺失、元素指认偏轻、各向同性
  或缺 ADP、标度差），差图把亏空记到了空洞头上。这是模型的性质，**不是
  空洞为空的证据**: pa1 里三个 run 把它写成"数据不支持掩膜"并交付了
  无掩膜的 R1 0.185（同一坐标加掩膜 0.09）。处置：先把骨架做完（原子
  齐、元素核实、重原子各向异性、加 H）再掩膜；仍失败再试 d_min≈1.0 或
  resolution_factor 0.33 的掩膜网格。
- **`bypass.diverged=true`**：f_000_s 连续多轮单调上涨（hex-l3-r3：
  1636→7479 e），电子数不是任何东西的测量；工具保留残差最好那一轮的
  f_mask，并告诉你是哪一轮。这同样指向模型不完整/标度问题，先改模型。
- **`solvent_mask_converged=false`**：达到 max_cycles 未收敛，电子数是
  下限；提高 max_cycles 再引用。79% 空洞的大孔 MOF 里电子数本来就由
  整体标度主导（Zr 模型 181–2100 e 不等），R 值的下降是稳健的，电子数
  不是，报告里给范围，不要精确到"六个 DMF"。
- 掩膜现在随节点快照保存（f_mask.pkl），checkout/branch 不再重算；
  模型一改仍必须重跑 solvent_mask（或 refine(refresh_mask=true)）。

## 电子数不稳定 ≠ 掩膜无效（pa2 cage 两格的教训）

- 模型还在变（补原子、拆位、换元素、加 H）时，每次 solvent_mask 的电子数
  会在几十个百分点内摆动（cage-l2-r2：2342→1304→2183→…→694；
  cage-l0-r2：2821→…→502→负积分丢弃）。掩膜吸收的是"模型缺的一切"，
  这是物理，不是工具坏了。两格 agent 据此判"掩膜不稳定"、以"原子+掩膜
  不能双算"为由放弃掩膜，交付 R1 0.22–0.23，而各自树里带掩膜的节点是
  0.12。
- **掩膜去留的唯一判据是精修**：同一模型带/不带掩膜各精修一次，比
  R1/wR2/GooF 与残差图；掩膜让 R1 降 0.1 且残差图变干净，它就该留着。
  电子数只在**最终模型**上引用一次，并附 electron_count_confidence。
- coordination_encroachment 在 Zr₆/桨轮等多核节点上会每次列出全部金属
  （端基 OH/H₂O 位 2.0–2.3 Å），那是"骨架待办"，不是撤掩膜的理由。
- 负积分丢弃时保留上一个收敛的掩膜（checkout 该节点或
  refine(refresh_mask=false)），继续补骨架；不要交付无掩膜模型。
- write_outputs 返回 better_nodes 时（树里有 R1 更低的节点），SUMMARY
  必须写明为何不交付它，"掩膜被撤"本身要有上一条的精修对照做依据。

## 掩膜失败后的第一步：与上一个成功掩膜的模型做 diff（mask_diagnosis）

- solvent_mask 的每次"非成功"（负积分丢弃 / nothing masked / diverged /
  未收敛），以及项目里已有掩膜时的每次成功，结果都带 `mask_diagnosis`：
  `previous_mask`（上一个成功掩膜是在哪个节点算的：节点 id、电子数、空洞数
  与体积、该节点 R1 及用该掩膜精修到的最好 R1、时间戳；它未收敛时另给
  `last_converged_mask`）、`model_delta`（当前模型相对该节点模型的差异：
  按位点、对称性感知 ≤0.3 Å 匹配，改名不算变化；列出增/删原子、元素改指
  认、占有率与 ADP 变化、H 增减、非 H 电子数前后）、`electron_change_pct`、
  `mask_params_changed`、`reading`（由 delta 推出的两三句判读）和 `rule`。
- 三条规则：
  1. NEGATIVE/diverged 之后的**第一步是 checkout 上一个收敛掩膜的节点并比较
     两个模型**（`compare_nodes`），不是改掩膜参数，更不是撤掩膜；
  2. **不要在同一步里删原子又重算掩膜**：先改模型、提交、看 delta，再重算；
  3. 两次调用之间**电子数变化 >30% 是"模型变了"的信号**：先看
     `model_delta`，再碰掩膜。delta 为空（模型没变）时，差异来自掩膜参数/
     网格（对比 solvent_radius / shrink / resolution_factor / d_min）或精修
     状态（标度、权重），不是模型。
- reading 的读法：模型变轻（删原子、元素改轻、占有率降）→ 负积分是骨架亏
  空被差图记到空洞头上；模型变重却负积分 → 新加的原子/元素放错或过重；
  模型没变 → 参数/网格效应。三种情形下都不该得出"空洞是空的"。

## 掩膜之后不能再"找客体"（pa3 教训，2026-09-03）

- 掩膜存入后，每张差值图都是对 Fc + F_mask 算的：**空腔内的密度按构造
  被吸收**，在有掩膜的节点上 inspect_map 找不到客体、integrate 出几个
  电子，都不是"不存在"的证据。solvent_mask 的 summary 里带
  guest_search_note 提醒这一点。
- 找客体/低占有率杂原子用掩膜前的差值图：`probe_site` 与
  `integrate_difference_density(mask='auto')` 在位点落入掩膜空腔时自动
  关掩膜（参考与候选同口径）并在 mask_handling 里说明；强制 mask='on'
  时它们会警告"这是掩膜构造，不是不存在的证据"。判读读
  [[mof-guest-evidence-rule]]。
- 顺序纪律：先在无掩膜（或掩膜前）模型上做客体搜索与 probe_site，决定
  建模还是掩膜；掩膜是对**剩下的**弥散密度的处置，不是对"没找到的"客体
  的处置。
