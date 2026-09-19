# CrystalPilot 运行记录质量审计：Round 5–9 + demo/mvp

审计员 B（r10 的 770/780 由另一位审计员负责，本文不涉及）。
生成：2026-08-30。数据源全部只读。

## 0. 数据源与方法

逐行解析各项目 `CrystalPilot Results/task_*/transcript.jsonl`（事件 kind：
tool_started/tool_completed/command_started/command_completed/approval_request/
approval_decision/user_steer/agent_message/turn_*），统计 ok=false、payload
`"ok": false`、exit_code≠0、started 无对应 completed（挂起/中断）、连续重试、
shell 中含晶体学关键词的调用；并与 ROUND5–9_NOTES.md 交叉印证。

| 项目 | transcript | 事件数 | MCP 完成/发起 | shell 命令 | MCP 失败 | shell 失败 | 损坏行 |
|---|---|---|---|---|---|---|---|
| r5-onitwin A | task_20260829_102829 | 275 | 54/54 | 20 | 2 | 1 | 0 |
| r5-onitwin B | task_20260829_154238 | 32 | 0/0 | 0 | – | – | 0 |
| r6-wco6 | task_20260829_162047 | 749 | 5/11 | 166 | 3 | 12 | 0 |
| r7-scratch | task_20260829_184311 | 4 | 0/0 | 0 | – | – | 0 |
| r7-cdmof | task_20260829_191329 | 357 | 72/72 | 23 | 9 | 2 | 0 |
| r8-dymof | task_20260829_222902 | 717 | **0/0** | 169 | – | 23 | 0 |
| r9-dymof2 | task_20260830_001411 | 649 | 101/105 | 32 | 8 | 2 | 0 |
| demo-live A | task_20260829_035635 | 192 | 50/50 | 4 | 1 | 0 | **3** |
| demo-live B | task_20260829_120538 | 9 | 1/1 | 0 | 0 | – | 0 |
| mvp-sjtu9 | task_20260828_170601 | 154 | 43/42 | 3 | 0 | 0 | 0 |
| mvp-p24cu | task_20260828_172100 | 493 | 124/117 | 6 | 3(+2 噪声) | 0 | **4** |

跳过说明：r5-onitwin/B 是连接性调试会话（无工具调用，见 §1.2）；r7-scratch
是多模态冒烟测试（1 问 1 答，通过，无问题）；demo-live/B 是单工具审批拒绝
测试（按设计工作，见 §7）。mvp-frames_lcyst 不在指派范围，仅在 §3 引
ROUND6_NOTES 作 MCP 启动缺陷旁证。

优先级口径：P0=损坏交付物/整战役降级；P1=高频阻断或审计完整性；P2=摩擦/上游。

---

## 1. r5-onitwin（邻硝基苯胺，精修交付战役）

工具失败：run_shelxl 1/7，refine 1/6。shell 1 失败（无关紧要的 rg 空匹配）。

**R5-1. run_shelxl(mode=check, l_s=0) 与 ACTA 冲突，必然失败。** L68：
`** L.S. 0 incompatible with ACTA **`，job.res 为空、无摘要。agent 被迫改用
l_s=1 对账（L69→L73 成功）。跨战役复发（见 §2 C1）。根因：check 模式写
ACTA 进 job.ins 却允许 l_s=0。修复：l_s=0 时剥 ACTA 或强制最小 1 循环。P1。

**R5-2. rename_atoms(canonical) 后氢约束索引失效，refine 硬失败。** L101 规范
重命名 64 原子 → L105 `InvalidConstraint: stored hydrogen constraints are
stale … expected 'HC14A' at index 40`。agent 重跑 add_hydrogens（L110）恢复。
属跨战役 stale-H 家族（§2 C2）。重排序类工具应自动刷新 h_constraints。P1。

**R5-3. set_twin/run_shelxl(adopt) 不拦不标 BASF 发散。** L85 反演孪晶试验
返回 ok=true，但 BASF 精修到 −2.098（合法域 0–1 之外），summary 无任何
sanity 标记，靠 agent 读数识破（L86 自述）。建议 adopt 摘要加 BASF 越界
警示字段。P2。

**R5-4. 输出装配继承粗解 ZERR，CIF 化学式/Z 错误（静默）。** L201：
write_outputs 沿用粗解 `ZERR 7` 产生分数化学式，agent 手工修 CIF/RES 元数据。
工具 ok=true，错误无告警。P1（见 §5 S5）。

**R5-5. 晶胞测定元数据在 state.json→context→CIF 链路丢失。** L208/L213：
staged 状态文件明明存有"1292 反射、θ=1.399–30.999°、DIALS"，context 同步
遗漏 → 3 个本可避免的 checkCIF A 警报，agent 手工回填。ROUND7 §3 已内化
（scale_and_export 写 context + publication.py 消费），待端到端确认。P1→已修待验。

背景（平台侧，ROUND5_NOTES）：本数据集 sfrm 路线因 dxtbx FormatBruker
摆动 2θ+固定 χ φ 扫几何缺陷整体不可索引，靠作者 CBF 转换绕行（上游缺口）；
find_spots 默认 min_spot_size=6 吞掉 >50% 提取斑点，notes 建议工具暴露参数
并在过滤比例过高时告警。P2 工具默认值缺口。

### 1.2 r5-onitwin/B：连接性中断记录（harness 证据）

task_20260829_154238：10 条 "Connectivity test … reply OK" 用户消息，仅第 7
条与最后 1 条得到 "OK"，**其余 8 轮 turn_completed 但 agent 零输出**（含
"expect visible failure reason" 探针也无错误浮出）。时间点在 r5A（10:28）与
r6（16:20）之间，与 r6 会话内 Transport closed 同期。问题：模型/连接失败时
harness 静默完成 turn，不给用户可见错误。P1。

---

## 2. r6-wco6（W(CO)₆ 原始帧全链路）：故障级联样本

MCP：11 发起/仅 5 完成；get_project_brief 3 次 `Transport closed`；
find_spots 4 次发起全部无 completed；import_frames 1 次中断。shell 166 条
（124 条晶体学相关），12 条失败。审批 151 次全人工 accept。

**R6-1. 工具版 find_spots 启动后停滞（0 CPU），两次挂死。** L17 首次发起，
等待 5 分钟后（L21–L23 三轮等待消息）进程检查发现 dials.find_spots CPU 几乎
不增长（L27/L28），无日志无反射表（L37）→ 定点杀 PID 重试（L45），第二次
同点停滞（L46/L53）。P0（当轮已修，见 R6-9）。

**R6-2. 诊断性直跑裸 exe 崩溃 0xc06d007f，agent 误诊根因。** L65 直跑
dials.find_spots.exe 崩在 `FormatROD._detector` 的 Windows DLL 加载异常；
L96 经 `conda run` 同命令 18.8s 成功 → agent 判定"根因是 CONDA_PREFIX 缺失"
（L111）并自建 dials-wrapper。**ROUND6_NOTES A/B 实测否定该假设**（87.3 vs
86.5s）：真凶是 Windows 下 dials.find_spots 多进程病理（nproc=1 11.6s /
nproc=4 86.5s，worker 重开 imageset）叠加机器争用。教训：单点对照即下结论
的诊断被平台基准推翻；工具默认已改 nproc=1。P0→已修。

**R6-3. 按进程名单选 PID 强杀，连 MCP 服务器一起杀死；会话内不重生。**
L27 用 `ProcessName -match 'python|dials'` 列进程 → L156
`Stop-Process -Id 39324,18352 -Force`（两个 PID 来自该名单，未核父链）→
L161/L163/L227 起 get_project_brief 全部 `Transport closed`，**余下全程
（约 1 小时）纯 PowerShell**。codex 限制：MCP 服务器死亡后会话内不重连
（ROUND6_NOTES 明记）。这就是"满屏 PowerShell"的根因，也是长期记忆
"绝不按名杀进程、先核父链"的出处。P0。

**R6-4. shell 直跑 staged 阶段绕过 state.json 阶段记录，破坏工具链前置检查。**
用户 steer（L182）明确指出：直跑的 find_spots/index 没写 stages 记录，后续
integrate_frames 等会被拒；给出补记/整链自跑两条路。工具缺口：无"外部完成
阶段的合法回填/收养"入口。P1。

**R6-5. MCP 死后 agent 自建 `invoke_tool.py` 直调 RefineProject.invoke_tool。**
L233–L246 读源码定位入口 → L246/L279 首两次调用因 PowerShell 引号吞噬 JSON
参数报 JSONDecodeError → L262 起发明 **base64 参数编码** 才稳定，并以此走完
建模/精修/checkCIF 全程（L262–L726 约 60 次）。保住了节点审计（幸运），但
暴露：a) 无官方本地 CLI 兜底通道；b) PowerShell 传参摩擦。P1。

**R6-6. 并发访问触发 state.json.tmp PermissionError。** L377 validate_structure
经 invoke_tool 调用时 `PermissionError: …\refine\state.json.tmp`（Windows 文件
锁）。busy-lock 显式报错已列入 ROUND6 修复清单。P1→已修待验。

**R6-7. σ=0 占位记录链路静默通过，GooF 爆到 529。** dials.export 写出 7 条
σ≤0 占位反射进 crystal.hkl，refine/统计全程 ok=true 无告警，直至无权重
GooF=529 暴露（ROUND6_NOTES；transcript L659–L691 用
select_good_intensities + 自写 filter_zero_variance.py 客观剔除后重精修）。
R7 已内化 `clean_hklf4`。P0→已修（§5 S4）。

**R6-8. run_checkcif 依赖 PATH 上的 shelxl，工具不自备。** L498 找 shelxl 的
递归搜索超时 600s（exit=124）→ L502 rg 找到 vendor\shelx\shelxl.exe → 此后
每次 checkCIF 都要 `$env:PATH='H:\CrystalPilot\vendor\shelx;'+…` 前置
（L642/L710/L726）。run_checkcif 应自带 vendor 路径。P2。

**R6-9. 其余 shell 摩擦。** conda 外层 MTZ 导出因 PowerShell/GBK 编码报错
（L211，agent 判为包装显示问题串行补跑）；`Get-Content` 相对路径/不存在
节点文件 4 次踩空（L310/L528/L538/L542——.crystalpilot 内部布局靠猜）。P2。

本轮平台修复（ROUND6_NOTES，均由本次故障驱动）：长阶段心跳、busy-lock
显式报错、find_spots nproc 默认、MCP spec-cache 启动（根除 mvp-frames_lcyst
L-cysteine 案的启动超时→84 shell 调用降级；numpy 必须在主线程先 import 的
OpenBLAS DllMain 死锁）、sg_screen 工具化、AGENTS v10。

---

## 3. r7-cdmof（CD-MOF 文献结构复核）+ r7-scratch

工具失败：run_shelxl **8/14**，refine 1/4。r7-scratch 无问题（多模态冒烟通过）。

**R7-1. SHELX `!` 行内注释被当指令内容。** L30 首个 run_shelxl：
`** WRONG NUMBER OF ATOM NAMES **`。根因：导入解析未先剥行内注释再拼续行。
当轮已修（_logical_lines，ROUND7 §6 缺陷 1）。P0→已修。

**R7-2. checkout/start-model 的 add_hydrogens 重放有损，分占位/特殊 AFIX 氢
每次检出都被毁。** 400→345 原子（每次复发）；transcript 中同一 C6J AFIX 错误
四次复发：L81、L174、L237、L280 全是
`** Cell contents from UNIT instruction and atom list do not agree ** / BAD
AFIX 13 CONNECTIVITY … C6J`；另 L67 `No match for H174 in DFIX`、L126 一串
BAD AFIX 13/23。8 次 SHELXL 失败中 6 次源于此族。当轮已修
（_h_replay_is_lossless 守卫 + PART 卡补写，ROUND7 §6 缺陷 2）。P0→已修。

**R7-3. edit_atoms 删 H 不清 h_riding_meta，删掉的 H 被重放复活。** L177
agent 自述"平台把原作者四个半占位 H 压成化学上不正确的单 H"→ 删 H6J →
L193 refine 失败 `expected 'H6J' at index 344`。当轮已修（删除时修剪
per_carrier + 清 h_constraints，ROUND7 §6 缺陷 3）。P0→已修。

**R7-4. 原始分占位氢无法往返，成为交付差距的直接原因。** L198：最终 R1 比
文献高 0.0022，agent 归因"重算掩膜 + 无法保留原分占位氢"。R7-2/3 修复后
声称三代往返稳定（400 原子/195 H/56 PART），本 transcript 里的交付仍带损失
且已如实披露。P1（历史交付注记）。

**R7-5. 单次 optimize_weights 325s**（L208），重 MOF 下权重扫描成本高，
无中间进度。P2 效率。

运维（ROUND7 §6）：起任务忘设权限档位，copilot 默认 → **52 个 MCP 写工具
逐个 elicitation 等批**；agent 把审批等待误读为"文件系统偏慢"（审批等待对
agent 不可见），催生 v12 等待提示与 r9 服务端自动审批。P1→已修。

---

## 4. r8-dymof（Dy-MOF 原始帧，29GB Zenodo）：零 MCP 战役

**全程 0 次 MCP 工具调用**（无 tool_started 事件），169 条 shell（70 条晶体
学），23 条失败；审批 138 放行/3 误拒。

**R8-1. 会话未走 MCP 的双重叙事，节点库全空 → UI 侧栏失明。** agent 开场
（L35）自述"**当前会话没有暴露精修工作台的类型化帧工具**，因此使用项目指定
的 crystalpilot.io.frames_dials 后备入口"；ROUND8 §2b 事后定性为"强 agent 读
源码后绕开 MCP 舒适路径直驱底层 API"，且解算走老 SolveSession 栈
（runs/run_*/artifacts），从未触碰会建节点的 refine 栈 → NodeStore 不存在、
节点树/3D/回合摘要全盲，审计链降级为散落 REPORT.json。两种解释（会话工具
配置缺失 vs agent 绕开）transcript 无法裁决，**建议核对该 task 的 MCP 挂载
配置以定责**。制度修复：AGENTS v13"模型级操作必须走 refine 工具"硬规 +
SolveSession runs 一键晋升节点（待办）。P0。

**R8-2. 审批守护 3 次误拒 + "approval request failed" 直接判 shell 失败。**
`\bformat\b` 黑名单误伤 PowerShell Format-Table：L501/L512/L579 reject →
对应命令以 exit=-1 "approval request failed" 记失败（L503/L514/L581），agent
换写法绕过。正则已改 `format\s+[a-z]:` 并固化回归测试（ROUND9）。P1→已修。

**R8-3. 结构解算能力缺口：charge flipping 全败，无 SHELXT/双空间备选。**
`crystalpilot.cli solve` 两轮（L273 P6₃/mmc 族、L295 P6₃22）全部
"structure solution failed on all charge-flipping attempts"；搜遍全盘无
shelxt/shelxd/superflip（L283/L305–L316，其中全盘递归搜索 600s 超时
L306）。agent 被迫手写 Patterson 搜 Dy（两次 cctbx assert 崩溃后才通，
L375 `assert self.anomalous_flag() == False`、L383 gridding symmetry_flags
assert）。重原子/超结构体系需要 Patterson/双空间工具化。P1。

**R8-4. DIALS 3.30 上游 bug：reindex 非整数指标置 (0,0,0) → scale uint64
溢出。** L418 `OverflowError: Python integer -1 out of bounds for uint64`；
agent 显式过滤 13231 行后成功（filter_c_half_reflections.py，失败日志留存）。
值得上报 DIALS 并在 scale_and_export 内防御。P1。

**R8-5. .venv 里 mmtbx.xtriage.exe 连续 3 次静默失败（空输出 exit=1）。**
L143/L147/L151 同命令三连败无任何诊断 → agent 改用 iotbx 一行式。Windows
下该入口疑似损坏；三次重复同命令也属低效。P2。

**R8-6. iotbx 读 SHELX .hkl 需 `=hklf4` 提示。** L116 直读失败（长提示教育
文案），L132 `dials.hkl=hklf4` 才通，已知 cctbx 坑，可包一层。P2。

**R8-7. PowerShell 5.1 无 `-Encoding Latin1`。** L46/L537 两次踩同坑（读
CrysAlisPro latin-1 元数据）。P2。

**R8-8. 自动流水线产出 R1=0.0449 的"漂亮假模型"。** 溶剂掩膜盖 89.9% 晶胞
吸收 1948 e/胞、模型仅 7 个 C 无 Dy，被 agent 识破拒绝（ROUND8 §2）。
工具未对"掩膜体积占比异常高"设防；estimate/validate 应告警。P1（§5 S7）。

其余：gemmi/cctbx API 试错各 1 次（L635→L639、L344→L348）；已知晶胞索引
三连败（L178/L191/L212）为受控参数试验并留证，非盲扫，不计缺陷。

---

## 5. r9-dymof2（sample_02 对照 E2E）

MCP 101 完成/105 发起（find_spots 4 次发起无回）；失败 8；shell 32（14 晶体
学）；审批 109 全自动放行（服务端内化生效）。

**R9-1. 宿主 spawn 链 DLL 加载器冻结：find_spots 三个中继方案全败，最终
WMI。** transcript：L34 import_frames 在 **MCP 900s 上限超时**（`timed out
awaiting tools/call after 900s`，底层 DIALS 未死，L36 只读对账后收养产物）；
find_spots 首跑冻结 ~43–47 分钟（L43–L99 约 25 条"仍在等待"消息），修复尝试
链 = 净化环境 ✗ → cmd 中继 ✗（L127–L135，第三次调用连服务重启一起中止）→
**WMI Win32_Process.Create 启动路径**（L135 起）后 572s 完成 27983 强峰。
ROUND9 §3b 详录（commit 81c62ff/385d604/6a4c2f4；codex tool_timeout
900→3900s）。P0→已修。

**R9-2. "no stored difference-map peaks - refine first"：分支/改模后峰表
不可用。** L324 add_atoms_from_difference_map 失败，白等一轮 refine 再来。
与 demo-live/A L139 同款（§6）。r10 提交 7f6a4fc"one peak table for map
tools (#14)"即此修复。P1→已修（r10）。

**R9-3. inspect_map 峰坐标与 model_disorder 校验不同像，直接给会拒。**
L472 用 inspect_map 报的 0.70Å 邻峰直接喂 model_disorder → "second site is
5.05 A away"（那是对称等价像坐标）；agent 只读做胞/对称变换折回同一邻近像
（L473 自述）才通过。工具应把峰坐标规约到目标原子最近像。P2 UX。

**R9-4. 诚实门批量拒绝（按设计，非缺陷，但记录摩擦）。** model_disorder 拒
特殊位置 DY3 拆分（L350，给出替代路径）；change_space_group 拒 P6/mmm
（L386，匹配 0.500）与 P6/m（L459，0.400）；assemble_asu 两次如实拒绝提交
（L502 5→5、L549 4→4，"搬运造不出键=物理事实"）。全部有清晰错误文案与
下一步指引，防线按预期工作。

**R9-5. run_shelxl(check, l_s=0)/ACTA 再现。** L507，同 R5-1。P1。

**R9-6. 交付 CIF 温度 293K 为 SHELXL 缺省而非实测**，已在 VALIDATION 披露
（ROUND9 §3）。元数据管线仍无实测温度来源。P2（§5 S8）。

效率注记：import 900s(超时)+find_spots 572s+index 333s+integrate 473s 均为
合理长阶段；真正浪费是冻结期 ~40+ 分钟与 ~30 条轮询消息（上下文膨胀）。

---

## 6. demo-live-sjtu9（现场演示 Zr-MOF）A/B

A：50 MCP 调用，1 失败；4 shell；34 审批；**3 条 transcript 损坏行**。

**D-1. 分支+edit 后峰表失效（同 R9-2）。** L139 `no stored difference-map
peaks - refine first` - branch(L131)+set_occupancy(L135) 后直接取峰失败，
多花一轮 solvent_mask+refine（L143/L147）再取。P1→已修（r10 #14）。

**D-2. 交付模型含匿名半占位 O6X，静默错误，外部专家才抓到。** L151
add_atoms_from_difference_map 加入 O6X（occ 0.5，距 O007 0.36Å，ok=true），
分支 R1 0.0743→0.0624 被采纳交付；当时 validate_structure 无 ghost/ASU 检查
→ 交付"找不到的氧"（孤立、Ueq 0.157）。R9 复现：删除重精修 ΔR1=+0.012 证明
密度真实=未建模孔道水；规范处置后 rename O1W，置信度 31→88.4
（ROUND9 §1/§2b）。防线（ghost_atom_suspect/asu_detached/assemble_asu）
r9 已入 validate_structure。P0（历史交付）→防线已建。

**D-3. solvent_mask 摘要内部数字自相矛盾（未解释）。** L155：单一空隙
`"electrons": 5259.5` 而同一结果 `total_solvent_electrons_per_cell: 1977.4`
（3.4 秒前 L143 两值一致 1673.7/1673.5）。ok=true 无告警。疑似掩膜迭代中间
值/单位混淆，**建议核查 solvent_mask 汇总代码**。P2（潜在静默）。

**D-4. transcript.jsonl 3 行损坏。** L74/L103（approval_request 长
tool_description 被截断成孤行）、L187（agent 长消息行首即乱码 `��性精修`）。
见 §9 C8。P1。

B（task_120538）：单次 rename_atoms 的 elicitation 被拒后 agent 正确报告
"未执行、模型无改动"并停，审批拒绝路径按设计工作，无缺陷。

---

## 7. mvp-sjtu9 / mvp-p24cu（8-28 两个 MVP 战役）

mvp-sjtu9：43 调用 0 失败，运行顺畅。但见 §5 S1 静默错误。

mvp-p24cu：124 完成/117 发起（差值与 4 条损坏行一致）；实际工具失败 3。

**M-1. refine stale-H InvalidConstraint（家族第三例）。** L257，删/改原子后
`expected 'H13A' at index 39`。P1（r7 已修，本战役早于修复）。

**M-2. checkout 恢复节点强行重建 19 个骑乘 H，污染最终态。** L402 agent：
"恢复节点时工作台又按旧分类重建了 19 个 H……避免这个已识别的氢约束恢复缺陷
污染交付物"——被迫设计"最后不再 checkout"的流程绕行，并重做整条
掩膜+精修+SHELXL 链（L412–L446，约 8 次额外调用）。即 R7-2 缺陷的 8-28
现场版。P0（当时）→r7 已修。

**M-3. add_hydrogens 无载体黑白名单 → 元素改判魔法。** L412 把 C13/C27/C32X
临时 reassign 成 O → L416 add_hydrogens(elements=["C"]) → L420 改回 C，以
排除 3 个不该带 H 的碳。工具缺参数（include/exclude carriers）。P2 工具缺口。

**M-4. run_shelxl(check, l_s=0) → "could not parse R factors"。** L330，
ACTA/L.S.0 家族的另一报错形态（连报错文案都不一致）。P1（并入 C1）。

**M-5. run_checkcif PLATON 300s 超时，本战役最终无 checkCIF 交付。** L406
超时 ok=false；agent 记为外部验证工具限制写入 unresolved（L408、L447），未
提升 timeout_s 重试。建议：超时可续跑/后台化，或提示可调大。P2。

**M-6. transcript 4 行损坏**（L176 两 JSON 粘连 Extra data；L276/L302 截断；
L460 长 SUMMARY 消息断行）。见 §9 C8。

---

## 8. 静默错误专节（工具 ok=true / 交付后才暴露）

- **S1 mvp-sjtu9：交付 confidence:"high"，实为 4 片段 ASU。** 最终自评
  chemistry_ok:true（transcript L153），R9 专家复现 identity 键图 13+4+2+2
  ，三个浮块只经对称连接（ROUND9 §1）。当时 validate_structure 只有对称等价
  重复计数 warning，无 ASU 连贯检查。
- **S2 mvp-p24cu：3 片段（41+8+1）+ 孤立 O5 + 6 个 C 的 Ueq 超标 3-4 倍**
  照常交付（ROUND9 §1）。
- **S3 demo-live/A：匿名 O6X 幽灵疑似原子交付**（本文 D-2；R9 裁决为真实
  孔道水，属"身份未声明"而非纯幽灵）。
- **S4 r6：7 条 σ=0 占位反射静默进入精修，GooF=529 才暴露**（R6-7）。
- **S5 r5：write_outputs 继承 ZERR 7 → CIF 分数化学式/错 Z**（R5-4）。
- **S6 demo-live/A：solvent_mask 空隙电子数 5259.5 vs 总数 1977.4 自相矛盾**
  （D-3，未解释，建议查）。
- **S7 r8：自动解算流水线 R1=0.0449"漂亮"假模型**（掩膜盖 89.9% 晶胞吸收
  1948 e，模型仅 7C 无 Dy），agent 自行识破，但工具层无掩膜占比防线（R8-8）。
- **S8 r9：final.cif 温度 293K 为 SHELXL 缺省值非实测**（已披露，R9-6）。

S1–S3 的共同根因（ASU 连贯/幽灵检测缺失）已由 R9 commit 14f3cc3 补防线
（asu_coherence/ghost_suspect/assemble_asu + AGENTS v13 铁律），三个结构
复检 detached 8→0。

---

## 9. 跨战役共性问题汇总（按出现频次/影响排序）

- **C1 run_shelxl(mode=check, l_s=0) 与 ACTA 不兼容**: 5 个战役踩中：r5A
  L68、r6 L556（消息）、r7-cdmof L63、r9 L507、mvp-p24cu L330（变体文案）。
  每次都靠 agent 改 l_s≥1 绕行。最高频纯工具 bug，修复成本极低。P1。
- **C2 氢约束/氢重放家族**: 6 处：stale InvalidConstraint 3 例（r5A L105、
  r7 L193、p24cu L257）+ checkout 有损重放 3 战役（r7 四次 C6J 复发
  L81/L174/L237/L280；p24cu L402 十九 H 重建；r7 400→345 原子）。r7 当轮修复
  （逻辑行注释/无损重放守卫/删 H 清 meta 三连），r7 之后未再现。当时 P0。
- **C3 Windows 子进程启动病理（spawn 链冻结/多进程停滞）**: r6 两次挂死
  + 误诊（R6-1/2），r9 三方案拉锯至 WMI（R9-1），合计浪费 ≥1.5 小时与两
  条战役的节奏。P0→r9 已修（WMI + nproc=1 + 心跳）。
- **C4 MCP 调用超时/中断与底层任务脱钩**: r9 import_frames 900s 超时但
  DIALS 仍在跑（L34/L36）；r6 import 中断但阶段已完成（L13/L16）。收养机制
  可用但要靠 get_project_brief 侦查。tool_timeout 已 900→3900s。P1→已修。
- **C5 MCP 服务器死亡=整会话降级 shell，且不重连**: r6 杀进程级联
  （R6-3）；mvp-frames_lcyst 启动超时案（ROUND6_NOTES：84 shell 调用降级，
  spec-cache+numpy 预导入已修启动路径）。**会话内重连/重生仍是 codex 侧
  未解限制**。P0（残留风险）。
- **C6 峰表生命周期**: demo A L139、r9 L324 两例"refine first"白耗；r10
  #14 已修。P1→已修。
- **C7 审批摩擦**: r7 52 写工具逐个等批+agent 误读等待为慢 FS；r8 外挂
  守护 3 误拒（`\bformat\b`）+ approval request failed 判败重试；r9 服务端
  内化后 0.0–0.3s 放行。P1→已修。
- **C8 transcript.jsonl 损坏行（审计完整性）**: demo A 3 行 + p24cu 4 行：
  超长事件（approval_request 的 tool_description、长 agent 消息）被截断/两
  JSON 粘连，伴随 p24cu started/completed 计数错位。写入端非原子/缓冲切割
  嫌疑。**尚无修复记录，建议排查转录写入层**。P1。
- **C9 出版元数据管线**: ZERR/Z 继承（r5）、晶胞测定统计丢失（r5，R7 内
  化）、温度缺省 293K（r9）、晶体外观/尺寸无处可取（r5/demo A 的 A 警报，
  数据侧确实无记录属诚实保留）。P1 部分已修。
- **C10 结构解算备选缺口**: r8 charge flipping 全败后无 SHELXT/双空间/
  Patterson 工具（R8-3，手写脚本补）。P1。
- **C11 全盘递归文件搜索超时 600s**: r6 L498、r8 L306（找 shelx 二进制）。
  工具/文档应直接告知 vendor 路径。P2。
- **C12 PowerShell 生态摩擦**: JSON 传参引号地狱→base64（r6）、GBK/编码
  （r6 L211、r8 L46/L537）、rg glob 引号（r8 L611）。P2。
- **C13 cctbx/DIALS 上游坑**: uint64 溢出（r8 L418）、xtriage 损坏
  （L143×3）、patterson asserts（L375/L383）、iotbx =hklf4（L116）、dxtbx
  FormatROD 裸启动 DLL 异常（r6 L65）、FormatBruker 几何缺口（ROUND5）。P2
  （包装层消化 + 上游上报清单）。
- **C14 会话开场 get_project_brief 连打 5 次**: r6 L5、r9 L38（超时后侦查）
  ；轻微轮询浪费。P2。

## 10. shell 绕道清单（工具缺口信号）

按"agent 用 shell/脚本做了本应有工具做的晶体学操作"归纳：

1. **r6 全链降级**：MCP 死后 dials.index/refine/integrate/symmetry/scale/
   export 全部 conda run 直跑（L176–L211、L449–L483），后段建模经自建
   invoke_tool.py base64 直调（L262–L726）。→ 缺：本地 CLI 兜底 + 服务重生。
2. **r6 数据清洗**：filter_zero_variance.py、select_good_intensities、
   dials.filter_reflections（L659–L683）。→ R7 已工具化 clean_hklf4。
3. **r6 按指定群重缩放**：dials.reindex 'P c m n' + dials.scale（L449/453）。
   → R7 已工具化 scale_and_export space_group=。
4. **r6 EXTI 试验**：手工拷 job.ins 直跑 vendor shelxl.exe（L510–L520）。
   → run_shelxl 无自定义指令注入口。P2。
5. **r6 晶胞测定统计**：cell_measurement_stats.py（L602）。→ R7 内化。
6. **r8 整轮**：run_free_supercell/run_average_cell/run_c_half.py 驱动
   crystalpilot.io.frames_dials；crystalpilot.cli solve；手写 Patterson
   （patterson_dy_search.py）、卫星峰统计（analyze_satellites.py）、Dy 占位
   /无序网格比较（compare_dy_*.py，等价于占位扫描工具）、gemmi 拼
   PARTIAL_DY_MODEL.cif。→ 缺：Patterson/重原子搜索、占位扫描、部分模型
   CIF 装配工具；SolveSession runs 晋升节点（待办）。
7. **r9 对称像折算**：cctbx 一行式把差值峰折回目标原子邻近像喂
   model_disorder（L477）。→ R9-3 的工具侧规约缺口。
8. **r9/r6/demo A 取证拷贝与 checkCIF 产物搬运**（platon.out/model.chk/
   日志→evidence/）。→ write_outputs 可选 evidence 打包。P2。
9. **mvp-p24cu 选择性加氢**：reassign 元素魔法（M-3）。→ add_hydrogens
   缺 include/exclude。
10. **r5 消光审计脚本** symmetry_absence_audit.py（交付目录内，配合
    check_symmetry 结论），观察类自补，可接受；后续 audit_reflection_data
    已覆盖大半。

## 11. 结语

r5→r9 的曲线整体健康：MCP 失败多为"诚实门"按设计拒绝（r9 尤其明显），
真缺陷大都在当轮或次轮闭环（C2/C3/C4/C6/C7/C10 部分）。**仍开放的三件事**：
C5 的 MCP 死亡不重连（codex 侧）、C8 transcript 损坏行（审计完整性）、
D-3 solvent_mask 数字矛盾（需核查）；外加 C1 这个五连击小 bug 若 r10 仍未
修，性价比最高。
