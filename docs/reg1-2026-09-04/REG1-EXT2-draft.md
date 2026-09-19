# ka1：知识层消融实验分析（草稿）

**实验设计**：只变一件事，项目自己的 AGENTS.md 里预装了多少晶体学知识。
A 臂 = tools（仅工具契约）：只有操作契约与诚实规则（怎么调工具、交付
格式、「没定就说没定，不许编」），没有任何技能卡、没有任何晶体学判据。
B 臂 = full（v32+技能卡）：现行 AGENTS v32 加完整技能卡库。两臂同一
条 L0 简报、同一模型、同一份数据、同一套 MCP 工具面。

**当前进度**：共 5 格，已开跑 5 格，已评分 5 格。

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
| hsl | B/full | acceptable | 0.0263 | 0.0264 | -0.0001 | 是 | — | s2 CIF↔fcf:是<br>s3 REPORT↔CIF:是<br>s4 checkCIF解释门:是<br>e 窥视干净:是<br>自洽:是<br>结论↔CIF:是<br>未决披露:3 条 | 是（交付即最佳，或差距在 0.01 以内） | 19 min | 8,483,520 | 158 | 1 | — | `c92b3945` 是 | graded |
| cuox | B/full | publication | 0.0178 | 0.0179 | -0.0001 | 是 | 是 | s2 CIF↔fcf:是<br>s3 REPORT↔CIF:是<br>s4 checkCIF解释门:是<br>e 窥视干净:是<br>自洽:是<br>结论↔CIF:是<br>未决披露:2 条 | 是（交付即最佳，或差距在 0.01 以内） | 14 min | 7,258,445 | 158 | 1 | — | `c92b3945` 是 | graded |
| dbu | B/full | acceptable | 0.0626 | 0.0447 | +0.0179 | 是 | — | s2 CIF↔fcf:是<br>s3 REPORT↔CIF:是<br>s4 checkCIF解释门:是<br>e 窥视干净:是<br>自洽:是<br>结论↔CIF:是<br>未决披露:2 条 | 是（交付即最佳，或差距在 0.01 以内） | 16 min | 7,821,154 | 151 | 0 | — | `c92b3945` 是 | graded |
| rz | B/full | below_bar | 0.1246 | 0.0996 | +0.0250 | 是 | — | s2 CIF↔fcf:是<br>s3 REPORT↔CIF:是<br>s4 checkCIF解释门:是<br>e 窥视干净:是<br>自洽:是<br>结论↔CIF:是<br>未决披露:3 条 | 是（交付即最佳，或差距在 0.01 以内） | 14 min | 7,368,445 | 152 | 0 | — | `c92b3945` 是 | graded |
| nm | B/full | acceptable | 0.0948 | 0.0526 | +0.0006 | 是 | — | s2 CIF↔fcf:是<br>s3 REPORT↔CIF:—<br>s4 checkCIF解释门:是<br>e 窥视干净:是<br>自洽:是<br>结论↔CIF:是<br>未决披露:2 条 | 是（交付即最佳，或差距在 0.01 以内） | 13 min | 5,245,141 | 125 | 0 | — | `c92b3945` 是 | graded |

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

### 2.1 hsl

| 项目 | A/tools | B/full |
|---|---|---|
| 等级 | — | acceptable |
| R1(agent) | — | 0.0263 |
| R1(ref) | — | 0.0264 |
| ΔR1 | — | -0.0001 |
| 空间群 agent / ref | — | P 21 21 21 (a+1/4,b,c-1/4) / P 21 21 21 |
| 空间群同型 | — | 是 |
| 骨架复现 emma solved | — | 是 |
| 元素一致 | — | — |
| 自洽 | — | 是 |
| 最佳节点是否交付 | — | 是（交付即最佳，或差距在 0.01 以内） |
| 掩膜 / 客体 | — | 掩膜=否；客体片段=3；空腔占比=0.0%；参考客体复现=—/— |
| 未达 publication 的原因 | — | - delivered CIF names a space group its own operator loop contradicts; the operator loop was believed so the structure comparison above is sound (see cif_symmetry<br>- CIF symmetry inconsistent: the operator loop defines P 21 21 21 (a+1/4,b,c-1/4), but _space_group_name_H-M_alt=P 21 21 21, _symmetry_space_group_name_H-M=P 21 2<br>- metadata incomplete (A-level CIF-item alerts, not scored): 183, 184, 185, 197, 198, 699 |
| 墙钟 | — | 19 min（1139 s） |
| 并发泳道 | — | 0 |
| tokens | — | 8,483,520 |
| 工具调用 / 出错 | — | 158 / 1 |
| knowledge_mode | — | full |

**机械判语：不可判**: A 臂未评分。n=1，不构成结论。

### 2.2 cuox

| 项目 | A/tools | B/full |
|---|---|---|
| 等级 | — | publication |
| R1(agent) | — | 0.0178 |
| R1(ref) | — | 0.0179 |
| ΔR1 | — | -0.0001 |
| 空间群 agent / ref | — | P 1 21/c 1 / P 1 21/c 1 |
| 空间群同型 | — | 是 |
| 骨架复现 emma solved | — | 是 |
| 元素一致 | — | 是 |
| 自洽 | — | 是 |
| 最佳节点是否交付 | — | 是（交付即最佳，或差距在 0.01 以内） |
| 掩膜 / 客体 | — | 掩膜=否；客体片段=1；空腔占比=0.0%；参考客体复现=—/— |
| 未达 publication 的原因 | — | - metadata incomplete (A-level CIF-item alerts, not scored): 183, 184, 185, 197, 198, 699 |
| 墙钟 | — | 14 min（812 s） |
| 并发泳道 | — | 0 |
| tokens | — | 7,258,445 |
| 工具调用 / 出错 | — | 158 / 1 |
| knowledge_mode | — | full |

**机械判语：不可判**: A 臂未评分。n=1，不构成结论。

### 2.3 dbu

| 项目 | A/tools | B/full |
|---|---|---|
| 等级 | — | acceptable |
| R1(agent) | — | 0.0626 |
| R1(ref) | — | 0.0447 |
| ΔR1 | — | +0.0179 |
| 空间群 agent / ref | — | P 1 21/n 1 / P 1 21/n 1 |
| 空间群同型 | — | 是 |
| 骨架复现 emma solved | — | 是 |
| 元素一致 | — | — |
| 自洽 | — | 是 |
| 最佳节点是否交付 | — | 是（交付即最佳，或差距在 0.01 以内） |
| 掩膜 / 客体 | — | 掩膜=否；客体片段=7；空腔占比=0.0%；参考客体复现=—/— |
| 未达 publication 的原因 | — | - chemistry: N1 is a planar six-ring atom carrying a C substituent at 1.47 A: aromatic C labelled N? (a pyridinium N-C looks the same; low confidence)<br>- R1 delta vs reference 0.0179 > 0.01<br>- disorder incomplete: C12A, C13A of the reference are not accounted for - model the component(s) before publication<br>- metadata incomplete (A-level CIF-item alerts, not scored): 183, 184, 185, 197, 198, 699 |
| 墙钟 | — | 16 min（964 s） |
| 并发泳道 | — | 0 |
| tokens | — | 7,821,154 |
| 工具调用 / 出错 | — | 151 / 0 |
| knowledge_mode | — | full |

**机械判语：不可判**: A 臂未评分。n=1，不构成结论。

### 2.4 rz

| 项目 | A/tools | B/full |
|---|---|---|
| 等级 | — | below_bar |
| R1(agent) | — | 0.1246 |
| R1(ref) | — | 0.0996 |
| ΔR1 | — | +0.0250 |
| 空间群 agent / ref | — | C 1 2/c 1 / C 1 2/c 1 |
| 空间群同型 | — | 是 |
| 骨架复现 emma solved | — | 是 |
| 元素一致 | — | — |
| 自洽 | — | 是 |
| 最佳节点是否交付 | — | 是（交付即最佳，或差距在 0.01 以内） |
| 掩膜 / 客体 | — | 掩膜=否；客体片段=3；空腔占比=0.0%；参考客体复现=—/— |
| 未达 publication 的原因 | — | - R1 delta vs reference 0.025 > 0.01<br>- R1 0.1246 above 0.10 and delta vs reference 0.025 above 0.02<br>- metadata incomplete (A-level CIF-item alerts, not scored): 183, 184, 185, 197, 198, 699 |
| 墙钟 | — | 14 min（864 s） |
| 并发泳道 | — | 0 |
| tokens | — | 7,368,445 |
| 工具调用 / 出错 | — | 152 / 0 |
| knowledge_mode | — | full |

**机械判语：不可判**: A 臂未评分。n=1，不构成结论。

### 2.5 nm

| 项目 | A/tools | B/full |
|---|---|---|
| 等级 | — | acceptable |
| R1(agent) | — | 0.0948 |
| R1(ref) | — | 0.0526 |
| ΔR1 | — | +0.0006 |
| 空间群 agent / ref | — | P -1 / P -1 |
| 空间群同型 | — | 是 |
| 骨架复现 emma solved | — | 是 |
| 元素一致 | — | — |
| 自洽 | — | 是 |
| 最佳节点是否交付 | — | 是（交付即最佳，或差距在 0.01 以内） |
| 掩膜 / 客体 | — | 掩膜=否；客体片段=1；空腔占比=0.0%；参考客体复现=2/2 |
| 未达 publication 的原因 | — | - disorder incomplete: C15B, C16B of the reference are not accounted for - model the component(s) before publication<br>- metadata incomplete (A-level CIF-item alerts, not scored): 183, 184, 185, 197, 198, 699<br>- lower-R1 node n0012 (R1 0.0807) is not a comparable model: space group P 1 differs from the delivered P -1 - a lower-symmetry trial refines more parameters agai<br>- the deposited model re-refined on the delivered data reaches R1 0.0942 (deposited 0.0526): the deposited R1 is not reproducible on these reflections, so the del |
| 墙钟 | — | 13 min（751 s） |
| 并发泳道 | — | 0 |
| tokens | — | 5,245,141 |
| 工具调用 / 出错 | — | 125 / 0 |
| knowledge_mode | — | full |

**机械判语：不可判**: A 臂未评分。n=1，不构成结论。

## 3. 过程分析（执行层）

本节每个数字都来自 `campaign_analysis.analyse_case` 对该格 rollout 的
挖掘：工具调用与结果、推理摘要、shell 命令。等级好坏与本节无关，一个
拿到 publication 的 run 照样可能在某个工具上空转二十分钟。

### 3.1 hsl-full-r1（B/full）

- rollout 记录 549 条；工具调用 158 次，其中出错 1 次；推理段 43 段

**工具错误率**

| 工具 | 调用 | 出错 | 错误率 | 累计耗时 | 最常见错误 |
|---|---|---|---|---|---|
| `view_structure` | 4 | 1 | 0.25 | 3.1s | `unknown parameter(s) ['view'] for 'view_structure' - nothing was run. Accepted parameters: ['highlight', 'stat` |
| `exec` | 91 | 0 | 0.0 | — | — |
| `inspect_model` | 5 | 0 | 0.0 | 1.2s | — |
| `refine` | 5 | 0 | 0.0 | 5.2s | — |
| `run_shelxl` | 5 | 0 | 0.0 | 11.5s | — |
| `run_shelxt` | 4 | 0 | 0.0 | 14.4s | — |
| `wait` | 4 | 0 | 0.0 | — | — |
| `run_checkcif` | 4 | 0 | 0.0 | 31.0s | — |
| `situation_report` | 3 | 0 | 0.0 | 2.1s | — |
| `check_symmetry` | 3 | 0 | 0.0 | 0.7s | — |
| `branch` | 3 | 0 | 0.0 | 3.3s | — |
| `get_project_brief` | 2 | 0 | 0.0 | 3.5s | — |
| `ingest_vendor_data` | 2 | 0 | 0.0 | 2.6s | — |
| `change_space_group` | 2 | 0 | 0.0 | 1.2s | — |
| `validate_structure` | 2 | 0 | 0.0 | 0.5s | — |
| `finalize_delivery` | 2 | 0 | 0.0 | 0.2s | — |
| `set_experiment` | 1 | 0 | 0.0 | 0.6s | — |
| `screen_space_groups` | 1 | 0 | 0.0 | 0.9s | — |
| `reflection_statistics` | 1 | 0 | 0.0 | 0.3s | — |
| `estimate_resolution` | 1 | 0 | 0.0 | 0.3s | — |
| `audit_reflection_data` | 1 | 0 | 0.0 | 0.3s | — |
| `ncs_audit` | 1 | 0 | 0.0 | 0.1s | — |
| `ghost_test` | 1 | 0 | 0.0 | 5.2s | — |
| `edit_atoms` | 1 | 0 | 0.0 | 1.1s | — |
| `assemble_asu` | 1 | 0 | 0.0 | 0.4s | — |
| `get_geometry` | 1 | 0 | 0.0 | 0.1s | — |
| `add_hydrogens` | 1 | 0 | 0.0 | 0.9s | — |
| `compare_nodes` | 1 | 0 | 0.0 | 0.2s | — |
| `audit_element_assignment` | 1 | 0 | 0.0 | 0.2s | — |
| `rename_atoms` | 1 | 0 | 0.0 | 0.5s | — |
| `run_olex2` | 1 | 0 | 0.0 | 102.9s | — |
| `write_outputs` | 1 | 0 | 0.0 | 0.8s | — |
| `checkout` | 1 | 0 | 0.0 | 0.3s | — |

协议性拒绝 1 次（不计入出错：工具按协议先拒、agent 补理由再收）：`finalize_delivery` ×1

**schema 拒绝（MCP 层在工具执行前挡下的调用）**

这类调用工具根本没跑过，因此和工具好不好用无关，只和**参数面好不好
调**有关。

_无_

**原地打转（短窗口内重复同一调用、同一参数）**

轮询已剔除（见下一小节）：detach 任务的状态查询本来就该重复。

- `inspect_model` 重复 3 次　参数 `{"detail": "atoms"}`
- `run_checkcif` 重复 3 次　参数 `{"cif": "CrystalPilot Results/task_20260904_033432/final.cif", "timeout_s": 420}`
- `get_project_brief` 重复 1 次　参数 `{}`
- `situation_report` 重复 1 次　参数 `{}`
- `validate_structure` 重复 1 次　参数 `{}`

**轮询（detach 任务的状态查询，按工具契约每 60-120 s 一次）**

_无_

**服务端丢下的工具（MCP 传输断开时仍在算）**

_无_

**参数试错（同一工具连续调用、参数每次都变，且其中有出错）**

_无_

**转向（换打法，并附紧邻其前的工具错误）**

- 触发词 `instead of`，其前无工具报错
  > **Exploring PowerShell Command**  I'm considering using PowerShell for reading and parsing data instead of Python. The command might get lengthy, but I think I can manage it. First, I’ll use `Get-Content` with ASCII encoding to read the file. I’ll then spl…

**shell 危险用法**

_无_

**数据泄漏审计**

_干净：未读取自己 staging 目录以外的导师侧路径_

**路径线索（agent 从目录名里读出的提示）**

_无_

### 3.2 cuox-full-r1（B/full）

- rollout 记录 512 条；工具调用 158 次，其中出错 1 次；推理段 40 段

**工具错误率**

| 工具 | 调用 | 出错 | 错误率 | 累计耗时 | 最常见错误 |
|---|---|---|---|---|---|
| `read_skill` | 4 | 1 | 0.25 | 0.7s | `no section matching 'PLAT196' in review-response-ruleset; sections: 1: 晶体学审稿意见应对规则集; 2: 主题索引（跨 A/B 合并）; 3: 导师裁` |
| `exec` | 87 | 0 | 0.0 | — | — |
| `run_shelxl` | 10 | 0 | 0.0 | 12.6s | — |
| `inspect_model` | 7 | 0 | 0.0 | 0.1s | — |
| `edit_atoms` | 4 | 0 | 0.0 | 1.0s | — |
| `situation_report` | 3 | 0 | 0.0 | 1.0s | — |
| `validate_structure` | 3 | 0 | 0.0 | 0.4s | — |
| `assemble_asu` | 3 | 0 | 0.0 | 0.1s | — |
| `get_project_brief` | 2 | 0 | 0.0 | 1.2s | — |
| `ingest_vendor_data` | 2 | 0 | 0.0 | 1.1s | — |
| `audit_reflection_data` | 2 | 0 | 0.0 | — | — |
| `run_shelxt` | 2 | 0 | 0.0 | 2.6s | — |
| `refine` | 2 | 0 | 0.0 | 0.8s | — |
| `audit_heavy_sites` | 2 | 0 | 0.0 | 0.6s | — |
| `add_atoms_from_difference_map` | 2 | 0 | 0.0 | 0.3s | — |
| `get_geometry` | 2 | 0 | 0.0 | 0.2s | — |
| `branch` | 2 | 0 | 0.0 | 0.4s | — |
| `finalize_delivery` | 2 | 0 | 0.0 | 0.5s | — |
| `set_experiment` | 1 | 0 | 0.0 | 0.1s | — |
| `screen_space_groups` | 1 | 0 | 0.0 | 0.1s | — |
| `estimate_resolution` | 1 | 0 | 0.0 | — | — |
| `ghost_test` | 1 | 0 | 0.0 | 0.7s | — |
| `inspect_map` | 1 | 0 | 0.0 | — | — |
| `audit_element_assignment` | 1 | 0 | 0.0 | — | — |
| `add_hydrogens` | 1 | 0 | 0.0 | 0.2s | — |
| `checkout` | 1 | 0 | 0.0 | 0.1s | — |
| `compare_nodes` | 1 | 0 | 0.0 | 0.1s | — |
| `check_symmetry` | 1 | 0 | 0.0 | — | — |
| `view_structure` | 1 | 0 | 0.0 | 0.4s | — |
| `rename_atoms` | 1 | 0 | 0.0 | 0.3s | — |
| `element_scan` | 1 | 0 | 0.0 | 10.3s | — |
| `set_z` | 1 | 0 | 0.0 | 0.5s | — |
| `write_outputs` | 1 | 0 | 0.0 | 1.5s | — |
| `run_checkcif` | 1 | 0 | 0.0 | 8.6s | — |
| `list_skills` | 1 | 0 | 0.0 | 0.2s | — |

协议性拒绝 1 次（不计入出错：工具按协议先拒、agent 补理由再收）：`finalize_delivery` ×1

**schema 拒绝（MCP 层在工具执行前挡下的调用）**

这类调用工具根本没跑过，因此和工具好不好用无关，只和**参数面好不好
调**有关。

_无_

**原地打转（短窗口内重复同一调用、同一参数）**

轮询已剔除（见下一小节）：detach 任务的状态查询本来就该重复。

- `inspect_model` 重复 4 次　参数 `{"detail": "atoms"}`
- `run_shelxl` 重复 2 次　参数 `{"l_s": 30, "mode": "adopt", "timeout_s": 180}`
- `get_project_brief` 重复 1 次　参数 `{}`
- `run_shelxl` 重复 1 次　参数 `{"l_s": 10, "mode": "adopt_wght", "timeout_s": 180, "wght_rounds": 4}`

**轮询（detach 任务的状态查询，按工具契约每 60-120 s 一次）**

_无_

**服务端丢下的工具（MCP 传输断开时仍在算）**

_无_

**参数试错（同一工具连续调用、参数每次都变，且其中有出错）**

- `read_skill` 连续 3 次，3 种参数，其中出错 1 次

连续换参但全部成功（读卡、逐段查看、逐片段验证一类的正常浏览，不计入易用性信号）：
`run_shelxl` 3 次 3 种; `run_shelxl` 4 次 3 种

**转向（换打法，并附紧邻其前的工具错误）**

- 触发词 `timeout`，其前无工具报错
  > …ydrogen atoms, which seems correct. I wonder if there's a coherent hydrogen bond network in the supercell. Checking symmetry is also crucial, and I might set a timeout for about 60 seconds to ensure everything's captured. There's a lot to unpack here!

**shell 危险用法**

_无_

**数据泄漏审计**

_干净：未读取自己 staging 目录以外的导师侧路径_

**路径线索（agent 从目录名里读出的提示）**

_无_

### 3.3 dbu-full-r1（B/full）

- rollout 记录 528 条；工具调用 151 次，其中出错 0 次；推理段 50 段

**工具错误率**

| 工具 | 调用 | 出错 | 错误率 | 累计耗时 | 最常见错误 |
|---|---|---|---|---|---|
| `exec` | 82 | 0 | 0.0 | — | — |
| `refine` | 5 | 0 | 0.0 | 4.5s | — |
| `add_hydrogens` | 5 | 0 | 0.0 | 3.4s | — |
| `run_shelxl` | 5 | 0 | 0.0 | 10.5s | — |
| `read_skill` | 4 | 0 | 0.0 | 1.0s | — |
| `situation_report` | 3 | 0 | 0.0 | 2.1s | — |
| `branch` | 3 | 0 | 0.0 | 1.9s | — |
| `validate_structure` | 3 | 0 | 0.0 | 1.0s | — |
| `get_geometry` | 3 | 0 | 0.0 | 0.6s | — |
| `set_restraints` | 3 | 0 | 0.0 | 2.1s | — |
| `get_project_brief` | 2 | 0 | 0.0 | 3.1s | — |
| `set_experiment` | 2 | 0 | 0.0 | 0.4s | — |
| `ingest_vendor_data` | 2 | 0 | 0.0 | 1.5s | — |
| `audit_reflection_data` | 2 | 0 | 0.0 | 0.4s | — |
| `inspect_model` | 2 | 0 | 0.0 | 0.4s | — |
| `edit_atoms` | 2 | 0 | 0.0 | 0.4s | — |
| `check_symmetry` | 2 | 0 | 0.0 | 0.3s | — |
| `assemble_asu` | 2 | 0 | 0.0 | 0.4s | — |
| `write_outputs` | 2 | 0 | 0.0 | 2.1s | — |
| `run_checkcif` | 2 | 0 | 0.0 | 13.2s | — |
| `model_disorder` | 2 | 0 | 0.0 | 1.1s | — |
| `checkout` | 2 | 0 | 0.0 | 1.4s | — |
| `finalize_delivery` | 2 | 0 | 0.0 | 0.7s | — |
| `screen_space_groups` | 1 | 0 | 0.0 | 0.2s | — |
| `estimate_resolution` | 1 | 0 | 0.0 | 0.4s | — |
| `change_space_group` | 1 | 0 | 0.0 | 0.3s | — |
| `run_shelxt` | 1 | 0 | 0.0 | 6.1s | — |
| `audit_element_assignment` | 1 | 0 | 0.0 | 0.1s | — |
| `inspect_map` | 1 | 0 | 0.0 | 0.3s | — |
| `rename_atoms` | 1 | 0 | 0.0 | 0.3s | — |
| `compare_nodes` | 1 | 0 | 0.0 | 0.2s | — |
| `view_structure` | 1 | 0 | 0.0 | 1.9s | — |

协议性拒绝 1 次（不计入出错：工具按协议先拒、agent 补理由再收）：`finalize_delivery` ×1

**schema 拒绝（MCP 层在工具执行前挡下的调用）**

这类调用工具根本没跑过，因此和工具好不好用无关，只和**参数面好不好
调**有关。

_无_

**原地打转（短窗口内重复同一调用、同一参数）**

轮询已剔除（见下一小节）：detach 任务的状态查询本来就该重复。

- `get_project_brief` 重复 1 次　参数 `{}`
- `run_shelxl` 重复 1 次　参数 `{"l_s": 15, "mode": "adopt", "timeout_s": 180}`

**轮询（detach 任务的状态查询，按工具契约每 60-120 s 一次）**

_无_

**服务端丢下的工具（MCP 传输断开时仍在算）**

_无_

**参数试错（同一工具连续调用、参数每次都变，且其中有出错）**

_无_

连续换参但全部成功（读卡、逐段查看、逐片段验证一类的正常浏览，不计入易用性信号）：
`read_skill` 3 次 3 种

**转向（换打法，并附紧邻其前的工具错误）**

- 触发词 `timeout`，其前无工具报错
  > … absorption, possibly before the final output. First, I’ll tackle the run_shelxl with adopt_wght. I expect about four jobs, each taking around 300, with a call timeout of 120 and five rounds.

**shell 危险用法**

_无_

**数据泄漏审计**

_干净：未读取自己 staging 目录以外的导师侧路径_

**路径线索（agent 从目录名里读出的提示）**

_无_

### 3.4 rz-full-r1（B/full）

- rollout 记录 503 条；工具调用 152 次，其中出错 0 次；推理段 46 段

**工具错误率**

| 工具 | 调用 | 出错 | 错误率 | 累计耗时 | 最常见错误 |
|---|---|---|---|---|---|
| `exec` | 80 | 0 | 0.0 | — | — |
| `run_shelxl` | 10 | 0 | 0.0 | 20.2s | — |
| `view_structure` | 4 | 0 | 0.0 | 5.2s | — |
| `refine` | 4 | 0 | 0.0 | 3.0s | — |
| `validate_structure` | 4 | 0 | 0.0 | 0.9s | — |
| `read_skill` | 3 | 0 | 0.0 | 0.5s | — |
| `run_shelxt` | 3 | 0 | 0.0 | 1.1s | — |
| `situation_report` | 3 | 0 | 0.0 | 3.9s | — |
| `add_hydrogens` | 3 | 0 | 0.0 | 0.9s | — |
| `assemble_asu` | 3 | 0 | 0.0 | 0.2s | — |
| `get_project_brief` | 2 | 0 | 0.0 | 1.1s | — |
| `ingest_vendor_data` | 2 | 0 | 0.0 | 1.5s | — |
| `audit_reflection_data` | 2 | 0 | 0.0 | 0.3s | — |
| `branch` | 2 | 0 | 0.0 | 1.3s | — |
| `inspect_model` | 2 | 0 | 0.0 | 0.5s | — |
| `audit_element_assignment` | 2 | 0 | 0.0 | 0.4s | — |
| `check_symmetry` | 2 | 0 | 0.0 | 0.2s | — |
| `rename_atoms` | 2 | 0 | 0.0 | 0.7s | — |
| `write_outputs` | 2 | 0 | 0.0 | 1.3s | — |
| `run_checkcif` | 2 | 0 | 0.0 | 19.2s | — |
| `compare_nodes` | 2 | 0 | 0.0 | 0.5s | — |
| `finalize_delivery` | 2 | 0 | 0.0 | 0.3s | — |
| `set_experiment` | 1 | 0 | 0.0 | 0.4s | — |
| `screen_space_groups` | 1 | 0 | 0.0 | 0.3s | — |
| `change_space_group` | 1 | 0 | 0.0 | 0.2s | — |
| `reflection_statistics` | 1 | 0 | 0.0 | 0.1s | — |
| `set_twin` | 1 | 0 | 0.0 | — | — |
| `set_weights` | 1 | 0 | 0.0 | 0.5s | — |
| `estimate_resolution` | 1 | 0 | 0.0 | 0.4s | — |
| `set_z` | 1 | 0 | 0.0 | 0.4s | — |
| `wait` | 1 | 0 | 0.0 | — | — |
| `edit_atoms` | 1 | 0 | 0.0 | 0.3s | — |
| `get_geometry` | 1 | 0 | 0.0 | 0.3s | — |

协议性拒绝 1 次（不计入出错：工具按协议先拒、agent 补理由再收）：`finalize_delivery` ×1

**schema 拒绝（MCP 层在工具执行前挡下的调用）**

这类调用工具根本没跑过，因此和工具好不好用无关，只和**参数面好不好
调**有关。

_无_

**原地打转（短窗口内重复同一调用、同一参数）**

轮询已剔除（见下一小节）：detach 任务的状态查询本来就该重复。

- `get_project_brief` 重复 1 次　参数 `{}`
- `situation_report` 重复 1 次　参数 `{"render": true}`
- `run_shelxl` 重复 1 次　参数 `{"l_s": 0, "mode": "check", "timeout_s": 300}`

**轮询（detach 任务的状态查询，按工具契约每 60-120 s 一次）**

- `run_shelxt` 轮询 `job_20260904_042610` 1 次

**服务端丢下的工具（MCP 传输断开时仍在算）**

_无_

**参数试错（同一工具连续调用、参数每次都变，且其中有出错）**

_无_

连续换参但全部成功（读卡、逐段查看、逐片段验证一类的正常浏览，不计入易用性信号）：
`run_shelxt` 3 次 3 种; `run_shelxl` 3 次 3 种

**转向（换打法，并附紧邻其前的工具错误）**

- 触发词 `timeout`，其前无工具报错
  > …it as "C20 H20 N2 O4". Also, there might be no need for "z" to be specified here. I'll set all space groups to true and run the process in detached mode with a timeout, maybe around 900 seconds. I need to call this.
- 触发词 `timeout`，其前无工具报错
  > …suggestions, but right now it just lists things without any state change. Before making big decisions, I need to check for symmetry first. So, I’ll run a small timeout check for symmetry.
- 触发词 `instead of`，其前无工具报错
  > **Clarifying code composition**  I see that there’s a composition deviation because I expected a placeholder instead of evidence from the start. This makes me wonder if I could adjudicate on this issue? I might need to use the `mark_adjudicated` code for composition de…

**shell 危险用法**

_无_

**数据泄漏审计**

_干净：未读取自己 staging 目录以外的导师侧路径_

**路径线索（agent 从目录名里读出的提示）**

_无_

### 3.5 nm-full-r1（B/full）

- rollout 记录 423 条；工具调用 125 次，其中出错 0 次；推理段 31 段

**工具错误率**

| 工具 | 调用 | 出错 | 错误率 | 累计耗时 | 最常见错误 |
|---|---|---|---|---|---|
| `exec` | 68 | 0 | 0.0 | — | — |
| `refine` | 6 | 0 | 0.0 | 8.6s | — |
| `run_shelxl` | 4 | 0 | 0.0 | 4.8s | — |
| `branch` | 3 | 0 | 0.0 | 3.1s | — |
| `situation_report` | 3 | 0 | 0.0 | 1.4s | — |
| `wait` | 3 | 0 | 0.0 | — | — |
| `get_project_brief` | 2 | 0 | 0.0 | 1.7s | — |
| `change_space_group` | 2 | 0 | 0.0 | 0.5s | — |
| `inspect_model` | 2 | 0 | 0.0 | 0.3s | — |
| `add_hydrogens` | 2 | 0 | 0.0 | 0.7s | — |
| `check_symmetry` | 2 | 0 | 0.0 | 0.3s | — |
| `compare_nodes` | 2 | 0 | 0.0 | 0.5s | — |
| `checkout` | 2 | 0 | 0.0 | 0.8s | — |
| `validate_structure` | 2 | 0 | 0.0 | 0.5s | — |
| `view_structure` | 2 | 0 | 0.0 | 2.8s | — |
| `finalize_delivery` | 2 | 0 | 0.0 | 0.4s | — |
| `set_experiment` | 1 | 0 | 0.0 | 0.4s | — |
| `ingest_vendor_data` | 1 | 0 | 0.0 | 1.0s | — |
| `screen_space_groups` | 1 | 0 | 0.0 | 0.2s | — |
| `audit_reflection_data` | 1 | 0 | 0.0 | 0.2s | — |
| `estimate_resolution` | 1 | 0 | 0.0 | 0.2s | — |
| `run_shelxt` | 1 | 0 | 0.0 | 2.8s | — |
| `audit_element_assignment` | 1 | 0 | 0.0 | 0.6s | — |
| `edit_atoms` | 1 | 0 | 0.0 | 0.5s | — |
| `rename_atoms` | 1 | 0 | 0.0 | 0.1s | — |
| `assemble_asu` | 1 | 0 | 0.0 | — | — |
| `inspect_map` | 1 | 0 | 0.0 | 0.8s | — |
| `reflection_statistics` | 1 | 0 | 0.0 | 0.3s | — |
| `model_disorder` | 1 | 0 | 0.0 | 0.2s | — |
| `run_olex2` | 1 | 0 | 0.0 | 92.8s | — |
| `get_geometry` | 1 | 0 | 0.0 | — | — |
| `set_z` | 1 | 0 | 0.0 | 0.2s | — |
| `write_outputs` | 1 | 0 | 0.0 | 0.8s | — |
| `run_checkcif` | 1 | 0 | 0.0 | 6.6s | — |

协议性拒绝 1 次（不计入出错：工具按协议先拒、agent 补理由再收）：`finalize_delivery` ×1

**schema 拒绝（MCP 层在工具执行前挡下的调用）**

这类调用工具根本没跑过，因此和工具好不好用无关，只和**参数面好不好
调**有关。

_无_

**原地打转（短窗口内重复同一调用、同一参数）**

轮询已剔除（见下一小节）：detach 任务的状态查询本来就该重复。

- `get_project_brief` 重复 1 次　参数 `{}`
- `add_hydrogens` 重复 1 次　参数 `{"elements": ["C", "N"]}`
- `run_shelxl` 重复 1 次　参数 `{"l_s": 0, "mode": "check", "timeout_s": 300}`

**轮询（detach 任务的状态查询，按工具契约每 60-120 s 一次）**

_无_

**服务端丢下的工具（MCP 传输断开时仍在算）**

_无_

**参数试错（同一工具连续调用、参数每次都变，且其中有出错）**

_无_

**转向（换打法，并附紧邻其前的工具错误）**

- 触发词 `timeout`，其前无工具报错
  > …s at 2705, so comparing R directly isn't feasible due to Friedel's independence. I need to run a check_symmetry on P1 to find the inversion mapping. I'll set a timeout for that check, maybe around 60 seconds.
- 触发词 `timeout`，其前无工具报错
  > …l remains the same and the publication is true. It looks like I will need to run checkcif on final.cif, which could take a few minutes. I’ll go ahead and set a timeout of 420 for this process.

**shell 危险用法**

_无_

**数据泄漏审计**

_干净：未读取自己 staging 目录以外的导师侧路径_

**路径线索（agent 从目录名里读出的提示）**

_无_

### 3.6 全实验汇总

**错误率最高的工具**（只列有过失败的）

| 工具 | 调用 | 出错 | 错误率 | 出错的格数 |
|---|---|---|---|---|
| `read_skill` | 11 | 1 | 0.091 | 1/3 |
| `view_structure` | 12 | 1 | 0.083 | 1/5 |

**打转 / 试错最多的工具**

| 工具 | 打转重复次数 | 参数试错种数 |
|---|---|---|
| `inspect_model` | 7 | 0 |
| `run_shelxl` | 6 | 0 |
| `get_project_brief` | 5 | 0 |
| `run_checkcif` | 3 | 0 |
| `read_skill` | 0 | 3 |
| `situation_report` | 2 | 0 |
| `validate_structure` | 1 | 0 |
| `add_hydrogens` | 1 | 0 |

**每个工具的累计耗时**

| 工具 | 调用 | 累计耗时 |
|---|---|---|
| `run_olex2` | 2 | 195.7s |
| `run_checkcif` | 10 | 78.6s |
| `run_shelxl` | 34 | 59.6s |
| `run_shelxt` | 11 | 27.0s |
| `refine` | 22 | 22.1s |
| `view_structure` | 12 | 13.4s |
| `get_project_brief` | 10 | 10.6s |
| `situation_report` | 15 | 10.5s |
| `element_scan` | 1 | 10.3s |
| `branch` | 13 | 10.0s |
| `ingest_vendor_data` | 9 | 7.7s |
| `write_outputs` | 7 | 6.5s |
| `add_hydrogens` | 12 | 6.1s |
| `ghost_test` | 2 | 5.9s |
| `validate_structure` | 14 | 3.3s |

## 4. 跑偏倾向与打转点（机械信号，待人工核读）

下面每一条都是程序能算出来的**信号**，不是结论。信号只回答「该去
transcript 的哪一段看」；看到的究竟是不是跑偏，必须人读。

- **hsl-full-r1**
  - [原地打转] `inspect_model` 同参数重复 3 次（阈值 3）
  - [原地打转] `run_checkcif` 同参数重复 3 次（阈值 3）
- **cuox-full-r1**
  - [原地打转] `inspect_model` 同参数重复 4 次（阈值 3）

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
| `inspect_model` | 7 | 0 | 0 | 0 | 7 | 18 | 0 | 0.0 |
| `run_shelxl` | 6 | 0 | 0 | 0 | 6 | 34 | 0 | 0.0 |
| `get_project_brief` | 5 | 0 | 0 | 0 | 5 | 10 | 0 | 0.0 |
| `read_skill` | 4 | 1 | 0 | 3 | 0 | 11 | 0 | 0.091 |
| `run_checkcif` | 3 | 0 | 0 | 0 | 3 | 10 | 0 | 0.0 |
| `situation_report` | 2 | 0 | 0 | 0 | 2 | 15 | 0 | 0.0 |
| `view_structure` | 1 | 1 | 0 | 0 | 0 | 12 | 0 | 0.083 |
| `validate_structure` | 1 | 0 | 0 | 0 | 1 | 14 | 0 | 0.0 |
| `add_hydrogens` | 1 | 0 | 0 | 0 | 1 | 12 | 0 | 0.0 |

## 附：运行记账

`root_agents_sha256` 对一条干净的臂必须是 null，`agents_chain` 长度必须
是 1（只有项目自己那份 AGENTS.md）。

| 格 | model | effort | knowledge_mode | agents_version | agents_sha256 | 匹配模板 | root_agents_sha256 | 链长 |
|---|---|---|---|---|---|---|---|---|
| hsl-full-r1 | gpt-5.6-sol | xhigh | full | <!-- crystalpilot-agents-v34 --> | `c92b3945` | 是 | null（干净） | 1 |
| cuox-full-r1 | gpt-5.6-sol | xhigh | full | <!-- crystalpilot-agents-v34 --> | `c92b3945` | 是 | null（干净） | 1 |
| dbu-full-r1 | gpt-5.6-sol | xhigh | full | <!-- crystalpilot-agents-v34 --> | `c92b3945` | 是 | null（干净） | 1 |
| rz-full-r1 | gpt-5.6-sol | xhigh | full | <!-- crystalpilot-agents-v34 --> | `c92b3945` | 是 | null（干净） | 1 |
| nm-full-r1 | gpt-5.6-sol | xhigh | full | <!-- crystalpilot-agents-v34 --> | `c92b3945` | 是 | null（干净） | 1 |

- 未发现祖先 AGENTS.md 注入、模板哈希不符或臂标签矛盾（未跑的格子无从检查）。
