# ka1：知识层消融实验分析（草稿）

**实验设计**：只变一件事，项目自己的 AGENTS.md 里预装了多少晶体学知识。
A 臂 = tools（仅工具契约）：只有操作契约与诚实规则（怎么调工具、交付
格式、「没定就说没定，不许编」），没有任何技能卡、没有任何晶体学判据。
B 臂 = full（v32+技能卡）：现行 AGENTS v32 加完整技能卡库。两臂同一
条 L0 简报、同一模型、同一份数据、同一套 MCP 工具面。

**当前进度**：共 1 格，已开跑 1 格，已评分 1 格。

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
| dbu | B/full | acceptable | 0.0626 | 0.0447 | +0.0179 | 是 | — | s2 CIF↔fcf:是<br>s3 REPORT↔CIF:是<br>s4 checkCIF解释门:是<br>e 窥视干净:是<br>自洽:是<br>结论↔CIF:是<br>未决披露:4 条 | 是（交付即最佳，或差距在 0.01 以内） | 14 min | 7,478,665 | 144 | 0 | — | `250395d3` 是 | graded |

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

### 2.1 dbu

| 项目 | A/tools | B/full |
|---|---|---|
| 等级 | — | acceptable |
| R1(agent) | — | 0.0626 |
| R1(ref) | — | 0.0447 |
| ΔR1 | — | +0.0179 |
| 空间群 agent / ref | — | P 1 21/n 1 / P 1 21/n 1 |
| 空间群同型 | — | 是 |
| 骨架复现 emma solved | — | 否 |
| 元素一致 | — | — |
| 自洽 | — | 是 |
| 最佳节点是否交付 | — | 是（交付即最佳，或差距在 0.01 以内） |
| 掩膜 / 客体 | — | 掩膜=否；客体片段=7；空腔占比=0.0%；参考客体复现=—/— |
| 未达 publication 的原因 | — | - framework_reproduced_disorder_incomplete: 26/28 reference non-H atoms matched (rms 0.029 A); unmatched = C12A (reference occupancy 0.265 < 1 (disorder component<br>- chemistry: N1 is a planar six-ring atom carrying a C substituent at 1.47 A: aromatic C labelled N? (a pyridinium N-C looks the same; low confidence)<br>- R1 delta vs reference 0.0179 > 0.01<br>- metadata incomplete (A-level CIF-item alerts, not scored): 183, 184, 185, 197, 198, 699 |
| 墙钟 | — | 14 min（838 s） |
| 并发泳道 | — | 0 |
| tokens | — | 7,478,665 |
| 工具调用 / 出错 | — | 144 / 0 |
| knowledge_mode | — | full |

**机械判语：不可判**: A 臂未评分。n=1，不构成结论。

## 3. 过程分析（执行层）

本节每个数字都来自 `campaign_analysis.analyse_case` 对该格 rollout 的
挖掘：工具调用与结果、推理摘要、shell 命令。等级好坏与本节无关，一个
拿到 publication 的 run 照样可能在某个工具上空转二十分钟。

### 3.1 dbu-full-r1（B/full）

- rollout 记录 491 条；工具调用 144 次，其中出错 0 次；推理段 38 段

**工具错误率**

| 工具 | 调用 | 出错 | 错误率 | 累计耗时 | 最常见错误 |
|---|---|---|---|---|---|
| `exec` | 80 | 0 | 0.0 | — | — |
| `refine` | 6 | 0 | 0.0 | 2.5s | — |
| `inspect_model` | 4 | 0 | 0.0 | 0.1s | — |
| `run_shelxl` | 4 | 0 | 0.0 | 1.8s | — |
| `read_skill` | 3 | 0 | 0.0 | — | — |
| `situation_report` | 3 | 0 | 0.0 | 0.7s | — |
| `branch` | 3 | 0 | 0.0 | 0.7s | — |
| `get_geometry` | 3 | 0 | 0.0 | — | — |
| `validate_structure` | 3 | 0 | 0.0 | 0.1s | — |
| `add_hydrogens` | 3 | 0 | 0.0 | 0.2s | — |
| `get_project_brief` | 2 | 0 | 0.0 | 0.2s | — |
| `ingest_vendor_data` | 2 | 0 | 0.0 | 0.6s | — |
| `audit_reflection_data` | 2 | 0 | 0.0 | — | — |
| `edit_atoms` | 2 | 0 | 0.0 | 0.3s | — |
| `view_structure` | 2 | 0 | 0.0 | 0.6s | — |
| `model_disorder` | 2 | 0 | 0.0 | 0.2s | — |
| `assemble_asu` | 2 | 0 | 0.0 | 0.1s | — |
| `write_outputs` | 2 | 0 | 0.0 | 0.4s | — |
| `run_checkcif` | 2 | 0 | 0.0 | 8.1s | — |
| `finalize_delivery` | 2 | 0 | 0.0 | 0.1s | — |
| `set_experiment` | 1 | 0 | 0.0 | 0.2s | — |
| `screen_space_groups` | 1 | 0 | 0.0 | 0.1s | — |
| `estimate_resolution` | 1 | 0 | 0.0 | — | — |
| `change_space_group` | 1 | 0 | 0.0 | 0.1s | — |
| `run_shelxt` | 1 | 0 | 0.0 | 2.3s | — |
| `audit_element_assignment` | 1 | 0 | 0.0 | — | — |
| `compare_nodes` | 1 | 0 | 0.0 | 0.1s | — |
| `inspect_map` | 1 | 0 | 0.0 | 0.1s | — |
| `check_symmetry` | 1 | 0 | 0.0 | — | — |
| `checkout` | 1 | 0 | 0.0 | 0.2s | — |
| `set_twin` | 1 | 0 | 0.0 | — | — |
| `rename_atoms` | 1 | 0 | 0.0 | 0.1s | — |

协议性拒绝 1 次（不计入出错：工具按协议先拒、agent 补理由再收）：`finalize_delivery` ×1

**schema 拒绝（MCP 层在工具执行前挡下的调用）**

这类调用工具根本没跑过，因此和工具好不好用无关，只和**参数面好不好
调**有关。

_无_

**原地打转（短窗口内重复同一调用、同一参数）**

轮询已剔除（见下一小节）：detach 任务的状态查询本来就该重复。

- `get_project_brief` 重复 1 次　参数 `{}`
- `validate_structure` 重复 1 次　参数 `{}`
- `run_checkcif` 重复 1 次　参数 `{"cif": "CrystalPilot Results/task_20260904_151114/final.cif", "timeout_s": 420}`

**轮询（detach 任务的状态查询，按工具契约每 60-120 s 一次）**

_无_

**服务端丢下的工具（MCP 传输断开时仍在算）**

_无_

**参数试错（同一工具连续调用、参数每次都变，且其中有出错）**

_无_

**转向（换打法，并附紧邻其前的工具错误）**

- 触发词 `instead of`，其前无工具报错
  > …aluating chemical configurations**  I’m considering when C00Q equals C00P double. In that case, C00Q divided by P would lead to each CH having 2 hydrogen atoms instead of 4. However, C00B seems like it would require additional valences or hydrogen atoms. It’s a subtle shift that might have implicat
- 触发词 `instead of`，其前无工具报错
  > …*  I'm noting that the merged position moved 0.3A, which isn’t the same as the original. If the goal is to reject the branch, it makes sense to check out n0012 instead of refining the merged version. So, I think the best step is to proceed with checking out n0012. That feels like the more straightf

**shell 危险用法**

_无_

**数据泄漏审计**

_干净：未读取自己 staging 目录以外的导师侧路径_

**路径线索（agent 从目录名里读出的提示）**

_无_

### 3.2 全实验汇总

**错误率最高的工具**（只列有过失败的）

| 工具 | 调用 | 出错 | 错误率 | 出错的格数 |
|---|---|---|---|---|
| _无工具报错_ | | | | |

**打转 / 试错最多的工具**

| 工具 | 打转重复次数 | 参数试错种数 |
|---|---|---|
| `validate_structure` | 1 | 0 |
| `get_project_brief` | 1 | 0 |
| `run_checkcif` | 1 | 0 |

**每个工具的累计耗时**

| 工具 | 调用 | 累计耗时 |
|---|---|---|
| `run_checkcif` | 2 | 8.1s |
| `refine` | 6 | 2.5s |
| `run_shelxt` | 1 | 2.3s |
| `run_shelxl` | 4 | 1.8s |
| `situation_report` | 3 | 0.7s |
| `branch` | 3 | 0.7s |
| `ingest_vendor_data` | 2 | 0.6s |
| `view_structure` | 2 | 0.6s |
| `write_outputs` | 2 | 0.4s |
| `edit_atoms` | 2 | 0.3s |
| `add_hydrogens` | 3 | 0.2s |
| `get_project_brief` | 2 | 0.2s |
| `model_disorder` | 2 | 0.2s |
| `set_experiment` | 1 | 0.2s |
| `checkout` | 1 | 0.2s |

## 4. 跑偏倾向与打转点（机械信号，待人工核读）

下面每一条都是程序能算出来的**信号**，不是结论。信号只回答「该去
transcript 的哪一段看」；看到的究竟是不是跑偏，必须人读。

_当前没有触发任何机械信号（也可能只是还没跑）_

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
| `validate_structure` | 1 | 0 | 0 | 0 | 1 | 3 | 0 | 0.0 |
| `get_project_brief` | 1 | 0 | 0 | 0 | 1 | 2 | 0 | 0.0 |
| `run_checkcif` | 1 | 0 | 0 | 0 | 1 | 2 | 0 | 0.0 |

## 附：运行记账

`root_agents_sha256` 对一条干净的臂必须是 null，`agents_chain` 长度必须
是 1（只有项目自己那份 AGENTS.md）。

| 格 | model | effort | knowledge_mode | agents_version | agents_sha256 | 匹配模板 | root_agents_sha256 | 链长 |
|---|---|---|---|---|---|---|---|---|
| dbu-full-r1 | gpt-5.6-sol | xhigh | full | <!-- crystalpilot-agents-v33 --> | `250395d3` | 是 | null（干净） | 1 |

- 未发现祖先 AGENTS.md 注入、模板哈希不符或臂标签矛盾（未跑的格子无从检查）。
