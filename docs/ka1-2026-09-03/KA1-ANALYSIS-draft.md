# ka1：知识层消融实验分析（草稿）

**实验设计**：只变一件事，项目自己的 AGENTS.md 里预装了多少晶体学知识。
A 臂 = tools（仅工具契约）：只有操作契约与诚实规则（怎么调工具、交付
格式、「没定就说没定，不许编」），没有任何技能卡、没有任何晶体学判据。
B 臂 = full（v32+技能卡）：现行 AGENTS v32 加完整技能卡库。两臂同一
条 L0 简报、同一模型、同一份数据、同一套 MCP 工具面。

**当前进度**：共 6 格，已开跑 6 格，已评分 6 格。

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
| cage | A/tools | below_bar | 0.2241 | 0.1395 | 不可比（分辨率截断不同；Δ=+0.0846） | 是 | 是 | s2 CIF↔fcf:是<br>s3 REPORT↔CIF:是<br>s4 checkCIF解释门:是<br>e 窥视干净:是<br>自洽:是<br>结论↔CIF:是<br>未决披露:9 条 | 否：树里最佳 n0040 R1 0.1977，交付 0.2241（Δ=+0.0264） | 145 min | 45,853,873 | 617 | 17 | — | `3f6c59fa` 是 | graded |
| cage | B/full | below_bar | 0.1642 | 0.1395 | 不可比（分辨率截断不同；Δ=+0.0247） | 是 | 是 | s2 CIF↔fcf:是<br>s3 REPORT↔CIF:是<br>s4 checkCIF解释门:是<br>e 窥视干净:是<br>自洽:是<br>结论↔CIF:是<br>未决披露:10 条 | 是（交付即最佳，或差距在 0.01 以内） | 194 min | 47,908,956 | 559 | 11 | — | `b23234a1` 是 | graded |
| hex | A/tools | publication | 0.0817 | 0.1162 | 不可比（分辨率截断不同；Δ=-0.0345） | 是 | 是 | s2 CIF↔fcf:是<br>s3 REPORT↔CIF:是<br>s4 checkCIF解释门:是<br>e 窥视干净:是<br>自洽:是<br>结论↔CIF:是<br>未决披露:3 条 | 是（交付即最佳，或差距在 0.01 以内） | 39 min | 12,712,101 | 195 | 4 | — | `3f6c59fa` 是 | graded |
| hex | B/full | publication | 0.0833 | 0.1162 | 不可比（分辨率截断不同；Δ=-0.0329） | 是 | 是 | s2 CIF↔fcf:是<br>s3 REPORT↔CIF:是<br>s4 checkCIF解释门:是<br>e 窥视干净:是<br>自洽:是<br>结论↔CIF:是<br>未决披露:5 条 | 是（交付即最佳，或差距在 0.01 以内） | 25 min | 15,358,921 | 194 | 1 | — | `b23234a1` 是 | graded |
| org | A/tools | no_delivery | — | — | — | — | — | — | — | 120 min | 7,076,874 | 171 | 6 | — | `3f6c59fa` 是 | graded |
| org | B/full | publication | 0.0263 | 0.0264 | -0.0001 | 是 | — | s2 CIF↔fcf:是<br>s3 REPORT↔CIF:是<br>s4 checkCIF解释门:是<br>e 窥视干净:是<br>自洽:是<br>结论↔CIF:是<br>未决披露:2 条 | 是（交付即最佳，或差距在 0.01 以内） | 17 min | 9,333,487 | 155 | 3 | — | `b23234a1` 是 | graded |

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

### 2.1 cage

| 项目 | A/tools | B/full |
|---|---|---|
| 等级 | below_bar | below_bar |
| R1(agent) | 0.2241 | 0.1642 |
| R1(ref) | 0.1395 | 0.1395 |
| ΔR1 | 不可比（分辨率截断不同；Δ=+0.0846） | 不可比（分辨率截断不同；Δ=+0.0247） |
| 空间群 agent / ref | P 1 21/c 1 / P 1 21/c 1 | P 1 21/c 1 / P 1 21/c 1 |
| 空间群同型 | 是 | 是 |
| 骨架复现 emma solved | 是 | 是 |
| 元素一致 | 是 | 是 |
| 自洽 | 是 | 是 |
| 最佳节点是否交付 | 否：树里最佳 n0040 R1 0.1977，交付 0.2241（Δ=+0.0264） | 是（交付即最佳，或差距在 0.01 以内） |
| 掩膜 / 客体 | 掩膜=否；客体片段=31；空腔占比=23.6%；参考客体复现=—/— | 掩膜=是；客体片段=39；空腔占比=27.6%；参考客体复现=—/— |
| 未达 publication 的原因 | - blocking A alerts (model quality): 082, 084, 201, 202, 241, 242, 374, 602<br>- chemistry: suspect_bonds: 26 N-N / carbonyl-length C-C bond(s) outside azide/azole/alkyne chemistry (11 high) - N1-N23 1.52 A (N-N); N3-N12 1.48 A (N-N); N3-N47<br>- R1 0.2241 above 0.10 (delta vs reference not comparable: different resolution cuts)<br>- metadata incomplete (A-level CIF-item alerts, not scored): 183, 184, 185, 660, 699<br>- data-quality A alerts (describe the dataset, not the model; must be explained, never block): 023<br>- a better node existed: n0040 R1 0.1977 vs delivered 0.2241 (delta +0.0264) | - blocking A alerts (model quality): 080, 211, 213, 214, 241, 242, 260, 310, 934<br>- chemistry: Zr02 (Zr) CN=10 outside the plausible [6, 9] for Zr (donor atoms 12, ligands 9; eta-ring = 3 sites, H excluded)<br>- chemistry: Zr04 (Zr) CN=10 outside the plausible [6, 9] for Zr (donor atoms 12, ligands 8; eta-ring = 3 sites, H excluded)<br>- chemistry: metal_bonded_light_atoms: 4 (1 high) - C047 (C) 2.12 A from Zr02 -> O (oxo/mu-O/OH, carboxylate, aqua)<br>- R1 0.1642 above 0.10 (delta vs reference not comparable: different resolution cuts)<br>- metadata incomplete (A-level CIF-item alerts, not scored): 183, 184, 185, 660, 699 |
| 墙钟 | 145 min（8723 s） | 194 min（11665 s） |
| 并发泳道 | 0 | 0 |
| tokens | 45,853,873 | 47,908,956 |
| 工具调用 / 出错 | 617 / 17 | 559 / 11 |
| knowledge_mode | tools_only | full |

**机械判语：B>A**：等级同为 below_bar，B 的 R1 低 0.0599。n=1，不构成结论。

### 2.2 hex

| 项目 | A/tools | B/full |
|---|---|---|
| 等级 | publication | publication |
| R1(agent) | 0.0817 | 0.0833 |
| R1(ref) | 0.1162 | 0.1162 |
| ΔR1 | 不可比（分辨率截断不同；Δ=-0.0345） | 不可比（分辨率截断不同；Δ=-0.0329） |
| 空间群 agent / ref | P 6/m m m / P 6/m m m | P 6/m m m / P 6/m m m |
| 空间群同型 | 是 | 是 |
| 骨架复现 emma solved | 是 | 是 |
| 元素一致 | 是 | 是 |
| 自洽 | 是 | 是 |
| 最佳节点是否交付 | 是（交付即最佳，或差距在 0.01 以内） | 是（交付即最佳，或差距在 0.01 以内） |
| 掩膜 / 客体 | 掩膜=是；客体片段=0；空腔占比=78.8%；参考客体复现=0/9 | 掩膜=是；客体片段=0；空腔占比=78.5%；参考客体复现=0/9 |
| 未达 publication 的原因 | - metadata incomplete (A-level CIF-item alerts, not scored): 183, 184, 185, 660, 699<br>- data-quality A alerts (describe the dataset, not the model; must be explained, never block): 020, 023<br>- r1_delta not comparable: agent d_min 1.0002 vs reference 1.1003 | - metadata incomplete (A-level CIF-item alerts, not scored): 183, 184, 185, 699<br>- data-quality A alerts (describe the dataset, not the model; must be explained, never block): 020, 023<br>- r1_delta not comparable: agent d_min 0.997 vs reference 1.1003 |
| 墙钟 | 39 min（2319 s） | 25 min（1484 s） |
| 并发泳道 | 0 | 0 |
| tokens | 12,712,101 | 15,358,921 |
| 工具调用 / 出错 | 195 / 4 | 194 / 1 |
| knowledge_mode | tools_only | full |

**机械判语：接近**：等级同为 publication，R1 相差 -0.0016，小于本报告声明的并列带 0.01。n=1，不构成结论。

### 2.3 org

| 项目 | A/tools | B/full |
|---|---|---|
| 等级 | no_delivery | publication |
| R1(agent) | — | 0.0263 |
| R1(ref) | — | 0.0264 |
| ΔR1 | — | -0.0001 |
| 空间群 agent / ref | — / — | P 21 21 21 (a+1/4,b,c-1/4) / P 21 21 21 |
| 空间群同型 | — | 是 |
| 骨架复现 emma solved | — | 是 |
| 元素一致 | — | — |
| 自洽 | — | 是 |
| 最佳节点是否交付 | — | 是（交付即最佳，或差距在 0.01 以内） |
| 掩膜 / 客体 | 掩膜=—；客体片段=—；空腔占比=—；参考客体复现=—/— | 掩膜=否；客体片段=3；空腔占比=0.0%；参考客体复现=—/— |
| 未达 publication 的原因 | - interrupted_before_verdict：主轮被 runner 中断（timeout），项目里没有 CrystalPilot Results/*/final.cif + final.fcf 交付；中断时任务目录里有 1 个文件 | - metadata incomplete (A-level CIF-item alerts, not scored): 183, 184, 185, 699 |
| 墙钟 | 120 min（7224 s） | 17 min（1042 s） |
| 并发泳道 | 0 | 0 |
| tokens | 7,076,874 | 9,333,487 |
| 工具调用 / 出错 | 171 / 6 | 155 / 3 |
| knowledge_mode | tools_only | full |

**机械判语：B>A**：等级 publication 高于 no_delivery。n=1，不构成结论。

## 3. 过程分析（执行层）

本节每个数字都来自 `campaign_analysis.analyse_case` 对该格 rollout 的
挖掘：工具调用与结果、推理摘要、shell 命令。等级好坏与本节无关，一个
拿到 publication 的 run 照样可能在某个工具上空转二十分钟。

### 3.1 cage-tools-r1（A/tools）

- rollout 记录 2126 条；工具调用 617 次，其中出错 17 次；推理段 119 段

**工具错误率**

| 工具 | 调用 | 出错 | 错误率 | 累计耗时 | 最常见错误 |
|---|---|---|---|---|---|
| `solvent_mask` | 4 | 4 | 1.0 | 16.3s | `no NEW mask stored - every void was dropped. BYPASS dropped 1 void(s) totalling 7735 A^3 (40% of the cell) (in` |
| `run_shelxl` | 26 | 3 | 0.115 | 534.2s | `shelxl produced no refinement summary (job.res unparsable). SHELXL says: ** etc. **; ** BAD AFIX  43  CONNECTI` |
| `ghost_test` | 13 | 3 | 0.231 | 1143.8s | `reference refinement of n0040 failed (shelxl produced no refinement summary (job.res unparsable). SHELXL says:` |
| `element_scan` | 5 | 3 | 0.6 | 182.6s | `reference refinement of n0133 failed (shelxl produced no refinement summary (job.res empty). SHELXL says: ** e` |
| `run_shelxt` | 26 | 1 | 0.038 | 3.4s | `Input validation error: 600 is greater than the maximum of 500` |
| `add_hydrogens` | 8 | 1 | 0.125 | 1.1s | `elements=[] protonates nothing - pass e.g. ['C'] or ['C','N','O']` |
| `finalize_delivery` | 2 | 1 | 0.5 | 1.0s | `NOT finalized: H:\CrystalPilot-campaigns\ka1-cage\p2bbf8c9c\CrystalPilot Results\task_20260903_170244
blocking` |
| `inspect_map` | 1 | 1 | 1.0 | — | `node n0000 has no stored difference-map peak table (peaks.json is written by refine, run_shelxl mode='adopt' a` |
| `exec` | 232 | 0 | 0.0 | — | — |
| `wait` | 159 | 0 | 0.0 | — | — |
| `branch` | 18 | 0 | 0.0 | 4.3s | — |
| `edit_atoms` | 16 | 0 | 0.0 | 3.3s | — |
| `inspect_model` | 13 | 0 | 0.0 | 0.9s | — |
| `checkout` | 13 | 0 | 0.0 | 2.6s | — |
| `refine` | 12 | 0 | 0.0 | 2946.3s | — |
| `validate_structure` | 9 | 0 | 0.0 | 5.3s | — |
| `view_structure` | 6 | 0 | 0.0 | 4.1s | — |
| `assemble_asu` | 6 | 0 | 0.0 | 18.2s | — |
| `get_project_brief` | 5 | 0 | 0.0 | 2.4s | — |
| `change_space_group` | 4 | 0 | 0.0 | 3.3s | — |
| `interpret_peaks` | 4 | 0 | 0.0 | 1.7s | — |
| `write_outputs` | 4 | 0 | 0.0 | 10.2s | — |
| `set_twin` | 3 | 0 | 0.0 | 0.2s | — |
| `audit_element_assignment` | 3 | 0 | 0.0 | 0.3s | — |
| `integrate_difference_density` | 3 | 0 | 0.0 | 7.8s | — |
| `ingest_vendor_data` | 2 | 0 | 0.0 | 2.6s | — |
| `solve_superflip` | 2 | 0 | 0.0 | 26.3s | — |
| `fourier_complete` | 2 | 0 | 0.0 | 512.7s | — |
| `list_nodes` | 2 | 0 | 0.0 | 0.2s | — |
| `set_experiment` | 2 | 0 | 0.0 | — | — |
| `rename_atoms` | 2 | 0 | 0.0 | 0.1s | — |
| `run_checkcif` | 2 | 0 | 0.0 | 61.5s | — |
| `estimate_resolution` | 1 | 0 | 0.0 | 0.7s | — |
| `audit_reflection_data` | 1 | 0 | 0.0 | 0.9s | — |
| `screen_space_groups` | 1 | 0 | 0.0 | 0.6s | — |
| `solve_charge_flipping` | 1 | 0 | 0.0 | 2.3s | — |
| `audit_heavy_sites` | 1 | 0 | 0.0 | 1.1s | — |
| `situation_report` | 1 | 0 | 0.0 | 1.7s | — |
| `set_resolution_limit` | 1 | 0 | 0.0 | 0.5s | — |
| `check_symmetry` | 1 | 0 | 0.0 | 2.2s | — |

**schema 拒绝（MCP 层在工具执行前挡下的调用）**

这类调用工具根本没跑过，因此和工具好不好用无关，只和**参数面好不好
调**有关。

- `run_shelxt` ×1　参数 `n_phase_sets`（out_of_range）：`600 is greater than the maximum of 500`

**原地打转（短窗口内重复同一调用、同一参数）**

轮询已剔除（见下一小节）：detach 任务的状态查询本来就该重复。

- `run_shelxl` 重复 8 次　参数 `{"l_s": 7, "mode": "adopt", "timeout_s": 900}`
- `run_shelxl` 重复 6 次　参数 `{"l_s": 5, "mode": "adopt", "timeout_s": 900}`
- `checkout` 重复 5 次　参数 `{"node": "n0000"}`
- `inspect_model` 重复 5 次　参数 `{"detail": "atoms"}`
- `validate_structure` 重复 4 次　参数 `{}`
- `view_structure` 重复 3 次　参数 `{"state": "asu", "views": ["a", "c", "oblique"]}`
- `get_project_brief` 重复 2 次　参数 `{}`
- `run_shelxl` 重复 2 次　参数 `{"l_s": 0, "mode": "check", "timeout_s": 900}`
- `checkout` 重复 1 次　参数 `{"node": "n0006"}`
- `checkout` 重复 1 次　参数 `{"node": "n0018"}`
- `solvent_mask` 重复 1 次　参数 `{"d_min": 0.996, "max_cycles": 50, "min_void_volume": 50, "resolution_factor": 0.25, "shrink_truncation_radius`
- `audit_element_assignment` 重复 1 次　参数 `{"elements": ["C", "N", "O"]}`

**轮询（detach 任务的状态查询，按工具契约每 60-120 s 一次）**

- `run_shelxt` 轮询 `job_20260903_170418` 10 次，覆盖 496.4s 墙钟（平均间隔 55.2s）
- `run_shelxt` 轮询 `job_20260903_172331` 5 次，覆盖 203.8s 墙钟（平均间隔 51.0s）
- `run_shelxt` 轮询 `job_20260903_190302` 4 次，覆盖 182.4s 墙钟（平均间隔 60.8s）
- 合计：19 次轮询，覆盖 882.6s 墙钟；这是**等待**，不是打转

**服务端丢下的工具（MCP 传输断开时仍在算）**

_无_

**参数试错（同一工具连续调用、参数每次都变）**

- `run_shelxt` 连续 7 次，4 种参数
- `run_shelxt` 连续 12 次，3 种参数
- `run_shelxt` 连续 7 次，3 种参数

**转向（换打法，并附紧邻其前的工具错误）**

- 触发词 `instead of`，其前无工具报错
  > …important to inspect the exact metadata for that tool. I can filter the results by exact name and then text it. So, I need to focus on finding the precise tool instead of continuing with a broad approach. Let's get this right!
- 触发词 `switch to`，其前无工具报错
  > **Addressing branch issues**  I'm noticing that the branch "shelxt_trial" is still active, but it seems like I didn’t switch to checkout "n0000." I wonder if the summary branch is still on "shelxt_trial" at "n0000" or if the branch head has moved somewhere. It might not fully u…
- 触发词 `timeout`，其前无工具报错
  > … with a broad description. I need to set the parameters: d_min at 1.0, max_peaks around 400, and defaulting maxcycles to 0. My seed will be 1, and I’ll allow a timeout of 600 seconds since this could take a while. I’m also considering how to manage calls, possibly using heartbeats for blocking. I w
- 触发词 `instead of`，其前无工具报错
  > **Clarifying operation actions**  I need to get the exact schema defined for this task. I’m considering whether to use "remove" for the operation action instead of "delete." I’ve used "delete" in the past, so maybe that’s what I should stick with. The summary mentions "edit_atoms" operations, and it
- 触发词 `failed again`，紧接在 `solvent_mask` 报错之后：`no NEW mask stored - every void was dropped. BYPASS dropped 1 void(s) totalling 6861 A^3 (36% of the cell) (in`
  > **Reassessing model adjustments**  It seems the mask failed again because I need a lighter framework. I’m considering adding hydrogens and correcting elements, which might involve tweaking carbon and oxygen levels…
- 触发词 `timeout`，其前无工具报错
  > …t improvement, but it's inconclusive, so I'll keep it for now. I need to check for symmetry, which could take a while - about 476 seconds - so maybe I should use a timeout of around 180 seconds? I’ll run that, and then I need to verify symmetry on the refined 301, despite poor element labels.

**shell 危险用法**

_无_

**数据泄漏审计**

_干净：未读取自己 staging 目录以外的导师侧路径_

**路径线索（agent 从目录名里读出的提示）**

- `pa1c-link`：**Evaluating data ingestion process**  I need to look into the data directory for pa1c-link to determine its contents. It seems the vendor d

### 3.2 cage-full-r1（B/full）

- rollout 记录 2046 条；工具调用 559 次，其中出错 11 次；推理段 111 段

**工具错误率**

| 工具 | 调用 | 出错 | 错误率 | 累计耗时 | 最常见错误 |
|---|---|---|---|---|---|
| `probe_site` | 5 | 2 | 0.4 | 921.5s | `_Refusal: delete of O063 failed: edit_atoms refused: 1 atom(s) you asked to delete (['O063']) were judged REAL` |
| `change_space_group` | 4 | 2 | 0.5 | 0.4s | `unknown parameter(s) ['reason'] for 'change_space_group' - nothing was run. Accepted parameters: ['accept_abse` |
| `compare_nodes` | 4 | 2 | 0.5 | 0.3s | `Input validation error: 'a' is a required property` |
| `run_shelxt` | 38 | 1 | 0.026 | 4.8s | `no element list available - pass composition='C H N ...'` |
| `run_shelxl` | 16 | 1 | 0.062 | 326.2s | `shelxl produced no refinement summary (job.res empty). SHELXL says: ** etc. **; ** Bond(s) to Zr01 ignored in ` |
| `view_structure` | 5 | 1 | 0.2 | 6.9s | `unknown parameter(s) ['mode'] for 'view_structure' - nothing was run. Accepted parameters: ['highlight', 'stat` |
| `solve_charge_flipping` | 1 | 1 | 1.0 | 18.8s | `charge flipping: no phase transition` |
| `optimize_weights` | 1 | 1 | 1.0 | 3900.0s | `tool call error: tool call failed for `crystalpilot/optimize_weights`

Caused by:
    timed out awaiting tools` |
| `exec` | 200 | 0 | 0.0 | — | — |
| `wait` | 185 | 0 | 0.0 | — | — |
| `branch` | 11 | 0 | 0.0 | 2.6s | — |
| `refine` | 10 | 0 | 0.0 | 941.5s | — |
| `read_skill` | 8 | 0 | 0.0 | 0.2s | — |
| `solvent_mask` | 8 | 0 | 0.0 | 37.2s | — |
| `inspect_model` | 5 | 0 | 0.0 | 0.7s | — |
| `checkout` | 5 | 0 | 0.0 | 0.9s | — |
| `ghost_test` | 5 | 0 | 0.0 | 999.8s | — |
| `validate_structure` | 5 | 0 | 0.0 | 8.8s | — |
| `situation_report` | 4 | 0 | 0.0 | 4.6s | — |
| `inspect_map` | 4 | 0 | 0.0 | 4.5s | — |
| `assemble_asu` | 4 | 0 | 0.0 | 9.9s | — |
| `get_project_brief` | 3 | 0 | 0.0 | 119.4s | — |
| `audit_reflection_data` | 2 | 0 | 0.0 | 2.2s | — |
| `audit_heavy_sites` | 2 | 0 | 0.0 | 5.0s | — |
| `audit_element_assignment` | 2 | 0 | 0.0 | 0.1s | — |
| `element_scan` | 2 | 0 | 0.0 | 968.6s | — |
| `add_hydrogens` | 2 | 0 | 0.0 | 0.4s | — |
| `write_outputs` | 2 | 0 | 0.0 | 7.7s | — |
| `set_experiment` | 1 | 0 | 0.0 | 0.1s | — |
| `ingest_vendor_data` | 1 | 0 | 0.0 | 1.9s | — |
| `screen_space_groups` | 1 | 0 | 0.0 | 1.8s | — |
| `estimate_resolution` | 1 | 0 | 0.0 | 0.7s | — |
| `reflection_statistics` | 1 | 0 | 0.0 | 2.2s | — |
| `set_resolution_limit` | 1 | 0 | 0.0 | 0.1s | — |
| `edit_atoms` | 1 | 0 | 0.0 | 0.1s | — |
| `solve_superflip` | 1 | 0 | 0.0 | 20.8s | — |
| `interpret_peaks` | 1 | 0 | 0.0 | 0.4s | — |
| `get_geometry` | 1 | 0 | 0.0 | — | — |
| `integrate_difference_density` | 1 | 0 | 0.0 | 1.0s | — |
| `model_disorder` | 1 | 0 | 0.0 | 0.1s | — |
| `check_symmetry` | 1 | 0 | 0.0 | — | — |
| `set_restraints` | 1 | 0 | 0.0 | — | — |
| `set_z` | 1 | 0 | 0.0 | 0.1s | — |
| `run_checkcif` | 1 | 0 | 0.0 | 58.7s | — |

**schema 拒绝（MCP 层在工具执行前挡下的调用）**

这类调用工具根本没跑过，因此和工具好不好用无关，只和**参数面好不好
调**有关。

- `compare_nodes` ×2　参数 `a`（missing_required）：`'a' is a required property`

**原地打转（短窗口内重复同一调用、同一参数）**

轮询已剔除（见下一小节）：detach 任务的状态查询本来就该重复。

- `refine` 重复 2 次　参数 `{}`
- `checkout` 重复 2 次　参数 `{"node": "n0148"}`
- `solvent_mask` 重复 2 次　参数 `{"d_min": 0.996, "max_cycles": 12}`
- `solvent_mask` 重复 2 次　参数 `{"d_min": 0.996, "max_cycles": 30}`
- `run_shelxl` 重复 2 次　参数 `{"l_s": 0, "mode": "check", "timeout_s": 300}`
- `checkout` 重复 1 次　参数 `{"node": "n0004"}`
- `branch` 重复 1 次　参数 `{"from_node": "n0004", "name": "main"}`
- `inspect_map` 重复 1 次　参数 `{}`
- `run_shelxl` 重复 1 次　参数 `{"l_s": 5, "mode": "adopt", "timeout_s": 180}`
- `run_shelxt` 重复 1 次　参数 `{"chem_quality": true, "composition": "Zr C O", "detach": true, "solve_resolution": 1.2, "timeout_s": 1800}`
- `run_shelxl` 重复 1 次　参数 `{"l_s": 0, "mode": "check", "timeout_s": 180}`
- `inspect_model` 重复 1 次　参数 `{"detail": "summary"}`

**轮询（detach 任务的状态查询，按工具契约每 60-120 s 一次）**

- `run_shelxt` 轮询 `job_20260903_193144` 12 次，覆盖 596.2s 墙钟（平均间隔 54.2s）
- `run_shelxt` 轮询 `job_20260903_194404` 10 次，覆盖 547.1s 墙钟（平均间隔 60.8s）
- `run_shelxt` 轮询 `job_20260903_215256` 4 次，覆盖 116.4s 墙钟（平均间隔 38.8s）
- `run_shelxt` 轮询 `job_20260903_215548` 3 次，覆盖 67.4s 墙钟（平均间隔 33.7s）
- 合计：29 次轮询，覆盖 1327.1s 墙钟；这是**等待**，不是打转

**服务端丢下的工具（MCP 传输断开时仍在算）**

_无_

**参数试错（同一工具连续调用、参数每次都变）**

- `run_shelxt` 连续 7 次，3 种参数
- `run_shelxt` 连续 12 次，3 种参数
- `probe_site` 连续 3 次，3 种参数
- `run_shelxt` 连续 6 次，3 种参数
- `run_shelxt` 连续 5 次，3 种参数
- `run_shelxl` 连续 3 次，3 种参数

**转向（换打法，并附紧邻其前的工具错误）**

- 触发词 `timeout`，其前无工具报错
  > **Planning timeout updates**  I’m on my 32nd try and it seems like I’m about to hit a 600-second timeout. I probably need to wait for that, which is around six minutes. Ma…
- 触发词 `instead of`，其前无工具报错
  > **Considering space group adoption**  I need to adopt from a job, and I'm thinking that maybe the best choice for the space group is Pc instead of P21/c. But we declared P21/c originally, so if I run shelxt without specifying a space group, it might automatically search through all options in La…
- 触发词 `instead of`，其前无工具报错
  > **Analyzing twin peaks in data**  I’ve found that metal residual peaks prefer twin configurations instead of split ones. Earlier, the twin alarm was triggered because the metric exceeded current P-1, but now the true Laue monoclinic matches the metric, so no…
- 触发词 `instead of`，其前无工具报错
  > …e of Na. I'm considering that the actual structure could contain Cu, based on existing benchmarks. There's also a possibility that the actual structure uses Zn instead of Zr, contrary to earlier assumptions based solely on wavelength. It's interesting to see how this unfolds!
- 触发词 `timeout`，紧接在 `optimize_weights` 报错之后：`tool call error: tool call failed for `crystalpilot/optimize_weights`

Caused by:
    timed out awaiting tools`
  > **Inspecting optimization state**  Okay, so it looks like the optimization process failed due to a timeout. I need to inspect the current state to understand what went wrong. There’s a lot to consider, like whether it’s a matter of resource allocation or some…
- 触发词 `timeout`，紧接在 `optimize_weights` 报错之后：`tool call error: tool call failed for `crystalpilot/optimize_weights`

Caused by:
    timed out awaiting tools`
  > …7, which has a value of 1.1867. I’m wondering whether we should optimize it further or if I've already adopted all final adjustments. There’s something about a timeout situation that feels like I need to take a closer look. I'm curious if the current performance aligns with what we want, so it's wo
- 触发词 `instead of`，其前无工具报错
  > **Considering output methods**  I could potentially have a tool output a compact code list parsed from the checkcif result instead of using the shell, but those results get lost after execution. Thankfully, checkcif.json already exists, so that saves me from rerunning. I can use she…

**shell 危险用法**

_无_

**数据泄漏审计**

_干净：未读取自己 staging 目录以外的导师侧路径_

**路径线索（agent 从目录名里读出的提示）**

- `PA1C-LINK`：**Checking symmetry in structure**  It seems the project is named "PA1C-LINK," but it might not be too helpful. An alternative issue is that

### 3.3 hex-tools-r1（A/tools）

- rollout 记录 674 条；工具调用 195 次，其中出错 4 次；推理段 49 段

**工具错误率**

| 工具 | 调用 | 出错 | 错误率 | 累计耗时 | 最常见错误 |
|---|---|---|---|---|---|
| `solvent_mask` | 5 | 2 | 0.4 | 356.0s | `no NEW mask stored - every void was dropped. BYPASS dropped 1 void(s) totalling 17503 A^3 (79% of the cell) (i` |
| `finalize_delivery` | 2 | 1 | 0.5 | 1.2s | `NOT finalized: H:\CrystalPilot-campaigns\ka1-hex\p92391ef8\CrystalPilot Results\task_20260903_155540
blocking ` |
| `import_frames` | 1 | 1 | 1.0 | — | `no scan frames recognised in H:\CrystalPilotData\staging\r25a - No recognisable diffraction frames found.` |
| `exec` | 96 | 0 | 0.0 | — | — |
| `wait` | 26 | 0 | 0.0 | — | — |
| `run_shelxt` | 15 | 0 | 0.0 | 3.9s | — |
| `refine` | 7 | 0 | 0.0 | 12.4s | — |
| `inspect_model` | 5 | 0 | 0.0 | 0.1s | — |
| `branch` | 4 | 0 | 0.0 | 0.8s | — |
| `edit_atoms` | 3 | 0 | 0.0 | 0.3s | — |
| `validate_structure` | 3 | 0 | 0.0 | 2.3s | — |
| `get_project_brief` | 2 | 0 | 0.0 | 0.8s | — |
| `ingest_vendor_data` | 2 | 0 | 0.0 | 2.4s | — |
| `reflection_statistics` | 2 | 0 | 0.0 | 4.4s | — |
| `ghost_test` | 2 | 0 | 0.0 | 26.3s | — |
| `add_hydrogens` | 2 | 0 | 0.0 | 0.2s | — |
| `run_shelxl` | 2 | 0 | 0.0 | 51.0s | — |
| `view_structure` | 2 | 0 | 0.0 | 2.2s | — |
| `screen_space_groups` | 1 | 0 | 0.0 | 0.3s | — |
| `estimate_resolution` | 1 | 0 | 0.0 | 0.9s | — |
| `set_resolution_limit` | 1 | 0 | 0.0 | 0.4s | — |
| `audit_reflection_data` | 1 | 0 | 0.0 | 2.1s | — |
| `audit_heavy_sites` | 1 | 0 | 0.0 | 1.9s | — |
| `audit_element_assignment` | 1 | 0 | 0.0 | 0.5s | — |
| `situation_report` | 1 | 0 | 0.0 | 2.0s | — |
| `set_z` | 1 | 0 | 0.0 | — | — |
| `rename_atoms` | 1 | 0 | 0.0 | — | — |
| `set_experiment` | 1 | 0 | 0.0 | — | — |
| `assemble_asu` | 1 | 0 | 0.0 | — | — |
| `check_symmetry` | 1 | 0 | 0.0 | — | — |
| `write_outputs` | 1 | 0 | 0.0 | 3.5s | — |
| `run_checkcif` | 1 | 0 | 0.0 | 29.5s | — |

**schema 拒绝（MCP 层在工具执行前挡下的调用）**

这类调用工具根本没跑过，因此和工具好不好用无关，只和**参数面好不好
调**有关。

_无_

**原地打转（短窗口内重复同一调用、同一参数）**

轮询已剔除（见下一小节）：detach 任务的状态查询本来就该重复。

- `get_project_brief` 重复 1 次　参数 `{}`

**轮询（detach 任务的状态查询，按工具契约每 60-120 s 一次）**

- `run_shelxt` 轮询 `job_20260903_155917` 8 次，覆盖 509.7s 墙钟（平均间隔 72.8s）
- `run_shelxt` 轮询 `job_20260903_160948` 3 次，覆盖 131.5s 墙钟（平均间隔 65.8s）
- 合计：11 次轮询，覆盖 641.2s 墙钟；这是**等待**，不是打转

**服务端丢下的工具（MCP 传输断开时仍在算）**

_无_

**参数试错（同一工具连续调用、参数每次都变）**

- `run_shelxt` 连续 5 次，3 种参数

**转向（换打法，并附紧邻其前的工具错误）**

- 触发词 `instead of`，其前无工具报错
  > …e edit_atoms function, but first, I have to validate the raw data to identify any mislabels or candidates related to metal bonding. I'm currently seeing iodine instead of metal, which might indicate some issues. After changing I to Zr, I'll run a refinement on the isotropic data, and I’ll need to p
- 触发词 `timeout`，紧接在 `solvent_mask` 报错之后：`no NEW mask stored - every void was dropped. BYPASS dropped 1 void(s) totalling 17342 A^3 (78% of the cell) (i`
  > …es, that’s crucial! Alright, I think it’s a good idea to run the adopt_wght with the parameters of l_s for about 10 iterations, with wght_rounds set to 5 and a timeout of 300 seconds. Let’s proceed!

**shell 危险用法**

_无_

**数据泄漏审计**

_干净：未读取自己 staging 目录以外的导师侧路径_

**路径线索（agent 从目录名里读出的提示）**

_无_

### 3.4 hex-full-r1（B/full）

- rollout 记录 674 条；工具调用 194 次，其中出错 1 次；推理段 51 段

**工具错误率**

| 工具 | 调用 | 出错 | 错误率 | 累计耗时 | 最常见错误 |
|---|---|---|---|---|---|
| `finalize_delivery` | 2 | 1 | 0.5 | 1.4s | `NOT finalized: H:\CrystalPilot-campaigns\ka1-hex\pf787826d\CrystalPilot Results\task_20260903_163552
blocking ` |
| `exec` | 97 | 0 | 0.0 | — | — |
| `wait` | 11 | 0 | 0.0 | — | — |
| `read_skill` | 7 | 0 | 0.0 | 0.6s | — |
| `refine` | 7 | 0 | 0.0 | 9.8s | — |
| `run_shelxt` | 5 | 0 | 0.0 | 1.0s | — |
| `solvent_mask` | 5 | 0 | 0.0 | 124.0s | — |
| `edit_atoms` | 4 | 0 | 0.0 | 0.3s | — |
| `checkout` | 4 | 0 | 0.0 | 0.6s | — |
| `set_experiment` | 3 | 0 | 0.0 | 0.2s | — |
| `branch` | 3 | 0 | 0.0 | 0.8s | — |
| `inspect_model` | 3 | 0 | 0.0 | — | — |
| `ghost_test` | 3 | 0 | 0.0 | 40.3s | — |
| `compare_nodes` | 3 | 0 | 0.0 | 0.2s | — |
| `write_outputs` | 3 | 0 | 0.0 | 11.3s | — |
| `ingest_vendor_data` | 2 | 0 | 0.0 | 3.0s | — |
| `screen_space_groups` | 2 | 0 | 0.0 | 7.5s | — |
| `audit_reflection_data` | 2 | 0 | 0.0 | 2.4s | — |
| `situation_report` | 2 | 0 | 0.0 | 2.4s | — |
| `audit_heavy_sites` | 2 | 0 | 0.0 | 2.5s | — |
| `validate_structure` | 2 | 0 | 0.0 | 1.0s | — |
| `run_shelxl` | 2 | 0 | 0.0 | 28.2s | — |
| `run_checkcif` | 2 | 0 | 0.0 | 51.2s | — |
| `get_project_brief` | 1 | 0 | 0.0 | 0.1s | — |
| `estimate_resolution` | 1 | 0 | 0.0 | 1.2s | — |
| `set_resolution_limit` | 1 | 0 | 0.0 | 0.1s | — |
| `reflection_statistics` | 1 | 0 | 0.0 | 2.0s | — |
| `change_space_group` | 1 | 0 | 0.0 | 0.4s | — |
| `list_skills` | 1 | 0 | 0.0 | — | — |
| `audit_element_assignment` | 1 | 0 | 0.0 | 0.1s | — |
| `set_z` | 1 | 0 | 0.0 | — | — |
| `inspect_map` | 1 | 0 | 0.0 | 0.5s | — |
| `probe_site` | 1 | 0 | 0.0 | 4.8s | — |
| `rename_atoms` | 1 | 0 | 0.0 | 0.1s | — |
| `add_hydrogens` | 1 | 0 | 0.0 | — | — |
| `assemble_asu` | 1 | 0 | 0.0 | — | — |
| `view_structure` | 1 | 0 | 0.0 | 2.1s | — |
| `check_symmetry` | 1 | 0 | 0.0 | — | — |
| `set_twin` | 1 | 0 | 0.0 | — | — |
| `element_scan` | 1 | 0 | 0.0 | 5.7s | — |
| `get_geometry` | 1 | 0 | 0.0 | 0.2s | — |

**schema 拒绝（MCP 层在工具执行前挡下的调用）**

这类调用工具根本没跑过，因此和工具好不好用无关，只和**参数面好不好
调**有关。

_无_

**原地打转（短窗口内重复同一调用、同一参数）**

轮询已剔除（见下一小节）：detach 任务的状态查询本来就该重复。

- `inspect_model` 重复 1 次　参数 `{"detail": "summary"}`
- `solvent_mask` 重复 1 次　参数 `{"d_min": 1, "max_cycles": 800}`
- `checkout` 重复 1 次　参数 `{"node": "n0067"}`
- `run_checkcif` 重复 1 次　参数 `{"cif": "CrystalPilot Results/task_20260903_163552/final.cif", "timeout_s": 600}`

**轮询（detach 任务的状态查询，按工具契约每 60-120 s 一次）**

- `run_shelxt` 轮询 `job_20260903_163912` 3 次，覆盖 105.8s 墙钟（平均间隔 52.9s）
- 合计：3 次轮询，覆盖 105.8s 墙钟；这是**等待**，不是打转

**服务端丢下的工具（MCP 传输断开时仍在算）**

_无_

**参数试错（同一工具连续调用、参数每次都变）**

- `run_shelxt` 连续 5 次，3 种参数

**转向（换打法，并附紧邻其前的工具错误）**

- 触发词 `timeout`，其前无工具报错
  > …ve already passed on an attempt and estimates say it’ll take around 104 seconds. I need to wait 60 seconds, but I could use functions.exec with a Promise for a timeout. It seems a max wait of 45 seconds might be okay instead of the full 60 to avoid blocking too long. I think it's best to wait 45 se
- 触发词 `instead of`，其前无工具报错
  > …O and OH groups. The density differences on O sites aren't immediately clear. Without solid synthesis priors, we might only incorporate C-H aromatic structures instead of O-H, which would mean addressing potential ambiguities with O and H. It's crucial to analyze the C peak4 to eliminate the possib
- 触发词 `timeout`，其前无工具报错
  > …ich is reassuring. Now, I need to check the symmetry for P6/mmm max, but it seems there’s likely no suggestion at this stage. I should also remember to set the timeout to 120 for any calls I make. I'm hopeful everything aligns well!
- 触发词 `instead of`，其前无工具报错
  > … 1.17, suggesting it might be terminal aqua with two H. With symmetry, there may be unique H arrangements, making it tricky to determine if I should force "OH" instead of "H2O." I'll need to explore this further!

**shell 危险用法**

_无_

**数据泄漏审计**

_干净：未读取自己 staging 目录以外的导师侧路径_

**路径线索（agent 从目录名里读出的提示）**

_无_

### 3.5 org-tools-r1（A/tools）

- rollout 记录 868 条；工具调用 171 次，其中出错 6 次；推理段 20 段

**工具错误率**

| 工具 | 调用 | 出错 | 错误率 | 累计耗时 | 最常见错误 |
|---|---|---|---|---|---|
| `run_shelxt` | 2 | 2 | 1.0 | 1810.0s | `no element list available - pass composition='C H N ...'` |
| `solve_superflip` | 2 | 2 | 1.0 | 7.5s | `superflip did not converge` |
| `get_project_brief` | 3 | 1 | 0.333 | 1806.0s | `gave up waiting after 1805s: 'solve_charge_flipping' (running 7545s so far) is still executing. Calls on one p` |
| `solve_charge_flipping` | 1 | 1 | 1.0 | 3900.0s | `tool call error: tool call failed for `crystalpilot/solve_charge_flipping`

Caused by:
    timed out awaiting ` |
| `wait` | 136 | 0 | 0.0 | — | — |
| `exec` | 20 | 0 | 0.0 | — | — |
| `change_space_group` | 3 | 0 | 0.0 | 0.2s | — |
| `ingest_vendor_data` | 2 | 0 | 0.0 | 0.5s | — |
| `screen_space_groups` | 1 | 0 | 0.0 | — | — |
| `reflection_statistics` | 1 | 0 | 0.0 | — | — |

**schema 拒绝（MCP 层在工具执行前挡下的调用）**

这类调用工具根本没跑过，因此和工具好不好用无关，只和**参数面好不好
调**有关。

_无_

**原地打转（短窗口内重复同一调用、同一参数）**

轮询已剔除（见下一小节）：detach 任务的状态查询本来就该重复。

- `get_project_brief` 重复 2 次　参数 `{}`
- `change_space_group` 重复 1 次　参数 `{"space_group": "P m m m"}`

**轮询（detach 任务的状态查询，按工具契约每 60-120 s 一次）**

_无_

**服务端丢下的工具（MCP 传输断开时仍在算）**

_无_

**参数试错（同一工具连续调用、参数每次都变）**

_无_

**转向（换打法，并附紧邻其前的工具错误）**

- 触发词 `timeout`，紧接在 `solve_charge_flipping` 报错之后：`tool call error: tool call failed for `crystalpilot/solve_charge_flipping`

Caused by:
    timed out awaiting `
  > …ing, but I’m not quite sure about that. I think I’ll apply the solve_charge_flipping method to each candidate using one seed. Just because Pmmm failed due to a timeout doesn’t mean there’s no solution. I might actually switch over to P212121 for further exploration.
- 触发词 `timeout`，其前无工具报错
  > **Evaluating timeout issues**  I'm considering why the `timeout_s` is being ignored. Maybe it's just waiting for approval, but I think we shouldn't keep waiting indefinitely…

**shell 危险用法**

_无_

**数据泄漏审计**

_干净：未读取自己 staging 目录以外的导师侧路径_

**路径线索（agent 从目录名里读出的提示）**

_无_

### 3.6 org-full-r1（B/full）

- rollout 记录 528 条；工具调用 155 次，其中出错 3 次；推理段 40 段

**工具错误率**

| 工具 | 调用 | 出错 | 错误率 | 累计耗时 | 最常见错误 |
|---|---|---|---|---|---|
| `finalize_delivery` | 2 | 1 | 0.5 | 0.2s | `NOT finalized: H:\CrystalPilot-campaigns\ka1-org\p813c1570\CrystalPilot Results\task_20260903_175551
blocking ` |
| `solve_charge_flipping` | 1 | 1 | 1.0 | 69.5s | `charge flipping: no phase transition` |
| `solve_superflip` | 1 | 1 | 1.0 | 60.3s | `superflip did not converge` |
| `exec` | 72 | 0 | 0.0 | — | — |
| `refine` | 8 | 0 | 0.0 | 18.4s | — |
| `wait` | 8 | 0 | 0.0 | — | — |
| `branch` | 7 | 0 | 0.0 | 2.5s | — |
| `run_shelxl` | 5 | 0 | 0.0 | 15.4s | — |
| `change_space_group` | 4 | 0 | 0.0 | 0.8s | — |
| `view_structure` | 4 | 0 | 0.0 | 16.6s | — |
| `inspect_model` | 4 | 0 | 0.0 | 0.4s | — |
| `read_skill` | 3 | 0 | 0.0 | 0.2s | — |
| `add_hydrogens` | 3 | 0 | 0.0 | 0.8s | — |
| `get_project_brief` | 2 | 0 | 0.0 | 1.4s | — |
| `ingest_vendor_data` | 2 | 0 | 0.0 | 2.4s | — |
| `situation_report` | 2 | 0 | 0.0 | 6.5s | — |
| `run_shelxt` | 2 | 0 | 0.0 | 9.8s | — |
| `check_symmetry` | 2 | 0 | 0.0 | 0.4s | — |
| `compare_nodes` | 2 | 0 | 0.0 | 0.9s | — |
| `checkout` | 2 | 0 | 0.0 | 0.6s | — |
| `validate_structure` | 2 | 0 | 0.0 | 0.2s | — |
| `assemble_asu` | 2 | 0 | 0.0 | 0.2s | — |
| `set_experiment` | 1 | 0 | 0.0 | 0.1s | — |
| `screen_space_groups` | 1 | 0 | 0.0 | 0.2s | — |
| `reflection_statistics` | 1 | 0 | 0.0 | 0.1s | — |
| `estimate_resolution` | 1 | 0 | 0.0 | — | — |
| `audit_reflection_data` | 1 | 0 | 0.0 | — | — |
| `probe_site` | 1 | 0 | 0.0 | 22.7s | — |
| `ghost_test` | 1 | 0 | 0.0 | 27.9s | — |
| `ncs_audit` | 1 | 0 | 0.0 | — | — |
| `edit_atoms` | 1 | 0 | 0.0 | 0.2s | — |
| `audit_element_assignment` | 1 | 0 | 0.0 | 0.1s | — |
| `rename_atoms` | 1 | 0 | 0.0 | 0.2s | — |
| `invert_structure` | 1 | 0 | 0.0 | 0.2s | — |
| `get_geometry` | 1 | 0 | 0.0 | 0.1s | — |
| `write_outputs` | 1 | 0 | 0.0 | 1.2s | — |
| `run_checkcif` | 1 | 0 | 0.0 | 15.2s | — |

**schema 拒绝（MCP 层在工具执行前挡下的调用）**

这类调用工具根本没跑过，因此和工具好不好用无关，只和**参数面好不好
调**有关。

_无_

**原地打转（短窗口内重复同一调用、同一参数）**

轮询已剔除（见下一小节）：detach 任务的状态查询本来就该重复。

- `get_project_brief` 重复 1 次　参数 `{}`
- `view_structure` 重复 1 次　参数 `{"state": "cell", "views": ["a", "b", "c", "oblique"]}`
- `check_symmetry` 重复 1 次　参数 `{"timeout_s": 180, "tolerance_A": 0.35}`
- `inspect_model` 重复 1 次　参数 `{"detail": "full"}`
- `add_hydrogens` 重复 1 次　参数 `{"elements": ["C"]}`

**轮询（detach 任务的状态查询，按工具契约每 60-120 s 一次）**

_无_

**服务端丢下的工具（MCP 传输断开时仍在算）**

_无_

**参数试错（同一工具连续调用、参数每次都变）**

_无_

**转向（换打法，并附紧邻其前的工具错误）**

- 触发词 `timeout`，紧接在 `solve_superflip` 报错之后：`superflip did not converge`
  > …addressing. My next step will be to determine the actual symmetry by using the check_symmetry function in P1 after it’s been refined. I think calling it with a timeout - maybe around 120 seconds - will be a good idea. I could also think about doing an NCS audit. Sequential processing might work here to

**shell 危险用法**

_无_

**数据泄漏审计**

_干净：未读取自己 staging 目录以外的导师侧路径_

**路径线索（agent 从目录名里读出的提示）**

_无_

### 3.7 全实验汇总

**错误率最高的工具**（只列有过失败的）

| 工具 | 调用 | 出错 | 错误率 | 出错的格数 |
|---|---|---|---|---|
| `optimize_weights` | 1 | 1 | 1.0 | 1/1 |
| `import_frames` | 1 | 1 | 1.0 | 1/1 |
| `solve_charge_flipping` | 4 | 3 | 0.75 | 3/4 |
| `finalize_delivery` | 8 | 4 | 0.5 | 4/4 |
| `solve_superflip` | 6 | 3 | 0.5 | 2/4 |
| `element_scan` | 8 | 3 | 0.375 | 1/3 |
| `probe_site` | 7 | 2 | 0.286 | 1/3 |
| `solvent_mask` | 22 | 6 | 0.273 | 2/4 |
| `compare_nodes` | 9 | 2 | 0.222 | 1/3 |
| `inspect_map` | 6 | 1 | 0.167 | 1/3 |
| `ghost_test` | 24 | 3 | 0.125 | 1/5 |
| `change_space_group` | 16 | 2 | 0.125 | 1/5 |
| `run_shelxl` | 51 | 4 | 0.078 | 2/5 |
| `add_hydrogens` | 16 | 1 | 0.062 | 1/5 |
| `get_project_brief` | 16 | 1 | 0.062 | 1/6 |

**打转 / 试错最多的工具**

| 工具 | 打转重复次数 | 参数试错种数 |
|---|---|---|
| `run_shelxt` | 1 | 28 |
| `run_shelxl` | 21 | 3 |
| `checkout` | 11 | 0 |
| `inspect_model` | 8 | 0 |
| `get_project_brief` | 6 | 0 |
| `solvent_mask` | 6 | 0 |
| `validate_structure` | 5 | 0 |
| `view_structure` | 4 | 0 |
| `probe_site` | 0 | 3 |
| `refine` | 2 | 0 |
| `write_outputs` | 2 | 0 |
| `run_checkcif` | 2 | 0 |
| `branch` | 1 | 0 |
| `add_hydrogens` | 1 | 0 |
| `change_space_group` | 1 | 0 |

**每个工具的累计耗时**

| 工具 | 调用 | 累计耗时 |
|---|---|---|
| `solve_charge_flipping` | 4 | 3990.6s |
| `refine` | 44 | 3928.4s |
| `optimize_weights` | 1 | 3900.0s |
| `ghost_test` | 24 | 2238.1s |
| `get_project_brief` | 16 | 1930.1s |
| `run_shelxt` | 88 | 1832.9s |
| `element_scan` | 8 | 1156.9s |
| `run_shelxl` | 51 | 955.0s |
| `probe_site` | 7 | 949.0s |
| `solvent_mask` | 22 | 533.5s |
| `fourier_complete` | 2 | 512.7s |
| `run_checkcif` | 7 | 216.1s |
| `solve_superflip` | 6 | 114.9s |
| `write_outputs` | 11 | 33.9s |
| `view_structure` | 18 | 31.9s |

## 4. 跑偏倾向与打转点（机械信号，待人工核读）

下面每一条都是程序能算出来的**信号**，不是结论。信号只回答「该去
transcript 的哪一段看」；看到的究竟是不是跑偏，必须人读。

- **cage-tools-r1**
  - [原地打转] `run_shelxl` 同参数重复 8 次（阈值 3）
  - [原地打转] `run_shelxl` 同参数重复 6 次（阈值 3）
  - [原地打转] `checkout` 同参数重复 5 次（阈值 3）
  - [原地打转] `inspect_model` 同参数重复 5 次（阈值 3）
  - [原地打转] `validate_structure` 同参数重复 4 次（阈值 3）
  - [原地打转] `view_structure` 同参数重复 3 次（阈值 3）
  - [schema 拒绝] `run_shelxt` 的调用被 MCP 层挡下 1 次，参数 `n_phase_sets`（out_of_range）：工具没跑过，是参数面的问题
  - [交付的不是最佳节点] 树里 n0040 的 R1 是 0.1977，交付的是 0.2241（Δ=+0.0264）
- **cage-full-r1**
  - [schema 拒绝] `compare_nodes` 的调用被 MCP 层挡下 2 次，参数 `a`（missing_required）：工具没跑过，是参数面的问题

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
| `run_shelxt` | 34 | 4 | 1 | 28 | 1 | 88 | 62 | 0.045 |
| `run_shelxl` | 28 | 4 | 0 | 3 | 21 | 51 | 0 | 0.078 |
| `solvent_mask` | 12 | 6 | 0 | 0 | 6 | 22 | 0 | 0.273 |
| `checkout` | 11 | 0 | 0 | 0 | 11 | 24 | 0 | 0.0 |
| `inspect_model` | 8 | 0 | 0 | 0 | 8 | 30 | 0 | 0.0 |
| `get_project_brief` | 7 | 1 | 0 | 0 | 6 | 16 | 0 | 0.062 |
| `validate_structure` | 5 | 0 | 0 | 0 | 5 | 21 | 0 | 0.0 |
| `view_structure` | 5 | 1 | 0 | 0 | 4 | 18 | 0 | 0.056 |
| `probe_site` | 5 | 2 | 0 | 3 | 0 | 7 | 0 | 0.286 |
| `finalize_delivery` | 4 | 4 | 0 | 0 | 0 | 8 | 0 | 0.5 |
| `compare_nodes` | 4 | 2 | 2 | 0 | 0 | 9 | 0 | 0.222 |
| `ghost_test` | 3 | 3 | 0 | 0 | 0 | 24 | 0 | 0.125 |
| `element_scan` | 3 | 3 | 0 | 0 | 0 | 8 | 0 | 0.375 |
| `change_space_group` | 3 | 2 | 0 | 0 | 1 | 16 | 0 | 0.125 |
| `solve_superflip` | 3 | 3 | 0 | 0 | 0 | 6 | 0 | 0.5 |
| `solve_charge_flipping` | 3 | 3 | 0 | 0 | 0 | 4 | 0 | 0.75 |
| `refine` | 2 | 0 | 0 | 0 | 2 | 44 | 0 | 0.0 |
| `add_hydrogens` | 2 | 1 | 0 | 0 | 1 | 16 | 0 | 0.062 |
| `write_outputs` | 2 | 0 | 0 | 0 | 2 | 11 | 0 | 0.0 |
| `run_checkcif` | 2 | 0 | 0 | 0 | 2 | 7 | 0 | 0.0 |
| `inspect_map` | 2 | 1 | 0 | 0 | 1 | 6 | 0 | 0.167 |
| `branch` | 1 | 0 | 0 | 0 | 1 | 43 | 0 | 0.0 |
| `audit_element_assignment` | 1 | 0 | 0 | 0 | 1 | 8 | 0 | 0.0 |
| `rename_atoms` | 1 | 0 | 0 | 0 | 1 | 5 | 0 | 0.0 |
| `check_symmetry` | 1 | 0 | 0 | 0 | 1 | 6 | 0 | 0.0 |
| `optimize_weights` | 1 | 1 | 0 | 0 | 0 | 1 | 0 | 1.0 |
| `import_frames` | 1 | 1 | 0 | 0 | 0 | 1 | 0 | 1.0 |

## 附：运行记账

`root_agents_sha256` 对一条干净的臂必须是 null，`agents_chain` 长度必须
是 1（只有项目自己那份 AGENTS.md）。

| 格 | model | effort | knowledge_mode | agents_version | agents_sha256 | 匹配模板 | root_agents_sha256 | 链长 |
|---|---|---|---|---|---|---|---|---|
| cage-tools-r1 | gpt-5.6-sol | xhigh | tools_only | <!-- crystalpilot-agents-tools-only-v1 --> | `3f6c59fa` | 是 | null（干净） | 1 |
| cage-full-r1 | gpt-5.6-sol | xhigh | full | <!-- crystalpilot-agents-v32 --> | `b23234a1` | 是 | null（干净） | 1 |
| hex-tools-r1 | gpt-5.6-sol | xhigh | tools_only | <!-- crystalpilot-agents-tools-only-v1 --> | `3f6c59fa` | 是 | null（干净） | 1 |
| hex-full-r1 | gpt-5.6-sol | xhigh | full | <!-- crystalpilot-agents-v32 --> | `b23234a1` | 是 | null（干净） | 1 |
| org-tools-r1 | gpt-5.6-sol | xhigh | tools_only | <!-- crystalpilot-agents-tools-only-v1 --> | `3f6c59fa` | 是 | null（干净） | 1 |
| org-full-r1 | gpt-5.6-sol | xhigh | full | <!-- crystalpilot-agents-v32 --> | `b23234a1` | 是 | null（干净） | 1 |

- 未发现祖先 AGENTS.md 注入、模板哈希不符或臂标签矛盾（未跑的格子无从检查）。
