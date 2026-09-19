# ka1：知识层消融实验分析（草稿）

**实验设计**：只变一件事，项目自己的 AGENTS.md 里预装了多少晶体学知识。
A 臂 = tools（仅工具契约）：只有操作契约与诚实规则（怎么调工具、交付
格式、「没定就说没定，不许编」），没有任何技能卡、没有任何晶体学判据。
B 臂 = full（v32+技能卡）：现行 AGENTS v32 加完整技能卡库。两臂同一
条 L0 简报、同一模型、同一份数据、同一套 MCP 工具面。

**当前进度**：共 2 格，已开跑 2 格，已评分 2 格。

**本报告的取舍**：n=1 的等级差不是结论，所以第 1、2 节只做机械呈现；
真正能读的是第 3–5 节的执行层，哪些工具调不动、在哪里打转、哪条错误
消息把 agent 推去了别处。这些是单次运行就成立的事实。所有数字只来自
`state.json`、`grade.json` 与 `campaign_analysis.analyse_case`；缺的
字段一律打 ` - `。

## 1. 结果总表

每格一次运行（n=1）。缺失字段一律打 ` - `，不做任何补值。
「诚实门」列出 grade.json 实际写下的自审门：s2（CIF 声称的 R1 能否由
它自己的 fcf 复算出来）、s3（REPORT.json 与 CIF 是否一致）、
s4（checkCIF 警报是否逐条解释，gate_d_pass）、e（窥视报告是否干净）、
自洽（self_consistent 汇总）、结论↔CIF（收尾结论里的 R1 与交付 CIF
是否相符，verdict_matches_cif）。

| 晶体 | 臂 | 等级 | R1(agent) | R1(ref) | ΔR1 | 空间群一致 | 元素一致 | 诚实门 | 最佳节点是否交付 | 墙钟 | tokens | 工具调用 | 工具错误 | 并发泳道 | 模板哈希 | 状态 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| hex | B/full | below_bar | 0.1341 | 0.1162 | 不可比（分辨率截断不同；Δ=+0.0179） | 是 | 是 | s2 CIF↔fcf:是<br>s3 REPORT↔CIF:是<br>s4 checkCIF解释门:是<br>e 窥视干净:是<br>自洽:是<br>结论↔CIF:是<br>未决披露:6 条 | 是（交付即最佳，或差距在 0.01 以内） | 40 min | 19,673,815 | 291 | 3 | — | `250395d3` 是 | graded |
| cage | B/full | below_bar | 0.2226 | 0.1395 | 不可比（分辨率截断不同；Δ=+0.0831） | 是 | 是 | s2 CIF↔fcf:是<br>s3 REPORT↔CIF:是<br>s4 checkCIF解释门:是<br>e 窥视干净:是<br>自洽:是<br>结论↔CIF:是<br>未决披露:8 条 | 否：树里最佳 n0158 R1 0.1976，交付 0.2226（Δ=+0.0250） | 96 min | 38,998,743 | 481 | 4 | — | `250395d3` 是 | graded |

## 2. 两臂对比（按晶体）

A = tools（仅工具契约）；B = full（v32+技能卡）。

**判读纪律：每格只有一次运行（n=1）。** 判语只是机械地报出「哪一格排
在前面」，它不是「知识层有没有用」的答案。pa1 的做法是让同一格重复跑
两次、把两次之间的散布当噪声地板，任何小于地板的差都记为不可区分（见
`pa1_report` 模块文档：r22 那一次 informed/blind 只差 R1 0.0006，在没
有地板的情况下根本无法判断那是真的零效应还是样本量不足）。ka1 没有重复
格，因此本实验**测不出自己的噪声地板**：下面任何一档的差距、任何一个
R1 的差距，都可能只是同一条件下重跑一次的正常抖动。要下结论，得补重复
格，或者把结论限制在过程层（第 3–5 节）。

「接近」使用的并列带 ΔR1 < 0.01 是本报告声明的呈现约定，
不是任何测量得到的阈值。

### 2.1 hex

| 项目 | A/tools | B/full |
|---|---|---|
| 等级 | — | below_bar |
| R1(agent) | — | 0.1341 |
| R1(ref) | — | 0.1162 |
| ΔR1 | — | 不可比（分辨率截断不同；Δ=+0.0179） |
| 空间群 agent / ref | — | P 6/m m m / P 6/m m m |
| 空间群同型 | — | 是 |
| 骨架复现 emma solved | — | 是 |
| 元素一致 | — | 是 |
| 自洽 | — | 是 |
| 最佳节点是否交付 | — | 是（交付即最佳，或差距在 0.01 以内） |
| 掩膜 / 客体 | — | 掩膜=是；客体片段=6；空腔占比=78.5%；参考客体复现=0/9 |
| 未达 publication 的原因 | — | - R1 0.1341 above 0.10 (delta vs reference not comparable: different resolution cuts)<br>- metadata incomplete (A-level CIF-item alerts, not scored): 183, 184, 185, 197, 198, 660, 699<br>- data-quality A alerts (describe the dataset, not the model; must be explained, never block): 020, 023<br>- r1_delta not comparable: agent d_min 0.997 vs reference 1.1003 |
| 墙钟 | — | 40 min（2396 s） |
| 并发泳道 | — | 0 |
| tokens | — | 19,673,815 |
| 工具调用 / 出错 | — | 291 / 3 |
| knowledge_mode | — | full |

**机械判语：不可判**: A 臂未评分。n=1，不构成结论。

### 2.2 cage

| 项目 | A/tools | B/full |
|---|---|---|
| 等级 | — | below_bar |
| R1(agent) | — | 0.2226 |
| R1(ref) | — | 0.1395 |
| ΔR1 | — | 不可比（分辨率截断不同；Δ=+0.0831） |
| 空间群 agent / ref | — | P 1 21/c 1 / P 1 21/c 1 |
| 空间群同型 | — | 是 |
| 骨架复现 emma solved | — | 是 |
| 元素一致 | — | 是 |
| 自洽 | — | 是 |
| 最佳节点是否交付 | — | 否：树里最佳 n0158 R1 0.1976，交付 0.2226（Δ=+0.0250） |
| 掩膜 / 客体 | — | 掩膜=否；客体片段=19；空腔占比=31.1%；参考客体复现=—/— |
| 未达 publication 的原因 | — | - blocking A alerts (model quality): 080, 082, 084, 201, 202, 241, 242, 602, 934<br>- R1 0.2226 above 0.10 (delta vs reference not comparable: different resolution cuts)<br>- metadata incomplete (A-level CIF-item alerts, not scored): 183, 184, 185, 197, 198, 660, 699<br>- data-quality A alerts (describe the dataset, not the model; must be explained, never block): 023<br>- a better node existed: n0158 R1 0.1976 vs delivered 0.2226 (delta +0.0250)<br>- lower-R1 node n0152 (R1 0.1636) is not a comparable model: 1818 parameters vs the delivered 849 (> 1.5x): a bigger model buys a lower R1 by construction |
| 墙钟 | — | 96 min（5778 s） |
| 并发泳道 | — | 0 |
| tokens | — | 38,998,743 |
| 工具调用 / 出错 | — | 481 / 4 |
| knowledge_mode | — | full |

**机械判语：不可判**: A 臂未评分。n=1，不构成结论。

## 3. 过程分析（执行层）

本节每个数字都来自 `campaign_analysis.analyse_case` 对该格 rollout 的
挖掘：工具调用与结果、推理摘要、shell 命令。等级好坏与本节无关，一个
拿到 publication 的 run 照样可能在某个工具上空转二十分钟。

### 3.1 hex-full-r1（B/full）

- rollout 记录 935 条；工具调用 291 次，其中出错 3 次；推理段 72 段

**工具错误率**

| 工具 | 调用 | 出错 | 错误率 | 累计耗时 | 最常见错误 |
|---|---|---|---|---|---|
| `solvent_mask` | 6 | 3 | 0.5 | 4.9s | `no NEW mask stored - every void was dropped. BYPASS dropped 1 void(s) totalling 17414 A^3 (79% of the cell) (i` |
| `exec` | 142 | 0 | 0.0 | — | — |
| `wait` | 15 | 0 | 0.0 | — | — |
| `run_shelxt` | 14 | 0 | 0.0 | 1.5s | — |
| `read_skill` | 13 | 0 | 0.0 | 0.2s | — |
| `run_shelxl` | 13 | 0 | 0.0 | 103.4s | — |
| `edit_atoms` | 8 | 0 | 0.0 | 0.6s | — |
| `situation_report` | 6 | 0 | 0.0 | 3.1s | — |
| `view_structure` | 5 | 0 | 0.0 | 5.8s | — |
| `inspect_model` | 5 | 0 | 0.0 | 0.2s | — |
| `refine` | 5 | 0 | 0.0 | 9.9s | — |
| `branch` | 5 | 0 | 0.0 | 0.6s | — |
| `checkout` | 5 | 0 | 0.0 | 0.8s | — |
| `validate_structure` | 4 | 0 | 0.0 | 1.6s | — |
| `get_project_brief` | 3 | 0 | 0.0 | 0.8s | — |
| `model_disorder` | 3 | 0 | 0.0 | 0.1s | — |
| `get_geometry` | 3 | 0 | 0.0 | 0.3s | — |
| `assemble_asu` | 3 | 0 | 0.0 | 0.1s | — |
| `add_hydrogens` | 3 | 0 | 0.0 | 0.2s | — |
| `ingest_vendor_data` | 2 | 0 | 0.0 | 2.4s | — |
| `screen_space_groups` | 2 | 0 | 0.0 | 6.7s | — |
| `audit_reflection_data` | 2 | 0 | 0.0 | 1.7s | — |
| `audit_heavy_sites` | 2 | 0 | 0.0 | 1.8s | — |
| `ghost_test` | 2 | 0 | 0.0 | 32.3s | — |
| `integrate_difference_density` | 2 | 0 | 0.0 | 0.3s | — |
| `compare_nodes` | 2 | 0 | 0.0 | 0.1s | — |
| `check_symmetry` | 2 | 0 | 0.0 | — | — |
| `finalize_delivery` | 2 | 0 | 0.0 | 1.2s | — |
| `set_experiment` | 1 | 0 | 0.0 | 0.3s | — |
| `estimate_resolution` | 1 | 0 | 0.0 | 1.1s | — |
| `set_resolution_limit` | 1 | 0 | 0.0 | 0.1s | — |
| `audit_element_assignment` | 1 | 0 | 0.0 | — | — |
| `set_restraints` | 1 | 0 | 0.0 | — | — |
| `set_twin` | 1 | 0 | 0.0 | — | — |
| `reflection_statistics` | 1 | 0 | 0.0 | 1.6s | — |
| `set_z` | 1 | 0 | 0.0 | 0.1s | — |
| `rename_atoms` | 1 | 0 | 0.0 | — | — |
| `inspect_map` | 1 | 0 | 0.0 | 0.5s | — |
| `write_outputs` | 1 | 0 | 0.0 | 3.0s | — |
| `run_checkcif` | 1 | 0 | 0.0 | 20.5s | — |

协议性拒绝 1 次（不计入出错：工具按协议先拒、agent 补理由再收）：`finalize_delivery` ×1

**schema 拒绝（MCP 层在工具执行前挡下的调用）**

这类调用工具根本没跑过，因此和工具好不好用无关，只和**参数面好不好
调**有关。

_无_

**原地打转（短窗口内重复同一调用、同一参数）**

轮询已剔除（见下一小节）：detach 任务的状态查询本来就该重复。

- `run_shelxl` 重复 3 次　参数 `{"l_s": 20, "mode": "adopt", "timeout_s": 300}`
- `situation_report` 重复 2 次　参数 `{"render": true}`
- `validate_structure` 重复 2 次　参数 `{"expect_framework": true}`
- `get_project_brief` 重复 1 次　参数 `{}`
- `solvent_mask` 重复 1 次　参数 `{"d_min": 0.997, "max_cycles": 10, "min_void_volume": 40, "resolution_factor": 0.33}`
- `solvent_mask` 重复 1 次　参数 `{"d_min": 0.997, "max_cycles": 30, "min_void_volume": 40, "resolution_factor": 0.33}`
- `run_shelxl` 重复 1 次　参数 `{"l_s": 16, "mode": "adopt", "timeout_s": 300}`
- `checkout` 重复 1 次　参数 `{"node": "n0066"}`
- `run_shelxl` 重复 1 次　参数 `{"l_s": 12, "mode": "adopt_wght", "timeout_s": 300, "wght_rounds": 3}`

**轮询（detach 任务的状态查询，按工具契约每 60-120 s 一次）**

- `run_shelxt` 轮询 `job_20260904_045524` 12 次，覆盖 634.9s 墙钟（平均间隔 57.7s）
- 合计：12 次轮询，覆盖 634.9s 墙钟；这是**等待**，不是打转

**服务端丢下的工具（MCP 传输断开时仍在算）**

_无_

**参数试错（同一工具连续调用、参数每次都变）**

- `read_skill` 连续 11 次，11 种参数
- `run_shelxt` 连续 14 次，3 种参数

**转向（换打法，并附紧邻其前的工具错误）**

- 触发词 `instead of`，其前无工具报错
  > …r C016 since it's truncated, but I suspect guest density is affecting my results. The peaks in pores might come from diffuse solvent; I should likely mask them instead of modeling. My current model may have mislabeled atoms. The ghost test suggests there’s some "real" density, but I should confirm 
- 触发词 `instead of`，其前无工具报错
  > …bon atoms. They seem connected from carboxylate to phenyl to pyrene, but this may not be the entire linker. I'm wondering if the linker might actually be H4TBC instead of TBAPy, with a hexagonal MOF containing C80.   It raises questions about whether there’s a known MOF matching these parameters. I
- 触发词 `timeout`，其前无工具报错
  > **Checking CIF function**  I realize I need to check the CIF now. It might take 2 to 4 minutes, so I should set a timeout of 600 seconds. I've set the necessary commentary already, so I can just proceed to call it now. Everything seems to be lined up, but I'll stay alert in…

**shell 危险用法**

_无_

**数据泄漏审计**

_干净：未读取自己 staging 目录以外的导师侧路径_

**路径线索（agent 从目录名里读出的提示）**

_无_

### 3.2 cage-full-r1（B/full）

- rollout 记录 1596 条；工具调用 481 次，其中出错 4 次；推理段 106 段

**工具错误率**

| 工具 | 调用 | 出错 | 错误率 | 累计耗时 | 最常见错误 |
|---|---|---|---|---|---|
| `ghost_test` | 9 | 2 | 0.222 | 708.8s | `could not rebuild the session from n0152: IndexError: tuple index out of range` |
| `solve_charge_flipping` | 2 | 1 | 0.5 | 64.4s | `charge flipping: no phase transition` |
| `probe_site` | 1 | 1 | 1.0 | 0.3s | `_Refusal: delete of C63 failed: edit_atoms refused: 1 atom(s) you asked to delete (['C63']) were judged REAL b` |
| `exec` | 212 | 0 | 0.0 | — | — |
| `wait` | 92 | 0 | 0.0 | — | — |
| `run_shelxt` | 45 | 0 | 0.0 | 8.1s | — |
| `branch` | 16 | 0 | 0.0 | 3.3s | — |
| `situation_report` | 13 | 0 | 0.0 | 9.4s | — |
| `refine` | 12 | 0 | 0.0 | 975.8s | — |
| `validate_structure` | 9 | 0 | 0.0 | 6.1s | — |
| `run_shelxl` | 7 | 0 | 0.0 | 33.2s | — |
| `edit_atoms` | 5 | 0 | 0.0 | 1.0s | — |
| `assemble_asu` | 5 | 0 | 0.0 | 4.4s | — |
| `reflection_statistics` | 4 | 0 | 0.0 | 4.0s | — |
| `interpret_peaks` | 4 | 0 | 0.0 | 1.0s | — |
| `element_scan` | 4 | 0 | 0.0 | 266.2s | — |
| `get_project_brief` | 3 | 0 | 0.0 | 0.6s | — |
| `inspect_model` | 3 | 0 | 0.0 | 0.2s | — |
| `audit_element_assignment` | 3 | 0 | 0.0 | 0.2s | — |
| `checkout` | 3 | 0 | 0.0 | 0.4s | — |
| `integrate_difference_density` | 3 | 0 | 0.0 | 1.6s | — |
| `ingest_vendor_data` | 2 | 0 | 0.0 | 2.8s | — |
| `audit_reflection_data` | 2 | 0 | 0.0 | 1.5s | — |
| `audit_heavy_sites` | 2 | 0 | 0.0 | 4.6s | — |
| `fourier_complete` | 2 | 0 | 0.0 | 367.2s | — |
| `view_structure` | 2 | 0 | 0.0 | 1.7s | — |
| `rename_atoms` | 2 | 0 | 0.0 | 0.1s | — |
| `write_outputs` | 2 | 0 | 0.0 | 2.9s | — |
| `set_experiment` | 1 | 0 | 0.0 | 0.1s | — |
| `screen_space_groups` | 1 | 0 | 0.0 | 1.3s | — |
| `estimate_resolution` | 1 | 0 | 0.0 | 0.7s | — |
| `set_resolution_limit` | 1 | 0 | 0.0 | 0.3s | — |
| `get_geometry` | 1 | 0 | 0.0 | — | — |
| `solve_superflip` | 1 | 0 | 0.0 | 13.5s | — |
| `ncs_audit` | 1 | 0 | 0.0 | — | — |
| `inspect_map` | 1 | 0 | 0.0 | 0.8s | — |
| `check_symmetry` | 1 | 0 | 0.0 | — | — |
| `solvent_mask` | 1 | 0 | 0.0 | 1.7s | — |
| `run_checkcif` | 1 | 0 | 0.0 | 20.9s | — |
| `finalize_delivery` | 1 | 0 | 0.0 | 0.7s | — |

**schema 拒绝（MCP 层在工具执行前挡下的调用）**

这类调用工具根本没跑过，因此和工具好不好用无关，只和**参数面好不好
调**有关。

_无_

**原地打转（短窗口内重复同一调用、同一参数）**

轮询已剔除（见下一小节）：detach 任务的状态查询本来就该重复。

- `situation_report` 重复 11 次　参数 `{"render": true}`
- `validate_structure` 重复 6 次　参数 `{}`
- `get_project_brief` 重复 1 次　参数 `{}`
- `audit_element_assignment` 重复 1 次　参数 `{"elements": ["C", "N", "O"]}`
- `reflection_statistics` 重复 1 次　参数 `{"d_min": 0.996, "laue_group": "2/m", "n_shells": 6}`
- `rename_atoms` 重复 1 次　参数 `{"mode": "canonical"}`
- `assemble_asu` 重复 1 次　参数 `{"dry_run": false}`
- `run_shelxl` 重复 1 次　参数 `{"l_s": 0, "mode": "check", "timeout_s": 300}`

**轮询（detach 任务的状态查询，按工具契约每 60-120 s 一次）**

- `run_shelxt` 轮询 `job_20260904_061956` 15 次，覆盖 397.7s 墙钟（平均间隔 28.4s）
- `run_shelxt` 轮询 `job_20260904_053540` 8 次，覆盖 402.6s 墙钟（平均间隔 57.5s）
- `run_shelxt` 轮询 `job_20260904_054626` 7 次，覆盖 404.0s 墙钟（平均间隔 67.3s）
- `run_shelxt` 轮询 `job_20260904_061645` 4 次，覆盖 18.7s 墙钟（平均间隔 6.2s）
- `run_shelxt` 轮询 `job_20260904_061242` 2 次，覆盖 43.6s 墙钟（平均间隔 43.6s）
- 合计：36 次轮询，覆盖 1266.6s 墙钟；这是**等待**，不是打转

**服务端丢下的工具（MCP 传输断开时仍在算）**

_无_

**参数试错（同一工具连续调用、参数每次都变）**

- `run_shelxt` 连续 10 次，3 种参数
- `run_shelxt` 连续 9 次，3 种参数
- `run_shelxt` 连续 4 次，3 种参数
- `run_shelxt` 连续 6 次，3 种参数
- `element_scan` 连续 3 次，3 种参数

**转向（换打法，并附紧邻其前的工具错误）**

- 触发词 `timeout`，其前无工具报错
  > …explore the peak configurations. For `seeds`, I plan to keep it fixed at 3 to ensure some variability. Also, I’ll limit the `max_attempts` to 2, and I think a `timeout` of 420 seconds should provide ample time for computations. This sounds like a solid plan!
- 触发词 `instead of`，紧接在 `probe_site` 报错之后：`_Refusal: delete of C63 failed: edit_atoms refused: 1 atom(s) you asked to delete (['C63']) were judged REAL b`
  > **Evaluating options for element scan**  I’m considering using element_scan with C63 candidates, and it looks like I should likely reassign branches instead of deleting them to avoid any blocking with the ledger. It’s interesting to think about how that might impact free occupancy, huh? I’m trying t
- 触发词 `instead of`，其前无工具报错
  > **Reassessing potential metal sites**  I'm considering that O007 and O008 might actually represent Zr metal sites instead of Na. An electron count of 11 seems more plausible than 40, which just isn’t realistic. So, it would make sense to branch at n0066 and reassign these s…

**shell 危险用法**

_无_

**数据泄漏审计**

_干净：未读取自己 staging 目录以外的导师侧路径_

**路径线索（agent 从目录名里读出的提示）**

_无_

### 3.3 全实验汇总

**错误率最高的工具**（只列有过失败的）

| 工具 | 调用 | 出错 | 错误率 | 出错的格数 |
|---|---|---|---|---|
| `probe_site` | 1 | 1 | 1.0 | 1/1 |
| `solve_charge_flipping` | 2 | 1 | 0.5 | 1/1 |
| `solvent_mask` | 7 | 3 | 0.429 | 1/2 |
| `ghost_test` | 11 | 2 | 0.182 | 1/2 |

**打转 / 试错最多的工具**

| 工具 | 打转重复次数 | 参数试错种数 |
|---|---|---|
| `run_shelxt` | 0 | 15 |
| `situation_report` | 13 | 0 |
| `read_skill` | 0 | 11 |
| `validate_structure` | 8 | 0 |
| `run_shelxl` | 6 | 0 |
| `element_scan` | 0 | 3 |
| `solvent_mask` | 2 | 0 |
| `get_project_brief` | 2 | 0 |
| `checkout` | 1 | 0 |
| `assemble_asu` | 1 | 0 |
| `audit_element_assignment` | 1 | 0 |
| `reflection_statistics` | 1 | 0 |
| `rename_atoms` | 1 | 0 |

**每个工具的累计耗时**

| 工具 | 调用 | 累计耗时 |
|---|---|---|
| `refine` | 17 | 985.7s |
| `ghost_test` | 11 | 741.1s |
| `fourier_complete` | 2 | 367.2s |
| `element_scan` | 4 | 266.2s |
| `run_shelxl` | 20 | 136.6s |
| `solve_charge_flipping` | 2 | 64.4s |
| `run_checkcif` | 2 | 41.4s |
| `solve_superflip` | 1 | 13.5s |
| `situation_report` | 19 | 12.5s |
| `run_shelxt` | 59 | 9.6s |
| `screen_space_groups` | 3 | 8.0s |
| `validate_structure` | 13 | 7.7s |
| `view_structure` | 7 | 7.5s |
| `solvent_mask` | 7 | 6.6s |
| `audit_heavy_sites` | 4 | 6.4s |

## 4. 跑偏倾向与打转点（机械信号，待人工核读）

下面每一条都是程序能算出来的**信号**，不是结论。信号只回答「该去
transcript 的哪一段看」；看到的究竟是不是跑偏，必须人读。

- **hex-full-r1**
  - [原地打转] `run_shelxl` 同参数重复 3 次（阈值 3）
- **cage-full-r1**
  - [原地打转] `situation_report` 同参数重复 11 次（阈值 3）
  - [原地打转] `validate_structure` 同参数重复 6 次（阈值 3）
  - [交付的不是最佳节点] 树里 n0158 的 R1 是 0.1976，交付的是 0.2226（Δ=+0.0250）

<!-- 人工核读：
  1. 逐格读 transcript，判断上面每条信号是真跑偏，还是正常的探索；
  2. 记下 tools 臂在没有技能卡的情况下自己重建了哪些判据、漏了哪些；
  3. 记下 full 臂是否出现「照卡执行但并不理解」的迹象；
  4. 写下每格最关键的一次转向，以及它是被哪一条工具消息推动的。
-->

## 5. 工具易用性信号

按「出错 + schema 拒绝 + 参数试错 + 打转」之和排序。这是**模型难以
正确调用的工具清单**，逐格证据见第 3 节。本节不解释原因。

schema 拒绝额外加权一次：它已经计入「出错」，但它比一次运行失败更
重，工具连跑都没跑，是参数面本身让模型调不对。轮询不计入任何一项
（那是工具契约要求的等待）。

| 工具 | 合计信号 | 出错 | 其中 schema 拒绝 | 参数试错 | 打转 | 调用 | 其中轮询 | 错误率 |
|---|---|---|---|---|---|---|---|---|
| `run_shelxt` | 15 | 0 | 0 | 15 | 0 | 59 | 48 | 0.0 |
| `situation_report` | 13 | 0 | 0 | 0 | 13 | 19 | 0 | 0.0 |
| `read_skill` | 11 | 0 | 0 | 11 | 0 | 13 | 0 | 0.0 |
| `validate_structure` | 8 | 0 | 0 | 0 | 8 | 13 | 0 | 0.0 |
| `run_shelxl` | 6 | 0 | 0 | 0 | 6 | 20 | 0 | 0.0 |
| `solvent_mask` | 5 | 3 | 0 | 0 | 2 | 7 | 0 | 0.429 |
| `element_scan` | 3 | 0 | 0 | 3 | 0 | 4 | 0 | 0.0 |
| `get_project_brief` | 2 | 0 | 0 | 0 | 2 | 6 | 0 | 0.0 |
| `ghost_test` | 2 | 2 | 0 | 0 | 0 | 11 | 0 | 0.182 |
| `checkout` | 1 | 0 | 0 | 0 | 1 | 8 | 0 | 0.0 |
| `assemble_asu` | 1 | 0 | 0 | 0 | 1 | 8 | 0 | 0.0 |
| `audit_element_assignment` | 1 | 0 | 0 | 0 | 1 | 4 | 0 | 0.0 |
| `reflection_statistics` | 1 | 0 | 0 | 0 | 1 | 5 | 0 | 0.0 |
| `rename_atoms` | 1 | 0 | 0 | 0 | 1 | 3 | 0 | 0.0 |
| `solve_charge_flipping` | 1 | 1 | 0 | 0 | 0 | 2 | 0 | 0.5 |
| `probe_site` | 1 | 1 | 0 | 0 | 0 | 1 | 0 | 1.0 |

## 附：运行记账

`root_agents_sha256` 对一条干净的臂必须是 null，`agents_chain` 长度必须
是 1（只有项目自己那份 AGENTS.md）。

| 格 | model | effort | knowledge_mode | agents_version | agents_sha256 | 匹配模板 | root_agents_sha256 | 链长 |
|---|---|---|---|---|---|---|---|---|
| hex-full-r1 | gpt-5.6-sol | xhigh | full | <!-- crystalpilot-agents-v33 --> | `250395d3` | 是 | null（干净） | 1 |
| cage-full-r1 | gpt-5.6-sol | xhigh | full | <!-- crystalpilot-agents-v33 --> | `250395d3` | 是 | null（干净） | 1 |

- 未发现祖先 AGENTS.md 注入、模板哈希不符或臂标签矛盾（未跑的格子无从检查）。
