# CrystalPilot 升级规划（2026-09-03，接手核实 + 自主排序 + 知识层消融对照）

> 交付：批准后先把本文原样落盘为 `docs/PLAN-2026-09-03-upgrade.md`（中文），再按 §6 顺序动手。
> 规划阶段只做了只读核实与轻量探针（grep、venv python 量字节数、读 codex 会话记录），未改代码、未跑战役、未跑 pytest。
> 三个只读审计子代理与一个规划子代理的结果已并入；项目主人 2026-09-03 的六项拍板见 §5。

---

## 0. 一页结论

1. **先做一个对照实验，再决定知识层要不要扩建。** 项目主人的担心（系统越来越依赖技能卡与内置阈值、压住基模自己的判断）与仓库自己的证据同向：pa1 结论"提示词信息量不是杠杆（L0–L2 全在噪声地板内）"、pa2 §8 "纪律越具体越容易被机械执行"、过程审计"agent 判断力非瓶颈，大头是工具说错话"。但**真正的"只给工具"臂从未跑过**: AGENTS 模板每回合都在。所以第一阶段是 **阶段 A：知识层消融**（3 晶体 × 2 臂 × 1 重复 = 6 格），结果决定阶段 C 的知识层工作做多少。
2. **分析稿列的五个泛化缺口全部仍在**，行号基本吻合；但两条形状不同：M–C 2.15 Å 只伤 σ-M–C（η 环早有通道）；`run_shelxl` 四参数背后已有受审计的 `data_cards` 通道（`set_resolution_limit` 是完整原型）。
3. **根目录 `AGENTS.md` 是活的上下文污染源，且只污染战役臂**：被 `.gitignore:69` 忽略、无标记、教已删的 CLI 后路与零免责 MOF 标尺；Codex 0.147 把 git 根到项目目录的 AGENTS.md 全部注入（pa4 7/7 会话首条 user 消息同时含根文件与 v31 模板）；战役项目在仓库内 `workbench/pa*/` 所以中招，仓库外真实项目不会，**pa1–pa4 与真实用户跑在两套上下文上**。这必须在阶段 A 之前修掉，否则两臂都被污染。模板 + 根文件 = 29 568 B，离 32 KiB 上限余 3.2 KB；字符守卫余 32 字符。
4. **分析稿三处与代码不符**：吸收边检查**已存在**（`tools_heavysites.py:179-226`）；评分器 R1 悬崖**已修**（`grade.py:1743-1744`）；`add_hydrogens` **已发 AFIX 147**。另两处不精确（FVAR 可经 `model_disorder`；Hirshfeld 缺检验不缺约束）。
5. **与知识层无关、任何实验结果下都该做的工具侧改动**：让已有证据被读到，SHELXL 成功作业的 `** WARNING` 被整段丢弃（`tools_shelxl.py:334-340`）、K 表/most disagreeable/限制残差>3σ 没回读、|E²−1| 只有一个数且无 ⟨I²⟩/⟨I⟩²、`screen_space_groups` E 统计与消光表不交叉、`connectivity.py:583` 把"没检查"编码成 `True`。这些是"工具说实话"，不是"教模型怎么想"，与主人的方向一致。
6. **知识层的现存问题**（八处矛盾、`read_skill(section=)` 丢免责、`save_skill` 抹溯源字段、模板"GooF→1"与手册相悖）中，**矛盾清理与错误纠正照做**（错的东西不该留在任何臂里），**扩建（三张新卡、模板重写）等阶段 A 结果**。
7. `data_ext2` 九个参考 fcf 复算 ≤0.002、18/20 格从未跑过；`org_hsl` 进阶段 A，其余五格作阶段 D 泛化门禁（主人已定）。
8. 基线更正：pytest **1154 passed / 1 skipped**，不是约 574。

---

## 1. 现状核实报告（逐条对照分析稿 §0，以代码为准）

### 1.1 五个代码缺口 + 三处文本问题

| # | 分析稿论断 | 核实 | 证据 |
|---|---|---|---|
| ① | `chem/knowledge.py` 自述 MOF 表；缺表金属 CN 静默通过 | **仍存在** | `knowledge.py:1`；37 个 MetalProfile（`:22-51`）无 `source`；`connectivity.py:583` `ok_cn = prof is None or …` |
| ② | M–C 上限写死 2.15 Å | **仍存在，比分析稿说的窄** | `connectivity.py:153-156`；η 环 1.85–2.85 Å 通道（`:31-36`、`:540-556`）+ `chem/metal_bonded_audit.py` 通用规则已识别 Cp/芳烃/羰基/NHC；漏的是 >2.15 Å 的 σ-M–C |
| ③ | 无金属则峰全判 C；N 预算死代码 | **仍存在** | `model_tools.py:156-157`、`:166-174`；`n_budget` `:162` 无引用；`chem_hint` 只两条 MOF 规则（`refinement_tools.py:73-82,133-159`） |
| ④ | `run_shelxl` 只 4 参数，EXTI 等不可达 | **仍存在，但有现成通道** | `tools_shelxl.py:447-464`；`data_cards`：`shelx_model.py:202-204`（只收 SHEL/OMIT/MERG/EXTI/SWAT）→ `project.py:196-197` → `nodes.py:485,671` → `shelx_writer.py:348-351`；`set_resolution_limit`（`tools_shelxl.py:2913-2979`）= 必填 reason + 幂等替换 + 反空操作守卫；`set_restraints` 8 kind（`restraints.py:23-25,38-41`）；FVAR 可经 `model_disorder`（`nodes.py:456-472`） |
| ⑤ | 三分类有代码无卡 | **仍存在** | `validation_tools.py:37-58`；20 张卡零 molecular/salt/organometallic；6 张 mof-/framework- 卡（分析稿说 4） |
| 文① | 根 `AGENTS.md` 旧版、不刷新 | **仍存在，且是活的** | `AGENTS.md:15` CLI、`:40-42` 标尺；`.gitignore:69`；`codex-home/sessions/2026/09/03/` 7/7 命中；codex-cli 0.147 系统提示："AGENTS.md at the root of the repo and any directories from the CWD up to the root are included"；`core.py:74-83` 无抑制项；`projects_root` 在仓库内（`pa1_manifests.py:24`、`agent_campaign.py:20`）；`ensure_agents_md`（`agents_md.py:384-386`）按当前标记重写，但**无标记的用户手写文件会被静默覆盖** |
| 文② | `agents_md.py:305-309` 零免责标尺 | **仍存在** | 与 `:263-265` 并存；根文件 `:40-42` 另有英文版 |
| 文③ | 技能卡互相冲突 | **仍存在，不止一处** | §1.2 |

### 1.2 知识层追加发现

- **八处矛盾**：(A) `framework-solve-ladder.md:67-76` R1<0.25 禁回阶梯 vs `data-ingest-space-group-protocol.md:46-47` / `framework-twin-pseudosymmetry-alarm.md:50-54` / `hklf5-twin-workflow.md:57-58`；(B) `mof-guest-evidence-rule.md:34` "<5–10% = 假客体" vs 同卡 `:39-41` vs `expert-cases/disorder-ruleset.md:271-275,402-404`；(C) `mof-solvent-mask-discipline.md:83-89` vs 同卡 `:14-33`，已升进模板 `:284-285`；(D) `agents_md.py:277-278` "每个片段必须与主片段直接成键"对盐/共晶错，语料原意（`review-response-ruleset.md:181-182`）是"无游离原子"（守卫 `test_agents_md.py:90` 只锁标题四字）；(E) `framework-restraint-idioms.md:68-70` vs `:35` vs `disorder-ruleset.md:389`；(F) 截断 advisory vs `hklf5-twin-workflow.md:159-160` + 模板 `:215-217`；(G) 电荷翻转两卡相反；(H) 权重时机两卡相反；模板 `:205/:307` "GooF→1" 与知识库 §17.4 相悖。
- **schema 与工具**：20 张卡无 scope/aliases/generalization_reviewed；expert-cases 用 `symptom` 旧 schema，`save_skill`（`tools_skills.py:464-473`）会抹掉 case/refs/practice_data；`list_skills` 只搜 name+description+tags+aliases（`:165-168`），aliases 零使用，同义环（`:126-149`）无 SHELXL 指令名；`read_skill(section=)` 不返回 frontmatter（`:353-362`）而模板 `:332-333` 鼓励按节读。
- **模板案例常数**：`:154`（0.125）、`:291`（0.68883/Zr）、`:300-302`。
- **预算**：模板 13 968 字符 / 26 117 B（守卫 <14000 字符）；根 3 451 B；合计 29 568 B vs 32 768。
- **战役结果不记知识版本**（`agent_campaign.py:253-256` 只记 model/effort）。

### 1.3 工具层追加发现

- `tools_shelxl.py:334-340` `**` 行只在硬崩时读；无 K 表、无 Most Disagreeable（`:270-296` 只解析限制，`:287,:295-296` 有比值无判词）；无 Hooft。实测 `.lst`（thiourea 帧集 `work/*.lst:441-462`）含 K vs Fc、K vs 分辨率、逐壳 R1、Most Disagreeable。
- 强度统计：`sg_screen.py:61-83` 单值；无 ⟨I²⟩/⟨I⟩²；`tools_analysis.py:756-799` 三条失效条件只实现一条；无 L-test；无 Patterson tNCS。
- `screen_space_groups`：三态（`absence_test.py:40-84`）好；E 统计与消光表不交叉（`sg_screen.py:107-178`）；`situation_report.conflicts`（`tools_analysis.py:2060-2071`）只两条。
- `check_symmetry` 无风险分级（`tools_symmetry.py:526-555`）；`change_space_group` 格心更严（`:632-669`）与共识相反。
- `system_type` 消费点全部不看：`mask_tools.py:41-43`、`tools_heavysites.py:995-1073`、`compute_confidence`（`validation_tools.py:78-124`）、`tools_deliver.py:471-514`、`grade.py`；`classify_system`（`connectivity.py:362-420`）模型不完整时给 unknown。
- 吸收边：`tools_heavysites.py:179-226` 已有表驱动检查；只在 `audit_heavy_sites` 内；`shelx_writer.py:204-258` 自动 DISP。
- `model_disorder`：二位点（`tools_disorder.py:515-520`）；无 s.u.（`tools_shelxl.py:603-605`）；无撤销；`:565-566` "SIMU is the platform equivalent (EADP)" 错。
- `add_hydrogens`：147 已发（`shelx_writer.py:45`），无旋转/受体扫描、无 148、无漏 H 正峰检测。
- `ghost_test`：灵敏度地板（`tools_batch.py:292-343`）范例；`real` 处置（`:109-113`）无非化学实体分支；"密度归谁"无单一裁决点。
- 求解门：`solution_tools.py:42-62` <70% 完整度门（有本平台 0/6 台账）；无 1.2 Å 披露；`estimate_resolution` 输出无人消费。
- 评分器：`grade.py:1743-1744` 悬崖已修；`evaluate_refinement.py:221` 仍绝对门；Class IV 只元素门（`grade.py:1707`；`evaluate_refinement.py:214` 有 H 计数）；`grade.py:594` 30% 是唯一 checkCIF 复写；**`r1_delta`（`:1729-1745`）不核对 d_min**；`evaluate_refinement.py:205-206` honesty_pass 需审。
- `scale_and_export` 4 参数；剔除前无 tNCS 检查。三套能力集合（MUTATING/READ_ONLY/SESSIONLESS）已有子集、互斥、穷尽三重不变式守卫（`tests/test_skills.py:200-255`，规划稿原句"无一致性测试"是错的，2026-09-03 迟到审计更正）；无人看守的是旧 agent 路径的第四套 `GATED_TOOLS`（`crystalpilot/agent/crystal_agent.py:89-91`）。

### 1.4 基准与测试

- pytest **1154 passed / 1 skipped**（`workdir/_pytest_full_pa4merge.log`）。
- `data_ext2` 九案例 fcf 复算 ≤0.002；`data_frames` 九套帧只到 `dials.import`；29 份战役清单穷举 **18/20 从未跑过**。
- 战役 runner：manifest `defaults`/case 支持 `model_override`/`effort_override`（`agent_campaign.py:247-250`）并写进项目设置；提示阶梯 L0–L3（`pa1_manifests.py:28-96`，L0 = "数据目录 + 请解这个结构"）；模板注入点 `core.py:127`；技能工具注册点 `registry.py:90-95`（与专家子代理同形，可按项目开关）。
- 待办来源：`PA4-ANALYSIS.md §7`、`PA2-ANALYSIS.md §7/§12`。

---

## 2. 阶段 A：知识层消融对照实验（第一阶段）

### 2.1 假设与我的判断

- **假设**（项目主人）：基模（gpt-5.6-sol @ xhigh）自己的推理足以解结构；技能卡与内置阈值可能压住它。
- **支持证据**：pa1 L0–L2 全在噪声地板内、L3 只影响元素身份；pa2 hex L0 两格 publication 而 L2 一格进 R-3 陷阱，cage L0-r2 的 Zr 处理比 L2-r2 好；过程审计判断力非瓶颈；本规划 §1.2 的八处矛盾说明知识层自身并不一致。
- **反向证据**：v28 记录 4/32 格因"后备 CLI"条款丢掉工具面，**操作契约**是实证必要的；诚实守则的每条都对应过真实事故（为降 R 加/删原子、静默改群、编造元数据）；Müller/Clegg 说自动化对非常规结构失败，但那说的是规则化的自动化，不是强基模。
- **我的判断**：两臂都值得跑，且结果**很可能是"操作契约 + 诚实守则 + 说实话的工具"就够，判断内容大多不加分**。但这必须由实验说，不由我说。技能卡是按需读取的（不进每回合上下文），模板才是常驻，所以最有信息量的变量是模板里的判断内容。

### 2.2 设计

- **臂 A（纯工具）**：模板 = 操作契约 + 诚实守则，约 3 KB：数据在哪、工具面延迟加载（等 15 s 至少三次，三次仍空即结束回合）、凡产生/修改模型的步骤只走 MCP、交付流程（`run_shelxl(check)` → `write_outputs` → `run_checkcif` → `finalize_delivery` + SUMMARY/VALIDATION 位置）、不读凭据文件；诚实四条（不为降 R 删/加无化学依据的原子、不删数据降 R、不静默改群、不编造元数据与结构，判不定写 unresolved）。**零晶体学判断、零阈值、零技能指针**；`list_skills/read_skill/save_skill/delete_skill` 不注册；`run_checkcif` 不附 related_skills；工具描述文本保持现状（残余混杂，记入结论）。
- **臂 B（当前全栈）**：v32 模板 + 20 张卡 + 5 张案例卡（消融前先做 §3 T0-0 卫生，两臂同一基线）。
- **晶体**：hex（NU-1000 034A1，B 臂基线 pa3/pa4 publication 0.080）、cage（Zr₆ 笼，B 臂基线 acceptable 0.1405 / below_bar 0.2223）、`data_ext2/org_hsl`（手性纯有机 P2₁2₁2₁ R1 .0264，两臂都无历史）。提示一律 **L0**（"数据目录 + 请解这个结构"）。3 × 2 × 1 = **6 格**，两泳道并发（4 核 BelowNormal，一次一个战役）；两臂结果接近再加重复。
- **模型**：gpt-5.6-sol @ xhigh（与 pa4 同）。
- **判读**（导师侧，`grade.py` 不改口径）：等级 / R1 / 元素表 / 空间群 / 骨架与客体层复现率 / 最佳节点是否交付 / 诚实门 / tokens 与墙钟；另加**定性读 transcript**：A 臂有没有做诚实守则之外的、B 臂规则禁止的事（为 R 删原子、丢数据、静默改群、掩膜吞骨架），以及 A 臂自己想出了哪些 B 臂靠卡才做的事（截断依据、掩膜对照、元素证据链）。
- **记账**：每格记 `knowledge_mode`、`agents_version`、`agents_sha256`；结果目录 `workdir/campaigns/ka1-*`；分析稿 `KA1-ANALYSIS.md`（中文）。

### 2.3 前置改动（半天，知识中性）

- **消融开关**：manifest `defaults`/case 增 `knowledge_mode: full | tools_only`（照 `model_override` 的路径写进项目设置 `agent_campaign.py:247-250`）；`ensure_agents_md`/`render_agents_md` 按项目设置选模板变体（新增 `TEMPLATE_TOOLS_ONLY`，独立 `VERSION_MARKER_TOOLS_ONLY`）；MCP 进程经 `core.py:78` 的 env 收到 `CRYSTALPILOT_KNOWLEDGE_MODE`，`registry.py:90-95` 在 `tools_only` 时不注册技能工具，`tools_deliver.run_checkcif` 不附 related_skills；`test_agents_md.py` 的"每个工具在模板里"守卫对 tools_only 变体豁免技能四工具。
- **必须先做的卫生**（§3 T0-0）：战役 `projects_root` 移出仓库、根 `AGENTS.md` 改一行指针并纳入 git、结果记知识版本、字节守卫、`ensure_agents_md` 不覆盖无标记文件。否则两臂都吃到根文件。

### 2.4 决策规则（跑完再定阶段 C 做多少）

- **A ≥ B 且诚实门无回退** → 模板收缩为操作契约 + 诚实守则（v33 = 大删），技能卡只保留按需可读、不进模板指针，阶段 C 的三张新卡与模板重写**不做**，精力全部给阶段 B 的工具改动；用 ext2 五格再验一次。
- **A 在某类事上系统性输**（例如掩膜吞骨架、静默改群、SHELXT 预算失控）→ 只把**对应那条**规则留在模板，每条规则必须能指向它防住的失败格（v28 的写法），其余删；技能卡保留但改证据式。
- **A 明显输且失败分散** → 阶段 C 按 §4 全做，但每条判断内容仍改证据式、去案例常数。
- 无论哪种：§3 的卫生与"工具说实话"改动照做；§4 的矛盾清理与错误纠正照做（错的东西不该留在任何臂里）。

---

## 3. 阶段 B：与知识层无关、任何结果下都做的改动

（原 T0-0 与 T1 工具项；每项独立提交、独立回滚；**零新工具**：模板只剩 32 字符，新工具要付模板行 + UI 卡；唯一例外 probe_fragment，主人已批准提高预算。所有以 s.u. 为分母的判词附尾句"s.u. 系统性低估 1.5–2×（Linden §13.7），本比值是下限"。提交信息注明"泛化审查：判据通用 / 合成晶体覆盖 X 型 / 反例 Y"。）

**T0-0 预算与基线记账（0.5 天，阶段 A 之前）**：`agent_campaign.py:253-256` `_save` 加 `agents_version/agents_sha256/root_agents_sha256/knowledge_mode`；新战役 `projects_root` = `H:/CrystalPilot-campaigns/<name>`（不改旧 manifest；不放 `H:/CrystalPilotData/`，那里有参考文件）；根 `AGENTS.md` 改一行指针并从 `.gitignore:69` 取消忽略；`tests/test_agents_md.py` 增字节守卫 `template+root < 32768−2048`；`agents_md.py:377-387` 对"存在且无标记"的文件不写、返回并冒 warning（三态测试）；`grade.py:594` 30% 改读 PLATON 602，读不到报 `porosity: not_checked`；`tools_disorder.py:565-566` 文案改正。验证：新单测；全量 1154 不动；新 rollout 首条消息不含 "Typical quality bars"。

**T1.1 SHELXL `.lst` 回读补全 ★（1.5 天）**：`summarize_shelxl_job`（`tools_shelxl.py:353-419`）内增量，`parse_shelxl_warnings`（成功路径也读）；`parse_variance_table`（K by Fc / by 分辨率 / 逐壳 R1，方向判词：低 Fc 组 K≫1 → 弱反射 Fo² 系统偏高（孪晶/未建模弱散射），K≪1 → 消光/权重；K 随分辨率单调 → 尺度/衰减；K 平坦≈1 = 权重收敛）；`parse_disagreeable_reflections`（方向：Fo²>Fc² 多数=漏原子/客体，Fo²<Fc² 多数=消光/多余/过重；整数指标关系用 gcd 提示孪晶律）；限制残差 `over_3_sigma` 单向旗标 + Linden 正面验收（受限 s.u.≈同类未受限）；shift/esd>1.5 附四方向；Hooft（非心且有 Friedel 对时 cctbx 算，否则 `not_applicable`）；`situation_report.conflicts` 加"掩膜体积内有建模原子"、"ghost 台账 real 落在掩膜空腔"。依据 §2.7/§15.2/§17.4/§17.5/§13.4。验证：`tests/test_shelxl_lst_readback.py` 手写 `.lst`（健康态无旗标且不出"通过"字样；低 Fc 组 K=0.6→判词不提 GooF；Fo²>Fc² 8/10→漏原子；反例 Fo²<Fc² 8/10→相反；方差块缺失→`None`）；`data_ext2/twin_rz5267`、`twintrap_nm` 上 `run_shelxl(check)` 秒级探针带/不带 TWIN 看 K 表方向。

**T1.2 `interpret_peaks` 无金属分支 + 求解能力披露（1 天）**：`model_tools.py:156-174` 无金属时按 0.7 Å 球积分密度排序，**O vs C 按密度分档**（Z 差 33%），**C/N 不猜**（Z 差 17%，需收敛 Ueq），标 C 并返回 `element_uncertain`、启用 `:162` 的 N 预算作披露、逐原子 `element_confidence`；`chem_hint` 加有机语汇；`run_shelxt`/`create_start_model`/`solve_*` 加 `solution_capability` **披露块**（d_min、最重元素 Z、"直接法在 d_min>~1.2 Å 且无重于 Si 的原子时门槛显著升高；本平台在此区间无成功率记录，失败不等于不可解"），复用 `_completeness_guard` 文案骨架但**不拒绝**。依据 §4.2/§4.3/§15.10。验证：苯甲酸二聚体（O 指认、C/N 不猜）、DBU·HCl（Cl 非 metal 走无金属路径触发最高档披露）、Cu 桨轮（回归）、反例含 S 噻吩、反例 d_min=0.75 Å 无警示措辞；`org_hsl`/`orgdis_dbu` 分钟级探针。

**T1.3 `connectivity.py:583` 三态化 + `system_type` 下沉 + 金属判据通用化（2 天）**：`cn_plausible` 三态（单独 commit）+ `validate_structure` `cn_not_checked` info；`_bond_cutoff` 统一"共价半径和 + tol；profile 存在时覆盖并记 source"，删 M–C 2.15，η 环不动；`MetalProfile` 加 `source`（**不扩表**）；`mask_tools.py:41-43` 常数→按金属半径（**不按 system_type 分支**）；`compute_confidence` unknown 时加 `evidence_gap` 且 grade 上限 medium（unknown 继承最严）；`tools_heavysites.py:995-1073` 加 source 披露不改数值；`tools_deliver.py:471-514` 措辞按类型换词条目不变；`grade.py` 记 `system_type` 不进分。验证：Cu 桨轮链、二茂铁、**Ru(bpy)₃Cl₂**（无表→None+警报）、DBU·HCl、反例 Zr₆O₈ 核无配体（unknown 最严）、反例 Ru→Fe 对照；Zr–CH₃ 2.28/La–C 2.6 成键、Zr···C(羧酸) 2.5 不成键。

**T1.4 强度统计壳层化 + ⟨I²⟩/⟨I⟩² + 失效条件 + 定群冲突字段（1.5 天）**：`sg_screen.py:61-83` 加 `e2m1_by_shell`；`reflection_statistics` 加 ⟨I²⟩/⟨I⟩²、⟨F⟩²/⟨F²⟩、L-test，判词带方向且单向；`E2M1_FAILURE_CONDITIONS` 五条逐条按当前组成/数据判断，`hint_valid: false`；`screen_space_groups` 加 `conflicts` **不改排序不加超群先验**；`check_symmetry` 加 `risk`/`kind` 与按数据 d_min 的可靠性注记。依据 §0.2/§1.9/§16.11/§3.2/§3.6。验证：`tests/test_intensity_statistics.py` 苯甲酸二聚体 P-1；+50:50 孪晶（<2 且判词不含赝平移）；+半胞赝平移（>2 且不含孪晶）；Zr 特殊位置盐（`hint_valid=false`）；反例健康数据无"通过"字样；`twintrap_nm`/`twin_rz5267` 探针。

**T1.5 `run_shelxl(extra_cards=…, reason=)` + `set_restraints` 扩 kind（2 天）**：复用 `set_resolution_limit` 形状；白名单与 `shelx_model.py:202-204` **同源一个常量**（数据卡 OMIT/MERG/EXTI/SWAT/HOPE；shelxl-only 约束卡 EADP/EXYZ/SAME/SUMP/FREE/BUMP/NCSY；拒绝 HKLF/FVAR/WGHT/SHEL/LATT/SYMM/L.S./PLAN/ACTA 各带独立拒绝语）；EXTI+SWAT 互斥（硬）、SWAT+f_mask 互斥（硬）、其余证据式提示；`SAME` 进几何 kind（映射 SADI 组），`EADP/EXYZ/SUMP` 进 `SHELXL_ONLY_KINDS`，in-process `refine` 返回**显式列出未施加的 N 条**。验证：三型合成晶体真 SHELXL `L.S. 0`；幂等、反空操作、6 条拒绝、往返、"未施加"声明；`orgdis_dbu` 导入回读。

**T1.6 `model_disorder` 验收闭环（1.5 天）**：FVAR 值与 esd 回读、`free_variable: {value, su, informative}` + 判词（0.95(10) → revoke）、`undo=<group>` 清理、自动建议 SAME；三位点推后。验证：合成 CF₃ 无序有机物。

**T1.7 吸收边警告前移 + ghost 非化学实体分支（0.5 天）**：`set_experiment`/`get_project_brief` 复用 `anomalous_terms`；`ghost_test` `real` 加"层错平均/调制卫星/漫散射"提示分支。验证：三种元素/波长组合。

**T1.8 漏 H 正峰检测（0.5 天）**：`annotate_peaks` 加 `H_candidate`（C/N/O 旁 0.85–1.05 Å 正峰，按共价半径）与 `misplaced_H`；O⋯O/O⋯N 短接触提示。受体定向与 AFIX 148 推后。

**T1.9 评分器一致性（1 天，阶段 A 之前完成 d_min 对齐）**：`evaluate_refinement.py:221` 与 `grade.py:1743-1744` 同口径；H 计数门统一；**`r1_delta` 先核对 d_min/θmax，不一致标 `r1_delta_incomparable` 回退绝对 R1**；电荷平衡只记账；过程证据只进 `evidence_gaps`（主人已定不计分）；审 honesty_pass。验证：夹具 + pa4 四格 `--regrade` 等级不变。

**T1.10 probe_fragment（主人已批准；排在阶段 A 与 T1.1–T1.4 之后并行）**：`tools_probe.py` 新工具（SMILES/模板 + 锚 → 理想几何 → 取向扫描 → 共用自由占有率 + 统一 Uiso 诊断分支精修（掩膜前）→ occ/U/ΔR1/位点残差 → 判词）；字符预算 14000→约 14300 记录理由；UI 卡。依据 §6.5/§5.7。验证：合成含 0.1–0.2 占有客体的框架与分子晶体各一；反例不存在片段→not_supported。

---

## 4. 阶段 C：知识层（以阶段 A 结果为条件）

**C-固定（任何结果都做，错的东西不该留在任何臂里）**：
- 模板 v33 = 纯删除/纠错：`:305-309` 零免责标尺删除或改单向证据式；`:154/:291/:300-302` 案例常数移出模板（`:291` 与 T1.7 同批）；`:205/:307/:207-211` "GooF→1" 改 K 表判据（依赖 T1.1）；`:215-217` 改证据式。
- 技能卡矛盾清理（主人已批准四条条款改证据式）：`framework-solve-ladder.md:67-76` → 回头查群触发签名清单，删 0.25；`mof-guest-evidence-rule.md:34` → 崩塌行为判据，删 5–10%；`mof-solvent-mask-discipline.md:83-89` → 三分法末位，删"降 0.1"与"不要交付无掩膜"；`framework-restraint-idioms.md:68-73` → 先分单原子/全模型，RIGU 非覆盖式 SIMU；`:277-278` "ASU 连贯性"句 → "无游离原子 + 片段身份按 system_type"（保留标题四字）；`:284-285` → 三分法末位。
- 工具修正：`tools_skills.py:353-362` `read_skill` 恒返回 frontmatter；`:464-473` `save_skill` 改 merge 保留既有键；`:126-149` 同义环加 SHELXL 指令族；20 张卡加 `scope`/`generalization_reviewed`。

**C-条件（阶段 A 决定）**：三张新卡（`molecular-organic-refinement` / `salt-cocrystal-asu-discipline` / `organometallic-hapticity-and-mc`，内容只从知识库逐条引证、不进模板指针）；模板 v34 修正性重写的其余部分。按 §2.4 规则：A ≥ B 则不做，改为收缩模板。

---

## 5. 项目主人已拍板（2026-09-03）

- **先做知识层消融对照实验**（主人提出）：臂 A = 操作契约 + 诚实守则、无判断内容、无技能工具；臂 B = 当前全栈；3 晶体（hex / cage / org_hsl）× 2 臂 × 1 重复 = 6 格，结果接近再加重复。
- **验证数据**：MOF 为产品优先，`data_ext2` 五格作每波工具改动后的泛化门禁（tune：org_hsl + coord_cuox；verify：orgdis_dbu、twin_rz5267、twintrap_nm 最后）。
- **四条条款全改成证据式**（ASU 连贯性句、掩膜只看 ΔR1、suggested_d_min 要真执行、GooF→1）。
- **probe_fragment 本轮做**，排在阶段 A 与 T1.1–T1.4 之后并行；提高字符预算并记录理由。
- **评分器过程证据只进诊断字段，不计分。**
- 已自行决定、供否决：根 `AGENTS.md` 改一行指针并纳入 git（不删）；MetalProfile 本轮不扩表；新战役 `projects_root` = `H:/CrystalPilot-campaigns/<name>`；子代理遗留的 `C:\tmp\x.py`、`C:\tmp\x2.py`、`H:\tmp\x2_out.txt` 由主人处置（仓库外，我不动）。

---

## 6. 执行顺序与验证

- 解释器只用 `H:\CrystalPilot\.venv\Scripts\python.exe`；私有 `--basetemp=workdir/pytest-tmp-<who>`；4 核 BelowNormal；一次一个重战役；不碰 `~/.codex`；不按名杀进程；不提交/打印 `testAPI.txt`；战役参考只放 `H:/CrystalPilotData/campaigns/`。
- 每项提交前：该项单测 + `tests/test_agents_md.py` + `tests/test_checkcif_chain.py`；每天末全量 pytest 对基线 1154。
- **顺序**：
  1. 第 1 天：T0-0 卫生与记账 + 消融开关（§2.3）+ `grade.py:594` + `tools_disorder.py:565` 文案 + T1.9 的 d_min 对齐 → 提交、tag `pre-ka1`、全量 pytest。
  2. 第 2–3 天：**阶段 A 发射**（`H:/CrystalPilotData/campaigns/ka1-{hex,cage,org}.json`，两泳道，L0）；跑的同时在 worktree 做 T1.1（工具侧，不影响运行中的战役，MCP 按 case 新 spawn，主树冻结的纪律沿用 pa2）。
  3. 阶段 A 跑完：`--regrade`、`KA1-ANALYSIS.md`（中文），按 §2.4 定阶段 C 范围；重启服务器合并 worktree。
  4. 之后：T1.1 合并 → C-固定（v33 + 卡矛盾清理 + 工具修正，tag `agents-v33`）→ T1.7 → T1.2 → T1.4 → T1.3 → T1.5 → T1.6/T1.8 → T1.10 并行 → C-条件（若做）→ 阶段 D：ext2 泛化门禁五格。
- 依赖：T0-0 先于阶段 A；T1.7 先于 `:291` 删除；T1.1 先于 GooF 改写；`connectivity.py:583` 三态化先于新卡引用字段；T1.5 的 extra_cards 先于 `SHELXL_ONLY_KINDS`；T1.9 的 d_min 对齐先于任何新战役评分。
- 回滚：每项单提交；阶段边界打 tag；工具项皆为加法可 `git revert`；`cn_plausible` 三态化与 `hint_valid` 各自 grep 消费者后单独提交。

---

## 7. 不同意分析稿的地方

- **D1 §8.4(a)"吸收边检查完全不存在"——错。** `tools_heavysites.py:179-226` 已有；真缺口是只在一个工具里。
- **D2 §3.4"评分器 R1≤0.10 绝对悬崖"——已过时**（`grade.py:1738-1744`）；仍绝对门的是 `evaluate_refinement.py:221`；且漏了更重要的 `r1_delta` 不对齐 d_min。
- **D3 "无 AFIX 147/148"——半错**（147 已发）。
- **D4 "FVAR 不可达"不准确；"Hirshfeld 缺"应写缺检验。**
- **D5 根 AGENTS.md 是 P0 文本小改，低估且诊断不完整**：活的、gitignore、每回合注入、只污染战役臂（构造效度）；正解是 projects_root 出仓 + 版本记账。
- **D6 §5 P1"补全 MetalProfile"——方向不对**：`:583` 形状本身错，补表不解决；氧化态窗口不相容；表无来源。正解：三态化 + 共价半径 + 表降级为证据。
- **D7 §5 P1"决策记录 + 可推翻条件"——应延后**：现有失败无一例是忘记决策。
- **D8 §5 P0"新建三张卡骨架"——同意做但反对填法，且现在改为以消融结果为条件。**
- **D9 §8.2(a)"评分器看过程证据"——方向同意，反对计分**（主人已定只进诊断）。
- **D10 §5 P0"list_skills 检索含正文"——部分反对**：改标题 + source + 同义环。
- **D11 `ghost_test` 无保留范例，补非化学实体分支。**
- **D12 路线图没列自己的 P13 样例判据 ⟨I²⟩/⟨I⟩²。**
- **D13 "六张卡自带免责表头"——只部分成立。**
- **D14 原则 14 举例 1.2 Å——建模但不能做拒绝门**（无本平台失败台账）。
- **D15 §3.3"`model_disorder` 无拆前先各向同性守卫"——代码守卫方向相反**（`tools_disorder.py:206-221` 要求先各向异性定劈裂方向），是工程取舍不是缺失。
- **D16 更根本的一条（主人的方向）：分析稿默认"知识层越完备越好"，把 P0 排成扩建技能卡与模板；本规划改为先证明知识层是否加分。** 分析稿 §2.3"经验来源集中在三颗晶体"与 §8.7 Linden "每 50 个结构一次的稀有情形"仍然成立，但它们支持的是**测更多类型的晶体**，不是**写更多卡**。
- **D17 简报里的测试基线约 574，实际 1154。**

---

## 附：规划阶段的披露

- 子代理遗留文件：`C:\tmp\x.py`、`C:\tmp\x2.py`、`H:\tmp\x2_out.txt`（仓库外，git 干净）。
- 未核实的假设：Codex `project_doc_max_bytes` 默认 32 768（codex-cli 0.147 含该配置键，config 未覆盖），未做溢出实验；守卫留 2 KB 余量。
- 阶段 A 的残余混杂：臂 A 的工具描述文本里仍含判断性文案（如 `ghost_test` 处置、`integrate_difference_density` 的电子数尺子）；这是"工具层"的一部分，本轮不剥离，结论里注明。
- 工作树里未提交的 `codex-home/config.toml`（trust 条目）与未跟踪的 `6000`、`design_ref/front-end/`、两份 docs，本规划不动它们。


---

## 8. 执行记录（随做随记）

### 第 1 天（2026-09-03）：卫生记账 + 消融开关

已提交（main，e6980e0 之后）：

- `99c4760` 根 `AGENTS.md` 改为一行指针并纳入 git（不再被 `.gitignore` 忽略）。
- `1a4e305` `knowledge_mode = full | tools_only` 项目设置：`TEMPLATE_TOOLS_ONLY`（1 768 字符 / 3 646 B，只有操作契约 + 诚实守则；守卫断言零判断词、零技能指针）；`ensure_agents_md` 三态（written / current / kept_foreign，无标记文件永不覆盖，`/projects/open` 回报）；MCP 进程经 `CRYSTALPILOT_KNOWLEDGE_MODE` 得知模式，`refine.registry` 不注册技能四工具，`run_checkcif` 不附 related_skills；`/projects/settings` 改模式即重写 AGENTS.md 并重建工作台；字节守卫 `模板 + 根文件 < 32768 − 2048`。
- `d1ee92a` runner：case/lane 级 `knowledge_mode`；state.json 记 `agents_version / agents_sha256 / agents_expected_sha256 / agents_matches_template / root_agents_sha256 / agents_chain`（从磁盘回读，不是从请求推断）。
- `b2e9953` `model_disorder` 文案：SIMU 是相似性限制，不是 EADP（等同约束）的"平台等价物"。
- `c3486b5` ka1 三份清单（`H:/CrystalPilotData/campaigns/ka1-{hex,cage,org}.json`，`projects_root = H:/CrystalPilot-campaigns/<lane>`，仓库外；org 晶体盲态分装到 `H:/CrystalPilotData/staging/ka1o/`：`crystal.hkl` + 无对称性的 `start.ins`）。
- `1aa619a` **实测抓到的坑**：MCP 的 tools/list 走按代码指纹的规格缓存，纯工具臂的进程虽然带了环境变量，仍被喂了全栈 69 个工具的缓存。修法：缓存键附加模式（`spec_cache.cache_key()`），`crystalpilot/knowledge_mode.py` 作唯一无依赖读取点。stdio 实测：tools_only 65 / full 69，冷热缓存皆对；HTTP 全链路（open → settings 切换两个方向 → mcp_status）复核通过。
- `40a70c0` MCP 进程启动时向 `<project>/.crystalpilot/mcp_server.jsonl` 追加一行证据（pid / knowledge_mode / 缓存命中 / 工具数），日志包收集之，臂标签是"请求了什么"，这一行是"实际跑了什么"。

阶段 A 的残余混杂（结论里必须披露）：tools_only 模式下 65 个工具描述里仍有 2 个提到技能（`audit_guest_evidence`、`integrate_difference_density`）；工具**运行结果**文本里指向 read_skill/技能的字符串共 18 处（9 个文件），本轮不剥离。`data_ext2/org_hsl` 的 hkl 由沉积 fcf 反推，系统消光反射已被 SHELXL 剔除，定群只能靠 E 统计与劳厄类合并统计，两臂条件相同但与真实冷启动不同，分析时要说明。

未纳入提交、留给主人的：`codex-home/config.toml` 的本地改动（trust 条目）；`H:/CrystalPilot-campaigns/_probe/`（HTTP 探针用的临时项目，可删）。

### 迟到的审计更正（2026-09-03 16:30，规划期两个只读子代理的后台 grep 返回）

- **撤回 §1.3 一条**："三套能力集合无一致性测试"错了。`tests/test_skills.py:200-255` 有子集（三集合 ⊆ 已注册工具）、互斥（MUTATING ∩ READ_ONLY = ∅）、穷尽（每个工具落进 MUTATING ∪ READ_ONLY ∪ 显式 NEITHER 白名单，24 项各带理由）三重不变式，且注释记录了它修复的那次"四个只读分析工具在只读模式被误拦到 2026-09"的事故。§1.3 正文已就地改正。
- **补一条真缺口（待办，不在本轮范围）**：旧 agent 路径 `crystalpilot/agent/crystal_agent.py:89-91` 的第四套集合 `GATED_TOOLS`（Copilot 档等审批）无任何测试，其成员 `set_space_group`/`restore_state` 只存在于旧管线 `pipeline/standard.py`，不在精修注册表里，真正改群的 `change_space_group` 与回滚的 `checkout` 不受这道门约束。该路径仍可达（`cli.py:21`、`server/app.py:135`、`benchmark/runner.py:36` 的 `run_auto`），但不是 Codex 工作台/战役所走的路径。处置建议：要么给 `GATED_TOOLS` 补"⊆ 已注册工具"守卫并换成现行工具名，要么随旧管线一起退役；由主人定。
- 两份报告其余结论不变；`.claude/worktrees/` 下两份旧工作树副本只是 grep 噪声。

### 第 1 天晚（2026-09-03 15:55–23:40）：阶段 A 跑完，决策落地

- ka1 六格全部结束并重评分：hex publication/publication（0.0817/0.0833）；org no_delivery/publication（—/0.0263）；cage below_bar/below_bar（0.2241/0.1642，后者模型移植复现参考 R1）。分析全文 `docs/ka1-2026-09-03/KA1-ANALYSIS.md`（含三份逐格核读、现场笔记、机械统计）。
- **§2.4 判定为第二档**：A 在流程纪律类（求解预算/组成许可、定群协议、掩膜纪律）系统性输；判断类规则零可测差别（知识已在工具返回里）；唯一模板措辞造成损失的一处是"慢≠卡死、绝不杀子进程"（cage-full 65 min 空等）。**阶段 C 范围**：v33 只保留能指向失败格的三组流程规则 + 操作契约加"长计算可分离/可放弃"，删其余判断内容；不做 C-条件的三张新卡与 v34 重写。
- **新增 P0（排在 T1.7 之前）**：客户端超时后服务端取消/释放锁；`solve_charge_flipping`/`optimize_weights`/长 `refine` 补预算与分离；SFAC 暴露 + `run_shelxt` 报错改写；`element_scan(free_occupancy=true)` 复现测试与修复；SHELXL 温度默认值不入 CIF；`finalize_delivery` 接受 `diagnostic`；ghost 判据排除近核纹波；`add_hydrogens` 当场自检 AFIX。
- 同日合并 T1.1（.lst 回读）与评分器酰胺修复；全量 pytest 1256 passed / 1 skipped；tag `ka1-done`。

### 主人拍板（2026-09-03 深夜）

- **同意 §2.4 第二档**：先修工具层 P0，再做 v33（只留能指向失败格的三组流程规则 + 操作契约加"长计算可分离/可放弃/换预算重发"）。
- 纠正：仓库内 `codex-home/`（CrystalPilot 自用的隔离 CODEX_HOME）可按需改动；禁区只有主人本机的 `C:\Users\lenovo\.codex\`。
- P0 工具层工作包（各自 worktree 并行，合并前逐支审查）：WP1 长计算预算/心跳/协作取消 + 队列消息（`solve_charge_flipping` / `optimize_weights` / `refine`）；WP2 SFAC 暴露 + `run_shelxt` 报错改写 + 消光"零观测"三态措辞；WP3 `element_scan(free_occupancy=true)` 复现与修复 + omit 电子数校准句 + readiness 不再推荐 optimize_weights；WP4 SHELXL 温度默认值不入 CIF + `set_experiment(null)` 回复纠正；WP5 `finalize_delivery` 接受 `diagnostic`；WP6 ghost 近核纹波判据 + `add_hydrogens` 当场 AFIX 自检。

### 第 2 天凌晨（2026-09-04 00:00–02:00）：P0 工具层合并中，v33 就位待合

- **已合入 main 的 P0 工作包**：WP1 预算/协作取消/队列消息（d6e46fa）、WP3 element_scan 自由占有率 → 仅占有率阶段 + 电子数标定（d62b7eb）、WP4 温度未知写 `?`（9f066fd）、WP5 finalize 收 diagnostic（2878507）、WP2 SFAC/UNIT 披露 + 消光措辞（5629178）。WP6（幽灵纹波判词 + add_hydrogens AFIX 自检）仍在其 worktree 中，第一部分已提交。
- **事后发现的孤儿进程**：ka1 org-tools 那格的 MCP 服务进程（codex 早已退出、战役 18:00 就超时收场）到 9 月 4 日凌晨仍在满转一个核，累计 518 CPU 分钟；核实命令行与父链后按 PID 杀掉。根因：服务器不感知 stdio 客户端消失（anyio 在 EOF 后要等不可中断的工作线程）。**修复 a5edf6c**：`server.py` transport watchdog，非破坏性探针（Windows PeekNamedPipe / POSIX ppid）每 5 s 一查，客户端消失后运行中的工具给 60 s 宽限，然后写证据行（`event=transport_closed`，含工具名/已耗时/预算）并 `os._exit(3)`；6 个新测试驱动真实管道 + 线程 + 退出路径。详见 `crystalpilot/mcp/CANCELLATION_NOTES.md` §(d) 与 ka1 现场笔记。
- **v33 已就位**（分支 `v33-stage`，ac4a236，等 WP6 合入后合并）：模板 13 968 → 7 461 字符 / 14 065 B；保留判断立场、操作契约、诚实守则和三组能指向失败格的流程规则（定群协议、求解预算 + 占位组成许可、掩膜纪律），操作契约加"长计算：预算内等、超预算记 unresolved 换路径"；删质量标尺、案例常数、GooF→1 与逐工具判断配方（两臂实测都从工具返回读到同样的判断）。tools_only 变体同步长计算句（标记 tools-only-v2）。守卫同步：teeth、预算 <8000 字符、`test_agents_template_carries_the_new_semantics` 改为"模板或工具说明二者之一"；`test_agent_campaign` 改比对 `VERSION_MARKER`。该 worktree 全量 pytest 1255 通过 / 3 失败（1 个即上述已修，2 个是新 worktree 缺未跟踪示例数据的旧问题）。
- 另开一个 Opus 子代理修战役分析三缺口（run_shelxt job_status 轮询不计为打转；`Input validation error` 单列为 schema 错误并进工具易用性排名；超时格收割 verdict/交付物），并顺带读取新的 `transport_closed` 证据行。
- 清理：`H:/CrystalPilot-campaigns/_probe/`（空目录）已删；`codex-home/config.toml` 的 trust 条目已在 26ac5f9 提交（主人已确认该目录可改）。

### 第 2 天凌晨（2026-09-04 02:00–03:30）：P0 收口，v33 合入并打标签

- **WP6 合入**（6f7b07d）：`ghost_test` 新增 `ripple` 判词（埋在重原子共价球内、自身无密度的傅里叶纹波，删不需 acknowledge_real；台账里后来的 ripple 可释放先前的 real）；`add_hydrogens` 逐载体按 **SHELXL 自身的 AFIX 邻接规则表**（在 shelxl.exe 上实测：13 需 3 邻、23/43 需 2、33/137 ≥1、83/147/163 需 1、93 需 1 且邻上再有一原子；连通性按 SHELXL 自带 SFAC 半径 + 0.5 Å；不合规时它自动忽略 Z 不在 6–10 的邻键）自检；`run_shelxl` 重放 riding-H 组前对照当前模型预检并拒绝过期组，cage 的 `BAD AFIX` 正是"add_hydrogens 之后模型变了、旧 H 组原样重放"造成的。
- **T1.7(a) 合入**（763ba98）：吸收边声明前移到 `set_experiment` / `get_project_brief`（`absorption_edge` 块：状态 edge_at_lambda / strong_fp / no_edge_nearby / wavelength_unknown / elements_unknown / unavailable；单一元素通用判据与 audit_heavy_sites 同源；Sasaki 缺项回落 Henke；三种不适用状态明说）。
- **v33 合入**（ad343e3，冲突两处：模板取 v33、`test_agent_campaign` 取 main 并改比对 `VERSION_MARKER`）。**全量 pytest 1450 passed / 1 skipped**（P0 前基线 1256/1）。**tag `agents-v33`**。服务器按 `workdir/restart_server_r13.ps1` 重启（结果见下一条记录）。
- **战役分析缺口合入**（7553063）+ ka1-org 重评 + 机械稿重出 + `KA1-ANALYSIS.md` 补记（cfaf657）。
- **新待办（WP6 顺带发现）**：`write_res` 在 ≥20 种元素时写出超过 80 字符的 `UNIT` 行，SHELXL 拒收，应按 SHELXL 续行规则（行尾 ` =` 续下一行）折行，SFAC 行同理。归入 T1.5 一并处理或单独小提交。
- **进行中**：T1.2（interpret_peaks 无金属分支 + `solution_capability` 披露，Opus 子代理 worktree）；T1.7(b)（ghost_test real 的"非化学实体密度"提示分支）。
- **未动、留给主人**：`.claude/worktrees/sad-dhawan-0751f5`（9 月 1 日会话遗留，433 行未提交的 FCF 总标度因子导入草稿：`_fcf_osf` / `_set_res_osf`，main 无对应实现）。

### 第 2 天清晨（2026-09-04 03:30–04:30）：T1.7(b) 合入，阶段 D 就位待发

- **T1.7(b) 合入**（0a2122e）：`ghost_test` 的 real 行附 `real_kind_hint`（atom_like / possibly_non_atomic）与逐项指标（满占有率下 Ueq ≥ 3× 本模型骨架中位数且 ≥ 0.15 Å²；≥3 个亚原子峰等距成链且间距落在共价键窗之外；自身对称像重叠；孤立密度 / 回峰偏离原位为辅助项），规则"≥1 主指标或 ≥2 辅助指标"写进返回；判词逻辑未动；峰形（拉长/分裂）声明为不可测而非估算；数据侧检查只点名注册表里存在的工具。real 的处置文本加一句"real 指密度真实，不等于它是原子"。160 项相关测试通过。
- 阶段 D 准备完毕：五个 ext2 晶体 staging（`H:/CrystalPilotData/staging/reg1-{hsl,cuox,dbu,rz,nm}`，冷启动 ins 同 ka1o 约定），清单 `H:/CrystalPilotData/campaigns/reg1-ext2.json`（5 格，7200 s）与 `reg1-mof.json`（hex 14400 s + cage 18000 s），已解析并校验路径。**等 T1.2 合入后发射 reg1-ext2**（战役期间主树冻结），之后 reg1-mof。

### 第 2 天早晨（2026-09-04 04:30–06:00）：T1.2 合入，阶段 D 门禁前的全量测试

- **T1.2 合入**（8f7b710）：`interpret_peaks` 拆成金属分支（行为不变）与**无金属分支**（组成里没有 `is_metal` 元素时走：按 0.7 Å 球积分密度排序；O/C 按密度分档、分界线取几何中点 √(Z₁Z₂)/Z_C；**C/N 不猜**，标 C 并返回 `element_uncertain` + `element_confidence`；N 预算只披露不指认；`chem_hint` 按几何读有机基元）；`run_shelxt` / `create_start_model` / `solve_charge_flipping` / `solve_superflip` 一律附 `solution_capability`（tier routine / harder / no_record 仅由 d_min 与最重元素 Z 决定：d_min ≤ 1.0 routine；≤ 1.2 需 Z ≥ 15；> 1.2 需 Z ≥ 20，否则 no_record 并写明"失败不等于不可解"），不拒绝、不改行为。新模块 `chem/solvability.py`、`tools/peak_chemistry.py`。44 项新测试。
- 真数据探针（只读拷贝 ext2）：org_hsl 4/4 个 O 按密度档指认正确，唯一的 N 按规则标 C 且 `element_uncertain`；orgdis_dbu 6 个 O 中 5 个正确、4 个 N 均标 C；orgdis_dbu 在 d_min = 1.3 Å 时电荷翻转无相变，披露块正确给出 no_record，正是该披露存在的场景。
- **行为变化需知**：未知组成现在走无金属分支（以前全标 C），所有标签 `element_confidence: low`；含 Cl/S/P/Br/I 的有机物不再把卤素当金属中心。遗留怪癖未动：金属分支里"金属 + 更重非金属（如 Zn + Br）"仍按 Z ≥ 17 选 Br 作"金属"。
- 相关测试 270 通过 / 1 失败（`test_shelxt_progress::test_detach_status_adopt_sequence`，单跑通过，负载下的计时抖动）。全量 pytest 作为发射 reg1-ext2 的门禁（结果见下一条）。

### 阶段 D 发射（2026-09-04 03:34）

- 全量 pytest（T1.2 合入后）：1523 passed / 1 skipped / 2 failed；两个失败均为负载下计时抖动（`test_olex2_tool` 活体冒烟单跑通过；`test_shelxt_staged` 的宽限测试是假 SHELXT 1.5 s 相位 vs 2 s 预算的边际设计，单跑也翻车，已把预算放宽到 3 s 保持原意，8950648）。
- **reg1-ext2 已发射**（03:34，runner 日志 `workdir/campaigns/reg1-ext2-runner.log`，状态 `workdir/campaigns/reg1-ext2/state.json`，项目根 `H:/CrystalPilot-campaigns/reg1-ext2/`）。首格 hsl-full-r1 的 state 已记 `agents_version` = v33、`agents_matches_template` = true、`root_agents_sha256` = null（仓库外，无根文件注入）。runner 与服务器进程树均已套 4 核 / BelowNormal。**战役期间 main 冻结**。
- 之后：reg1-mof（hex + cage）；两战役都用 `ka1_report --lanes reg1-ext2,reg1-mof --root workdir/campaigns` 出机械稿，再写中文分析并与 ka1 full 臂对照。

### 阶段 D 第一战役 reg1-ext2 结束（2026-09-04 03:34–04:52，五格共 75 分钟）

| 格 | 评级（原始） | R1 agent / ref | 独立 emma 核对 | 备注 |
|---|---|---|---|---|
| hsl | below_bar | 0.0263 / 0.0264 | 13/13 匹配，rms 0.001 Å，元素零错 | **误判**：交付 CIF 对称标签自相矛盾（见缺陷 D1），评分器随之判"骨架未复现" |
| cuox | publication | 0.0178 / 0.0179 | — | 干净 |
| dbu | below_bar | 0.0626 / 0.0447 | 26/28（缺无序组分 A 的 C12A/C13A） | 无序未建模；"骨架未复现"措辞过重 |
| rz | below_bar | 0.1246 / 0.0996 | 21/21，1 个 N 标成 C | 孪晶未建模：`set_twin(law='suggest')` 回答"无候选"（见缺陷 D3） |
| nm | acceptable | 0.0948 / 0.0526 | 23/25（缺无序组分 B） | "有更好节点"是 P1 试探（参数翻倍），agent 拒绝正确 |

- **审计误报**：机械稿把五格全标"数据泄漏"，命中的是各格自己的 staging 目录，`ka1_report.staging_allow` 只认识 ka1 三种晶体。已修（8f39eb6：并入泳道清单的 data_dir/data_alias），重出后五格"窥视干净"。
- **缺陷 D1（交付层，任何非标准设置都会触发）**：`report/cif.py` 把 `symbol_and_number()` 的"(a+1/4,b,c-1/4)"后缀截掉，写标准 H-M 符号却附移位算符；cctbx 报 Inconsistent symmetry，PLATON 同理。修法：交付时统一到标准设置（含 hkl 重指标）或写真实 Hall 符号；评分器遇标签冲突以算符环为准并单独标记 `cif_symmetry_inconsistent`。Opus 子代理进行中（前两次因 API 529 中断）。
- **缺陷 D2（评分器）**："骨架未复现"未区分"只差无序组分"；"有更好节点"未排除不同空间群/参数翻倍的试探节点。并入同一子代理。
- **缺陷 D3（工具层，P0 级）**：`set_twin(law='suggest')` 从未返回过任何候选律，算符身份用 `str(rot_mx)`（对象地址）、变换回工作基用 `rt_mx * rt_mx`（TypeError 被吞），于是对任何晶体都回答"无候选 = 该度规下不可能"。已在分支 `fix-twin-suggest`（bd79728）修：整数矩阵做身份、C⁻¹RC 变换、报告度规偏差与 8° 内的近失候选、措辞不再说"不可能"；合成覆盖 C2/c 赝正交（rz 晶胞）、P-1 赝单斜、真三斜、Pnma、P4/n。**待 reg1-mof 结束后合并**。
- 其余观察：五格都在 12–19 min 内交付并通过 checkCIF 解释门、结论与 CIF 一致；`solution_capability`/`absorption_edge` 新块未见负作用；rz 的 N/C 错标与 T1.2 的"C/N 不猜"一致，交付前的 C/N 裁决需要一个明确步骤（Ueq/几何/氢），列入待办。

### T1.2b 完成待合（2026-09-04 05:50）

- 分支 `worktree-agent-a32a16e266850e1bb`：`validate_structure` 新增 `light_atom_element_check`，精修后每个满占有率轻原子的 Ueq 对"质量可比"（Z 比 ≤ 1.6）的成键邻居做一致性检查，带 too_light_label / too_heavy_label、建议元素、置信度；`nitro_vs_carboxylate_candidates` 基于 X(O)₂ 平面基元 + Ueq 比给提示；从不自动改标签。判据来自物理：dU = ln(Z_label/Z_true)/(8π²⟨s²⟩)，⟨s²⟩ 用 cctbx 真精修标定为 0.25·s_max²（首次估计 0.6 差 2 倍）；实测 0.83 Å 下 N 位标 C 的 Ueq 缩到 0.31×、C 位标 N 涨到 2.18×。带 0.55 / 1.50，且要求对**每个**参考邻居一致（一致性规则消除了误标位点把邻居中位数拖低造成的二次误报，同时保护正确的羧酸盐）。21 项新测试全部用 smtbx 真精修产生 Ueq。已知局限：室温大 Ueq 下单步"过轻"只到 0.67× 会漏；无取代基的对称环把误差摊到赝等价位点。`interpret_peaks` 阶段无法给 Ueq 提示（新建模型 U 全等），只留指针。

### D1/D2 修复完成待合（2026-09-04 06:00）

- 分支 `worktree-agent-ad258d6fd933a9d08`（86155d2）。**决策 (b)：保留精修所用设置，如实命名**: final.cif 是 SHELXL ACTA 的原生输出（带 esd 的坐标、U_ij、按算符编号的几何环、内嵌 res/hkl），final.fcf/final.fab 是同一作业的字节拷贝（fab 的掩膜系数在原点移位下要乘相因子），只有重新精修才能诚实地换基；且评分器的 `_reproduce_refinement` 靠内嵌 res+hkl 复算 R1。于是坐标不动，`write_outputs` 返回 `setting_change`（cb_op、hkl_reindexed、applied=false、setting、hall、hm）。新模块 `io/cif_symmetry.py` 供两个 CIF 写手共用（此前二者不一致：report/cif.py 截符号后缀，publication.py 把 SHELXL 的 `?` Hall 原样透传，ka1 org-full 交付里的 `?` 即来源于此）；每个名字只有能解析回同一算符群才写。
- **PLATON 实测**（主仓库 vendor/shelx/platon.exe）：hsl 交付的 120_G（符号与算符不符）、125_C（无 Hall）消失，换成 122_A（未给 H-M 符号），总警报数不变，这是诚实的置换：交付确实不在表列设置里。对表列的非参考设置（P2₁/n、Fd-3m:1）PLATON 零对称警报。
- 评分器：标签冲突时按算符环解析并记 `cif_symmetry_inconsistent`；新增 `framework_verdict` / `framework_diagnosis` / `emma_match_fraction` / `emma_framework_rule`；`better_nodes_skipped` + 可比性规则（同空间群、参数数 ≤ 1.5×）。**用真交付重评**：hsl below_bar → acceptable（13/13，对称缺陷仍是阻塞项故到不了 publication）；dbu → acceptable（`framework_reproduced_disorder_incomplete`，缺 C12A/C13A，occ 0.265）；nm 的"有更好节点"改为"n0012 是 P1、不可比"。52 项新测试。
- 子代理自报的判断点：`framework_reproduced_disorder_incomplete` 升到 acceptable 没有匹配比例下限，**合并时加下限 0.85**。

### reg1-mof hex 结果与根因（2026-09-04 06:15）

- hex-full-r1：R1 0.1341（ka1 full 臂 0.0833），同一数据、同一截断（n_strong 2069）、骨架原子相同。**掩膜互换实验**（SHELXL L.S. 0）：ka1 模型 0.0834（自己的掩膜）/ 0.1814（无掩膜）；reg1 模型 0.1341 / 0.1946。差距在掩膜：ka1 的 agent 把 `solvent_mask` max_cycles 加到 800（92 s）追收敛，reg1 的只用 10/30（<1 s）。原因是 **WP1 给 solvent_mask 加的 BUDGET 句**："默认 10 循环……降低 max_cycles 来限制开销（结果报 converged=false、电子数为下限，这是诚实不是失败）"——把不收敛说成可接受状态。P0 措辞引入的回归，被阶段 D 门禁抓住。
- 修复（分支 `fix-twin-suggest` 28178ca，等 cage 跑完合并）：默认 max_cycles 1000 + 自执行 600 s 预算（在 BYPASS 循环之间检查，到期保留最佳循环并报 `bypass.stopped_by`、`budget`、`convergence_advice`）；描述改为"未收敛的掩膜 = 电子数下限且 R1 上限（reg1 hex：同一模型 0.134 vs 0.083），交付前必须收敛或在 unresolved 说明"。`budget.py` 表加 solvent_mask 600 s。测试 4 项新 + 既有掩膜/预算/交付测试 78 通过。
- 评分器口径：literature 参考下 `publication` 不要求绝对 R1 ≤ 0.10（hex 0.134 仍判 publication，而 acceptable 反而要求），D2 分支合并后改为 publication ⊂ acceptable，并重评所有格。
- cage-full-r1 05:33 起在跑（用的仍是旧默认值，作为对照证据）；结束后：合并四个分支 → 全量 pytest → 重启服务器 → `--regrade` reg1-ext2/reg1-mof → 重跑 hex + cage（reg2-mof）确认修复。

### T1.6 完成待合（2026-09-04 06:40）

- 分支 `worktree-agent-ae876abad3bea2f28`：新模块 `refine/disorder_accept.py`；`.lst` 回读 FVAR 值与 s.u.（`shelxl.free_variables`）；`run_shelxl` 每个无序组返回 `disorder_acceptance`（free_variable{value, su, informative, verdict}、occupancy、adp、separation（对数据 d_min）、delta_r1、restraint_suggestion、undo）与汇总 `disorder_verdict`；判词 supported / inconclusive / revoke / pending / unknown。规则：先看 s.u.（>0.10 → inconclusive，避免未测定的比例冒充 revoke）；|k| 或 |1−k| ≤ 2 s.u. → revoke（两种不同的读法）；组分 Ueq 对模型自身中位数（>3× 或 <1/3）；最近 A–B 距离对数据 d_min（一个分辨率元内不可分辨）；ΔR1 明说不是证据、上升才是反证。`model_disorder(undo=<group>)` 合并回单点、重编 FVAR、清 PART/限制/H 元数据。限制建议：SADI 展开（set_restraints 没有 SAME）+ SIMU（各向异性后再 DELU），只建议不施加。27 项测试用 vendor SHELXL 真精修：CF₃ 转子 0.7/0.3 真值 → FVAR2 = 0.7018(13) supported；有序真值假拆 → 0.9987(11) revoke；undo 复原；P-1 Zn/Cl 拆分证明与元素/晶格无关。
- 未做：`situation_report` 未显示判词（tools_analysis.py 在禁改名单上），合并后补 4 行（`tools_analysis.py:2112` 读 `g["verdict"]`）。

### T1.4 完成待合（2026-09-04 06:50）

- 分支 `worktree-agent-a6f082b9fc0e53477`（0bf16cd）：`sg_screen.py` 新增分壳 |E²−1|、⟨I²⟩/⟨I⟩²、⟨F⟩²/⟨F²⟩、L-test（参考值按小分子全中心情形推导：0.637/0.500，不是大分子文献的 0.500/0.333，否则每个健康的有机 P-1 都会被标）；每个读数带方向、强度、`argues_for`/`not_argued_for`，可分辨带 = max(3σ 采样, 0.2×未孪–全孪跨度)；**两个方向不对称**：刚性/各向异性把 ⟨I²⟩/⟨I⟩² 与 ⟨|E²−1|⟩ 推高（两个 ext2 真数据集与合成二聚体都读 4.1–5.1 / 1.08–1.11），向上分支无独立证据不下结论，向下分支不需要。`E2M1_FAILURE_CONDITIONS` 五条按当前组成/数据逐条判断（最重元素占 Σ nZ² > 0.50；≥10 % 散射功率在特殊位置；清楚的孪晶侧读数；弱指标类 < 0.35；分辨率/反射数）；`hint_usability` 永久单边规则：非中心提示不得用于去掉反演中心。`screen_space_groups` 加 `conflicts` 不改排序；`check_symmetry` 加 kind / risk / reliability（≤0.84 / ≤1.2 Å / 更粗）。30 项测试；真数据探针（去孪晶后的 fcf 派生数据）读数均落在未孪晶括号内，符合预期。
- 注意：`reflection_statistics` 返回体 4.6 KB → 15.5 KB；中心对称基线下 50:50 孪晶恰好坐在非中心参考值上（XPREP 陷阱），已作为测试固化。

### reg1-mof cage 根因 + SHELX 编码守卫（2026-09-04 07:32）

- cage-full-r1 below_bar 0.2226（无掩膜、19 个显式客体片段），树内最佳 n0152 0.1636（掩膜、各向异性；ka1 0.1642）。n0152 之后 `ghost_test`/回读全部 IndexError：model.res 里 C010 U33 = 16.58 Å²（smtbx 各向异性精修发散），SHELX 编码把 |p| ≥ 5 解成自由变量引用而 FVAR 只有 1 个 → 节点永久不可读，agent 失去最佳节点后改走显式客体路线。详见 `docs/reg1-2026-09-04/REG1-ANALYSIS.md` §5.2。
- 修复 7ef11b1：`io/shelx_codes.py`；写入器拒写、读取器点名、`refine` 回退发散参数并重算指标（`diverged_atoms`/`note_diverged`）。`tests/test_shelx_codes.py` 7 个测试；相关 21 个测试模块 407 通过。
- 其它已提交：9f107ca（评分器 publication ⊂ acceptable；situation_report 显示 T1.6 判词计数）。全量 pytest 与两个战役的 `--regrade` 后台进行中；随后重启服务器、重出机械稿、启动 reg2-mof。

### 战役后收尾（2026-09-04 07:43）

- `--regrade` 两个战役（合并后的评分器）：reg1-ext2 = hsl acceptable（对称命名缺陷仍阻塞 publication）、cuox publication、dbu acceptable（disorder_incomplete）、rz below_bar、nm acceptable；reg1-mof = hex below_bar（0.1341，literature 参考下不再误判 publication）、cage below_bar（0.2226）。机械稿已重出（29aa0e0）。
- e70f8c6：`framework_reproduced_disorder_incomplete` 加匹配比例下限 0.85（子代理自报的缺口；测试固件扩到 dbu 形状 25/29）。
- 6c4fa4b：写入器 SFAC/UNIT/FVAR 超 76 列自动 `=` 续行（≥20 种元素时 SHELXL 80 列截断的旧账），`wrap_card` 与读取器共用。
- 全量 pytest 第一遍：1215 passed 后被 `test_olex2_tool.py::TestLiveSmoke::test_help_boot` 打断（olex2c 在负载下没等到提示符；单跑 68 s 通过，属负载抖动）；第二遍不带 -x 进行中（workdir/pytest-full-0904b.log）。
- 服务器已重启到合并后的代码（uvicorn PID 19124，4 核 BelowNormal）。合并过的 5 个 worktree/分支已删；`workdir/probe-cage-ghost` 副本已删。下一步：全量通过后启动 reg2-mof（hex + cage 确认），期间 main 冻结。

### reg2-mof 确认跑结果（2026-09-04 09:48）

- hex-full-r1 **publication** R1 0.0858（ka1 0.0833 / reg1 0.1341）：掩膜 92 个循环收敛，掩膜收敛修复成立。cage-full-r1 below_bar R1 0.1570（ka1 0.1642 / reg1 0.2226）：三次最好，掩膜 + 67 个客体片段，交付 diagnostic 且 unresolved 9 条属实；发散回退未触发，ghost_test/checkout 0 错。两格 683 次调用 1 次出错（refine 掩膜过期）。详见 `docs/reg1-2026-09-04/REG1-ANALYSIS.md` §7、机械稿 `REG2-MOF-draft.md`。
- 新待办：T1.6 `disorder_acceptance` 对重原子分裂加"配位球一致分裂"读数（cage Zr3/Zr7 0.75 Å 分裂被统计判词放行）；战役泳道目录名去语义（agent 从 `reg2-mof` 读出 MOF）；`refine` 掩膜过期提示补 `refresh_mask=true`（本轮已改）。

### T1.6b 配位球一致性 + 泳道名去语义（2026-09-04 14:29）

- 主人指示：此后不再成批跑战役，**每次只跑一格**，用来判断某一项修改是否生效、有无潜在问题。
- 7c47278：`disorder_accept.sphere_reading`，对分裂组的每一对组分，找同时与两个组分成键的**单点邻居**，比较它到 A 与到 B 的键长差 |d_A − d_B|，参照该邻居自己的 rms 位移 sqrt(U_eq)（2 倍，下限 0.15 Å）；超过即"该邻居无法同时与两个组分成键"，占有率 s.u. 给出的 `supported` 降为 `inconclusive`（`verdict_demoted_from`），disposition 改为先决定几何（把该动的邻居一起分裂并限制，或用 probe_site/ghost_test 判第二个位置不是原子），不得照原样交付。环折叠（备选位置垂直于键）判 consistent；邻居本身属于其它无序组则不算单点。元素无关、只参照模型自身 U_eq。`tests/test_disorder_sphere.py` 6 个测试；原金属卤化物固件改为把第二个 Cl 放在 Zn 配位球上（1.0 Å 弦），否则它自己就是配位球不一致的例子。
- 同一提交：`agent_campaign` 新增 `defaults.anonymize_lane`，泳道目录变成 `l<sha1[:8]>`，与 `anonymize_projects` 配套；旧泳道按原名回退以便 `--regrade`。新清单 `H:/CrystalPilotData/campaigns/reg3-rz.json`：只跑 rz 一格（孪晶律修复的回归），数据目录用中性别名 `staging/s2c7e` 指向 reg1-rz。
- 相关 36 个测试模块 764 通过（`test_shelxt_staged` 一个计时测试在负载下抖动，单跑通过）。

### reg3-rz 单格回归结果（2026-09-04 14:44）

- rz-full-r1 **publication** R1 0.1032（reg1 0.1246 below_bar；沉积 0.0996）：`set_twin(law='suggest')` 给出候选（度规偏差 2.3°），agent 先把无孪晶模型做到 0.122 再测试候选律，BASF 0.2 → 0.02365（沉积 0.02337），律与沉积律相差一个 C2/c 自身的二重轴，等价。12.7 min、154 次调用、1 次 schema 拒绝（`checkout` 缺 node）。泳道 `l48a5add1` + 别名 `s2c7e`，路径线索为空。详见 REG1-ANALYSIS §8、`REG3-RZ-draft.md`。
- 新待办：`read_skill` 发现成本（三个战役都是连续 4 次换参数）；`checkout` 无参数时缺省到活动节点而非拒绝。下一格：dbu 或 nm（T1.6 + T1.6b 首次在真实分裂上验证）。

### 顺手的两项（2026-09-04 14:49）

- 4236486：`checkout` 接受 `target`/`branch` 作为 `node` 的别名（reg3-rz 唯一的一次出错就是 `checkout({target: 'solve_c2c'})` 被 schema 拒绝），无目标时返回活动节点/分支/最近节点表而不是裸拒绝；`campaign_analysis.find_arg_churn` 给每串换参调用记 `n_errors`，机械稿只把**有出错**的串计入"难调用"信号，全部成功的换参列为浏览（reg3 的 5 次 read_skill 读卡曾被误报为难调用）。reg2/reg3 机械稿已按新口径重出，REG1-ANALYSIS §8.2/8.3 已更正。
- 下一格：reg4-dbu（`H:/CrystalPilotData/campaigns/reg4-dbu.json`，泳道匿名 + 别名 `staging/s9b41`），验证 T1.6 无序验收闭环与 T1.6b 配位球读数在真实有机分裂上的表现。

### reg4-dbu 单格结果 + model_disorder 峰位放置（2026-09-04 15:10）

- dbu-full-r1 acceptable R1 0.0626（与 reg1 相同；沉积 0.0447），26/28。agent 找对了无序原子（C00P/C00Q，占有率 0.8 对沉积 0.735）并调了 `model_disorder`，但用了缺省 0.6 Å ADP 轴位移；工具在 pending 块里说"低于 d_min 不可分辨"，agent 36 秒后 `checkout` 回无分裂分支交付，T1.6 闭环没转起来。详见 REG1-ANALYSIS §9。
- 修复：`model_disorder` 的 B 位点优先取上一次 refine 差值图里属于该原子的峰（0.4–1.6 Å、离它最近），报 `second_site_from`；无峰才退回 ADP 轴并说明；各向同性原子有峰不再拒绝。pending 的 disposition 与 separation 读数改为"读数不是判词，立刻在本分支精修读 s.u."。5 个新测试，118 通过。
- 下一格：reg5-dbu（同数据重跑）验证这两处。

### reg5-dbu 单格重跑 + T1.6b 氢原子缺陷（2026-09-04 15:31）

- dbu-full-r1 acceptable 0.0626（三次相同）。峰位放置生效（B 在 1.12 e/Å³、1.00 Å 的峰上），但 T1.6b 配位球读数把骑乘氢当邻居报"2 of 5 不一致"，agent 以"可能是氢密度"在 19 s 后 undo，未精修。详见 REG1-ANALYSIS §10。
- 修复：配位球读数排除 H；不一致重原子邻居有自己的残余峰时点名一起分裂（`neighbours_with_own_peak`）；`model_disorder` 新增 `evidence`（B 到最近模型氢的距离、载体分裂前 U_eq/中位数、ADP 各向异性比）。109 个相关测试通过。
- 下一格 reg6-dbu（`reg6-dbu.json`，别名 `s7a29`）。若仍在精修前弃用分裂，改提流程规则给主人决定（"画出的分裂只能由精修后的 s.u. 裁决"），不再改措辞。

### reg6-dbu 第三次单格：升级为流程规则决策（2026-09-04 15:51）

- dbu-full-r1 acceptable 0.0626（第四次相同）。这次 agent 没调 `model_disorder`，在精修前以"峰在氢范围、证据不足"否决；它自己在推理里写了"I should model the disorder for C16 and maybe C15"然后去交付。四次 dbu 四个不同假设，都在 SHELXL 精修前止损。工具侧三处缺陷已修完（缺省位移、pending 措辞、氢当证人），**不再改措辞**。
- 提给主人决定（REG1-ANALYSIS §11.3）：A. v34 加一条流程规则"无序由精修裁决，精修前不得否决画出的分裂"（约 90 字，预算放得下，需同步守卫测试）；B. `validate_structure`/`situation_report` 加 `disorder_candidates` 主动读数。建议 A+B 后再跑一格 dbu。nm 的回归等这个决定之后再跑（同类无序问题，先跑只会重复结论）。

### 主人决定：A + B 都做，再跑一格 dbu（2026-09-04 15:59）

- **A. 模板 v34**（tag `agents-v34`）：专家评审铁律新增"无序纪律"一条，无序由精修裁决，不由假设裁决；disorder_candidates → model_disorder（B 落在峰上）→ restraint_suggestion → 该分支 run_shelxl(adopt) → 按 disorder_acceptance 的 s.u. 留/限制/撤销；"可能是氢""数据未必支持""低于 d_min"是待检验的假设。正文 7807 字符（预算 <8000）。守卫测试加"无序纪律"齿；pa2 语义守卫改为版本无关（≥ v33）。
- **B. `refine/disorder_candidates.py`**：对上一次差值图的每个残余峰，找它所属的原子（0.4–1.6 Å、离它最近、且峰不坐在任何已建原子或氢的 0.35 Å 内），报峰高/距离、载体 U_eq 相对模型中位数的倍数、ADP max/min、峰到最近模型氢的距离，并写明下一步；`validate_structure` 返回 `disorder_candidates` + info 级 `disorder_candidate` 警报，`situation_report` 在 open_items 与叙述里列出（中文）。3 个新测试；相关 201 通过。
- 下一格 reg7-dbu（`reg7-dbu.json`，别名 `s1d6f`，模板 v34）。

### reg7-dbu 结果：A + B 生效（2026-09-04 16:27）

- dbu-full-r1 **publication** R1 0.0475（沉积 0.0447；此前四次 0.0626 acceptable），28/28，三碳链无序 0.707(6):0.293(6) 带 16 条限制。链路完整：validate_structure 列候选 → model_disorder（B 在峰上）→ set_restraints → run_shelxl(adopt) → supported 0.702(7) → 扩到三原子 → 再试 O004/O00A/C00G 各分支后按残差驳回。详见 REG1-ANALYSIS §12。
- 评分器缺陷 75c8ed9：盐/共晶的 emma precision 把模型建出的反离子当多余原子（15/29 → below_bar）；与"另计"参考原子匹配的模型原子现从分母扣除（3 个新测试，61 通过）。reg7 重评 publication；reg1-ext2 按新口径重评。
- 下一格建议：nm（同类无序 + 非合并孪晶陷阱）。

### reg8-nm 单格：基准数据缺陷 + 评分器第三处修正（2026-09-04 17:00）

- nm-full-r1 R1 0.0948（与 reg1 相同），23/25。**根因是数据**：ref.hkl 由 HKLF 5 孪晶精修的 fcf 派生（10410 行 / 5378 组 hkl，最多重复 8 次，53.5% 组 3σ 外不一致）；沉积模型本身在这份数据上按 HKLF 4 只到 0.0942。agent 报出 42.3% 不一致并如实披露。详见 REG1-ANALYSIS §13。
- 修复：b4deb00 评分器 `reference_on_delivered_data` 臂（沉积模型在交付数据上重精修作 R1 基准，`r1_delta_basis` 披露）+ `audit_reflection_data` HKLF 5 导出签名读数；01c2d13/后续：publication 门读 framework 诊断（未建无序组分留 acceptable）。重评：reg8/reg1 nm acceptable（Δ +0.0006），reg7 dbu publication 不变。数据侧 REFERENCE-CAVEAT.md（gitignored 数据目录）。
- 新待办：候选列表带"已试/已裁决"标记并读 mark_adjudicated；ingest 时报重复 hkl；view_structure 无原子时给晶胞视图；model_disorder 重派骑乘 H。

