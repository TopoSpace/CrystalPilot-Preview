# R7 子代理实验（草稿，2026-09-05）

计划 `docs/PLAN-2026-09-04-round2.md` R7：主人 2026-09-04 拍板"子代理默认关，只在最高
推理档位提示可委派，先跑一格对照再定是否放宽"。本文分两部分：先是**机制探针**（两次
一分钟级的探测，回答"能不能、怎么才安全"），再是**一格 cage 对照**（回答"有没有用、
多少钱"）。所有事实都有落盘证据：`workdir/r7-probe/run.log`、`run2.log`、探针项目的
`.crystalpilot/mcp_server.jsonl`、`docs/R7-SUBAGENT-GROUNDWORK.md`（Sonnet 副线的
文档调研，已验证 / 未验证分开列）。

## 1. 机制探针（一次性项目 `H:/CrystalPilot-campaigns/r7-probe/p-probe`，mvp-sjtu9 数据）

副线调研留下三个只能实跑回答的问题：① app-server 驱动的会话能否按名拉起自定义角色；
② 只读隔离怎么落到子代理的 MCP 连接上；③ 角色文件里的 `sandbox_mode` 会不会被父
turn 的实时权限盖掉（本轮不靠它）。做法：项目里放一个项目级角色
`.codex/agents/validation_ro.toml`（自带 `[mcp_servers.crystalpilot]` 覆盖：同一解释器、
`--project <本项目>`、`CRYSTALPILOT_MCP_READONLY=1`），个人级 `codex-home/agents/validation.toml`
不带覆盖；一条消息让主 agent 拉起子代理、让子代理必须调一次 `edit_atoms` 并原样记录
服务端回应。

**探针 1（run.log，54 s）**

- `spawn_agent(agent_type="validation_ro")` 失败，系统原文：
  `Full-history forked agents inherit the parent agent type; omit agent_type, or spawn without a full-history fork.`
  ，不是"角色不存在"，是默认的 full-history fork 不允许指定角色类型。
- 主 agent 按回退规则改拉个人级 `validation`，成功。**关键副产物**：
  `mcp_server.jsonl` 里出现第二个 MCP 进程（pid 53512，`readonly: false`，规格缓存命中）
  ，子代理线程会**另起一份**父代理配置的 MCP 进程，而个人级角色没有覆盖，这份是
  **可写的**。所以个人级角色目录一律不放角色文件（已从 `codex-home/agents/` 移到包数据
  `crystalpilot/workbench/agent_roles/`，只按项目生成）。
- 子代理自己拒绝调 `edit_atoms`（它的指令是只读），没有测到服务端闸门。

**探针 2（run2.log，77 s）**

- 主 agent 显式 `fork_turns="none"` 后，`spawn_agent(agent_type="validation_ro")`
  **成功**：项目级角色经 app-server 链路可解析（副线担心的 openai/codex#26408 的项目级
  失败没有复现）。
- `mcp_server.jsonl`：父进程 pid 56808 `readonly: false`；子代理进程 pid 55932
  **`readonly: true`**（角色文件的 MCP 覆盖生效，环境变量到位）。
- 子代理调 `edit_atoms` 删 C008，服务端原文：
  `tool 'edit_atoms' is blocked: this workbench is in READ-ONLY mode (inspection tools only). Ask the user to switch the permission mode to make model changes.`
  模型未被修改；子代理按 JSON 格式回了判词（空间群 I 41/a m d :2、13 原子、
  `symmetry.confirmed=false`）。
- 子代理 MCP 冷启动约 7 s（规格缓存命中 + 主线程预热 0.09 s）。

**结论**：只读隔离靠"项目级角色文件 + 自带只读 MCP 覆盖"落地，服务端强制，不依赖
codex 沙箱；模板必须写明 `fork_turns="none"`。未回答的：③（本轮不依赖它）、
`[agents]` 里 `max_depth` / `job_max_runtime_seconds` 两个键在 0.147.0 是否仍生效
（留给下一轮用 `--strict-config` 核）。

## 2. 落地（提交 7fab11a）

- 项目设置 `subagents`：`top_tier`（默认）/ `off`。有效档位 = xhigh 且 top_tier 时：
  AGENTS.md 换 **v37-delegate** 变体（多一段 8368 − 7915 = 453 字符的"可委派的只读审计
  子代理"），项目 `.codex/agents/` 生成四个角色（space_group / chemistry / density /
  validation），每个自带只读 MCP 覆盖；档位或策略一变即重写/删除（带
  `# crystalpilot-role-v1` 标记，用户自己的文件不动），下一个对话生效。
- UI 权限菜单：开关"只读审计子代理（最高档提示）"+ 当前状态行；系统行"已进入/退出
  委派档位"。
- 守卫：`tests/test_agents_md.py::test_delegate_variant_is_a_distinct_marked_rendering`、
  `tests/test_codex_agent_roles.py`（角色文件字段、不提任何写类工具、按项目写入/删除/
  保留外来文件）、`tests/test_structure_class_setting.py::test_delegation_tier_in_settings_and_update`。

## 3. 一格 cage 对照的设计（reg11-cage → reg12-cage）

基线：reg2-mof `cage-full-r1`（模板 v33，无提示）= below_bar，
R1 0.157（Δ +0.0175，文献参考），72 min，23.7 M tokens。本格：同一数据、同一参考、
xhigh、v37-delegate + 四个只读角色。n=1，且工具面从 v33 到 v37 之间改了 R2–R6 全部
内容，所以对照是**描述性**的，不能把差异归因于委派。

## 4. reg11-cage 第一次实跑（2026-09-05 06:57–07:30）：委派发生了，格子死于流中断 + 主机崩溃

**过程**（`workdir/campaigns/reg11-cage/`，项目 `H:/CrystalPilot-campaigns/reg11-cage/p93536cf1`，
转录 `CrystalPilot Results/task_20260905_065740/transcript.jsonl`，MCP 进程日志
`.crystalpilot/mcp_server.jsonl`，子代理 rollout `codex-home/sessions/2026/09/05/rollout-2026-09-05T07-21-{42,53}-*.jsonl`）：

- 06:57 开跑，AGENTS.md = v37-delegate，`.codex/agents/` 四个角色在位（state.json：
  `agents_matches_template: true`，`delegation: true`）。
- 07:11–07:21 两轮 SHELXT（第二轮按正确组成重解，P2₁/c，SysAbs 0.99，六个 Zr 位点），
  分支 `shelxt_zr6_p21c`。
- **07:21:42 主 agent 决定委派**，原话："当前分叉确实困难：P2₁/c 与 Zr₆/两个 Zr₃ 核心可信，
  但自动轻原子网明显混入大量错误 C/N/O 标签和悬空碎片……我会按项目约定并行请化学建模与
  差值密度两个只读专家审计当前节点；我仍是唯一改模者，并会逐条用本会话实测核对其建议。"
  ，这正是模板段落写的"只在真正有分歧处委派"。
- 07:21:46 / 07:21:56：两个新的 MCP 进程启动，**都是 `readonly: true`**（pid 51184、3540；
  父进程 pid 53104 `readonly: false`），角色文件的只读覆盖在真实战役里生效。
- 子代理 chemistry：07:21:42–07:25:17（3.6 min）；density：07:21:53–07:26:20（4.5 min）。
  两份判词都是要求的 JSON（assessment / recommendation / confidence / evidence / risks），
  证据条目引用了 `get_project_brief`、`inspect_model`、`inspect_map` 的具体数字：
  - chemistry（confidence **low**）："支持两个近等边 Zr₃ 三角单元由有机骨架连成一个六金属
    分子/笼，不支持紧凑八面体 Zr₆ 氧簇……ZR03、ZR04 的坐标环境存在致命重叠，必须先裁决；
    N048 与 ZR03 是否为同一重位点的错误双峰……"，并明确说"项目无 ligand SMILES 或合成先验
    可约束，其余大量 N/C 不做批量互换"。
  - density（confidence **medium**）："围绕六个 Zr 的 0.75–0.90 Å 卫星峰更符合未建模各向异性、
    Zr 吸收边异常散射遗漏及傅里叶截断纹波，不能据此拆分六个 Zr；N048 距 ZR03 仅 0.816 Å 且
    +6.17 e/Å³ 正峰正落在其上；O007/O008/O009 省略图 14.2/14.7/10.3 e，是真实密度而非 ghost……"
- 主 agent 并没有干等：07:22–07:28 自己跑了 `validate_structure`、8 轮各向同性精修、
  `assemble_asu`、12 个原子的 `ghost_test`（277 s）。**07:28:20 的裁决**："两位专家与我方幽灵
  测试一致：N048 的密度真实，但距 ZR03 仅约 0.82–0.88 Å，不能作为独立 N；最合理的可检验假设
  是 ZR03 的两位点无序。该测试会在独立分支进行……交由 SHELXL 的占有率及其标准不确定度裁决；
  若不受支持就撤销。"——判词被当作参考、与自己的实测对照后才行动，且落到可检验的分支上。
- 07:29 分支 `zr03_split_trial`、`edit_atoms` 重派 N048→Zr、`model_disorder` 两位点、SADI 约束，
  07:29:39 `run_shelxl(adopt, l_s=8)`。
- **07:30:14 回合失败**：`stream disconnected before completion: stream closed before
  response.completed`（模型流在 `response.completed` 之前被关闭，1941 s 的工作回合就此结束）；
  runner 立刻发收尾回合，07:30:33 以同一错误再次失败（19 s）；07:30:35 评分 no_delivery。
  **07:45:07 主机以 Kernel-Power 41（未正常关机即重启）起来**，系统日志 6008 记录的"上次意外
  关闭"时间是 07:11:31（该时间戳是事件日志最后一次心跳，不是精确崩溃时刻）。两次流中断发生
  在崩溃前十几分钟，很可能是主机走向崩溃时网络/进程已经不正常，但这只能是推断。

**这个错误是不是偶发**：在全部战役转录与 Codex 会话 rollout 里搜 `stream disconnected before
completion`，只出现在两处：2026-08-28 12:50–13:15（三个 rollout，共 4 次，同一时段）和本次
07:30（2 次）。中间 8 天、约 40 格战役一次都没有。所以它是**成簇出现的瞬时传输故障**
（网关或本机网络），不是某个工具或模板的问题；但一次就足以让 32 分钟的格子被判 no_delivery，
因为 runner 把首次失败当成了终局。

**修法（已提交）**：`agent_campaign.py` 加 `_retry_transient`，回合以瞬时传输类错误
（`stream disconnected / stream closed / connection reset / 502–504 / temporarily unavailable`
等）失败时，等 45 s，在**同一线程**上重发"从中断处继续、不要重复已完成步骤"的提示，最多
2 次；收尾回合同样处理；每次重试写入 SSE 日志包（`runner_retry`）与 state（`stream_retries`、
`last_stream_error`）。非瞬时错误（工具异常等）不重试。测试
`tests/test_agent_campaign.py::TestTransientStreamRetry`。

**对 R7 问题的部分回答（n=1，未完成的格子）**：委派机制在真实战役里按设计工作，只在分歧点
委派、两个角色并行、各自只读、判词结构化且有数字、主 agent 用自己的实测对照后再行动。成本：
两个子代理各 3.6 / 4.5 min 墙钟（与主 agent 的幽灵测试并行，几乎不增加总墙钟），tokens 在父线
程的 7.76 M 之外（子线程用量未进 state.json 的 usage 汇总，见 §6 待办）。结果无法评判，格子
没有跑完。复跑 reg12-cage（同清单，runner 带重试）。

## 5. reg12-cage 复跑（2026-09-05 08:01–09:04）：委派三次、机制全程正常，结果没有比基线好

**结果**（`workdir/campaigns/reg12-cage/`，项目 `H:/CrystalPilot-campaigns/reg12-cage/pe8f898bd`）：

| | 基线 reg2-mof cage-full-r1（v33，无提示） | reg11-cage（v37-delegate，死于流中断） | **reg12-cage（v37-delegate）** |
|---|---|---|---|
| 等级 | below_bar | no_delivery | **below_bar** |
| R1 / 分辨率截断 | 0.157（Δ +0.0175） | — | 0.1986（d_min 0.996 Å；参考 0.1395 @ 0.691 Å，评分器判"不可比"） |
| 骨架 | — | — | framework_reproduced 133/154（召回 0.881、精确率 0.917，rms 0.249 Å） |
| 组成 | — | — | C105 O34 Zr6 vs 参考 C119 Cl3 N6 O20 Zr6（N、Cl 全缺；空腔密度按"真实但非原子型"移除并交给掩膜，溶剂可及空洞 59%） |
| checkCIF A/B/C | 92/119/291 | — | 21/38/100（A 级里 7 条模型质量阻断：080/084/201/202/241/242/934） |
| 树里更好的节点 | — | — | 有：n0179 R1 0.1691 vs 交付 0.1986（Δ 0.0295） |
| 墙钟 | 72.5 min | 32.6 min（中断） | **62.7 min** |
| tokens（父线程） | 23.7 M / 62.5 k | 7.8 M / 15 k | **29.0 M / 78 k** |
| 工具调用 | — | 134 | 157 |
| 委派 | 无 | 2（chemistry + density） | **3**（chemistry + density @08:37，validation @08:54） |
| 流中断重试 | — | 无（未修） | 0 次触发 |

**委派的三次，逐条**（子代理 rollout `codex-home/sessions/2026/09/05/rollout-2026-09-05T08-37-51-*`、
`08-38-05-*`、`08-54-05-*`；MCP 进程日志 pid 9104 / 3696 / 49888 全部 `readonly: true`）：

1. 08:37:48 主 agent："这里已经达到需要专家复核的分叉：主笼轮廓和掩膜证据明确，但缺少合成
   先验使 C/N/O 指认与局部短键无法唯一化。我将按项目规则并行调用化学建模与差值密度两个只读
   审计代理；它们只给证据，不会改动当前节点。"
   - chemistry（08:37:51–08:40:46，2.9 min，15 次只读工具调用，confidence **high**）：
     "n0133 可支持'两个近三角形 Zr₃ 单元组成的有限分子宿主'这一低层级描述，但不能可靠命名为
     特定笼拓扑，也不能把当前五元密度片段定为真实 Cp/芳环。大量 1.0–1.2 Å 短键、异常配位和
     高 Ueq 表明轻原子骨架仍存在严重错连、元素误判或未建无序；当前远未达到发表级。"
   - density（08:38:05–08:40:35，2.5 min，15 次，confidence **medium**）："六个最高的框架邻近峰均距
     Zr 仅 0.62–1.06 Å，不符合 Zr–O 键长，更像重原子傅里叶纹波……六个位点同时出现相似模式，使
     全局纹波/数据误差比六个独立真实分裂更可信……掩膜应暂时保留：同一 145 原子模型中它令 R1
     从 0.3408 降至 0.2144……精确位点测试未发现掩膜覆盖 Zr/O 原子中心。"
   - 主 agent 08:42:06："两位审计者的证据一致：空腔密度和异常轻原子位置都是真实散射，但不少并
     不像离散原子。现在先做删除，回峰实验，区分'应保留的原子'与'应由掩膜/无序描述的非原子密度'。"
     ，判词被当作证据、随后用 `ghost_test` 自己核，与 reg11 的行为一致。
2. 08:54:05 validation（–08:58:44，4.6 min，5 次，confidence **high**），交付前复核：
   "final.res 与 final.cif 使用了不同坐标状态，掩膜重复计数风险未在 VALIDATION.md 中诚实展开，
   且少数警报解释有事实性错误。" 主 agent 09:03:18："逐条报告现已与这一次最终 checkCIF 完全对应
   ……先前审计指出的温度字段释义、24 个强度离群点释义、Zr/O 残余峰原文以及掩膜潜在重叠披露均已
   修正。"——**这是子代理实际改变了交付物的一次**：三处 VALIDATION.md 的事实错误在交付前被纠正。

**读法（n=1，工具面 v33→v37 之间改了 R2–R6 全部内容，所以只能是描述）**：

- 机制：三次委派都发生在真实分叉（元素/连接性无先验可裁、密度归属、交付前复核），都是只读的，
  判词结构化、引用具体数字，主 agent 每次都用自己的实测对照后再动手。两次并行委派与主 agent 的
  幽灵测试同时进行，墙钟不增反减（62.7 vs 72.5 min）。
- 结果：没有更好。R1 更高（0.199 @ 1.0 Å vs 0.157），组成丢了 N 与 Cl（参考里有 6 N、3 Cl；agent
  把空腔密度当弥散溶剂掩掉），且树里有更好的节点没交付（n0179，Δ 0.0295，评分器已按"交付比树内
  最佳差"记账）。这些错误不是子代理造成的：density 的判词恰恰建议"暂不新增宿主重原子、保留
  掩膜"，主 agent 采纳了；在缺少合成先验的 cage 数据（完整度 73.6%）上，两个 agent 一起做出的判断
  与一个 agent 一样错。**子代理提供的是第二双眼睛，不是第二份先验。**
- 成本：父线程 29.0 M 输入 tokens（基线 23.7 M，+22%）；三个子线程各 2.5–4.6 min 墙钟，其 token
  用量未进汇总（§6）。

## 7. 结论与建议（交主人拍板）

1. **机制可以留**：只读隔离经实跑证实（五个子代理 MCP 进程全部 `readonly: true`，探针里
   `edit_atoms` 被拒），委派只在分叉处发生，判词质量可用，validation 角色在交付前抓到了三处事实
   错误。
2. **不建议放宽**：默认策略维持"只在最高档位提示、子代理只读"。两格（reg11 未完成、reg12 完成）
   都没有显示委派能提高结果；成本 +22% tokens。要证明"有用"，需要同一数据、同一工具面的
   A/B（v37 vs v37-delegate 各 ≥2 次），本轮没有这个预算。
3. **下一轮再做**：把子线程 token 并入战役 usage；把 rollout 里的 spawn/verdict 回填成 `collab_*`
   事件（e3b7f56 已让下一次直接进转录）；给 validation 角色一个更明确的交付前触发点（本格是 agent
   自己想到的）；合成先验缺失时的"元素/组成"问题（reg9 的 N/C、reg12 的 N/Cl）是比子代理更值
   得投入的能力空洞。

## 6. 待办

- 子线程的 token 用量没有进 state.json 的 `usage` 汇总（`token_usage` 事件只来自父线程）；
  要评估委派成本，得从子代理 rollout 汇总或让 workbench 把 collab 线程的用量并入。
- 父线程转录里没有 `collab_*` 事件（探针里只有 `wait` 有）：spawn 的记录只在 rollout 里，
  UI 的子代理目录因此看不到本次委派，下一轮把 rollout 的 spawn/verdict 回填成事件。
- `[agents]` 的 `max_depth` / `job_max_runtime_seconds` 在 0.147.0 是否仍生效（`--strict-config`）。
