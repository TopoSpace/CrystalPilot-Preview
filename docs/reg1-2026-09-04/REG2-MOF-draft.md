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
| hex | B/full | publication | 0.0858 | 0.1162 | 不可比（分辨率截断不同；Δ=-0.0304） | 是 | 是 | s2 CIF↔fcf:是<br>s3 REPORT↔CIF:是<br>s4 checkCIF解释门:是<br>e 窥视干净:是<br>自洽:是<br>结论↔CIF:是<br>未决披露:6 条 | 是（交付即最佳，或差距在 0.01 以内） | 38 min | 21,588,739 | 313 | 1 | — | `250395d3` 是 | graded |
| cage | B/full | below_bar | 0.1570 | 0.1395 | 不可比（分辨率截断不同；Δ=+0.0175） | 是 | 是 | s2 CIF↔fcf:是<br>s3 REPORT↔CIF:是<br>s4 checkCIF解释门:是<br>e 窥视干净:是<br>自洽:是<br>结论↔CIF:是<br>未决披露:9 条 | 是（交付即最佳，或差距在 0.01 以内） | 72 min | 23,804,580 | 370 | 0 | — | `250395d3` 是 | graded |

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
| 等级 | — | publication |
| R1(agent) | — | 0.0858 |
| R1(ref) | — | 0.1162 |
| ΔR1 | — | 不可比（分辨率截断不同；Δ=-0.0304） |
| 空间群 agent / ref | — | P 6/m m m / P 6/m m m |
| 空间群同型 | — | 是 |
| 骨架复现 emma solved | — | 是 |
| 元素一致 | — | 是 |
| 自洽 | — | 是 |
| 最佳节点是否交付 | — | 是（交付即最佳，或差距在 0.01 以内） |
| 掩膜 / 客体 | — | 掩膜=是；客体片段=0；空腔占比=78.7%；参考客体复现=0/9 |
| 未达 publication 的原因 | — | - metadata incomplete (A-level CIF-item alerts, not scored): 183, 184, 185, 197, 198, 660, 699<br>- data-quality A alerts (describe the dataset, not the model; must be explained, never block): 020, 023<br>- r1_delta not comparable: agent d_min 0.997 vs reference 1.1003 |
| 墙钟 | — | 38 min（2262 s） |
| 并发泳道 | — | — |
| tokens | — | 21,588,739 |
| 工具调用 / 出错 | — | 313 / 1 |
| knowledge_mode | — | full |

**机械判语：不可判**: A 臂未评分。n=1，不构成结论。

### 2.2 cage

| 项目 | A/tools | B/full |
|---|---|---|
| 等级 | — | below_bar |
| R1(agent) | — | 0.1570 |
| R1(ref) | — | 0.1395 |
| ΔR1 | — | 不可比（分辨率截断不同；Δ=+0.0175） |
| 空间群 agent / ref | — | P 1 21/c 1 / P 1 21/c 1 |
| 空间群同型 | — | 是 |
| 骨架复现 emma solved | — | 是 |
| 元素一致 | — | 是 |
| 自洽 | — | 是 |
| 最佳节点是否交付 | — | 是（交付即最佳，或差距在 0.01 以内） |
| 掩膜 / 客体 | — | 掩膜=是；客体片段=67；空腔占比=22.9%；参考客体复现=—/— |
| 未达 publication 的原因 | — | - blocking A alerts (model quality): 080, 084, 211, 213, 214, 241, 242, 260, 310, 342, 973<br>- chemistry: Zr7 (Zr) CN=5 outside the plausible [6, 9] for Zr (donor atoms 5, ligands 5; eta-ring = 3 sites, H excluded)<br>- R1 0.157 above 0.10 (delta vs reference not comparable: different resolution cuts)<br>- metadata incomplete (A-level CIF-item alerts, not scored): 183, 184, 185, 197, 198, 660, 699<br>- data-quality A alerts (describe the dataset, not the model; must be explained, never block): 023<br>- r1_delta not comparable: agent d_min 0.996 vs reference 0.6909 |
| 墙钟 | — | 72 min（4348 s） |
| 并发泳道 | — | 0 |
| tokens | — | 23,804,580 |
| 工具调用 / 出错 | — | 370 / 0 |
| knowledge_mode | — | full |

**机械判语：不可判**: A 臂未评分。n=1，不构成结论。

## 3. 过程分析（执行层）

本节每个数字都来自 `campaign_analysis.analyse_case` 对该格 rollout 的
挖掘：工具调用与结果、推理摘要、shell 命令。等级好坏与本节无关，一个
拿到 publication 的 run 照样可能在某个工具上空转二十分钟。

### 3.1 hex-full-r1（B/full）

- rollout 记录 1009 条；工具调用 313 次，其中出错 1 次；推理段 80 段

**工具错误率**

| 工具 | 调用 | 出错 | 错误率 | 累计耗时 | 最常见错误 |
|---|---|---|---|---|---|
| `refine` | 12 | 1 | 0.083 | 20.0s | `stored solvent mask is stale (f_mask has 11289 reflections, data has 21774): the data changed since masking. R` |
| `exec` | 161 | 0 | 0.0 | — | — |
| `wait` | 16 | 0 | 0.0 | — | — |
| `run_shelxt` | 14 | 0 | 0.0 | 1.7s | — |
| `run_shelxl` | 7 | 0 | 0.0 | 37.9s | — |
| `checkout` | 7 | 0 | 0.0 | 1.6s | — |
| `read_skill` | 6 | 0 | 0.0 | 0.1s | — |
| `inspect_model` | 6 | 0 | 0.0 | 0.2s | — |
| `get_project_brief` | 5 | 0 | 0.0 | 0.3s | — |
| `screen_space_groups` | 5 | 0 | 0.0 | 15.2s | — |
| `edit_atoms` | 5 | 0 | 0.0 | 0.5s | — |
| `compare_nodes` | 5 | 0 | 0.0 | 0.3s | — |
| `ghost_test` | 5 | 0 | 0.0 | 62.6s | — |
| `add_hydrogens` | 5 | 0 | 0.0 | 0.2s | — |
| `situation_report` | 4 | 0 | 0.0 | 1.9s | — |
| `validate_structure` | 4 | 0 | 0.0 | 1.4s | — |
| `view_structure` | 4 | 0 | 0.0 | 3.0s | — |
| `branch` | 4 | 0 | 0.0 | 1.0s | — |
| `model_disorder` | 4 | 0 | 0.0 | 0.3s | — |
| `list_nodes` | 4 | 0 | 0.0 | 0.2s | — |
| `ingest_vendor_data` | 2 | 0 | 0.0 | 2.8s | — |
| `audit_heavy_sites` | 2 | 0 | 0.0 | 1.5s | — |
| `set_restraints` | 2 | 0 | 0.0 | 0.1s | — |
| `assemble_asu` | 2 | 0 | 0.0 | — | — |
| `solvent_mask` | 2 | 0 | 0.0 | 9.5s | — |
| `check_symmetry` | 2 | 0 | 0.0 | — | — |
| `change_space_group` | 2 | 0 | 0.0 | 0.6s | — |
| `finalize_delivery` | 2 | 0 | 0.0 | 1.2s | — |
| `set_experiment` | 1 | 0 | 0.0 | 1.8s | — |
| `audit_reflection_data` | 1 | 0 | 0.0 | 0.8s | — |
| `estimate_resolution` | 1 | 0 | 0.0 | 0.8s | — |
| `set_resolution_limit` | 1 | 0 | 0.0 | 0.1s | — |
| `reflection_statistics` | 1 | 0 | 0.0 | 4.1s | — |
| `audit_element_assignment` | 1 | 0 | 0.0 | — | — |
| `probe_site` | 1 | 0 | 0.0 | 6.5s | — |
| `set_z` | 1 | 0 | 0.0 | — | — |
| `rename_atoms` | 1 | 0 | 0.0 | — | — |
| `set_twin` | 1 | 0 | 0.0 | — | — |
| `element_scan` | 1 | 0 | 0.0 | 6.8s | — |
| `write_outputs` | 1 | 0 | 0.0 | 4.9s | — |
| `run_checkcif` | 1 | 0 | 0.0 | 20.5s | — |
| `get_geometry` | 1 | 0 | 0.0 | 0.1s | — |

协议性拒绝 1 次（不计入出错：工具按协议先拒、agent 补理由再收）：`finalize_delivery` ×1

**schema 拒绝（MCP 层在工具执行前挡下的调用）**

这类调用工具根本没跑过，因此和工具好不好用无关，只和**参数面好不好
调**有关。

_无_

**原地打转（短窗口内重复同一调用、同一参数）**

轮询已剔除（见下一小节）：detach 任务的状态查询本来就该重复。

- `get_project_brief` 重复 3 次　参数 `{}`
- `run_shelxl` 重复 2 次　参数 `{"l_s": 0, "mode": "check", "timeout_s": 300}`
- `screen_space_groups` 重复 1 次　参数 `{"d_min": 0.997, "laue_group": "P -1", "max_out": 2, "merge_stats": true}`
- `situation_report` 重复 1 次　参数 `{"render": true}`
- `validate_structure` 重复 1 次　参数 `{"expect_framework": true}`
- `checkout` 重复 1 次　参数 `{"node": "n0115"}`

**轮询（detach 任务的状态查询，按工具契约每 60-120 s 一次）**

- `run_shelxt` 轮询 `job_20260904_075158` 12 次，覆盖 590.2s 墙钟（平均间隔 53.7s）
- 合计：12 次轮询，覆盖 590.2s 墙钟；这是**等待**，不是打转

**服务端丢下的工具（MCP 传输断开时仍在算）**

_无_

**参数试错（同一工具连续调用、参数每次都变，且其中有出错）**

_无_

连续换参但全部成功（读卡、逐段查看、逐片段验证一类的正常浏览，不计入易用性信号）：
`read_skill` 4 次 4 种; `add_hydrogens` 3 次 3 种

**转向（换打法，并附紧邻其前的工具错误）**

- 触发词 `instead of`，其前无工具报错
  > …hema list since there’s a hint indicating I need to do so. The fact that AGENTS can read suggests that I should focus on using the crystalpilot skill knowledge instead of relying on the “available skill” system. I’ll have to explore this further and ensure I understand how to utilize these tools ef
- 触发词 `timeout`，其前无工具报错
  > …model isn't atomless, since run_shelxt ignores atoms and can adapt the solution. I’ll set the composition as "C N O." I think it's a good idea to detach with a timeout of 900 and solve_resolution of 0.997. Also, I’ll make sure n_phase_sets is set to default omit, and all_space_groups is true. Let’s
- 触发词 `instead of`，其前无工具报错
  > …e waiting for around 60 seconds. While I can call functionality like `functions.wait`, I might explore using `Start-Sleep` or even a `Promise` to set timeouts. Instead of blocking too long, I think a 20-second wait works well to allow the search to complete and then eventually update commentary soo
- 触发词 `timeout`，其前无工具报错
  > … promising! I should definitely keep the mask. Now, it’s time to run a symmetry check on the refined model before moving forward with the group. I should set a timeout for `check_symmetry`, maybe around 120 seconds, just to be cautious. Let’s get that done!

**shell 危险用法**

_无_

**数据泄漏审计**

_干净：未读取自己 staging 目录以外的导师侧路径_

**路径线索（agent 从目录名里读出的提示）**

- `r25a`：… title and read the start.ins file, focusing on the first 30 lines, as it might contain relevant information like title r25a. I’m wondering
- `r25a`：…ated to unregistered heavy atoms. The data composition indicates only CHNO, but it could also contain metal. The title “r25a” and “reg2-mof

### 3.2 cage-full-r1（B/full）

- rollout 记录 1261 条；工具调用 370 次，其中出错 0 次；推理段 97 段

**工具错误率**

| 工具 | 调用 | 出错 | 错误率 | 累计耗时 | 最常见错误 |
|---|---|---|---|---|---|
| `exec` | 158 | 0 | 0.0 | — | — |
| `wait` | 57 | 0 | 0.0 | — | — |
| `run_shelxt` | 22 | 0 | 0.0 | 2.4s | — |
| `run_shelxl` | 12 | 0 | 0.0 | 192.2s | — |
| `branch` | 11 | 0 | 0.0 | 2.5s | — |
| `refine` | 10 | 0 | 0.0 | 638.8s | — |
| `validate_structure` | 9 | 0 | 0.0 | 7.2s | — |
| `inspect_model` | 7 | 0 | 0.0 | 0.4s | — |
| `edit_atoms` | 7 | 0 | 0.0 | 0.4s | — |
| `situation_report` | 6 | 0 | 0.0 | 3.4s | — |
| `checkout` | 6 | 0 | 0.0 | 0.7s | — |
| `solvent_mask` | 6 | 0 | 0.0 | 13.3s | — |
| `integrate_difference_density` | 5 | 0 | 0.0 | 3.7s | — |
| `assemble_asu` | 4 | 0 | 0.0 | 4.1s | — |
| `read_skill` | 4 | 0 | 0.0 | 0.1s | — |
| `get_project_brief` | 3 | 0 | 0.0 | 1.8s | — |
| `audit_reflection_data` | 3 | 0 | 0.0 | 1.9s | — |
| `add_atoms_from_difference_map` | 3 | 0 | 0.0 | 0.3s | — |
| `compare_nodes` | 3 | 0 | 0.0 | 0.2s | — |
| `ghost_test` | 3 | 0 | 0.0 | 353.7s | — |
| `ingest_vendor_data` | 2 | 0 | 0.0 | 2.0s | — |
| `screen_space_groups` | 2 | 0 | 0.0 | 2.7s | — |
| `view_structure` | 2 | 0 | 0.0 | 1.3s | — |
| `check_symmetry` | 2 | 0 | 0.0 | — | — |
| `get_geometry` | 2 | 0 | 0.0 | 0.1s | — |
| `probe_site` | 2 | 0 | 0.0 | 169.7s | — |
| `set_restraints` | 2 | 0 | 0.0 | 0.1s | — |
| `write_outputs` | 2 | 0 | 0.0 | 5.4s | — |
| `set_experiment` | 1 | 0 | 0.0 | 0.5s | — |
| `estimate_resolution` | 1 | 0 | 0.0 | 0.5s | — |
| `set_resolution_limit` | 1 | 0 | 0.0 | 0.1s | — |
| `solve_superflip` | 1 | 0 | 0.0 | 11.9s | — |
| `interpret_peaks` | 1 | 0 | 0.0 | 0.1s | — |
| `fourier_complete` | 1 | 0 | 0.0 | 8.7s | — |
| `audit_heavy_sites` | 1 | 0 | 0.0 | 1.8s | — |
| `audit_element_assignment` | 1 | 0 | 0.0 | 0.1s | — |
| `element_scan` | 1 | 0 | 0.0 | 472.3s | — |
| `reflection_statistics` | 1 | 0 | 0.0 | 1.0s | — |
| `inspect_map` | 1 | 0 | 0.0 | 0.4s | — |
| `model_disorder` | 1 | 0 | 0.0 | 0.1s | — |
| `rename_atoms` | 1 | 0 | 0.0 | 0.1s | — |
| `run_checkcif` | 1 | 0 | 0.0 | 26.6s | — |
| `finalize_delivery` | 1 | 0 | 0.0 | 1.1s | — |

**schema 拒绝（MCP 层在工具执行前挡下的调用）**

这类调用工具根本没跑过，因此和工具好不好用无关，只和**参数面好不好
调**有关。

_无_

**原地打转（短窗口内重复同一调用、同一参数）**

轮询已剔除（见下一小节）：detach 任务的状态查询本来就该重复。

- `validate_structure` 重复 3 次　参数 `{}`
- `inspect_model` 重复 3 次　参数 `{"detail": "atoms"}`
- `solvent_mask` 重复 3 次　参数 `{"d_min": 0.996, "max_cycles": 1000, "min_void_volume": 40, "timeout_s": 600}`
- `situation_report` 重复 2 次　参数 `{"render": true}`
- `checkout` 重复 2 次　参数 `{"node": "n0076"}`
- `get_project_brief` 重复 1 次　参数 `{}`
- `audit_reflection_data` 重复 1 次　参数 `{}`
- `run_shelxl` 重复 1 次　参数 `{"l_s": 5, "mode": "adopt", "timeout_s": 300}`
- `validate_structure` 重复 1 次　参数 `{"expect_framework": true}`
- `run_shelxl` 重复 1 次　参数 `{"l_s": 0, "mode": "check", "timeout_s": 300}`

**轮询（detach 任务的状态查询，按工具契约每 60-120 s 一次）**

- `run_shelxt` 轮询 `job_20260904_083023` 9 次，覆盖 407.8s 墙钟（平均间隔 51.0s）
- `run_shelxt` 轮询 `job_20260904_083738` 8 次，覆盖 364.9s 墙钟（平均间隔 52.1s）
- 合计：17 次轮询，覆盖 772.7s 墙钟；这是**等待**，不是打转

**服务端丢下的工具（MCP 传输断开时仍在算）**

_无_

**参数试错（同一工具连续调用、参数每次都变，且其中有出错）**

_无_

连续换参但全部成功（读卡、逐段查看、逐片段验证一类的正常浏览，不计入易用性信号）：
`run_shelxt` 22 次 7 种; `integrate_difference_density` 5 次 5 种; `read_skill` 4 次 4 种

**转向（换打法，并附紧邻其前的工具错误）**

- 触发词 `timeout`，其前无工具报错
  > …CHNO placeholder, and maybe include Z. I think I should set all_space_groups to true and use current P21/c.   For solve_resolution, I could go with 0.996 and a timeout of around 1200 seconds since the user wants a solve and there's a long allowed time. I just need to detach to return the job, and c
- 触发词 `timeout`，其前无工具报错
  > …f. It looks like the process ignores the cutoff based on a note, but I've successfully merged all 44,942. That should be manageable! I'll set n_cycles to 5 and timeout to 300. I'm hoping this approach will help highlight key aspects of the data I’m analyzing. Let's see what happens!
- 触发词 `instead of`，其前无工具报错
  > …isting atom after multiple additions is actually an Oxygen atom? That’s a bit suspicious since there are two peaks registered, likely due to a recently added O instead of a metal. Hmm, I think I need to refine this over five cycles to clarify the results.
- 触发词 `instead of`，其前无工具报错
  > **Evaluating data audit**  I'm thinking about using the full data for the audit instead of a cutoff for Rint, which seems okay. There’s no twin involved, and the pseudo-translation appears to be oddly weak, maybe moderately useful. I might …
- 触发词 `instead of`，其前无工具报错
  > …s only. It seems like we need to figure out the SHELXT composition for Zr, C, and O, but the exact formula is unknown. The existing model, n0002, is promising. Instead of starting from scratch, I think it's better to return to the full model and apply a solvent mask early. I need to prune any nonse
- 触发词 `instead of`，其前无工具报错
  > **Evaluating model occupancy**  I need to remember that tool acceptance suggests we should keep based occupancy instead of R. Even though keeping the split might yield slightly worse results with R, it's okay because of chemistry, along with the importance of disclosure. …
- 触发词 `instead of`，其前无工具报错
  > …apply weights first. There are too many high-energy atoms that are unconstrained, so I'll need to prune or restrain them. It seems I could provide a diagnostic instead of a final answer since there's some synthesis that's missing. I might also have to remove dubious guest fragments from the mask to
- 触发词 `instead of`，其前无工具报错
  > **Analyzing computational errors**  I realize there's a critical mistake in the process. After checking out n0108, I see that the mask recompute only gave 822 instead of 1172, likely because n0108 corresponds to the current model while the solvent mask was based on an older snapshot. The mask from n

**shell 危险用法**

_无_

**数据泄漏审计**

_干净：未读取自己 staging 目录以外的导师侧路径_

**路径线索（agent 从目录名里读出的提示）**

- `pa1c-link`：…using direct methods with the exact composition of Zr6 and a known linker, though the linker remains unknown. The path "pa1c-link" might re

### 3.3 全实验汇总

**错误率最高的工具**（只列有过失败的）

| 工具 | 调用 | 出错 | 错误率 | 出错的格数 |
|---|---|---|---|---|
| `refine` | 22 | 1 | 0.045 | 1/2 |

**打转 / 试错最多的工具**

| 工具 | 打转重复次数 | 参数试错种数 |
|---|---|---|
| `validate_structure` | 5 | 0 |
| `run_shelxl` | 4 | 0 |
| `get_project_brief` | 4 | 0 |
| `checkout` | 3 | 0 |
| `inspect_model` | 3 | 0 |
| `situation_report` | 3 | 0 |
| `solvent_mask` | 3 | 0 |
| `screen_space_groups` | 1 | 0 |
| `audit_reflection_data` | 1 | 0 |

**每个工具的累计耗时**

| 工具 | 调用 | 累计耗时 |
|---|---|---|
| `refine` | 22 | 658.8s |
| `element_scan` | 2 | 479.1s |
| `ghost_test` | 8 | 416.3s |
| `run_shelxl` | 19 | 230.1s |
| `probe_site` | 3 | 176.2s |
| `run_checkcif` | 2 | 47.1s |
| `solvent_mask` | 8 | 22.8s |
| `screen_space_groups` | 7 | 17.9s |
| `solve_superflip` | 1 | 11.9s |
| `write_outputs` | 3 | 10.3s |
| `fourier_complete` | 1 | 8.7s |
| `validate_structure` | 13 | 8.6s |
| `situation_report` | 10 | 5.3s |
| `reflection_statistics` | 2 | 5.1s |
| `ingest_vendor_data` | 4 | 4.8s |

## 4. 跑偏倾向与打转点（机械信号，待人工核读）

下面每一条都是程序能算出来的**信号**，不是结论。信号只回答「该去
transcript 的哪一段看」；看到的究竟是不是跑偏，必须人读。

- **hex-full-r1**
  - [原地打转] `get_project_brief` 同参数重复 3 次（阈值 3）
- **cage-full-r1**
  - [原地打转] `validate_structure` 同参数重复 3 次（阈值 3）
  - [原地打转] `inspect_model` 同参数重复 3 次（阈值 3）
  - [原地打转] `solvent_mask` 同参数重复 3 次（阈值 3）

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
| `validate_structure` | 5 | 0 | 0 | 0 | 5 | 13 | 0 | 0.0 |
| `run_shelxl` | 4 | 0 | 0 | 0 | 4 | 19 | 0 | 0.0 |
| `get_project_brief` | 4 | 0 | 0 | 0 | 4 | 8 | 0 | 0.0 |
| `checkout` | 3 | 0 | 0 | 0 | 3 | 13 | 0 | 0.0 |
| `inspect_model` | 3 | 0 | 0 | 0 | 3 | 13 | 0 | 0.0 |
| `situation_report` | 3 | 0 | 0 | 0 | 3 | 10 | 0 | 0.0 |
| `solvent_mask` | 3 | 0 | 0 | 0 | 3 | 8 | 0 | 0.0 |
| `refine` | 1 | 1 | 0 | 0 | 0 | 22 | 0 | 0.045 |
| `screen_space_groups` | 1 | 0 | 0 | 0 | 1 | 7 | 0 | 0.0 |
| `audit_reflection_data` | 1 | 0 | 0 | 0 | 1 | 4 | 0 | 0.0 |

## 附：运行记账

`root_agents_sha256` 对一条干净的臂必须是 null，`agents_chain` 长度必须
是 1（只有项目自己那份 AGENTS.md）。

| 格 | model | effort | knowledge_mode | agents_version | agents_sha256 | 匹配模板 | root_agents_sha256 | 链长 |
|---|---|---|---|---|---|---|---|---|
| hex-full-r1 | gpt-5.6-sol | xhigh | full | <!-- crystalpilot-agents-v33 --> | `250395d3` | 是 | null（干净） | 1 |
| cage-full-r1 | gpt-5.6-sol | xhigh | full | <!-- crystalpilot-agents-v33 --> | `250395d3` | 是 | null（干净） | 1 |

- 未发现祖先 AGENTS.md 注入、模板哈希不符或臂标签矛盾（未跑的格子无从检查）。
