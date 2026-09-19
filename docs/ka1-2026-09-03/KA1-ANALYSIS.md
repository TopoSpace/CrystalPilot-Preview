# KA1 知识层消融对照实验：分析报告（2026-09-03）

> 状态：完成稿（2026-09-03 23:40）。结果表以 22:55 重评分后的 grade.json 为准；§4–§7 以三份核读稿为据。
> 数据来源：`workdir/campaigns/ka1-{hex,org,cage}/state.json`、各格 `grade.json`、`logs/`（SSE、codex rollout、引擎事件、节点树、交付物、`mcp_server.jsonl`）、现场笔记 `ka1-notes-live.md`、机械统计草稿 `KA1-ANALYSIS-draft.md`（`ka1_report`）、三份核读稿 `ka1-readout-{hex,org,cage}.md`。

---

## 1. 一页结论

1. **结果**：hex 两臂同为 publication（0.0817 vs 0.0833，同一个结构）；org 纯工具臂 no_delivery、全栈臂 publication（R1 0.0263 = 参考）；cage 两臂同为 below_bar，但全栈臂 0.1642 的模型移植到参考数据上复现参考 R1（0.1409 vs 0.1395），纯工具臂 0.2241 的模型不是参考解。机械判语：hex 接近、org B>A、cage B>A。n = 1，R1 差 < 0.01 与墙钟差都不能解读。
2. **对主人假设的回答**："知识层压住基模的判断"在本实验里**没有出现**：六格里没有一格是全栈臂因为照规则执行而做错、纯工具臂因为自由而做对。相反的方向也只成立一半：纯工具臂在 hex 上把截断、劳厄类、负掩膜诊断、real 原子处置全部自己做对了，在 cage 上自己走到了分支/对照/幽灵测试/去孪晶/各向异性顺序/分离作业轮询，在 org 上正确识别了消光反射已被剔除并诚实收尾。**基模的判断力不是瓶颈**：这与 pa1–pa4 的过程审计一致。
3. **知识层真正加分的地方全是流程纪律，不是晶体学判断**：定群协议（cage-tools 被 SHELXT 的 R 值牵去 Pc 75 min）、掩膜纪律（cage-tools 4/4 败、重建后不再重试、PLAT602）、"占位组成可以猜"的许可（org-tools 把 composition 报错读成数据缺陷）。三条都能指向具体失败格。晶体学判断类的规则（吸收边、幽灵原子、元素身份、质量标尺）在六格里**没有产生可测的差别**：因为同样的知识已经写在工具返回里（`audit_heavy_sites` 报 Zr K 边、`ghost_test` 带处置协议、`solvent_mask` 带三分法），两臂都读到了。
4. **本实验最大的损失来自工具层，两臂共有**：无预算、无分离的求解/权重计算 + codex 客户端超时后服务端不取消 + 项目锁陪葬（org-tools 整格、cage-full 65 min）；SFAC 未暴露 + 报错措辞（org 分岔点）；`element_scan(free_occupancy=true)` 疑似失效（cage 两臂把 3 个 Cl 标成 O 的直接原因之一）；SHELXL 温度默认值污染 CIF（四份交付）；`diagnostic` 状态被 finalize 拒收；ghost 判据把近核纹波判成 real。这些修好之前，模板/卡的任何改动都测不出来。
5. **建议**（§6）：模板 v33 按 §2.4 第二档收缩，只保留能指向失败格的三组流程规则 + 操作契约加"长计算可分离/可放弃"一句，其余判断内容删除或下沉到工具返回；不做三张新卡与 v34 重写；技能卡保留按需可读。**先修 §7.1 的 P0，再做知识层**。
6. **必须一起披露的**：消融不纯（工具描述 2/65、工具返回 18 处指向技能；纯工具臂在 hex 上 ≥ 6 次被工具返回指向 read_skill 而找不到该工具），所以本实验测的是"模板 + 技能工具"的增量，不是"晶体学知识"的增量；org 数据消光反射缺失；每格一次。

---

## 2. 实验是什么、怎么保证两臂只差知识层

- **问题**（主人提出）：CrystalPilot 是否越来越依赖技能卡与模板里的判断规则，压住了基模（gpt-5.6-sol @ xhigh）自己的推理？"只给工具、不给知识"能不能解出结构？
- **两臂**：
  - **A 纯工具（`knowledge_mode = tools_only`）**：AGENTS.md 只有操作契约 + 诚实守则（1 768 字符 / 3 646 B）：工具面延迟加载怎么等、凡改模型只走 MCP、串行执行、慢≠卡死、交付流程与文件位置、凭据卫生；诚实四条（不为统计量增删改判原子/丢数据、不静默改群、不编造元数据与结构、不确定写 unresolved）。**零晶体学判断、零阈值、零技能指针**；`list_skills/read_skill/save_skill/delete_skill` 不注册（MCP 进程 65 个工具）；`run_checkcif` 不附 related_skills。
  - **B 全栈（`full`）**：当前 v32 模板（13 968 字符：工具图谱 + 判断方式 + 诚实守则 + 专家评审铁律 + 质量标尺 + 技能库指针）+ 20 张技能卡 + 5 张案例卡（69 个工具）。
- **相同项**：数据、L0 提示（"数据目录（只读）：… 请解这个结构。"）、模型与推理强度、权限档 auto、工具描述文本、评分器、超时（hex 4 h / cage 5 h / org 2 h）。
- **构造效度的证据**（每格都有，不是声明）：state.json 记 `agents_version`（模板标记）、`agents_sha256` 与 `agents_expected_sha256`（磁盘文件哈希 = 渲染哈希，六格全 true）、`root_agents_sha256 = null`（战役目录在仓库外 `H:/CrystalPilot-campaigns/`，codex 没有别的 AGENTS.md 可注入，pa1–pa4 时代仓库根那份旧文件被一并注入的问题已排除）；`logs/mcp_server.jsonl` 记 MCP 进程实际的 `mode` 与工具数（tools_only 格 65，full 格 69）。
- **发射前实测抓到并修掉的一个会让实验作废的坑**：MCP 的 tools/list 走按代码指纹的规格缓存，纯工具臂的进程虽带环境变量，最初仍被喂了全栈 69 个工具的缓存；缓存键现附加模式（`spec_cache.cache_key()`），stdio 与 HTTP 两条链路复核后才发射。
- **残余混杂（必须披露）**：
  1. tools_only 下 65 个工具描述里仍有 2 个提到技能（`audit_guest_evidence`、`integrate_difference_density`）；工具**结果**文本里指向 read_skill/技能的字符串共 18 处（9 个文件）。本轮不剥离。
  2. 工具描述本身带判断性文案（如 ghost_test 处置档、integrate_difference_density 的电子数尺子、run_shelxt 的预算说明），这是"工具层"，两臂相同，但意味着 A 臂并非"零知识"，而是"零模板/零卡"。
  3. org 数据（`data_ext2/org_hsl`）的 hkl 由沉积 fcf 反推，系统消光反射已被 SHELXL 剔除：`screen_space_groups` 对所有候选只能报 `no_absence_conditions`，定群只能靠 E 统计与合并统计。两臂条件相同，但与真实冷启动不同。
  4. n = 1：每格只跑一次。pa1 的重复格测得同一晶体同一提示的 R1 差可达噪声地板量级；本实验任何 ΔR1 < 0.01 或墙钟差都不能解读为臂效应。
- **规模**：3 晶体 × 2 臂 × 1 重复 = 6 格，两泳道并发（4 核 BelowNormal），15:55 发射，22:52 全部结束。

---

## 3. 结果总表

（重评分后由 `ka1_report` 草稿核对；下表为跑完当时的数值，标 ⟲ 者预期随评分器修复变化。）

| 晶体 | 臂 | 等级 | R1(agent) | R1(ref) @ d_min | agent d_min | ΔR1 可比？ | 原子数 | 墙钟 | tokens | 备注 |
|---|---|---|---|---|---|---|---|---|---|---|
| hex（NU-1000，Zr-MOF，λ 0.68883） | 纯工具 | publication | 0.0817 | 0.1162 @ 1.10 Å | 1.000 Å | 否（截断不同） | 26 | 39 min | 12.7 M | 660 元数据警报只在此臂 |
| hex | 全栈 | publication | 0.0833 | 同上 | 0.997 Å | 否 | 26 | 25 min | 15.4 M | |
| org（C₈H₁₁NO₄，P2₁2₁2₁，CuKα） | 纯工具 | **no_delivery** | — | 0.0264 @ 0.805 Å | — | — | 0 | 120 min（超时） | 7.1 M | 3.7 min 起被无上限电荷翻转锁死 |
| org | 全栈 | acceptable ⟲ | 0.0263 | 同上 | 0.805 Å | **是**（Δ −0.0001） | 24 | 17 min | 9.3 M | 组成与参考完全一致；只因评分器酰胺假阳性未到 publication（已修，待重评） |
| cage（Zr₆ 笼，λ 0.68883，完整度 73.6 %） | 纯工具 | below_bar | 0.2241 | 0.1395 @ 0.69 Å | 0.996 Å | 否 | 222 | 145 min | — | 自报 solved=false；最佳节点 0.1977 未交付；PLAT602 空洞 23.6 % 未掩膜 |
| cage | 全栈 | below_bar | 0.1642 | 同上 | 0.996 Å | 否 | 221 | 194 min | 47.9 M | 自报 solved=false、模型 diagnostic；已掩膜（空洞 27.6 %）；Zr CN=10 与 C047 金属键合轻原子旗标 |

历史参照（全栈臂，pa2–pa4）：hex publication ≈0.080；cage acceptable 0.1405 / below_bar 0.2223。

---

## 4. 两臂逐晶体对比

（细节、时间线与逐条引文见三份核读稿 `ka1-readout-{hex,org,cage}.md`；本节只写结论性事实。）

### 4.1 hex（NU-1000）：两臂交付了同一个结构，差别全在工具开销

- **结构层面同一**：26 原子、P6/mmm、`C88 H44 O32 Zr6`、Z = 3、155 参数、0 限制、6 个骑乘芳香 H、全各向异性；对参考的 emma rms 0.088 vs 0.086 Å；checkCIF C 级 23 条完全相同。真正的差别只有两处：A660（纯工具臂把 `_diffrn_radiation_type` 留成 `?`，全栈臂经 `set_experiment` 写了 synchrotron 并带出处）和掩膜电子数（238.1 vs 49.1 e/胞，两臂都没收敛、都如实标了低置信）。
- **13.9 min 墙钟差的 94.6 % 是两项工具开销**：SHELXT 623.8 s（纯工具臂两次作业，`n_phase_sets=300`、让 SHELXT 搜 18 个群，再用 `Zr C N O` 重解一次无增益）vs 65.8 s；`solvent_mask` 356 s vs 124 s。不是判断力差别，是"没人告诉它 SHELXT 预算"的探路成本。
- **纯工具臂自己做对的**：按 CC1/2 逐壳（0.556 → 0.272）定截断并主动说"要清楚披露"；用 Rint 比较 + E 统计定劳厄类，并且正确指出"消光数据分不开 P6/mmm 与 P622"；负掩膜诊断正确（缺 H → 先各向异性加 H → 掩膜成功）；real 原子处置正确。
- **决定性的知识来自工具层与预训练，不是模板/卡**：`audit_heavy_sites` 的返回本身就带中文的 Zr K 边警告（f′ = −9.04、z_eff 31.0、`edge_at_lambda`）与 `ready_for_r_vs_z: false`；`ghost_test` 返回完整的"ghost 是唯一删除许可"协议；`solvent_mask` 返回三分法与"电子数摆动是物理"。两臂都读到了。两臂又都从胞参数 + 渲染图**认出了 NU-1000/TBAPy**并据此推出 Zr18 C264 H132 O96 / Z = 3，模板与卡都没给这个。
- **禁令违反：两臂均未发现**（为 R 删原子、静默改群、掩膜吞骨架）。两臂删孔内原子都在成组 `ghost_test` 判 `real`（ΔR1 +0.044 / +0.047）之后、带 `acknowledge_real` 与化学理由。
- **两臂共同漏掉的**：参考含 1/8 占有的溴代芳基客体（Br6 occ 0.125 + 7 个部分 C）并自带 FAB 掩膜；两臂都把整个孔道掩掉（客体召回 0.0），都没调 `integrate_difference_density` / `audit_guest_evidence`，候选元素表里从未出现卤素，**这是全栈模板明文有、全栈臂没执行的规则**。
- **"R1 比参考低"不能读成更好**：把两臂模型移植到参考自己的数据上 R1 = 0.1320 / 0.1321，比参考模型的 0.1162 差 0.016；低 R1 来自各自的还原/截断/掩膜。
- **两臂共同撞到的工具缺陷**：`_diffrn_ambient_temperature 293(2)`（SHELXL TEMP 默认值）进了两份 CIF；全栈臂显式 `set_experiment(temperature_K=null)`，工具答 `remove_requested_but_absent`，CIF 里的值照旧，两臂都只能靠 SUMMARY 文字披露。`add_hydrogens` 的矛盾警告与 `}}` 排版错字两臂都遇到。SHELXT 在 `C H N O` 组成串下会发明 `I18`（两臂都碰到）。
- **消融不纯的实证**：纯工具臂的工具返回里 ≥ 6 次指向 `read_skill` 卡（audit_reflection_data、audit_heavy_sites、audit_element_assignment、solvent_mask ×3、write_outputs）；agent 两次在 `ALL_TOOLS` 里找 `read_skill`，找不到就放弃了。另外 `list_skills('Zr absorption edge …')` 在全栈臂返回 0 张，**根本没有吸收边技能卡**，这条知识只活在 `audit_heavy_sites` 的返回里。
- **判读**：在 hex 上知识层没有可测的增量；纯工具臂多付了约 14 min 的工具探路成本、少用了 2.6 M tokens。n = 1，0.0016 的 R1 差与墙钟差都在噪声内。

### 4.2 org（小有机物）：胜负在一个参数，败因在一个没有预算的工具

- **分岔点只有一个参数**：2.10 min 纯工具臂的 `run_shelxt` 在 0.008 s 内失败：`no element list available - pass composition='C H N ...'`。它把这读成**数据**缺陷（原话："数据未提供元素清单，SHELXT 因而不能启动"），转投"不需要显式组成"的引擎。全栈臂 1.45 min 首次调用就传了 `composition="C H N O"`，7.2 s 成功。两臂看到的工具描述完全相同（`composition?: string`，无说明文字）；`TEMPLATE_TOOLS_ONLY` 里 composition / SFAC / shelxt 一次都没出现；全栈臂读的那张卡（data-ingest-space-group-protocol）也**不提** composition。差别来自 v32 模板里一条别的规则的字面："SHELXT 组成串（尤其占位的 C H N O）…不是元素证据"——模板没有教这个参数，它**给了"占位组成可以猜"的许可**；而纯工具臂手里只有诚实守则"不编造…结构"，它把猜组成也当成了编造。
- **no_delivery 的直接原因是工具层的洞，不是知识缺口**：`solve_charge_flipping` 没有 `timeout_s`、没有 detach、没有墙钟（`solution_tools.py:97-135`），描述里还写着"failure 时多试 seeds"；"盲扫 d_min/seed 记录很差"的劝阻只出现在**失败返回**里，一个永不返回的调用永远送不出这句话。v32 的预算纪律只写了 SHELXT；全栈臂若开同样的 8×20×5000 也会死在同一处。
- **平台事实被日志坐实并加细**：68.30 min codex 3 900 s 超时 → 98.79 min `run_shelxt` 收到 `(running 5729s so far)` → 129.05 min（case 已结束之后）`get_project_brief` 收到 `(running 7545s so far)`。`QUEUE_MAX_S = 1800` 让此后每次调用白烧 30 min。
- **65 min 的等待 = 76 次 `wait` 调用（共 136 次调用）+ 50 条等待语**。它在 44.58 min 正确估出"约 1 小时"并选择等；它考虑过杀进程（被"绝不杀进程"挡住）、并发（被串行规则挡住）、"是否在等审批"（想了 5 次，实际 0 次审批事件）；**从未考虑**开第二个项目/分支或用更小预算重发。诚实守则在这里变成了绑手的绳子，这是操作契约缺一句"长计算可分离/可放弃"的代价。
- **纯工具臂自己的晶体学并不差**：识别出文件里的消光反射已被剔除；说"不能因为算法收敛就采纳"；98.95 min 自己诊断出平台缺陷；无泄漏、无危险 shell；收尾结论诚实（solved=false / confidence=low）。两处真正的判断失误：锚定在单一 mmm 合并 E 统计（0.957，"中心对称"）上；无视 Superflip 返回的 `{op "-1", agreement 70.74}` 警报，8 s 后又回到中心对称的 Pmmm。
- **全栈臂的取胜路线是它自己发明的，不是卡教的**：在 P−1 求解 → SHELXT 给出 R1 0.072 的 P1 解 → `check_symmetry` 找不到额外算符（未匹配原子 = SHELXT 错标的 C/N/O）→ 按几何把四份 P1 拷贝配对、改判 4 个元素 → `check_symmetry` 给出 3 个算符、匹配分数 1.0 → 9.09 min `change_space_group(adopt_suggestion=true)`。
- **运行记账的两处更正**：org-full-r1 重评分后 grade.json 为 publication（`chemistry.flags=[]`），state.json 里的 "acceptable" 是旧标签；纯工具臂 rollout 里有诚实的收尾结论，但 `verdict.json` 只收到 `{"unparsed": "状态无变化…"}`，主回合被中断后 runner 没有收割到最终结论，这是 runner 的一个缺口。
- **新发现的工具层问题**：`no_absence_conditions` 一个字串两种相反含义（P222 真的没有条件；P2₁2₁2₁ 有条件但观测数为零，在 fcf 反推数据上后者正是螺旋轴的**阳性**指纹）；按劳厄类的 E 统计只有 `screen_space_groups(all)` 有、`reflection_statistics(all)` 没有；`friedel=null` 与 `wilson.skipped` 不给原因；完整度守卫让人缩短一个本工具没有的 `timeout_s`；交付 CIF 的 `_symmetry_space_group_name_H-M` 为空，群名带 `(a+1/4,b,c-1/4)` 基矢注记、`change_space_group` 剥不掉，agent 只好 waive 一条 A 警报。评分器内部矛盾：emma 13/13 原子 rms 0.001 Å，而 `model_transplant` 报 R1 0.4227 "模型不同"（非标准 P2₁2₁2₁ 设置经 `invert_structure` 后的原点/手性对齐疑似有错；不影响等级，但是假警报源）。
- **判读**：org 是知识层"有用"最清晰的一格，但拆开看，可归于知识层的只有"占位组成可以猜"这一句许可；败因（无预算求解工具、客户端超时不取消、SFAC 未暴露、消光缺失时的报法）全部是工具层，两臂共有。

### 4.3 cage（Zr₆ 笼）：同为 below_bar，但不是同一种失败

- **移植检验把两格分开了**：把全栈臂模型放到参考数据上 R1 0.1409 vs 参考 0.1395，评分器判语"publication-grade MODEL"，即它的原子位置基本就是参考解，差距全在数据还原侧（0.996 Å 截断、73.6 % 完整度）；纯工具臂模型移植后 0.2388，"model itself differs"。
- **时间去向**：纯工具臂 145 min 里 94 min（65 %）花在"先走错群（Pc，低对称逃逸 + 反演孪晶 BASF ≈ 0.49）→ 119 min 由 `check_symmetry` 判出 12 个 Zr 100 % 服从 −x,y,−z 而全模型不服从 → 删 289 个轻原子重建 P2₁/c"。全栈臂 194 min 里 88 min（45 %）没有产生任何模型进展：SHELXT 轮询 23 min + **`optimize_weights({})` 一次空转 65 min**（codex 3 900 s 超时，服务端继续算，节点 4 051 s 后才落库；期间 agent 发 30 条"按规则不杀大结构精修，继续等"）。去掉这 65 min，全栈臂 129 min 就到同样的交付面。
- **定群**：两臂最终都是 P2₁/c（与参考同型）。全栈臂按卡走 `screen_space_groups(laue_group='all', merge_stats)`，1.3 min 定群、此后没换过；纯工具臂只查了一个劳厄类，被 SHELXT 的"Pc 解 R1 更低"牵着走了 75 min。纠错的那一步（119 min）是**工具判词驱动**的，不是模型自发的，工具说了，它当场听懂并补了自己的第二条证据（孪晶比例 0.49）。
- **Zr 的身份两臂都靠同一个工具**：`audit_heavy_sites` 主动报出 Zr（f′ = −9.04、`edge_at_lambda`），纯工具臂 18.6 min、全栈臂 12.8 min 改判；SHELXT 自己塞进的 Br7 / I12 都被纠正。功劳在工具层不在模板；两份 CIF 都带 Zr 的 DISP 卡。
- **两臂最实质的共同化学失误**：参考里的 3 个 Cl（氯代溶剂）两臂都精确找到了位置、都标成了 O。全栈臂 `probe_site` 给出 Cl 占有 0.597 / Br 0.258 / Na 0.888 全拟合到约 10 e，它的结论"缺合成信息不能唯一指认，列为约 10 e 的未决位点"在规则上无懈可击，缺的是先验（L0 不给）和一句工具校准（R1 ≈ 0.19 的不完整模型上 omit 电子数系统性偏低约一半）。纯工具臂**被工具的数字带错**：`integrate_difference_density` 报 8.8 e"支持满占 O"；`element_scan(free_occupancy=true)` 五个候选元素的 occupancy 全部恰好 1.000、Ueq 全部同一个 0.0208，跨两臂三次 `element_scan(free_occupancy=true)` **每一行都是 1.000**，而同位点 `probe_site` 能精修出占有率。**疑似工具缺陷**（自由占有率没有生效），直接产生了交付 CIF 里的 O1 标签。
- **掩膜：4/4 败 vs 8/8 成**。纯工具臂第一次掩膜就违反了工具失败消息里那条 rule（删掉 55 个 real 位点 12 s 后就算掩膜 → 空洞积分为负 → BYPASS 全丢），此后因为从未有过成功掩膜，`mask_diagnosis.previous_mask` 恒为 null、只能盲改参数；119.5 min 重建 P2₁/c 之后**再没重试过掩膜**：而新模型正是消息里说的"framework finished"状态。这是纯工具臂唯一一处明显执行遗漏，代价是 PLAT602 + 0.2241（pa2 cage "0.12 vs 0.23"几乎原样重演）。全栈臂在读了 mof-solvent-mask-discipline 卡、`assemble_asu` 之后、没删任何原子的模型上一次成功（847 e，confidence high），改模即重算，电子数掉 26 % 且 confidence low 时也没有丢掩膜，与卡一致。一条工具说了没人跟的话：首次掩膜就带 `coordination_encroachment`（掩膜网格伸进 I003 配位球 2.7 Å），到交付都没清偿；评分器的 Zr CN = 10 与 C047 金属键合轻原子旗标很可能同源。
- **ghost_test 在这颗晶体上没有判别力**：113 个位点 0 个 ghost。纯工具臂 96 个位点带 `acknowledge_real` 删除，其中距 Zr 0.72–1.05 Å、Uiso = −0.001 的近核纹波被工具判成 real（删掉后纹波当然还在），把唯一的删除许可挡在 acknowledge_real 后面，判据缺陷；另外 78 个"交给掩膜统一处理"的位点，掩膜从未成功，这批密度最后既不在模型里也不在掩膜里。全栈臂全程 0 次删除，两次被 `edit_atoms` 的 real 闸门挡住后改走 element_scan。
- **评分器旗标的真实含义**：N43/N48"羧酸形 N"与 26 条可疑 N–N 都落在同一片孔道残余密度里，C11 同时接两个 N 和一个 1.57 Å 的 C，既不是羧酸也不是酰胺，是**被当成原子写下的未指认密度**。几何判据是真阳性、标签是错的（不是"O 标成 N"）。全栈臂没有 N 旗标只因为它用 `composition="Zr C O"` 重解，模型里根本没有 N（换来 24 条 1.16–1.27 Å 的 C–C 旗标）。两臂 SUMMARY 都如实写了"大量游离位点与不可能短接触"。
- **交付决策都是有据、公开的**：纯工具臂交 0.2241 而不交 n0040 的 0.1977，`summary_note` 与 SUMMARY 都写明"Pc 节点是低对称逃逸 + 337 原子过参数化 + 无掩膜，不按最低 R 选模"——正确。全栈臂在 188 min 舍弃把 R1 压到 0.17 但"把弱位点拖进重原子附近"的分支，交更稳的坐标，v32"化学合理性 > R 值"被逐字执行。
- **诚实性**：两臂 verdict 都是 solved=false / confidence low，与 CIF 一致；无为 R 删原子、无静默换群、无编造 restraint、泄漏干净。**两处工具侧问题**：(1) 纯工具臂显式 `set_experiment(temperature_K=null)`，工具答"CIF 将写 ?"，但两份 CIF 都写着 `293(2)`（SHELXL TEMP 默认被原样装配），诚实守则是 agent 守住的，工具把它破坏了，工具的消息本身是错的；(2) `status='final'` 语义过软（23 条披露式豁免把自评"不能发表"的模型升成 final），而更诚实的 `diagnostic` 反被惩罚（`finalize_delivery` 拒绝受理，SUMMARY/VALIDATION/checkcif.json 没进 MANIFEST 哈希清单，agent 为此原地打转）。
- **"规则替代判断"的教科书样本，也是本实验唯一一处模板明确造成损失的地方**：全栈臂的 `optimize_weights` 空转 65 min 里，agent 在 91 min 就得出了正确的技术结论（"这个耗时本身说明内核权重网格不适合当前 220 原子全各向异性模型"），却因为模板与项目约定写着"慢≠卡死；绝不杀子进程、绝不绕开工具"而继续等了 40 min（78.9 / 82.9 / 102.9 / 120.4 min 四段原话都在引用这条规则）。根因仍是工具没有心跳、没有 detach、没有给任何可判断的证据；但规则的措辞把"不要杀进程"写成了"不能放弃调用"。同一段还有一条**工具消息压过模板规则**的实例：模板说"采纳 SHELXL 建议用 adopt_wght，不要手动循环"，而 `element_scan` 的 readiness 提示写着 "set_weights from run_shelxl's suggested_wght (or optimize_weights)"——全栈臂选了工具指的那条路；纯工具臂没读到这句，用 `adopt_wght` 17 s 完事。
- **纯工具臂 16 次失败里 8 次同根**：`add_hydrogens` 生成的 AFIX 与 SHELXL 的连通性判断不一致，`add_hydrogens` 自己不报错，错误到下一次 SHELXL 才炸、每次只暴露一个坏载体，逼出 6 轮 `add_hydrogens(exclude=[…逐个追加])` → `run_shelxl` 的锯齿（约 12 min）。全栈臂也撞到一次后撤回了 H。
- **纯工具臂没用的工具**：`probe_site` 0 次（它在纯工具模式下是可用的）、`compare_nodes` 0 次、`situation_report` 1 次、`view_structure` 6 次但从未看堆积（全是 asu）；全栈臂交付前专门看了超胞三个方向。这是"没有工具图谱"的代价：它不知道哪个工具是问"有没有/是什么"的正确入口。
- **SHELXT 预算规则的一个反例（混杂）**：纯工具臂违反 v32"n_phase_sets 绝不加大"（200 → 600 被 schema 拒 → 500），best CFOM 单调上升 0.636 → 0.689 → 0.731；但同批还改了 composition（加 Zr）与 `space_group=`，工具的超时诊断也明说"CFOM 低于录取线时改搜索不改预算"——说明**规则的措辞把三件事捆在了一起**，不能读成"规则错了"。两臂都没踩到预算陷阱（无作业被超时杀）。
- **判读**：cage 上全栈臂更好（R1 低 0.06、掩膜做了、模型移植复现参考），可归于知识层的是两条**流程纪律**：定群协议（一次拿全劳厄类，别被解的 R 值牵着走）与掩膜纪律（骨架完整再掩、失败别删原子重算、别丢掉收敛的掩膜）。可归于工具层的更多：吸收边识别（两臂靠工具）、低对称逃逸纠错（工具判词）、`element_scan` 自由占有率失效、ghost 判据在纹波上失灵、温度默认值污染、`diagnostic` 被 finalize 拒收、`optimize_weights` 无预算。

---

## 5. 执行层分析：错在哪、偏向哪、在哪打转、哪些工具不好用

（待补机械统计与核读；以下是发射期间现场已确认、不依赖核读稿的事实。）

### 5.1 平台缺陷（与臂无关，任一臂都会中）

1. **codex 超时不取消服务端计算**（org-tools-r1，17:03 实测）：`solve_charge_flipping` 跑到 codex 工具硬超时 3 900 s 后，MCP 工作进程 CPU 仍在涨（3 994 s → 15 s 后 4 011 s），项目锁被它占住；agent 后续的 `run_shelxt` 与所有监测调用排在锁后，`QUEUE_MAX_S = 1 800 s` 到期只会得到 "gave up waiting"。一次调用拖垮整格。
2. **求解工具预算不对称**：`run_shelxt` 有 grace / detach / job_status 三件套并把预算钳在 500，`solve_charge_flipping` 无上限、无 detach、无心跳，接受了 8 种子 × 20 次 × 5 000 迭代。
3. **SFAC 未暴露**：start.ins 有 `SFAC C H N O`，摄入后会话没有元素清单；`run_shelxt` 报 "no element list available - pass composition='C H N ...'"——纯工具臂把它读成"SHELXT 不可用"。信息其实在文件里。
4. **消光反射缺失时的报法**：`screen_space_groups` 逐群报 `no_absence_conditions`，没有一句"本数据不含消光类反射，无法用消光判群"。
5. **规格缓存键**（发射前修掉）：tools/list 缓存按代码指纹、不看进程模式。

### 5.2 评分器问题（本次暴露，已修）

- `chemistry_flags (b)` "羧酸形 N" 对酰胺 N 假阳性（org-full-r1）：规则缺"X 须为端基（恰一个重原子邻居）"条件；已加并附羧酸/酰胺/酰亚胺三用例。残余：未取代伯酰胺只看重原子仍是端基 N，几何上不可区分，不特例。
- 新加的两项在本战役里都被用到：`r1_delta` 先比 d_min（hex/cage 全部"不可比"，改按绝对 R1 判；org 可比）；porosity 旗标改读 PLATON 601/602/604/605（cage-tools 的 602 被读到，cage-full 有掩膜块不触发）。

### 5.3 机械统计（`ka1_report` / `campaign_analysis`，六格合计 1 891 次工具调用、39 次出错）

**泄漏审计与路径线索**：六格均无 mentor 侧路径触碰、无祖先 AGENTS.md 注入、模板哈希全部匹配（附 A）。结果可用。

**出错率最高的工具**（合计；出错的格数/调用过的格数）

| 工具 | 调用 | 出错 | 出错格 | 出错内容（核读确认） |
|---|---|---|---|---|
| `solve_charge_flipping` | 4 | 3 | 3/4 | org-tools：无上限预算跑到 codex 3 900 s 硬超时；hex/org-full：不收敛/拒跑，秒级返回 |
| `optimize_weights` | 1 | 1 | 1/1 | cage-full：无参数调用，221 原子模型上迭代到 3 900 s 硬超时，**第二例"长计算 + 客户端超时不取消"** |
| `finalize_delivery` | 8 | 4 | 4/4 | 四个交付格首次调用一律被门拒（"blocking (fix, or waive by id with a reason)"：A 级 183/184/185/699 元数据 + 020/023/082/084），第二次带 waive 通过。**设计如此**，但盲态战役里元数据 A 警报必然存在，每格都要走一遍"拒 → 逐条 waive"的两步仪式 |
| `solve_superflip` | 6 | 3 | 2/4 | "superflip did not converge"（org 两臂各遇到；错群/合并数据下都不收敛） |
| `element_scan` / `probe_site` | 8 / 7 | 3 / 2 | 1/3 | cage-full 的元素扫描超预算/候选拒绝（细节见核读稿） |
| `solvent_mask` | 22 | 6 | 2/4 | cage 两臂：掩膜发散/负密度丢弃/与建模客体互斥（cage-tools 最终交付未掩膜，PLAT602） |
| `get_project_brief` | 16 | 1 | 1/6 | org-tools：`gave up waiting after 1805s: 'solve_charge_flipping' (running 7545s so far) is still executing`，一个只读的状态查询被锁在长计算后面 30 分钟 |
| `import_frames` | 1 | 1 | 1/1 | hex-tools 对只有 hkl 的目录调了帧路线入口（"no scan frames recognised"），一次即纠正，纯工具臂在没有工具图谱时的探路成本 |
| `run_shelxl` | 51 | 4 | 2/5 | 作业级失败（细节见核读稿） |

**累计耗时最高的工具**：`solve_charge_flipping` 3 991 s（4 次，几乎全在 org-tools 那一次）、`refine` 3 928 s（44 次，cage 大结构正常）、`optimize_weights` 3 900 s（1 次，即超时那次）、`ghost_test` 2 238 s（24 次）、`get_project_brief` 1 930 s（16 次，**其中 1 806 s 是排队**）、`run_shelxt` 1 833 s（88 次，含分离作业轮询）、`element_scan` 1 157 s（8 次）。

**"原地打转"信号的甄别**：机械统计把 `run_shelxt` 同参数重复 53 次列为打转之首，但其中大部分是 `run_shelxt(job_status=<job>)` 对分离作业的**合法轮询**（模板 v31 教的做法，纯工具臂 cage 格也自己这么做了）；`run_shelxl` 同参数重复 21 次（cage-tools 8 + 6）和 `checkout` 11 次、`inspect_model` 8 次才是需要人读的候选。真正的原地打转是 org-tools 的 51 分钟"继续等待锁释放"（agent_message 55 条中约 50 条是等待语，期间零工具返回），这不是模型不会判断，是平台没给它任何可行动作。

**参数试错**：`run_shelxt` 28 种参数组合（两臂都在 cage 上反复调 n_phase_sets / timeout_s / composition / space_group），`probe_site` 3 种。

**shell 危险用法**：未见 `Get-Content` 无 `-Encoding`、多行 `python -c` 等已知坏习惯。

**平台级"僵死"三例的共同形状**：`solve_charge_flipping`（org-tools，65 min）、`optimize_weights`（cage-full，65 min）、`get_project_brief` 排队 30 min（org-tools）。三例都不是模型判断失误本身造成的损失上限，而是**工具没有预算钳制、没有心跳、客户端超时后服务端不取消、后续调用全部陪葬**。这是本实验最大的工具层发现，两臂都中。

---

## 6. §2.4 决策规则的建议

计划 §2.4 预设了三种结局。本实验的结局是第二种，**A 在某些类别的事上系统性输，且能指名**：

| 类别 | 证据格 | A 输在哪 | 这条是不是知识层能防的 |
|---|---|---|---|
| 求解预算与"猜占位组成"的许可 | org-tools（no_delivery） | 把 SHELXT 的 composition 报错读成"数据缺陷"，转投无预算的电荷翻转 | **一半**：许可是模板给的（"占位 C H N O 不是元素证据"）；但败因（无预算、不取消、SFAC 未暴露）是工具层 |
| 定群协议 | cage-tools（75 min Pc 长征） | 只查一个劳厄类，被解的 R 值牵着走 | **是**：卡上的"laue_group='all' 一次拿全、榜单是证据不是判决"直接对应 |
| 掩膜纪律 | cage-tools（4/4 败、PLAT602） | 删原子后立刻掩膜；失败后盲改参数；重建后不再重试 | **是**：卡上的三条对应；但工具失败消息里已经写了同样的话，agent 第一次没读进去 |
| 元素身份（吸收边） | hex/cage 两臂 | 无差别 | 否：知识在 `audit_heavy_sites` 返回里 |
| ghost/real 处置、诚实门、泄漏、禁令 | 六格 | 无差别（两臂都干净） | 否：诚实守则 + 工具闸门够用 |
| hex 全流程 | hex 两臂 | 无差别，A 多付 14 min 工具探路 | 否 |

**建议（供主人拍板）**：

1. **模板 v33 走"只留能指向失败格的规则"路线**（§2.4 第二档），不做 §4 C-条件里的三张新卡与 v34 修正性重写。保留并改写成证据式的规则只有三组：(a) 求解预算与组成，"SHELXT 需要组成串；占位组成可以猜但不是元素证据；任何求解调用先看有没有 detach/预算，没有的一律用小预算试探"（指向 org-tools）；(b) 定群协议，"一次拿全劳厄类，解的 R 值不是群的证据，`check_symmetry` 在采纳前跑"（指向 cage-tools 75 min）；(c) 掩膜纪律三句（指向 cage-tools 4/4 与 pa2 cage）。其余判断内容（质量标尺、大段元素身份规则、GooF→1、案例常数）删除或降为工具返回文本。**理由**：hex 证明在"工具说实话"的地方模板没有增量；org/cage 证明模板增量集中在流程纪律，而不是晶体学判断。
2. **操作契约要加一句**：长计算可分离、可放弃、可换预算重发；"不杀进程"不等于"只能干等"。org-tools 51 min 的空等与 cage-full 65 min 的空等（后者在 91 min 已判定工具不适用，却因"慢≠卡死、绝不杀子进程"又等了 40 min）都是这一句缺失的直接代价，不是模型的问题。这也是六格里**唯一一处模板措辞明确造成损失**的地方，v33 必须改写这条。
3. **技能卡保留按需可读，不进模板指针**（hex 的 tools_only 臂在工具返回里 ≥6 次被指向 read_skill 却找不到工具，说明工具层已经在替模板做指针的事）。三张新卡不做；把 org/cage 暴露的知识写进**工具返回**（吸收边已在；补"omit 电子数在不完整模型上系统偏低"、"消光反射缺失时如何判群"两句）。
4. **先修工具层再谈知识层**（§7 P0）。本实验最大的损失（org-tools 全格、cage-full 65 min、hex-tools 14 min）全部来自工具层：无预算求解、客户端超时不取消、SFAC 未暴露、`element_scan` 自由占有率失效、温度默认值污染、`diagnostic` 被 finalize 拒收。这些修好之前，任何新一轮消融的结果都会被它们淹没。
5. **要不要加重复格**：hex 两臂之差 0.0016 在噪声内、cage 两臂之差 0.06 且模型移植判语不同、org 是零对一。结论方向不依赖重复；但若要给"模板 v33 收缩后没有回退"一个数字，应在 v33 落地后用 ext2 五格 + hex/cage 各一格做回归，而不是重跑 ka1。

---

## 7. 优化点清单（按"知识层能防的"与"工具层必须修的"分列；每条附证据格）

### 7.1 工具层必须修（任何臂都会中）

**P0（本实验直接造成整格或小时级损失）**
1. **长计算的取消与预算**：codex 客户端超时后 MCP 服务端要能取消当前调用（或至少释放项目锁并标记作业为孤儿）；`solve_charge_flipping`、`optimize_weights`、`refine(anisotropic)` 等无上限计算补 `timeout_s`/detach/job_status/心跳，与 `run_shelxt` 同形；`QUEUE_MAX_S` 到期的调用应返回"锁被 X 占用 N 秒，可用 abort=true 放弃"而不是让 agent 干等。证据：org-tools 65 + 30 min；cage-full 65 min；`get_project_brief` 排队 1 806 s。
2. **SFAC 暴露 + `run_shelxt` 报错改写**：摄入 ins 时把 `SFAC` 作为"披露的元素猜测"写进会话；报错改为"ins 声明了 SFAC C H N O（UNIT 为占位），如确认化学请传 composition='C H N O'"。证据：org-tools 2.10 min、cage-full 因未传 ins 也撞到同一条。
3. **`element_scan(free_occupancy=true)` 疑似失效**：跨两臂三次调用每一行 occupancy 恰好 1.000、Ueq 同值，同位点 `probe_site` 却能精修占有率。先写复现测试再修；直接导致 cage-tools 把 Cl 标成 O。
4. **实验温度默认值污染 CIF**：`set_experiment(temperature_K=null)` 回复"CIF 将写 ?"，实际两份 CIF 都写 `293(2)`（SHELXL TEMP 默认被装配）。修 CIF 装配 + 修回复文本。证据：hex 两臂、cage 两臂。
5. **`diagnostic` 状态与 `finalize_delivery` 的设计矛盾**：诚实地标 diagnostic 就拿不到 MANIFEST 封存（SUMMARY/VALIDATION/checkcif.json 不进哈希清单），标 final 则要 23 条披露式豁免把"不能发表"升成 final。让 finalize 接受 diagnostic 并在 MANIFEST 里明记状态。证据：cage 两臂。

**P1**
6. `solvent_mask` 失败消息里的 rule 已经写对，但纯工具臂第一次没读进去：把"不要删原子后立刻重算"做成**守卫**（同一步内有 delete 且无成功掩膜时先拒绝一次并给出对照建议），并在重建/换群后主动提示"骨架已完整，可重试掩膜"。证据：cage-tools 4/4 败、重建后 0 次重试。
7. `ghost_test` 对距重原子 < 1.1 Å、Uiso ≤ 0 的位点直接判"纹波，非原子"，不进 real/inconclusive；判据在本晶体 113 位点 0 ghost，无判别力时应直说。证据：cage-tools 96 个 acknowledge_real 删除。
8. `integrate_difference_density` / `probe_site` 在 R1 > 0.15 的不完整模型上给出"omit 电子数系统性偏低约一半"的校准句；候选元素表自动包含合成常见卤素。证据：cage 两臂 3 个 Cl 标 O。
9. `screen_space_groups`：消光类零观测时区分"该群无条件"与"有条件但数据里没有这类反射"（后者在 fcf 反推数据上是螺旋轴的阳性指纹），并加一句"本数据无法用消光判群"。证据：org 两臂。
10. `change_space_group` 剥掉带基矢注记的群名（`(a+1/4,b,c-1/4)`），否则 CIF `_symmetry_space_group_name_H-M` 为空、逼 agent waive A122。证据：org-full。
11. `run_shelxt` 描述把"n_phase_sets 不是相位集数、默认不传、CFOM 低改搜索不改预算"三件事分开写；`n_phase_sets=300` 让 per-try 时间翻三倍的代价在描述里写明。证据：hex-tools 558 s、cage-tools 反例。
12. `mask_obligations` 里的 `coordination_encroachment` 要成为交付前必清偿项（进 finalize 门），否则 Zr CN = 10 这类旗标一路带到评分。证据：cage-full。
13. `add_hydrogens` 生成的 AFIX 要在**放置当场**用 SHELXL 的连通性规则自检并一次列出全部坏载体，而不是让下一次 `run_shelxl` 每次炸一个（cage-tools 8/16 次失败同根、约 12 min 锯齿）；矛盾警告与 `}}` 排版错字；AFIX 崩溃后的撤回路径。证据：hex 两臂、cage 两臂。
13b. `element_scan` 的 readiness 提示不要把 `optimize_weights` 与 `adopt_wght` 并列推荐（模板说前者不要手动循环，工具消息说"or optimize_weights"，全栈臂听了工具、掉进 65 min）；工具消息与模板冲突时以工具消息为准是本实验反复出现的行为，所以**工具消息必须与模板同源审校**。
13c. `campaign_analysis` 把 schema 层的 `Input validation error` 计入工具错误（cage 漏计 3 次），并把 `run_shelxt(job_status=…)` 轮询从打转/试错里排除。

**P2**
14. `campaign_analysis` 把 `run_shelxt(job_status)` 轮询记成打转/试错，按 job_status 参数排除；`run_shelxt(job_status, wait_s=)` 让一次调用阻塞等待而不是 60 s 轮询一次。
15. `import_frames` 对只有 hkl 的目录给出"这是厂商 hkl 路线，请用 ingest_vendor_data"。证据：hex-tools。
16. `reflection_statistics(laue_group='all')` 也给按劳厄类的 E 统计；`friedel=null` / `wilson.skipped` 给原因。证据：org。
17. 评分器：`model_transplant` 对非标准设置 + 反演后的原点/手性对齐疑似错（org-full emma 13/13 rms 0.001 Å 却报 R1 0.4227"模型不同"）；runner 在主回合被中断时没有收割 rollout 里已有的收尾结论（org-tools verdict.json 只剩 `{"unparsed": …}`）。

### 7.2 知识层能防的（写进模板 v33 或工具返回）

- **求解预算与组成许可**（org-tools）：一句"占位组成可以猜、不是元素证据；求解调用先看预算与分离能力"。
- **定群协议**（cage-tools）：`laue_group='all'` 一次拿全；解的 R 值不是群的证据；采纳前 `check_symmetry`。
- **掩膜纪律**（cage-tools）：骨架完整再掩；失败后不删原子重算；不丢收敛的掩膜；重建后重试。
- **长计算的操作契约**（org-tools、cage-full）："不杀进程"≠"只能干等"：分离、放弃、换预算重发都是合法动作。

### 7.3 两臂都没做到、任何层都没防住的
- hex：参考里 1/8 占有的溴代芳基客体两臂都掩掉，都没做电子数检验，候选元素表没有卤素，全栈模板明文有这条、全栈臂没执行；说明**模板里的规则不等于执行**，工具侧的义务清单（`integrate_difference_density` 进 finalize 门）比模板句子可靠。
- cage：3 个 Cl 两臂都标 O（见 7.1-3、7.1-8）。

---

## 附 A. 运行记账

（由 `ka1_report` 草稿"附：运行记账"节复制并核对。）

## 附 B. 本轮改动清单

- 发射前（tag `pre-ka1`）：根 AGENTS.md 指针；knowledge_mode 开关与三态 ensure；runner 记账；EADP 文案；ka1 清单与 org 分装；规格缓存键；MCP 启动证据行；评分器 PLATON 空洞回读 + r1_delta 分辨率对齐；ka1_report 生成器。
- 战役期间在 worktree 完成、cage 结束后合并（tag `ka1-done`）：评分器酰胺假阳性修复；T1.1 SHELXL .lst 回读（warnings / variance_analysis / disagreeable_reflections / 限制残差 3σ / shift-esd 四方向 / situation_report 两条掩膜冲突）；模板长度守卫去路径耦合。

## 补记（2026-09-04 凌晨）：分析工具修正后的三处改读 + 一个事后发现

分析管线（`campaign_analysis` / `ka1_report`）修了三个缺口后重新出机械稿（`KA1-ANALYSIS-draft.md` 已整体替换），结论不变，但三处读数要改：

1. **"原地打转"被高估**：hex-tools 原计 10 组重复调用，其中 9 组是 `run_shelxt(job_status=…)` 对分离作业的轮询（2 个作业共 11 次、覆盖 641 s、平均 55–73 s 一次，正是工具契约写的 60–120 s 节律）。轮询现在单列为"等待"，真正的打转只剩 1 组。cage-tools 同理：29 次轮询覆盖 1 327 s 是等待，不是转圈。
2. **schema 拒绝此前不可见**：MCP 层在执行前挡下的调用（`Input validation error`）原先没计入。cage-full 工具错误 9 → 11，多出的 2 次是 `compare_nodes` 缺必填参数 `a`；cage-tools 有 1 次 `run_shelxt(n_phase_sets=600)` 超上限 500 被拒。这类拒绝与工具好不好用无关，只说明**参数面难调**：它们现在进工具易用性排名并单独加权。
3. **org-tools 的收场性质改判**：原记录把中断时 agent 最后一句话（"状态无变化：原求解仍在运行，没有新节点或错误。继续等待。"）当作 verdict 存了下来。重评后标为 `interrupted_before_verdict`：主轮被 runner 按 7200 s 超时中断，任务目录里只有 1 个文件、没有 final.cif/final.fcf，verdict 无处可收。这与"agent 交付了 nothing 且自己承认"是两种不同的失败，现在能区分了。

事后发现（详见 `ka1-notes-live.md` 2026-09-04 段与 `crystalpilot/mcp/CANCELLATION_NOTES.md` §(d)）：org-tools 那格的 MCP 服务进程在 codex 退出后仍持续满转一个核，到次日凌晨累计 518 CPU 分钟。它证实 §3.2 的"服务器继续计算"不只是墙钟损失，还是机器资源损失；根因是服务器不感知 stdio 客户端消失。修复已入 main（transport watchdog，a5edf6c）。这个案例也把"慢≠卡死、绝不杀子进程"那条模板规则的代价补全了：v33 已把它改成"预算内等、超预算记 unresolved 换路径"。
