# ka1 现场观察笔记（跑的过程中随手记，供 KA1-ANALYSIS 定性核读用）

> 只记事实与时间戳，不下结论。所有判断留到六格跑完。

## 2026-09-03 15:55 发射 org + hex；17:02 hex 泳道两格已结束；17:03 补发 cage

### hex（NU-1000，B 臂历史基线 pa3/pa4 publication ≈0.080）

| 格 | 臂 | 等级 | R1 | d_min | 墙钟 | tokens(total) | 原子数 |
|---|---|---|---|---|---|---|---|
| hex-tools-r1 | 纯工具 | publication | 0.0817 | 1.000 Å | 2 319 s（39 min） | 12.7 M | 26 |
| hex-full-r1 | 全栈 | publication | 0.0833 | 0.997 Å | 1 484 s（25 min） | 15.4 M | 26 |

- 参考（课题组手工终解）R1 0.1162 @ 1.10 Å；两臂都比参考截得深（1.0 Å）且 R1 更低，评分器新加的 d_min 对齐正确地把 ΔR1 标成"不可比"，等级按绝对 R1 判（0.08 < 0.10 且元素/群/胞一致）。
- 两臂原子数相同（26）、空间群一致；`composition_max_rel_dev_non_h = 1.0`：与参考组成差一整个元素（大概率参考里有客体/溶剂而交付没有，待核读 SUMMARY）。
- 未评分的 A 级警报：元数据 183/184/185/699（660 只在 tools 臂）；数据质量 020/023 两臂相同。
- 待核读：纯工具臂多花 14 min 与 2.5 M 更少 tokens 的差异来自哪里；有没有做掩膜；ghost/客体处置；VALIDATION 写法。

### org（N-(3-oxobutanoyl)-L-homoserine lactone，P2₁2₁2₁，参考 R1 0.0264 @ CuKα；hkl 由沉积 fcf 反推，消光反射缺失）

**org-tools-r1（纯工具臂），截至 17:05 仍在跑，n_atoms = 0：**

- 1.1 min `get_project_brief` → `ingest_vendor_data(list_candidates)` → `ingest_vendor_data(hkl=crystal.hkl, ins=start.ins)`。
- 1.7 min `screen_space_groups(laue_group=mmm, merge_stats)`：因数据里没有消光类反射，所有候选都是 `no_absence_conditions`；`reflection_statistics(laue_group=all)`。
- 2.3 min `change_space_group("P m m m")` - agent 原话："形式上声明 Pmmm，让 SHELXT 在该 Laue 类内定群"（把中心对称的 Laue 群当占位群声明）。
- 2.5 min `run_shelxt(adopt, all_space_groups, chem_quality, n_phase_sets=100, timeout_s=600)` → **0.001 s 即失败：`no element list available - pass composition='C H N ...'`**。start.ins 里明明有 `SFAC C H N O`（UNIT 是占位 1 1 1 1），会话没把 SFAC 当元素清单暴露出来；agent 把这条错误读成"没有元素清单，SHELXT 用不了"，转投 Superflip，**没有按提示补 composition= 重试**。
- 2.9 min `solve_superflip(maxcycles=1000)` → `superflip did not converge`（Pmmm 下）；3.1 min 改 `P -1` 再 `solve_superflip(maxcycles=5000, allow_low_completeness)` → 仍不收敛（5.9 s）；3.5 min 改回 `P m m m`。
- 3.7 min `solve_charge_flipping(d_min=0.9, seeds=8 个, max_attempts_per_seed=20, max_solving_iterations=5000, max_peaks=80)`，在 **Pmmm（中心对称、错群）** 下，预算 8×20×5000。**此后 60+ min 没有任何工具返回**；agent 每隔一会儿输出一句"计算尚未结束且没有新输出；继续等待最终结论"（agent_message 55 条，其中大量是这类等待语）。
- 17:05 复核：MCP 工作进程（pid 58768）CPU 3 792 s → 10 s 后 3 803 s，即**单核满载在算，不是挂死**；codex 的工具超时 3 900 s 约在 17:03–17:04 到期，之后 agent 会收到超时错误，case 超时 7 200 s 在 17:55。
- 平台侧备注：进程树 `codex.exe → .venv\Scripts\python.exe(存根, 0 CPU) → pyenv 3.12.4 python.exe(真解释器)` 是 Windows venv 启动器的正常形状，不是"MCP 又生了一个 MCP"。`mcp_server.jsonl` 两行（15:55:22 冷缓存、15:55:30 热缓存）= codex 起了两次 MCP 进程（建线程列工具 + 回合执行）。

**三条工具侧信号（候选优化点，等全部跑完再定）：**
1. `run_shelxt` 的"no element list available"在 ins 已含 SFAC 时是误导：至少该说"ins 声明了 SFAC C H N O（UNIT 为占位），如确认化学请传 composition='C H N O'"，或摄入时把 SFAC 作为披露的元素猜测写进会话。
2. `solve_charge_flipping` 无预算上限、无 detach/心跳、无"在中心对称占位群里跑不出非心结构"的提示；一个错误的参数组合能吃掉整个 case 的时间而 agent 只能干等。对比 `run_shelxt` 已有 grace/detach/job_status。
3. `screen_space_groups` 在"数据里根本没有消光类反射"时应明确说"本数据无法用消光判群（可能是已剔除消光的合并数据），只能靠 E 统计/求解试验"，而不是逐群报 `no_absence_conditions`。

### 待观察
- org-tools-r1 超时后 agent 的恢复动作；org-full-r1 是否直接按卡走（read_skill data-ingest…→ 组成 → SHELXT）。
- cage 两格（17:03 发射，tools 先跑）。

### 17:08 追记：codex 超时不会取消服务端计算（平台缺陷，候选 P0）

- 68.7 min：codex 以 `timed out awaiting tools/call after 3900s` 结束 `solve_charge_flipping` 调用；agent 随即改走 `run_shelxt(composition="C" 占位)`。
- 但 MCP 工作进程（pid 58768）CPU 仍在涨：3 994 s → 15 s 后 4 011 s。**电荷翻转在服务端继续算**，项目锁仍被它占着；`run_shelxt` 排在锁后面（agent 两分钟内连说"作业初始化仍未返回"），`QUEUE_MAX_S = 1800 s` 到期它也只会得到"gave up waiting"。case 超时 17:55。
- 结论性事实（不是推断）：客户端放弃调用 ≠ 服务端停止计算；一次无上限的求解调用能拖垮整个 case，且后续所有调用都陪葬。`run_shelxt` 有 detach/grace/job_status 三件套，`solve_charge_flipping` 一件都没有，也没有服务端的"客户端已断开则取消"。
- 这一条与臂无关（全栈臂遇到同样参数也一样），但纯工具臂更容易开出这种预算（模板里没有 SHELXT/求解预算纪律）。留到分析里区分"知识层能防的"与"工具层必须修的"。

## 18:15 org 泳道结束

| 格 | 臂 | 等级 | R1 | d_min | 墙钟 | tokens | 备注 |
|---|---|---|---|---|---|---|---|
| org-tools-r1 | 纯工具 | **no_delivery** | — | — | 7 224 s（超时） | 7.1 M | 从 3.7 min 起被自己开出的电荷翻转预算锁死到 case 超时；codex 3900 s 超时后服务端仍在算，后续 run_shelxt 与监测调用全部排队，agent 从 69 min 到 120 min 每分钟一句"继续等待锁释放"，turn 以 interrupted 结束 |
| org-full-r1 | 全栈 | acceptable | 0.0263（参考 0.0264） | 0.8049 = 参考 | 1 042 s（17 min） | 9.3 M | P2₁2₁2₁ 正确、24 原子、组成与参考完全一致（dev 0.0）、ΔR1 −0.0001 可比；未到 publication 只因评分器化学旗标 |

- **评分器假阳性（待修，跑完 cage 再动 .py）**：`grade.py` chemistry_flags (b) "carboxylate-shaped X-C(-C)-X'" 把酰胺 N1（N–C 1.34 Å，N…O 2.24 Å）判成"羧酸 O 误标 N"。酰胺与羧酸在 C 周围几何相同，区别在 X 本身：羧酸 O 是端基（1 个重原子邻居），酰胺 N 有 2 个重原子邻居（酰基 C + 内酯环 α-C）。规则缺"X 须为端基"条件。参考 CIF 同样标 N，agent 是对的。修后对 ka1-org `--regrade`；这条不影响两臂对比方向（改后 org-full 会升 publication）。
- 这一格是目前最清晰的一次"知识层有用"信号：同一数据、同一模型，全栈臂 17 min 出正确结构，纯工具臂 2 h 空手。但机制要读 transcript 才能定：是技能卡（定群协议/SHELXT 组成）直接给了路，还是模板里的求解预算纪律避开了那个坑。

## 18:15 cage-tools-r1 进行中（17:03 起，72 min，112 次工具调用）
- 用了 branch/edit_atoms(delete, reassign)/solvent_mask(一次失败)/validate_structure/audit_element_assignment/ghost_test×2/set_twin(remove)/refine(aniso_heavy, anisotropic)/run_shelxl(adopt)，纯工具臂在大结构上把工具面用得很开，且自己走到了"去 twin 再各向异性"这种步骤。等结果。

## 19:15 等 cage 期间在 worktree 完成、尚未合并的两支
- `worktree-agent-af02e7c29fcf5c9c2`（fad482a）：评分器 chemistry_flags (b) 只对端基 N（恰一个重原子邻居）触发；合成用例羧酸(阳性)/酰胺/酰亚胺(阴性)；69 passed。残余：伯酰胺 -C(=O)NH₂ 只看重原子时仍是端基 N，几何上不可区分，披露不特例。
- `worktree-agent-aa6ad85b6a95946f6`（dbca44a, 79a0ab4, d809b1b）：T1.1 SHELXL .lst 回读，`warnings`（成功路径也读）、`variance_analysis`（K 按 Fc/按分辨率 + 中位数/MAD 自适应判词，K 可为负的组单独陈述）、`disagreeable_reflections`（Fo²>Fc² 方向计数 + 指标模式，排除格心自带关系）、限制残差 >3σ、shift/esd>1.5 四方向；`situation_report` 加两条掩膜-模型冲突（球近似，边界写进消息）。35 新测试；twin_rz5267 探针：去掉 TWIN 卡后最弱组 K 6.75→43.15、50/50 Fo²>Fc²，方向与 §2.7 一致。
- 合并推迟到 cage 结束：主树 .py 一改，下一次 MCP 冷启动就要在负载下导入 cctbx。
- 顺带发现：`test_template_stays_lean_and_keeps_teeth` 的 14000 字符守卫含仓库绝对路径（worktree 路径长 42 字符 → 14010 失败），合并时改成与路径无关。

## 22:20 cage-tools-r1 结束；cage-full-r1 进行中（Claude 会话曾重启，runner 进程未受影响：pid 26260/55700 仍在）

| 格 | 臂 | 等级 | R1 | d_min | 墙钟 | 原子数 | 备注 |
|---|---|---|---|---|---|---|---|
| cage-tools-r1 | 纯工具 | below_bar | 0.2241（参考 0.1395 @ 0.69 Å，不可比） | 0.996 Å | 8 723 s（2.4 h） | 222 | 群/胞与参考一致；verdict 自报 solved=false、confidence=low，unresolved 写明"轻原子拓扑及 C/N/O 身份未定、H/客体/溶剂未完成、大空洞掩膜未成功"；210 个节点，最佳节点 n0040 R1 0.1977 未交付（Δ+0.026）；阻塞 A 警报 082/084/201/202/241/242/374/602；化学旗标：N43/N48 羧酸形 N（MOF 里这类多半是真误标，与 org 的酰胺不同）、26 条 N–N/羰基长 C–C 可疑键；PLATON 602 未掩膜空洞 23.6%（新 porosity 读法生效，来源 platon rerun）|

- 与历史 B 臂 cage 基线（pa2/pa4：acceptable 0.1405 / below_bar 0.2223）相比落在下端；诚实度上它没有硬凑：solved=false + unresolved 完整。
- 过程侧：2 h 处推翻自己的群/解重来（SHELXT detach + job_status 轮询用法正确）；183 次调用 15 次失败；掩膜失败后未能恢复。待读 rollout 定位 15 次失败的工具与原因。
- cage-full-r1：19:28 起，170 min，133 次调用 7 次失败，现处于逐元素扫描（element_scan/probe_site），R1 尚未出，最长可跑到 00:28。

## 2026-09-04 01:30 事后发现：org-tools 的 MCP 服务进程成了孤儿，多算了 9.6 小时

- 进程 `python -m crystalpilot.mcp --project H:\CrystalPilot-campaigns\ka1-org\pe4fa7e09`（venv 启动器 24092 → 解释器 58768）自 9 月 3 日 15:55 起一直存活；其父进程（该战役项目的 codex）早已退出，战役本身 18:00 左右就按 7200 s 超时收场。
- 杀前取证：4 s 墙钟内消耗 4.2 s CPU（约 1 核持续满转），28 个线程，累计 518 CPU 分钟，工作集 42 MB。这就是 org-tools 那次无预算的 Pmmm 电荷翻转（KA1-ANALYSIS §3.2）：codex 放弃请求后，服务器不但没有取消（WP1 已修），连 stdio 管道随 codex 消失后也不退出，`anyio.run(_run)` 在 stdin EOF 后返回，但工具还在非守护工作线程里跑，解释器在退出时等它。
- 处置：核实命令行与父链属于 CrystalPilot 后按 PID 杀掉（taskkill /PID 24092 /T）。**不是按进程名杀**。
- 归类：工具层执行缺陷（与 WP1 同源，第二种表现）。修法在 `crystalpilot/mcp/server.py`：传输关闭后写一行证据（还在跑的工具名、已耗时）并 `os._exit`，不等待工作线程。同时该案例说明"慢≠卡死、绝不杀子进程"在模板里的代价还包括**机器资源**，不只是墙钟。
