# 第三轮 R4 复盘：整客体工具与研究目标（2026-09-06）

> 计划：`docs/PLAN-2026-09-05-round3.md` §3 R4、§9 WP5 / WP7。上一轮：`R3-R3-draft.md`。本文只写实测到的东西；"没做"的单列。

## 0. 一句话

R4 给 Agent 补了两样它在 09-05 演示里没有的东西，**整片段姿态搜索**（`search_fragment_pose` / `accept_fragment_pose`）和**研究目标 + 试验记忆**（`set_investigation` / 试验账本）；同题复跑 Zr-MOF 一格，**无人插话**，43 分钟 / 123 次调用 / 117 节点，Agent 自己搜索并试装了整个对溴苯乙酸客体、用 SHELXL 证伪、把四条否决理由与六个未试方向记进账本，以诊断交付收尾（R1 0.0860）。对照取证基线（398 次调用、3 h 20 min、三次人工插话、最终 n0224 一个自由精修下会塌陷的"整客体候选"），这次的结论更诚实、路径更短；但**数据本身仍不支持整客体**：这一格证明的是"工具让 Agent 能提出并检验整分子假设"，不是"找到了客体"。

## 1. 交付了什么（代码）

| 提交 | 内容 |
|---|---|
| `b2cdebb` WP5 | `refine/tools_pose.py`：`search_fragment_pose`（只读），SMILES/模板 → 构象库（`ligand.ideal_geometry` + 扭转采样）；种子 = 差值图峰三元组几何哈希（对称像内）+ 区域随机种子；打分 = 逐原子密度（map-σ 单位）− 碰撞场（cKDTree）− 锚定罚；Nelder–Mead 6 自由度局部精修；特殊位置吸附与对称折叠；对称感知去重；逐原子证据类 **direct_peak（≥3σ）/ weak_density（≥1σ）/ geometry_only**；候选缓存 `.crystalpilot/refine/pose_candidates.json`（按节点 + 修订号）；预算 600 s，超时返回已得候选并标 `timeout`。`accept_fragment_pose`（改模），一个候选一次成节点：共享 FVAR（`disorder_groups`，origin `kind:"fragment_pose"`）、PART、EADP 卡（走 R3 的有效模型状态）。`model_disorder(undo)` 对片段 FVAR 干净拒绝并指向 `edit_atoms(delete)`。 |
| `8bfd65a` WP7-a | `refine/trial_ledger.py`：TRIALED 工具（fit_fragment / search_fragment_pose / probe_site / ghost_test / element_scan / integrate_difference_density / audit_guest_evidence）每次成功调用按 **工具 + 归一化有效输入**（标签大小写与顺序、锚点顺序、1e-3 以下浮点噪声不算新试验；预算与自由文本不算输入）记到 `.crystalpilot/refine/trial_ledger.json`；`project.invoke_tool` 调用前查：同节点命中附 `tool_status.prior_trial`，祖先命中附 `prior_trials_on_ancestors`（只告知），旁支忽略；**只提示不拒绝**。`situation_report.open_items.recent_trials`。 |
| `5f7f421` WP7-b | `refine/investigation.py` + 工具 `set_investigation`（SESSIONLESS，不建节点）：goal / 两级达成（candidate_complete、scientifically_established，"met" 必须带证据）/ budget / ruled_out（带证据 + 节点 + 时间）/ open_directions（替换、追加、关闭）。`finalize_delivery` 的 diagnostic 分支自动把未达层级与未试方向写进 `open_items`（REPORT.json.finalized + MANIFEST.json），**既无记录又无 `unmet_goals` 参数才拒绝**；final 晋级不受此门。AGENTS 模板 **v39**："目标分级与停止规则"（一条路线失败只否决该构型，不否决目标）+ `set_investigation` 一行 + `tool_status.prior_trial` 一句；为守住 9000 字符预算做了等义压缩（delegate 变体 8981）。 |
| `8bfd65a`（顺带） | `threadReducer.ts` 的 CRYSTAL_MUTATING 补 `accept_fragment_pose`（WP5 漏项，`tests/test_ui_tool_sets.py` 抓到）。 |
| R4-c（本文 §4） | 实机证据反哺：`audit_guest_evidence` 检验 3 加**位移对照**；`search_fragment_pose` 候选排序**锚点优先**。 |

工具总数 74（71 + search / accept / set_investigation）。UI：四张新卡（`toolCards.tsx`）。

## 2. 实机一格：Zr-MOF 同题复跑（`H:\CrystalPilot-campaigns\r3\r4-mof`）

- 条件：同 09-05 演示的 brief 与先验（`workdir/live-demos/briefs/r4-mof.md`、`contexts/r4-mof.json`），源 `staging/r25a`，structure_class framework，gpt-6-astra @ xhigh，子代理关，权限 auto，**无人插话**（launcher 只发了一条任务）。日志 `workdir/live-demos/r4-mof-20260906-0130/`，线程 `01a0729f-46aa-7c01-bb00-24cf47f072a3`。
- API：全程没有遇到"暂时不可用"，没有重试。

### 2.1 数字对照

| | 09-05 演示（取证基线） | R4 复跑 |
|---|---|---|
| 人工插话 | 3 次（客体存在 / 要整分子 / 允许非发表级候选） | **0** |
| 墙钟 | 3 h 20 min | **43 min**（01:30:50 → 02:14） |
| MCP 调用 | 398（16 次显式失败） | **123**（2 次失败：一次 `solvent_mask` 全部空洞被丢弃、一次 `run_shelxl` AFIX 预检拒绝，都是如实的拒绝） |
| 节点 / 分支 | 225 / — | 117 / 51 |
| 交付 | D0 n0070 R1 0.0847（无客体）→ D1 n0116 0.1653（仅 Br）→ D2 n0224 0.1699（受约束整客体候选，diagnostic） | 一次：**n0109 diagnostic，R1 0.0860 / wR2 0.2640 / GooF 0.907**（1.000 Å 截断 + 收敛掩膜 ABIN 591.6 e/胞），checkCIF 8A/3B/21C 逐条解释，`restartable: true` |
| 整客体 | 人工推动后逐原子拼出 n0224；自由精修下占有率塌陷 | Agent 自己两次 `search_fragment_pose`，`accept_fragment_pose` c01（占有率 0.1，PART −1，EADP）→ SHELXL 6 组几何 restraint 后 FVAR 0.052(6)、O1 漂移 5.05 Å、C6 2.96 Å → **证伪并记账** |
| 试验重复 | 27 次 fit_fragment 里 15 次零新增，多次同锚点重跑 | 试验账本 14 条，**同节点同输入重跑 0 次**（`prior_trial` 一次都没触发） |

### 2.2 Agent 用新工具做了什么（事件日志）

1. 01:31 第一个回合就 `set_investigation(goal=…, open_directions=…)`，目标写成"独立解析 Zr/TBAPy 类结构并检验对溴苯乙酸处理后是否存在可由衍射建立的完整客体或结合片段；无法建立时诊断性交付"。
2. n0041：以最强孔峰为 Br 锚点 `search_fragment_pose`（SMILES `Brc1ccc(CC(=O)O)cc1`，区域半径 5 Å，占有率假设 0.1），最优候选 3 direct / 2 weak / 6 geometry_only，多个原子距骨架 0.80–0.98 Å；`probe_site` 显示 Br/O 两种假设占有率 0.092/0.391 却同为 ~3.2 e。**记 ruled_out**，并追加方向"扩大排斥距离的全孔搜索"。
3. n0049–n0052：第二次搜索（全孔、`clash_distance` 2.0 Å）→ `accept_fragment_pose(c01, occupancy 0.1, PART −1, EADP)` → `set_restraints` → `run_shelxl`：FVAR 0.052(6)，max shift/su 4.36，O1 漂 5.05 Å。`audit_guest_evidence` 却给出 **supports**（三检验齐绿，其中检验 3 "撤约束后位移 0.00 Å"）。Agent 的原话："audit_guest_evidence 虽标签 supports，但逐原子自由占有率 0.066–0.852，不能代表统一分子计量；其撤限制测试 0.001 Å 位移与真实先前漂移及无效化学不相容，不采纳。" → `tier:candidate_complete=unmet` + ruled_out。
4. n0100 / n0103：两个孔位的无序模型各做了 12 轮 SHELXL 检验（一个 SADI 残差 4.33σ、两位置 0.649 Å 低于有效分辨率；一个 FVAR −2.42 非物理）→ 各记一条 ruled_out，"只否决此两位置模型，不证明孔密度不存在"。
5. n0109：`set_investigation` 把两级都标 unmet（带证据句），六个 open_directions；`write_outputs(status=diagnostic, summary_note, unresolved×9)`；`finalize_delivery(unmet_goals×4)` - MANIFEST/REPORT 的 `open_items` 共 29 项：8 条 A 警报、9 条 unresolved、**goal:candidate_complete、goal:scientifically_established、direction#1–6、unmet_goal#1–4**。

这就是 WP7 想要的行为：目标与构型分离、否决带证据、未试方向留给下一次。

### 2.3 这一格暴露的问题（已修 / 待做）

| 问题 | 处理 |
|---|---|
| `audit_guest_evidence` 检验 3 对 0.07 占有率客体报"撤约束后不动（0.00 Å）→ supports"，而 SHELXL 让同一客体漂 5 Å——位点梯度弱时 LM 不动是惯性不是支持 | **已修（R4-c）**：检验 3 加位移对照，把客体副本刚性移 0.3 Å 再同法精修，`return_fraction` < 0.5 时判 inconclusive（"数据既不把它按在原处也不把它推开"）；`tests/test_guest_evidence.py` 合成客体回到 ≥50%、合成幽灵回不来 |
| Br 锚定搜索里违反锚点的候选靠密度分排第一 | **已修（R4-c）**：满足全部锚点的候选排在前面，分数其次 |
| 掩膜电子数两个口径：`solvent_mask`/交付 591.6 e/胞，`analyze_packing` 只读重算 1193.2 e/胞，Agent 如实标"口径未澄清，不用于计量" | **待做（R5 逐图层范围时一起）**：两处电子数要么同一函数要么各自写明"按胞 / 按显示范围 / 模型快照 nXXXX" |
| Agent 跑了 18 次 shell（分析脚本），其中一次 KeyError 退出码 1 | 允许（分析探索用 shell）；UI 把失败命令单独显示、未折叠（R2 规则在起作用） |
| `write_outputs.metrics.n_params = -1`（占位），指标页显示"未知"（R1 已修显示层） | 数值层待补：从 SHELXL 作业读参数数 |

## 3. 只读验证：旧峰表能不能提出人工路径的候选（计划里的 n0079 检查）

在演示项目的轻量副本（`C:\tmp\claude\mof-n0079`：只拷 nodes + state + 输入，原项目不动）上强制活动节点，跑 `search_fragment_pose`（不接受任何候选，节点序号 225 前后不变）：

| 场景 | 结果 |
|---|---|
| n0079，用节点存的旧峰表（80 峰）与重算峰表各一次，占有率假设 0.3 | 首候选 1 direct / 4 weak / 5 geometry_only，判 **inconclusive**；与 n0224 人工候选的 11 个客体原子**没有一个在 0.7 Å 内**（最近 16 Å，对称等价已考虑），工具没有复现人工路径 |
| n0116（D1：Br 已定位，无整分子），把 n0224 的 Br 位置作为锚点（容差 0.7 Å，区域 7 Å），占有率假设 0.15 | 五个候选全部 **inconclusive**，前三个 Br 距锚点 1.06–1.21 Å（违反锚点，判词点名"the top pose violates an anchor"）；c04 有 2 个原子落在 n0224 客体 0.7 Å 内，其余 geometry_only / weak |

读法：n0116 的差值图里 Br 之外没有整个客体的密度，工具不会凭几何把它编出来；这与取证报告"n0224 候选最弱的氧靠几何先验补入、自由占有率归零、撤约束后分子散开"一致，也与本格 Agent 的结论一致。**工具的诚实门在起作用**，但它也没有拿出比人工路径更好的候选，因为数据里没有。锚点排序问题由此发现并修掉。

## 4. R4-c：实机证据反哺工具（提交见 git log）

- `refine/tools_chemaudit.py`：检验 3 拆出 `_trial()`，跑两次，原位撤约束、位移 0.3 Å 撤约束；`test3_restraints.displacement_control = {displacement_A, mean_distance_after_A, return_fraction, cycles_done, terminated_by, reading: held|partial|not_held}`；supports 需要 return_fraction ≥ 0.5。
- `refine/tools_pose.py`：候选排序键 (锚点全满足 → 0/1, −score)。
- 通用性：对照用的是"随机方向刚性位移 + 同样的 LS"，不含元素、占有率或晶体常数。

## 5. 证据与基线

- UI 证据轮 **r3-r4**（`workdir/ui-evidence/r3-r4/`，36 张）：`e2e/r2b-layout.pw.ts` 6 passed（900 / 1100 / 1440 × 浅深）在 r4-mof 项目上；`1440-light-thread.png` 看到：状态行"空闲 · 上次回合 42:36 · 节点 n0116"、失败的 `solvent_mask` 单行红字、失败的 shell 脚本命令卡（KeyError）未折叠、Agent 的诊断结论段落、交付摘要卡"诊断性 · 节点 n0109 · R1 0.0860 wR2 0.2640 GooF 0.91 · 5 个主文件 · 全部 15 个文件"、回合收束行"已完成 · 42:36 · 节点 n0000…n0116 (40) · R1 0.1822→0.0860 · run_shelxl×13 branch×9 …"。
- 测试：`tests/test_fragment_pose.py`（12）、`tests/test_trial_ledger.py`（9）、`tests/test_investigation.py`（7）、`tests/test_guest_evidence.py`（11）、`tests/test_finalize_delivery.py` 的诊断封存用例改为必须说明未达目标；vitest 315；tsc 干净；全量 pytest **2457 passed / 24 skipped / 3 failed**（10 min 28 s，`workdir/pytest-full-r4.log`），三个失败都是守卫抓到本轮的疏漏：模板压缩时丢了"不杀进程"一句、`test_upgrade_instructions` 的 9000 字符是含绝对路径的总长（delegate 变体 9021）、`set_investigation` 未在 `test_skills` 的分类表登记；随后恢复措辞 / 再删 47 字（delegate 总长 8994）/ 登记，复跑相关五个套件 73 passed。
- tag：`r3-r4-done`。

## 6. 没做 / 边界

- 姿态搜索只用差值图与几何，不做扭转精修后的 SHELXL 试精修（那是 `accept_fragment_pose` 之后 Agent 的事）；大胞 P6/mmm 上 16 000–21 600 个种子 15 s 内跑完，但更大的片段（>20 重原子）与更多构象没有实测预算。
- 试验账本只记 7 个 TRIALED 工具；`prior_trial` 在本格没有触发过，所以"提示是否改变行为"没有证据。
- `set_investigation` 的 tiers 是两级固定枚举；没有做"预算到点自动提醒"。
- n0079 检查只说明"工具不会编造"，不能反证人工候选错，两者都被数据否决。
- 模板预算贴边（delegate 变体 8981 / 9000）：下一轮再加内容必须先删字。
- 掩膜电子数两口径未澄清（→ R5）。
