# 第三轮 R7 复盘：子代理分档与 A/B（2026-09-06，机制部分收口，A/B 待 API）

> 对应计划 `docs/PLAN-2026-09-05-round3.md` §3 R7 / §9 WP9。机制、契约、测试与 UI 已收口（tag `r3-r7-impl`）；**A/B 四格与 R6 的交互实验一样被模型 API 断流挡住**（09-06 04:10–04:38 五次探测全部 `stream disconnected before completion`），按主人指示先做系统工作，API 恢复后按 §4 的协议跑。

## 1. 目标对照

| 计划项 | 结果 | 提交 |
|---|---|---|
| 统一策略 `subagents = off \| top_tier \| aggressive` | ✅ `agent_roles.SUBAGENT_POLICIES = ("top_tier", "aggressive", "off")`；策略 × 有效档位 → **委派层级** `off / hint / aggressive`（`delegation_tier`）：top_tier 在 xhigh 及以上给"可委派"提示；aggressive 在 xhigh 同 top_tier，在 **max / ultra** 换成主动委派变体；低档位任何策略都没有角色文件 | `54fcd20` |
| `aggressive` 只在探针证实 `max` 可用时出现 | ✅ R0 探针已证实网关接受 max/ultra（`docs/reg1-2026-09-04/EFFORT-PROBE.md`）；`service.AGGRESSIVE_EFFORTS = ("max", "ultra")` 直接由 `TOP_TIER_EFFORTS` 派生 | 同上 |
| 模板变体：max 档"主动委派五类只读审计并汇总裁决"，xhigh 档只"提示可委派" | ✅ `agents_md.DELEGATION_SECTION_AGGRESSIVE`（标记 `v40-aggressive` / `v40-tools-only-aggressive`）：三个固定检查点（① 采纳空间群前 → space_group；② 骨架建成、掩膜前 → chemistry + density；③ 交付前 → validation + refinement_strategy），每份判词写一张裁决表（角色 / 判词摘要 / evidence 是否与实测一致 / 采纳与否及理由），一个检查点总墙钟超 15 分钟就不再等；提示变体改为五个角色 | 同上 |
| `consult_specialist` 与原生角色共用判词 schema | ✅ 新模块 `workbench/subagent_contract.py`（叶子模块）：`SPECIALTIES` 五项、`VERDICT_SCHEMA`、`VERDICT_FIELDS`、`parse_verdict`（非 JSON 退化为低置信自由文本，绝不编字段）；`tools_specialist` 改为从它导入；第五个角色文件 `agent_roles/refinement_strategy.toml`；测试锁定"角色文件集合 == 专长表"且每个角色的说明写全五个判词字段 | 同上 |
| 子线程 token 并入 `usage`；目录行显示 running / inactive / 时长 / token | ◐ 目录已显示状态 / 时长 / 模型·档位（round-2）。**token 做不到**：真实 transcript 里 Codex 的 `collab_*` 事件 `agents_states` 为空，没有子线程用量可读（reg12-cage 的 3 次委派全部如此）；不伪造，等 Codex 暴露再接 | — |
| 设置与启动器 | ✅ 设置字典 `delegation.tier / aggressive_efforts`；UI 开关改为三选一（最高档提示（默认）/ 最高档主动委派 / 关闭），状态行按层级说明；`scripts/run_live.py --subagents aggressive` 直接可用 | 同上 |
| A/B 四格（cage 与小分子各 关/开） | ✅（GLM 版，§4a）：小分子对 B1/B2 同结构同指标、委派无科学收益、多 18 min；cage 对 A1/A2′ 的差别由提问卡而非委派决定；A2（首次 aggressive）暴露并修掉子代理机制在第三方模型上的四处缺陷 | 见 §4a |

## 2. 做法要点

- **一条规则定层级**（`agent_roles.delegation_tier`）：`off` 或档位不在最高层 → off；`aggressive` 且档位 ∈ {max, ultra} → aggressive；其余 → hint。`delegation_active` = tier ≠ off（旧调用者不变）。`ProjectState.open(delegate_for=…)` 接受 bool 或层级名（服务端传 `delegation_tier_for`）。
- **模板预算**：plain 8570 / hint 8986（< 9000）/ aggressive 9163 - aggressive 变体只在 max/ultra 渲染，测试给它单独 9600 的上限并写明原因。
- **主动委派的边界写进模板**：子代理是顾问不是决策者；承重数字自己核；同时最多 2 个；写类工具服务端拒绝；15 分钟上限。
- **判词解析统一**：嵌套工具原来 `json.loads` 失败就手写兜底，现在两条路径都走 `parse_verdict`（多余字段丢弃，缺字段整体退化，不补造）。

## 3. 证据

- pytest：`tests/test_codex_agent_roles.py`（五角色、`test_delegation_tiers` 真值表）、`tests/test_agents_md.py::test_aggressive_variant_is_a_distinct_proactive_rendering`、`tests/test_upgrade_instructions.py`（三种变体 × 两种模式）、`tests/test_structure_class_setting.py`（设置字典层级、更新链路 hint → aggressive → hint → off）、`tests/test_subagent_contract.py`（4）；相关套件 68 + 140 passed；全量见 UI-EVIDENCE R7 节。
- vitest 342；tsc 干净。
- 全量 pytest（R7 机制提交后）2505 passed / 26 skipped（`workdir/pytest-full-r7.log`）；含顺带修复后 2509 passed / 26 skipped / 0 failed（10:48）（`workdir/pytest-full-anom.log`）。
- 全量 pytest（R7 GLM A/B 收口，含 CPU 上限 / fourier_complete / 子代理四修 / auto 审批拒绝）**2534 passed / 26 skipped / 0 failed**（2026-09-06 19:01，12 min 05 s，`workdir/pytest-full-r7done.log`）。
- Playwright 证据轮 **r3-r7**（`workdir/ui-evidence/r3-r7/`，8 张，复用 `e2e/r6-interaction.pw.ts`）：`r6-light-settings.png` 里"只读审计子代理 最高档提示（默认）▾"下拉与状态行"当前档位已开启：角色 chemistry / density / refinement_strategy / space_group / validation"。

## 4. A/B 协议（待 API 恢复后执行，一次一格）

> **2026-09-06 11:30 改动**：网关 API 断流后主人给了 OpenRouter 的 GLM 作临时测试模型（[[openrouter]] 说明见 `docs/CAPABILITIES-2026-09.md` §4）。GLM 的档位阶梯是 low/medium/high，`high` 既是顶档也是 aggressive 档（`service.EFFORT_LADDERS`），所以四格都用 `--provider openrouter --effort high`；同一对（off/aggressive）必须同模型：cage 对用 `z-ai/glm-5.3-flash`（多模态，子线程若开图不会 404），小分子对用 `z-ai/glm-5.3`（纯文本，`vision=false`）。主人预期 GLM 不如 GPT，所以这次 A/B 只回答"主动委派在同一弱模型上是否不劣于关闭"，不与 09-04 的 GPT 数据横比；网关恢复后按原协议（max 档）复跑。

| 格 | 数据 | 档位 | 策略 | 目的 |
|---|---|---|---|---|
| A1 | Zr6 笼（reg12-cage 同源输入） | max | off | 基线：同档位、无委派 |
| A2 | 同上 | max | aggressive | 主动委派三检查点 |
| B1 | 小分子 org_hsl（data_ext2） | max | off | 基线 |
| B2 | 同上 | max | aggressive | 主动委派 |

- 启动（GLM 版）：cage `scripts/run_live.py --source H:/CrystalPilotData/staging/pa1c --name r7-cage-<off|agg> --provider openrouter --model z-ai/glm-5.3-flash --effort high --subagents <off|aggressive> --brief workdir/live-demos/briefs/r7-cage.md --structure-class cage --hours 3`；小分子 `--source H:/CrystalPilotData/staging/reg1-hsl --name r7-hsl-<off|agg> --model z-ai/glm-5.3 --brief workdir/live-demos/briefs/r1-org-hsl.md --structure-class small_molecule`。
- 启动（原协议）：`scripts/run_live.py --source <staging> --name r7-<cell> --effort max --subagents <off|aggressive> --brief workdir/live-demos/briefs/<…>.md --context … --hours 3 --structure-class <cage|small_molecule>`（同模型 gpt-6-astra、同简报、同先验；无人插话；一次只跑一格，4 核 BelowNormal）。
- 指标（同 R4 复盘口径）：结构 / 元素正确率（对参考结构）、`VALIDATION.md` 事实错误数、有效试验数（试验账本）、墙钟、父线程 token（`token_usage`）、委派次数与每次墙钟（`collab_*`）、裁决表是否出现且判词与实测一致。子线程 token 不可得（见 §1）。
- 判定：aggressive 在两种样本上都不劣于 off（正确率不降、事实错误不增）且墙钟增幅可接受，才把默认策略从 top_tier 放宽；否则默认保持 top_tier（与 round-2 结论一致）。

### 4a. GLM 实跑记录（2026-09-06，一次一格）

| 格 | 项目 / 模型 | 策略 | 时间线 | 结果与观察 |
|---|---|---|---|---|
| A1 | `r3\r7-cage-off`，z-ai/glm-5.3-flash @ high（vision=true） | off | 12:04–13:39（95 min，84 次调用）；12:41 提问卡"这颗晶体的化学内容是什么"→12:46 以课题组记录（Zr 源 + 有机配体，预期 Zr 簇分立笼）作 `[prior]` 答复 | 诊断交付 n0070：R1(I>2σ) 0.2137 / wR2 0.5693 / GooF 1.581；先验之前把六个强位点当 O 且 P2₁/m 假设被自己否决（中心对称占位假象），先验之后 `probe_site` 对 Zr 强支持（ΔR1 −0.079 / −0.074，Zr–O 2.1–2.4 Å，Zr–Zr 3.35–3.49 Å）→ Zr6 八面体核心确认；外围配体未闭合，约 60 个高 ADP 原子用 SIMU/DELU + 掩膜（588 e/胞、46.6 %）；checkCIF 34 A / 36 B / 77 C。途中 `fourier_complete` 因 `u_equiv: None`（发散回退原子）崩溃、Agent 改走掩膜，已修（ecb412e）。截图 `workdir/ui-evidence/r3-r7/flash-cage-ask-card.png`、`flash-cage-off-delivered.png` |
| A2 | `r3\r7-cage-agg`，同上 | aggressive | 13:41 起；14:39 提问卡（重位点是 In/Cd/Sn/Sb？）同样答以 Zr 先验；14:49 检查点② 委派 chemistry + density；**14:56 主机蓝屏**（bugcheck 0x12b 硬件坏页，A2 正以 20 核无上限跑 `fourier_complete`），中断于 n0064；15:20 新线程续接（节点链完整，先验随简报带上）→ **17:09 诊断性封存 n0150**（续接线程 77 次调用；两次被 `.codex\tmp` 写脚本的审批卡住共约 12 min，人工放行） | **委派失败，机制缺陷两处**（Codex 日志库实证）：① 子代理跑在 codex 自己的默认模型 gpt-5.5 上（请求 instructions 是"You are Codex, a coding agent based on GPT-5"），不是父线程的 GLM；② 子代理首回合在它自己的只读 MCP 服务器答 tools/list 之前就发出（首个 POST 14:49:03.77，MCP 启动记录 14:49:04；同一回合内工具表不再刷新），两只子代理都答"MCP 工具未挂载"，Agent 按模板写了"不采纳"的裁决表并本地替代。续接线程终态：R1(I>2σ) 0.1779 / R1(all) 0.2985 / wR2 0.4432 / GooF 1.838，Zr6 核心按先验重定型（I001–I006 → ZR1–ZR6，N01B → O），掩膜 7056 Å³（36.7 %）1985 e/胞，checkCIF A/B/C 共 216 条逐条写入 VALIDATION.md，8 条未解决问题；比 A1（R1 0.2137）略好，但两格都没做到配体闭合。Agent 把 checkCIF 作业目录里 0 字节的 `model.fcf` 说成"工具侧复制产物为空"——那是 PLATON 自己重建 fcf 失败留下的空文件（`run_checkcif` 只放 model.cif，`fcf_recreation` 字段已解释），不是交付缺陷。截图 `workdir/ui-evidence/r3-r7/flash-cage-agg-ask-card.png`、`flash-cage-agg-delivered.png`。修法（b78436d）：角色文件写 `model = effective_model(settings)`（override 或 config 默认）；委派模板 v41 改两步，`spawn_agent(agent_type, fork_turns="none", message="回复 READY")` → `wait_agent` → `send_input` 审计任务 → `wait_agent`（第二回合已有工具）。续接线程用的是 v41 模板与带 model 的角色文件，检查点③（交付前）将检验修法 |
| B1 | `r3\r7-hsl-off`，小分子 org_hsl（staging `ka1o`，冷启动 INS），z-ai/glm-5.3 @ high（vision=false） | off | 17:13–17:20（**7 min，33 次调用**），无提问卡 | **发表级 `final` 交付**：P2₁2₁2₁、C8H11NO4、Z=4；R1(I>2σ) 0.0263 / R1(all) 0.0273 / wR2 0.0688 / GooF 1.036 / Flack −0.007(8)；先按 Marsh 纪律试 Pmmm（R1 0.51 判不成立）再显式分支到 P2₁2₁2₁（SHELXT 一次 R1 0.079）；无 restraint / 无掩膜 / 未截断；checkCIF 无晶体学 A/B/C 警报，10 项元数据警报逐条豁免披露；与 GPT 的 R1 格（16 min 38 s / 53 次）同题同答案、更快。截图 `workdir/ui-evidence/r3-r7/glm53-hsl-off-delivered.png` |
| B2 | `r3\r7-hsl-agg`，同上 | aggressive | 17:22–17:47（**25 min，42 次调用，5 次委派**：检查点① space_group，② chemistry + density，③ validation + refinement_strategy；子代理全部跑在 z-ai/glm-5.3、带 MCP 工具，Codex 日志逐条核过），无提问卡 | **同一结构、同一指标**：P2₁2₁2₁，R1(I>2σ) 0.0263 / R1(all) 0.0272 / wR2 0.0678 / GooF 0.976 / Flack −0.007(8)；五份判词与主 Agent 实测全部"一致"，裁决表按模板写出（chemistry/density 否决核旁 0.13–0.22 e/Å³ 峰的分裂；validation 抓出 moiety 写成 `N1` 的 C 级格式问题并修掉）。差异只在收尾：B2 因元数据 A 级不能消除而**按 diagnostic 封存**（0 项豁免），B1 走了 10 项元数据豁免封成 `final`，同一模型两次不同的判断，不是委派造成的。截图 `workdir/ui-evidence/r3-r7/glm53-hsl-agg-delivered.png` |
| A2′ | `r3\r7-cage-agg2`，z-ai/glm-5.3-flash @ high | aggressive | 17:48–18:43（55 min，124 次调用）；**没有发提问卡**；18:14–18:20 陷入 `list_skills` 死循环（连续 20 余次），18:19 我插话叫停并提示"按提问卡格式问一次，否则走数据路线；波长在 Zr 吸收边附近"（这句提示比 A1 在提问卡之前得到的多，是对 A2′ 有利的干预，记入）；检查点③ 只 spawn 了一次 validation 子代理就 wait/close（**Flash 没有按两步委派走**），子代理首回合无工具 → "未挂载"记 unresolved | 诊断封存：R1 0.284 / wR2 0.59，112 个非氢原子中 **102 个仍是游离片段**，O1–O6 被判"occupancy×Z ≈ 8–11 e，不是金属"——**没有找到 Zr6 核心**；无掩膜、各向异性不收敛（11 NPD）。截图 `workdir/ui-evidence/r3-r7/flash-cage-agg2-delivered.png` |

- 续接线程（15:20 起，v41 模板 + 带 model 的角色文件）在检查点①③ 再次委派失败：codex 用模型元数据校验角色的 reasoning effort，第三方模型的元数据为空表（"Supported reasoning efforts: （空）"）。第三处修法：`codex-home/model_catalog.json`（`model_catalog_json`）把两个 GLM 与 gpt-6-astra 声明给 codex；探针 `_probe/glm53f2`（15:52）两步委派成功、spawn_agent 列出三个模型；`model_override` 变更现在重渲染角色文件。这三处修法都只到**新开的** app-server 进程（服务重启后），A2 续接线程仍是旧进程，它的委派仍失败，所以 **A2 只能算 off 臂的重复**；真正的 aggressive 臂要在重启后再跑一格（cage A2′ 或小分子 B2）。
- **cage 对的读法**：A1（off）与 A2′（aggressive）的差别不在委派，而在**提问卡**: A1 在 12:41 问了组成、拿到 Zr 先验后 `probe_site` 立刻确认 Zr6 核心（R1 0.214）；A2′ 从头到尾没问，把六个最强位点判成非金属，R1 0.284、骨架未闭合。同一模型两次跑出不同的"要不要问"的判断，说明 R6 的提问卡机制对这类样本比 R7 的子代理更决定成败。A2′ 的委派本身又败在父模型不守两步协议（Flash），所以给角色文件加了子代理侧的热身保护（7510458，每个角色先调一次 `list_mcp_resources`，codex 在同一回合每次工具往返后会重建工具表，A2′ 子代理第二个请求就带上了工具）。
- **小分子对的读法**：aggressive 没有改变答案，只多花了 18 min 墙钟与五份子线程 token；它带来的唯一实质贡献是 validation 顾问抓到的 moiety 格式问题（C 级）。与 round-2 的结论一致：子代理机制可用、在简单样本上不产生科学收益。cage 对要等 A2′。
- 判读口径（GLM 版）：A1 与 A2 的差异首先是机制是否工作，其次才是委派收益；A2 的前半段（到 14:56）在委派失败的意义上等价于"off + 浪费 2 分钟"，续接线程才是真正的 aggressive 臂。
- 与 CPU 上限有关的提醒：09-06 15:19 之前 `limit_cpu` 从未生效（ctypes 句柄截断，见 CAPABILITIES §8），A1 与 A2 前半段都是无上限跑的；续接线程起 MCP 子进程实测 affinity=15、BelowNormal，墙钟不可与之前直接比。

## 5. 没做 / 边界

- A/B 已在 GLM 上跑完五格（§4a）：**结论与 round-2 一致，子代理机制可用、未证明有益，默认策略保持 `top_tier`**；GPT 版 A/B（max 档）等网关恢复后按 §4 原协议补跑。
- GLM-5.3 Flash 作为父模型不可靠：一次 `list_skills` 死循环（需插话）、不守两步委派协议；GLM-5.3 守协议、判断稳。
- 子线程 token 不可观测。
- 主动委派的三个检查点是模板约定，没有服务端强制；Agent 不委派也不会被拦。
- `aggressive` 在 xhigh 档等同 top_tier（有意为之：xhigh 的预算不够养五个顾问）。

## 6. 顺带修复（2026-09-06 05:00，同一 tag）

等 API 的间隙追了 R5 留下的"掩膜电子 2.02 倍"：会话从 `model.res` 重建时丢了反常散射项（数据在 Zr K 边上，f′(Zr) = −9.04 e），每次 checkout / 分支 / 查看器重算都受影响。修法、影响范围与修复后实测见 `docs/reg1-2026-09-04/R3-R5-draft.md` §7；能力表 §3 掩膜行与 §1 孔道行同步更新。
